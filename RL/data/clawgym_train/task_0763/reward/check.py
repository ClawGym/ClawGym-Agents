import json
import os
import sys
import re

def read_text(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_initiative_yaml(fp):
    """
    Very simple YAML-like parser for top-level key: value pairs.
    Returns dict with lowercase keys, focusing on 'organization' and 'timeline'.
    """
    content = read_text(fp)
    data = {}
    if content is None:
        return data
    for line in content.splitlines():
        # Ignore comments and blank lines
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        # Only handle top-level simple key: value
        if ":" in line and not line.startswith((" ", "\t", "-")):
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            # Strip surrounding quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key.lower()] = val
    return data

def contains_case_insensitive(haystack, needle):
    if haystack is None or needle is None:
        return False
    return needle.lower() in haystack.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    team_json_path = os.path.join(output_dir, "team.json")
    squad_json_path = os.path.join(output_dir, "squad_report.json")
    squad_md_path = os.path.join(output_dir, "squad_report.md")
    plan_md_path = os.path.join(output_dir, "plan.md")
    rationale_txt_path = os.path.join(output_dir, "rationale.txt")

    # 1) team.json checks
    checks["team_json_exists"] = os.path.isfile(team_json_path)
    team_obj = None
    checks["team_json_valid"] = False
    checks["team_has_keys"] = False
    checks["team_security_is_sentinel_kestrel"] = False
    if checks["team_json_exists"]:
        team_obj = load_json(team_json_path)
        if isinstance(team_obj, dict):
            checks["team_json_valid"] = True
            needed_keys = {"builder", "security", "operator"}
            if needed_keys.issubset(set(team_obj.keys())):
                # Ensure all map to strings
                if all(isinstance(team_obj.get(k), str) for k in needed_keys):
                    checks["team_has_keys"] = True
                    if team_obj.get("security") == "Sentinel Kestrel":
                        checks["team_security_is_sentinel_kestrel"] = True

    # 2) squad_report.json checks
    checks["squad_json_exists"] = os.path.isfile(squad_json_path)
    squad_obj = None
    checks["squad_json_valid"] = False
    checks["squad_schema_ok"] = False
    checks["squad_preset_ok"] = False
    checks["squad_team_len_3"] = False
    checks["squad_team_has_security_sentinel"] = False
    checks["squad_next_action_present"] = False
    if checks["squad_json_exists"]:
        squad_obj = load_json(squad_json_path)
        if isinstance(squad_obj, dict):
            checks["squad_json_valid"] = True
            if squad_obj.get("schema_version") == "aoi.squad.report.v0.1":
                checks["squad_schema_ok"] = True
            run = squad_obj.get("run", {})
            if isinstance(run, dict) and run.get("preset") == "builder-security-operator":
                checks["squad_preset_ok"] = True
            team = squad_obj.get("team")
            if isinstance(team, list) and len(team) == 3:
                # verify each has nickname and role
                if all(isinstance(m, dict) and ("nickname" in m) and ("role" in m) for m in team):
                    checks["squad_team_len_3"] = True
                    for m in team:
                        if m.get("nickname") == "Sentinel Kestrel" and m.get("role") == "Sentinel":
                            checks["squad_team_has_security_sentinel"] = True
                            break
            synth = squad_obj.get("synthesis", {})
            if isinstance(synth, dict):
                next_actions = synth.get("next_actions")
                if isinstance(next_actions, list):
                    for a in next_actions:
                        if not isinstance(a, dict):
                            continue
                        if a.get("action") == "Review and refine outputs" and a.get("priority") == "P1":
                            checks["squad_next_action_present"] = True
                            break

    # 3) squad_report.md checks
    checks["squad_md_exists"] = os.path.isfile(squad_md_path)
    checks["squad_md_has_title"] = False
    checks["squad_md_has_preset"] = False
    checks["squad_md_mentions_sentinel"] = False
    if checks["squad_md_exists"]:
        md = read_text(squad_md_path) or ""
        if "AOI Squad Report" in md:
            checks["squad_md_has_title"] = True
        if "builder-security-operator" in md:
            checks["squad_md_has_preset"] = True
        if "Sentinel Kestrel" in md:
            checks["squad_md_mentions_sentinel"] = True

    # 4) plan.md checks
    checks["plan_md_exists"] = os.path.isfile(plan_md_path)
    checks["plan_has_exec_summary"] = False
    checks["plan_has_change_overview"] = False
    checks["plan_has_stakeholder_analysis"] = False
    checks["plan_has_communication_plan"] = False
    checks["plan_has_training_enablement"] = False
    checks["plan_has_resistance_mitigation"] = False
    checks["plan_has_rollout_strategy"] = False
    checks["plan_has_success_metrics"] = False
    checks["plan_has_risk_register"] = False
    checks["plan_has_timeline_milestones"] = False
    checks["plan_has_budget_estimate"] = False
    checks["plan_has_quick_reference_checklist"] = False
    checks["plan_has_appendix"] = False
    checks["plan_has_adkar"] = False
    checks["plan_mentions_org"] = False
    checks["plan_mentions_timeline_value"] = False

    plan_text = None
    if checks["plan_md_exists"]:
        plan_text = read_text(plan_md_path) or ""
        lt = plan_text.lower()

        # Section labels (case-insensitive allowed)
        if "executive summary" in lt:
            checks["plan_has_exec_summary"] = True
        if "1. change overview" in lt:
            checks["plan_has_change_overview"] = True
        if "2. stakeholder analysis" in lt:
            checks["plan_has_stakeholder_analysis"] = True
        if "3. communication plan" in lt:
            checks["plan_has_communication_plan"] = True
        if "4. training & enablement" in lt or "4. training and enablement" in lt:
            checks["plan_has_training_enablement"] = True
        if "5. resistance mitigation" in lt:
            checks["plan_has_resistance_mitigation"] = True
        if "6. rollout strategy" in lt:
            checks["plan_has_rollout_strategy"] = True
        if "7. success metrics" in lt or "7. success metrics & tracking" in lt:
            checks["plan_has_success_metrics"] = True
        if "8. risk register" in lt:
            checks["plan_has_risk_register"] = True
        if "9. timeline & milestones" in lt or "9. timeline and milestones" in lt:
            checks["plan_has_timeline_milestones"] = True
        if "10. budget estimate" in lt:
            checks["plan_has_budget_estimate"] = True
        if "quick-reference checklist" in lt:
            checks["plan_has_quick_reference_checklist"] = True
        if "appendix" in lt:
            checks["plan_has_appendix"] = True
        if "adkar" in lt:
            checks["plan_has_adkar"] = True

        # Initiative context check: organization name and timeline
        init_yaml_path = os.path.join(input_dir, "initiative.yaml")
        init = parse_initiative_yaml(init_yaml_path)
        org = init.get("organization")
        timeline_value = init.get("timeline")
        if org:
            if org in plan_text:
                checks["plan_mentions_org"] = True
        if timeline_value:
            if timeline_value in plan_text:
                checks["plan_mentions_timeline_value"] = True

    # 5) rationale.txt checks
    checks["rationale_exists"] = os.path.isfile(rationale_txt_path)
    checks["rationale_min_len"] = False
    checks["rationale_mentions_preset"] = False
    checks["rationale_mentions_security_term"] = False
    checks["rationale_mentions_sentinel"] = False
    if checks["rationale_exists"]:
        rtxt = read_text(rationale_txt_path) or ""
        if len(rtxt) >= 300:
            checks["rationale_min_len"] = True
        if "builder-security-operator" in rtxt:
            checks["rationale_mentions_preset"] = True
        # term "security" (case-insensitive acceptable)
        if contains_case_insensitive(rtxt, "security"):
            checks["rationale_mentions_security_term"] = True
        if "Sentinel Kestrel" in rtxt:
            checks["rationale_mentions_sentinel"] = True

    # Compute reward as average of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward in [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()