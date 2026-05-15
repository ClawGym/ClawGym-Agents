import json
import os
import sys
import csv
import re

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def approx_equal(value, target, tol_abs=None, tol_pct=None):
    try:
        v = float(value)
        t = float(target)
    except (TypeError, ValueError):
        return False
    if tol_abs is not None:
        return abs(v - t) <= tol_abs
    if tol_pct is not None:
        if t == 0:
            return abs(v - t) <= 1e-6
        return abs(v - t) <= abs(t) * tol_pct
    # default: exact
    return v == t

def parse_float_maybe(s):
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        # remove thousands separators and spaces
        s2 = s.replace(",", "").strip()
        try:
            return float(s2)
        except ValueError:
            return None
    return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def read_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return True, reader.fieldnames, rows
    except Exception:
        return False, None, []

def compute_rating_from_benchmarks(carbon_per_area, bench):
    # Follow the skill's logic
    best = bench.get("best_benchmark")
    good = bench.get("good_benchmark")
    typical = bench.get("typical_benchmark")
    if best is None or good is None or typical is None:
        # fallback Residential benchmarks
        best = 150
        good = 280
        typical = 400
    c = carbon_per_area
    try:
        c = float(c)
    except Exception:
        return None
    try:
        best = float(best); good = float(good); typical = float(typical)
    except Exception:
        best, good, typical = 150.0, 280.0, 400.0
    if c <= best:
        return "A (Best Practice)"
    elif c <= good:
        return "B (Good Practice)"
    elif c <= typical:
        return "C (Typical)"
    else:
        return "D (Above Typical)"

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        # Existence checks
        "base_json_exists": False,
        "alternatives_csv_exists": False,
        "report_lowest_exists": False,
        "reductions_json_exists": False,

        # base_project.json checks
        "base_json_valid": False,
        "base_total_ok": False,
        "base_intensity_ok": False,
        "base_stages_keys_ok": False,
        "base_stage_a1_a3_ok": False,
        "base_stage_a4_ok": False,
        "base_stage_a5_ok": False,
        "base_stage_b_ok": False,
        "base_stage_c_ok": False,
        "base_stage_d_ok": False,
        "base_benchmark_rating_ok": False,

        # alternatives.csv checks
        "alternatives_columns_ok": False,
        "alternatives_rows_ok": False,
        "alternatives_base_intensity_ok": False,
        "alternatives_lc_concrete_intensity_ok": False,
        "alternatives_timber_intensity_ok": False,
        "alternatives_lowest_timber_ok": False,
        "alternatives_vs_base_negative_ok": False,

        # report_lowest.md checks
        "report_lowest_contains_title_ok": False,
        "report_lowest_contains_option_ok": False,
        "report_lowest_contains_intensity_ok": False,

        # reductions_base.json checks
        "reductions_valid_json": False,
        "reductions_has_items": False,
        "reductions_concrete_suggestion_ok": False,
    }

    # Required output files
    base_json_path = os.path.join(output_dir, "base_project.json")
    alts_csv_path = os.path.join(output_dir, "alternatives.csv")
    report_md_path = os.path.join(output_dir, "report_lowest.md")
    reductions_json_path = os.path.join(output_dir, "reductions_base.json")

    # Existence
    if os.path.isfile(base_json_path):
        checks["base_json_exists"] = True
    if os.path.isfile(alts_csv_path):
        checks["alternatives_csv_exists"] = True
    if os.path.isfile(report_md_path):
        checks["report_lowest_exists"] = True
    if os.path.isfile(reductions_json_path):
        checks["reductions_json_exists"] = True

    # If any required artifact missing, reward must be 0.0 (no partial credit)
    all_required_exist = all([
        checks["base_json_exists"],
        checks["alternatives_csv_exists"],
        checks["report_lowest_exists"],
        checks["reductions_json_exists"],
    ])

    base_obj = None
    if checks["base_json_exists"]:
        ok, obj = read_json_file(base_json_path)
        if ok and isinstance(obj, dict):
            checks["base_json_valid"] = True
            base_obj = obj

            # Base totals
            total_ec = obj.get("total_embodied_carbon")
            if total_ec is not None and approx_equal(total_ec, 855156.25, tol_pct=0.01):
                checks["base_total_ok"] = True

            cpa = obj.get("carbon_per_area")
            if cpa is not None and approx_equal(cpa, 178.16, tol_abs=0.5):
                checks["base_intensity_ok"] = True

            # carbon_by_stage keys and values
            expected_stage_labels = [
                "Product Stage (A1-A3)",
                "Transport to Site (A4)",
                "Construction (A5)",
                "Use Stage (B1-B7)",
                "End of Life (C1-C4)",
                "Beyond Lifecycle (D)",
            ]
            cbs = obj.get("carbon_by_stage")
            if isinstance(cbs, dict) and all(k in cbs for k in expected_stage_labels):
                checks["base_stages_keys_ok"] = True
                # Check approximate values ±1% (except B stage which should be near 0)
                if approx_equal(cbs.get("Product Stage (A1-A3)"), 1032950.0, tol_pct=0.01):
                    checks["base_stage_a1_a3_ok"] = True
                if approx_equal(cbs.get("Transport to Site (A4)"), 22962.5, tol_pct=0.01):
                    checks["base_stage_a4_ok"] = True
                if approx_equal(cbs.get("Construction (A5)"), 11081.25, tol_pct=0.01):
                    checks["base_stage_a5_ok"] = True
                # Use Stage expected 0.0
                b_val = cbs.get("Use Stage (B1-B7)")
                try:
                    b_val_f = float(b_val)
                    if abs(b_val_f - 0.0) <= 1e-6:
                        checks["base_stage_b_ok"] = True
                except Exception:
                    pass
                if approx_equal(cbs.get("End of Life (C1-C4)"), 31062.5, tol_pct=0.01):
                    checks["base_stage_c_ok"] = True
                d_val = cbs.get("Beyond Lifecycle (D)")
                try:
                    d_val_f = float(d_val)
                    if d_val_f < 0 and approx_equal(d_val_f, -242900.0, tol_pct=0.01):
                        checks["base_stage_d_ok"] = True
                except Exception:
                    pass

            # benchmark rating check
            bc = obj.get("benchmark_comparison", {})
            if isinstance(bc, dict) and "rating" in bc and ("carbon_per_area" in bc or cpa is not None):
                reported_rating = bc.get("rating")
                cpa_for_rating = bc.get("carbon_per_area", cpa)
                # try to compute rating based on provided benchmarks if present
                computed = compute_rating_from_benchmarks(cpa_for_rating, bc)
                if reported_rating == "B (Good Practice)" or (computed is not None and reported_rating == computed):
                    checks["base_benchmark_rating_ok"] = True

    # alternatives.csv validation
    alts_rows = []
    alts_fieldnames = []
    if checks["alternatives_csv_exists"]:
        ok, fieldnames, rows = read_csv_dicts(alts_csv_path)
        if ok and fieldnames is not None:
            alts_fieldnames = fieldnames
            expected_cols = ["Option", "Total Carbon (tCO2e)", "Carbon/m² (kgCO2e)", "vs Base", "Rating"]
            if fieldnames == expected_cols:
                checks["alternatives_columns_ok"] = True

            # Expect exactly 3 rows: Base Design, LC Concrete, Timber Floors + Reduced Steel
            options = [r.get("Option", "") for r in rows]
            expected_options = {"Base Design", "LC Concrete", "Timber Floors + Reduced Steel"}
            if len(rows) == 3 and set(options) == expected_options:
                checks["alternatives_rows_ok"] = True

            # Build lookup by option
            by_opt = {r.get("Option", ""): r for r in rows}

            # Base intensity approx 178.16 ±0.5
            if "Base Design" in by_opt:
                base_row = by_opt["Base Design"]
                cpm2 = parse_float_maybe(base_row.get("Carbon/m² (kgCO2e)"))
                if cpm2 is not None and approx_equal(cpm2, 178.16, tol_abs=0.5):
                    checks["alternatives_base_intensity_ok"] = True

            if "LC Concrete" in by_opt:
                lc_row = by_opt["LC Concrete"]
                cpm2 = parse_float_maybe(lc_row.get("Carbon/m² (kgCO2e)"))
                if cpm2 is not None and approx_equal(cpm2, 140.24, tol_abs=0.5):
                    checks["alternatives_lc_concrete_intensity_ok"] = True

            if "Timber Floors + Reduced Steel" in by_opt:
                tim_row = by_opt["Timber Floors + Reduced Steel"]
                cpm2 = parse_float_maybe(tim_row.get("Carbon/m² (kgCO2e)"))
                if cpm2 is not None and approx_equal(cpm2, 103.71, tol_abs=0.5):
                    checks["alternatives_timber_intensity_ok"] = True
                # vs Base negative
                vsb = tim_row.get("vs Base", "")
                if isinstance(vsb, str) and vsb.strip().startswith("-"):
                    checks["alternatives_vs_base_negative_ok"] = True

            # Lowest-carbon option is Timber Floors + Reduced Steel
            # Compute min based on Carbon/m² (kgCO2e)
            try:
                vals = []
                for r in rows:
                    opt = r.get("Option", "")
                    v = parse_float_maybe(r.get("Carbon/m² (kgCO2e)"))
                    if v is not None:
                        vals.append((v, opt))
                if vals:
                    min_opt = sorted(vals, key=lambda x: x[0])[0][1]
                    if min_opt == "Timber Floors + Reduced Steel":
                        checks["alternatives_lowest_timber_ok"] = True
            except Exception:
                pass

    # report_lowest.md validation
    if checks["report_lowest_exists"]:
        ok, text = read_text_file(report_md_path)
        if ok and text:
            # Title must include "Embodied Carbon Assessment Report"
            if "Embodied Carbon Assessment Report" in text:
                checks["report_lowest_contains_title_ok"] = True
            # Must include the option name "Timber Floors + Reduced Steel"
            if "Timber Floors + Reduced Steel" in text:
                checks["report_lowest_contains_option_ok"] = True
            # Must include a line indicating "Carbon Intensity" (case-insensitive)
            if re.search(r"carbon\s+intensity", text, flags=re.IGNORECASE):
                checks["report_lowest_contains_intensity_ok"] = True

    # reductions_base.json validation
    if checks["reductions_json_exists"]:
        ok, arr = read_json_file(reductions_json_path)
        if ok and isinstance(arr, list):
            checks["reductions_valid_json"] = True
            if len(arr) >= 1:
                checks["reductions_has_items"] = True
            # At least one suggestion for Concrete mentioning low-carbon strategy with numeric impact
            concrete_ok = False
            for item in arr if isinstance(arr, list) else []:
                if not isinstance(item, dict):
                    continue
                cat = item.get("category")
                sug = item.get("suggestion") or item.get("Suggestion") or ""
                impact = item.get("impact")
                cat_match = isinstance(cat, str) and cat.lower() == "concrete"
                sug_text = str(sug).lower()
                mentions = ("low-carbon concrete" in sug_text) or ("low carbon concrete" in sug_text) or ("ggbs" in sug_text) or ("pfa" in sug_text)
                impact_num = None
                if isinstance(impact, (int, float)):
                    impact_num = float(impact)
                elif isinstance(impact, str):
                    try:
                        impact_num = float(impact.strip())
                    except Exception:
                        impact_num = None
                if cat_match and mentions and (impact_num is not None):
                    concrete_ok = True
                    break
            if concrete_ok:
                checks["reductions_concrete_suggestion_ok"] = True

    # Compute reward
    # If any required artifact missing -> overall reward must be 0.0
    if not all_required_exist:
        reward = 0.0
    else:
        # Score fraction of passed checks (all checks contribute once all required exist)
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Prepare result JSON (reward first)
    result = {"reward": reward}
    # Keep insertion order of checks
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()