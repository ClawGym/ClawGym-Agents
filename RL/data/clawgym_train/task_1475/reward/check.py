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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def file_non_empty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def last_non_empty_line(text):
    if text is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) backlink_report.md checks
    report_path = os.path.join(output_dir, "backlink_report.md")
    report_exists = os.path.isfile(report_path)
    checks["report_exists"] = report_exists
    report_nonempty = file_non_empty(report_path)
    checks["report_non_empty"] = report_nonempty

    report_content = read_text(report_path) if report_exists else None

    def content_has(sub):
        return bool(report_content and (sub in report_content))

    checks["report_has_domain"] = content_has("acmeanalytics.com")
    checks["report_has_analysis_date"] = content_has("Analysis Date")
    checks["report_has_section_profile_overview"] = content_has("## Backlink Profile Overview")
    checks["report_has_section_link_quality"] = content_has("## Link Quality Analysis")
    checks["report_has_section_toxic"] = content_has("## Toxic Link Analysis")
    checks["report_has_section_competitive"] = content_has("## Competitive Backlink Analysis")
    checks["report_has_section_opportunities"] = content_has("## Link Building Opportunities")
    checks["report_has_section_change_tracking"] = content_has("## Link Change Tracking")
    checks["report_has_section_report_header"] = content_has("Backlink Analysis Report")
    checks["report_has_profile_health_score_text"] = content_has("Profile Health Score")
    checks["report_has_link_intersection_text"] = content_has("Link Intersection")
    checks["report_has_priority_matrix_text"] = content_has("Priority Matrix")
    checks["report_has_toxic_score_text"] = content_has("Toxic Score")
    checks["report_has_disavow_text"] = content_has("Disavow")

    # Complexity Assessment line containing emoji 🧠 or 🧠🔥 (checking for 🧠 covers both)
    complexity_ok = False
    if report_content:
        for line in report_content.splitlines():
            if "Complexity Assessment" in line and "🧠" in line:
                complexity_ok = True
                break
    checks["report_has_complexity_assessment_line_with_emoji"] = complexity_ok

    # If report file missing, dependent checks should remain False
    if not report_exists:
        for key in list(checks.keys()):
            if key.startswith("report_") and key not in ("report_exists",):
                checks[key] = False
    if report_exists and not report_nonempty:
        for key in list(checks.keys()):
            if key.startswith("report_") and key not in ("report_exists", "report_non_empty"):
                checks[key] = False

    # 2) disavow.txt checks
    disavow_path = os.path.join(output_dir, "disavow.txt")
    disavow_exists = os.path.isfile(disavow_path)
    checks["disavow_exists"] = disavow_exists
    disavow_nonempty = file_non_empty(disavow_path)
    checks["disavow_non_empty"] = disavow_nonempty

    disavow_has_two_domain_entries = False
    if disavow_exists and disavow_nonempty:
        content = read_text(disavow_path) or ""
        lines = content.splitlines()
        count = 0
        for ln in lines:
            if re.match(r'^domain:', ln):
                count += 1
        disavow_has_two_domain_entries = count >= 2
    checks["disavow_has_two_domain_entries"] = disavow_has_two_domain_entries

    if not disavow_exists:
        checks["disavow_non_empty"] = False
        checks["disavow_has_two_domain_entries"] = False
    if disavow_exists and not disavow_nonempty:
        checks["disavow_has_two_domain_entries"] = False

    # 3) opportunities_backlog.json checks
    opp_path = os.path.join(output_dir, "opportunities_backlog.json")
    opp_exists = os.path.isfile(opp_path)
    checks["opp_exists"] = opp_exists
    opp_data = read_json(opp_path) if opp_exists else None
    checks["opp_valid_json"] = opp_data is not None

    opp_is_array_len_5_10 = False
    opp_items_have_required_keys = False
    opp_items_story_starts = False
    opp_items_points_valid = False
    opp_items_acceptance_valid = False

    if isinstance(opp_data, list):
        length_ok = 5 <= len(opp_data) <= 10
        opp_is_array_len_5_10 = length_ok

        required_keys = {"id", "title", "story", "acceptance_criteria", "points", "priority"}
        items_have_keys = True
        story_starts_ok = True
        points_ok = True
        ac_ok = True

        for item in opp_data:
            if not isinstance(item, dict):
                items_have_keys = False
                story_starts_ok = False
                points_ok = False
                ac_ok = False
                break
            if not required_keys.issubset(item.keys()):
                items_have_keys = False
            story = item.get("story")
            if not (isinstance(story, str) and story.startswith("As a")):
                story_starts_ok = False
            points = item.get("points")
            if points not in {1, 2, 3, 5, 8}:
                points_ok = False
            # acceptance criteria
            ac = item.get("acceptance_criteria")
            if not (isinstance(ac, list) and len(ac) >= 4):
                ac_ok = False
            else:
                # At least one entry starts with "Given"
                has_given = any(isinstance(c, str) and c.startswith("Given") for c in ac)
                if not has_given:
                    ac_ok = False

        opp_items_have_required_keys = items_have_keys and len(opp_data) > 0
        opp_items_story_starts = story_starts_ok and len(opp_data) > 0
        opp_items_points_valid = points_ok and len(opp_data) > 0
        opp_items_acceptance_valid = ac_ok and len(opp_data) > 0

    checks["opp_is_array_len_5_10"] = opp_is_array_len_5_10
    checks["opp_items_have_required_keys"] = opp_items_have_required_keys
    checks["opp_items_story_starts_with_As_a"] = opp_items_story_starts
    checks["opp_items_points_valid"] = opp_items_points_valid
    checks["opp_items_acceptance_criteria_valid"] = opp_items_acceptance_valid

    if not opp_exists:
        checks["opp_valid_json"] = False
        checks["opp_is_array_len_5_10"] = False
        checks["opp_items_have_required_keys"] = False
        checks["opp_items_story_starts_with_As_a"] = False
        checks["opp_items_points_valid"] = False
        checks["opp_items_acceptance_criteria_valid"] = False
    elif opp_exists and opp_data is None:
        checks["opp_is_array_len_5_10"] = False
        checks["opp_items_have_required_keys"] = False
        checks["opp_items_story_starts_with_As_a"] = False
        checks["opp_items_points_valid"] = False
        checks["opp_items_acceptance_criteria_valid"] = False

    # 4) sprint_plan.md checks
    sprint_path = os.path.join(output_dir, "sprint_plan.md")
    sprint_exists = os.path.isfile(sprint_path)
    checks["sprint_exists"] = sprint_exists
    sprint_nonempty = file_non_empty(sprint_path)
    checks["sprint_non_empty"] = sprint_nonempty

    sprint_has_capacity_27_line = False
    sprint_committed_points_leq_23 = False
    sprint_stretch_points_leq_4 = False

    if sprint_exists and sprint_nonempty:
        sprint_content = read_text(sprint_path) or ""
        if re.search(r'Capacity:\s*27\b', sprint_content):
            sprint_has_capacity_27_line = True
        m_committed = re.search(r'Committed points:\s*(\d+)', sprint_content)
        if m_committed:
            try:
                committed_val = int(m_committed.group(1))
                if committed_val <= 23:
                    sprint_committed_points_leq_23 = True
            except Exception:
                sprint_committed_points_leq_23 = False
        m_stretch = re.search(r'Stretch points:\s*(\d+)', sprint_content)
        if m_stretch:
            try:
                stretch_val = int(m_stretch.group(1))
                if stretch_val <= 4:
                    sprint_stretch_points_leq_4 = True
            except Exception:
                sprint_stretch_points_leq_4 = False

    checks["sprint_has_capacity_27_line"] = sprint_has_capacity_27_line
    checks["sprint_committed_points_leq_23"] = sprint_committed_points_leq_23
    checks["sprint_stretch_points_leq_4"] = sprint_stretch_points_leq_4

    if not sprint_exists:
        checks["sprint_non_empty"] = False
        checks["sprint_has_capacity_27_line"] = False
        checks["sprint_committed_points_leq_23"] = False
        checks["sprint_stretch_points_leq_4"] = False
    elif sprint_exists and not sprint_nonempty:
        checks["sprint_has_capacity_27_line"] = False
        checks["sprint_committed_points_leq_23"] = False
        checks["sprint_stretch_points_leq_4"] = False

    # 5) security_audit.json checks
    audit_path = os.path.join(output_dir, "security_audit.json")
    audit_exists = os.path.isfile(audit_path)
    checks["audit_exists"] = audit_exists
    audit_data = read_json(audit_path) if audit_exists else None
    checks["audit_valid_json"] = audit_data is not None

    required_audit_keys = [
        "risk_level",
        "overall_score",
        "vulnerabilities",
        "vulnerability_count",
        "best_practices_compliance",
        "action_recommended",
        "safe_to_deploy",
        "audit_timestamp",
    ]
    audit_has_required_keys = False
    audit_vulns_nonempty = False
    audit_risk_level_valid = False
    audit_bpc_valid = False
    audit_safe_bool = False

    if isinstance(audit_data, dict):
        audit_has_required_keys = all(k in audit_data for k in required_audit_keys)
        vulns = audit_data.get("vulnerabilities")
        if isinstance(vulns, list) and len(vulns) > 0:
            audit_vulns_nonempty = True
        rl = audit_data.get("risk_level")
        if isinstance(rl, str) and rl.upper() in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            audit_risk_level_valid = True
        bpc = audit_data.get("best_practices_compliance")
        if isinstance(bpc, (int, float)) and (0.0 <= float(bpc) <= 1.0):
            audit_bpc_valid = True
        std = audit_data.get("safe_to_deploy")
        if isinstance(std, bool):
            audit_safe_bool = True

    checks["audit_has_required_keys"] = audit_has_required_keys
    checks["audit_vulnerabilities_non_empty"] = audit_vulns_nonempty
    checks["audit_risk_level_valid"] = audit_risk_level_valid
    checks["audit_bpc_valid"] = audit_bpc_valid
    checks["audit_safe_to_deploy_boolean"] = audit_safe_bool

    if not audit_exists:
        checks["audit_valid_json"] = False
        checks["audit_has_required_keys"] = False
        checks["audit_vulnerabilities_non_empty"] = False
        checks["audit_risk_level_valid"] = False
        checks["audit_bpc_valid"] = False
        checks["audit_safe_to_deploy_boolean"] = False
    elif audit_exists and audit_data is None:
        checks["audit_has_required_keys"] = False
        checks["audit_vulnerabilities_non_empty"] = False
        checks["audit_risk_level_valid"] = False
        checks["audit_bpc_valid"] = False
        checks["audit_safe_to_deploy_boolean"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()