import json
import os
import sys
import csv
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_json_exists": False,
        "report_json_required_keys": False,
        "report_money_two_decimals": False,
        "income_sum_matches": False,
        "expense_sum_matches": False,
        "top3_expense_correct": False,
        "tx_by_day_exists": False,
        "tx_by_day_header": False,
        "tx_by_day_totals_match_report": False,
        "record_days_match": False,
        "avg_daily_values_match": False,
        "budgets_csv_exists": False,
        "budgets_csv_header": False,
        "budgets_csv_matches_report": False,
        "mom_yoy_csv_exists": False,
        "mom_yoy_csv_header": False,
        "mom_yoy_csv_matches_report": False,
        "goals_json_exists": False,
        "goals_leftover_matches_report_balance": False,
        "goals_contributions_capped": False,
        "goals_have_required_fields": False,
    }

    # Helpers
    def parse_number(val):
        # Accept string with two decimals or numeric; return float if parsable, else None
        if isinstance(val, (int, float)):
            try:
                return float(val)
            except Exception:
                return None
        if isinstance(val, str):
            s = val.strip()
            # allow leading +/-
            if re.match(r'^-?\d+(\.\d+)?$', s):
                try:
                    return float(s)
                except Exception:
                    return None
        return None

    def is_two_decimal_money(val):
        # Accept strings exactly two decimals, or numeric that is a multiple of 0.01 (within tolerance)
        if isinstance(val, str):
            return re.match(r'^-?\d+\.\d{2}$', val.strip()) is not None
        if isinstance(val, (int, float)):
            try:
                v = float(val)
            except Exception:
                return False
            # check v * 100 is near integer
            return abs(v * 100 - round(v * 100)) < 1e-6
        return False

    def float_eq(a, b, tol=1e-6):
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) <= tol

    # Load report.json
    report_path = os.path.join(output_dir, "report.json")
    report = None
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            checks["report_json_exists"] = True
        except Exception:
            report = None

    required_keys = ["total_income", "total_expense", "balance", "savings_rate",
                     "income_by_category", "expense_by_category", "top3_expense",
                     "daily_stats", "comparisons", "budgets_status"]

    if report is not None and all(k in report for k in required_keys):
        checks["report_json_required_keys"] = True

    # Validate money formatting for report.json
    def validate_report_money_formats(rep):
        # money fields: total_income, total_expense, balance
        # income_by_category values; expense_by_category values
        # top3_expense[i].amount
        # daily_stats.avg_daily_expense, avg_daily_income
        # budgets_status[].budget, spent, remaining
        # We do not enforce two decimals on savings_rate or pct fields
        money_ok = True
        if not is_two_decimal_money(rep.get("total_income")):
            money_ok = False
        if not is_two_decimal_money(rep.get("total_expense")):
            money_ok = False
        if not is_two_decimal_money(rep.get("balance")):
            money_ok = False

        for m in ("income_by_category", "expense_by_category"):
            obj = rep.get(m, {})
            if not isinstance(obj, dict):
                money_ok = False
                break
            for v in obj.values():
                if not is_two_decimal_money(v):
                    money_ok = False
                    break

        t3 = rep.get("top3_expense", [])
        if not isinstance(t3, list):
            money_ok = False
        else:
            for item in t3:
                if not isinstance(item, dict):
                    money_ok = False
                    break
                if not is_two_decimal_money(item.get("amount")):
                    money_ok = False
                    break

        ds = rep.get("daily_stats", {})
        if not isinstance(ds, dict):
            money_ok = False
        else:
            if not is_two_decimal_money(ds.get("avg_daily_expense")):
                money_ok = False
            if not is_two_decimal_money(ds.get("avg_daily_income")):
                money_ok = False
            # record_days should be integer-like
            rd = ds.get("record_days")
            if not isinstance(rd, int):
                # accept string int
                if isinstance(rd, str) and rd.isdigit():
                    pass
                else:
                    money_ok = False

        bs_arr = rep.get("budgets_status", [])
        if not isinstance(bs_arr, list):
            money_ok = False
        else:
            for item in bs_arr:
                if not isinstance(item, dict):
                    money_ok = False
                    break
                for key in ("budget", "spent", "remaining"):
                    if not is_two_decimal_money(item.get(key)):
                        money_ok = False
                        break
                # status must be "over" or "within"
                st = item.get("status")
                if st not in ("over", "within"):
                    money_ok = False
                    break

        return money_ok

    if checks["report_json_required_keys"]:
        if validate_report_money_formats(report):
            checks["report_money_two_decimals"] = True

    # Sums match and top3 expense correctness
    if checks["report_json_required_keys"]:
        ti = parse_number(report.get("total_income"))
        te = parse_number(report.get("total_expense"))
        # Sum income_by_category
        inc_sum = None
        exp_sum = None
        inc_obj = report.get("income_by_category", {})
        exp_obj = report.get("expense_by_category", {})
        if isinstance(inc_obj, dict):
            s = 0.0
            ok = True
            for v in inc_obj.values():
                num = parse_number(v)
                if num is None:
                    ok = False
                    break
                s += num
            if ok:
                inc_sum = round(s, 2)
        if isinstance(exp_obj, dict):
            s = 0.0
            ok = True
            for v in exp_obj.values():
                num = parse_number(v)
                if num is None:
                    ok = False
                    break
                s += num
            if ok:
                exp_sum = round(s, 2)

        if ti is not None and inc_sum is not None and float_eq(round(ti, 2), inc_sum, tol=1e-2):
            checks["income_sum_matches"] = True
        if te is not None and exp_sum is not None and float_eq(round(te, 2), exp_sum, tol=1e-2):
            checks["expense_sum_matches"] = True

        # top3 expense correctness
        t3 = report.get("top3_expense", [])
        if isinstance(exp_obj, dict) and isinstance(t3, list):
            # compute top3 from expense_by_category
            items = []
            for cat, v in exp_obj.items():
                num = parse_number(v)
                if num is None:
                    items = []
                    break
                items.append((cat, round(num, 2)))
            if items:
                items_sorted = sorted(items, key=lambda x: (-x[1], x[0]))
                top3_expected = items_sorted[:3]
                # Compare with t3
                ok = True
                if len(t3) != len(top3_expected):
                    # Allow if less than 3 categories exist but ensure matching length
                    if len(items_sorted) >= 3:
                        ok = False
                if ok:
                    for i, exp_item in enumerate(top3_expected):
                        if i >= len(t3):
                            ok = False
                            break
                        got = t3[i]
                        if not isinstance(got, dict):
                            ok = False
                            break
                        gcat = got.get("category")
                        gamt = parse_number(got.get("amount"))
                        if gcat != exp_item[0] or (gamt is None) or not float_eq(round(gamt, 2), exp_item[1], tol=1e-2):
                            ok = False
                            break
                if ok:
                    checks["top3_expense_correct"] = True

    # transactions_by_day.csv checks
    tx_day_path = os.path.join(output_dir, "transactions_by_day.csv")
    tx_rows = []
    if os.path.isfile(tx_day_path):
        try:
            with open(tx_day_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                checks["tx_by_day_exists"] = True
                header = rows[0]
                if header == ["date", "total_income", "total_expense", "num_records"]:
                    checks["tx_by_day_header"] = True
                # parse rows
                for r in rows[1:]:
                    if len(r) != 4:
                        continue
                    date = r[0].strip()
                    inc = parse_number(r[1])
                    exp = parse_number(r[2])
                    try:
                        nr = int(r[3])
                    except Exception:
                        nr = None
                    if inc is None or exp is None or nr is None:
                        continue
                    tx_rows.append({"date": date, "income": inc, "expense": exp, "num_records": nr})
        except Exception:
            pass

    if checks["report_json_required_keys"] and checks["tx_by_day_header"] and tx_rows:
        total_income_days = round(sum(r["income"] for r in tx_rows), 2)
        total_expense_days = round(sum(r["expense"] for r in tx_rows), 2)
        ti = parse_number(report.get("total_income"))
        te = parse_number(report.get("total_expense"))
        if ti is not None and te is not None:
            if float_eq(round(ti, 2), total_income_days, tol=1e-2) and float_eq(round(te, 2), total_expense_days, tol=1e-2):
                checks["tx_by_day_totals_match_report"] = True

        # record_days = unique dates count
        unique_dates = set(r["date"] for r in tx_rows)
        rd = report.get("daily_stats", {}).get("record_days")
        # accept int or string int
        rd_int = None
        if isinstance(rd, int):
            rd_int = rd
        elif isinstance(rd, str) and rd.isdigit():
            rd_int = int(rd)
        if rd_int is not None and rd_int == len(unique_dates):
            checks["record_days_match"] = True

        # avg daily
        ds = report.get("daily_stats", {})
        ave_inc = parse_number(ds.get("avg_daily_income"))
        ave_exp = parse_number(ds.get("avg_daily_expense"))
        if rd_int and rd_int > 0 and ave_inc is not None and ave_exp is not None:
            exp_ave_inc = round(total_income_days / rd_int, 2)
            exp_ave_exp = round(total_expense_days / rd_int, 2)
            if float_eq(round(ave_inc, 2), exp_ave_inc, tol=1e-2) and float_eq(round(ave_exp, 2), exp_ave_exp, tol=1e-2):
                checks["avg_daily_values_match"] = True

    # budgets_status.csv checks
    budgets_csv_path = os.path.join(output_dir, "budgets_status.csv")
    budgets_csv_rows = None
    if os.path.isfile(budgets_csv_path):
        try:
            with open(budgets_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                checks["budgets_csv_exists"] = True
                header = rows[0]
                if header == ["category", "budget", "spent", "remaining", "status"]:
                    checks["budgets_csv_header"] = True
                budgets_csv_rows = rows[1:]
        except Exception:
            pass

    if checks["report_json_required_keys"] and checks["budgets_csv_header"] and budgets_csv_rows is not None:
        # Build mapping from CSV
        csv_map = {}
        csv_ok = True
        for r in budgets_csv_rows:
            if len(r) != 5:
                csv_ok = False
                break
            cat = r[0].strip()
            b = parse_number(r[1])
            s = parse_number(r[2])
            rem = parse_number(r[3])
            st = r[4].strip()
            if None in (b, s, rem) or st not in ("over", "within"):
                csv_ok = False
                break
            csv_map[cat] = {"budget": round(float(b), 2),
                            "spent": round(float(s), 2),
                            "remaining": round(float(rem), 2),
                            "status": st}
        bs_arr = report.get("budgets_status", [])
        if csv_ok and isinstance(bs_arr, list):
            # Compare both ways: ensure categories count match and per-category values match (to two decimals)
            rep_map = {}
            rep_ok = True
            for item in bs_arr:
                if not isinstance(item, dict) or "category" not in item:
                    rep_ok = False
                    break
                cat = item["category"]
                b = parse_number(item.get("budget"))
                s = parse_number(item.get("spent"))
                rem = parse_number(item.get("remaining"))
                st = item.get("status")
                if None in (b, s, rem) or st not in ("over", "within"):
                    rep_ok = False
                    break
                rep_map[cat] = {"budget": round(float(b), 2),
                                "spent": round(float(s), 2),
                                "remaining": round(float(rem), 2),
                                "status": st}
            if rep_ok and set(rep_map.keys()) == set(csv_map.keys()):
                per_ok = True
                for cat in rep_map:
                    a = rep_map[cat]
                    b = csv_map[cat]
                    if not (float_eq(a["budget"], b["budget"], tol=1e-2) and
                            float_eq(a["spent"], b["spent"], tol=1e-2) and
                            float_eq(a["remaining"], b["remaining"], tol=1e-2) and
                            a["status"] == b["status"]):
                        per_ok = False
                        break
                if per_ok:
                    checks["budgets_csv_matches_report"] = True

    # moM_yoy.csv checks
    mom_yoy_csv_path = os.path.join(output_dir, "moM_yoy.csv")
    mom_yoy_rows = None
    if os.path.isfile(mom_yoy_csv_path):
        try:
            with open(mom_yoy_csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                checks["mom_yoy_csv_exists"] = True
                header = rows[0]
                if header == ["comparison", "type", "change_pct"]:
                    checks["mom_yoy_csv_header"] = True
                mom_yoy_rows = rows[1:]
        except Exception:
            pass

    if checks["report_json_required_keys"] and checks["mom_yoy_csv_header"] and mom_yoy_rows is not None:
        # Build csv mapping
        csv_map = {}
        csv_ok = True
        for r in mom_yoy_rows:
            if len(r) != 3:
                csv_ok = False
                break
            comp = r[0].strip()
            typ = r[1].strip()
            val = parse_number(r[2])
            if comp not in ("mom", "yoy") or typ not in ("expense", "income") or val is None:
                csv_ok = False
                break
            csv_map[(comp, typ)] = float(val)
        # Extract from report
        rep_comp = report.get("comparisons", {})
        try:
            mom = rep_comp.get("mom", {})
            yoy = rep_comp.get("yoy", {})
            expected = {
                ("mom", "expense"): parse_number(mom.get("expense_change_pct")),
                ("mom", "income"): parse_number(mom.get("income_change_pct")),
                ("yoy", "expense"): parse_number(yoy.get("expense_change_pct")),
                ("yoy", "income"): parse_number(yoy.get("income_change_pct")),
            }
            exp_ok = all(v is not None for v in expected.values())
        except Exception:
            exp_ok = False
            expected = {}
        if csv_ok and exp_ok:
            # Ensure exactly four required rows and values match within tolerance
            if set(csv_map.keys()) == set(expected.keys()):
                vals_ok = True
                for k, v in expected.items():
                    if not float_eq(round(csv_map[k], 6), round(float(v), 6), tol=1e-4):
                        vals_ok = False
                        break
                if vals_ok:
                    checks["mom_yoy_csv_matches_report"] = True

    # goals_progress.json checks
    goals_path = os.path.join(output_dir, "goals_progress.json")
    goals_data = None
    if os.path.isfile(goals_path):
        try:
            with open(goals_path, "r", encoding="utf-8") as f:
                goals_data = json.load(f)
            checks["goals_json_exists"] = True
        except Exception:
            goals_data = None

    if checks["report_json_required_keys"] and goals_data is not None and isinstance(goals_data, dict):
        lo = parse_number(goals_data.get("leftover_balance"))
        report_balance = parse_number(report.get("balance"))
        if lo is not None and report_balance is not None:
            expected_lo = max(round(report_balance, 2), 0.0)
            if float_eq(round(lo, 2), round(expected_lo, 2), tol=1e-2):
                checks["goals_leftover_matches_report_balance"] = True

        # contributions capped
        goals_list = goals_data.get("goals")
        contrib_ok = False
        fields_ok = False
        if isinstance(goals_list, list):
            # Sum contributions
            total_contrib = 0.0
            each_fields_ok = True
            for g in goals_list:
                if not isinstance(g, dict):
                    each_fields_ok = False
                    break
                # Required fields
                required_g_fields = ["name", "target", "months", "saved", "remaining", "monthly_need", "proposed_contribution_march"]
                if not all(k in g for k in required_g_fields):
                    each_fields_ok = False
                    break
                # Basic type/format checks for numeric fields
                for num_key in ["target", "saved", "remaining", "monthly_need", "proposed_contribution_march"]:
                    if not is_two_decimal_money(g.get(num_key)):
                        each_fields_ok = False
                        break
                # months integer-like
                months = g.get("months")
                if not isinstance(months, int):
                    # accept string int
                    if not (isinstance(months, str) and months.isdigit()):
                        each_fields_ok = False
                        break
                # Add contribution
                pc = parse_number(g.get("proposed_contribution_march"))
                if pc is None:
                    each_fields_ok = False
                    break
                total_contrib += float(pc)
            if each_fields_ok and lo is not None:
                if lo > 0:
                    if total_contrib <= 0.7 * lo + 1e-6:
                        contrib_ok = True
                else:
                    # balance negative: contributions should be 0 and rationale present
                    all_zero = True
                    for g in goals_list:
                        pc = parse_number(g.get("proposed_contribution_march"))
                        if pc is None or abs(pc) > 1e-6:
                            all_zero = False
                            break
                    rationale = goals_data.get("rationale")
                    if all_zero and isinstance(rationale, str) and rationale.strip() != "":
                        contrib_ok = True
            fields_ok = each_fields_ok
        checks["goals_contributions_capped"] = contrib_ok
        checks["goals_have_required_fields"] = fields_ok

    # Compute reward as ratio of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # No-op baseline: if output dir missing or empty, ensure reward = 0.0
    # If no primary artifact (report.json) exists, set reward to 0.0
    if not checks["report_json_exists"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()