import json
import os
import sys
import csv
from datetime import datetime

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def parse_simple_yaml(path):
    """
    Minimal YAML parser for a limited, known structure:
    - key: value pairs
    - lists with '- value'
    - nested dicts one level via indentation (e.g., target_promo_window: \n  start_date: 2026-07-01)
    Assumes no complex YAML types.
    """
    result = {}
    stack = [(0, result)]
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for raw in lines:
        line = raw.rstrip("\n")
        # Strip comments
        if "#" in line:
            # Keep text before # unless it's in a value; naive approach: split on first '#'
            idx = line.find("#")
            before = line[:idx]
            if before.strip() == "":
                line = ""
            else:
                line = before.rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")

        # Adjust stack based on indentation
        while stack and indent < stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1]

        if content.startswith("- "):
            # list item
            item = content[2:].strip()
            # infer type
            val = parse_scalar(item)
            # find last key that is a list
            # if current_dict is a list, append; else need to locate a list in parent context
            if isinstance(current_dict, list):
                current_dict.append(val)
            else:
                # we need to append to a list tied to a previous key; this simplistic parser expects:
                # key:
                #   - item
                # so current_dict should contain the last inserted key that is a list
                # attempt to find last key that maps to a list
                list_key = None
                for k in reversed(list(current_dict.keys())):
                    if isinstance(current_dict[k], list):
                        list_key = k
                        break
                if list_key is None:
                    # create an anonymous list? Not expected; skip
                    continue
                current_dict[list_key].append(val)
            continue

        if ":" in content:
            key, val = content.split(":", 1)
            key = key.strip()
            val_str = val.strip()
            if val_str == "":
                # start a nested dict or list under this key
                # peek next line to decide if it's a list or dict; but we will default to dict here
                new_container = {}
                current_dict[key] = new_container
                stack.append((indent + 2, new_container))
            else:
                # scalar value
                current_dict[key] = parse_scalar(val_str)
        else:
            # Unrecognized format; skip
            continue

    return result

def parse_scalar(s):
    # Try to parse as number, boolean, null, else return string (strip quotes)
    s_strip = s.strip()
    if s_strip.lower() in ("true", "false"):
        return s_strip.lower() == "true"
    if s_strip.lower() in ("null", "none"):
        return None
    # Remove surrounding quotes
    if (s_strip.startswith('"') and s_strip.endswith('"')) or (s_strip.startswith("'") and s_strip.endswith("'")):
        s_strip = s_strip[1:-1]
    # Try int
    try:
        if s_strip.isdigit() or (s_strip.startswith("-") and s_strip[1:].isdigit()):
            return int(s_strip)
    except:
        pass
    # Try float
    try:
        return float(s_strip)
    except:
        return s_strip

def read_sales_csv(path):
    """
    Read sales CSV and return:
    - products set
    - per_product totals: dict -> {units, revenue, gross_margin, margin_pct}
    - per_product pricing: dict -> {P: unit_price (weighted avg), C: cost_per_unit (weighted avg)}
    We attempt to map column names flexibly.
    """
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in reader.fieldnames]

        def find_col(possible):
            for p in possible:
                for h in headers:
                    if h.lower() == p.lower():
                        return h
            return None

        col_product = find_col(["product"])
        col_units = find_col(["units", "quantity", "qty"])
        col_price = find_col(["unit_price", "price"])
        col_cost = find_col(["cost_per_unit", "unit_cost", "cost"])

        if not (col_product and col_units and col_price and col_cost):
            raise ValueError("CSV missing required columns: product, units, unit_price/price, cost_per_unit/unit_cost/cost")

        sums = {}  # per product accumulation
        for row in reader:
            try:
                product = row[col_product].strip()
                units = float(row[col_units])
                price = float(row[col_price])
                cost = float(row[col_cost])
            except Exception:
                continue
            if product not in sums:
                sums[product] = {
                    "units": 0.0,
                    "revenue": 0.0,
                    "gross_margin": 0.0,
                    "price_units_sum": 0.0,  # for weighted avg
                    "cost_units_sum": 0.0
                }
            sums[product]["units"] += units
            sums[product]["revenue"] += units * price
            sums[product]["gross_margin"] += (price - cost) * units
            sums[product]["price_units_sum"] += price * units
            sums[product]["cost_units_sum"] += cost * units

        totals = {}
        pricing = {}
        for product, agg in sums.items():
            units = agg["units"]
            revenue = agg["revenue"]
            gross_margin = agg["gross_margin"]
            margin_pct = (gross_margin / revenue) if revenue != 0 else 0.0
            totals[product] = {
                "units": units,
                "revenue": revenue,
                "gross_margin": gross_margin,
                "margin_pct": margin_pct,
            }
            if units > 0:
                P = agg["price_units_sum"] / units
                C = agg["cost_units_sum"] / units
            else:
                P = 0.0
                C = 0.0
            pricing[product] = {"P": P, "C": C}
        return set(totals.keys()), totals, pricing

def approx_equal(a, b, tol=1e-6):
    return abs(a - b) <= tol

def parse_iso_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def load_summary_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compute_discount_margin_pct(P, C, d):
    # post-discount margin pct = (P*(1-d) - C) / (P*(1-d))
    denom = P * (1 - d)
    if denom <= 0:
        return None
    return (denom - C) / denom

def compute_d_cap_by_margin(P, C, min_margin_pct):
    # d <= 1 - C / (P * (1 - m))
    denom = P * (1 - min_margin_pct)
    if denom <= 0:
        return 0.0
    return 1 - (C / denom)

def try_get_promo_window(obj):
    """
    Attempt to find a target promo window in objectives YAML.
    Accepts keys:
    - 'target_promo_window': {start_date/end_date or start/end}
    """
    # Direct expected key
    window = obj.get("target_promo_window")
    if isinstance(window, dict):
        start = window.get("start_date") or window.get("start")
        end = window.get("end_date") or window.get("end")
        return start, end
    # Try nested search for dict with start/end keys
    for k, v in obj.items():
        if isinstance(v, dict):
            if ("start_date" in v or "start" in v) and ("end_date" in v or "end" in v):
                start = v.get("start_date") or v.get("start")
                end = v.get("end_date") or v.get("end")
                return start, end
    return None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_analysis_md": False,
        "analysis_sections_ok": False,

        "has_summary_json": False,
        "summary_json_valid": False,
        "constraints_match_yaml": False,
        "totals_products_complete": False,
        "totals_values_correct": False,
        "top_products_ok": False,
        "discounts_present_all_products": False,
        "discounts_within_limits": False,
        "post_discount_margin_correct": False,
        "discount_margin_floor_ok": False,
        "discount_product_specific_cap_ok": False,

        "has_promo_calendar": False,
        "calendar_header_ok": False,
        "calendar_rows_valid": False,
        "calendar_channels_allowed": False,
        "calendar_discount_matches_summary": False,
        "calendar_dates_valid": False,
        "calendar_sparkling_within_window": False,
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.md")
    summary_path = os.path.join(output_dir, "summary.json")
    calendar_path = os.path.join(output_dir, "promo_calendar.csv")
    sales_csv_path = os.path.join(input_dir, "sales.csv")
    objectives_yaml_path = os.path.join(input_dir, "objectives.yaml")

    # Load inputs
    try:
        objectives = parse_simple_yaml(objectives_yaml_path)
    except Exception:
        objectives = {}

    # Extract constraints
    min_margin_pct = objectives.get("min_margin_pct")
    max_discount_pct = objectives.get("max_discount_pct")
    channels_focus = objectives.get("channels_focus") if isinstance(objectives.get("channels_focus"), list) else None
    window_start_str, window_end_str = try_get_promo_window(objectives)
    window_start = parse_iso_date(str(window_start_str)) if window_start_str else None
    window_end = parse_iso_date(str(window_end_str)) if window_end_str else None

    # Load sales
    products_set = set()
    computed_totals = {}
    pricing = {}
    try:
        products_set, computed_totals, pricing = read_sales_csv(sales_csv_path)
    except Exception:
        products_set = set()
        computed_totals = {}
        pricing = {}

    # 1) analysis.md checks
    if os.path.isfile(analysis_path):
        checks["has_analysis_md"] = True
        try:
            analysis_text = read_text(analysis_path)
            required_sections = [
                "Analysis & Insights",
                "Actionable Deliverables",
                "Implementation Guidance",
                "Best Practices",
            ]
            if all(sec in analysis_text for sec in required_sections):
                checks["analysis_sections_ok"] = True
        except Exception:
            pass

    # 2) summary.json checks
    summary = None
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        summary = load_summary_json(summary_path)
        if isinstance(summary, dict):
            checks["summary_json_valid"] = True

    if summary and checks["summary_json_valid"]:
        constraints = summary.get("constraints")
        totals = summary.get("totals")
        top_products = summary.get("top_products_by_revenue")
        disc_recs = summary.get("discount_recommendations")

        # constraints match YAML
        if isinstance(constraints, dict) and (min_margin_pct is not None) and (max_discount_pct is not None):
            sm_min = constraints.get("min_margin_pct")
            sm_max = constraints.get("max_discount_pct")
            try:
                if sm_min is not None and sm_max is not None and approx_equal(float(sm_min), float(min_margin_pct), 1e-9) and approx_equal(float(sm_max), float(max_discount_pct), 1e-9):
                    checks["constraints_match_yaml"] = True
            except Exception:
                pass

        # totals complete and values correct
        if isinstance(totals, dict) and computed_totals:
            # products present
            products_ok = all(p in totals for p in products_set)
            if products_ok:
                checks["totals_products_complete"] = True
            # values correct
            values_ok = True
            for p, comp_vals in computed_totals.items():
                tv = totals.get(p)
                if not isinstance(tv, dict):
                    values_ok = False
                    break
                # Compare within tolerances
                try:
                    # units as integer-like
                    if not approx_equal(float(tv.get("units", float("nan"))), float(comp_vals["units"]), 1e-6):
                        values_ok = False
                        break
                    if not approx_equal(float(tv.get("revenue", float("nan"))), float(comp_vals["revenue"]), 1e-6):
                        values_ok = False
                        break
                    if not approx_equal(float(tv.get("gross_margin", float("nan"))), float(comp_vals["gross_margin"]), 1e-6):
                        values_ok = False
                        break
                    if not approx_equal(float(tv.get("margin_pct", float("nan"))), float(comp_vals["margin_pct"]), 1e-4):
                        values_ok = False
                        break
                except Exception:
                    values_ok = False
                    break
            if values_ok and checks["totals_products_complete"]:
                checks["totals_values_correct"] = True

        # top_products_by_revenue
        if isinstance(top_products, list) and computed_totals:
            # compute expected top 2 by revenue desc
            sorted_by_rev = sorted(computed_totals.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
            expected_top2 = [sorted_by_rev[0][0], sorted_by_rev[1][0]] if len(sorted_by_rev) >= 2 else []
            if len(top_products) == 2 and top_products == expected_top2:
                checks["top_products_ok"] = True

        # discount recommendations checks
        if isinstance(disc_recs, dict) and computed_totals and (min_margin_pct is not None) and (max_discount_pct is not None):
            # presence
            if all(p in disc_recs for p in products_set):
                checks["discounts_present_all_products"] = True

            limits_ok = True
            pdm_ok = True
            floor_ok = True
            cap_ok = True
            for p in products_set:
                rec = disc_recs.get(p, {})
                try:
                    d = float(rec.get("discount_pct"))
                    pdm = float(rec.get("post_discount_margin_pct"))
                    # within [0, max_discount_pct]
                    if not (d >= -1e-9 and d <= float(max_discount_pct) + 1e-9):
                        limits_ok = False
                    # product-specific cap based on min_margin_pct
                    P = pricing[p]["P"]
                    C = pricing[p]["C"]
                    d_cap = compute_d_cap_by_margin(P, C, float(min_margin_pct))
                    if d > d_cap + 0.001:
                        cap_ok = False
                    # computed post-discount margin
                    computed_pdm = compute_discount_margin_pct(P, C, d)
                    if computed_pdm is None or abs(pdm - computed_pdm) > 0.01:
                        pdm_ok = False
                    # margin floor
                    if pdm + 1e-9 < float(min_margin_pct):
                        floor_ok = False
                except Exception:
                    limits_ok = False
                    pdm_ok = False
                    floor_ok = False
                    cap_ok = False
            if limits_ok:
                checks["discounts_within_limits"] = True
            if pdm_ok:
                checks["post_discount_margin_correct"] = True
            if floor_ok:
                checks["discount_margin_floor_ok"] = True
            if cap_ok:
                checks["discount_product_specific_cap_ok"] = True

    # 3) promo_calendar.csv checks
    calendar_rows = []
    if os.path.isfile(calendar_path):
        checks["has_promo_calendar"] = True
        try:
            with open(calendar_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["product", "start_date", "end_date", "discount_pct", "channel"]
                if header == expected_header:
                    checks["calendar_header_ok"] = True
                    # parse rows
                    for r in rows[1:]:
                        if len(r) != 5:
                            continue
                        product, start_s, end_s, d_s, channel = r
                        calendar_rows.append({
                            "product": product.strip(),
                            "start_date": start_s.strip(),
                            "end_date": end_s.strip(),
                            "discount_pct": d_s.strip(),
                            "channel": channel.strip(),
                        })
        except Exception:
            pass

    if calendar_rows and summary and isinstance(summary, dict):
        disc_recs = summary.get("discount_recommendations", {})
        constraints = summary.get("constraints", {})
        # channels allowed
        channels_ok = True
        if isinstance(channels_focus, list) and len(channels_focus) > 0:
            allowed_set = set([str(c) for c in channels_focus])
            for row in calendar_rows:
                if row["channel"] not in allowed_set:
                    channels_ok = False
                    break
        else:
            channels_ok = False  # cannot validate without channels_focus
        if channels_ok:
            checks["calendar_channels_allowed"] = True

        # rows valid: product in recs, discount matches, dates valid and start<=end
        rows_valid = True
        discounts_match = True
        dates_valid = True
        for row in calendar_rows:
            p = row["product"]
            try:
                d_val = float(row["discount_pct"])
            except Exception:
                d_val = None
            # product presence
            if not isinstance(disc_recs, dict) or p not in disc_recs:
                rows_valid = False
            else:
                try:
                    rec_d = float(disc_recs[p]["discount_pct"])
                    if d_val is None or abs(d_val - rec_d) > 0.001:
                        discounts_match = False
                except Exception:
                    discounts_match = False
            # dates
            sd = parse_iso_date(row["start_date"])
            ed = parse_iso_date(row["end_date"])
            if sd is None or ed is None or sd > ed:
                dates_valid = False
        if rows_valid:
            checks["calendar_rows_valid"] = True
        if discounts_match:
            checks["calendar_discount_matches_summary"] = True
        if dates_valid:
            checks["calendar_dates_valid"] = True

        # Sparkling Lime within window
        within_ok = False
        if window_start and window_end:
            for row in calendar_rows:
                if row["product"] == "Sparkling Lime 330ml":
                    sd = parse_iso_date(row["start_date"])
                    ed = parse_iso_date(row["end_date"])
                    if sd and ed and (sd >= window_start) and (ed <= window_end):
                        within_ok = True
                        break
        # Only mark true if we have a window to check
        if window_start and window_end and within_ok:
            checks["calendar_sparkling_within_window"] = True

    # Compute reward
    # No-op baseline: if output/ missing or no required artifacts, ensure reward 0.0 naturally by zero trues.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Print JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()