import json
import os
import sys
import csv
from datetime import datetime, date, timedelta

def parse_simple_yaml(path):
    # Minimal YAML parser for simple key: value pairs
    # Supports strings (quoted/unquoted), integers
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if ":" not in s:
                    continue
                key, val = s.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Remove inline comments after value if present
                if " #" in val:
                    val = val.split(" #", 1)[0].strip()
                # Strip quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                # Try int
                if val.lower() in ("true", "false"):
                    parsed = val.lower() == "true"
                else:
                    try:
                        parsed = int(val)
                    except ValueError:
                        parsed = val
                data[key] = parsed
    except Exception:
        return {}
    return data

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "y", "yes")
    return False

def safe_date_parse(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        # try other common formats
        for fmt in ("%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
    return None

def read_vehicles_input(path):
    try:
        data = load_json(path)
        if isinstance(data, dict):
            # assume slugs are keys
            return data
        elif isinstance(data, list):
            m = {}
            for item in data:
                if isinstance(item, dict):
                    slug = item.get("slug")
                    if slug:
                        m[slug] = item
            return m
    except Exception:
        pass
    return {}

def compute_expected_fuel_metrics(csv_path):
    # Returns dict with keys: last_mpg, rolling_avg, drop_percent, anomaly, last_fill_date
    # Implements rules from task.
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Normalize keys
                date_str = (r.get("date") or "").strip()
                gallons = r.get("gallons")
                cost = r.get("cost")
                odometer = r.get("odometer")
                partial = r.get("partial_fill")
                try:
                    gallons_f = float(gallons)
                except Exception:
                    gallons_f = None
                try:
                    cost_f = float(cost)
                except Exception:
                    cost_f = None
                try:
                    odo_i = int(float(odometer))
                except Exception:
                    try:
                        odo_i = int(odometer)
                    except Exception:
                        odo_i = None
                part_b = parse_bool(partial)
                d = safe_date_parse(date_str)
                rows.append({
                    "date_raw": date_str,
                    "date": d,
                    "gallons": gallons_f,
                    "cost": cost_f,
                    "odometer": odo_i,
                    "partial_fill": part_b
                })
    except Exception:
        return None

    # Sort by date if parsable; otherwise keep original order
    if all(r["date"] is not None for r in rows):
        rows.sort(key=lambda x: x["date"])
    # Build list of non-partial fills and compute mpg at each (except first)
    non_partial = [r for r in rows if not r["partial_fill"] and r["odometer"] is not None and r["gallons"] not in (None, 0)]
    if len(non_partial) < 2:
        return None  # cannot compute
    # Compute mpg for each non-partial with a previous non-partial
    mpgs = []
    for i, r in enumerate(non_partial):
        if i == 0:
            mpgs.append(None)  # first cannot compute
            continue
        prev = non_partial[i-1]
        # (current odometer – previous non-partial fill’s odometer) / gallons for the current fill-up
        try:
            dist = r["odometer"] - prev["odometer"]
            mpg = dist / r["gallons"] if r["gallons"] else None
        except Exception:
            mpg = None
        mpgs.append(mpg)

    # Last non-partial fill is the last element
    last_idx = len(non_partial) - 1
    last_mpg = mpgs[last_idx]
    last_date = non_partial[last_idx]["date"]
    if last_mpg is None:
        return None
    # Rolling avg is average of the three most recent completed (non-partial) fill-ups immediately BEFORE the most recent non-partial
    # That means mpgs at indices last_idx-1, last_idx-2, last_idx-3 (must be not None)
    prior_mpgs = []
    i = last_idx - 1
    while i >= 0 and len(prior_mpgs) < 3:
        if mpgs[i] is not None:
            prior_mpgs.append(mpgs[i])
        i -= 1
    if len(prior_mpgs) < 3:
        return None  # not enough prior non-partial with computed mpg
    rolling_avg = sum(prior_mpgs) / 3.0
    if rolling_avg == 0 or rolling_avg is None:
        return None
    drop_percent = ((rolling_avg - last_mpg) / rolling_avg) * 100.0
    anomaly = last_mpg < (rolling_avg * 0.85)
    return {
        "last_mpg": last_mpg,
        "rolling_avg": rolling_avg,
        "drop_percent": drop_percent,
        "anomaly": anomaly,
        "last_fill_date": last_date.isoformat() if isinstance(last_date, date) else None
    }

def get_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    state_path = os.path.join(output_dir, "data", "mechanic", "state.json")
    sched_dir = os.path.join(output_dir, "data", "mechanic")
    f150_sched_path = os.path.join(sched_dir, "f150-schedule.json")
    rpod_sched_path = os.path.join(sched_dir, "rpod_trailer-schedule.json")
    fuel_report_path = os.path.join(output_dir, "reports", "fuel_report_f150.json")
    warranty_alerts_path = os.path.join(output_dir, "reports", "warranty_alerts.md")
    pre_tow_path = os.path.join(output_dir, "reports", "pre_tow_checklist.md")

    # Input paths
    vehicles_input_path = os.path.join(input_dir, "vehicles.json")
    fuel_logs_input_path = os.path.join(input_dir, "fuel_logs.csv")
    settings_yaml_path = os.path.join(input_dir, "settings.yaml")
    trip_plan_path = os.path.join(input_dir, "trip_plan.txt")

    # Load inputs
    vehicles_input = read_vehicles_input(vehicles_input_path)
    settings = parse_simple_yaml(settings_yaml_path)
    today_str = settings.get("today")
    today_date = safe_date_parse(today_str) if isinstance(today_str, str) else None
    months_threshold = settings.get("months_threshold")
    miles_threshold = settings.get("miles_threshold")
    if not isinstance(months_threshold, int):
        try:
            months_threshold = int(months_threshold)
        except Exception:
            months_threshold = None
    if not isinstance(miles_threshold, int):
        try:
            miles_threshold = int(miles_threshold)
        except Exception:
            miles_threshold = None

    checks = {
        # State file validations
        "state_exists": False,
        "state_valid_json": False,
        "has_vehicle_f150": False,
        "has_vehicle_rpod_trailer": False,
        "f150_schedule_file_ref_valid": False,
        "rpod_schedule_file_ref_valid": False,
        "f150_warranty_factory_powertrain_ford_2026_06_15": False,
        "recalls_last_checked_null_all": False,
        "mileage_history_today_both": False,
        # Schedules validations
        "f150_schedule_exists_valid": False,
        "f150_schedule_vehicle_section_fields": False,
        "f150_schedule_services_count": False,
        "f150_schedule_services_required_fields": False,
        "f150_schedule_has_oil_filter": False,
        "rpod_schedule_exists_valid": False,
        "rpod_schedule_vehicle_section_fields": False,
        "rpod_schedule_services_count": False,
        "rpod_schedule_services_required_fields": False,
        "rpod_schedule_has_wheel_bearing_repack": False,
        # Fuel report validations
        "fuel_report_exists_valid": False,
        "fuel_report_values_match": False,
        # Warranty alerts report validations
        "warranty_alerts_exists": False,
        "warranty_alerts_contains_f150_expiring": False,
        # Pre-tow checklist validations
        "pre_tow_exists": False,
        "pre_tow_has_required_headings": False,
        "pre_tow_min_checkboxes": False,
    }

    state_data = None
    if os.path.isfile(state_path):
        checks["state_exists"] = True
        try:
            state_data = load_json(state_path)
            if isinstance(state_data, dict):
                checks["state_valid_json"] = True
        except Exception:
            state_data = None

    # Validate state content
    vehicles_state = {}
    if checks["state_valid_json"]:
        vehicles_state = state_data.get("vehicles") if isinstance(state_data.get("vehicles"), dict) else {}
        if "f150" in vehicles_state:
            checks["has_vehicle_f150"] = True
        if "rpod_trailer" in vehicles_state:
            checks["has_vehicle_rpod_trailer"] = True

        # schedule_file refs
        def validate_schedule_ref(slug, expected_filename):
            v = vehicles_state.get(slug, {})
            sf = v.get("schedule_file")
            if not isinstance(sf, str) or not sf.strip():
                return False
            basename = os.path.basename(sf)
            # The file must exist in output/data/mechanic/
            target = os.path.join(sched_dir, basename)
            return os.path.isfile(target) and (basename == expected_filename)
        checks["f150_schedule_file_ref_valid"] = validate_schedule_ref("f150", "f150-schedule.json")
        checks["rpod_schedule_file_ref_valid"] = validate_schedule_ref("rpod_trailer", "rpod_trailer-schedule.json")

        # recalls last_checked null for both vehicles
        def is_last_checked_null(slug):
            v = vehicles_state.get(slug, {})
            rec = v.get("recalls")
            if not isinstance(rec, dict):
                return False
            return ("last_checked" in rec) and (rec.get("last_checked") is None)
        checks["recalls_last_checked_null_all"] = is_last_checked_null("f150") and is_last_checked_null("rpod_trailer")

        # f150 warranty presence check (type/provider/end_date)
        f150 = vehicles_state.get("f150", {})
        warranties = f150.get("warranties")
        found_fw = False
        if isinstance(warranties, list):
            for w in warranties:
                if not isinstance(w, dict):
                    continue
                if w.get("type") == "factory_powertrain" and w.get("provider") == "Ford" and w.get("end_date") == "2026-06-15":
                    found_fw = True
                    break
        checks["f150_warranty_factory_powertrain_ford_2026_06_15"] = found_fw

        # mileage_history today for both vehicles with current_miles matching input
        # Read expected current miles from input vehicles.json
        veh_in = vehicles_input
        def get_expected_miles(slug):
            d = veh_in.get(slug, {})
            # They might use 'current_miles' or 'current_mileage'
            cm = d.get("current_miles")
            if cm is None:
                cm = d.get("current_mileage")
            try:
                return int(cm)
            except Exception:
                try:
                    return int(float(cm))
                except Exception:
                    return None

        def has_mileage_entry(slug):
            v_state = vehicles_state.get(slug, {})
            mh = v_state.get("mileage_history")
            if not isinstance(mh, list) or today_date is None:
                return False
            expected_miles = get_expected_miles(slug)
            if expected_miles is None:
                # fall back to state's own current_miles
                cm = v_state.get("current_miles")
                try:
                    expected_miles = int(cm)
                except Exception:
                    return False
            for e in mh:
                if not isinstance(e, dict):
                    continue
                dstr = e.get("date")
                miles = e.get("miles")
                if not isinstance(dstr, str):
                    continue
                d = safe_date_parse(dstr)
                if d == today_date:
                    try:
                        m = int(miles)
                    except Exception:
                        try:
                            m = int(float(miles))
                        except Exception:
                            continue
                    if m == expected_miles:
                        return True
            return False

        checks["mileage_history_today_both"] = has_mileage_entry("f150") and has_mileage_entry("rpod_trailer")

    # Validate schedule files
    # f150
    f150_sched = None
    if os.path.isfile(f150_sched_path):
        try:
            f150_sched = load_json(f150_sched_path)
            if isinstance(f150_sched, dict):
                checks["f150_schedule_exists_valid"] = True
        except Exception:
            pass
    if checks["f150_schedule_exists_valid"]:
        veh = f150_sched.get("vehicle")
        if isinstance(veh, dict):
            req_fields = ["year", "make", "model", "type", "duty"]
            if all(k in veh for k in req_fields):
                checks["f150_schedule_vehicle_section_fields"] = True
        services = f150_sched.get("services")
        if isinstance(services, list):
            if len(services) >= 5:
                checks["f150_schedule_services_count"] = True
            # Required fields per service and at least one interval
            svc_ok = True
            has_oil_filter = False
            for s in services:
                if not isinstance(s, dict):
                    svc_ok = False
                    break
                req = ["id", "name", "details", "priority", "cost_diy", "cost_shop", "cost_dealer"]
                if not all(k in s for k in req):
                    svc_ok = False
                    break
                if not ("interval_miles" in s or "interval_months" in s):
                    svc_ok = False
                    break
                if s.get("id") == "oil_filter":
                    has_oil_filter = True
            checks["f150_schedule_services_required_fields"] = svc_ok
            checks["f150_schedule_has_oil_filter"] = has_oil_filter

    # rpod trailer
    rpod_sched = None
    if os.path.isfile(rpod_sched_path):
        try:
            rpod_sched = load_json(rpod_sched_path)
            if isinstance(rpod_sched, dict):
                checks["rpod_schedule_exists_valid"] = True
        except Exception:
            pass
    if checks["rpod_schedule_exists_valid"]:
        veh = rpod_sched.get("vehicle")
        if isinstance(veh, dict):
            req_fields = ["year", "make", "model", "type", "duty"]
            if all(k in veh for k in req_fields):
                checks["rpod_schedule_vehicle_section_fields"] = True
        services = rpod_sched.get("services")
        if isinstance(services, list):
            if len(services) >= 3:
                checks["rpod_schedule_services_count"] = True
            svc_ok = True
            has_req = False
            for s in services:
                if not isinstance(s, dict):
                    svc_ok = False
                    break
                req = ["id", "name", "details", "priority", "cost_diy", "cost_shop", "cost_dealer"]
                if not all(k in s for k in req):
                    svc_ok = False
                    break
                if not ("interval_miles" in s or "interval_months" in s):
                    svc_ok = False
                    break
                if s.get("id") == "wheel_bearing_repack":
                    has_req = True
            checks["rpod_schedule_services_required_fields"] = svc_ok
            checks["rpod_schedule_has_wheel_bearing_repack"] = has_req

    # Fuel report checks
    fuel_report_data = None
    if os.path.isfile(fuel_report_path):
        try:
            fuel_report_data = load_json(fuel_report_path)
            if isinstance(fuel_report_data, dict):
                # Must contain numeric fields and boolean anomaly
                lm = fuel_report_data.get("last_mpg")
                ra = fuel_report_data.get("rolling_avg")
                dp = fuel_report_data.get("drop_percent")
                an = fuel_report_data.get("anomaly")
                if is_number(lm) and is_number(ra) and is_number(dp) and isinstance(an, bool):
                    checks["fuel_report_exists_valid"] = True
        except Exception:
            pass

    # Compute expected fuel metrics from input and compare
    expected_metrics = compute_expected_fuel_metrics(fuel_logs_input_path)
    if expected_metrics and checks["fuel_report_exists_valid"]:
        tol = 0.2
        try:
            lm_ok = abs(float(fuel_report_data.get("last_mpg")) - float(expected_metrics["last_mpg"])) <= tol
            ra_ok = abs(float(fuel_report_data.get("rolling_avg")) - float(expected_metrics["rolling_avg"])) <= tol
            dp_ok = abs(float(fuel_report_data.get("drop_percent")) - float(expected_metrics["drop_percent"])) <= tol
            an_ok = bool(fuel_report_data.get("anomaly")) == bool(expected_metrics["anomaly"])
            checks["fuel_report_values_match"] = lm_ok and ra_ok and dp_ok and an_ok
        except Exception:
            checks["fuel_report_values_match"] = False

    # Warranty alerts report
    if os.path.isfile(warranty_alerts_path):
        checks["warranty_alerts_exists"] = True
        content = get_text_file(warranty_alerts_path) or ""
        # Determine if F-150 factory powertrain should be expiring soon
        # Inspect input vehicles.json for f150 label, warranties
        veh_in = vehicles_input.get("f150", {})
        label = veh_in.get("label") or (vehicles_state.get("f150", {}).get("label") if isinstance(vehicles_state.get("f150", {}), dict) else None) or "F-150"
        current_miles = None
        try:
            cm = veh_in.get("current_miles", veh_in.get("current_mileage"))
            current_miles = int(cm) if cm is not None else None
        except Exception:
            try:
                current_miles = int(float(cm))
            except Exception:
                current_miles = None
        warranties_in = veh_in.get("warranties")
        should_alert = False
        if isinstance(warranties_in, list) and today_date is not None and isinstance(months_threshold, int):
            for w in warranties_in:
                if not isinstance(w, dict):
                    continue
                w_type = w.get("type")
                provider = w.get("provider")
                end_date_str = w.get("end_date")
                end_miles = w.get("end_miles")
                ed = safe_date_parse(end_date_str) if isinstance(end_date_str, str) else None
                date_ok = False
                miles_ok = False
                if ed is not None:
                    days_until = (ed - today_date).days
                    if days_until >= 0 and days_until <= (months_threshold * 31):
                        date_ok = True
                if isinstance(miles_threshold, int) and current_miles is not None and isinstance(end_miles, (int, float)):
                    delta_miles = int(end_miles - current_miles)
                    if delta_miles >= 0 and delta_miles <= miles_threshold:
                        miles_ok = True
                if (date_ok or miles_ok) and w_type == "factory_powertrain" and provider == "Ford" and end_date_str == "2026-06-15":
                    should_alert = True
                    break
        # Check content for required info if should_alert
        if should_alert:
            has_phrase = "expiring soon" in content.lower()
            has_label = (label in content) if isinstance(label, str) else False
            has_type = "factory_powertrain" in content
            has_provider = "Ford" in content
            has_end_date = "2026-06-15" in content
            checks["warranty_alerts_contains_f150_expiring"] = all([has_phrase, has_label, has_type, has_provider, has_end_date])

    # Pre-tow checklist
    if os.path.isfile(pre_tow_path):
        checks["pre_tow_exists"] = True
        content = get_text_file(pre_tow_path) or ""
        # Required headings exactly
        lines = [ln.strip() for ln in content.splitlines()]
        has_truck = any(ln.strip() == "TRUCK:" for ln in lines)
        has_hitch = any(ln.strip() == "HITCH/CONNECTION:" for ln in lines)
        has_trailer = any(ln.strip() == "TRAILER/RV:" for ln in lines)
        checks["pre_tow_has_required_headings"] = has_truck and has_hitch and has_trailer
        # Count checkboxes with "□ " prefix
        checkbox_count = sum(1 for ln in content.splitlines() if ln.startswith("□ "))
        checks["pre_tow_min_checkboxes"] = checkbox_count >= 10

    # Compute reward as average of checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output is empty or missing main required artifacts, reward should be 0.0
    # If none of the key artifacts exist, force reward 0.0
    key_artifacts = [
        checks["state_exists"],
        checks["f150_schedule_exists_valid"],
        checks["rpod_schedule_exists_valid"],
        checks["fuel_report_exists_valid"],
        checks["warranty_alerts_exists"],
        checks["pre_tow_exists"],
    ]
    if not any(key_artifacts):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()