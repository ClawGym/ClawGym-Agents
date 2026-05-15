import json
import os
import sys
import csv
from datetime import datetime, timezone, timedelta

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abs_path(root, *parts):
    return os.path.join(root, *parts)

def parse_iso8601(ts_str):
    s = ts_str.strip()
    # Replace Z with +00:00 for fromisoformat compatibility
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Handle space separator
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Fallback attempts with common patterns
        fmts = [
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]
        for fmt in fmts:
            try:
                dt = datetime.strptime(s, fmt)
                # Assume naive times are UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
        raise

def fmt_time_of_day(dt):
    # dt may be timezone-aware or naive; use its own hour/min/sec/microsecond
    h = str(dt.hour).zfill(2)
    m = str(dt.minute).zfill(2)
    s = str(dt.second).zfill(2)
    ms = str(int(dt.microsecond / 1000)).zfill(3)
    return f"{h}:{m}:{s}.{ms}"

def format_latency(ms):
    # ms is a float milliseconds
    if ms < 1000:
        return f"{int(round(ms))}ms"
    elif ms < 60000:
        return f"{ms/1000:.2f}s"
    else:
        return f"{ms/60000:.2f}min"

def read_jsonl(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            events.append(obj)
    return events

def compute_health_expected(input_health_path):
    events = read_jsonl(input_health_path)
    # Build list with parsed datetimes and original strings
    parsed = []
    for ev in events:
        ts_str = ev.get("timestamp")
        if not ts_str:
            continue
        dt = parse_iso8601(ts_str)
        # Normalize naive timestamps to UTC for calculations
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        parsed.append((dt, ts_str, ev))
    # Sort by datetime
    parsed.sort(key=lambda x: x[0])

    actions = []
    last_restart_dt = None
    current_hour_marker = None
    current_hour_restart_count = 0

    for dt, ts_str, ev in parsed:
        # Determine hour marker of this event
        hour_marker = dt.strftime("%Y%m%d%H")
        if current_hour_marker != hour_marker:
            current_hour_marker = hour_marker
            current_hour_restart_count = 0

        # Conditions for restart
        if ev.get("gateway_status") == "failed" and (ev.get("http_ok") is False):
            cooldown_ok = True
            if last_restart_dt is not None:
                diff = (dt - last_restart_dt).total_seconds()
                cooldown_ok = diff >= 180.0
            rate_ok = current_hour_restart_count < 5
            if cooldown_ok and rate_ok:
                actions.append(ts_str)
                last_restart_dt = dt
                current_hour_restart_count += 1

    # Determine final hour marker as hour of last event if any, else None
    final_hour_marker = parsed[-1][0].strftime("%Y%m%d%H") if parsed else None

    # last_restart epoch seconds or null
    if last_restart_dt is None:
        last_restart_epoch = None
    else:
        # Use integer epoch seconds
        last_restart_epoch = int(last_restart_dt.timestamp())

    # restart_count is number of restarts in the final hour
    # We already have current_hour_restart_count at the end of loop for final hour
    restart_count = current_hour_restart_count if parsed else 0

    expected_state = {
        "last_restart": last_restart_epoch,
        "restart_count": restart_count,
        "hour_marker": final_hour_marker
    }

    return actions, expected_state

def compute_gpu_alerts_expected(gpu_csv_path):
    overheat = False
    power_capped = False
    oom_risk = False
    if not os.path.isfile(gpu_csv_path):
        return overheat, power_capped, oom_risk

    with open(gpu_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalize headers to lower-case for robust access
        headers = [h.lower() for h in reader.fieldnames] if reader.fieldnames else []
        has_pwr_cap = "pwr_cap" in headers
        for row in reader:
            # Lowercase keys for consistent access
            lr = {k.lower(): v for k, v in row.items()}
            # temp
            if "temp" in lr:
                try:
                    t = float(str(lr["temp"]).strip())
                    if t >= 85:
                        overheat = True
                except Exception:
                    pass
            # mem
            if "mem" in lr:
                try:
                    memv = float(str(lr["mem"]).strip())
                    if memv >= 95:
                        oom_risk = True
                except Exception:
                    pass
            # pwr_cap
            if has_pwr_cap and "pwr_cap" in lr:
                val = str(lr["pwr_cap"]).strip()
                try:
                    if int(float(val)) == 1:
                        power_capped = True
                except Exception:
                    # Non-numeric values: treat as False
                    pass
    # If pwr_cap column is absent, explicitly set False
    if not has_pwr_cap:
        power_capped = False
    return overheat, power_capped, oom_risk

def compute_ping_report_expected(pings_csv_path):
    # Returns the expected full text for ping_report.txt
    blocks = []
    with open(pings_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            model = row.get("model", "").strip()
            start_ts = row.get("start_ts", "").strip()
            end_ts = row.get("end_ts", "").strip()
            if not model or not start_ts or not end_ts:
                continue
            dt_start = parse_iso8601(start_ts)
            dt_end = parse_iso8601(end_ts)
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=timezone.utc)
            if dt_end.tzinfo is None:
                dt_end = dt_end.replace(tzinfo=timezone.utc)
            sent_str = fmt_time_of_day(dt_start)
            recv_str = fmt_time_of_day(dt_end)
            delta_ms = (dt_end - dt_start).total_seconds() * 1000.0
            # Prevent negative duration formatting; if negative, still format absolute?
            # We will keep as is (could be negative), but clamp to zero minimum for display
            if delta_ms < 0:
                delta_ms = 0.0
            latency_str = format_latency(delta_ms)
            # Build block lines
            block_lines = [
                f"🧪 PING {model}",
                "",
                f"📤 Sent:     {sent_str}",
                f"📥 Received: {recv_str}",
                f"⏱️  Latency:  {latency_str}",
                "",
                "🎯 Pong!",
            ]
            blocks.append("\n".join(block_lines))
    return "\n".join(blocks)

def compute_poe_summary_expected(currency_json_path, items_json_path):
    # Currency section
    currency_header = "name,chaosEquivalent,pay_listing_count,paySparkLine_totalChange"
    items_header = "name,chaosValue,divineValue,sparkline_totalChange,listingCount"
    lines_out = [currency_header]
    try:
        with open(currency_json_path, "r", encoding="utf-8") as f:
            currency_data = json.load(f)
        found_divine = None
        for line in currency_data.get("lines", []):
            if line.get("currencyTypeName") == "Divine Orb":
                found_divine = line
                break
        if found_divine is not None:
            name = found_divine.get("currencyTypeName", "")
            chaos_eq = found_divine.get("chaosEquivalent", "")
            pay = found_divine.get("pay", {}) if isinstance(found_divine.get("pay", {}), dict) else {}
            pay_listing_count = pay.get("listing_count", "")
            pay_spark = found_divine.get("paySparkLine", {}) if isinstance(found_divine.get("paySparkLine", {}), dict) else {}
            total_change = pay_spark.get("totalChange", "")
            lines_out.append(f"{name},{chaos_eq},{pay_listing_count},{total_change}")
    except Exception:
        # If parsing fails, just include the header per spec
        pass

    # Blank line separator
    lines_out.append("")

    # Items section
    lines_out.append(items_header)
    try:
        with open(items_json_path, "r", encoding="utf-8") as f:
            items_data = json.load(f)
        item_lines = items_data.get("lines", [])
        # Sort by chaosValue descending
        def get_chaos(x):
            try:
                return float(x.get("chaosValue", 0))
            except Exception:
                return 0.0
        sorted_items = sorted(item_lines, key=get_chaos, reverse=True)
        top = sorted_items[:3]
        for it in top:
            name = it.get("name", "")
            chaos = it.get("chaosValue", "")
            divine = it.get("divineValue", "")
            spark = it.get("sparkline", {}) if isinstance(it.get("sparkline", {}), dict) else {}
            total_change = spark.get("totalChange", "")
            listing = it.get("listingCount", "")
            lines_out.append(f"{name},{chaos},{divine},{total_change},{listing}")
    except Exception:
        # If parse error, only header remains
        pass

    return "\n".join(lines_out)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def main():
    root = get_workspace_root()
    input_dir = abs_path(root, "input")
    output_dir = abs_path(root, "output")

    # Paths
    health_path = abs_path(input_dir, "health_checks.jsonl")
    gpu_path = abs_path(input_dir, "gpu_dmon.csv")
    pings_path = abs_path(input_dir, "model_pings.csv")
    currency_path = abs_path(input_dir, "poe_currency.json")
    items_path = abs_path(input_dir, "poe_items.json")

    actions_out_path = abs_path(output_dir, "actions.json")
    state_out_path = abs_path(output_dir, "state.json")
    gpu_alerts_out_path = abs_path(output_dir, "gpu_alerts.json")
    ping_report_out_path = abs_path(output_dir, "ping_report.txt")
    poe_summary_out_path = abs_path(output_dir, "poe_summary.csv")

    checks = {
        "actions_json_exists": False,
        "actions_json_correct": False,
        "state_json_exists": False,
        "state_json_correct": False,
        "gpu_alerts_json_exists": False,
        "gpu_alerts_json_correct": False,
        "ping_report_txt_exists": False,
        "ping_report_txt_correct": False,
        "poe_summary_csv_exists": False,
        "poe_summary_csv_correct": False,
    }

    # Compute expected values
    try:
        expected_actions, expected_state = compute_health_expected(health_path)
    except Exception:
        expected_actions, expected_state = None, None

    try:
        expected_overheat, expected_power_capped, expected_oom = compute_gpu_alerts_expected(gpu_path)
    except Exception:
        expected_overheat = expected_power_capped = expected_oom = None

    try:
        expected_ping_text = compute_ping_report_expected(pings_path)
    except Exception:
        expected_ping_text = None

    try:
        expected_poe_summary = compute_poe_summary_expected(currency_path, items_path)
    except Exception:
        expected_poe_summary = None

    # Check actions.json
    if os.path.isfile(actions_out_path):
        checks["actions_json_exists"] = True
        try:
            with open(actions_out_path, "r", encoding="utf-8") as f:
                agent_actions = json.load(f)
            if isinstance(agent_actions, list) and expected_actions is not None:
                # Compare lists exactly
                checks["actions_json_correct"] = agent_actions == expected_actions
        except Exception:
            checks["actions_json_correct"] = False

    # Check state.json
    if os.path.isfile(state_out_path):
        checks["state_json_exists"] = True
        try:
            with open(state_out_path, "r", encoding="utf-8") as f:
                agent_state = json.load(f)
            if isinstance(agent_state, dict) and expected_state is not None:
                # Compare specific fields exactly
                ls_a = agent_state.get("last_restart", None)
                rc_a = agent_state.get("restart_count", None)
                hm_a = agent_state.get("hour_marker", None)
                ls_e = expected_state.get("last_restart", None)
                rc_e = expected_state.get("restart_count", None)
                hm_e = expected_state.get("hour_marker", None)
                checks["state_json_correct"] = (ls_a == ls_e and rc_a == rc_e and hm_a == hm_e)
        except Exception:
            checks["state_json_correct"] = False

    # Check gpu_alerts.json
    if os.path.isfile(gpu_alerts_out_path):
        checks["gpu_alerts_json_exists"] = True
        try:
            with open(gpu_alerts_out_path, "r", encoding="utf-8") as f:
                agent_gpu = json.load(f)
            if isinstance(agent_gpu, dict) and expected_overheat is not None:
                over_a = agent_gpu.get("overheat", None)
                cap_a = agent_gpu.get("power_capped", None)
                oom_a = agent_gpu.get("oom_risk", None)
                checks["gpu_alerts_json_correct"] = (over_a is expected_overheat) and (cap_a is expected_power_capped) and (oom_a is expected_oom)
        except Exception:
            checks["gpu_alerts_json_correct"] = False

    # Check ping_report.txt
    if os.path.isfile(ping_report_out_path):
        checks["ping_report_txt_exists"] = True
        try:
            agent_text = read_text(ping_report_out_path)
            if expected_ping_text is not None:
                # Compare normalized by stripping trailing newlines
                checks["ping_report_txt_correct"] = agent_text.rstrip("\n") == expected_ping_text.rstrip("\n")
        except Exception:
            checks["ping_report_txt_correct"] = False

    # Check poe_summary.csv
    if os.path.isfile(poe_summary_out_path):
        checks["poe_summary_csv_exists"] = True
        try:
            agent_csv = read_text(poe_summary_out_path)
            if expected_poe_summary is not None:
                checks["poe_summary_csv_correct"] = agent_csv.rstrip("\n") == expected_poe_summary.rstrip("\n")
        except Exception:
            checks["poe_summary_csv_correct"] = False

    # Compute reward: average of correctness across the five main deliverables
    correctness_flags = [
        checks["actions_json_correct"],
        checks["state_json_correct"],
        checks["gpu_alerts_json_correct"],
        checks["ping_report_txt_correct"],
        checks["poe_summary_csv_correct"],
    ]
    passed = sum(1 for x in correctness_flags if x)
    reward = passed / float(len(correctness_flags)) if correctness_flags else 0.0

    # No-op baseline: if output dir missing or empty or none correct, reward should be 0.0
    # The above already results in 0.0 if none correct
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()