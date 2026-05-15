import json
import os
import sys
import re
from datetime import datetime

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_date_str(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def is_time_str(s):
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except Exception:
        return False

def amount_two_decimals(x):
    try:
        v = float(x)
    except Exception:
        return False
    return abs(v * 100 - round(v * 100)) < 1e-6

def find_expense(expenses, date_str, amount, tol=0.01):
    matches = []
    for e in expenses:
        if isinstance(e, dict) and e.get("date") == date_str:
            try:
                ea = float(e.get("amount"))
            except Exception:
                continue
            if abs(ea - amount) <= tol:
                matches.append(e)
    return matches

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def to_lower_or_none(s):
    if s is None:
        return None
    if isinstance(s, str):
        return s.lower()
    return None

def compute_category_sums(expenses):
    sums = {}
    for e in expenses:
        cat = e.get("category")
        amt = safe_float(e.get("amount"))
        if cat is None or amt is None:
            continue
        sums[cat] = sums.get(cat, 0.0) + amt
    return sums

def approx_equal(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_bullet_lines_with_dollar(text):
    if text is None:
        return 0, 0
    lines = text.splitlines()
    bullet_lines = [ln for ln in lines if re.match(r'^\s*[-*]\s+', ln)]
    dollar_lines = [ln for ln in bullet_lines if '$' in ln]
    return len(bullet_lines), len(dollar_lines)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    expenses_path = os.path.join(output_dir, "expenses.json")
    income_path = os.path.join(output_dir, "income.json")
    budgets_path = os.path.join(output_dir, "budgets.json")
    summary_path = os.path.join(output_dir, "summary_feb_2026.json")
    insights_path = os.path.join(output_dir, "insights.md")

    # Initialize all checks to False
    check_names = [
        "expenses_file_exists",
        "expenses_is_array",
        "expenses_len_13",
        "expenses_fields_valid",
        "expenses_currency_usd_all",
        "expenses_amounts_two_decimals",
        # 13 specific expense validations
        "exp_2026_02_01_1500_bills",
        "exp_2026_02_03_5_food",
        "exp_2026_02_03_12_5_food",
        "exp_2026_02_05_50_bills",
        "exp_2026_02_08_45_food",
        "exp_2026_02_10_89_shopping",
        "exp_2026_02_12_30_entertainment",
        "exp_2026_02_14_55_transport",
        "exp_2026_02_15_15_99_subscriptions",
        "exp_2026_02_18_95_food_card",
        "exp_2026_02_20_15_transport",
        "exp_2026_02_21_30_food_split",
        "exp_2026_02_22_80_bills",
        "income_file_exists",
        "income_single_salary_entry",
        "budgets_file_exists",
        "budgets_three_required",
        "summary_file_exists",
        "summary_structure_valid",
        "summary_totals_match_expected",
        "summary_by_category_match_expected",
        "summary_totals_consistency_with_files",
        "insights_file_exists",
        "insights_bullets_and_dollar"
    ]
    for n in check_names:
        checks[n] = False

    # Load files
    expenses = load_json(expenses_path)
    if expenses is not None:
        checks["expenses_file_exists"] = True
        if isinstance(expenses, list):
            checks["expenses_is_array"] = True
            if len(expenses) == 13:
                checks["expenses_len_13"] = True

            # Validate fields for each expense
            fields_ok = True
            currency_ok = True
            two_decimals_ok = True
            for e in expenses:
                if not isinstance(e, dict):
                    fields_ok = False
                    break
                # Required keys
                req_keys = ["id", "amount", "currency", "category", "description", "payment_method", "date", "time", "tags"]
                for k in req_keys:
                    if k not in e:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                # Types and formats
                if not isinstance(e.get("currency"), str):
                    fields_ok = False
                    break
                if not isinstance(e.get("category"), str):
                    fields_ok = False
                    break
                if not isinstance(e.get("description"), str):
                    fields_ok = False
                    break
                # payment_method can be None or str
                pm = e.get("payment_method")
                if not (pm is None or isinstance(pm, str)):
                    fields_ok = False
                    break
                # date/time format
                if not (isinstance(e.get("date"), str) and is_date_str(e.get("date"))):
                    fields_ok = False
                    break
                if not (isinstance(e.get("time"), str) and is_time_str(e.get("time"))):
                    fields_ok = False
                    break
                # tags list
                if not isinstance(e.get("tags"), list):
                    fields_ok = False
                    break
                # amount numeric and 2 decimals
                amt = safe_float(e.get("amount"))
                if amt is None:
                    fields_ok = False
                    break
                if not amount_two_decimals(amt):
                    two_decimals_ok = False
                # currency USD
                if e.get("currency") != "USD":
                    currency_ok = False

            if fields_ok:
                checks["expenses_fields_valid"] = True
            if currency_ok:
                checks["expenses_currency_usd_all"] = True
            if two_decimals_ok:
                checks["expenses_amounts_two_decimals"] = True

            # Specific expense validations by (date, amount) -> category/payment
            expected_expenses = [
                ("2026-02-01", 1500.00, "Bills", None, "exp_2026_02_01_1500_bills"),
                ("2026-02-03", 5.00, "Food", None, "exp_2026_02_03_5_food"),
                ("2026-02-03", 12.50, "Food", None, "exp_2026_02_03_12_5_food"),
                ("2026-02-05", 50.00, "Bills", None, "exp_2026_02_05_50_bills"),
                ("2026-02-08", 45.00, "Food", None, "exp_2026_02_08_45_food"),
                ("2026-02-10", 89.00, "Shopping", None, "exp_2026_02_10_89_shopping"),
                ("2026-02-12", 30.00, "Entertainment", None, "exp_2026_02_12_30_entertainment"),
                ("2026-02-14", 55.00, "Transport", None, "exp_2026_02_14_55_transport"),
                ("2026-02-15", 15.99, "Subscriptions", None, "exp_2026_02_15_15_99_subscriptions"),
                ("2026-02-18", 95.00, "Food", "card", "exp_2026_02_18_95_food_card"),
                ("2026-02-20", 15.00, "Transport", None, "exp_2026_02_20_15_transport"),
                ("2026-02-21", 30.00, "Food", None, "exp_2026_02_21_30_food_split"),
                ("2026-02-22", 80.00, "Bills", None, "exp_2026_02_22_80_bills"),
            ]
            for (d, a, cat, pm_exp, check_name) in expected_expenses:
                mats = find_expense(expenses, d, a, tol=0.01)
                ok = False
                for e in mats:
                    if e.get("category") == cat:
                        if pm_exp is not None:
                            if to_lower_or_none(e.get("payment_method")) == pm_exp.lower():
                                ok = True
                                break
                        else:
                            ok = True
                            break
                checks[check_name] = ok

    # Income checks
    income = load_json(income_path)
    if income is not None:
        checks["income_file_exists"] = True
        # Must contain exactly one entry for 2026-02-25 with amount 5000.00 and source "salary"
        ok_income = False
        if isinstance(income, list) and len(income) == 1 and isinstance(income[0], dict):
            inc = income[0]
            date_ok = inc.get("date") == "2026-02-25"
            amt = safe_float(inc.get("amount"))
            amt_ok = amt is not None and approx_equal(amt, 5000.00, tol=0.01)
            src_ok = inc.get("source") == "salary"
            # id present and notes present (can be null)
            id_ok = "id" in inc
            notes_ok = "notes" in inc  # allow None or str
            if date_ok and amt_ok and src_ok and id_ok and notes_ok:
                ok_income = True
        checks["income_single_salary_entry"] = ok_income

    # Budgets checks
    budgets = load_json(budgets_path)
    if budgets is not None:
        checks["budgets_file_exists"] = True
        req_budgets = {
            "Food": 500.00,
            "Transport": 300.00,
            "Shopping": 200.00
        }
        found = {k: False for k in req_budgets.keys()}
        if isinstance(budgets, list):
            for b in budgets:
                if not isinstance(b, dict):
                    continue
                cat = b.get("category")
                amt = safe_float(b.get("amount"))
                per = b.get("period")
                created = b.get("created")
                has_id = "id" in b
                if cat in req_budgets and amt is not None:
                    if approx_equal(amt, req_budgets[cat], tol=0.01) and per == "monthly" and has_id and isinstance(created, str) and is_date_str(created):
                        found[cat] = True
        checks["budgets_three_required"] = all(found.values())

    # Summary checks
    summary = load_json(summary_path)
    if summary is not None and isinstance(summary, dict):
        checks["summary_file_exists"] = True
        # Structure
        month_ok = summary.get("month") == "2026-02"
        te = safe_float(summary.get("total_expenses"))
        ti = safe_float(summary.get("total_income"))
        ns = safe_float(summary.get("net_savings"))
        byc = summary.get("by_category")
        structure_ok = month_ok and (te is not None) and (ti is not None) and (ns is not None) and isinstance(byc, dict)
        checks["summary_structure_valid"] = structure_ok

        # Expected numbers
        if structure_ok:
            te_ok = approx_equal(te, 2022.49, tol=0.01)
            ti_ok = approx_equal(ti, 5000.00, tol=0.01)
            ns_ok = approx_equal(ns, 2977.51, tol=0.01)
            checks["summary_totals_match_expected"] = te_ok and ti_ok and ns_ok

            expected_byc = {
                "Bills": 1630.00,
                "Food": 187.50,
                "Shopping": 89.00,
                "Entertainment": 30.00,
                "Transport": 70.00,
                "Subscriptions": 15.99
            }
            byc_ok = True
            for k, v in expected_byc.items():
                val = safe_float(byc.get(k))
                if not approx_equal(val, v, tol=0.01):
                    byc_ok = False
                    break
            checks["summary_by_category_match_expected"] = byc_ok

            # Consistency with files: recompute from expenses/income when available
            consistency_ok = False
            if isinstance(expenses, list) and isinstance(income, list) and len(income) == 1:
                # total expenses
                total_e = 0.0
                for e in expenses:
                    av = safe_float(e.get("amount"))
                    if av is not None:
                        total_e += av
                total_i = safe_float(income[0].get("amount")) or 0.0
                net = total_i - total_e
                sums = compute_category_sums(expenses)
                sums_ok = True
                for k, v in expected_byc.items():
                    if not approx_equal(sums.get(k, 0.0), v, tol=0.01):
                        sums_ok = False
                        break
                totals_ok = approx_equal(total_e, 2022.49, tol=0.01) and approx_equal(total_i, 5000.00, tol=0.01) and approx_equal(net, 2977.51, tol=0.01)
                summary_matches = approx_equal(te, total_e, tol=0.01) and approx_equal(ti, total_i, tol=0.01) and approx_equal(ns, net, tol=0.01)
                # Also check that by_category sums to total_expenses
                byc_sum = sum([safe_float(x) or 0.0 for x in byc.values()])
                byc_sum_ok = approx_equal(byc_sum, te, tol=0.02)  # leniency on rounding
                consistency_ok = sums_ok and totals_ok and summary_matches and byc_sum_ok
            checks["summary_totals_consistency_with_files"] = consistency_ok

    # Insights checks
    insights_text = read_text(insights_path)
    if insights_text is not None:
        checks["insights_file_exists"] = True
        bullets, dollars = count_bullet_lines_with_dollar(insights_text)
        checks["insights_bullets_and_dollar"] = bullets >= 5 and dollars >= 2

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or no required files exist, reward must be 0.0
    required_files_exist = any([
        checks.get("expenses_file_exists", False),
        checks.get("income_file_exists", False),
        checks.get("budgets_file_exists", False),
        checks.get("summary_file_exists", False),
        checks.get("insights_file_exists", False),
    ])
    if not required_files_exist:
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    output = {"reward": reward}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()