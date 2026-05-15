import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def contains_in_order(text, substrings, case_insensitive=True):
    s = text.lower() if case_insensitive else text
    idx = -1
    for sub in substrings:
        needle = sub.lower() if case_insensitive else sub
        new_idx = s.find(needle, idx + 1)
        if new_idx == -1:
            return False
        idx = new_idx
    return True

def find_section_start(text, section_name):
    t = text.lower()
    name = section_name.lower()
    return t.find(name)

def count_priority_action_items(text):
    # Count list items within the "Priority Action Plan" section
    start = find_section_start(text, "Priority Action Plan")
    if start == -1:
        return 0
    subsection = text[start:]
    # Optionally stop at next major heading if present
    # Look for markdown heading pattern or known next sections (none expected after priority)
    # We will just count from start to end; acceptable per spec.
    lines = subsection.splitlines()
    bullet_pat = re.compile(r'^\s*[-*]\s+\S')
    numbered_pat = re.compile(r'^\s*\d+[\.\)]\s+\S')
    count = 0
    for line in lines:
        if bullet_pat.search(line) or numbered_pat.search(line):
            count += 1
    return count

def has_markdown_header_with_columns(text, required_cols):
    # Find any markdown table header line that contains all required substrings
    lines = text.splitlines()
    for line in lines:
        if '|' in line:
            l = line.strip()
            hay = l.lower()
            if all(col.lower() in hay for col in required_cols):
                return True
    return False

def line_window_contains(lines, idx, predicate):
    start = max(0, idx - 1)
    end = min(len(lines), idx + 2)
    for i in range(start, end):
        if predicate(lines[i]):
            return True
    return False

def int_like_but_not_bool(x):
    return isinstance(x, int) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # audit_report.md
        "audit_exists": False,
        "audit_has_sections": False,
        "audit_sections_in_order": False,
        "audit_has_citations": False,
        "audit_action_items_in_priority_plan": False,
        "audit_has_template_disclaimer": False,
        # training_matrix.md
        "training_exists": False,
        "training_has_header_cols": False,
        "training_has_forklift_1910_178": False,
        "training_has_loto_1910_147_maintenance": False,
        # jha_forklift_loading.md
        "jha_exists": False,
        "jha_mentions_jha": False,
        "jha_table_header_has_cols": False,
        "jha_has_steps_1_to_4": False,
        # incident_analysis.md
        "incident_exists": False,
        "incident_includes_5_whys": False,
        "incident_includes_recordkeeping_terms": False,
        # management_dashboard.json
        "dashboard_exists": False,
        "dashboard_valid_json": False,
        "dashboard_has_required_keys_and_types": False,
    }

    # 1) audit_report.md
    audit_path = os.path.join(output_dir, "audit_report.md")
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        audit_text = read_text_file(audit_path)
        audit_lower = audit_text.lower()

        # Section presence
        needed_sections = [
            "Hazard Assessment Matrix",
            "OSHA Compliance Checklist",
            "Gap Analysis",
            "Priority Action Plan",
        ]
        has_all = all(s.lower() in audit_lower for s in map(str, needed_sections))
        checks["audit_has_sections"] = has_all

        # Sections order
        checks["audit_sections_in_order"] = contains_in_order(audit_text, needed_sections, case_insensitive=True)

        # Citations
        has_osha_1910 = "osha 29 cfr 1910" in audit_lower
        has_147 = "1910.147" in audit_text
        has_1200 = "1910.1200" in audit_text
        has_178 = "1910.178" in audit_text
        checks["audit_has_citations"] = has_osha_1910 and has_147 and has_1200 and has_178

        # At least 3 action items in Priority Action Plan
        action_count = count_priority_action_items(audit_text)
        checks["audit_action_items_in_priority_plan"] = action_count >= 3

        # Disclaimer phrase exact
        disclaimer_phrase = "This document must be reviewed by a competent safety professional before implementation."
        checks["audit_has_template_disclaimer"] = disclaimer_phrase in audit_text

    # 2) training_matrix.md
    training_path = os.path.join(output_dir, "training_matrix.md")
    if os.path.isfile(training_path):
        checks["training_exists"] = True
        training_text = read_text_file(training_path)
        training_lines = training_text.splitlines()

        # Header with Role, Frequency, Regulatory, Cost
        checks["training_has_header_cols"] = has_markdown_header_with_columns(
            training_text, ["Role", "Frequency", "Regulatory", "Cost"]
        )

        # Forklift/PIT with 1910.178 same or adjacent line
        forklift_ok = False
        for i, line in enumerate(training_lines):
            if re.search(r'\b(forklift|PIT|powered industrial truck)\b', line, re.IGNORECASE):
                if line_window_contains(training_lines, i, lambda s: "1910.178" in s):
                    forklift_ok = True
                    break
        checks["training_has_forklift_1910_178"] = forklift_ok

        # LOTO for maintenance with 1910.147 same or adjacent line
        loto_ok = False
        for i, line in enumerate(training_lines):
            if re.search(r'\b(LOTO|lockout|tagout|lockout/tagout)\b', line, re.IGNORECASE):
                # check window for 1910.147 and maintenance mention
                window_start = max(0, i - 1)
                window_end = min(len(training_lines), i + 2)
                window = training_lines[window_start:window_end]
                has_147 = any("1910.147" in w for w in window)
                has_maintenance = any(re.search(r'maintenance', w, re.IGNORECASE) for w in window)
                if has_147 and has_maintenance:
                    loto_ok = True
                    break
        checks["training_has_loto_1910_147_maintenance"] = loto_ok

    # 3) jha_forklift_loading.md
    jha_path = os.path.join(output_dir, "jha_forklift_loading.md")
    if os.path.isfile(jha_path):
        checks["jha_exists"] = True
        jha_text = read_text_file(jha_path)
        jha_lower = jha_text.lower()

        # Mention Job Hazard Analysis or JHA
        checks["jha_mentions_jha"] = ("job hazard analysis" in jha_lower) or ("jha" in jha_lower)

        # Table header includes Step, Hazard, Risk, Controls
        checks["jha_table_header_has_cols"] = has_markdown_header_with_columns(
            jha_text, ["Step", "Hazard", "Risk", "Controls"]
        )

        # Literal strings Step 1..4
        steps_ok = all(f"Step {n}" in jha_text for n in [1, 2, 3, 4])
        checks["jha_has_steps_1_to_4"] = steps_ok

    # 4) incident_analysis.md
    incident_path = os.path.join(output_dir, "incident_analysis.md")
    if os.path.isfile(incident_path):
        checks["incident_exists"] = True
        incident_text = read_text_file(incident_path)
        incident_lower = incident_text.lower()

        # Exact phrase "5 Whys"
        checks["incident_includes_5_whys"] = "5 Whys" in incident_text

        # Recordkeeping terms: recordable or lost time or first aid
        checks["incident_includes_recordkeeping_terms"] = any(
            term in incident_lower for term in ["recordable", "lost time", "first aid"]
        )

    # 5) management_dashboard.json
    dash_path = os.path.join(output_dir, "management_dashboard.json")
    dash_data = None
    if os.path.isfile(dash_path):
        checks["dashboard_exists"] = True
        try:
            with open(dash_path, "r", encoding="utf-8") as f:
                dash_data = json.load(f)
            checks["dashboard_valid_json"] = True
        except Exception:
            checks["dashboard_valid_json"] = False

        if checks["dashboard_valid_json"]:
            keys_ok = all(k in dash_data for k in [
                "readiness_score",
                "total_employees",
                "last12mo_incidents",
                "top_risks",
                "next_30_days_priorities",
            ])
            types_ok = False
            ranges_ok = False
            lists_ok = False
            if keys_ok:
                rs = dash_data.get("readiness_score")
                te = dash_data.get("total_employees")
                li = dash_data.get("last12mo_incidents")
                tr = dash_data.get("top_risks")
                np = dash_data.get("next_30_days_priorities")

                # Types
                rs_is_num = isinstance(rs, (int, float)) and not isinstance(rs, bool)
                te_is_int = int_like_but_not_bool(te)
                li_is_int = int_like_but_not_bool(li)
                tr_is_list = isinstance(tr, list)
                np_is_list = isinstance(np, list)
                types_ok = rs_is_num and te_is_int and li_is_int and tr_is_list and np_is_list

                # Ranges and lengths
                if rs_is_num:
                    ranges_ok = (0 <= float(rs) <= 100)
                if tr_is_list and np_is_list:
                    lists_ok = (len(tr) >= 3 and len(np) >= 3)

            checks["dashboard_has_required_keys_and_types"] = keys_ok and types_ok and ranges_ok and lists_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()