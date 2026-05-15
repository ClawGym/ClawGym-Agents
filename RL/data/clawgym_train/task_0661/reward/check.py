import json
import os
import re
import sys

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return []

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def line_starts_with_label(line, label):
    # Case-insensitive; allow optional colon or dash after label
    # Example matches: "Current state:", "current state -", "Current state — ...", "Current state ..."
    pattern = r'^\s*' + re.escape(label) + r'\b\s*(?::|[-—])?\s*'
    return re.match(pattern, line, flags=re.IGNORECASE) is not None

def find_briefing_sequence(lines, labels, max_lines=20):
    # Search within the first max_lines for labels in order
    search_space = lines[:max_lines]
    pos = -1
    for label in labels:
        found = False
        for i in range(pos + 1, len(search_space)):
            if line_starts_with_label(search_space[i], label):
                pos = i
                found = True
                break
        if not found:
            return False
    return True

def normalize_cells(line):
    # Split markdown table row into cells, trim spaces and ignore leading/trailing pipes
    parts = [c.strip() for c in line.strip().strip("|").split("|")]
    return parts

def is_md_separator(line):
    # Markdown separator lines are typically like: |---|-----|----| with optional colons
    s = line.strip()
    if "|" not in s:
        return False
    # Remove allowed separator chars and spaces; if nothing remains, it's a separator
    cleaned = re.sub(r'[\s\-\|\:]', '', s)
    return cleaned == ""

def find_table_header_index(lines, expected_headers):
    for i, line in enumerate(lines):
        if "|" in line:
            cells = normalize_cells(line)
            # Ignore empty cell artifacts from consecutive pipes only at ends, normalize_cells handles ends
            if cells == expected_headers:
                return i
    return -1

def count_data_rows_after_header(lines, header_idx, min_cols=3):
    count = 0
    for j in range(header_idx + 1, len(lines)):
        l = lines[j].strip()
        if not l:
            continue
        if "|" not in l:
            continue
        if is_md_separator(l):
            continue
        cells = normalize_cells(l)
        # Count rows with at least min_cols cells
        if len(cells) >= min_cols:
            count += 1
    return count

def find_total_recovered_amount(lines):
    # Returns (found, amount_float)
    pattern = re.compile(r'^\s*Total recovered revenue:\s*\$([0-9]+(?:\.[0-9]{1,2})?)\b', re.IGNORECASE)
    for line in lines:
        m = pattern.match(line)
        if m:
            try:
                val = float(m.group(1))
                return True, val
            except ValueError:
                return False, 0.0
    return False, 0.0

def contains_money(text):
    return re.search(r'\$\d+(?:\.\d{1,2})?', text) is not None

def contains_all(text, words):
    t = text.lower()
    return all(w.lower() in t for w in words)

def mission_log_has_fields(text):
    t = text.lower()
    return ("situation:" in t) and ("recommendation style:" in t) and ("follow-through note:" in t)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "briefing_exists": False,
        "briefing_has_required_sequence": False,
        "audit_report_exists": False,
        "audit_table_header_ok": False,
        "audit_has_two_data_rows": False,
        "audit_total_recovered_valid": False,
        "audit_has_assumptions_after_table": False,
        "admin_message_exists": False,
        "admin_has_approve_update_amount": False,
        "mission_log_exists": False,
        "mission_log_has_required_fields": False,
    }

    # 1) briefing.md checks
    briefing_path = os.path.join(output_dir, "briefing.md")
    if os.path.isfile(briefing_path):
        checks["briefing_exists"] = True
        briefing_lines = read_lines(briefing_path)
        required_labels = ["Current state", "Main risk", "Recommendation", "Next step"]
        if find_briefing_sequence(briefing_lines, required_labels, max_lines=20):
            checks["briefing_has_required_sequence"] = True

    # 2) audit_report.md checks
    audit_path = os.path.join(output_dir, "audit_report.md")
    if os.path.isfile(audit_path):
        checks["audit_report_exists"] = True
        audit_lines = read_lines(audit_path)

        # Table header
        expected_headers = ["Item in Notes", "Status in Bill", "Estimated Leakage"]
        header_idx = find_table_header_index(audit_lines, expected_headers)
        if header_idx != -1:
            checks["audit_table_header_ok"] = True
            # Data rows after header (ignoring separator lines)
            if count_data_rows_after_header(audit_lines, header_idx, min_cols=3) >= 2:
                checks["audit_has_two_data_rows"] = True
            # "Assumptions" appears after the table header somewhere
            after_text = "\n".join(audit_lines[header_idx + 1 : ])
            if re.search(r'\bassumptions\b', after_text, flags=re.IGNORECASE):
                checks["audit_has_assumptions_after_table"] = True

        # Total recovered revenue line
        found_total, amount = find_total_recovered_amount(audit_lines)
        if found_total and amount > 0.0:
            checks["audit_total_recovered_valid"] = True

    # 3) admin_message.txt checks
    admin_path = os.path.join(output_dir, "admin_message.txt")
    if os.path.isfile(admin_path):
        checks["admin_message_exists"] = True
        admin_text = read_text(admin_path)
        has_words = contains_all(admin_text, ["approve", "update"])
        has_amount = contains_money(admin_text)
        if has_words and has_amount:
            checks["admin_has_approve_update_amount"] = True

    # 4) mission_log.md checks
    mission_path = os.path.join(output_dir, "mission_log.md")
    if os.path.isfile(mission_path):
        checks["mission_log_exists"] = True
        mission_text = read_text(mission_path)
        if mission_log_has_fields(mission_text):
            checks["mission_log_has_required_fields"] = True

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()