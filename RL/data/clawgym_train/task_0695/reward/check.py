import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_headers_indices(lines, headers):
    indices = {}
    order = []
    for i, line in enumerate(lines):
        if line.strip() in headers:
            hdr = line.strip()
            if hdr not in indices:
                indices[hdr] = i
                order.append(hdr)
    # Ensure exact presence and order
    if len(indices) != len(headers):
        return None, False
    correct_order = [h for h in headers]
    is_ordered = order == correct_order
    return indices, is_ordered

def section_lines(lines, start_idx, end_idx):
    return lines[start_idx+1:end_idx]

TONE_MARKS = "āáǎàēéěèiíǐìōóǒòūúǔùǖǘǚǜ"

def has_tone_mark(s):
    return any(ch in s for ch in TONE_MARKS)

def normalize_en(s):
    s = s.strip().lower()
    # Replace punctuation with space
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def split_meaning_tokens(s):
    # Split on common separators for multi-meaning strings
    parts = re.split(r"[/;,]|(?:\s+\bor\b\s+)|(?:\s+\band\b\s+)", s, flags=re.IGNORECASE)
    return [normalize_en(p) for p in parts if normalize_en(p)]

def detect_number_line(line):
    m = re.match(r"^\s*(\d+)[\.\)]\s*$", line.strip())
    return int(m.group(1)) if m else None

def detect_question_number_line(line):
    m = re.match(r"^\s*(\d+)[\.\)]\s+", line.strip())
    return int(m.group(1)) if m else None

def extract_label_value(line, label):
    prefix = label
    if line.strip().startswith(prefix):
        return line.strip()[len(prefix):].strip()
    return None

def count_bullets(lines):
    return [ln for ln in lines if re.match(r"^\s*[-*]\s+", ln.strip())]

def parse_preferences(pref_obj):
    level = None
    topic = None
    # level
    for k in ["hsk_level", "level", "hskLevel"]:
        if k in pref_obj:
            level = pref_obj[k]
            break
    # cast to int if possible
    try:
        if isinstance(level, str):
            level = int(re.sub(r"[^\d]", "", level))
        elif isinstance(level, (float,)):
            level = int(level)
    except Exception:
        pass
    # topic
    for k in ["topic", "primary_topic", "topic_focus", "topicFocus"]:
        if k in pref_obj:
            topic = pref_obj[k]
            break
    if isinstance(topic, list) and topic:
        topic = topic[0]
    if isinstance(topic, dict):
        # try a 'name' field
        topic = topic.get("name") or topic.get("primary") or None
    if isinstance(topic, str):
        topic = topic.strip()
    return level, topic

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    session_path = os.path.join(output_dir, "mandarin_drill_session.md")
    meta_path = os.path.join(output_dir, "mandarin_drill_meta.json")
    prefs_path = os.path.join(input_dir, "preferences.json")
    avoid_path = os.path.join(input_dir, "avoid_list.json")

    checks = {
        "session_file_exists": False,
        "meta_file_exists": False,
        "headers_ok": False,
        "vocab_count_10": False,
        "vocab_items_structure": False,
        "vocab_pinyin_tone_marks_all": False,
        "vocab_tone_number_notation_all": False,
        "vocab_no_banned_meanings": False,
        "grammar_labels_ok": False,
        "grammar_examples_3": False,
        "grammar_pattern_not_banned": False,
        "characters_count_3": False,
        "characters_items_structure": False,
        "tone_drill_5_pairs": False,
        "reading_5to8_sentences_with_pinyin": False,
        "reading_english_translation_present": False,
        "reading_highlighted_points_3": False,
        "reading_has_tone_marks_in_pinyin": False,
        "speaking_scenario_present": False,
        "speaking_dialogue_4_turns": False,
        "speaking_prompts_3": False,
        "speaking_vocab_6": False,
        "quiz_5_questions": False,
        "quiz_answers_present": False,
        "cultural_note_present": False,
        "meta_fields_valid": False,
        "meta_counts_match": False,
        "meta_level_and_topic_match": False,
        "meta_no_banned_true_and_consistent": False
    }

    session_text = read_text(session_path)
    meta_obj = load_json(meta_path)
    prefs_obj = load_json(prefs_path) or {}
    avoid_obj = load_json(avoid_path) or {}
    banned_vocab = avoid_obj.get("vocabulary_en", []) or []
    banned_patterns = avoid_obj.get("grammar_patterns_en", []) or []
    banned_vocab_norm = set(normalize_en(x) for x in banned_vocab if isinstance(x, str))
    banned_patterns_norm = set(normalize_en(x) for x in banned_patterns if isinstance(x, str))

    if session_text is not None:
        checks["session_file_exists"] = True
    if meta_obj is not None:
        checks["meta_file_exists"] = True

    # Only proceed with structural checks if session exists
    observed_counts = {
        "vocab_items": 0,
        "characters_items": 0,
        "tone_pairs": 0,
        "quiz_questions": 0
    }

    headers = [
        "1) Vocabulary",
        "2) Grammar pattern",
        "3) Character focus",
        "4) Tone drill",
        "5) Reading passage",
        "6) Speaking prompt",
        "7) Quick quiz",
        "Cultural note"
    ]

    if session_text:
        lines = session_text.splitlines()
        hdr_indices, ordered = find_headers_indices(lines, headers)
        if hdr_indices is not None and ordered:
            checks["headers_ok"] = True

            # Extract sections
            idx = hdr_indices
            # Section end indices
            def end_of(h):
                i = headers.index(h)
                if i == len(headers) - 1:
                    return len(lines)
                nh = headers[i + 1]
                return idx[nh]
            vocab_lines = section_lines(lines, idx["1) Vocabulary"], end_of("1) Vocabulary"))
            grammar_lines = section_lines(lines, idx["2) Grammar pattern"], end_of("2) Grammar pattern"))
            char_lines = section_lines(lines, idx["3) Character focus"], end_of("3) Character focus"))
            tone_lines = section_lines(lines, idx["4) Tone drill"], end_of("4) Tone drill"))
            reading_lines = section_lines(lines, idx["5) Reading passage"], end_of("5) Reading passage"))
            speaking_lines = section_lines(lines, idx["6) Speaking prompt"], end_of("6) Speaking prompt"))
            quiz_lines = section_lines(lines, idx["7) Quick quiz"], end_of("7) Quick quiz"))
            cultural_lines = section_lines(lines, idx["Cultural note"], end_of("Cultural note"))

            # Vocabulary parsing
            vocab_required_labels = ["- Characters:", "- Pinyin:", "- Tone:", "- Meaning:", "- Example:", "- Memory tip:"]
            i = 0
            vocab_items = []
            vocab_pinyin_ok = True
            vocab_tone_notation_ok = True
            no_banned_meanings = True
            numbers_seen = []
            while i < len(vocab_lines):
                num = detect_number_line(vocab_lines[i])
                if num is not None:
                    numbers_seen.append(num)
                    item = {"number": num, "lines": []}
                    i += 1
                    for lab in vocab_required_labels:
                        # Skip blank lines between parts
                        while i < len(vocab_lines) and vocab_lines[i].strip() == "":
                            i += 1
                        if i >= len(vocab_lines):
                            item = None
                            break
                        if not vocab_lines[i].strip().startswith(lab):
                            item = None
                            break
                        val = extract_label_value(vocab_lines[i], lab)
                        item["lines"].append((lab, val if val is not None else ""))
                        i += 1
                    if item is not None and len(item["lines"]) == 6:
                        # Check Pinyin tone marks
                        pinyin_val = item["lines"][1][1] if len(item["lines"]) > 1 else ""
                        if not has_tone_mark(pinyin_val or ""):
                            vocab_pinyin_ok = False
                        # Check Tone notation
                        tone_val = item["lines"][2][1] if len(item["lines"]) > 2 else ""
                        if not any(tok in (tone_val or "").lower() for tok in ["1st", "2nd", "3rd", "4th", "neutral"]):
                            vocab_tone_notation_ok = False
                        # Check banned meanings
                        meaning_val = item["lines"][3][1] if len(item["lines"]) > 3 else ""
                        norm_mean_full = normalize_en(meaning_val)
                        tokens = split_meaning_tokens(meaning_val)
                        # Compare full equality and tokens equality
                        if norm_mean_full in banned_vocab_norm or any(t in banned_vocab_norm for t in tokens):
                            no_banned_meanings = False
                        vocab_items.append(item)
                    else:
                        # Structure broken
                        pass
                else:
                    i += 1
            # Validate count and numbering
            if len(vocab_items) == 10 and numbers_seen == list(range(1, 11)):
                checks["vocab_count_10"] = True
                checks["vocab_items_structure"] = True
            else:
                # Structure: also ensure labels ordering per item was validated above
                if len(vocab_items) == 10:
                    checks["vocab_count_10"] = True
                if len(vocab_items) > 0:
                    # Only set true if all items had correct labels
                    all_struct = True
                    for it in vocab_items:
                        labs = [lab for (lab, _) in it["lines"]]
                        if labs != vocab_required_labels:
                            all_struct = False
                            break
                    if all_struct:
                        checks["vocab_items_structure"] = True
            observed_counts["vocab_items"] = len(vocab_items)
            if len(vocab_items) == 10 and vocab_pinyin_ok:
                checks["vocab_pinyin_tone_marks_all"] = True
            if len(vocab_items) == 10 and vocab_tone_notation_ok:
                checks["vocab_tone_number_notation_all"] = True
            if len(vocab_items) == 10 and no_banned_meanings:
                checks["vocab_no_banned_meanings"] = True

            # Grammar pattern parsing
            def find_label_index(section, label):
                for idx0, ln in enumerate(section):
                    if ln.strip().startswith(label):
                        return idx0
                return None

            g_labels = [
                "Pattern name (English):",
                "Structure:",
                "Explanation:",
                "Examples:",
                "Common mistakes:",
                "Comparison:"
            ]
            g_idx = [find_label_index(grammar_lines, lab) for lab in g_labels]
            if all(x is not None for x in g_idx) and g_idx == sorted(g_idx):
                checks["grammar_labels_ok"] = True
                # Examples count
                ex_start = g_idx[3]
                cm_start = g_idx[4]
                example_block = grammar_lines[ex_start+1:cm_start]
                # Count example-like lines
                example_like = []
                for ln in example_block:
                    if ln.strip() == "":
                        continue
                    if re.match(r"^\s*(?:[-*]|\d+[\.\)])\s+", ln) or True:
                        # Accept any non-empty line as potential example, will refine by tone mark
                        example_like.append(ln)
                # Count lines with tone marks as a proxy for pinyin present
                tone_lines = [ln for ln in example_like if has_tone_mark(ln)]
                if len(example_like) >= 3 and len(tone_lines) >= 3:
                    checks["grammar_examples_3"] = True
                # Pattern name not banned
                patt_line = grammar_lines[g_idx[0]].strip()
                patt_val = extract_label_value(patt_line, "Pattern name (English):") or ""
                if normalize_en(patt_val) not in banned_patterns_norm:
                    checks["grammar_pattern_not_banned"] = True

            # Character focus parsing
            char_required_labels = ["Character:", "Pinyin:", "Radical:", "Strokes:", "Compounds:", "Memory tip:"]
            i = 0
            char_items = []
            char_numbers_seen = []
            while i < len(char_lines):
                num = detect_number_line(char_lines[i])
                if num is not None:
                    char_numbers_seen.append(num)
                    item = {"number": num, "lines": []}
                    i += 1
                    for lab in char_required_labels:
                        while i < len(char_lines) and char_lines[i].strip() == "":
                            i += 1
                        if i >= len(char_lines):
                            item = None
                            break
                        if not char_lines[i].strip().startswith(lab):
                            item = None
                            break
                        val = extract_label_value(char_lines[i], lab)
                        item["lines"].append((lab, val if val is not None else ""))
                        i += 1
                    if item is not None and len(item["lines"]) == 6:
                        char_items.append(item)
                else:
                    i += 1
            observed_counts["characters_items"] = len(char_items)
            if len(char_items) == 3 and char_numbers_seen == [1, 2, 3]:
                checks["characters_count_3"] = True
                # Structure correctness
                allc = all([ [lab for (lab, _) in it["lines"]] == char_required_labels for it in char_items ])
                if allc:
                    checks["characters_items_structure"] = True

            # Tone drill parsing
            tone_pairs = 0
            tone_numbers_seen = []
            for ln in tone_lines:
                m = detect_question_number_line(ln)
                if m is not None:
                    # Ensure 'vs' and tone marks
                    if re.search(r"\bvs\b", ln, flags=re.IGNORECASE) and len([ch for ch in ln if ch in TONE_MARKS]) >= 2:
                        tone_pairs += 1
                        tone_numbers_seen.append(m)
            if tone_pairs == 5 and tone_numbers_seen == [1,2,3,4,5]:
                checks["tone_drill_5_pairs"] = True
            observed_counts["tone_pairs"] = tone_pairs

            # Reading passage parsing
            # Find "English translation:" and "Highlighted points:"
            r_english_idx = None
            r_highlight_idx = None
            for idx0, ln in enumerate(reading_lines):
                if ln.strip().startswith("English translation:"):
                    r_english_idx = idx0
                if ln.strip().startswith("Highlighted points:"):
                    r_highlight_idx = idx0
            # Sentence blocks
            sent_pairs = 0
            has_tone_in_pinyin = False
            if r_english_idx is not None:
                i = 0
                while i < r_english_idx:
                    ln = reading_lines[i].strip()
                    if ln != "" and not ln.startswith("Pinyin:"):
                        # Expect next line starts with Pinyin:
                        if i+1 < r_english_idx and reading_lines[i+1].strip().startswith("Pinyin:"):
                            sent_pairs += 1
                            if has_tone_mark(reading_lines[i+1]):
                                has_tone_in_pinyin = True
                            i += 2
                        else:
                            i += 1
                    else:
                        i += 1
                if 5 <= sent_pairs <= 8:
                    checks["reading_5to8_sentences_with_pinyin"] = True
                # English translation present and non-empty content
                eng_block = reading_lines[r_english_idx:]
                if any(ln.strip() for ln in eng_block if not ln.strip().startswith("English translation:")):
                    checks["reading_english_translation_present"] = True
            if r_highlight_idx is not None:
                # Count bullet items after this line
                hl_block = reading_lines[r_highlight_idx+1:]
                bullets = [ln for ln in hl_block if re.match(r"^\s*[-*]\s+", ln.strip())]
                # Stop at next section header if mistakenly included
                # But given section boundaries, this block ends before speaking section
                if len(bullets) == 3:
                    checks["reading_highlighted_points_3"] = True
            if has_tone_in_pinyin:
                checks["reading_has_tone_marks_in_pinyin"] = True

            # Speaking prompt parsing
            sp_idx_scn = find_label_index(speaking_lines, "Scenario:")
            sp_idx_dlg = find_label_index(speaking_lines, "Sample dialogue:")
            sp_idx_pr = find_label_index(speaking_lines, "Practice prompts:")
            sp_idx_vocab = find_label_index(speaking_lines, "Suggested vocabulary:")
            if sp_idx_scn is not None:
                # Ensure scenario has some content
                if any(ln.strip() for ln in speaking_lines[sp_idx_scn+1:sp_idx_scn+3]):
                    checks["speaking_scenario_present"] = True
            if sp_idx_dlg is not None and sp_idx_pr is not None and sp_idx_dlg < sp_idx_pr:
                dlg_block = speaking_lines[sp_idx_dlg+1:sp_idx_pr]
                # Count lines that look like turns (label followed by colon)
                turns = [ln for ln in dlg_block if re.match(r"^\s*[-*]?\s*[^:]{1,40}:\s*", ln.strip())]
                if len(turns) >= 4:
                    checks["speaking_dialogue_4_turns"] = True
            if sp_idx_pr is not None and sp_idx_vocab is not None and sp_idx_pr < sp_idx_vocab:
                pr_block = speaking_lines[sp_idx_pr+1:sp_idx_vocab]
                pr_items = [ln for ln in pr_block if re.match(r"^\s*(?:[-*]|\d+[\.\)])\s+", ln.strip())]
                if len(pr_items) >= 3:
                    checks["speaking_prompts_3"] = True
            if sp_idx_vocab is not None:
                vocab_block = speaking_lines[sp_idx_vocab+1:]
                # Items until next section, count lines with tone-mark characters
                vocab_items_lines = [ln for ln in vocab_block if ln.strip() and not any(ln.strip().startswith(h) for h in headers)]
                tone_items = [ln for ln in vocab_items_lines if has_tone_mark(ln)]
                if len(tone_items) >= 6:
                    checks["speaking_vocab_6"] = True

            # Quiz parsing
            # Before divider
            divider_idx = None
            ans_idx = None
            for idx0, ln in enumerate(quiz_lines):
                if ln.strip() == "----" and divider_idx is None:
                    divider_idx = idx0
                if ln.strip().startswith("Answers:") and ans_idx is None:
                    ans_idx = idx0
            q_numbers = []
            if divider_idx is not None:
                before = quiz_lines[:divider_idx]
                for ln in before:
                    qn = detect_question_number_line(ln)
                    if qn is not None:
                        q_numbers.append(qn)
                if q_numbers == [1,2,3,4,5]:
                    checks["quiz_5_questions"] = True
                observed_counts["quiz_questions"] = len([n for n in q_numbers if 1 <= n <= 5])
            # Answers block
            if ans_idx is not None:
                after = quiz_lines[ans_idx+1:]
                ans_nums = []
                for ln in after:
                    m = re.match(r"^\s*(\d+)[\.\)]\s*", ln.strip())
                    if m:
                        try:
                            ans_nums.append(int(m.group(1)))
                        except Exception:
                            pass
                if sorted(ans_nums[:5]) == [1,2,3,4,5]:
                    checks["quiz_answers_present"] = True

            # Cultural note
            if cultural_lines is not None:
                content = "\n".join(cultural_lines).strip()
                if content:
                    # Count sentences via ., !, ?
                    sentences = [s for s in re.split(r"[.!?]\s*", content) if s.strip()]
                    if len(sentences) >= 2:
                        checks["cultural_note_present"] = True

    # Meta validations
    prefs_level, prefs_topic = parse_preferences(prefs_obj if isinstance(prefs_obj, dict) else {})
    meta_fields_valid = False
    meta_counts_match = False
    meta_level_and_topic_match = False
    meta_no_banned = False
    if meta_obj and isinstance(meta_obj, dict):
        # Required keys
        required_keys = ["hsk_level", "topic", "vocab_count", "characters_count", "minimal_pairs_count", "quiz_count", "no_banned_content"]
        if all(k in meta_obj for k in required_keys):
            # Check fixed counts
            if (meta_obj.get("vocab_count") == 10 and
                meta_obj.get("characters_count") == 3 and
                meta_obj.get("minimal_pairs_count") == 5 and
                meta_obj.get("quiz_count") == 5 and
                isinstance(meta_obj.get("no_banned_content"), bool)):
                meta_fields_valid = True
            # Cross-check observed counts when session was parsed
            if observed_counts["vocab_items"] == 10 and observed_counts["tone_pairs"] == 5 and observed_counts["quiz_questions"] == 5 and observed_counts["characters_items"] == 3:
                if (meta_obj.get("vocab_count") == observed_counts["vocab_items"] and
                    meta_obj.get("minimal_pairs_count") == observed_counts["tone_pairs"] and
                    meta_obj.get("quiz_count") == observed_counts["quiz_questions"] and
                    meta_obj.get("characters_count") == observed_counts["characters_items"]):
                    meta_counts_match = True
            # Level and topic match
            meta_level = meta_obj.get("hsk_level")
            meta_topic = meta_obj.get("topic")
            level_match = (prefs_level is None) or (str(meta_level).strip() == str(prefs_level).strip())
            topic_match = True
            if isinstance(meta_topic, str) and isinstance(prefs_topic, str):
                topic_match = normalize_en(meta_topic) == normalize_en(prefs_topic)
            elif prefs_topic is not None and isinstance(meta_topic, str):
                # If preferences topic missing or not string, accept if meta topic non-empty
                topic_match = False
            if level_match and topic_match:
                meta_level_and_topic_match = True
            # no_banned_content must be true and consistent with checks
            if meta_obj.get("no_banned_content") is True:
                meta_no_banned = True

    checks["meta_fields_valid"] = meta_fields_valid
    checks["meta_counts_match"] = meta_counts_match
    checks["meta_level_and_topic_match"] = meta_level_and_topic_match
    # This check depends on detecting no banned vocab and non-banned grammar and meta flag set True
    if checks["vocab_no_banned_meanings"] and checks["grammar_pattern_not_banned"] and meta_no_banned:
        checks["meta_no_banned_true_and_consistent"] = True

    # If either required output file is missing, enforce reward 0.0
    all_required_exist = checks["session_file_exists"] and checks["meta_file_exists"]

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if all_required_exist else 0.0

    # Print final JSON on last line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()