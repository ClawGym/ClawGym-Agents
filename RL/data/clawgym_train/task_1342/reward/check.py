import csv
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Set, Tuple

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

workspace_root = get_workspace_root()
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks (all false by default; set to True only after verification)
checks = {
    "has_project_load_plan": False,
    "pl_first_line_add_project_matches": False,
    "pl_tasks_count_correct": False,
    "pl_task_deps_ref_valid": False,
    "pl_task_acyclic": False,
    "pl_milestones_count_correct": False,
    "pl_milestones_match_values": False,
    "pl_timesheet_count_correct": False,
    "pl_timesheet_items_fields_and_task_names_valid": False,
    "pl_timesheet_totals_match": False,
    "pl_order_correct": False,

    "has_gantt": False,
    "gantt_project_name_match": False,
    "gantt_tasks_cover_all": False,
    "gantt_dates_match": False,
    "gantt_dep_names_valid": False,
    "gantt_acyclic": False,

    "has_billing_csv": False,
    "billing_totals_match": False,

    "has_resource_csv": False,
    "resource_totals_match": False,

    "has_checklist": False,
    "cl_has_lifecycle_phrase": False,
    "cl_has_confirm_submit": False,
    "cl_has_confirm_bill": False,
    "cl_has_never_confirm_line": False,
    "cl_has_circular_dependency_phrase": False
}

# Utility functions
def read_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl_file(path: str) -> List[dict]:
    objs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            objs.append(json.loads(s))
    return objs

def read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # Normalize keys to lower-case for robustness but preserve values
            norm_row = {}
            for k, v in row.items():
                key = k.strip()
                norm_row[key] = v.strip() if isinstance(v, str) else v
            rows.append(norm_row)
        return rows

def quantize_2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def parse_decimal_safe(s, default="0"):
    if s is None or s == "":
        s = default
    try:
        return Decimal(str(s))
    except Exception:
        return Decimal(default)

def split_depends(value: str) -> List[str]:
    if not value:
        return []
    # Split by comma, semicolon, or pipe
    parts = re.split(r"[;,|]", value)
    return [p.strip() for p in parts if p.strip()]

def build_graph(nodes: Set[str], edges: Dict[str, List[str]]) -> Dict[str, List[str]]:
    # Ensure all nodes are present, even if no edges
    g = {n: [] for n in nodes}
    for src, deps in edges.items():
        if src not in g:
            g[src] = []
        for d in deps:
            if d in nodes:
                g[src].append(d)
    return g

def has_cycle(graph: Dict[str, List[str]]) -> bool:
    # Detect cycle via DFS colors: 0=unvisited, 1=visiting, 2=visited
    color = {node: 0 for node in graph}

    def dfs(u):
        color[u] = 1
        for v in graph[u]:
            if color[v] == 1:
                return True
            if color[v] == 0 and dfs(v):
                return True
        color[u] = 2
        return False

    for node in graph:
        if color[node] == 0:
            if dfs(node):
                return True
    return False

def compare_unordered_csv(expected: Dict[str, Tuple[Decimal, Decimal]], rows: List[Dict[str, str]], hours_col: str, amount_col: str) -> bool:
    # Build actual map
    actual_map: Dict[str, Tuple[Decimal, Decimal]] = {}
    for r in rows:
        emp = r.get("employee_id", "").strip()
        if emp == "":
            # Skip malformed row
            continue
        hours = parse_decimal_safe(r.get(hours_col, "0"))
        amount = parse_decimal_safe(r.get(amount_col, "0"))
        # Normalize to 2 decimals for comparison
        hours_q = quantize_2(hours)
        amount_q = quantize_2(amount)
        actual_map[emp] = (hours_q, amount_q)
    # Compare keys
    if set(expected.keys()) != set(actual_map.keys()):
        return False
    # Compare values
    for k, (eh, ea) in expected.items():
        ah, aa = actual_map.get(k, (None, None))
        if ah is None:
            return False
        if quantize_2(eh) != quantize_2(ah):
            return False
        if quantize_2(ea) != quantize_2(aa):
            return False
    return True

# Load inputs
project_spec_path = os.path.join(input_dir, "project_spec.json")
tasks_csv_path = os.path.join(input_dir, "tasks.csv")
milestones_csv_path = os.path.join(input_dir, "milestones.csv")
timesheet_items_path = os.path.join(input_dir, "timesheet_items.jsonl")

project_spec = None
tasks_rows: List[Dict[str, str]] = []
milestones_rows: List[Dict[str, str]] = []
timesheet_items: List[Dict[str, object]] = []

try:
    if os.path.isfile(project_spec_path):
        project_spec = read_json_file(project_spec_path)
except Exception:
    project_spec = None

try:
    if os.path.isfile(tasks_csv_path):
        tasks_rows = read_csv(tasks_csv_path)
except Exception:
    tasks_rows = []

try:
    if os.path.isfile(milestones_csv_path):
        milestones_rows = read_csv(milestones_csv_path)
except Exception:
    milestones_rows = []

try:
    if os.path.isfile(timesheet_items_path):
        timesheet_items = read_jsonl_file(timesheet_items_path)
except Exception:
    timesheet_items = []

# Precompute expected aggregates and structures
# Tasks set and dependencies from input (for validation against gantt.json and plan references)
task_names_set: Set[str] = set()
task_deps_from_input: Dict[str, List[str]] = {}
task_dates_from_input: Dict[str, Tuple[str, str]] = {}
assignee_hours: Dict[str, Decimal] = {}

for row in tasks_rows:
    tname = row.get("task_name", "").strip()
    if not tname:
        continue
    task_names_set.add(tname)
    dep_str = row.get("depends_on", "")
    deps_list = split_depends(dep_str)
    # Only keep deps that reference some task (we will validate existence later)
    task_deps_from_input[tname] = deps_list
    start_date = row.get("start_date", "")
    end_date = row.get("end_date", "")
    task_dates_from_input[tname] = (start_date, end_date)
    assigned_to = (row.get("assigned_to") or "").strip()
    est_hours = parse_decimal_safe(row.get("estimated_hours", "0"))
    if assigned_to:
        assignee_hours[assigned_to] = assignee_hours.get(assigned_to, Decimal("0")) + (est_hours if est_hours is not None else Decimal("0"))

# Expected billing summary from timesheet items
expected_billing: Dict[str, Tuple[Decimal, Decimal]] = {}
for it in timesheet_items:
    emp = str(it.get("employee_id", "")).strip()
    if not emp:
        # Skip malformed
        continue
    hours = parse_decimal_safe(it.get("hours", "0"))
    rate = parse_decimal_safe(it.get("billing_rate", "0"))
    curr_hours, curr_amount = expected_billing.get(emp, (Decimal("0"), Decimal("0")))
    curr_hours += hours
    curr_amount += (hours * rate)
    expected_billing[emp] = (quantize_2(curr_hours), quantize_2(curr_amount))

# Validate project_load_plan.jsonl
pl_path = os.path.join(output_dir, "project_load_plan.jsonl")
pl_objs: List[dict] = []
if os.path.isfile(pl_path):
    try:
        pl_objs = read_jsonl_file(pl_path)
        checks["has_project_load_plan"] = True
    except Exception:
        pl_objs = []
        checks["has_project_load_plan"] = False

if checks["has_project_load_plan"]:
    # Filter by action/type
    def get_action(obj):
        return obj.get("action") or obj.get("type") or ""

    # Remove empty/None objects just in case
    pl_objs = [o for o in pl_objs if isinstance(o, dict) and o]

    # Order check: expected groups: project, tasks..., milestones..., timesheets...
    actions_seq = [get_action(o) for o in pl_objs]
    # Count objects by type
    proj_indices = [i for i, a in enumerate(actions_seq) if a == "add-project"]
    task_indices = [i for i, a in enumerate(actions_seq) if a == "add-task"]
    milestone_indices = [i for i, a in enumerate(actions_seq) if a == "add-milestone"]
    timesheet_indices = [i for i, a in enumerate(actions_seq) if a == "add-timesheet"]

    # First line must be add-project
    if len(pl_objs) > 0 and get_action(pl_objs[0]) == "add-project":
        # Validate project fields match spec
        pobj = pl_objs[0]
        if project_spec is not None:
            expected_name = project_spec.get("name")
            expected_company_id = project_spec.get("company_id")
            expected_project_type = project_spec.get("project_type")
            if (
                pobj.get("name") == expected_name
                and pobj.get("company_id") == expected_company_id
                and pobj.get("project_type") == expected_project_type
            ):
                checks["pl_first_line_add_project_matches"] = True
        else:
            # If no project_spec provided, cannot match; requirement ties to provided presence; keep False
            pass

    # Ordering correctness: add-project first, then all tasks, then milestones, then timesheets
    def is_grouped_in_order(indices_list_groups: List[List[int]]) -> bool:
        # All indices within each group should be increasing; and last index of group i < first index of group i+1 (if both non-empty)
        prev_last = -1
        for idxs in indices_list_groups:
            if not idxs:
                # Empty group is okay
                continue
            # Ensure increasing
            if any(a > b for a, b in zip(idxs, idxs[1:])):
                return False
            if prev_last >= 0 and idxs[0] <= prev_last:
                return False
            prev_last = idxs[-1]
        return True

    order_ok = False
    if proj_indices == [0] and is_grouped_in_order([task_indices, milestone_indices, timesheet_indices]):
        # Also ensure no other actions in between (i.e., indices cover all)
        covered = set(proj_indices + task_indices + milestone_indices + timesheet_indices)
        if covered == set(range(len(pl_objs))):
            order_ok = True
    checks["pl_order_correct"] = order_ok

    # Task validations in plan
    plan_task_objs = [pl_objs[i] for i in task_indices]
    if len(plan_task_objs) == len(tasks_rows):
        checks["pl_tasks_count_correct"] = True

    # Validate task dependencies reference valid task names and acyclic
    plan_task_names = [o.get("name") for o in plan_task_objs if isinstance(o.get("name"), str)]
    plan_task_name_set = set([n for n in plan_task_names if n])
    # Map depends_on_names arrays
    plan_edges: Dict[str, List[str]] = {}
    dep_names_all_valid = True
    for o in plan_task_objs:
        name = o.get("name")
        deps = o.get("depends_on_names")
        if name is None or not isinstance(deps, list):
            dep_names_all_valid = False
            break
        # Every depends_on_names entry must match another task_name from tasks.csv
        dep_list = []
        for d in deps:
            if not isinstance(d, str):
                dep_names_all_valid = False
                break
            if d not in task_names_set:
                dep_names_all_valid = False
                break
            dep_list.append(d)
        if not dep_names_all_valid:
            break
        plan_edges[name] = dep_list
    if dep_names_all_valid:
        checks["pl_task_deps_ref_valid"] = True
        # Acyclic?
        graph = build_graph(plan_task_name_set, plan_edges)
        if not has_cycle(graph):
            checks["pl_task_acyclic"] = True

    # Milestones validations
    plan_milestone_objs = [pl_objs[i] for i in milestone_indices]
    if len(plan_milestone_objs) == len(milestones_rows):
        checks["pl_milestones_count_correct"] = True
    # Compare that each milestone in input has matching entry by milestone_name and target_date
    mil_input_pairs = []
    for r in milestones_rows:
        mil_input_pairs.append((r.get("milestone_name", "").strip(), r.get("target_date", "").strip()))
    mil_plan_pairs = []
    for o in plan_milestone_objs:
        mil_plan_pairs.append((str(o.get("milestone_name", "")).strip(), str(o.get("target_date", "")).strip()))
    if mil_input_pairs:
        if set(mil_input_pairs) == set(mil_plan_pairs) and len(mil_input_pairs) == len(mil_plan_pairs):
            checks["pl_milestones_match_values"] = True
    else:
        # If no milestones input, require zero milestones in plan and mark match true
        if len(plan_milestone_objs) == 0:
            checks["pl_milestones_match_values"] = True

    # Timesheets validations
    plan_timesheet_objs = [pl_objs[i] for i in timesheet_indices]
    unique_employees = sorted(set([str(i.get("employee_id", "")).strip() for i in timesheet_items if str(i.get("employee_id", "")).strip() != ""]))
    if len(plan_timesheet_objs) == len(unique_employees):
        checks["pl_timesheet_count_correct"] = True

    # Check items array and totals
    timesheets_items_ok = True
    timesheets_totals_ok = True

    # Validate that each timesheet is grouped by employee_id (one per employee)
    # This script cannot enforce "exactly one per" beyond count, but we will ensure each employee_id appears once
    plan_emp_ids = [str(o.get("employee_id", "")).strip() for o in plan_timesheet_objs]
    if set(plan_emp_ids) != set(unique_employees):
        timesheets_items_ok = False
        timesheets_totals_ok = False
    else:
        # Build mapping of employee to its items from plan
        for o in plan_timesheet_objs:
            emp = str(o.get("employee_id", "")).strip()
            items = o.get("items")
            if not isinstance(items, list):
                timesheets_items_ok = False
                timesheets_totals_ok = False
                break
            # Items must contain project_name, task_name, hours, billing_rate, activity_type and task_name must exist in tasks.csv
            for it in items:
                if not isinstance(it, dict):
                    timesheets_items_ok = False
                    break
                for key in ["project_name", "task_name", "hours", "billing_rate", "activity_type"]:
                    if key not in it:
                        timesheets_items_ok = False
                        break
                if timesheets_items_ok is False:
                    break
                # Validate task_name exists in tasks.csv
                tnm = str(it.get("task_name", "")).strip()
                if tnm not in task_names_set:
                    timesheets_items_ok = False
                    break
            if timesheets_items_ok is False:
                timesheets_totals_ok = False
                break
            # Compute total billing amount and compare to provided
            comp_total = Decimal("0")
            for it in items:
                h = parse_decimal_safe(it.get("hours", "0"))
                r = parse_decimal_safe(it.get("billing_rate", "0"))
                comp_total += (h * r)
            comp_total_q = quantize_2(comp_total)
            provided_total = parse_decimal_safe(o.get("total_billing_amount", "0"))
            provided_total_q = quantize_2(provided_total)
            if comp_total_q != provided_total_q:
                timesheets_totals_ok = False
                # Do not break to catch other potential issues, but it's enough to fail
        # end for each plan timesheet

    if timesheets_items_ok:
        checks["pl_timesheet_items_fields_and_task_names_valid"] = True
    if timesheets_totals_ok:
        checks["pl_timesheet_totals_match"] = True

# Validate gantt_data.json
gantt_path = os.path.join(output_dir, "gantt_data.json")
gantt_obj = None
if os.path.isfile(gantt_path):
    try:
        gantt_obj = read_json_file(gantt_path)
        checks["has_gantt"] = True
    except Exception:
        gantt_obj = None

if checks["has_gantt"] and isinstance(gantt_obj, dict):
    # project_name must be present
    if project_spec is not None and gantt_obj.get("project_name") == project_spec.get("name"):
        checks["gantt_project_name_match"] = True
    # tasks array
    tasks_list = gantt_obj.get("tasks")
    if isinstance(tasks_list, list):
        # There must be one entry per task in tasks.csv
        gantt_tasks_by_name = {}
        all_have_required = True
        for t in tasks_list:
            if not isinstance(t, dict):
                all_have_required = False
                break
            name = t.get("name")
            sd = t.get("start_date")
            ed = t.get("end_date")
            deps = t.get("depends_on")
            if not isinstance(name, str) or not isinstance(sd, str) or not isinstance(ed, str) or not isinstance(deps, list):
                all_have_required = False
                break
            gantt_tasks_by_name[name] = (sd, ed, deps)
        if all_have_required and set(gantt_tasks_by_name.keys()) == task_names_set:
            checks["gantt_tasks_cover_all"] = True
            # Dates match input
            dates_match = True
            for name, (sd, ed, _) in gantt_tasks_by_name.items():
                in_sd, in_ed = task_dates_from_input.get(name, ("", ""))
                if sd != in_sd or ed != in_ed:
                    dates_match = False
                    break
            if dates_match:
                checks["gantt_dates_match"] = True
            # Dependency names valid and acyclic
            deps_valid = True
            edges = {}
            for name, (_, _, deps) in gantt_tasks_by_name.items():
                for d in deps:
                    if d not in gantt_tasks_by_name:
                        deps_valid = False
                        break
                edges[name] = deps
                if not deps_valid:
                    break
            if deps_valid:
                checks["gantt_dep_names_valid"] = True
                graph = build_graph(set(gantt_tasks_by_name.keys()), edges)
                if not has_cycle(graph):
                    checks["gantt_acyclic"] = True

# Validate billing_summary.csv
billing_csv_path = os.path.join(output_dir, "billing_summary.csv")
if os.path.isfile(billing_csv_path):
    checks["has_billing_csv"] = True
    try:
        billing_rows = read_csv(billing_csv_path)
        # Header validation: employee_id,total_hours,total_amount
        header_ok = True
        # DictReader already parsed headers; ensure columns exist
        for col in ["employee_id", "total_hours", "total_amount"]:
            if not (len(billing_rows) == 0 or col in billing_rows[0] or all(col in r for r in billing_rows)):
                header_ok = False
                break
        if header_ok:
            # Compare unordered with expected_billing
            # expected_billing values already quantized
            if compare_unordered_csv(expected_billing, billing_rows, "total_hours", "total_amount"):
                checks["billing_totals_match"] = True
    except Exception:
        pass

# Validate resource_utilization.csv
resource_csv_path = os.path.join(output_dir, "resource_utilization.csv")
if os.path.isfile(resource_csv_path):
    checks["has_resource_csv"] = True
    try:
        resource_rows = read_csv(resource_csv_path)
        # Header validation: employee_id,estimated_hours
        header_ok = True
        for col in ["employee_id", "estimated_hours"]:
            if not (len(resource_rows) == 0 or col in resource_rows[0] or all(col in r for r in resource_rows)):
                header_ok = False
                break
        if header_ok:
            # Build expected map of employee_id -> (hours, amount?) Here only hours
            expected_res: Dict[str, Tuple[Decimal, Decimal]] = {}
            for emp, hrs in assignee_hours.items():
                expected_res[emp] = (quantize_2(hrs), Decimal("0"))
            # Build actual map (hours only)
            actual_map: Dict[str, Decimal] = {}
            for r in resource_rows:
                emp = r.get("employee_id", "").strip()
                if not emp:
                    continue
                hrs = parse_decimal_safe(r.get("estimated_hours", "0"))
                actual_map[emp] = quantize_2(hrs)
            # Compare keys
            if set(expected_res.keys()) == set(actual_map.keys()):
                # Compare values
                ok = True
                for emp, (eh, _) in expected_res.items():
                    if quantize_2(eh) != quantize_2(actual_map.get(emp, Decimal("0"))):
                        ok = False
                        break
                if ok:
                    checks["resource_totals_match"] = True
    except Exception:
        pass

# Validate submission_checklist.md
checklist_path = os.path.join(output_dir, "submission_checklist.md")
if os.path.isfile(checklist_path):
    checks["has_checklist"] = True
    try:
        with open(checklist_path, "r", encoding="utf-8") as f:
            content = f.read()
        low = content.lower()
        # Lifecycle phrase
        if "draft -> submitted -> billed".lower() in low:
            checks["cl_has_lifecycle_phrase"] = True
        # Lines with confirm and submit
        for line in low.splitlines():
            if "confirm" in line and "submit" in line:
                checks["cl_has_confirm_submit"] = True
                break
        # Lines with confirm and bill
        for line in low.splitlines():
            if "confirm" in line and "bill" in line:
                checks["cl_has_confirm_bill"] = True
                break
        # Sentence stating "Never confirm" and mentioning adding tasks and listing records or reports
        never_ok = False
        for line in low.splitlines():
            if "never confirm" in line and (("adding tasks" in line) or ("add tasks" in line)) and (("listing records" in line) or ("reports" in line)):
                never_ok = True
                break
        if never_ok:
            checks["cl_has_never_confirm_line"] = True
        # Contains phrase "circular dependency"
        if "circular dependency" in low:
            checks["cl_has_circular_dependency_phrase"] = True
    except Exception:
        pass

# Compute reward as fraction of passed checks
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)

# No-op baseline: if output folder is missing or empty, reward must be 0.0
# We consider no-op when none of the "has_*" artifacts exist.
has_any_output_artifact = any([
    checks["has_project_load_plan"],
    checks["has_gantt"],
    checks["has_billing_csv"],
    checks["has_resource_csv"],
    checks["has_checklist"]
])

if not has_any_output_artifact:
    reward = 0.0
else:
    # Reward as proportion of passed checks
    reward = passed_checks / total_checks
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, float(reward)))

# Print exactly one JSON object as last line
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))