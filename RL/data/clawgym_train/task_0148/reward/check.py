import json
import os
import sys
from collections import Counter, defaultdict

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def get_required_fields_map(cat_schema):
    """
    Attempt to normalize schema for a category into a mapping: field -> type_str
    Accepts several possible shapes:
    - {"required": {"field": "type", ...}}
    - {"required_fields": {"field": "type", ...}}
    - {"fields": [{"name": "...", "type": "...", "required": true}, ...]}
    - {"field": "type", ...} (flat mapping)
    """
    if not isinstance(cat_schema, dict):
        return {}
    # explicit containers
    if isinstance(cat_schema.get("required"), dict):
        return {k: str(v).lower() for k, v in cat_schema["required"].items()}
    if isinstance(cat_schema.get("required_fields"), dict):
        return {k: str(v).lower() for k, v in cat_schema["required_fields"].items()}
    if isinstance(cat_schema.get("fields"), list):
        out = {}
        for fld in cat_schema["fields"]:
            if isinstance(fld, dict) and fld.get("required") is True and "name" in fld and "type" in fld:
                out[str(fld["name"])] = str(fld["type"]).lower()
        if out:
            return out
    # fallback: assume entire mapping is field->type
    # filter out non-type-like values (keep str values)
    flat = {}
    for k, v in cat_schema.items():
        if isinstance(v, str):
            flat[k] = v.lower()
    return flat

def check_type(val, type_str):
    t = (type_str or "").strip().lower()
    if t in ("number", "numeric", "float", "int"):
        return is_number(val)
    if t in ("boolean", "bool"):
        return isinstance(val, bool)
    if t in ("string", "str", "text"):
        return isinstance(val, str) and len(val) >= 0  # allow empty string as type, content validated separately elsewhere
    # Unknown type hint: do not fail on unknown, consider as pass if field exists
    return True

def float_equal(a, b, tol=1e-6):
    if not (is_number(a) and is_number(b)):
        return False
    return abs(float(a) - float(b)) <= tol

def to_lower_str(x):
    return str(x).lower() if isinstance(x, str) else x

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "output_catalog_exists": False,
        "parsed_catalog_array": False,
        "catalog_length_matches_input": False,
        "names_preserved_exact": False,
        "categories_match_input": False,
        "schema_fields_present_and_typed": False,
        # Validations computed from catalog
        "all_smartphones_have_galaxy_ai": False,
        "all_listed_tvs_run_tizen_and_7yr_upgrades": False,
        "s26_ultra_specs_match": False,
        "s26_plus_specs_match": False,
        "z_trifold_specs_match": False,
        "z_fold7_specs_match": False,
        "z_flip7_specs_match": False,
        "tab_s11_ultra_s_pen_included": False,
        "watch_ultra_titanium_ip68": False,
        "neo_qled_8k_tech_and_resolution": False,
        "samsung_oled_qd_oled": False,
        "the_frame_art_mode": False,
        "crystal_uhd_standard_led_4k": False,
        "family_hub_bespoke_ai_gemini_and_food_meal": False,
        "jet_bot_ai_camera_and_liquid": False,
        "all_are_smartthings_compatible": False,
        # checks.json related
        "output_checks_exists": False,
        "parsed_checks_object": False,
        "checks_counts_total_match": False,
        "checks_counts_by_category_match": False,
        "checks_validations_all_exist": False,
        "checks_validations_are_booleans": False,
        "checks_validations_values_correct": False,
    }

    # Read inputs
    products_path = os.path.join(input_dir, "products.json")
    schema_path = os.path.join(input_dir, "schema.json")
    products_list = load_json_file(products_path)
    schema = load_json_file(schema_path)

    # Prepare expected counts categories
    expected_categories = ["smartphone", "tablet", "wearable", "tv", "appliance", "robot_vacuum"]

    # Load catalog output
    catalog_path = os.path.join(output_dir, "catalog.json")
    catalog = None
    if os.path.isfile(catalog_path):
        checks["output_catalog_exists"] = True
        catalog = load_json_file(catalog_path)
        if isinstance(catalog, list):
            checks["parsed_catalog_array"] = True

    # Proceed only if we have products_list and catalog parsed
    name_to_input_category = {}
    if isinstance(products_list, list):
        for item in products_list:
            if isinstance(item, dict) and "name" in item and "category" in item:
                name_to_input_category[item["name"]] = item["category"]

    # Validate length and names set
    if checks["parsed_catalog_array"] and isinstance(products_list, list):
        if len(catalog) == len(products_list):
            checks["catalog_length_matches_input"] = True
        input_names = [p["name"] for p in products_list if isinstance(p, dict) and "name" in p]
        catalog_names = [c.get("name") for c in catalog if isinstance(c, dict)]
        if set(input_names) == set(catalog_names) and len(input_names) == len(catalog_names):
            checks["names_preserved_exact"] = True

    # Validate categories match input and schema field presence/types
    categories_match = True
    schema_ok = True

    # Build required fields per category from schema
    required_fields_by_cat = {}
    if isinstance(schema, dict):
        for cat, cat_schema in schema.items():
            required_fields_by_cat[cat] = get_required_fields_map(cat_schema)

    if checks["parsed_catalog_array"]:
        for obj in catalog:
            if not isinstance(obj, dict):
                schema_ok = False
                categories_match = False
                break
            name = obj.get("name")
            category = obj.get("category")
            # Check category matches input
            if name in name_to_input_category:
                if category != name_to_input_category[name]:
                    categories_match = False
            else:
                # Name not in input list; names_preserved_exact will already fail, but keep robust
                categories_match = False
            # Check required fields per schema
            req = required_fields_by_cat.get(category, {})
            for field, t in req.items():
                # Must exist and not be None
                if field not in obj:
                    schema_ok = False
                    break
                val = obj[field]
                if val is None:
                    schema_ok = False
                    break
                # Types check
                if not check_type(val, t):
                    schema_ok = False
                    break
            if schema_ok is False:
                break

    if checks["parsed_catalog_array"]:
        checks["categories_match_input"] = categories_match
        checks["schema_fields_present_and_typed"] = schema_ok

    # Helper: find by exact name
    def find_product_by_name(nm):
        if not checks["parsed_catalog_array"]:
            return None
        for obj in catalog:
            if isinstance(obj, dict) and obj.get("name") == nm:
                return obj
        return None

    # Compute validations from catalog
    if checks["parsed_catalog_array"]:
        # all_smartphones_have_galaxy_ai
        smartphones = [o for o in catalog if isinstance(o, dict) and o.get("category") == "smartphone"]
        if smartphones:
            if all(o.get("galaxy_ai") is True for o in smartphones):
                checks["all_smartphones_have_galaxy_ai"] = True
        else:
            # If no smartphones listed, this should fail deterministically
            checks["all_smartphones_have_galaxy_ai"] = False

        # TVs tizen + 7yr
        tvs = [o for o in catalog if isinstance(o, dict) and o.get("category") == "tv"]
        if tvs:
            tvs_ok = True
            for tv in tvs:
                if tv.get("tizen_os") is not True:
                    tvs_ok = False
                    break
                oy = tv.get("os_upgrade_years")
                if not is_number(oy) or oy < 7:
                    tvs_ok = False
                    break
            checks["all_listed_tvs_run_tizen_and_7yr_upgrades"] = tvs_ok

        # all_are_smartthings_compatible
        all_ok_smartthings = True
        if catalog:
            for o in catalog:
                if o.get("smartthings_compatible") is not True:
                    all_ok_smartthings = False
                    break
            checks["all_are_smartthings_compatible"] = all_ok_smartthings

        # S26 Ultra
        s26u = find_product_by_name("Galaxy S26 Ultra")
        if s26u and s26u.get("category") == "smartphone":
            c_ok = s26u.get("chipset") == "Snapdragon 8 Elite Gen 5"
            d_ok = is_number(s26u.get("display_inches")) and float_equal(s26u.get("display_inches"), 6.9)
            b_ok = is_number(s26u.get("battery_mah")) and int(s26u.get("battery_mah")) == 5000
            s_ok = s26u.get("s_pen_included") is True
            checks["s26_ultra_specs_match"] = all([c_ok, d_ok, b_ok, s_ok])

        # S26+
        s26p = find_product_by_name("Galaxy S26+")
        if s26p and s26p.get("category") == "smartphone":
            c_ok = s26p.get("chipset") == "Exynos 2600"
            d_ok = is_number(s26p.get("display_inches")) and float_equal(s26p.get("display_inches"), 6.7)
            s_ok = s26p.get("s_pen_included") is False
            checks["s26_plus_specs_match"] = all([c_ok, d_ok, s_ok])

        # Z TriFold
        ztri = find_product_by_name("Galaxy Z TriFold")
        if ztri and ztri.get("category") == "smartphone":
            t_ok = ztri.get("triple_fold") is True
            p_ok = is_number(ztri.get("price_usd")) and float_equal(ztri.get("price_usd"), 2900.0)
            checks["z_trifold_specs_match"] = (t_ok and p_ok)

        # Z Fold7
        zfold7 = find_product_by_name("Galaxy Z Fold7")
        if zfold7 and zfold7.get("category") == "smartphone":
            b_ok = zfold7.get("book_style") is True
            idv = zfold7.get("inner_display_inches")
            i_ok = is_number(idv) and (float_equal(idv, 8.0) or float_equal(idv, 8))
            checks["z_fold7_specs_match"] = (b_ok and i_ok)

        # Z Flip7
        zflip7 = find_product_by_name("Galaxy Z Flip7")
        if zflip7 and zflip7.get("category") == "smartphone":
            c_ok = zflip7.get("clamshell") is True
            lod_ok = zflip7.get("large_outer_display") is True
            checks["z_flip7_specs_match"] = (c_ok and lod_ok)

        # Tab S11 Ultra
        tab = find_product_by_name("Galaxy Tab S11 Ultra")
        if tab and tab.get("category") == "tablet":
            sp_ok = tab.get("s_pen_included") is True
            prem_ok = tab.get("premium") is True
            st_ok = tab.get("smartthings_compatible") is True
            checks["tab_s11_ultra_s_pen_included"] = (sp_ok and prem_ok and st_ok)

        # Watch Ultra
        watch = find_product_by_name("Galaxy Watch Ultra")
        if watch and watch.get("category") == "wearable":
            mat = watch.get("material")
            ip = watch.get("ip_rating")
            mat_ok = isinstance(mat, str) and mat.strip().lower() == "titanium"
            ip_ok = (ip == "IP68")
            st_ok = watch.get("smartthings_compatible") is True
            checks["watch_ultra_titanium_ip68"] = (mat_ok and ip_ok and st_ok)

        # TVs specifics
        # Neo QLED 8K
        neo = find_product_by_name("Neo QLED 8K")
        if neo and neo.get("category") == "tv":
            tech_ok = neo.get("technology") == "Mini LED + Quantum Dot"
            res_ok = neo.get("resolution") == "8K"
            checks["neo_qled_8k_tech_and_resolution"] = (tech_ok and res_ok)
        # Samsung OLED
        oled = find_product_by_name("Samsung OLED")
        if oled and oled.get("category") == "tv":
            tech_ok = oled.get("technology") == "QD-OLED"
            checks["samsung_oled_qd_oled"] = tech_ok is True
        # The Frame
        frame = find_product_by_name("The Frame")
        if frame and frame.get("category") == "tv":
            art_ok = frame.get("art_mode") is True
            checks["the_frame_art_mode"] = art_ok
        # Crystal UHD
        crystal = find_product_by_name("Crystal UHD")
        if crystal and crystal.get("category") == "tv":
            tech_ok = crystal.get("technology") == "Standard LED"
            res_ok = crystal.get("resolution") == "4K"
            checks["crystal_uhd_standard_led_4k"] = (tech_ok and res_ok)

        # Appliance: Bespoke AI Family Hub Refrigerator
        fam = find_product_by_name("Bespoke AI Family Hub Refrigerator")
        if fam and fam.get("category") == "appliance":
            b_ok = fam.get("bespoke_ai") is True
            g_ok = fam.get("gemini_ai") is True
            f_ok = fam.get("food_recognition") is True
            m_ok = fam.get("meal_planning") is True
            st_ok = fam.get("smartthings_compatible") is True
            checks["family_hub_bespoke_ai_gemini_and_food_meal"] = all([b_ok, g_ok, f_ok, m_ok, st_ok])

        # Robot Vacuum: Bespoke Jet Bot AI
        jet = find_product_by_name("Bespoke Jet Bot AI")
        if jet and jet.get("category") == "robot_vacuum":
            c_ok = jet.get("camera_navigation") is True
            l_ok = jet.get("liquid_spill_detection") is True
            st_ok = jet.get("smartthings_compatible") is True
            checks["jet_bot_ai_camera_and_liquid"] = (c_ok and l_ok and st_ok)

    # Load checks.json and verify internal consistency
    checks_path = os.path.join(output_dir, "checks.json")
    checks_json = None
    if os.path.isfile(checks_path):
        checks["output_checks_exists"] = True
        checks_json = load_json_file(checks_path)
        if isinstance(checks_json, dict):
            checks["parsed_checks_object"] = True

    # Compute our own counts based on catalog
    own_counts_total = None
    own_counts_by_cat = {k: 0 for k in expected_categories}
    if checks["parsed_catalog_array"]:
        own_counts_total = len(catalog)
        for obj in catalog:
            cat = obj.get("category")
            if cat in own_counts_by_cat:
                own_counts_by_cat[cat] += 1
            else:
                # categories outside expected set are not counted but will break by_category comparison
                own_counts_by_cat.setdefault(cat, 0)
                own_counts_by_cat[cat] += 1

    # Validate checks.json content
    if checks["parsed_checks_object"] and checks["parsed_catalog_array"]:
        ok_total_match = False
        ok_by_cat_match = False
        ok_validations_exist = False
        ok_validations_bool = False
        ok_validations_values = False

        counts = checks_json.get("counts") if isinstance(checks_json, dict) else None
        validations = checks_json.get("validations") if isinstance(checks_json, dict) else None

        if isinstance(counts, dict):
            total = counts.get("total")
            if isinstance(total, int) and own_counts_total is not None and total == own_counts_total:
                ok_total_match = True

            by_cat = counts.get("by_category")
            if isinstance(by_cat, dict):
                # ensure keys exist for all expected categories
                missing_keys = [k for k in expected_categories if k not in by_cat]
                if not missing_keys:
                    # compare tallies
                    match = True
                    for k in expected_categories:
                        v = by_cat.get(k)
                        if not isinstance(v, int):
                            match = False
                            break
                        # In case catalog had unexpected categories, require those not to be in by_cat
                        if k in own_counts_by_cat:
                            if by_cat[k] != own_counts_by_cat[k]:
                                match = False
                                break
                    # Also ensure by_cat does not have extra categories beyond expected that have nonzero values; but spec doesn't forbid extras explicitly.
                    ok_by_cat_match = match

        # Ensure validations keys exist and are boolean, and equal to our computed
        expected_validation_keys = [
            "all_smartphones_have_galaxy_ai",
            "all_listed_tvs_run_tizen_and_7yr_upgrades",
            "s26_ultra_specs_match",
            "s26_plus_specs_match",
            "z_trifold_specs_match",
            "z_fold7_specs_match",
            "z_flip7_specs_match",
            "tab_s11_ultra_s_pen_included",
            "watch_ultra_titanium_ip68",
            "neo_qled_8k_tech_and_resolution",
            "samsung_oled_qd_oled",
            "the_frame_art_mode",
            "crystal_uhd_standard_led_4k",
            "family_hub_bespoke_ai_gemini_and_food_meal",
            "jet_bot_ai_camera_and_liquid",
            "all_are_smartthings_compatible",
        ]
        if isinstance(validations, dict):
            # existence
            if all(k in validations for k in expected_validation_keys):
                ok_validations_exist = True
            # booleans
            if ok_validations_exist and all(isinstance(validations.get(k), bool) for k in expected_validation_keys):
                ok_validations_bool = True
            # values
            if ok_validations_bool:
                values_match = True
                for k in expected_validation_keys:
                    # Compare with our computed checks
                    if validations.get(k) != checks.get(k, False):
                        values_match = False
                        break
                ok_validations_values = values_match

        checks["checks_counts_total_match"] = ok_total_match
        checks["checks_counts_by_category_match"] = ok_by_cat_match
        checks["checks_validations_all_exist"] = ok_validations_exist
        checks["checks_validations_are_booleans"] = ok_validations_bool
        checks["checks_validations_values_correct"] = ok_validations_values

    # Compute reward as fraction of passed checks; enforce 0 if primary artifacts missing
    total_points = len(checks)
    passed_points = sum(1 for v in checks.values() if v is True)

    # No-op baseline: if catalog missing or empty or not parsed, reward must be 0.0
    if not checks["parsed_catalog_array"]:
        reward = 0.0
    else:
        # Fractional score
        reward = passed_points / float(total_points) if total_points > 0 else 0.0

    # Clamp 0..1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print final JSON
    # Ensure "reward" is the first field by constructing ordered dict via tuple expansion
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()