import csv
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            header = rdr.fieldnames
            if header is None:
                return None
            rows = [dict(r) for r in rdr]
            return header, rows
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _round2(val: float) -> float:
    return round(val + 1e-12, 2)


def _parse_cpi_json(path: Path) -> Optional[List[Tuple[int, int, float, str]]]:
    """
    Returns list of tuples: (year, month, value, periodName)
    Filters seriesID == CUURA421SA0 and period M01..M12
    """
    data = _safe_load_json(path)
    if not isinstance(data, dict) and not isinstance(data, list):
        return None
    series_items = []
    if isinstance(data, dict):
        if "Results" in data and isinstance(data["Results"], dict) and "series" in data["Results"]:
            series_items = data["Results"].get("series", [])
        elif "series" in data and isinstance(data.get("series"), list):
            series_items = data.get("series")
        elif isinstance(data.get("data"), list) and data.get("seriesID"):
            series_items = [data]
        else:
            series_items = []
    elif isinstance(data, list):
        series_items = data
    obs: List[Tuple[int, int, float, str]] = []
    found = False
    for s in series_items or []:
        sid = s.get("seriesID") or s.get("seriesId") or s.get("series_id")
        if sid != "CUURA421SA0":
            continue
        found = True
        for d in s.get("data", []):
            period = d.get("period")
            if not isinstance(period, str) or not period.startswith("M") or period == "M13":
                continue
            year = d.get("year")
            value = d.get("value")
            period_name = d.get("periodName") or d.get("period_name") or ""
            try:
                y = int(str(year))
                m = int(period[1:])
                v = float(str(value).replace(",", ""))
            except Exception:
                continue
            obs.append((y, m, v, str(period_name)))
    if not found:
        return None
    return obs


def _parse_cpi_csv(path: Path) -> Optional[List[Tuple[int, int, float, str]]]:
    """
    Returns list of tuples: (year, month, value, periodName)
    We only have series_id, year, period, value. periodName will be month name derived.
    Filters CUURA421SA0 and M01..M12.
    """
    parsed = _safe_read_csv(path)
    if parsed is None:
        return None
    header, rows = parsed
    norm_rows = []
    for r in rows:
        nr = {k.lower(): v for k, v in r.items()}
        norm_rows.append(nr)
    obs: List[Tuple[int, int, float, str]] = []
    found = False
    for r in norm_rows:
        sid = r.get("series_id") or r.get("seriesid")
        if sid != "CUURA421SA0":
            continue
        found = True
        period = (r.get("period") or "").strip()
        if not period.startswith("M") or period == "M13":
            continue
        try:
            year = int((r.get("year") or "").strip())
            month = int(period[1:])
            value = float((r.get("value") or "").replace(",", "").strip())
        except Exception:
            continue
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        period_name = month_names[month] if 1 <= month <= 12 else ""
        obs.append((year, month, value, period_name))
    if not found:
        return None
    return obs


def _select_cpi_obs(workspace: Path) -> Tuple[Optional[List[Tuple[int, int, float, str]]], str]:
    """
    Attempt to parse CPI obs from JSON or CSV. Returns (obs_list, source_type)
    source_type in {"json","csv",""}.
    """
    json_path = workspace / "data" / "raw" / "cpi_la.json"
    csv_path = workspace / "data" / "raw" / "cpi_la.csv"
    if json_path.exists():
        obs = _parse_cpi_json(json_path)
        if obs is not None and len(obs) > 0:
            return obs, "json"
    if csv_path.exists():
        obs = _parse_cpi_csv(csv_path)
        if obs is not None and len(obs) > 0:
            return obs, "csv"
    return None, ""


def _compute_latest_and_yoy(obs: List[Tuple[int, int, float, str]]) -> Optional[Tuple[float, Tuple[int, int, float, str]]]:
    """
    obs: list of (year, month, value, periodName)
    Return (yoy_rate, latest_tuple)
    """
    if not obs:
        return None
    latest = max(obs, key=lambda x: (x[0], x[1]))
    latest_year, latest_month, latest_val, _ = latest
    prev = None
    for (y, m, v, pn) in obs:
        if y == latest_year - 1 and m == latest_month:
            prev = (y, m, v, pn)
            break
    if prev is None:
        return None
    prev_val = prev[2]
    try:
        yoy = (latest_val - prev_val) / prev_val
    except Exception:
        return None
    return yoy, latest


def _load_expected_schema(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[str]]]:
    schema_path = workspace / "input" / "expected_report_schema.json"
    data = _safe_load_json(schema_path)
    if not isinstance(data, dict):
        return None, None
    adj_cols = data.get("adjusted_budget_columns")
    sum_cols = data.get("summary_columns")
    if not isinstance(adj_cols, list) or not isinstance(sum_cols, list):
        return None, None
    try:
        adj_cols = [str(x) for x in adj_cols]
        sum_cols = [str(x) for x in sum_cols]
    except Exception:
        return None, None
    return adj_cols, sum_cols


def _load_input_properties(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "maintenance_budget.csv"
    parsed = _safe_read_csv(path)
    if parsed is None:
        return None
    header, rows = parsed
    return rows


def _parse_adjusted_report(workspace: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    path = workspace / "reports" / "adjusted_budget.csv"
    parsed = _safe_read_csv(path)
    if parsed is None:
        return None
    header, rows = parsed
    return header, rows


def _parse_summary(workspace: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    path = workspace / "reports" / "summary.csv"
    parsed = _safe_read_csv(path)
    if parsed is None:
        return None
    header, rows = parsed
    return header, rows


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= tol


def _contains_timestamp(text: str) -> bool:
    patterns = [
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?",
        r"\d{4}-\d{2}-\d{2}",
        r"\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}(:\d{2})?",
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_cpi_file_present": 0.0,
        "raw_cpi_series_and_parse_ok": 0.0,
        "raw_cpi_has_min_24_months": 0.0,
        "adjusted_report_exists": 0.0,
        "adjusted_report_header_exact": 0.0,
        "adjusted_report_row_count_matches_input": 0.0,
        "adjusted_report_yoy_uniform_and_matches_cpi": 0.0,
        "adjusted_report_values_correct": 0.0,
        "summary_exists": 0.0,
        "summary_header_exact": 0.0,
        "summary_one_row": 0.0,
        "summary_totals_min_max_correct": 0.0,
        "summary_yoy_matches_report": 0.0,
        "summary_as_of_date_matches_cpi": 0.0,
        "log_includes_required_info": 0.0,
        "validate_script_exists_and_executable": 0.0,
        "validate_script_runs_success": 0.0,
        "run_once_script_invokes_validator": 0.0,
        "cron_schedule_correct": 0.0,
    }

    # Load CPI obs
    obs, _ = _select_cpi_obs(workspace)
    cpi_json_path = workspace / "data" / "raw" / "cpi_la.json"
    cpi_csv_path = workspace / "data" / "raw" / "cpi_la.csv"
    if cpi_json_path.exists() or cpi_csv_path.exists():
        scores["raw_cpi_file_present"] = 1.0
    else:
        scores["raw_cpi_file_present"] = 0.0

    if obs is not None and len(obs) > 0:
        scores["raw_cpi_series_and_parse_ok"] = 1.0
        uniq = {(y, m) for (y, m, v, pn) in obs}
        if len(uniq) >= 24:
            scores["raw_cpi_has_min_24_months"] = 1.0
    else:
        scores["raw_cpi_series_and_parse_ok"] = 0.0
        scores["raw_cpi_has_min_24_months"] = 0.0

    yoy_info = None
    if obs is not None:
        yoy_info = _compute_latest_and_yoy(obs)

    expected_yoy = None
    latest_obs = None
    if yoy_info is not None:
        expected_yoy, latest_obs = yoy_info

    adj_expected_cols, sum_expected_cols = _load_expected_schema(workspace)

    # Adjusted report checks
    adj_parsed = _parse_adjusted_report(workspace)
    if adj_parsed is not None:
        scores["adjusted_report_exists"] = 1.0
        adj_header, adj_rows = adj_parsed
        if adj_expected_cols is not None and adj_header == adj_expected_cols:
            scores["adjusted_report_header_exact"] = 1.0
        input_rows = _load_input_properties(workspace)
        if input_rows is not None:
            if len(adj_rows) == len(input_rows):
                scores["adjusted_report_row_count_matches_input"] = 1.0
        if adj_rows:
            yoy_values = []
            uniform_ok = True
            for r in adj_rows:
                val = _parse_float(r.get("yoy_inflation_rate", ""))
                if val is None:
                    uniform_ok = False
                    break
                yoy_values.append(val)
            if uniform_ok and all(_almost_equal(y, yoy_values[0], 1e-6) for y in yoy_values):
                if expected_yoy is not None and _almost_equal(yoy_values[0], expected_yoy, 1e-4):
                    scores["adjusted_report_yoy_uniform_and_matches_cpi"] = 1.0
        if expected_yoy is not None and adj_rows and input_rows is not None:
            base_by_id: Dict[str, float] = {}
            for r in input_rows:
                pid = r.get("property_id")
                base = _parse_float(r.get("monthly_budget_usd", ""))
                if pid and base is not None:
                    base_by_id[pid] = base
            all_ok = True
            for r in adj_rows:
                pid = r.get("property_id", "")
                base_out = _parse_float(r.get("base_monthly_budget_usd", ""))
                adj_out = _parse_float(r.get("inflation_adjusted_monthly_budget_usd", ""))
                yoy_out = _parse_float(r.get("yoy_inflation_rate", ""))
                if pid not in base_by_id or base_out is None or adj_out is None or yoy_out is None:
                    all_ok = False
                    break
                if not _almost_equal(base_out, base_by_id[pid], 1e-6):
                    all_ok = False
                    break
                if not _almost_equal(yoy_out, expected_yoy, 1e-4):
                    all_ok = False
                    break
                expected_adj = _round2(base_out * (1.0 + expected_yoy))
                if not _almost_equal(adj_out, expected_adj, 0.005):
                    all_ok = False
                    break
            if all_ok:
                scores["adjusted_report_values_correct"] = 1.0

    # Summary checks
    sum_parsed = _parse_summary(workspace)
    if sum_parsed is not None:
        scores["summary_exists"] = 1.0
        sum_header, sum_rows = sum_parsed
        if sum_expected_cols is not None and sum_header == sum_expected_cols:
            scores["summary_header_exact"] = 1.0
        if len(sum_rows) == 1:
            scores["summary_one_row"] = 1.0
        if adj_parsed is not None and len(sum_rows) == 1:
            adj_header, adj_rows = adj_parsed
            base_vals = []
            adj_vals = []
            needed_cols = {"base_monthly_budget_usd", "inflation_adjusted_monthly_budget_usd", "yoy_inflation_rate"}
            if set(needed_cols).issubset(set(adj_header)):
                for r in adj_rows:
                    b = _parse_float(r.get("base_monthly_budget_usd", ""))
                    a = _parse_float(r.get("inflation_adjusted_monthly_budget_usd", ""))
                    if b is None or a is None:
                        base_vals = []
                        adj_vals = []
                        break
                    base_vals.append(b)
                    adj_vals.append(a)
                if base_vals and adj_vals:
                    total_base = _round2(sum(base_vals))
                    total_adj = _round2(sum(adj_vals))
                    min_adj = _round2(min(adj_vals))
                    max_adj = _round2(max(adj_vals))
                    srow = sum_rows[0]
                    tb = _parse_float(srow.get("total_base_budget_usd", ""))
                    ta = _parse_float(srow.get("total_adjusted_budget_usd", ""))
                    ymin = _parse_float(srow.get("min_adjusted_budget_usd", ""))
                    ymax = _parse_float(srow.get("max_adjusted_budget_usd", ""))
                    if tb is not None and ta is not None and ymin is not None and ymax is not None:
                        if _almost_equal(tb, total_base, 0.005) and _almost_equal(ta, total_adj, 0.005) and _almost_equal(ymin, min_adj, 0.005) and _almost_equal(ymax, max_adj, 0.005):
                            scores["summary_totals_min_max_correct"] = 1.0
                    yoy_from_adj = None
                    if adj_rows:
                        first_yoy = _parse_float(adj_rows[0].get("yoy_inflation_rate", ""))
                        if first_yoy is not None:
                            uniform = True
                            for r in adj_rows:
                                v = _parse_float(r.get("yoy_inflation_rate", ""))
                                if v is None or not _almost_equal(v, first_yoy, 1e-6):
                                    uniform = False
                                    break
                            if uniform:
                                yoy_from_adj = first_yoy
                    yoy_sum = _parse_float(sum_rows[0].get("yoy_inflation_rate", ""))
                    if yoy_from_adj is not None and yoy_sum is not None and _almost_equal(yoy_from_adj, yoy_sum, 1e-4):
                        scores["summary_yoy_matches_report"] = 1.0
        if sum_rows and expected_yoy is not None and latest_obs is not None:
            srow = sum_rows[0]
            as_of = srow.get("as_of_date", "")
            latest_year, latest_month, _, latest_period_name = latest_obs
            valid_formats = set()
            valid_formats.add(f"{latest_year:04d}-{latest_month:02d}")
            month_name = latest_period_name if latest_period_name else datetime(2000, latest_month, 1).strftime("%B")
            valid_formats.add(f"{month_name} {latest_year}")
            acceptable = False
            if as_of in valid_formats:
                acceptable = True
            elif as_of.startswith(f"{latest_year:04d}-{latest_month:02d}"):
                acceptable = True
            elif as_of.strip().lower() == f"{month_name} {latest_year}".lower():
                acceptable = True
            if acceptable:
                scores["summary_as_of_date_matches_cpi"] = 1.0

    # Logs check
    log_path = workspace / "logs" / "last_run.log"
    log_text = _safe_read_text(log_path) or ""
    if log_text:
        has_ts = _contains_timestamp(log_text)
        has_cpi_obs = False
        for _m in re.finditer(r"(CPI[^0-9]{0,20}|observations[^0-9]{0,20})(\d{1,4})", log_text, flags=re.IGNORECASE):
            has_cpi_obs = True
            break
        has_props = False
        props_ok = False
        input_rows = _load_input_properties(workspace)
        expected_props = len(input_rows) if input_rows is not None else None
        for m in re.finditer(r"(properties[^0-9]{0,20})(\d{1,6})", log_text, flags=re.IGNORECASE):
            has_props = True
            try:
                val = int(m.group(2))
                if expected_props is None or val == expected_props:
                    props_ok = True
                    break
            except Exception:
                continue
        has_validation = bool(re.search(r"\b(validation).*(pass|passed|fail|failed)\b", log_text, flags=re.IGNORECASE))
        if has_ts and has_cpi_obs and props_ok and has_validation:
            scores["log_includes_required_info"] = 1.0

    # Validator script
    validate_script = workspace / "scripts" / "validate_output.sh"
    if validate_script.exists():
        scores["validate_script_exists_and_executable"] = 1.0
        if (workspace / "reports" / "adjusted_budget.csv").exists() and (workspace / "reports" / "summary.csv").exists():
            try:
                res = subprocess.run(["bash", str(validate_script)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                if res.returncode == 0:
                    scores["validate_script_runs_success"] = 1.0
            except Exception:
                scores["validate_script_runs_success"] = 0.0

    # run_once.sh contains invocation of validator
    run_once = workspace / "scripts" / "run_once.sh"
    run_once_text = _safe_read_text(run_once) or ""
    if run_once_text:
        if "validate_output.sh" in run_once_text:
            scores["run_once_script_invokes_validator"] = 1.0

    # Cron schedule
    cron_path = workspace / "scheduler" / "cron.tab"
    cron_text = _safe_read_text(cron_path) or ""
    if cron_text:
        for line in cron_text.splitlines():
            if line.strip().startswith("#") or not line.strip():
                continue
            if "0 6 2 * *" in line and "validate_output.sh" in line:
                scores["cron_schedule_correct"] = 1.0
                break

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()