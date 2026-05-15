import json
import os
import sys
import csv

def load_session_id(input_dir):
    session_path = os.path.join(input_dir, "session.json")
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        session_id = data.get("session")
        if isinstance(session_id, str) and session_id.strip():
            return session_id.strip()
    except Exception:
        pass
    return None

def load_participants(input_dir):
    participants_path = os.path.join(input_dir, "participants.csv")
    rows = []
    try:
        with open(participants_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys to expected set; handle possible variations silently
                normalized = {
                    "event": (row.get("event") or "").strip(),
                    "user": (row.get("user") or "").strip(),
                    "email": (row.get("email") or "").strip(),
                    "register": (row.get("register") or "").strip().lower(),
                    "checkin": (row.get("checkin") or "").strip().lower(),
                    "payment_status": (row.get("payment_status") or "").strip().lower(),
                }
                rows.append(normalized)
    except Exception:
        return None, None, None, None
    # Compute expected counts
    run_expected = sum(1 for r in rows if r["register"] == "yes")
    check_expected = sum(1 for r in rows if r["checkin"] == "yes")
    convert_expected = sum(1 for r in rows if r["payment_status"] == "paid")
    expected_total = run_expected + check_expected + convert_expected
    # Per-event counts
    by_event = {}
    for r in rows:
        ev = r["event"]
        if ev not in by_event:
            by_event[ev] = {"run": 0, "check": 0, "convert": 0}
        if r["register"] == "yes":
            by_event[ev]["run"] += 1
        if r["checkin"] == "yes":
            by_event[ev]["check"] += 1
        if r["payment_status"] == "paid":
            by_event[ev]["convert"] += 1
    return rows, (run_expected, check_expected, convert_expected, expected_total), by_event, participants_path

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def file_exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def validate_export_json(export_json_path, session_id, expected_counts):
    run_expected, check_expected, convert_expected, expected_total = expected_counts
    result = {
        "export_json_exists": False,
        "export_json_valid": False,
        "export_json_session_entries_enough": False,
        "export_json_action_counts_enough": False,
    }
    if not file_exists(export_json_path):
        return result, 0, 0, 0, 0
    result["export_json_exists"] = True
    data = read_json_file(export_json_path)
    if not isinstance(data, list):
        return result, 0, 0, 0, 0
    result["export_json_valid"] = True
    # Count entries with session tag
    total_with_session = 0
    run_with_session = 0
    check_with_session = 0
    convert_with_session = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        val = item.get("value")
        if not isinstance(val, str):
            continue
        if session_id in val:
            total_with_session += 1
            vlow = val.lower()
            if "action=register" in vlow:
                run_with_session += 1
            if "action=checkin" in vlow:
                check_with_session += 1
            if "action=payment:paid" in vlow:
                convert_with_session += 1
    if total_with_session >= expected_total:
        result["export_json_session_entries_enough"] = True
    # Ensure per-action counts meet or exceed expectations
    if (run_with_session >= run_expected and
        check_with_session >= check_expected and
        convert_with_session >= convert_expected):
        result["export_json_action_counts_enough"] = True
    return result, total_with_session, run_with_session, check_with_session, convert_with_session

def validate_export_csv(export_csv_path, session_id, expected_total):
    result = {
        "export_csv_exists": False,
        "export_csv_header_ok": False,
        "export_csv_session_rows_enough": False,
    }
    if not file_exists(export_csv_path):
        return result, 0
    result["export_csv_exists"] = True
    try:
        with open(export_csv_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return result, 0
    if not lines:
        return result, 0
    header = lines[0].strip().lower()
    # Expect a header with type,time,value in some order, separated by commas
    header_cols = [c.strip() for c in header.split(",")]
    if all(col in header_cols for col in ["type", "time", "value"]):
        result["export_csv_header_ok"] = True
    # Count rows (excluding header) that contain the session id substring
    count_session_rows = 0
    for line in lines[1:]:
        if session_id in line:
            count_session_rows += 1
    if count_session_rows >= expected_total:
        result["export_csv_session_rows_enough"] = True
    return result, count_session_rows

def validate_summary_json(summary_path, session_id, expected_counts, by_event_expected):
    run_expected, check_expected, convert_expected, expected_total = expected_counts
    result = {
        "summary_json_exists": False,
        "summary_json_valid": False,
        "summary_counts_match": False,
        "summary_by_event_match": False,
    }
    if not file_exists(summary_path):
        return result
    result["summary_json_exists"] = True
    data = read_json_file(summary_path)
    if not isinstance(data, dict):
        return result
    # Basic structure check
    if "session" not in data or "counts" not in data or "by_event" not in data:
        return result
    counts = data.get("counts")
    by_event = data.get("by_event")
    if not isinstance(counts, dict) or not isinstance(by_event, dict):
        return result
    # Session check (must equal)
    if data.get("session") != session_id:
        # Still mark valid JSON structure but fail counts
        result["summary_json_valid"] = True
        return result
    result["summary_json_valid"] = True
    # Counts check
    try:
        run_c = int(counts.get("run"))
        check_c = int(counts.get("check"))
        convert_c = int(counts.get("convert"))
        total_c = int(counts.get("total"))
    except Exception:
        run_c = check_c = convert_c = total_c = None
    if (run_c == run_expected and
        check_c == check_expected and
        convert_c == convert_expected and
        total_c == expected_total):
        result["summary_counts_match"] = True
    # by_event check: ensure each expected event is present with matching counts
    by_event_ok = True
    for ev, ev_counts in by_event_expected.items():
        got = by_event.get(ev)
        if not isinstance(got, dict):
            by_event_ok = False
            break
        try:
            grun = int(got.get("run"))
            gcheck = int(got.get("check"))
            gconvert = int(got.get("convert"))
        except Exception:
            by_event_ok = False
            break
        if grun != ev_counts["run"] or gcheck != ev_counts["check"] or gconvert != ev_counts["convert"]:
            by_event_ok = False
            break
    if by_event_ok:
        result["summary_by_event_match"] = True
    return result

def validate_report(report_path):
    result = {
        "report_exists": False,
        "report_has_sections": False,
        "report_has_commands": False,
    }
    if not file_exists(report_path):
        return result
    result["report_exists"] = True
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return result
    lower = content.lower()
    # Must include "Recommendations" and either "Overview" or "Analysis"
    has_recs = "recommendations" in lower
    has_overview_or_analysis = ("overview" in lower) or ("analysis" in lower)
    if has_recs and has_overview_or_analysis:
        result["report_has_sections"] = True
    # Appendix with commands; require "appendix" and representative commands
    has_appendix = "appendix" in lower
    has_run_cmd = "signup run" in lower
    has_check_cmd = "signup check" in lower
    has_convert_cmd = "signup convert" in lower
    if has_appendix and has_run_cmd and has_check_cmd and has_convert_cmd:
        result["report_has_commands"] = True
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {}
    # Load inputs
    session_id = load_session_id(input_dir)
    rows, expected_counts, by_event_expected, participants_path = load_participants(input_dir)
    # Initialize expected counts defaults
    if expected_counts is None:
        expected_counts = (0, 0, 0, 0)
        by_event_expected = {}

    run_expected, check_expected, convert_expected, expected_total = expected_counts

    # Validate export.json
    export_json_path = os.path.join(output_dir, "export.json")
    ej_checks, ej_total_with_session, ej_run, ej_check, ej_convert = validate_export_json(export_json_path, session_id or "", expected_counts)
    checks.update(ej_checks)

    # Validate export.csv
    export_csv_path = os.path.join(output_dir, "export.csv")
    ec_checks, ec_session_rows = validate_export_csv(export_csv_path, session_id or "", expected_total)
    checks.update(ec_checks)

    # Validate summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary_checks = validate_summary_json(summary_path, session_id or "", expected_counts, by_event_expected or {})
    checks.update(summary_checks)

    # Validate report.md
    report_path = os.path.join(output_dir, "report.md")
    report_checks = validate_report(report_path)
    checks.update(report_checks)

    # Define weights for reward calculation
    weights = {
        "export_json_valid": 0.10,
        "export_json_session_entries_enough": 0.15,
        "export_json_action_counts_enough": 0.15,
        "export_csv_header_ok": 0.10,
        "export_csv_session_rows_enough": 0.10,
        "summary_json_valid": 0.10,
        "summary_counts_match": 0.15,
        "summary_by_event_match": 0.10,
        "report_has_sections": 0.05,
    }

    # Ensure baseline no-op: if output directory missing or empty, reward must be 0
    output_exists = os.path.isdir(output_dir) and any(os.scandir(output_dir))
    # Compute reward
    reward = 0.0
    if output_exists:
        for key, w in weights.items():
            if checks.get(key, False):
                reward += w
    else:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print results
    result_obj = {"reward": reward}
    # Add all check booleans (ensuring boolean type)
    for k, v in checks.items():
        result_obj[k] = bool(v)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()