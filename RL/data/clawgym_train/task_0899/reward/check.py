import json
import sys
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(text.split())


def _contains_all_tokens(text: str, tokens: List[str], case_insensitive: bool = True) -> bool:
    hay = text.lower() if case_insensitive else text
    for t in tokens:
        needle = t.lower() if case_insensitive else t
        if needle not in hay:
            return False
    return True


def _tests_output_passed(text: str) -> bool:
    # Favor recognizing positive pass patterns while rejecting failures/errors
    l = text.lower()
    # If clear failure/error indicators not zero
    if "traceback" in l:
        return False
    if "failed" in l and ("0 failed" not in l and "failed=0" not in l):
        return False
    if "error" in l and ("0 error" not in l and "errors=0" not in l and "0 errors" not in l):
        return False
    # Positive signals
    if "passed" in l or "ok" in l:
        return True
    return False


def _compute_expected_from_csv(csv_rows: List[Dict[str, str]]) -> Dict[str, Any]:
    timestamps = [r.get("timestamp") for r in csv_rows if r.get("timestamp") is not None]
    temps = []
    for r in csv_rows:
        try:
            temps.append(float(r.get("celsius")))
        except Exception:
            # If any row is malformed, propagate by raising to be handled by caller
            raise
    sensor_id = csv_rows[0].get("sensor_id") if csv_rows else None
    total = len(temps)
    max_obs = max(temps) if temps else None
    window_start = min(timestamps) if timestamps else None
    window_end = max(timestamps) if timestamps else None
    return {
        "sensor_id": sensor_id,
        "total_readings": total,
        "max_observed_celsius": max_obs,
        "window_start": window_start,
        "window_end": window_end,
    }


def _extract_incident_window(log_path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(log_path)
    if text is None:
        return None
    start_ts = None
    end_ts = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Expect format: <timestamp> ... event=ALERT_RAISED ... or event=ALERT_CLEARED
        parts = line.split()
        ts = parts[0] if parts else None
        if "event=ALERT_RAISED" in line and start_ts is None:
            start_ts = ts
        if "event=ALERT_CLEARED" in line:
            end_ts = ts
    if start_ts or end_ts:
        return {"start": start_ts, "end": end_ts}
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "thresholds_correct_value": 0.0,
        "test_results_file_present": 0.0,
        "tests_passed_summary": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_structure": 0.0,
        "validation_report_values_correct": 0.0,
        "alert_template_exists_and_concise": 0.0,
        "alert_template_fields_and_placeholders": 0.0,
        "incident_email_exists_with_headers": 0.0,
        "incident_email_content_quality": 0.0,
    }

    # Check thresholds.json
    cfg_path = workspace / "config" / "thresholds.json"
    cfg = _load_json(cfg_path)
    if cfg is not None and isinstance(cfg, dict):
        try:
            produce = cfg.get("produce", {})
            max_c = produce.get("max_celsius", None)
            if max_c == 7.0:
                scores["thresholds_correct_value"] = 1.0
        except Exception:
            scores["thresholds_correct_value"] = 0.0

    # Check test results file presence and content for passing tests
    test_results_path = workspace / "output" / "test_results.txt"
    test_results_text = _read_text(test_results_path)
    if test_results_text is not None and test_results_text.strip():
        scores["test_results_file_present"] = 1.0
        if _tests_output_passed(test_results_text):
            scores["tests_passed_summary"] = 1.0

    # Validation report existence and structure/values
    report_path = workspace / "output" / "validation_report.json"
    report = _load_json(report_path)
    if report is not None and isinstance(report, dict):
        scores["validation_report_exists"] = 1.0
        required_fields = [
            "sensor_id",
            "threshold_celsius",
            "max_observed_celsius",
            "total_readings",
            "violations",
            "window_start",
            "window_end",
        ]
        if all(k in report for k in required_fields):
            scores["validation_report_structure"] = 1.0

            # Compute expected from CSV and thresholds
            csv_path = workspace / "data" / "readings.csv"
            rows = _parse_csv_rows(csv_path)
            cfg = cfg if cfg is not None else _load_json(cfg_path)
            try:
                if rows is not None and cfg is not None and isinstance(cfg, dict):
                    exp = _compute_expected_from_csv(rows)
                    # Check reported fields against expectations
                    # sensor_id, totals, start/end exact
                    conds = []
                    conds.append(report.get("sensor_id") == exp["sensor_id"])
                    conds.append(report.get("total_readings") == exp["total_readings"])
                    conds.append(report.get("window_start") == exp["window_start"])
                    conds.append(report.get("window_end") == exp["window_end"])
                    # threshold must be exactly 7.0 after fix
                    conds.append(report.get("threshold_celsius") == 7.0)
                    # max_observed should be equal to computed max
                    try:
                        rep_max = float(report.get("max_observed_celsius"))
                        exp_max = float(exp["max_observed_celsius"]) if exp["max_observed_celsius"] is not None else None
                        conds.append(exp_max is not None and abs(rep_max - exp_max) < 1e-9)
                    except Exception:
                        conds.append(False)
                    # violations should be 0 and max <= 7.0
                    conds.append(report.get("violations") == 0)
                    try:
                        conds.append(float(report.get("max_observed_celsius")) <= 7.0)
                    except Exception:
                        conds.append(False)
                    if all(conds):
                        scores["validation_report_values_correct"] = 1.0
            except Exception:
                # Any parsing error yields 0.0
                pass

    # Alert template checks
    alert_path = workspace / "output" / "alert_template.md"
    alert_text = _read_text(alert_path)
    if alert_text is not None and alert_text.strip():
        # length check
        if _word_count(alert_text) <= 120:
            scores["alert_template_exists_and_concise"] = 1.0
        # fields and placeholders
        field_tokens = ["summary", "impact", "what you should do", "context"]
        placeholder_tokens = ["sensor_id", "max_observed_celsius", "window_start", "window_end"]
        if _contains_all_tokens(alert_text, field_tokens, case_insensitive=True) and _contains_all_tokens(
            alert_text, placeholder_tokens, case_insensitive=True
        ):
            scores["alert_template_fields_and_placeholders"] = 1.0

    # Incident email checks
    email_path = workspace / "output" / "incident_email.md"
    email_text = _read_text(email_path)
    if email_text is not None and email_text.strip():
        # Headers/address presence
        has_addr = "kitchen@office.example" in email_text
        # Subject and Body labels present with non-empty subject line
        lines = email_text.splitlines()
        has_subject_label = any("subject:" in ln.lower() for ln in lines)
        subject_nonempty = False
        for ln in lines:
            if "subject:" in ln.lower():
                after = ln.split(":", 1)[1].strip()
                if after:
                    subject_nonempty = True
                    break
        has_body_label = any("body:" in ln.lower() for ln in lines)
        if has_addr and has_subject_label and has_body_label and subject_nonempty:
            scores["incident_email_exists_with_headers"] = 1.0

        # Content quality checks
        content_l = email_text.lower()
        # Root cause
        root_cause_ok = ("misconfigur" in content_l and "threshold" in content_l)
        # Remediation mentions 7.0
        remediation_ok = "7.0" in email_text
        # Incident window from logs
        incident_info = _extract_incident_window(workspace / "logs" / "incident.log")
        window_ok = False
        if incident_info is not None:
            st = incident_info.get("start")
            en = incident_info.get("end")
            if st and en and (st in email_text) and (en in email_text):
                window_ok = True
        # Reference to validation report file
        evidence_ok = "validation_report.json" in email_text
        # Next steps / prevent recurrence
        next_steps_ok = ("next steps" in content_l) or ("prevent recurrence" in content_l)
        # Reassurance about safety
        reassurance_ok = ("safe" in content_l or "safety" in content_l) and ("priority" in content_l)

        if all([root_cause_ok, remediation_ok, window_ok, evidence_ok, next_steps_ok, reassurance_ok]):
            scores["incident_email_content_quality"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()