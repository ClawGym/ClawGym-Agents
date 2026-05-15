import json
import sys
import csv
from pathlib import Path
from itertools import combinations


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_csv_load(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _to_int(s):
    try:
        return int(s)
    except Exception:
        return None


def _parse_simple_yaml_mapping(lines):
    # Minimal YAML parser for simple nested dicts with scalar values.
    # Supports mappings with indentation using spaces and simple scalars (ints/strings).
    root = {}
    stack = [(-1, root)]  # list of tuples (indent_level, current_dict)
    for raw_line in lines:
        if not raw_line.strip():
            continue
        # ignore comments
        if raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        # Pop to correct indentation level
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1] if stack else root

        if ":" in line:
            key_part, value_part = line.split(":", 1)
            key = key_part.strip()
            value = value_part.strip()
            if value == "":
                # Start of a new nested mapping
                new_map = {}
                current_dict[key] = new_map
                stack.append((indent, new_map))
            else:
                # Scalar value
                val = value
                # Try to parse int
                iv = None
                try:
                    iv = int(val)
                except Exception:
                    iv = None
                if iv is not None:
                    current_dict[key] = iv
                else:
                    # leave as string, but strip quotes if any
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    current_dict[key] = val
        else:
            # Unexpected line format; ignore
            continue
    return root


def _load_constraints_yaml(path: Path):
    text = _read_text(path)
    if text is None:
        return None
    try:
        lines = text.splitlines()
        data = _parse_simple_yaml_mapping(lines)
        # Basic validation for expected keys
        if not isinstance(data, dict):
            return None
        if "budget" not in data or "max_projects" not in data:
            return None
        budget = data.get("budget", {})
        if not isinstance(budget, dict):
            return None
        if "max_cost" not in budget or "max_hours" not in budget:
            return None
        # Ensure ints where expected
        try:
            budget["max_cost"] = int(budget["max_cost"])
            budget["max_hours"] = int(budget["max_hours"])
            data["max_projects"] = int(data["max_projects"])
        except Exception:
            return None
        # Category requirements may be nested
        cat_req = data.get("category_requirements", {})
        if isinstance(cat_req, dict):
            min_by_cat = cat_req.get("min_by_category", {})
            # convert values to ints
            if isinstance(min_by_cat, dict):
                clean = {}
                for k, v in min_by_cat.items():
                    try:
                        clean[k] = int(v)
                    except Exception:
                        return None
                data["category_requirements"]["min_by_category"] = clean
            else:
                data["category_requirements"]["min_by_category"] = {}
        else:
            data["category_requirements"] = {"min_by_category": {}}
        return data
    except Exception:
        return None


def _parse_projects_csv(path: Path):
    rows = _safe_csv_load(path)
    if rows is None:
        return None
    projects = []
    required = {"project_id", "profit", "cost", "hours", "category"}
    if not rows:
        return None
    if not required.issubset(set(rows[0].keys())):
        return None
    for r in rows:
        pid = r.get("project_id")
        profit = _to_int(r.get("profit"))
        cost = _to_int(r.get("cost"))
        hours = _to_int(r.get("hours"))
        cat = r.get("category")
        if pid is None or profit is None or cost is None or hours is None or cat is None:
            return None
        projects.append({
            "project_id": pid,
            "profit": profit,
            "cost": cost,
            "hours": hours,
            "category": cat
        })
    return projects


def _parse_rules(path: Path):
    text = _read_text(path)
    if text is None:
        return None
    blacklist = set()
    incompatible = []  # list of (A,B)
    dependencies = []  # list of (A,B) meaning A depends on B
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("BLACKLIST:"):
            part = line.split(":", 1)[1].strip()
            if part:
                blacklist.add(part)
        elif line.upper().startswith("PAIR_INCOMPATIBLE:"):
            part = line.split(":", 1)[1].strip()
            if "," in part:
                a, b = [x.strip() for x in part.split(",", 1)]
                if a and b:
                    incompatible.append((a, b))
        elif line.upper().startswith("DEPENDENCY:"):
            part = line.split(":", 1)[1].strip()
            if "->" in part:
                a, b = [x.strip() for x in part.split("->", 1)]
                if a and b:
                    dependencies.append((a, b))
        else:
            # Unknown rule; ignore
            continue
    return {
        "blacklist": blacklist,
        "incompatible": incompatible,
        "dependencies": dependencies,
    }


def _parse_selection_csv(path: Path):
    rows = _safe_csv_load(path)
    if rows is None:
        return None
    required = {"project_id", "selected", "profit", "cost", "hours", "category"}
    if not rows or not required.issubset(set(rows[0].keys())):
        return None
    sel = []
    for r in rows:
        pid = r.get("project_id")
        sel_flag = _to_int(r.get("selected"))
        profit = _to_int(r.get("profit"))
        cost = _to_int(r.get("cost"))
        hours = _to_int(r.get("hours"))
        cat = r.get("category")
        if pid is None or sel_flag is None or profit is None or cost is None or hours is None or cat is None:
            return None
        if sel_flag not in (0, 1):
            return None
        sel.append({
            "project_id": pid,
            "selected": sel_flag,
            "profit": profit,
            "cost": cost,
            "hours": hours,
            "category": cat
        })
    return sel


def _selection_matches_projects(selection_rows, projects):
    # Validate that selection.csv corresponds exactly to the projects.csv values per row
    proj_by_id = {p["project_id"]: p for p in projects}
    sel_ids = [r["project_id"] for r in selection_rows]
    proj_ids = [p["project_id"] for p in projects]

    # Ensure sets are equal and counts match
    if set(sel_ids) != set(proj_ids):
        return False
    if len(selection_rows) != len(projects):
        return False

    # Check each row for attribute matching
    for r in selection_rows:
        pid = r["project_id"]
        if pid not in proj_by_id:
            return False
        p = proj_by_id[pid]
        if r["profit"] != p["profit"]:
            return False
        if r["cost"] != p["cost"]:
            return False
        if r["hours"] != p["hours"]:
            return False
        if r["category"] != p["category"]:
            return False
    return True


def _compute_selection_aggregates(selection_rows):
    total_selected = sum(1 for r in selection_rows if r["selected"] == 1)
    total_profit = sum(r["profit"] for r in selection_rows if r["selected"] == 1)
    total_cost = sum(r["cost"] for r in selection_rows if r["selected"] == 1)
    total_hours = sum(r["hours"] for r in selection_rows if r["selected"] == 1)
    category_counts = {}
    for r in selection_rows:
        if r["selected"] == 1:
            cat = r["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
    return {
        "total_selected": total_selected,
        "total_profit": total_profit,
        "total_cost": total_cost,
        "total_hours": total_hours,
        "category_counts": category_counts,
    }


def _feasible(selection_rows, constraints, rules, projects_by_id):
    if constraints is None or rules is None or selection_rows is None:
        return False
    budget = constraints.get("budget", {})
    max_cost = budget.get("max_cost")
    max_hours = budget.get("max_hours")
    max_projects = constraints.get("max_projects")
    min_by_category = constraints.get("category_requirements", {}).get("min_by_category", {})

    sel_set = {r["project_id"] for r in selection_rows if r["selected"] == 1}
    # Budget, hours, project count
    totals = _compute_selection_aggregates(selection_rows)
    if max_cost is None or max_hours is None or max_projects is None:
        return False
    if totals["total_cost"] > max_cost:
        return False
    if totals["total_hours"] > max_hours:
        return False
    if totals["total_selected"] > max_projects:
        return False

    # Category minimums
    if isinstance(min_by_category, dict):
        # Count by category across selected
        counts = {}
        for pid in sel_set:
            cat = projects_by_id[pid]["category"]
            counts[cat] = counts.get(cat, 0) + 1
        for cat, minval in min_by_category.items():
            try:
                minv = int(minval)
            except Exception:
                return False
            if counts.get(cat, 0) < minv:
                return False

    # Rules
    blacklist = rules.get("blacklist", set())
    incompatible = rules.get("incompatible", [])
    dependencies = rules.get("dependencies", [])
    # BLACKLIST
    if any(pid in sel_set for pid in blacklist):
        return False
    # PAIR_INCOMPATIBLE
    for a, b in incompatible:
        if a in sel_set and b in sel_set:
            return False
    # DEPENDENCY A->B means if A selected, B must be selected
    for a, b in dependencies:
        if a in sel_set and b not in sel_set:
            return False

    return True


def _bruteforce_optimal(projects, constraints, rules):
    # Compute the maximum total profit over all feasible subsets
    if projects is None or constraints is None or rules is None:
        return None
    n = len(projects)
    # Safety guard to avoid explosion
    if n > 22:
        return None
    ids = [p["project_id"] for p in projects]
    profits = [p["profit"] for p in projects]
    costs = [p["cost"] for p in projects]
    hours = [p["hours"] for p in projects]
    cats = [p["category"] for p in projects]
    budget = constraints.get("budget", {})
    max_cost = budget.get("max_cost")
    max_hours = budget.get("max_hours")
    max_projects = constraints.get("max_projects")
    min_by_category = constraints.get("category_requirements", {}).get("min_by_category", {})
    if max_cost is None or max_hours is None or max_projects is None:
        return None

    blacklist = set(rules.get("blacklist", set()))
    incompatible = rules.get("incompatible", [])
    dependencies = rules.get("dependencies", [])

    best_profit = None

    # Pre-compute category requirement keys
    req_cats = list(min_by_category.keys()) if isinstance(min_by_category, dict) else []

    # Iterate over all subsets by size to allow early pruning of max_projects
    for k in range(0, min(max_projects, n) + 1):
        for combo in combinations(range(n), k):
            # Early prune by blacklist
            if any(ids[i] in blacklist for i in combo):
                continue
            # Incompatibles
            violates_incompat = False
            present = set(ids[i] for i in combo)
            for a, b in incompatible:
                if a in present and b in present:
                    violates_incompat = True
                    break
            if violates_incompat:
                continue
            # Dependencies
            dep_ok = True
            for a, b in dependencies:
                if a in present and b not in present:
                    dep_ok = False
                    break
            if not dep_ok:
                continue
            # Budgets and hours
            sum_cost = sum(costs[i] for i in combo)
            if sum_cost > max_cost:
                continue
            sum_hours = sum(hours[i] for i in combo)
            if sum_hours > max_hours:
                continue
            # Category mins
            if req_cats:
                count_by_cat = {}
                for i in combo:
                    c = cats[i]
                    count_by_cat[c] = count_by_cat.get(c, 0) + 1
                ok_cat = True
                for c in req_cats:
                    minv = int(min_by_category.get(c, 0))
                    if count_by_cat.get(c, 0) < minv:
                        ok_cat = False
                        break
                if not ok_cat:
                    continue
            # Profit
            p = sum(profits[i] for i in combo)
            if best_profit is None or p > best_profit:
                best_profit = p

    if best_profit is None:
        # If no feasible subset found, the optimal profit is 0 if empty subset allowed and feasible; check feasibility of empty set
        # Empty set feasibility:
        empty_feasible = True
        # Check category minimums for empty set
        if isinstance(min_by_category, dict):
            for c, minv in min_by_category.items():
                if int(minv) > 0:
                    empty_feasible = False
                    break
        if empty_feasible and 0 <= max_projects and 0 <= max_cost and 0 <= max_hours:
            best_profit = 0
        else:
            best_profit = 0
    return best_profit


def _float_close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "deliverable_scripts_present": 0.0,
        "output_selection_csv_present_and_correct": 0.0,
        "selection_feasible": 0.0,
        "summary_json_correct": 0.0,
        "validation_json_fields_and_truth": 0.0,
        "selection_is_optimal": 0.0,
    }

    # Check scripts existence
    solve_script = workspace / "solve_portfolio.py"
    validate_script = workspace / "tests" / "validate.py"
    if solve_script.is_file() and validate_script.is_file():
        scores["deliverable_scripts_present"] = 1.0

    # Load inputs
    projects_path = workspace / "input" / "projects.csv"
    constraints_path = workspace / "input" / "constraints.yaml"
    rules_path = workspace / "input" / "exclusions.txt"

    projects = _parse_projects_csv(projects_path) if projects_path.exists() else None
    constraints = _load_constraints_yaml(constraints_path) if constraints_path.exists() else None
    rules = _parse_rules(rules_path) if rules_path.exists() else None

    # Outputs
    selection_path = workspace / "output" / "selection.csv"
    summary_path = workspace / "output" / "summary.json"
    validation_path = workspace / "output" / "validation.json"

    selection_rows = _parse_selection_csv(selection_path) if selection_path.exists() else None

    # Validate selection.csv structure and consistency with projects
    selection_ok = False
    projects_by_id = {}
    if projects is not None:
        projects_by_id = {p["project_id"]: p for p in projects}
    if selection_rows is not None and projects is not None:
        if _selection_matches_projects(selection_rows, projects):
            selection_ok = True
    if selection_ok:
        scores["output_selection_csv_present_and_correct"] = 1.0

    # Feasibility of selection
    feasible_ok = False
    if selection_ok and constraints is not None and rules is not None:
        feasible_ok = _feasible(selection_rows, constraints, rules, projects_by_id)
    if feasible_ok:
        scores["selection_feasible"] = 1.0

    # Compute brute-force optimal profit
    optimal_profit = _bruteforce_optimal(projects, constraints, rules)

    # Selection is optimal
    if selection_ok and optimal_profit is not None:
        agg = _compute_selection_aggregates(selection_rows)
        if agg["total_profit"] == optimal_profit:
            scores["selection_is_optimal"] = 1.0

    # Validate summary.json content
    summary_ok = False
    if summary_path.exists() and selection_ok and constraints is not None and projects is not None:
        summary = _safe_json_load(summary_path)
        if isinstance(summary, dict):
            required_fields = [
                "total_candidates",
                "total_selected",
                "total_profit_selected",
                "total_cost_selected",
                "total_hours_selected",
                "avg_profit_all",
                "avg_cost_all",
                "category_counts_selected",
                "budget_remaining",
            ]
            if all(k in summary for k in required_fields):
                # Compute expected
                agg = _compute_selection_aggregates(selection_rows)
                total_candidates = len(projects)
                avg_profit_all = sum(p["profit"] for p in projects) / float(total_candidates) if total_candidates > 0 else 0.0
                avg_cost_all = sum(p["cost"] for p in projects) / float(total_candidates) if total_candidates > 0 else 0.0
                budget_remaining = {
                    "cost": constraints["budget"]["max_cost"] - agg["total_cost"],
                    "hours": constraints["budget"]["max_hours"] - agg["total_hours"],
                }

                # Validate values with strict ints and tolerant floats
                checks = []
                checks.append(summary.get("total_candidates") == total_candidates)
                checks.append(summary.get("total_selected") == agg["total_selected"])
                checks.append(summary.get("total_profit_selected") == agg["total_profit"])
                checks.append(summary.get("total_cost_selected") == agg["total_cost"])
                checks.append(summary.get("total_hours_selected") == agg["total_hours"])
                checks.append(_float_close(summary.get("avg_profit_all"), avg_profit_all))
                checks.append(_float_close(summary.get("avg_cost_all"), avg_cost_all))
                # Category counts: allow omission of zero-count categories
                cat_counts = summary.get("category_counts_selected")
                if isinstance(cat_counts, dict):
                    cats_with_pos = {k: v for k, v in agg["category_counts"].items() if v > 0}
                    # All positive counts must be present and equal
                    cat_ok = all(cat_counts.get(k) == v for k, v in cats_with_pos.items())
                    # Any categories in summary that are not in projects should not matter; ignore
                else:
                    cat_ok = False
                checks.append(cat_ok)
                # Budget remaining
                br = summary.get("budget_remaining")
                if isinstance(br, dict):
                    br_ok = (br.get("cost") == budget_remaining["cost"]) and (br.get("hours") == budget_remaining["hours"])
                else:
                    br_ok = False
                checks.append(br_ok)

                if all(checks):
                    summary_ok = True
    if summary_ok:
        scores["summary_json_correct"] = 1.0

    # Validate validation.json content
    validation_ok = False
    if validation_path.exists() and selection_ok:
        validation = _safe_json_load(validation_path)
        if isinstance(validation, dict):
            fields_ok = all(k in validation for k in ["enumerated_optimal_profit", "solver_profit", "profits_match", "constraints_satisfied"])
            if fields_ok:
                agg = _compute_selection_aggregates(selection_rows)
                solver_profit_ok = validation.get("solver_profit") == agg["total_profit"]
                profits_match_true = validation.get("profits_match") is True
                constraints_true = validation.get("constraints_satisfied") is True
                enumerated_ok = True
                if optimal_profit is not None:
                    enumerated_ok = validation.get("enumerated_optimal_profit") == optimal_profit
                else:
                    # If we couldn't compute optimal, at least check it's a number
                    enumerated_ok = isinstance(validation.get("enumerated_optimal_profit"), (int, float))
                if solver_profit_ok and profits_match_true and constraints_true and enumerated_ok:
                    validation_ok = True
    if validation_ok:
        scores["validation_json_fields_and_truth"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()