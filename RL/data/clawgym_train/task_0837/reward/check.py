import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

workspace_root = get_workspace_root()
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path: str) -> Tuple[bool, Optional[Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def parse_csv(path: str) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return False, [], []
        headers = rows[0]
        data_rows = rows[1:]
        # Build list of dicts tolerant to header case
        normalized_headers = [h.strip() for h in headers]
        out = []
        for r in data_rows:
            if len(r) == 0:
                continue
            row_dict = {}
            for i, h in enumerate(normalized_headers):
                if i < len(r):
                    row_dict[h] = r[i]
                else:
                    row_dict[h] = ""
            out.append(row_dict)
        return True, out, normalized_headers
    except Exception:
        return False, [], []

def to_float_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    # strip $ and commas and spaces
    s2 = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s2)
    except Exception:
        return None

def norm(s: str) -> str:
    # Lowercase, remove punctuation except spaces, collapse spaces
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-&/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def norm_simple(s: str) -> str:
    # More aggressive normalization for matching pantry items
    s = norm(s)
    # remove common descriptors
    s = s.replace("gluten free", "gf").replace("gluten-free", "gf")
    s = re.sub(r"\bbrand\b|\bstore brand\b|\borganic\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # singularize naive: remove trailing 's' for words >3 chars
    parts = s.split()
    parts2 = []
    for w in parts:
        if len(w) > 3 and w.endswith("s"):
            parts2.append(w[:-1])
        else:
            parts2.append(w)
    s = " ".join(parts2)
    return s

def extract_string_list(maybe_list: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(maybe_list, list):
        return out
    for item in maybe_list:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key in ["name", "item", "title", "label", "value"]:
                if key in item and isinstance(item[key], str):
                    out.append(item[key])
                    break
    return out

def get_meal_ideas(obj: Any) -> List[str]:
    ideas: List[str] = []
    if not isinstance(obj, dict):
        return ideas
    # look for standard keys
    for key in ["meals", "meal_ideas", "ideas", "mealIdeas", "mealideas"]:
        if key in obj and isinstance(obj[key], list):
            arr = [str(x) for x in obj[key] if isinstance(x, (str, int, float)) or isinstance(x, dict) and False]
            # If dicts inside, ignore for simplicity
            ideas.extend([str(x) for x in arr])
    # fallback: any array-valued field containing strings length >=2
    if not ideas:
        for v in obj.values():
            if isinstance(v, list):
                arr = [x for x in v if isinstance(x, (str, int, float))]
                if len(arr) >= 2:
                    ideas.extend([str(x) for x in arr])
    return ideas

def line_contains_both(line: str, a_opts: List[str], b_opts: List[str]) -> bool:
    ln = line.lower()
    has_a = any(a in ln for a in a_opts)
    has_b = any(b in ln for b in b_opts)
    return has_a and has_b

def read_on_hand_items(pantry_path: str) -> List[str]:
    ok, data = read_json(pantry_path)
    items: List[str] = []
    if not ok or data is None:
        return items
    try:
        if isinstance(data, dict):
            # if dict has list under "items" or "pantry"
            for k in ["items", "pantry", "on_hand_items", "stock"]:
                if k in data and isinstance(data[k], list):
                    for entry in data[k]:
                        if isinstance(entry, dict):
                            name = entry.get("item") or entry.get("name") or entry.get("label") or entry.get("title")
                            on_hand = entry.get("on_hand")
                            if on_hand is None:
                                on_hand = entry.get("onHand")
                            if isinstance(name, str) and bool(on_hand):
                                items.append(name)
                        elif isinstance(entry, str):
                            # assume string implies on hand
                            items.append(entry)
                # if dict mapping item->on_hand bool
            # top-level mapping item -> boolean
            if all(isinstance(v, (bool, dict)) for v in data.values()):
                for k, v in data.items():
                    if isinstance(v, bool) and v:
                        items.append(k)
                    elif isinstance(v, dict) and v.get("on_hand") is True:
                        items.append(k)
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    name = entry.get("item") or entry.get("name") or entry.get("label") or entry.get("title")
                    on_hand = entry.get("on_hand")
                    if on_hand is None:
                        on_hand = entry.get("onHand")
                    if isinstance(name, str) and bool(on_hand):
                        items.append(name)
                elif isinstance(entry, str):
                    items.append(entry)
    except Exception:
        pass
    # normalize
    return [norm_simple(x) for x in items]

def any_contains_mushroom(items: List[str]) -> bool:
    for s in items:
        if "mushroom" in s.lower():
            return True
    return False

def contains_phrase(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()

checks: Dict[str, bool] = {}

# Paths
meal_plan_path = os.path.join(output_dir, "meal_plan.json")
shopping_list_path = os.path.join(output_dir, "shopping_list.csv")
budget_breakdown_path = os.path.join(output_dir, "budget_breakdown.json")
prep_schedule_path = os.path.join(output_dir, "prep_schedule.md")
storage_guide_path = os.path.join(output_dir, "storage_guide.md")
pantry_path = os.path.join(input_dir, "pantry.json")

# 1) meal_plan.json
checks["meal_plan_exists"] = os.path.isfile(meal_plan_path)
meal_plan_json_ok = False
meal_plan = None
if checks["meal_plan_exists"]:
    meal_plan_json_ok, meal_plan = read_json(meal_plan_path)
checks["meal_plan_valid_json"] = meal_plan_json_ok

# initialize dependent checks to False
checks["meal_plan_budget_50"] = False
checks["meal_plan_restrictions_include"] = False
checks["meal_plan_base_template_structure"] = False
checks["meal_plan_assembly_formula_valid"] = False
checks["meal_plan_weekly_plan_7days_2ideas"] = False
checks["meal_plan_proteins_vegetarian"] = False
checks["meal_plan_starches_gluten_free"] = False
checks["meal_plan_sauces_gf_includes_tamari_or_coconut_aminos"] = False
checks["meal_plan_no_mushrooms"] = False

if meal_plan_json_ok and isinstance(meal_plan, dict):
    # budget
    budget = meal_plan.get("budget", None)
    if isinstance(budget, (int, float)) and float(budget) == 50.0:
        checks["meal_plan_budget_50"] = True

    # restrictions
    restrictions = meal_plan.get("restrictions", [])
    restr_lc = [str(x).lower() for x in restrictions] if isinstance(restrictions, list) else []
    if "vegetarian" in restr_lc and ("gluten-free" in restr_lc or "gluten free" in restr_lc):
        checks["meal_plan_restrictions_include"] = True

    # base_template structure
    bt = meal_plan.get("base_template", {})
    bt_ok = isinstance(bt, dict) and all(k in bt for k in ["proteins", "starches", "vegetables", "sauces"])
    if bt_ok:
        pr = extract_string_list(bt.get("proteins"))
        st = extract_string_list(bt.get("starches"))
        ve = extract_string_list(bt.get("vegetables"))
        sa = extract_string_list(bt.get("sauces"))
        if all(isinstance(x, list) for x in [pr, st, ve, sa]):
            checks["meal_plan_base_template_structure"] = True
    else:
        pr = st = ve = sa = []

    # assembly formula
    af = meal_plan.get("assembly_formula")
    if isinstance(af, str):
        af_l = af.lower()
        # require all concept words present
        if ("grain" in af_l or "starch" in af_l) and ("protein" in af_l) and ("vegetable" in af_l) and ("sauce" in af_l):
            checks["meal_plan_assembly_formula_valid"] = True

    # weekly plan
    wp = meal_plan.get("weekly_plan", [])
    wp_ok = False
    if isinstance(wp, list) and len(wp) == 7:
        ok_each = True
        for day_obj in wp:
            if not isinstance(day_obj, dict):
                ok_each = False
                break
            if "day" not in day_obj:
                ok_each = False
                break
            ideas = get_meal_ideas(day_obj)
            if len(ideas) < 2:
                ok_each = False
                break
        wp_ok = ok_each
    checks["meal_plan_weekly_plan_7days_2ideas"] = wp_ok

    # proteins vegetarian
    meat_terms = [
        "chicken","beef","pork","tuna","sardine","salmon","shrimp","turkey","ham","bacon",
        "sausage","lamb","duck","fish","anchovy","anchovies","tilapia"
    ]
    proteins_lc = [s.lower() for s in extract_string_list(bt.get("proteins", []))]
    if proteins_lc:
        if not any(any(mt in p for mt in meat_terms) for p in proteins_lc):
            checks["meal_plan_proteins_vegetarian"] = True

    # starches gluten-free
    starches_lc = [s.lower() for s in extract_string_list(bt.get("starches", []))]
    gf_bad_terms = ["wheat", "barley", "rye", "farro", "spelt", "bulgur", "semolina", "seitan", "couscous", "bread", "flour tortilla"]
    def starch_ok(item: str) -> bool:
        it = item.lower()
        if any(b in it for b in gf_bad_terms):
            return False
        if "pasta" in it and not any(g in it for g in ["rice", "corn", "quinoa", "gluten-free", "gluten free", "gf"]):
            return False
        if "oat" in it and not any(g in it for g in ["gluten-free", "gluten free", "gf"]):
            return False
        # otherwise assume OK (rice, potato, quinoa, corn, etc.)
        return True
    if starches_lc and all(starch_ok(x) for x in starches_lc):
        checks["meal_plan_starches_gluten_free"] = True

    # sauces tamari or coconut aminos; no "soy sauce"
    sauces_lc = [s.lower() for s in extract_string_list(bt.get("sauces", []))]
    has_gf_soy_style = any(("tamari" in s) or ("coconut aminos" in s) for s in sauces_lc)
    has_plain_soy = any("soy sauce" in s for s in sauces_lc)
    if has_gf_soy_style and not has_plain_soy:
        checks["meal_plan_sauces_gf_includes_tamari_or_coconut_aminos"] = True

    # no mushrooms anywhere in base_template or weekly plan ideas
    no_mush = True
    if any_contains_mushroom(proteins_lc + starches_lc + [s.lower() for s in extract_string_list(bt.get("vegetables", []))] + sauces_lc):
        no_mush = False
    if wp and isinstance(wp, list):
        for day_obj in wp:
            ideas = get_meal_ideas(day_obj)
            if any("mushroom" in str(x).lower() for x in ideas):
                no_mush = False
                break
    checks["meal_plan_no_mushrooms"] = no_mush

# 2) shopping_list.csv
checks["shopping_list_exists"] = os.path.isfile(shopping_list_path)
checks["shopping_list_has_headers"] = False
checks["shopping_list_total_in_range"] = False
checks["shopping_list_includes_tamari_or_coconut_aminos_pantry_flavor"] = False
checks["shopping_list_excludes_on_hand"] = False
checks["shopping_list_no_mushrooms"] = False

csv_ok = False
csv_rows: List[Dict[str, str]] = []
csv_headers: List[str] = []
if checks["shopping_list_exists"]:
    csv_ok, csv_rows, csv_headers = parse_csv(shopping_list_path)
    # headers check
    required_headers = ["item","category","unit","quantity","estimated_cost","notes"]
    headers_norm_map = {h.lower().strip(): h for h in csv_headers}
    has_all = all(h in headers_norm_map for h in required_headers)
    checks["shopping_list_has_headers"] = csv_ok and has_all

    if csv_ok and has_all:
        # total range
        total = 0.0
        for row in csv_rows:
            val = to_float_money(row.get(headers_norm_map["estimated_cost"], ""))
            if val is not None:
                total += val
        if 40.0 <= total <= 60.0:
            checks["shopping_list_total_in_range"] = True

        # includes tamari or coconut aminos in pantry_flavor
        found_pf = False
        for row in csv_rows:
            item = str(row.get(headers_norm_map["item"], "")).lower()
            cat = str(row.get(headers_norm_map["category"], "")).lower()
            if cat == "pantry_flavor" and (("tamari" in item) or ("coconut aminos" in item)):
                found_pf = True
                break
        checks["shopping_list_includes_tamari_or_coconut_aminos_pantry_flavor"] = found_pf

        # excludes on-hand
        on_hand = read_on_hand_items(pantry_path)
        on_hand_set = set(on_hand)
        def is_forbidden(item_name: str) -> bool:
            item_n = norm_simple(item_name)
            # compare equality after normalization
            if item_n in on_hand_set:
                return True
            # also forbid exact pantry terms that are very common seasoning if they appear explicitly and on-hand
            for oh in on_hand_set:
                # token-based contain check: both directions
                if oh and (oh in item_n or item_n in oh):
                    return True
            return False
        forbidden_found = False
        for row in csv_rows:
            item = str(row.get(headers_norm_map["item"], ""))
            if is_forbidden(item):
                forbidden_found = True
                break
        checks["shopping_list_excludes_on_hand"] = not forbidden_found

        # no mushrooms
        no_mush = True
        for row in csv_rows:
            item = str(row.get(headers_norm_map["item"], "")).lower()
            if "mushroom" in item:
                no_mush = False
                break
        checks["shopping_list_no_mushrooms"] = no_mush

# 3) budget_breakdown.json
checks["budget_breakdown_exists"] = os.path.isfile(budget_breakdown_path)
bb_ok, bb = (False, None)
if checks["budget_breakdown_exists"]:
    bb_ok, bb = read_json(budget_breakdown_path)
checks["budget_breakdown_valid_json"] = bool(bb_ok and isinstance(bb, dict))
checks["budget_breakdown_categories_numeric"] = False
checks["budget_breakdown_total_matches_sum"] = False
checks["budget_breakdown_total_in_range"] = False
checks["budget_breakdown_matches_csv_by_category"] = False

if checks["budget_breakdown_valid_json"]:
    # required numeric fields
    cats = ["proteins", "starches", "vegetables", "pantry_flavor", "total"]
    numeric = True
    values: Dict[str, float] = {}
    for c in cats:
        v = bb.get(c, None)
        if not isinstance(v, (int, float)):
            numeric = False
            break
        values[c] = float(v)
    checks["budget_breakdown_categories_numeric"] = numeric
    if numeric:
        sum_cats = values["proteins"] + values["starches"] + values["vegetables"] + values["pantry_flavor"]
        if abs(sum_cats - values["total"]) <= 0.50:
            checks["budget_breakdown_total_matches_sum"] = True
        if 40.0 <= values["total"] <= 60.0:
            checks["budget_breakdown_total_in_range"] = True

        # compare with CSV grouped totals (within $1.00)
        if checks.get("shopping_list_has_headers", False):
            headers_norm_map = {h.lower().strip(): h for h in csv_headers}
            cat_field = headers_norm_map.get("category")
            cost_field = headers_norm_map.get("estimated_cost")
            group_totals: Dict[str, float] = {"proteins": 0.0, "starches": 0.0, "vegetables": 0.0, "pantry_flavor": 0.0}
            for row in csv_rows:
                if cat_field is None or cost_field is None:
                    continue
                cat = str(row.get(cat_field, "")).lower().strip()
                cost = to_float_money(row.get(cost_field, ""))
                if cost is None:
                    continue
                if cat in group_totals:
                    group_totals[cat] += cost
            match = True
            for c in ["proteins", "starches", "vegetables", "pantry_flavor"]:
                if abs(group_totals[c] - values[c]) > 1.00:
                    match = False
                    break
            checks["budget_breakdown_matches_csv_by_category"] = match

# 4) prep_schedule.md
checks["prep_schedule_exists"] = os.path.isfile(prep_schedule_path)
checks["prep_schedule_mentions_parallel_cooking"] = False
checks["prep_schedule_includes_required_steps"] = False
checks["prep_schedule_includes_food_safety_phrases"] = False
if checks["prep_schedule_exists"]:
    ps = read_text(prep_schedule_path) or ""
    ps_l = ps.lower()
    # parallel cooking mention
    if ("parallel cooking" in ps_l) or ("while things are cooking, do the next thing".lower() in ps_l):
        checks["prep_schedule_mentions_parallel_cooking"] = True
    # required steps
    has_grains = any(x in ps_l for x in ["grain", "rice", "quinoa", "oat"])
    # oven proteins (vegetarian): look for oven and one of tofu/eggs/egg/frittata/sheet-pan eggs
    has_oven = ("oven" in ps_l)
    has_veg_protein = any(x in ps_l for x in ["tofu", "egg", "eggs", "frittata", "sheet-pan eggs", "sheet pan eggs"])
    has_roasted_veg = ("roast" in ps_l and "vegetable" in ps_l)
    has_sauce = ("sauce" in ps_l)
    has_stew_soup = ("stew" in ps_l) or ("soup" in ps_l)
    has_portion = ("portion" in ps_l)
    has_freeze = ("freez" in ps_l)  # freeze/freezing/frozen
    if has_grains and has_oven and has_veg_protein and has_roasted_veg and has_sauce and has_stew_soup and has_portion and has_freeze:
        checks["prep_schedule_includes_required_steps"] = True
    # food safety phrases
    fs1 = "cool from 140f to 40f within 2 hours"
    fs2 = "shallow containers"
    fs3 = "ice bath"
    if (fs1 in ps_l) and (fs2 in ps_l) and (fs3 in ps_l):
        checks["prep_schedule_includes_food_safety_phrases"] = True

# 5) storage_guide.md
checks["storage_guide_exists"] = os.path.isfile(storage_guide_path)
checks["storage_guide_refrigerator_lines"] = False
checks["storage_guide_freezer_3_months"] = False
checks["storage_guide_zero_waste_labeling"] = False
if checks["storage_guide_exists"]:
    sg = read_text(storage_guide_path) or ""
    lines = sg.splitlines()
    # fridge lines
    has_rice = False
    has_beans_lentils = False
    has_soups_stews = False
    for line in lines:
        l = line.lower()
        if "cooked rice" in l and ("4-5 days" in l or "4–5 days" in l):
            has_rice = True
        if (("beans" in l) or ("lentils" in l)) and ("4-5 days" in l or "4–5 days" in l):
            has_beans_lentils = True
        if (("soups" in l) or ("stews" in l)) and ("4-5 days" in l or "4–5 days" in l):
            has_soups_stews = True
    if has_rice and has_beans_lentils and has_soups_stews:
        checks["storage_guide_refrigerator_lines"] = True

    # freezer 3 months for grains/beans/soups
    freezer_lines = [l.lower() for l in lines if "3 month" in l.lower()]
    has_3mo = any(any(k in l for k in ["grain", "beans", "lentils", "soups", "stews"]) for l in freezer_lines)
    checks["storage_guide_freezer_3_months"] = has_3mo

    # zero-waste labeling: FIFO + label with dates
    sg_l = sg.lower()
    fifo_ok = ("first in, first out" in sg_l) or ("fifo" in sg_l)
    label_ok = ("label" in sg_l and "date" in sg_l)
    checks["storage_guide_zero_waste_labeling"] = fifo_ok and label_ok

# Compute reward
# Only artifact-dependent checks are included; missing files keep dependent checks False.
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)
reward = 0.0
if total_checks > 0 and passed_checks > 0:
    reward = passed_checks / total_checks

# Print exactly one JSON object on last non-empty stdout line
result = {"reward": round(reward, 6)}
result.update(checks)
print(json.dumps(result))