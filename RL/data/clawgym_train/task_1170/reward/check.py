import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return None

def parse_jsonl_lines(path):
    results = []
    lines = read_lines(path)
    if lines is None:
        return None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            results.append(json.loads(s))
        except Exception:
            results.append(None)
    return results

def count_vocab_items(lines):
    # Count lines matching triple separator with spaces around em dash or hyphen
    # Pattern: "[any] — [any] — [any]" or "[any] - [any] - [any]"
    if lines is None:
        return 0
    count = 0
    triple_re = re.compile(r'^.+(?:\s—\s|\s-\s).+(?:\s—\s|\s-\s).+$')
    for line in lines:
        if triple_re.match(line.strip()):
            count += 1
    return count

def extract_vocab_headwords(lines):
    # Extract headword as text before first ' — ' or ' - '
    headwords = set()
    if lines is None:
        return headwords
    for raw in lines:
        line = raw.rstrip("\n")
        idx_em = line.find(" — ")
        idx_hy = line.find(" - ")
        idxs = [i for i in [idx_em, idx_hy] if i != -1]
        if not idxs:
            continue
        idx = min(idxs)
        head = line[:idx].strip()
        if head:
            headwords.add(head)
    return headwords

def contains_japanese(text):
    return bool(re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', text or ""))

def line_startswith_any(line, prefixes):
    s = line.lstrip()  # allow leading spaces
    return any(s.startswith(p) for p in prefixes)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    lesson_plan_path = os.path.join(output_dir, "lesson_plan.md")
    flashcards_path = os.path.join(output_dir, "flashcards.jsonl")
    conversation_path = os.path.join(output_dir, "conversation.md")
    cultural_tips_path = os.path.join(output_dir, "cultural_tips.md")

    vocab_topics_path = os.path.join(input_dir, "vocab_topics.txt")
    priority_phrases_path = os.path.join(input_dir, "priority_phrases.jsonl")

    checks = {
        "has_lesson_plan": False,
        "lesson_sections": False,
        "lesson_has_japanese": False,
        "lesson_vocab_items_count_ge_6": False,
        "lesson_examples_translations_memoryhooks_ge_6": False,
        "lesson_quiz_labels": False,
        "lesson_contains_input_topic": False,

        "has_flashcards": False,
        "flashcards_min_lines": False,
        "flashcards_all_json_and_keys": False,
        "flashcards_at_least_3_types": False,
        "flashcards_fronts_match_vocab_headwords_ge_2": False,

        "has_conversation": False,
        "conversation_scene_valid": False,
        "conversation_min_turns": False,
        "conversation_min_japanese_lines": False,
        "conversation_all_turns_have_romaji_and_english": False,
        "conversation_has_recap_subsections": False,

        "has_cultural_tips": False,
        "cultural_tips_min_bullets": False,
        "cultural_tips_contains_keywords": False,

        "priority_phrases_covered_ge_3": False
    }

    # 1) Lesson plan checks
    lesson_text = read_text_file(lesson_plan_path)
    lesson_lines = read_lines(lesson_plan_path)
    if lesson_text is not None and lesson_lines is not None:
        checks["has_lesson_plan"] = True

        # Sections labeled exactly: Warm-up, New content, Practice, Cool-down, Homework (case-sensitive)
        required_sections = ["Warm-up", "New content", "Practice", "Cool-down", "Homework"]
        if all(sec in lesson_text for sec in required_sections):
            checks["lesson_sections"] = True

        # Presence of Japanese characters
        if contains_japanese(lesson_text):
            checks["lesson_has_japanese"] = True

        # Vocabulary builder count
        vocab_count = count_vocab_items(lesson_lines)
        if vocab_count >= 6:
            checks["lesson_vocab_items_count_ge_6"] = True

        # Ensure at least 6 occurrences of each label
        example_count = lesson_text.count("Example sentence:")
        translation_count = lesson_text.count("Translation:")
        memoryhook_count = lesson_text.count("Memory hook:")
        if example_count >= 6 and translation_count >= 6 and memoryhook_count >= 6:
            checks["lesson_examples_translations_memoryhooks_ge_6"] = True

        # Quiz section labels
        if ("Target → English" in lesson_text and
            "English → Target" in lesson_text and
            "Fill in the blank" in lesson_text):
            checks["lesson_quiz_labels"] = True

        # Contains at least one topic from input/vocab_topics.txt
        topics_text = read_text_file(vocab_topics_path)
        if topics_text:
            topics = [t.strip() for t in topics_text.splitlines() if t.strip()]
            if any(t in lesson_text for t in topics):
                checks["lesson_contains_input_topic"] = True

    # Prepare vocab headwords for cross-check with flashcards
    lesson_headwords = extract_vocab_headwords(lesson_lines) if lesson_lines else set()

    # 2) Flashcards checks
    flashcards_lines = read_lines(flashcards_path)
    if flashcards_lines is not None:
        checks["has_flashcards"] = True
        non_empty_lines = [ln for ln in flashcards_lines if ln.strip()]
        if len(non_empty_lines) >= 12:
            checks["flashcards_min_lines"] = True

        parsed = parse_jsonl_lines(flashcards_path)
        all_json_and_keys = True
        allowed_types = {"word_to_translation", "translation_to_word", "sentence_completion", "phrase"}
        types_seen = set()
        fronts = []
        if parsed is not None and len(parsed) == len(non_empty_lines):
            for obj in parsed:
                if not isinstance(obj, dict):
                    all_json_and_keys = False
                    break
                # Validate keys exist
                if not all(k in obj for k in ("type", "front", "back", "transliteration")):
                    all_json_and_keys = False
                    break
                # Validate type value
                tval = obj.get("type")
                if tval not in allowed_types:
                    all_json_and_keys = False
                    break
                types_seen.add(tval)
                fronts.append(str(obj.get("front", "")))
        else:
            all_json_and_keys = False

        if all_json_and_keys:
            checks["flashcards_all_json_and_keys"] = True

        if len(types_seen) >= 3:
            checks["flashcards_at_least_3_types"] = True

        # Fronts match at least two headwords from lesson vocab entries
        match_count = 0
        hw_lower = {h.lower() for h in lesson_headwords}
        for fr in fronts:
            if fr.strip().lower() in hw_lower:
                match_count += 1
        if match_count >= 2:
            checks["flashcards_fronts_match_vocab_headwords_ge_2"] = True

    # 3) Conversation checks
    convo_lines = read_lines(conversation_path)
    convo_text = read_text_file(conversation_path)
    if convo_lines is not None and convo_text is not None:
        checks["has_conversation"] = True

        # Scene line: first non-empty line starting with 'Scene:'
        first_non_empty = None
        for ln in convo_lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        if first_non_empty and first_non_empty.startswith("Scene:"):
            lower_scene = first_non_empty.lower()
            if ("tokyo" in lower_scene) and ("restaurant" in lower_scene or "ordering" in lower_scene):
                checks["conversation_scene_valid"] = True

        # Dialogue lines starting with 'You:' or 'Server:'
        dialogue_lines = [ln.rstrip("\n") for ln in convo_lines if line_startswith_any(ln, ["You:", "Server:"])]
        if len(dialogue_lines) >= 8:
            checks["conversation_min_turns"] = True

        # At least 5 dialogue lines contain Japanese characters
        jap_count = sum(1 for ln in dialogue_lines if contains_japanese(ln))
        if jap_count >= 5:
            checks["conversation_min_japanese_lines"] = True

        # Each dialogue line contains parentheses (romaji) and ' - ' for English translation
        format_ok = True
        for ln in dialogue_lines:
            has_paren = "(" in ln and ")" in ln
            has_dash_translation = " - " in ln
            has_japanese = contains_japanese(ln)
            if not (has_paren and has_dash_translation and has_japanese):
                format_ok = False
                break
        if format_ok and len(dialogue_lines) >= 1:
            checks["conversation_all_turns_have_romaji_and_english"] = True

        # Recap section with subheadings
        if ("Recap" in convo_text and
            "Corrections" in convo_text and
            "New vocabulary" in convo_text and
            "Cultural notes" in convo_text):
            checks["conversation_has_recap_subsections"] = True

    # 4) Cultural tips checks
    tips_lines = read_lines(cultural_tips_path)
    tips_text = read_text_file(cultural_tips_path)
    if tips_lines is not None and tips_text is not None:
        checks["has_cultural_tips"] = True
        bullet_count = 0
        for ln in tips_lines:
            s = ln.lstrip()
            if s.startswith("-") or s.startswith("*"):
                bullet_count += 1
        if bullet_count >= 3:
            checks["cultural_tips_min_bullets"] = True

        lower_tips = tips_text.lower()
        if (("polite" in lower_tips) or ("politeness" in lower_tips)) and ("etiquette" in lower_tips):
            checks["cultural_tips_contains_keywords"] = True

    # 5) Cross-file checks with inputs: priority phrases
    priority_objs = parse_jsonl_lines(priority_phrases_path)
    lesson_and_convo_text = ((lesson_text or "") + "\n" + (convo_text or "")).lower()
    if priority_objs is not None and lesson_and_convo_text:
        phrases = []
        for obj in priority_objs:
            if isinstance(obj, dict):
                val = obj.get("english_phrase")
                if isinstance(val, str) and val.strip():
                    phrases.append(val.strip())
        matched_unique = set()
        for p in phrases:
            if p.lower() in lesson_and_convo_text:
                matched_unique.add(p.lower())
        if len(matched_unique) >= 3:
            checks["priority_phrases_covered_ge_3"] = True

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure reward is 0.0 if no outputs (no-op baseline)
    outputs_exist = any(os.path.isfile(p) for p in [lesson_plan_path, flashcards_path, conversation_path, cultural_tips_path])
    if not outputs_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()