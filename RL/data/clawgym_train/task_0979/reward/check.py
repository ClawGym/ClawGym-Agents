import json
import os
import sys
import csv
import math
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def approx_equal(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None

def to_float(v):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            return float(s)
        return None
    except Exception:
        return None

def is_int_value(v):
    try:
        if isinstance(v, int):
            return True
        if isinstance(v, float):
            return v.is_integer()
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return True
            fv = float(s)
            return fv.is_integer()
        return False
    except Exception:
        return False

def normalize_name(s):
    s = s.lower()
    s = s.replace("—", " ").replace("–", " ").replace("-", " ")
    s = re.sub(r"[%$:,/()\[\]]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def contains_number_variants(text, number):
    # Check for exact integer, with/without commas, with .00, and with optional dollar sign
    n_int = int(round(number))
    variants = set()
    base = str(n_int)
    with_commas = "{:,}".format(n_int)
    variants.update([base, with_commas, f"{base}.00", f"{with_commas}.00"])
    all_tokens = set()
    for v in variants:
        all_tokens.add(v)
        all_tokens.add("$" + v)
    t = text
    return any(v in t for v in all_tokens)

def extract_numbers(s):
    return [float(x) for x in re.findall(r"\d+\.?\d*", s)]

def kpi_name_present(required_key, names_norm):
    # required_key can be a tuple of keywords that must all appear
    if isinstance(required_key, tuple):
        for name in names_norm:
            if all(k in name for k in required_key):
                return True
        return False
    else:
        for name in names_norm:
            if required_key in name:
                return True
        return False

def supply_target_ok(target_str):
    s = target_str.lower()
    # Accept phrases indicating less than or equal to 6%
    if ("<" in s or "≤" in s or "less than" in s or "under" in s or "below" in s or "max" in s or "at most" in s):
        # Check a number 6 nearby
        nums = extract_numbers(s)
        if any(abs(n - 6.0) < 1e-6 or n < 6.0001 for n in nums):
            return True
    return False

def revenue_per_labor_hour_target_ok(target):
    # Must indicate 45–65 range; accept if both 45 and 65 appear in the string (numbers)
    s = str(target)
    nums = extract_numbers(s)
    # If both 45 and 65 present explicitly
    if any(abs(n - 45) < 0.001 for n in nums) and any(abs(n - 65) < 0.001 for n in nums):
        return True
    # Or a range that spans within 45-65
    if len(nums) >= 2:
        lo = min(nums[0], nums[1])
        hi = max(nums[0], nums[1])
        if lo <= 45 + 1e-6 and hi >= 65 - 1e-6:
            return True
        if 45 - 1e-6 <= lo <= 65 + 1e-6 and 45 - 1e-6 <= hi <= 65 + 1e-6:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Initialize all checks to False
    check_names = [
        # pricing
        "has_pricing_json",
        "pricing_required_keys",
        "pricing_facility_type_medical_dental",
        "pricing_base_rate_in_range",
        "pricing_restroom_fee_in_range",
        "pricing_production_rate_in_range",
        "pricing_visits_per_month_consistent",
        "pricing_monthly_base_calc",
        "pricing_restroom_addon_calc",
        "pricing_total_monthly_price_calc",
        "pricing_hours_per_visit_calc",
        "pricing_clock_hours_per_visit_calc",
        "pricing_hours_per_month_calc",
        "pricing_supply_budget_in_range",
        "pricing_monthly_supply_budget_calc",
        "pricing_supply_pct_in_range",
        "pricing_labor_plan_valid",
        # qc checklist
        "has_qc_csv",
        "qc_header_valid",
        "qc_rows_count",
        "qc_areas_complete",
        "qc_scales_and_targets",
        # kpis
        "has_kpis_json",
        "kpis_length_10",
        "kpis_required_names_present",
        "kpis_revenue_per_labor_hour_target_ok",
        "kpis_supply_cost_target_ok",
        # proposal
        "has_proposal_md",
        "proposal_contains_required_phrases",
        "proposal_contains_total_monthly_price",
    ]
    for n in check_names:
        checks[n] = False

    # 1) Validate output/pricing_calculation.json
    pricing_path = os.path.join(output_dir, "pricing_calculation.json")
    pricing = read_json(pricing_path)
    if isinstance(pricing, dict):
        checks["has_pricing_json"] = True
        required_keys = [
            "facility_name", "facility_type", "cleanable_sq_ft", "days_per_week", "visits_per_month", "restrooms",
            "base_rate_per_sqft", "restroom_fee",
            "monthly_base", "monthly_restroom_addon", "total_monthly_price",
            "production_rate_sqft_per_hour", "hours_per_visit", "crew_size", "clock_hours_per_visit", "hours_per_month",
            "labor_plan",
            "supply_budget_per_visit", "monthly_supply_budget", "supply_pct_of_revenue",
            "assumptions"
        ]
        if all(k in pricing for k in required_keys):
            checks["pricing_required_keys"] = True

            try:
                # facility_type medical/dental
                ft = str(pricing.get("facility_type", "")).lower()
                if ("medical" in ft) or ("dental" in ft):
                    checks["pricing_facility_type_medical_dental"] = True

                # ranges
                base_rate = to_float(pricing.get("base_rate_per_sqft"))
                restroom_fee = to_float(pricing.get("restroom_fee"))
                prod_rate = to_float(pricing.get("production_rate_sqft_per_hour"))

                if base_rate is not None and 0.12 - 1e-9 <= base_rate <= 0.20 + 1e-9:
                    checks["pricing_base_rate_in_range"] = True
                if restroom_fee is not None and 75 - 1e-9 <= restroom_fee <= 150 + 1e-9:
                    checks["pricing_restroom_fee_in_range"] = True
                if prod_rate is not None and 2500 - 1e-9 <= prod_rate <= 3500 + 1e-9:
                    checks["pricing_production_rate_in_range"] = True

                # recompute visits_per_month
                days_per_week = to_float(pricing.get("days_per_week"))
                visits_pm = to_float(pricing.get("visits_per_month"))
                if days_per_week is not None and visits_pm is not None:
                    expected_visits = int(round(days_per_week * 4.33))
                    if abs(visits_pm - expected_visits) <= 1:
                        checks["pricing_visits_per_month_consistent"] = True

                # financial calculations
                cleanable = to_float(pricing.get("cleanable_sq_ft"))
                restrooms = to_float(pricing.get("restrooms"))
                monthly_base = to_float(pricing.get("monthly_base"))
                monthly_addon = to_float(pricing.get("monthly_restroom_addon"))
                total_monthly = to_float(pricing.get("total_monthly_price"))

                if None not in (cleanable, base_rate, monthly_base):
                    if approx_equal(monthly_base, cleanable * base_rate, 2.00):
                        checks["pricing_monthly_base_calc"] = True
                if None not in (restrooms, restroom_fee, monthly_addon):
                    if approx_equal(monthly_addon, restrooms * restroom_fee, 2.00):
                        checks["pricing_restroom_addon_calc"] = True
                if None not in (monthly_base, monthly_addon, total_monthly):
                    if approx_equal(total_monthly, monthly_base + monthly_addon, 2.00):
                        checks["pricing_total_monthly_price_calc"] = True

                # hours calculations
                hours_per_visit = to_float(pricing.get("hours_per_visit"))
                crew_size = to_float(pricing.get("crew_size"))
                clock_hours_per_visit = to_float(pricing.get("clock_hours_per_visit"))
                hours_per_month = to_float(pricing.get("hours_per_month"))

                if None not in (cleanable, prod_rate, hours_per_visit):
                    if approx_equal(hours_per_visit, cleanable / prod_rate, 0.1):
                        checks["pricing_hours_per_visit_calc"] = True

                if None not in (hours_per_visit, crew_size, clock_hours_per_visit) and crew_size not in (0, None):
                    if approx_equal(clock_hours_per_visit, hours_per_visit / crew_size, 0.1):
                        checks["pricing_clock_hours_per_visit_calc"] = True

                if None not in (hours_per_visit, visits_pm, hours_per_month):
                    if approx_equal(hours_per_month, hours_per_visit * visits_pm, 0.5):
                        checks["pricing_hours_per_month_calc"] = True

                # supply budget
                supply_per_visit = to_float(pricing.get("supply_budget_per_visit"))
                monthly_supply = to_float(pricing.get("monthly_supply_budget"))
                supply_pct = to_float(pricing.get("supply_pct_of_revenue"))

                if supply_per_visit is not None and 5 - 1e-9 <= supply_per_visit <= 20 + 1e-9:
                    checks["pricing_supply_budget_in_range"] = True

                if None not in (supply_per_visit, visits_pm, monthly_supply):
                    if approx_equal(monthly_supply, supply_per_visit * visits_pm, 2.00):
                        checks["pricing_monthly_supply_budget_calc"] = True

                if None not in (monthly_supply, total_monthly, supply_pct) and total_monthly not in (0, None):
                    expected_pct = (monthly_supply / total_monthly) * 100.0
                    if 5 - 1e-9 <= supply_pct <= 8 + 1e-9 and abs(supply_pct - expected_pct) <= 0.5:
                        checks["pricing_supply_pct_in_range"] = True

                # labor plan validity
                labor_plan = pricing.get("labor_plan")
                labor_ok = False
                if isinstance(labor_plan, list) and len(labor_plan) > 0:
                    labor_ok = True
                    for item in labor_plan:
                        if not isinstance(item, dict):
                            labor_ok = False
                            break
                        role = item.get("role")
                        headcount = item.get("headcount")
                        rate = item.get("hourly_rate")
                        if not role or not is_int_value(headcount) or to_float(headcount) < 1:
                            labor_ok = False
                            break
                        rate_f = to_float(rate)
                        # Accept broad reasonable range for industry roles
                        if rate_f is None or not (14 <= rate_f <= 30):
                            labor_ok = False
                            break
                if labor_ok:
                    checks["pricing_labor_plan_valid"] = True

            except Exception:
                pass

    # 2) Validate output/qc_checklist.csv
    qc_path = os.path.join(output_dir, "qc_checklist.csv")
    headers, rows = parse_csv_dicts(qc_path)
    if headers is not None and rows is not None:
        checks["has_qc_csv"] = True
        # Validate headers (case-insensitive, order-insensitive)
        required_cols = ["area", "criteria", "score_scale_min", "score_scale_max", "target_average"]
        hdr_map = {h.lower().strip(): h for h in headers}
        if all(col in hdr_map for col in required_cols):
            checks["qc_header_valid"] = True

            # Exactly 7 rows with specific areas
            expected_areas = set([
                "floors",
                "surfaces",
                "restrooms",
                "trash",
                "windows/glass",
                "kitchen/break room",
                "overall appearance"
            ])
            if len(rows) == 7:
                checks["qc_rows_count"] = True

            present_areas = set()
            areas_ok = True
            scales_ok = True
            for r in rows:
                # Access with case-insensitive keys
                def get_val(row, key):
                    for k in row:
                        if k.lower().strip() == key:
                            return row[k]
                    return None

                area = (get_val(r, "area") or "").strip().lower()
                present_areas.add(area)

                smin = to_float(get_val(r, "score_scale_min"))
                smax = to_float(get_val(r, "score_scale_max"))
                targ = to_float(get_val(r, "target_average"))
                if smin != 1 or smax != 5 or (targ is None or targ < 4.5):
                    scales_ok = False

            if present_areas == expected_areas:
                checks["qc_areas_complete"] = True
            if scales_ok:
                checks["qc_scales_and_targets"] = True

    # 3) Validate output/kpis.json
    kpis_path = os.path.join(output_dir, "kpis.json")
    kpis = read_json(kpis_path)
    if isinstance(kpis, list):
        checks["has_kpis_json"] = True
        # Must be length 10
        if len(kpis) == 10:
            checks["kpis_length_10"] = True
        # Validate structure and names
        names_norm = []
        structure_ok = True
        for item in kpis:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if "name" not in item or "target" not in item:
                structure_ok = False
                break
            names_norm.append(normalize_name(str(item["name"])))
        if structure_ok:
            # Required names presence
            # Define required KPI identifiers as substrings/keyword tuples
            required_name_specs = [
                "revenue per labor hour",
                "client retention rate",
                "complaint rate",
                "employee turnover",
                ("supply cost", "revenue"),
                ("close rate", "bid"),
                "average job value",
                ("drive time", "work time"),
                "rebooking rate",
                "revenue per client per year",
            ]
            all_present = True
            for spec in required_name_specs:
                if not kpi_name_present(spec, names_norm):
                    all_present = False
                    break
            if all_present:
                checks["kpis_required_names_present"] = True

            # Find specific targets
            # Revenue per labor hour target must indicate 45–65
            rplh_ok = False
            supply_ok = False
            for item in kpis:
                name_n = normalize_name(str(item.get("name", "")))
                target = item.get("target", "")
                if "revenue per labor hour" in name_n:
                    if revenue_per_labor_hour_target_ok(str(target)):
                        rplh_ok = True
                if ("supply cost" in name_n) and ("revenue" in name_n):
                    if supply_target_ok(str(target)):
                        supply_ok = True
            if rplh_ok:
                checks["kpis_revenue_per_labor_hour_target_ok"] = True
            if supply_ok:
                checks["kpis_supply_cost_target_ok"] = True

    # 4) Validate output/proposal.md
    proposal_path = os.path.join(output_dir, "proposal.md")
    proposal_text = read_text(proposal_path)
    if isinstance(proposal_text, str):
        checks["has_proposal_md"] = True
        text_lc = proposal_text.lower()
        # Normalize curly quotes for certain phrases
        text_norm = text_lc.replace("’", "'").replace("“", '"').replace("”", '"')

        phrases_ok = True
        required_any_green = any(x in text_norm for x in ["issa cims", "green seal", "leed"])
        required_phrases = [
            "osha",
            # Either "Safety Data Sheets" or "SDS"
            # We will handle separately
            "hazard communication",
            "ppe",
            "general liability",
            # Workers' comp may have curly or straight apostrophe; we normalized above
            "workers' comp",
            "surety bond",
            "umbrella",
            "respond within 2 hours",
            "re-clean within 24 hours",
        ]
        # Check main phrases (excluding SDS which is handled specially)
        for p in required_phrases:
            if p not in text_norm:
                phrases_ok = False
                break
        # SDS check
        if not (("safety data sheets" in text_norm) or ("sds" in text_norm)):
            phrases_ok = False
        if not required_any_green:
            phrases_ok = False

        if phrases_ok:
            checks["proposal_contains_required_phrases"] = True

        # Include numeric total monthly price (rounded to nearest dollar)
        total_monthly = None
        if isinstance(pricing, dict):
            total_monthly = to_float(pricing.get("total_monthly_price"))
        price_included = False
        if total_monthly is not None:
            if contains_number_variants(text_norm, total_monthly):
                price_included = True
        if price_included:
            checks["proposal_contains_total_monthly_price"] = True

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Ensure baseline: if output directory missing or empty, reward must be 0.0 by virtue of checks False
    out = {"reward": float(reward)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()