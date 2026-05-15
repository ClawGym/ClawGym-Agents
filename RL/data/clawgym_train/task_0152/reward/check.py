import json
import os
import sys
import re
import csv

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_csv_expected(csv_path):
    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Normalize fields
                name = (r.get("name") or "").strip()
                row = {
                    "type": (r.get("type") or "").strip(),
                    "name": name,
                    "plants_raw": r.get("plants") or "",
                    "plants": [p.strip() for p in (r.get("plants") or "").split(",") if p.strip() != ""],
                    "severity": (r.get("severity") or "").strip(),
                    "notes": (r.get("notes") or "").strip(),
                    "treat_method": (r.get("treat_method") or "").strip(),
                    "treat_product": (r.get("treat_product") or "").strip(),
                    "treat_status": (r.get("treat_status") or "").strip(),
                }
                rows.append(row)
        return rows, None
    except Exception as e:
        return None, str(e)

def normalize_plants_list(plants):
    # plants might be list of strings or any; ensure normalized trimmed list of strings
    out = []
    if isinstance(plants, list):
        for p in plants:
            if isinstance(p, str):
                s = p.strip()
                if s != "":
                    out.append(s)
    elif isinstance(plants, str):
        # if someone mistakenly put string, split by comma
        out = [p.strip() for p in plants.split(",") if p.strip() != ""]
    return out

def join_plants(plants_list):
    # join with commas, no spaces to compare consistently; use normalization first
    return ",".join(normalize_plants_list(plants_list))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected mapping of top 2 recommended products for known problems
    # These must match exactly the strings from the tool's built-in database and task rubric.
    top2_map = {
        "aphids": ["neem oil", "insecticidal soap"],
        "slugs": ["beer traps", "diatomaceous earth"],
        "powdery mildew": ["sulfur fungicide", "neem oil"],
        "early blight": ["copper fungicide", "remove affected leaves"],
        "spider mites": ["neem oil", "insecticidal soap"],
        "caterpillars": ["Bacillus thuringiensis (Bt)", "neem oil"],
    }

    expected_names_set = set(top2_map.keys())

    checks = {
        "json_exists": False,
        "json_valid": False,
        "problems_key_ok": False,
        "problems_count_ok": False,
        "json_names_match_input": False,
        "ids_pattern_ok": False,
        "all_problem_entries_valid": False,
        "recs_ok": False,
        "tsv_exists": False,
        "tsv_header_ok": False,
        "tsv_rows_count_ok": False,
        "tsv_matches_json": False,
    }

    # Paths
    json_path = os.path.join(output_dir, "garden_health_report.json")
    tsv_path = os.path.join(output_dir, "problem_index.tsv")
    csv_path = os.path.join(input_dir, "observations.csv")

    # Read input CSV as reference
    expected_rows, csv_err = read_csv_expected(csv_path)
    if expected_rows is None:
        expected_rows = []
    # Build expected set from CSV
    csv_names_set = set([r["name"].strip().lower() for r in expected_rows if r.get("name")])
    # If CSV has the six expected names, it should match expected_names_set; otherwise we still proceed.

    # Load JSON
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        data, json_err = load_json(json_path)
        if isinstance(data, dict):
            checks["json_valid"] = True
            if "problems" in data and isinstance(data["problems"], list):
                checks["problems_key_ok"] = True
                problems = data["problems"]
                # Determine expected count: prefer CSV count if available else fall back to 6 from rubric
                expected_count = len(expected_rows) if expected_rows else 6
                if len(problems) == expected_count:
                    checks["problems_count_ok"] = True

                # Validate names set matches CSV (if CSV available) and expected rubric set
                json_names = [p.get("name") for p in problems if isinstance(p, dict)]
                json_names_set = set([str(n).strip().lower() for n in json_names if n is not None])

                names_match_input = False
                if expected_rows:
                    names_match_input = json_names_set == csv_names_set
                else:
                    # If CSV not available, compare with rubric set
                    names_match_input = json_names_set == expected_names_set
                checks["json_names_match_input"] = names_match_input

                # Build helper index for expected rows by name (lower)
                exp_by_name = {r["name"].strip().lower(): r for r in expected_rows}

                # Validate each problem entry deeply
                ids_ok = True
                entries_ok = True
                recs_ok = True
                id_regex = re.compile(r"^(pest|disease)_([a-z_]+)_(\d{14})$")
                for p in problems:
                    if not isinstance(p, dict):
                        entries_ok = False
                        ids_ok = False
                        recs_ok = False
                        break
                    pid = p.get("id")
                    ptype = p.get("type")
                    pname = p.get("name")
                    pplants = p.get("plants")
                    pseverity = p.get("severity")
                    precs = p.get("recommendations")
                    ptreatments = p.get("treatments")

                    # id pattern check
                    if not isinstance(pid, str):
                        ids_ok = False
                    else:
                        m = id_regex.match(pid)
                        if not m:
                            ids_ok = False
                        else:
                            # Ensure name portion equals problem name lower underscored
                            base_name = (pname or "").lower().replace(" ", "_")
                            if m.group(2) != base_name:
                                ids_ok = False

                    # Validate against expected row from CSV if present
                    expected_row = None
                    if pname is not None:
                        expected_row = exp_by_name.get(str(pname).strip().lower())

                    # Type
                    if expected_row:
                        if ptype != expected_row["type"]:
                            entries_ok = False

                    # Name
                    if expected_row:
                        if pname != expected_row["name"]:
                            entries_ok = False

                    # Plants
                    if expected_row:
                        expected_plants = expected_row["plants"]
                        json_plants = normalize_plants_list(pplants)
                        if json_plants != expected_plants:
                            entries_ok = False

                    # Severity
                    if expected_row:
                        if pseverity != expected_row["severity"]:
                            entries_ok = False

                    # Treatments
                    # Must be an array length 1 with method, product, and optional status
                    if not isinstance(ptreatments, list) or len(ptreatments) != 1 or not isinstance(ptreatments[0], dict):
                        entries_ok = False
                    else:
                        t0 = ptreatments[0]
                        method = t0.get("method")
                        product = t0.get("product")
                        status_val = t0.get("status") if "status" in t0 else None

                        if expected_row:
                            if method != expected_row["treat_method"]:
                                entries_ok = False
                            # product: if CSV has non-blank, must equal that; otherwise equals first recommended
                            exp_prod_csv = (expected_row["treat_product"] or "").strip()
                            if exp_prod_csv:
                                if product != exp_prod_csv:
                                    entries_ok = False
                            else:
                                # Need top1 from recommendations by problem name
                                key = str(pname).strip().lower()
                                top2 = top2_map.get(key)
                                if not top2:
                                    entries_ok = False
                                else:
                                    if product != top2[0]:
                                        entries_ok = False
                            # status: if CSV treat_status provided, must exist and equal; else may be absent or empty
                            exp_status = (expected_row["treat_status"] or "").strip()
                            if exp_status:
                                if "status" not in t0 or t0.get("status") != exp_status:
                                    entries_ok = False
                            else:
                                # if status present but non-empty, that's okay? Spec says omit or empty allowed.
                                if "status" in t0 and isinstance(t0.get("status"), str) and t0.get("status").strip() != "":
                                    # If CSV blank but status non-empty, fail
                                    entries_ok = False

                    # Recommendations top two
                    key = (pname or "").strip().lower()
                    expected_top2 = top2_map.get(key)
                    # Must exist and equal expected list of length 2
                    if not isinstance(precs, dict) or "top_products" not in precs or not isinstance(precs["top_products"], list):
                        recs_ok = False
                    else:
                        tops = precs["top_products"]
                        if expected_top2 is None or len(tops) != 2 or tops != expected_top2:
                            recs_ok = False

                checks["ids_pattern_ok"] = ids_ok
                checks["all_problem_entries_valid"] = entries_ok
                checks["recs_ok"] = recs_ok

    # TSV checks
    if os.path.isfile(tsv_path):
        checks["tsv_exists"] = True
        try:
            with open(tsv_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
            if lines:
                header = lines[0]
                if header == "id\ttype\tname\tplants\tseverity":
                    checks["tsv_header_ok"] = True
                data_lines = lines[1:] if len(lines) > 1 else []
                # Expected count same as JSON problems if available, else CSV count
                expected_count = None
                json_data = None
                if checks["json_valid"] and checks.get("problems_key_ok", False):
                    with open(json_path, "r", encoding="utf-8") as jf:
                        json_data = json.load(jf)
                    if isinstance(json_data, dict) and isinstance(json_data.get("problems"), list):
                        expected_count = len(json_data["problems"])
                if expected_count is None:
                    expected_count = len(expected_rows)
                # If nothing to compare, keep strict to 6 per spec
                if expected_count == 0:
                    expected_count = 6
                if len(data_lines) == expected_count:
                    checks["tsv_rows_count_ok"] = True

                # Validate each row matches JSON entries
                matches_json = False
                if json_data and isinstance(json_data.get("problems"), list):
                    problems = json_data["problems"]
                    by_id = {}
                    for p in problems:
                        if isinstance(p, dict) and isinstance(p.get("id"), str):
                            by_id[p["id"]] = p
                    # Parse TSV rows and verify against JSON
                    ok = True
                    seen_ids = set()
                    for dl in data_lines:
                        cols = dl.split("\t")
                        if len(cols) != 5:
                            ok = False
                            break
                        rid, rtype, rname, rplants_str, rseverity = cols
                        if rid not in by_id:
                            ok = False
                            break
                        jp = by_id[rid]
                        # type
                        if jp.get("type") != rtype:
                            ok = False
                            break
                        # name
                        if jp.get("name") != rname:
                            ok = False
                            break
                        # plants: compare normalized arrays
                        jp_plants = normalize_plants_list(jp.get("plants"))
                        tsv_plants = [p.strip() for p in rplants_str.split(",") if p.strip() != ""]
                        if jp_plants != tsv_plants:
                            ok = False
                            break
                        # severity
                        if jp.get("severity") != rseverity:
                            ok = False
                            break
                        seen_ids.add(rid)
                    # Ensure all JSON problems are represented exactly once
                    if ok:
                        if len(seen_ids) != len(problems):
                            ok = False
                    matches_json = ok
                checks["tsv_matches_json"] = matches_json
        except Exception:
            pass

    # Compute reward as proportion of checks passed, but ensure baseline 0 when outputs missing
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Ensure no-op baseline: if both output files are missing or empty, reward = 0.0
    outputs_present = checks["json_exists"] or checks["tsv_exists"]
    if not outputs_present:
        reward = 0.0
    else:
        # Only grant reward based on checks that depend on outputs
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()