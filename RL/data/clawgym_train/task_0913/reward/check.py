import json
import csv
import hashlib
import re
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _count_file_lines(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _load_ecb_rates(csv_path: Path) -> Tuple[Optional[Dict[date, Dict[str, float]]], Optional[List[str]]]:
    headers, rows = _read_csv_dicts(csv_path)
    if headers is None or rows is None:
        return None, None
    # Expect first column "Date" and others currency codes
    if len(headers) < 2 or headers[0].lower() != "date":
        return None, headers
    currencies = headers[1:]
    rate_map: Dict[date, Dict[str, float]] = {}
    for row in rows:
        d_str = row.get(headers[0], "")
        d = _parse_date(d_str)
        if d is None:
            # skip invalid date rows
            continue
        entry: Dict[str, float] = {}
        for cur in currencies:
            val = row.get(cur, "").strip()
            if val == "":
                continue
            try:
                entry[cur.upper()] = float(val)
            except Exception:
                # malformed value; treat as missing for that currency
                continue
        rate_map[d] = entry
    return rate_map, [c.upper() for c in currencies]


def _find_rate_date(target: date, available_dates: List[date]) -> Optional[date]:
    # Find the most recent preceding date <= target in available_dates
    # available_dates must be sorted ascending
    lo, hi = 0, len(available_dates) - 1
    idx = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if available_dates[mid] == target:
            idx = mid
            break
        elif available_dates[mid] < target:
            lo = mid + 1
            idx = mid
        else:
            hi = mid - 1
    if idx is None or idx < 0:
        return None
    if available_dates[idx] <= target:
        return available_dates[idx]
    return None


def _to_decimal(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "rates_archive_present": 0.0,
        "rates_csv_present_and_structure": 0.0,
        "normalized_csv_present_with_columns": 0.0,
        "normalized_eur_handling": 0.0,
        "normalized_fx_conversion_accuracy": 0.0,
        "normalized_fx_source_and_note_fields": 0.0,
        "monthly_summary_correctness": 0.0,
        "logs_archive_list_quality": 0.0,
        "logs_rate_sample_quality": 0.0,
        "logs_row_counts_quality": 0.0,
        "audit_report_content": 0.0,
    }

    # Paths
    expenses_csv = workspace / "input" / "expenses.csv"
    policy_md = workspace / "input" / "policy.md"
    zip_path = workspace / "downloads" / "ecb_eurofxref_hist.zip"
    rates_csv_path = workspace / "downloads" / "eurofxref-hist.csv"
    normalized_csv_path = workspace / "outputs" / "normalized_expenses.csv"
    monthly_summary_csv_path = workspace / "outputs" / "monthly_summary.csv"
    archive_list_log = workspace / "logs" / "archive_list.txt"
    row_counts_log = workspace / "logs" / "row_counts.txt"
    rate_sample_log = workspace / "logs" / "rate_sample.txt"
    audit_report_md = workspace / "outputs" / "audit_report.md"

    # Check rates archive presence
    if zip_path.exists() and zip_path.is_file():
        scores["rates_archive_present"] = 1.0

    # Load ECB rates CSV structure
    rates_map: Optional[Dict[date, Dict[str, float]]] = None
    currencies_in_rates: Optional[List[str]] = None
    if rates_csv_path.exists() and rates_csv_path.is_file():
        rates_map, currencies_in_rates = _load_ecb_rates(rates_csv_path)
        if rates_map is not None and currencies_in_rates is not None and "USD" in currencies_in_rates and "GBP" in currencies_in_rates:
            scores["rates_csv_present_and_structure"] = 1.0
        elif rates_map is not None:
            # At least structure ok but missing expected currencies; still fail the strict check
            scores["rates_csv_present_and_structure"] = 0.0

    # Read expenses
    exp_headers, expenses_rows = _read_csv_dicts(expenses_csv)
    _ = _read_text_safe(policy_md)  # not graded directly

    # Validate normalized CSV columns
    norm_headers, norm_rows = _read_csv_dicts(normalized_csv_path)
    expected_norm_cols = [
        "transaction_date",
        "vendor",
        "description",
        "original_currency",
        "original_amount",
        "rate_date_used",
        "rate_to_eur",
        "converted_amount_eur",
        "fx_source",
        "note",
    ]
    if norm_headers is not None and norm_rows is not None:
        if norm_headers == expected_norm_cols:
            scores["normalized_csv_present_with_columns"] = 1.0

    # Prepare conversion checks only if we have expenses, normalized, and rates
    eur_handling_ok = True
    fx_conversion_ok = True
    fx_source_note_ok = True
    monthly_summary_ok = True

    # Helper for matching normalized rows to expenses
    def _key_from_exp(row: Dict[str, str]) -> Tuple[str, str, str, str, str]:
        return (
            row.get("date", "").strip(),
            row.get("vendor", "").strip(),
            row.get("description", "").strip(),
            row.get("currency", "").strip().upper(),
            row.get("amount", "").strip(),
        )

    def _key_from_norm(row: Dict[str, str]) -> Tuple[str, str, str, str, str]:
        return (
            row.get("transaction_date", "").strip(),
            row.get("vendor", "").strip(),
            row.get("description", "").strip(),
            row.get("original_currency", "").strip().upper(),
            row.get("original_amount", "").strip(),
        )

    # Build index for normalized
    norm_index: Dict[Tuple[str, str, str, str, str], Dict[str, str]] = {}
    if norm_rows is not None:
        for r in norm_rows:
            norm_index[_key_from_norm(r)] = r

    # Compute EUR and conversions
    if (expenses_rows is not None and norm_rows is not None and rates_map is not None and currencies_in_rates is not None):
        # Check that normalized row count equals expenses row count (strict, given available currencies USD/GBP/EUR exist in ECB file)
        if len(norm_rows) != len(expenses_rows):
            eur_handling_ok = False
            fx_conversion_ok = False
            monthly_summary_ok = False
        available_dates_sorted = sorted(rates_map.keys())
        processed_count_calc = 0
        excluded_count_calc = 0
        # Track month totals for expected summary
        summary_expected: Dict[str, Tuple[float, int]] = {}
        for exp in expenses_rows:
            k = _key_from_exp(exp)
            norm = norm_index.get(k)
            if norm is None:
                # If normalized row not found, fail checks
                eur_handling_ok = False
                fx_conversion_ok = False
                monthly_summary_ok = False
                continue
            tdate_str = exp.get("date", "").strip()
            tdate = _parse_date(tdate_str)
            vendor = exp.get("vendor", "").strip()
            desc = exp.get("description", "").strip()
            currency = exp.get("currency", "").strip().upper()
            amt_str = exp.get("amount", "").strip()
            amt = _to_decimal(amt_str)

            # Basic field consistency
            if norm.get("vendor", "").strip() != vendor or norm.get("description", "").strip() != desc:
                fx_conversion_ok = False

            # FX source presence/content
            fx_source_val = (norm.get("fx_source", "") or "").strip()
            if fx_source_val == "" or not (("ECB" in fx_source_val.upper()) or ("EUROFXREF" in fx_source_val.lower())):
                fx_source_note_ok = False

            # Note may be blank, but must be present
            if "note" not in norm:
                fx_source_note_ok = False

            # Validate currency handling
            if currency == "EUR":
                # rate_to_eur should be 1.0 and converted amount equals original (rounded to 2 decimals)
                try:
                    rate_val = float((norm.get("rate_to_eur", "") or "0").strip())
                except Exception:
                    rate_val = None
                conv_val_str = (norm.get("converted_amount_eur", "") or "").strip()
                conv_val = _to_decimal(conv_val_str)
                if rate_val is None or abs(rate_val - 1.0) > 1e-9:
                    eur_handling_ok = False
                if amt is None or conv_val is None:
                    eur_handling_ok = False
                else:
                    expected_conv = round(amt + 0.0, 2)
                    if abs(conv_val - expected_conv) > 0.005:
                        eur_handling_ok = False
                processed_count_calc += 1
                month_key = tdate_str[:7] if tdate_str and len(tdate_str) >= 7 else ""
                if month_key:
                    prev_sum, prev_cnt = summary_expected.get(month_key, (0.0, 0))
                    summary_expected[month_key] = (prev_sum + (conv_val if conv_val is not None else 0.0), prev_cnt + 1)
            else:
                # Non-EUR: must have rate
                if tdate is None or amt is None:
                    fx_conversion_ok = False
                    continue
                # Find applicable rate date
                rate_date = _find_rate_date(tdate, available_dates_sorted)
                if rate_date is None:
                    excluded_count_calc += 1
                    fx_conversion_ok = False
                    continue
                # Get rate for currency
                rate_for_date = rates_map.get(rate_date, {})
                rate = rate_for_date.get(currency)
                if rate is None:
                    # Try earlier dates until find a rate for that currency
                    idx = available_dates_sorted.index(rate_date)
                    found_rate = None
                    while idx >= 0:
                        d_ = available_dates_sorted[idx]
                        rmap = rates_map.get(d_, {})
                        if currency in rmap:
                            found_rate = (d_, rmap[currency])
                            break
                        idx -= 1
                    if found_rate is None:
                        excluded_count_calc += 1
                        fx_conversion_ok = False
                        continue
                    else:
                        rate_date, rate = found_rate
                # Now compare normalized values
                try:
                    norm_rate = float((norm.get("rate_to_eur", "") or "0").strip())
                except Exception:
                    norm_rate = None
                norm_rate_date_str = (norm.get("rate_date_used", "") or "").strip()
                expected_eur = round(amt / rate, 2)
                norm_conv = _to_decimal((norm.get("converted_amount_eur", "") or "").strip())
                if norm_rate is None or abs(norm_rate - rate) > 1e-6:
                    fx_conversion_ok = False
                if norm_rate_date_str != rate_date.strftime("%Y-%m-%d"):
                    fx_conversion_ok = False
                if norm_conv is None or abs(norm_conv - expected_eur) > 0.005:
                    fx_conversion_ok = False
                processed_count_calc += 1
                month_key = tdate.strftime("%Y-%m")
                prev_sum, prev_cnt = summary_expected.get(month_key, (0.0, 0))
                summary_expected[month_key] = (prev_sum + expected_eur, prev_cnt + 1)

        # Set eur handling score
        if eur_handling_ok:
            scores["normalized_eur_handling"] = 1.0
        # FX conversion accuracy
        if fx_conversion_ok:
            scores["normalized_fx_conversion_accuracy"] = 1.0
        # fx_source/note
        if fx_source_note_ok:
            scores["normalized_fx_source_and_note_fields"] = 1.0

        # Monthly summary correctness
        ms_headers, ms_rows = _read_csv_dicts(monthly_summary_csv_path)
        if (ms_headers is not None and ms_rows is not None and
                ms_headers == ["month", "total_converted_eur", "transactions_count"] and monthly_summary_ok):
            provided_summary: Dict[str, Tuple[float, int]] = {}
            ok = True
            for r in ms_rows:
                m = (r.get("month", "") or "").strip()
                tot = _to_decimal((r.get("total_converted_eur", "") or "").strip())
                cnt_str = (r.get("transactions_count", "") or "").strip()
                try:
                    cnt = int(cnt_str)
                except Exception:
                    cnt = None
                if m == "" or tot is None or cnt is None:
                    ok = False
                    break
                provided_summary[m] = (round(tot, 2), cnt)
            if set(provided_summary.keys()) != set(summary_expected.keys()):
                ok = False
            else:
                for m, (exp_sum, exp_cnt) in summary_expected.items():
                    prov = provided_summary.get(m)
                    if prov is None:
                        ok = False
                        break
                    prov_sum, prov_cnt = prov
                    if prov_cnt != exp_cnt:
                        ok = False
                        break
                    if abs(prov_sum - round(exp_sum, 2)) > 0.01:
                        ok = False
                        break
            if ok:
                scores["monthly_summary_correctness"] = 1.0

    # Logs: archive_list.txt
    archive_text = _read_text_safe(archive_list_log)
    if archive_text is not None:
        has_csv_name = "eurofxref-hist.csv" in archive_text.lower()
        presence_note = bool(re.search(r"\bpresent\b", archive_text, flags=re.IGNORECASE)) or bool(
            re.search(r"\bnot\s+present\b", archive_text, flags=re.IGNORECASE))
        indicates_expected_present = bool(re.search(r"(expected).*(csv).*(present)", archive_text, flags=re.IGNORECASE)) or bool(
            re.search(r"(csv).*(present)", archive_text, flags=re.IGNORECASE))
        if has_csv_name and presence_note and indicates_expected_present:
            scores["logs_archive_list_quality"] = 1.0

    # Logs: rate_sample.txt
    rate_sample_text = _read_text_safe(rate_sample_log)
    if rate_sample_text is not None and rates_csv_path.exists():
        has_date_header = "date" in rate_sample_text.lower()
        has_usd_or_gbp = ("usd" in rate_sample_text.lower()) or ("gbp" in rate_sample_text.lower())
        actual_header = None
        try:
            with rates_csv_path.open("r", encoding="utf-8") as f:
                actual_header = f.readline().strip()
        except Exception:
            actual_header = None
        matches_header = actual_header is not None and actual_header.strip() in rate_sample_text
        if has_date_header and has_usd_or_gbp and (matches_header or True):
            scores["logs_rate_sample_quality"] = 1.0

    # Logs: row_counts.txt
    row_counts_text = _read_text_safe(row_counts_log)
    if row_counts_text is not None:
        has_input_path = "input/expenses.csv" in row_counts_text
        has_norm_path = "outputs/normalized_expenses.csv" in row_counts_text
        nums = [int(n) for n in re.findall(r"\b\d+\b", row_counts_text)]
        input_lines = _count_file_lines(expenses_csv)
        norm_lines = _count_file_lines(normalized_csv_path)
        counts_match_logged = False
        if input_lines is not None and norm_lines is not None:
            if input_lines in nums and norm_lines in nums:
                counts_match_logged = True
        interpretation_ok = bool(re.search(r"(match|aligned|equal|mismatch|do\s+not\s+match)", row_counts_text, flags=re.IGNORECASE))
        mentions_header_or_excluded = bool(re.search(r"(header|exclude|excluded)", row_counts_text, flags=re.IGNORECASE))
        if has_input_path and has_norm_path and counts_match_logged and interpretation_ok and mentions_header_or_excluded:
            scores["logs_row_counts_quality"] = 1.0

    # Audit report content
    audit_text = _read_text_safe(audit_report_md)
    if audit_text is not None:
        audit_score = 0.0
        parts = 0
        # 1) Exact ECB resource used (name and dataset identifier "EXR")
        parts += 1
        if ("European Central Bank" in audit_text) or ("ECB" in audit_text):
            if ("Euro foreign exchange reference rates" in audit_text) and ("EXR" in audit_text):
                audit_score += 1.0
        # 2) Where files were saved (paths)
        parts += 1
        if ("downloads/ecb_eurofxref_hist.zip" in audit_text) and ("downloads/eurofxref-hist.csv" in audit_text):
            audit_score += 1.0
        # 3) How date fallback was applied (most recent preceding business day)
        parts += 1
        if re.search(r"(preceding|previous).*(business\s+day)", audit_text, flags=re.IGNORECASE):
            audit_score += 1.0
        # 4) Any currencies that could not be matched (mention of unmatched/unknown currencies)
        parts += 1
        if re.search(r"(unmatched|unknown|not\s+matched|could\s+not\s+be\s+matched|not\s+present)", audit_text, flags=re.IGNORECASE):
            audit_score += 1.0
        # 5) Total count processed vs excluded and phrasing
        parts += 1
        if ("processed" in audit_text.lower()) and ("excluded" in audit_text.lower()):
            audit_score += 1.0
        # 6) SHA-256 checksum of downloads/eurofxref-hist.csv present and matches
        parts += 1
        expected_sha = _sha256_file(rates_csv_path)
        sha_ok = False
        if expected_sha:
            if expected_sha.lower() in audit_text.lower():
                sha_ok = True
        if sha_ok:
            audit_score += 1.0
        # 7) References to relevant logs
        parts += 1
        if ("logs/archive_list.txt" in audit_text) and ("logs/row_counts.txt" in audit_text) and ("logs/rate_sample.txt" in audit_text):
            audit_score += 1.0
        if parts > 0:
            scores["audit_report_content"] = audit_score / parts

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()