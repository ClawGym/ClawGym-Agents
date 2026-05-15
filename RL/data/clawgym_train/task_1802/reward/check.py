import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import csv

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def d2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def d1(x):
    return Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

def parse_decimal(val):
    if val is None:
        raise InvalidOperation("None value")
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    s = str(val).strip()
    # Remove common thousand separators
    s = s.replace(",", "")
    if s == "":
        return Decimal("0")
    return Decimal(s)

def read_csv_rows(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    return fieldnames, rows

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compute_expected(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    # Paths
    design_path = os.path.join(input_dir, "design_elements.csv")
    asbuilt_path = os.path.join(input_dir, "asbuilt_elements.csv")
    prices_path = os.path.join(input_dir, "unit_prices.csv")
    waste_path = os.path.join(input_dir, "waste_factors.json")

    # Read inputs
    design_fields, design_rows = read_csv_rows(design_path)
    asbuilt_fields, asbuilt_rows = read_csv_rows(asbuilt_path)
    prices_fields, prices_rows = read_csv_rows(prices_path)
    waste_factors = read_json(waste_path)

    # Validate required columns
    required_design = {"Category", "Volume"}
    required_asbuilt = {"Category", "Material", "Volume"}
    required_prices = {"Category", "Unit_Price"}

    inputs_valid = required_design.issubset(set(design_fields)) and \
                   required_asbuilt.issubset(set(asbuilt_fields)) and \
                   required_prices.issubset(set(prices_fields))

    if not inputs_valid:
        return {
            "inputs_valid": False
        }

    # Parse waste factors to Decimal
    waste_dec = {}
    for k, v in waste_factors.items():
        try:
            waste_dec[str(k)] = parse_decimal(v)
        except Exception:
            waste_dec[str(k)] = Decimal("1.0")

    # Aggregate as-built for QTO
    net_by_cat = {}
    gross_by_cat = {}
    count_by_cat = {}

    for r in asbuilt_rows:
        cat = (r.get("Category") or "").strip()
        mat = (r.get("Material") or "").strip()
        try:
            vol = parse_decimal(r.get("Volume"))
        except Exception:
            vol = Decimal("0")
        if cat == "":
            # Skip entries without category
            continue
        factor = waste_dec.get(mat, Decimal("1.0"))
        net_by_cat[cat] = net_by_cat.get(cat, Decimal("0")) + vol
        gross_by_cat[cat] = gross_by_cat.get(cat, Decimal("0")) + (vol * factor)
        count_by_cat[cat] = count_by_cat.get(cat, 0) + 1

    categories_qto = sorted(net_by_cat.keys())
    qto_expected = []
    for cat in categories_qto:
        net = net_by_cat.get(cat, Decimal("0"))
        gross = gross_by_cat.get(cat, Decimal("0"))
        net_r = d2(net)
        gross_r = d2(gross)
        waste_r = d2(gross - net)
        qto_expected.append({
            "Category": cat,
            "Count": count_by_cat.get(cat, 0),
            "Net_Volume": net_r,
            "Gross_Volume": gross_r,
            "Waste_Volume": waste_r
        })

    # Unit prices by category
    price_by_cat = {}
    for r in prices_rows:
        cat = (r.get("Category") or "").strip()
        if cat == "":
            continue
        try:
            price = parse_decimal(r.get("Unit_Price"))
        except Exception:
            price = Decimal("0")
        price_by_cat[cat] = price

    # Cost estimate expected (use Gross_Volume from QTO, as rounded)
    cost_rows = []
    for cat in categories_qto:
        gross_v = next((row["Gross_Volume"] for row in qto_expected if row["Category"] == cat), d2("0"))
        unit_price = price_by_cat.get(cat, Decimal("0"))
        total_cost = d2(gross_v * unit_price)
        cost_rows.append({
            "Category": cat,
            "Gross_Volume": gross_v,
            "Unit_Price": unit_price,
            "Total_Cost": total_cost  # rounded to 2 decimals
        })
    grand_total = sum([r["Total_Cost"] for r in cost_rows], Decimal("0"))
    # Compute percentages rounded to 1 decimal
    for r in cost_rows:
        if grand_total == 0:
            pct = Decimal("0.0")
        else:
            pct = d1((r["Total_Cost"] / grand_total) * Decimal("100"))
        r["Cost_Pct"] = pct

    # Comparison expected
    design_by_cat = {}
    for r in design_rows:
        cat = (r.get("Category") or "").strip()
        if cat == "":
            continue
        try:
            vol = parse_decimal(r.get("Volume"))
        except Exception:
            vol = Decimal("0")
        design_by_cat[cat] = design_by_cat.get(cat, Decimal("0")) + vol

    asbuilt_sum_by_cat = {}
    for r in asbuilt_rows:
        cat = (r.get("Category") or "").strip()
        if cat == "":
            continue
        try:
            vol = parse_decimal(r.get("Volume"))
        except Exception:
            vol = Decimal("0")
        asbuilt_sum_by_cat[cat] = asbuilt_sum_by_cat.get(cat, Decimal("0")) + vol

    comp_categories = sorted(set(design_by_cat.keys()).union(set(asbuilt_sum_by_cat.keys())))
    comp_expected = []
    for cat in comp_categories:
        dsum = design_by_cat.get(cat, Decimal("0"))
        asum = asbuilt_sum_by_cat.get(cat, Decimal("0"))
        design_r = d2(dsum)
        asbuilt_r = d2(asum)
        diff_r = d2(asum - dsum)
        if dsum == 0:
            # Treat 0/0 as 0.0; if design is 0 and as-built > 0, set to 0.0 to avoid division by zero
            var_pct = Decimal("0.0")
        else:
            var_pct = d1(((asum - dsum) / dsum) * Decimal("100"))
        comp_expected.append({
            "Category": cat,
            "Design_Volume": design_r,
            "AsBuilt_Volume": asbuilt_r,
            "Difference": diff_r,
            "Variance_Pct": var_pct
        })

    return {
        "inputs_valid": True,
        "qto_expected": qto_expected,
        "cost_expected": cost_rows,
        "comp_expected": comp_expected,
        "categories_qto": categories_qto,
        "comp_categories": comp_categories
    }

def read_output_csv(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames or []
    return fields, rows

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "inputs_valid": False,
        "qto_file_exists": False,
        "qto_structure_ok": False,
        "qto_sorted_ok": False,
        "qto_values_ok": False,
        "cost_file_exists": False,
        "cost_structure_ok": False,
        "cost_sorted_ok": False,
        "cost_values_ok": False,
        "comparison_file_exists": False,
        "comparison_structure_ok": False,
        "comparison_sorted_ok": False,
        "comparison_values_ok": False,
        "only_expected_outputs": False
    }

    # Early baseline: if output missing or empty => reward stays 0.0
    if not os.path.isdir(output_dir):
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Compute expected values from inputs
    try:
        exp = compute_expected(workspace_root)
    except Exception:
        # If any error computing expected, we cannot award points
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    checks["inputs_valid"] = bool(exp.get("inputs_valid", False))

    # QTO verification
    qto_path = os.path.join(output_dir, "qto_asbuilt_by_category.csv")
    if os.path.isfile(qto_path):
        checks["qto_file_exists"] = True
        try:
            fields, rows = read_output_csv(qto_path)
            expected_fields = ["Category", "Count", "Net_Volume", "Gross_Volume", "Waste_Volume"]
            if fields == expected_fields:
                checks["qto_structure_ok"] = True

            # Check sorting by Category ascending
            cats = [r.get("Category", "") for r in rows]
            if cats == sorted(cats):
                checks["qto_sorted_ok"] = True

            # Check values: must match expected categories and values exactly with rounding
            qto_expected = exp.get("qto_expected", [])
            expected_by_cat = {row["Category"]: row for row in qto_expected}
            # Must contain exactly expected categories and same number of rows
            if len(rows) == len(qto_expected) and set(cats) == set(expected_by_cat.keys()):
                values_ok = True
                for r in rows:
                    cat = r.get("Category", "")
                    exp_row = expected_by_cat.get(cat)
                    if exp_row is None:
                        values_ok = False
                        break
                    # Count
                    try:
                        count_val = int(str(r.get("Count", "")).strip())
                    except Exception:
                        values_ok = False
                        break
                    if count_val != exp_row["Count"]:
                        values_ok = False
                        break
                    # Volumes
                    try:
                        net_v = d2(parse_decimal(r.get("Net_Volume")))
                        gross_v = d2(parse_decimal(r.get("Gross_Volume")))
                        waste_v = d2(parse_decimal(r.get("Waste_Volume")))
                    except Exception:
                        values_ok = False
                        break
                    if net_v != exp_row["Net_Volume"] or gross_v != exp_row["Gross_Volume"] or waste_v != exp_row["Waste_Volume"]:
                        values_ok = False
                        break
                if values_ok and checks["qto_structure_ok"] and checks["qto_sorted_ok"]:
                    checks["qto_values_ok"] = True
        except Exception:
            pass

    # Cost estimate verification
    cost_path = os.path.join(output_dir, "cost_estimate.csv")
    if os.path.isfile(cost_path):
        checks["cost_file_exists"] = True
        try:
            fields, rows = read_output_csv(cost_path)
            expected_fields = ["Category", "Gross_Volume", "Unit_Price", "Total_Cost", "Cost_Pct"]
            if fields == expected_fields:
                checks["cost_structure_ok"] = True

            cats = [r.get("Category", "") for r in rows]
            if cats == sorted(cats):
                checks["cost_sorted_ok"] = True

            cost_expected = exp.get("cost_expected", [])
            expected_by_cat = {row["Category"]: row for row in cost_expected}
            # Must contain exactly expected categories and same number of rows
            if len(rows) == len(cost_expected) and set(cats) == set(expected_by_cat.keys()):
                # Recompute grand total from provided rows to validate Cost_Pct
                try:
                    # Validate values
                    values_ok = True
                    # Compute expected grand total
                    grand_total = sum([r["Total_Cost"] for r in cost_expected], Decimal("0"))
                    for r in rows:
                        cat = r.get("Category", "")
                        exp_row = expected_by_cat.get(cat)
                        if exp_row is None:
                            values_ok = False
                            break
                        try:
                            gross_v = d2(parse_decimal(r.get("Gross_Volume")))
                            unit_p = d2(parse_decimal(r.get("Unit_Price")))
                            total_c = d2(parse_decimal(r.get("Total_Cost")))
                            cost_pct = d1(parse_decimal(r.get("Cost_Pct")))
                        except Exception:
                            values_ok = False
                            break

                        # Check gross and unit price match expected
                        if gross_v != exp_row["Gross_Volume"]:
                            values_ok = False
                            break
                        if unit_p != exp_row["Unit_Price"]:
                            values_ok = False
                            break

                        # Check total cost computed from gross and unit price rounded to 2 decimals
                        calc_total = d2(exp_row["Gross_Volume"] * exp_row["Unit_Price"])
                        if total_c != calc_total or total_c != exp_row["Total_Cost"]:
                            values_ok = False
                            break

                        # Check percentage: based on expected grand total
                        if grand_total == 0:
                            exp_pct = Decimal("0.0")
                        else:
                            exp_pct = d1((exp_row["Total_Cost"] / grand_total) * Decimal("100"))
                        if cost_pct != exp_pct:
                            values_ok = False
                            break
                    if values_ok and checks["cost_structure_ok"] and checks["cost_sorted_ok"]:
                        checks["cost_values_ok"] = True
                except Exception:
                    pass
        except Exception:
            pass

    # Comparison verification
    comp_path = os.path.join(output_dir, "comparison_by_category.json")
    if os.path.isfile(comp_path):
        checks["comparison_file_exists"] = True
        try:
            data = read_json(comp_path)
            if isinstance(data, list):
                # Structure: each object must have keys exactly
                expected_keys = {"Category", "Design_Volume", "AsBuilt_Volume", "Difference", "Variance_Pct"}
                struct_ok = True
                for obj in data:
                    if not isinstance(obj, dict):
                        struct_ok = False
                        break
                    keys = set(obj.keys())
                    if keys != expected_keys:
                        struct_ok = False
                        break
                if struct_ok:
                    checks["comparison_structure_ok"] = True

                # Sorting
                cats = [str(obj.get("Category", "")) for obj in data]
                if cats == sorted(cats):
                    checks["comparison_sorted_ok"] = True

                # Values
                comp_expected = exp.get("comp_expected", [])
                expected_by_cat = {row["Category"]: row for row in comp_expected}
                if len(data) == len(comp_expected) and set(cats) == set(expected_by_cat.keys()):
                    values_ok = True
                    for obj in data:
                        cat = str(obj.get("Category", ""))
                        exp_obj = expected_by_cat.get(cat)
                        if exp_obj is None:
                            values_ok = False
                            break
                        try:
                            d_vol = d2(parse_decimal(obj.get("Design_Volume")))
                            a_vol = d2(parse_decimal(obj.get("AsBuilt_Volume")))
                            diff = d2(parse_decimal(obj.get("Difference")))
                            varp = d1(parse_decimal(obj.get("Variance_Pct")))
                        except Exception:
                            values_ok = False
                            break
                        if d_vol != exp_obj["Design_Volume"] or a_vol != exp_obj["AsBuilt_Volume"] or diff != exp_obj["Difference"] or varp != exp_obj["Variance_Pct"]:
                            values_ok = False
                            break
                    if values_ok and checks["comparison_structure_ok"] and checks["comparison_sorted_ok"]:
                        checks["comparison_values_ok"] = True
        except Exception:
            pass

    # Only expected outputs present
    try:
        output_files = sorted([f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))])
        expected_files = sorted(["qto_asbuilt_by_category.csv", "cost_estimate.csv", "comparison_by_category.json"])
        checks["only_expected_outputs"] = (output_files == expected_files)
    except Exception:
        checks["only_expected_outputs"] = False

    # Compute reward
    qto_pass = checks["qto_file_exists"] and checks["qto_structure_ok"] and checks["qto_sorted_ok"] and checks["qto_values_ok"]
    cost_pass = checks["cost_file_exists"] and checks["cost_structure_ok"] and checks["cost_sorted_ok"] and checks["cost_values_ok"]
    comp_pass = checks["comparison_file_exists"] and checks["comparison_structure_ok"] and checks["comparison_sorted_ok"] and checks["comparison_values_ok"]

    # Require no extra outputs for any positive reward
    if not checks["only_expected_outputs"]:
        reward = 0.0
    else:
        # Average of the three deliverables
        total = 3
        score = (1 if qto_pass else 0) + (1 if cost_pass else 0) + (1 if comp_pass else 0)
        reward = score / total if total > 0 else 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()