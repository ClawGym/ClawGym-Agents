import json
import os
import sys
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    # Accept ISO 8601, including timezone, and 'Z'
    if not isinstance(dt_str, str):
        return None
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def parse_hhmm(s: str) -> Optional[time]:
    if not isinstance(s, str):
        return None
    parts = s.strip().split(":")
    try:
        if len(parts) == 2:
            h = int(parts[0])
            m = int(parts[1])
            sec = 0
        elif len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            sec = int(parts[2])
        else:
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec <= 59):
            return None
        return time(hour=h, minute=m, second=sec)
    except Exception:
        return None

def time_to_seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second

def to_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def normalize_provider_record(p: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure expected keys exist in a normalized way
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "rating": to_float(p.get("rating")),
        "distanceMiles": to_float(p.get("distanceMiles")),
        "services": p.get("services") if isinstance(p.get("services"), list) else [],
    }

def extract_availability_map(av_data: Any) -> Dict[Tuple[str, str, str], List[str]]:
    """
    Returns a mapping: (providerId, serviceId, date) -> list of slot strings.
    Supports multiple common shapes:
    - List of objects with keys: providerId, serviceId, date, timeSlots (or slots)
    - Dict with key 'availabilities' or 'availability' as a list of those objects
    - Nested dict: {providerId: {serviceId: {date: [slots]}}}
    """
    mapping: Dict[Tuple[str, str, str], List[str]] = {}

    def add_entry(pid: str, sid: str, date_str: str, slots: Any):
        if not isinstance(pid, str) or not isinstance(sid, str) or not isinstance(date_str, str):
            return
        if not isinstance(slots, list):
            return
        key = (pid, sid, date_str)
        mapping[key] = []
        for s in slots:
            if isinstance(s, str):
                mapping[key].append(s)

    if isinstance(av_data, list):
        for item in av_data:
            if not isinstance(item, dict):
                continue
            pid = item.get("providerId")
            sid = item.get("serviceId")
            date_str = item.get("date")
            slots = item.get("timeSlots", item.get("slots"))
            add_entry(pid, sid, date_str, slots)
        return mapping

    if isinstance(av_data, dict):
        # Try keyed list
        for key in ("availabilities", "availability"):
            if key in av_data and isinstance(av_data[key], list):
                for item in av_data[key]:
                    if not isinstance(item, dict):
                        continue
                    pid = item.get("providerId")
                    sid = item.get("serviceId")
                    date_str = item.get("date")
                    slots = item.get("timeSlots", item.get("slots"))
                    add_entry(pid, sid, date_str, slots)
                return mapping
        # Try nested dict
        for pid, v1 in av_data.items():
            if not isinstance(v1, dict):
                continue
            for sid, v2 in v1.items():
                if isinstance(v2, dict):
                    for date_str, slots in v2.items():
                        add_entry(pid, sid, date_str, slots)
        return mapping

    return mapping

def find_service(provider: Dict[str, Any], target_service_name: str) -> Optional[Dict[str, Any]]:
    services = provider.get("services", [])
    if not isinstance(services, list):
        return None
    for s in services:
        if isinstance(s, dict) and s.get("serviceName") == target_service_name:
            return s
    return None

def compute_expected_selection(preferences: Dict[str, Any], providers: List[Dict[str, Any]], availability_map: Dict[Tuple[str, str, str], List[str]]) -> Optional[Dict[str, Any]]:
    # Extract preference values
    pref_date = preferences.get("date")
    time_window = preferences.get("timeWindow") if isinstance(preferences.get("timeWindow"), dict) else {}
    tw_start_s = time_window.get("start")
    tw_end_s = time_window.get("end")
    min_rating = to_float(preferences.get("minimumRating"))
    max_distance = to_float(preferences.get("maxDistance"))

    if not isinstance(pref_date, str):
        return None
    start_t = parse_hhmm(tw_start_s) if isinstance(tw_start_s, str) else None
    end_t = parse_hhmm(tw_end_s) if isinstance(tw_end_s, str) else None
    if start_t is None or end_t is None or min_rating is None or max_distance is None:
        return None
    start_sec = time_to_seconds(start_t)
    end_sec = time_to_seconds(end_t)

    TARGET_SERVICE_NAME = "Deluxe Pedicure"

    # Build candidates
    slot_records: List[Dict[str, Any]] = []
    for p_raw in providers:
        p = normalize_provider_record(p_raw)
        if p["id"] is None or p["name"] is None:
            continue
        if p["rating"] is None or p["distanceMiles"] is None:
            continue
        if p["rating"] < min_rating:
            continue
        if p["distanceMiles"] > max_distance:
            continue
        svc = find_service(p, TARGET_SERVICE_NAME)
        if not svc or not isinstance(svc.get("serviceId"), str):
            continue
        service_id = svc["serviceId"]
        # Get availability for this provider/service/date
        key = (p["id"], service_id, pref_date)
        slot_list = availability_map.get(key, [])
        if not isinstance(slot_list, list):
            continue
        for slot_str in slot_list:
            dt = parse_iso_datetime(slot_str)
            if dt is None:
                continue
            # Ensure date match and within time window (inclusive)
            if dt.date().isoformat() != pref_date:
                continue
            slot_sec = dt.hour * 3600 + dt.minute * 60 + dt.second
            if slot_sec < start_sec or slot_sec > end_sec:
                continue
            slot_records.append({
                "dt": dt,
                "slot_str": slot_str,
                "providerId": p["id"],
                "providerName": p["name"],
                "serviceId": service_id,
                "serviceName": TARGET_SERVICE_NAME,
                "rating": p["rating"],
                "distanceMiles": p["distanceMiles"],
            })

    if not slot_records:
        return None

    # Choose earliest time (by absolute timestamp). If tie on time, apply tie-breakers.
    # Compute earliest timestamp
    min_ts = min(rec["dt"].timestamp() for rec in slot_records)
    same_time = [rec for rec in slot_records if rec["dt"].timestamp() == min_ts]
    # Tie-breakers: highest rating, then smallest distanceMiles, then lexicographically smallest providerId
    same_time.sort(key=lambda r: (-r["rating"], r["distanceMiles"], r["providerId"]))
    best = same_time[0]
    return best

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        "output_exists": False,
        "output_json_valid": False,
        "keys_exact": False,
        "values_all_strings": False,
        "customer_fields_match": False,
        "provider_service_names_match": False,
        "timeslot_exists_verbatim": False,
        "meets_constraints": False,
        "optimal_selection": False,
    }

    required_keys = {
        "providerId",
        "providerName",
        "serviceId",
        "serviceName",
        "timeSlot",
        "customerName",
        "customerEmail",
        "customerPhone",
    }

    # Locate files
    pref_path = os.path.join(input_dir, "preferences.json")
    providers_path = os.path.join(input_dir, "providers.json")
    availability_path = os.path.join(input_dir, "availability.json")
    output_path = os.path.join(output_dir, "booking_request.json")

    preferences = load_json(pref_path)
    providers_data = load_json(providers_path)
    availability_data = load_json(availability_path)

    # Build availability map for later validations (even if output missing, no positive reward without output)
    availability_map: Dict[Tuple[str, str, str], List[str]] = {}
    if availability_data is not None:
        availability_map = extract_availability_map(availability_data)

    # Normalize providers list
    providers_list: List[Dict[str, Any]] = []
    if isinstance(providers_data, list):
        providers_list = providers_data
    elif isinstance(providers_data, dict) and "providers" in providers_data and isinstance(providers_data["providers"], list):
        providers_list = providers_data["providers"]

    # Load output
    output_obj: Optional[Dict[str, Any]] = None
    if os.path.isfile(output_path):
        checks["output_exists"] = True
        output_obj = load_json(output_path)
        if isinstance(output_obj, dict):
            checks["output_json_valid"] = True

    # If output JSON valid, proceed with validations on structure and values
    if checks["output_json_valid"]:
        keys_set = set(output_obj.keys())
        if keys_set == required_keys and len(output_obj) == len(required_keys):
            checks["keys_exact"] = True

        # Ensure all values are strings
        if all(isinstance(output_obj.get(k), str) for k in required_keys):
            checks["values_all_strings"] = True

    # Validate customer fields
    if checks["output_json_valid"]:
        # Preferences may have customer fields at root or under a 'customer' object
        pref_customer_name = None
        pref_customer_email = None
        pref_customer_phone = None
        if isinstance(preferences, dict):
            pref_customer_name = preferences.get("customerName")
            pref_customer_email = preferences.get("customerEmail")
            pref_customer_phone = preferences.get("customerPhone")
            if not all(isinstance(x, str) for x in [pref_customer_name, pref_customer_email, pref_customer_phone]):
                cust = preferences.get("customer")
                if isinstance(cust, dict):
                    pref_customer_name = cust.get("name") or cust.get("customerName")
                    pref_customer_email = cust.get("email") or cust.get("customerEmail")
                    pref_customer_phone = cust.get("phone") or cust.get("customerPhone")

        if all(isinstance(x, str) for x in [pref_customer_name, pref_customer_email, pref_customer_phone]):
            if (output_obj.get("customerName") == pref_customer_name and
                output_obj.get("customerEmail") == pref_customer_email and
                output_obj.get("customerPhone") == pref_customer_phone):
                checks["customer_fields_match"] = True

    # Provider and service name validation, timeslot existence, and constraints
    selected_provider: Optional[Dict[str, Any]] = None
    selected_service: Optional[Dict[str, Any]] = None
    if checks["output_json_valid"]:
        out_pid = output_obj.get("providerId")
        out_sid = output_obj.get("serviceId")
        out_time = output_obj.get("timeSlot")
        out_pname = output_obj.get("providerName")
        out_sname = output_obj.get("serviceName")

        # Find provider by id
        for p in providers_list:
            if isinstance(p, dict) and p.get("id") == out_pid:
                selected_provider = normalize_provider_record(p)
                # Find service by id in provider
                for s in p.get("services", []) if isinstance(p.get("services"), list) else []:
                    if isinstance(s, dict) and s.get("serviceId") == out_sid:
                        selected_service = s
                        break
                break

        # Verify names
        if selected_provider and selected_service:
            pname_ok = (selected_provider.get("name") == out_pname)
            sname_ok = (selected_service.get("serviceName") == out_sname)
            if pname_ok and sname_ok:
                checks["provider_service_names_match"] = True

        # Timeslot exists verbatim
        if isinstance(preferences, dict) and isinstance(out_time, str):
            pref_date = preferences.get("date")
            key = (out_pid, out_sid, pref_date) if isinstance(pref_date, str) else None
            if key and key in availability_map:
                if out_time in availability_map[key]:
                    checks["timeslot_exists_verbatim"] = True

        # Meets constraints
        if selected_provider and selected_service and isinstance(preferences, dict):
            # Service name must be exactly "Deluxe Pedicure"
            svcname_ok = selected_service.get("serviceName") == "Deluxe Pedicure"
            min_rating = to_float(preferences.get("minimumRating"))
            max_distance = to_float(preferences.get("maxDistance"))
            rating_ok = (min_rating is not None and selected_provider.get("rating") is not None and selected_provider["rating"] >= min_rating)
            distance_ok = (max_distance is not None and selected_provider.get("distanceMiles") is not None and selected_provider["distanceMiles"] <= max_distance)
            date_ok = False
            timewindow_ok = False
            pref_date = preferences.get("date")
            if isinstance(pref_date, str) and isinstance(output_obj.get("timeSlot"), str):
                dt = parse_iso_datetime(output_obj["timeSlot"])
                if dt is not None and dt.date().isoformat() == pref_date:
                    date_ok = True
                tw = preferences.get("timeWindow") if isinstance(preferences.get("timeWindow"), dict) else {}
                st = parse_hhmm(tw.get("start")) if isinstance(tw.get("start"), str) else None
                et = parse_hhmm(tw.get("end")) if isinstance(tw.get("end"), str) else None
                if dt is not None and st is not None and et is not None:
                    sec = dt.hour * 3600 + dt.minute * 60 + dt.second
                    timewindow_ok = (time_to_seconds(st) <= sec <= time_to_seconds(et))
            if svcname_ok and rating_ok and distance_ok and date_ok and timewindow_ok:
                checks["meets_constraints"] = True

    # Optimal selection check
    expected = None
    if isinstance(preferences, dict) and providers_list and availability_map:
        expected = compute_expected_selection(preferences, providers_list, availability_map)

    if checks["output_json_valid"] and expected is not None:
        if (output_obj.get("providerId") == expected.get("providerId") and
            output_obj.get("serviceId") == expected.get("serviceId") and
            output_obj.get("timeSlot") == expected.get("slot_str") and
            output_obj.get("providerName") == expected.get("providerName") and
            output_obj.get("serviceName") == expected.get("serviceName")):
            checks["optimal_selection"] = True

    # Compute reward: average of checks; ensure 0.0 if no output or required artifacts missing/invalid
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["output_exists"] and checks["output_json_valid"] else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()