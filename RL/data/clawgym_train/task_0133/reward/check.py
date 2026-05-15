import json
import os
import sys
import csv
import math

def nearly_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None

def parse_int(val):
    if isinstance(val, int):
        return val
    try:
        return int(float(val))
    except Exception:
        return None

def parse_bool(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "t")

def read_csv_dicts(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames if reader.fieldnames is not None else []
        rows = [row for row in reader]
    return header, rows

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def round2(x):
    return round(x, 2)

def safe_sum(vals):
    total = 0.0
    for v in vals:
        if v is None:
            return None
        try:
            total += float(v)
        except Exception:
            return None
    return total

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_detailed_file": False,
        "detailed_header_ok": False,
        "detailed_sorted": False,
        "detailed_costs_consistent": False,
        "detailed_missing_price_flags": False,

        "has_summary_file": False,
        "summary_header_ok": False,
        "summary_groups_match": False,
        "summary_values_match": False,
        "summary_sorted_desc": False,
        "summary_volume_pct_total_ok": False,

        "has_pivot_file": False,
        "pivot_columns_ok": False,
        "pivot_rows_match": False,
        "pivot_values_match": False,
        "pivot_row_totals_ok": False,

        "has_report_file": False,
        "report_keys_ok": False,
        "report_totals_match": False,
        "report_levels_match": False,
        "report_categories_match": False,
    }

    # Paths to expected output files
    detailed_path = os.path.join(output_dir, "detailed_elements.csv")
    summary_path = os.path.join(output_dir, "summary_by_category_material.csv")
    pivot_path = os.path.join(output_dir, "pivot_by_level_category.csv")
    report_path = os.path.join(output_dir, "report.json")

    # Expected header for detailed
    expected_detailed_header = [
        "ElementId", "Category", "Material", "Level",
        "Volume_m3", "Area_m2", "Unit_Price", "Markup_Rate",
        "Base_Cost", "Total_Cost", "Missing_Price"
    ]

    # Read detailed_elements.csv
    detailed_header = []
    detailed_rows = []
    typed_rows = []
    if os.path.isfile(detailed_path):
        checks["has_detailed_file"] = True
        try:
            detailed_header, detailed_rows = read_csv_dicts(detailed_path)
        except Exception:
            detailed_header, detailed_rows = [], []

        if detailed_header == expected_detailed_header:
            checks["detailed_header_ok"] = True

        # Parse and validate rows
        costs_consistent = True
        missing_flags_ok = True
        parse_failed = False

        for row in detailed_rows:
            elem_id = row.get("ElementId", "")
            cat = row.get("Category", "")
            mat = row.get("Material", "")
            lvl = row.get("Level", "")
            vol = parse_float(row.get("Volume_m3"))
            area = parse_float(row.get("Area_m2"))
            unit_price = parse_float(row.get("Unit_Price"))
            markup_rate = parse_float(row.get("Markup_Rate"))
            base_cost = parse_float(row.get("Base_Cost"))
            total_cost = parse_float(row.get("Total_Cost"))
            missing_price = parse_bool(row.get("Missing_Price"))

            if None in (vol, area, unit_price, markup_rate, base_cost, total_cost):
                parse_failed = True

            # Cost checks if parsable
            if not parse_failed:
                calc_base = (vol or 0.0) * (unit_price or 0.0)
                if not nearly_equal(calc_base, base_cost, 0.01):
                    costs_consistent = False
                calc_total = (base_cost or 0.0) * (1.0 + (markup_rate or 0.0))
                if not nearly_equal(calc_total, total_cost, 0.01):
                    costs_consistent = False

                # Missing price flag equivalence
                is_zero_price = abs(unit_price or 0.0) <= 1e-9
                if is_zero_price != bool(missing_price):
                    missing_flags_ok = False

            typed_rows.append({
                "ElementId": str(elem_id),
                "Category": str(cat),
                "Material": str(mat),
                "Level": str(lvl),
                "Volume_m3": vol,
                "Area_m2": area,
                "Unit_Price": unit_price,
                "Markup_Rate": markup_rate,
                "Base_Cost": base_cost,
                "Total_Cost": total_cost,
                "Missing_Price": bool(missing_price),
            })

        if not parse_failed and len(detailed_rows) > 0:
            checks["detailed_costs_consistent"] = costs_consistent
            checks["detailed_missing_price_flags"] = missing_flags_ok
        elif not detailed_rows:
            # If there are no rows, cost and missing price checks are vacuously true
            # but to avoid vacuous passes, keep them False when there are no rows
            pass

        # Sorting check
        if detailed_rows:
            orig_order = [(str(r.get("Level", "")), str(r.get("Category", "")), str(r.get("ElementId", ""))) for r in detailed_rows]
            sorted_rows = sorted(detailed_rows, key=lambda r: (str(r.get("Level", "")), str(r.get("Category", "")), str(r.get("ElementId", ""))))
            sorted_order = [(str(r.get("Level", "")), str(r.get("Category", "")), str(r.get("ElementId", ""))) for r in sorted_rows]
            if orig_order == sorted_order:
                checks["detailed_sorted"] = True
        else:
            # If empty, consider it sorted
            checks["detailed_sorted"] = True

    # Compute expected aggregates from detailed for cross-file checks
    group_expected = {}  # (Category, Material) -> dict with aggregates
    levels_set = set()
    categories_set = set()
    total_volume_all = 0.0
    total_base_cost_all = 0.0
    total_cost_all = 0.0
    missing_price_count = 0

    pivot_expected = {}  # (Level, Category) -> total_cost sum

    if checks["has_detailed_file"] and checks["detailed_header_ok"]:
        for r in typed_rows:
            # Skip rows if any critical numeric fields are None; treat as invalid detailed
            if any(v is None for v in (r["Volume_m3"], r["Area_m2"], r["Unit_Price"], r["Markup_Rate"], r["Base_Cost"], r["Total_Cost"])):
                continue
            cat = r["Category"]
            mat = r["Material"]
            lvl = r["Level"]
            vol = r["Volume_m3"]
            area = r["Area_m2"]
            base_c = r["Base_Cost"]
            tot_c = r["Total_Cost"]

            key = (cat, mat)
            g = group_expected.get(key)
            if g is None:
                g = {
                    "element_count": 0,
                    "total_volume": 0.0,
                    "total_area": 0.0,
                    "base_cost": 0.0,
                    "total_cost": 0.0,
                    "sum_for_avg": 0.0,  # total_volume again for mean
                }
                group_expected[key] = g
            g["element_count"] += 1
            g["total_volume"] += vol
            g["total_area"] += area
            g["base_cost"] += base_c
            g["total_cost"] += tot_c
            g["sum_for_avg"] += vol

            levels_set.add(lvl)
            categories_set.add(cat)

            total_volume_all += vol
            total_base_cost_all += base_c
            total_cost_all += tot_c

            if r["Missing_Price"]:
                missing_price_count += 1

            piv_key = (lvl, cat)
            pivot_expected[piv_key] = pivot_expected.get(piv_key, 0.0) + tot_c

    # SUMMARY CHECKS
    summary_header_expected = ["Category", "Material", "element_count", "total_volume", "total_area", "avg_volume", "base_cost", "total_cost", "volume_pct"]
    summary_rows = []
    summary_groups_in_file = set()
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        try:
            summary_header, summary_rows = read_csv_dicts(summary_path)
        except Exception:
            summary_header, summary_rows = [], []

        if summary_header == summary_header_expected:
            checks["summary_header_ok"] = True

        # Validate groups match and values
        if checks["has_detailed_file"] and checks["detailed_header_ok"]:
            summary_groups_in_file = set()
            values_match = True
            parse_err = False

            # Build a map from (Category, Material) to row values
            summary_map = {}
            for row in summary_rows:
                cat = str(row.get("Category", ""))
                mat = str(row.get("Material", ""))
                key = (cat, mat)
                summary_groups_in_file.add(key)
                try:
                    element_count = parse_int(row.get("element_count"))
                    total_volume = parse_float(row.get("total_volume"))
                    total_area = parse_float(row.get("total_area"))
                    avg_volume = parse_float(row.get("avg_volume"))
                    base_cost = parse_float(row.get("base_cost"))
                    total_cost = parse_float(row.get("total_cost"))
                    volume_pct = parse_float(row.get("volume_pct"))
                except Exception:
                    parse_err = True
                    continue
                if None in (element_count, total_volume, total_area, avg_volume, base_cost, total_cost, volume_pct):
                    parse_err = True
                summary_map[key] = {
                    "element_count": element_count,
                    "total_volume": total_volume,
                    "total_area": total_area,
                    "avg_volume": avg_volume,
                    "base_cost": base_cost,
                    "total_cost": total_cost,
                    "volume_pct": volume_pct,
                }

            if not parse_err:
                # Groups match
                if set(group_expected.keys()) == summary_groups_in_file:
                    checks["summary_groups_match"] = True

                # Compute expected rounded values and compare
                for key, g in group_expected.items():
                    exp_count = g["element_count"]
                    exp_total_volume = round2(g["total_volume"])
                    exp_total_area = round2(g["total_area"])
                    exp_avg_volume = round2((g["sum_for_avg"] / exp_count) if exp_count > 0 else 0.0)
                    exp_base_cost = round2(g["base_cost"])
                    exp_total_cost = round2(g["total_cost"])
                    if total_volume_all > 0:
                        exp_volume_pct = round2((g["total_volume"] / total_volume_all) * 100.0)
                    else:
                        exp_volume_pct = 0.0

                    if key not in summary_map:
                        values_match = False
                        continue
                    row_vals = summary_map[key]
                    if row_vals["element_count"] != exp_count:
                        values_match = False
                    if not nearly_equal(row_vals["total_volume"], exp_total_volume, 0.01):
                        values_match = False
                    if not nearly_equal(row_vals["total_area"], exp_total_area, 0.01):
                        values_match = False
                    if not nearly_equal(row_vals["avg_volume"], exp_avg_volume, 0.01):
                        values_match = False
                    if not nearly_equal(row_vals["base_cost"], exp_base_cost, 0.01):
                        values_match = False
                    if not nearly_equal(row_vals["total_cost"], exp_total_cost, 0.01):
                        values_match = False
                    if not nearly_equal(row_vals["volume_pct"], exp_volume_pct, 0.01):
                        values_match = False

                if values_match and checks["summary_groups_match"]:
                    checks["summary_values_match"] = True

                # Check sorted by total_volume descending
                if summary_rows:
                    totals = []
                    for row in summary_rows:
                        tv = parse_float(row.get("total_volume"))
                        if tv is None:
                            totals = None
                            break
                        totals.append(tv)
                    if totals is not None:
                        sorted_desc = all(totals[i] >= totals[i+1] - 1e-9 for i in range(len(totals)-1))
                        if sorted_desc:
                            checks["summary_sorted_desc"] = True
                else:
                    # empty summary is vacuously sorted
                    checks["summary_sorted_desc"] = True

                # Check volume_pct sums to ~100 (skip if no rows or total volume is zero)
                if summary_rows and total_volume_all > 0:
                    pct_sum = 0.0
                    valid = True
                    for row in summary_rows:
                        vp = parse_float(row.get("volume_pct"))
                        if vp is None:
                            valid = False
                            break
                        pct_sum += vp
                    if valid and abs(pct_sum - 100.0) <= 0.1:
                        checks["summary_volume_pct_total_ok"] = True
                else:
                    # Degenerate case: no volume, accept as OK
                    checks["summary_volume_pct_total_ok"] = True

    # PIVOT CHECKS
    pivot_header = []
    pivot_rows = []
    if os.path.isfile(pivot_path):
        checks["has_pivot_file"] = True
        try:
            pivot_header, pivot_rows = read_csv_dicts(pivot_path)
        except Exception:
            pivot_header, pivot_rows = [], []

        # Validate columns
        pivot_columns_ok = False
        if pivot_header and len(pivot_header) >= 2:
            first_col = pivot_header[0]
            remaining_cols = pivot_header[1:]
            # Expect 'Level' as first column and 'Total' present
            if first_col == "Level" and "Total" in remaining_cols:
                # categories columns are remaining excluding 'Total'
                cat_cols = [c for c in remaining_cols if c != "Total"]
                if checks["has_detailed_file"] and checks["detailed_header_ok"]:
                    if set(cat_cols) == categories_set:
                        pivot_columns_ok = True
                else:
                    # If we cannot determine categories from detailed, at least ensure 'Total' exists
                    pivot_columns_ok = True
        if pivot_columns_ok:
            checks["pivot_columns_ok"] = True

        # Validate rows and values against expected
        if checks["has_detailed_file"] and checks["detailed_header_ok"] and checks["pivot_columns_ok"]:
            levels_in_pivot = set()
            values_match = True
            row_totals_ok = True

            # Build a map from (level, category) in pivot
            for row in pivot_rows:
                lvl = str(row.get("Level", ""))
                if lvl == "" and not categories_set and "Total" in row:
                    # Allow an empty pivot with no levels
                    continue
                levels_in_pivot.add(lvl)
                # Check each category value
                row_sum = 0.0
                row_sum_valid = True
                for cat in categories_set:
                    v = parse_float(row.get(cat, "0"))
                    if v is None:
                        values_match = False
                        row_sum_valid = False
                        continue
                    # expected value:
                    exp = pivot_expected.get((lvl, cat), 0.0)
                    if not nearly_equal(v, exp, 0.01):
                        values_match = False
                    row_sum += v
                # Check total column
                total_cell = parse_float(row.get("Total"))
                if total_cell is None or not row_sum_valid or not nearly_equal(total_cell, row_sum, 0.01):
                    row_totals_ok = False

            # Check that levels match
            if levels_set == levels_in_pivot:
                checks["pivot_rows_match"] = True
            else:
                # Special case: no levels expected and pivot has no rows
                if not levels_set and not levels_in_pivot:
                    checks["pivot_rows_match"] = True

            if values_match:
                checks["pivot_values_match"] = True
            if row_totals_ok:
                checks["pivot_row_totals_ok"] = True

    # REPORT CHECKS
    if os.path.isfile(report_path):
        checks["has_report_file"] = True
        try:
            report_obj = read_json(report_path)
        except Exception:
            report_obj = None

        if isinstance(report_obj, dict):
            required_keys = {"total_base_cost", "total_cost", "total_volume", "missing_price_count", "levels", "categories"}
            if required_keys.issubset(set(report_obj.keys())):
                checks["report_keys_ok"] = True

                # Validate totals and lists against detailed aggregates
                if checks["has_detailed_file"] and checks["detailed_header_ok"]:
                    r_tbc = parse_float(report_obj.get("total_base_cost"))
                    r_tc = parse_float(report_obj.get("total_cost"))
                    r_tv = parse_float(report_obj.get("total_volume"))
                    r_mpc = report_obj.get("missing_price_count")
                    try:
                        r_mpc_int = int(r_mpc)
                    except Exception:
                        r_mpc_int = None

                    if r_tbc is not None and nearly_equal(r_tbc, total_base_cost_all, 0.01) and \
                       r_tc is not None and nearly_equal(r_tc, total_cost_all, 0.01) and \
                       r_tv is not None and nearly_equal(r_tv, total_volume_all, 0.01):
                        checks["report_totals_match"] = True

                    # Levels and categories lists
                    r_levels = report_obj.get("levels")
                    r_categories = report_obj.get("categories")
                    if isinstance(r_levels, list):
                        exp_levels = sorted(list(levels_set))
                        if r_levels == exp_levels:
                            checks["report_levels_match"] = True
                    if isinstance(r_categories, list):
                        exp_categories = sorted(list(categories_set))
                        if r_categories == exp_categories:
                            checks["report_categories_match"] = True

                    if r_mpc_int is not None and r_mpc_int == missing_price_count:
                        # Incorporate into totals match? The spec separates only totals match criteria;
                        # missing_price_count is validated implicitly here; no separate boolean field requested
                        pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Enforce no-op baseline: if output missing or empty fails yield 0 reward already
    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()