import json
import os
import re
import sys
from typing import Any, Dict, List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_bool(v: Any) -> bool:
    return isinstance(v, bool)

def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)

def word_count(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])

def has_abs_path_token(s: str) -> bool:
    # Detect absolute path tokens beginning with "/" separated by whitespace or start of string
    # Allow none; enforce relative-only commands.
    # If any token starts with "/" (e.g., "/root", "/usr", "/input", etc.), flag it.
    pattern = re.compile(r"(^|[\s;|&])/[^\s]*")
    return bool(pattern.search(s))

def extract_decision(text: str) -> str:
    # Find the first line starting with "Decision:"
    for line in text.splitlines():
        if line.strip().lower().startswith("decision:"):
            return line.split(":", 1)[1].strip()
    return ""

def csv_parse_lines(text: str) -> List[List[str]]:
    # Simple CSV split by commas, not handling quotes heavily (expected simple content)
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    parsed = []
    for ln in lines:
        # Split preserving empty columns
        parts = [p.strip() for p in ln.split(",")]
        parsed.append(parts)
    return parsed

def contains_currency_amounts(text: str, min_count: int = 2) -> bool:
    # Currency regex: $ followed by digit and digits/commas
    matches = re.findall(r"\$[0-9][0-9,]*", text)
    return len(matches) >= min_count

def contains_any_limits(text: str) -> bool:
    # Check for any of 23500, 31000, 70000, 4300, 8550 with optional commas
    # Build patterns to match numbers with optional comma grouping
    targets = ["23500", "31000", "70000", "4300", "8550"]
    for t in targets:
        # Allow comma anywhere appropriate: e.g., 23,500 or 70,000
        if len(t) > 3:
            # Insert optional comma before last three digits
            pat = re.escape(t[:-3]) + r",?" + re.escape(t[-3:])
        else:
            pat = re.escape(t)
        if re.search(r"\b" + pat + r"\b", text):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Initialize all checks to False
    # 1) agent_session_plan.json checks
    checks["plan_exists_and_valid_json"] = False
    checks["plan_has_actions_array_ge_6"] = False
    checks["plan_actions_have_min_fields"] = False
    checks["plan_has_add_with_worktree_sandbox_yolo_launch_group_hier"] = False
    checks["plan_has_lifecycle_action_start_stop_restart"] = False
    checks["plan_has_capture_action"] = False
    checks["plan_has_group_change_action"] = False
    checks["plan_has_non_default_profile_action"] = False
    checks["plan_commands_preview_no_abs_paths"] = False

    # 2) security_vetting_report.md checks
    checks["vetting_report_exists"] = False
    checks["vetting_has_sections_all"] = False
    checks["vetting_has_critical_signals_phrase"] = False
    checks["vetting_rejects_if_input_has_danger_signals"] = False

    # 3) benefits_recommendations.md checks
    checks["benefits_recs_exists"] = False
    checks["benefits_recs_has_currency_amounts_two_plus"] = False
    checks["benefits_recs_has_2026_limits_number"] = False
    checks["benefits_recs_mentions_company_state"] = False

    # 4) benefits_compliance_calendar.csv checks
    checks["compliance_calendar_exists"] = False
    checks["compliance_calendar_header_ok"] = False
    checks["compliance_calendar_rows_ge_12"] = False
    checks["compliance_calendar_has_ACA"] = False
    checks["compliance_calendar_has_Form5500"] = False
    checks["compliance_calendar_has_SafeHarbor"] = False

    # 5) adversarial_notes.txt checks
    checks["adversarial_notes_exists"] = False
    checks["adversarial_notes_wordcount_ge_200"] = False
    checks["adversarial_notes_has_required_terms"] = False

    # 6) run_summary.json consistency checks
    checks["run_summary_exists"] = False
    checks["run_summary_has_required_keys"] = False
    checks["run_summary_session_actions_count_matches"] = False
    checks["run_summary_has_compliance_12_months_consistent"] = False
    checks["run_summary_vetting_decision_matches"] = False

    # Paths
    plan_path = os.path.join(output_dir, "agent_session_plan.json")
    vetting_path = os.path.join(output_dir, "security_vetting_report.md")
    benefits_recs_path = os.path.join(output_dir, "benefits_recommendations.md")
    calendar_path = os.path.join(output_dir, "benefits_compliance_calendar.csv")
    notes_path = os.path.join(output_dir, "adversarial_notes.txt")
    summary_path = os.path.join(output_dir, "run_summary.json")

    # Load inputs where needed
    skill_candidate_path = os.path.join(input_dir, "skill_candidate.py")
    company_profile_path = os.path.join(input_dir, "company_profile.json")

    # 1) Agent session plan
    actions: List[Dict[str, Any]] = []
    plan = read_json(plan_path)
    if isinstance(plan, dict):
        checks["plan_exists_and_valid_json"] = True
        actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
        if isinstance(actions, list) and len(actions) >= 6:
            checks["plan_has_actions_array_ge_6"] = True

        # Min fields check and commands absolute paths rule
        min_fields_ok = True
        no_abs_paths = True
        for a in actions:
            if not (isinstance(a, dict) and isinstance(a.get("action"), str) and isinstance(a.get("target"), str) and isinstance(a.get("commands_preview"), str)):
                min_fields_ok = False
            else:
                if has_abs_path_token(a.get("commands_preview", "")):
                    no_abs_paths = False
        if min_fields_ok and len(actions) > 0:
            checks["plan_actions_have_min_fields"] = True
        if no_abs_paths and len(actions) > 0:
            checks["plan_commands_preview_no_abs_paths"] = True

        # Specific action presence checks
        # add with group having "/" and worktree and sandbox true, yolo true, launch true
        add_ok = False
        lifecycle_ok = False
        capture_ok = False
        group_change_ok = False
        non_default_profile_ok = False

        for a in actions:
            if isinstance(a, dict):
                act = a.get("action")
                if act == "add":
                    group = a.get("group")
                    worktree = a.get("worktree")
                    sandbox = a.get("sandbox")
                    yolo = a.get("yolo")
                    launch = a.get("launch")
                    if isinstance(group, str) and "/" in group and isinstance(worktree, str) and worktree != "" and sandbox is True and yolo is True and launch is True:
                        add_ok = True
                if act in ("start", "stop", "restart"):
                    lifecycle_ok = True
                if act == "capture":
                    capture_ok = True
                if act in ("rename", "move_group"):
                    group_change_ok = True
                # Non-default profile action: profile exists and != "default"
                if "profile" in a and isinstance(a.get("profile"), str) and a.get("profile").strip().lower() != "default":
                    non_default_profile_ok = True

        if add_ok:
            checks["plan_has_add_with_worktree_sandbox_yolo_launch_group_hier"] = True
        if lifecycle_ok:
            checks["plan_has_lifecycle_action_start_stop_restart"] = True
        if capture_ok:
            checks["plan_has_capture_action"] = True
        if group_change_ok:
            checks["plan_has_group_change_action"] = True
        if non_default_profile_ok:
            checks["plan_has_non_default_profile_action"] = True

    # 2) Security vetting report
    vetting_text = ""
    skill_text = read_text(skill_candidate_path)
    if os.path.isfile(vetting_path):
        checks["vetting_report_exists"] = True
        vetting_text = read_text(vetting_path)
        # Required sections
        required_sections = [
            "Skill Information",
            "Source Reputation",
            "Static Code Analysis",
            "Permission Scope",
            "Dependency Chain",
            "Behavioral Intent",
            "Risk Scoring",
            "Decision",
            "Reviewer Notes",
            "Audit Trail",
        ]
        lower_report = vetting_text.lower()
        sections_ok = all(sec.lower() in lower_report for sec in required_sections)
        if sections_ok:
            checks["vetting_has_sections_all"] = True

        if "critical signals" in lower_report:
            checks["vetting_has_critical_signals_phrase"] = True

        # If input contains danger patterns, decision must be Reject
        danger_patterns = [
            "base64",
            "aws_secret_access_key",
            "curl",
            "wget",
            "eval(",
            "exec(",
            "~/.ssh",
        ]
        input_has_danger = False
        skill_lower = skill_text.lower()
        for pat in danger_patterns:
            if pat in skill_lower:
                input_has_danger = True
                break
        if input_has_danger:
            dec = extract_decision(vetting_text)
            if dec.strip().lower().find("reject") != -1:
                checks["vetting_rejects_if_input_has_danger_signals"] = True
        else:
            # If no danger, do not set this check to True (remains False), as it's conditioned on presence
            pass

    # 3) Benefits recommendations
    if os.path.isfile(benefits_recs_path):
        checks["benefits_recs_exists"] = True
        recs_text = read_text(benefits_recs_path)

        if contains_currency_amounts(recs_text, min_count=2):
            checks["benefits_recs_has_currency_amounts_two_plus"] = True

        if contains_any_limits(recs_text):
            checks["benefits_recs_has_2026_limits_number"] = True

        # Mention at least one state from company_profile.json
        states = []
        company = read_json(company_profile_path)
        if isinstance(company, dict):
            st = company.get("states")
            if isinstance(st, list):
                for s in st:
                    if isinstance(s, str) and re.fullmatch(r"[A-Z]{2}", s.strip()):
                        states.append(s.strip())
        mention_ok = False
        for s in states:
            # word boundary search
            if re.search(r"\b" + re.escape(s) + r"\b", recs_text):
                mention_ok = True
                break
        if mention_ok:
            checks["benefits_recs_mentions_company_state"] = True

    # 4) Compliance calendar
    calendar_text = ""
    if os.path.isfile(calendar_path):
        checks["compliance_calendar_exists"] = True
        calendar_text = read_text(calendar_path)
        parsed = csv_parse_lines(calendar_text)
        if parsed:
            header = parsed[0]
            if header == ["Month", "Task", "Owner", "DueDate"]:
                checks["compliance_calendar_header_ok"] = True
            # data rows are lines after header
            data_rows = parsed[1:] if len(parsed) > 1 else []
            if len(data_rows) >= 12:
                checks["compliance_calendar_rows_ge_12"] = True
            # scan tasks for substrings
            has_aca = False
            has_form = False
            has_sh = False
            for row in data_rows:
                if len(row) >= 2:
                    task = row[1]
                    tl = task.lower()
                    if "aca" in tl:
                        has_aca = True
                    if "form 5500" in tl:
                        has_form = True
                    if "safe harbor" in tl:
                        has_sh = True
            if has_aca:
                checks["compliance_calendar_has_ACA"] = True
            if has_form:
                checks["compliance_calendar_has_Form5500"] = True
            if has_sh:
                checks["compliance_calendar_has_SafeHarbor"] = True

    # 5) Adversarial notes
    if os.path.isfile(notes_path):
        checks["adversarial_notes_exists"] = True
        notes_text = read_text(notes_path)
        if word_count(notes_text) >= 200:
            checks["adversarial_notes_wordcount_ge_200"] = True
        # Must include Security, Patterns, Debugging, Performance (case-insensitive)
        needed = ["security", "patterns", "debugging", "performance"]
        ntl = notes_text.lower()
        if all(word in ntl for word in needed):
            checks["adversarial_notes_has_required_terms"] = True

    # 6) Run summary
    summary = read_json(summary_path)
    if isinstance(summary, dict):
        checks["run_summary_exists"] = True
        required_keys = [
            "agent_session_plan",
            "vetting_report",
            "benefits_recommendations",
            "compliance_calendar",
            "adversarial_notes",
            "session_actions_count",
            "has_compliance_12_months",
            "vetting_decision",
        ]
        # Validate existence and types
        has_all = all(k in summary for k in required_keys)
        types_ok = (
            isinstance(summary.get("agent_session_plan"), str)
            and isinstance(summary.get("vetting_report"), str)
            and isinstance(summary.get("benefits_recommendations"), str)
            and isinstance(summary.get("compliance_calendar"), str)
            and isinstance(summary.get("adversarial_notes"), str)
            and is_int(summary.get("session_actions_count"))
            and is_bool(summary.get("has_compliance_12_months"))
            and isinstance(summary.get("vetting_decision"), str)
        )
        if has_all and types_ok:
            checks["run_summary_has_required_keys"] = True

        # session_actions_count matches
        if isinstance(actions, list) and is_int(summary.get("session_actions_count")):
            if summary.get("session_actions_count") == len(actions):
                checks["run_summary_session_actions_count_matches"] = True

        # has_compliance_12_months consistent with calendar
        if isinstance(summary.get("has_compliance_12_months"), bool):
            calendar_rows_ge_12 = checks["compliance_calendar_rows_ge_12"]
            if bool(summary.get("has_compliance_12_months")) == bool(calendar_rows_ge_12):
                checks["run_summary_has_compliance_12_months_consistent"] = True

        # vetting decision matches the Decision line in report
        report_decision = extract_decision(vetting_text).strip().lower()
        summary_decision = summary.get("vetting_decision", "").strip().lower() if isinstance(summary.get("vetting_decision"), str) else ""
        if report_decision != "" and summary_decision == report_decision:
            checks["run_summary_vetting_decision_matches"] = True

    # Compute reward as average of checks that are True
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output directory missing or empty of all required artifacts, force 0.0
    required_artifacts = [plan_path, vetting_path, benefits_recs_path, calendar_path, notes_path, summary_path]
    if not os.path.isdir(output_dir) or not any(os.path.isfile(p) for p in required_artifacts):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()