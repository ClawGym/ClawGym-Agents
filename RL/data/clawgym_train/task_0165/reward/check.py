import json
import os
import sys
import math
import csv

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_competitors_csv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                name = (r.get("name") or "").strip()
                price_raw = r.get("monthly_price")
                if price_raw is None:
                    continue
                try:
                    price = float(str(price_raw).strip())
                except Exception:
                    continue
                rows.append({"name": name, "monthly_price": price})
        return rows, None
    except Exception as e:
        return None, str(e)

def cents(price):
    # Return integer cents rounded to nearest cent
    return int(round(float(price) * 100))

def ends_with_99(price):
    try:
        return cents(price) % 100 == 99
    except Exception:
        return False

def get_required_paths(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")
    out_file = os.path.join(output_dir, "pricing", "recommendations.json")
    ctx_file = os.path.join(input_dir, "context.json")
    competitors_file = os.path.join(input_dir, "competitors.csv")
    return input_dir, output_dir, reward_dir, out_file, ctx_file, competitors_file

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir, out_file, ctx_file, competitors_file = get_required_paths(workspace_root)

    checks = {
        "file_exists_and_valid_json": False,
        "product_nonempty": False,
        "tiers_structure_valid": False,
        "prices_charm_and_thresholds": False,
        "ratios_valid": False,
        "display_order_and_anchor_valid": False,
        "social_proof_valid": False,
        "decoy_valid": False,
        "daily_price_math_valid": False,
        "comparison_valid": False,
        "scarcity_valid": False,
        "bundling_valid": False,
        "framing_valid": False,
    }

    # Load output JSON
    data, json_err = read_json(out_file)
    if data is None:
        # If the artifact is missing or invalid, reward must be exactly 0.0
        print(json.dumps({"reward": 0.0, **checks}))
        return

    checks["file_exists_and_valid_json"] = True

    # Check product non-empty
    product = data.get("product")
    if isinstance(product, str) and product.strip() != "":
        checks["product_nonempty"] = True

    # Prepare to validate tiers
    tiers = data.get("tiers")
    tiers_by_id = {}
    if isinstance(tiers, list) and len(tiers) == 3:
        ids_ok = True
        required_ids = {"starter", "growth", "premium"}
        seen_ids = set()
        tier_fields_ok = True
        features_ok = True
        types_ok = True
        for t in tiers:
            if not isinstance(t, dict):
                types_ok = False
                break
            tid = t.get("id")
            name = t.get("name")
            monthly_price = t.get("monthly_price")
            price_display = t.get("price_display")
            daily_price = t.get("daily_price")
            features = t.get("features")
            most_popular = t.get("most_popular")
            badge = t.get("badge") if "badge" in t else None  # can be null

            # id validation
            if tid not in required_ids:
                ids_ok = False
            else:
                seen_ids.add(tid)

            # type validations
            if not isinstance(name, str):
                types_ok = False
            # monthly_price must be number
            try:
                _ = float(monthly_price)
            except Exception:
                types_ok = False
            if not isinstance(price_display, str):
                types_ok = False
            try:
                _ = float(daily_price)
            except Exception:
                types_ok = False
            if not (isinstance(features, list) and len(features) >= 3 and all(isinstance(x, str) for x in features)):
                features_ok = False
            if not isinstance(most_popular, bool):
                types_ok = False
            # badge can be string or None
            if badge is not None and not isinstance(badge, str):
                types_ok = False

            tiers_by_id[tid] = t

        if ids_ok and seen_ids == required_ids and types_ok and features_ok:
            checks["tiers_structure_valid"] = True

    # Prices charm and thresholds
    prices_ok = False
    if checks["tiers_structure_valid"]:
        try:
            s_price = float(tiers_by_id["starter"]["monthly_price"])
            g_price = float(tiers_by_id["growth"]["monthly_price"])
            p_price = float(tiers_by_id["premium"]["monthly_price"])

            charm_ok = ends_with_99(s_price) and ends_with_99(g_price) and ends_with_99(p_price)
            # thresholds
            th_ok = (s_price <= 29.99 + 1e-9) and (g_price <= 99.99 + 1e-9) and (110.00 - 1e-9 <= p_price <= 199.99 + 1e-9)
            prices_ok = charm_ok and th_ok
        except Exception:
            prices_ok = False
    checks["prices_charm_and_thresholds"] = prices_ok

    # Ratios
    ratios_ok = False
    if checks["tiers_structure_valid"]:
        try:
            s_price = float(tiers_by_id["starter"]["monthly_price"])
            g_price = float(tiers_by_id["growth"]["monthly_price"])
            p_price = float(tiers_by_id["premium"]["monthly_price"])
            if s_price > 0 and g_price > 0:
                rg = g_price / s_price
                pg = p_price / g_price
                ratios_ok = (1.6 - 1e-9 <= rg <= 2.2 + 1e-9) and (1.1 - 1e-9 <= pg <= 1.3 + 1e-9)
        except Exception:
            ratios_ok = False
    checks["ratios_valid"] = ratios_ok

    # Display order and anchoring highest->lowest
    display_ok = False
    if checks["tiers_structure_valid"]:
        order = data.get("display_order")
        try:
            s_price = float(tiers_by_id["starter"]["monthly_price"])
            g_price = float(tiers_by_id["growth"]["monthly_price"])
            p_price = float(tiers_by_id["premium"]["monthly_price"])
            order_ok = isinstance(order, list) and order == ["premium", "growth", "starter"]
            price_rank_ok = (p_price >= g_price >= s_price) and (p_price >= g_price) and (g_price >= s_price)
            display_ok = order_ok and price_rank_ok
        except Exception:
            display_ok = False
    checks["display_order_and_anchor_valid"] = display_ok

    # Social proof
    social_ok = False
    if checks["tiers_structure_valid"]:
        try:
            g = tiers_by_id["growth"]
            s = tiers_by_id["starter"]
            p = tiers_by_id["premium"]
            g_ok = (g.get("most_popular") is True) and (g.get("badge") == "Most Popular")
            def other_ok(t):
                return (t.get("most_popular") is False) and (t.get("badge") is None)
            social_ok = g_ok and other_ok(s) and other_ok(p)
        except Exception:
            social_ok = False
    checks["social_proof_valid"] = social_ok

    # Decoy
    decoy_ok = data.get("decoy_tier_id") == "premium"
    checks["decoy_valid"] = decoy_ok

    # Daily price math for each tier: round(monthly/30, 2)
    daily_ok = False
    if checks["tiers_structure_valid"]:
        try:
            all_ok = True
            for tid in ["starter", "growth", "premium"]:
                t = tiers_by_id[tid]
                m = float(t.get("monthly_price"))
                d = float(t.get("daily_price"))
                expected = round(m / 30.0, 2)
                if not approx_equal(d, expected, tol=0.01):
                    all_ok = False
                    break
            daily_ok = all_ok
        except Exception:
            daily_ok = False
    checks["daily_price_math_valid"] = daily_ok

    # Comparison: parse competitors, compute max price and savings
    comparison_ok = False
    comp = data.get("comparison") if isinstance(data.get("comparison"), dict) else {}
    if isinstance(comp, dict):
        comp_rows, comp_err = read_competitors_csv(competitors_file)
        if comp_rows is not None and len(comp_rows) > 0 and checks["tiers_structure_valid"]:
            try:
                # find max competitor price
                top_row = max(comp_rows, key=lambda r: float(r.get("monthly_price", 0.0)))
                top_price = float(top_row["monthly_price"])
                top_name = top_row["name"]
                reported_top_price = comp.get("top_competitor_price")
                reported_top_name = comp.get("top_competitor_name")
                g_price = float(tiers_by_id["growth"]["monthly_price"])
                reported_savings = comp.get("growth_savings_vs_top_competitor")
                # Validate
                top_price_ok = approx_equal(reported_top_price, top_price, tol=0.01)
                # Name should be a string; do not enforce exact match but prefer match if provided
                name_ok = isinstance(reported_top_name, str) and reported_top_name.strip() != ""
                # Compute expected savings
                expected_savings = round(top_price - g_price, 2)
                savings_ok = approx_equal(reported_savings, expected_savings, tol=0.01) and (expected_savings >= -1e-9)
                comparison_ok = top_price_ok and name_ok and savings_ok
            except Exception:
                comparison_ok = False
        else:
            comparison_ok = False
    checks["comparison_valid"] = comparison_ok

    # Scarcity exact match
    scarcity = data.get("scarcity")
    scarcity_ok = (
        isinstance(scarcity, dict)
        and scarcity.get("type") == "capacity"
        and scarcity.get("limit") == 25
        and scarcity.get("applies_to") == "growth"
    )
    checks["scarcity_valid"] = scarcity_ok

    # Bundling for growth
    bundling = data.get("bundling")
    bundling_ok = False
    if isinstance(bundling, dict) and "growth" in bundling and checks["tiers_structure_valid"]:
        try:
            g_bundle = bundling["growth"]
            comps = g_bundle.get("components")
            total = g_bundle.get("itemized_value_total")
            if isinstance(comps, list) and len(comps) >= 3:
                comp_sum = 0.0
                comps_ok = True
                for c in comps:
                    if not (isinstance(c, dict) and isinstance(c.get("name"), str)):
                        comps_ok = False
                        break
                    try:
                        val = float(c.get("implied_value"))
                    except Exception:
                        comps_ok = False
                        break
                    comp_sum += val
                if comps_ok:
                    sum_ok = approx_equal(total, comp_sum, tol=0.01)
                    g_price = float(tiers_by_id["growth"]["monthly_price"])
                    min_required = g_price * 1.2
                    value_ok = (total is not None) and (float(total) >= (min_required - 0.01))
                    bundling_ok = sum_ok and value_ok
        except Exception:
            bundling_ok = False
    checks["bundling_valid"] = bundling_ok

    # Framing: ROI for growth
    framing_ok = False
    framing = data.get("framing")
    if isinstance(framing, dict) and checks["tiers_structure_valid"]:
        g_framing = framing.get("growth")
        if isinstance(g_framing, dict):
            roi = g_framing.get("roi")
            if isinstance(roi, dict):
                # Load context to get estimated_monthly_savings_per_customer
                ctx, ctx_err = read_json(ctx_file)
                if ctx is not None:
                    ems = ctx.get("estimated_monthly_savings_per_customer")
                    try:
                        ems_val = float(ems)
                        g_price = float(tiers_by_id["growth"]["monthly_price"])
                        reported_ems = roi.get("estimated_monthly_savings")
                        # Days to payback: ceil(growth_price / (estimated_monthly_savings_per_customer / 30))
                        if ems_val > 0:
                            per_day = ems_val / 30.0
                            expected_days = int(math.ceil(g_price / per_day))
                            reported_days = roi.get("days_to_payback")
                            ems_ok = approx_equal(reported_ems, ems_val, tol=0.01)
                            days_ok = isinstance(reported_days, (int, float)) and int(reported_days) == expected_days
                            framing_ok = ems_ok and days_ok
                        else:
                            framing_ok = False
                    except Exception:
                        framing_ok = False
    checks["framing_valid"] = framing_ok

    # If output missing or invalid, reward must be 0.0; we already handled early return.
    # Otherwise, compute fraction of passed checks.
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if checks["file_exists_and_valid_json"] else 0.0

    # Ensure reward within [0,1]
    try:
        reward = max(0.0, min(1.0, float(reward)))
    except Exception:
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()