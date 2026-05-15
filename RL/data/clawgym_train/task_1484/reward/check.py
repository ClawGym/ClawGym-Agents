import csv
import json
import math
import os
import sys
from typing import Dict, Tuple

def canonical_method(s: str) -> str:
    if s is None:
        return ""
    t = s.strip().lower().replace("-", " ").replace("_", " ")
    t = " ".join(t.split())
    if "bray" in t:
        return "Bray"
    if "olsen" in t:
        return "Olsen"
    if "mehlich" in t and "3" in t:
        return "Mehlich 3"
    return s.strip()

def compute_category(method: str, pppm: float) -> str:
    m = canonical_method(method)
    v = pppm
    if m == "Bray":
        if v < 5:
            return "Very Low"
        if 5 <= v <= 15:
            return "Low"
        if 16 <= v <= 25:
            return "Medium"
        if 26 <= v <= 50:
            return "High"
        if v > 50:
            return "Very High"
    elif m == "Olsen":
        if v < 3:
            return "Very Low"
        if 3 <= v <= 7:
            return "Low"
        if 8 <= v <= 14:
            return "Medium"
        if 15 <= v <= 25:
            return "High"
        if v > 25:
            return "Very High"
    elif m == "Mehlich 3":
        if v < 12:
            return "Very Low"
        if 12 <= v <= 20:
            return "Low"
        if 21 <= v <= 30:
            return "Medium"
        if 31 <= v <= 50:
            return "High"
        if v > 50:
            return "Very High"
    return ""

def action_for_category(cat: str) -> str:
    mapping = {
        "Very Low": "Heavy P needed",
        "Low": "Build P level",
        "Medium": "Maintenance",
        "High": "Reduce/skip P",
        "Very High": "No P needed",
    }
    return mapping.get(cat, "")

def crop_key(name: str) -> str:
    if name is None:
        return ""
    n = name.strip().lower()
    n = " ".join(n.split())
    # Normalize some simple synonyms
    synonyms = {
        "corn": "corn (grain)",
        "corn grain": "corn (grain)",
        "maize": "corn (grain)",
        "maize grain": "corn (grain)",
        "soybeans": "soybean",
        "alfalfa": "alfalfa hay",
        "silage corn": "corn silage",
    }
    return synonyms.get(n, n)

def removal_rate_for_crop(name: str) -> Tuple[bool, float]:
    key = crop_key(name)
    rates = {
        "corn (grain)": 0.37,
        "soybean": 0.75,
        "wheat": 0.50,
        "alfalfa hay": 12.0,
        "corn silage": 3.5,
        "potato": 0.18,
    }
    if key in rates:
        return True, rates[key]
    return False, 0.0

def safe_float(x):
    try:
        return float(x)
    except:
        return None

def approx_equal(a: float, b: float, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except:
        return False

def format_two_decimals(x: float) -> str:
    try:
        return f"{float(x):.2f}"
    except:
        return ""

def read_csv_dict(path: str) -> Tuple[bool, list, list]:
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
        return True, headers, rows
    except Exception:
        return False, [], []

def get_required_input_fields(headers: list) -> Dict[str, str]:
    # Map input headers case-insensitively to required names
    name_map = {}
    lower_map = {h.lower(): h for h in headers}
    for need in ["FieldID", "SoilTestMethod", "SoilTestP_ppm", "PlannedCrop", "ExpectedYield"]:
        h = lower_map.get(need.lower())
        if h is None:
            # try some alternates
            if need.lower() == "soiltestp_ppm":
                for alt in ["soil_test_p_ppm", "soiltestp", "soil_p_ppm"]:
                    if alt in lower_map:
                        h = lower_map[alt]
                        break
            if need.lower() == "expectedyield":
                for alt in ["expected_yield", "yield", "target_yield"]:
                    if alt in lower_map:
                        h = lower_map[alt]
                        break
        if h:
            name_map[need] = h
    return name_map

def last_nonempty_line_print(obj: dict):
    # Ensure the last printed non-empty line is the JSON
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "recommendations_exists": False,
        "recommendations_header_correct": False,
        "rows_match_input_count_and_ids": False,
        "values_match_input": False,
        "categories_correct": False,
        "actions_correct": False,
        "removal_rate_correct": False,
        "maintenance_calc_correct": False,
        "notes_nonempty": False,
        "summary_exists": False,
        "summary_structure_correct": False,
        "summary_categories_match_csv": False,
        "summary_total_maintenance_matches": False,
    }

    # Paths
    input_fields_path = os.path.join(input_dir, "fields.csv")
    rec_path = os.path.join(output_dir, "recommendations.csv")
    summary_path = os.path.join(output_dir, "summary.json")

    # Load input
    input_ok, input_headers, input_rows = read_csv_dict(input_fields_path)

    # Load output recommendations
    rec_ok, rec_headers, rec_rows = read_csv_dict(rec_path)
    if rec_ok:
        checks["recommendations_exists"] = True

    expected_headers = [
        "FieldID",
        "SoilTestMethod",
        "SoilTestP_ppm",
        "Category",
        "Action",
        "PlannedCrop",
        "ExpectedYield",
        "RemovalRate_P2O5_lb_per_unit",
        "Maintenance_P2O5_lb_acre",
        "Notes",
    ]
    if checks["recommendations_exists"]:
        if rec_headers == expected_headers:
            checks["recommendations_header_correct"] = True

    # Prepare input index by FieldID
    input_index: Dict[str, dict] = {}
    if input_ok:
        in_field_map = get_required_input_fields(input_headers)
        if all(k in in_field_map for k in ["FieldID", "SoilTestMethod", "SoilTestP_ppm", "PlannedCrop", "ExpectedYield"]):
            for r in input_rows:
                fid = (r.get(in_field_map["FieldID"], "") or "").strip()
                if fid:
                    input_index[fid] = r

    # Compare row counts and IDs
    if rec_ok and input_ok and input_index:
        rec_ids = [ (row.get("FieldID","") or "").strip() for row in rec_rows ]
        input_ids = list(input_index.keys())
        if len(rec_ids) == len(input_ids) and set(rec_ids) == set(input_ids):
            checks["rows_match_input_count_and_ids"] = True

    # Verify values match input for key columns
    if checks["rows_match_input_count_and_ids"]:
        values_match = True
        in_map = get_required_input_fields(input_headers)
        for row in rec_rows:
            fid = (row.get("FieldID","") or "").strip()
            in_row = input_index.get(fid, {})
            # Compare SoilTestMethod (normalized)
            out_method = canonical_method(row.get("SoilTestMethod","") or "")
            in_method = canonical_method(in_row.get(in_map["SoilTestMethod"], "") if in_row else "")
            if out_method != in_method:
                values_match = False
                break
            # Compare SoilTestP_ppm numeric
            out_ppm = safe_float(row.get("SoilTestP_ppm"))
            in_ppm = safe_float(in_row.get(in_map["SoilTestP_ppm"], "") if in_row else None)
            if out_ppm is None or in_ppm is None or not approx_equal(out_ppm, in_ppm, tol=0.001):
                values_match = False
                break
            # PlannedCrop (case-insensitive)
            out_crop = (row.get("PlannedCrop","") or "").strip().lower()
            in_crop = ((in_row.get(in_map["PlannedCrop"], "") if in_row else "") or "").strip().lower()
            if out_crop != in_crop:
                values_match = False
                break
            # ExpectedYield numeric
            out_y = safe_float(row.get("ExpectedYield"))
            in_y = safe_float(in_row.get(in_map["ExpectedYield"], "") if in_row else None)
            if out_y is None or in_y is None or not approx_equal(out_y, in_y, tol=0.001):
                values_match = False
                break
        if values_match:
            checks["values_match_input"] = True

    # Validate categories and actions, removal rates, maintenance, notes
    if rec_ok:
        cats_ok = True
        acts_ok = True
        rates_ok = True
        maint_ok = True
        notes_ok = True
        for row in rec_rows:
            method = row.get("SoilTestMethod", "")
            pppm = safe_float(row.get("SoilTestP_ppm"))
            category = row.get("Category", "")
            action = row.get("Action", "")
            crop = row.get("PlannedCrop", "")
            expected_yield = safe_float(row.get("ExpectedYield"))
            rr = safe_float(row.get("RemovalRate_P2O5_lb_per_unit"))
            maint = safe_float(row.get("Maintenance_P2O5_lb_acre"))
            notes = (row.get("Notes","") or "").strip()

            # Validate category
            if pppm is None:
                cats_ok = False
                break
            expected_cat = compute_category(method, pppm)
            if category != expected_cat:
                cats_ok = False
            # Validate action
            expected_act = action_for_category(expected_cat)
            if action != expected_act:
                acts_ok = False
            # Validate removal rate for crop
            ok_rate, expected_rr = removal_rate_for_crop(crop)
            if not ok_rate or rr is None or not approx_equal(rr, expected_rr, tol=1e-6):
                rates_ok = False
            # Validate maintenance calculation with rounding
            if expected_yield is None or maint is None:
                maint_ok = False
            else:
                expected_maint = expected_yield * expected_rr if ok_rate and expected_yield is not None else None
                if expected_maint is None or not approx_equal(maint, expected_maint, tol=0.01):
                    maint_ok = False
            # Validate notes non-empty (brief phrase)
            if not notes:
                notes_ok = False

        if cats_ok:
            checks["categories_correct"] = True
        if acts_ok:
            checks["actions_correct"] = True
        if rates_ok:
            checks["removal_rate_correct"] = True
        if maint_ok:
            checks["maintenance_calc_correct"] = True
        if notes_ok:
            checks["notes_nonempty"] = True

    # Load summary
    summary_ok = False
    summary_data = None
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
            summary_ok = True
        except Exception:
            summary_ok = False
    if summary_ok:
        checks["summary_exists"] = True

    # Summary structure check
    if checks["summary_exists"]:
        sd = summary_data
        struct_ok = True
        # Keys
        if not isinstance(sd, dict):
            struct_ok = False
        else:
            required_keys = {"total_fields", "categories", "total_maintenance_P2O5"}
            if set(sd.keys()) != required_keys:
                struct_ok = False
            else:
                if not isinstance(sd["total_fields"], int):
                    struct_ok = False
                if not isinstance(sd["categories"], dict):
                    struct_ok = False
                else:
                    cat_keys = {"Very Low", "Low", "Medium", "High", "Very High"}
                    if set(sd["categories"].keys()) != cat_keys:
                        struct_ok = False
                    else:
                        for k, v in sd["categories"].items():
                            if not isinstance(v, int):
                                struct_ok = False
                                break
                # total_maintenance_P2O5 numeric
                if not isinstance(sd["total_maintenance_P2O5"], (int, float)):
                    struct_ok = False
        if struct_ok:
            checks["summary_structure_correct"] = True

    # Summary vs CSV consistency checks
    if checks["summary_structure_correct"] and rec_ok:
        # Category counts from CSV
        csv_cat_counts: Dict[str, int] = {"Very Low":0, "Low":0, "Medium":0, "High":0, "Very High":0}
        for row in rec_rows:
            c = row.get("Category", "")
            if c in csv_cat_counts:
                csv_cat_counts[c] += 1
        cats_match = True
        for k in csv_cat_counts:
            if summary_data["categories"].get(k, None) != csv_cat_counts[k]:
                cats_match = False
                break
        if cats_match:
            checks["summary_categories_match_csv"] = True

        # Total fields check equals number of CSV rows
        total_fields_match = (summary_data.get("total_fields") == len(rec_rows))
        # Sum maintenance from CSV
        sum_maint_csv = 0.0
        valid_sum = True
        for row in rec_rows:
            m = safe_float(row.get("Maintenance_P2O5_lb_acre"))
            if m is None:
                valid_sum = False
                break
            sum_maint_csv += m
        if valid_sum and approx_equal(summary_data.get("total_maintenance_P2O5"), sum_maint_csv, tol=0.01) and total_fields_match:
            checks["summary_total_maintenance_matches"] = True

    # Compute reward: fraction of passed checks, but ensure zero if core artifact missing
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["recommendations_exists"] else 0.0
    # If no summary exists, still compute fraction but recommendations_exists gating already set baseline semantics.
    # Ensure 0.0 if outputs are empty or missing required artifacts
    if not checks["recommendations_exists"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    last_nonempty_line_print(result)

if __name__ == "__main__":
    main()