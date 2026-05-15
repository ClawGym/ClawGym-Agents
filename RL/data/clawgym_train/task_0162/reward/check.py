import json
import os
import sys
from datetime import datetime
from math import sqrt

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_timestamp(ts):
    # Attempt robust ISO8601 parsing
    if not isinstance(ts, str):
        return None
    try:
        # Handle 'Z' suffix as UTC
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def is_sorted_ascending_timestamps(arr):
    # Accept empty or single element as sorted
    if len(arr) <= 1:
        return True
    parsed = []
    for item in arr:
        ts = item.get("timestamp")
        dt = parse_timestamp(ts)
        parsed.append((dt, ts))
    for i in range(len(parsed) - 1):
        a_dt, a_raw = parsed[i]
        b_dt, b_raw = parsed[i+1]
        if a_dt is not None and b_dt is not None:
            if a_dt > b_dt:
                return False
        else:
            # Fallback to raw string comparison if parsing fails
            if a_raw > b_raw:
                return False
    return True

def sample_stats(values):
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    if n >= 2:
        var = sum((x - mean) ** 2 for x in values) / (n - 1)
        stdev = sqrt(var)
    else:
        stdev = 0.0
    return {
        "mean": mean,
        "stdev": stdev,
        "min": min(values),
        "max": max(values),
        "count": n
    }

def approx_equal(a, b, tol=1e-6):
    return abs(a - b) <= tol

def build_expected_baselines(input_data):
    expected = {}
    metrics = ["temperature", "heart_rate", "sleep_hours"]
    exclusions = {
        "temperature": 1,
        "heart_rate": 10,
        "sleep_hours": 3
    }
    for m in metrics:
        series = input_data.get(m, [])
        if not isinstance(series, list):
            series = []
        # Exclude latest N readings by order (end of list)
        excl = exclusions[m]
        hist = series[:-excl] if excl <= len(series) else []
        hist_vals = [item["value"] for item in hist if item is not None and "value" in item]
        stats = sample_stats(hist_vals) if len(hist_vals) > 0 else None
        if stats is None:
            # If no historical values, define a structure with zeros but count 0 to avoid None
            expected[m] = {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        else:
            expected[m] = stats
    return expected

def build_expected_alerts(input_data, config, expected_baselines):
    alerts = []
    thresholds = config.get("thresholds", {}) if isinstance(config, dict) else {}
    # Temperature high
    temp_series = input_data.get("temperature", []) if isinstance(input_data, dict) else []
    if isinstance(temp_series, list) and len(temp_series) >= 1:
        latest_temp = temp_series[-1]
        t_value = latest_temp.get("value")
        t_ts = latest_temp.get("timestamp")
        t_thr = thresholds.get("temperature_high_f")
        if t_value is not None and t_thr is not None and isinstance(t_value, (int, float)) and isinstance(t_thr, (int, float)):
            if t_value >= t_thr:
                severity = "critical" if t_value >= 101.5 else "warning"
                alerts.append({
                    "type": "temperature_high",
                    "severity": severity,
                    "value": float(t_value),
                    "threshold": float(t_thr),
                    "timestamp": t_ts,
                    "message": ""  # message content not strictly validated; placeholder expected to be non-empty by agent
                })
    # Heart rate high
    hr_series = input_data.get("heart_rate", []) if isinstance(input_data, dict) else []
    if isinstance(hr_series, list) and len(hr_series) >= 1:
        last10 = hr_series[-10:] if len(hr_series) >= 10 else hr_series[:]
        hr_vals = [x.get("value") for x in last10 if x is not None and "value" in x]
        hr_vals = [float(v) for v in hr_vals if isinstance(v, (int, float))]
        if len(hr_vals) >= 1:
            hr_avg = sum(hr_vals) / len(hr_vals)
            hr_thr = thresholds.get("heart_rate_high")
            if hr_thr is not None and isinstance(hr_thr, (int, float)):
                if hr_avg >= hr_thr:
                    alerts.append({
                        "type": "heart_rate_high",
                        "severity": "warning",
                        "value": float(hr_avg),
                        "threshold": float(hr_thr),
                        "timestamp": hr_series[-1].get("timestamp"),
                        "message": ""
                    })
    # Sleep degradation
    sleep_series = input_data.get("sleep_hours", []) if isinstance(input_data, dict) else []
    if isinstance(sleep_series, list) and len(sleep_series) >= 3:
        last3 = sleep_series[-3:]
        s_vals = [x.get("value") for x in last3 if x is not None and "value" in x]
        s_vals = [float(v) for v in s_vals if isinstance(v, (int, float))]
        if len(s_vals) == 3:
            recent_avg = sum(s_vals) / 3.0
            baseline = expected_baselines.get("sleep_hours", {})
            b_count = baseline.get("count", 0)
            b_mean = baseline.get("mean", None)
            if b_count and b_mean is not None:
                if recent_avg < b_mean * 0.70:
                    alerts.append({
                        "type": "sleep_degradation",
                        "severity": "info",
                        "value": float(recent_avg),
                        "baseline": float(b_mean),
                        "timestamp": sleep_series[-1].get("timestamp"),
                        "message": ""
                    })
    return alerts

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_readings_json": False,
        "readings_json_valid": False,
        "readings_have_required_keys": False,
        "readings_counts_match_input": False,
        "readings_sorted_ascending": False,
        "readings_last_elements_match": False,
        "has_baselines_json": False,
        "baselines_json_valid": False,
        "baselines_have_required_metrics": False,
        "baselines_values_correct": False,
        "has_alerts_json": False,
        "alerts_json_valid": False,
        "alerts_exact_match": False,
        "has_summary_md": False,
        "summary_min_lines": False
    }

    # Load input references
    health_data_path = os.path.join(input_dir, "health_data.json")
    config_path = os.path.join(input_dir, "config.json")
    input_data = parse_json_file(health_data_path) or {}
    config = parse_json_file(config_path) or {}

    # 1) Validate readings.json
    readings_path = os.path.join(output_dir, "readings.json")
    if os.path.isfile(readings_path):
        checks["has_readings_json"] = True
        readings_obj = parse_json_file(readings_path)
        if isinstance(readings_obj, dict):
            checks["readings_json_valid"] = True
            required_metrics = ["temperature", "heart_rate", "sleep_hours"]
            # Check required keys
            if all(k in readings_obj for k in required_metrics):
                # And ensure arrays
                arrays_ok = True
                for k in required_metrics:
                    if not isinstance(readings_obj.get(k), list):
                        arrays_ok = False
                        break
                if arrays_ok:
                    checks["readings_have_required_keys"] = True
                    # Counts match input
                    counts_ok = True
                    for m in required_metrics:
                        in_series = input_data.get(m, [])
                        out_series = readings_obj.get(m, [])
                        if not isinstance(in_series, list):
                            in_series = []
                        if not isinstance(out_series, list):
                            counts_ok = False
                            break
                        if len(in_series) != len(out_series):
                            counts_ok = False
                            break
                    if counts_ok:
                        checks["readings_counts_match_input"] = True
                    # Sorted ascending check for each metric
                    sorted_ok = True
                    for m in required_metrics:
                        series = readings_obj.get(m, [])
                        # Verify objects have timestamp and value keys
                        for item in series:
                            if not isinstance(item, dict) or "timestamp" not in item or "value" not in item:
                                sorted_ok = False
                                break
                        if not sorted_ok:
                            break
                        if not is_sorted_ascending_timestamps(series):
                            sorted_ok = False
                            break
                    if sorted_ok:
                        checks["readings_sorted_ascending"] = True
                    # Last elements match input
                    last_ok = True
                    for m in required_metrics:
                        in_series = input_data.get(m, [])
                        out_series = readings_obj.get(m, [])
                        if not isinstance(in_series, list) or not isinstance(out_series, list) or len(in_series) == 0 or len(out_series) == 0:
                            last_ok = False
                            break
                        in_last = in_series[-1]
                        out_last = out_series[-1]
                        # Compare timestamp and value equality
                        if in_last.get("timestamp") != out_last.get("timestamp"):
                            last_ok = False
                            break
                        in_val = in_last.get("value")
                        out_val = out_last.get("value")
                        # Numeric compare or exact equality
                        if isinstance(in_val, (int, float)) and isinstance(out_val, (int, float)):
                            if not approx_equal(float(in_val), float(out_val)):
                                last_ok = False
                                break
                        else:
                            if in_val != out_val:
                                last_ok = False
                                break
                    if last_ok:
                        checks["readings_last_elements_match"] = True

    # 2) Validate baselines.json
    baselines_path = os.path.join(output_dir, "baselines.json")
    expected_baselines = None
    if os.path.isfile(baselines_path):
        checks["has_baselines_json"] = True
        baselines_obj = parse_json_file(baselines_path)
        if isinstance(baselines_obj, dict):
            checks["baselines_json_valid"] = True
            required_metrics = ["temperature", "heart_rate", "sleep_hours"]
            if all(k in baselines_obj for k in required_metrics):
                checks["baselines_have_required_metrics"] = True
            # Compute expected baselines from input
            expected_baselines = build_expected_baselines(input_data)
            # Compare values
            values_ok = True
            for m in required_metrics:
                if m not in baselines_obj or m not in expected_baselines:
                    values_ok = False
                    break
                got = baselines_obj[m]
                exp = expected_baselines[m]
                # Ensure fields exist
                for fld in ["mean", "stdev", "min", "max", "count"]:
                    if fld not in got:
                        values_ok = False
                        break
                if not values_ok:
                    break
                # If expected count is 0, require got count == 0
                if exp["count"] == 0:
                    if got.get("count") != 0:
                        values_ok = False
                        break
                    # For zero count, we cannot verify stats meaningfully; require zeros for consistency
                    if any(not approx_equal(float(got.get(f, 0.0)), 0.0) for f in ["mean", "stdev", "min", "max"]):
                        values_ok = False
                        break
                else:
                    # Numeric comparisons with tolerance
                    try:
                        got_mean = float(got.get("mean"))
                        got_stdev = float(got.get("stdev"))
                        got_min = float(got.get("min"))
                        got_max = float(got.get("max"))
                        got_count = int(got.get("count"))
                    except Exception:
                        values_ok = False
                        break
                    if not approx_equal(got_mean, float(exp["mean"])) or not approx_equal(got_stdev, float(exp["stdev"])):
                        values_ok = False
                        break
                    if not approx_equal(got_min, float(exp["min"])) or not approx_equal(got_max, float(exp["max"])):
                        values_ok = False
                        break
                    if got_count != int(exp["count"]):
                        values_ok = False
                        break
            if values_ok and checks["baselines_have_required_metrics"]:
                checks["baselines_values_correct"] = True

    # 3) Validate alerts.json
    alerts_path = os.path.join(output_dir, "alerts.json")
    if os.path.isfile(alerts_path):
        checks["has_alerts_json"] = True
        alerts_obj = parse_json_file(alerts_path)
        if isinstance(alerts_obj, list):
            checks["alerts_json_valid"] = True
            # Build expected alerts using input data, config, and computed baselines
            if expected_baselines is None:
                expected_baselines = build_expected_baselines(input_data)
            expected_alerts = build_expected_alerts(input_data, config, expected_baselines)
            # We require exact match in count and types
            match_ok = True
            if len(alerts_obj) != len(expected_alerts):
                match_ok = False
            else:
                # Map expected by type (ensure unique types)
                exp_by_type = {a["type"]: a for a in expected_alerts}
                # Validate each alert in output matches an expected one
                seen_types = set()
                for a in alerts_obj:
                    if not isinstance(a, dict):
                        match_ok = False
                        break
                    a_type = a.get("type")
                    if a_type not in exp_by_type or a_type in seen_types:
                        match_ok = False
                        break
                    seen_types.add(a_type)
                    exp = exp_by_type[a_type]
                    # Required fields presence
                    if "severity" not in a or "timestamp" not in a or "message" not in a:
                        match_ok = False
                        break
                    # Severity exact
                    if a.get("severity") != exp.get("severity"):
                        match_ok = False
                        break
                    # Timestamp exact
                    if a.get("timestamp") != exp.get("timestamp"):
                        match_ok = False
                        break
                    # Numeric fields by type
                    if a_type in ("temperature_high", "heart_rate_high"):
                        if "value" not in a or "threshold" not in a:
                            match_ok = False
                            break
                        try:
                            got_val = float(a.get("value"))
                            got_thr = float(a.get("threshold"))
                        except Exception:
                            match_ok = False
                            break
                        if not approx_equal(got_val, float(exp.get("value"))) or not approx_equal(got_thr, float(exp.get("threshold"))):
                            match_ok = False
                            break
                    elif a_type == "sleep_degradation":
                        if "value" not in a or "baseline" not in a:
                            match_ok = False
                            break
                        try:
                            got_val = float(a.get("value"))
                            got_base = float(a.get("baseline"))
                        except Exception:
                            match_ok = False
                            break
                        if not approx_equal(got_val, float(exp.get("value"))) or not approx_equal(got_base, float(exp.get("baseline"))):
                            match_ok = False
                            break
                    else:
                        # Unknown alert type
                        match_ok = False
                        break
                # Ensure there are exactly the expected alert types
                if match_ok:
                    if set(exp_by_type.keys()) != set(seen_types):
                        match_ok = False
            if match_ok:
                checks["alerts_exact_match"] = True

    # 4) Validate summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            non_empty_lines = [ln for ln in content.splitlines() if ln.strip() != ""]
            if len(non_empty_lines) >= 3:
                checks["summary_min_lines"] = True
        except Exception:
            pass

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()