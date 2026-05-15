import json
import os
import sys
import csv

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_heading_line(line):
    s = line.strip()
    # Remove leading Markdown heading markers (#) and following spaces
    i = 0
    while i < len(s) and s[i] == '#':
        i += 1
    if i > 0:
        # remove any extra spaces after hashes
        s = s[i:].lstrip()
    return s

def check_audit_report_md(path):
    # Required headings exactly once
    required = [
        "Summary of Findings",
        "CTA Analysis",
        "Hero Section",
        "Trust Signals",
        "Social Proof",
        "Mobile Optimization",
        "Page Speed Considerations",
        "Copy Optimization",
        "A/B Testing Strategy",
        "Next Steps",
    ]
    if not os.path.isfile(path):
        return False
    content = read_text_file(path)
    if content is None:
        return False
    counts = {k: 0 for k in required}
    for line in content.splitlines():
        norm = normalize_heading_line(line)
        if norm in counts:
            counts[norm] += 1
    # All required must be present exactly once
    for k in required:
        if counts.get(k, 0) != 1:
            return False
    return True

def is_nonempty_string(v):
    return isinstance(v, str) and v.strip() != ""

def check_ab_test_plan_json(path):
    if not os.path.isfile(path):
        return False
    data = read_json_file(path)
    if not isinstance(data, list):
        return False
    if not (6 <= len(data) <= 10):
        return False
    allowed_segments = {"mobile", "desktop", "all"}
    for item in data:
        if not isinstance(item, dict):
            return False
        keys_required = ["id", "hypothesis", "metric", "expected_impact", "confidence", "priority_score", "variant_a", "variant_b", "segment", "duration_days"]
        for k in keys_required:
            if k not in item:
                return False
        # id must be non-empty string
        if not is_nonempty_string(item.get("id")):
            return False
        if not is_nonempty_string(item.get("hypothesis")):
            return False
        if not is_nonempty_string(item.get("metric")):
            return False
        if not is_nonempty_string(item.get("expected_impact")):
            return False
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, int) or not (1 <= confidence <= 5):
            return False
        priority_score = item.get("priority_score")
        if isinstance(priority_score, bool) or not isinstance(priority_score, (int, float)):
            return False
        if not is_nonempty_string(item.get("variant_a")):
            return False
        if not is_nonempty_string(item.get("variant_b")):
            return False
        segment = item.get("segment")
        if not isinstance(segment, str) or segment not in allowed_segments:
            return False
        duration_days = item.get("duration_days")
        if isinstance(duration_days, bool) or not isinstance(duration_days, int) or duration_days < 7:
            return False
    return True

def check_prioritized_actions_csv(path):
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return False
    if not rows:
        return False
    header = rows[0]
    expected_header = ["priority", "category", "recommendation", "effort", "impact", "confidence", "owner"]
    if header != expected_header:
        return False
    data_rows = rows[1:]
    if len(data_rows) < 10:
        return False
    allowed_levels = {"low", "medium", "high"}
    for r in data_rows:
        # Allow shorter or longer rows but require at least 7 columns
        if len(r) < 7:
            return False
        prio_raw = r[0].strip()
        try:
            prio = int(prio_raw)
        except Exception:
            return False
        if prio not in {1, 2, 3}:
            return False
        effort = r[3].strip().lower()
        impact = r[4].strip().lower()
        if effort not in allowed_levels or impact not in allowed_levels:
            return False
        conf_raw = r[5].strip()
        try:
            conf = int(conf_raw)
        except Exception:
            return False
        if conf < 1 or conf > 5:
            return False
    return True

def check_summary_json(path):
    if not os.path.isfile(path):
        return False
    data = read_json_file(path)
    if not isinstance(data, dict):
        return False
    required_keys = ["platform", "product", "current_cr", "mobile_share", "primary_traffic_sources", "key_issues", "quick_wins"]
    for k in required_keys:
        if k not in data:
            return False
    if not is_nonempty_string(data.get("platform")):
        return False
    if not is_nonempty_string(data.get("product")):
        return False
    current_cr = data.get("current_cr")
    if isinstance(current_cr, bool) or not isinstance(current_cr, (int, float)) or current_cr <= 0:
        return False
    mobile_share = data.get("mobile_share")
    if isinstance(mobile_share, bool) or not isinstance(mobile_share, (int, float)) or not (0 <= mobile_share <= 100):
        return False
    pts = data.get("primary_traffic_sources")
    if not isinstance(pts, list) or len(pts) < 2 or not all(isinstance(x, str) and x.strip() != "" for x in pts):
        return False
    key_issues = data.get("key_issues")
    if not isinstance(key_issues, list) or len(key_issues) < 1 or not all(isinstance(x, str) and x.strip() != "" for x in key_issues):
        return False
    quick_wins = data.get("quick_wins")
    if not isinstance(quick_wins, list) or len(quick_wins) < 3 or not all(isinstance(x, str) and x.strip() != "" for x in quick_wins):
        return False
    return True

def main():
    workspace_root = get_workspace_root()
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "audit_report_has_sections": False,
        "ab_test_plan_valid": False,
        "prioritized_actions_valid": False,
        "summary_json_valid": False,
    }

    audit_md_path = os.path.join(output_dir, "audit_report.md")
    ab_json_path = os.path.join(output_dir, "ab_test_plan.json")
    actions_csv_path = os.path.join(output_dir, "prioritized_actions.csv")
    summary_json_path = os.path.join(output_dir, "summary.json")

    if os.path.isfile(audit_md_path):
        checks["audit_report_has_sections"] = check_audit_report_md(audit_md_path)

    if os.path.isfile(ab_json_path):
        checks["ab_test_plan_valid"] = check_ab_test_plan_json(ab_json_path)

    if os.path.isfile(actions_csv_path):
        checks["prioritized_actions_valid"] = check_prioritized_actions_csv(actions_csv_path)

    if os.path.isfile(summary_json_path):
        checks["summary_json_valid"] = check_summary_json(summary_json_path)

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    # Print exactly one JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()