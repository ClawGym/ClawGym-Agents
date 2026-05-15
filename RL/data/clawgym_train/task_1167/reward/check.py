import json
import os
import re
import sys
import csv

def read_csv_headwords(csv_path):
    headwords = []
    if not os.path.isfile(csv_path):
        return headwords
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
        if not rows:
            return headwords
        header = [h.strip().lower() for h in rows[0]]
        # Try to find a column for headword
        candidates = ["headword", "word", "term", "entry"]
        idx = None
        for c in candidates:
            if c in header:
                idx = header.index(c)
                break
        if idx is None:
            # Fallback: assume first column
            idx = 0
        for row in rows[1:]:
            if not row:
                continue
            # Pad row if shorter
            if idx >= len(row):
                continue
            hw = row[idx].strip()
            if hw:
                headwords.append(hw)
    return headwords

def read_jsonl(path):
    objs = []
    lines = []
    if not os.path.isfile(path):
        return objs, lines
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if raw.strip() == "":
                continue
            try:
                obj = json.loads(raw)
                objs.append(obj)
                lines.append(raw)
            except Exception:
                # keep placeholder for invalid
                objs.append(None)
                lines.append(raw)
    return objs, lines

def parse_grades_jsonl(path):
    objs, _ = read_jsonl(path)
    grades = []
    for o in objs:
        if not isinstance(o, dict):
            continue
        hw = o.get("headword")
        gr = o.get("grade")
        if isinstance(hw, str) and isinstance(gr, int):
            grades.append({"headword": hw, "grade": gr})
    return grades

def count_bullet_lines(text):
    cnt = 0
    for line in text.splitlines():
        if line.startswith("• "):
            cnt += 1
    return cnt

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        # add_results.jsonl checks
        "add_exists": False,
        "add_line_count_correct": False,
        "add_all_json_valid": False,
        "add_fields_valid": False,
        "add_headwords_match_set": False,
        # rendered_cards.txt checks
        "render_exists": False,
        "render_nonempty": False,
        "render_contains_all_headwords": False,
        "render_has_examples_header": False,
        "render_bullets_ge_15": False,
        # review_application.jsonl checks
        "review_exists": False,
        "review_line_count_correct": False,
        "review_all_json_valid": False,
        "review_fields_valid": False,
        "review_grade_interval_consistent": False,
        "review_headwords_match_set": False,
        # summary.md checks
        "summary_exists": False,
        "summary_mentions_all_headwords": False,
        "summary_has_grading_scale": False,
        "summary_line_count_ok": False,
    }

    # Load input references
    words_csv = os.path.join(input_dir, "words.csv")
    input_headwords = read_csv_headwords(words_csv)
    input_headwords_norm = [hw.strip() for hw in input_headwords]
    input_headword_set = {hw.lower() for hw in input_headwords_norm}

    grades_path = os.path.join(input_dir, "review_grades.jsonl")
    input_grades = parse_grades_jsonl(grades_path)
    input_grade_map = {g["headword"].lower(): g["grade"] for g in input_grades}
    input_grades_set = set(input_grade_map.keys())

    # 1) add_results.jsonl
    add_path = os.path.join(output_dir, "add_results.jsonl")
    if os.path.isfile(add_path):
        checks["add_exists"] = True
        add_objs, add_lines = read_jsonl(add_path)
        # line count equals number of data rows in CSV
        if len(add_lines) == len(input_headwords_norm) and len(add_lines) > 0:
            checks["add_line_count_correct"] = True
        # validate json and fields
        all_valid_json = all(isinstance(o, dict) for o in add_objs) and len(add_objs) == len(add_lines)
        checks["add_all_json_valid"] = all_valid_json
        fields_valid = True
        headwords_out = []
        statuses_ok = {"ok", "exists"}
        if all_valid_json:
            for o in add_objs:
                status = o.get("status")
                cid = o.get("id")
                hw = o.get("headword")
                if status not in statuses_ok or not isinstance(cid, int) or not isinstance(hw, str):
                    fields_valid = False
                    break
                headwords_out.append(hw)
            checks["add_fields_valid"] = fields_valid
        if fields_valid and len(headwords_out) == len(input_headwords_norm) and len(headwords_out) > 0:
            # compare sets case-insensitive
            out_set = {h.lower().strip() for h in headwords_out}
            checks["add_headwords_match_set"] = (out_set == input_headword_set)

    # 2) rendered_cards.txt
    render_path = os.path.join(output_dir, "rendered_cards.txt")
    if os.path.isfile(render_path):
        checks["render_exists"] = True
        try:
            with open(render_path, "r", encoding="utf-8") as f:
                render_text = f.read()
        except Exception:
            render_text = ""
        if render_text.strip() != "":
            checks["render_nonempty"] = True
            # check each headword appears (case-insensitive)
            text_lower = render_text.lower()
            contains_all = True
            for hw in input_headwords_norm:
                if hw.strip() == "":
                    continue
                if hw.lower() not in text_lower:
                    contains_all = False
                    break
            checks["render_contains_all_headwords"] = contains_all
            # examples header
            checks["render_has_examples_header"] = ("examples" in text_lower)
            # bullet lines count
            bullets = count_bullet_lines(render_text)
            if bullets >= 15:
                checks["render_bullets_ge_15"] = True

    # 3) review_application.jsonl
    review_path = os.path.join(output_dir, "review_application.jsonl")
    if os.path.isfile(review_path):
        checks["review_exists"] = True
        review_objs, review_lines = read_jsonl(review_path)
        # line count equals number of objects in input/review_grades.jsonl
        if len(review_lines) == len(input_grades) and len(review_lines) > 0:
            checks["review_line_count_correct"] = True
        all_json_valid = all(isinstance(o, dict) for o in review_objs) and len(review_objs) == len(review_lines)
        checks["review_all_json_valid"] = all_json_valid
        fields_valid = True
        grade_interval_ok = True
        headwords_review_out = []
        if all_json_valid:
            for o in review_objs:
                hw = o.get("headword")
                gr = o.get("grade")
                cid = o.get("card_id")
                new_obj = o.get("new")
                if not isinstance(hw, str) or not isinstance(gr, int) or not isinstance(cid, int) or not isinstance(new_obj, dict):
                    fields_valid = False
                    break
                interval_days = new_obj.get("interval_days")
                due_at = new_obj.get("due_at")
                if not isinstance(interval_days, int) or not isinstance(due_at, str):
                    fields_valid = False
                    break
                # ISO-like timestamp check: YYYY-MM-DDTHH:...
                if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:", due_at) is None:
                    fields_valid = False
                    break
                # grade constraints
                # Must match input grade for that headword if present
                exp_grade = input_grade_map.get(hw.lower())
                if exp_grade is not None:
                    if gr != exp_grade:
                        grade_interval_ok = False
                # interval constraints
                if gr == 0:
                    if interval_days != 0:
                        grade_interval_ok = False
                else:
                    if interval_days < 1:
                        grade_interval_ok = False
                headwords_review_out.append(hw)
        checks["review_fields_valid"] = fields_valid
        if fields_valid:
            checks["review_grade_interval_consistent"] = grade_interval_ok
            out_set = {h.lower().strip() for h in headwords_review_out}
            checks["review_headwords_match_set"] = (out_set == input_grades_set)

    # 4) summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = ""
        # line count
        lines = [ln for ln in summary_text.splitlines()]
        if 15 <= len(lines) <= 400:
            checks["summary_line_count_ok"] = True
        # grading scale mention
        if re.search(r"0\s*[–-]\s*3", summary_text):
            checks["summary_has_grading_scale"] = True
        # mention all headwords
        text_lower = summary_text.lower()
        mentions_all = True
        for hw in input_headwords_norm:
            if hw.strip() == "":
                continue
            if hw.lower() not in text_lower:
                mentions_all = False
                break
        checks["summary_mentions_all_headwords"] = mentions_all

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # No-op baseline: if required artifacts are missing entirely, ensure 0.0
    # If none of the four outputs exist, set reward 0.0
    outputs_exist = any(os.path.isfile(p) for p in [add_path, render_path, review_path, summary_path])
    if not outputs_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()