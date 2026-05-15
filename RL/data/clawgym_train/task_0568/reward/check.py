import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to expected artifacts
    status_path = os.path.join(output_dir, "raw", "status.txt")
    devices_path = os.path.join(output_dir, "raw", "devices.txt")
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "report.md")
    log_path = os.path.join(output_dir, "log.txt")

    checks = {
        # Raw outputs
        "raw_status_exists": False,
        "raw_status_nonempty": False,
        "raw_devices_exists": False,
        "raw_devices_nonempty": False,

        # Summary JSON validations
        "summary_exists": False,
        "summary_json_valid": False,
        "summary_backend_state_type": False,
        "summary_hostname_type": False,
        "summary_ip_addresses_array": False,
        "summary_peer_count_int": False,
        "summary_device_count_int": False,
        "summary_offline_count_int": False,

        # Report validations
        "report_exists": False,
        "report_contains_title_phrase": False,
        "report_has_data_sources_section_and_paths": False,
        "report_has_findings_section": False,
        "report_has_recommendations_section": False,

        # Log validations
        "log_exists": False,
        "log_has_iso_date": False,
        "log_mentions_status": False,
        "log_mentions_devices": False,
    }

    # Helper: check file existence and non-empty
    def file_exists_nonempty(p):
        if os.path.isfile(p):
            try:
                return os.path.getsize(p) > 0
            except OSError:
                return False
        return False

    # Raw status
    if os.path.isfile(status_path):
        checks["raw_status_exists"] = True
        if file_exists_nonempty(status_path):
            checks["raw_status_nonempty"] = True

    # Raw devices
    if os.path.isfile(devices_path):
        checks["raw_devices_exists"] = True
        if file_exists_nonempty(devices_path):
            checks["raw_devices_nonempty"] = True

    # Summary JSON
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["summary_json_valid"] = True

            # backend_state: string
            if isinstance(data.get("backend_state"), str):
                checks["summary_backend_state_type"] = True

            # hostname: string
            if isinstance(data.get("hostname"), str):
                checks["summary_hostname_type"] = True

            # ip_addresses: list of strings
            ip_addrs = data.get("ip_addresses")
            if isinstance(ip_addrs, list) and all(isinstance(x, str) for x in ip_addrs):
                checks["summary_ip_addresses_array"] = True

            # peer_count: int >= 0
            peer_count = data.get("peer_count")
            if isinstance(peer_count, int) and peer_count >= 0:
                checks["summary_peer_count_int"] = True

            # device_count: int >= 0
            device_count = data.get("device_count")
            if isinstance(device_count, int) and device_count >= 0:
                checks["summary_device_count_int"] = True

            # offline_count: int >= 0
            offline_count = data.get("offline_count")
            if isinstance(offline_count, int) and offline_count >= 0:
                checks["summary_offline_count_int"] = True

        except Exception:
            # Leave summary-related checks as False
            pass

    # Report validations
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()

            # Exact phrase
            if "Zero Trust Mesh Network" in report_content:
                checks["report_contains_title_phrase"] = True

            # Data Sources section and both paths
            has_data_sources = "Data Sources" in report_content
            mentions_status = "output/raw/status.txt" in report_content
            mentions_devices = "output/raw/devices.txt" in report_content
            if has_data_sources and mentions_status and mentions_devices:
                checks["report_has_data_sources_section_and_paths"] = True

            # Findings section
            if "Findings" in report_content:
                checks["report_has_findings_section"] = True

            # Recommendations section
            if "Recommendations" in report_content:
                checks["report_has_recommendations_section"] = True

        except Exception:
            pass

    # Log validations
    if os.path.isfile(log_path):
        checks["log_exists"] = True
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log_content = f.read()

            # ISO-like date pattern (YYYY-MM-DD)
            if re.search(r"\b\d{4}-\d{2}-\d{2}\b", log_content):
                checks["log_has_iso_date"] = True

            # Mentions of "status" and "devices"
            lower_log = log_content.lower()
            if "status" in lower_log:
                checks["log_mentions_status"] = True
            if "devices" in lower_log:
                checks["log_mentions_devices"] = True

        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure 0.0 when no artifacts produced (baseline no-op)
    # If none of the file existence checks passed, reward should be 0.0
    file_existence_flags = [
        checks["raw_status_exists"],
        checks["raw_devices_exists"],
        checks["summary_exists"],
        checks["report_exists"],
        checks["log_exists"],
    ]
    if not any(file_existence_flags):
        reward = 0.0

    # Bound reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()