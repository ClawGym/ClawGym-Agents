import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List[Any]]:
    data = _load_json(path)
    if isinstance(data, list):
        return data
    return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_iso8601(ts: Any) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        try:
            datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            return True
        except Exception:
            return False


def _to_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, bool):
            return None
        return int(x)
    except Exception:
        try            :
            return int(float(str(x)))
        except Exception:
            return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, bool):
            return None
        return float(x)
    except Exception:
        try:
            return float(str(x))
        except Exception:
            return None


def _floats_close(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def _parse_timeseries_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    rows_raw = _read_csv_dicts(path)
    if rows_raw is None:
        return None, "unreadable"
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        expected_header = "year,population,gdp_per_capita"
        if header_line != expected_header:
            return None, "bad_header"
    except Exception:
        return None, "unreadable"
    data = []
    years_seen = set()
    for row in rows_raw:
        y = row.get("year")
        pop = row.get("population")
        gdp = row.get("gdp_per_capita")
        if y is None or pop is None or gdp is None:
            return None, "missing_columns"
        yi = _to_int(y)
        pi = _to_float(pop)
        gi = _to_float(gdp)
        if yi is None or pi is None or gi is None:
            return None, "non_numeric"
        if yi < 2000 or yi > 2020:
            return None, "year_out_of_range"
        if yi in years_seen:
            return None, "duplicate_year"
        years_seen.add(yi)
        data.append({"year": yi, "population": pi, "gdp_per_capita": gi})
    data.sort(key=lambda r: r["year"])
    return data, None


def _compute_cagr(timeseries: List[Dict[str, Any]]) -> Optional[float]:
    year_to_pop = {r["year"]: r["population"] for r in timeseries}
    if 2000 in year_to_pop and 2020 in year_to_pop:
        start = year_to_pop[2000]
        end = year_to_pop[2020]
        if start is None or end is None or start <= 0:
            return None
        years = 20
        try:
            return (end / start) ** (1.0 / years) - 1.0
        except Exception:
            return None
    return None


def _compute_growth_correlation(timeseries: List[Dict[str, Any]]) -> Tuple[Optional[float], int]:
    if not timeseries or len(timeseries) < 3:
        return None, 0
    timeseries_sorted = sorted(timeseries, key=lambda r: r["year"])
    pop_growth = []
    gdp_growth = []
    for i in range(1, len(timeseries_sorted)):
        y_prev = timeseries_sorted[i - 1]
        y_cur = timeseries_sorted[i]
        if y_cur["year"] != y_prev["year"] + 1:
            continue
        p0 = y_prev["population"]
        p1 = y_cur["population"]
        g0 = y_prev["gdp_per_capita"]
        g1 = y_cur["gdp_per_capita"]
        if p0 is None or p0 <= 0 or g0 is None or g0 <= 0:
            continue
        try:
            gp = (p1 / p0) - 1.0
            gg = (g1 / g0) - 1.0
        except Exception:
            continue
        pop_growth.append(gp)
        gdp_growth.append(gg)
    n = len(pop_growth)
    if n < 3:
        return None, n
    mean_x = sum(pop_growth) / n
    mean_y = sum(gdp_growth) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(pop_growth, gdp_growth))
    den_x = (sum((x - mean_x) ** 2 for x in pop_growth)) ** 0.5
    den_y = (sum((y - mean_y) ** 2 for y in gdp_growth)) ** 0.5
    if den_x == 0 or den_y == 0:
        return None, n
    corr = num / (den_x * den_y)
    if corr > 1:
        corr = 1.0
    if corr < -1:
        corr = -1.0
    return corr, n


def _extract_email_localpart(email: str) -> str:
    return email.split("@")[0] if "@" in email else email


def _find_subject_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("subject:"):
            return line.strip()
    return None


def _contains_approx_percentage(text: str, value: Optional[float], tolerance_pct: float = 0.1) -> bool:
    if value is None:
        return True
    matches = re.findall(r'(-?\d+(?:\.\d+)?)\s*%', text)
    if not matches:
        return False
    target = value * 100.0
    for m in matches:
        try:
            v = float(m)
            if abs(v - target) <= tolerance_pct:
                return True
        except Exception:
            continue
    return False


def _contains_approx_corr_two_decimals(text: str, corr: Optional[float], tolerance: float = 0.01) -> bool:
    if corr is None:
        return True
    tokens = re.findall(r'(-?\d+(?:\.\d+)?)', text)
    if not tokens:
        return False
    target = round(corr, 2)
    for t in tokens:
        try:
            v = float(t)
            if -1.0 <= v <= 1.0 and abs(v - target) <= tolerance:
                return True
        except Exception:
            continue
    return False


def _has_indicators_and_years(text: str) -> bool:
    lower = text.lower()
    has_years = ("2000" in lower and "2020" in lower)
    has_indicators = (("sp.pop.totl" in lower) or ("population" in lower)) and (("ny.gdp.pcap.kd" in lower) or ("gdp per capita" in lower))
    return has_years and has_indicators


def _paths_listed_as_bullets(text: str, paths: List[str]) -> bool:
    lines = text.splitlines()
    found = {p: False for p in paths}
    for line in lines:
        l = line.strip()
        if l.startswith("-") or l.startswith("*"):
            for p in paths:
                if p in l:
                    found[p] = True
    return all(found.values())


def _had_errors_for_iso3(logs: List[Dict[str, Any]], iso3: str) -> Optional[bool]:
    if logs is None:
        return None
    had_any = False
    seen = False
    for e in logs:
        if isinstance(e, dict) and e.get("iso3") == iso3:
            seen = True
            success = e.get("success", None)
            exit_code = e.get("exit_code", None)
            try:
                ec = int(exit_code) if exit_code is not None else None
            except Exception:
                ec = None
            if success is False or (ec is not None and ec != 0):
                had_any = True
    if not seen:
        return None
    return had_any


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "download_log_present_and_schema": 0.0,
        "download_log_entries_complete": 0.0,
        "timeseries_files_valid_structure": 0.0,
        "metrics_consistency_with_timeseries": 0.0,
        "aggregate_summary_consistency": 0.0,
        "email_subjects_correct": 0.0,
        "email_bodies_content_and_attachments": 0.0,
    }

    recipients_path = workspace / "input" / "recipients.csv"
    recipients_rows = _read_csv_dicts(recipients_path)
    if not recipients_rows:
        return scores
    recipients = []
    for row in recipients_rows:
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        iso3 = (row.get("iso3") or "").strip()
        country = (row.get("country") or "").strip()
        if name and email and iso3 and country:
            recipients.append({"name": name, "email": email, "iso3": iso3, "country": country})
    expected_iso3s = [r["iso3"] for r in recipients]
    indicators = ["SP.POP.TOTL", "NY.GDP.PCAP.KD"]

    log_path = workspace / "out" / "logs" / "download_status.json"
    logs_array = _load_json_array(log_path)

    if logs_array is None:
        scores["download_log_present_and_schema"] = 0.0
        scores["download_log_entries_complete"] = 0.0
    else:
        required_fields = ["iso3", "indicator_code", "years_requested", "http_status", "exit_code", "bytes_received", "error_message", "timestamp", "success"]
        total_entries = 0
        valid_entries = 0
        coverage_pairs = {(iso, ind): False for iso in expected_iso3s for ind in indicators}
        for entry in logs_array:
            if not isinstance(entry, dict):
                continue
            iso = entry.get("iso3")
            ind = entry.get("indicator_code")
            if iso in expected_iso3s and ind in indicators:
                total_entries += 1
                has_all = all(k in entry for k in required_fields)
                types_ok = True
                if not has_all:
                    types_ok = False
                else:
                    years_req = entry.get("years_requested")
                    http_status = entry.get("http_status")
                    exit_code = entry.get("exit_code")
                    bytes_received = entry.get("bytes_received")
                    error_message = entry.get("error_message")
                    timestamp = entry.get("timestamp")
                    success = entry.get("success")

                    if years_req != "2000-2020":
                        types_ok = False
                    if not isinstance(http_status, (int, float, str)):
                        types_ok = False
                    if _to_int(exit_code) is None:
                        types_ok = False
                    if _to_float(bytes_received) is None:
                        types_ok = False
                    if not isinstance(error_message, str):
                        types_ok = False
                    if not _parse_iso8601(timestamp):
                        types_ok = False
                    if not isinstance(success, bool):
                        types_ok = False
                if types_ok:
                    valid_entries += 1
                coverage_pairs[(iso, ind)] = True
        schema_score = valid_entries / total_entries if total_entries else 0.0
        scores["download_log_present_and_schema"] = float(schema_score)
        coverage_count = sum(1 for v in coverage_pairs.values() if v)
        scores["download_log_entries_complete"] = float(coverage_count / max(1, len(coverage_pairs))) if coverage_pairs else 0.0

    ts_valid_count = 0
    ts_total = len(expected_iso3s)
    timeseries_by_iso: Dict[str, List[Dict[str, Any]]] = {}
    for iso in expected_iso3s:
        ts_path = workspace / "out" / "data" / f"{iso}_timeseries.csv"
        ts, err = _parse_timeseries_csv(ts_path)
        if ts is not None:
            all_ok = True
            for r in ts:
                if not isinstance(r["year"], int):
                    all_ok = False
                    break
                if _to_float(r["population"]) is None:
                    all_ok = False
                    break
                if _to_float(r["gdp_per_capita"]) is None:
                    all_ok = False
                    break
            if all_ok:
                ts_valid_count += 1
                timeseries_by_iso[iso] = ts
    scores["timeseries_files_valid_structure"] = float(ts_valid_count / ts_total) if ts_total else 0.0

    metrics_total_checks = 0
    metrics_pass_checks = 0
    metrics_by_iso: Dict[str, Dict[str, Any]] = {}
    for rec in recipients:
        iso = rec["iso3"]
        country = rec["country"]
        ts = timeseries_by_iso.get(iso, [])
        years_count = len(ts)
        missing_years = [y for y in range(2000, 2021) if all(r["year"] != y for r in ts)]
        cagr = _compute_cagr(ts)
        corr, corr_n = _compute_growth_correlation(ts)
        metrics_path = workspace / "out" / "metrics" / f"summary_{iso}.json"
        metrics_json = _load_json(metrics_path)
        metrics_by_iso[iso] = metrics_json if isinstance(metrics_json, dict) else {}
        field_checks = {
            "iso3": False,
            "country": False,
            "years_range": False,
            "years_count": False,
            "missing_years": False,
            "cagr_pop_2000_2020": False,
            "corr_pop_growth_vs_gdppc_growth": False,
            "corr_n": False,
            "data_source": False,
        }
        if isinstance(metrics_json, dict):
            field_checks["iso3"] = metrics_json.get("iso3") == iso
            field_checks["country"] = metrics_json.get("country") == country
            field_checks["years_range"] = metrics_json.get("years_range") == "2000-2020"
            field_checks["years_count"] = metrics_json.get("years_count") == years_count
            my = metrics_json.get("missing_years")
            field_checks["missing_years"] = isinstance(my, list) and [int(y) for y in my] == missing_years
            mj_cagr = metrics_json.get("cagr_pop_2000_2020", None)
            if cagr is None:
                field_checks["cagr_pop_2000_2020"] = mj_cagr is None
            else:
                mj_cagr_val = _to_float(mj_cagr)
                field_checks["cagr_pop_2000_2020"] = mj_cagr_val is not None and _floats_close(mj_cagr_val, cagr, tol=1e-4)
            mj_corr = metrics_json.get("corr_pop_growth_vs_gdppc_growth", None)
            if corr is None:
                field_checks["corr_pop_growth_vs_gdppc_growth"] = mj_corr is None
            else:
                mj_corr_val = _to_float(mj_corr)
                field_checks["corr_pop_growth_vs_gdppc_growth"] = mj_corr_val is not None and _floats_close(mj_corr_val, corr, tol=1e-4)
            field_checks["corr_n"] = metrics_json.get("corr_n") == corr_n
            field_checks["data_source"] = metrics_json.get("data_source") == "World Bank Open Data"
        metrics_total_checks += len(field_checks)
        metrics_pass_checks += sum(1 for v in field_checks.values() if v)
    scores["metrics_consistency_with_timeseries"] = (metrics_pass_checks / metrics_total_checks) if metrics_total_checks else 0.0

    agg_path = workspace / "out" / "summary" / "aggregate_status.csv"
    agg_rows = _read_csv_dicts(agg_path)
    agg_score = 0.0
    if agg_rows is None:
        scores["aggregate_summary_consistency"] = 0.0
    else:
        try:
            with agg_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "iso3,recipient_email,years_in_timeseries,missing_years_count,cagr_pop_2000_2020,corr_pop_growth_vs_gdppc_growth,had_errors"
            header_ok = header_line == expected_header
        except Exception:
            header_ok = False
        rows_by_iso = {}
        for row in agg_rows:
            rows_by_iso[row.get("iso3", "").strip()] = row
        per_iso_checks = 0
        per_iso_pass = 0
        for rec in recipients:
            iso = rec["iso3"]
            email = rec["email"]
            ts = timeseries_by_iso.get(iso, [])
            years_count = len(ts)
            miss_count = len([y for y in range(2000, 2021) if all(r["year"] != y for r in ts)])
            met = metrics_by_iso.get(iso, {})
            had_err = _had_errors_for_iso3(logs_array if logs_array is not None else [], iso)
            row = rows_by_iso.get(iso)
            checks = {
                "row_present": row is not None,
                "recipient_email": False,
                "years_in_timeseries": False,
                "missing_years_count": False,
                "cagr": False,
                "corr": False,
                "had_errors": False,
            }
            if row is not None:
                checks["recipient_email"] = (row.get("recipient_email", "").strip() == email)
                yit = _to_int(row.get("years_in_timeseries"))
                myc = _to_int(row.get("missing_years_count"))
                cagr_val = _to_float(row.get("cagr_pop_2000_2020"))
                corr_val = _to_float(row.get("corr_pop_growth_vs_gdppc_growth"))
                had_errors_str = (row.get("had_errors") or "").strip().lower()
                had_errors_bool = None
                if had_errors_str in ["true", "false"]:
                    had_errors_bool = (had_errors_str == "true")
                checks["years_in_timeseries"] = (yit == years_count)
                checks["missing_years_count"] = (myc == miss_count)
                met_cagr = met.get("cagr_pop_2000_2020", None) if isinstance(met, dict) else None
                met_corr = met.get("corr_pop_growth_vs_gdppc_growth", None) if isinstance(met, dict) else None
                if met_cagr is None:
                    checks["cagr"] = (row.get("cagr_pop_2000_2020") in [None, "", ""])
                else:
                    checks["cagr"] = (cagr_val is not None and met_cagr is not None and _floats_close(cagr_val, _to_float(met_cagr), tol=1e-4))
                if met_corr is None:
                    checks["corr"] = (row.get("corr_pop_growth_vs_gdppc_growth") in [None, "", ""])
                else:
                    checks["corr"] = (corr_val is not None and met_corr is not None and _floats_close(corr_val, _to_float(met_corr), tol=1e-4))
                if had_err is None:
                    checks["had_errors"] = False
                else:
                    checks["had_errors"] = (had_errors_bool == had_err)
            per_iso_checks += len(checks)
            per_iso_pass += sum(1 for v in checks.values() if v)
        total_checks = per_iso_checks + 1
        total_pass = per_iso_pass + (1 if header_ok else 0)
        agg_score = total_pass / total_checks if total_checks else 0.0
        scores["aggregate_summary_consistency"] = float(agg_score)

    subjects_total = 0
    subjects_pass = 0
    bodies_total = 0
    bodies_pass = 0
    for rec in recipients:
        iso = rec["iso3"]
        email = rec["email"]
        name = rec["name"]
        country = rec["country"]
        local = _extract_email_localpart(email)
        email_path = workspace / "out" / "emails" / f"{iso}_{local}.md"
        txt = _read_text(email_path)
        subjects_total += 1
        if txt is not None:
            subj_line = _find_subject_line(txt)
            if subj_line:
                subj_text = subj_line.split(":", 1)[1].strip() if ":" in subj_line else subj_line
                expected_subject_hyphen = f"Update: Population vs. Development for {country} ({iso}) 2000-2020"
                expected_subject_endash = f"Update: Population vs. Development for {country} ({iso}) 2000–2020"
                if subj_text == expected_subject_hyphen or subj_text == expected_subject_endash:
                    subjects_pass += 1
        bodies_total += 1
        if txt is not None:
            body_ok = True
            if name not in txt:
                body_ok = False
            if not _has_indicators_and_years(txt):
                body_ok = False
            ts = timeseries_by_iso.get(iso, [])
            cagr_val = _compute_cagr(ts)
            corr_val, corr_n = _compute_growth_correlation(ts)
            if not _contains_approx_percentage(txt, cagr_val, tolerance_pct=0.1):
                body_ok = False
            if not _contains_approx_corr_two_decimals(txt, corr_val, tolerance=0.01):
                body_ok = False
            if "data download status" not in txt.lower():
                body_ok = False
            mentioned_status = True
            if logs_array is not None:
                has_issue = False
                for e in logs_array:
                    if isinstance(e, dict) and e.get("iso3") == iso:
                        try:
                            ec = int(e.get("exit_code"))
                        except Exception:
                            ec = None
                        hs = e.get("http_status")
                        hs_int = None
                        try:
                            hs_int = int(hs)
                        except Exception:
                            try:
                                hs_int = int(float(str(hs)))
                            except Exception:
                                hs_int = None
                        if (ec is not None and ec != 0) or (hs_int is not None and hs_int != 200):
                            has_issue = True
                lower = txt.lower()
                if has_issue:
                    if not ("error" in lower or "non-zero" in lower or "http" in lower):
                        mentioned_status = False
                else:
                    if not ("success" in lower or "successful" in lower):
                        mentioned_status = False
            if not mentioned_status:
                body_ok = False
            attach_paths = [f"out/data/{iso}_timeseries.csv", f"out/metrics/summary_{iso}.json"]
            if not _paths_listed_as_bullets(txt, attach_paths):
                body_ok = False
            for p in attach_paths:
                if not (workspace / p).exists():
                    body_ok = False
            if body_ok:
                bodies_pass += 1

    scores["email_subjects_correct"] = float(subjects_pass / subjects_total) if subjects_total else 0.0
    scores["email_bodies_content_and_attachments"] = float(bodies_pass / bodies_total) if bodies_total else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()