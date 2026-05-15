import sys
import json
import re
import csv
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Tuple, Optional


ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open("r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        if not lines:
            return None, None
        reader = csv.DictReader(lines)
        headers = reader.fieldnames
        if headers is None:
            return None, None
        rows = [dict(row) for row in reader]
        return headers, rows
    except Exception:
        return None, None


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _is_valid_zip(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_file():
            return False
        return zipfile.is_zipfile(str(path))
    except Exception:
        return False


def _load_rates(path: Path) -> Tuple[bool, Dict[date, Dict[str, float]]]:
    headers, rows = _read_csv_dicts(path)
    if headers is None or rows is None:
        return False, {}
    required_cols = {"date", "USD_per_EUR", "GBP_per_EUR", "JPY_per_EUR"}
    if not required_cols.issubset(set(headers)):
        return False, {}
    rate_map: Dict[date, Dict[str, float]] = {}
    for r in rows:
        d_str = r.get("date", "")
        d_parsed = _parse_iso_date(d_str)
        if d_parsed is None:
            return False, {}
        usd = _parse_float(r.get("USD_per_EUR"))
        gbp = _parse_float(r.get("GBP_per_EUR"))
        jpy = _parse_float(r.get("JPY_per_EUR"))
        if usd is None or gbp is None or jpy is None:
            return False, {}
        rate_map[d_parsed] = {"USD_per_EUR": usd, "GBP_per_EUR": gbp, "JPY_per_EUR": jpy}
    if not rate_map:
        return False, {}
    return True, rate_map


def _find_effective_rate_date(tx_date: date, available_dates: List[date]) -> Optional[date]:
    # Find the most recent available date on or before tx_date
    candidates = [d for d in available_dates if d <= tx_date]
    if not candidates:
        return None
    return max(candidates)


def _build_spend_key(row: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    # date, campaign, channel, market, currency, amount_local (as string exact)
    return (
        row.get("date", "").strip(),
        row.get("campaign", "").strip(),
        row.get("channel", "").strip(),
        row.get("market", "").strip(),
        row.get("currency", "").strip(),
        row.get("amount_local", "").strip(),
    )


def _load_spend_input(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    headers, rows = _read_csv_dicts(path)
    if headers is None or rows is None:
        return False, []
    required = {"date", "campaign", "channel", "market", "currency", "amount_local"}
    if not required.issubset(set(headers)):
        return False, []
    # Validate dates and amounts are parseable
    for r in rows:
        if _parse_iso_date(r.get("date", "")) is None:
            return False, []
        if _parse_float(r.get("amount_local")) is None:
            return False, []
    return True, rows


def _load_converted_spend(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    headers, rows = _read_csv_dicts(path)
    if headers is None or rows is None:
        return False, []
    required = {
        "date",
        "campaign",
        "channel",
        "market",
        "currency",
        "amount_local",
        "fx_rate_date_used",
        "currency_per_EUR_used",
        "USD_per_EUR_used",
        "amount_usd",
    }
    if not required.issubset(set(headers)):
        return False, []
    # Validate parseability of key fields
    for r in rows:
        if _parse_iso_date(r.get("date", "")) is None:
            return False, []
        if _parse_iso_date(r.get("fx_rate_date_used", "")) is None:
            return False, []
        if _parse_float(r.get("amount_local")) is None:
            return False, []
        if _parse_float(r.get("USD_per_EUR_used")) is None:
            return False, []
        # currency_per_EUR_used may be blank for EUR rows; allow blank or numeric
        cval = r.get("currency_per_EUR_used")
        if (cval is not None) and (cval.strip() != ""):
            if _parse_float(cval) is None:
                return False, []
        if _parse_float(r.get("amount_usd")) is None:
            return False, []
    return True, rows


def _load_aggregated(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    headers, rows = _read_csv_dicts(path)
    if headers is None or rows is None:
        return False, []
    required = {"year_month", "channel", "total_usd"}
    if not required.issubset(set(headers)):
        return False, []
    # Validate year_month format and total_usd parseability
    for r in rows:
        ym = r.get("year_month", "")
        if not re.match(r"^\d{4}-\d{2}$", ym or ""):
            return False, []
        if _parse_float(r.get("total_usd")) is None:
            return False, []
    return True, rows


def _compute_expected_amount_usd(amount_local: float, currency: str, usd_per_eur: float, curr_per_eur: Optional[float]) -> Optional[float]:
    try:
        if currency == "EUR":
            return amount_local * usd_per_eur
        elif currency in ("GBP", "JPY"):
            if curr_per_eur is None or curr_per_eur == 0:
                return None
            eur_amount = amount_local / curr_per_eur
            return eur_amount * usd_per_eur
        else:
            # Unsupported currency based on task
            return None
    except Exception:
        return None


def _round2(x: float) -> float:
    return round(x + 1e-12, 2)


def _normalize_money_str(s: str) -> str:
    # Remove commas to allow comparison with/without thousands separators
    return s.replace(",", "").strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ecb_zip_valid": 0.0,
        "ecb_rates_csv_structure_valid": 0.0,
        "conversion_file_structure_valid": 0.0,
        "conversion_rows_covered": 0.0,
        "fx_rate_date_selection_correct": 0.0,
        "fx_rates_used_values_correct": 0.0,
        "amount_usd_calculation_correct": 0.0,
        "monthly_aggregation_structure_valid": 0.0,
        "monthly_aggregation_values_correct": 0.0,
        "memo_sections_order_and_presence": 0.0,
        "memo_data_source_citation_valid": 0.0,
        "memo_key_results_list_matches_aggregates": 0.0,
    }

    # Paths
    ecb_zip_path = workspace / "output" / "external" / "ecb_eurofxref_hist.zip"
    ecb_rates_csv_path = workspace / "output" / "external" / "ecb_rates_extracted.csv"
    converted_csv_path = workspace / "output" / "data" / "spend_converted_usd.csv"
    aggregated_csv_path = workspace / "output" / "data" / "spend_by_channel_month_usd.csv"
    memo_path = workspace / "output" / "memo" / "normalized_spend_memo.md"
    input_spend_path = workspace / "input" / "spend_by_campaign.csv"

    # Check zip validity
    if _is_valid_zip(ecb_zip_path):
        scores["ecb_zip_valid"] = 1.0

    # Load rates
    rates_ok, rates_map = _load_rates(ecb_rates_csv_path)
    if rates_ok:
        scores["ecb_rates_csv_structure_valid"] = 1.0

    # Load input spend
    spend_ok, spend_rows = _load_spend_input(input_spend_path)

    # Load converted
    conv_ok, conv_rows = _load_converted_spend(converted_csv_path)
    if conv_ok:
        scores["conversion_file_structure_valid"] = 1.0

    # Map spend rows by key
    if spend_ok and conv_ok and rates_ok:
        # Coverage check
        spend_keys = [_build_spend_key(r) for r in spend_rows]
        conv_keys = [_build_spend_key(r) for r in conv_rows]
        spend_set = set(spend_keys)
        conv_set = set(conv_keys)
        if len(spend_set) == 0:
            coverage = 0.0
        else:
            coverage = len(spend_set.intersection(conv_set)) / float(len(spend_set))
        # Require exact coverage of all rows
        scores["conversion_rows_covered"] = 1.0 if (coverage == 1.0 and len(spend_set) == len(conv_set)) else coverage

        # Build conv lookup
        conv_lookup: Dict[Tuple[str, str, str, str, str, str], Dict[str, str]] = {}
        for r in conv_rows:
            conv_lookup[_build_spend_key(r)] = r

        # FX date selection, rates used, amount_usd calculation
        available_rate_dates = sorted(rates_map.keys())
        if not available_rate_dates:
            scores["fx_rate_date_selection_correct"] = 0.0
            scores["fx_rates_used_values_correct"] = 0.0
            scores["amount_usd_calculation_correct"] = 0.0
        else:
            total_rows = 0
            fx_date_correct = 0
            fx_values_correct = 0
            amt_correct = 0
            for srow in spend_rows:
                key = _build_spend_key(srow)
                crow = conv_lookup.get(key)
                if crow is None:
                    continue
                total_rows += 1
                tx_date = _parse_iso_date(srow["date"])
                fx_date_used = _parse_iso_date(crow.get("fx_rate_date_used", ""))
                effective = _find_effective_rate_date(tx_date, available_rate_dates) if tx_date else None
                if fx_date_used is not None and effective is not None and fx_date_used == effective:
                    fx_date_correct += 1
                # Check rates used values match the effective date
                if effective in rates_map:
                    usd_rate_expected = rates_map[effective]["USD_per_EUR"]
                    usd_used = _parse_float(crow.get("USD_per_EUR_used"))
                    # For currency_per_EUR_used:
                    curr = srow.get("currency", "").strip()
                    curr_used_val = crow.get("currency_per_EUR_used")
                    curr_used = _parse_float(curr_used_val) if (curr_used_val is not None and curr_used_val.strip() != "") else None
                    if curr == "EUR":
                        currency_match = True  # accept any (blank or ~1)
                        if curr_used is not None:
                            currency_match = abs(curr_used - 1.0) < 1e-6 or curr_used == 1.0
                    elif curr in ("GBP", "JPY"):
                        expected_key = f"{curr}_per_EUR"
                        curr_expected = rates_map[effective].get(expected_key)
                        currency_match = (curr_used is not None) and (curr_expected is not None) and (abs(curr_used - curr_expected) < 1e-6)
                    else:
                        currency_match = False
                    usd_match = (usd_used is not None) and (abs(usd_used - usd_rate_expected) < 1e-6)
                    if currency_match and usd_match:
                        fx_values_correct += 1
                    # Check amount_usd calculation
                    amt_loc = _parse_float(srow.get("amount_local"))
                    expected_curr_rate = None
                    if curr in ("GBP", "JPY"):
                        expected_curr_rate = rates_map[effective].get(f"{curr}_per_EUR")
                    expected_usd = None
                    if amt_loc is not None:
                        expected_usd = _compute_expected_amount_usd(amt_loc, curr, usd_rate_expected, expected_curr_rate)
                    amt_usd_used = _parse_float(crow.get("amount_usd"))
                    if expected_usd is not None and amt_usd_used is not None:
                        if abs(expected_usd - amt_usd_used) <= 0.01:
                            amt_correct += 1
            denom = float(total_rows) if total_rows > 0 else 0.0
            scores["fx_rate_date_selection_correct"] = (fx_date_correct / denom) if denom > 0 else 0.0
            scores["fx_rates_used_values_correct"] = (fx_values_correct / denom) if denom > 0 else 0.0
            scores["amount_usd_calculation_correct"] = (amt_correct / denom) if denom > 0 else 0.0

    # Aggregation checks
    agg_ok, agg_rows = _load_aggregated(aggregated_csv_path)
    if agg_ok:
        scores["monthly_aggregation_structure_valid"] = 1.0

    if conv_ok and agg_ok:
        # Compute expected aggregation from converted file
        expected: Dict[Tuple[str, str], float] = {}
        for r in conv_rows:
            d = _parse_iso_date(r.get("date", ""))
            ch = r.get("channel", "").strip()
            amt = _parse_float(r.get("amount_usd"))
            if d is None or ch == "" or amt is None:
                expected = {}
                break
            ym = f"{d.year:04d}-{d.month:02d}"
            key = (ym, ch)
            expected[key] = expected.get(key, 0.0) + amt
        if not expected:
            scores["monthly_aggregation_values_correct"] = 0.0
        else:
            # Round to 2 decimals
            expected_rounded = {k: _round2(v) for k, v in expected.items()}
            # Load actual
            actual: Dict[Tuple[str, str], float] = {}
            for r in agg_rows:
                ym = r.get("year_month", "").strip()
                ch = r.get("channel", "").strip()
                tot = _parse_float(r.get("total_usd"))
                if ym == "" or ch == "" or tot is None:
                    actual = {}
                    break
                actual[(ym, ch)] = tot
            if not actual:
                scores["monthly_aggregation_values_correct"] = 0.0
            else:
                # Compare sets and values
                if set(expected_rounded.keys()) != set(actual.keys()):
                    scores["monthly_aggregation_values_correct"] = 0.0
                else:
                    total = len(expected_rounded)
                    correct = 0
                    for k, v in expected_rounded.items():
                        if abs(actual.get(k, 0.0) - v) < 1e-6:
                            correct += 1
                    scores["monthly_aggregation_values_correct"] = (correct / total) if total > 0 else 0.0

    # Memo checks
    memo_text = ""
    if memo_path.exists():
        try:
            memo_text = memo_path.read_text(encoding="utf-8")
        except Exception:
            memo_text = ""

    if memo_text:
        # Sections order and presence: ensure placeholder removed and three subsections order
        placeholder_present = "[INSERT_ANALYSIS_HERE]" in memo_text
        data_src_idx = memo_text.lower().find("data source")
        method_idx = memo_text.lower().find("method")
        key_results_idx = memo_text.lower().find("key results")
        if (not placeholder_present) and (data_src_idx != -1) and (method_idx != -1) and (key_results_idx != -1) and (data_src_idx < method_idx < key_results_idx):
            scores["memo_sections_order_and_presence"] = 1.0

        # Data source citation validity: official name, path, and ISO date present in/near data source section
        data_source_block = memo_text
        if data_src_idx != -1:
            # Take content from "Data source" to "Method"
            end_idx = method_idx if method_idx != -1 else len(memo_text)
            data_source_block = memo_text[data_src_idx:end_idx]
        official_name = "European Central Bank — Euro foreign exchange reference rates: historical data"
        path_str = "output/external/ecb_eurofxref_hist.zip"
        has_name = official_name in data_source_block
        has_path = path_str in data_source_block
        has_iso_date = ISO_DATE_RE.search(data_source_block) is not None
        if has_name and has_path and has_iso_date:
            scores["memo_data_source_citation_valid"] = 1.0

        # Key results match aggregates
        agg_ok2, agg_rows2 = _load_aggregated(aggregated_csv_path)
        if agg_ok2:
            # Build expected bullet lines
            expected_lines = []
            for r in agg_rows2:
                ym = r.get("year_month", "").strip()
                ch = r.get("channel", "").strip()
                tot = _parse_float(r.get("total_usd"))
                if ym == "" or ch == "" or tot is None:
                    continue
                # Format: YYYY-MM — CHANNEL: $TOTAL_USD (USD) using rounded totals; channel text as in file
                expected_str_no_commas = f"{ym} — {ch}: ${_round2(tot):.2f} (USD)"
                expected_lines.append(expected_str_no_commas)

            # Extract lines after "Key results"
            memo_lines = memo_text.splitlines()
            kr_pos = None
            for i, line in enumerate(memo_lines):
                if "key results" in line.lower():
                    kr_pos = i
                    break
            search_lines = memo_lines[kr_pos + 1 :] if kr_pos is not None else memo_lines

            # Collect bullet lines text normalized without leading bullet markers and without commas
            bullet_texts = []
            for line in search_lines:
                stripped = line.strip()
                if stripped.startswith("- ") or stripped.startswith("* "):
                    content = stripped[2:].strip()
                    # Normalize commas for amounts
                    bullet_texts.append(_normalize_money_str(content))
            # Check coverage
            if expected_lines:
                total = len(expected_lines)
                matched = 0
                for exp in expected_lines:
                    exp_norm = _normalize_money_str(exp)
                    # Search any bullet that matches exactly
                    if any(bt == exp_norm for bt in bullet_texts):
                        matched += 1
                scores["memo_key_results_list_matches_aggregates"] = (matched / total) if total > 0 else 0.0
            else:
                scores["memo_key_results_list_matches_aggregates"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Print without sorting keys to preserve insertion order as defined in grade()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()