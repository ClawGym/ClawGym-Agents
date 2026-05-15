import csv
import json
import re
import sys
from datetime import datetime, date
from pathlib import Path
from xml.etree import ElementTree as ET


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            headers = reader.fieldnames or []
        return rows, headers
    except Exception:
        return None, None


def _safe_float(x):
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _parse_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _is_close(a: float, b: float, abs_tol: float = 0.01) -> bool:
    try:
        return abs(a - b) <= abs_tol
    except Exception:
        return False


def _is_close_rel(a: float, b: float, rel_tol: float = 1e-6) -> bool:
    try:
        if b == 0:
            return abs(a) <= rel_tol
        return abs((a - b) / b) <= rel_tol
    except Exception:
        return False


def _load_ecb_rates(path: Path):
    # Returns (rates_by_ccy: dict[str, list[(date, rate)]], ok_structure: bool)
    if not path.exists():
        return None, False
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        # Find all Cube nodes with time attribute
        # ECB uses namespaces, so search regardless of namespace
        date_cubes = root.findall(".//{*}Cube[@time]")
        rates_by_ccy = {}
        for dc in date_cubes:
            time_attr = dc.attrib.get("time")
            d = _parse_date(time_attr) if time_attr else None
            if not d:
                continue
            for rc in list(dc):
                cur = rc.attrib.get("currency")
                rate = rc.attrib.get("rate")
                if not cur or not rate:
                    continue
                fr = _safe_float(rate)
                if fr is None:
                    continue
                rates_by_ccy.setdefault(cur.upper(), []).append((d, fr))
        # Sort lists by date
        for ccy in rates_by_ccy:
            rates_by_ccy[ccy].sort(key=lambda x: x[0])
        ok_structure = bool(date_cubes and len(rates_by_ccy) > 0)
        return rates_by_ccy, ok_structure
    except Exception:
        return None, False


def _find_rate_on_or_before(rates_by_ccy, ccy: str, for_date: date):
    # Returns (rate_date, rate) or (None, None)
    if rates_by_ccy is None:
        return None, None
    seq = rates_by_ccy.get(ccy.upper())
    if not seq:
        return None, None
    # Binary search greatest date <= for_date
    lo, hi = 0, len(seq) - 1
    best_idx = None
    while lo <= hi:
        mid = (lo + hi) // 2
        md = seq[mid][0]
        if md <= for_date:
            best_idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best_idx is None:
        return None, None
    return seq[best_idx]


def _multiset_count(list_of_tuples):
    d = {}
    for t in list_of_tuples:
        d[t] = d.get(t, 0) + 1
    return d


def _detect_month_column(headers, rows):
    # Prefer 'month', then 'year_month', else any column with values like YYYY-MM
    if "month" in headers:
        return "month"
    if "year_month" in headers:
        return "year_month"
    pattern = re.compile(r"^\d{4}-\d{2}$")
    for h in headers:
        # Check all populated values match pattern
        ok = True
        if len(rows) == 0:
            continue
        for r in rows:
            v = str(r.get(h, "")).strip()
            if not pattern.match(v):
                ok = False
                break
        if ok:
            return h
    return None


def _compute_monthly_summary_from_cleaned(cleaned_rows):
    summary = {}
    for r in cleaned_rows:
        ds = r.get("date", "").strip()
        d = _parse_date(ds)
        if not d:
            # Skip malformed date rows; they will cause structure/correctness to fail elsewhere
            return None
        month = f"{d.year:04d}-{d.month:02d}"
        cat = r.get("category", "")
        ea = _safe_float(r.get("eur_amount"))
        if ea is None:
            return None
        key = (month, cat)
        s, c = summary.get(key, (0.0, 0))
        summary[key] = (s + ea, c + 1)
    return summary


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_suspicious_rows(trans_rows, vendors_set):
    suspicious = []
    for r in trans_rows:
        category = (r.get("category") or "").strip()
        vendor = (r.get("vendor") or "").strip()
        currency = (r.get("currency") or "").strip()
        amount = (r.get("amount") or "").strip()
        ds = (r.get("date") or "").strip()
        # Condition 1
        if category == "Books" and vendor not in vendors_set:
            suspicious.append({
                "date": ds,
                "vendor": vendor,
                "category": category,
                "currency": currency,
                "amount": amount,
                "reason": "books_category_vendor_not_listed",
            })
        # Condition 2
        if vendor in vendors_set and category != "Books":
            suspicious.append({
                "date": ds,
                "vendor": vendor,
                "category": category,
                "currency": currency,
                "amount": amount,
                "reason": "vendor_listed_but_category_not_books",
            })
    return suspicious


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "pipeline_script_present": 0.0,
        "pipeline_script_uses_ecb_domain": 0.0,
        "exchange_rates_xml_present": 0.0,
        "exchange_rates_xml_parseable": 0.0,
        "exchange_rates_contains_usd_gbp": 0.0,
        "exchange_rates_cover_needed_txn_dates": 0.0,
        "cleaned_transactions_present": 0.0,
        "cleaned_transactions_structure": 0.0,
        "cleaned_preserves_original_columns_and_rows": 0.0,
        "cleaned_conversion_accuracy": 0.0,
        "monthly_summary_present": 0.0,
        "monthly_summary_structure": 0.0,
        "monthly_summary_correct": 0.0,
        "books_vendor_check_present": 0.0,
        "books_vendor_check_structure": 0.0,
        "books_vendor_check_correct": 0.0,
        "report_json_present": 0.0,
        "report_json_structure": 0.0,
        "report_json_correct": 0.0,
    }

    # Check pipeline script
    script_path = workspace / "scripts" / "run_analysis.sh"
    if script_path.exists():
        scores["pipeline_script_present"] = 1.0
        content = _read_text(script_path)
        if ("ecb.europa.eu" in content) and ("eurofxref-hist.xml" in content) and ("data/exchange_rates.xml" in content):
            scores["pipeline_script_uses_ecb_domain"] = 1.0

    # Input transactions and vendors
    input_transactions_path = workspace / "input" / "transactions.csv"
    input_vendors_path = workspace / "input" / "vendors_bookstores.csv"
    input_rows, input_headers = _load_csv_dicts(input_transactions_path)
    if input_rows is None:
        input_rows = []
        input_headers = []
    vendors_rows, vendors_headers = _load_csv_dicts(input_vendors_path)
    vendor_set = set()
    if vendors_rows is not None:
        for r in vendors_rows:
            v = (r.get("vendor") or "").strip()
            if v != "":
                vendor_set.add(v)

    # Exchange rates XML checks
    rates_path = workspace / "data" / "exchange_rates.xml"
    if rates_path.exists():
        scores["exchange_rates_xml_present"] = 1.0
    rates_by_ccy, ecb_ok = _load_ecb_rates(rates_path)
    if ecb_ok:
        scores["exchange_rates_xml_parseable"] = 1.0
        if ("USD" in rates_by_ccy) and ("GBP" in rates_by_ccy):
            scores["exchange_rates_contains_usd_gbp"] = 1.0

    # Needed dates coverage
    need_cover_ok = False
    if ecb_ok and input_rows is not None:
        needed = []
        for r in input_rows:
            ccy = (r.get("currency") or "").strip().upper()
            if ccy in ("USD", "GBP"):
                d = _parse_date((r.get("date") or "").strip())
                if d:
                    needed.append((ccy, d))
        if len(needed) == 0:
            # No non-EUR in inputs; trivially ok
            need_cover_ok = True
        else:
            ok_all = True
            for ccy, d in needed:
                rd, rr = _find_rate_on_or_before(rates_by_ccy, ccy, d)
                if rd is None or rr is None:
                    ok_all = False
                    break
            need_cover_ok = ok_all
    if need_cover_ok:
        scores["exchange_rates_cover_needed_txn_dates"] = 1.0

    # Cleaned transactions checks
    cleaned_path = workspace / "output" / "cleaned_transactions.csv"
    cleaned_rows, cleaned_headers = _load_csv_dicts(cleaned_path)
    if cleaned_rows is not None:
        scores["cleaned_transactions_present"] = 1.0

        required_original_cols = ["date", "description", "category", "currency", "amount", "vendor"]
        required_added_cols = ["eur_rate_used", "rate_date_used", "eur_amount"]

        structure_ok = True
        for col in required_original_cols + required_added_cols:
            if col not in (cleaned_headers or []):
                structure_ok = False
                break
        if structure_ok:
            scores["cleaned_transactions_structure"] = 1.0

        # Preserve original columns and rows (multiset equality of projections on original columns)
        preserve_ok = False
        if input_rows is not None and cleaned_rows is not None:
            inp_proj = [tuple((r.get(c) or "").strip() for c in required_original_cols) for r in input_rows]
            cln_proj = [tuple((r.get(c) or "").strip() for c in required_original_cols) for r in cleaned_rows]
            preserve_ok = _multiset_count(inp_proj) == _multiset_count(cln_proj)
        if preserve_ok:
            scores["cleaned_preserves_original_columns_and_rows"] = 1.0

        # Conversion accuracy using ECB rates
        conv_ok = True
        if not ecb_ok:
            conv_ok = False
        else:
            for r in cleaned_rows:
                date_str = (r.get("date") or "").strip()
                ccy = (r.get("currency") or "").strip().upper()
                amt_str = (r.get("amount") or "").strip()
                rate_used_str = (r.get("eur_rate_used") or "").strip()
                rate_date_used_str = (r.get("rate_date_used") or "").strip()
                eur_amt_str = (r.get("eur_amount") or "").strip()

                d = _parse_date(date_str)
                if not d:
                    conv_ok = False
                    break
                amt = _safe_float(amt_str)
                rate_used = _safe_float(rate_used_str)
                eur_amt = _safe_float(eur_amt_str)

                if amt is None or rate_used is None or eur_amt is None:
                    conv_ok = False
                    break

                if ccy == "EUR":
                    # eur_rate_used must be 1 and eur_amount equals amount; rate_date_used can be empty or equal to date
                    if not _is_close_rel(rate_used, 1.0, rel_tol=1e-12):
                        conv_ok = False
                        break
                    if not _is_close(eur_amt, amt, abs_tol=0.01):
                        conv_ok = False
                        break
                    if rate_date_used_str not in ("", date_str):
                        conv_ok = False
                        break
                elif ccy in ("USD", "GBP"):
                    rd, rr = _find_rate_on_or_before(rates_by_ccy, ccy, d)
                    if rd is None or rr is None:
                        conv_ok = False
                        break
                    # ECB quotes: foreign currency per 1 EUR => EUR = amount / rate
                    expected_rate = rr
                    expected_rate_date_str = rd.strftime("%Y-%m-%d")
                    if not _is_close_rel(rate_used, expected_rate, rel_tol=1e-6):
                        conv_ok = False
                        break
                    if rate_date_used_str != expected_rate_date_str:
                        conv_ok = False
                        break
                    expected_eur = amt / expected_rate
                    if not _is_close(eur_amt, expected_eur, abs_tol=0.01):
                        conv_ok = False
                        break
                else:
                    # Unknown currency: cannot validate
                    conv_ok = False
                    break
        if conv_ok:
            scores["cleaned_conversion_accuracy"] = 1.0

    # Monthly summary checks
    monthly_path = workspace / "output" / "monthly_summary.csv"
    monthly_rows, monthly_headers = _load_csv_dicts(monthly_path)
    if monthly_rows is not None:
        scores["monthly_summary_present"] = 1.0

        # Structure: must include a month-like column, category, total_eur_spend, txn_count
        structure_ok = False
        if monthly_headers is not None:
            month_col = _detect_month_column(monthly_headers, monthly_rows)
            if (month_col is not None) and ("category" in monthly_headers) and ("total_eur_spend" in monthly_headers) and ("txn_count" in monthly_headers):
                structure_ok = True
        if structure_ok:
            scores["monthly_summary_structure"] = 1.0

        # Correctness: compare against cleaned aggregation
        correct_ok = False
        if structure_ok and cleaned_rows is not None:
            expected = _compute_monthly_summary_from_cleaned(cleaned_rows)
            if expected is not None:
                # Build actual mapping
                month_col = _detect_month_column(monthly_headers, monthly_rows)
                actual = {}
                for r in monthly_rows:
                    m = (r.get(month_col) or "").strip()
                    cat = (r.get("category") or "").strip()
                    tes = _safe_float(r.get("total_eur_spend"))
                    tc = r.get("txn_count")
                    try:
                        tc_int = int(str(tc).strip())
                    except Exception:
                        tc_int = None
                    if tes is None or tc_int is None:
                        actual = None
                        break
                    actual[(m, cat)] = (tes, tc_int)
                if actual is not None:
                    # Compare keys
                    if set(actual.keys()) == set(expected.keys()):
                        # Compare values
                        ok_vals = True
                        for k, (exp_sum, exp_cnt) in expected.items():
                            # sums tolerance 0.01
                            act_sum, act_cnt = actual[k]
                            if not _is_close(act_sum, exp_sum, abs_tol=0.01):
                                ok_vals = False
                                break
                            if act_cnt != exp_cnt:
                                ok_vals = False
                                break
                        correct_ok = ok_vals
        if correct_ok:
            scores["monthly_summary_correct"] = 1.0

    # Books vendor check
    books_check_path = workspace / "output" / "books_vendor_check.csv"
    bvc_rows, bvc_headers = _load_csv_dicts(books_check_path)
    if bvc_rows is not None:
        scores["books_vendor_check_present"] = 1.0

        # Structure: must include required columns
        required_bvc_cols = {"date", "vendor", "category", "currency", "amount", "reason"}
        structure_ok = False
        if bvc_headers is not None:
            structure_ok = required_bvc_cols.issubset(set(bvc_headers))
        if structure_ok:
            scores["books_vendor_check_structure"] = 1.0

        # Correctness: compute expected suspicious from cleaned if available else input
        correct_ok = False
        base_rows = cleaned_rows if cleaned_rows is not None else input_rows
        if structure_ok and base_rows is not None and len(vendor_set) > 0:
            expected_list = _compute_suspicious_rows(base_rows, vendor_set)
            # Build projections to compare as multisets on required columns
            def proj(rows):
                res = []
                for r in rows:
                    # Only accept valid reasons
                    reason = (r.get("reason") or "").strip()
                    if reason not in ("books_category_vendor_not_listed", "vendor_listed_but_category_not_books"):
                        # Skip invalid reason row when building actual; will cause mismatch
                        pass
                    res.append((
                        (r.get("date") or "").strip(),
                        (r.get("vendor") or "").strip(),
                        (r.get("category") or "").strip(),
                        (r.get("currency") or "").strip(),
                        (r.get("amount") or "").strip(),
                        reason,
                    ))
                return res

            actual_proj = proj(bvc_rows)
            expected_proj = proj(expected_list)
            correct_ok = _multiset_count(actual_proj) == _multiset_count(expected_proj)
        if correct_ok:
            scores["books_vendor_check_correct"] = 1.0

    # Report JSON checks
    report_path = workspace / "output" / "report.json"
    report_obj = _load_json(report_path)
    if report_obj is not None:
        scores["report_json_present"] = 1.0

        # Structure
        structure_ok = False
        if isinstance(report_obj, dict):
            required_keys = {"total_eur_spend", "books_eur_spend", "books_share_of_total", "top_3_vendors_by_eur_spend"}
            if required_keys.issubset(set(report_obj.keys())) and isinstance(report_obj.get("top_3_vendors_by_eur_spend"), list):
                structure_ok = True
        if structure_ok:
            scores["report_json_structure"] = 1.0

        # Correctness: recompute from cleaned
        correct_ok = False
        if structure_ok and cleaned_rows is not None:
            total = 0.0
            books = 0.0
            by_vendor = {}
            for r in cleaned_rows:
                ea = _safe_float(r.get("eur_amount"))
                if ea is None:
                    by_vendor = None
                    break
                total += ea
                if (r.get("category") or "").strip() == "Books":
                    books += ea
                vendor = (r.get("vendor") or "").strip()
                by_vendor[vendor] = by_vendor.get(vendor, 0.0) + ea
            if by_vendor is not None:
                share = 0.0 if total == 0.0 else (books / total)
                # Sort vendors by spend desc, then vendor name asc for deterministic ordering
                sorted_vendors = sorted(by_vendor.items(), key=lambda kv: (-kv[1], kv[0]))
                top3 = sorted_vendors[:3]
                # Validate numbers with tolerance
                r_total = _safe_float(report_obj.get("total_eur_spend"))
                r_books = _safe_float(report_obj.get("books_eur_spend"))
                r_share = _safe_float(report_obj.get("books_share_of_total"))
                r_top = report_obj.get("top_3_vendors_by_eur_spend")
                if (
                    r_total is not None and r_books is not None and r_share is not None and isinstance(r_top, list)
                    and _is_close(r_total, total, abs_tol=0.01)
                    and _is_close(r_books, books, abs_tol=0.01)
                    and _is_close(r_share, share, abs_tol=1e-4)
                ):
                    # Validate top vendors
                    ok_top = True
                    if len(r_top) != len(top3):
                        ok_top = False
                    else:
                        for i, (vname, vsum) in enumerate(top3):
                            item = r_top[i]
                            if not isinstance(item, dict):
                                ok_top = False
                                break
                            iv = (item.get("vendor") or "").strip()
                            isum = _safe_float(item.get("eur_spend"))
                            if iv != vname or isum is None or not _is_close(isum, vsum, abs_tol=0.01):
                                ok_top = False
                                break
                    correct_ok = ok_top
        if correct_ok:
            scores["report_json_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1].strip() != "":
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()