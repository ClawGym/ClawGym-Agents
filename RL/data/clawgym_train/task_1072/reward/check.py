import json
import os
import sys
import re

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_simple_yaml(path):
    """
    Minimal YAML parser for simple key: value pairs.
    Converts keys to a normalized form (lowercase, remove non-alnum) to reduce brittleness.
    Supports basic scalars: strings, integers, booleans.
    """
    data = {}
    text = read_file(path)
    if text is None:
        return data
    for line in text.splitlines():
        # strip comments
        if "#" in line:
            # keep content before '#'
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_\-\s]+)\s*:\s*(.+)?$", line)
        if not m:
            continue
        key_raw = m.group(1).strip()
        val_raw = (m.group(2) or "").strip()
        # normalize key: lowercase and remove non-alphanumeric
        key_norm = re.sub(r"[^a-z0-9]", "", key_raw.lower())
        # parse value
        v = val_raw
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.lower() in ("yes", "no"):
            v = v.lower() == "yes"
        else:
            # try int
            try:
                v = int(v)
            except Exception:
                # keep as string (strip surrounding quotes if present)
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
        data[key_norm] = v
    return data

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "plan_exists": False,
        "plan_json_valid": False,
        "tradeoffs_exists": False,
        "tradeoffs_json_valid": False,
        "plan_has_required_keys": False,
        "base_city_nonempty": False,
        "base_neighborhood_nonempty": False,
        "itinerary_length_matches": False,
        "itinerary_items_valid": False,
        "itinerary_days_sequential": False,
        "entry_nationality_matches": False,
        "entry_visa_notes_mentions": False,
        "money_pix_strategy_keywords": False,
        "money_cash_buffer_nonempty": False,
        "arrival_late_flag_matches": False,
        "arrival_transport_recommendation_keywords": False,
        "booking_priorities_count": False,
        "safety_notes_keywords": False,
        "weather_fallbacks_count": False,
        "connectivity_mentions_esim_or_sim": False,
        "tradeoffs_file_path_correct": False,
        "tradeoffs_length_matches": False,
        "tradeoffs_addons_match": False,
        "tradeoffs_items_fields_valid": False,
    }

    # Paths
    plan_path = os.path.join(output_dir, "plan.json")
    tradeoffs_path = os.path.join(output_dir, "tradeoffs.json")
    trip_prefs_path = os.path.join(input_dir, "trip_prefs.yaml")
    proposed_addons_path = os.path.join(input_dir, "proposed_addons.txt")

    # Read inputs
    prefs = parse_simple_yaml(trip_prefs_path)
    nationality = prefs.get("nationality", None)
    latenightarrival = prefs.get("latenightarrival", None)
    # accept alternative key if present (e.g., latenightarrivalflag)
    if latenightarrival is None:
        latenightarrival = prefs.get("latenightarrivalflag", None)
    duration_days = prefs.get("durationdays", None)

    # Load outputs
    plan = None
    tradeoffs = None

    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan = load_json(plan_path)
        if isinstance(plan, dict):
            checks["plan_json_valid"] = True

    if os.path.isfile(tradeoffs_path):
        checks["tradeoffs_exists"] = True
        tradeoffs = load_json(tradeoffs_path)
        if isinstance(tradeoffs, list):
            checks["tradeoffs_json_valid"] = True

    # Evaluate plan.json structure
    if checks["plan_json_valid"]:
        required_keys = [
            "base", "itinerary", "entry", "money", "arrival_plan",
            "booking_priorities", "safety_notes", "weather_fallbacks",
            "connectivity", "tradeoffs_file"
        ]
        if all(k in plan for k in required_keys):
            checks["plan_has_required_keys"] = True

            # base
            base = plan.get("base", {})
            if isinstance(base, dict):
                city = base.get("city", "")
                neighborhood = base.get("neighborhood", "")
                if isinstance(city, str) and city.strip():
                    checks["base_city_nonempty"] = True
                if isinstance(neighborhood, str) and neighborhood.strip():
                    checks["base_neighborhood_nonempty"] = True

            # itinerary
            itinerary = plan.get("itinerary", [])
            itinerary_valid = True
            days_list = []
            if isinstance(itinerary, list):
                # length equals duration_days
                if isinstance(duration_days, int) and len(itinerary) == duration_days:
                    checks["itinerary_length_matches"] = True
                # validate items
                for item in itinerary:
                    if not isinstance(item, dict):
                        itinerary_valid = False
                        break
                    d = item.get("day")
                    p = item.get("plan")
                    if not (isinstance(d, int) and isinstance(p, str) and p.strip()):
                        itinerary_valid = False
                        break
                    days_list.append(d)
                if itinerary_valid:
                    checks["itinerary_items_valid"] = True
                    # optional sequential days check: 1..n increasing by 1
                    if len(days_list) > 0:
                        sorted_days = sorted(days_list)
                        expected = list(range(1, len(days_list) + 1))
                        if sorted_days == expected:
                            checks["itinerary_days_sequential"] = True

            # entry
            entry = plan.get("entry", {})
            if isinstance(entry, dict):
                nat_out = entry.get("nationality", None)
                visa_notes = entry.get("visa_notes", "")
                if isinstance(nationality, str) and nat_out == nationality:
                    checks["entry_nationality_matches"] = True
                if isinstance(visa_notes, str):
                    vn_lower = visa_notes.lower()
                    # must include "visa" or "evisa" and also "passport"
                    if (("visa" in vn_lower) or ("evisa" in vn_lower)) and ("passport" in vn_lower):
                        checks["entry_visa_notes_mentions"] = True

            # money
            money = plan.get("money", {})
            if isinstance(money, dict):
                pix_strategy = money.get("pix_strategy", "")
                cash_buffer = money.get("cash_buffer", "")
                if isinstance(pix_strategy, str) and ("PIX" in pix_strategy) and ("CPF" in pix_strategy):
                    checks["money_pix_strategy_keywords"] = True
                if isinstance(cash_buffer, str) and cash_buffer.strip():
                    checks["money_cash_buffer_nonempty"] = True

            # arrival plan
            arrival = plan.get("arrival_plan", {})
            if isinstance(arrival, dict):
                late_flag_out = arrival.get("late_night_arrival", None)
                tr = arrival.get("transport_recommendation", "")
                if isinstance(latenightarrival, bool) and isinstance(late_flag_out, bool) and late_flag_out == latenightarrival:
                    checks["arrival_late_flag_matches"] = True
                if isinstance(tr, str):
                    tl = tr.lower()
                    if ("taxi" in tl or "ride-hail" in tl) and ("avoid" in tl):
                        checks["arrival_transport_recommendation_keywords"] = True

            # booking priorities
            bp = plan.get("booking_priorities", [])
            if isinstance(bp, list) and len(bp) >= 3 and all(isinstance(x, str) for x in bp):
                checks["booking_priorities_count"] = True

            # safety notes
            sn = plan.get("safety_notes", "")
            if isinstance(sn, str):
                sl = sn.lower()
                if ("theft" in sl) and ("heat" in sl):
                    checks["safety_notes_keywords"] = True

            # weather fallbacks
            wf = plan.get("weather_fallbacks", [])
            if isinstance(wf, list) and len(wf) >= 1 and all(isinstance(x, str) for x in wf):
                checks["weather_fallbacks_count"] = True

            # connectivity
            conn = plan.get("connectivity", "")
            if isinstance(conn, str):
                cl = conn.lower()
                if ("esim" in cl) or (re.search(r"\bsim\b", cl) is not None):
                    checks["connectivity_mentions_esim_or_sim"] = True

            # tradeoffs file path
            tof = plan.get("tradeoffs_file", "")
            if isinstance(tof, str) and tof == "output/tradeoffs.json":
                checks["tradeoffs_file_path_correct"] = True

    # Evaluate tradeoffs.json
    proposed_lines = []
    # read proposed_addons.txt
    prop_text = read_file(proposed_addons_path)
    if prop_text is not None:
        for line in prop_text.splitlines():
            if line.strip() != "":
                proposed_lines.append(line.strip())

    if checks["tradeoffs_json_valid"]:
        # Must be array with length equal to non-empty lines in proposed_addons.txt
        if isinstance(tradeoffs, list):
            if len(tradeoffs) == len(proposed_lines):
                checks["tradeoffs_length_matches"] = True

            # Check add_on coverage and item-specific fields
            add_on_values = []
            items_fields_ok = True
            for item in tradeoffs:
                if not isinstance(item, dict):
                    items_fields_ok = False
                    break
                add_on = item.get("add_on", None)
                included = item.get("included", None)
                if not isinstance(add_on, str) or add_on.strip() == "" or not isinstance(included, bool):
                    items_fields_ok = False
                    break
                add_on_values.append(add_on.strip())
                if included:
                    tcost = item.get("transfer_cost_hours", None)
                    if not is_number(tcost) or (tcost is not None and tcost <= 0):
                        items_fields_ok = False
                        break
                else:
                    reason = item.get("reason_excluded", None)
                    if not (isinstance(reason, str) and reason.strip()):
                        items_fields_ok = False
                        break

            # Add-on matching: all add_on values must match proposed lines (trimmed)
            if len(add_on_values) == len(proposed_lines) and all(a in proposed_lines for a in add_on_values):
                checks["tradeoffs_addons_match"] = True
            else:
                checks["tradeoffs_addons_match"] = False

            if items_fields_ok:
                checks["tradeoffs_items_fields_valid"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Baseline: if both outputs missing or output dir missing/empty, reward must be 0.0
    output_exists = os.path.isdir(output_dir) and any(
        os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir) if os.path.exists(output_dir)
    )
    if not output_exists:
        reward = 0.0
    else:
        # If neither plan nor tradeoffs exists, no reward
        if not checks["plan_exists"] and not checks["tradeoffs_exists"]:
            reward = 0.0
        else:
            reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()