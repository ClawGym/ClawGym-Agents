import json
import os
import sys
import re
from collections import OrderedDict, Counter

def read_jsonl(path):
    entries = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    entries.append(obj)
                except Exception:
                    # Skip invalid JSON lines to remain robust
                    continue
    except Exception:
        return []
    return entries

def read_rules(path):
    replacements = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Expecting {"replacements": [{"from": "...", "to": "..."} , ...]}
        if isinstance(data, dict) and isinstance(data.get("replacements"), list):
            for rep in data["replacements"]:
                if isinstance(rep, dict) and "from" in rep and "to" in rep:
                    fval = rep["from"]
                    tval = rep["to"]
                    if isinstance(fval, str) and isinstance(tval, str):
                        replacements.append((fval, tval))
        elif isinstance(data, list):
            # Fallback: top-level list of replacement pairs as dicts
            for rep in data:
                if isinstance(rep, dict) and "from" in rep and "to" in rep:
                    fval = rep["from"]
                    tval = rep["to"]
                    if isinstance(fval, str) and isinstance(tval, str):
                        replacements.append((fval, tval))
    except Exception:
        pass
    return replacements

def normalize_message(msg, replacements):
    if not isinstance(msg, str):
        msg = "" if msg is None else str(msg)
    s = msg.lower()
    # Strip punctuation characters . , : ; !
    trans_table = str.maketrans('', '', '.,:;!')
    s = s.translate(trans_table)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    # Trim
    s = s.strip()
    # Apply ordered literal substring replacements
    for frm, to in replacements:
        s = s.replace(frm, to)
    return s

def compute_ground_truth(logs_path, rules_path):
    entries = read_jsonl(logs_path)
    total = len(entries)
    level_counts = Counter()
    error_norm_counts = Counter()
    replacements = read_rules(rules_path)

    for obj in entries:
        level = obj.get("level")
        if isinstance(level, str):
            level_counts[level] += 1
            if level == "ERROR":
                msg = obj.get("message", "")
                norm = normalize_message(msg, replacements)
                error_norm_counts[norm] += 1

    # Prepare summary rows sorted by level ascending
    summary_levels_sorted = sorted(level_counts.keys())
    summary_rows = [(lvl, level_counts[lvl]) for lvl in summary_levels_sorted]

    # Prepare top errors up to 3, sort by count desc then message asc
    top_errors = []
    if error_norm_counts:
        items = list(error_norm_counts.items())
        items.sort(key=lambda x: (-x[1], x[0]))
        for i, (msg, cnt) in enumerate(items[:3]):
            top_errors.append({"message": msg, "count": cnt})

    # Prepare report content
    report_lines = []
    report_lines.append("Log Analysis Report")
    report_lines.append(f"Total entries: {total}")
    # Fixed order for report counts; include only if present
    for lvl in ["DEBUG", "ERROR", "INFO", "WARN"]:
        if lvl in level_counts:
            report_lines.append(f"{lvl}: {level_counts[lvl]}")
    report_lines.append("Top errors:")
    for idx, item in enumerate(top_errors, start=1):
        report_lines.append(f"{idx}. {item['message']} — {item['count']}")
    report_text = "\n".join(report_lines)

    return {
        "total": total,
        "summary_rows": summary_rows,
        "top_errors": top_errors,
        "report_text": report_text,
        "levels_present": set(level_counts.keys())
    }

def parse_summary_csv(text):
    lines = text.splitlines()
    if not lines:
        return None, []
    header = lines[0].strip()
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != 2:
            return header, None
        level = parts[0].strip()
        cnt_str = parts[1].strip()
        if not cnt_str.isdigit():
            return header, None
        rows.append((level, int(cnt_str)))
    return header, rows

def load_json_array(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def eq_with_optional_trailing_newline(a, b):
    if a == b:
        return True
    if a is None or b is None:
        return False
    if a.endswith("\n") and a[:-1] == b:
        return True
    if b.endswith("\n") and b[:-1] == a:
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    logs_path = os.path.join(input_dir, "logs.jsonl")
    rules_path = os.path.join(input_dir, "rules.json")

    gt = compute_ground_truth(logs_path, rules_path)

    # Initialize checks
    checks = OrderedDict()
    checks["summary_exists"] = False
    checks["summary_valid"] = False
    checks["top_errors_exists"] = False
    checks["top_errors_valid"] = False
    checks["report_exists"] = False
    checks["report_valid"] = False

    # Check summary.csv
    summary_path = os.path.join(output_dir, "summary.csv")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        content = read_text(summary_path)
        if content is not None:
            header, rows = parse_summary_csv(content)
            if header == "level,count" and rows is not None:
                # Must have exactly one row per level present in input
                expected_rows = gt["summary_rows"]
                # Validate row count
                if len(rows) == len(expected_rows):
                    # Validate sorting by level ascending
                    expected_sorted_levels = [lvl for lvl, _ in expected_rows]
                    given_levels = [lvl for lvl, _ in rows]
                    # Ensure exact set and order
                    if given_levels == expected_sorted_levels:
                        # Validate counts
                        levels_ok = True
                        for (lvl_exp, cnt_exp), (lvl_got, cnt_got) in zip(expected_rows, rows):
                            if lvl_exp != lvl_got or cnt_exp != cnt_got:
                                levels_ok = False
                                break
                        if levels_ok:
                            checks["summary_valid"] = True

    # Check top_errors.json
    top_path = os.path.join(output_dir, "top_errors.json")
    if os.path.isfile(top_path):
        checks["top_errors_exists"] = True
        data = load_json_array(top_path)
        if data is not None:
            # Build expected
            expected = gt["top_errors"]
            # Validate length <= 3 and equals expected exactly
            if isinstance(data, list):
                # Ensure each item has exactly two keys: message and count with correct types
                shape_ok = True
                for itm in data:
                    if not isinstance(itm, dict):
                        shape_ok = False
                        break
                    keys = set(itm.keys())
                    if keys != {"message", "count"}:
                        shape_ok = False
                        break
                    if not isinstance(itm["message"], str):
                        shape_ok = False
                        break
                    if not (isinstance(itm["count"], int) and itm["count"] >= 0):
                        shape_ok = False
                        break
                if shape_ok and data == expected:
                    checks["top_errors_valid"] = True

    # Check report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        content = read_text(report_path)
        if content is not None:
            expected = gt["report_text"]
            if eq_with_optional_trailing_newline(content, expected):
                checks["report_valid"] = True

    # Compute reward: proportion of valid artifacts
    valid_checks = [
        checks["summary_valid"],
        checks["top_errors_valid"],
        checks["report_valid"],
    ]
    passed = sum(1 for v in valid_checks if v)
    reward = passed / 3.0

    # No-op baseline: if all required artifacts missing or invalid, reward must be 0.0
    if reward == 0:
        reward_value = 0.0
    else:
        reward_value = float(reward)

    out = OrderedDict()
    out["reward"] = reward_value
    for k, v in checks.items():
        out[k] = v
    print(json.dumps(out))

if __name__ == "__main__":
    main()