import json
import sys
import subprocess
import csv
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            rdr = csv.DictReader(f)
            header = rdr.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in rdr]
            return header, rows
    except Exception:
        return None, None


def _safe_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: Any) -> Optional[int]:
    try:
        # Allow float strings that are whole numbers
        if isinstance(s, float):
            return int(s) if s.is_integer() else None
        s_str = str(s).strip()
        if s_str == "":
            return None
        if re.fullmatch(r"-?\d+", s_str):
            return int(s_str)
        # check if it's something like "3.0"
        f = float(s_str)
        if f.is_integer():
            return int(f)
        return None
    except Exception:
        return None


def _compare_float(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _run_checker(workspace: Path) -> Optional[Dict[str, Any]]:
    check_script = workspace / "input" / "check_data.py"
    readings_csv = workspace / "input" / "readings.csv"
    if not check_script.exists() or not readings_csv.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(check_script), str(readings_csv)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace),
            text=True,
            encoding="utf-8",
        )
        stdout = proc.stdout
        stderr = proc.stderr
        rc = proc.returncode
        parsed = _parse_checker_output(stdout=stdout, stderr=stderr)
        parsed["returncode"] = rc
        parsed["stdout"] = stdout
        parsed["stderr"] = stderr
        return parsed
    except Exception:
        return None


def _parse_checker_output(stdout: str, stderr: str) -> Dict[str, Any]:
    # Parse ERROR lines from stderr and WARNING + SUMMARY from stdout
    error_re = re.compile(r"^ERROR\s+unit=(?P<unit>[^ ]+)\s+timestamp=(?P<ts>[^ ]+)\s+reason=(?P<reason>.+)$")
    warn_re = re.compile(r"^WARNING\s+unit=(?P<unit>[^ ]+)\s+timestamp=(?P<ts>[^ ]+)\s+reason=(?P<reason>.+)$")
    summary_re = re.compile(r"^SUMMARY\s+errors=(?P<errors>\d+)\s+warnings=(?P<warnings>\d+)$")

    errors_by_pair = set()
    warnings_by_pair = set()
    errors_by_unit: Dict[str, int] = {}
    warnings_by_unit: Dict[str, int] = {}
    summary_counts = {"errors": None, "warnings": None}

    for line in stderr.splitlines():
        m = error_re.match(line.strip())
        if m:
            unit = m.group("unit")
            ts = m.group("ts")
            errors_by_pair.add((unit, ts))
            errors_by_unit[unit] = errors_by_unit.get(unit, 0) + 1
    for line in stdout.splitlines():
        sline = line.strip()
        m_w = warn_re.match(sline)
        if m_w:
            unit = m_w.group("unit")
            ts = m_w.group("ts")
            warnings_by_pair.add((unit, ts))
            warnings_by_unit[unit] = warnings_by_unit.get(unit, 0) + 1
            continue
        m_s = summary_re.match(sline)
        if m_s:
            summary_counts["errors"] = int(m_s.group("errors"))
            summary_counts["warnings"] = int(m_s.group("warnings"))

    return {
        "errors_by_pair": errors_by_pair,
        "warnings_by_pair": warnings_by_pair,
        "errors_by_unit": errors_by_unit,
        "warnings_by_unit": warnings_by_unit,
        "summary": summary_counts,
    }


def _parse_checker_log_content(content: str) -> Dict[str, Any]:
    # Log may contain both stdout and stderr mixed. Extract ERROR/WARNING/SUMMARY regardless of stream.
    error_re = re.compile(r"^ERROR\s+unit=(?P<unit>[^ ]+)\s+timestamp=(?P<ts>[^ ]+)\s+reason=(?P<reason>.+)$")
    warn_re = re.compile(r"^WARNING\s+unit=(?P<unit>[^ ]+)\s+timestamp=(?P<ts>[^ ]+)\s+reason=(?P<reason>.+)$")
    summary_re = re.compile(r"^SUMMARY\s+errors=(?P<errors>\d+)\s+warnings=(?P<warnings>\d+)$")

    errors_by_pair = set()
    warnings_by_pair = set()
    errors_by_unit: Dict[str, int] = {}
    warnings_by_unit: Dict[str, int] = {}
    summary_counts = {"errors": None, "warnings": None}
    for raw in content.splitlines():
        line = raw.strip()
        m_e = error_re.match(line)
        if m_e:
            unit = m_e.group("unit")
            ts = m_e.group("ts")
            errors_by_pair.add((unit, ts))
            errors_by_unit[unit] = errors_by_unit.get(unit, 0) + 1
            continue
        m_w = warn_re.match(line)
        if m_w:
            unit = m_w.group("unit")
            ts = m_w.group("ts")
            warnings_by_pair.add((unit, ts))
            warnings_by_unit[unit] = warnings_by_unit.get(unit, 0) + 1
            continue
        m_s = summary_re.match(line)
        if m_s:
            summary_counts["errors"] = int(m_s.group("errors"))
            summary_counts["warnings"] = int(m_s.group("warnings"))
            continue
    return {
        "errors_by_pair": errors_by_pair,
        "warnings_by_pair": warnings_by_pair,
        "errors_by_unit": errors_by_unit,
        "warnings_by_unit": warnings_by_unit,
        "summary": summary_counts,
    }


def _detect_exit_code_in_log(content: str, expected_rc: int) -> bool:
    # Accept several formats:
    # - A line that is exactly the integer exit code
    # - Lines containing 'exit code: N', 'exit_code=N', 'returncode: N', etc.
    patterns = [
        re.compile(r"(?i)\bexit\s*code\b\s*[:=]\s*(\d+)\b"),
        re.compile(r"(?i)\breturn\s*code\b\s*[:=]\s*(\d+)\b"),
        re.compile(r"(?i)\b(exitcode|returncode)\b\s*[:=]?\s*(\d+)\b"),
    ]
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        # exact integer line
        if re.fullmatch(r"-?\d+", stripped):
            try:
                val = int(stripped)
                if val == expected_rc:
                    return True
            except Exception:
                pass
        # pattern match
        for pat in patterns:
            m = pat.search(stripped)
            if m:
                g = m.groups()
                num = None
                for token in g[::-1]:
                    if token is None:
                        continue
                    if re.fullmatch(r"\d+", str(token)):
                        num = int(token)
                        break
                if num is not None and num == expected_rc:
                    return True
    return False


def _load_readings(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "readings.csv"
    header, rows = _load_csv_dicts(path)
    if header is None or rows is None:
        return None
    # Verify required columns exist
    required = ["unit_id", "site", "region", "timestamp", "energy_kwh", "runtime_hours"]
    for col in required:
        if col not in header:
            return None
    return rows


def _compute_expected_metrics(workspace: Path, error_pairs: set) -> Optional[Dict[str, Any]]:
    rows = _load_readings(workspace)
    if rows is None:
        return None
    units = {}
    for row in rows:
        unit = (row.get("unit_id") or "").strip()
        site = (row.get("site") or "").strip()
        region = (row.get("region") or "").strip()
        ts = (row.get("timestamp") or "").strip()
        e_s = row.get("energy_kwh")
        r_s = row.get("runtime_hours")
        if unit == "" or ts == "":
            continue
        # skip if (unit, ts) flagged as error
        if (unit, ts) in error_pairs:
            continue
        e_v = _safe_float(e_s)
        r_v = _safe_float(r_s)
        if unit not in units:
            units[unit] = {
                "site": site,
                "region": region,
                "valid_readings": 0,
                "total_energy_kwh": 0.0,
                "total_runtime_hours": 0.0,
            }
        units[unit]["valid_readings"] += 1
        units[unit]["total_energy_kwh"] += (e_v if e_v is not None else 0.0)
        units[unit]["total_runtime_hours"] += (r_v if r_v is not None else 0.0)

    # Ensure each unit in readings appears in summary even if zero valid rows
    unit_ids_in_readings = set([(row.get("unit_id") or "").strip() for row in rows if (row.get("unit_id") or "").strip() != ""])
    for uid in unit_ids_in_readings:
        if uid not in units:
            site = ""
            region = ""
            for row in rows:
                if (row.get("unit_id") or "").strip() == uid:
                    site = (row.get("site") or "").strip()
                    region = (row.get("region") or "").strip()
                    break
            units[uid] = {
                "site": site,
                "region": region,
                "valid_readings": 0,
                "total_energy_kwh": 0.0,
                "total_runtime_hours": 0.0,
                "avg_kwh_per_hour": 0.0,
            }

    # Compute avg
    for uid, rec in units.items():
        runtime = rec.get("total_runtime_hours", 0.0)
        if runtime > 0:
            rec["avg_kwh_per_hour"] = rec.get("total_energy_kwh", 0.0) / runtime
        else:
            rec["avg_kwh_per_hour"] = 0.0

    return {
        "units": units,
        "unit_ids": sorted(units.keys()),
    }


def _expected_least_efficient_top5(expected_metrics: Dict[str, Any]) -> List[Tuple[str, float, float, int]]:
    # Filter: valid_readings >= 3 and total_runtime_hours >= 10
    rows = []
    for uid, rec in expected_metrics["units"].items():
        vr = rec.get("valid_readings", 0)
        tr = rec.get("total_runtime_hours", 0.0)
        if vr >= 3 and tr >= 10:
            rows.append((uid, rec.get("avg_kwh_per_hour", 0.0), tr, vr))
    # Sort ascending by avg_kwh_per_hour, then unit_id ascending
    rows.sort(key=lambda x: (x[1], x[0]))
    return rows[:5]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "data_check_log_messages": 0.0,
        "data_check_log_exit_code_recorded": 0.0,
        "issues_by_unit_counts_correct": 0.0,
        "efficiency_summary_correct_values": 0.0,
        "least_efficient_top5_correct_order_and_values": 0.0,
    }

    # Paths to expected outputs
    out_dir = workspace / "output"
    data_check_log_path = out_dir / "data_check.log"
    issues_by_unit_path = out_dir / "issues_by_unit.csv"
    efficiency_summary_path = out_dir / "efficiency_summary.csv"
    least_efficient_path = out_dir / "least_efficient_top5.csv"

    # Run checker to compute expected
    checker_result = _run_checker(workspace)
    # Prepare expected structures
    expected_error_pairs = set()
    expected_warning_pairs = set()
    expected_errors_by_unit: Dict[str, int] = {}
    expected_warnings_by_unit: Dict[str, int] = {}
    expected_summary_err = None
    expected_summary_warn = None
    expected_rc = None
    if checker_result is not None:
        expected_error_pairs = checker_result.get("errors_by_pair", set())
        expected_warning_pairs = checker_result.get("warnings_by_pair", set())
        expected_errors_by_unit = checker_result.get("errors_by_unit", {})
        expected_warnings_by_unit = checker_result.get("warnings_by_unit", {})
        summary = checker_result.get("summary", {})
        expected_summary_err = summary.get("errors")
        expected_summary_warn = summary.get("warnings")
        expected_rc = checker_result.get("returncode")

    # 1) Validate data_check.log content (messages and summary)
    log_content = _read_text(data_check_log_path)
    if log_content is not None and checker_result is not None:
        parsed_log = _parse_checker_log_content(log_content)
        # Check that sets of error pairs and warning pairs match expected (exact)
        log_error_pairs = parsed_log.get("errors_by_pair", set())
        log_warning_pairs = parsed_log.get("warnings_by_pair", set())
        log_summary = parsed_log.get("summary", {})
        log_sum_err = log_summary.get("errors")
        log_sum_warn = log_summary.get("warnings")

        if (
            log_error_pairs == expected_error_pairs
            and log_warning_pairs == expected_warning_pairs
            and log_sum_err == expected_summary_err
            and log_sum_warn == expected_summary_warn
        ):
            scores["data_check_log_messages"] = 1.0
        else:
            scores["data_check_log_messages"] = 0.0
    else:
        scores["data_check_log_messages"] = 0.0

    # 1b) Check that exit code is recorded in the log in some recognizable form
    if log_content is not None and expected_rc is not None:
        if _detect_exit_code_in_log(log_content, expected_rc):
            scores["data_check_log_exit_code_recorded"] = 1.0
        else:
            scores["data_check_log_exit_code_recorded"] = 0.0
    else:
        scores["data_check_log_exit_code_recorded"] = 0.0

    # 2) Validate issues_by_unit.csv
    header, rows = _load_csv_dicts(issues_by_unit_path)
    if header is not None and rows is not None and checker_result is not None:
        # Require exact header order
        required_header = ["unit_id", "errors", "warnings"]
        if header == required_header:
            # Build mapping from file
            file_map: Dict[str, Tuple[int, int]] = {}
            valid = True
            for row in rows:
                uid = (row.get("unit_id") or "").strip()
                if uid == "":
                    valid = False
                    break
                e = _safe_int(row.get("errors"))
                w = _safe_int(row.get("warnings"))
                if e is None or w is None:
                    valid = False
                    break
                if uid in file_map:
                    valid = False
                    break
                file_map[uid] = (e, w)
            if valid:
                # Expected counts by unit
                expected_counts = {}
                readings_rows = _load_readings(workspace)
                units_in_readings = set()
                if readings_rows is not None:
                    units_in_readings = set([(r.get("unit_id") or "").strip() for r in readings_rows if (r.get("unit_id") or "").strip() != ""])
                # Combine units set: any unit that appears in readings or messages
                combined_units = set(units_in_readings) | set(expected_errors_by_unit.keys()) | set(expected_warnings_by_unit.keys())
                for uid in combined_units:
                    e = expected_errors_by_unit.get(uid, 0)
                    w = expected_warnings_by_unit.get(uid, 0)
                    expected_counts[uid] = (e, w)
                ok = True
                for uid, (e_exp, w_exp) in expected_counts.items():
                    if e_exp != 0 or w_exp != 0:
                        if uid not in file_map:
                            ok = False
                            break
                        e_got, w_got = file_map[uid]
                        if e_got != e_exp or w_got != w_exp:
                            ok = False
                            break
                if ok:
                    for uid, (e_got, w_got) in file_map.items():
                        if uid in expected_counts:
                            e_exp, w_exp = expected_counts[uid]
                            if e_got != e_exp or w_got != w_exp:
                                ok = False
                                break
                if ok:
                    scores["issues_by_unit_counts_correct"] = 1.0
                else:
                    scores["issues_by_unit_counts_correct"] = 0.0
            else:
                scores["issues_by_unit_counts_correct"] = 0.0
        else:
            scores["issues_by_unit_counts_correct"] = 0.0
    else:
        scores["issues_by_unit_counts_correct"] = 0.0

    # 3) Validate efficiency_summary.csv
    expected_metrics = None
    if checker_result is not None:
        expected_metrics = _compute_expected_metrics(workspace, checker_result.get("errors_by_pair", set()))
    if expected_metrics is not None:
        header_s, rows_s = _load_csv_dicts(efficiency_summary_path)
        if header_s is not None and rows_s is not None:
            req_header_s = ["unit_id", "site", "region", "valid_readings", "total_energy_kwh", "total_runtime_hours", "avg_kwh_per_hour"]
            if header_s == req_header_s:
                # Build file mapping by unit
                file_units: Dict[str, Dict[str, Any]] = {}
                valid = True
                for row in rows_s:
                    uid = (row.get("unit_id") or "").strip()
                    if uid == "":
                        valid = False
                        break
                    if uid in file_units:
                        valid = False
                        break
                    site = (row.get("site") or "").strip()
                    region = (row.get("region") or "").strip()
                    vr = _safe_int(row.get("valid_readings"))
                    te = _safe_float(row.get("total_energy_kwh"))
                    tr = _safe_float(row.get("total_runtime_hours"))
                    avg = _safe_float(row.get("avg_kwh_per_hour"))
                    if vr is None or te is None or tr is None or avg is None:
                        valid = False
                        break
                    file_units[uid] = {
                        "site": site,
                        "region": region,
                        "valid_readings": vr,
                        "total_energy_kwh": te,
                        "total_runtime_hours": tr,
                        "avg_kwh_per_hour": avg,
                    }
                if valid:
                    readings_rows = _load_readings(workspace)
                    units_in_readings = set()
                    if readings_rows is not None:
                        units_in_readings = set([(r.get("unit_id") or "").strip() for r in readings_rows if (r.get("unit_id") or "").strip() != ""])
                    if set(file_units.keys()) == units_in_readings:
                        ok = True
                        for uid in units_in_readings:
                            exp = expected_metrics["units"].get(uid)
                            if exp is None:
                                ok = False
                                break
                            got = file_units.get(uid)
                            if got is None:
                                ok = False
                                break
                            if got["site"] != exp["site"] or got["region"] != exp["region"]:
                                ok = False
                                break
                            if got["valid_readings"] != exp["valid_readings"]:
                                ok = False
                                break
                            if not _compare_float(got["total_energy_kwh"], exp["total_energy_kwh"]):
                                ok = False
                                break
                            if not _compare_float(got["total_runtime_hours"], exp["total_runtime_hours"]):
                                ok = False
                                break
                            if not _compare_float(got["avg_kwh_per_hour"], exp["avg_kwh_per_hour"]):
                                ok = False
                                break
                        if ok:
                            scores["efficiency_summary_correct_values"] = 1.0
                        else:
                            scores["efficiency_summary_correct_values"] = 0.0
                    else:
                        scores["efficiency_summary_correct_values"] = 0.0
                else:
                    scores["efficiency_summary_correct_values"] = 0.0
            else:
                scores["efficiency_summary_correct_values"] = 0.0
        else:
            scores["efficiency_summary_correct_values"] = 0.0
    else:
        scores["efficiency_summary_correct_values"] = 0.0

    # 4) Validate least_efficient_top5.csv
    if expected_metrics is not None:
        expected_top5 = _expected_least_efficient_top5(expected_metrics)
        header_t, rows_t = _load_csv_dicts(least_efficient_path)
        if header_t is not None and rows_t is not None:
            req_header_t = ["unit_id", "avg_kwh_per_hour", "total_runtime_hours", "valid_readings"]
            if header_t == req_header_t:
                # Parse rows preserving order
                valid = True
                file_top: List[Tuple[str, float, float, int]] = []
                for row in rows_t:
                    uid = (row.get("unit_id") or "").strip()
                    avg = _safe_float(row.get("avg_kwh_per_hour"))
                    tr = _safe_float(row.get("total_runtime_hours"))
                    vr = _safe_int(row.get("valid_readings"))
                    if uid == "" or avg is None or tr is None or vr is None:
                        valid = False
                        break
                    file_top.append((uid, avg, tr, vr))
                if valid:
                    if len(file_top) == len(expected_top5):
                        ok = True
                        for (uid_g, avg_g, tr_g, vr_g), (uid_e, avg_e, tr_e, vr_e) in zip(file_top, expected_top5):
                            if uid_g != uid_e:
                                ok = False
                                break
                            if vr_g != vr_e:
                                ok = False
                                break
                            if not _compare_float(avg_g, avg_e):
                                ok = False
                                break
                            if not _compare_float(tr_g, tr_e):
                                ok = False
                                break
                        if ok:
                            scores["least_efficient_top5_correct_order_and_values"] = 1.0
                        else:
                            scores["least_efficient_top5_correct_order_and_values"] = 0.0
                    else:
                        scores["least_efficient_top5_correct_order_and_values"] = 0.0
                else:
                    scores["least_efficient_top5_correct_order_and_values"] = 0.0
            else:
                scores["least_efficient_top5_correct_order_and_values"] = 0.0
        else:
            scores["least_efficient_top5_correct_order_and_values"] = 0.0
    else:
        scores["least_efficient_top5_correct_order_and_values"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()