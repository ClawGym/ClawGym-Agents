import json
import os
import sys
import csv
from typing import Any, Dict, List, Tuple

def approx_equal(a: float, b: float, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def to_bool(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return False

def to_number(val):
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip()
    try:
        if s.lower() in ("nan", "inf", "-inf"):
            return float("nan")
    except Exception:
        pass
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return None

def parse_scalar_yaml_value(s: str):
    s = s.strip()
    if s == "" or s.lower() == "null":
        return None
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1]
    sl = s.lower()
    if sl in ("true", "false"):
        return sl == "true"
    # numbers
    try:
        if "." in s or "e" in sl:
            return float(s)
        return int(s)
    except Exception:
        return s

def get_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

def parse_map_of_scalars(lines: List[str], start_idx: int, base_indent: int) -> Tuple[Dict[str, Any], int]:
    d: Dict[str, Any] = {}
    i = start_idx
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "" or line.lstrip().startswith("#"):
            i += 1
            continue
        ind = get_indent(line)
        if ind < base_indent:
            break
        if ind == base_indent and ":" in line:
            # key: value
            chunk = line.strip()
            # split only on first colon
            parts = chunk.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip() if len(parts) > 1 else ""
            if val == "":
                # value may be on subsequent indented lines; assume empty string
                d[key] = ""
                i += 1
                continue
            d[key] = parse_scalar_yaml_value(val)
            i += 1
        else:
            # skip deeper indentation until next item
            i += 1
    return d, i

def parse_map_of_lists(lines: List[str], start_idx: int, base_indent: int) -> Tuple[Dict[str, List[Any]], int]:
    d: Dict[str, List[Any]] = {}
    i = start_idx
    n = len(lines)
    current_key = None
    while i < n:
        line = lines[i]
        if line.strip() == "" or line.lstrip().startswith("#"):
            i += 1
            continue
        ind = get_indent(line)
        if ind < base_indent:
            break
        if ind == base_indent and ":" in line:
            # new category key
            chunk = line.strip()
            parts = chunk.split(":", 1)
            current_key = parts[0].strip()
            d[current_key] = []
            i += 1
            continue
        if current_key is not None and ind >= base_indent + 2:
            stripped = line.strip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                d[current_key].append(parse_scalar_yaml_value(item))
                i += 1
                continue
            else:
                # ignore non-list content under key
                i += 1
                continue
        else:
            i += 1
    return d, i

def parse_config_yaml(path: str) -> Dict[str, Any]:
    # Specialized parser for expected config.yaml structure
    cfg: Dict[str, Any] = {}
    if not os.path.isfile(path):
        return cfg
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "" or line.lstrip().startswith("#"):
            i += 1
            continue
        ind = get_indent(line)
        if ind != 0:
            i += 1
            continue
        # top-level key
        if ":" not in line:
            i += 1
            continue
        key, rest = line.split(":", 1)
        top_key = key.strip()
        rest_val = rest.strip()
        if top_key in ("triggers_by_category", "error_handling_by_category", "tool_capacities", "tool_costs"):
            # mapping of scalars
            d, i2 = parse_map_of_scalars(lines, i + 1, base_indent=2)
            cfg[top_key] = d
            i = i2
            continue
        if top_key in ("action_templates", "conditions_by_category"):
            # mapping of lists
            d, i2 = parse_map_of_lists(lines, i + 1, base_indent=2)
            cfg[top_key] = d
            i = i2
            continue
        if top_key == "maintenance_plan":
            d, i2 = parse_map_of_scalars(lines, i + 1, base_indent=2)
            cfg[top_key] = d
            i = i2
            continue
        # scalar numeric/string
        if rest_val != "":
            cfg[top_key] = parse_scalar_yaml_value(rest_val)
            i += 1
        else:
            # empty, skip
            cfg[top_key] = None
            i += 1
    return cfg

def read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_csv_dicts(path: str) -> Tuple[List[Dict[str, Any]], str]:
    if not os.path.isfile(path):
        return [], "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows, ""
    except Exception as e:
        return [], str(e)

def parse_readme_lines(path: str) -> List[str]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return []

def parse_roi_csv(path: str) -> Tuple[List[Dict[str, str]], str]:
    if not os.path.isfile(path):
        return [], "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames
        return rows, ",".join(header) if header else ""
    except Exception as e:
        return [], str(e)

def coerce_task_id(val: Any) -> str:
    # For comparison, always convert to string without surrounding spaces
    return str(val).strip()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "has_audit": False,
        "audit_json_valid": False,
        "audit_time_costs_ok": False,
        "audit_sort_ok": False,
        "has_workflows": False,
        "workflows_json_valid": False,
        "workflows_only_eligible": False,
        "workflows_templates_match": False,
        "workflows_maintenance_ok": False,
        "workflows_roi_ok": False,
        "tool_selection_ok": False,
        "has_roi_csv": False,
        "roi_header_ok": False,
        "roi_matches_workflows": False,
        "has_readme": False,
        "readme_lines_match": False,
    }

    # Paths
    tasks_csv_path = os.path.join(input_dir, "tasks.csv")
    config_yaml_path = os.path.join(input_dir, "config.yaml")
    audit_json_path = os.path.join(output_dir, "audit.json")
    workflows_json_path = os.path.join(output_dir, "workflows.json")
    roi_csv_path = os.path.join(output_dir, "roi.csv")
    readme_path = os.path.join(output_dir, "README.md")

    # Load inputs
    tasks_rows, tasks_err = read_csv_dicts(tasks_csv_path)
    config = parse_config_yaml(config_yaml_path)

    # Parse audit.json
    audit_json, audit_err = read_json_file(audit_json_path)
    if os.path.isfile(audit_json_path):
        checks["has_audit"] = True
    if audit_json and isinstance(audit_json, dict) and "tasks" in audit_json and "tasks_sorted_by_time_cost" in audit_json:
        checks["audit_json_valid"] = True

    # Build a map of audit tasks and verify time_cost and sort
    audit_tasks = []
    task_map_by_id = {}
    if checks["audit_json_valid"]:
        tasks_list = audit_json.get("tasks", [])
        # Verify each task has required fields and time_cost
        time_costs_ok = True
        for t in tasks_list:
            try:
                task_id_val = t.get("task_id")
                task_id = coerce_task_id(task_id_val)
                minutes = to_number(t.get("minutes_per_task"))
                freq = to_number(t.get("frequency_per_month"))
                time_cost = to_number(t.get("time_cost_hours"))
                if minutes is None or freq is None or time_cost is None:
                    time_costs_ok = False
                else:
                    expected_tc = (float(minutes) * float(freq)) / 60.0
                    if not approx_equal(expected_tc, float(time_cost), 0.01):
                        time_costs_ok = False
                # Build for future
                # Convert booleans and numerics
                audit_task = {
                    "task_id": task_id,
                    "name": t.get("name"),
                    "category": t.get("category"),
                    "minutes_per_task": float(minutes) if minutes is not None else None,
                    "frequency_per_month": float(freq) if freq is not None else None,
                    "repetitive": to_bool(t.get("repetitive")),
                    "rule_based": to_bool(t.get("rule_based")),
                    "requires_judgment": to_bool(t.get("requires_judgment")),
                    "estimated_setup_hours": float(to_number(t.get("estimated_setup_hours"))) if to_number(t.get("estimated_setup_hours")) is not None else None,
                    "complexity_level": int(to_number(t.get("complexity_level"))) if to_number(t.get("complexity_level")) is not None else None,
                    "time_cost_hours": float(time_cost) if time_cost is not None else None,
                }
                audit_tasks.append(audit_task)
                task_map_by_id[task_id] = audit_task
            except Exception:
                time_costs_ok = False
        checks["audit_time_costs_ok"] = time_costs_ok

        # Verify sort order
        expected_sorted_ids = []
        try:
            # Sort by descending time_cost_hours, tie by task_id ascending (string)
            sortable = []
            for t in audit_tasks:
                tc = t.get("time_cost_hours")
                if tc is None:
                    tc = 0.0
                sortable.append((float(tc), t["task_id"]))
            sortable.sort(key=lambda x: (-x[0], x[1]))
            expected_sorted_ids = [tid for _, tid in sortable]
            actual_sorted_ids = [coerce_task_id(x) for x in audit_json.get("tasks_sorted_by_time_cost", [])]
            # Compare exact order
            checks["audit_sort_ok"] = (expected_sorted_ids == actual_sorted_ids)
        except Exception:
            checks["audit_sort_ok"] = False

    # Eligible tasks based on audit.json tasks
    eligible_ids: List[str] = []
    if audit_tasks:
        for t in audit_tasks:
            minutes = t.get("minutes_per_task")
            freq = t.get("frequency_per_month")
            if minutes is None or freq is None:
                continue
            if to_bool(t.get("repetitive")) and to_bool(t.get("rule_based")) and (not to_bool(t.get("requires_judgment"))) and float(minutes) >= 10 and float(freq) >= 4:
                eligible_ids.append(t["task_id"])

    # Parse workflows.json
    workflows_json, workflows_err = read_json_file(workflows_json_path)
    if os.path.isfile(workflows_json_path):
        checks["has_workflows"] = True
    workflows_list: List[Dict[str, Any]] = []
    if isinstance(workflows_json, list):
        checks["workflows_json_valid"] = True
        workflows_list = workflows_json

    # Validate workflows against eligibility, templates, maintenance, ROI, and tool selection
    templates_match_all = True
    maintenance_ok_all = True
    roi_ok_all = True
    tool_ok_all = True
    only_eligible = True

    # Load config components
    triggers_by_category = config.get("triggers_by_category", {}) or {}
    action_templates = config.get("action_templates", {}) or {}
    conditions_by_category = config.get("conditions_by_category", {}) or {}
    error_handling_by_category = config.get("error_handling_by_category", {}) or {}
    maintenance_plan = config.get("maintenance_plan", {}) or {}
    tool_capacities = config.get("tool_capacities", {}) or {}
    tool_costs = config.get("tool_costs", {}) or {}
    hourly_value_of_time = config.get("hourly_value_of_time", None)
    setup_hourly_cost = config.get("setup_hourly_cost", None)
    payback_threshold_months = config.get("payback_threshold_months", None)
    max_tool_budget = config.get("max_tool_budget", None)

    # Coerce numeric config
    def num(v, default=None):
        nv = to_number(v)
        return float(nv) if nv is not None else default

    hourly_value_of_time = num(hourly_value_of_time, None)
    setup_hourly_cost = num(setup_hourly_cost, None)
    payback_threshold_months = num(payback_threshold_months, None)
    max_tool_budget = num(max_tool_budget, None)

    def acceptable_tools_for_task(complexity: int) -> List[str]:
        # Determine acceptable tools per deterministic rules with tie-flexibility
        # S = tools with capacity >= complexity
        S = [(tool, int(to_number(cap))) for tool, cap in tool_capacities.items() if to_number(cap) is not None and int(to_number(cap)) >= complexity]
        if not S:
            return []
        # sort by capacity asc, then by cost asc, then name for stability
        def tool_cost(tool_name):
            c = to_number(tool_costs.get(tool_name))
            return float(c) if c is not None else float("inf")
        S.sort(key=lambda x: (x[1], tool_cost(x[0]), x[0]))
        mincap = S[0][1]
        mincap_tools = [t for t, c in S if c == mincap]
        # First, candidates within mincap and within budget
        within_budget_candidates = []
        if max_tool_budget is not None:
            for t in mincap_tools:
                cst = to_number(tool_costs.get(t))
                if cst is not None and float(cst) <= max_tool_budget:
                    within_budget_candidates.append(t)
        # Accept any of them if present
        if within_budget_candidates:
            return within_budget_candidates
        # Else find next higher-capacity group with any within budget
        if max_tool_budget is not None:
            higher_caps = sorted(set(c for _, c in S if c > mincap))
            for cap in higher_caps:
                candidates = [t for t, c in S if c == cap]
                wb = []
                for t in candidates:
                    cst = to_number(tool_costs.get(t))
                    if cst is not None and float(cst) <= max_tool_budget:
                        wb.append(t)
                if wb:
                    return wb
        # If none within budget, select the lowest-cost tools that meet capacity
        # Determine minimal cost among S
        min_cost = None
        for t, _ in S:
            cst = to_number(tool_costs.get(t))
            if cst is None:
                continue
            cstf = float(cst)
            if min_cost is None or cstf < min_cost:
                min_cost = cstf
        if min_cost is None:
            # If costs missing, accept the minimal capacity group
            return mincap_tools
        cheap_tools = [t for t, _ in S if approx_equal(to_number(tool_costs.get(t)), min_cost, 1e-9) or (to_number(tool_costs.get(t)) is not None and float(to_number(tool_costs.get(t))) == min_cost)]
        return cheap_tools

    if workflows_list:
        # Build set for eligibility check
        eligible_set = set(eligible_ids)
        for wf in workflows_list:
            try:
                wf_task_id = coerce_task_id(wf.get("task_id"))
                if wf_task_id not in eligible_set:
                    only_eligible = False
                # Templates and maintenance
                task = task_map_by_id.get(wf_task_id)
                if not task:
                    # If not present in audit, fail relevant checks
                    templates_match_all = False
                    maintenance_ok_all = False
                    roi_ok_all = False
                    tool_ok_all = False
                    continue
                category = task.get("category")
                # If category missing from templates, we do not expect a workflow entry; mark failure for template match
                if category not in triggers_by_category or category not in action_templates or category not in conditions_by_category or category not in error_handling_by_category:
                    # The presence of a workflow for a missing template category is a template mismatch
                    templates_match_all = False
                else:
                    exp_trigger = triggers_by_category.get(category)
                    exp_actions = action_templates.get(category) or []
                    exp_conditions = conditions_by_category.get(category) or []
                    exp_error = error_handling_by_category.get(category)
                    # compare
                    if wf.get("trigger") != exp_trigger:
                        templates_match_all = False
                    # Ensure arrays and exact order
                    wf_actions = wf.get("actions", [])
                    if wf_actions != exp_actions:
                        templates_match_all = False
                    wf_cond = wf.get("conditions", [])
                    if wf_cond != exp_conditions:
                        templates_match_all = False
                    if wf.get("error_handling") != exp_error:
                        templates_match_all = False
                # Maintenance plan
                mp = wf.get("maintenance_plan")
                if not isinstance(mp, dict) or ("weekly_check" not in mp) or ("monthly_audit" not in mp):
                    maintenance_ok_all = False
                else:
                    exp_weekly = (maintenance_plan.get("weekly_check") or "")
                    exp_monthly = (maintenance_plan.get("monthly_audit") or "")
                    if mp.get("weekly_check") != exp_weekly or mp.get("monthly_audit") != exp_monthly:
                        maintenance_ok_all = False
                # ROI checks
                # Gather numbers
                est_setup = to_number(wf.get("estimated_setup_hours"))
                hours_saved = to_number(wf.get("hours_saved_per_month"))
                mv_saved = to_number(wf.get("monthly_value_saved"))
                setup_cost = to_number(wf.get("setup_cost"))
                m_tool_cost = to_number(wf.get("monthly_tool_cost"))
                payback = to_number(wf.get("payback_months"))
                net_savings = to_number(wf.get("net_monthly_savings"))
                meets = wf.get("meets_threshold")
                # Basic type presence
                numbers_present = all(v is not None for v in [est_setup, hours_saved, mv_saved, setup_cost, m_tool_cost, payback, net_savings])
                if not numbers_present or hourly_value_of_time is None or setup_hourly_cost is None or payback_threshold_months is None:
                    roi_ok_all = False
                else:
                    # hours_saved should equal time_cost from audit
                    expected_hours = to_number(task.get("time_cost_hours"))
                    if expected_hours is None or not approx_equal(expected_hours, hours_saved, 0.01):
                        roi_ok_all = False
                    # monthly_value_saved
                    if not approx_equal(hours_saved * hourly_value_of_time, mv_saved, 0.01):
                        roi_ok_all = False
                    # setup_cost
                    if not approx_equal(est_setup * setup_hourly_cost, setup_cost, 0.01):
                        roi_ok_all = False
                    # monthly_tool_cost equals tool_costs[tool]
                    tool_name = wf.get("tool")
                    cfg_tool_cost = to_number(tool_costs.get(tool_name))
                    if cfg_tool_cost is None or not approx_equal(cfg_tool_cost, m_tool_cost, 0.01):
                        roi_ok_all = False
                    # payback months
                    if mv_saved == 0:
                        # If no monthly value saved, payback could be inf or handling; consider mismatch
                        roi_ok_all = False
                    else:
                        if not approx_equal(setup_cost / mv_saved, payback, 0.01):
                            roi_ok_all = False
                    # net savings
                    if not approx_equal(mv_saved - m_tool_cost, net_savings, 0.01):
                        roi_ok_all = False
                    # meets threshold
                    exp_meets = (payback is not None and payback_threshold_months is not None and float(payback) < float(payback_threshold_months))
                    if bool(meets) != bool(exp_meets):
                        roi_ok_all = False
                # Tool selection rules
                comp_level = task.get("complexity_level")
                if comp_level is None:
                    tool_ok_all = False
                else:
                    comp_level_int = int(comp_level)
                    acceptable_tools = acceptable_tools_for_task(comp_level_int)
                    chosen = wf.get("tool")
                    if not acceptable_tools:
                        # No acceptable tool computed but a tool exists -> fail
                        tool_ok_all = False
                    else:
                        if chosen not in acceptable_tools:
                            tool_ok_all = False
            except Exception:
                templates_match_all = False
                maintenance_ok_all = False
                roi_ok_all = False
                tool_ok_all = False
                only_eligible = False

        checks["workflows_only_eligible"] = only_eligible
        checks["workflows_templates_match"] = templates_match_all
        checks["workflows_maintenance_ok"] = maintenance_ok_all
        checks["workflows_roi_ok"] = roi_ok_all
        checks["tool_selection_ok"] = tool_ok_all

    # ROI CSV checks
    if os.path.isfile(roi_csv_path):
        checks["has_roi_csv"] = True
    roi_rows, roi_header = parse_roi_csv(roi_csv_path)
    expected_header = "task_id,hours_saved_per_month,monthly_value_saved,setup_cost,monthly_tool_cost,payback_months,meets_threshold,tool"
    if roi_header == expected_header:
        checks["roi_header_ok"] = True

    if roi_rows and workflows_list:
        # Check there is exactly one row per workflow
        wf_by_id = {coerce_task_id(wf.get("task_id")): wf for wf in workflows_list}
        if len(roi_rows) == len(workflows_list):
            rows_match = True
            for row in roi_rows:
                tid = coerce_task_id(row.get("task_id"))
                if tid not in wf_by_id:
                    rows_match = False
                    break
                wf = wf_by_id[tid]
                # Compare numeric values within tolerance
                def row_num(field):
                    return to_number(row.get(field))
                if not approx_equal(row_num("hours_saved_per_month"), to_number(wf.get("hours_saved_per_month")), 0.01):
                    rows_match = False
                    break
                if not approx_equal(row_num("monthly_value_saved"), to_number(wf.get("monthly_value_saved")), 0.01):
                    rows_match = False
                    break
                if not approx_equal(row_num("setup_cost"), to_number(wf.get("setup_cost")), 0.01):
                    rows_match = False
                    break
                if not approx_equal(row_num("monthly_tool_cost"), to_number(wf.get("monthly_tool_cost")), 0.01):
                    rows_match = False
                    break
                if not approx_equal(row_num("payback_months"), to_number(wf.get("payback_months")), 0.01):
                    rows_match = False
                    break
                # meets_threshold exact boolean match
                row_meets = str(row.get("meets_threshold", "")).strip().lower()
                wf_meets = bool(wf.get("meets_threshold"))
                if row_meets not in ("true", "false"):
                    rows_match = False
                    break
                if (row_meets == "true") != wf_meets:
                    rows_match = False
                    break
                # tool exact match
                if str(row.get("tool", "")).strip() != str(wf.get("tool", "")):
                    rows_match = False
                    break
            if rows_match:
                checks["roi_matches_workflows"] = True

    # README checks
    if os.path.isfile(readme_path):
        checks["has_readme"] = True
        lines = parse_readme_lines(readme_path)
        lines_match = False
        # Need two lines: "Eligible tasks automated: N" and next line "Task IDs: ...", matching workflows.json
        wf_ids = [coerce_task_id(wf.get("task_id")) for wf in workflows_list]
        wf_id_set = set(wf_ids)
        for idx in range(len(lines) - 1):
            line1 = lines[idx].strip()
            line2 = lines[idx + 1].strip()
            if line1.lower().startswith("eligible tasks automated:") and line2.lower().startswith("task ids:"):
                # Extract N and ids
                try:
                    n_str = line1.split(":", 1)[1].strip()
                    n_val = int(n_str)
                except Exception:
                    continue
                ids_str = line2.split(":", 1)[1].strip()
                # Parse comma-separated
                if ids_str == "":
                    listed_ids = []
                else:
                    listed_ids = [coerce_task_id(s) for s in ids_str.split(",")]
                    listed_ids = [s.strip() for s in listed_ids if s.strip() != ""]
                if n_val == len(wf_ids) and set(listed_ids) == wf_id_set:
                    lines_match = True
                    break
        checks["readme_lines_match"] = lines_match

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # No-op baseline: if output dir missing or empty of required artifacts, keep 0.0
    required_paths = [audit_json_path, workflows_json_path, roi_csv_path, readme_path]
    if not any(os.path.isfile(p) for p in required_paths):
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()