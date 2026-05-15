import json
import os
import re
import sys
from typing import Any, Dict, List

def is_number_like(val: Any) -> bool:
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        s = val.strip()
        # Remove common currency symbols and commas
        s = s.replace(",", "")
        s = s.replace("€", "").replace("$", "")
        # Extract first number-like pattern
        m = re.search(r"-?\d+(\.\d+)?", s)
        return m is not None
    return False

def to_lower_set(items: List[str]) -> set:
    return set([str(x).lower() for x in items])

def extract_leg_endpoints(leg: Any) -> List[str]:
    """
    Attempt to extract endpoints for an intercity leg.
    Returns a list of lowercased tokens of place names found.
    """
    endpoints = []
    if isinstance(leg, dict):
        for key in ["from", "to", "origin", "destination", "start", "end"]:
            if key in leg and isinstance(leg[key], str):
                endpoints.append(leg[key].strip())
    elif isinstance(leg, str):
        # Split around common separators
        parts = re.split(r"\s*(->|—|-|to|→)\s*", leg)
        # Keep non-separator tokens
        tokens = [p for i, p in enumerate(parts) if i % 2 == 0 and p.strip()]
        endpoints.extend([t.strip() for t in tokens])
    return [e.lower() for e in endpoints]

def contains_keyword(hay: str, needle: str) -> bool:
    return needle.lower() in hay.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}
    # Initialize all checks to False
    check_names = [
        "required_outputs_present",
        "has_itinerary_json",
        "itinerary_json_valid",
        "json_has_required_top_level_fields",
        "entry_fields_valid",
        "season_fields_valid",
        "corridor_valid",
        "base_cities_valid",
        "day_by_day_length_10",
        "day_by_day_items_valid",
        "has_transfer_windows",
        "has_weather_sensitive_and_backups",
        "transport_rail_first",
        "intercity_legs_present",
        "car_variant_present",
        "reservations_deadlines_present",
        "airport_transfers_present",
        "departure_buffer_true",
        "budget_fields_valid",
        "safety_emergency_numbers_valid",
        "safety_mountain_risk_present",
        "payment_fields_present",
        "rail_corridor_sequence_consistent",
        "has_itinerary_md",
        "itinerary_md_nonempty",
        "itinerary_md_has_sections",
        "rubric_notes_present"
    ]
    for n in check_names:
        checks[n] = False

    json_path = os.path.join(output_dir, "itinerary.json")
    md_path = os.path.join(output_dir, "itinerary.md")

    json_exists = os.path.isfile(json_path)
    md_exists = os.path.isfile(md_path)
    checks["has_itinerary_json"] = json_exists
    checks["has_itinerary_md"] = md_exists
    checks["required_outputs_present"] = json_exists and md_exists

    data: Dict[str, Any] = {}
    if json_exists:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["itinerary_json_valid"] = True
        except Exception:
            checks["itinerary_json_valid"] = False

    # Validate JSON structure if valid
    if checks["itinerary_json_valid"]:
        required_top_keys = [
            "entry",
            "season",
            "corridor",
            "base_cities",
            "day_by_day",
            "transport",
            "reservations",
            "airport_transfers",
            "departure_buffer",
            "weather_backups",
            "budget",
            "safety",
            "payment",
            "rubric_notes",
        ]
        if all(k in data for k in required_top_keys):
            checks["json_has_required_top_level_fields"] = True

        # entry fields
        entry_ok = False
        try:
            entry = data.get("entry", {})
            passport = entry.get("passport", None)
            schengen_days_total = entry.get("schengen_days_total", None)
            visa_path_locked = entry.get("visa_path_locked", None)
            passport_validity_checked = entry.get("passport_validity_checked", None)
            entry_ok = (
                passport is not None
                and (isinstance(schengen_days_total, (int, float)) or is_number_like(schengen_days_total))
                and visa_path_locked is True
                and passport_validity_checked is True
            )
        except Exception:
            entry_ok = False
        checks["entry_fields_valid"] = entry_ok

        # season fields
        season_ok = False
        try:
            season = data.get("season", {})
            month = season.get("month", "")
            season_type = season.get("season_type", "")
            season_ok = contains_keyword(str(month), "july") and contains_keyword(str(season_type), "summer")
        except Exception:
            season_ok = False
        checks["season_fields_valid"] = season_ok

        # corridor check
        corridor_ok = False
        try:
            corridor = str(data.get("corridor", "")).strip()
            corridor_l = corridor.lower()
            corridor_ok = (
                len(corridor) > 0
                and ("vienna" in corridor_l)
                and ("salzburg" in corridor_l)
                and (("innsbruck" in corridor_l) or ("tyrol" in corridor_l) or ("tirol" in corridor_l))
            )
        except Exception:
            corridor_ok = False
        checks["corridor_valid"] = corridor_ok

        # base cities
        base_ok = False
        try:
            base_cities = data.get("base_cities", [])
            if isinstance(base_cities, list):
                bases_l = [str(b).lower() for b in base_cities]
                has_vienna = any("vienna" in b for b in bases_l)
                has_salzburg = any("salzburg" in b for b in bases_l)
                has_tirol = any(("innsbruck" in b) or ("tyrol" in b) or ("tirol" in b) for b in bases_l)
                base_ok = has_vienna and has_salzburg and has_tirol
        except Exception:
            base_ok = False
        checks["base_cities_valid"] = base_ok

        # day_by_day
        dby_ok = False
        dby_items_ok = False
        transfer_windows_ok = False
        weather_sensitive_ok = False
        try:
            dby = data.get("day_by_day", [])
            if isinstance(dby, list) and len(dby) == 10:
                dby_ok = True
            # Validate each item minimal structure
            items_ok = True
            tw_count = 0
            ws_any = False
            for item in dby if isinstance(dby, list) else []:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                if "day" not in item or "base" not in item or "activities" not in item:
                    items_ok = False
                    break
                if not isinstance(item.get("activities"), list):
                    items_ok = False
                    break
                if "transfer_window" in item:
                    tw_count += 1
                if item.get("weather_sensitive", False) is True:
                    ws_any = True
            dby_items_ok = items_ok
            transfer_windows_ok = tw_count >= 1  # at least some items include transfer_window
            weather_sensitive_ok = ws_any
        except Exception:
            dby_ok = False
            dby_items_ok = False
            transfer_windows_ok = False
            weather_sensitive_ok = False
        checks["day_by_day_length_10"] = dby_ok
        checks["day_by_day_items_valid"] = dby_items_ok
        checks["has_transfer_windows"] = transfer_windows_ok

        # weather backups non-empty and combined with at least one weather-sensitive day
        wb_ok = False
        try:
            weather_backups = data.get("weather_backups", [])
            wb_ok = isinstance(weather_backups, list) and len(weather_backups) > 0 and weather_sensitive_ok
        except Exception:
            wb_ok = False
        checks["has_weather_sensitive_and_backups"] = wb_ok

        # transport
        rail_first_ok = False
        intercity_legs_ok = False
        car_variant_ok = False
        rail_seq_ok = False
        try:
            transport = data.get("transport", {})
            rail_first_ok = transport.get("rail_first", False) is True
            intercity_legs = transport.get("intercity_legs", [])
            intercity_legs_ok = isinstance(intercity_legs, list) and len(intercity_legs) > 0

            car_variant = transport.get("car_variant", {})
            if isinstance(car_variant, dict):
                cv_enabled_present = isinstance(car_variant.get("enabled", None), bool)
                cv_when = car_variant.get("when_to_use", "")
                cv_costs = car_variant.get("estimated_costs", {})
                car_variant_ok = cv_enabled_present and isinstance(cv_when, str) and len(cv_when.strip()) > 0 and isinstance(cv_costs, dict)

            # Check for Vienna->Salzburg and Salzburg->(Innsbruck/Tyrol) legs
            # For each leg, collect endpoints and look for pairs
            has_v_to_s = False
            has_s_to_t = False
            for leg in intercity_legs if isinstance(intercity_legs, list) else []:
                endpoints = extract_leg_endpoints(leg)
                text = " ".join(endpoints).lower()
                if "vienna" in text and "salzburg" in text:
                    has_v_to_s = True
                if "salzburg" in text and ("innsbruck" in text or "tyrol" in text or "tirol" in text):
                    has_s_to_t = True
            rail_seq_ok = has_v_to_s and has_s_to_t
        except Exception:
            rail_first_ok = False
            intercity_legs_ok = False
            car_variant_ok = False
            rail_seq_ok = False
        checks["transport_rail_first"] = rail_first_ok
        checks["intercity_legs_present"] = intercity_legs_ok
        checks["car_variant_present"] = car_variant_ok
        checks["rail_corridor_sequence_consistent"] = rail_seq_ok

        # reservations deadlines
        res_ok = False
        try:
            reservations = data.get("reservations", {})
            deadlines = reservations.get("deadlines", [])
            res_ok = isinstance(deadlines, list) and len(deadlines) > 0
        except Exception:
            res_ok = False
        checks["reservations_deadlines_present"] = res_ok

        # airport transfers
        at_ok = False
        try:
            at = data.get("airport_transfers", {})
            at_ok = isinstance(at, dict) and ("arrival" in at) and ("departure" in at)
        except Exception:
            at_ok = False
        checks["airport_transfers_present"] = at_ok

        # departure buffer
        depbuf_ok = False
        try:
            depbuf = data.get("departure_buffer", None)
            depbuf_ok = depbuf is True
        except Exception:
            depbuf_ok = False
        checks["departure_buffer_true"] = depbuf_ok

        # budget numeric fields
        budget_ok = False
        try:
            budget = data.get("budget", {})
            req_fields = [
                "rail_tickets",
                "local_transit_passes",
                "car_costs",
                "tolls_parking_vignette",
                "mountain_lifts",
                "hotels",
                "meals_misc",
            ]
            if isinstance(budget, dict) and all(k in budget for k in req_fields):
                budget_ok = all(is_number_like(budget.get(k)) for k in req_fields)
        except Exception:
            budget_ok = False
        checks["budget_fields_valid"] = budget_ok

        # safety
        safety_em_ok = False
        safety_mr_ok = False
        try:
            safety = data.get("safety", {})
            em_nums = safety.get("emergency_numbers", [])
            if isinstance(em_nums, list):
                em_strs = [str(x) for x in em_nums]
                safety_em_ok = ("112" in em_strs) or ("144" in em_strs)
            mr = safety.get("mountain_risk", "")
            safety_mr_ok = isinstance(mr, str) and len(mr.strip()) > 0
        except Exception:
            safety_em_ok = False
            safety_mr_ok = False
        checks["safety_emergency_numbers_valid"] = safety_em_ok
        checks["safety_mountain_risk_present"] = safety_mr_ok

        # payment
        pay_ok = False
        try:
            pay = data.get("payment", {})
            cards = pay.get("cards", "")
            cash = pay.get("cash", "")
            tipping = pay.get("tipping", "")
            pay_ok = (
                isinstance(cards, str) and len(cards.strip()) > 0
                and isinstance(cash, str) and len(cash.strip()) > 0
                and isinstance(tipping, str) and len(tipping.strip()) > 0
            )
        except Exception:
            pay_ok = False
        checks["payment_fields_present"] = pay_ok

        # rubric_notes presence
        rn_ok = False
        try:
            rn = data.get("rubric_notes", {})
            rn_ok = isinstance(rn, dict) and all(k in rn for k in ["pace_logic", "accessibility_considerations", "why_rail_first"])
        except Exception:
            rn_ok = False
        checks["rubric_notes_present"] = rn_ok

    # Validate MD
    if md_exists:
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            checks["itinerary_md_nonempty"] = len(md_content.strip()) > 0
            lc = md_content.lower()
            required_phrases = [
                "base-city strategy",
                "day-by-day",
                "transfer window",
                "reservation deadlines",
                "rail-first",
                "car variant",
                "budget",
                "safety",
                "payment",
                "emergency",
            ]
            checks["itinerary_md_has_sections"] = all(phrase in lc for phrase in required_phrases)
        except Exception:
            checks["itinerary_md_nonempty"] = False
            checks["itinerary_md_has_sections"] = False

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if checks["required_outputs_present"] else 0.0
    # Clamp reward
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()