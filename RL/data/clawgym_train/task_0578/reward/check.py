import json
import os
import sys
import csv
import re

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for r in reader:
                rows.append(r)
        return rows
    except Exception:
        return None

def is_int_string(s):
    try:
        int(s)
        return True
    except Exception:
        return False

def is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def to_candidate_filter_strings(threshold):
    candidates = set()
    if isinstance(threshold, int):
        candidates.add(f"speed>={threshold}")
    elif isinstance(threshold, float):
        # Primary normalized float without unnecessary trailing zeros
        norm = format(threshold, ".15g")
        candidates.add(f"speed>={norm}")
        # If it is an integer value float, add integer form too
        if float(int(threshold)) == float(threshold):
            candidates.add(f"speed>={int(threshold)}")
        # Also add a simple one-decimal representation if it ends with .0 in many generators
        candidates.add(f"speed>={threshold}")
    else:
        candidates.add(f"speed>={str(threshold)}")
    return candidates

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_summary_csv": False,
        "summary_header_ok": False,
        "summary_two_rows": False,
        "summary_integer_columns": False,
        "summary_final_source_standings": False,

        "has_report_json": False,
        "report_has_required_keys": False,
        "report_config_valid": False,
        "report_session_valid": False,
        "report_filters_contains_threshold": False,
        "report_drivers_valid": False,
        "report_weather_rules_ok": False,

        "cross_driver_set_match": False,

        "has_provenance_md": False,
        "provenance_min_commands": False,
        "provenance_includes_required_commands": False,
        "provenance_has_gotchas": False,
    }

    # Paths
    summary_path = os.path.join(output_dir, "summary.csv")
    report_path = os.path.join(output_dir, "report.json")
    provenance_path = os.path.join(output_dir, "provenance.md")

    # Parse summary.csv
    summary_rows = None
    if os.path.isfile(summary_path):
        checks["has_summary_csv"] = True
        summary_rows = parse_csv(summary_path)

    summary_drivers_set = set()
    if checks["has_summary_csv"] and summary_rows is not None and len(summary_rows) >= 1:
        header = summary_rows[0]
        expected_header = ["driver", "final_position_source", "pit_stop_count", "stint_count", "speed_ge_threshold_count"]
        if header == expected_header:
            checks["summary_header_ok"] = True

        data_rows = summary_rows[1:] if len(summary_rows) > 1 else []
        if len(data_rows) == 2:
            checks["summary_two_rows"] = True

        # Validate integer columns and final_position_source
        all_int_cols_ok = True
        all_final_src_ok = True
        for r in data_rows:
            # Ensure row length is exactly 5
            if len(r) != 5:
                all_int_cols_ok = False
                all_final_src_ok = False
                continue
            # Collect driver
            summary_drivers_set.add(r[0])
            # Check final_position_source
            if r[1] != "standings":
                all_final_src_ok = False
            # Check integer columns: indexes 2,3,4
            for idx in [2, 3, 4]:
                if not is_int_string(r[idx]):
                    all_int_cols_ok = False
        if data_rows:
            checks["summary_integer_columns"] = all_int_cols_ok
            checks["summary_final_source_standings"] = all_final_src_ok

    # Parse report.json
    report = None
    if os.path.isfile(report_path):
        report = load_json_file(report_path)
        if isinstance(report, dict):
            checks["has_report_json"] = True

    config_drivers_set = set()
    speed_threshold_value = None
    include_weather_value = None

    if checks["has_report_json"]:
        # Required keys
        required_keys = {"config", "session", "filters", "drivers"}
        if all(k in report for k in required_keys):
            checks["report_has_required_keys"] = True

        # Validate config
        config_ok = False
        if isinstance(report.get("config"), dict):
            cfg = report["config"]
            drivers = cfg.get("drivers")
            speed_threshold = cfg.get("speed_threshold")
            include_weather = cfg.get("include_weather")
            drivers_ok = isinstance(drivers, list) and len(drivers) == 2 and all(isinstance(d, str) for d in drivers)
            if drivers_ok:
                # Check each driver is 3-letter uppercase string
                regex = re.compile(r"^[A-Z]{3}$")
                drivers_ok = all(bool(regex.match(d)) for d in drivers)
            st_ok = is_number(speed_threshold)
            iw_ok = isinstance(include_weather, bool)
            if drivers_ok and st_ok and iw_ok:
                config_ok = True
                config_drivers_set = set(drivers)
                speed_threshold_value = speed_threshold
                include_weather_value = include_weather
        checks["report_config_valid"] = config_ok

        # Validate session
        session_ok = False
        session = report.get("session")
        if isinstance(session, dict):
            has_key = "key" in session
            has_source = "source" in session and session["source"] in ("latest", "fallback")
            # key can be string or number
            key_val = session.get("key", None)
            key_ok = isinstance(key_val, (str, int, float))
            session_ok = has_key and has_source and key_ok
        checks["report_session_valid"] = session_ok

        # Validate filters contains the speed filter
        filters_ok = False
        filters = report.get("filters")
        if isinstance(filters, list) and speed_threshold_value is not None:
            candidates = to_candidate_filter_strings(speed_threshold_value)
            filters_ok = any(isinstance(f, str) and f in candidates for f in filters)
        checks["report_filters_contains_threshold"] = filters_ok

        # Validate drivers array details
        drivers_ok = False
        drivers_arr = report.get("drivers")
        if isinstance(drivers_arr, list) and len(drivers_arr) == 2 and speed_threshold_value is not None and isinstance(report.get("config"), dict):
            per_ok = True
            for item in drivers_arr:
                if not isinstance(item, dict):
                    per_ok = False
                    break
                code = item.get("code")
                fps = item.get("final_position_source")
                pit_cnt = item.get("pit_stop_count")
                stint_cnt = item.get("stint_count")
                max_thr = item.get("max_speed_threshold")
                notes = item.get("notes")

                if not (isinstance(code, str) and code in config_drivers_set):
                    per_ok = False
                    break
                if fps != "standings":
                    per_ok = False
                    break
                if not is_number(pit_cnt):
                    per_ok = False
                    break
                if not is_number(stint_cnt):
                    per_ok = False
                    break
                if not (isinstance(max_thr, dict) and "threshold" in max_thr and "count" in max_thr and is_number(max_thr["count"])):
                    per_ok = False
                    break
                # Threshold equality check (numeric equality)
                thr_val = max_thr.get("threshold")
                if not (is_number(thr_val) and float(thr_val) == float(speed_threshold_value)):
                    per_ok = False
                    break
                if not isinstance(notes, str):
                    per_ok = False
                    break
            drivers_ok = per_ok
        checks["report_drivers_valid"] = drivers_ok

        # Weather rules
        weather_ok = False
        if include_weather_value is True:
            ws = report.get("weather_summary", None)
            if isinstance(ws, str) and ws.strip() != "":
                weather_ok = True
        elif include_weather_value is False:
            # Must not include weather_summary
            weather_ok = "weather_summary" not in report
        checks["report_weather_rules_ok"] = weather_ok

    # Cross-file driver set match
    if checks["summary_header_ok"] and checks["summary_two_rows"] and checks["report_config_valid"]:
        if summary_drivers_set and config_drivers_set and summary_drivers_set == config_drivers_set:
            checks["cross_driver_set_match"] = True

    # provenance.md checks
    prov_text = None
    if os.path.isfile(provenance_path):
        checks["has_provenance_md"] = True
        prov_text = read_text(provenance_path)

    if checks["has_provenance_md"] and isinstance(prov_text, str):
        lines = [ln.rstrip("\n") for ln in prov_text.splitlines()]
        cmd_lines = [ln for ln in lines if ln.lstrip().startswith("COMMAND:")]
        if len(cmd_lines) >= 4:
            checks["provenance_min_commands"] = True

        # Required command substrings
        joined_cmds_lower = "\n".join(cmd_lines).lower()
        has_standings = "standings drivers" in joined_cmds_lower
        has_stints = "stints" in joined_cmds_lower
        has_pit = "pit" in joined_cmds_lower
        has_filter = "--filter" in joined_cmds_lower
        checks["provenance_includes_required_commands"] = all([has_standings, has_stints, has_pit, has_filter])

        # Gotchas section and phrases
        prov_lower = prov_text.lower()
        has_gotchas = "gotchas" in prov_lower
        has_limit_phrase = "limit is client-side" in prov_lower
        has_positions_phrase = "positions is a time series" in prov_lower
        checks["provenance_has_gotchas"] = has_gotchas and has_limit_phrase and has_positions_phrase

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Baseline: if no artifacts exist under output, reward must be 0.0
    output_exists = os.path.isdir(output_dir) and any(
        os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir)
    )
    if not output_exists:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward in [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()