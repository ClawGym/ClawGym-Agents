import json
import os
import sys
from datetime import datetime, time, timezone, timedelta

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def parse_iso_datetime(s, tz_hint=None, target_date_str=None):
    """
    Parse an ISO 8601 datetime.
    - Accepts 'Z' by converting to '+00:00'.
    - If no tzinfo and tz_hint is 'America/Los_Angeles' and target_date is in May 2026,
      assume PDT (-07:00) for 2026-05-02.
    Returns (datetime_obj_or_None).
    """
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except Exception:
        return None
    # If naive and hint matches, attach -07:00 for May 2, 2026
    if dt.tzinfo is None and tz_hint == "America/Los_Angeles":
        if target_date_str == "2026-05-02":
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-7)))
    return dt

def within_time_window_local(dt, start_t: time, end_t: time):
    """Check if aware datetime dt has its local clock time within [start_t, end_t] inclusive."""
    if not isinstance(dt, datetime):
        return False
    # Use local clock time from dt (which already has tzinfo)
    hh = dt.hour
    mm = dt.minute
    ss = dt.second
    t_local = time(hh, mm, ss)
    # Compare inclusive on hours/minutes/seconds
    return (t_local >= start_t) and (t_local <= end_t)

def ensure_list_providers(providers_data):
    # Expect a list of provider objects. If wrapped, try to unwrap common keys.
    if isinstance(providers_data, list):
        return providers_data
    if isinstance(providers_data, dict):
        for key in ["providers", "data", "items", "results"]:
            if key in providers_data and isinstance(providers_data[key], list):
                return providers_data[key]
    return []

def extract_providers_map(providers_list):
    """Return dict providerId -> provider object with normalized fields."""
    by_id = {}
    for p in providers_list:
        pid = p.get("providerId") or p.get("id") or p.get("provider_id")
        name = p.get("name") or p.get("providerName") or ""
        dist = to_float(p.get("distanceMiles") if "distanceMiles" in p else p.get("distance_miles") or p.get("distance") or 0.0)
        rating = to_float(p.get("rating") if "rating" in p else p.get("stars") or 0.0)
        services = p.get("services") if isinstance(p.get("services"), list) else []
        by_id[str(pid)] = {
            "raw": p,
            "providerId": str(pid),
            "name": name,
            "distanceMiles": dist,
            "rating": rating,
            "services": services,
        }
    return by_id

def find_service(provider_obj, service_name_exact):
    """Find service by exact name; return dict with id and price if found, else None."""
    for s in provider_obj.get("services", []):
        nm = s.get("name") or s.get("serviceName")
        if nm == service_name_exact:
            sid = s.get("serviceId") or s.get("id") or s.get("service_id")
            price = s.get("price")
            try:
                price_num = float(price)
            except Exception:
                price_num = None
            return {"serviceId": str(sid), "name": nm, "price": price_num, "raw": s}
    return None

def normalize_availability_structure(av_data):
    """
    Normalize availability into a list of entries:
    Each entry: { "providerId": str, "timezone": str or None, "slots": [iso strings] }
    Slots may include multiple dates; date filter will apply later.
    We support two common formats:
      1) List of objects with keys: providerId, date (optional), timezone (optional), slots: [...]
      2) Dict mapping providerId -> { "timezone": ..., "<YYYY-MM-DD>": [slots], ... } or -> [slots]
    """
    out = []
    if isinstance(av_data, list):
        for item in av_data:
            pid = item.get("providerId") or item.get("id") or item.get("provider_id")
            if not pid:
                continue
            tz = item.get("timezone") or av_data[0].get("timezone") if isinstance(av_data, list) and av_data else None
            # Prefer item["slots"]; if not present but "times" exists
            slots = []
            if isinstance(item.get("slots"), list):
                slots = [s for s in item["slots"] if isinstance(s, str)]
            # Also consider per-date keys if present
            possible_date_keys = [k for k in item.keys() if isinstance(k, str) and len(k) == 10 and k[4] == "-" and k[7] == "-"]
            for dk in possible_date_keys:
                if isinstance(item.get(dk), list):
                    slots.extend([s for s in item.get(dk, []) if isinstance(s, str)])
            out.append({"providerId": str(pid), "timezone": tz, "slots": slots})
        return out
    if isinstance(av_data, dict):
        global_tz = av_data.get("timezone")
        # If keys look like providerIds (strings), iterate them
        for k, v in av_data.items():
            if k == "timezone":
                continue
            pid = k
            tz = None
            slots = []
            if isinstance(v, list):
                slots = [s for s in v if isinstance(s, str)]
            elif isinstance(v, dict):
                tz = v.get("timezone") or global_tz
                # Collect slots across date keys
                for dk, dv in v.items():
                    if isinstance(dv, list) and isinstance(dk, str):
                        # If dk looks like date string or just a list of iso slots
                        slots.extend([s for s in dv if isinstance(s, str)])
            if slots:
                out.append({"providerId": str(pid), "timezone": tz or global_tz, "slots": slots})
        # Also support a top-level list under a common key
        for key in ["availability", "data", "items", "results"]:
            if key in av_data and isinstance(av_data[key], list):
                out.extend(normalize_availability_structure(av_data[key]))
        return out
    return out

def earliest_in_window(slots_list, tz_hint, target_date_str, start_t, end_t):
    """
    slots_list: list of iso strings
    Returns (dt, original_str) for earliest slot within window on target date, or (None, None)
    """
    candidates = []
    for s in slots_list:
        dt = parse_iso_datetime(s, tz_hint=tz_hint, target_date_str=target_date_str)
        if not isinstance(dt, datetime):
            continue
        # Match date exactly
        try:
            dt_date_str = dt.date().isoformat()
        except Exception:
            continue
        if dt_date_str != target_date_str:
            continue
        if within_time_window_local(dt, start_t, end_t):
            candidates.append((dt, s))
    if not candidates:
        return None, None
    # Sort by absolute time
    candidates.sort(key=lambda x: x[0])
    return candidates[0]

def compute_eligibles(providers_by_id, availability_entries, service_name_exact, max_distance, target_date_str, window_start, window_end, default_tz_hint="America/Los_Angeles"):
    # Build map for availability: providerId -> (tz_hint, slots[])
    av_map = {}
    for e in availability_entries:
        pid = e.get("providerId")
        if not pid:
            continue
        rec = av_map.get(pid, {"timezone": e.get("timezone") or default_tz_hint, "slots": []})
        rec["slots"].extend(e.get("slots") or [])
        # Keep first non-empty timezone
        if not rec.get("timezone"):
            rec["timezone"] = e.get("timezone") or default_tz_hint
        av_map[pid] = rec

    eligibles = []
    for pid, p in providers_by_id.items():
        # service check
        svc = find_service(p, service_name_exact)
        if not svc:
            continue
        # distance check
        if to_float(p.get("distanceMiles")) > max_distance:
            continue
        # availability check
        av = av_map.get(pid)
        tz_hint = None
        slots = []
        if av:
            tz_hint = av.get("timezone") or default_tz_hint
            slots = av.get("slots", [])
        # Fallback tz_hint
        if not tz_hint:
            tz_hint = default_tz_hint
        dt_earliest, iso_earliest = earliest_in_window(slots, tz_hint, target_date_str, window_start, window_end)
        if dt_earliest is None:
            continue
        eligibles.append({
            "providerId": pid,
            "providerName": p.get("name", ""),
            "serviceId": svc["serviceId"],
            "serviceName": service_name_exact,
            "price": svc["price"],
            "rating": to_float(p.get("rating")),
            "firstEligibleSlot_dt": dt_earliest,
            "firstEligibleSlot": iso_earliest,
        })
    return eligibles

def sort_eligibles(eligibles):
    # Sort by: lowest price, then highest rating, then earliest firstEligibleSlot
    return sorted(
        eligibles,
        key=lambda e: (
            to_float(e.get("price")),                       # ascending price
            -to_float(e.get("rating")),                     # descending rating
            e.get("firstEligibleSlot_dt") or datetime.max   # earliest dt
        )
    )

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Constants per task
    TARGET_SERVICE = "Tire Rotation & Balance"
    TARGET_DATE = "2026-05-02"
    ZIP_CODE = "94107"
    MAX_DISTANCE = 5.0
    TIMEZONE_STR = "America/Los_Angeles"
    WINDOW_START_STR = "10:00"
    WINDOW_END_STR = "14:00"
    WINDOW_START = time(10, 0, 0)
    WINDOW_END = time(14, 0, 0)
    TIE_BREAKERS = ["lowest_price", "highest_rating", "earliest_slot"]
    CUSTOMER = {
        "name": "Alex Morgan",
        "email": "alex.morgan@example.com",
        "phone": "+14155550123",
    }

    checks = {
        "booking_file_exists": False,
        "booking_valid_json": False,
        "booking_customer_date_service_ok": False,
        "booking_provider_service_match_ok": False,
        "booking_distance_and_availability_ok": False,
        "booking_selected_provider_correct": False,
        "booking_timeSlot_earliest_ok": False,
        "booking_names_and_price_ok": False,
        "booking_criteria_ok": False,
        "shortlist_file_exists": False,
        "shortlist_valid_json": False,
        "shortlist_eligibles_exact_ok": False,
        "shortlist_firstEligibleSlot_ok": False,
        "shortlist_selection_order_ok": False,
        "shortlist_chosen_consistency_ok": False,
        "cross_consistency_ok": False,
    }

    # Load reference inputs
    providers_path = os.path.join(input_dir, "providers.json")
    availability_path = os.path.join(input_dir, "availability.json")
    providers_data, providers_err = load_json_file(providers_path)
    availability_data, availability_err = load_json_file(availability_path)

    providers_list = ensure_list_providers(providers_data) if providers_data is not None else []
    providers_by_id = extract_providers_map(providers_list) if providers_list else {}
    availability_entries = normalize_availability_structure(availability_data) if availability_data is not None else []

    # Compute ground truth eligibles and ordering
    eligibles = compute_eligibles(
        providers_by_id,
        availability_entries,
        TARGET_SERVICE,
        MAX_DISTANCE,
        TARGET_DATE,
        WINDOW_START,
        WINDOW_END,
        default_tz_hint=TIMEZONE_STR
    )
    sorted_eligibles = sort_eligibles(eligibles)
    expected_selection_order = [e["providerId"] for e in sorted_eligibles]
    expected_chosen = expected_selection_order[0] if expected_selection_order else None
    expected_earliest_slot_by_provider = {e["providerId"]: e["firstEligibleSlot"] for e in eligibles}
    expected_service_by_provider = {}
    expected_price_by_provider = {}
    for pid, p in providers_by_id.items():
        svc = find_service(p, TARGET_SERVICE)
        if svc:
            expected_service_by_provider[pid] = svc["serviceId"]
            expected_price_by_provider[pid] = svc["price"]

    # Load outputs
    booking_path = os.path.join(output_dir, "booking.json")
    shortlist_path = os.path.join(output_dir, "shortlist.json")

    booking_obj = None
    shortlist_obj = None

    if os.path.isfile(booking_path):
        checks["booking_file_exists"] = True
        booking_obj, err = load_json_file(booking_path)
        if booking_obj is not None and isinstance(booking_obj, dict):
            checks["booking_valid_json"] = True
    if os.path.isfile(shortlist_path):
        checks["shortlist_file_exists"] = True
        shortlist_obj, err = load_json_file(shortlist_path)
        if shortlist_obj is not None and isinstance(shortlist_obj, dict):
            checks["shortlist_valid_json"] = True

    # Validate booking.json core fields
    if checks["booking_valid_json"]:
        b = booking_obj
        # Customer, date, serviceName
        try:
            cust_ok = b.get("customer", {}) == CUSTOMER
            date_ok = b.get("date") == TARGET_DATE
            svcname_ok = b.get("serviceName") == TARGET_SERVICE
            if cust_ok and date_ok and svcname_ok:
                checks["booking_customer_date_service_ok"] = True
        except Exception:
            pass

        # Criteria
        try:
            crit = b.get("criteria", {})
            crit_ok = (
                isinstance(crit, dict)
                and crit.get("zipCode") == ZIP_CODE
                and to_float(crit.get("maxDistanceMiles")) == MAX_DISTANCE
                and crit.get("date") == TARGET_DATE
                and crit.get("windowStart") == WINDOW_START_STR
                and crit.get("windowEnd") == WINDOW_END_STR
                and crit.get("timezone") == TIMEZONE_STR
                and isinstance(crit.get("tieBreakers"), list)
                and crit.get("tieBreakers") == TIE_BREAKERS
            )
            if crit_ok:
                checks["booking_criteria_ok"] = True
        except Exception:
            pass

        # Provider/service match
        try:
            b_pid = str(b.get("providerId"))
            b_pname = b.get("providerName")
            b_sid = str(b.get("serviceId"))
            b_price = to_float(b.get("price"), None)
            provider_obj = providers_by_id.get(b_pid)
            if provider_obj:
                svc = find_service(provider_obj, TARGET_SERVICE)
                if svc and svc["serviceId"] == b_sid and (b_price is not None) and abs(to_float(svc["price"]) - b_price) < 1e-9:
                    checks["booking_provider_service_match_ok"] = True
        except Exception:
            pass

        # Distance and availability window
        try:
            b_pid = str(b.get("providerId"))
            provider_obj = providers_by_id.get(b_pid)
            distance_ok = provider_obj is not None and to_float(provider_obj.get("distanceMiles")) <= MAX_DISTANCE
            # Availability within window on target date
            av_slots = []
            tz_hint = TIMEZONE_STR
            for e in availability_entries:
                if str(e.get("providerId")) == b_pid:
                    av_slots.extend(e.get("slots") or [])
                    if e.get("timezone"):
                        tz_hint = e.get("timezone")
            # Evaluate in-window
            any_in_window = False
            for s in av_slots:
                dt = parse_iso_datetime(s, tz_hint=tz_hint, target_date_str=TARGET_DATE)
                if isinstance(dt, datetime) and dt.date().isoformat() == TARGET_DATE and within_time_window_local(dt, WINDOW_START, WINDOW_END):
                    any_in_window = True
                    break
            if distance_ok and any_in_window:
                checks["booking_distance_and_availability_ok"] = True
        except Exception:
            pass

        # Names and price correctness (providerName/serviceName alignment)
        try:
            b_pid = str(b.get("providerId"))
            provider_obj = providers_by_id.get(b_pid)
            name_ok = provider_obj is not None and b.get("providerName") == provider_obj.get("name")
            svcname_ok = b.get("serviceName") == TARGET_SERVICE
            # price alignment checked earlier; also ensure serviceId matches provider service list
            svc = find_service(provider_obj, TARGET_SERVICE) if provider_obj else None
            sid_ok = svc is not None and str(b.get("serviceId")) == str(svc["serviceId"])
            price_ok = svc is not None and abs(to_float(b.get("price")) - to_float(svc["price"])) < 1e-9
            if name_ok and svcname_ok and sid_ok and price_ok:
                checks["booking_names_and_price_ok"] = True
        except Exception:
            pass

        # Selected provider correctness and earliest slot correctness
        try:
            b_pid = str(b.get("providerId"))
            # Compare against expected chosen provider based on inputs
            if expected_chosen is not None and b_pid == expected_chosen:
                checks["booking_selected_provider_correct"] = True
            # timeSlot earliest for chosen provider
            b_time = b.get("timeSlot")
            exp_slot = expected_earliest_slot_by_provider.get(b_pid)
            if isinstance(b_time, str) and exp_slot is not None and b_time == exp_slot:
                checks["booking_timeSlot_earliest_ok"] = True
        except Exception:
            pass

    # Validate shortlist.json
    if checks["shortlist_valid_json"]:
        s = shortlist_obj
        try:
            elig_list = s.get("eligibleProviders", [])
            if isinstance(elig_list, list):
                # The eligible set must match computed eligibles exactly
                got_ids = [str(e.get("providerId")) for e in elig_list if isinstance(e, dict) and "providerId" in e]
                exp_ids_set = set([e["providerId"] for e in eligibles])
                got_ids_set = set(got_ids)
                if got_ids_set == exp_ids_set:
                    checks["shortlist_eligibles_exact_ok"] = True
                # firstEligibleSlot correctness per provider
                fes_ok = True
                for e in elig_list:
                    if not isinstance(e, dict):
                        fes_ok = False
                        break
                    pid = str(e.get("providerId"))
                    # Check serviceName constant and core fields match
                    if e.get("serviceName") != TARGET_SERVICE:
                        fes_ok = False
                        break
                    # Check serviceId and price and rating against providers
                    prov = providers_by_id.get(pid)
                    svc = find_service(prov, TARGET_SERVICE) if prov else None
                    if not prov or not svc:
                        fes_ok = False
                        break
                    if str(e.get("serviceId")) != str(svc["serviceId"]):
                        fes_ok = False
                        break
                    if abs(to_float(e.get("price")) - to_float(svc["price"])) >= 1e-9:
                        fes_ok = False
                        break
                    # rating
                    if abs(to_float(e.get("rating")) - to_float(prov.get("rating"))) >= 1e-9:
                        fes_ok = False
                        break
                    # firstEligibleSlot equals expected
                    exp_slot = expected_earliest_slot_by_provider.get(pid)
                    if exp_slot is None or e.get("firstEligibleSlot") != exp_slot:
                        fes_ok = False
                        break
                if fes_ok:
                    checks["shortlist_firstEligibleSlot_ok"] = True
        except Exception:
            pass

        # selectionOrder and chosen consistency
        try:
            sel_order = s.get("selectionOrder")
            chosen_id = s.get("chosenProviderId")
            if isinstance(sel_order, list) and all(isinstance(x, (str, int)) for x in sel_order):
                sel_order_str = [str(x) for x in sel_order]
                if sel_order_str == expected_selection_order:
                    checks["shortlist_selection_order_ok"] = True
                # chosen equals first of selectionOrder and equals booking.providerId
                booking_pid = str(booking_obj.get("providerId")) if isinstance(booking_obj, dict) and booking_obj.get("providerId") is not None else None
                if len(sel_order_str) > 0 and str(chosen_id) == sel_order_str[0] and (booking_pid is None or str(chosen_id) == booking_pid):
                    checks["shortlist_chosen_consistency_ok"] = True
        except Exception:
            pass

    # Cross-file consistency: booking provider appears in shortlist eligibleProviders and matches chosenProviderId
    try:
        if checks["booking_valid_json"] and checks["shortlist_valid_json"]:
            b_pid = str(booking_obj.get("providerId"))
            chosen = str(shortlist_obj.get("chosenProviderId"))
            elig_list = shortlist_obj.get("eligibleProviders", [])
            elig_ids = set(str(e.get("providerId")) for e in elig_list if isinstance(e, dict) and "providerId" in e)
            if b_pid == chosen and b_pid in elig_ids:
                checks["cross_consistency_ok"] = True
    except Exception:
        pass

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op (no files) yields 0.0
    if not checks["booking_file_exists"] and not checks["shortlist_file_exists"]:
        reward = 0.0

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()