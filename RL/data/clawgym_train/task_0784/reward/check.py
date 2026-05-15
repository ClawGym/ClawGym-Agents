import json
import csv
import sys
import re
from pathlib import Path
from datetime import date, datetime, timedelta


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _parse_iso_date(s: str):
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _parse_amount(s: str):
    if s is None:
        return None
    try:
        s2 = str(s).strip().replace("$", "").replace(",", "")
        if s2 == "":
            return 0.0
        return float(s2)
    except Exception:
        return None


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_start_end(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def _months_in_range(start: date, end: date):
    months = []
    cur = date(start.year, start.month, 1)
    end_norm = date(end.year, end.month, 1)
    while cur <= end_norm:
        months.append(f"{cur.year:04d}-{cur.month:02d}")
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return months


def _parse_config_yaml(path: Path):
    text = _safe_read_text(path)
    if text is None:
        return None
    opening_balance = None
    reserve_minimum = None
    rp_start = None
    rp_end = None
    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            if not raw_line.startswith(" "):
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "opening_balance":
                    opening_balance = _parse_amount(val.strip().strip("'").strip('"'))
                elif key == "reserve_minimum":
                    reserve_minimum = _parse_amount(val.strip().strip("'").strip('"'))
                elif key == "reporting_period":
                    current_section = "reporting_period"
                else:
                    current_section = None
            else:
                if current_section == "reporting_period":
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("'").strip('"')
                    if key == "start":
                        rp_start = _parse_iso_date(val)
                    elif key == "end":
                        rp_end = _parse_iso_date(val)
    if opening_balance is None or reserve_minimum is None or rp_start is None or rp_end is None:
        return None
    return {
        "opening_balance": opening_balance,
        "reserve_minimum": reserve_minimum,
        "period_start": rp_start,
        "period_end": rp_end,
    }


def _approx_equal(a: float, b: float, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _parse_bool_cell(s: str):
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"true", "t", "yes", "y", "1"}:
        return True
    if v in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _contains_number_approximately(text: str, value: float, tol: float = 0.01) -> bool:
    if text is None:
        return False
    cleaned = text.replace("$", "")
    num_pattern = r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?"
    matches = re.findall(num_pattern, cleaned)
    for m in matches:
        try:
            v = float(m.replace(",", ""))
            if abs(v - value) <= tol:
                return True
        except Exception:
            continue
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "finance_summary_exists": 0.0,
        "finance_summary_columns_and_months": 0.0,
        "finance_summary_donations_match_inputs": 0.0,
        "finance_summary_expenses_match_inputs": 0.0,
        "finance_summary_net_and_balance_consistency": 0.0,
        "finance_summary_pct_and_below_reserve_validity": 0.0,
        "pledge_status_exists": 0.0,
        "pledge_status_columns_and_rows": 0.0,
        "pledge_status_expected_and_actual_correct": 0.0,
        "pledge_status_fulfillment_rate_correct": 0.0,
        "status_update_exists": 0.0,
        "status_update_totals_correct": 0.0,
        "status_update_reserve_note_present": 0.0,
        "status_update_career_transition_spending_mentioned": 0.0,
        "validation_report_exists_and_well_formed": 0.0,
        "validation_report_includes_required_checks": 0.0,
        "validation_log_exists_and_contains_summary": 0.0,
    }

    cfg = _parse_config_yaml(workspace / "input" / "config.yaml")
    donations_rows, _ = _load_csv_dicts(workspace / "input" / "transactions_donations.csv")
    expenses_rows, _ = _load_csv_dicts(workspace / "input" / "transactions_expenses.csv")
    pledges_rows, _ = _load_csv_dicts(workspace / "input" / "pledges.csv")

    if cfg and donations_rows is not None and expenses_rows is not None:
        period_start = cfg["period_start"]
        period_end = cfg["period_end"]
        months = _months_in_range(period_start, period_end)

        donations_by_month = {m: 0.0 for m in months}
        expenses_by_month = {m: 0.0 for m in months}
        ct_expenses_by_month = {m: 0.0 for m in months}

        for r in donations_rows:
            d = _parse_iso_date(r.get("date", ""))
            if d is None:
                donations_by_month = None
                break
            if period_start <= d <= period_end:
                amt = _parse_amount(r.get("amount"))
                if amt is None:
                    donations_by_month = None
                    break
                key = _month_key(d)
                if key in donations_by_month:
                    donations_by_month[key] += amt

        for r in expenses_rows:
            d = _parse_iso_date(r.get("date", ""))
            if d is None:
                expenses_by_month = None
                ct_expenses_by_month = None
                break
            if period_start <= d <= period_end:
                amt = _parse_amount(r.get("amount"))
                if amt is None:
                    expenses_by_month = None
                    ct_expenses_by_month = None
                    break
                key = _month_key(d)
                if key in expenses_by_month:
                    expenses_by_month[key] += amt
                    cat = (r.get("category") or "").strip()
                    if cat == "Grant:CareerTransition":
                        ct_expenses_by_month[key] += amt

        ytd_donations_total = None
        ytd_expenses_total = None
        if donations_by_month is not None and expenses_by_month is not None:
            ytd_donations_total = sum(donations_by_month.values())
            ytd_expenses_total = sum(expenses_by_month.values())
        ytd_ct_expenses_total = None
        if ct_expenses_by_month is not None:
            ytd_ct_expenses_total = sum(ct_expenses_by_month.values())

        opening_balance = cfg["opening_balance"]
        reserve_minimum = cfg["reserve_minimum"]
        expected_nets_by_month = None
        expected_cum_by_month = None
        if donations_by_month is not None and expenses_by_month is not None:
            expected_nets_by_month = {m: donations_by_month[m] - expenses_by_month[m] for m in months}
            expected_cum_by_month = {}
            running = opening_balance
            for m in months:
                running += expected_nets_by_month[m]
                expected_cum_by_month[m] = running
    else:
        months = []
        donations_by_month = None
        expenses_by_month = None
        ct_expenses_by_month = None
        ytd_donations_total = None
        ytd_expenses_total = None
        ytd_ct_expenses_total = None
        expected_nets_by_month = None
        expected_cum_by_month = None
        opening_balance = None
        reserve_minimum = None

    finance_summary_path = workspace / "output" / "finance_summary.csv"
    if finance_summary_path.exists():
        scores["finance_summary_exists"] = 1.0
        fs_rows, fs_fields = _load_csv_dicts(finance_summary_path)
        if fs_rows is not None and fs_fields is not None:
            expected_cols = ["month", "donations", "expenses", "net", "cum_balance", "pct_careertransition_expenses", "below_reserve"]
            cols_ok = fs_fields == expected_cols
            months_ok = False
            fs_months = []
            per_row_parsed = []
            parse_error = False
            for r in fs_rows:
                m = (r.get("month") or "").strip()
                fs_months.append(m)
                d_amt = _parse_amount(r.get("donations"))
                e_amt = _parse_amount(r.get("expenses"))
                n_amt = _parse_amount(r.get("net"))
                c_amt = _parse_amount(r.get("cum_balance"))
                p_amt = _parse_amount(r.get("pct_careertransition_expenses"))
                b_val = _parse_bool_cell(r.get("below_reserve"))
                if any(v is None for v in [d_amt, e_amt, n_amt, c_amt, p_amt]) or b_val is None:
                    parse_error = True
                    break
                per_row_parsed.append((m, d_amt, e_amt, n_amt, c_amt, p_amt, b_val))
            if not parse_error and cfg:
                months_ok = (fs_months == months)
            if cols_ok and months_ok and not parse_error:
                scores["finance_summary_columns_and_months"] = 1.0

            if (donations_by_month is not None) and not parse_error and cfg:
                computed_total = sum(donations_by_month.values())
                file_total = sum(x[1] for x in per_row_parsed)
                per_month_ok = True
                for (m, d_amt, _, _, _, _, _) in per_row_parsed:
                    if not _approx_equal(d_amt, donations_by_month.get(m, None), 0.02):
                        per_month_ok = False
                        break
                if _approx_equal(computed_total, file_total, 0.05) and per_month_ok:
                    scores["finance_summary_donations_match_inputs"] = 1.0

            if (expenses_by_month is not None) and not parse_error and cfg:
                computed_total_e = sum(expenses_by_month.values())
                file_total_e = sum(x[2] for x in per_row_parsed)
                per_month_ok_e = True
                for (m, _, e_amt, _, _, _, _) in per_row_parsed:
                    if not _approx_equal(e_amt, expenses_by_month.get(m, None), 0.02):
                        per_month_ok_e = False
                        break
                if _approx_equal(computed_total_e, file_total_e, 0.05) and per_month_ok_e:
                    scores["finance_summary_expenses_match_inputs"] = 1.0

            if not parse_error and cfg:
                net_ok = True
                cum_ok = True
                running = opening_balance
                for (m, d_amt, e_amt, n_amt, c_amt, _, _) in per_row_parsed:
                    if not _approx_equal(n_amt, d_amt - e_amt, 0.02):
                        net_ok = False
                        break
                    running += n_amt
                    if not _approx_equal(c_amt, running, 0.05):
                        cum_ok = False
                        break
                if net_ok and cum_ok:
                    scores["finance_summary_net_and_balance_consistency"] = 1.0

            if not parse_error and cfg and ct_expenses_by_month is not None:
                pct_ok = True
                below_ok = True
                running = opening_balance
                for (m, d_amt, e_amt, _n_amt, _c_amt, p_amt, b_val) in per_row_parsed:
                    exp_total = expenses_by_month.get(m) if expenses_by_month else None
                    exp_ct = ct_expenses_by_month.get(m) if ct_expenses_by_month else None
                    if exp_total is None or exp_ct is None:
                        pct_ok = False
                        break
                    expected_pct = 0.0 if _approx_equal(exp_total, 0.0, 1e-9) else (exp_ct / exp_total)
                    if not _approx_equal(p_amt, expected_pct, 0.01):
                        pct_ok = False
                        break
                    running += (d_amt - e_amt)
                    expected_below = running < reserve_minimum
                    if b_val != expected_below:
                        below_ok = False
                        break
                if pct_ok and below_ok:
                    scores["finance_summary_pct_and_below_reserve_validity"] = 1.0

    pledge_status_path = workspace / "output" / "pledge_status.csv"
    if pledge_status_path.exists():
        scores["pledge_status_exists"] = 1.0
        ps_rows, ps_fields = _load_csv_dicts(pledge_status_path)
        if ps_rows is not None and ps_fields is not None:
            expected_ps_cols = ["pledge_id", "donor_name", "designated_fund", "months_in_period", "expected_received", "actual_received", "fulfillment_rate_percent"]
            cols_ok = ps_fields == expected_ps_cols
            rows_ok = False
            parse_error = False
            parsed = {}
            for r in ps_rows:
                pid = (r.get("pledge_id") or "").strip()
                if pid == "":
                    parse_error = True
                    break
                donor = (r.get("donor_name") or "").strip()
                fund = (r.get("designated_fund") or "").strip()
                months_in_period = r.get("months_in_period")
                expected_received = r.get("expected_received")
                actual_received = r.get("actual_received")
                frate = r.get("fulfillment_rate_percent")
                mi = None if months_in_period is None else _parse_amount(str(months_in_period))
                er = _parse_amount(expected_received)
                ar = _parse_amount(actual_received)
                fr = _parse_amount(frate)
                if mi is None or er is None or ar is None or fr is None:
                    parse_error = True
                    break
                try:
                    mi_int = int(round(mi))
                except Exception:
                    parse_error = True
                    break
                parsed[pid] = {
                    "donor_name": donor,
                    "designated_fund": fund,
                    "months_in_period": mi_int,
                    "expected_received": er,
                    "actual_received": ar,
                    "fulfillment_rate_percent": fr,
                }
            if not parse_error and pledges_rows is not None and cfg:
                pledges_ids = [(r.get("pledge_id") or "").strip() for r in pledges_rows]
                if set(parsed.keys()) == set(pledges_ids) and len(parsed) == len(pledges_rows):
                    rows_ok = True
            if cols_ok and rows_ok and not parse_error:
                scores["pledge_status_columns_and_rows"] = 1.0

            expected_ok = False
            fulfillment_ok = False
            if pledges_rows is not None and donations_rows is not None and cfg and not parse_error:
                period_start = cfg["period_start"]
                period_end = cfg["period_end"]
                actual_by_pledge = {}
                for dr in donations_rows:
                    d = _parse_iso_date(dr.get("date", ""))
                    if d is None:
                        actual_by_pledge = None
                        break
                    if period_start <= d <= period_end:
                        pid = (dr.get("pledge_id") or "").strip()
                        amt = _parse_amount(dr.get("amount"))
                        if amt is None:
                            actual_by_pledge = None
                            break
                        if pid != "":
                            actual_by_pledge[pid] = actual_by_pledge.get(pid, 0.0) + amt
                if actual_by_pledge is not None:
                    expected_all_good = True
                    fr_all_good = True
                    for pr in pledges_rows:
                        pid = (pr.get("pledge_id") or "").strip()
                        donor = (pr.get("donor_name") or "").strip()
                        fund = (pr.get("designated_fund") or "").strip()
                        start = _parse_iso_date(pr.get("start_date") or "")
                        end = _parse_iso_date(pr.get("end_date") or "")
                        monthly_amount = _parse_amount(pr.get("monthly_amount"))
                        if monthly_amount is None:
                            expected_all_good = False
                            fr_all_good = False
                            break
                        active_start = start if start else period_start
                        active_end = end if end else period_end
                        if active_start < period_start:
                            active_start = period_start
                        if active_end > period_end:
                            active_end = period_end
                        count = 0
                        for m in _months_in_range(period_start, period_end):
                            y, mo = int(m.split("-")[0]), int(m.split("-")[1])
                            ms, me = _month_start_end(y, mo)
                            if not (active_end < ms or active_start > me):
                                count += 1
                        expected_received = monthly_amount * count
                        actual_received = actual_by_pledge.get(pid, 0.0)
                        frow = parsed.get(pid)
                        if frow is None:
                            expected_all_good = False
                            fr_all_good = False
                            break
                        if frow["donor_name"] != donor or frow["designated_fund"] != fund:
                            expected_all_good = False
                        if frow["months_in_period"] != count:
                            expected_all_good = False
                        if not _approx_equal(frow["expected_received"], expected_received, 0.02):
                            expected_all_good = False
                        if not _approx_equal(frow["actual_received"], actual_received, 0.02):
                            expected_all_good = False
                        if expected_received > 0:
                            expected_rate = (actual_received / expected_received) * 100.0
                            if not _approx_equal(frow["fulfillment_rate_percent"], expected_rate, 0.1):
                                fr_all_good = False
                    if expected_all_good:
                        scores["pledge_status_expected_and_actual_correct"] = 1.0
                    if fr_all_good:
                        scores["pledge_status_fulfillment_rate_correct"] = 1.0

    status_path = workspace / "output" / "status_update.md"
    if status_path.exists():
        scores["status_update_exists"] = 1.0
        text = _safe_read_text(status_path)
        if text is None:
            text = ""
        totals_ok = False
        reserve_note_ok = False
        ct_spending_ok = False
        if cfg and donations_by_month is not None and expenses_by_month is not None and expected_cum_by_month is not None and ct_expenses_by_month is not None:
            ytd_don = sum(donations_by_month.values())
            ytd_exp = sum(expenses_by_month.values())
            ytd_net = ytd_don - ytd_exp
            months_list = _months_in_range(cfg["period_start"], cfg["period_end"])
            end_month = months_list[-1] if months_list else None
            ending_balance = expected_cum_by_month.get(end_month) if end_month else None
            if ending_balance is not None:
                have_d = _contains_number_approximately(text, ytd_don, 0.05)
                have_e = _contains_number_approximately(text, ytd_exp, 0.05)
                have_n = _contains_number_approximately(text, ytd_net, 0.05)
                have_b = _contains_number_approximately(text, ending_balance, 0.05)
                if have_d and have_e and have_n and have_b:
                    totals_ok = True
            reserve_words = ("reserve",)
            mention_reserve = any(w in text.lower() for w in reserve_words)
            below_months = []
            running = cfg["opening_balance"]
            for m in months_list:
                running += (donations_by_month[m] - expenses_by_month[m])
                if running < cfg["reserve_minimum"]:
                    below_months.append(m)
            if mention_reserve:
                if len(below_months) == 0:
                    ok_keywords = ("maintained", "above", "met", "never dipped", "did not dip", "not below", "within")
                    if any(k in text.lower() for k in ok_keywords):
                        reserve_note_ok = True
                else:
                    month_names = {
                        "01": ["jan", "january"],
                        "02": ["feb", "february"],
                        "03": ["mar", "march"],
                        "04": ["apr", "april"],
                        "05": ["may"],
                        "06": ["jun", "june"],
                        "07": ["jul", "july"],
                        "08": ["aug", "august"],
                        "09": ["sep", "sept", "september"],
                        "10": ["oct", "october"],
                        "11": ["nov", "november"],
                        "12": ["dec", "december"],
                    }
                    mentions_any = False
                    for m in below_months:
                        y, mo = m.split("-")
                        if m in text:
                            mentions_any = True
                            break
                        for nm in month_names.get(mo, []):
                            if nm in text.lower():
                                mentions_any = True
                                break
                        if mentions_any:
                            break
                    if mentions_any or "below" in text.lower():
                        reserve_note_ok = True
            ct_total = sum(ct_expenses_by_month.values())
            if _contains_number_approximately(text, ct_total, 0.05):
                if ("career" in text.lower()) or ("transition" in text.lower()) or ("careertransition" in text.lower()):
                    ct_spending_ok = True
        if totals_ok:
            scores["status_update_totals_correct"] = 1.0
        if reserve_note_ok:
            scores["status_update_reserve_note_present"] = 1.0
        if ct_spending_ok:
            scores["status_update_career_transition_spending_mentioned"] = 1.0

    validation_report_path = workspace / "output" / "validation_report.json"
    if validation_report_path.exists():
        text = _safe_read_text(validation_report_path)
        try:
            data = json.loads(text) if text is not None else None
        except Exception:
            data = None
        well_formed = False
        includes_required = False
        if isinstance(data, dict):
            all_passed = isinstance(data.get("all_checks_passed"), bool)
            checks = data.get("checks")
            checks_ok = isinstance(checks, list)
            entries_ok = True
            if checks_ok:
                for entry in checks:
                    if not isinstance(entry, dict):
                        entries_ok = False
                        break
                    if "name" not in entry or "status" not in entry or "details" not in entry:
                        entries_ok = False
                        break
            if all_passed and checks_ok and entries_ok:
                well_formed = True
            if checks_ok:
                names = [str(c.get("name", "")).lower() for c in checks if isinstance(c, dict)]
                has_don = any(("donation" in n and "sum" in n) or ("donations" in n and "sum" in n) for n in names)
                has_exp = any(("expense" in n and "sum" in n) or ("expenses" in n and "sum" in n) for n in names)
                has_cum = any(("cum" in n and "balance" in n) or ("cumulative" in n and "balance" in n) for n in names)
                has_pledge = any(("pledge" in n and ("actual" in n or "expected" in n)) for n in names)
                if has_don and has_exp and has_cum and has_pledge:
                    includes_required = True
        if well_formed:
            scores["validation_report_exists_and_well_formed"] = 1.0
        if includes_required:
            scores["validation_report_includes_required_checks"] = 1.0

    validation_log_path = workspace / "output" / "VALIDATION_LOG.txt"
    if validation_log_path.exists():
        text = _safe_read_text(validation_log_path) or ""
        has_command = ("python" in text.lower()) or ("command" in text.lower()) or ("$" in text) or ("validation" in text.lower())
        has_summary = ("pass" in text.lower()) or ("fail" in text.lower()) or ("all_checks_passed" in text.lower())
        if has_command and has_summary:
            scores["validation_log_exists_and_contains_summary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()