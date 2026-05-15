import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "report.json")
    summary_path = os.path.join(output_dir, "summary.md")

    checks = {
        "report_exists": False,
        "report_json_valid": False,
        "report_has_top_keys": False,
        "policy_expiring_soon_int": False,
        "hosts_array_len_6": False,
        "each_host_required_fields": False,
        "valid_true_entries_have_cert_fields_and_formats": False,
        "valid_false_entries_have_null_cert_and_error": False,
        "sorting_rule_valid": False,
        "contains_bad_host_invalid_false": False,
        "summary_exists": False,
        "summary_has_total_hosts_line_with_int": False,
        "summary_has_expiring_soon_line_with_int": False,
        "summary_has_table_header": False,
        "summary_has_comparison_header": False,
        "summary_has_fingerprints_changed_line": False,
        "summary_has_added_hosts_line": False,
        "summary_has_removed_hosts_line": False,
    }

    report_data = None

    # Check report.json existence and validity
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            checks["report_json_valid"] = isinstance(report_data, dict)
        except Exception:
            checks["report_json_valid"] = False

    # Validate report top-level structure
    hosts_list = []
    if checks["report_json_valid"]:
        generated_at = report_data.get("generated_at", None)
        policy = report_data.get("policy", None)
        hosts_list = report_data.get("hosts", None)

        if isinstance(generated_at, str) and generated_at.strip() != "" and isinstance(policy, dict) and isinstance(hosts_list, list):
            checks["report_has_top_keys"] = True

        exp_days = None
        if isinstance(policy, dict) and "expiring_soon_days" in policy and isinstance(policy["expiring_soon_days"], int):
            checks["policy_expiring_soon_int"] = True
            exp_days = policy["expiring_soon_days"]

        if isinstance(hosts_list, list) and len(hosts_list) == 6:
            checks["hosts_array_len_6"] = True

        # Validate per-host fields
        if isinstance(hosts_list, list):
            all_have_required = True
            valid_true_cert_ok = True
            valid_false_ok = True
            contains_bad_host_invalid_false = False

            for entry in hosts_list:
                # Required fields for every host
                required_present = (
                    isinstance(entry, dict) and
                    isinstance(entry.get("host", None), str) and
                    isinstance(entry.get("valid", None), bool) and
                    isinstance(entry.get("expiring_soon", None), bool) and
                    isinstance(entry.get("days_until_expiry", None), int) and
                    "error" in entry and isinstance(entry.get("error"), str) and
                    "certificate" in entry
                )
                if not required_present:
                    all_have_required = False

                # Check special host requirement
                if entry.get("host") == "bad.host.invalid" and entry.get("valid") is False:
                    contains_bad_host_invalid_false = True

                # For valid=true, check certificate fields/formats
                if entry.get("valid") is True:
                    cert = entry.get("certificate")
                    if not isinstance(cert, dict):
                        valid_true_cert_ok = False
                    else:
                        subj = cert.get("subject")
                        issuer = cert.get("issuer")
                        vfrom = cert.get("valid_from")
                        vto = cert.get("valid_to")
                        fp = cert.get("fingerprint_sha256")
                        sans = cert.get("subject_alt_names")
                        # Basic type checks
                        basics_ok = (
                            isinstance(subj, str) and subj.strip() != "" and
                            isinstance(issuer, str) and issuer.strip() != "" and
                            isinstance(vfrom, str) and vfrom.strip() != "" and
                            isinstance(vto, str) and vto.strip() != "" and
                            isinstance(fp, str) and
                            isinstance(sans, list)
                        )
                        if not basics_ok:
                            valid_true_cert_ok = False
                        else:
                            # fingerprint format: exactly 64 lowercase hex, no colons
                            if ":" in fp or re.fullmatch(r"[0-9a-f]{64}", fp) is None:
                                valid_true_cert_ok = False
                else:
                    # For valid=false
                    if entry.get("valid") is False:
                        cert = entry.get("certificate")
                        err = entry.get("error")
                        if cert is not None or not (isinstance(err, str) and err.strip() != ""):
                            valid_false_ok = False

            checks["each_host_required_fields"] = all_have_required
            checks["valid_true_entries_have_cert_fields_and_formats"] = valid_true_cert_ok
            checks["valid_false_entries_have_null_cert_and_error"] = valid_false_ok
            checks["contains_bad_host_invalid_false"] = contains_bad_host_invalid_false

            # Sorting rule: all valid=true before any valid=false; among valids, days_until_expiry non-decreasing
            if len(hosts_list) > 0:
                valid_seen_after_invalid = False
                invalid_started = False
                valid_days = []
                sorting_valid = True
                for entry in hosts_list:
                    v = entry.get("valid") is True
                    if not v:
                        invalid_started = True
                    if v and invalid_started:
                        valid_seen_after_invalid = True
                    if v:
                        # days_until_expiry int already checked earlier; guard anyway
                        days = entry.get("days_until_expiry")
                        if not isinstance(days, int):
                            sorting_valid = False
                        else:
                            valid_days.append(days)
                # Check no valid after invalid
                if valid_seen_after_invalid:
                    sorting_valid = False
                # Check non-decreasing order among valid entries
                if len(valid_days) >= 1 and valid_days != sorted(valid_days):
                    sorting_valid = False
                checks["sorting_rule_valid"] = sorting_valid

    # Check summary.md
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = ""

        # Total hosts line with integer
        total_hosts_line_ok = False
        expiring_soon_line_ok = False
        table_header_ok = False
        comparison_header_ok = False
        fingerprints_changed_line_ok = False
        added_hosts_line_ok = False
        removed_hosts_line_ok = False

        # Process lines
        lines = [ln.rstrip("\n") for ln in summary_text.splitlines()]
        for ln in lines:
            if ln.startswith("Total hosts:"):
                m = re.match(r"^Total hosts:\s*\d+\b", ln)
                if m:
                    total_hosts_line_ok = True
            if ln.startswith("Expiring soon:"):
                m = re.match(r"^Expiring soon:\s*\d+\b", ln)
                if m:
                    expiring_soon_line_ok = True
            if ln.startswith("## Comparison Against Previous"):
                comparison_header_ok = True
            if ln.startswith("Fingerprints changed:"):
                fingerprints_changed_line_ok = True
            if ln.startswith("Added hosts:"):
                added_hosts_line_ok = True
            if ln.startswith("Removed hosts:"):
                removed_hosts_line_ok = True

        # Table header presence (substring check)
        if "| Host | Valid | DaysUntilExpiry | ExpiringSoon |" in summary_text:
            table_header_ok = True

        checks["summary_has_total_hosts_line_with_int"] = total_hosts_line_ok
        checks["summary_has_expiring_soon_line_with_int"] = expiring_soon_line_ok
        checks["summary_has_table_header"] = table_header_ok
        checks["summary_has_comparison_header"] = comparison_header_ok
        checks["summary_has_fingerprints_changed_line"] = fingerprints_changed_line_ok
        checks["summary_has_added_hosts_line"] = added_hosts_line_ok
        checks["summary_has_removed_hosts_line"] = removed_hosts_line_ok

    # Compute reward
    # Enforce no-op baseline: if required artifacts missing, reward must be 0.0
    required_outputs_present = checks["report_exists"] and checks["summary_exists"]
    if not required_outputs_present:
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Reward is fraction of passed checks
        reward = passed / float(total) if total > 0 else 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()