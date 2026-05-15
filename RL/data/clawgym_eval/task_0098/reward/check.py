import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

def parse_iso8601(ts: str):
    # Attempt to parse common ISO8601 formats; fallback to string order
    if isinstance(ts, str):
        t = ts.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(t)
        except Exception:
            pass
    return None

def round_three_decimals_half_up(value: float) -> float:
    # Standard rounding to three decimals using half-up rule
    d = Decimal(str(value))
    r = d.quantize(Decimal("0.000"), rounding=ROUND_HALF_UP)
    return float(r)

def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()

def build_expected(input_dir):
    health_path = os.path.join(input_dir, "health_log.json")
    config_path = os.path.join(input_dir, "config_base.json")
    health = load_json_file(health_path)
    base_config = load_json_file(config_path)

    if not isinstance(health, list):
        raise ValueError("input/health_log.json must be a JSON array")

    check_statuses = {"healthy", "port_closed", "process_missing", "port_timeout"}
    events = []
    for idx, ev in enumerate(health):
        # Expect at least 'timestamp' and 'status'
        ts = ev.get("timestamp")
        st = ev.get("status")
        events.append({
            "idx": idx,
            "timestamp": ts,
            "status": st,
            "parsed_dt": parse_iso8601(ts),
            "raw_ts": ts if isinstance(ts, str) else ""
        })

    # Derive check events
    check_events = [e for e in events if e["status"] in check_statuses]
    # Sort by timestamp ascending; tiebreak by original index to keep stable order
    def sort_key(e):
        if e["parsed_dt"] is not None:
            return (e["parsed_dt"], e["idx"])
        # fallback to string compare if parse failed
        return (e["raw_ts"], e["idx"])
    check_events_sorted = sorted(check_events, key=sort_key)

    # Build expected normalized lines
    expected_normalized = []
    for e in check_events_sorted:
        status = e["status"]
        expected_normalized.append({
            "ts": e["timestamp"],
            "status": status,
            "ok": True if status == "healthy" else False,
            "type": "check",
        })

    # Metrics
    total_checks = len(check_events_sorted)
    healthy_count = sum(1 for e in check_events_sorted if e["status"] == "healthy")
    unhealthy_count = total_checks - healthy_count
    restart_attempts = sum(1 for e in events if e["status"] == "restart_attempted")
    restart_successes = sum(1 for e in events if e["status"] == "restart_success")
    if total_checks > 0:
        last_check_status = check_events_sorted[-1]["status"]
    else:
        last_check_status = None

    # Count maximal consecutive runs of non-healthy checks length >= 3
    failure_set = {"port_closed", "process_missing", "port_timeout"}
    failure_sequences_of_3_plus = 0
    run_len = 0
    for e in check_events_sorted:
        if e["status"] in failure_set:
            run_len += 1
        else:
            if run_len >= 3:
                failure_sequences_of_3_plus += 1
            run_len = 0
    if run_len >= 3:
        failure_sequences_of_3_plus += 1

    success_rate = 0.0
    if total_checks > 0:
        success_rate = round_three_decimals_half_up(healthy_count / total_checks)

    # Recommended config
    gw = base_config.get("gateway", {}) if isinstance(base_config, dict) else {}
    port_value = gw.get("port", None)
    recommended_config = {
        "port": port_value,
        "check_interval_seconds": 30,
        "max_restart_attempts": 12 if restart_attempts > 5 else 10,
        "restart_delay_seconds": 7 if failure_sequences_of_3_plus >= 2 else 5,
    }

    expected_summary = {
        "total_checks": total_checks,
        "healthy_count": healthy_count,
        "unhealthy_count": unhealthy_count,
        "restart_attempts": restart_attempts,
        "restart_successes": restart_successes,
        "last_check_status": last_check_status,
        "failure_sequences_of_3_plus": failure_sequences_of_3_plus,
        "success_rate": success_rate,
        "recommended_config": recommended_config,
    }

    # Build expected optimized_config by updating only specified gateway fields
    expected_optimized = deepcopy(base_config if isinstance(base_config, dict) else {})
    if "gateway" not in expected_optimized or not isinstance(expected_optimized.get("gateway"), dict):
        expected_optimized["gateway"] = {}
    expected_optimized["gateway"]["check_interval_seconds"] = recommended_config["check_interval_seconds"]
    expected_optimized["gateway"]["max_restart_attempts"] = recommended_config["max_restart_attempts"]
    expected_optimized["gateway"]["restart_delay_seconds"] = recommended_config["restart_delay_seconds"]
    # Preserve port unchanged (do not set/overwrite here)

    return expected_normalized, expected_summary, expected_optimized

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "normalized_exists": False,
        "normalized_content_correct": False,
        "summary_exists": False,
        "summary_content_correct": False,
        "optimized_exists": False,
        "optimized_content_correct": False,
    }

    try:
        expected_normalized, expected_summary, expected_optimized = build_expected(input_dir)
    except Exception:
        # If inputs are bad, outputs cannot pass; leave checks as False
        expected_normalized, expected_summary, expected_optimized = None, None, None

    # Validate normalized_health.jsonl
    normalized_path = os.path.join(output_dir, "normalized_health.jsonl")
    if os.path.isfile(normalized_path):
        checks["normalized_exists"] = True
        try:
            lines = read_jsonl_lines(normalized_path)
            # Reject empty file if there should be events
            objs = []
            for i, line in enumerate(lines):
                if line.strip() == "":
                    # Empty line counts as invalid extra line
                    pass
                try:
                    obj = json.loads(line)
                except Exception:
                    # If line is empty, json.loads will fail; mark invalid later
                    obj = None
                objs.append(obj)

            # Remove None entries caused by empty or invalid JSON lines
            # But we must ensure we had exactly len(expected_normalized) valid JSON objects
            valid_objs = [o for o in objs if isinstance(o, dict)]

            if expected_normalized is not None and len(valid_objs) == len(expected_normalized):
                all_ok = True
                for idx, (got, exp) in enumerate(zip(valid_objs, expected_normalized)):
                    # Must contain at least the required keys
                    required_keys = {"ts", "status", "ok", "type"}
                    if not required_keys.issubset(set(got.keys())):
                        all_ok = False
                        break
                    if got["ts"] != exp["ts"]:
                        all_ok = False
                        break
                    if got["status"] != exp["status"]:
                        all_ok = False
                        break
                    if bool(got["ok"]) != exp["ok"]:
                        all_ok = False
                        break
                    if got["type"] != "check":
                        all_ok = False
                        break
                # Additionally ensure there are no extra valid JSON lines beyond expected
                if len(valid_objs) != len(expected_normalized):
                    all_ok = False
                # Ensure there were no extra non-JSON garbage lines
                if len(valid_objs) != len([l for l in lines if l.strip() != ""]):
                    all_ok = False
                if all_ok:
                    checks["normalized_content_correct"] = True
        except Exception:
            pass

    # Validate health_summary.json
    summary_path = os.path.join(output_dir, "health_summary.json")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            summary_obj = load_json_file(summary_path)
            # Must be dict and contain required keys
            required_top = {
                "total_checks",
                "healthy_count",
                "unhealthy_count",
                "restart_attempts",
                "restart_successes",
                "last_check_status",
                "failure_sequences_of_3_plus",
                "success_rate",
                "recommended_config",
            }
            has_required = isinstance(summary_obj, dict) and required_top.issubset(set(summary_obj.keys()))
            if has_required and expected_summary is not None:
                ok = True
                # Compare integer/string fields exactly
                for k in [
                    "total_checks",
                    "healthy_count",
                    "unhealthy_count",
                    "restart_attempts",
                    "restart_successes",
                    "failure_sequences_of_3_plus",
                ]:
                    if summary_obj.get(k) != expected_summary.get(k):
                        ok = False
                        break
                if ok:
                    # last_check_status can be None
                    if summary_obj.get("last_check_status", None) != expected_summary.get("last_check_status", None):
                        ok = False
                if ok:
                    # success_rate with 3-decimal rounding; compare with tolerance
                    exp_sr = expected_summary["success_rate"]
                    got_sr = summary_obj.get("success_rate")
                    # Ensure got_sr is a number
                    if not isinstance(got_sr, (int, float)):
                        ok = False
                    else:
                        if abs(float(got_sr) - float(exp_sr)) > 1e-9:
                            ok = False
                if ok:
                    # recommended_config must contain exactly the specified keys and values
                    rc = summary_obj.get("recommended_config")
                    if not isinstance(rc, dict):
                        ok = False
                    else:
                        expected_keys = {"port", "check_interval_seconds", "max_restart_attempts", "restart_delay_seconds"}
                        if set(rc.keys()) != expected_keys:
                            ok = False
                        else:
                            if rc["port"] != expected_summary["recommended_config"]["port"]:
                                ok = False
                            if rc["check_interval_seconds"] != 30:
                                ok = False
                            exp_mra = expected_summary["recommended_config"]["max_restart_attempts"]
                            if rc["max_restart_attempts"] != exp_mra:
                                ok = False
                            exp_rds = expected_summary["recommended_config"]["restart_delay_seconds"]
                            if rc["restart_delay_seconds"] != exp_rds:
                                ok = False
                if ok:
                    checks["summary_content_correct"] = True
        except Exception:
            pass

    # Validate optimized_config.json
    optimized_path = os.path.join(output_dir, "optimized_config.json")
    if os.path.isfile(optimized_path):
        checks["optimized_exists"] = True
        try:
            optimized_obj = load_json_file(optimized_path)
            if expected_optimized is not None and isinstance(optimized_obj, dict):
                # Deep equality check
                if optimized_obj == expected_optimized:
                    checks["optimized_content_correct"] = True
        except Exception:
            pass

    # Compute reward: only content correctness counts, equally weighted across three artifacts
    content_checks = [
        checks["normalized_content_correct"],
        checks["summary_content_correct"],
        checks["optimized_content_correct"],
    ]
    passed = sum(1 for c in content_checks if c)
    reward = passed / 3.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()