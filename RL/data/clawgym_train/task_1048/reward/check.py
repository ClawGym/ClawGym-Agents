import json
import os
import re
import sys
import csv

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_number(x):
    return isinstance(x, int) or isinstance(x, float)

def validate_pillars(pillars, stems_set, branches_set):
    # pillars should be dict with year, month, day, hour
    if not isinstance(pillars, dict):
        return False
    for pos in ["year", "month", "day", "hour"]:
        if pos not in pillars or not isinstance(pillars[pos], dict):
            return False
        item = pillars[pos]
        if "stem" not in item or "branch" not in item or "hidden_stems" not in item:
            return False
        if item["stem"] not in stems_set:
            return False
        if item["branch"] not in branches_set:
            return False
        hs = item["hidden_stems"]
        if not isinstance(hs, list):
            return False
        for s in hs:
            if s not in stems_set:
                return False
    return True

def validate_five_elements(fe):
    # keys wood, fire, earth, metal, water
    if not isinstance(fe, dict):
        return False
    required = ["wood", "fire", "earth", "metal", "water"]
    chinese_map = {
        "wood": "木",
        "fire": "火",
        "earth": "土",
        "metal": "金",
        "water": "水",
    }
    for k in required:
        if k not in fe or not isinstance(fe[k], dict):
            return False
        v = fe[k]
        if "score" not in v or "percent" not in v or "chinese" not in v:
            return False
        if not is_number(v["score"]):
            return False
        if not isinstance(v["percent"], str) or not v["percent"].endswith("%"):
            return False
        if v["chinese"] != chinese_map[k]:
            return False
    return True

def validate_major_luck(ml, stems_set, branches_set):
    if not isinstance(ml, dict):
        return False
    if "direction" not in ml or "start_age" not in ml or "periods" not in ml:
        return False
    if ml["direction"] not in {"顺排", "逆排"}:
        return False
    if not isinstance(ml["start_age"], int) or ml["start_age"] < 1:
        return False
    periods = ml["periods"]
    if not isinstance(periods, list) or len(periods) < 8:
        return False
    age_re = re.compile(r"^\d+-\d+$")
    years_re = re.compile(r"^\d{4}-\d{4}$")
    for p in periods:
        if not isinstance(p, dict):
            return False
        if "age" not in p or "years" not in p or "stem" not in p or "branch" not in p:
            return False
        if not isinstance(p["age"], str) or age_re.match(p["age"]) is None:
            return False
        if not isinstance(p["years"], str) or years_re.match(p["years"]) is None:
            return False
        if p["stem"] not in stems_set or p["branch"] not in branches_set:
            return False
    return True

def validate_relationships(rel):
    if not isinstance(rel, list):
        return False
    for item in rel:
        if not isinstance(item, dict):
            return False
        if "type" not in item or "positions" not in item or "result" not in item:
            return False
        if not isinstance(item["type"], str):
            return False
        if not isinstance(item["positions"], list):
            return False
        if not isinstance(item["result"], str):
            return False
    return True

def dominant_elements_keys(five_elements):
    # Return set of keys with max score
    max_score = None
    keys = []
    for k, v in five_elements.items():
        sc = v.get("score")
        if not is_number(sc):
            continue
        if max_score is None or sc > max_score:
            max_score = sc
            keys = [k]
        elif sc == max_score:
            keys.append(k)
    return set(keys)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "charts_exists": False,
        "charts_json_valid": False,
        "charts_results_len_3": False,
        "charts_items_have_id_and_input": False,
        "pillars_valid_all": False,
        "five_elements_valid_all": False,
        "day_master_strength_valid_all": False,
        "major_luck_valid_all": False,
        "relationships_valid_all": False,
        "summary_exists": False,
        "summary_header_ok": False,
        "summary_rows_3": False,
        "summary_rows_match_charts": False,
        "charts_results_match_input_ids_and_fields": False,
    }

    stems = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
    branches = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
    stems_set = set(stems)
    branches_set = set(branches)

    # Read input births.json for reference
    births_path = os.path.join(input_dir, "births.json")
    input_births, _ = load_json_file(births_path)
    input_ids = set()
    input_by_id = {}
    if isinstance(input_births, list):
        for person in input_births:
            pid = person.get("id")
            if pid is not None:
                input_ids.add(str(pid))
                input_by_id[str(pid)] = person

    # Load charts.json
    charts_path = os.path.join(output_dir, "charts.json")
    if os.path.isfile(charts_path):
        checks["charts_exists"] = True
        charts_json, err = load_json_file(charts_path)
        if charts_json is not None and isinstance(charts_json, dict):
            checks["charts_json_valid"] = True
            results = charts_json.get("results")
            if isinstance(results, list) and len(results) == 3:
                checks["charts_results_len_3"] = True

            # Validate ids and input echo presence and consistency with input if available
            items_have_id_and_input = True
            match_input_fields = True
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        items_have_id_and_input = False
                        break
                    rid = item.get("id")
                    rin = item.get("input")
                    if not isinstance(rid, str) or not isinstance(rin, dict):
                        items_have_id_and_input = False
                        break
                    # Check input fields presence and type
                    for f in ["date","time","city","gender"]:
                        if f not in rin or not isinstance(rin[f], str):
                            items_have_id_and_input = False
                            break
                    # Cross-check with input file if available
                    if input_by_id:
                        ref = input_by_id.get(rid)
                        if not ref:
                            match_input_fields = False
                        else:
                            # Compare fields as strings
                            if str(ref.get("date","")) != rin.get("date",""):
                                match_input_fields = False
                            if str(ref.get("time","")) != rin.get("time",""):
                                match_input_fields = False
                            if str(ref.get("city","")) != rin.get("city",""):
                                match_input_fields = False
                            if str(ref.get("gender","")) != rin.get("gender",""):
                                match_input_fields = False
                checks["charts_items_have_id_and_input"] = items_have_id_and_input
                # Only set this True if we have input ref and all matched
                if input_by_id and items_have_id_and_input and match_input_fields and len(results) == len(input_by_id) == 3:
                    checks["charts_results_match_input_ids_and_fields"] = True

            # Validate pillars/five_elements/day_master_strength/major_luck/relationships for all
            if isinstance(results, list) and len(results) > 0:
                pillars_all = True
                fe_all = True
                dms_all = True
                ml_all = True
                rel_all = True
                for item in results:
                    # pillars
                    if not validate_pillars(item.get("pillars"), stems_set, branches_set):
                        pillars_all = False
                    # five elements
                    if not validate_five_elements(item.get("five_elements")):
                        fe_all = False
                    # day master strength
                    dms = item.get("day_master_strength")
                    if dms not in {"偏强","偏弱"}:
                        dms_all = False
                    # major luck
                    if not validate_major_luck(item.get("major_luck"), stems_set, branches_set):
                        ml_all = False
                    # relationships
                    if not validate_relationships(item.get("relationships", [])):
                        rel_all = False
                checks["pillars_valid_all"] = pillars_all
                checks["five_elements_valid_all"] = fe_all
                checks["day_master_strength_valid_all"] = dms_all
                checks["major_luck_valid_all"] = ml_all
                checks["relationships_valid_all"] = rel_all

    # Load and validate summary.csv
    summary_path = os.path.join(output_dir, "summary.csv")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                reader = list(csv.reader(f))
            if len(reader) >= 1:
                header = reader[0]
                expected_header = ["id","gender","birth_local_time","city","day_master_stem","major_luck_direction","major_luck_start_age","dominant_element_en"]
                if header == expected_header:
                    checks["summary_header_ok"] = True
                rows = reader[1:]
                if len(rows) == 3:
                    checks["summary_rows_3"] = True

                # Cross-check against charts.json
                if checks["charts_json_valid"]:
                    charts_json, _ = load_json_file(charts_path)
                    results = charts_json.get("results") if isinstance(charts_json, dict) else None
                    if isinstance(results, list):
                        by_id = {}
                        for item in results:
                            rid = item.get("id")
                            if isinstance(rid, str):
                                by_id[rid] = item
                        all_ok = True
                        for row in rows:
                            if len(row) != 8:
                                all_ok = False
                                break
                            rid, gender, birth_local_time, city, day_master_stem, major_luck_direction, major_luck_start_age, dominant_element_en = row
                            if rid not in by_id:
                                all_ok = False
                                break
                            cj = by_id[rid]
                            # Check input consistency
                            rin = cj.get("input", {})
                            if rin.get("gender","") != gender:
                                all_ok = False
                                break
                            expected_blt = f"{rin.get('date','')} {rin.get('time','')}"
                            if expected_blt != birth_local_time:
                                all_ok = False
                                break
                            if rin.get("city","") != city:
                                all_ok = False
                                break
                            # day master stem
                            pillars = cj.get("pillars", {})
                            ds = None
                            if isinstance(pillars, dict) and isinstance(pillars.get("day"), dict):
                                ds = pillars["day"].get("stem")
                            if ds != day_master_stem:
                                all_ok = False
                                break
                            # major luck direction and start_age
                            ml = cj.get("major_luck", {})
                            if ml.get("direction") != major_luck_direction:
                                all_ok = False
                                break
                            try:
                                mla = int(major_luck_start_age)
                            except Exception:
                                all_ok = False
                                break
                            if ml.get("start_age") != mla:
                                all_ok = False
                                break
                            # dominant element
                            fe = cj.get("five_elements", {})
                            dom_keys = dominant_elements_keys(fe)
                            if dominant_element_en not in dom_keys:
                                all_ok = False
                                break
                        if all_ok and len(rows) == 3:
                            checks["summary_rows_match_charts"] = True
        except Exception:
            # If reading/parsing fails, keep flags as False
            pass

    # Compute reward: require both output artifacts to exist for any positive reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    if not (checks["charts_exists"] and checks["summary_exists"]):
        reward = 0.0
    else:
        # Avoid giving reward if the most critical validations fail
        critical = [
            "charts_json_valid",
            "charts_results_len_3",
            "charts_items_have_id_and_input",
            "pillars_valid_all",
            "five_elements_valid_all",
            "day_master_strength_valid_all",
            "major_luck_valid_all",
            "relationships_valid_all",
            "summary_header_ok",
            "summary_rows_3",
            "summary_rows_match_charts",
        ]
        # If any critical check is False, compute fractional based on passed; else full
        if all(checks[c] for c in critical):
            reward = 1.0
        else:
            # Fractional score: passed/total, but clamp to <1
            reward = round(passed_checks / total_checks, 6)
            if reward == 1.0:
                reward = 0.99

    # Print final JSON (single line)
    output = {"reward": float(reward)}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()