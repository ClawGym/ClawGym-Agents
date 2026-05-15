import json
import os
import sys
import re
import csv

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def percent_str_ok(s):
    if not isinstance(s, str):
        return False
    if not s.endswith("%"):
        return False
    digits = s[:-1]
    return len(digits) > 0 and digits.isdigit()

def validate_age_str(s):
    if not isinstance(s, str):
        return False
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", s)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return a <= b

def validate_years_str(s):
    if not isinstance(s, str):
        return False
    m = re.fullmatch(r"\s*(\d{4})\s*-\s*(\d{4})\s*", s)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return a <= b

def validate_person_schema(person):
    # Basic required keys
    required_top = ["name", "birth", "pillars", "day_master", "five_elements", "major_luck", "relationships"]
    for k in required_top:
        if k not in person:
            return False
    if not isinstance(person["name"], str) or not person["name"]:
        return False

    # birth sub-object
    birth = person["birth"]
    if not isinstance(birth, dict):
        return False
    for bk in ["date", "time", "lat", "lon", "gender"]:
        if bk not in birth:
            return False
    if not isinstance(birth["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", birth["date"]):
        return False
    if not isinstance(birth["time"], str) or not re.fullmatch(r"\d{2}:\d{2}", birth["time"]):
        return False
    if not is_number(birth["lat"]) or not is_number(birth["lon"]):
        return False
    if birth["gender"] not in ("male", "female"):
        return False

    # pillars
    pillars = person["pillars"]
    if not isinstance(pillars, dict):
        return False
    for pos in ["year", "month", "day", "hour"]:
        if pos not in pillars or not isinstance(pillars[pos], dict):
            return False
        p = pillars[pos]
        if "stem" not in p or "branch" not in p or "hidden_stems" not in p:
            return False
        if not isinstance(p["stem"], str) or not p["stem"]:
            return False
        if not isinstance(p["branch"], str) or not p["branch"]:
            return False
        if not isinstance(p["hidden_stems"], list):
            return False
        for hs in p["hidden_stems"]:
            if not isinstance(hs, str):
                return False

    # day_master equals day stem
    if not isinstance(person["day_master"], str):
        return False
    if person["day_master"] != pillars["day"]["stem"]:
        return False

    # five elements
    fe = person["five_elements"]
    if not isinstance(fe, dict):
        return False
    for elem in ["wood", "fire", "earth", "metal", "water"]:
        if elem not in fe:
            return False
        e = fe[elem]
        if not isinstance(e, dict):
            return False
        if "score" not in e or "percent" not in e:
            return False
        if not is_number(e["score"]):
            return False
        if not percent_str_ok(e["percent"]):
            return False

    # major luck
    ml = person["major_luck"]
    if not isinstance(ml, dict):
        return False
    if "start_age" not in ml or "direction" not in ml or "periods" not in ml:
        return False
    if not is_number(ml["start_age"]):
        return False
    if not isinstance(ml["direction"], str) or not ml["direction"]:
        return False
    if not isinstance(ml["periods"], list) or len(ml["periods"]) != 8:
        return False
    for per in ml["periods"]:
        if not isinstance(per, dict):
            return False
        for pk in ["age", "years", "stem", "branch"]:
            if pk not in per:
                return False
        if not validate_age_str(per["age"]):
            return False
        if not validate_years_str(per["years"]):
            return False
        if not isinstance(per["stem"], str) or not per["stem"]:
            return False
        if not isinstance(per["branch"], str) or not per["branch"]:
            return False

    # relationships
    rel = person["relationships"]
    if not isinstance(rel, list):
        return False
    for r in rel:
        if not isinstance(r, dict):
            return False
        if "type" not in r or "positions" not in r or "result" not in r:
            return False
        if not isinstance(r["type"], str):
            return False
        if not isinstance(r["result"], str):
            return False
        if not isinstance(r["positions"], list):
            return False
        for pos in r["positions"]:
            if not isinstance(pos, str):
                return False

    return True

def parse_csv_with_header(path):
    try:
        rows = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(row)
        return rows
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "charts_json_exists": False,
        "charts_has_3_entries": False,
        "charts_people_match_input": False,
        "charts_schema_valid": False,
        "charts_five_elements_format": False,  # subset already in schema; will mirror schema result
        "charts_major_luck_format": False,     # subset already in schema; will mirror schema result
        "charts_relationships_format": False,  # subset already in schema; will mirror schema result
        "consistency_csv_matches_charts": False,
        "report_md_exists": False,
        "report_mentions_name_and_day_master": False,
    }

    charts_path = os.path.join(output_dir, "charts.json")
    csv_path = os.path.join(output_dir, "consistency.csv")
    report_path = os.path.join(output_dir, "report.md")
    input_people_path = os.path.join(input_dir, "people.json")

    charts = None
    if os.path.isfile(charts_path):
        charts = read_json_file(charts_path)
        if isinstance(charts, list):
            checks["charts_json_exists"] = True

    # charts must exist and have length 3
    if checks["charts_json_exists"] and len(charts) == 3:
        checks["charts_has_3_entries"] = True

    # Validate schema and extract convenience mappings
    name_to_person = {}
    if checks["charts_has_3_entries"]:
        schema_ok = True
        fe_ok = True
        ml_ok = True
        rel_ok = True
        for person in charts:
            if not isinstance(person, dict):
                schema_ok = False
                break
            if not validate_person_schema(person):
                schema_ok = False
                break
            # The following mirrors sub-checks if schema is valid per person
            # Major luck and five elements and relationships were validated as part of schema
            # Mark them true if all persons pass
            name_to_person[person["name"]] = person

        if schema_ok:
            checks["charts_schema_valid"] = True
            checks["charts_five_elements_format"] = True
            checks["charts_major_luck_format"] = True
            checks["charts_relationships_format"] = True

    # Compare with input people.json for coverage and birth field matching
    input_people = read_json_file(input_people_path)
    if isinstance(input_people, list) and len(input_people) == 3 and checks["charts_has_3_entries"]:
        # Build sets for comparison
        match_all = True
        input_names = set()
        for rec in input_people:
            # Expect fields: name, date, time, lat, lon, gender
            if not isinstance(rec, dict):
                match_all = False
                break
            required = ["name", "date", "time", "lat", "lon", "gender"]
            if any(k not in rec for k in required):
                match_all = False
                break
            input_names.add(rec["name"])
            out = name_to_person.get(rec["name"])
            if not out:
                match_all = False
                break
            birth = out["birth"]
            # Require exact match for primary birth fields
            # date and time strings, lat/lon numbers, gender
            if birth["date"] != rec["date"]:
                match_all = False
                break
            if birth["time"] != rec["time"]:
                match_all = False
                break
            # For numbers, allow exact numeric equality
            if not is_number(rec["lat"]) or not is_number(rec["lon"]):
                match_all = False
                break
            if float(birth["lat"]) != float(rec["lat"]) or float(birth["lon"]) != float(rec["lon"]):
                match_all = False
                break
            if birth["gender"] != rec["gender"]:
                match_all = False
                break

        # Also ensure charts contain exactly these names (no extras)
        if match_all:
            charts_names = set(name_to_person.keys())
            if charts_names != input_names:
                match_all = False

        if match_all:
            checks["charts_people_match_input"] = True

    # Validate consistency.csv
    if os.path.isfile(csv_path) and checks["charts_schema_valid"]:
        rows = parse_csv_with_header(csv_path)
        if rows is not None and len(rows) >= 2:
            # Remove empty trailing rows
            cleaned = [r for r in rows if any(cell.strip() for cell in r)]
            if cleaned:
                header = cleaned[0]
                data_rows = cleaned[1:]
                # Expect header exactly
                if header == ["name", "day_master", "month_branch"] and len(data_rows) == 3:
                    # Build map from charts for lookup
                    ok = True
                    seen_names = set()
                    for row in data_rows:
                        if len(row) != 3:
                            ok = False
                            break
                        nm, dm, mb = row[0], row[1], row[2]
                        if nm not in name_to_person:
                            ok = False
                            break
                        person = name_to_person[nm]
                        if person["day_master"] != dm:
                            ok = False
                            break
                        if person["pillars"]["month"]["branch"] != mb:
                            ok = False
                            break
                        if nm in seen_names:
                            ok = False
                            break
                        seen_names.add(nm)
                    if ok and len(seen_names) == 3:
                        checks["consistency_csv_matches_charts"] = True

    # Validate report.md existence
    report_text = None
    if os.path.isfile(report_path):
        report_text = read_text_file(report_path)
        if isinstance(report_text, str):
            checks["report_md_exists"] = True

    # Validate report mentions each person's name and day master at least once
    if checks["report_md_exists"] and checks["charts_schema_valid"]:
        all_mentioned = True
        for person in charts:
            nm = person["name"]
            dm = person["day_master"]
            if (nm not in report_text) or (dm not in report_text):
                all_mentioned = False
                break
        if all_mentioned:
            checks["report_mentions_name_and_day_master"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no outputs at all, reward must be 0.0
    outputs_present = any(os.path.exists(os.path.join(output_dir, f)) for f in ["charts.json", "consistency.csv", "report.md"])
    if not outputs_present:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()