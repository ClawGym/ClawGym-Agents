import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until proven)
    checks = {
        "raw_host_discovery_json": False,
        "raw_top_ports_json": False,
        "raw_service_detect_json": False,
        "summary_json_valid": False,
        "summary_targets_localhost_entry": False,
        "summary_scan_ids_complete": False,
        "summary_generated_at_ok": False,
        "security_memo_exists": False,
        "security_memo_content_ok": False,
    }

    # Paths
    host_discovery_path = os.path.join(output_dir, "raw", "host_discovery.json")
    top_ports_path = os.path.join(output_dir, "raw", "top_ports.json")
    service_detect_path = os.path.join(output_dir, "raw", "service_detect.json")
    summary_path = os.path.join(output_dir, "report", "summary.json")
    security_memo_path = os.path.join(output_dir, "report", "security_memo.md")

    # Helper to load JSON safely
    def load_json_file(p):
        try:
            with open(p, "r") as f:
                return json.load(f)
        except Exception:
            return None

    # Validate raw/host_discovery.json
    if os.path.isfile(host_discovery_path):
        data = load_json_file(host_discovery_path)
        if isinstance(data, dict):
            scan_id = data.get("scan_id")
            target = data.get("target")
            if isinstance(scan_id, str) and scan_id.strip() != "" and isinstance(target, str) and target.strip() != "":
                checks["raw_host_discovery_json"] = True

    # Validate raw/top_ports.json
    if os.path.isfile(top_ports_path):
        data = load_json_file(top_ports_path)
        if isinstance(data, dict):
            scan_id = data.get("scan_id")
            target = data.get("target")
            has_port_count_key = ("top_ports_scanned" in data) or ("ports_scanned" in data)
            if isinstance(scan_id, str) and scan_id.strip() != "" and isinstance(target, str) and target.strip() != "" and has_port_count_key:
                checks["raw_top_ports_json"] = True

    # Validate raw/service_detect.json
    if os.path.isfile(service_detect_path):
        data = load_json_file(service_detect_path)
        if isinstance(data, dict):
            scan_id = data.get("scan_id")
            target = data.get("target")
            if isinstance(scan_id, str) and scan_id.strip() != "" and isinstance(target, str) and target.strip() != "":
                checks["raw_service_detect_json"] = True

    # Validate report/summary.json
    summary_data = None
    if os.path.isfile(summary_path):
        summary_data = load_json_file(summary_path)
        if isinstance(summary_data, dict):
            # Must contain keys: targets (array), generated_at (string), scan_ids (object)
            has_targets = isinstance(summary_data.get("targets"), list)
            has_generated_at = isinstance(summary_data.get("generated_at"), str)
            has_scan_ids = isinstance(summary_data.get("scan_ids"), dict)
            if has_targets and has_generated_at and has_scan_ids:
                checks["summary_json_valid"] = True

            # If valid basic structure, check specific requirements
            if checks["summary_json_valid"]:
                # targets array has at least one entry with target == "127.0.0.1" and includes host_up (bool) and open_ports (list)
                localhost_ok = False
                for entry in summary_data.get("targets", []):
                    if isinstance(entry, dict) and entry.get("target") == "127.0.0.1":
                        host_up = entry.get("host_up")
                        open_ports = entry.get("open_ports")
                        if isinstance(host_up, bool) and isinstance(open_ports, list):
                            localhost_ok = True
                            break
                if localhost_ok:
                    checks["summary_targets_localhost_entry"] = True

                # scan_ids contains non-empty strings for host_discovery, top_ports, service_detection
                scan_ids = summary_data.get("scan_ids", {})
                def nonempty_str(v):
                    return isinstance(v, str) and v.strip() != ""
                if (
                    isinstance(scan_ids, dict) and
                    nonempty_str(scan_ids.get("host_discovery")) and
                    nonempty_str(scan_ids.get("top_ports")) and
                    nonempty_str(scan_ids.get("service_detection"))
                ):
                    checks["summary_scan_ids_complete"] = True

                # generated_at is non-empty string that includes 'T' and no surrounding whitespace
                ga = summary_data.get("generated_at")
                if isinstance(ga, str) and ga != "" and "T" in ga and ga == ga.strip():
                    checks["summary_generated_at_ok"] = True

    # Validate security_memo.md
    if os.path.isfile(security_memo_path):
        checks["security_memo_exists"] = True
        try:
            with open(security_memo_path, "r", encoding="utf-8", errors="ignore") as f:
                memo_text = f.read()
        except Exception:
            memo_text = ""

        memo_low = memo_text.lower()
        # Required substrings (case-insensitive):
        # - One of: "permission" or "authorized"
        # - "scope"
        # - "127.0.0.1"
        # - "audit"
        # - One of: "next steps" or "recommendations"
        has_perm = ("permission" in memo_low) or ("authorized" in memo_low)
        has_scope = "scope" in memo_low
        has_localhost = "127.0.0.1" in memo_text  # numeric string, case-insensitive not needed
        has_audit = "audit" in memo_low
        has_next_or_reco = ("next steps" in memo_low) or ("recommendations" in memo_low)
        if has_perm and has_scope and has_localhost and has_audit and has_next_or_reco:
            checks["security_memo_content_ok"] = True

    # Compute reward as fraction of checks passed; enforce 0.0 for no-op baseline
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Ensure no-op baseline is exactly 0.0 if no required artifacts
    # If none of the primary artifact existence checks are true, set reward to 0.0
    primary_exist_checks = [
        checks["raw_host_discovery_json"],
        checks["raw_top_ports_json"],
        checks["raw_service_detect_json"],
        checks["summary_json_valid"],
        checks["security_memo_exists"],
    ]
    if not any(primary_exist_checks):
        reward = 0.0

    # Print single JSON object with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()