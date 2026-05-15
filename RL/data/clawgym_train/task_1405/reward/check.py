import json
import os
import sys
import csv
import re
from statistics import median

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    x = str(x).strip().replace(",", "")
    if x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None

def parse_int(x):
    f = parse_float(x)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None

def parse_bool(x):
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    s = str(x).strip().lower()
    if s in ("true", "yes", "y", "1", "t"):
        return True
    if s in ("false", "no", "n", "0", "f"):
        return False
    return False

def round_money(val):
    if val is None:
        return None
    # Round to nearest dollar
    return int(round(float(val)))

def round_2(val):
    if val is None:
        return None
    return round(float(val), 2)

def get_first_present(d, keys):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None

def get_living_area(subject):
    # Try common keys for living area in sqft
    keys = [
        "living_area_sqft", "living_area", "sqft", "area_sqft", "size_sqft", "size", "gross_living_area_sqft"
    ]
    val = get_first_present(subject, keys)
    return parse_float(val)

def get_lot_size_sqft(obj):
    keys = ["lot_size_sqft", "lot_sqft", "lot_size", "lot_area_sqft"]
    val = get_first_present(obj, keys)
    return parse_float(val)

def get_bedrooms(obj):
    keys = ["bedrooms", "beds", "br"]
    val = get_first_present(obj, keys)
    return parse_float(val)

def get_bathrooms_components(obj):
    # Returns (full_baths, half_baths, total_baths_if_available)
    full_keys = ["bathrooms_full", "full_baths", "baths_full"]
    half_keys = ["bathrooms_half", "half_baths", "baths_half"]
    total_keys = ["bathrooms_total", "baths_total"]
    full = get_first_present(obj, full_keys)
    half = get_first_present(obj, half_keys)
    total = get_first_present(obj, total_keys)
    # Also consider 'bathrooms' or 'baths' as either total or full with decimals
    if total is None:
        total_val = get_first_present(obj, ["bathrooms", "baths"])
        # If it's a decimal (e.g., 2.5), treat as total
        if total_val is not None:
            try:
                f = float(total_val)
                # If both full and half present, we will use components; else treat as total
                if full is None and half is None:
                    total = f
            except Exception:
                pass
    full = parse_float(full) if full is not None else None
    half = parse_float(half) if half is not None else None
    total = parse_float(total) if total is not None else None
    return full, half, total

def compute_total_baths(full, half, total, half_weight):
    if total is not None and full is None and half is None:
        return float(total)
    f = full if full is not None else 0.0
    h = half if half is not None else 0.0
    if half is None and total is not None and full is not None:
        # If both total and full are known but half is None, infer half assuming total = full + half*half_weight
        # half = (total - full) / half_weight
        try:
            h = max(0.0, (float(total) - float(f)) / (half_weight if half_weight else 0.5))
        except Exception:
            h = 0.0
    hw = half_weight if half_weight is not None else 0.5
    return float(f) + float(h) * float(hw)

def get_condition(obj):
    keys = ["condition", "property_condition"]
    val = get_first_present(obj, keys)
    if isinstance(val, str):
        return val.strip().lower()
    return None

def get_year_built(obj):
    keys = ["year_built", "built_year"]
    val = get_first_present(obj, keys)
    return parse_int(val)

def get_distance_miles(row):
    keys = ["distance_miles", "dist_miles", "distance"]
    val = get_first_present(row, keys)
    return parse_float(val)

def safe_lower(s):
    return s.lower() if isinstance(s, str) else s

def read_comps_csv(path):
    comps = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            comps.append({k.strip(): v.strip() if isinstance(v, str) else v for k, v in r.items()})
    return comps

def percent_from_value(v):
    # interpret v as decimal fraction if <=1.0, else as percent (e.g., 5 -> 0.05)
    if v is None:
        return 0.0
    f = parse_float(v)
    if f is None:
        return 0.0
    if abs(f) > 1.0:
        return f / 100.0
    return f

def compute_adjustments(policy, subject, comp_row):
    # Extract parameters
    adj_cfg = policy.get("adjustments", {})
    # Bedrooms
    subj_bed = get_bedrooms(subject) or 0.0
    comp_bed = get_bedrooms(comp_row) or 0.0
    bed_cfg = adj_cfg.get("bedrooms", {})
    bed_factor = bed_cfg.get("per_unit_percent") or bed_cfg.get("percent_per_bedroom") or 0.0
    bed_dir = bed_cfg.get("direction") or "more_is_better"
    bed_diff = subj_bed - comp_bed
    if bed_dir == "more_is_better":
        bedrooms_percent = bed_diff * bed_factor
    elif bed_dir == "less_is_better":
        bedrooms_percent = -bed_diff * bed_factor
    else:
        # default to subject - comp times factor
        bedrooms_percent = bed_diff * bed_factor

    # Bathrooms with half-baths
    bath_cfg = adj_cfg.get("bathrooms", {})
    bath_factor = bath_cfg.get("per_unit_percent") or bath_cfg.get("percent_per_bathroom") or 0.0
    half_weight = bath_cfg.get("half_bath_weight", 0.5)
    bath_dir = bath_cfg.get("direction") or "more_is_better"
    s_full, s_half, s_total = get_bathrooms_components(subject)
    c_full, c_half, c_total = get_bathrooms_components(comp_row)
    subj_baths = compute_total_baths(s_full, s_half, s_total, half_weight) if (s_full is not None or s_half is not None or s_total is not None) else 0.0
    comp_baths = compute_total_baths(c_full, c_half, c_total, half_weight) if (c_full is not None or c_half is not None or c_total is not None) else 0.0
    bath_diff = subj_baths - comp_baths
    if bath_dir == "more_is_better":
        bathrooms_percent = bath_diff * bath_factor
    elif bath_dir == "less_is_better":
        bathrooms_percent = -bath_diff * bath_factor
    else:
        bathrooms_percent = bath_diff * bath_factor

    # Age or Year Built
    age_cfg = adj_cfg.get("age", {})
    age_per_year = age_cfg.get("per_year_percent") or 0.0
    age_attr = age_cfg.get("attribute") or "year_built"
    age_dir = age_cfg.get("direction") or "newer_is_better"  # typical
    if age_attr == "age_years":
        subj_age = parse_float(get_first_present(subject, ["age_years", "age"])) or None
        comp_age = parse_float(get_first_present(comp_row, ["age_years", "age"])) or None
        if subj_age is None or comp_age is None:
            # fallback via year_built if ages not provided
            sy = get_year_built(subject)
            cy = get_year_built(comp_row)
            subj_age = None
            comp_age = None
            if sy is not None and cy is not None:
                # relative difference using year built difference
                # age difference in years is -(year_built difference)
                # subject older (higher age) == lower year_built
                # We'll compute consistently with direction using year difference
                year_diff = (sy - cy)
                # If attribute requested age_years, then age_diff = (current - sy) - (current - cy) = cy - sy = -(sy - cy)
                age_diff = (cy - sy)
                if age_dir == "less_is_better":
                    age_percent = -age_diff * age_per_year  # less age is better
                elif age_dir == "more_is_better":
                    age_percent = age_diff * age_per_year
                else:
                    age_percent = -age_diff * age_per_year
            else:
                age_percent = 0.0
        else:
            age_diff = (subj_age - comp_age)
            if age_dir == "less_is_better":
                age_percent = -age_diff * age_per_year  # less age is better
            elif age_dir == "more_is_better":
                age_percent = age_diff * age_per_year
            else:
                age_percent = -age_diff * age_per_year
    else:
        # Use year_built difference, newer is better (higher year better)
        sy = get_year_built(subject)
        cy = get_year_built(comp_row)
        if sy is None or cy is None:
            age_percent = 0.0
        else:
            ydiff = (sy - cy)
            if age_dir in ("newer_is_better", "more_is_better"):
                age_percent = ydiff * age_per_year
            elif age_dir in ("older_is_better", "less_is_better"):
                age_percent = -ydiff * age_per_year
            else:
                age_percent = ydiff * age_per_year

    # Condition
    cond_cfg = adj_cfg.get("condition", {})
    subj_cond = get_condition(subject)
    comp_cond = get_condition(comp_row)
    condition_percent = 0.0
    if subj_cond is not None and comp_cond is not None:
        levels_order = cond_cfg.get("levels_order")
        per_level = cond_cfg.get("per_level_percent")
        level_map_percent = cond_cfg.get("level_mapping_percent")
        if isinstance(levels_order, list) and per_level is not None:
            so = [safe_lower(x) for x in levels_order]
            try:
                si = so.index(safe_lower(subj_cond))
                ci = so.index(safe_lower(comp_cond))
                diff_levels = si - ci
                condition_percent = diff_levels * float(per_level)
            except Exception:
                condition_percent = 0.0
        elif isinstance(level_map_percent, dict):
            s_map = {safe_lower(k): float(v) for k, v in level_map_percent.items()}
            if safe_lower(subj_cond) in s_map and safe_lower(comp_cond) in s_map:
                condition_percent = s_map[safe_lower(subj_cond)] - s_map[safe_lower(comp_cond)]
            else:
                condition_percent = 0.0
        else:
            condition_percent = 0.0

    # Lot size per 1000 sqft
    lot_cfg = adj_cfg.get("lot_size", {})
    lot_factor = lot_cfg.get("per_1000_sqft_percent") or 0.0
    lot_dir = lot_cfg.get("direction") or "more_is_better"
    subj_lot = get_lot_size_sqft(subject) or 0.0
    comp_lot = get_lot_size_sqft(comp_row) or 0.0
    lot_diff_thousands = (subj_lot - comp_lot) / 1000.0 if (subj_lot is not None and comp_lot is not None) else 0.0
    if lot_dir == "more_is_better":
        lot_size_percent = lot_diff_thousands * lot_factor
    elif lot_dir == "less_is_better":
        lot_size_percent = -lot_diff_thousands * lot_factor
    else:
        lot_size_percent = lot_diff_thousands * lot_factor

    # Pool
    pool_cfg = adj_cfg.get("pool", {})
    pool_percent_unit = pool_cfg.get("percent") or 0.0
    pool_dir = pool_cfg.get("direction") or "has_pool_is_better"
    subj_pool = parse_bool(get_first_present(subject, ["pool", "has_pool", "pool_present"]))
    comp_pool = parse_bool(get_first_present(comp_row, ["pool", "has_pool", "pool_present"]))
    if pool_dir == "has_pool_is_better":
        if subj_pool and not comp_pool:
            pool_percent = pool_percent_unit
        elif (not subj_pool) and comp_pool:
            pool_percent = -pool_percent_unit
        else:
            pool_percent = 0.0
    else:
        # Fallback: positive when subject has vs comp
        pool_percent = (1 if (subj_pool and not comp_pool) else (-1 if ((not subj_pool) and comp_pool) else 0)) * pool_percent_unit

    # Location from comp row
    loc_val = get_first_present(comp_row, ["location_percent", "location_adj", "loc_percent"])
    location_percent = percent_from_value(parse_float(loc_val))

    # Round individual percents to two decimals
    bedrooms_percent = round_2(bedrooms_percent)
    bathrooms_percent = round_2(bathrooms_percent)
    age_percent = round_2(age_percent)
    condition_percent = round_2(condition_percent)
    lot_size_percent = round_2(lot_size_percent)
    pool_percent = round_2(pool_percent)
    location_percent = round_2(location_percent)

    total_percent = round_2(
        (bedrooms_percent or 0.0)
        + (bathrooms_percent or 0.0)
        + (age_percent or 0.0)
        + (condition_percent or 0.0)
        + (lot_size_percent or 0.0)
        + (pool_percent or 0.0)
        + (location_percent or 0.0)
    )

    return {
        "bedrooms_percent": bedrooms_percent or 0.0,
        "bathrooms_percent": bathrooms_percent or 0.0,
        "age_percent": age_percent or 0.0,
        "condition_percent": condition_percent or 0.0,
        "lot_size_percent": lot_size_percent or 0.0,
        "pool_percent": pool_percent or 0.0,
        "location_percent": location_percent or 0.0,
        "total_percent": total_percent or 0.0
    }

def comps_approach_value(policy, adjusted_prices, comp_ids=None, abs_total_percents=None):
    cfg = policy.get("comps_approach", policy.get("comps", {}))
    method = (cfg.get("method") or "median").lower()
    if not adjusted_prices:
        return None, cfg.get("method") or "median"
    if method == "median":
        val = round_money(median(adjusted_prices))
        return val, "median"
    if method in ("mean", "average"):
        avg = sum(adjusted_prices) / len(adjusted_prices)
        return round_money(avg), "average" if method == "average" else "mean"
    if method == "weighted_average":
        weights = cfg.get("weights")
        if isinstance(weights, dict) and comp_ids is not None:
            # Map weights by comp_id
            w_list = []
            for cid in comp_ids:
                w = parse_float(weights.get(str(cid))) if cid in weights else parse_float(weights.get(cid))
                if w is None:
                    w = 0.0
                w_list.append(float(w))
        elif isinstance(weights, list):
            w_list = [parse_float(w) or 0.0 for w in weights]
        elif isinstance(weights, dict) and weights.get("type") == "inverse_abs_adjustment" and abs_total_percents is not None:
            w_list = []
            for a in abs_total_percents:
                w_list.append(1.0 / a if a and a != 0 else 0.0)
        else:
            # default equal weights
            w_list = [1.0] * len(adjusted_prices)
        total_w = sum(w_list)
        if total_w == 0:
            avg = sum(adjusted_prices) / len(adjusted_prices)
            return round_money(avg), "weighted_average"
        wa = sum(p * w for p, w in zip(adjusted_prices, w_list)) / total_w
        return round_money(wa), "weighted_average"
    # Fallback to median
    val = round_money(median(adjusted_prices))
    return val, "median"

def compute_income_value(income_json):
    monthly_rent = parse_float(income_json.get("monthly_rent")) or 0.0
    op_exp_rate = parse_float(income_json.get("operating_expense_rate")) or 0.0
    cap_rate = parse_float(income_json.get("cap_rate")) or 0.0
    noi = monthly_rent * 12.0 * (1.0 - op_exp_rate)
    value = None
    if cap_rate and cap_rate != 0:
        value = noi / cap_rate
    return round_2(noi), cap_rate, round_money(value) if value is not None else None

def compute_cost_value(cost_json):
    land_value = parse_float(cost_json.get("land_value")) or 0.0
    rcn = parse_float(cost_json.get("replacement_cost_new")) or 0.0
    dep = parse_float(cost_json.get("depreciation_percent")) or 0.0
    if abs(dep) > 1.0:
        dep = dep / 100.0
    value = land_value + rcn * (1.0 - dep)
    return round_money(land_value), round_money(rcn), round_2(dep), round_money(value)

def compute_reconciliation(policy, comps_val, income_val, cost_val):
    rec = policy.get("reconciliation", {})
    weights = rec.get("weights", policy.get("weights", {}))
    w_comps = parse_float(weights.get("comps")) if isinstance(weights, dict) else None
    w_income = parse_float(weights.get("income")) if isinstance(weights, dict) else None
    w_cost = parse_float(weights.get("cost")) if isinstance(weights, dict) else None
    # Default to 0 if missing (though policy should provide)
    w_comps = w_comps if w_comps is not None else 0.0
    w_income = w_income if w_income is not None else 0.0
    w_cost = w_cost if w_cost is not None else 0.0
    final_estimate = (comps_val or 0.0) * w_comps + (income_val or 0.0) * w_income + (cost_val or 0.0) * w_cost
    final_estimate_rounded = round_money(final_estimate)
    range_percent = rec.get("range_percent", policy.get("range_percent", 0.0))
    if abs(range_percent) > 1.0:
        range_percent = range_percent / 100.0
    low = round_money(final_estimate_rounded * (1.0 - range_percent))
    high = round_money(final_estimate_rounded * (1.0 + range_percent))
    return {
        "weights": {"comps": w_comps, "income": w_income, "cost": w_cost},
        "final_estimate": final_estimate_rounded,
        "range_percent": range_percent,
        "low": low,
        "high": high
    }

def determine_confidence(policy, comps_rows, abs_total_percents):
    # Generic deterministic rules
    conf_cfg = policy.get("confidence_rules") or policy.get("confidence_thresholds") or policy.get("confidence", {})
    # Normalize to dict with High/Medium/Low keys if possible
    # Accept both cases
    def get_level(cfg, name):
        for k, v in cfg.items():
            if k.lower() == name.lower():
                return v
        return {}
    high = get_level(conf_cfg, "high")
    med = get_level(conf_cfg, "medium")
    low = get_level(conf_cfg, "low")
    # Compute metrics
    n = len(comps_rows)
    distances = []
    for row in comps_rows:
        distances.append(get_distance_miles(row))
    within_count = {}
    def count_within(max_d):
        if max_d is None:
            return n
        cnt = 0
        for d in distances:
            if d is None:
                # If no distance provided, we cannot count it positively; be conservative
                continue
            if d <= max_d:
                cnt += 1
        return cnt
    def abs_adj_ok(max_abs):
        if max_abs is None:
            return True
        for a in abs_total_percents:
            if a is None:
                return False
            if a > max_abs:
                return False
        return True

    # Evaluate High
    maxd = parse_float(high.get("max_distance_miles")) if high else None
    min_comps = int(parse_int(high.get("min_comps"))) if high and high.get("min_comps") is not None else None
    min_within = int(parse_int(high.get("min_within_distance"))) if high and high.get("min_within_distance") is not None else None
    max_abs = parse_float(high.get("max_abs_total_adjustment")) if high else None
    conds = []
    if min_comps is not None:
        conds.append(n >= min_comps)
    if min_within is not None:
        conds.append(count_within(maxd) >= min_within)
    elif maxd is not None:
        # If only max_distance_miles present, require all comps within
        conds.append(count_within(maxd) == n)
    if max_abs is not None:
        conds.append(abs_adj_ok(max_abs))
    if all(conds) and (conds != []):
        return "High"

    # Evaluate Medium
    maxd = parse_float(med.get("max_distance_miles")) if med else None
    min_comps = int(parse_int(med.get("min_comps"))) if med and med.get("min_comps") is not None else None
    min_within = int(parse_int(med.get("min_within_distance"))) if med and med.get("min_within_distance") is not None else None
    max_abs = parse_float(med.get("max_abs_total_adjustment")) if med else None
    conds = []
    if min_comps is not None:
        conds.append(n >= min_comps)
    if min_within is not None:
        conds.append(count_within(maxd) >= min_within)
    elif maxd is not None:
        conds.append(count_within(maxd) == n)
    if max_abs is not None:
        conds.append(abs_adj_ok(max_abs))
    if all(conds) and (conds != []):
        return "Medium"

    # If low is defined explicitly with conditions, we could check, otherwise default Low
    return "Low"

def approx_equal(a, b, tol):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_report_file": False,
        "report_schema_valid": False,
        "comps_adjustments_valid": False,
        "comps_approach_valid": False,
        "income_valid": False,
        "cost_valid": False,
        "reconciliation_valid": False,
        "ppsf_valid": False,
        "confidence_valid": False,
        "market_context_valid": False,
        "has_summary_file": False,
        "summary_format_valid": False,
        "summary_matches_final": False
    }

    # Paths
    prop_path = os.path.join(input_dir, "property.json")
    comps_path = os.path.join(input_dir, "comps.csv")
    policy_path = os.path.join(input_dir, "adjustment_policy.json")
    income_path = os.path.join(input_dir, "income.json")
    cost_path = os.path.join(input_dir, "cost.json")
    market_path = os.path.join(input_dir, "market.json")

    report_path = os.path.join(output_dir, "report.json")
    summary_path = os.path.join(output_dir, "summary.txt")

    # Load inputs
    try:
        prop_json = load_json(prop_path)
        comps_rows = read_comps_csv(comps_path)
        policy_json = load_json(policy_path)
        income_json = load_json(income_path)
        cost_json = load_json(cost_path)
        market_json = load_json(market_path)
    except Exception:
        # If inputs cannot be read, no positive checks should be awarded (they depend on output anyway)
        pass

    report = None
    if os.path.isfile(report_path):
        checks["has_report_file"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            report = None

    # Schema validation
    if report is not None and isinstance(report, dict):
        required_top = [
            "subject", "comps", "comps_approach", "income_approach",
            "cost_approach", "reconciliation", "price_per_sqft",
            "confidence", "market_context"
        ]
        has_all = all(k in report for k in required_top)
        comps_ok = isinstance(report.get("comps"), list)
        comps_subkeys_ok = True
        if comps_ok:
            for c in report["comps"]:
                req_adj_keys = ["bedrooms_percent", "bathrooms_percent", "age_percent",
                                "condition_percent", "lot_size_percent", "pool_percent",
                                "location_percent", "total_percent"]
                if not isinstance(c, dict):
                    comps_subkeys_ok = False
                    break
                if "comp_id" not in c or "sale_price" not in c or "adjustments" not in c or "adjusted_price" not in c:
                    comps_subkeys_ok = False
                    break
                adj = c.get("adjustments")
                if not isinstance(adj, dict) or not all(k in adj for k in req_adj_keys):
                    comps_subkeys_ok = False
                    break
        comps_approach_ok = isinstance(report.get("comps_approach"), dict) and "method" in report.get("comps_approach", {}) and "value" in report.get("comps_approach", {})
        income_ok = isinstance(report.get("income_approach"), dict) and all(k in report["income_approach"] for k in ["noi", "cap_rate", "value"])
        cost_ok = isinstance(report.get("cost_approach"), dict) and all(k in report["cost_approach"] for k in ["land_value", "replacement_cost_new", "depreciation_percent", "value"])
        rec_ok = isinstance(report.get("reconciliation"), dict) and "weights" in report["reconciliation"] and "final_estimate" in report["reconciliation"] and "value_range" in report["reconciliation"]
        ppsf_ok = isinstance(report.get("price_per_sqft"), dict) and all(k in report["price_per_sqft"] for k in ["subject_sqft", "final_ppsf", "neighborhood_ppsf_avg", "difference"])
        conf_ok = isinstance(report.get("confidence"), str)
        market_ok = isinstance(report.get("market_context"), str)
        if has_all and comps_ok and comps_subkeys_ok and comps_approach_ok and income_ok and cost_ok and rec_ok and ppsf_ok and conf_ok and market_ok:
            checks["report_schema_valid"] = True

    # Proceed with deeper checks only if schema valid
    expected_adjusted_prices = []
    abs_total_percents = []
    comp_ids_in_output = []
    if checks["report_schema_valid"]:
        # Verify subject matches input exactly
        # We do not score this separately but rely on subsequent computations
        # Compute expected adjustments and compare per comp
        comps_out = report["comps"]
        per_comp_ok = True
        for c in comps_out:
            comp_id = str(c.get("comp_id"))
            comp_ids_in_output.append(comp_id)
            # Find the corresponding comp row by comp_id if available, else by index order
            row = None
            # Try to match by comp_id field in CSV
            for r in comps_rows:
                rid = get_first_present(r, ["comp_id", "id", "comp"])
                if rid is not None and str(rid) == comp_id:
                    row = r
                    break
            if row is None:
                # Try match by sale_price if unique
                row = None
                for r in comps_rows:
                    sp = parse_float(get_first_present(r, ["sale_price", "price"]))
                    if approx_equal(sp, c.get("sale_price"), 1.0):
                        row = r
                        break
            if row is None:
                per_comp_ok = False
                break
            expected_adj = compute_adjustments(policy_json, prop_json, row)
            # Compare each percent within ±0.01
            adj_out = c.get("adjustments", {}) or {}
            all_keys = ["bedrooms_percent", "bathrooms_percent", "age_percent",
                        "condition_percent", "lot_size_percent", "pool_percent",
                        "location_percent", "total_percent"]
            for k in all_keys:
                out_val = parse_float(adj_out.get(k))
                exp_val = expected_adj.get(k)
                if not approx_equal(out_val, exp_val, 0.01):
                    per_comp_ok = False
                    break
            if not per_comp_ok:
                break
            # Compute adjusted price using sale_price and total_percent (rounded)
            sale_price_in_csv = parse_float(get_first_present(row, ["sale_price", "price"])) or 0.0
            sale_price_out = parse_float(c.get("sale_price"))
            # Sale price should match input within $1
            if not approx_equal(sale_price_out, sale_price_in_csv, 1.0):
                per_comp_ok = False
                break
            adjusted_expected = round_money(sale_price_in_csv * (1.0 + expected_adj["total_percent"]))
            expected_adjusted_prices.append(adjusted_expected)
            abs_total_percents.append(abs(expected_adj["total_percent"]))
            if not approx_equal(parse_float(c.get("adjusted_price")), adjusted_expected, 1.0):
                per_comp_ok = False
                break
        checks["comps_adjustments_valid"] = per_comp_ok

        # Comps approach verification
        comps_method_expected, method_label = None, None
        try:
            comps_method_expected, method_label = comps_approach_value(policy_json, expected_adjusted_prices, comp_ids_in_output, abs_total_percents)
        except Exception:
            comps_method_expected, method_label = None, None
        comps_approach_out = report.get("comps_approach", {})
        method_out = str(comps_approach_out.get("method")) if comps_approach_out.get("method") is not None else None
        comps_value_out = parse_float(comps_approach_out.get("value"))
        # Method comparison: normalize lower case
        method_policy = (policy_json.get("comps_approach", {}).get("method") or "median")
        if comps_method_expected is not None and method_out is not None:
            method_match = str(method_out).lower() == str(method_policy).lower()
        else:
            method_match = False
        value_match = approx_equal(comps_value_out, comps_method_expected, 1.0) if comps_method_expected is not None else False
        checks["comps_approach_valid"] = method_match and value_match

        # Income approach
        noi_exp, cap_rate, income_val_exp = compute_income_value(income_json)
        income_out = report.get("income_approach", {})
        noi_out = parse_float(income_out.get("noi"))
        cap_out = parse_float(income_out.get("cap_rate"))
        val_out = parse_float(income_out.get("value"))
        income_ok = approx_equal(noi_out, noi_exp, 0.01) and approx_equal(cap_out, cap_rate, 1e-12) and approx_equal(val_out, income_val_exp, 1.0)
        checks["income_valid"] = income_ok

        # Cost approach
        land_exp, rcn_exp, dep_exp, cost_val_exp = compute_cost_value(cost_json)
        cost_out = report.get("cost_approach", {})
        land_out = parse_float(cost_out.get("land_value"))
        rcn_out = parse_float(cost_out.get("replacement_cost_new"))
        dep_out = parse_float(cost_out.get("depreciation_percent"))
        if dep_out is not None and abs(dep_out) > 1.0:
            dep_out = dep_out / 100.0
        val_cost_out = parse_float(cost_out.get("value"))
        cost_ok = approx_equal(land_out, land_exp, 1.0) and approx_equal(rcn_out, rcn_exp, 1.0) and approx_equal(dep_out, dep_exp, 0.01) and approx_equal(val_cost_out, cost_val_exp, 1.0)
        checks["cost_valid"] = cost_ok

        # Reconciliation
        comps_val_used = comps_method_expected if comps_method_expected is not None else None
        income_val_used = income_val_exp
        cost_val_used = cost_val_exp
        rec_expected = compute_reconciliation(policy_json, comps_val_used, income_val_used, cost_val_used)
        rec_out = report.get("reconciliation", {})
        weights_out = rec_out.get("weights", {})
        w_comps_out = parse_float(weights_out.get("comps"))
        w_income_out = parse_float(weights_out.get("income"))
        w_cost_out = parse_float(weights_out.get("cost"))
        final_out = parse_float(rec_out.get("final_estimate"))
        vr = rec_out.get("value_range", {}) or {}
        low_out = parse_float(vr.get("low"))
        high_out = parse_float(vr.get("high"))
        rp_out = parse_float(vr.get("range_percent"))
        rec_ok = (
            approx_equal(w_comps_out, rec_expected["weights"]["comps"], 1e-9)
            and approx_equal(w_income_out, rec_expected["weights"]["income"], 1e-9)
            and approx_equal(w_cost_out, rec_expected["weights"]["cost"], 1e-9)
            and approx_equal(final_out, rec_expected["final_estimate"], 1.0)
            and approx_equal(low_out, rec_expected["low"], 1.0)
            and approx_equal(high_out, rec_expected["high"], 1.0)
            and approx_equal(rp_out, rec_expected["range_percent"], 1e-9)
        )
        checks["reconciliation_valid"] = rec_ok

        # Price per sqft
        subject_sqft = get_living_area(prop_json) or 0.0
        ppsf_out = report.get("price_per_sqft", {}) or {}
        subject_sqft_out = parse_float(ppsf_out.get("subject_sqft"))
        final_ppsf_out = parse_float(ppsf_out.get("final_ppsf"))
        nb_avg = parse_float(market_json.get("price_per_sqft")) or parse_float(market_json.get("neighborhood_price_per_sqft"))
        nb_avg_out = parse_float(ppsf_out.get("neighborhood_ppsf_avg"))
        final_estimate_used = rec_expected["final_estimate"]
        final_ppsf_expected = round_2((final_estimate_used / subject_sqft) if subject_sqft else 0.0)
        diff_out = parse_float(ppsf_out.get("difference"))
        diff_expected = round_2(final_ppsf_expected - (nb_avg if nb_avg is not None else 0.0))
        ppsf_ok = approx_equal(subject_sqft_out, subject_sqft, 0.01) and approx_equal(final_ppsf_out, final_ppsf_expected, 0.01) and approx_equal(nb_avg_out, nb_avg, 0.01) and approx_equal(diff_out, diff_expected, 0.01)
        checks["ppsf_valid"] = ppsf_ok

        # Confidence
        conf_out = report.get("confidence")
        confidence_expected = determine_confidence(policy_json, comps_rows, abs_total_percents)
        checks["confidence_valid"] = (str(conf_out) == str(confidence_expected))

        # Market context
        mc_in = market_json.get("market_context") or market_json.get("market_condition")
        checks["market_context_valid"] = (report.get("market_context") == mc_in)

    # Summary checks
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
        except Exception:
            lines = []
        if len(lines) >= 2:
            line1 = lines[0]
            line2 = lines[1]
            m1 = re.match(r"^Final Estimate: \$[0-9,]+$", line1 or "")
            m2 = re.match(r"^Confidence: (High|Medium|Low)$", line2 or "")
            if m1 and m2:
                checks["summary_format_valid"] = True
                # Compare amount with reconciliation.final_estimate
                amt_str = line1.split("$", 1)[1].replace(",", "")
                try:
                    amt_val = int(amt_str)
                except Exception:
                    amt_val = None
                rep_final = None
                if checks["report_schema_valid"]:
                    rep_final = parse_int(report.get("reconciliation", {}).get("final_estimate"))
                checks["summary_matches_final"] = (amt_val is not None and rep_final is not None and amt_val == rep_final)

    # Compute reward as fraction of passed checks
    total_checks = len([k for k in checks.keys()])
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no outputs, reward must be 0.0
    if not checks["has_report_file"] and not checks["has_summary_file"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()