import json
import os
import sys
import csv

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def to_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def to_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default

def parse_csv_header_has_columns(path, required_cols):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return False
            hdr_lower = [h.strip().lower() for h in header]
            return all(col in hdr_lower for col in required_cols)
    except Exception:
        return False

def get_altitude_ft(input_dir):
    alt_path = os.path.join(input_dir, "altitude.txt")
    txt = read_text_file(alt_path)
    if txt is None:
        return None
    txt = txt.strip()
    # allow integer like "1450" or "1450 ft"
    digits = ""
    for ch in txt:
        if ch.isdigit() or (ch == '-' and not digits):
            digits += ch
        elif digits and not ch.isdigit():
            break
    try:
        return int(digits)
    except Exception:
        # try plain int
        try:
            return int(txt)
        except Exception:
            return None

def altitude_increment_for(ft):
    if ft is None:
        return None
    if ft <= 1000:
        return 0
    elif ft <= 3000:
        return 5
    elif ft <= 6000:
        return 10
    elif ft <= 8000:
        return 15
    elif ft <= 10000:
        return 20
    else:
        # Above 10,000 not specified; assume 20 for validation purposes
        return 20

def contains_keyword(s, keywords):
    s_low = (s or "").lower()
    for k in keywords:
        if k in s_low:
            return True
    return False

def check_methods_allowed(batches):
    allowed = {"fermentation_dry_salt", "fermentation_brine", "water_bath_canning", "dehydration", "quick_pickling"}
    for b in batches:
        m = b.get("method")
        if m not in allowed:
            return False
    return True

def all_batches_have_jars_valid(batches):
    for b in batches:
        jars = b.get("jars")
        if not isinstance(jars, list) or len(jars) == 0:
            return False
        valid_any = False
        for j in jars:
            if not isinstance(j, dict):
                continue
            size_oz = j.get("size_oz")
            count = j.get("count")
            if is_number(size_oz) and isinstance(count, int) and count >= 1:
                valid_any = True
            else:
                # allow count numeric but integer-like
                if is_number(count) and int(float(count)) == float(count) and int(float(count)) >= 1 and is_number(size_oz):
                    valid_any = True
        if not valid_any:
            return False
    return True

def validate_fermentation_dry_salt(batches):
    applicable = False
    for b in batches:
        if b.get("method") == "fermentation_dry_salt":
            applicable = True
            veg_w = b.get("veg_total_weight_g")
            salt_percent = b.get("salt_percent")
            salt_g = b.get("salt_g")
            keep_submerged = b.get("keep_submerged")
            if not (is_number(veg_w) and to_float(veg_w, -1) > 0):
                return applicable, False
            if not (is_number(salt_percent) and 1.8 <= to_float(salt_percent) <= 2.2):
                return applicable, False
            if not is_number(salt_g):
                return applicable, False
            # compute expected salt
            expected = round(to_float(veg_w) * to_float(salt_percent) / 100.0)
            # tolerance ±2 g
            if abs(to_float(salt_g) - expected) > 2:
                return applicable, False
            if keep_submerged is not True:
                return applicable, False
    return applicable, True

def validate_fermentation_brine(batches):
    applicable = False
    for b in batches:
        if b.get("method") == "fermentation_brine":
            applicable = True
            brine_percent = b.get("brine_percent")
            brine_total_ml = b.get("brine_total_ml")
            keep_submerged = b.get("keep_submerged")
            if not (is_number(brine_percent) and 3.0 <= to_float(brine_percent) <= 5.0):
                return applicable, False
            if not (is_number(brine_total_ml) and to_float(brine_total_ml) > 0):
                return applicable, False
            if keep_submerged is not True:
                return applicable, False
    return applicable, True

def validate_wbc_times_and_altitude(batches, altitude_ft):
    applicable = False
    times_valid = True
    altitude_valid = True
    inc = altitude_increment_for(altitude_ft)
    for b in batches:
        if b.get("method") == "water_bath_canning":
            applicable = True
            base = b.get("process_time_base_min")
            adj = b.get("process_time_adjusted_min")
            if not (is_number(base) and to_float(base) > 0 and is_number(adj) and to_float(adj) >= to_float(base)):
                times_valid = False
            # altitude adjustment exact increment
            if inc is None:
                altitude_valid = False
            else:
                try:
                    diff = round(to_float(adj) - to_float(base))
                    if diff != inc:
                        altitude_valid = False
                except Exception:
                    altitude_valid = False
    return applicable, times_valid, altitude_valid

def validate_tomato_acid(batches):
    applicable = False
    ok = True
    for b in batches:
        if b.get("method") == "water_bath_canning" and contains_keyword(b.get("primary_ingredient",""), ["tomato"]):
            applicable = True
            lemon = b.get("lemon_tbsp_per_quart")
            citric = b.get("citric_acid_tsp_per_quart")
            lemon_ok = is_number(lemon) and to_float(lemon) >= 2.0
            citric_ok = is_number(citric) and to_float(citric) >= 0.5
            if not (lemon_ok or citric_ok):
                ok = False
    return applicable, ok

def validate_pickled_low_acid(batches):
    # Only for WBC batches with low-acid veg keywords in primary_ingredient
    applicable = False
    ok = True
    keywords = ["cucumber", "bean", "green bean", "jalapeno", "onion", "carrot", "cauliflower"]
    for b in batches:
        if b.get("method") == "water_bath_canning":
            pi = (b.get("primary_ingredient") or "")
            if contains_keyword(pi, keywords):
                applicable = True
                is_pickled = b.get("is_pickled")
                vineg_ratio = b.get("vinegar_ratio")
                acidity = b.get("acidity_percent")
                if not (is_pickled is True and is_number(vineg_ratio) and to_float(vineg_ratio) >= 1.0 and is_number(acidity) and to_float(acidity) >= 5.0):
                    ok = False
    return applicable, ok

def validate_dehydration_herbs(batches):
    applicable = False
    ok = True
    for b in batches:
        if b.get("method") == "dehydration" and (b.get("category") == "herbs"):
            applicable = True
            air_dry = b.get("air_dry")
            temp_f = b.get("target_temp_F")
            if air_dry is True:
                continue
            # else require 95-115 F
            if not (is_number(temp_f) and 95 <= to_float(temp_f) <= 115):
                ok = False
    return applicable, ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    batch_plan_path = os.path.join(output_dir, "batch_plan.json")
    instructions_path = os.path.join(output_dir, "instructions.md")
    shopping_list_path = os.path.join(output_dir, "shopping_list.csv")
    schedule_path = os.path.join(output_dir, "schedule.txt")

    checks = {
        "has_batch_plan_json": False,
        "has_instructions_md": False,
        "has_shopping_list_csv": False,
        "has_schedule_txt": False,
        "batch_plan_json_valid": False,
        "altitude_matches": False,
        "batches_count_ge_4": False,
        "allowed_methods_only": False,
        "all_batches_have_jars": False,
        "includes_fermentation_dry_salt": False,
        "includes_wbc_tomato": False,
        "includes_wbc_peach": False,
        "includes_pickled_cucumber_or_greenbean": False,
        "fermentation_dry_salt_params_valid": False,
        "fermentation_brine_params_valid": False,  # applicable if any brine batch exists
        "wbc_times_valid": False,                  # applicable if any wbc
        "wbc_altitude_adjustments_valid": False,   # applicable if any wbc
        "tomato_acid_added": False,                # applicable if any tomato wbc
        "pickled_low_acid_requirements_met": False,# applicable if any low-acid veg wbc
        "dehydration_herbs_params_valid": False,   # applicable if any herbs dehydration
        "instructions_keywords_present": False,
        "shopping_list_has_required_columns": False,
        "schedule_nonempty": False,
    }

    # Existence checks
    checks["has_batch_plan_json"] = os.path.isfile(batch_plan_path)
    checks["has_instructions_md"] = os.path.isfile(instructions_path)
    checks["has_shopping_list_csv"] = os.path.isfile(shopping_list_path)
    checks["has_schedule_txt"] = os.path.isfile(schedule_path)

    altitude_ft_input = get_altitude_ft(input_dir)

    plan = None
    batches = []
    if checks["has_batch_plan_json"]:
        plan = load_json_file(batch_plan_path)
        if isinstance(plan, dict):
            checks["batch_plan_json_valid"] = True
            # altitude match
            out_alt = plan.get("altitude_ft")
            if altitude_ft_input is not None and (out_alt == altitude_ft_input):
                checks["altitude_matches"] = True
            # batches
            batches = plan.get("batches")
            if isinstance(batches, list):
                if len(batches) >= 4:
                    checks["batches_count_ge_4"] = True
                # methods allowed
                if check_methods_allowed(batches):
                    checks["allowed_methods_only"] = True
                # all batches have jars
                if all_batches_have_jars_valid(batches):
                    checks["all_batches_have_jars"] = True
                # inclusions
                includes_dry = any(b.get("method") == "fermentation_dry_salt" for b in batches)
                checks["includes_fermentation_dry_salt"] = includes_dry
                includes_wbc_tomato = any((b.get("method") == "water_bath_canning") and contains_keyword(b.get("primary_ingredient",""), ["tomato"]) for b in batches)
                checks["includes_wbc_tomato"] = includes_wbc_tomato
                includes_wbc_peach = any((b.get("method") == "water_bath_canning") and contains_keyword(b.get("primary_ingredient",""), ["peach"]) for b in batches)
                checks["includes_wbc_peach"] = includes_wbc_peach
                includes_pickled_cuke_or_bean = any(
                    (b.get("method") == "water_bath_canning") and contains_keyword(b.get("primary_ingredient",""), ["cucumber", "green bean", "bean"])
                    for b in batches
                )
                checks["includes_pickled_cucumber_or_greenbean"] = includes_pickled_cuke_or_bean

                # parameter validations
                applicable_dry, dry_ok = validate_fermentation_dry_salt(batches)
                checks["fermentation_dry_salt_params_valid"] = (applicable_dry and dry_ok)
                applicable_brine, brine_ok = validate_fermentation_brine(batches)
                # Only set True if applicable and ok; else remain False (no vacuous passes)
                checks["fermentation_brine_params_valid"] = (applicable_brine and brine_ok)
                applicable_wbc, times_ok, alt_ok = validate_wbc_times_and_altitude(batches, altitude_ft_input)
                checks["wbc_times_valid"] = (applicable_wbc and times_ok)
                checks["wbc_altitude_adjustments_valid"] = (applicable_wbc and alt_ok)
                applicable_tom, tom_ok = validate_tomato_acid(batches)
                checks["tomato_acid_added"] = (applicable_tom and tom_ok)
                applicable_pick, pick_ok = validate_pickled_low_acid(batches)
                checks["pickled_low_acid_requirements_met"] = (applicable_pick and pick_ok)
                applicable_dehyd, dehyd_ok = validate_dehydration_herbs(batches)
                checks["dehydration_herbs_params_valid"] = (applicable_dehyd and dehyd_ok)

    # Instructions keywords
    if checks["has_instructions_md"]:
        instr_text = read_text_file(instructions_path) or ""
        low = instr_text.lower()
        need_terms = ["botulism", "2%", "5%", "keep submerged", "altitude"]
        checks["instructions_keywords_present"] = all(t in low for t in need_terms)

    # Shopping list header
    if checks["has_shopping_list_csv"]:
        required_cols = ["item", "quantity", "unit", "purpose"]
        checks["shopping_list_has_required_columns"] = parse_csv_header_has_columns(shopping_list_path, required_cols)

    # Schedule non-empty
    if checks["has_schedule_txt"]:
        sched = read_text_file(schedule_path)
        checks["schedule_nonempty"] = bool(sched and sched.strip())

    # Determine applicable checks for scoring
    # Required artifacts must all exist to award any points
    all_required_exist = checks["has_batch_plan_json"] and checks["has_instructions_md"] and checks["has_shopping_list_csv"] and checks["has_schedule_txt"]

    # Build list of checks to include in score (exclude the has_* existence flags themselves)
    scoring_keys = [
        "batch_plan_json_valid",
        "altitude_matches",
        "batches_count_ge_4",
        "allowed_methods_only",
        "all_batches_have_jars",
        "includes_fermentation_dry_salt",
        "includes_wbc_tomato",
        "includes_wbc_peach",
        "includes_pickled_cucumber_or_greenbean",
        "fermentation_dry_salt_params_valid",
        "wbc_times_valid",
        "wbc_altitude_adjustments_valid",
        "tomato_acid_added",
        "pickled_low_acid_requirements_met",
        "instructions_keywords_present",
        "shopping_list_has_required_columns",
        "schedule_nonempty",
    ]

    # Conditionally include optional checks only if applicable True or False is already set by presence
    # fermentation_brine_params_valid and dehydration_herbs_params_valid are optional; include them only if applicable was True
    # We can't distinguish applicability now via another flag, but we encoded True only when applicable & ok.
    # To avoid penalizing absence, include them in scoring only if they are True; otherwise, check if any corresponding method exists.
    # Better approach: recompute applicability quickly.
    has_brine = any(isinstance(b, dict) and b.get("method") == "fermentation_brine" for b in batches) if isinstance(batches, list) else False
    has_dehyd_herbs = any(isinstance(b, dict) and b.get("method") == "dehydration" and b.get("category") == "herbs" for b in batches) if isinstance(batches, list) else False
    if has_brine:
        scoring_keys.append("fermentation_brine_params_valid")
    if has_dehyd_herbs:
        scoring_keys.append("dehydration_herbs_params_valid")

    # Compute reward
    if not all_required_exist:
        reward = 0.0
    else:
        applicable = scoring_keys
        if len(applicable) == 0:
            # Should not happen; but ensure defined
            reward = 0.0
        else:
            passed = sum(1 for k in applicable if checks.get(k, False) is True)
            reward = passed / float(len(applicable))
            # Clamp between 0 and 1
            if reward < 0:
                reward = 0.0
            if reward > 1:
                reward = 1.0

    # Ensure if outputs missing, zero reward explicitly
    if not all_required_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()