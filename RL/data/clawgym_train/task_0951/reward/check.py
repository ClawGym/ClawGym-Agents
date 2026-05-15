import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_lower_hex_64(s):
    return isinstance(s, str) and re.fullmatch(r"[0-9a-f]{64}", s) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "shield-report.json")
    audit_path = os.path.join(output_dir, "shield-audit.jsonl")

    # Initialize checks with explicit False to avoid vacuous pass
    checks = {
        "report_file_exists": False,
        "report_json_valid": False,
        "scanned_path_correct": False,
        "findings_list_present": False,
        "findings_exactly_three": False,
        "finding_steal_keys_correct": False,
        "finding_exfiltrate_correct": False,
        "finding_destroy_correct": False,
        "pattern_and_line_valid_all": False,
        "severities_correct": False,
        "summary_totals_correct": False,
        "no_safe_tool_flagged": False,
        "audit_file_exists": False,
        "audit_lines_json_valid": False,
        "audit_events_sequence_correct": False,
        "audit_indices_chain_valid": False,
        "audit_hash_chain_valid": False,
        "audit_finding_files_match_report": False,
    }

    report_data = None
    findings = []
    # Expected files from task
    expected_files = {
        "credential_access": "input/project/steal_keys.py",
        "data_exfiltration": "input/project/exfiltrate.py",
        "destructive_operation": "input/project/destroy.py",
    }

    # Load and validate report
    if os.path.isfile(report_path):
        checks["report_file_exists"] = True
        report_data, err = load_json(report_path)
        if isinstance(report_data, dict):
            checks["report_json_valid"] = True

            # scanned_path
            if report_data.get("scanned_path") == "input/project":
                checks["scanned_path_correct"] = True

            # findings list presence
            f_list = report_data.get("findings")
            if isinstance(f_list, list):
                findings = f_list
                checks["findings_list_present"] = True

                # exactly three findings
                if len(findings) == 3:
                    checks["findings_exactly_three"] = True

                # Verify each finding has required keys and types
                all_pattern_line_ok = True
                severities_ok = True
                # map to check specific findings
                has_steal = False
                has_exfil = False
                has_destroy = False

                for f in findings:
                    if not isinstance(f, dict):
                        all_pattern_line_ok = False
                        severities_ok = False
                        continue
                    file_path = f.get("file")
                    ftype = f.get("type")
                    pattern = f.get("pattern")
                    severity = f.get("severity")
                    line = f.get("line")

                    # pattern non-empty string and line positive int
                    if not (isinstance(pattern, str) and pattern.strip() and isinstance(line, int) and line > 0):
                        all_pattern_line_ok = False

                    # severity mapping per type
                    expected_sev = None
                    if ftype == "credential_access":
                        expected_sev = "medium"
                    elif ftype == "data_exfiltration":
                        expected_sev = "high"
                    elif ftype == "destructive_operation":
                        expected_sev = "high"
                    else:
                        # unknown type; consider severity wrong
                        severities_ok = False
                    if expected_sev is not None and severity != expected_sev:
                        severities_ok = False

                    # Check specific expected findings
                    if file_path == expected_files["credential_access"] and ftype == "credential_access" and severity == "medium":
                        has_steal = True
                    if file_path == expected_files["data_exfiltration"] and ftype == "data_exfiltration" and severity == "high":
                        has_exfil = True
                    if file_path == expected_files["destructive_operation"] and ftype == "destructive_operation" and severity == "high":
                        has_destroy = True

                if all_pattern_line_ok and len(findings) > 0:
                    checks["pattern_and_line_valid_all"] = True
                if severities_ok and len(findings) > 0:
                    checks["severities_correct"] = True
                if has_steal:
                    checks["finding_steal_keys_correct"] = True
                if has_exfil:
                    checks["finding_exfiltrate_correct"] = True
                if has_destroy:
                    checks["finding_destroy_correct"] = True

                # Ensure safe_tool.py is not flagged
                if not any(isinstance(f, dict) and f.get("file") == "input/project/safe_tool.py" for f in findings):
                    checks["no_safe_tool_flagged"] = True

            # summary validation
            summary_ok = False
            summary = report_data.get("summary")
            if isinstance(summary, dict) and isinstance(summary.get("total_findings"), int) and isinstance(summary.get("by_type"), dict):
                by_type = summary.get("by_type")
                # exact totals required by task
                if summary.get("total_findings") == 3:
                    # compute counts from findings list if present
                    if isinstance(findings, list) and len(findings) == 3:
                        count_ca = sum(1 for f in findings if isinstance(f, dict) and f.get("type") == "credential_access")
                        count_de = sum(1 for f in findings if isinstance(f, dict) and f.get("type") == "data_exfiltration")
                        count_do = sum(1 for f in findings if isinstance(f, dict) and f.get("type") == "destructive_operation")
                        if by_type.get("credential_access") == 1 and by_type.get("data_exfiltration") == 1 and by_type.get("destructive_operation") == 1:
                            if count_ca == 1 and count_de == 1 and count_do == 1:
                                summary_ok = True
            if summary_ok:
                checks["summary_totals_correct"] = True

    # Load and validate audit log
    audit_lines = []
    if os.path.isfile(audit_path):
        checks["audit_file_exists"] = True
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                raw_lines = [ln.rstrip("\n") for ln in f.readlines()]
            # Filter out empty lines
            raw_lines = [ln for ln in raw_lines if ln.strip() != ""]
            parsed = []
            json_ok = True
            for ln in raw_lines:
                try:
                    obj = json.loads(ln)
                    if not isinstance(obj, dict):
                        json_ok = False
                        break
                    parsed.append(obj)
                except Exception:
                    json_ok = False
                    break
            if json_ok and parsed:
                audit_lines = parsed
                checks["audit_lines_json_valid"] = True
        except Exception:
            pass

    # If both report findings and audit lines exist, validate sequence and chain
    if checks["audit_lines_json_valid"]:
        # events sequence
        seq_ok = True
        idx_ok = True
        chain_ok = True
        # Must be: 1 start + N findings + 1 completed
        n_findings = len(findings) if isinstance(findings, list) else 0
        expected_len = 2 + n_findings
        if len(audit_lines) != expected_len:
            seq_ok = False
            idx_ok = False  # indices can't be correct if length not matching
            chain_ok = False
        else:
            # First line checks
            first = audit_lines[0]
            if first.get("index") != 0 or first.get("event") != "scan_started" or first.get("prev_hash") != "GENESIS":
                seq_ok = False
            if not is_lower_hex_64(first.get("hash", "")):
                chain_ok = False
            # Middle lines: finding_recorded
            for i in range(1, 1 + n_findings):
                line = audit_lines[i]
                # index strictly increasing by 1
                if line.get("index") != i:
                    idx_ok = False
                if line.get("event") != "finding_recorded":
                    seq_ok = False
                # finding lines must include file
                if "file" not in line or not isinstance(line.get("file"), str) or not line.get("file"):
                    seq_ok = False
                # prev_hash must equal previous hash
                prev = audit_lines[i - 1]
                if line.get("prev_hash") != prev.get("hash"):
                    chain_ok = False
                # hash format
                if not is_lower_hex_64(line.get("hash", "")):
                    chain_ok = False
            # Last line: scan_completed
            last = audit_lines[-1]
            if last.get("index") != expected_len - 1:
                idx_ok = False
            if last.get("event") != "scan_completed":
                seq_ok = False
            # prev_hash link from previous line
            if last.get("prev_hash") != audit_lines[-2].get("hash"):
                chain_ok = False
            if not is_lower_hex_64(last.get("hash", "")):
                chain_ok = False

        if seq_ok:
            checks["audit_events_sequence_correct"] = True
        if idx_ok:
            checks["audit_indices_chain_valid"] = True
        if chain_ok:
            checks["audit_hash_chain_valid"] = True

        # Validate that audit finding files match report finding files (set equality)
        if isinstance(findings, list) and findings:
            report_files = set(f.get("file") for f in findings if isinstance(f, dict) and isinstance(f.get("file"), str))
            audit_files = set()
            for obj in audit_lines:
                if obj.get("event") == "finding_recorded" and isinstance(obj.get("file"), str):
                    audit_files.add(obj.get("file"))
            if len(audit_files) == len(report_files) == n_findings and audit_files == report_files:
                checks["audit_finding_files_match_report"] = True

    # Compute reward as fraction of passed checks, but ensure baseline: if no outputs -> 0.0
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if any(checks[k] for k in checks):  # any passed
        reward = passed / total
    # However, enforce exactly 0.0 if output dir missing or no report and no audit
    if not os.path.isdir(output_dir) or (not checks["report_file_exists"] and not checks["audit_file_exists"]):
        reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()