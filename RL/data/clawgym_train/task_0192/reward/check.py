import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def split_csv_lines(text):
    # Simple CSV splitter assuming no embedded commas and standard newline handling
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    return lines

def ci_contains(haystack, needle):
    return needle.lower() in haystack.lower()

def last_nonempty_print(obj):
    # Ensure the last non-empty stdout line is the JSON object
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # hospitality_plan.json related
        "has_hospitality_plan_json": False,
        "hospitality_plan_valid_json": False,
        "hospitality_plan_exact_keys": False,
        "reception_plan_timeline_keywords": False,
        "seating_arrangement_names_protocol_alternating": False,
        "dining_arrangements_restaurant_halal_no_alcohol": False,
        "etiquette_guide_keywords": False,
        "gift_suggestions_valid_names_budget_no_alcohol": False,
        "talking_points_required_topics": False,
        "follow_up_plan_timing_thanks_proposal": False,
        # itinerary.csv related
        "has_itinerary_csv": False,
        "itinerary_header_ok": False,
        "itinerary_min_rows": False,
        "itinerary_days_covered": False,
        "itinerary_has_arrival": False,
        "itinerary_has_tour": False,
        "itinerary_has_prayer": False,
        "itinerary_meal_includes_both_names": False,
    }

    # Expected artifacts
    plan_path = os.path.join(output_dir, "hospitality_plan.json")
    itin_path = os.path.join(output_dir, "itinerary.csv")

    # Load hospitality_plan.json
    if os.path.isfile(plan_path):
        checks["has_hospitality_plan_json"] = True
        plan_obj = parse_json(plan_path)
        if isinstance(plan_obj, dict):
            checks["hospitality_plan_valid_json"] = True
            required_keys = [
                "reception_plan",
                "seating_arrangement",
                "dining_arrangements",
                "etiquette_guide",
                "gift_suggestions",
                "talking_points",
                "follow_up_plan",
            ]
            # Check exactly these keys, all must be non-empty strings
            keys_ok = set(plan_obj.keys()) == set(required_keys)
            values_ok = True
            for k in required_keys:
                v = plan_obj.get(k, None)
                if not isinstance(v, str) or len(v.strip()) == 0:
                    values_ok = False
                    break
            checks["hospitality_plan_exact_keys"] = keys_ok and values_ok

            # Convenience get values only if strings
            rp = plan_obj.get("reception_plan") if isinstance(plan_obj.get("reception_plan"), str) else ""
            sa = plan_obj.get("seating_arrangement") if isinstance(plan_obj.get("seating_arrangement"), str) else ""
            da = plan_obj.get("dining_arrangements") if isinstance(plan_obj.get("dining_arrangements"), str) else ""
            eg = plan_obj.get("etiquette_guide") if isinstance(plan_obj.get("etiquette_guide"), str) else ""
            gs = plan_obj.get("gift_suggestions") if isinstance(plan_obj.get("gift_suggestions"), str) else ""
            tp = plan_obj.get("talking_points") if isinstance(plan_obj.get("talking_points"), str) else ""
            fp = plan_obj.get("follow_up_plan") if isinstance(plan_obj.get("follow_up_plan"), str) else ""

            # reception_plan: must include "Day 1", "Day 2" and words "arrival", "tour", "prayer"
            if ("Day 1" in rp) and ("Day 2" in rp) and ci_contains(rp, "arrival") and ci_contains(rp, "tour") and ci_contains(rp, "prayer"):
                checks["reception_plan_timeline_keywords"] = True

            # seating_arrangement: includes lead guest and host CEO names ("Layla" or "Layla Al-Farsi") and ("Alex" or "Alex Morgan"),
            # and contains "seniority" or "protocol" and "alternating"
            sa_l = sa.lower()
            has_layla = ("layla" in sa_l) or ("layla al-farsi" in sa_l)
            has_alex = ("alex" in sa_l) or ("alex morgan" in sa_l)
            has_seniority_or_protocol = ("seniority" in sa_l) or ("protocol" in sa_l)
            has_alternating = "alternating" in sa_l
            if has_layla and has_alex and has_seniority_or_protocol and has_alternating:
                checks["seating_arrangement_names_protocol_alternating"] = True

            # dining_arrangements: contains at least one exact restaurant name and contains "halal" and "no alcohol"
            # Exact restaurants allowed: "Cedar & Spice (Halal Certified)" or "Green Leaf Bistro"
            exact_restaurants = [
                "Cedar & Spice (Halal Certified)",
                "Green Leaf Bistro",
            ]
            has_exact_restaurant = any(name in da for name in exact_restaurants)
            if has_exact_restaurant and ci_contains(da, "halal") and ci_contains(da, "no alcohol"):
                checks["dining_arrangements_restaurant_halal_no_alcohol"] = True

            # etiquette_guide: contains "no alcohol", "handshake", and "prayer"
            if ci_contains(eg, "no alcohol") and ci_contains(eg, "handshake") and ci_contains(eg, "prayer"):
                checks["etiquette_guide_keywords"] = True

            # gift_suggestions: contains at least two exact gift names among specific list, not contain "Crystal Wine Set",
            # and mentions budget context (presence of "$" or "budget")
            gift_names_allowed = [
                "Hamilton Leather Notebook",
                "City Artisan Date Selection",
                "Premium Tea Sampler (No Alcohol)",
            ]
            count_present = sum(1 for g in gift_names_allowed if g in gs)
            not_contains_wine_set = ("Crystal Wine Set" not in gs)
            budget_context = ("$" in gs) or ("budget" in gs.lower())
            if count_present >= 2 and not_contains_wine_set and budget_context:
                checks["gift_suggestions_valid_names_budget_no_alcohol"] = True

            # talking_points: contains "JV", "sustainability", "supply chain"
            if ci_contains(tp, "JV") and ci_contains(tp, "sustainability") and ci_contains(tp, "supply chain"):
                checks["talking_points_required_topics"] = True

            # follow_up_plan: contains "24", and words "thank" and "proposal"
            if ("24" in fp) and ci_contains(fp, "thank") and ci_contains(fp, "proposal"):
                checks["follow_up_plan_timing_thanks_proposal"] = True

    # Load itinerary.csv
    if os.path.isfile(itin_path):
        checks["has_itinerary_csv"] = True
        csv_text = read_text(itin_path)
        if isinstance(csv_text, str):
            lines = split_csv_lines(csv_text)
            if len(lines) >= 1:
                header = lines[0]
                if header == "day,time,activity,location,participants":
                    checks["itinerary_header_ok"] = True
                data_rows = lines[1:] if len(lines) > 1 else []
                # Filter out any rows that don't have 5 columns when split by comma
                parsed_rows = []
                for row in data_rows:
                    cols = [c.strip() for c in row.split(",")]
                    if len(cols) >= 5:
                        # If more columns, join extras into participants to be tolerant
                        if len(cols) > 5:
                            cols = cols[:4] + [",".join(cols[4:]).strip()]
                        parsed_rows.append(cols)

                if len(parsed_rows) >= 6:
                    checks["itinerary_min_rows"] = True

                # Checks on content
                has_day1 = False
                has_day2 = False
                has_arrival = False
                has_tour = False
                has_prayer = False
                meal_with_both_names = False

                for cols in parsed_rows:
                    day, time, activity, location, participants = cols[0], cols[1], cols[2], cols[3], cols[4]
                    day_l = day.lower()
                    activity_l = activity.lower()
                    participants_l = participants.lower()
                    if "day 1" in day_l:
                        has_day1 = True
                    if "day 2" in day_l:
                        has_day2 = True
                    if "arrival" in activity_l:
                        has_arrival = True
                    if "tour" in activity_l:
                        has_tour = True
                    if "prayer" in activity_l:
                        has_prayer = True
                    if ("lunch" in activity_l or "dinner" in activity_l):
                        has_layla = ("layla al-farsi" in participants_l) or ("layla" in participants_l)
                        has_alex = ("alex morgan" in participants_l) or ("alex" in participants_l)
                        if has_layla and has_alex:
                            meal_with_both_names = True

                if has_day1 and has_day2:
                    checks["itinerary_days_covered"] = True
                if has_arrival:
                    checks["itinerary_has_arrival"] = True
                if has_tour:
                    checks["itinerary_has_tour"] = True
                if has_prayer:
                    checks["itinerary_has_prayer"] = True
                if meal_with_both_names:
                    checks["itinerary_meal_includes_both_names"] = True

    # Compute reward as proportion of passed checks.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure the no-op baseline yields 0.0 when no artifacts exist
    # If both main artifacts are missing or output dir absent, force reward = 0.0
    output_exists = os.path.isdir(output_dir)
    if (not output_exists) or (not checks["has_hospitality_plan_json"] and not checks["has_itinerary_csv"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    # Place reward first, then checks
    result.update(checks)
    last_nonempty_print(result)

if __name__ == "__main__":
    main()