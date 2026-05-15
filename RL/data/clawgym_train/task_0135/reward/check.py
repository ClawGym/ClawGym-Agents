import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def norm_header(h):
    # normalize CSV headers
    return re.sub(r"[^a-z0-9]+", "", h.lower())

def norm_name(s):
    return (s or "").strip().lower()

def norm_unit(u):
    if u is None:
        return None
    u = u.strip().lower().replace(" ", "_").replace(".", "")
    # common aliases
    if u == "l":
        u = "l"
    if u in ("milliliter", "milliliters"):
        u = "ml"
    if u in ("liter", "liters"):
        u = "l"
    if u in ("ounce", "ounces"):
        u = "oz"
    if u in ("pound", "pounds"):
        u = "lb"
    if u in ("fluid_ounce", "fluidounces", "floz"):
        u = "fl_oz"
    return u

WEIGHT_TO_G = {
    "g": 1.0,
    "kg": 1000.0,
    "oz": 28.349523125,
    "lb": 453.59237,
}

# Nutrition labeling-friendly approximations for volume
VOLUME_TO_ML = {
    "ml": 1.0,
    "l": 1000.0,
    "fl_oz": 29.5735295625,
    "cup": 240.0,
    "tbsp": 15.0,
    "tsp": 5.0,
}

def unit_dimension(u):
    if u in WEIGHT_TO_G:
        return "weight"
    if u in VOLUME_TO_ML:
        return "volume"
    return None

def convert_amount(amount, from_unit, to_unit):
    fu = norm_unit(from_unit)
    tu = norm_unit(to_unit)
    if fu == tu:
        return amount
    fd = unit_dimension(fu)
    td = unit_dimension(tu)
    if fd is None or td is None or fd != td:
        return None
    if fd == "weight":
        # convert to grams then to target
        grams = amount * WEIGHT_TO_G[fu]
        return grams / WEIGHT_TO_G[tu]
    else:
        # volume
        ml = amount * VOLUME_TO_ML[fu]
        return ml / VOLUME_TO_ML[tu]

def parse_float_safe(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def parse_csv_foods(path):
    foods = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # normalize headers
            header_map = {h: norm_header(h) for h in reader.fieldnames or []}
            # reverse map normalized -> original
            def get_field(row, key_norm):
                for orig, norm in header_map.items():
                    if norm == key_norm:
                        return row.get(orig)
                return None
            for row in reader:
                name = (get_field(row, "name") or "").strip()
                if not name:
                    # try food name alternative
                    name = (get_field(row, "foodname") or "").strip()
                if not name:
                    continue
                per_amount = parse_float_safe(get_field(row, "peramount"))
                per_unit = norm_unit(get_field(row, "perunit"))
                # nutrients
                nutrients_keys = {
                    "calories_kcal": "calorieskcal",
                    "protein_g": "proteing",
                    "carbs_g": "carbsg",
                    "fiber_g": "fiberg",
                    "sugar_g": "sugarg",
                    "fat_g": "fatg",
                    "sat_fat_g": "satfatg",
                }
                nutrients = {}
                for k, nk in nutrients_keys.items():
                    nutrients[k] = parse_float_safe(get_field(row, nk))
                foods[norm_name(name)] = {
                    "name": name,
                    "per_amount": per_amount if per_amount else 0.0,
                    "per_unit": per_unit,
                    "nutrients": nutrients,
                }
    except FileNotFoundError:
        return {}
    except Exception:
        # best-effort: return what we parsed so far
        pass
    return foods

def parse_meal_plan_yaml(path):
    """
    Very simple state-machine parser for expected structure:
    date: YYYY-MM-DD
    meals:
      - name: ...
        time: HH:MM
        ingredients:
          - food: ...
            amount: N
            unit: unit
    """
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result = {"date": None, "meals": []}
    in_meals = False
    current_meal = None
    in_ingredients = False
    current_ingredient = None

    def parse_key_value(s):
        # expects "key: value"
        if ":" not in s:
            return None, None
        k, v = s.split(":", 1)
        return k.strip(), v.strip()

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # top-level date
        if indent == 0 and content.startswith("date:"):
            k, v = parse_key_value(content)
            result["date"] = v.strip().strip("'\"")
            continue

        # top-level meals:
        if indent == 0 and content == "meals:":
            in_meals = True
            current_meal = None
            in_ingredients = False
            continue

        if in_meals:
            # new meal item
            if indent == 2 and content.startswith("- "):
                current_meal = {"name": None, "time": None, "ingredients": []}
                result["meals"].append(current_meal)
                # inline properties after "- "
                rest = content[2:].strip()
                if rest:
                    # could be "name: Breakfast"
                    k, v = parse_key_value(rest)
                    if k:
                        if k == "name":
                            current_meal["name"] = v.strip().strip("'\"")
                        elif k == "time":
                            current_meal["time"] = v.strip().strip("'\"")
                in_ingredients = False
                continue

            # meal properties
            if indent == 4 and current_meal:
                if content == "ingredients:":
                    in_ingredients = True
                    continue
                k, v = parse_key_value(content)
                if k == "name":
                    current_meal["name"] = v.strip().strip("'\"")
                elif k == "time":
                    current_meal["time"] = v.strip().strip("'\"")
                continue

            # ingredient list item
            if in_ingredients and indent == 6 and content.startswith("- "):
                current_ingredient = {"food": None, "amount": None, "unit": None}
                current_meal["ingredients"].append(current_ingredient)
                # inline kv after "- "
                rest = content[2:].strip()
                if rest and ":" in rest:
                    k, v = parse_key_value(rest)
                    if k == "food":
                        current_ingredient["food"] = v.strip().strip("'\"")
                    elif k == "amount":
                        try:
                            current_ingredient["amount"] = float(v.strip().strip("'\""))
                        except Exception:
                            current_ingredient["amount"] = parse_float_safe(v)
                    elif k == "unit":
                        current_ingredient["unit"] = v.strip().strip("'\"")
                continue

            # ingredient properties
            if in_ingredients and indent == 8 and current_ingredient:
                k, v = parse_key_value(content)
                if k == "food":
                    current_ingredient["food"] = v.strip().strip("'\"")
                elif k == "amount":
                    try:
                        current_ingredient["amount"] = float(v.strip().strip("'\""))
                    except Exception:
                        current_ingredient["amount"] = parse_float_safe(v)
                elif k == "unit":
                    current_ingredient["unit"] = v.strip().strip("'\"")
                continue

    # basic validation
    if result["date"] is None:
        return None
    # ensure amounts as floats
    for m in result["meals"]:
        for ing in m.get("ingredients", []):
            if ing.get("amount") is None:
                ing["amount"] = 0.0
            else:
                ing["amount"] = float(ing["amount"])
    return result

def compute_expected_totals(foods, meal_plan):
    totals = {
        "calories_kcal": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fiber_g": 0.0,
        "sugar_g": 0.0,
        "fat_g": 0.0,
        "sat_fat_g": 0.0,
    }
    meals = meal_plan.get("meals", [])
    for meal in meals:
        for ing in meal.get("ingredients", []):
            food_name = norm_name(ing.get("food"))
            food = foods.get(food_name)
            if not food:
                # try exact case match if normalization changed characters
                for k, v in foods.items():
                    if v["name"].strip().lower() == food_name:
                        food = v
                        break
            if not food:
                continue
            amount = float(ing.get("amount") or 0.0)
            unit = norm_unit(ing.get("unit"))
            base_amount = float(food.get("per_amount") or 0.0)
            base_unit = norm_unit(food.get("per_unit"))
            if base_amount == 0 or base_unit is None or unit is None:
                scale = 0.0
            else:
                # scale = ingredient amount in baseUnit / base_amount
                # we convert ingredient amount to base_unit first
                converted = convert_amount(amount, unit, base_unit)
                if converted is None:
                    scale = 0.0
                else:
                    scale = converted / base_amount
            for k in totals.keys():
                base_val = float(food["nutrients"].get(k) or 0.0)
                totals[k] += base_val * scale
    return totals

def parse_summary_for_nutrient(summary_text, nutrient_key):
    """
    Extracts consumed, goal, pct, status for a nutrient from a YAML-like summary text.
    Supports inline mapping or indented sub-mapping.
    """
    lines = summary_text.splitlines()
    # pattern to find the nutrient line
    pattern = re.compile(rf"^(\s*){re.escape(nutrient_key)}\s*:\s*(.*)$")
    for idx, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        rest = m.group(2).strip()
        out = {"consumed": None, "goal": None, "pct": None, "status": None}
        # inline map: {consumed: 123, goal: 2000, pct: 6.1, status: ok}
        if rest.startswith("{") and rest.endswith("}"):
            inner = rest[1:-1].strip()
            parts = [p.strip() for p in inner.split(",")]
            for p in parts:
                if ":" in p:
                    k, v = p.split(":", 1)
                    key = k.strip()
                    val = v.strip()
                    if key in out:
                        if key == "status":
                            out[key] = val.strip("'\"")
                        else:
                            try:
                                out[key] = float(val)
                            except Exception:
                                # strip quotes and retry
                                try:
                                    out[key] = float(val.strip("'\""))
                                except Exception:
                                    out[key] = None
            return out
        # indented block
        j = idx + 1
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                j += 1
                continue
            cur_indent = len(ln) - len(ln.lstrip(" "))
            if cur_indent <= indent:
                break
            # parse k: v
            stripped = ln.strip()
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k in out:
                    if k == "status":
                        out[k] = v.strip("'\"")
                    else:
                        try:
                            out[k] = float(v)
                        except Exception:
                            try:
                                out[k] = float(v.strip("'\""))
                            except Exception:
                                out[k] = None
            j += 1
        return out
    return None

def approx_equal(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def compute_reward(checks, required_paths_exist):
    # If any required output file is missing, reward must be 0.0
    if not all(required_paths_exist):
        return 0.0
    # reward as fraction of passed checks
    bool_values = [v for k, v in checks.items() if isinstance(v, bool)]
    if not bool_values:
        return 0.0
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values)
    if total == 0:
        return 0.0
    return passed / total

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "exists_food_library_yaml": False,
        "exists_meals_created_json": False,
        "exists_daily_summary_yaml": False,
        "exists_search_chicken_yaml": False,
        "exists_search_rice_yaml": False,

        "food_library_includes_all_names": False,
        "meals_created_shape_valid": False,
        "meals_created_names_times": False,
        "meals_created_ids_present": False,

        "daily_summary_parsed": False,
        "daily_consumed_match": False,
        "daily_pct_match": False,
        "daily_status_match": False,

        "search_chicken_mentions": False,
        "search_rice_mentions": False,
    }

    # Required output paths
    path_food_lib = os.path.join(output_dir, "food_library.yaml")
    path_meals_created = os.path.join(output_dir, "meals_created.json")
    path_daily_summary = os.path.join(output_dir, "daily_summary_2026-03-15.yaml")
    path_search_chicken = os.path.join(output_dir, "search_chicken.yaml")
    path_search_rice = os.path.join(output_dir, "search_rice.yaml")

    if os.path.isfile(path_food_lib):
        checks["exists_food_library_yaml"] = True
    if os.path.isfile(path_meals_created):
        checks["exists_meals_created_json"] = True
    if os.path.isfile(path_daily_summary):
        checks["exists_daily_summary_yaml"] = True
    if os.path.isfile(path_search_chicken):
        checks["exists_search_chicken_yaml"] = True
    if os.path.isfile(path_search_rice):
        checks["exists_search_rice_yaml"] = True

    required_paths_exist = [
        checks["exists_food_library_yaml"],
        checks["exists_meals_created_json"],
        checks["exists_daily_summary_yaml"],
        checks["exists_search_chicken_yaml"],
        checks["exists_search_rice_yaml"],
    ]

    # If any required file missing, reward should be 0.0 at end (but still print checks)
    # Proceed with further validation only if all exist
    if all(required_paths_exist):
        # Load inputs for expected computation
        foods_csv_path = os.path.join(input_dir, "foods.csv")
        meal_plan_yaml_path = os.path.join(input_dir, "meal_plan.yaml")
        goals_json_path = os.path.join(input_dir, "goals.json")

        foods = parse_csv_foods(foods_csv_path)
        meal_plan = parse_meal_plan_yaml(meal_plan_yaml_path)
        goals = read_json(goals_json_path) or {}

        # 1) food_library.yaml must include all food names (case-insensitive acceptable)
        food_lib_text = read_text(path_food_lib) or ""
        includes_all = True
        for nf, rec in foods.items():
            name = rec["name"]
            # presence check: appear at least once in text (case-insensitive)
            if re.search(re.escape(name), food_lib_text, flags=re.IGNORECASE) is None:
                includes_all = False
                break
        checks["food_library_includes_all_names"] = includes_all

        # 2) meals_created.json checks
        mc = read_json(path_meals_created)
        if isinstance(mc, dict) and "date" in mc and "meals" in mc and isinstance(mc["meals"], list):
            checks["meals_created_shape_valid"] = True
            # names and times exactly as required
            expected = [
                ("Breakfast", "08:00"),
                ("Lunch", "13:00"),
                ("Dinner", "19:00"),
            ]
            got = []
            ids_ok = True
            for m in mc["meals"]:
                name = m.get("name")
                time = m.get("time")
                mid = m.get("id")
                got.append((name, time))
                if not isinstance(mid, str) or len(mid.strip()) < 3:
                    ids_ok = False
            checks["meals_created_ids_present"] = ids_ok
            # order may or may not matter; require exactly these three pairs regardless of order
            try:
                got_sorted = sorted(got)
                exp_sorted = sorted(expected)
                checks["meals_created_names_times"] = (len(got_sorted) == 3 and got_sorted == exp_sorted and mc.get("date") == "2026-03-15")
            except Exception:
                checks["meals_created_names_times"] = False
        else:
            checks["meals_created_shape_valid"] = False
            checks["meals_created_names_times"] = False
            checks["meals_created_ids_present"] = False

        # 3) daily summary numeric validation
        summary_text = read_text(path_daily_summary) or ""
        expected_totals = {}
        if meal_plan is not None:
            expected_totals = compute_expected_totals(foods, meal_plan)

        nutrients = ["calories_kcal", "protein_g", "carbs_g", "fiber_g", "sugar_g", "fat_g", "sat_fat_g"]

        summary_ok = True
        pct_ok = True
        status_ok = True
        summary_parsed_any = False

        # Determine goal directions
        # protein_g and fiber_g are minimum targets; others are maximums
        min_targets = {"protein_g", "fiber_g"}

        for n in nutrients:
            parsed = parse_summary_for_nutrient(summary_text, n)
            if not parsed:
                summary_ok = False
                pct_ok = False
                status_ok = False
                continue
            summary_parsed_any = True
            consumed = parsed.get("consumed")
            goal = parsed.get("goal")
            pct = parsed.get("pct")
            status = parsed.get("status")
            exp_consumed = expected_totals.get(n, 0.0)

            # consumed within 0.5 abs tol
            if consumed is None or not approx_equal(consumed, exp_consumed, 0.5):
                summary_ok = False

            # goal pct check if goal present and >0
            if goal is None or goal == 0:
                pct_ok = False
            else:
                exp_pct = (exp_consumed / float(goal)) * 100.0
                if pct is None or not approx_equal(pct, exp_pct, 1.0):
                    pct_ok = False

            # status check
            if n in min_targets:
                exp_status = "under" if exp_consumed < float(goal or 0.0) else ("ok" if approx_equal(exp_consumed, goal, 0.0001) else "ok")
                # The task requires these to be "under"
                if status != "under":
                    status_ok = False
            else:
                # for max targets must be ok (consumed <= goal), not over
                if goal is None:
                    status_ok = False
                else:
                    if exp_consumed <= float(goal):
                        if status != "ok":
                            status_ok = False
                    else:
                        # over is not allowed by spec
                        status_ok = False

        checks["daily_summary_parsed"] = summary_parsed_any
        checks["daily_consumed_match"] = summary_ok
        checks["daily_pct_match"] = pct_ok
        checks["daily_status_match"] = status_ok

        # 4) search files mention queries at least twice (case-insensitive, in at least two lines)
        chicken_text = read_text(path_search_chicken) or ""
        rice_text = read_text(path_search_rice) or ""

        def mentions_at_least_twice_in_lines(text, term):
            count_lines = 0
            for ln in text.splitlines():
                if re.search(rf"{re.escape(term)}", ln, flags=re.IGNORECASE):
                    count_lines += 1
            return count_lines >= 2

        checks["search_chicken_mentions"] = mentions_at_least_twice_in_lines(chicken_text, "chicken")
        checks["search_rice_mentions"] = mentions_at_least_twice_in_lines(rice_text, "rice")

    reward = compute_reward(checks, required_paths_exist)
    # Print single JSON object as last non-empty line
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()