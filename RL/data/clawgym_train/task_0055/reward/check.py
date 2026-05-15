import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _parse_csv_rows(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None


def _extract_warning_error_lines(log_text: str) -> Tuple[List[str], List[str]]:
    warnings = []
    errors = []
    for line in log_text.splitlines():
        ls = line.lstrip()
        if ls.startswith("WARNING"):
            warnings.append(line.strip())
        elif ls.startswith("ERROR"):
            errors.append(line.strip())
    return warnings, errors


def _compute_expected_from_inputs(workspace: Path) -> Optional[dict]:
    data_path = workspace / "input" / "data" / "temperature_daily.csv"
    cfg_path = workspace / "input" / "config" / "thresholds.json"
    if not data_path.exists() or not cfg_path.exists():
        return None
    cfg = _load_json(cfg_path)
    if cfg is None:
        return None
    min_t = cfg.get("min_temp_c", -50)
    max_t = cfg.get("max_temp_c", 45)
    try:
        with data_path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows_total = 0
            stations = set()
            warnings = []
            errors = []
            sums = {}
            counts = {}
            for row in reader:
                rows_total += 1
                date = (row.get("date") or "").strip()
                stn = (row.get("station") or "").strip()
                temp_str = (row.get("temp_c") or "").strip()
                if stn:
                    stations.add(stn)
                if temp_str == "":
                    msg = f"Missing temperature at {date} station={stn}"
                    errors.append(msg)
                    continue
                try:
                    temp = float(temp_str)
                    sums[stn] = sums.get(stn, 0.0) + temp
                    counts[stn] = counts.get(stn, 0) + 1
                    if temp < min_t or temp > max_t:
                        msg = f"Out-of-range temperature {temp}C at {date} station={stn} (min={min_t}, max={max_t})"
                        warnings.append(msg)
                except ValueError:
                    msg = f"Non-numeric temperature '{temp_str}' at {date} station={stn}"
                    errors.append(msg)
        means = {}
        for stn in stations:
            cnt = counts.get(stn, 0)
            if cnt > 0:
                means[stn] = sums.get(stn, 0.0) / cnt
            else:
                means[stn] = None
        return {
            "rows_total": rows_total,
            "stations": sorted(list(stations)),
            "stations_count": len(stations),
            "warnings_count": len(warnings),
            "errors_count": len(errors),
            "warnings": warnings,
            "errors": errors,
            "means": means,
            "counts_numeric": counts,
        }
    except Exception:
        return None


def _contains_station_mean(text: str, station: str, mean_value: Optional[float]) -> bool:
    if mean_value is None:
        # look for station and NA
        pattern = re.compile(rf"{re.escape(station)}", re.IGNORECASE)
        if not pattern.search(text):
            return False
        return "NA" in text or "na" in text
    # Search for station name and numeric value in proximity
    # Create a flexible pattern allowing some formatting differences
    # We'll accept exact string of value with up to 4 decimal places.
    # Generate candidate numeric strings
    candidates = set()
    candidates.add(f"{mean_value}")
    candidates.add(f"{mean_value:.2f}")
    candidates.add(f"{mean_value:.3f}")
    candidates.add(f"{mean_value:.4f}")
    # Build regex that checks station within 50 chars of the number
    station_pat = re.escape(station)
    for cand in candidates:
        num_pat = re.escape(cand)
        prox = re.compile(rf"{station_pat}.{{0,50}}{num_pat}|{num_pat}.{{0,50}}{station_pat}", re.IGNORECASE | re.DOTALL)
        if prox.search(text):
            return True
    return False


def _line_with_owner_and_issue(lines: List[str], owner: str) -> bool:
    issue_keywords = ["Missing temperature", "Out-of-range temperature", "Non-numeric temperature", "WARNING", "ERROR"]
    for idx, line in enumerate(lines):
        if owner.lower() in line.lower():
            # Check same line or adjacent lines for issue keyword
            neighborhood = [line]
            if idx > 0:
                neighborhood.append(lines[idx - 1])
            if idx + 1 < len(lines):
                neighborhood.append(lines[idx + 1])
            for neigh in neighborhood:
                for kw in issue_keywords:
                    if kw.lower() in neigh.lower():
                        return True
    return False


def _find_command_in_text(text: str) -> bool:
    # Accept 'python' or 'python3', with the specified arguments in order.
    # Allow optional redirection at the end.
    cmd_re = re.compile(
        r"(python3?|PYTHON3?)\s+scripts/qc\.py\s+--data\s+input/data/temperature_daily\.csv\s+--config\s+input/config/thresholds\.json\s+--outdir\s+out(\s*>.*)?",
        re.IGNORECASE,
    )
    return bool(cmd_re.search(text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    out_dir = workspace / "out"
    deliverables_dir = workspace / "deliverables"

    run_log_path = out_dir / "run.log"
    summary_path = out_dir / "qc_summary.json"
    metrics_path = out_dir / "metrics.csv"
    meeting_notes_path = deliverables_dir / "meeting_notes.md"
    email_path = deliverables_dir / "email_draft.txt"

    scores = {
        "has_out_run_log": 0.0,
        "has_out_qc_summary_json": 0.0,
        "has_out_metrics_csv": 0.0,
        "has_deliverables_meeting_notes": 0.0,
        "has_deliverables_email_draft": 0.0,
        "log_counts_match_summary": 0.0,
        "summary_core_fields_valid": 0.0,
        "summary_matches_expected_input": 0.0,
        "metrics_valid_structure": 0.0,
        "metrics_consistent_with_summary": 0.0,
        "metrics_match_expected_values": 0.0,
        "run_log_contains_info_lines": 0.0,
        "meeting_notes_status_snapshot_complete": 0.0,
        "meeting_notes_key_findings_complete": 0.0,
        "meeting_notes_action_items_per_person": 0.0,
        "email_addressed_to_dr_chen": 0.0,
        "email_includes_command_reproducible": 0.0,
        "email_includes_counts_and_warnings_summary": 0.0,
        "email_action_items_listed": 0.0,
        "email_mentions_artifacts_locations": 0.0,
    }

    # Existence checks
    if run_log_path.exists():
        scores["has_out_run_log"] = 1.0
    if summary_path.exists():
        scores["has_out_qc_summary_json"] = 1.0
    if metrics_path.exists():
        scores["has_out_metrics_csv"] = 1.0
    if meeting_notes_path.exists():
        scores["has_deliverables_meeting_notes"] = 1.0
    if email_path.exists():
        scores["has_deliverables_email_draft"] = 1.0

    # Load contents
    log_text = _read_text(run_log_path) if run_log_path.exists() else None
    summary = _load_json(summary_path) if summary_path.exists() else None

    # Check run log info lines
    if log_text:
        has_start = "INFO: Starting QC run at" in log_text
        has_end = "INFO: QC completed successfully" in log_text
        if has_start and has_end:
            scores["run_log_contains_info_lines"] = 1.0

    # Cross-check counts between log and summary
    if log_text and summary:
        warnings_lines, errors_lines = _extract_warning_error_lines(log_text)
        w_count = len(warnings_lines)
        e_count = len(errors_lines)
        ws = summary.get("warnings_count")
        es = summary.get("errors_count")
        try:
            if isinstance(ws, int) and isinstance(es, int) and w_count == ws and e_count == es:
                scores["log_counts_match_summary"] = 1.0
        except Exception:
            pass

    # Validate summary core fields
    if summary:
        try:
            required_keys = ["run_timestamp", "data_path", "config_path", "rows_total", "stations_count", "warnings_count", "errors_count", "warnings", "errors", "stations"]
            has_keys = all(k in summary for k in required_keys)
            correct_paths = (summary.get("data_path") == "input/data/temperature_daily.csv" and summary.get("config_path") == "input/config/thresholds.json")
            types_ok = isinstance(summary.get("warnings"), list) and isinstance(summary.get("errors"), list) and isinstance(summary.get("stations"), list)
            if has_keys and correct_paths and types_ok:
                scores["summary_core_fields_valid"] = 1.0
        except Exception:
            pass

    # Validate metrics CSV structure
    header_body = _parse_csv_rows(metrics_path) if metrics_path.exists() else None
    metrics_rows_dicts = _parse_csv_dicts(metrics_path) if metrics_path.exists() else None
    if header_body:
        header, body = header_body
        if header == ["station", "mean_temp_c", "count_numeric"] and len(body) >= 0:
            scores["metrics_valid_structure"] = 1.0

    # Metrics consistent with summary (stations)
    if summary and metrics_rows_dicts is not None:
        try:
            metrics_stations = [row.get("station", "").strip() for row in metrics_rows_dicts]
            if sorted(metrics_stations) == sorted(summary.get("stations", [])):
                scores["metrics_consistent_with_summary"] = 1.0
        except Exception:
            pass

    # Compute expected from inputs
    expected = _compute_expected_from_inputs(workspace)

    # Summary matches expected input (rows, stations, warnings/errors counts)
    if summary and expected:
        try:
            if (
                summary.get("rows_total") == expected.get("rows_total")
                and summary.get("stations_count") == expected.get("stations_count")
                and summary.get("warnings_count") == expected.get("warnings_count")
                and summary.get("errors_count") == expected.get("errors_count")
            ):
                scores["summary_matches_expected_input"] = 1.0
        except Exception:
            pass

    # Metrics match expected values
    if metrics_rows_dicts is not None and expected:
        try:
            ok = True
            for row in metrics_rows_dicts:
                stn = (row.get("station") or "").strip()
                mean_str = (row.get("mean_temp_c") or "").strip()
                cnt_str = (row.get("count_numeric") or "").strip()
                exp_count = expected["counts_numeric"].get(stn, 0)
                # parse count
                try:
                    cnt_val = int(cnt_str)
                except Exception:
                    ok = False
                    break
                if cnt_val != exp_count:
                    ok = False
                    break
                exp_mean = expected["means"].get(stn)
                if exp_mean is None:
                    if mean_str.upper() != "NA":
                        ok = False
                        break
                else:
                    try:
                        mean_val = float(mean_str)
                        if abs(mean_val - exp_mean) > 1e-6:
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
            if ok:
                scores["metrics_match_expected_values"] = 1.0
        except Exception:
            pass

    # Meeting notes checks
    meeting_text = _read_text(meeting_notes_path) if meeting_notes_path.exists() else None
    if meeting_text and summary:
        # Status snapshot includes timestamp, data path, total rows, number of stations, and one-sentence status mentioning warnings/errors
        has_ts = str(summary.get("run_timestamp", "")) in meeting_text
        has_data_path = "input/data/temperature_daily.csv" in meeting_text
        has_rows = str(summary.get("rows_total", "")) in meeting_text
        has_stations = str(summary.get("stations_count", "")) in meeting_text
        mentions_status = ("warning" in meeting_text.lower()) or ("error" in meeting_text.lower())
        if has_ts and has_data_path and has_rows and has_stations and mentions_status:
            scores["meeting_notes_status_snapshot_complete"] = 1.0

        # Key findings: list exact WARNING and ERROR messages from run.log and summarize station means
        # Use run.log messages for exactness if available
        kf_ok = True
        if log_text:
            warn_lines, err_lines = _extract_warning_error_lines(log_text)
            for line in warn_lines + err_lines:
                if line not in meeting_text:
                    kf_ok = False
                    break
        else:
            kf_ok = False
        # Check station means summarized
        if kf_ok and expected:
            for stn, mean_val in expected["means"].items():
                if not _contains_station_mean(meeting_text, stn, mean_val):
                    kf_ok = False
                    break
        if kf_ok:
            scores["meeting_notes_key_findings_complete"] = 1.0

        # Action items per person: Alex, Priya, Sam each with reference to specific issue
        lines = meeting_text.splitlines()
        names_ok = True
        for name in ["Alex", "Priya", "Sam"]:
            if not _line_with_owner_and_issue(lines, name):
                names_ok = False
                break
        if names_ok:
            scores["meeting_notes_action_items_per_person"] = 1.0

    # Email draft checks
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text:
        if "Chen" in email_text:
            scores["email_addressed_to_dr_chen"] = 1.0
        if _find_command_in_text(email_text):
            scores["email_includes_command_reproducible"] = 1.0
        # Counts and warnings/errors mention
        has_rows = False
        has_stations = False
        has_warn_err = ("warning" in email_text.lower()) or ("error" in email_text.lower())
        if summary:
            if str(summary.get("rows_total", "")) in email_text:
                has_rows = True
            if str(summary.get("stations_count", "")) in email_text:
                has_stations = True
        if has_rows and has_stations and has_warn_err:
            scores["email_includes_counts_and_warnings_summary"] = 1.0
        # Action items succinctly (owner -> task)
        action_ok = True
        for name in ["Alex", "Priya", "Sam"]:
            # Look for 'name ->' or 'name →'
            pattern = re.compile(rf"{name}\s*(->|→)", re.IGNORECASE)
            if not pattern.search(email_text):
                action_ok = False
                break
        if action_ok:
            scores["email_action_items_listed"] = 1.0
        # Mentions artifact locations (out/ and deliverables/)
        if "out/" in email_text and "deliverables/" in email_text:
            scores["email_mentions_artifacts_locations"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()