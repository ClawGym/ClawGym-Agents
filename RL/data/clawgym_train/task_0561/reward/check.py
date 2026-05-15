import json
import os
import re
import sys

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def find_section_bounds(text, start_key, end_keys):
    """
    Find a section in text that starts at the first occurrence of start_key (case-insensitive)
    and ends at the next occurrence of any of end_keys (case-insensitive). If no end found,
    returns end of text.
    Returns (start_index, end_index) or (None, None) if start not found.
    """
    if not text:
        return (None, None)
    low = text.lower()
    sk = start_key.lower()
    start = low.find(sk)
    if start == -1:
        return (None, None)
    # Start from the end of the matched key to include content after header/title
    start_index = start + len(sk)
    # Find next end key
    end_index = len(text)
    for ek in end_keys:
        pos = low.find(ek.lower(), start_index)
        if pos != -1 and pos < end_index:
            end_index = pos
    return (start_index, end_index)

def line_has_allowed_value(lines, prefix_lower, allowed_values):
    """
    Search for a line that contains prefix_lower (already lower-cased for comparison),
    then check if any allowed value appears in that same line (case-insensitive).
    """
    for line in lines:
        ll = line.lower()
        if prefix_lower in ll:
            for val in allowed_values:
                if val.lower() in ll:
                    return True
    return False

def line_has_allowed_exact_verdict(lines, prefix_lower, allowed_values):
    """
    Similar to line_has_allowed_value, but ensures the allowed verdict string appears
    in the same line as the 'VERDICT:' label. We still do a substring check for the exact
    allowed phrase (case-sensitive to keep the phrase exact), but we accept if found anywhere
    on that line after the prefix presence.
    """
    for line in lines:
        if prefix_lower in line.lower():
            for val in allowed_values:
                if val in line:
                    return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all checks defaulting to False
    checks = {}

    # Paths
    brief_path = os.path.join(output_dir, "BRIEF.md")
    report_path = os.path.join(output_dir, "VETTING_REPORT.md")
    handoff_path = os.path.join(output_dir, "HANDOFF.md")
    eval_path = os.path.join(output_dir, "EVALUATION.md")
    decision_path = os.path.join(output_dir, "DECISION.md")

    # ---------- BRIEF.md checks ----------
    brief_exists = os.path.isfile(brief_path)
    checks["brief_exists"] = brief_exists

    brief_content = read_file(brief_path) if brief_exists else None
    if brief_content:
        low = brief_content.lower()
        checks["brief_has_background"] = "background" in low
        checks["brief_has_objective"] = "objective" in low
        checks["brief_has_sprint_contract"] = "sprint contract" in low
        checks["brief_has_related_files"] = "related files" in low
        checks["brief_has_constraints"] = "constraints" in low
        checks["brief_has_handoff_requirements"] = "handoff requirements" in low

        # Extract Sprint Contract section
        sc_start, sc_end = find_section_bounds(
            brief_content,
            "Sprint Contract",
            ["## ", "### ", "Related Files", "Constraints", "Handoff Requirements", "Background", "Objective"]
        )
        sc_text = brief_content[sc_start:sc_end] if sc_start is not None else ""
        sc_low = sc_text.lower() if sc_text else ""

        # Count checkbox items "- [ ]"
        checks["brief_sc_has_four_checkboxes"] = sc_text.count("- [ ]") >= 4

        # Mention requirements
        checks["brief_sc_mentions_red_flags"] = "red flags" in sc_low
        checks["brief_sc_mentions_permissions"] = "permission" in sc_low
        checks["brief_sc_mentions_risk_level"] = "risk level" in sc_low
        checks["brief_sc_mentions_verdict"] = "verdict" in sc_low
    else:
        # If brief missing, dependent checks remain False by default
        checks.setdefault("brief_has_background", False)
        checks.setdefault("brief_has_objective", False)
        checks.setdefault("brief_has_sprint_contract", False)
        checks.setdefault("brief_has_related_files", False)
        checks.setdefault("brief_has_constraints", False)
        checks.setdefault("brief_has_handoff_requirements", False)
        checks.setdefault("brief_sc_has_four_checkboxes", False)
        checks.setdefault("brief_sc_mentions_red_flags", False)
        checks.setdefault("brief_sc_mentions_permissions", False)
        checks.setdefault("brief_sc_mentions_risk_level", False)
        checks.setdefault("brief_sc_mentions_verdict", False)

    # ---------- VETTING_REPORT.md checks ----------
    report_exists = os.path.isfile(report_path)
    checks["report_exists"] = report_exists

    report_content = read_file(report_path) if report_exists else None
    if report_content:
        rlow = report_content.lower()
        checks["report_has_title"] = "skill vetting report" in rlow

        # Skill, Author/Owner, Version
        has_skill_field = "skill:" in rlow
        has_author_or_owner = ("author:" in rlow) or ("owner:" in rlow)
        has_version = "version" in rlow
        checks["report_has_skill_author_owner_version"] = bool(has_skill_field and has_author_or_owner and has_version)

        # Metrics referencing downloads/stars/updated_at
        metrics_hit = any(token in rlow for token in ["downloads", "stars", "updated_at"])
        checks["report_has_metrics"] = metrics_hit

        # RED FLAGS section token presence
        rf_start, rf_end = find_section_bounds(
            report_content,
            "RED FLAGS",
            [
                "PERMISSIONS NEEDED", "PERMISSIONS", "RISK LEVEL", "VERDICT", "EVALUATION",
                "NOTES", "METRICS", "KNOWN ISSUES", "WHAT WAS DONE", "PERMISSIONS:"
            ]
        )
        rf_text = report_content[rf_start:rf_end] if rf_start is not None else ""
        red_flag_tokens = ["~/.ssh", "~/.aws", "eval", "base64", "198.51.100.10"]
        rf_hit = False
        if rf_text:
            for tok in red_flag_tokens:
                if tok.lower() in rf_text.lower():
                    rf_hit = True
                    break
        checks["report_red_flags_token"] = rf_hit

        # PERMISSIONS NEEDED section with Files/Network/Commands labels
        pn_start, pn_end = find_section_bounds(
            report_content,
            "PERMISSIONS NEEDED",
            ["RISK LEVEL", "VERDICT", "RED FLAGS", "NOTES", "EVALUATION", "DECISION", "METRICS"]
        )
        pn_text = report_content[pn_start:pn_end] if pn_start is not None else ""
        pn_low = pn_text.lower() if pn_text else ""
        checks["report_permissions_needed_has_files_network_commands"] = all(
            label in pn_low for label in ["files:", "network:", "commands:"]
        )

        # RISK LEVEL line
        lines = report_content.splitlines()
        allowed_risk = ["LOW", "MEDIUM", "HIGH", "EXTREME"]
        checks["report_has_risk_level_line_with_category"] = line_has_allowed_value(lines, "risk level:", allowed_risk)

        # VERDICT line with allowed verdict
        allowed_verdicts = ["SAFE TO INSTALL", "INSTALL WITH CAUTION", "DO NOT INSTALL"]
        checks["report_has_verdict_line_with_allowed"] = line_has_allowed_exact_verdict(lines, "verdict:", allowed_verdicts)

    else:
        checks.setdefault("report_has_title", False)
        checks.setdefault("report_has_skill_author_owner_version", False)
        checks.setdefault("report_has_metrics", False)
        checks.setdefault("report_red_flags_token", False)
        checks.setdefault("report_permissions_needed_has_files_network_commands", False)
        checks.setdefault("report_has_risk_level_line_with_category", False)
        checks.setdefault("report_has_verdict_line_with_allowed", False)

    # ---------- HANDOFF.md checks ----------
    handoff_exists = os.path.isfile(handoff_path)
    checks["handoff_exists"] = handoff_exists

    handoff_content = read_file(handoff_path) if handoff_exists else None
    if handoff_content:
        hlow = handoff_content.lower()
        checks["handoff_has_what_was_done"] = "what was done" in hlow
        # Ensure VETTING_REPORT.md is mentioned (file change list should include it)
        checks["handoff_lists_vetting_report"] = "vetting_report.md".lower() in hlow
        checks["handoff_has_design_decisions"] = "design decisions" in hlow
        checks["handoff_has_known_issues"] = "known issues" in hlow
    else:
        checks.setdefault("handoff_has_what_was_done", False)
        checks.setdefault("handoff_lists_vetting_report", False)
        checks.setdefault("handoff_has_design_decisions", False)
        checks.setdefault("handoff_has_known_issues", False)

    # ---------- EVALUATION.md checks ----------
    evaluation_exists = os.path.isfile(eval_path)
    checks["evaluation_exists"] = evaluation_exists

    evaluation_content = read_file(eval_path) if evaluation_exists else None
    if evaluation_content:
        elow = evaluation_content.lower()
        checks["evaluation_has_skeptical_line"] = "your job is to find problems, not to praise." in elow
        # At least one occurrence of Pass or Fail
        checks["evaluation_has_pass_fail"] = ("pass" in elow) or ("fail" in elow)
        # Refer to criterion or criteria
        checks["evaluation_mentions_criterion"] = ("criterion" in elow) or ("criteria" in elow)
    else:
        checks.setdefault("evaluation_has_skeptical_line", False)
        checks.setdefault("evaluation_has_pass_fail", False)
        checks.setdefault("evaluation_mentions_criterion", False)

    # ---------- DECISION.md checks ----------
    decision_exists = os.path.isfile(decision_path)
    checks["decision_exists"] = decision_exists

    decision_content = read_file(decision_path) if decision_exists else None
    if decision_content:
        dlow = decision_content.lower()
        # Gate decision contains one of ship, fix, escalate as a whole word
        checks["decision_has_gate_decision"] = bool(re.search(r"\b(ship|fix|escalate)\b", dlow))
        dlines = decision_content.splitlines()
        allowed_verdicts = ["SAFE TO INSTALL", "INSTALL WITH CAUTION", "DO NOT INSTALL"]
        checks["decision_has_verdict_line_with_allowed"] = line_has_allowed_exact_verdict(dlines, "verdict:", allowed_verdicts)
    else:
        checks.setdefault("decision_has_gate_decision", False)
        checks.setdefault("decision_has_verdict_line_with_allowed", False)

    # Compute reward as the fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory is missing or empty or no required artifacts, ensure reward is 0.0
    required_any = brief_exists or report_exists or handoff_exists or evaluation_exists or decision_exists
    if not required_any:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()