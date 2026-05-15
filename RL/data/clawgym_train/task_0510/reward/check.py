import json
import csv
import re
import math
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = []
            for row in reader:
                # Normalize by stripping whitespace from keys and values
                norm_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm_row)
            return headers, rows
    except Exception:
        return None, None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_events_md(path: Path) -> Optional[Dict[int, List[str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    events: Dict[int, List[str]] = {}
    # Pattern: "- 1910: Title"
    pattern = re.compile(r'^\s*-\s*(\d{4})\s*:\s*(.+?)\s*$', re.MULTILINE)
    for m in pattern.finditer(text):
        year = int(m.group(1))
        title = m.group(2).strip()
        events.setdefault(year, []).append(title)
    return events


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _pearson_correlation(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _compute_expected(workspace: Path) -> Optional[dict]:
    # Load inputs
    exports_path = workspace / "input" / "rice_exports_korea_1910_1920.csv"
    prices_path = workspace / "input" / "rice_price_index_1910_1920.csv"
    events_path = workspace / "input" / "events.md"

    exp_headers, exp_rows = _safe_read_csv_dicts(exports_path)
    pri_headers, pri_rows = _safe_read_csv_dicts(prices_path)
    events = _parse_events_md(events_path)

    if exp_headers is None or exp_rows is None or pri_headers is None or pri_rows is None or events is None:
        return None

    # Build year -> value maps
    exports_map: Dict[int, int] = {}
    price_map: Dict[int, float] = {}
    for r in exp_rows:
        y = _to_int(r.get("Year", ""))
        v = _to_int(r.get("Exports_tons", ""))
        if y is None or v is None:
            return None
        exports_map[y] = v
    for r in pri_rows:
        y = _to_int(r.get("Year", ""))
        v = _to_float(r.get("PriceIndex_1910_100", ""))
        if y is None or v is None:
            return None
        price_map[y] = v

    years_exports = set(exports_map.keys())
    years_price = set(price_map.keys())
    years_intersection = sorted(years_exports & years_price)
    years_only_exports = sorted(years_exports - years_price)
    years_only_price = sorted(years_price - years_exports)

    # Compute YoY using previous year in the analyzed series (intersection, chronological)
    yoy_exports: Dict[int, Optional[float]] = {}
    yoy_price: Dict[int, Optional[float]] = {}
    prev_year: Optional[int] = None
    for y in years_intersection:
        if prev_year is None:
            yoy_exports[y] = None
            yoy_price[y] = None
        else:
            prev_e = exports_map.get(prev_year)
            prev_p = price_map.get(prev_year)
            cur_e = exports_map.get(y)
            cur_p = price_map.get(y)
            if prev_e is None or prev_e == 0 or prev_p is None or prev_p == 0:
                return None
            yoy_exports[y] = ((cur_e - prev_e) / prev_e) * 100.0
            yoy_price[y] = ((cur_p - prev_p) / prev_p) * 100.0
        prev_year = y

    # BothUp10pct: both YoY >= 10.0
    both_up_years = []
    both_up_flags: Dict[int, bool] = {}
    for y in years_intersection:
        ye = yoy_exports[y]
        yp = yoy_price[y]
        flag = False
        if ye is not None and yp is not None and ye >= 10.0 and yp >= 10.0:
            flag = True
            both_up_years.append(y)
        both_up_flags[y] = flag

    # EventsWithin1Y sets
    events_within: Dict[int, List[str]] = {}
    for y in years_intersection:
        items = []
        for ey, titles in events.items():
            if abs(ey - y) <= 1:
                for t in titles:
                    items.append(f"{ey}: {t}")
        events_within[y] = sorted(items)

    # Correlation
    xs = [float(exports_map[y]) for y in years_intersection]
    ys = [float(price_map[y]) for y in years_intersection]
    corr = _pearson_correlation(xs, ys)
    if corr is None:
        return None

    return {
        "exports_map": exports_map,
        "price_map": price_map,
        "years_intersection": years_intersection,
        "years_only_exports": years_only_exports,
        "years_only_price": years_only_price,
        "yoy_exports": yoy_exports,
        "yoy_price": yoy_price,
        "both_up_flags": both_up_flags,
        "both_up_years": both_up_years,
        "events_within": events_within,
        "correlation": corr,
    }


def _parse_metrics_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _safe_read_csv_dicts(path)


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    st = s.strip().lower()
    if st in ("true", "t", "yes", "y"):
        return True
    if st in ("false", "f", "no", "n"):
        return False
    return None


def _split_events_list(s: str) -> List[str]:
    if not s:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def _floats_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _email_contains_correlation(email: str, corr: float) -> bool:
    # Accept either: a float in [-1,1] within 0.05 of corr; or mention 'correlation' with correct sign
    # Look for numbers in text that are in [-1,1]
    num_pattern = re.compile(r'[-+]?\d+(?:\.\d+)?')
    numbers = []
    for m in num_pattern.finditer(email):
        try:
            val = float(m.group(0))
            numbers.append(val)
        except Exception:
            continue
    for val in numbers:
        if -1.0 <= val <= 1.0 and abs(val - corr) <= 0.05:
            return True
    # Check sign language
    if "correlation" in email.lower():
        if corr >= 0 and ("positive" in email.lower() or "positively" in email.lower()):
            return True
        if corr < 0 and ("negative" in email.lower() or "negatively" in email.lower()):
            return True
    return False


def _email_mentions_bothup_years_and_events(email: str, both_up_years: List[int], events_within: Dict[int, List[str]]) -> bool:
    low = email.lower()
    for y in both_up_years:
        # year should appear
        if str(y) not in email:
            return False
        # at least one nearby event title should appear
        titles = []
        for item in events_within.get(y, []):
            # item format "YYYY: title"
            if ": " in item:
                titles.append(item.split(": ", 1)[1])
        if not titles:
            # if no nearby events exist, do not enforce; but in this dataset, there are
            continue
        any_title_present = any(t.lower() in low for t in titles)
        if not any_title_present:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_headers_correct": 0.0,
        "metrics_years_coverage_and_order": 0.0,
        "metrics_exports_and_price_values_correct": 0.0,
        "yoy_calculations_correct": 0.0,
        "bothup_flag_correct": 0.0,
        "eventswithin1y_correct": 0.0,
        "summary_years_and_counts_correct": 0.0,
        "correlation_value_correct": 0.0,
        "mismatched_years_correct": 0.0,
        "both_up_10pct_years_correct": 0.0,
        "cross_count_consistency": 0.0,
        "email_addresses_prof_kim_and_paths": 0.0,
        "email_correlation_summary_present": 0.0,
        "email_mentions_bothup_years_and_events": 0.0,
    }

    expected = _compute_expected(workspace)
    # If expected cannot be computed due to missing/malformed inputs, fail all related checks gracefully.
    if expected is None:
        return scores

    metrics_path = workspace / "output" / "metrics.csv"
    summary_path = workspace / "output" / "summary.json"
    email_path = workspace / "output" / "email_draft.txt"

    # Metrics CSV checks
    m_headers, m_rows = _parse_metrics_csv(metrics_path)
    if m_headers is not None and m_rows is not None:
        # Check headers exactly
        expected_headers = [
            "Year",
            "Exports_tons",
            "PriceIndex_1910_100",
            "YoY_Exports_pct",
            "YoY_PriceIndex_pct",
            "BothUp10pct",
            "EventsWithin1Y",
        ]
        if m_headers == expected_headers:
            scores["metrics_headers_correct"] = 1.0

        # Check years coverage and order
        try:
            m_years = [int(r.get("Year", "").strip()) for r in m_rows]
            if m_years == expected["years_intersection"]:
                scores["metrics_years_coverage_and_order"] = 1.0
        except Exception:
            pass

        # Check exports and price values
        ep_ok = True
        for r in m_rows:
            y = _to_int(r.get("Year", ""))
            exp_v = _to_int(r.get("Exports_tons", ""))
            pri_v = _to_float(r.get("PriceIndex_1910_100", ""))
            if y is None or exp_v is None or pri_v is None:
                ep_ok = False
                break
            if expected["exports_map"].get(y) != exp_v:
                ep_ok = False
                break
            if not _floats_close(float(expected["price_map"].get(y)), float(pri_v), tol=1e-6):
                ep_ok = False
                break
        if ep_ok and len(m_rows) == len(expected["years_intersection"]):
            scores["metrics_exports_and_price_values_correct"] = 1.0

        # Check YoY calculations
        yoy_ok = True
        for idx, r in enumerate(m_rows):
            y = _to_int(r.get("Year", ""))
            yoy_e_str = r.get("YoY_Exports_pct", "")
            yoy_p_str = r.get("YoY_PriceIndex_pct", "")
            if y is None:
                yoy_ok = False
                break
            expected_yoy_e = expected["yoy_exports"].get(y)
            expected_yoy_p = expected["yoy_price"].get(y)
            # First chronological year must be blank
            if idx == 0:
                if (yoy_e_str is not None and yoy_e_str != "") or (yoy_p_str is not None and yoy_p_str != ""):
                    yoy_ok = False
                    break
            else:
                # Should be numeric and close
                yoy_e_val = _to_float(yoy_e_str) if yoy_e_str != "" else None
                yoy_p_val = _to_float(yoy_p_str) if yoy_p_str != "" else None
                if yoy_e_val is None or yoy_p_val is None:
                    yoy_ok = False
                    break
                # Allow small tolerance to account for rounding
                if expected_yoy_e is None or expected_yoy_p is None:
                    yoy_ok = False
                    break
                if not _floats_close(yoy_e_val, expected_yoy_e, tol=0.05):
                    yoy_ok = False
                    break
                if not _floats_close(yoy_p_val, expected_yoy_p, tol=0.05):
                    yoy_ok = False
                    break
        if yoy_ok and len(m_rows) == len(expected["years_intersection"]):
            scores["yoy_calculations_correct"] = 1.0

        # Check BothUp10pct flags
        both_ok = True
        for r in m_rows:
            y = _to_int(r.get("Year", ""))
            b_str = r.get("BothUp10pct", "")
            if y is None or b_str is None:
                both_ok = False
                break
            b_val = _parse_bool_str(b_str)
            if b_val is None:
                both_ok = False
                break
            if bool(expected["both_up_flags"].get(y)) != b_val:
                both_ok = False
                break
        if both_ok and len(m_rows) == len(expected["years_intersection"]):
            scores["bothup_flag_correct"] = 1.0

        # Check EventsWithin1Y contents (as unordered sets)
        events_ok = True
        for r in m_rows:
            y = _to_int(r.get("Year", ""))
            e_field = r.get("EventsWithin1Y", "")
            if y is None or e_field is None:
                events_ok = False
                break
            got_set = set(_split_events_list(e_field))
            exp_set = set(expected["events_within"].get(y, []))
            if got_set != exp_set:
                events_ok = False
                break
        if events_ok and len(m_rows) == len(expected["years_intersection"]):
            scores["eventswithin1y_correct"] = 1.0

    # Summary JSON checks
    summary = _safe_load_json(summary_path)
    if isinstance(summary, dict):
        years_analyzed = summary.get("years_analyzed")
        corr_val = summary.get("pearson_correlation_exports_vs_price_index")
        mismatched = summary.get("mismatched_years")
        both_up_list = summary.get("both_up_10pct_years")

        years_ok = isinstance(years_analyzed, list) and [int(y) for y in years_analyzed] == expected["years_intersection"]
        if years_ok:
            scores["summary_years_and_counts_correct"] = 1.0

        corr_ok = isinstance(corr_val, (int, float)) and _floats_close(float(corr_val), float(expected["correlation"]), tol=1e-6)
        if corr_ok:
            scores["correlation_value_correct"] = 1.0

        mm_ok = False
        if isinstance(mismatched, dict):
            exp_only = mismatched.get("exports_only")
            pri_only = mismatched.get("price_index_only")
            try:
                exp_only_list = [int(x) for x in (exp_only or [])]
                pri_only_list = [int(x) for x in (pri_only or [])]
                mm_ok = (exp_only_list == expected["years_only_exports"] and pri_only_list == expected["years_only_price"])
            except Exception:
                mm_ok = False
        if mm_ok:
            scores["mismatched_years_correct"] = 1.0

        both_up_ok = False
        if isinstance(both_up_list, list):
            try:
                both_up_ok = [int(y) for y in both_up_list] == expected["both_up_years"]
            except Exception:
                both_up_ok = False
        if both_up_ok:
            scores["both_up_10pct_years_correct"] = 1.0

    # Cross-file consistency: rows in metrics == length of years_analyzed
    consistent = False
    if m_rows is not None and summary is not None and isinstance(summary, dict):
        ya = summary.get("years_analyzed")
        if isinstance(ya, list):
            try:
                consistent = len(m_rows) == len(ya)
            except Exception:
                consistent = False
    if consistent:
        scores["cross_count_consistency"] = 1.0

    # Email checks
    try:
        email_text = email_path.read_text(encoding="utf-8")
    except Exception:
        email_text = None

    if isinstance(email_text, str):
        # Addressed to Prof. Kim and paths included
        has_prof = "prof. kim" in email_text.lower()
        has_metrics_path = "output/metrics.csv" in email_text
        has_summary_path = "output/summary.json" in email_text
        if has_prof and has_metrics_path and has_summary_path:
            scores["email_addresses_prof_kim_and_paths"] = 1.0

        # Correlation summary present
        if _email_contains_correlation(email_text, expected["correlation"]):
            scores["email_correlation_summary_present"] = 1.0

        # Mentions both-up years and nearby events
        if _email_mentions_bothup_years_and_events(email_text, expected["both_up_years"], expected["events_within"]):
            scores["email_mentions_bothup_years_and_events"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()