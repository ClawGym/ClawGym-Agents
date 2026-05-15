import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, f"no_header_{path}"
            # Normalize headers by stripping spaces
            headers = [h.strip() if isinstance(h, str) else h for h in reader.fieldnames]
            rows = []
            for raw_row in reader:
                row = {}
                for k in reader.fieldnames:
                    key = k.strip() if isinstance(k, str) else k
                    val = raw_row.get(k, "")
                    if isinstance(val, str):
                        val = val.strip()
                    row[key] = val
                rows.append(row)
            return {"headers": headers, "rows": rows}, None
    except Exception as e:
        return None, f"error_reading_{path}: {e}"


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"error_loading_json_{path}: {e}"


def _to_decimal(val):
    try:
        if isinstance(val, (int, float)):
            # Avoid float inaccuracies by stringifying
            val = f"{val}"
        if isinstance(val, str):
            val = val.strip()
        d = Decimal(val)
        return d
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_date_month(date_str: str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m")
    except Exception:
        return None


def _quantize_2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _csv_headers_match_exact(got_headers, expected_headers):
    return list(got_headers) == list(expected_headers)


def _normalize_badminton_row(row):
    # Normalized tuple for comparison: (date, description, type, amount(Decimal), currency, category, month)
    amt = _to_decimal(row.get("amount", ""))
    if amt is None:
        return None
    try:
        # ensure normalized values as strings and strip
        date = (row.get("date") or "").strip()
        desc = (row.get("description") or "").strip()
        typ = (row.get("type") or "").strip()
        cur = (row.get("currency") or "").strip()
        cat = (row.get("category") or "").strip()
        month = (row.get("month") or "").strip()
        return (date, desc, typ, _quantize_2(amt), cur, cat, month)
    except Exception:
        return None


def _compute_expected_badminton(trans_rows):
    # Filter by category == "Sports - Badminton" and type in ["debit","credit"]
    expected = []
    seen = set()
    for r in trans_rows:
        category = (r.get("category") or "").strip()
        typ = (r.get("type") or "").strip()
        if category != "Sports - Badminton":
            continue
        if typ not in ("debit", "credit"):
            continue
        date = (r.get("date") or "").strip()
        desc = (r.get("description") or "").strip()
        amt = _to_decimal(r.get("amount", ""))
        cur = (r.get("currency") or "").strip()
        if not date or amt is None:
            # skip malformed
            continue
        dedup_key = (date, desc, typ, _quantize_2(amt))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        month = _parse_date_month(date)
        if not month:
            continue
        expected.append({
            "date": date,
            "description": desc,
            "type": typ,
            "amount": _quantize_2(amt),  # keep as Decimal for later compare
            "currency": cur,
            "category": category,
            "month": month,
        })
    return expected


def _compute_expected_monthly_summary(badminton_rows):
    # For months 2025-01 and 2025-02
    totals = {
        "2025-01": {"debit": Decimal("0.00"), "credit": Decimal("0.00")},
        "2025-02": {"debit": Decimal("0.00"), "credit": Decimal("0.00")},
    }
    for r in badminton_rows:
        month = r["month"]
        if month not in totals:
            continue
        amt = r["amount"]
        typ = r["type"]
        if typ == "debit":
            totals[month]["debit"] += amt
        elif typ == "credit":
            totals[month]["credit"] += amt
    result = {}
    for m in ["2025-01", "2025-02"]:
        deb = _quantize_2(totals[m]["debit"])
        cre = _quantize_2(totals[m]["credit"])
        net = _quantize_2(deb - cre)
        result[m] = {"total_debits": deb, "total_credits": cre, "net_total": net}
    return result


def _compute_expected_cross_check(trans_rows):
    # Scan non-badminton category descriptions for keywords
    keywords = ["badminton", "court", "shuttle", "racket", "string", "coach", "club", "mixed doubles"]
    expected = []
    for r in trans_rows:
        category = (r.get("category") or "").strip()
        if category == "Sports - Badminton":
            continue
        desc = (r.get("description") or "").strip()
        desc_lower = desc.lower()
        matched = None
        for kw in keywords:
            if kw in desc_lower:
                matched = kw
                break
        if matched:
            # Include row
            date = (r.get("date") or "").strip()
            typ = (r.get("type") or "").strip()
            amt = _to_decimal(r.get("amount", ""))
            cur = (r.get("currency") or "").strip()
            if not date or amt is None:
                continue
            expected.append({
                "date": date,
                "description": desc,
                "type": typ,
                "amount": _quantize_2(amt),
                "currency": cur,
                "category": category,
                "matched_keyword": matched,
            })
    return expected


def _compute_expected_budget_summary(budget_rows):
    per_cat = defaultdict(Decimal)
    grand_total = Decimal("0.00")
    currency_per_row = set()
    for r in budget_rows:
        cat = (r.get("category") or "").strip()
        cost = _to_decimal(r.get("cost", ""))
        cur = (r.get("currency") or "").strip()
        if cost is None:
            # malformed -> treat as failure later
            return None, None
        per_cat[cat] += _quantize_2(cost)
        grand_total += _quantize_2(cost)
        if cur:
            currency_per_row.add(cur)
    # Assume USD; but ensure if currency present, it's USD only
    currency = "USD" if not currency_per_row else (currency_per_row.pop() if len(currency_per_row) == 1 else None)
    if currency is None:
        return None, None
    # Build summary list
    summary = []
    for cat, total in per_cat.items():
        summary.append({"category": cat, "total_cost": _quantize_2(total), "currency": currency})
    return summary, _quantize_2(grand_total)


def _rows_to_set_badminton(rows):
    res = set()
    for r in rows:
        t = _normalize_badminton_row(r)
        if t is None:
            return None
        res.add(t)
    return res


def _rows_to_set_crosscheck(rows):
    res = set()
    for r in rows:
        amt = _to_decimal(r.get("amount", ""))
        if amt is None:
            return None
        try:
            date = (r.get("date") or "").strip()
            desc = (r.get("description") or "").strip()
            typ = (r.get("type") or "").strip()
            cur = (r.get("currency") or "").strip()
            cat = (r.get("category") or "").strip()
            mk = (r.get("matched_keyword") or "").strip().lower()
            res.add((date, desc, typ, _quantize_2(amt), cur, cat, mk))
        except Exception:
            return None
    return res


def _rows_to_map_budget(rows):
    res = {}
    for r in rows:
        amt = _to_decimal(r.get("total_cost", ""))
        if amt is None:
            return None
        cat = (r.get("category") or "").strip()
        cur = (r.get("currency") or "").strip()
        res[cat] = (_quantize_2(amt), cur)
    return res


def _validate_two_decimal_string(s: str) -> bool:
    return isinstance(s, str) and re.fullmatch(r"-?\d+\.\d{2}", s.strip()) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "badminton_transactions_csv_correct": 0.0,
        "monthly_summary_csv_correct": 0.0,
        "potential_missed_badminton_csv_correct": 0.0,
        "tournament_budget_summary_csv_correct": 0.0,
        "report_json_correct": 0.0,
    }

    # Load inputs
    tx_path = workspace / "input" / "transactions.csv"
    budget_path = workspace / "input" / "tournament_budget.csv"

    tx_data, tx_err = _read_csv_dicts(tx_path)
    budget_data, budget_err = _read_csv_dicts(budget_path)

    # Prepare expected values if inputs are available
    tx_rows = tx_data["rows"] if tx_data else None
    budget_rows = budget_data["rows"] if budget_data else None

    expected_badminton = None
    expected_monthly = None
    expected_cross = None
    expected_budget_summary = None
    expected_budget_total = None

    if tx_rows is not None:
        expected_badminton = _compute_expected_badminton(tx_rows)
        expected_monthly = _compute_expected_monthly_summary(expected_badminton)
        expected_cross = _compute_expected_cross_check(tx_rows)

    if budget_rows is not None:
        expected_budget_summary, expected_budget_total = _compute_expected_budget_summary(budget_rows)

    # Check badminton_transactions.csv
    bt_path = workspace / "output" / "badminton_transactions.csv"
    if expected_badminton is not None and bt_path.exists():
        out_bt, out_err = _read_csv_dicts(bt_path)
        if out_bt and _csv_headers_match_exact(out_bt["headers"], ["date", "description", "type", "amount", "currency", "category", "month"]):
            # Normalize and compare sets
            # Convert expected to comparable tuples
            expected_set = set()
            for r in expected_badminton:
                expected_set.add((r["date"], r["description"], r["type"], r["amount"], r["currency"], r["category"], r["month"]))
            output_set = _rows_to_set_badminton(out_bt["rows"])
            # Check duplicates by (date, description, type, amount)
            dedup_keys = set()
            has_dup = False
            for r in out_bt["rows"]:
                amt = _to_decimal(r.get("amount", ""))
                if amt is None:
                    has_dup = True
                    break
                k = ((r.get("date") or "").strip(), (r.get("description") or "").strip(), (r.get("type") or "").strip(), _quantize_2(amt))
                if k in dedup_keys:
                    has_dup = True
                    break
                dedup_keys.add(k)
                # Verify month correctness paired with date
                date = (r.get("date") or "").strip()
                month = (r.get("month") or "").strip()
                expected_month = _parse_date_month(date)
                if expected_month is None or expected_month != month:
                    has_dup = True
                    break
            if output_set is not None and not has_dup and output_set == expected_set and len(out_bt["rows"]) == len(expected_badminton):
                scores["badminton_transactions_csv_correct"] = 1.0

    # Check monthly_badminton_summary.csv
    ms_path = workspace / "output" / "monthly_badminton_summary.csv"
    if expected_monthly is not None and ms_path.exists():
        out_ms, out_err = _read_csv_dicts(ms_path)
        if out_ms and _csv_headers_match_exact(out_ms["headers"], ["month", "total_debits", "total_credits", "net_total"]):
            # Build mapping and validate formatting and values
            ok = True
            found_months = {}
            for r in out_ms["rows"]:
                month = (r.get("month") or "").strip()
                td = r.get("total_debits", "")
                tc = r.get("total_credits", "")
                nt = r.get("net_total", "")
                if not (_validate_two_decimal_string(td) and _validate_two_decimal_string(tc) and _validate_two_decimal_string(nt)):
                    ok = False
                    break
                td_dec = _to_decimal(td)
                tc_dec = _to_decimal(tc)
                nt_dec = _to_decimal(nt)
                if td_dec is None or tc_dec is None or nt_dec is None:
                    ok = False
                    break
                found_months[month] = {"total_debits": _quantize_2(td_dec), "total_credits": _quantize_2(tc_dec), "net_total": _quantize_2(nt_dec)}
            # Must exactly contain 2025-01 and 2025-02 and nothing else
            if ok and set(found_months.keys()) == {"2025-01", "2025-02"}:
                for m in ["2025-01", "2025-02"]:
                    exp = expected_monthly[m]
                    got = found_months[m]
                    if not (got["total_debits"] == exp["total_debits"] and got["total_credits"] == exp["total_credits"] and got["net_total"] == exp["net_total"]):
                        ok = False
                        break
            else:
                ok = False
            if ok:
                scores["monthly_summary_csv_correct"] = 1.0

    # Check potential_missed_badminton.csv
    pm_path = workspace / "output" / "potential_missed_badminton.csv"
    if expected_cross is not None and pm_path.exists():
        out_pm, out_err = _read_csv_dicts(pm_path)
        if out_pm and _csv_headers_match_exact(out_pm["headers"], ["date", "description", "type", "amount", "currency", "category", "matched_keyword"]):
            expected_set = set()
            for r in expected_cross:
                expected_set.add((r["date"], r["description"], r["type"], r["amount"], r["currency"], r["category"], r["matched_keyword"].lower()))
            output_set = _rows_to_set_crosscheck(out_pm["rows"])
            if output_set is not None and output_set == expected_set and len(out_pm["rows"]) == len(expected_cross):
                scores["potential_missed_badminton_csv_correct"] = 1.0

    # Check tournament_budget_summary.csv
    tb_path = workspace / "output" / "tournament_budget_summary.csv"
    if expected_budget_summary is not None and tb_path.exists():
        out_tb, out_err = _read_csv_dicts(tb_path)
        if out_tb and _csv_headers_match_exact(out_tb["headers"], ["category", "total_cost", "currency"]):
            got_map = _rows_to_map_budget(out_tb["rows"])
            if got_map is not None:
                # Build expected map
                exp_map = {r["category"]: (r["total_cost"], r["currency"]) for r in expected_budget_summary}
                # Compare keys and values
                if set(got_map.keys()) == set(exp_map.keys()):
                    ok = True
                    for cat in exp_map:
                        g_amt, g_cur = got_map[cat]
                        e_amt, e_cur = exp_map[cat]
                        if g_cur != e_cur or g_amt != e_amt:
                            ok = False
                            break
                    if ok:
                        scores["tournament_budget_summary_csv_correct"] = 1.0

    # Check report.json
    report_path = workspace / "output" / "report.json"
    if expected_monthly is not None and expected_budget_total is not None and report_path.exists():
        data, jerr = _load_json(report_path)
        if isinstance(data, dict):
            ok = True
            # months_analyzed
            months_analyzed = data.get("months_analyzed")
            if months_analyzed != ["2025-01", "2025-02"]:
                ok = False
            # badminton_net_spend_by_month
            bnm = data.get("badminton_net_spend_by_month")
            if not isinstance(bnm, dict):
                ok = False
            else:
                # Compare within 0.01 tolerance
                for m in ["2025-01", "2025-02"]:
                    if m not in bnm:
                        ok = False
                        break
                    val = bnm[m]
                    val_dec = _to_decimal(val)
                    if val_dec is None:
                        ok = False
                        break
                    val_dec = _quantize_2(val_dec)
                    if val_dec != expected_monthly[m]["net_total"]:
                        ok = False
                        break
            # average_monthly_badminton_spend
            avg = data.get("average_monthly_badminton_spend")
            avg_dec = _to_decimal(avg) if ok else None
            if avg_dec is None:
                ok = False
            else:
                avg_dec = _quantize_2(avg_dec)
                exp_avg = _quantize_2((expected_monthly["2025-01"]["net_total"] + expected_monthly["2025-02"]["net_total"]) / Decimal("2"))
                if avg_dec != exp_avg:
                    ok = False
            # tournament_budget_total
            tbt = data.get("tournament_budget_total")
            tbt_dec = _to_decimal(tbt) if ok else None
            if tbt_dec is None:
                ok = False
            else:
                tbt_dec = _quantize_2(tbt_dec)
                if tbt_dec != expected_budget_total:
                    ok = False
            # months_to_cover_budget_at_current_average (rounded to two decimals)
            mtc = data.get("months_to_cover_budget_at_current_average")
            mtc_dec = _to_decimal(mtc) if ok else None
            if mtc_dec is None:
                ok = False
            else:
                mtc_dec = _quantize_2(mtc_dec)
                if avg_dec is None or avg_dec == Decimal("0.00"):
                    ok = False
                else:
                    exp_mtc = _quantize_2(expected_budget_total / avg_dec)
                    if mtc_dec != exp_mtc:
                        ok = False
            # cross_check object
            cross = data.get("cross_check")
            if not isinstance(cross, dict):
                ok = False
            else:
                pmc = cross.get("potential_missed_count")
                notes = cross.get("notes")
                exp_pmc = len(expected_cross) if expected_cross is not None else 0
                if not isinstance(pmc, int) or pmc != exp_pmc:
                    ok = False
                expected_notes = "Keyword matches listed in potential_missed_badminton.csv are not included in spend totals."
                if notes != expected_notes:
                    ok = False
            if ok:
                scores["report_json_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()