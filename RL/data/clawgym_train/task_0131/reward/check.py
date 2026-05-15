import json
import os
import sys

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    audit_dir = os.path.join(output_dir, "audit")
    summary_path = os.path.join(audit_dir, "summary.json")

    # Initialize checks to False
    checks = {
        "has_summary_file": False,
        "parsed_json_valid": False,
        "config_path_ok": False,
        "config_parsed_true": False,
        "severities_has_keys": False,
        "severities_values_ints_nonnegative": False,
        "severity_minimums": False,
        "present_ids_is_list": False,
        "ids_unique_sorted": False,
        "ids_required_present": False,
        "detected_flags_present_and_bool": False,
        "flags_values_true": False,
        "evidence_map_has_required_keys": False,
        "evidence_map_entries_nonempty": False,
        "total_findings_gte_ids_len": False,
    }

    required_ids = {"NET-001", "AUTH-001", "EXEC-001", "EXEC-002", "CHAN-001"}
    required_flags = [
        "wildcard_bind",
        "auth_weak_or_missing",
        "sandbox_disabled",
        "unrestricted_exec",
        "channel_allowlist_missing",
    ]
    required_severity_keys = ["critical", "high", "medium", "low", "info"]

    data = None
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        try:
            data = load_json(summary_path)
            if isinstance(data, dict):
                checks["parsed_json_valid"] = True
        except Exception:
            data = None

    if checks["parsed_json_valid"]:
        # config_path must be exactly "input/openclaw.json"
        cfg_path = data.get("config_path")
        if isinstance(cfg_path, str) and cfg_path == "input/openclaw.json":
            checks["config_path_ok"] = True

        # config_parsed is boolean and True
        cfg_parsed = data.get("config_parsed")
        if isinstance(cfg_parsed, bool) and cfg_parsed is True:
            checks["config_parsed_true"] = True

        # severities object structure and values
        severities = data.get("severities")
        if isinstance(severities, dict):
            if all(k in severities for k in required_severity_keys):
                checks["severities_has_keys"] = True
                # values are ints and >= 0
                if all(is_int(severities.get(k)) and severities.get(k) >= 0 for k in required_severity_keys):
                    checks["severities_values_ints_nonnegative"] = True
                # minimums: critical>=1, high>=1, medium>=1
                if (
                    is_int(severities.get("critical")) and severities.get("critical") >= 1 and
                    is_int(severities.get("high")) and severities.get("high") >= 1 and
                    is_int(severities.get("medium")) and severities.get("medium") >= 1
                ):
                    checks["severity_minimums"] = True

        # present_finding_ids checks
        ids = data.get("present_finding_ids")
        if isinstance(ids, list):
            # all strings
            if all(isinstance(x, str) for x in ids):
                checks["present_ids_is_list"] = True
                # unique and sorted
                unique_ids = sorted(set(ids))
                if ids == unique_ids:
                    checks["ids_unique_sorted"] = True
                # contains required
                if required_ids.issubset(set(ids)):
                    checks["ids_required_present"] = True

        # detected_flags checks
        flags = data.get("detected_flags")
        if isinstance(flags, dict):
            if all(k in flags and isinstance(flags.get(k), bool) for k in required_flags):
                checks["detected_flags_present_and_bool"] = True
                if all(flags.get(k) is True for k in required_flags):
                    checks["flags_values_true"] = True

        # evidence_map checks
        evidence_map = data.get("evidence_map")
        if isinstance(evidence_map, dict):
            if all(k in evidence_map for k in required_ids):
                checks["evidence_map_has_required_keys"] = True
                # each required key maps to a non-empty array of non-empty strings
                em_ok = True
                for k in required_ids:
                    v = evidence_map.get(k)
                    if not isinstance(v, list) or len(v) == 0:
                        em_ok = False
                        break
                    # each item must be a non-empty string (after strip)
                    for item in v:
                        if not isinstance(item, str) or len(item.strip()) == 0:
                            em_ok = False
                            break
                    if not em_ok:
                        break
                if em_ok:
                    checks["evidence_map_entries_nonempty"] = True

        # total_findings >= len(present_finding_ids)
        total_findings = data.get("total_findings")
        if is_int(total_findings):
            ids_len = len(ids) if isinstance(ids, list) else 0
            if total_findings >= ids_len:
                checks["total_findings_gte_ids_len"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Gate positive reward on presence and valid JSON
    if not (checks["has_summary_file"] and checks["parsed_json_valid"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()