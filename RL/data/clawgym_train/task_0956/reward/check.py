import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def d_round2(val):
    try:
        d = Decimal(str(val))
    except Exception:
        d = Decimal(0)
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def has_max_two_decimal_places(val):
    try:
        d = Decimal(str(val))
    except Exception:
        return False
    exp = d.as_tuple().exponent
    if exp >= 0:
        return True
    return (-exp) <= 2

def is_number(val):
    return (isinstance(val, (int, float)) and not isinstance(val, bool))

def sum_amounts(records, month_prefix, txn_type):
    total = Decimal("0.00")
    for r in records:
        try:
            if isinstance(r, dict) and r.get("type") == txn_type and isinstance(r.get("date"), str) and r["date"].startswith(month_prefix):
                amt = Decimal(str(r.get("amount", 0)))
                total += amt
        except Exception:
            continue
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def sums_by_category(records, month_prefix, txn_type):
    cats = {}
    for r in records:
        try:
            if isinstance(r, dict) and r.get("type") == txn_type and isinstance(r.get("date"), str) and r["date"].startswith(month_prefix):
                cat = r.get("category")
                if cat is None:
                    continue
                amt = Decimal(str(r.get("amount", 0)))
                cats[cat] = cats.get(cat, Decimal("0.00")) + amt
        except Exception:
            continue
    # round to 2 decimals
    return {k: float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for k, v in cats.items()}

def compute_pct(curr, ref):
    if ref == 0:
        return None
    pct = ((Decimal(str(curr)) - Decimal(str(ref))) / Decimal(str(ref))) * Decimal("100")
    return float(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def collect_numeric_fields_summary(s):
    nums = []
    # totals
    t = s.get("totals", {})
    for k in ["income", "expense", "balance", "savings_rate_percent"]:
        v = t.get(k)
        if v is not None:
            nums.append(v)
    # comparisons
    comp = s.get("comparisons", {})
    for key in ["month_over_month", "year_over_year"]:
        inner = comp.get(key, {})
        for k in ["income_pct", "expense_pct"]:
            v = inner.get(k)
            if v is not None:
                nums.append(v)
    # categories
    for dkey in ["expense_by_category", "income_by_category"]:
        dct = s.get(dkey, {})
        if isinstance(dct, dict):
            for v in dct.values():
                nums.append(v)
    # budget_status
    bs = s.get("budget_status", [])
    if isinstance(bs, list):
        for item in bs:
            if isinstance(item, dict):
                for k in ["budget", "spent", "delta"]:
                    v = item.get(k)
                    if v is not None:
                        nums.append(v)
    return nums

def collect_numeric_fields_goals(goals_arr):
    nums = []
    if isinstance(goals_arr, list):
        for g in goals_arr:
            if not isinstance(g, dict):
                continue
            for k in ["target", "months", "monthly_need", "saved", "progress_percent", "remaining"]:
                v = g.get(k)
                if v is not None:
                    nums.append(v)
    return nums

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "summary_exists": False,
        "summary_valid_json": False,
        "summary_keys_exact": False,
        "summary_month_correct": False,
        "totals_income_correct": False,
        "totals_expense_correct": False,
        "totals_balance_correct": False,
        "totals_savings_rate_correct": False,
        "comparisons_mom_income_correct": False,
        "comparisons_mom_expense_correct": False,
        "comparisons_yoy_income_correct": False,
        "comparisons_yoy_expense_correct": False,
        "expense_by_category_correct": False,
        "income_by_category_correct": False,
        "budget_status_set_correct": False,
        "budget_status_values_correct": False,
        "goals_exists": False,
        "goals_valid_json": False,
        "goals_length_match": False,
        "goals_names_match": False,
        "goals_fields_and_values_correct": False,
        "numeric_types_and_two_decimals": False,
    }

    # Paths
    records_path = os.path.join(input_dir, "records.json")
    budgets_path = os.path.join(input_dir, "budgets.json")
    goals_in_path = os.path.join(input_dir, "goals.json")

    summary_path = os.path.join(output_dir, "summary_2026-03.json")
    goals_out_path = os.path.join(output_dir, "goals_progress.json")

    # Load input data
    records = load_json(records_path)
    budgets = load_json(budgets_path)
    goals_input = load_json(goals_in_path)

    # Load and validate summary output
    summary = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary = load_json(summary_path)
        if isinstance(summary, dict):
            checks["summary_valid_json"] = True

    # Load and validate goals output
    goals_out = None
    if os.path.isfile(goals_out_path):
        checks["goals_exists"] = True
        goals_out = load_json(goals_out_path)
        if isinstance(goals_out, list):
            checks["goals_valid_json"] = True

    # If outputs missing, reward will remain 0.0
    # Proceed to compute expectations only if inputs are available and outputs valid
    if checks["summary_valid_json"] and isinstance(records, list) and isinstance(budgets, dict):
        expected_keys = {"month", "totals", "comparisons", "expense_by_category", "income_by_category", "budget_status"}
        if set(summary.keys()) == expected_keys:
            checks["summary_keys_exact"] = True

        if summary.get("month") == "2026-03":
            checks["summary_month_correct"] = True

        # Compute expected values
        month = "2026-03"
        prev_month = "2026-02"
        yoy_month = "2025-03"

        income_curr = sum_amounts(records, month, "income")
        expense_curr = sum_amounts(records, month, "expense")
        balance_curr = d_round2(Decimal(str(income_curr)) - Decimal(str(expense_curr)))
        if income_curr == 0:
            savings_rate = 0.00
        else:
            savings_rate = d_round2((Decimal(str(balance_curr)) / Decimal(str(income_curr))) * Decimal("100"))

        if isinstance(summary.get("totals"), dict):
            t = summary["totals"]
            if is_number(t.get("income")) and d_round2(t["income"]) == income_curr:
                checks["totals_income_correct"] = True
            if is_number(t.get("expense")) and d_round2(t["expense"]) == expense_curr:
                checks["totals_expense_correct"] = True
            if is_number(t.get("balance")) and d_round2(t["balance"]) == balance_curr:
                checks["totals_balance_correct"] = True
            if is_number(t.get("savings_rate_percent")) and d_round2(t["savings_rate_percent"]) == savings_rate:
                checks["totals_savings_rate_correct"] = True

        # Comparisons
        income_prev = sum_amounts(records, prev_month, "income")
        expense_prev = sum_amounts(records, prev_month, "expense")
        income_yoy = sum_amounts(records, yoy_month, "income")
        expense_yoy = sum_amounts(records, yoy_month, "expense")

        expected_mom_income = compute_pct(income_curr, income_prev)
        expected_mom_expense = compute_pct(expense_curr, expense_prev)
        expected_yoy_income = compute_pct(income_curr, income_yoy)
        expected_yoy_expense = compute_pct(expense_curr, expense_yoy)

        comps = summary.get("comparisons", {})
        mom = comps.get("month_over_month", {}) if isinstance(comps, dict) else {}
        yoy = comps.get("year_over_year", {}) if isinstance(comps, dict) else {}

        # mom income
        mom_income_val = mom.get("income_pct", None) if isinstance(mom, dict) else None
        if (expected_mom_income is None and mom_income_val is None) or (
            expected_mom_income is not None and is_number(mom_income_val) and d_round2(mom_income_val) == expected_mom_income
        ):
            checks["comparisons_mom_income_correct"] = True

        # mom expense
        mom_expense_val = mom.get("expense_pct", None) if isinstance(mom, dict) else None
        if (expected_mom_expense is None and mom_expense_val is None) or (
            expected_mom_expense is not None and is_number(mom_expense_val) and d_round2(mom_expense_val) == expected_mom_expense
        ):
            checks["comparisons_mom_expense_correct"] = True

        # yoy income
        yoy_income_val = yoy.get("income_pct", None) if isinstance(yoy, dict) else None
        if (expected_yoy_income is None and yoy_income_val is None) or (
            expected_yoy_income is not None and is_number(yoy_income_val) and d_round2(yoy_income_val) == expected_yoy_income
        ):
            checks["comparisons_yoy_income_correct"] = True

        # yoy expense
        yoy_expense_val = yoy.get("expense_pct", None) if isinstance(yoy, dict) else None
        if (expected_yoy_expense is None and yoy_expense_val is None) or (
            expected_yoy_expense is not None and is_number(yoy_expense_val) and d_round2(yoy_expense_val) == expected_yoy_expense
        ):
            checks["comparisons_yoy_expense_correct"] = True

        # Categories
        exp_by_cat_expected = sums_by_category(records, month, "expense")
        inc_by_cat_expected = sums_by_category(records, month, "income")

        exp_by_cat_out = summary.get("expense_by_category", {})
        inc_by_cat_out = summary.get("income_by_category", {})

        exp_cat_ok = False
        inc_cat_ok = False

        if isinstance(exp_by_cat_out, dict) and set(exp_by_cat_out.keys()) == set(exp_by_cat_expected.keys()):
            vals_ok = True
            for k, v in exp_by_cat_expected.items():
                if not is_number(exp_by_cat_out.get(k)) or d_round2(exp_by_cat_out[k]) != v:
                    vals_ok = False
                    break
            if vals_ok:
                exp_cat_ok = True

        if isinstance(inc_by_cat_out, dict) and set(inc_by_cat_out.keys()) == set(inc_by_cat_expected.keys()):
            vals_ok = True
            for k, v in inc_by_cat_expected.items():
                if not is_number(inc_by_cat_out.get(k)) or d_round2(inc_by_cat_out[k]) != v:
                    vals_ok = False
                    break
            if vals_ok:
                inc_cat_ok = True

        checks["expense_by_category_correct"] = exp_cat_ok
        checks["income_by_category_correct"] = inc_cat_ok

        # Budget status
        bs_out = summary.get("budget_status", [])
        bs_set_ok = False
        bs_vals_ok = False
        if isinstance(bs_out, list):
            # Build expected mapping
            expected_bs = {}
            for cat, budget_val in budgets.items():
                try:
                    budget_val_num = float(Decimal(str(budget_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                except Exception:
                    budget_val_num = d_round2(budget_val)
                spent = sums_by_category(records, month, "expense").get(cat, 0.00)
                status = "over" if spent > budget_val_num else "within"
                if status == "over":
                    delta = d_round2(Decimal(str(spent)) - Decimal(str(budget_val_num)))
                else:
                    delta = d_round2(Decimal(str(budget_val_num)) - Decimal(str(spent)))
                expected_bs[cat] = {
                    "category": cat,
                    "budget": budget_val_num,
                    "spent": d_round2(spent),
                    "status": status,
                    "delta": delta,
                }
            out_map = {}
            all_obj_keys_ok = True
            for item in bs_out:
                if not isinstance(item, dict):
                    all_obj_keys_ok = False
                    break
                if set(item.keys()) != {"category", "budget", "spent", "status", "delta"}:
                    all_obj_keys_ok = False
                    break
                out_map[item.get("category")] = item
            if all_obj_keys_ok and set(out_map.keys()) == set(budgets.keys()):
                bs_set_ok = True
                vals_ok = True
                for cat, exp in expected_bs.items():
                    itm = out_map.get(cat)
                    if itm is None:
                        vals_ok = False
                        break
                    # Compare values
                    if not (is_number(itm.get("budget")) and d_round2(itm["budget"]) == exp["budget"]):
                        vals_ok = False
                        break
                    if not (is_number(itm.get("spent")) and d_round2(itm["spent"]) == exp["spent"]):
                        vals_ok = False
                        break
                    if itm.get("status") != exp["status"]:
                        vals_ok = False
                        break
                    if not (is_number(itm.get("delta")) and d_round2(itm["delta"]) == exp["delta"]):
                        vals_ok = False
                        break
                if vals_ok:
                    bs_vals_ok = True

        checks["budget_status_set_correct"] = bs_set_ok
        checks["budget_status_values_correct"] = bs_vals_ok

    # Goals output validation
    if checks["goals_valid_json"] and isinstance(goals_input, list):
        names_input = [g.get("name") for g in goals_input if isinstance(g, dict)]
        names_out = [g.get("name") for g in goals_out if isinstance(g, dict)]
        if len(goals_out) == len(goals_input):
            checks["goals_length_match"] = True
        if set(names_out) == set(names_input):
            checks["goals_names_match"] = True

        # Build expected per goal and validate fields/values
        expected_by_name = {}
        valid_values = True
        for g in goals_input:
            if not isinstance(g, dict):
                valid_values = False
                break
            name = g.get("name")
            target = float(Decimal(str(g.get("target", 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            months_val = g.get("months", 0)
            try:
                months_int = int(months_val)
            except Exception:
                months_int = 0
            saved = float(Decimal(str(g.get("saved", 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            monthly_need = 0.00
            if months_int != 0:
                monthly_need = d_round2(Decimal(str(target)) / Decimal(str(months_int)))
            progress_percent = 0.00
            if target != 0:
                raw_pct = (Decimal(str(saved)) / Decimal(str(target))) * Decimal("100")
                # clamp to 100
                if raw_pct > Decimal("100"):
                    raw_pct = Decimal("100")
                progress_percent = float(raw_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            remaining = d_round2(max(Decimal(str(target)) - Decimal(str(saved)), Decimal("0.00")))
            achieved = bool(Decimal(str(saved)) >= Decimal(str(target)))
            expected_by_name[name] = {
                "name": name,
                "target": target,
                "months": months_int,
                "monthly_need": monthly_need,
                "saved": saved,
                "progress_percent": progress_percent,
                "remaining": remaining,
                "achieved": achieved,
            }
        # Validate goals_out exactly
        if valid_values:
            for obj in goals_out:
                if not isinstance(obj, dict):
                    valid_values = False
                    break
                if set(obj.keys()) != {"name", "target", "months", "monthly_need", "saved", "progress_percent", "remaining", "achieved"}:
                    valid_values = False
                    break
                name = obj.get("name")
                exp = expected_by_name.get(name)
                if exp is None:
                    valid_values = False
                    break
                # Check numeric types and values
                if not isinstance(obj.get("achieved"), bool):
                    valid_values = False
                    break
                for k in ["target", "months", "monthly_need", "saved", "progress_percent", "remaining"]:
                    v = obj.get(k)
                    if k == "months":
                        # months must be number (int or float representing integer)
                        if not is_number(v):
                            valid_values = False
                            break
                        # Value equality
                        if int(v) != exp[k]:
                            valid_values = False
                            break
                    else:
                        if not is_number(v):
                            valid_values = False
                            break
                        if d_round2(v) != exp[k]:
                            valid_values = False
                            break
                if obj.get("achieved") != exp["achieved"]:
                    valid_values = False
                    break
        checks["goals_fields_and_values_correct"] = valid_values

    # Numeric types and two-decimals check across outputs
    numeric_ok = True
    if summary is None or goals_out is None:
        numeric_ok = False
    else:
        # Collect numeric values
        nums_summary = collect_numeric_fields_summary(summary)
        nums_goals = collect_numeric_fields_goals(goals_out)
        all_nums = nums_summary + nums_goals
        if len(all_nums) == 0:
            numeric_ok = False
        else:
            for v in all_nums:
                if not is_number(v):
                    numeric_ok = False
                    break
                if not has_max_two_decimal_places(v):
                    numeric_ok = False
                    break
    checks["numeric_types_and_two_decimals"] = numeric_ok

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if (checks["summary_exists"] and checks["goals_exists"]) else 0.0

    # Output single JSON object
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()