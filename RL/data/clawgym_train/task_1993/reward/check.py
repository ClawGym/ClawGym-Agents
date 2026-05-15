import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def is_non_empty_string(x):
    return isinstance(x, str) and len(x.strip()) > 0

def is_iso8601_datetime(dt_str: str) -> bool:
    if not isinstance(dt_str, str):
        return False
    if "T" not in dt_str:
        return False
    s = dt_str.strip()
    # Accept 'Z' by converting to +00:00
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False

def extract_hhmm_from_iso(dt_str: str) -> Optional[str]:
    # Expect format YYYY-MM-DDTHH:MM...
    if not isinstance(dt_str, str) or "T" not in dt_str:
        return None
    try:
        tpart = dt_str.split("T", 1)[1]
        hhmm = tpart[:5]
        h, m = hhmm.split(":")
        if len(h) == 2 and len(m) == 2 and h.isdigit() and m.isdigit():
            return hhmm
        return None
    except Exception:
        return None

def hhmm_compare(a: str, b: str) -> int:
    # returns -1 if a<b, 0 if equal, 1 if a>b lexicographically safe for HH:MM
    if a == b:
        return 0
    return -1 if a < b else 1

def in_window(hhmm: str, start: str, end: str) -> bool:
    # inclusive window: start <= hhmm <= end
    if not (isinstance(start, str) and isinstance(end, str) and isinstance(hhmm, str)):
        return False
    # Ensure format HH:MM
    try:
        sh, sm = start.split(":")
        eh, em = end.split(":")
        th, tm = hhmm.split(":")
        if not (len(sh) == len(eh) == len(th) == 2 and len(sm) == len(em) == len(tm) == 2):
            return False
        if not (sh.isdigit() and sm.isdigit() and eh.isdigit() and em.isdigit() and th.isdigit() and tm.isdigit()):
            return False
    except Exception:
        return False
    return (start <= hhmm <= end)

def collect_all_slots_by_pair(checks_arr: List[Dict]) -> Dict[Tuple[str, str], List[str]]:
    m: Dict[Tuple[str, str], List[str]] = {}
    for chk in checks_arr:
        pid = chk.get("providerId")
        sid = chk.get("serviceId")
        slots = chk.get("availableSlots", [])
        if isinstance(pid, str) and isinstance(sid, str) and isinstance(slots, list):
            m[(pid, sid)] = [s for s in slots if isinstance(s, str)]
    return m

def union_all_slots(checks_arr: List[Dict]) -> List[str]:
    slots: List[str] = []
    for chk in checks_arr:
        arr = chk.get("availableSlots", [])
        if isinstance(arr, list):
            for s in arr:
                if isinstance(s, str):
                    slots.append(s)
    return slots

def earliest_slot(slots: List[str]) -> Optional[str]:
    # Determine earliest by HH:MM lexicographic on extracted HH:MM; keep stable by original order tie
    best: Optional[str] = None
    best_hhmm: Optional[str] = None
    for s in slots:
        hhmm = extract_hhmm_from_iso(s)
        if hhmm is None:
            continue
        if best is None:
            best = s
            best_hhmm = hhmm
        else:
            # compare
            if hhmm_compare(hhmm, best_hhmm) < 0:
                best = s
                best_hhmm = hhmm
    return best

def earliest_slot_in_window(slots: List[str], start: str, end: str) -> Optional[str]:
    filtered: List[str] = []
    for s in slots:
        hhmm = extract_hhmm_from_iso(s)
        if hhmm is None:
            continue
        if in_window(hhmm, start, end):
            filtered.append(s)
    return earliest_slot(filtered)

def validate_email(email: str) -> bool:
    return isinstance(email, str) and "@" in email and len(email.strip()) > 0

def validate_phone(phone: str) -> bool:
    if not isinstance(phone, str) or len(phone.strip()) == 0:
        return False
    return phone[0] == "+" or phone[0].isdigit()

def build_abs(*parts):
    return os.path.join(*parts)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = build_abs(workspace_root, "input")
    output_dir = build_abs(workspace_root, "output")
    reward_dir = build_abs(workspace_root, "reward")

    # Initialize checks dict with all False
    checks: Dict[str, bool] = {
        "file_search_exists": False,
        "file_availability_exists": False,
        "file_selected_exists": False,
        "file_booking_exists": False,
        "search_schema_valid": False,
        "search_matches_input": False,
        "search_providers_schema": False,
        "availability_schema_valid": False,
        "availability_two_providers": False,
        "availability_refs_search": False,
        "availability_slots_iso": False,
        "selected_schema_valid": False,
        "selected_refs_availability": False,
        "selected_date_matches": False,
        "selected_window_matches_input": False,
        "selection_policy_correct": False,
        "selection_is_earliest": False,
        "booking_schema_valid": False,
        "booking_matches_selected": False,
        "booking_customer_matches_input": False
    }

    # Paths
    search_path = build_abs(output_dir, "search_results.json")
    availability_path = build_abs(output_dir, "availability_checks.json")
    selected_path = build_abs(output_dir, "selected_booking.json")
    booking_path = build_abs(output_dir, "booking_confirmation.json")
    request_path = build_abs(input_dir, "request.json")
    customer_path = build_abs(input_dir, "customer.json")

    # Load inputs
    request_data = load_json(request_path)
    customer_data = load_json(customer_path)

    # Load outputs
    search_data = load_json(search_path) if os.path.isfile(search_path) else None
    if search_data is not None:
        checks["file_search_exists"] = True

    availability_data = load_json(availability_path) if os.path.isfile(availability_path) else None
    if availability_data is not None:
        checks["file_availability_exists"] = True

    selected_data = load_json(selected_path) if os.path.isfile(selected_path) else None
    if selected_data is not None:
        checks["file_selected_exists"] = True

    booking_data = load_json(booking_path) if os.path.isfile(booking_path) else None
    if booking_data is not None:
        checks["file_booking_exists"] = True

    # Validate search_results.json schema and match with request
    providers_set: set = set()
    provider_service_set: set = set()
    if isinstance(search_data, dict):
        # required: query, zipCode, maxResults, providers
        q = search_data.get("query")
        zc = search_data.get("zipCode")
        mr = search_data.get("maxResults")
        prov = search_data.get("providers")
        if isinstance(q, str) and isinstance(zc, str) and (isinstance(mr, int) or isinstance(mr, float)) and isinstance(prov, list):
            # providers non-empty with schema
            valid_providers = True
            if len(prov) >= 1:
                for p in prov:
                    if not isinstance(p, dict):
                        valid_providers = False
                        break
                    pid = p.get("providerId")
                    pname = p.get("providerName")
                    services = p.get("services")
                    if not (isinstance(pid, str) and is_non_empty_string(pid) and isinstance(services, list) and len(services) >= 1 and isinstance(pname, str)):
                        valid_providers = False
                        break
                    providers_set.add(pid)
                    for s in services:
                        if not isinstance(s, dict):
                            valid_providers = False
                            break
                        sid = s.get("serviceId")
                        sname = s.get("serviceName")
                        if not (isinstance(sid, str) and is_non_empty_string(sid) and isinstance(sname, str)):
                            valid_providers = False
                            break
                        provider_service_set.add((pid, sid))
                    if not valid_providers:
                        break
            else:
                valid_providers = False
            if valid_providers:
                checks["search_schema_valid"] = True
                checks["search_providers_schema"] = True
            # match with input request
            if isinstance(request_data, dict):
                rq = request_data.get("query")
                rzc = request_data.get("zipCode")
                rmr = request_data.get("maxResults")
                if q == rq and zc == rzc and ((isinstance(mr, (int, float)) and mr == rmr) or (isinstance(mr, int) and isinstance(rmr, int) and mr == rmr)):
                    checks["search_matches_input"] = True

    # Validate availability_checks.json
    checks_arr: List[Dict] = []
    availability_date = None
    if isinstance(availability_data, dict):
        date_val = availability_data.get("date")
        checks_list = availability_data.get("checks")
        if isinstance(date_val, str) and isinstance(checks_list, list):
            # Validate each check
            slots_iso_ok = True
            refs_ok = True
            for item in checks_list:
                if not isinstance(item, dict):
                    slots_iso_ok = False
                    refs_ok = False
                    break
                pid = item.get("providerId")
                sid = item.get("serviceId")
                slots = item.get("availableSlots")
                if not (isinstance(pid, str) and isinstance(sid, str) and isinstance(slots, list)):
                    slots_iso_ok = False
                    refs_ok = False
                    break
                # Check that (pid, sid) corresponds to search_results providers/services
                if (pid, sid) not in provider_service_set:
                    refs_ok = False
                # Validate slots are ISO-8601 and contain the date
                for s in slots:
                    if not (isinstance(s, str) and is_iso8601_datetime(s) and (isinstance(date_val, str) and date_val in s)):
                        slots_iso_ok = False
                        break
                checks_arr.append(item)
            # Two distinct providers
            distinct_providers = len({c.get("providerId") for c in checks_arr if isinstance(c, dict) and isinstance(c.get("providerId"), str)}) >= 2
            if slots_iso_ok:
                checks["availability_slots_iso"] = True
            if refs_ok and len(checks_arr) == len(checks_list):
                checks["availability_refs_search"] = True
            if distinct_providers:
                checks["availability_two_providers"] = True
            checks["availability_schema_valid"] = True
            availability_date = date_val

    # Validate selected_booking.json
    chosen_pid = None
    chosen_sid = None
    chosen_date = None
    chosen_slot = None
    selection_policy = None
    chosen_window = None
    if isinstance(selected_data, dict):
        pid = selected_data.get("providerId")
        sid = selected_data.get("serviceId")
        date_s = selected_data.get("date")
        timeSlot = selected_data.get("timeSlot")
        policy = selected_data.get("selectionPolicy")
        window = selected_data.get("window")
        if (isinstance(pid, str) and isinstance(sid, str) and isinstance(date_s, str) and
            isinstance(timeSlot, str) and is_iso8601_datetime(timeSlot) and isinstance(policy, str) and
            policy in ("window", "any") and isinstance(window, dict) and
            isinstance(window.get("start"), str) and isinstance(window.get("end"), str)):
            checks["selected_schema_valid"] = True
            chosen_pid = pid
            chosen_sid = sid
            chosen_date = date_s
            chosen_slot = timeSlot
            selection_policy = policy
            chosen_window = window

        # selected_refs_availability, date matches, timeSlot contains date, slot in availableSlots for pair
        if checks["selected_schema_valid"] and isinstance(availability_date, str) and isinstance(checks_arr, list):
            # date equality
            if date_s == availability_date and availability_date in timeSlot:
                checks["selected_date_matches"] = True
            # find matching check
            match = None
            for c in checks_arr:
                if c.get("providerId") == pid and c.get("serviceId") == sid:
                    match = c
                    break
            if match:
                slots = match.get("availableSlots", [])
                if isinstance(slots, list) and timeSlot in slots:
                    checks["selected_refs_availability"] = True

        # window matches input
        if checks["selected_schema_valid"] and isinstance(request_data, dict):
            req_window = request_data.get("window")
            if isinstance(req_window, dict) and req_window.get("start") == window.get("start") and req_window.get("end") == window.get("end"):
                checks["selected_window_matches_input"] = True

        # selection_policy_correct based on window inclusion
        if checks["selected_schema_valid"] and chosen_window is not None:
            hhmm = extract_hhmm_from_iso(timeSlot)
            if hhmm is not None:
                within = in_window(hhmm, chosen_window.get("start"), chosen_window.get("end"))
                if (within and policy == "window") or ((not within) and policy == "any"):
                    checks["selection_policy_correct"] = True

        # selection_is_earliest across all checks given the policy and window from input
        if checks["selected_refs_availability"] and isinstance(request_data, dict):
            # Union slots on availability_date only
            all_slots = []
            for c in checks_arr:
                slots = c.get("availableSlots", [])
                if isinstance(slots, list):
                    for s in slots:
                        if isinstance(s, str) and isinstance(availability_date, str) and availability_date in s:
                            all_slots.append(s)
            # Determine expected slot
            expected_slot = None
            if isinstance(request_data.get("window"), dict):
                w = request_data["window"]
                wstart = w.get("start")
                wend = w.get("end")
                if isinstance(wstart, str) and isinstance(wend, str):
                    # earliest within window if any
                    expected_slot = earliest_slot_in_window(all_slots, wstart, wend)
            if expected_slot is None:
                expected_slot = earliest_slot(all_slots)
            if expected_slot is not None and chosen_slot == expected_slot:
                checks["selection_is_earliest"] = True

    # Validate booking_confirmation.json
    if isinstance(booking_data, dict):
        bookingId = booking_data.get("bookingId")
        bpid = booking_data.get("providerId")
        bsid = booking_data.get("serviceId")
        bslot = booking_data.get("timeSlot")
        cust = booking_data.get("customer")
        schema_ok = True
        if not (is_non_empty_string(bookingId) and isinstance(bpid, str) and isinstance(bsid, str) and isinstance(bslot, str) and is_iso8601_datetime(bslot)):
            schema_ok = False
        if not (isinstance(cust, dict) and is_non_empty_string(cust.get("name", "")) and validate_email(cust.get("email", "")) and validate_phone(cust.get("phone", ""))):
            schema_ok = False
        if schema_ok:
            checks["booking_schema_valid"] = True
        # matches selected
        if checks["selected_schema_valid"] and schema_ok:
            if (bpid == chosen_pid) and (bsid == chosen_sid) and (bslot == chosen_slot):
                checks["booking_matches_selected"] = True
        # customer matches input
        if schema_ok and isinstance(customer_data, dict):
            if (cust.get("name") == customer_data.get("name") and
                cust.get("email") == customer_data.get("email") and
                cust.get("phone") == customer_data.get("phone")):
                checks["booking_customer_matches_input"] = True

    # Compute reward: proportion of checks passed, but ensure baseline 0 if required files missing
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline no-op: if any of the four required files is missing, set reward 0
    required_files_present = checks["file_search_exists"] and checks["file_availability_exists"] and checks["file_selected_exists"] and checks["file_booking_exists"]
    reward = (passed / total_checks) if required_files_present else 0.0

    # Ensure reward within [0,1]
    try:
        reward = max(0.0, min(1.0, float(reward)))
    except Exception:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()