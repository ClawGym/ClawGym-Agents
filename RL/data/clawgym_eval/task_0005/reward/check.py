import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def extract_hours(obj: Any) -> List[Dict[str, Any]]:
    # Accept either a top-level list of hour dicts or common container keys
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for key in ["hours", "hourly", "data", "forecast", "entries"]:
            if key in obj and isinstance(obj[key], list):
                return [x for x in obj[key] if isinstance(x, dict)]
        # Fallback: find the first list of dicts that contain 'time' keys
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "time" in v[0]:
                return v
    return []

def meets_hour_conditions(hour: Dict[str, Any], thr: Dict[str, Any]) -> bool:
    try:
        wind_ok = float(hour.get("wind_speed_10m_mph", float("inf"))) <= float(thr["wind_max_mph"])
        gust_ok = float(hour.get("wind_gusts_10m_mph", float("inf"))) <= float(thr["gust_max_mph"])
        temp = float(hour.get("temperature_F", float("nan")))
        temp_ok = float(thr["min_temp_F"]) <= temp <= float(thr["max_temp_F"])
        rain_ok = float(hour.get("rain_probability_pct", float("inf"))) <= float(thr["rain_prob_max_pct"])
        return wind_ok and gust_ok and temp_ok and rain_ok
    except Exception:
        return False

def check_post_window_dry(hours: List[Dict[str, Any]], start_idx: int, win_len: int, dry_len: int, thr: Dict[str, Any]) -> bool:
    # Require exactly dry_len hours immediately after window; must all satisfy rain prob <= threshold
    end_idx = start_idx + win_len
    if end_idx + dry_len > len(hours):
        return False
    max_rain = float(thr["rain_prob_max_pct"])
    for i in range(end_idx, end_idx + dry_len):
        try:
            rp = float(hours[i].get("rain_probability_pct", float("inf")))
        except Exception:
            return False
        if rp > max_rain:
            return False
    return True

def sliding_windows(hours: List[Dict[str, Any]], thr: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        win_len = int(thr["window_hours"])
        dry_len = int(thr["post_window_dry_hours"])
    except Exception:
        return []
    n = len(hours)
    candidates: List[Dict[str, Any]] = []
    for i in range(0, n - win_len + 1):
        hseg = hours[i:i+win_len]
        # Ensure all hours meet conditions
        if not all(meets_hour_conditions(h, thr) for h in hseg):
            continue
        # Post-window dryness
        dry_ok = check_post_window_dry(hours, i, win_len, dry_len, thr)
        if not dry_ok:
            continue
        # Compute metrics
        temps: List[float] = []
        winds: List[float] = []
        gusts: List[float] = []
        for h in hseg:
            try:
                temps.append(float(h.get("temperature_F", float("nan"))))
            except Exception:
                temps.append(float("nan"))
            try:
                winds.append(float(h.get("wind_speed_10m_mph", float("nan"))))
            except Exception:
                winds.append(float("nan"))
            try:
                gusts.append(float(h.get("wind_gusts_10m_mph", float("nan"))))
            except Exception:
                gusts.append(float("nan"))
        if any([t != t for t in temps]):  # NaN check
            continue
        avg_temp = sum(temps) / len(temps) if temps else float("nan")
        max_wind = max(winds) if winds else float("nan")
        max_gust = max(gusts) if gusts else float("nan")
        start_time = str(hseg[0].get("time", ""))
        end_time = str(hseg[-1].get("time", ""))
        candidates.append({
            "start_idx": i,
            "start_time": start_time,
            "end_time": end_time,
            "avg_temp_F": avg_temp,
            "max_wind_mph": max_wind,
            "max_gust_mph": max_gust,
            "dry_post_hours_ok": True,
            "hour_count": win_len
        })
    # Select earliest; if tie on start_idx, pick highest avg temperature
    if not candidates:
        return []
    candidates.sort(key=lambda x: (x["start_idx"], -x["avg_temp_F"]))
    return [candidates[0]]

def float_close(a: float, b: float, tol: float = 0.1) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_csv_line(line: str) -> List[str]:
    # Simple CSV without quoted commas
    return [part.strip() for part in line.strip().split(",")]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks: Dict[str, bool] = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_two_lines": False,
        "csv_start_time_ok": False,
        "csv_end_time_ok": False,
        "csv_avg_temp_ok": False,
        "csv_max_wind_ok": False,
        "csv_max_gust_ok": False,
        "csv_dry_flag_ok": False,
        "summary_exists": False,
        "summary_valid_json": False,
        "summary_field_id_ok": False,
        "summary_thresholds_match": False,
        "summary_selected_times_ok": False,
        "summary_hour_count_ok": False,
        "summary_avg_temp_ok": False,
        "summary_max_wind_ok": False,
        "summary_max_gust_ok": False,
        "summary_checked_hours_ok": False,
        "csv_json_consistent": False
    }

    # Paths
    forecast_path = os.path.join(input_dir, "field_14_forecast_hourly.json")
    thresholds_path = os.path.join(input_dir, "spray_thresholds.json")
    csv_path = os.path.join(output_dir, "spray_plan.csv")
    summary_path = os.path.join(output_dir, "summary.json")

    # Read inputs
    forecast_json = read_json(forecast_path)
    thresholds_json = read_json(thresholds_path)

    # Compute expected window from inputs
    expected_window: Optional[Dict[str, Any]] = None
    hours: List[Dict[str, Any]] = []
    window_hours = None
    checked_hours_count = None
    if isinstance(thresholds_json, dict) and forecast_json is not None:
        hours = extract_hours(forecast_json)
        checked_hours_count = len(hours)
        try:
            # Sliding window selection
            wins = sliding_windows(hours, thresholds_json)
            if wins:
                expected_window = wins[0]
                # Round avg_temp_F to one decimal for comparison to CSV formatted value
                expected_window["avg_temp_F_rounded"] = round(expected_window["avg_temp_F"] + 1e-9, 1)
            window_hours = int(thresholds_json.get("window_hours")) if "window_hours" in thresholds_json else None
        except Exception:
            expected_window = None

    # Validate CSV
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                raw_lines = f.read().splitlines()
            # Filter out purely empty lines
            lines = [ln for ln in raw_lines if ln.strip() != ""]
            if len(lines) == 2:
                checks["csv_two_lines"] = True
            header_expected = "start_time,end_time,avg_temp_F,max_wind_mph,max_gust_mph,dry_post_hours_ok"
            if lines:
                if lines[0].strip() == header_expected:
                    checks["csv_header_ok"] = True
            # If we have expected window computed and there is a data line, validate contents
            if len(lines) >= 2 and expected_window is not None:
                data_fields = parse_csv_line(lines[1])
                if len(data_fields) == 6:
                    csv_start, csv_end, csv_avg_s, csv_max_wind_s, csv_max_gust_s, csv_dry = data_fields
                    # Start/end times
                    if csv_start == expected_window.get("start_time", ""):
                        checks["csv_start_time_ok"] = True
                    if csv_end == expected_window.get("end_time", ""):
                        checks["csv_end_time_ok"] = True
                    # Numeric comparisons
                    try:
                        csv_avg = float(csv_avg_s)
                        exp_avg = expected_window["avg_temp_F_rounded"]
                        if float_close(csv_avg, exp_avg, tol=0.11):
                            checks["csv_avg_temp_ok"] = True
                    except Exception:
                        pass
                    try:
                        csv_max_wind = float(csv_max_wind_s)
                        if float_close(csv_max_wind, float(expected_window["max_wind_mph"]), tol=0.01):
                            checks["csv_max_wind_ok"] = True
                    except Exception:
                        pass
                    try:
                        csv_max_gust = float(csv_max_gust_s)
                        if float_close(csv_max_gust, float(expected_window["max_gust_mph"]), tol=0.01):
                            checks["csv_max_gust_ok"] = True
                    except Exception:
                        pass
                    # Dry flag (should be "yes" if the window was chosen)
                    dry_flag_ok = csv_dry.strip().lower() == ("yes" if expected_window.get("dry_post_hours_ok", False) else "no")
                    if dry_flag_ok:
                        checks["csv_dry_flag_ok"] = True
        except Exception:
            # Leave CSV-related checks as-is (False)
            pass

    # Validate summary.json
    summary_data = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            summary_data = read_json(summary_path)
            if isinstance(summary_data, dict):
                checks["summary_valid_json"] = True
                # field_id
                if summary_data.get("field_id") == 14:
                    checks["summary_field_id_ok"] = True
                # thresholds_used match input exactly (deep equality by canonical JSON)
                if isinstance(thresholds_json, dict) and "thresholds_used" in summary_data:
                    try:
                        t_in = json.dumps(thresholds_json, sort_keys=True)
                        t_out = json.dumps(summary_data["thresholds_used"], sort_keys=True)
                        if t_in == t_out:
                            checks["summary_thresholds_match"] = True
                    except Exception:
                        pass
                # selected_window checks
                sel = summary_data.get("selected_window")
                if isinstance(sel, dict) and expected_window is not None:
                    times_ok = (sel.get("start_time") == expected_window.get("start_time")) and (sel.get("end_time") == expected_window.get("end_time"))
                    if times_ok:
                        checks["summary_selected_times_ok"] = True
                    # hour_count
                    try:
                        if window_hours is not None and int(sel.get("hour_count")) == int(window_hours):
                            checks["summary_hour_count_ok"] = True
                    except Exception:
                        pass
                    # avg temp
                    try:
                        if float_close(float(sel.get("avg_temp_F")), float(expected_window["avg_temp_F_rounded"]), tol=0.11):
                            checks["summary_avg_temp_ok"] = True
                    except Exception:
                        pass
                    # max wind/gust
                    try:
                        if float_close(float(sel.get("max_wind_mph")), float(expected_window["max_wind_mph"]), tol=0.01):
                            checks["summary_max_wind_ok"] = True
                    except Exception:
                        pass
                    try:
                        if float_close(float(sel.get("max_gust_mph")), float(expected_window["max_gust_mph"]), tol=0.01):
                            checks["summary_max_gust_ok"] = True
                    except Exception:
                        pass
                # checked_hours equals total hours in input
                if checked_hours_count is not None:
                    try:
                        if int(summary_data.get("checked_hours")) == int(checked_hours_count):
                            checks["summary_checked_hours_ok"] = True
                    except Exception:
                        pass
        except Exception:
            # summary_valid_json remains False if parsing failed
            pass

    # Cross-consistency between CSV and JSON (if both parsed and have expected)
    if checks["csv_exists"] and checks["summary_valid_json"] and summary_data and expected_window is not None:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
            if len(lines) >= 2:
                data_fields = parse_csv_line(lines[1])
                if len(data_fields) == 6:
                    csv_start, csv_end, csv_avg_s, csv_max_wind_s, csv_max_gust_s, csv_dry = data_fields
                    sel = summary_data.get("selected_window", {})
                    consistent = True
                    consistent &= (sel.get("start_time") == csv_start)
                    consistent &= (sel.get("end_time") == csv_end)
                    try:
                        consistent &= float_close(float(sel.get("avg_temp_F")), float(csv_avg_s), tol=0.11)
                    except Exception:
                        consistent = False
                    try:
                        consistent &= float_close(float(sel.get("max_wind_mph")), float(csv_max_wind_s), tol=0.01)
                    except Exception:
                        consistent = False
                    try:
                        consistent &= float_close(float(sel.get("max_gust_mph")), float(csv_max_gust_s), tol=0.01)
                    except Exception:
                        consistent = False
                    if consistent:
                        checks["csv_json_consistent"] = True
        except Exception:
            pass

    # Compute reward
    # Baseline: if required artifacts missing, reward must be exactly 0.0
    required_present = checks["csv_exists"] and checks["summary_exists"]
    if not required_present:
        reward = 0.0
    else:
        # Reward is fraction of passed checks (excluding existence to encourage correctness, or include them all equally)
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp between 0 and 1
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()