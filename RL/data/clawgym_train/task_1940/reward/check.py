import json
import os
import sys
import csv
import re

def parse_float_num(s):
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    val = s.strip()
    # Remove currency symbols and labels
    val = val.replace("$", "")
    val = val.replace("USD", "").replace("usd", "").strip()
    # Remove trailing commas
    val = val.rstrip(",")
    try:
        return float(val)
    except:
        return None

def extract_floats_from_line(line):
    # Find positive floats/ints in a line
    nums = re.findall(r'\d+(?:\.\d+)?', line)
    floats = []
    for n in nums:
        try:
            floats.append(float(n))
        except:
            pass
    return floats

def validate_rent_range_for(name, rmin, rmax):
    # Returns True if the rent range fits specified constraints per neighborhood
    if rmin is None or rmax is None:
        return False
    if not (isinstance(rmin, (int, float)) and isinstance(rmax, (int, float))):
        return False
    if rmin >= rmax:
        return False
    if name == "Palermo":
        canon_min, canon_max = 500, 750
        allowed_min_low, allowed_max_high = 450, 800
        required_overlap = 150
    elif name == "Belgrano":
        canon_min, canon_max = 400, 600
        allowed_min_low, allowed_max_high = 350, 650
        required_overlap = 150
    elif name == "Puerto Madero":
        canon_min, canon_max = 800, 1200
        allowed_min_low, allowed_max_high = 700, 1400
        required_overlap = 300
    else:
        return False
    if rmin < allowed_min_low or rmax > allowed_max_high:
        return False
    overlap_low = max(rmin, canon_min)
    overlap_high = min(rmax, canon_max)
    overlap = overlap_high - overlap_low
    return overlap >= required_overlap

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Neighborhoods checks
        "neighborhoods_file_exists": False,
        "neighborhoods_is_array_len3": False,
        "neighborhoods_has_required_fields": False,
        "neighborhoods_names_match_set": False,
        "neighborhoods_rent_range_palermo_valid": False,
        "neighborhoods_rent_range_belgrano_valid": False,
        "neighborhoods_rent_range_puerto_madero_valid": False,
        # Budget checks
        "budget_file_exists": False,
        "budget_header_valid": False,
        "budget_categories_exact": False,
        "budget_all_numeric_positive": False,
        "budget_totals_match": False,
        "budget_rent_range_ok": False,
        "budget_utilities_range_ok": False,
        "budget_internet_range_ok": False,
        "budget_transport_range_ok": False,
        "budget_healthcare_range_ok": False,
        "budget_phone_range_ok": False,
        "budget_entertainment_range_ok": False,
        "budget_misc_range_ok": False,
        "budget_food_consistency_ok": False,
        "budget_total_range_ok": False,
        # Transport checks
        "transport_file_exists": False,
        "transport_keywords_present": False,
        "transport_subte_cost_ok": False,
        "transport_bus_cost_ok": False,
        "transport_monthly_cost_ok": False,
    }

    # Neighborhoods.json validation
    neighborhoods_path = os.path.join(output_dir, "neighborhoods.json")
    neighborhoods_data = None
    if os.path.isfile(neighborhoods_path):
        checks["neighborhoods_file_exists"] = True
        try:
            with open(neighborhoods_path, "r", encoding="utf-8") as f:
                neighborhoods_data = json.load(f)
            if isinstance(neighborhoods_data, list) and len(neighborhoods_data) == 3:
                checks["neighborhoods_is_array_len3"] = True
                required_names = {"Palermo", "Belgrano", "Puerto Madero"}
                names = set()
                fields_ok = True
                rent_ranges = {}
                for item in neighborhoods_data:
                    if not isinstance(item, dict):
                        fields_ok = False
                        break
                    # Required keys
                    req_keys = ["name", "why", "pros", "cons", "rent_usd_range", "commute_notes"]
                    if any(k not in item for k in req_keys):
                        fields_ok = False
                        break
                    # Types
                    if not isinstance(item["name"], str):
                        fields_ok = False
                        break
                    if not isinstance(item["why"], str):
                        fields_ok = False
                        break
                    if not (isinstance(item["pros"], list) and len(item["pros"]) >= 3 and all(isinstance(p, str) for p in item["pros"])):
                        fields_ok = False
                        break
                    if not (isinstance(item["cons"], list) and len(item["cons"]) >= 2 and all(isinstance(c, str) for c in item["cons"])):
                        fields_ok = False
                        break
                    if not isinstance(item["rent_usd_range"], dict):
                        fields_ok = False
                        break
                    if "min" not in item["rent_usd_range"] or "max" not in item["rent_usd_range"]:
                        fields_ok = False
                        break
                    rmin = item["rent_usd_range"]["min"]
                    rmax = item["rent_usd_range"]["max"]
                    if not (isinstance(rmin, (int, float)) and isinstance(rmax, (int, float))):
                        fields_ok = False
                        break
                    if not isinstance(item["commute_notes"], str):
                        fields_ok = False
                        break
                    names.add(item["name"])
                    rent_ranges[item["name"]] = (rmin, rmax)
                if fields_ok:
                    checks["neighborhoods_has_required_fields"] = True
                if names == required_names:
                    checks["neighborhoods_names_match_set"] = True
                # Rent range validations per neighborhood
                for nb_name in ["Palermo", "Belgrano", "Puerto Madero"]:
                    if nb_name in rent_ranges:
                        rmin, rmax = rent_ranges[nb_name]
                        valid = validate_rent_range_for(nb_name, rmin, rmax)
                        key = f"neighborhoods_rent_range_{nb_name.lower().replace(' ', '_')}_valid"
                        checks[key] = valid
        except Exception:
            # Leave checks as initialized
            pass

    # Budget.csv validation
    budget_path = os.path.join(output_dir, "budget.csv")
    if os.path.isfile(budget_path):
        checks["budget_file_exists"] = True
        try:
            with open(budget_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["category", "single_usd", "couple_usd"]:
                    checks["budget_header_valid"] = True
                data_rows = rows[1:]
                # Expect exactly categories set
                expected_categories = [
                    "Rent", "Utilities", "Internet", "Groceries", "Dining out",
                    "Transport", "Healthcare", "Phone", "Entertainment", "Misc", "Total"
                ]
                cat_set_expected = set(expected_categories)
                categories = []
                values = {}
                all_numeric_positive = True
                for r in data_rows:
                    if len(r) != 3:
                        all_numeric_positive = False
                        break
                    category = r[0].strip()
                    categories.append(category)
                    single_val = parse_float_num(r[1])
                    couple_val = parse_float_num(r[2])
                    if single_val is None or couple_val is None:
                        all_numeric_positive = False
                        break
                    if single_val <= 0 or couple_val <= 0:
                        all_numeric_positive = False
                        break
                    values[category] = (single_val, couple_val)
                # Check categories exact and unique
                if set(categories) == cat_set_expected and len(categories) == len(set(categories)) == len(expected_categories):
                    checks["budget_categories_exact"] = True
                if all_numeric_positive:
                    checks["budget_all_numeric_positive"] = True

                # Totals match sums
                if checks["budget_categories_exact"] and checks["budget_all_numeric_positive"]:
                    sum_single = 0.0
                    sum_couple = 0.0
                    for cat in expected_categories:
                        if cat != "Total":
                            s, c = values.get(cat, (0.0, 0.0))
                            sum_single += s
                            sum_couple += c
                    total_single, total_couple = values.get("Total", (None, None))
                    if total_single is not None and total_couple is not None:
                        if abs(total_single - sum_single) <= 0.01 and abs(total_couple - sum_couple) <= 0.01:
                            checks["budget_totals_match"] = True

                    # Range checks per category
                    def in_range(val, lo, hi):
                        return val is not None and (val >= lo and val <= hi)

                    # Rent (Palermo 1BR) both single and couple in [500, 750]
                    if "Rent" in values:
                        s, c = values["Rent"]
                        if in_range(s, 500, 750) and in_range(c, 500, 750):
                            checks["budget_rent_range_ok"] = True

                    # Utilities: single [20,60], couple [20,80]
                    if "Utilities" in values:
                        s, c = values["Utilities"]
                        if in_range(s, 20, 60) and in_range(c, 20, 80):
                            checks["budget_utilities_range_ok"] = True

                    # Internet: both [20,40]
                    if "Internet" in values:
                        s, c = values["Internet"]
                        if in_range(s, 20, 40) and in_range(c, 20, 40):
                            checks["budget_internet_range_ok"] = True

                    # Transport: single [40,80], couple [60,160]
                    if "Transport" in values:
                        s, c = values["Transport"]
                        if in_range(s, 40, 80) and in_range(c, 60, 160):
                            checks["budget_transport_range_ok"] = True

                    # Healthcare: single [50,150], couple [100,300]
                    if "Healthcare" in values:
                        s, c = values["Healthcare"]
                        if in_range(s, 50, 150) and in_range(c, 100, 300):
                            checks["budget_healthcare_range_ok"] = True

                    # Phone: single [10,25], couple [20,50]
                    if "Phone" in values:
                        s, c = values["Phone"]
                        if in_range(s, 10, 25) and in_range(c, 20, 50):
                            checks["budget_phone_range_ok"] = True

                    # Entertainment: single [30,100], couple [60,200]
                    if "Entertainment" in values:
                        s, c = values["Entertainment"]
                        if in_range(s, 30, 100) and in_range(c, 60, 200):
                            checks["budget_entertainment_range_ok"] = True

                    # Misc: single [50,150], couple [75,250]
                    if "Misc" in values:
                        s, c = values["Misc"]
                        if in_range(s, 50, 150) and in_range(c, 75, 250):
                            checks["budget_misc_range_ok"] = True

                    # Food consistency: (Groceries + Dining out) single [350,500], couple [600,800]
                    if "Groceries" in values and "Dining out" in values:
                        gs, gc = values["Groceries"]
                        ds, dc = values["Dining out"]
                        total_s = gs + ds
                        total_c = gc + dc
                        if (total_s >= 350 and total_s <= 500) and (total_c >= 600 and total_c <= 800):
                            checks["budget_food_consistency_ok"] = True

                    # Comfortable total check: Total single [1500,2000], Total couple [1500,2500]
                    if "Total" in values:
                        ts, tc = values["Total"]
                        if in_range(ts, 1500, 2000) and in_range(tc, 1500, 2500):
                            checks["budget_total_range_ok"] = True

        except Exception:
            # Leave as False
            pass

    # Transport.md validation
    transport_path = os.path.join(output_dir, "transport.md")
    if os.path.isfile(transport_path):
        checks["transport_file_exists"] = True
        try:
            with open(transport_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            text = "\n".join(lines)
            lower_text = text.lower()
            # Keywords: "SUBE", "Subte", "colectivo"/"colectivos", "taxi", and "Uber" or "Cabify"
            has_sube = "sube" in lower_text
            has_subte = "subte" in lower_text
            has_colectivo = ("colectivo" in lower_text) or ("colectivos" in lower_text)
            has_taxi = "taxi" in lower_text
            has_ride = ("uber" in lower_text) or ("cabify" in lower_text)
            if has_sube and has_subte and has_colectivo and has_taxi and has_ride:
                checks["transport_keywords_present"] = True

            # Subte per-ride cost in [0.35, 0.60] on a line mentioning subte
            subte_cost_ok = False
            for line in lines:
                if "subte" in line.lower():
                    nums = extract_floats_from_line(line)
                    for n in nums:
                        if 0.35 <= n <= 0.60:
                            subte_cost_ok = True
                            break
                if subte_cost_ok:
                    break
            checks["transport_subte_cost_ok"] = subte_cost_ok

            # Colectivos per-ride cost in [0.25, 0.50] on a line mentioning colectivo
            bus_cost_ok = False
            for line in lines:
                ll = line.lower()
                if ("colectivo" in ll) or ("colectivos" in ll) or ("bus" in ll) or ("buses" in ll):
                    nums = extract_floats_from_line(line)
                    for n in nums:
                        if 0.25 <= n <= 0.50:
                            bus_cost_ok = True
                            break
                if bus_cost_ok:
                    break
            checks["transport_bus_cost_ok"] = bus_cost_ok

            # Monthly pass or monthly cost in [15, 25] on a line referencing monthly or pass
            monthly_cost_ok = False
            for line in lines:
                ll = line.lower()
                if ("monthly" in ll) or ("month" in ll) or ("pass" in ll):
                    nums = extract_floats_from_line(line)
                    for n in nums:
                        if 15 <= n <= 25:
                            monthly_cost_ok = True
                            break
                if monthly_cost_ok:
                    break
            checks["transport_monthly_cost_ok"] = monthly_cost_ok

        except Exception:
            # Leave as False
            pass

    # Compute reward as fraction of checks passed, but ensure 0.0 if no outputs at all
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # If output dir missing or empty, reward must be 0.0
    any_output = os.path.isdir(output_dir) and any(True for _ in os.scandir(output_dir))
    if any_output:
        reward = passed / total_checks if total_checks > 0 else 0.0
    else:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()