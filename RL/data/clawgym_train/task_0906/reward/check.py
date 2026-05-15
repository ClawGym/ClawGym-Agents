import json
import os
import sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # automation_audit.json checks
        "audit_exists": False,
        "audit_valid_json": False,
        "audit_has_tasks_array": False,
        "audit_len_ge_6": False,
        "audit_tasks_fields_valid": False,
        "audit_time_cost_formula_ok": False,
        "audit_sorted_desc": False,
        "audit_at_least_3_ge_3h": False,

        # workflows.json checks
        "workflows_exists": False,
        "workflows_valid_json": False,
        "workflows_array_len_ge_3": False,
        "workflows_each_has_required_keys": False,
        "workflows_platform_category_valid_for_all": False,
        "workflows_actions_len_2_to_5_all": False,
        "workflows_roi_fields_numeric_and_payback_ok": False,
        "workflows_has_simple_mvp": False,

        # monitoring_plan.md checks
        "monitoring_exists_nonempty": False,
        "monitoring_contains_phrases": False,

        # checklist.txt checks
        "checklist_exists": False,
        "checklist_has_required_bullets": False,
    }

    # 1) automation_audit.json
    audit_path = os.path.join(output_dir, "automation_audit.json")
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        audit_data, audit_err = read_json_file(audit_path)
        if audit_data is not None and isinstance(audit_data, dict):
            checks["audit_valid_json"] = True
            tasks = audit_data.get("tasks")
            if isinstance(tasks, list):
                checks["audit_has_tasks_array"] = True
                if len(tasks) >= 6:
                    checks["audit_len_ge_6"] = True

                # Validate task fields and types
                all_fields_valid = True
                formula_ok = True
                time_costs = []
                ge_3_count = 0
                for t in tasks:
                    if not isinstance(t, dict):
                        all_fields_valid = False
                        formula_ok = False
                        break
                    required_keys = [
                        "task_name",
                        "minutes_per_task",
                        "frequency_per_month",
                        "time_cost_hours",
                        "repetitive",
                        "requires_judgment",
                        "automation_candidate",
                    ]
                    if not all(k in t for k in required_keys):
                        all_fields_valid = False
                        formula_ok = False
                        break
                    # Type checks
                    if not isinstance(t["task_name"], str):
                        all_fields_valid = False
                    if not is_number(t["minutes_per_task"]):
                        all_fields_valid = False
                    if not is_number(t["frequency_per_month"]):
                        all_fields_valid = False
                    if not is_number(t["time_cost_hours"]):
                        all_fields_valid = False
                    if not isinstance(t["repetitive"], bool):
                        all_fields_valid = False
                    if not isinstance(t["requires_judgment"], bool):
                        all_fields_valid = False
                    if not isinstance(t["automation_candidate"], bool):
                        all_fields_valid = False

                    if not all_fields_valid:
                        formula_ok = False
                        break

                    minutes = float(t["minutes_per_task"])
                    freq_mo = float(t["frequency_per_month"])
                    time_cost = float(t["time_cost_hours"])
                    expected = (minutes * freq_mo) / 60.0
                    if abs(time_cost - expected) > 0.05:
                        formula_ok = False
                    time_costs.append(time_cost)
                    if time_cost >= 3.0:
                        ge_3_count += 1

                if all_fields_valid:
                    checks["audit_tasks_fields_valid"] = True
                if formula_ok and all_fields_valid and len(tasks) > 0:
                    checks["audit_time_cost_formula_ok"] = True
                    # Sorted non-increasing check
                    sorted_ok = True
                    for i in range(1, len(time_costs)):
                        if time_costs[i-1] + 1e-9 < time_costs[i]:
                            sorted_ok = False
                            break
                    if sorted_ok:
                        checks["audit_sorted_desc"] = True
                    if ge_3_count >= 3:
                        checks["audit_at_least_3_ge_3h"] = True

    # 2) workflows.json
    workflows_path = os.path.join(output_dir, "workflows.json")
    if os.path.isfile(workflows_path):
        checks["workflows_exists"] = True
        workflows_data, wf_err = read_json_file(workflows_path)
        if workflows_data is not None and isinstance(workflows_data, list):
            checks["workflows_valid_json"] = True
            if len(workflows_data) >= 3:
                checks["workflows_array_len_ge_3"] = True

            required_keys_wf = {
                "name", "trigger", "conditions", "actions", "error_handling",
                "platform_category", "test_plan", "monitoring", "roi"
            }
            allowed_platforms = {"simple-2-3-steps", "visual-multi-step", "self-hosted-advanced"}

            all_have_required = True
            all_platforms_valid = True
            all_actions_len_ok = True
            roi_payback_ok_all = True
            has_simple_mvp = False

            for wf in workflows_data:
                if not isinstance(wf, dict):
                    all_have_required = False
                    all_platforms_valid = False
                    all_actions_len_ok = False
                    roi_payback_ok_all = False
                    continue

                if not required_keys_wf.issubset(wf.keys()):
                    all_have_required = False

                # platform_category
                pc = wf.get("platform_category")
                if not isinstance(pc, str) or pc not in allowed_platforms:
                    all_platforms_valid = False

                # conditions type (string or array)
                conds = wf.get("conditions")
                if not (isinstance(conds, str) or isinstance(conds, list)):
                    all_have_required = False  # treat as missing/invalid

                # actions length 2..5
                actions = wf.get("actions")
                if not isinstance(actions, list) or not (2 <= len(actions) <= 5):
                    all_actions_len_ok = False

                # error_handling, trigger, name, test_plan, monitoring should be strings
                for k in ["error_handling", "trigger", "name", "test_plan", "monitoring"]:
                    if not isinstance(wf.get(k), str):
                        all_have_required = False

                # ROI fields
                roi = wf.get("roi")
                if not isinstance(roi, dict):
                    roi_payback_ok_all = False
                else:
                    sh = roi.get("setup_hours")
                    ts = roi.get("time_saved_hours_per_month")
                    tmc = roi.get("tool_monthly_cost")
                    pm = roi.get("payback_months")
                    if not (is_number(sh) and is_number(ts) and is_number(tmc) and is_number(pm)):
                        roi_payback_ok_all = False
                    else:
                        if ts == 0:
                            roi_payback_ok_all = False
                        else:
                            expected = float(sh) / float(ts)
                            if abs(float(pm) - expected) > 0.1:
                                roi_payback_ok_all = False

                # simple MVP condition
                if isinstance(pc, str) and pc == "simple-2-3-steps" and isinstance(actions, list) and (2 <= len(actions) <= 3):
                    has_simple_mvp = True

            if all_have_required:
                checks["workflows_each_has_required_keys"] = True
            if all_platforms_valid:
                checks["workflows_platform_category_valid_for_all"] = True
            if all_actions_len_ok:
                checks["workflows_actions_len_2_to_5_all"] = True
            if roi_payback_ok_all:
                checks["workflows_roi_fields_numeric_and_payback_ok"] = True
            if has_simple_mvp:
                checks["workflows_has_simple_mvp"] = True

    # 3) monitoring_plan.md
    monitoring_path = os.path.join(output_dir, "monitoring_plan.md")
    if os.path.isfile(monitoring_path):
        try:
            with open(monitoring_path, "r", encoding="utf-8") as f:
                mon_content = f.read()
            if mon_content and mon_content.strip():
                checks["monitoring_exists_nonempty"] = True
                lc = mon_content.lower()
                phrases = ["weekly check", "monthly audit", "error notifications"]
                if all(p in lc for p in phrases):
                    checks["monitoring_contains_phrases"] = True
        except Exception:
            pass

    # 4) checklist.txt
    checklist_path = os.path.join(output_dir, "checklist.txt")
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        try:
            with open(checklist_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n").strip() for ln in f.readlines()]
            required_bullets = {
                "- Start with simple 2-3 step workflows",
                "- Always include error notifications",
                "- Test with edge cases",
                "- Don't automate before optimizing",
            }
            line_set = set(lines)
            if required_bullets.issubset(line_set):
                checks["checklist_has_required_bullets"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if no files in output, reward should be 0.0
    # If output dir missing or empty, force reward to 0.0
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward = 0.0
        # Also ensure no checks are incorrectly set (they should already be False)

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()