import json
import os
import sys
import csv
import re

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def count_lines_starting_with(lines, prefix):
    return sum(1 for line in lines if line.startswith(prefix))

def is_non_ascii_present(s):
    return any(ord(ch) > 127 for ch in s)

def safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None

def split_scenarios(dialogues_text):
    lines = dialogues_text.splitlines()
    scenario_indices = [i for i, line in enumerate(lines) if line.startswith("## Scenario:")]
    scenarios = []
    for idx, start in enumerate(scenario_indices):
        end = scenario_indices[idx + 1] if idx + 1 < len(scenario_indices) else len(lines)
        scenarios.append(lines[start:end])
    return scenarios

def extract_day_blocks(plan_text):
    lines = plan_text.splitlines()
    day_indices = []
    for i, line in enumerate(lines):
        if re.fullmatch(r"## Day [1-7]", line.strip()):
            day_indices.append(i)
    blocks = []
    for idx, start in enumerate(day_indices):
        end = day_indices[idx + 1] if idx + 1 < len(day_indices) else len(lines)
        block = "\n".join(lines[start:end])
        blocks.append(block)
    return blocks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) output/plan.md checks
    plan_path = os.path.join(output_dir, "plan.md")
    plan_exists = os.path.isfile(plan_path)
    checks["plan_exists"] = False
    checks["plan_has_header_fields"] = False
    checks["plan_has_days_sections"] = False
    checks["plan_days_have_subsections"] = False

    if plan_exists:
        checks["plan_exists"] = True
        plan_text = read_text_file(plan_path)
        if all(s in plan_text for s in ["Learner:", "Target Language: Japanese", "Goal:"]):
            checks["plan_has_header_fields"] = True
        # Verify day sections exactly Day 1..Day 7
        lines = plan_text.splitlines()
        day_labels = set([line.strip() for line in lines if re.fullmatch(r"## Day [1-7]", line.strip())])
        expected_day_labels = {f"## Day {i}" for i in range(1, 8)}
        if day_labels == expected_day_labels:
            checks["plan_has_days_sections"] = True
            # For each day block, ensure subsections exist
            blocks = extract_day_blocks(plan_text)
            needed_subsections = ["Warm-up", "New content", "Practice", "Cool-down", "Homework"]
            all_blocks_ok = True
            for block in blocks:
                if not all(sub in block for sub in needed_subsections):
                    all_blocks_ok = False
                    break
            if all_blocks_ok and len(blocks) == 7:
                checks["plan_days_have_subsections"] = True

    # 2) output/vocabulary.csv checks
    vocab_path = os.path.join(output_dir, "vocabulary.csv")
    checks["vocab_exists"] = False
    checks["vocab_header_correct"] = False
    checks["vocab_rows_count_ge_35"] = False
    checks["vocab_rows_nonempty_fields"] = False
    checks["vocab_target_word_non_ascii_coverage_ge_80pct"] = False

    if os.path.isfile(vocab_path):
        checks["vocab_exists"] = True
        rows = read_csv_rows(vocab_path)
        if rows and len(rows) >= 1:
            header = rows[0]
            expected_header = [
                "target_word",
                "transliteration",
                "english",
                "example_sentence_target",
                "example_sentence_english",
                "memory_hook",
            ]
            if header == expected_header:
                checks["vocab_header_correct"] = True
                data_rows = rows[1:]
                if len(data_rows) >= 35:
                    checks["vocab_rows_count_ge_35"] = True
                    nonempty_ok = True
                    non_ascii_count = 0
                    for r in data_rows:
                        # Ensure row length at least equals header length
                        if len(r) < len(expected_header):
                            nonempty_ok = False
                            break
                        target_word = r[0].strip()
                        translit = r[1].strip()
                        ex_target = r[3].strip()
                        ex_english = r[4].strip()
                        memo = r[5].strip()
                        if not translit or not ex_target or not ex_english or not memo:
                            nonempty_ok = False
                            break
                        if target_word and is_non_ascii_present(target_word):
                            non_ascii_count += 1
                    if nonempty_ok:
                        checks["vocab_rows_nonempty_fields"] = True
                    total = len(data_rows)
                    if total > 0:
                        ratio = non_ascii_count / total
                        if ratio >= 0.8:
                            checks["vocab_target_word_non_ascii_coverage_ge_80pct"] = True

    # 3) output/dialogues.md checks
    dialogues_path = os.path.join(output_dir, "dialogues.md")
    checks["dialogues_exists"] = False
    checks["dialogues_has_at_least_two_scenarios"] = False
    checks["dialogues_each_scenario_has_corrections_notes"] = False
    checks["dialogues_each_scenario_has_balanced_utterance_triples_ge8"] = False

    if os.path.isfile(dialogues_path):
        checks["dialogues_exists"] = True
        d_text = read_text_file(dialogues_path)
        scenarios = split_scenarios(d_text)
        if len(scenarios) >= 2:
            checks["dialogues_has_at_least_two_scenarios"] = True
            # Corrections & Notes presence
            corrections_ok = all(any("Corrections & Notes" in line for line in block) for block in scenarios)
            if corrections_ok:
                checks["dialogues_each_scenario_has_corrections_notes"] = True
            # Utterance triples counts
            triples_ok = True
            for block in scenarios:
                jp_count = sum(1 for line in block if line.startswith("[JP]"))
                rom_count = sum(1 for line in block if line.startswith("[ROM]"))
                en_count = sum(1 for line in block if line.startswith("[EN]"))
                if not (jp_count >= 8 and rom_count >= 8 and en_count >= 8 and jp_count == rom_count == en_count):
                    triples_ok = False
                    break
            if triples_ok:
                checks["dialogues_each_scenario_has_balanced_utterance_triples_ge8"] = True

    # 4) output/flashcards.json checks
    flashcards_path = os.path.join(output_dir, "flashcards.json")
    checks["flashcards_exists"] = False
    checks["flashcards_valid_json_array_ge24"] = False
    checks["flashcards_items_valid_structure_and_types"] = False

    if os.path.isfile(flashcards_path):
        checks["flashcards_exists"] = True
        fc = safe_load_json(flashcards_path)
        if isinstance(fc, list) and len(fc) >= 24:
            checks["flashcards_valid_json_array_ge24"] = True
            allowed_types = {"word", "phrase", "sentence-completion", "conjugation"}
            items_ok = True
            for item in fc:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                if not all(k in item for k in ["type", "front", "back"]):
                    items_ok = False
                    break
                t = item.get("type")
                front = item.get("front")
                back = item.get("back")
                if t not in allowed_types:
                    items_ok = False
                    break
                if not isinstance(front, str) or not isinstance(back, str):
                    items_ok = False
                    break
                if not front.strip() or not back.strip():
                    items_ok = False
                    break
            if items_ok:
                checks["flashcards_items_valid_structure_and_types"] = True

    # 5) output/script_practice.md checks
    script_path = os.path.join(output_dir, "script_practice.md")
    checks["script_practice_exists"] = False
    checks["script_practice_exactly_10_characters"] = False
    checks["script_practice_labels_counts_each_10"] = False

    if os.path.isfile(script_path):
        checks["script_practice_exists"] = True
        s_text = read_text_file(script_path)
        s_lines = s_text.splitlines()
        char_count = count_lines_starting_with(s_lines, "Character:")
        pron_count = count_lines_starting_with(s_lines, "Pronunciation:")
        stroke_count = count_lines_starting_with(s_lines, "Stroke order:")
        ex_count = count_lines_starting_with(s_lines, "Example word:")
        memo_count = count_lines_starting_with(s_lines, "Memory hook:")
        if char_count == 10:
            checks["script_practice_exactly_10_characters"] = True
        if pron_count == 10 and stroke_count == 10 and ex_count == 10 and memo_count == 10:
            checks["script_practice_labels_counts_each_10"] = True

    # 6) output/cultural_notes.md checks
    cultural_path = os.path.join(output_dir, "cultural_notes.md")
    checks["cultural_notes_exists"] = False
    checks["cultural_notes_at_least_5_bullets"] = False
    checks["cultural_notes_has_politeness_keyword"] = False

    if os.path.isfile(cultural_path):
        checks["cultural_notes_exists"] = True
        c_text = read_text_file(cultural_path)
        c_lines = c_text.splitlines()
        bullets = [line for line in c_lines if line.startswith("- ")]
        if len(bullets) >= 5:
            checks["cultural_notes_at_least_5_bullets"] = True
        keywords = ["polite", "politeness", "formal", "casual"]
        if any(any(kw in line.lower() for kw in keywords) for line in bullets):
            checks["cultural_notes_has_politeness_keyword"] = True

    # 7) output/assessment_quiz.json checks
    quiz_path = os.path.join(output_dir, "assessment_quiz.json")
    checks["quiz_exists"] = False
    checks["quiz_valid_json_array_ge10"] = False
    checks["quiz_items_valid_structure"] = False

    if os.path.isfile(quiz_path):
        checks["quiz_exists"] = True
        q = safe_load_json(quiz_path)
        if isinstance(q, list) and len(q) >= 10:
            checks["quiz_valid_json_array_ge10"] = True
            items_ok = True
            for item in q:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                if not all(k in item for k in ["question", "options", "answer_index"]):
                    items_ok = False
                    break
                question = item.get("question")
                options = item.get("options")
                answer_index = item.get("answer_index")
                if not isinstance(question, str) or not question.strip():
                    items_ok = False
                    break
                if not isinstance(options, list) or len(options) < 3 or not all(isinstance(o, str) for o in options):
                    items_ok = False
                    break
                if not isinstance(answer_index, int) or not (0 <= answer_index < len(options)):
                    items_ok = False
                    break
            if items_ok:
                checks["quiz_items_valid_structure"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
        # Bound reward to [0,1]
        reward = max(0.0, min(1.0, reward))
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()