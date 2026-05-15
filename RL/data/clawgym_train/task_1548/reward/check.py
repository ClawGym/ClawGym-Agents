import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def normalize_bearing(deg: float) -> float:
    res = deg % 360.0
    if res < 0:
        res += 360.0
    return res

def round1(x: float) -> float:
    return round(x + 1e-12, 1)

def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def parse_floats_from_text(text: str) -> List[float]:
    nums = []
    # Capture floats/ints with optional sign
    for m in re.finditer(r'[-+]?\d+(?:\.\d+)?', text):
        try:
            nums.append(float(m.group(0)))
        except:
            pass
    return nums

def has_number_approximately(text: str, target: float, tol: float = 0.1) -> bool:
    nums = parse_floats_from_text(text)
    for n in nums:
        if abs(n - target) <= tol:
            return True
    # Also try matching the exact string representation (robust against formatting)
    target_str = str(target)
    if target_str in text:
        return True
    # Try a version trimmed to 1 decimal
    target_1 = f"{target:.1f}"
    if target_1 in text:
        return True
    # Try integer form if it's close to an int
    if abs(target - round(target)) < 1e-6:
        if str(int(round(target))) in text:
            return True
    return False

def compute_expected_leg_metrics(leg: Dict[str, Any]) -> Tuple[float, float, float]:
    fe = float(leg["from"]["easting"])
    fn = float(leg["from"]["northing"])
    te = float(leg["to"]["easting"])
    tn = float(leg["to"]["northing"])
    dE = te - fe
    dN = tn - fn
    grid_deg = math.degrees(math.atan2(dE, dN))
    grid_deg = normalize_bearing(grid_deg)
    dist_m = math.hypot(dE, dN)
    return grid_deg, dist_m, dE

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Initialize checks to False
    checks["route_card_exists"] = False
    checks["route_card_json_valid"] = False
    checks["route_card_top_fields_match_input"] = False
    checks["route_card_legs_count_match"] = False
    checks["route_card_legs_structure_names_coords_ok"] = False
    checks["route_card_grid_bearings_within_tolerance"] = False
    checks["route_card_magnetic_bearings_within_tolerance"] = False
    checks["route_card_distances_within_tolerance"] = False
    checks["route_card_estimated_paces_within_tolerance"] = False
    checks["route_card_handrails_backstops_present"] = False

    checks["training_plan_exists"] = False
    checks["training_plan_declination_and_value_present"] = False
    checks["training_plan_declination_application_explained"] = False
    checks["training_plan_keywords_present"] = False
    checks["training_plan_safety_phone_and_911_and_route"] = False
    checks["training_plan_practice_refs_leg_names"] = False

    # Load input reference
    input_path = os.path.join(input_dir, "navigation_brief.json")
    try:
        input_data = load_json_file(input_path)
    except Exception:
        # If input missing or invalid, we cannot score positives that depend on outputs.
        # We still must ensure overall behavior yields 0 if outputs missing.
        input_data = None

    # ROUTE CARD CHECKS
    route_path = os.path.join(output_dir, "route_card.json")
    if os.path.isfile(route_path):
        checks["route_card_exists"] = True
        route_data = None
        try:
            route_data = load_json_file(route_path)
            if isinstance(route_data, dict):
                checks["route_card_json_valid"] = True
        except Exception:
            route_data = None

        if route_data and input_data and isinstance(input_data, dict):
            # Validate top-level keys and equality to input
            top_fields_ok = True
            try:
                # Required keys
                required_keys = [
                    "location",
                    "declination_deg_east_positive",
                    "grid_system",
                    "assume_grid_equals_true_north",
                    "pace_count_per_100m",
                    "legs",
                ]
                for k in required_keys:
                    if k not in route_data:
                        top_fields_ok = False
                        break
                if top_fields_ok:
                    # Match to input
                    if (route_data.get("location") != input_data.get("location")
                        or route_data.get("grid_system") != input_data.get("grid_system")
                        or bool(route_data.get("assume_grid_equals_true_north")) != bool(input_data.get("assume_grid_equals_true_north"))):
                        top_fields_ok = False
                    else:
                        # declination numeric equality
                        in_decl = float(input_data.get("declination_deg_east_positive"))
                        out_decl = float(route_data.get("declination_deg_east_positive"))
                        if abs(in_decl - out_decl) > 1e-6:
                            top_fields_ok = False
                        # pace count numeric presence
                        _ = float(route_data.get("pace_count_per_100m"))
                checks["route_card_top_fields_match_input"] = top_fields_ok
            except Exception:
                checks["route_card_top_fields_match_input"] = False

            # Legs length
            legs_count_ok = False
            input_legs = input_data.get("legs") if isinstance(input_data, dict) else None
            out_legs = route_data.get("legs") if isinstance(route_data, dict) else None

            if isinstance(input_legs, list) and isinstance(out_legs, list):
                if len(input_legs) == len(out_legs):
                    legs_count_ok = True
            checks["route_card_legs_count_match"] = legs_count_ok

            # Initialize per-leg counters for score
            total_leg_checks = 0
            passed_leg_checks = 0

            # Validate legs structure: names and coordinates mirror input in order
            legs_structure_ok = True
            grid_bearings_all_ok = True
            mag_bearings_all_ok = True
            distances_all_ok = True
            paces_all_ok = True
            handrails_backstops_all_ok = True

            # Tolerances
            deg_tol = 1.0
            dist_tol = 10.0  # meters
            paces_tol = 5     # paces

            if legs_count_ok:
                try:
                    in_decl = float(input_data["declination_deg_east_positive"])
                    pace_per_100m = float(input_data["pace_count_per_100m"])
                except Exception:
                    in_decl = None
                    pace_per_100m = None

                for i in range(len(input_legs)):
                    in_leg = input_legs[i]
                    out_leg = out_legs[i]

                    # Names and coordinates mirror
                    total_leg_checks += 1
                    try:
                        from_name_ok = out_leg.get("from_name") == in_leg.get("from_name")
                        to_name_ok = out_leg.get("to_name") == in_leg.get("to_name")

                        # Coordinates mirror
                        fe_ok = float(out_leg.get("from", {}).get("easting")) == float(in_leg.get("from", {}).get("easting"))
                        fn_ok = float(out_leg.get("from", {}).get("northing")) == float(in_leg.get("from", {}).get("northing"))
                        te_ok = float(out_leg.get("to", {}).get("easting")) == float(in_leg.get("to", {}).get("easting"))
                        tn_ok = float(out_leg.get("to", {}).get("northing")) == float(in_leg.get("to", {}).get("northing"))
                        this_struct_ok = all([from_name_ok, to_name_ok, fe_ok, fn_ok, te_ok, tn_ok])
                    except Exception:
                        this_struct_ok = False

                    if not this_struct_ok:
                        legs_structure_ok = False
                    else:
                        passed_leg_checks += 1

                    # Compute expected values if possible
                    try:
                        # Compute expected grid bearing and distance
                        exp_grid_deg, exp_dist_m, _ = compute_expected_leg_metrics(in_leg)
                        exp_grid_deg_r = round1(exp_grid_deg)
                        # Magnetic: grid - declination (east positive)
                        if in_decl is None:
                            this_grid_ok = False
                            this_mag_ok = False
                        else:
                            exp_mag_deg = normalize_bearing(exp_grid_deg_r - in_decl)
                            exp_mag_deg_r = round1(exp_mag_deg)

                            # Compare with output values
                            out_grid = float(out_leg.get("grid_bearing_deg"))
                            out_mag = float(out_leg.get("magnetic_bearing_deg"))

                            # Tolerance check
                            if abs(exp_grid_deg_r - out_grid) <= deg_tol:
                                this_grid_ok = True
                            else:
                                this_grid_ok = False
                            if abs(exp_mag_deg_r - out_mag) <= deg_tol:
                                this_mag_ok = True
                            else:
                                this_mag_ok = False
                    except Exception:
                        this_grid_ok = False
                        this_mag_ok = False

                    total_leg_checks += 1
                    if this_grid_ok:
                        passed_leg_checks += 1
                    else:
                        grid_bearings_all_ok = False

                    total_leg_checks += 1
                    if this_mag_ok:
                        passed_leg_checks += 1
                    else:
                        mag_bearings_all_ok = False

                    # Distance check
                    try:
                        exp_grid_deg, exp_dist_m, _ = compute_expected_leg_metrics(in_leg)
                        exp_dist_m_r = round1(exp_dist_m)
                        out_dist = float(out_leg.get("distance_m"))
                        this_dist_ok = abs(exp_dist_m_r - out_dist) <= dist_tol
                    except Exception:
                        this_dist_ok = False

                    total_leg_checks += 1
                    if this_dist_ok:
                        passed_leg_checks += 1
                    else:
                        distances_all_ok = False

                    # Estimated paces check
                    try:
                        if pace_per_100m is None:
                            this_pace_ok = False
                        else:
                            exp_paces = int(round(exp_dist_m * (pace_per_100m / 100.0)))
                            out_paces = int(out_leg.get("estimated_paces"))
                            this_pace_ok = abs(exp_paces - out_paces) <= paces_tol
                    except Exception:
                        this_pace_ok = False

                    total_leg_checks += 1
                    if this_pace_ok:
                        passed_leg_checks += 1
                    else:
                        paces_all_ok = False

                    # Handrail/backstop present non-empty
                    try:
                        handrail = out_leg.get("handrail")
                        backstop = out_leg.get("backstop")
                        this_hb_ok = isinstance(handrail, str) and handrail.strip() != "" and isinstance(backstop, str) and backstop.strip() != ""
                    except Exception:
                        this_hb_ok = False

                    total_leg_checks += 1
                    if this_hb_ok:
                        passed_leg_checks += 1
                    else:
                        handrails_backstops_all_ok = False

            # Set final booleans for leg aspects
            checks["route_card_legs_structure_names_coords_ok"] = legs_structure_ok and legs_count_ok
            checks["route_card_grid_bearings_within_tolerance"] = grid_bearings_all_ok and legs_count_ok
            checks["route_card_magnetic_bearings_within_tolerance"] = mag_bearings_all_ok and legs_count_ok
            checks["route_card_distances_within_tolerance"] = distances_all_ok and legs_count_ok
            checks["route_card_estimated_paces_within_tolerance"] = paces_all_ok and legs_count_ok
            checks["route_card_handrails_backstops_present"] = handrails_backstops_all_ok and legs_count_ok
        else:
            # If we cannot read input or route data properly, leave related checks False
            pass

    # TRAINING PLAN CHECKS
    training_path = os.path.join(output_dir, "training_plan.md")
    if os.path.isfile(training_path):
        checks["training_plan_exists"] = True
        try:
            ttext = read_text_file(training_path)
        except Exception:
            ttext = ""

        if input_data and isinstance(input_data, dict) and ttext:
            tlow = ttext.lower()

            # Declination presence and value
            decl_present = ("declination" in tlow)
            decl_val_ok = False
            try:
                in_decl = float(input_data.get("declination_deg_east_positive"))
            except Exception:
                in_decl = None
            if in_decl is not None:
                decl_val_ok = has_number_approximately(ttext, in_decl, tol=0.1)

            checks["training_plan_declination_and_value_present"] = decl_present and decl_val_ok

            # Declination application explanation: look near "declination" for "bearing" and either "add" or "subtract"
            expl_ok = False
            if decl_present:
                for m in re.finditer(r'declination', tlow):
                    start = max(0, m.start() - 120)
                    end = min(len(tlow), m.end() + 120)
                    window = tlow[start:end]
                    if ("bearing" in window) and (("add" in window) or ("subtract" in window)):
                        expl_ok = True
                        break
            checks["training_plan_declination_application_explained"] = expl_ok

            # Keywords presence
            keywords_ok = True
            kw_list = ["map", "scale", "contour", "grid", "compass", "bearing", "handrail", "backstop", "stop", "sit", "think", "observe", "plan"]
            for kw in kw_list:
                if kw not in tlow:
                    keywords_ok = False
                    break
            # One of the natural nav keywords
            natnav_ok = any(k in tlow for k in ["shadow stick", "polaris", "southern cross"])
            keywords_ok = keywords_ok and natnav_ok
            checks["training_plan_keywords_present"] = keywords_ok

            # Safety: charged phone and 911 and route/return time
            safety_phone = ("charged phone" in tlow)
            safety_911 = ("911" in ttext)  # keep case as numerals only
            safety_route = ("route" in tlow) or ("return time" in tlow)
            checks["training_plan_safety_phone_and_911_and_route"] = safety_phone and safety_911 and safety_route

            # Practice referencing provided leg names
            practice_ok = ("practice" in tlow) or ("exercise" in tlow)
            leg_name_ok = False
            try:
                input_legs = input_data.get("legs")
                if isinstance(input_legs, list):
                    names = set()
                    for leg in input_legs:
                        fn = str(leg.get("from_name", ""))
                        tn = str(leg.get("to_name", ""))
                        if fn:
                            names.add(fn.lower())
                        if tn:
                            names.add(tn.lower())
                    for nm in names:
                        if nm and nm in tlow:
                            leg_name_ok = True
                            break
            except Exception:
                leg_name_ok = False
            checks["training_plan_practice_refs_leg_names"] = practice_ok and leg_name_ok

    # Compute reward
    # Route card score: consider only checks that depend on route_card.json existence/content
    route_checks_keys = [
        "route_card_exists",
        "route_card_json_valid",
        "route_card_top_fields_match_input",
        "route_card_legs_count_match",
        "route_card_legs_structure_names_coords_ok",
        "route_card_grid_bearings_within_tolerance",
        "route_card_magnetic_bearings_within_tolerance",
        "route_card_distances_within_tolerance",
        "route_card_estimated_paces_within_tolerance",
        "route_card_handrails_backstops_present",
    ]
    route_total = 0
    route_pass = 0
    for k in route_checks_keys:
        # Only count if it depends on output; all listed do
        route_total += 1
        if checks.get(k, False):
            route_pass += 1
    # If the file doesn't exist, route_pass will be small (only if any checks mistakenly True). Ensure baseline remains 0.

    # Training plan score
    training_checks_keys = [
        "training_plan_exists",
        "training_plan_declination_and_value_present",
        "training_plan_declination_application_explained",
        "training_plan_keywords_present",
        "training_plan_safety_phone_and_911_and_route",
        "training_plan_practice_refs_leg_names",
    ]
    training_total = 0
    training_pass = 0
    for k in training_checks_keys:
        training_total += 1
        if checks.get(k, False):
            training_pass += 1

    # Do not award any credit if corresponding output artifacts are missing:
    if not checks["route_card_exists"]:
        route_pass = 0
        route_total = len(route_checks_keys)
    if not checks["training_plan_exists"]:
        training_pass = 0
        training_total = len(training_checks_keys)

    route_score = (route_pass / route_total) if route_total > 0 else 0.0
    training_score = (training_pass / training_total) if training_total > 0 else 0.0

    reward = 0.5 * route_score + 0.5 * training_score

    # Ensure numeric bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Baseline: If outputs are missing (both), reward must be 0.0
    if not checks["route_card_exists"] and not checks["training_plan_exists"]:
        reward = 0.0

    # Print final JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()