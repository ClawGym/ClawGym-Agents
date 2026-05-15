import json
import os
import sys
from typing import Dict, Any, List, Tuple

def is_iso8601_like(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    # Simple heuristic: contains 'T' between date and time, length reasonable
    return "T" in s and len(s) >= 19

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def load_csv_pairs(path: str) -> Tuple[bool, Dict[str, str]]:
    pairs: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Split on first comma only to allow commas in values (rare here)
                parts = line.split(",", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip()
                if key:
                    pairs[key] = value
        return True, pairs
    except Exception:
        return False, {}

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used but kept for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "report.json")
    summary_csv_path = os.path.join(output_dir, "summary.csv")

    checks: Dict[str, bool] = {
        "has_report_json": False,
        "report_json_valid": False,
        "report_required_keys": False,
        "timestamp_valid": False,
        "duration_non_negative": False,
        "summary_fields_exist_and_int": False,
        "verdict_is_dangerous": False,
        "summary_environment_accesses_ge6": False,
        "summary_sensitive_env_accesses_ge6": False,
        "summary_subprocess_calls_ge1": False,
        "summary_warnings_ge6": False,
        "environment_contains_required_sensitive_keys": False,
        "subprocesses_array_len_ge1": False,
        "warnings_array_len_ge6": False,
        "has_summary_csv": False,
        "csv_has_required_rows": False,
        "csv_values_match_json": False,
    }

    report: Dict[str, Any] = {}
    summary: Dict[str, Any] = {}

    # Check report.json existence
    if os.path.isfile(report_path):
        checks["has_report_json"] = True

        # Parse JSON
        ok, data = load_json(report_path)
        if ok and isinstance(data, dict):
            checks["report_json_valid"] = True
            report = data

            # Check required top-level keys
            required_top_keys = ["timestamp", "duration_seconds", "verdict", "summary", "environment", "subprocesses", "warnings"]
            if all(k in report for k in required_top_keys):
                checks["report_required_keys"] = True

                # Timestamp check
                if is_iso8601_like(report.get("timestamp")):
                    checks["timestamp_valid"] = True

                # Duration check
                dur = report.get("duration_seconds")
                if isinstance(dur, (int, float)) and dur >= 0:
                    checks["duration_non_negative"] = True

                # Summary fields
                summary = report.get("summary", {})
                summary_required_ints = ["filesystem_operations", "environment_accesses", "sensitive_env_accesses", "network_calls", "subprocess_calls", "warnings"]
                if isinstance(summary, dict) and all(x in summary for x in summary_required_ints) and all(isinstance(summary.get(x), int) for x in summary_required_ints):
                    checks["summary_fields_exist_and_int"] = True

                    # Specific thresholds
                    if summary.get("environment_accesses", 0) >= 6:
                        checks["summary_environment_accesses_ge6"] = True
                    if summary.get("sensitive_env_accesses", 0) >= 6:
                        checks["summary_sensitive_env_accesses_ge6"] = True
                    if summary.get("subprocess_calls", 0) >= 1:
                        checks["summary_subprocess_calls_ge1"] = True
                    if summary.get("warnings", 0) >= 6:
                        checks["summary_warnings_ge6"] = True

                # Verdict check
                if report.get("verdict") == "DANGEROUS":
                    checks["verdict_is_dangerous"] = True

                # Environment entries for required keys with sensitive=true
                env_list = report.get("environment")
                required_env_keys = {"OPENAI_API_KEY", "GITHUB_TOKEN"}
                if isinstance(env_list, list):
                    found_keys = set()
                    for item in env_list:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key")
                        sens = item.get("sensitive")
                        if key in required_env_keys and sens is True:
                            found_keys.add(key)
                    if required_env_keys.issubset(found_keys):
                        checks["environment_contains_required_sensitive_keys"] = True

                # Subprocess array length
                sp_list = report.get("subprocesses")
                if isinstance(sp_list, list) and len(sp_list) >= 1:
                    # Also ensure entries have expected keys
                    has_required_shape = True
                    for item in sp_list:
                        if not isinstance(item, dict) or "command" not in item or "timestamp" not in item:
                            has_required_shape = False
                            break
                    if has_required_shape:
                        checks["subprocesses_array_len_ge1"] = True

                # Warnings array length
                warn_list = report.get("warnings")
                if isinstance(warn_list, list) and len(warn_list) >= 6:
                    # Ensure entries have expected keys
                    has_required_shape_w = True
                    for item in warn_list:
                        if not isinstance(item, dict) or "message" not in item or "timestamp" not in item:
                            has_required_shape_w = False
                            break
                    if has_required_shape_w:
                        checks["warnings_array_len_ge6"] = True

    # Check summary.csv
    if os.path.isfile(summary_csv_path):
        checks["has_summary_csv"] = True
        ok_csv, pairs = load_csv_pairs(summary_csv_path)
        required_csv_rows = ["verdict", "environment_accesses", "sensitive_env_accesses", "subprocess_calls", "warnings"]
        if ok_csv and all(k in pairs for k in required_csv_rows):
            checks["csv_has_required_rows"] = True

            # Only compare if JSON summary is valid
            all_match = True
            if checks["report_json_valid"] and checks["summary_fields_exist_and_int"]:
                # Compare counts
                for k in ["environment_accesses", "sensitive_env_accesses", "subprocess_calls", "warnings"]:
                    csv_val_str = pairs.get(k, "").strip()
                    try:
                        csv_val = int(csv_val_str)
                    except Exception:
                        all_match = False
                        break
                    if summary.get(k) != csv_val:
                        all_match = False
                        break
                # Compare verdict
                if all_match:
                    if "verdict" in pairs:
                        if str(report.get("verdict", "")).strip() != pairs["verdict"].strip():
                            all_match = False
                    else:
                        all_match = False
            else:
                all_match = False

            if all_match:
                checks["csv_values_match_json"] = True

    # Compute reward as fraction of passed checks.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward is exactly 0.0 if no required artifacts (both) are present
    if not checks["has_report_json"] and not checks["has_summary_csv"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()