import json
import os
import sys
import re

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def approx_equal(a, b, tol):
    try:
        return abs(a - b) <= tol
    except Exception:
        return False

def percent_within(a, b, pct_tol):
    # pct_tol as fraction, e.g., 0.02 for 2%
    try:
        if b == 0:
            return False
        return abs(a - b) <= abs(b) * pct_tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    timeline_path = os.path.join(output_dir, "plan", "timeline.md")
    weights_path = os.path.join(output_dir, "plan", "weights.json")
    conversion_path = os.path.join(output_dir, "plan", "conversion.json")
    recipe_path = os.path.join(input_dir, "recipe.json")

    checks = {
        "timeline_exists": False,
        "timeline_includes_8am_saturday": False,
        "timeline_mentions_friday_and_contingency": False,
        "timeline_mentions_grams_and_float_test": False,

        "conversion_exists": False,
        "conversion_valid_json": False,
        "conversion_required_keys": False,
        "conversion_additional_water_zero": False,
        "conversion_additional_flour_correct": False,
        "conversion_resulting_values_consistent": False,
        "conversion_hydration_percent_correct": False,

        "weights_exists": False,
        "weights_valid_json": False,
        "weights_steps_structure_and_totals": False,
        "weights_final_structure": False,
        "weights_final_total_meets_requirement": False,
        "weights_target_hydration_matches_recipe": False,
    }

    # Gate: if any required artifact missing, final reward must be 0.0
    # We'll compute checks but enforce reward gating at the end.
    all_required_exist = True

    # timeline.md checks
    if os.path.isfile(timeline_path):
        checks["timeline_exists"] = True
        try:
            with open(timeline_path, "r", encoding="utf-8") as f:
                timeline_text = f.read()
            # Check for "8:00 AM" and "Saturday" exact substring for the former, word for the latter
            if ("8:00 AM" in timeline_text) and ("Saturday" in timeline_text or "saturday" in timeline_text):
                checks["timeline_includes_8am_saturday"] = True
            # Check mentions of Friday and contingency cue (either "contingency" or "if")
            lower_text = timeline_text.lower()
            if ("friday" in lower_text) and ("contingency" in lower_text or " if " in lower_text or lower_text.startswith("if ") or lower_text.endswith(" if")):
                checks["timeline_mentions_friday_and_contingency"] = True
            # At least three occurrences of grams units and a mention of float test
            # Use regex to match quantities followed by 'g'
            gram_matches = re.findall(r"\b\d+(?:\.\d+)?\s*g\b", timeline_text)
            if len(gram_matches) >= 3 and ("float test" in lower_text):
                checks["timeline_mentions_grams_and_float_test"] = True
        except Exception:
            pass
    else:
        all_required_exist = False

    # conversion.json checks
    conv = None
    if os.path.isfile(conversion_path):
        checks["conversion_exists"] = True
        conv = read_json_file(conversion_path)
        if isinstance(conv, dict):
            checks["conversion_valid_json"] = True
            required_keys = [
                "input_starter_g",
                "input_hydration_percent",
                "target_hydration_percent",
                "additional_flour_g",
                "additional_water_g",
                "resulting_flour_g",
                "resulting_water_g",
                "resulting_total_g",
                "resulting_hydration_percent",
                "formula",
            ]
            if all(k in conv for k in required_keys):
                checks["conversion_required_keys"] = True
                try:
                    input_starter_g = float(conv["input_starter_g"])
                    input_hyd = float(conv["input_hydration_percent"])
                    target_hyd = float(conv["target_hydration_percent"])
                    add_flour = float(conv["additional_flour_g"])
                    add_water = float(conv["additional_water_g"])
                    res_flour = float(conv["resulting_flour_g"])
                    res_water = float(conv["resulting_water_g"])
                    res_total = float(conv["resulting_total_g"])
                    res_hyd = float(conv["resulting_hydration_percent"])

                    # Flour-only adjustment: additional_water_g must be 0
                    if approx_equal(add_water, 0.0, 1e-6):
                        checks["conversion_additional_water_zero"] = True

                    # For 100% hydration starter: initial flour = water = input/2
                    # Expect additional_flour ≈ input / 6 (±2%)
                    # Only apply check if input_hydration_percent is ~100 and target ~75
                    # but spec applies the approx formula regardless:
                    if input_starter_g > 0:
                        expected_add_flour = input_starter_g / 6.0
                        if percent_within(add_flour, expected_add_flour, 0.02):  # ±2%
                            checks["conversion_additional_flour_correct"] = True

                    # Resulting flour and water consistency
                    if input_hyd > 0:
                        init_flour = (input_starter_g / (1.0 + input_hyd/100.0))
                        init_water = input_starter_g - init_flour
                    else:
                        # If somehow input_hyd not positive, default to 100% assumption
                        init_flour = input_starter_g / 2.0
                        init_water = input_starter_g / 2.0

                    flour_ok = approx_equal(res_flour, init_flour + add_flour, 0.1)
                    water_ok = approx_equal(res_water, init_water + add_water, 0.1)
                    total_ok = approx_equal(res_total, input_starter_g + add_flour + add_water, 0.1)

                    if flour_ok and water_ok and total_ok:
                        checks["conversion_resulting_values_consistent"] = True

                    # Hydration correctness: resulting_hydration_percent == (res_water/res_flour)*100 within ±0.5%
                    # and be approximately target (±0.5%)
                    if res_flour > 0:
                        calc_hyd = (res_water / res_flour) * 100.0
                        within_ratio = abs(res_hyd - calc_hyd) <= 0.5
                        near_target = abs(res_hyd - target_hyd) <= 0.5
                        if within_ratio and near_target:
                            checks["conversion_hydration_percent_correct"] = True
                except Exception:
                    pass
        else:
            # invalid JSON or wrong type
            pass
    else:
        all_required_exist = False

    # weights.json checks
    weights = None
    if os.path.isfile(weights_path):
        checks["weights_exists"] = True
        weights = read_json_file(weights_path)
        if isinstance(weights, dict):
            checks["weights_valid_json"] = True
            steps_ok = False
            final_ok = False
            try:
                steps = weights.get("steps")
                if isinstance(steps, list) and len(steps) >= 2:
                    per_step_ok = True
                    for step in steps:
                        required_step_keys = [
                            "step_name",
                            "time_window",
                            "starter_in_g",
                            "flour_g",
                            "water_g",
                            "hydration_percent",
                            "total_g",
                        ]
                        if not isinstance(step, dict) or not all(k in step for k in required_step_keys):
                            per_step_ok = False
                            break
                        try:
                            starter_in_g = float(step["starter_in_g"])
                            flour_g = float(step["flour_g"])
                            water_g = float(step["water_g"])
                            total_g = float(step["total_g"])
                            if not approx_equal(total_g, starter_in_g + flour_g + water_g, 0.1):
                                per_step_ok = False
                                break
                        except Exception:
                            per_step_ok = False
                            break
                    if per_step_ok:
                        steps_ok = True
                if steps_ok:
                    checks["weights_steps_structure_and_totals"] = True
            except Exception:
                pass

            try:
                final_obj = weights.get("final")
                if isinstance(final_obj, dict):
                    if all(k in final_obj for k in ["final_total_g", "target_hydration_percent", "required_amount_g", "buffer_g"]):
                        checks["weights_final_structure"] = True
                        final_ok = True
            except Exception:
                pass

            # Cross-check with recipe.json for required totals and hydration
            recipe = read_json_file(recipe_path)
            if final_ok and isinstance(recipe, dict):
                try:
                    target_starter_grams = float(recipe.get("target_starter_grams"))
                    target_starter_hydration_percent = float(recipe.get("target_starter_hydration_percent"))
                    reserve_after_use_grams = float(recipe.get("reserve_after_use_grams"))

                    final_total_g = float(weights["final"]["final_total_g"])
                    # Requirement: final_total_g ≥ target_starter_grams + reserve_after_use_grams
                    if final_total_g >= target_starter_grams + reserve_after_use_grams - 1e-6:
                        checks["weights_final_total_meets_requirement"] = True

                    # target_hydration_percent within ±1% of recipe
                    final_target_hyd = float(weights["final"]["target_hydration_percent"])
                    if abs(final_target_hyd - target_starter_hydration_percent) <= 1.0:
                        checks["weights_target_hydration_matches_recipe"] = True
                except Exception:
                    pass
        else:
            # invalid JSON or wrong type
            pass
    else:
        all_required_exist = False

    # Compute reward
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    if not all_required_exist:
        reward = 0.0
    else:
        # Score as fraction of passed checks
        reward = passed / total if total > 0 else 0.0
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()