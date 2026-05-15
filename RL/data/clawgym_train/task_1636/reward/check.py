import json
import os
import sys
from typing import Any, Dict, Tuple, Optional, List

def to_float(val) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            return None
    return None

def approx_equal(a: Any, b: Any, tol: float = 0.01) -> bool:
    fa = to_float(a)
    fb = to_float(b)
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol

def load_json_file(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content == "":
                return False, None
            return True, json.loads(content)
    except Exception:
        return False, None

def extract_weekly_totals(obj: Any) -> Tuple[Dict[str, float], Optional[float]]:
    per_cat: Dict[str, float] = {}
    overall: Optional[float] = None

    # Try common shapes
    if isinstance(obj, dict):
        # Look for nested structures first
        for key in ["per_category", "perCategory", "category_totals", "categories"]:
            if key in obj:
                sub = obj[key]
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        fv = to_float(v)
                        if fv is not None:
                            per_cat[k] = fv
                elif isinstance(sub, list):
                    for item in sub:
                        if isinstance(item, dict):
                            cat = item.get("category")
                            total = item.get("total", item.get("amount"))
                            if isinstance(cat, str):
                                fv = to_float(total)
                                if fv is not None:
                                    per_cat[cat] = fv
        # If still empty, try direct keys
        if not per_cat:
            for k, v in obj.items():
                if isinstance(k, str) and to_float(v) is not None:
                    per_cat[k] = to_float(v)  # type: ignore

        # Overall total lookup
        for key in ["overall_total", "overall", "total", "grand_total", "sum"]:
            if key in obj and to_float(obj[key]) is not None:
                overall = to_float(obj[key])
                break

        # Or nested summary
        if overall is None and isinstance(obj.get("summary"), dict):
            for key in ["overall_total", "overall", "total", "grand_total", "sum"]:
                if key in obj["summary"] and to_float(obj["summary"][key]) is not None:
                    overall = to_float(obj["summary"][key])
                    break

    elif isinstance(obj, list):
        # List of dicts with category + total
        for item in obj:
            if isinstance(item, dict):
                cat = item.get("category")
                total = item.get("total", item.get("amount"))
                if isinstance(cat, str):
                    fv = to_float(total)
                    if fv is not None:
                        per_cat[cat] = fv
        # Overall might be a separate item
        for item in obj:
            if isinstance(item, dict):
                for key in ["overall_total", "overall", "total", "grand_total", "sum"]:
                    if key in item and to_float(item[key]) is not None:
                        overall = to_float(item[key])
                        break
            if overall is not None:
                break

    return per_cat, overall

def get_list_from_maybe_container(obj: Any) -> Optional[List[Any]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ["reminders", "items", "data", "list"]:
            if key in obj and isinstance(obj[key], list):
                return obj[key]
    return None

def parse_iso_date(d: str) -> Optional[str]:
    # For sorting purposes, lexicographic works for YYYY-MM-DD
    if isinstance(d, str) and len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Expected data
    weekly_expected = {
        "Food": 67.30,
        "Travel": 12.75,
        "Entertainment": 14.00,
        "Health": 23.20,
        "Education": 99.00,
    }
    weekly_expected_total = 216.25

    budget_expected = {
        "Food": (400.00, 85.70, 314.30),
        "Rent": (1200.00, 1200.00, 0.00),
        "Utilities": (200.00, 85.50, 114.50),
        "Travel": (300.00, 232.75, 67.25),
        "Entertainment": (150.00, 14.00, 136.00),
        "Shopping": (250.00, 45.99, 204.01),
        "Health": (100.00, 23.20, 76.80),
        "Misc": (100.00, 350.00, -250.00),
        "Education": (500.00, 99.00, 401.00),
    }

    reminders_expected = [
        {"type": "EMI", "name": "Car Loan", "amount": 350.00, "due_date": "2026-04-15"},
        {"type": "ONE_TIME", "name": "Insurance Premium", "amount": 350.00, "due_date": "2026-04-20"},
    ]

    csv_expected_lines = [
        "date,description,category,amount",
        "2026-04-01,Rent for April,Rent,1200.00",
        "2026-04-03,Electricity Bill,Utilities,85.50",
        "2026-04-06,Groceries at Market,Food,62.30",
        "2026-04-07,Coffee with friend,Food,5.00",
        "2026-04-08,Uber to office,Travel,12.75",
        "2026-04-09,Movie night,Entertainment,14.00",
        "2026-04-11,Online course,Education,99.00",
        "2026-04-12,Pharmacy,Health,23.20",
        "2026-04-13,Lunch with team,Food,18.40",
        "2026-04-15,Books purchase,Shopping,45.99",
        "2026-04-18,Flight booking,Travel,220.00",
        "2026-04-20,Insurance premium payment,Misc,350.00",
    ]

    # 1) Weekly digest checks
    weekly_path = os.path.join(output_dir, "weekly_digest_2026-04-06_to_2026-04-12.json")
    checks["weekly_file_exists"] = os.path.isfile(weekly_path)
    weekly_json_valid = False
    weekly_categories_match = False
    weekly_overall_total_ok = False
    if checks["weekly_file_exists"]:
        ok, data = load_json_file(weekly_path)
        weekly_json_valid = ok and data is not None
        if weekly_json_valid:
            per_cat, overall = extract_weekly_totals(data)
            # Validate categories
            cat_ok = True
            for cat, exp_val in weekly_expected.items():
                if cat not in per_cat or not approx_equal(per_cat[cat], exp_val):
                    cat_ok = False
                    break
            weekly_categories_match = cat_ok
            # Validate overall total
            if overall is not None and approx_equal(overall, weekly_expected_total):
                weekly_overall_total_ok = True
    checks["weekly_json_valid"] = weekly_json_valid
    checks["weekly_categories_match"] = weekly_categories_match
    checks["weekly_overall_total_ok"] = weekly_overall_total_ok

    # 2) Budget status checks
    budget_path = os.path.join(output_dir, "budget_status_2026-04.json")
    checks["budget_file_exists"] = os.path.isfile(budget_path)
    budget_json_valid = False
    # Per-category checks
    for cat in budget_expected.keys():
        checks[f"budget_{cat}_ok"] = False
    checks["budget_misc_overspending_marked"] = False

    budget_obj = None
    if checks["budget_file_exists"]:
        ok, data = load_json_file(budget_path)
        budget_json_valid = ok and isinstance(data, dict)
        budget_obj = data if budget_json_valid else None
    checks["budget_json_valid"] = budget_json_valid

    if budget_obj:
        for cat, (exp_budget, exp_spent, exp_remaining) in budget_expected.items():
            cat_info = budget_obj.get(cat)
            if isinstance(cat_info, dict):
                b = to_float(cat_info.get("budget"))
                s = to_float(cat_info.get("spent"))
                r = to_float(cat_info.get("remaining"))
                if b is not None and s is not None and r is not None:
                    if approx_equal(b, exp_budget) and approx_equal(s, exp_spent) and approx_equal(r, exp_remaining):
                        checks[f"budget_{cat}_ok"] = True
        # Overspending marker for Misc: accept negative remaining or explicit flag/status
        misc_info = budget_obj.get("Misc")
        if isinstance(misc_info, dict):
            r = to_float(misc_info.get("remaining"))
            overspend_flag = False
            if r is not None and r < -0.01:
                overspend_flag = True
            else:
                for key in ["overspending", "overspent"]:
                    val = misc_info.get(key)
                    if isinstance(val, bool) and val:
                        overspend_flag = True
                status_val = misc_info.get("status")
                if isinstance(status_val, str) and status_val.strip().lower() in {"overspent", "over", "exceeded"}:
                    overspend_flag = True
            checks["budget_misc_overspending_marked"] = overspend_flag

    # 3) Reminders checks
    reminders_path = os.path.join(output_dir, "reminders_next_14_days_from_2026-04-10.json")
    checks["reminders_file_exists"] = os.path.isfile(reminders_path)
    reminders_json_valid = False
    checks["reminders_correct_items"] = False
    checks["reminders_sorted"] = False
    if checks["reminders_file_exists"]:
        ok, data = load_json_file(reminders_path)
        if ok:
            lst = get_list_from_maybe_container(data)
            if isinstance(lst, list):
                reminders_json_valid = True
                # Validate fields and exact items
                # Extract only required fields
                extracted = []
                fields_ok = True
                for item in lst:
                    if not isinstance(item, dict):
                        fields_ok = False
                        break
                    t = item.get("type")
                    n = item.get("name")
                    a = to_float(item.get("amount"))
                    d = item.get("due_date")
                    if not (isinstance(t, str) and isinstance(n, str) and a is not None and isinstance(d, str)):
                        fields_ok = False
                        break
                    extracted.append({"type": t, "name": n, "amount": a, "due_date": d})
                if fields_ok and len(extracted) == 2:
                    # Check sorting by due_date ascending
                    due_dates = [x["due_date"] for x in extracted]
                    if all(parse_iso_date(dd) for dd in due_dates):
                        sorted_dates = sorted(due_dates)
                        checks["reminders_sorted"] = (due_dates == sorted_dates)
                    # Compare against expected (order should be ascending by date)
                    # First, sort both by due_date to compare regardless of current order
                    extracted_sorted = sorted(extracted, key=lambda x: x["due_date"])
                    expected_sorted = sorted(reminders_expected, key=lambda x: x["due_date"])
                    pair_match = True
                    for got, exp in zip(extracted_sorted, expected_sorted):
                        if got["type"] != exp["type"] or got["name"] != exp["name"] or got["due_date"] != exp["due_date"] or not approx_equal(got["amount"], exp["amount"]):
                            pair_match = False
                            break
                    checks["reminders_correct_items"] = pair_match
        reminders_json_valid = reminders_json_valid and True
    checks["reminders_json_valid"] = reminders_json_valid

    # 4) CSV export checks
    csv_path = os.path.join(output_dir, "april_2026_transactions.csv")
    checks["csv_file_exists"] = os.path.isfile(csv_path)
    checks["csv_header_ok"] = False
    checks["csv_rows_ok"] = False
    if checks["csv_file_exists"]:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Normalize line endings to \n and strip trailing whitespace lines
            lines = [ln for ln in content.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln != ""]
            # Must match exactly the expected lines
            if len(lines) == len(csv_expected_lines):
                if lines[0] == csv_expected_lines[0]:
                    checks["csv_header_ok"] = True
                # Compare all lines
                rows_ok = all(got == exp for got, exp in zip(lines, csv_expected_lines))
                checks["csv_rows_ok"] = rows_ok
        except Exception:
            pass

    # Compute reward: fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no relevant output files exist, reward must be 0.0
    any_output = any([
        checks.get("weekly_file_exists", False),
        checks.get("budget_file_exists", False),
        checks.get("reminders_file_exists", False),
        checks.get("csv_file_exists", False),
    ])
    if not any_output:
        reward = 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()