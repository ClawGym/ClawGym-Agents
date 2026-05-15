import json
import os
import sys
import math
import re
from collections import Counter
from datetime import datetime, timezone

def read_json_lines(path):
    if not os.path.isfile(path):
        return []
    lines = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                lines.append(obj)
            except json.JSONDecodeError:
                # skip invalid JSON lines
                continue
    return lines

def parse_iso8601(ts):
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    # Handle 'Z' suffix
    if s.endswith('Z'):
        s2 = s[:-1] + '+00:00'
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except Exception:
        return None
    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (isinstance(x, float) and math.isnan(x))

def to_float_if_number(x):
    if is_number(x):
        return float(x)
    return None

def to_int_or_zero(x):
    if is_number(x):
        try:
            return int(x)
        except Exception:
            return 0
    return 0

def median(values):
    n = len(values)
    if n == 0:
        return 0.0
    vals = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return (vals[mid - 1] + vals[mid]) / 2.0

def round_safe(val, digits):
    # Ensure consistent rounding behavior
    return round(val, digits)

def compute_expected_from_input(input_path):
    json_objs = read_json_lines(input_path)
    valid_snapshots = []
    for obj in json_objs:
        ts = obj.get("timestamp")
        dt = parse_iso8601(ts)
        if dt is None:
            continue
        valid_snapshots.append((obj, dt, ts))

    snapshot_count = len(valid_snapshots)

    # Determine earliest and latest timestamps (keep original strings for output)
    if snapshot_count > 0:
        # Use epoch for comparison
        def to_epoch(d):
            return d.timestamp()
        # Find min and max by epoch, tie-breaker by lexicographic timestamp string
        earliest = min(valid_snapshots, key=lambda tup: (to_epoch(tup[1]), tup[2]))
        latest = max(valid_snapshots, key=lambda tup: (to_epoch(tup[1]), tup[2]))
        first_timestamp = earliest[2]
        last_timestamp = latest[2]
    else:
        first_timestamp = ""
        last_timestamp = ""

    # Miner IP majority (tie-break lexicographically)
    ip_counter = Counter()
    for obj, _, _ in valid_snapshots:
        ip = obj.get("ip")
        if isinstance(ip, str):
            ip_counter[ip] += 1
    if ip_counter:
        max_count = max(ip_counter.values())
        candidates = [ip for ip, cnt in ip_counter.items() if cnt == max_count]
        miner_ip = sorted(candidates)[0]
    else:
        miner_ip = ""

    # Sums for shares
    shares_accepted = 0
    shares_rejected = 0

    # Lists for averages and medians
    hash_rates = []
    hash_rates_1m = []
    hash_rates_10m = []
    powers = []
    temps = []
    wifi_rssi_vals = []

    # Max bestDiff
    best_bestDiff_present = False
    best_bestDiff_val = 0.0

    # Alerts tracking
    any_overheat = False
    any_fan_failure = False
    any_pool_disconnected = False

    for obj, _, _ in valid_snapshots:
        # shares
        shares_accepted += to_int_or_zero(obj.get("sharesAccepted"))
        shares_rejected += to_int_or_zero(obj.get("sharesRejected"))

        # hash rates
        v = to_float_if_number(obj.get("hashRate"))
        if v is not None and math.isfinite(v):
            hash_rates.append(v)
        v = to_float_if_number(obj.get("hashRate_1m"))
        if v is not None and math.isfinite(v):
            hash_rates_1m.append(v)
        v = to_float_if_number(obj.get("hashRate_10m"))
        if v is not None and math.isfinite(v):
            hash_rates_10m.append(v)

        # power
        v = to_float_if_number(obj.get("power"))
        if v is not None and math.isfinite(v):
            powers.append(v)

        # temp (ignore -1)
        v = to_float_if_number(obj.get("temp"))
        if v is not None and math.isfinite(v) and v != -1:
            temps.append(v)

        # wifiRSSI
        v = to_float_if_number(obj.get("wifiRSSI"))
        if v is not None and math.isfinite(v):
            wifi_rssi_vals.append(v)

        # bestDiff
        v = to_float_if_number(obj.get("bestDiff"))
        if v is not None and math.isfinite(v):
            if not best_bestDiff_present:
                best_bestDiff_val = v
                best_bestDiff_present = True
            else:
                if v > best_bestDiff_val:
                    best_bestDiff_val = v

        # Alerts
        # OVERHEAT: any temp > 85
        tv = to_float_if_number(obj.get("temp"))
        if tv is not None and math.isfinite(tv) and tv > 85:
            any_overheat = True

        # FAN_FAILURE_SUSPECTED: fanspeed < 20 while temp > 70
        fv = to_float_if_number(obj.get("fanspeed"))
        if (fv is not None and math.isfinite(fv) and fv < 20) and (tv is not None and math.isfinite(tv) and tv > 70):
            any_fan_failure = True

        # POOL_DISCONNECTED: missing/empty stratumURL OR stratumPort is 0 or missing
        url = obj.get("stratumURL", None)
        url_missing_or_empty = True
        if isinstance(url, str):
            if url.strip() != "":
                url_missing_or_empty = False

        port = obj.get("stratumPort", None)
        port_missing = False
        port_is_zero = False
        if port is None:
            port_missing = True
        else:
            if is_number(port):
                port_is_zero = (int(port) == 0)
            elif isinstance(port, str):
                pstrip = port.strip()
                if pstrip == "":
                    port_missing = True
                else:
                    try:
                        pint = int(pstrip)
                        port_is_zero = (pint == 0)
                    except Exception:
                        port_missing = True
            else:
                port_missing = True

        if url_missing_or_empty or port_missing or port_is_zero:
            any_pool_disconnected = True

    # Averages
    def mean_or_zero(values):
        if len(values) == 0:
            return 0.0
        return sum(values) / len(values)

    avg_hashrate_raw = mean_or_zero(hash_rates)
    avg_hashrate_1m_raw = mean_or_zero(hash_rates_1m)
    avg_hashrate_10m_raw = mean_or_zero(hash_rates_10m)
    avg_power_raw = mean_or_zero(powers)
    avg_temp_raw = mean_or_zero(temps)
    max_temp_raw = max(temps) if temps else 0.0
    min_temp_raw = min(temps) if temps else 0.0

    # Rounding
    avg_hashrate = round_safe(avg_hashrate_raw, 2)
    avg_hashrate_1m = round_safe(avg_hashrate_1m_raw, 2)
    avg_hashrate_10m = round_safe(avg_hashrate_10m_raw, 2)
    avg_power = round_safe(avg_power_raw, 2)
    avg_temp = round_safe(avg_temp_raw, 2)
    max_temp = round_safe(max_temp_raw, 2)
    min_temp = round_safe(min_temp_raw, 2)

    # reject rate
    denom = shares_accepted + shares_rejected
    if denom > 0:
        reject_rate = round_safe(shares_rejected / denom, 4)
    else:
        reject_rate = 0.0

    # wifi median rounded to 1 decimal
    median_wifiRSSI_raw = median(wifi_rssi_vals)
    median_wifiRSSI = round_safe(median_wifiRSSI_raw, 1)

    # best_bestDiff
    best_bestDiff = best_bestDiff_val if best_bestDiff_present else 0

    # efficiency
    if avg_power == 0.0:
        efficiency = 0.0
    else:
        efficiency = round_safe(avg_hashrate / avg_power, 3)

    # Alerts using computed summary where required
    alerts = set()
    if any_overheat:
        alerts.add("OVERHEAT")
    if any_fan_failure:
        alerts.add("FAN_FAILURE_SUSPECTED")
    if any_pool_disconnected:
        alerts.add("POOL_DISCONNECTED")
    if reject_rate > 0.05:
        alerts.add("HIGH_REJECT_RATE")
    if avg_hashrate_10m < 200:
        alerts.add("LOW_HASHRATE_10M")
    if median_wifiRSSI < -70:
        alerts.add("WEAK_WIFI")

    expected_summary = {
        "miner_ip": miner_ip,
        "snapshot_count": snapshot_count,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "shares_accepted": shares_accepted,
        "shares_rejected": shares_rejected,
        "reject_rate": reject_rate,
        "avg_hashrate": avg_hashrate,
        "avg_hashrate_1m": avg_hashrate_1m,
        "avg_hashrate_10m": avg_hashrate_10m,
        "avg_power": avg_power,
        "avg_temp": avg_temp,
        "max_temp": max_temp,
        "min_temp": min_temp,
        "best_bestDiff": best_bestDiff,
        "median_wifiRSSI": median_wifiRSSI,
        "efficiency_gh_per_w": efficiency,
    }
    return expected_summary, alerts

def load_json_file(path):
    if not os.path.isfile(path):
        return None, "missing"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    if not os.path.isfile(path):
        return None, "missing"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content, None
    except Exception as e:
        return None, str(e)

def keys_exact(dct, required_keys):
    if not isinstance(dct, dict):
        return False
    return set(dct.keys()) == set(required_keys)

def almost_equal(a, b, tol):
    return abs(a - b) <= tol

def verify_summary(summary, expected):
    # keys
    required_keys = [
        "miner_ip",
        "snapshot_count",
        "first_timestamp",
        "last_timestamp",
        "shares_accepted",
        "shares_rejected",
        "reject_rate",
        "avg_hashrate",
        "avg_hashrate_1m",
        "avg_hashrate_10m",
        "avg_power",
        "avg_temp",
        "max_temp",
        "min_temp",
        "best_bestDiff",
        "median_wifiRSSI",
        "efficiency_gh_per_w",
    ]
    res = {}
    res["summary_keys_exact"] = keys_exact(summary, required_keys)

    # Only attempt value comparisons if keys are exact
    vals_ok = True
    if res["summary_keys_exact"]:
        # exact equality for strings/ints
        vals_ok = (
            summary.get("miner_ip") == expected.get("miner_ip")
            and summary.get("snapshot_count") == expected.get("snapshot_count")
            and summary.get("first_timestamp") == expected.get("first_timestamp")
            and summary.get("last_timestamp") == expected.get("last_timestamp")
            and summary.get("shares_accepted") == expected.get("shares_accepted")
            and summary.get("shares_rejected") == expected.get("shares_rejected")
        )
        # floats with tolerances
        if vals_ok:
            float_checks = [
                ("reject_rate", 0.0005),
                ("avg_hashrate", 0.01),
                ("avg_hashrate_1m", 0.01),
                ("avg_hashrate_10m", 0.01),
                ("avg_power", 0.01),
                ("avg_temp", 0.01),
                ("max_temp", 0.01),
                ("min_temp", 0.01),
                ("median_wifiRSSI", 0.1),
                ("efficiency_gh_per_w", 0.0015),
            ]
            for key, tol in float_checks:
                sv = summary.get(key)
                ev = expected.get(key)
                try:
                    s_f = float(sv)
                    e_f = float(ev)
                except Exception:
                    vals_ok = False
                    break
                if not almost_equal(s_f, e_f, tol):
                    vals_ok = False
                    break
            # best_bestDiff: exact numeric match
            if vals_ok:
                sb = summary.get("best_bestDiff")
                eb = expected.get("best_bestDiff")
                try:
                    # direct comparison allowing tiny float noise
                    vals_ok = abs(float(sb) - float(eb)) <= 1e-9
                except Exception:
                    vals_ok = False
    else:
        vals_ok = False
    res["summary_values_match"] = vals_ok
    return res

def parse_alerts_file(content):
    # Return set of codes, ignoring empty lines and whitespace
    lines = [ln.strip() for ln in content.splitlines()]
    codes = [ln for ln in lines if ln != ""]
    return set(codes), codes  # set and original list order

def verify_alerts(alerts_content, expected_alerts):
    allowed = {
        "OVERHEAT",
        "FAN_FAILURE_SUSPECTED",
        "POOL_DISCONNECTED",
        "HIGH_REJECT_RATE",
        "LOW_HASHRATE_10M",
        "WEAK_WIFI",
    }
    codes_set, codes_list = parse_alerts_file(alerts_content)
    # Check that all codes are allowed and there are no duplicates beyond set size
    only_allowed = all(code in allowed for code in codes_set) and all(code in allowed or code.strip() == "" for code in codes_list)
    no_duplicates = len(codes_set) == len([c for c in codes_list if c != ""])
    exact_match = codes_set == expected_alerts
    return {
        "alerts_only_allowed": only_allowed,
        "alerts_no_duplicates": no_duplicates,
        "alerts_match_expected": exact_match and only_allowed and no_duplicates,
    }

def extract_number_from_line(line):
    # Extract first float-like number from a string
    m = re.search(r'[-+]?\d+(?:\.\d+)?', line)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def verify_report(report_content, summary):
    lines = report_content.splitlines()
    # Presence of required labeled lines
    def find_line(prefix):
        for ln in lines:
            if ln.strip().startswith(prefix):
                return ln
        return None

    miner_line = find_line("Miner IP:")
    snapshot_line = find_line("Snapshot count:")
    time_line = find_line("Time range:")
    hashrate_line = any("Hashrate (GH/s):" in ln for ln in lines)
    power_line = any("Power (W):" in ln for ln in lines)
    temp_line = any("Temperature (°C):" in ln for ln in lines)
    shares_line = any("Shares:" in ln for ln in lines)
    wifi_line = any("WiFi RSSI (dBm):" in ln for ln in lines)
    eff_line_obj = find_line("Efficiency (GH/s per W):")

    required_present = all([
        miner_line is not None,
        snapshot_line is not None,
        time_line is not None,
        hashrate_line,
        power_line,
        temp_line,
        shares_line,
        wifi_line,
        eff_line_obj is not None,
    ])

    # If summary not available, cannot check consistency
    consistent = False
    if required_present and isinstance(summary, dict):
        miner_val = miner_line.split(":", 1)[1].strip() if ":" in miner_line else ""
        snapshot_num = extract_number_from_line(snapshot_line)
        # Check time range includes both timestamps from summary.json
        ft = summary.get("first_timestamp", "")
        lt = summary.get("last_timestamp", "")
        time_contains = (ft in time_line) and (lt in time_line)

        # Efficiency matches within tolerance
        eff_val = extract_number_from_line(eff_line_obj)
        eff_summary = summary.get("efficiency_gh_per_w")
        try:
            eff_match = eff_val is not None and eff_summary is not None and almost_equal(float(eff_val), float(eff_summary), 0.0015)
        except Exception:
            eff_match = False

        consistent = (
            miner_val == summary.get("miner_ip") and
            snapshot_num is not None and int(snapshot_num) == summary.get("snapshot_count") and
            time_contains and
            eff_match
        )

    return {
        "report_required_lines_present": required_present,
        "report_values_consistent_with_summary": consistent
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "summary_exists": False,
        "summary_json_valid": False,
        "summary_keys_exact": False,
        "summary_values_match": False,
        "alerts_exists": False,
        "alerts_only_allowed": False,
        "alerts_no_duplicates": False,
        "alerts_match_expected": False,
        "report_exists": False,
        "report_required_lines_present": False,
        "report_values_consistent_with_summary": False,
    }

    input_path = os.path.join(input_dir, "snapshots.jsonl")
    if not os.path.isfile(input_path):
        # If input missing, cannot award any credit
        print(json.dumps({"reward": 0.0, **checks}))
        return

    expected_summary, expected_alerts = compute_expected_from_input(input_path)

    # summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary_data, summary_err = load_json_file(summary_path)
    if summary_data is not None and summary_err is None:
        checks["summary_exists"] = True
        if isinstance(summary_data, dict):
            checks["summary_json_valid"] = True
            summary_ver = verify_summary(summary_data, expected_summary)
            checks.update(summary_ver)
        else:
            checks["summary_json_valid"] = False

    # alerts.txt
    alerts_path = os.path.join(output_dir, "alerts.txt")
    alerts_content, alerts_err = read_text_file(alerts_path)
    if alerts_content is not None and alerts_err is None:
        checks["alerts_exists"] = True
        alerts_ver = verify_alerts(alerts_content, expected_alerts)
        checks.update(alerts_ver)

    # report.txt
    report_path = os.path.join(output_dir, "report.txt")
    report_content, report_err = read_text_file(report_path)
    if report_content is not None and report_err is None:
        checks["report_exists"] = True
        # For consistency checks that compare to summary.json, require summary_json_valid True
        if checks["summary_json_valid"]:
            report_ver = verify_report(report_content, summary_data)
        else:
            report_ver = {"report_required_lines_present": False, "report_values_consistent_with_summary": False}
        checks.update(report_ver)

    # Compute reward as fraction of passed checks
    # Only count checks that depend on outputs
    check_keys_for_reward = [
        "summary_exists",
        "summary_json_valid",
        "summary_keys_exact",
        "summary_values_match",
        "alerts_exists",
        "alerts_only_allowed",
        "alerts_no_duplicates",
        "alerts_match_expected",
        "report_exists",
        "report_required_lines_present",
        "report_values_consistent_with_summary",
    ]
    total = len(check_keys_for_reward)
    passed = sum(1 for k in check_keys_for_reward if checks.get(k, False))
    reward = 0.0 if passed == 0 else passed / total
    # No-op baseline: if output dir missing or empty, ensure 0.0
    outputs_present = any(os.path.isfile(os.path.join(output_dir, fn)) for fn in ["summary.json", "alerts.txt", "report.txt"])
    if not outputs_present:
        reward = 0.0

    print(json.dumps({"reward": round(reward, 6), **checks}))

if __name__ == "__main__":
    main()