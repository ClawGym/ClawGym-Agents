import json
import os
import sys
import re
import csv

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def recursive_keys_include_value(obj):
    # Returns True if any dict key exactly equals 'value' at any depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "value":
                return True
            if recursive_keys_include_value(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if recursive_keys_include_value(item):
                return True
    return False

def collect_all_strings(obj):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                results.append(k)
            results.extend(collect_all_strings(v))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(collect_all_strings(item))
    elif isinstance(obj, str):
        results.append(obj)
    return results

def has_substring_in_obj(obj, substrings):
    # substrings: list of substrings; return True if all substrings found (case-insensitive)
    strings = collect_all_strings(obj)
    lower_strings = [s.lower() for s in strings]
    def contains(sub):
        sub_l = sub.lower()
        return any(sub_l in s for s in lower_strings)
    return all(contains(s) for s in substrings)

def has_any_substring_in_obj(obj, substrings):
    strings = collect_all_strings(obj)
    lower_strings = [s.lower() for s in strings]
    for sub in substrings:
        sub_l = sub.lower()
        if any(sub_l in s for s in lower_strings):
            return True
    return False

def is_iso8601_like(s):
    if not isinstance(s, str) or not s.strip():
        return False
    # Simple ISO-8601-like check: YYYY-MM-DDTHH:MM:SS, optionally with timezone or fractional seconds
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    return re.match(pattern, s) is not None

def validate_findings_csv(path, allowed_files):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return False, False, False
    header_ok = False
    rows_ok = False
    files_covered = False

    if rows and rows[0] == ["file", "critical_count", "high_count", "medium_count", "low_count"]:
        header_ok = True
    # Expect exactly 4 data rows (one per allowed file)
    data_rows = rows[1:] if len(rows) > 1 else []
    if len(data_rows) == 4:
        # Validate each row file and numeric counts
        seen = set()
        all_valid = True
        for r in data_rows:
            if len(r) != 5:
                all_valid = False
                break
            fpath = r[0]
            if fpath not in allowed_files:
                all_valid = False
                break
            if fpath in seen:
                all_valid = False
                break
            seen.add(fpath)
            # numeric checks
            for val in r[1:]:
                try:
                    int(val)
                except Exception:
                    all_valid = False
                    break
            if not all_valid:
                break
        rows_ok = all_valid
        files_covered = all_valid and (seen == set(allowed_files))
    else:
        rows_ok = False
        files_covered = False
    return header_ok, rows_ok, files_covered

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Allowed input files
    allowed_files = [
        "input/cloudformation.yaml",
        "input/terraform_hcl.txt",
        "input/lambda_env.json",
        "input/ecs_task_env.json",
    ]

    checks = {
        "has_security_report_json": False,
        "security_report_top_keys": False,
        "critical_findings_basic": False,
        "findings_table_nonempty_min3": False,
        "findings_table_items_valid": False,
        "findings_severity_has_high_or_critical": False,
        "no_value_keys_in_report": False,
        "migration_plan_sections_and_secrets_ref": False,
        "git_remediation_commands_present": False,
        "prevention_mentions_precommit_and_ci": False,
        "has_findings_csv": False,
        "findings_csv_header_ok": False,
        "findings_csv_rows_for_all_inputs": False,
        "has_scan_manifest_json": False,
        "scan_manifest_structure_ok": False,
        "scan_manifest_patterns_nonempty": False,
        "scan_manifest_timestamp_iso": False,
        "scan_manifest_lists_all_files": False,
    }

    # Paths
    security_report_path = os.path.join(output_dir, "security_report.json")
    findings_csv_path = os.path.join(output_dir, "findings.csv")
    scan_manifest_path = os.path.join(output_dir, "scan_manifest.json")

    # Load security_report.json
    security_report, sr_error = (None, None)
    if os.path.isfile(security_report_path):
        security_report, sr_error = load_json_file(security_report_path)
        if isinstance(security_report, dict):
            checks["has_security_report_json"] = True

    if checks["has_security_report_json"]:
        # Top-level keys presence
        required_top_keys = ["critical_findings", "findings_table", "migration_plan", "git_remediation", "prevention"]
        if all(k in security_report for k in required_top_keys):
            checks["security_report_top_keys"] = True

        # Critical findings basic check: array and entries reference input/ paths
        cf = security_report.get("critical_findings")
        if isinstance(cf, list) and len(cf) >= 0:
            # If non-empty, ensure entries contain "input/"
            if len(cf) == 0:
                # Allow empty but still pass basic structure
                checks["critical_findings_basic"] = True
            else:
                # Each element should be a string containing 'input/'
                ok_cf = True
                for el in cf:
                    if not isinstance(el, (str,)):
                        ok_cf = False
                        break
                    if "input/" not in el:
                        ok_cf = False
                        break
                if ok_cf:
                    checks["critical_findings_basic"] = True

        # Findings table checks
        ft = security_report.get("findings_table")
        if isinstance(ft, list) and len(ft) >= 3:
            checks["findings_table_nonempty_min3"] = True
            # Validate each item
            allowed_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
            items_valid = True
            has_high_or_critical = False
            for item in ft:
                if not isinstance(item, dict):
                    items_valid = False
                    break
                # required keys
                if not all(k in item for k in ["file", "line", "secret_type", "severity", "blast_radius"]):
                    items_valid = False
                    break
                # file check
                fpath = item["file"]
                if not (isinstance(fpath, str) and fpath.startswith("input/") and fpath in allowed_files):
                    items_valid = False
                    break
                # line numeric
                line = item["line"]
                try:
                    # Accept int-like
                    line_num = int(line)
                    if line_num < 1:
                        items_valid = False
                        break
                except Exception:
                    items_valid = False
                    break
                # severity
                sev = item["severity"]
                if not (isinstance(sev, str) and sev in allowed_severities):
                    items_valid = False
                    break
                if sev in {"CRITICAL", "HIGH"}:
                    has_high_or_critical = True
                # secret_type and blast_radius are strings (non-empty preferred)
                if not isinstance(item["secret_type"], str) or not item["secret_type"]:
                    items_valid = False
                    break
                if not isinstance(item["blast_radius"], str) or not item["blast_radius"]:
                    items_valid = False
                    break
            if items_valid:
                checks["findings_table_items_valid"] = True
            if has_high_or_critical:
                checks["findings_severity_has_high_or_critical"] = True

        # Ensure no key named "value" appears anywhere in report
        if not recursive_keys_include_value(security_report):
            checks["no_value_keys_in_report"] = True

        # Migration plan sections: python, node, terraform and references Secrets Manager
        mp = security_report.get("migration_plan")
        if isinstance(mp, dict):
            keys_lower = {k.lower(): k for k in mp.keys()}
            has_python = any(k.lower() == "python" for k in mp.keys())
            has_node = any(k.lower() == "node" for k in mp.keys())
            has_terraform = any(k.lower() == "terraform" for k in mp.keys())
            # Reference to secrets manager in content (search strings)
            # Accept presence of "secrets" or "secrets_manager" or "secrets manager"
            secrets_ref = has_any_substring_in_obj(mp, ["secrets manager", "secrets_manager", "secrets"])
            if has_python and has_node and has_terraform and secrets_ref:
                checks["migration_plan_sections_and_secrets_ref"] = True

        # git_remediation commands present
        gr = security_report.get("git_remediation")
        if isinstance(gr, dict):
            bfg = gr.get("bfg_commands")
            gfr = gr.get("git_filter_repo_commands")
            bfg_ok = isinstance(bfg, list) and any(isinstance(x, str) and x.strip() for x in bfg)
            gfr_ok = isinstance(gfr, list) and any(isinstance(x, str) and x.strip() for x in gfr)
            if bfg_ok or gfr_ok:
                checks["git_remediation_commands_present"] = True

        # prevention mentions pre-commit and CI detector (e.g., CodeGuru or secrets detector)
        prev = security_report.get("prevention")
        if isinstance(prev, (dict, list, str)):
            # Require "pre-commit" and either "CodeGuru" or "secrets detector"
            has_precommit = has_any_substring_in_obj(prev, ["pre-commit"])
            has_ci_detector = has_any_substring_in_obj(prev, ["codeguru", "secrets detector"])
            if has_precommit and has_ci_detector:
                checks["prevention_mentions_precommit_and_ci"] = True

    # Validate findings.csv
    if os.path.isfile(findings_csv_path):
        checks["has_findings_csv"] = True
        header_ok, rows_ok, files_covered = validate_findings_csv(findings_csv_path, allowed_files)
        if header_ok:
            checks["findings_csv_header_ok"] = True
        if rows_ok and files_covered:
            checks["findings_csv_rows_for_all_inputs"] = True

    # Validate scan_manifest.json
    scan_manifest, sm_error = (None, None)
    if os.path.isfile(scan_manifest_path):
        checks["has_scan_manifest_json"] = True
        scan_manifest, sm_error = load_json_file(scan_manifest_path)
        if isinstance(scan_manifest, dict):
            # structure
            if all(k in scan_manifest for k in ["files", "patterns", "timestamp"]):
                checks["scan_manifest_structure_ok"] = True
            # patterns non-empty (array or object)
            patterns = scan_manifest.get("patterns")
            if (isinstance(patterns, list) and len(patterns) > 0) or (isinstance(patterns, dict) and len(patterns.keys()) > 0):
                checks["scan_manifest_patterns_nonempty"] = True
            # timestamp iso-like
            ts = scan_manifest.get("timestamp")
            if is_iso8601_like(ts):
                checks["scan_manifest_timestamp_iso"] = True
            # files list contains all four allowed files (paths must start with input/)
            files_list = scan_manifest.get("files")
            if isinstance(files_list, list):
                files_norm = [f for f in files_list if isinstance(f, str) and f.startswith("input/")]
                if all(af in files_norm for af in allowed_files):
                    checks["scan_manifest_lists_all_files"] = True

    # Compute reward
    # Enforce baseline: if any required artifact missing, reward must be 0.0
    required_exist = checks["has_security_report_json"] and checks["has_findings_csv"] and checks["has_scan_manifest_json"]
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_exist:
        reward = 0.0
    else:
        # Fraction of checks passed
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp to [0,1]
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    # Output single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()