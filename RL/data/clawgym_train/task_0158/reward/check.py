import json
import os
import sys
import csv
from datetime import datetime, date

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_csv_dicts(path):
    rows = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                rows.append({k: (v if v is not None else "") for k, v in r.items()})
    except FileNotFoundError:
        return []
    return rows

def parse_amount(text):
    if text is None:
        return 0.0
    s = str(text).strip().replace(",", "")
    # remove currency or non-numeric except (), . and -
    cleaned = []
    for ch in s:
        if ch.isdigit() or ch in ".()-":
            cleaned.append(ch)
    s2 = "".join(cleaned)
    if s2.startswith("(") and s2.endswith(")"):
        s2 = "-" + s2[1:-1]
    try:
        return float(s2) if s2 else 0.0
    except Exception:
        try:
            return float(s)
        except Exception:
            return 0.0

def to_date(s):
    if not s:
        return None
    s = s.strip()[:10]
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        # attempt common formats
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
    return None

def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"

def add_month(dt):
    # add one calendar month, clamping day
    y = dt.year
    m = dt.month + 1
    if m > 12:
        m = 1
        y += 1
    day = dt.day
    # clamp to end of target month
    for d in range(31, 27, -1):
        try:
            return date(y, m, min(day, d))
        except ValueError:
            continue
    # fallback
    return date(y, m, 1)

def compute_cashflow_metrics(transactions):
    total_in = 0.0
    total_out = 0.0
    days = set()
    monthly = {}
    cat_spend = {}
    merch_spend = {}
    for row in transactions:
        amount = parse_amount(row.get("amount", "0"))
        d = to_date(row.get("date", ""))
        if d:
            days.add(d.isoformat())
            mk = month_key(d)
        else:
            mk = "unknown"
        merchant = (row.get("merchant") or "unknown").strip() or "unknown"
        category = (row.get("category") or "uncategorized").strip() or "uncategorized"
        if amount >= 0:
            total_in += amount
            monthly.setdefault(mk, {"in": 0.0, "out": 0.0, "net": 0.0})
            monthly[mk]["in"] += amount
        else:
            spend = -amount
            total_out += spend
            monthly.setdefault(mk, {"in": 0.0, "out": 0.0, "net": 0.0})
            monthly[mk]["out"] += spend
            cat_spend[category] = cat_spend.get(category, 0.0) + spend
            merch_spend[merchant] = merch_spend.get(merchant, 0.0) + spend
    for k, v in monthly.items():
        v["net"] = v["in"] - v["out"]
    unique_days = len(days) if days else 1
    avg_daily_burn = total_out / unique_days
    # build top 5 lists
    top_categories = sorted(cat_spend.items(), key=lambda x: x[1], reverse=True)[:5]
    top_merchants = sorted(merch_spend.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "total_inflow": total_in,
        "total_outflow": total_out,
        "net_cashflow": total_in - total_out,
        "avg_daily_burn": avg_daily_burn,
        "monthly_totals": monthly,
        "top_categories": [{"name": n, "spend": v} for n, v in top_categories],
        "top_merchants": [{"name": n, "spend": v} for n, v in top_merchants],
    }

def similar_amounts(values):
    if not values:
        return False
    avg = sum(values) / len(values)
    if avg == 0:
        return all(abs(v) <= 2 for v in values)
    for v in values:
        if abs(v - avg) > max(2, abs(avg) * 0.15):
            return False
    return True

def detect_monthly_recurring(transactions):
    groups = {}
    for row in transactions:
        amount = parse_amount(row.get("amount", "0"))
        if amount >= 0:
            continue
        merchant = (row.get("merchant") or "unknown").strip() or "unknown"
        d = to_date(row.get("date", ""))
        if not d:
            continue
        groups.setdefault(merchant, []).append((d, -amount))
    results = {}
    for merchant, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x[0])
        gaps = [(items[i][0] - items[i-1][0]).days for i in range(1, len(items))]
        avg_gap = sum(gaps) / len(gaps)
        amounts = [v for _, v in items]
        cadence = None
        if 25 <= avg_gap <= 35 and similar_amounts(amounts):
            cadence = "monthly"
        if cadence:
            avg_amount = sum(amounts) / len(amounts)
            last_date = items[-1][0]
            results[merchant] = {
                "merchant": merchant,
                "cadence": cadence,
                "count": len(items),
                "average_amount": avg_amount,
                "last_date": last_date,
            }
    return results

def sum_balances(rows):
    total = 0.0
    for r in rows:
        total += parse_amount(r.get("balance", "0"))
    return total

def next_due_date_for_due_day(year, month, due_day):
    dd = int(due_day)
    # clamp to valid day for the month
    for d in range(dd, 27, -1):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    # as last resort
    return date(year, month, 28)

def load_debts(debt_rows):
    debts = []
    for r in debt_rows:
        try:
            dd = int(str(r.get("due_day", "")).strip() or "0")
        except Exception:
            dd = 0
        debt = {
            "name": (r.get("name") or "").strip(),
            "balance": parse_amount(r.get("balance", "0")),
            "apr_percent": float(str(r.get("apr_percent", "0")).strip() or 0.0),
            "min_payment": parse_amount(r.get("min_payment", "0")),
            "due_day": dd,
            "notes": (r.get("notes") or "").strip(),
        }
        if debt["name"]:
            debts.append(debt)
    return debts

def obligations_next_14_days(transactions, balances_rows, debt_rows, start_date, end_date):
    # debts
    debts = load_debts(debt_rows)
    obligations = {}
    for d in debts:
        if d["due_day"] <= 0:
            continue
        due_dt = next_due_date_for_due_day(start_date.year, start_date.month, d["due_day"])
        if start_date <= due_dt <= end_date:
            obligations[d["name"]] = {
                "name": d["name"],
                "amount": round(d["min_payment"], 2),
                "due_date": due_dt.isoformat(),
            }
    # recurring merchants (monthly)
    rec = detect_monthly_recurring(transactions)
    for m, info in rec.items():
        next_dt = add_month(info["last_date"])
        if start_date <= next_dt <= end_date:
            if m not in obligations:
                obligations[m] = {
                    "name": m,
                    "amount": round(info["average_amount"], 2),
                    "due_date": next_dt.isoformat(),
                }
    # return list
    return list(obligations.values())

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "cashflow_exists": False,
        "cashflow_totals_ok": False,
        "cashflow_monthly_ok": False,
        "cashflow_top_categories_ok": False,
        "cashflow_top_merchants_ok": False,

        "recurring_exists": False,
        "recurring_required_ok": False,

        "runway_exists": False,
        "runway_date_ok": False,
        "runway_cash_ok": False,
        "runway_obligations_ok": False,
        "runway_totals_ok": False,

        "triage_exists": False,
        "triage_order_ok": False,
        "triage_values_match_ok": False,

        "actions_exists": False,
        "actions_substrings_ok": False,
    }

    # Load inputs for expected computations
    transactions_path = os.path.join(input_dir, "transactions.csv")
    balances_path = os.path.join(input_dir, "balances.csv")
    debts_path = os.path.join(input_dir, "debts.csv")
    transactions = read_csv_dicts(transactions_path)
    balances_rows = read_csv_dicts(balances_path)
    debt_rows = read_csv_dicts(debts_path)

    # Compute expected cashflow metrics from input (deterministic)
    cashflow_expected = compute_cashflow_metrics(transactions)
    # Normalize monthly keys we care about (e.g., ensure rounding for comparison)
    monthly_expected = {}
    for k, v in cashflow_expected["monthly_totals"].items():
        monthly_expected[k] = {
            "in": round(v["in"], 2),
            "out": round(v["out"], 2),
            "net": round(v["in"] - v["out"], 2),
        }
    # Build expected top category/merchant spends map for required names
    # From reward summary, verify at least these (we compute amounts to compare)
    must_have_categories = ["Housing", "Groceries", "Debt Payments", "Utilities", "Subscriptions"]
    cat_amounts = {}
    # recompute full category spend
    full_cat = {}
    for row in transactions:
        amt = parse_amount(row.get("amount", "0"))
        if amt < 0:
            cat = (row.get("category") or "uncategorized").strip() or "uncategorized"
            full_cat[cat] = full_cat.get(cat, 0.0) + (-amt)
    for name in must_have_categories:
        if name in full_cat:
            cat_amounts[name] = round(full_cat[name], 2)
    must_have_merchants = ["Rent", "Supermarket", "Student Loan", "Electric Co", "CC BankX"]
    merch_amounts = {}
    full_merch = {}
    for row in transactions:
        amt = parse_amount(row.get("amount", "0"))
        if amt < 0:
            merch = (row.get("merchant") or "unknown").strip() or "unknown"
            full_merch[merch] = full_merch.get(merch, 0.0) + (-amt)
    for name in must_have_merchants:
        if name in full_merch:
            merch_amounts[name] = round(full_merch[name], 2)

    # Cashflow summary.json checks
    cashflow_file = os.path.join(output_dir, "cashflow_summary.json")
    if os.path.isfile(cashflow_file):
        checks["cashflow_exists"] = True
        try:
            data = load_json(cashflow_file)
            # Totals
            ti = data.get("total_inflow")
            to = data.get("total_outflow")
            net = data.get("net_cashflow")
            burn = data.get("avg_daily_burn")
            exp_ti = round(cashflow_expected["total_inflow"], 2)
            exp_to = round(cashflow_expected["total_outflow"], 2)
            exp_net = round(cashflow_expected["net_cashflow"], 2)
            exp_burn = round(cashflow_expected["avg_daily_burn"], 2)
            if all([
                approx_equal(ti, exp_ti, 0.01),
                approx_equal(to, exp_to, 0.01),
                approx_equal(net, exp_net, 0.01),
                approx_equal(burn, exp_burn, 0.01),
            ]):
                checks["cashflow_totals_ok"] = True

            # Monthly totals: ensure keys for months present in input (focus on 2026-01, 2026-02, 2026-03 if present)
            monthly_out = data.get("monthly_totals") or {}
            months_to_check = [m for m in monthly_expected.keys() if m in ("2026-01", "2026-02", "2026-03")]
            monthly_ok = True
            for m in months_to_check:
                mv = monthly_out.get(m)
                if not isinstance(mv, dict):
                    monthly_ok = False
                    break
                if not (approx_equal(mv.get("in"), monthly_expected[m]["in"], 0.01) and
                        approx_equal(mv.get("out"), monthly_expected[m]["out"], 0.01) and
                        approx_equal(mv.get("net"), monthly_expected[m]["net"], 0.01)):
                    monthly_ok = False
                    break
            if months_to_check and monthly_ok:
                checks["cashflow_monthly_ok"] = True

            # Top categories: must contain specified names with approx spend values
            tc = data.get("top_categories") or []
            tc_map = {}
            for item in tc:
                if isinstance(item, dict):
                    n = item.get("name")
                    s = item.get("spend")
                    if n is not None:
                        tc_map[str(n)] = s
            cat_ok = True
            for name, exp_val in cat_amounts.items():
                if name not in tc_map or not approx_equal(tc_map[name], exp_val, 0.01):
                    cat_ok = False
                    break
            if cat_amounts and cat_ok:
                checks["cashflow_top_categories_ok"] = True

            # Top merchants
            tm = data.get("top_merchants") or []
            tm_map = {}
            for item in tm:
                if isinstance(item, dict):
                    n = item.get("name")
                    s = item.get("spend")
                    if n is not None:
                        tm_map[str(n)] = s
            merch_ok = True
            for name, exp_val in merch_amounts.items():
                if name not in tm_map or not approx_equal(tm_map[name], exp_val, 0.01):
                    merch_ok = False
                    break
            if merch_amounts and merch_ok:
                checks["cashflow_top_merchants_ok"] = True

        except Exception:
            pass

    # Recurring.json checks
    recurring_file = os.path.join(output_dir, "recurring.json")
    recurring_required = {
        "Spotify": {"count": None, "avg_tol": 0.05},
        "Rent": {"count": None, "avg_tol": 0.05},
        "Gym Membership": {"count": None, "avg_tol": 0.05},
        "Electric Co": {"count": None, "avg_tol": 0.05},
        "Cloud Storage": {"count": None, "avg_tol": 0.05},
        "Student Loan": {"count": None, "avg_tol": 0.05},
        "CC BankX": {"count": None, "avg_tol": 0.05},
    }
    # Derive expected counts and averages from input using monthly detection
    rec_detected = detect_monthly_recurring(transactions)
    for rname in recurring_required.keys():
        if rname in rec_detected:
            recurring_required[rname]["count"] = rec_detected[rname]["count"]
            recurring_required[rname]["avg"] = round(rec_detected[rname]["average_amount"], 2)

    if os.path.isfile(recurring_file):
        checks["recurring_exists"] = True
        try:
            rec = load_json(recurring_file)
            if isinstance(rec, list):
                # Build lookup
                out_map = {}
                for item in rec:
                    if isinstance(item, dict):
                        m = (item.get("merchant") or "").strip()
                        if m:
                            out_map[m] = item
                ok = True
                for name, req in recurring_required.items():
                    # Only check if we could detect expected from input
                    if "avg" not in req or req["count"] is None:
                        ok = False
                        break
                    if name not in out_map:
                        ok = False
                        break
                    itm = out_map[name]
                    if (str(itm.get("cadence")).lower() != "monthly" or
                        itm.get("count") != req["count"] or
                        not approx_equal(itm.get("average_amount"), req["avg"], req.get("avg_tol", 0.05))):
                        ok = False
                        break
                if ok:
                    checks["recurring_required_ok"] = True
        except Exception:
            pass

    # Runway review checks
    runway_file = os.path.join(output_dir, "runway_review.json")
    if os.path.isfile(runway_file):
        checks["runway_exists"] = True
        try:
            runway = load_json(runway_file)
            # date_assumed
            checks["runway_date_ok"] = (runway.get("date_assumed") == "2026-03-12")
            # cash_today from balances
            exp_cash_today = round(sum_balances(balances_rows), 2)
            if approx_equal(runway.get("cash_today"), exp_cash_today, 0.01):
                checks["runway_cash_ok"] = True
            # obligations presence
            obligations = runway.get("obligations_next_14_days") or []
            # Build set
            obl_map = {}
            for o in obligations:
                if isinstance(o, dict) and "name" in o:
                    obl_map[o["name"]] = o
            # Expected obligations computed from inputs within window
            start_dt = date(2026, 3, 12)
            end_dt = date(2026, 3, 26)
            expected_obl = obligations_next_14_days(transactions, balances_rows, debt_rows, start_dt, end_dt)
            # From reward summary, we require at least these five:
            required_obl = {
                "Electric Co": {"due_date": "2026-03-15", "amount": None},
                "Cloud Storage": {"due_date": "2026-03-20", "amount": None},
                "CC BankX": {"due_date": "2026-03-17", "amount": None},
                "Medical Bill": {"due_date": "2026-03-18", "amount": None},
                "Student Loan": {"due_date": "2026-03-25", "amount": None},
            }
            # Fill expected amounts from computed obligations list
            exp_obl_map = {o["name"]: o for o in expected_obl}
            for k in list(required_obl.keys()):
                if k in exp_obl_map:
                    required_obl[k]["amount"] = round(float(exp_obl_map[k]["amount"]), 2) if "amount" in exp_obl_map[k] else None
            obl_ok = True
            for name, req in required_obl.items():
                if name not in obl_map:
                    obl_ok = False
                    break
                itm = obl_map[name]
                if itm.get("due_date") != req["due_date"]:
                    obl_ok = False
                    break
                if req["amount"] is not None and not approx_equal(itm.get("amount"), req["amount"], 0.02):
                    obl_ok = False
                    break
            if obl_ok:
                checks["runway_obligations_ok"] = True
            # totals
            exp_total_obl = 0.0
            for o in obligations:
                try:
                    exp_total_obl += float(o.get("amount", 0.0))
                except Exception:
                    pass
            # Compare reported total and free_to_spend to cash_today - sum(amounts)
            total_reported = runway.get("total_obligations_next_14_days")
            fts_reported = runway.get("free_to_spend")
            if all([
                approx_equal(total_reported, exp_total_obl, 0.02),
                approx_equal(fts_reported, exp_cash_today - exp_total_obl, 0.02)
            ]):
                checks["runway_totals_ok"] = True
        except Exception:
            pass

    # Debt triage checks
    triage_file = os.path.join(output_dir, "debt_triage.json")
    if os.path.isfile(triage_file):
        checks["triage_exists"] = True
        try:
            triage = load_json(triage_file)
            if isinstance(triage, list) and len(triage) >= 3:
                first_three = triage[:3]
                names = [ (i.get("name") if isinstance(i, dict) else None) for i in first_three ]
                due_dates = [ (i.get("due_date") if isinstance(i, dict) else None) for i in first_three ]
                if names == ["CC BankX", "Student Loan", "Medical Bill"] and due_dates == ["2026-03-17", "2026-03-25", "2026-03-18"]:
                    checks["triage_order_ok"] = True
                # Verify apr_percent and min_payment values match debts.csv for those names
                debts_map = { d["name"]: d for d in load_debts(debt_rows) }
                vals_ok = True
                for item in first_three:
                    if not isinstance(item, dict):
                        vals_ok = False
                        break
                    nm = item.get("name")
                    if nm not in debts_map:
                        vals_ok = False
                        break
                    exp_apr = debts_map[nm]["apr_percent"]
                    exp_min = debts_map[nm]["min_payment"]
                    if not approx_equal(item.get("apr_percent"), exp_apr, 0.01):
                        vals_ok = False
                        break
                    if not approx_equal(item.get("min_payment"), exp_min, 0.01):
                        vals_ok = False
                        break
                    # ensure priority field present and is int-like
                    pr = item.get("priority")
                    try:
                        int(pr)
                    except Exception:
                        vals_ok = False
                        break
                if vals_ok:
                    checks["triage_values_match_ok"] = True
        except Exception:
            pass

    # next_actions.md checks
    actions_file = os.path.join(output_dir, "next_actions.md")
    if os.path.isfile(actions_file):
        checks["actions_exists"] = True
        try:
            with open(actions_file, "r", encoding="utf-8") as fh:
                txt = fh.read()
            # At least 3 lines
            line_count = len([ln for ln in txt.splitlines() if ln.strip()])
            substrings_ok = all([
                ("CC BankX" in txt),
                ("2026-03-17" in txt),
                ("Student Loan" in txt),
                ("2026-03-25" in txt),
                (("Electric Co" in txt) or ("Cloud Storage" in txt)),
            ])
            if line_count >= 3 and substrings_ok:
                checks["actions_substrings_ok"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0
    # Ensure exact 0.0 on no-op baseline (no output files)
    output_exists = any(os.path.isfile(os.path.join(output_dir, fn)) for fn in [
        "cashflow_summary.json", "recurring.json", "runway_review.json", "debt_triage.json", "next_actions.md"
    ])
    if not output_exists:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()