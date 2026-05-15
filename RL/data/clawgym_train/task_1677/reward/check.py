import json
import os
import sys
import re
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_sections_by_heading(text, heading_title):
    # Return sections of text that start with a markdown heading whose title matches exactly heading_title
    lines = text.splitlines()
    heading_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title == heading_title:
                heading_indices.append(i)
    sections = []
    for idx, start in enumerate(heading_indices):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith("#"):
                end = j
                break
        sections.append("\n".join(lines[start:end]))
    return sections

def first_non_empty_line(text):
    for line in text.splitlines():
        if line.strip() != "":
            return line
    return ""

def contains_all_substrings(text, substrings):
    return all(s in text for s in substrings)

def is_int_but_not_bool(x):
    return isinstance(x, int) and not isinstance(x, bool)

def validate_summary(summary_data):
    # Returns tuple: (valid_array_and_length, items_have_required_fields_and_types, formula_valid, decisions_valid)
    if not isinstance(summary_data, list):
        return (False, False, False, False)
    if len(summary_data) < 3:
        return (False, False, False, False)

    fields_ok = True
    formula_ok = True
    decisions_ok = True

    for item in summary_data:
        # Must be dict
        if not isinstance(item, dict):
            fields_ok = False
            formula_ok = False
            decisions_ok = False
            break

        # Required integer fields
        req_int_fields = ["frequency_score", "time_cost_score", "skill_required_score", "risk_score", "priority_score"]
        for k in req_int_fields:
            if k not in item or not is_int_but_not_bool(item[k]):
                fields_ok = False

        # Decision field
        decision = item.get("decision", None)
        if not isinstance(decision, str) or decision not in ("proposed", "defer"):
            decisions_ok = False

        # Validate formula only if integer fields present
        if fields_ok:
            f = item["frequency_score"]
            t = item["time_cost_score"]
            s = item["skill_required_score"]
            r = item["risk_score"]
            p = item["priority_score"]
            expected = f * t * (4 - s) * (4 - r)
            if p != expected:
                formula_ok = False

    return (True, fields_ok, formula_ok, decisions_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to required output files
    proposals_path = os.path.join(output_dir, "autonomy", "proposals.md")
    tracking_path = os.path.join(output_dir, "autonomy", "tracking.md")
    rejected_path = os.path.join(output_dir, "autonomy", "rejected.md")
    weekly_path = os.path.join(output_dir, "autonomy", "report-weekly.md")
    summary_path = os.path.join(output_dir, "autonomy", "summary.json")

    checks = OrderedDict()

    # Initialize checks to False
    checks["proposals_exists"] = False
    checks["proposals_has_sections"] = False
    checks["proposals_sections_have_pilot_sentence"] = False
    checks["proposals_sections_have_safety_sentence"] = False
    checks["proposals_sections_have_question"] = False

    checks["tracking_exists"] = False
    checks["tracking_has_headings"] = False

    checks["rejected_exists"] = False
    checks["rejected_first_line_is_header_with_rejected"] = False

    checks["weekly_exists"] = False
    checks["weekly_has_required_labels"] = False

    checks["summary_exists"] = False
    checks["summary_is_array_and_len_ge_3"] = False
    checks["summary_items_have_required_int_fields"] = False
    checks["summary_items_priority_formula_valid"] = False
    checks["summary_items_decision_valid"] = False

    checks["no_home_paths_in_outputs"] = False

    # proposals.md checks
    proposals_text = None
    if os.path.isfile(proposals_path):
        checks["proposals_exists"] = True
        proposals_text = read_text(proposals_path)
        if proposals_text is not None:
            sections = parse_sections_by_heading(proposals_text, "Delegation opportunity")
            if len(sections) >= 3:
                checks["proposals_has_sections"] = True
                # All sections must include the required substrings
                pilot_sentence = "Pilot: First 5x I'll do it and tell you after."
                safety_sentence = "I will not act without your explicit approval."
                question = "Want to try?"

                # Evaluate per-section presence
                all_have_pilot = all(pilot_sentence in s for s in sections)
                all_have_safety = all(safety_sentence in s for s in sections)
                all_have_question = all(question in s for s in sections)

                checks["proposals_sections_have_pilot_sentence"] = all_have_pilot
                checks["proposals_sections_have_safety_sentence"] = all_have_safety
                checks["proposals_sections_have_question"] = all_have_question

    # tracking.md checks
    tracking_text = None
    if os.path.isfile(tracking_path):
        checks["tracking_exists"] = True
        tracking_text = read_text(tracking_path)
        if tracking_text is not None:
            has_delegated = "## Delegated" in tracking_text
            has_pilot_phase = "## Pilot Phase" in tracking_text
            checks["tracking_has_headings"] = has_delegated and has_pilot_phase

    # rejected.md checks
    rejected_text = None
    if os.path.isfile(rejected_path):
        checks["rejected_exists"] = True
        rejected_text = read_text(rejected_path)
        if rejected_text is not None:
            first_line = first_non_empty_line(rejected_text)
            # Must be a header line with '#' and contain 'Rejected'
            if first_line.strip().startswith("#") and re.search(r"rejected", first_line, flags=re.IGNORECASE):
                checks["rejected_first_line_is_header_with_rejected"] = True

    # weekly report checks
    weekly_text = None
    if os.path.isfile(weekly_path):
        checks["weekly_exists"] = True
        weekly_text = read_text(weekly_path)
        if weekly_text is not None:
            has_title = "Autonomy Report" in weekly_text
            has_fully_owned = "Fully owned:" in weekly_text
            has_in_pilot = "In pilot:" in weekly_text
            has_identified = "Identified:" in weekly_text
            has_reliability = "Reliability:" in weekly_text
            checks["weekly_has_required_labels"] = all(
                [has_title, has_fully_owned, has_in_pilot, has_identified, has_reliability]
            )

    # summary.json checks
    summary_text = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_text = read_text(summary_path)
        if summary_text is not None:
            try:
                data = json.loads(summary_text)
                arr_ok, fields_ok, formula_ok, decisions_ok = validate_summary(data)
                checks["summary_is_array_and_len_ge_3"] = arr_ok
                checks["summary_items_have_required_int_fields"] = fields_ok
                checks["summary_items_priority_formula_valid"] = formula_ok
                checks["summary_items_decision_valid"] = decisions_ok
            except Exception:
                # Keep defaults as False
                pass

    # No "~/" anywhere in any output file contents
    output_files = [proposals_path, tracking_path, rejected_path, weekly_path, summary_path]
    all_exist = all(os.path.isfile(p) for p in output_files)
    no_home_paths_flag = False
    if all_exist:
        no_home_paths_flag = True
        for p in output_files:
            content = read_text(p)
            if content is None or "~/" in content:
                no_home_paths_flag = False
                break
    checks["no_home_paths_in_outputs"] = no_home_paths_flag

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure the "no-op baseline": if no outputs exist at all under output/autonomy, reward is 0.0
    autonomy_dir = os.path.join(output_dir, "autonomy")
    outputs_present = any(os.path.isfile(os.path.join(autonomy_dir, f)) for f in ["proposals.md", "tracking.md", "rejected.md", "report-weekly.md", "summary.json"])
    if not outputs_present:
        reward = 0.0

    result = OrderedDict()
    result["reward"] = reward
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()