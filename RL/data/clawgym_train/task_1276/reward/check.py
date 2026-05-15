import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_int(n):
    try:
        return float(n).is_integer()
    except Exception:
        return False

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def dir_has_any_file(d):
    if not os.path.isdir(d):
        return False
    for root, _, files in os.walk(d):
        for fn in files:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_any_output": False,

        # plan.json
        "plan_exists": False,
        "plan_structure_valid": False,
        "plan_quick_wins_count": False,
        "plan_quick_wins_constraints": False,
        "plan_medium_count": False,
        "plan_medium_constraints": False,
        "plan_strategic_count": False,
        "plan_strategic_constraints": False,

        # analysis_summary.md
        "analysis_exists_nonempty": False,
        "analysis_has_headers": False,
        "analysis_has_cubic_utilization_line": False,
        "analysis_has_travel_time_line": False,
        "analysis_has_automation_keyword": False,
        "analysis_has_DART_and_cycle_count": False,

        # cost_per_order.csv
        "cost_csv_valid_header": False,
        "cost_csv_required_rows": False,
        "cost_csv_bases_exact": False,
        "cost_csv_costs_in_range": False,

        # abc_summary.json
        "abc_json_valid": False,
        "abc_percent_ranges": False,
        "abc_sum_approx_100": False,
        "abc_A_items_near_packstations_true": False,

        # assumptions.json
        "assumptions_json_valid": False,
        "assumptions_has_min_items": False,
        "assumptions_non_empty_strings": False,

        # rubric_notes.md
        "rubric_notes_exists": False,
        "rubric_notes_len": False,
        "rubric_notes_contains_keywords": False,
    }

    # Baseline any output?
    checks["has_any_output"] = dir_has_any_file(output_dir)

    # 1) plan.json
    plan_path = os.path.join(output_dir, "plan.json")
    plan = load_json(plan_path)
    if plan is not None and isinstance(plan, dict):
        checks["plan_exists"] = True
        # Structure keys
        required_keys = ["quick_wins", "medium_term", "strategic_investments"]
        if all(k in plan and isinstance(plan[k], list) for k in required_keys):
            checks["plan_structure_valid"] = True

            # Quick wins
            qw = plan["quick_wins"]
            if isinstance(qw, list) and len(qw) >= 4:
                checks["plan_quick_wins_count"] = True
                qw_ok = True
                for item in qw:
                    if not isinstance(item, dict):
                        qw_ok = False
                        break
                    title = item.get("title")
                    roi = item.get("expected_roi_percent")
                    cost = item.get("investment_cost_usd")
                    time = item.get("timeline_days")
                    resources = item.get("resources")
                    if not (isinstance(title, str) and title.strip()):
                        qw_ok = False; break
                    if not (isinstance(roi, (int, float)) and roi > 0):
                        qw_ok = False; break
                    if not (isinstance(cost, (int, float)) and cost <= 5000):
                        qw_ok = False; break
                    if not (isinstance(time, int) and 0 <= time <= 30):
                        qw_ok = False; break
                    if not (isinstance(resources, list) and len(resources) >= 1):
                        qw_ok = False; break
                if qw_ok:
                    checks["plan_quick_wins_constraints"] = True

            # Medium term
            mt = plan["medium_term"]
            if isinstance(mt, list) and len(mt) >= 3:
                checks["plan_medium_count"] = True
                mt_ok = True
                for item in mt:
                    if not isinstance(item, dict):
                        mt_ok = False
                        break
                    title = item.get("title")
                    roi = item.get("expected_roi_percent")
                    cost = item.get("investment_cost_usd")
                    time = item.get("timeline_days")
                    resources = item.get("resources")
                    if not (isinstance(title, str) and title.strip()):
                        mt_ok = False; break
                    if not (isinstance(roi, (int, float)) and roi > 0):
                        mt_ok = False; break
                    if not (isinstance(cost, (int, float)) and 5000 <= cost <= 50000):
                        mt_ok = False; break
                    if not (isinstance(time, int) and 30 <= time <= 90):
                        mt_ok = False; break
                    if not (isinstance(resources, list) and len(resources) >= 1):
                        mt_ok = False; break
                if mt_ok:
                    checks["plan_medium_constraints"] = True

            # Strategic investments
            si = plan["strategic_investments"]
            if isinstance(si, list) and len(si) >= 3:
                checks["plan_strategic_count"] = True
                si_ok = True
                for item in si:
                    if not isinstance(item, dict):
                        si_ok = False
                        break
                    title = item.get("title")
                    roi = item.get("expected_roi_percent")
                    cost = item.get("investment_cost_usd")
                    time = item.get("timeline_days")
                    resources = item.get("resources")
                    if not (isinstance(title, str) and title.strip()):
                        si_ok = False; break
                    if not (isinstance(roi, (int, float)) and roi > 0):
                        si_ok = False; break
                    if not (isinstance(cost, (int, float)) and cost >= 50000):
                        si_ok = False; break
                    if not (isinstance(time, int) and time >= 90):
                        si_ok = False; break
                    if not (isinstance(resources, list) and len(resources) >= 1):
                        si_ok = False; break
                if si_ok:
                    checks["plan_strategic_constraints"] = True

    # 2) analysis_summary.md
    analysis_path = os.path.join(output_dir, "analysis_summary.md")
    analysis_content = read_text(analysis_path)
    if analysis_content is not None:
        if analysis_content.strip():
            checks["analysis_exists_nonempty"] = True
            required_headers = [
                "Space Utilization Audit",
                "Pick Path Optimization",
                "Labor Productivity Metrics",
                "Inventory Accuracy",
                "Cost Per Order Analysis",
                "Automation ROI Calculator",
                "Safety & Compliance",
            ]
            if all(h in analysis_content for h in required_headers):
                checks["analysis_has_headers"] = True

            # Cubic utilization line
            # Pattern: Cubic utilization:\s*\d+(\.\d+)?%?
            if re.search(r"Cubic utilization:\s*\d+(\.\d+)?%?", analysis_content):
                checks["analysis_has_cubic_utilization_line"] = True

            # Travel time % of pick time: \s*\d+(\.\d+)?%
            if re.search(r"Travel time % of pick time:\s*\d+(\.\d+)?%", analysis_content):
                checks["analysis_has_travel_time_line"] = True

            # Automation keyword
            automation_keywords = ["pick-to-light", "conveyor", "AS/RS", "AMR", "AGV", "sortation"]
            if any(kw in analysis_content for kw in automation_keywords):
                checks["analysis_has_automation_keyword"] = True

            # Contains DART and cycle count
            if ("DART" in analysis_content) and ("cycle count" in analysis_content.lower()):
                checks["analysis_has_DART_and_cycle_count"] = True

    # 3) cost_per_order.csv
    cost_csv_path = os.path.join(output_dir, "cost_per_order.csv")
    if os.path.isfile(cost_csv_path):
        try:
            with open(cost_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["category", "basis", "cost_usd"]:
                    checks["cost_csv_valid_header"] = True
                    data_rows = rows[1:]
                    expected_categories = ["Receiving", "Storage", "Pick & Pack", "Shipping", "Returns"]
                    # Ensure exactly one row per category and exactly 5 rows
                    categories = [r[0] for r in data_rows if len(r) >= 3]
                    if len(data_rows) == 5 and set(categories) == set(expected_categories):
                        checks["cost_csv_required_rows"] = True
                        # Basis exact per category
                        basis_expected = {
                            "Receiving": "per unit",
                            "Storage": "per pallet-month",
                            "Pick & Pack": "per order",
                            "Shipping": "per order",
                            "Returns": "per return",
                        }
                        bases_ok = True
                        costs_ok = True
                        for r in data_rows:
                            if len(r) != 3:
                                bases_ok = False
                                costs_ok = False
                                break
                            cat, basis, cost_s = r
                            # Basis check
                            exp_basis = basis_expected.get(cat)
                            if exp_basis is None or basis != exp_basis:
                                bases_ok = False
                            # Cost ranges
                            cost = to_float(cost_s)
                            if cost is None:
                                costs_ok = False
                            else:
                                if cat == "Receiving":
                                    if not (0.30 <= cost <= 0.80): costs_ok = False
                                elif cat == "Storage":
                                    if not (8.00 <= cost <= 15.00): costs_ok = False
                                elif cat == "Pick & Pack":
                                    if not (1.50 <= cost <= 4.00): costs_ok = False
                                elif cat == "Shipping":
                                    if not (cost > 0.00): costs_ok = False
                                elif cat == "Returns":
                                    if not (5.00 <= cost <= 15.00): costs_ok = False
                        if bases_ok:
                            checks["cost_csv_bases_exact"] = True
                        if costs_ok:
                            checks["cost_csv_costs_in_range"] = True
        except Exception:
            pass

    # 4) abc_summary.json
    abc_path = os.path.join(output_dir, "abc_summary.json")
    abc = load_json(abc_path)
    if isinstance(abc, dict):
        # Validate presence and types
        if all(k in abc for k in ["A_percent", "B_percent", "C_percent", "A_items_near_packstations"]):
            a = abc.get("A_percent")
            b = abc.get("B_percent")
            c = abc.get("C_percent")
            near = abc.get("A_items_near_packstations")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and isinstance(c, (int, float)):
                checks["abc_json_valid"] = True
                # Ranges
                if (15 <= a <= 30) and (20 <= b <= 40) and (30 <= c <= 70):
                    checks["abc_percent_ranges"] = True
                # Sum approx 100 +/- 2.0
                total = a + b + c
                if abs(total - 100.0) <= 2.0:
                    checks["abc_sum_approx_100"] = True
                # Boolean true
                if isinstance(near, bool) and near is True:
                    checks["abc_A_items_near_packstations_true"] = True

    # 5) assumptions.json
    assumptions_path = os.path.join(output_dir, "assumptions.json")
    assumptions = load_json(assumptions_path)
    if isinstance(assumptions, dict) and "assumptions" in assumptions:
        arr = assumptions.get("assumptions")
        if isinstance(arr, list):
            checks["assumptions_json_valid"] = True
            if len(arr) >= 3:
                checks["assumptions_has_min_items"] = True
            non_empty_ok = True
            for item in arr:
                if not (isinstance(item, str) and item.strip()):
                    non_empty_ok = False
                    break
            if non_empty_ok and len(arr) >= 1:
                checks["assumptions_non_empty_strings"] = True

    # 6) rubric_notes.md
    rn_path = os.path.join(output_dir, "rubric_notes.md")
    rn_content = read_text(rn_path)
    if rn_content is not None:
        checks["rubric_notes_exists"] = True
        if len(rn_content) >= 800:
            checks["rubric_notes_len"] = True
        lc = rn_content.lower()
        if ("risk" in lc) and ("prioritization" in lc):
            checks["rubric_notes_contains_keywords"] = True

    # Compute reward
    # No-op baseline: if no output files at all, reward = 0.0
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    if not checks["has_any_output"]:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()