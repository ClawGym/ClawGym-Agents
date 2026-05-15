import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                rows.append(dict(row))
            return rows
    except Exception:
        return None


def _csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            return header
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_bool_like(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"true", "t", "yes", "y", "1"}:
        return True
    if v in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _datestr_to_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected(data_a_path: Path, data_b_path: Path) -> Optional[List[Dict[str, object]]]:
    rows_a = _load_csv_safe(data_a_path)
    rows_b = _load_csv_safe(data_b_path)
    if rows_a is None or rows_b is None:
        return None
    # Expect columns: date,temp_c
    # Build dicts by date
    def build_map(rows):
        m = {}
        for r in rows:
            d = r.get("date")
            t = r.get("temp_c")
            if d is None or t is None:
                return None
            fv = _to_float(t)
            if fv is None:
                return None
            m[d] = fv
        return m

    map_a = build_map(rows_a)
    map_b = build_map(rows_b)
    if map_a is None or map_b is None:
        return None
    common_dates = sorted(set(map_a.keys()).intersection(set(map_b.keys())))
    merged = []
    for d in common_dates:
        ta = map_a[d]
        tb = map_b[d]
        mean = (ta + tb) / 2.0
        absdiff = abs(ta - tb)
        consistent = absdiff <= 1.5
        merged.append({
            "date": d,
            "temp_a": ta,
            "temp_b": tb,
            "mean_temp_c": mean,
            "abs_diff_c": absdiff,
            "consistent": consistent,
        })
    return merged


def _round2(x: float) -> float:
    # Round to 2 decimals in a deterministic manner
    return float(f"{x:.2f}")


def _compute_metrics_from_expected(expected_rows: List[Dict[str, object]]) -> Dict[str, object]:
    # n_common_days: count of merged rows
    n_common = len(expected_rows)
    # consistent mask
    consistent_rows = [r for r in expected_rows if bool(r.get("consistent"))]
    n_mismatch = sum(1 for r in expected_rows if not bool(r.get("consistent")))
    # mean_temp_c_consistent: average of mean_temp_c over consistent
    if len(consistent_rows) > 0:
        mean_consistent = sum(float(r["mean_temp_c"]) for r in consistent_rows) / float(len(consistent_rows))
    else:
        mean_consistent = float("nan")
    # trend on consistent rows: y = a + b t, t days since earliest consistent date
    if len(consistent_rows) > 0:
        dates = [r["date"] for r in consistent_rows]
        # convert to datetime
        dtobjs = [_datestr_to_date(d) for d in dates]
        # Handle parse issues by treating invalid dates as None
        if any(d is None for d in dtobjs):
            slope_per_day = 0.0
        else:
            t0 = min(dtobjs)
            tvals = [(d - t0).days for d in dtobjs]
            yvals = [float(r["mean_temp_c"]) for r in consistent_rows]
            # least squares b = cov(t,y)/var(t)
            n = len(tvals)
            if n == 1:
                slope_per_day = 0.0
            else:
                mean_t = sum(tvals) / n
                mean_y = sum(yvals) / n
                num = sum((t - mean_t) * (y - mean_y) for t, y in zip(tvals, yvals))
                den = sum((t - mean_t) ** 2 for t in tvals)
                if den == 0:
                    slope_per_day = 0.0
                else:
                    slope_per_day = num / den
        trend_per_decade = slope_per_day * 3652.5
    else:
        mean_consistent = float("nan")
        trend_per_decade = float("nan")
    metrics = {
        "n_common_days": n_common,
        "n_mismatch_days": n_mismatch,
        "mean_temp_c_consistent": _round2(mean_consistent) if mean_consistent == mean_consistent else None,
        "trend_c_per_decade_consistent": _round2(trend_per_decade) if trend_per_decade == trend_per_decade else None,
    }
    return metrics


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _extract_ints(s: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b\d+\b", s)]


def _contains_token(line: str, token: str) -> bool:
    # case-insensitive token presence
    return token.lower() in line.lower()


def _word_count(text: str) -> int:
    # Simple whitespace split
    tokens = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inventory_file_exists": 0.0,
        "inventory_lists_both_csvs": 0.0,
        "inventory_counts_correct": 0.0,
        "inventory_columns_listed": 0.0,
        "script_exists": 0.0,
        "script_is_valid_python": 0.0,
        "cleaned_merged_file_exists": 0.0,
        "cleaned_merged_header_order_correct": 0.0,
        "cleaned_merged_row_count_correct": 0.0,
        "cleaned_merged_values_match_expected": 0.0,
        "metrics_file_exists": 0.0,
        "metrics_keys_correct": 0.0,
        "metrics_values_match_expected": 0.0,
        "letter_file_exists": 0.0,
        "letter_starts_with_required_greeting": 0.0,
        "letter_word_count_acceptable": 0.0,
        "letter_includes_metric_values": 0.0,
    }

    # Paths
    data_dir = workspace / "data"
    notes_dir = workspace / "notes"
    scripts_dir = workspace / "scripts"
    output_dir = workspace / "output"

    a_csv = data_dir / "thermometer_a.csv"
    b_csv = data_dir / "thermometer_b.csv"

    file_inventory = output_dir / "file_inventory.txt"
    cleaned_merged = output_dir / "cleaned_merged.csv"
    metrics_json = output_dir / "metrics.json"
    letter_polished = output_dir / "letter_polished.txt"
    analyze_script = scripts_dir / "analyze_temps.py"

    # Precompute expected from inputs if available
    expected_rows = None
    expected_metrics = None
    if a_csv.exists() and b_csv.exists():
        expected_rows = _compute_expected(a_csv, b_csv)
        if expected_rows is not None:
            expected_metrics = _compute_metrics_from_expected(expected_rows)

    # 1) file_inventory.txt checks
    if file_inventory.exists():
        scores["inventory_file_exists"] = 1.0
        inv_text = _read_text_safe(file_inventory)
        if inv_text is not None:
            # must list each CSV under data/, its row count, and its columns.
            # Check that both thermometer_a.csv and thermometer_b.csv are mentioned
            lines = inv_text.splitlines()
            # find lines containing filenames
            line_a = None
            line_b = None
            for ln in lines:
                if "thermometer_a.csv" in ln:
                    line_a = ln
                if "thermometer_b.csv" in ln:
                    line_b = ln
            if line_a and line_b:
                scores["inventory_lists_both_csvs"] = 1.0
                # Check row counts (excluding header)
                # Determine counts from actual files if possible
                a_rows = _load_csv_safe(a_csv)
                b_rows = _load_csv_safe(b_csv)
                a_count = len(a_rows) if a_rows is not None else None
                b_count = len(b_rows) if b_rows is not None else None
                counts_ok = True
                if a_count is not None:
                    ints_a = _extract_ints(line_a)
                    counts_ok = counts_ok and (a_count in ints_a)
                if b_count is not None:
                    ints_b = _extract_ints(line_b)
                    counts_ok = counts_ok and (b_count in ints_b)
                if counts_ok and a_count is not None and b_count is not None:
                    scores["inventory_counts_correct"] = 1.0
                # Check columns mentioned
                cols_ok = True
                if line_a is not None:
                    cols_ok = cols_ok and _contains_token(line_a, "date") and _contains_token(line_a, "temp_c")
                if line_b is not None:
                    cols_ok = cols_ok and _contains_token(line_b, "date") and _contains_token(line_b, "temp_c")
                if cols_ok:
                    scores["inventory_columns_listed"] = 1.0

    # 2) script existence and validity
    if analyze_script.exists():
        scores["script_exists"] = 1.0
        # Try to load/compile as Python
        txt = _read_text_safe(analyze_script)
        if txt is not None:
            try:
                compile(txt, str(analyze_script), "exec")
                scores["script_is_valid_python"] = 1.0
            except Exception:
                pass

    # 3) cleaned_merged.csv checks
    if cleaned_merged.exists():
        scores["cleaned_merged_file_exists"] = 1.0
        header = _csv_header(cleaned_merged)
        if header is not None:
            expected_header = ["date", "temp_a", "temp_b", "mean_temp_c", "abs_diff_c", "consistent"]
            if header == expected_header:
                scores["cleaned_merged_header_order_correct"] = 1.0
        rows = _load_csv_safe(cleaned_merged)
        if rows is not None:
            # Compare to expected if available
            if expected_rows is not None:
                # Build maps by date for both
                produced_by_date = {}
                valid_rows = True
                for r in rows:
                    d = r.get("date")
                    if d is None:
                        valid_rows = False
                        break
                    ta = _to_float(r.get("temp_a", ""))
                    tb = _to_float(r.get("temp_b", ""))
                    mean = _to_float(r.get("mean_temp_c", ""))
                    absdiff = _to_float(r.get("abs_diff_c", ""))
                    cons_raw = r.get("consistent", "")
                    cons = _parse_bool_like(str(cons_raw))
                    if ta is None or tb is None or mean is None or absdiff is None or cons is None:
                        valid_rows = False
                        break
                    produced_by_date[d] = {"temp_a": ta, "temp_b": tb, "mean_temp_c": mean, "abs_diff_c": absdiff, "consistent": cons}
                if valid_rows:
                    # Check row count
                    if len(produced_by_date) == len(expected_rows):
                        scores["cleaned_merged_row_count_correct"] = 1.0
                    # Check each expected row exists with correct values
                    ok_vals = True
                    for er in expected_rows:
                        d = er["date"]
                        if d not in produced_by_date:
                            ok_vals = False
                            break
                        pr = produced_by_date[d]
                        if not _float_equal(pr["temp_a"], er["temp_a"]):
                            ok_vals = False
                            break
                        if not _float_equal(pr["temp_b"], er["temp_b"]):
                            ok_vals = False
                            break
                        if not _float_equal(pr["mean_temp_c"], er["mean_temp_c"]):
                            ok_vals = False
                            break
                        if not _float_equal(pr["abs_diff_c"], er["abs_diff_c"]):
                            ok_vals = False
                            break
                        if bool(pr["consistent"]) != bool(er["consistent"]):
                            ok_vals = False
                            break
                    if ok_vals:
                        scores["cleaned_merged_values_match_expected"] = 1.0

    # 4) metrics.json checks
    if metrics_json.exists():
        scores["metrics_file_exists"] = 1.0
        met = _load_json_safe(metrics_json)
        if isinstance(met, dict):
            required_keys = {"n_common_days", "n_mismatch_days", "mean_temp_c_consistent", "trend_c_per_decade_consistent"}
            if set(met.keys()) == required_keys:
                scores["metrics_keys_correct"] = 1.0
            # Compare values to expected if we can compute them
            if expected_metrics is not None:
                values_ok = True
                # n_common_days
                try:
                    if int(met.get("n_common_days")) != int(expected_metrics["n_common_days"]):
                        values_ok = False
                except Exception:
                    values_ok = False
                # n_mismatch_days
                try:
                    if int(met.get("n_mismatch_days")) != int(expected_metrics["n_mismatch_days"]):
                        values_ok = False
                except Exception:
                    values_ok = False
                # mean_temp_c_consistent (rounded 2 decimals)
                try:
                    m_mean = float(met.get("mean_temp_c_consistent"))
                    if _round2(m_mean) != expected_metrics["mean_temp_c_consistent"]:
                        values_ok = False
                except Exception:
                    values_ok = False
                # trend_c_per_decade_consistent (rounded 2 decimals)
                try:
                    m_trend = float(met.get("trend_c_per_decade_consistent"))
                    if _round2(m_trend) != expected_metrics["trend_c_per_decade_consistent"]:
                        values_ok = False
                except Exception:
                    values_ok = False
                if values_ok:
                    scores["metrics_values_match_expected"] = 1.0

    # 5) letter_polished.txt checks
    if letter_polished.exists():
        scores["letter_file_exists"] = 1.0
        txt = _read_text_safe(letter_polished)
        if txt is not None:
            stripped = txt.lstrip()
            if stripped.startswith("Youth Science Club of Dümbüllü,"):
                scores["letter_starts_with_required_greeting"] = 1.0
            # word count 120–180
            wc = _word_count(txt)
            if 120 <= wc <= 180:
                scores["letter_word_count_acceptable"] = 1.0
            # includes the values of mean_temp_c_consistent, trend_c_per_decade_consistent, and n_mismatch_days
            metrics = _load_json_safe(metrics_json) if metrics_json.exists() else None
            include_ok = False
            if isinstance(metrics, dict):
                try:
                    mean_val = float(metrics.get("mean_temp_c_consistent"))
                    trend_val = float(metrics.get("trend_c_per_decade_consistent"))
                    mismatch_val = int(metrics.get("n_mismatch_days"))
                    mean_str = f"{_round2(mean_val):.2f}"
                    trend_str = f"{_round2(trend_val):.2f}"
                    mismatch_str = f"{mismatch_val:d}"
                    # Check presence as tokens (word boundaries); allow sign before trend as part of token
                    has_mean = re.search(rf"\b{re.escape(mean_str)}\b", txt) is not None
                    # trend may include negative sign; ensure exact match with rounding
                    has_trend = re.search(rf"\b{re.escape(trend_str)}\b", txt) is not None
                    has_mismatch = re.search(rf"\b{re.escape(mismatch_str)}\b", txt) is not None
                    include_ok = has_mean and has_trend and has_mismatch
                except Exception:
                    include_ok = False
            if include_ok:
                scores["letter_includes_metric_values"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()