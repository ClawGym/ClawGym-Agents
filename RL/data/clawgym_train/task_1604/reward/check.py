import json
import os
import sys
import csv
import re
from typing import Any, Dict, List, Tuple, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path: str) -> Tuple[Optional[Any], bool]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data, True
    except Exception:
        return None, False

def is_string(value: Any) -> bool:
    return isinstance(value, str)

def is_bool(value: Any) -> bool:
    return isinstance(value, bool)

def is_object(value: Any) -> bool:
    return isinstance(value, dict)

def is_array(value: Any) -> bool:
    return isinstance(value, list)

def approx_equal(a: float, b: float, tol: float = 0.05) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            value = value.strip()
        return float(value)
    except Exception:
        return None

def find_section_indices(lines: List[str], titles_ci: List[str]) -> Dict[str, int]:
    indices: Dict[str, int] = {}
    for i, line in enumerate(lines):
        lower = line.strip().lower()
        for t in titles_ci:
            if t not in indices and t in lower:
                indices[t] = i
    return indices

def count_bullets(lines: List[str]) -> int:
    count = 0
    pattern = re.compile(r'^\s*(?:[-*]|\d+\.)\s+')
    for line in lines:
        if pattern.match(line):
            count += 1
    return count

def get_section_block(lines: List[str], start_idx: int, next_start_idx: Optional[int]) -> List[str]:
    if start_idx < 0:
        return []
    end = next_start_idx if next_start_idx is not None else len(lines)
    if end < start_idx:
        end = len(lines)
    return lines[start_idx+1:end]

def validate_automation_plan(plan: Any) -> Dict[str, bool]:
    checks = {
        "has_automation_plan": False,
        "automation_plan_valid_json": False,
        "automation_plan_required_top_keys": False,
        "automation_plan_workflows_count": False,
        "automation_plan_workflow_fields_all_present": False,
        "automation_plan_actions_valid": False,
        "automation_plan_monitoring_fields": False,
        "automation_plan_conditions_at_least_one_non_empty": False,
        "automation_plan_has_deduplication_true": False,
    }

    if plan is None:
        return checks

    checks["has_automation_plan"] = True
    checks["automation_plan_valid_json"] = True

    # Top-level required keys
    top_keys_ok = all(k in plan for k in ["hourly_rate", "monthly_budget", "assumptions", "workflows"])
    checks["automation_plan_required_top_keys"] = bool(top_keys_ok)

    workflows = plan.get("workflows") if isinstance(plan, dict) else None
    if isinstance(workflows, list) and 3 <= len(workflows) <= 5:
        checks["automation_plan_workflows_count"] = True
    else:
        return checks  # If workflows count invalid, dependent checks remain False

    # Validate each workflow
    required_wf_keys = ["name", "description", "trigger", "conditions", "actions", "deduplication", "error_handling", "monitoring", "tool_selection"]
    all_present = True
    actions_valid_all = True
    monitoring_valid_all = True
    any_non_empty_conditions = False
    any_dedup_true = False

    for wf in workflows:
        if not isinstance(wf, dict):
            all_present = False
            actions_valid_all = False
            monitoring_valid_all = False
            continue

        # Required keys presence and basic types
        if not all(k in wf for k in required_wf_keys):
            all_present = False

        # Types for selected fields
        if "name" in wf and not is_string(wf["name"]):
            all_present = False
        if "description" in wf and not is_string(wf["description"]):
            all_present = False
        if "trigger" in wf and not is_string(wf["trigger"]):
            all_present = False
        if "conditions" in wf and not is_array(wf["conditions"]):
            all_present = False
        if "deduplication" in wf and not is_bool(wf["deduplication"]):
            all_present = False

        # Actions validation: array length >= 2, each action has type (string) and parameters (object)
        actions = wf.get("actions")
        if not (is_array(actions) and len(actions) >= 2):
            actions_valid_all = False
        else:
            for act in actions:
                if not isinstance(act, dict):
                    actions_valid_all = False
                    break
                if "type" not in act or not is_string(act["type"]):
                    actions_valid_all = False
                    break
                if "parameters" not in act or not is_object(act["parameters"]):
                    actions_valid_all = False
                    break

        # error_handling existence (array or object)
        if "error_handling" in wf:
            eh = wf["error_handling"]
            if not (is_object(eh) or is_array(eh)):
                all_present = False

        # monitoring object with 'schedule' and at least one of ['checks', 'what_to_check', 'metrics']
        monitoring = wf.get("monitoring")
        if not is_object(monitoring):
            monitoring_valid_all = False
        else:
            schedule_ok = "schedule" in monitoring and is_string(monitoring.get("schedule"))
            checks_key_present = any(k in monitoring for k in ["checks", "what_to_check", "metrics"])
            monitoring_valid_all = monitoring_valid_all and schedule_ok and checks_key_present

        # tool_selection with complexity_level in allowed set
        ts = wf.get("tool_selection")
        if not (is_object(ts) and "complexity_level" in ts and is_string(ts["complexity_level"]) and ts["complexity_level"] in {"low", "medium", "high"}):
            all_present = False

        # Track conditions non-empty and dedup true
        if is_array(wf.get("conditions")) and len(wf.get("conditions")) >= 1:
            any_non_empty_conditions = True
        if is_bool(wf.get("deduplication")) and wf.get("deduplication") is True:
            any_dedup_true = True

    checks["automation_plan_workflow_fields_all_present"] = all_present
    checks["automation_plan_actions_valid"] = actions_valid_all
    checks["automation_plan_monitoring_fields"] = monitoring_valid_all
    checks["automation_plan_conditions_at_least_one_non_empty"] = any_non_empty_conditions
    checks["automation_plan_has_deduplication_true"] = any_dedup_true

    return checks

def validate_roi_csv(csv_path: str, workflows_count: Optional[int]) -> Dict[str, bool]:
    checks = {
        "has_roi_csv": False,
        "roi_header_exact": False,
        "roi_min_rows": False,
        "roi_numeric_fields_valid": False,
        "roi_value_formulas_correct": False,
        "roi_sorted_by_payback": False,
        "roi_rows_match_workflows_count": False,
    }
    if not os.path.isfile(csv_path):
        return checks

    checks["has_roi_csv"] = True

    expected_header = ["task_name","minutes_per_task","frequency_per_month","time_saved_hours_per_month","setup_time_hours","tool_cost_per_month","hourly_rate","monthly_value_saved_usd","payback_months","priority"]

    rows: List[Dict[str, str]] = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == expected_header:
                checks["roi_header_exact"] = True
            for row in reader:
                # Skip completely blank rows
                if row is None:
                    continue
                # If all fields empty, skip
                if all((v is None or str(v).strip() == "") for v in row.values()):
                    continue
                rows.append(row)
    except Exception:
        return checks

    if len(rows) >= 3:
        checks["roi_min_rows"] = True

    # Numeric fields parse and formula checks
    numeric_ok = True
    formula_ok = True
    paybacks: List[float] = []
    for row in rows:
        mpt = parse_float(row.get("minutes_per_task"))
        fpm = parse_float(row.get("frequency_per_month"))
        tsh = parse_float(row.get("time_saved_hours_per_month"))
        sth = parse_float(row.get("setup_time_hours"))
        tcost = parse_float(row.get("tool_cost_per_month"))
        hrate = parse_float(row.get("hourly_rate"))
        mvs = parse_float(row.get("monthly_value_saved_usd"))
        pb = parse_float(row.get("payback_months"))
        # Check numeric presence
        for v in [mpt, fpm, tsh, sth, tcost, hrate, mvs, pb]:
            if v is None:
                numeric_ok = False
                break
        if not numeric_ok:
            break
        # Formula checks
        # monthly_value_saved_usd ≈ time_saved_hours_per_month * hourly_rate
        if mvs is None or tsh is None or hrate is None:
            formula_ok = False
        else:
            if not approx_equal(mvs, tsh * hrate, tol=0.05):
                formula_ok = False
        # payback_months ≈ (setup_time_hours * hourly_rate + tool_cost_per_month) / monthly_value_saved_usd
        if mvs is None or mvs == 0:
            formula_ok = False
        else:
            expected_pb = (sth * hrate + tcost) / mvs
            if pb is None or not approx_equal(pb, expected_pb, tol=0.05):
                formula_ok = False
        if pb is not None:
            paybacks.append(pb)

    checks["roi_numeric_fields_valid"] = numeric_ok
    checks["roi_value_formulas_correct"] = formula_ok

    # Sorted ascending by payback_months (non-decreasing)
    if len(paybacks) == len(rows) and len(rows) >= 1:
        sorted_paybacks = sorted(paybacks)
        # allow non-decreasing sequence
        is_sorted = all(paybacks[i] <= paybacks[i+1] + 1e-12 for i in range(len(paybacks)-1))
        # Also verify equals sorted list within tolerance
        # To be tolerant to tiny float differences, compare tuples rounded to 6 decimals
        if is_sorted:
            checks["roi_sorted_by_payback"] = True

    # Optional cross-check with workflows count
    if workflows_count is not None and checks["roi_min_rows"]:
        if len(rows) == workflows_count:
            checks["roi_rows_match_workflows_count"] = True

    return checks

def find_section_ranges(lines: List[str], section_titles: List[str]) -> Dict[str, Tuple[int, Optional[int]]]:
    # Return start index and next start index for each found section name (lowercased)
    indices = {}
    lower_titles = [t.lower() for t in section_titles]
    # Find start indices
    start_map = {}
    for i, line in enumerate(lines):
        low = line.strip().lower()
        for t in lower_titles:
            if t not in start_map and t in low:
                start_map[t] = i
    # Determine next start indices
    for t in lower_titles:
        if t in start_map:
            start_idx = start_map[t]
            # Find the nearest next section start among the others with greater index
            next_indices = [start_map[ot] for ot in lower_titles if ot in start_map and start_map[ot] > start_idx]
            next_idx = min(next_indices) if next_indices else None
            indices[t] = (start_idx, next_idx)
    return indices

def validate_testing_md(path: str) -> Dict[str, bool]:
    checks = {
        "has_testing_md": False,
        "testing_has_sections": False,
        "testing_checklist_min_items": False,
        "testing_edge_cases_min_items": False,
        "testing_failure_injection_min_items": False,
    }
    content = read_text(path)
    if content is None:
        return checks
    checks["has_testing_md"] = True

    lines = content.splitlines()
    titles = ["Testing checklist", "Edge cases", "Failure injection"]
    ranges = find_section_ranges(lines, titles)
    has_all = all(t.lower() in ranges for t in titles)
    checks["testing_has_sections"] = has_all

    if not has_all:
        return checks

    # Count bullets in each section
    # Testing checklist needs at least 8 items
    block = get_section_block(lines, ranges["testing checklist"][0], ranges["edge cases"][0])
    if count_bullets(block) >= 8:
        checks["testing_checklist_min_items"] = True

    # Edge cases: at least 5 items
    block = get_section_block(lines, ranges["edge cases"][0], ranges["failure injection"][0])
    if count_bullets(block) >= 5:
        checks["testing_edge_cases_min_items"] = True

    # Failure injection: at least 3 items
    block = get_section_block(lines, ranges["failure injection"][0], ranges["failure injection"][1])
    if count_bullets(block) >= 3:
        checks["testing_failure_injection_min_items"] = True

    return checks

def validate_maintenance_md(path: str) -> Dict[str, bool]:
    checks = {
        "has_maintenance_md": False,
        "maintenance_has_sections": False,
        "maintenance_weekly_min_items": False,
        "maintenance_monthly_min_items": False,
        "maintenance_error_channel_min_items": False,
    }
    content = read_text(path)
    if content is None:
        return checks
    checks["has_maintenance_md"] = True

    lines = content.splitlines()
    titles = ["Weekly checks", "Monthly audit", "Error handling channel"]
    ranges = find_section_ranges(lines, titles)
    has_all = all(t.lower() in ranges for t in titles)
    checks["maintenance_has_sections"] = has_all

    if not has_all:
        return checks

    # Weekly checks: at least 2 items
    block = get_section_block(lines, ranges["weekly checks"][0], ranges["monthly audit"][0])
    if count_bullets(block) >= 2:
        checks["maintenance_weekly_min_items"] = True

    # Monthly audit: at least 2 items
    block = get_section_block(lines, ranges["monthly audit"][0], ranges["error handling channel"][0])
    if count_bullets(block) >= 2:
        checks["maintenance_monthly_min_items"] = True

    # Error handling channel: at least 2 items
    block = get_section_block(lines, ranges["error handling channel"][0], ranges["error handling channel"][1])
    if count_bullets(block) >= 2:
        checks["maintenance_error_channel_min_items"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks as False
    all_checks: Dict[str, bool] = {}

    # 1) automation_plan.json
    automation_plan_path = os.path.join(output_dir, "automation_plan.json")
    plan_data = None
    plan_exists = os.path.isfile(automation_plan_path)
    if plan_exists:
        plan_data, plan_valid = load_json(automation_plan_path)
        # validate_automation_plan will set flags including existence
        plan_checks = validate_automation_plan(plan_data if plan_valid else None)
    else:
        plan_checks = validate_automation_plan(None)

    all_checks.update(plan_checks)

    workflows_count = None
    if plan_checks.get("automation_plan_workflows_count"):
        try:
            workflows_count = len(plan_data.get("workflows")) if isinstance(plan_data, dict) and isinstance(plan_data.get("workflows"), list) else None
        except Exception:
            workflows_count = None

    # 2) roi.csv
    roi_path = os.path.join(output_dir, "roi.csv")
    roi_checks = validate_roi_csv(roi_path, workflows_count)
    all_checks.update(roi_checks)

    # 3) testing.md
    testing_path = os.path.join(output_dir, "testing.md")
    testing_checks = validate_testing_md(testing_path)
    all_checks.update(testing_checks)

    # 4) maintenance.md
    maintenance_path = os.path.join(output_dir, "maintenance.md")
    maintenance_checks = validate_maintenance_md(maintenance_path)
    all_checks.update(maintenance_checks)

    # Compute reward as fraction of passed checks
    total = len(all_checks)
    passed = sum(1 for v in all_checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # No-op baseline: if no outputs exist or no required artifacts, ensure reward is 0.0
    outputs_present = any([
        os.path.isfile(automation_plan_path),
        os.path.isfile(roi_path),
        os.path.isfile(testing_path),
        os.path.isfile(maintenance_path),
    ])
    if not outputs_present:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()