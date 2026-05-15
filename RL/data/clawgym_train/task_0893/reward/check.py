import json
import os
import sys
import csv
import re

def read_text_lines(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().splitlines()
    except Exception:
        return None

def is_valid_date(s):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

def is_valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s))

def word_count(text):
    return len([w for w in text.split() if w.strip()])

def validate_posts_csv(path):
    result = {
        "posts_csv_exists": False,
        "posts_csv_header_valid": False,
        "posts_csv_row_count_7": False,
        "posts_csv_rows_valid_format": False,
        "posts_bodies_length_and_question": False,
        "posts_bodies_no_urls": False,
        "posts_hashtags_valid": False,
    }
    if not os.path.isfile(path):
        return result

    result["posts_csv_exists"] = True

    expected_header = ["date", "day_of_week", "time", "hook", "body", "hashtags", "cta"]
    rows = []
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            all_rows = list(reader)
        if not all_rows:
            return result
        header = all_rows[0]
        if header == expected_header:
            result["posts_csv_header_valid"] = True
        data_rows = all_rows[1:]
        rows = data_rows
    except Exception:
        return result

    if len(rows) == 7:
        result["posts_csv_row_count_7"] = True

    # Initialize per-condition flags; only set True after verifying all rows
    rows_valid_format = True
    bodies_len_and_q = True
    bodies_no_urls = True
    hashtags_valid_all = True

    for r in rows:
        # If row has fewer columns, pad; if more, trim
        if len(r) < 7:
            r = r + [""] * (7 - len(r))
        elif len(r) > 7:
            r = r[:7]
        date, day_of_week, time_s, hook, body, hashtags, cta = r

        # rows_valid_format checks: date/time formats; hook/cta non-empty
        if not (is_valid_date(date) and is_valid_time(time_s) and hook.strip() and cta.strip()):
            rows_valid_format = False

        # body length between 120 and 300 words inclusive, contains at least one '?'
        wc = word_count(body or "")
        if not (120 <= wc <= 300 and ("?" in (body or ""))):
            bodies_len_and_q = False

        # body contains no http(s) URL
        low = (body or "").lower()
        if ("http://" in low) or ("https://" in low):
            bodies_no_urls = False

        # hashtags: 3-5 tokens, each starting with '#'
        tokens = [t for t in (hashtags or "").split() if t.strip()]
        if not (3 <= len(tokens) <= 5 and all(tok.startswith("#") and len(tok) > 1 for tok in tokens)):
            hashtags_valid_all = False

    result["posts_csv_rows_valid_format"] = rows_valid_format and (len(rows) == 7)
    result["posts_bodies_length_and_question"] = bodies_len_and_q and (len(rows) == 7)
    result["posts_bodies_no_urls"] = bodies_no_urls and (len(rows) == 7)
    result["posts_hashtags_valid"] = hashtags_valid_all and (len(rows) == 7)

    return result

def validate_hooks_txt(path):
    checks = {
        "hooks_txt_exists": False,
        "hooks_txt_min_20": False,
        "hooks_txt_each_le_12_words": False,
    }
    lines = read_text_lines(path)
    if lines is None:
        return checks
    checks["hooks_txt_exists"] = True
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    if len(non_empty) >= 20:
        checks["hooks_txt_min_20"] = True
    all_le_12 = True
    for ln in non_empty:
        if word_count(ln) > 12:
            all_le_12 = False
            break
    checks["hooks_txt_each_le_12_words"] = all_le_12 and (len(non_empty) >= 20)
    return checks

def validate_hashtags_txt(path):
    checks = {
        "hashtags_txt_exists": False,
        "hashtags_txt_min_10": False,
        "hashtags_txt_sets_valid": False,
    }
    lines = read_text_lines(path)
    if lines is None:
        return checks
    checks["hashtags_txt_exists"] = True
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    if len(non_empty) >= 10:
        checks["hashtags_txt_min_10"] = True
    all_sets_valid = True
    for ln in non_empty:
        tokens = [t for t in ln.split() if t.strip()]
        if not (3 <= len(tokens) <= 5 and all(tok.startswith("#") and len(tok) > 1 for tok in tokens)):
            all_sets_valid = False
            break
    checks["hashtags_txt_sets_valid"] = all_sets_valid and (len(non_empty) >= 10)
    return checks

def validate_ctas_txt(path):
    checks = {
        "ctas_txt_exists": False,
        "ctas_txt_min_10": False,
    }
    lines = read_text_lines(path)
    if lines is None:
        return checks
    checks["ctas_txt_exists"] = True
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    if len(non_empty) >= 10:
        checks["ctas_txt_min_10"] = True
    return checks

def validate_schedule_md(path):
    checks = {
        "schedule_md_exists": False,
        "schedule_md_exactly_7_lines": False,
        "schedule_md_lines_valid": False,
    }
    lines = read_text_lines(path)
    if lines is None:
        return checks
    checks["schedule_md_exists"] = True
    # Consider only non-empty trimmed lines as entries
    entries = [ln.strip() for ln in lines if ln.strip()]
    if len(entries) == 7:
        checks["schedule_md_exactly_7_lines"] = True
    # Validate each line: contains a weekday name and time HH:MM
    dows = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    dow_pattern = re.compile(r"\b(" + "|".join(dows) + r")\b", re.IGNORECASE)
    all_valid = True
    for ln in entries:
        if not dow_pattern.search(ln):
            all_valid = False
            break
        times = re.findall(r"\b([01]\d|2[0-3]):[0-5]\d\b", ln)
        if not times:
            all_valid = False
            break
    checks["schedule_md_lines_valid"] = all_valid and (len(entries) == 7)
    return checks

def validate_export_json(path):
    checks = {
        "export_json_exists": False,
        "export_json_valid": False,
        "export_json_counts_ok": False,
    }
    if not os.path.isfile(path):
        return checks
    checks["export_json_exists"] = True
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return checks
    if not isinstance(data, list):
        return checks

    valid_schema = True
    counts = {"draft":0, "hooks":0, "hashtags":0, "cta":0, "schedule":0}
    for item in data:
        if not isinstance(item, dict):
            valid_schema = False
            break
        # Must have keys type,time,value and all strings
        if not all(k in item for k in ("type","time","value")):
            valid_schema = False
            break
        if not (isinstance(item["type"], str) and isinstance(item["time"], str) and isinstance(item["value"], str)):
            valid_schema = False
            break
        t = item.get("type")
        if t in counts:
            counts[t] += 1
    if not valid_schema:
        return checks
    checks["export_json_valid"] = True
    if counts["draft"] >= 7 and counts["hooks"] >= 20 and counts["hashtags"] >= 10 and counts["cta"] >= 10 and counts["schedule"] >= 7:
        checks["export_json_counts_ok"] = True
    return checks

def validate_summary_md(path):
    checks = {
        "summary_md_exists": False,
        "summary_has_headings": False,
    }
    lines = read_text_lines(path)
    if lines is None:
        return checks
    checks["summary_md_exists"] = True
    text = "\n".join(lines)
    has_strategy = re.search(r"^##\s+Strategy\s*$", text, re.MULTILINE) is not None
    has_tone = re.search(r"^##\s+Tone\s*$", text, re.MULTILINE) is not None
    has_sched = re.search(r"^##\s+Schedule Rationale\s*$", text, re.MULTILINE) is not None
    checks["summary_has_headings"] = bool(has_strategy and has_tone and has_sched)
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all False so that missing outputs yield 0.0
    all_checks = {}

    # Validate each artifact
    posts_checks = validate_posts_csv(os.path.join(output_dir, "posts.csv"))
    all_checks.update(posts_checks)

    hooks_checks = validate_hooks_txt(os.path.join(output_dir, "hooks.txt"))
    all_checks.update(hooks_checks)

    hashtags_checks = validate_hashtags_txt(os.path.join(output_dir, "hashtags.txt"))
    all_checks.update(hashtags_checks)

    ctas_checks = validate_ctas_txt(os.path.join(output_dir, "ctas.txt"))
    all_checks.update(ctas_checks)

    schedule_checks = validate_schedule_md(os.path.join(output_dir, "schedule.md"))
    all_checks.update(schedule_checks)

    export_checks = validate_export_json(os.path.join(output_dir, "export.json"))
    all_checks.update(export_checks)

    summary_checks = validate_summary_md(os.path.join(output_dir, "summary.md"))
    all_checks.update(summary_checks)

    # Compute reward as average of booleans
    bool_values = list(all_checks.values())
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values) if bool_values else 1
    reward = (passed / total) if total > 0 else 0.0

    # Explicit no-op baseline: if output dir missing or empty -> reward = 0.0
    if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir) if not name.startswith(".")]) == 0):
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print exactly one JSON object; ensure "reward" is first
    result = {"reward": reward}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()