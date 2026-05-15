import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_simple_yaml_kv(path, expected_keys):
    """
    Minimal YAML parser for top-level key: value pairs.
    Returns dict of expected_keys mapped to their string values if found.
    Ignores comments and blank lines.
    """
    result = {}
    text = read_text(path)
    if text is None:
        return result
    for line in text.splitlines():
        # Remove comments
        line_no_comment = line.split("#", 1)[0]
        if not line_no_comment.strip():
            continue
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$', line_no_comment)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2)
        # Strip surrounding quotes if any
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key in expected_keys:
            result[key] = str(val)
    return result

def is_nonneg_int(v):
    return isinstance(v, int) and v >= 0

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def count_bullet_lines(md_text):
    count = 0
    for line in md_text.splitlines():
        if line.lstrip().startswith("- ") or line.lstrip().startswith("* "):
            count += 1
    return count

def last_non_empty_print(obj):
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "diagnostics_exists": False,
        "diagnostics_has_required_keys": False,
        "diagnostics_counts_valid": False,
        "rules_values_copied": False,
        "incidents_exists_and_header": False,
        "incidents_ids_and_status_valid": False,
        "incidents_count_matches_diagnostics": False,
        "diagnoses_totals_match_incidents": False,
        "resolution_counts_match": False,
        "recommendations_exists_and_summary": False,
        "recommendations_min_bullets": False,
        "recommendations_ws_phrase": False,           # conditional
        "recommendations_caffeinate_phrase": False,   # conditional
        "recommendations_critical_phrase": False      # conditional
    }

    # Paths
    diag_path = os.path.join(output_dir, "diagnostics.json")
    incidents_path = os.path.join(output_dir, "incidents.csv")
    rec_path = os.path.join(output_dir, "recommendations.md")
    rules_yaml_path = os.path.join(input_dir, "health_rules.yaml")

    diagnostics = load_json(diag_path)
    if diagnostics is not None:
        checks["diagnostics_exists"] = True

    # Validate diagnostics.json required keys and structure
    required_top_keys = [
        "first_log_timestamp",
        "last_log_timestamp",
        "heartbeat_count",
        "alert_count",
        "resolved_count",
        "critical_count",
        "incident_count",
        "diagnoses",
        "actions",
        "caffeinate_runs",
        "rules"
    ]
    required_diag_codes = ["PROCESS_DOWN", "HTTP_UNREACHABLE", "WS_FREQUENT_DISCONNECT"]
    required_action_names = ["Restarting gateway", "Restarting node"]
    rules_required_keys = ["ws_disconnect_threshold", "heartbeat_window_minutes"]

    if diagnostics is not None:
        has_keys = all(k in diagnostics for k in required_top_keys)
        # Check nested keys
        diag_diag_ok = isinstance(diagnostics.get("diagnoses"), dict) and all(code in diagnostics.get("diagnoses", {}) for code in required_diag_codes)
        diag_actions_ok = isinstance(diagnostics.get("actions"), dict) and all(an in diagnostics.get("actions", {}) for an in required_action_names)
        diag_rules_ok = isinstance(diagnostics.get("rules"), dict) and all(rk in diagnostics.get("rules", {}) for rk in rules_required_keys)
        checks["diagnostics_has_required_keys"] = bool(has_keys and diag_diag_ok and diag_actions_ok and diag_rules_ok)

        # Check counts are non-negative integers
        counts_ok = True
        for k in ["heartbeat_count", "alert_count", "resolved_count", "critical_count", "incident_count", "caffeinate_runs"]:
            if not is_nonneg_int(diagnostics.get(k, None)):
                counts_ok = False
                break
        # Nested counts for diagnoses/actions should be non-negative integers
        if counts_ok:
            for code in required_diag_codes:
                if not is_nonneg_int(diagnostics["diagnoses"].get(code, None)):
                    counts_ok = False
                    break
        if counts_ok:
            for an in required_action_names:
                if not is_nonneg_int(diagnostics["actions"].get(an, None)):
                    counts_ok = False
                    break
        checks["diagnostics_counts_valid"] = counts_ok

        # Compare rules to YAML input values
        yaml_vals = parse_simple_yaml_kv(rules_yaml_path, set(rules_required_keys))
        rules_ok = True
        for rk in rules_required_keys:
            # YAML must have these keys to verify; otherwise fail
            if rk not in yaml_vals:
                rules_ok = False
                break
            # Compare as string for robustness
            diag_val = diagnostics["rules"].get(rk, None)
            if diag_val is None:
                rules_ok = False
                break
            if str(diag_val) != str(yaml_vals[rk]):
                rules_ok = False
                break
        checks["rules_values_copied"] = rules_ok

    # Validate incidents.csv
    rows = read_csv_rows(incidents_path)
    incidents_data_rows = []
    if rows is not None and len(rows) >= 1:
        header = rows[0]
        expected_header = ["incident_id", "start_timestamp", "end_timestamp", "issue_codes", "actions_taken", "resolution_status"]
        if header == expected_header:
            checks["incidents_exists_and_header"] = True
            incidents_data_rows = rows[1:]
        else:
            checks["incidents_exists_and_header"] = False

    # Validate ids sequential and statuses and simple actions_taken format
    ids_status_ok = False
    if checks["incidents_exists_and_header"]:
        ids_ok = True
        status_ok = True
        actions_format_ok = True
        allowed_status = {"RESOLVED", "CRITICAL", "UNKNOWN"}
        expected_id = 1
        for r in incidents_data_rows:
            if len(r) != 6:
                ids_ok = False
                status_ok = False
                actions_format_ok = False
                break
            # incident_id sequential integer starting at 1
            try:
                inc_id = int(r[0].strip())
                if inc_id != expected_id:
                    ids_ok = False
                expected_id += 1
                if inc_id < 1:
                    ids_ok = False
            except Exception:
                ids_ok = False
            # resolution_status validity
            if r[5].strip() not in allowed_status:
                status_ok = False
            # actions_taken semicolon-separated or empty (basic check: no commas)
            actions_field = r[4].strip()
            if "," in actions_field:
                actions_format_ok = False
        ids_status_ok = ids_ok and status_ok and actions_format_ok
        checks["incidents_ids_and_status_valid"] = ids_status_ok

    # Cross-file consistency checks
    if diagnostics is not None and checks["incidents_exists_and_header"]:
        # incident_count matches number of rows
        checks["incidents_count_matches_diagnostics"] = (diagnostics.get("incident_count") == len(incidents_data_rows))

        # diagnoses totals across incidents
        code_counts_from_csv = {c: 0 for c in required_diag_codes}
        for r in incidents_data_rows:
            issue_codes_field = r[3].strip()
            if issue_codes_field:
                parts = [p.strip() for p in issue_codes_field.split("+") if p.strip()]
                for p in parts:
                    if p in code_counts_from_csv:
                        code_counts_from_csv[p] += 1
        diag_match = True
        for c in required_diag_codes:
            if diagnostics.get("diagnoses", {}).get(c) != code_counts_from_csv.get(c, 0):
                diag_match = False
                break
        checks["diagnoses_totals_match_incidents"] = diag_match

        # resolution counts match
        res_counts = {"RESOLVED": 0, "CRITICAL": 0}
        for r in incidents_data_rows:
            status = r[5].strip()
            if status in res_counts:
                res_counts[status] += 1
        res_ok = True
        if diagnostics.get("resolved_count") != res_counts["RESOLVED"]:
            res_ok = False
        if diagnostics.get("critical_count") != res_counts["CRITICAL"]:
            res_ok = False
        checks["resolution_counts_match"] = res_ok

    # recommendations.md checks
    rec_text = read_text(rec_path)
    if rec_text is not None:
        # Must begin with a line starting with "Summary:"
        first_line = rec_text.splitlines()[0] if rec_text.splitlines() else ""
        if first_line.startswith("Summary:"):
            checks["recommendations_exists_and_summary"] = True
        # At least 5 bullet lines
        if count_bullet_lines(rec_text) >= 5:
            checks["recommendations_min_bullets"] = True

        # Conditional phrases based on diagnostics
        if diagnostics is not None:
            ws_count = diagnostics.get("diagnoses", {}).get("WS_FREQUENT_DISCONNECT")
            if isinstance(ws_count, int) and ws_count > 0:
                # exact phrase "restart Node first"
                if "restart Node first" in rec_text:
                    checks["recommendations_ws_phrase"] = True
            else:
                # Not required, consider as passed when not applicable
                checks["recommendations_ws_phrase"] = True

            caff_runs = diagnostics.get("caffeinate_runs")
            if isinstance(caff_runs, int) and caff_runs == 0:
                # at least one line (not necessarily bullet in spec, but we check any line) containing both substrings
                found = False
                for line in rec_text.splitlines():
                    if ("prevent sleep" in line.lower()) and ("caffeinate" in line.lower()):
                        found = True
                        break
                checks["recommendations_caffeinate_phrase"] = found
            else:
                checks["recommendations_caffeinate_phrase"] = True

            crit_count = diagnostics.get("critical_count")
            if isinstance(crit_count, int) and crit_count > 0:
                found = False
                for line in rec_text.splitlines():
                    if ("manual investigation" in line.lower()) and ("service plist" in line.lower()):
                        found = True
                        break
                checks["recommendations_critical_phrase"] = found
            else:
                checks["recommendations_critical_phrase"] = True

    # Compute reward
    # Only count conditional recommendation checks if diagnostics exists and recommendations exist
    # But above we already set them to True if not applicable; if diagnostics missing, they remain False.
    total_checks = 0
    passed_checks = 0
    for k, v in checks.items():
        total_checks += 1
        if v:
            passed_checks += 1

    # Ensure no-op baseline: if output dir missing or all three required files missing, reward 0.0
    required_files_exist = os.path.isfile(diag_path) and os.path.isfile(incidents_path) and os.path.isfile(rec_path)
    if total_checks == 0:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
    # If none of the required artifacts exist, force reward to 0.0
    if not required_files_exist:
        # Additionally, if output directory does not exist or is empty, also force 0
        reward = 0.0

    # Bound reward between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    last_non_empty_print(result)

if __name__ == "__main__":
    main()