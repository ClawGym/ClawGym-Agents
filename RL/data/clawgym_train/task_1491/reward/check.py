import json
import os
import re
import sys
from datetime import datetime

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def is_valid_date(s):
    if not isinstance(s, str):
        return False
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return False
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def is_valid_time(s):
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", s):
        return False
    try:
        hh, mm, ss = map(int, s.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return False
        return True
    except Exception:
        return False

def validate_record(rec):
    # Returns (valid_bool, reason_if_invalid)
    # Required fields: id (string), name (string), birth_date (YYYY-MM-DD), birth_time (HH:MM:SS 24h), birth_location (string)
    # The task summary mentions id for filenames; treat id as required for processing.
    required_str_fields = ["id", "name", "birth_date", "birth_time", "birth_location"]
    for k in required_str_fields:
        if k not in rec or not isinstance(rec[k], str) or rec[k].strip() == "":
            return False, f"missing or invalid field {k}"
    if not is_valid_date(rec["birth_date"]):
        return False, "invalid birth_date format"
    if not is_valid_time(rec["birth_time"]):
        return False, "invalid birth_time format"
    return True, None

def expected_language(rec):
    lang = rec.get("language", None)
    if isinstance(lang, str) and lang.strip() != "":
        return lang
    return "en"

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def validate_chart_json(obj):
    # Required fields and structures:
    # name (string), birth_date (YYYY-MM-DD), birth_time (HH:MM:SS), birth_location (string)
    # ascendant.sign (string), ascendant.degree (number)
    # sun.sign (string), sun.degree (number)
    # moon.sign (string), moon.degree (number)
    # planets: non-empty array of objects: each {name (string), sign (string), degree (number)}
    # houses: object with at least one key
    # chart_interpretation: non-empty string
    if not isinstance(obj, dict):
        return False, "chart not an object"
    # Basic identity fields
    for k in ["name", "birth_date", "birth_time", "birth_location"]:
        if k not in obj or not isinstance(obj[k], str) or obj[k].strip() == "":
            return False, f"missing or invalid {k}"
    if not is_valid_date(obj["birth_date"]):
        return False, "birth_date format invalid"
    if not is_valid_time(obj["birth_time"]):
        return False, "birth_time format invalid"
    # Ascendant
    asc = obj.get("ascendant")
    if not isinstance(asc, dict) or "sign" not in asc or "degree" not in asc:
        return False, "missing ascendant info"
    if not isinstance(asc["sign"], str) or asc["sign"].strip() == "" or not is_number(asc["degree"]):
        return False, "invalid ascendant fields"
    # Sun
    sun = obj.get("sun")
    if not isinstance(sun, dict) or "sign" not in sun or "degree" not in sun:
        return False, "missing sun info"
    if not isinstance(sun["sign"], str) or sun["sign"].strip() == "" or not is_number(sun["degree"]):
        return False, "invalid sun fields"
    # Moon
    moon = obj.get("moon")
    if not isinstance(moon, dict) or "sign" not in moon or "degree" not in moon:
        return False, "missing moon info"
    if not isinstance(moon["sign"], str) or moon["sign"].strip() == "" or not is_number(moon["degree"]):
        return False, "invalid moon fields"
    # Planets
    planets = obj.get("planets")
    if not isinstance(planets, list) or len(planets) == 0:
        return False, "planets array missing or empty"
    for p in planets:
        if not isinstance(p, dict):
            return False, "planet entry not object"
        if "name" not in p or "sign" not in p or "degree" not in p:
            return False, "planet missing fields"
        if not isinstance(p["name"], str) or p["name"].strip() == "":
            return False, "planet name invalid"
        if not isinstance(p["sign"], str) or p["sign"].strip() == "":
            return False, "planet sign invalid"
        if not is_number(p["degree"]):
            return False, "planet degree invalid"
    # Houses
    houses = obj.get("houses")
    if not isinstance(houses, dict) or len(houses.keys()) == 0:
        return False, "houses missing or empty"
    # chart_interpretation
    ci = obj.get("chart_interpretation")
    if not isinstance(ci, str) or ci.strip() == "":
        return False, "chart_interpretation missing or empty"
    return True, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "stats_exists": False,
        "stats_counts_correct": False,
        "manifest_exists": False,
        "manifest_structure_valid": False,
        "manifest_ids_match_valid": False,
        "manifest_paths_resolve": False,
        "manifest_language_correct": False,
        "manifest_signs_match_charts": False,
        "skipped_exists": False,
        "skipped_structure_valid": False,
        "skipped_ids_correct": False,
        "charts_exist_for_valid": False,
        "charts_content_valid": False,
    }

    # Parse input people.jsonl
    people_path = os.path.join(input_dir, "people.jsonl")
    lines = read_text_lines(people_path)
    total_rows = 0
    records = []
    if lines is not None:
        for line in lines:
            if line is None:
                continue
            s = line.strip()
            if s == "":
                continue
            total_rows += 1
            try:
                rec = json.loads(s)
                if isinstance(rec, dict):
                    records.append(rec)
                else:
                    # Not an object: treat as invalid with no id
                    records.append({"_invalid_raw": True})
            except Exception:
                # Invalid JSON
                records.append({"_invalid_json": True})

    # Determine valid and invalid records by our validation
    valid_ids = []
    invalid_ids = []
    id_to_record = {}
    for rec in records:
        if not isinstance(rec, dict):
            invalid_ids.append(None)
            continue
        if rec.get("_invalid_raw") or rec.get("_invalid_json"):
            # cannot ascertain id
            invalid_ids.append(None)
            continue
        ok, reason = validate_record(rec)
        rid = rec.get("id") if isinstance(rec.get("id"), str) else None
        if ok and rid:
            valid_ids.append(rid)
            id_to_record[rid] = rec
        else:
            # even if rid is None, we track as invalid but cannot enforce skipped id
            invalid_ids.append(rid)

    expected_processed = len(valid_ids)
    expected_skipped = len([i for i in invalid_ids if i is not None]) + (len([i for i in invalid_ids if i is None]))
    # We consider total_rows as the count of non-empty lines
    expected_total = total_rows

    # Load outputs
    stats_path = os.path.join(output_dir, "stats.json")
    manifest_path = os.path.join(output_dir, "manifest.json")
    skipped_path = os.path.join(output_dir, "skipped.json")

    # stats.json checks
    stats_obj = read_json(stats_path)
    if isinstance(stats_obj, dict):
        checks["stats_exists"] = True
        tr = stats_obj.get("total_rows")
        pr = stats_obj.get("processed")
        sk = stats_obj.get("skipped")
        if isinstance(tr, int) and isinstance(pr, int) and isinstance(sk, int):
            if tr == expected_total and pr == expected_processed and sk == (expected_total - expected_processed):
                checks["stats_counts_correct"] = True

    # skipped.json checks
    skipped_arr = read_json(skipped_path)
    skipped_ids_in_output = set()
    if isinstance(skipped_arr, list):
        checks["skipped_exists"] = True
        structure_ok = True
        for item in skipped_arr:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if "id" not in item or "reason" not in item:
                structure_ok = False
                break
            if not isinstance(item["id"], str) or item["id"].strip() == "":
                structure_ok = False
                break
            if not isinstance(item["reason"], str) or item["reason"].strip() == "":
                structure_ok = False
                break
            skipped_ids_in_output.add(item["id"])
        if structure_ok:
            checks["skipped_structure_valid"] = True
            # Only compare ids that we can derive from input (non-None)
            expected_invalid_ids = set([i for i in invalid_ids if i is not None])
            # Require exact match with expected invalid ids
            if skipped_ids_in_output == expected_invalid_ids:
                checks["skipped_ids_correct"] = True

    # manifest.json checks
    manifest_arr = read_json(manifest_path)
    manifest_by_id = {}
    charts_exist_for_all = True
    charts_valid_for_all = True
    paths_resolve_ok = True
    language_ok_all = True
    signs_match_all = True
    if isinstance(manifest_arr, list):
        checks["manifest_exists"] = True
        structure_ok = True
        for item in manifest_arr:
            if not isinstance(item, dict):
                structure_ok = False
                break
            # Required fields: id, name, language, ascendant_sign, sun_sign, moon_sign, chart_path
            req_fields = ["id", "name", "language", "ascendant_sign", "sun_sign", "moon_sign", "chart_path"]
            for f in req_fields:
                if f not in item:
                    structure_ok = False
                    break
            if not structure_ok:
                break
            if not all(isinstance(item[f], str) and item[f].strip() != "" for f in ["id", "name", "language", "ascendant_sign", "sun_sign", "moon_sign", "chart_path"]):
                structure_ok = False
                break
            manifest_by_id[item["id"]] = item
        if structure_ok:
            checks["manifest_structure_valid"] = True
            # IDs match exactly the valid ids
            if set(manifest_by_id.keys()) == set(valid_ids):
                checks["manifest_ids_match_valid"] = True

            # For each valid id, resolve chart_path, validate chart, language, and signs
            for vid in valid_ids:
                item = manifest_by_id.get(vid)
                if not item:
                    charts_exist_for_all = False
                    charts_valid_for_all = False
                    paths_resolve_ok = False
                    language_ok_all = False
                    signs_match_all = False
                    continue
                chart_path_field = item.get("chart_path", "")
                resolved = None
                # Accept relative 'charts/{id}.json' or 'output/charts/{id}.json' or absolute
                if os.path.isabs(chart_path_field):
                    resolved = chart_path_field
                else:
                    # relative: if starts with 'charts', resolve under output_dir
                    if chart_path_field.startswith("charts"):
                        resolved = os.path.join(output_dir, chart_path_field)
                    elif chart_path_field.startswith("output"):
                        resolved = os.path.join(workspace_root, chart_path_field)
                    else:
                        # treat as relative to output dir by default
                        resolved = os.path.join(output_dir, chart_path_field)
                try:
                    resolved = os.path.realpath(resolved)
                except Exception:
                    pass
                expected_chart_path = os.path.join(output_dir, "charts", f"{vid}.json")
                # Path must point to the corresponding charts/{id}.json
                same_target = os.path.realpath(resolved) == os.path.realpath(expected_chart_path)
                if not same_target:
                    paths_resolve_ok = False
                if not os.path.isfile(expected_chart_path):
                    charts_exist_for_all = False
                    charts_valid_for_all = False
                    signs_match_all = False
                    continue
                # Validate chart content
                chart_obj = read_json(expected_chart_path)
                ok, _ = validate_chart_json(chart_obj)
                if not ok:
                    charts_valid_for_all = False
                else:
                    # Language correctness in manifest based on input record
                    rec = id_to_record.get(vid, {})
                    exp_lang = expected_language(rec)
                    if item.get("language") != exp_lang:
                        language_ok_all = False
                    # Signs consistency between manifest and chart
                    try:
                        asc_sign = chart_obj["ascendant"]["sign"]
                        sun_sign = chart_obj["sun"]["sign"]
                        moon_sign = chart_obj["moon"]["sign"]
                        if item.get("ascendant_sign") != asc_sign or item.get("sun_sign") != sun_sign or item.get("moon_sign") != moon_sign:
                            signs_match_all = False
                    except Exception:
                        signs_match_all = False

            if paths_resolve_ok:
                checks["manifest_paths_resolve"] = True
            if language_ok_all and checks["manifest_ids_match_valid"]:
                checks["manifest_language_correct"] = True
            if signs_match_all and checks["manifest_ids_match_valid"]:
                checks["manifest_signs_match_charts"] = True

    # charts existence and validity aggregated checks
    # charts_exist_for_valid: must exist for all valid ids
    if len(valid_ids) > 0 and charts_exist_for_all:
        checks["charts_exist_for_valid"] = True
    elif len(valid_ids) == 0:
        # If there are no valid ids, then by definition no charts should exist; but do not grant positive credit.
        checks["charts_exist_for_valid"] = False

    if len(valid_ids) > 0 and charts_valid_for_all:
        checks["charts_content_valid"] = True
    elif len(valid_ids) == 0:
        checks["charts_content_valid"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty required artifacts, ensure reward is 0
    required_files = [
        os.path.join(output_dir, "manifest.json"),
        os.path.join(output_dir, "stats.json"),
        os.path.join(output_dir, "skipped.json"),
    ]
    required_present = all(os.path.isfile(p) for p in required_files)
    if not required_present:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()