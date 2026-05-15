import json
import os
import re
import sys
import csv

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        dicts = []
        for r in rows[1:]:
            # Normalize row length to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            if any(cell.strip() for cell in r):
                dicts.append({header[i]: r[i] for i in range(len(header))})
        return header, dicts
    except Exception:
        return None, []

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Report checks
        "report_exists": False,
        "report_sections": False,
        "report_references_inputs": False,
        # Suspicious processes checks
        "processes_exists": False,
        "processes_header": False,
        "processes_min_rows": False,
        "processes_has_injection_truthy": False,
        "processes_network_count_integers": False,
        # IOCs checks
        "iocs_exists": False,
        "iocs_valid_json": False,
        "iocs_min_len": False,
        "iocs_required_keys": False,
        "iocs_types_diverse": False,
        # Mock users checks
        "mock_users_exists": False,
        "mock_users_header": False,
        "mock_users_min_rows": False,
        "mock_users_ids_uuid_like": False,
        "mock_users_emails_valid": False,
        "mock_users_active_boolean": False,
        # Notes export checks
        "notes_exists": False,
        "notes_valid_json": False,
        "notes_required_keys": False,
        "notes_time_format": False,
        "notes_required_types_present": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "report", "incident_report.md")
    processes_path = os.path.join(output_dir, "findings", "suspicious_processes.csv")
    iocs_path = os.path.join(output_dir, "iocs", "indicators.json")
    mock_users_path = os.path.join(output_dir, "seed", "mock_users.csv")
    notes_export_path = os.path.join(output_dir, "notes", "export.json")

    # 1) Report validations
    report_text = read_file_text(report_path)
    if report_text is not None:
        checks["report_exists"] = True
        lower_text = report_text.lower()

        # Required sections: Hypotheses, Analysis, (Audit or Auditing), Adversarial Verification, Synthesis,
        # and mentions "Indicators of Compromise" or "IOCs"
        required_sections = [
            ("hypotheses", None),
            ("analysis", None),
            ("adversarial verification", None),
            ("synthesis", None),
        ]
        has_audit = ("audit" in lower_text) or ("auditing" in lower_text)
        has_iocs_section = ("indicators of compromise" in lower_text) or ("iocs" in lower_text)

        has_required_basic = all(s in lower_text for (s, _) in required_sections)
        checks["report_sections"] = bool(has_required_basic and has_audit and has_iocs_section)

        # Must reference each input file name at least once
        input_filenames = [
            "memory_pslist.csv",
            "memory_netscan.csv",
            "memory_malfind.txt",
            "yara_hits.json",
            "case_brief.md",
        ]
        checks["report_references_inputs"] = all(fn.lower() in lower_text for fn in input_filenames)

    # 2) Suspicious processes CSV validations
    header, rows = (None, [])
    if os.path.isfile(processes_path):
        checks["processes_exists"] = True
        header, rows = load_csv_dicts(processes_path)
        expected_header = ["pid", "name", "detection_sources", "has_injection", "network_endpoints_count", "notes"]
        if header == expected_header:
            checks["processes_header"] = True

        # at least 3 data rows
        if len(rows) >= 3:
            checks["processes_min_rows"] = True

        # at least one row where has_injection is truthy ("true","yes","1" case-insensitive)
        truthy_values = {"true", "yes", "1"}
        has_truthy = False
        net_counts_all_int = True

        for r in rows:
            val = r.get("has_injection", "")
            if isinstance(val, str) and val.strip().lower() in truthy_values:
                has_truthy = True
            net_val = r.get("network_endpoints_count", "")
            try:
                _ = int(str(net_val).strip())
            except Exception:
                net_counts_all_int = False

        checks["processes_has_injection_truthy"] = has_truthy
        checks["processes_network_count_integers"] = net_counts_all_int

    # 3) IOCs JSON validations
    iocs = None
    if os.path.isfile(iocs_path):
        checks["iocs_exists"] = True
        iocs = load_json(iocs_path)
        if isinstance(iocs, list):
            checks["iocs_valid_json"] = True
            if len(iocs) >= 12:
                checks["iocs_min_len"] = True
            # Every object contains keys: type, value, source, confidence
            required_keys = {"type", "value", "source", "confidence"}
            has_all_keys = True
            types_set = set()
            for item in iocs:
                if not isinstance(item, dict):
                    has_all_keys = False
                    break
                if not required_keys.issubset(item.keys()):
                    has_all_keys = False
                    break
                t = str(item.get("type", "")).lower()
                types_set.add(t)
            checks["iocs_required_keys"] = has_all_keys
            allowed_types = {"domain", "ip", "hash", "registry", "mutex", "path"}
            types_diverse_count = len(types_set.intersection(allowed_types))
            checks["iocs_types_diverse"] = types_diverse_count >= 3

    # 4) Mock users CSV validations
    mu_header, mu_rows = (None, [])
    if os.path.isfile(mock_users_path):
        checks["mock_users_exists"] = True
        mu_header, mu_rows = load_csv_dicts(mock_users_path)
        expected_mu_header = ["id", "name", "email", "phone", "address", "company", "created_at", "active"]
        if mu_header == expected_mu_header:
            checks["mock_users_header"] = True
        if len(mu_rows) >= 50:
            checks["mock_users_min_rows"] = True

        # id looks like UUIDs: regex [0-9a-fA-F-]{36}
        uuid_like = True
        email_valid = True
        active_valid = True
        uuid_re = re.compile(r"^[0-9a-fA-F-]{36}$")
        valid_active_vals = {"true", "false", "0", "1"}
        for r in mu_rows:
            idv = str(r.get("id", "")).strip()
            emailv = str(r.get("email", "")).strip()
            activev = str(r.get("active", "")).strip().lower()
            if not uuid_re.fullmatch(idv):
                uuid_like = False
            if "@" not in emailv:
                email_valid = False
            if activev not in valid_active_vals:
                active_valid = False
            # Early break if all failed already to save time
            if not uuid_like and not email_valid and not active_valid:
                # continue scanning could be unnecessary, but we can break
                pass
        checks["mock_users_ids_uuid_like"] = uuid_like
        checks["mock_users_emails_valid"] = email_valid
        checks["mock_users_active_boolean"] = active_valid

    # 5) Notes export JSON validations
    notes = None
    if os.path.isfile(notes_export_path):
        checks["notes_exists"] = True
        notes = load_json(notes_export_path)
        if isinstance(notes, list):
            checks["notes_valid_json"] = True
            # Each object with keys: type, time, value
            has_keys = True
            time_fmt_ok = True
            time_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
            types_present = set()
            for item in notes:
                if not isinstance(item, dict):
                    has_keys = False
                    time_fmt_ok = False
                    break
                if not {"type", "time", "value"}.issubset(item.keys()):
                    has_keys = False
                tval = str(item.get("time", ""))
                if not time_re.fullmatch(tval):
                    time_fmt_ok = False
                types_present.add(str(item.get("type", "")))
            checks["notes_required_keys"] = has_keys
            checks["notes_time_format"] = time_fmt_ok
            required_types = {"add", "plan", "track", "review", "streak", "remind", "prioritize", "tag", "timeline", "report", "weekly-review"}
            checks["notes_required_types_present"] = required_types.issubset(types_present)

    # Compute reward
    # Group weights: report 0.2, processes 0.2, iocs 0.2, mock users 0.2, notes 0.2
    weights = {
        # Report (0.2 total)
        "report_exists": 0.2/3.0,
        "report_sections": 0.2/3.0,
        "report_references_inputs": 0.2/3.0,
        # Processes (0.2 total across 5)
        "processes_exists": 0.2/5.0,
        "processes_header": 0.2/5.0,
        "processes_min_rows": 0.2/5.0,
        "processes_has_injection_truthy": 0.2/5.0,
        "processes_network_count_integers": 0.2/5.0,
        # IOCs (0.2 total across 5)
        "iocs_exists": 0.2/5.0,
        "iocs_valid_json": 0.2/5.0,
        "iocs_min_len": 0.2/5.0,
        "iocs_required_keys": 0.2/5.0,
        "iocs_types_diverse": 0.2/5.0,
        # Mock users (0.2 total across 6)
        "mock_users_exists": 0.2/6.0,
        "mock_users_header": 0.2/6.0,
        "mock_users_min_rows": 0.2/6.0,
        "mock_users_ids_uuid_like": 0.2/6.0,
        "mock_users_emails_valid": 0.2/6.0,
        "mock_users_active_boolean": 0.2/6.0,
        # Notes export (0.2 total across 5)
        "notes_exists": 0.2/5.0,
        "notes_valid_json": 0.2/5.0,
        "notes_required_keys": 0.2/5.0,
        "notes_time_format": 0.2/5.0,
        "notes_required_types_present": 0.2/5.0,
    }

    reward = 0.0
    for k, passed in checks.items():
        if passed:
            reward += weights.get(k, 0.0)

    # Clamp to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()