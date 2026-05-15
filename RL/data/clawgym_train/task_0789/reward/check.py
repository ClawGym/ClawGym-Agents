import json
import os
import sys
from typing import Any, Dict, Tuple, List

def read_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_close(a: float, b: float, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def get_required(d: dict, keys: List[str]) -> bool:
    cur = d
    try:
        for k in keys:
            if k not in cur:
                return False
            cur = cur[k]
        return True
    except Exception:
        return False

def compute_baseline_metrics(b: Dict[str, Any]) -> Dict[str, float]:
    sessions = float(b["sessions"])
    base_conv = float(b["base_conversion_rate"])

    main_price = float(b["main_price"])
    main_cost = float(b["main_unit_cost"])

    case_price = float(b["case_price"])
    case_cost = float(b["case_unit_cost"])
    case_attach = float(b["case_attach_rate"])

    warranty_price = float(b["warranty_price"])
    warranty_cost = float(b["warranty_unit_cost"])
    warranty_attach = float(b["warranty_attach_rate"])

    orders = sessions * base_conv
    aov = main_price + case_attach * case_price + warranty_attach * warranty_price
    cogs_per_order = main_cost + case_attach * case_cost + warranty_attach * warranty_cost
    margin_per_order = aov - cogs_per_order
    revenue = aov * orders
    gross_profit = margin_per_order * orders
    gmr = (margin_per_order / aov) if aov != 0 else 0.0

    return {
        "orders": orders,
        "aov": aov,
        "revenue": revenue,
        "gross_margin_rate": gmr,
        "gross_profit": gross_profit,
        "cogs_per_order": cogs_per_order,
        "margin_per_order": margin_per_order,
    }

def compute_bundle_metrics(b: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, float]:
    # Baseline components
    base = compute_baseline_metrics(b)
    orders = base["orders"]

    # Prices and costs
    main_price = float(b["main_price"])
    main_cost = float(b["main_unit_cost"])
    case_price = float(b["case_price"])
    case_cost = float(b["case_unit_cost"])
    warranty_price = float(b["warranty_price"])
    warranty_cost = float(b["warranty_unit_cost"])
    case_attach = float(b["case_attach_rate"])
    warranty_attach = float(b["warranty_attach_rate"])

    # Scenario params
    bundle_price = float(s.get("bundle_offer", {}).get("bundle_price", 0.0))
    bundle_take_rate = float(s.get("bundle_offer", {}).get("bundle_take_rate", 0.0))
    bundle_items = s.get("bundle_offer", {}).get("bundle_items", ["main", "case"])

    # COGS for bundled items (sum unit costs for listed items)
    item_cost_map = {
        "main": main_cost,
        "case": case_cost,
        "warranty": warranty_cost,
    }
    bundled_items_cogs = sum(item_cost_map.get(it, 0.0) for it in bundle_items)

    # Revenue and COGS per order for bundle segment
    rev_bundle = bundle_price + warranty_attach * warranty_price
    cogs_bundle = bundled_items_cogs + warranty_attach * warranty_cost

    # Revenue and COGS per order for non-bundle segment (baseline attach rates)
    rev_non_bundle = main_price + case_attach * case_price + warranty_attach * warranty_price
    cogs_non_bundle = main_cost + case_attach * case_cost + warranty_attach * warranty_cost

    aov = bundle_take_rate * rev_bundle + (1.0 - bundle_take_rate) * rev_non_bundle
    cogs_per_order = bundle_take_rate * cogs_bundle + (1.0 - bundle_take_rate) * cogs_non_bundle
    margin_per_order = aov - cogs_per_order
    revenue = aov * orders
    gross_profit = margin_per_order * orders
    gmr = (margin_per_order / aov) if aov != 0 else 0.0

    return {
        "orders": orders,  # conversion unchanged
        "aov": aov,
        "revenue": revenue,
        "gross_margin_rate": gmr,
        "gross_profit": gross_profit,
    }

def compute_upsell_metrics(b: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, float]:
    base = compute_baseline_metrics(b)
    orders = base["orders"]

    main_price = float(b["main_price"])
    main_cost = float(b["main_unit_cost"])

    case_price = float(b["case_price"])
    case_cost = float(b["case_unit_cost"])
    case_attach = float(b["case_attach_rate"])

    warranty_price = float(b["warranty_price"])
    warranty_cost = float(b["warranty_unit_cost"])
    warranty_attach = float(b["warranty_attach_rate"])

    item = s.get("upsell_offer", {}).get("item")
    new_attach_rate = float(s.get("upsell_offer", {}).get("new_attach_rate", 0.0))
    if item == "case":
        case_attach = new_attach_rate
    elif item == "warranty":
        warranty_attach = new_attach_rate
    # else: if item unknown, leave baseline

    aov = main_price + case_attach * case_price + warranty_attach * warranty_price
    cogs_per_order = main_cost + case_attach * case_cost + warranty_attach * warranty_cost
    margin_per_order = aov - cogs_per_order
    revenue = aov * orders
    gross_profit = margin_per_order * orders
    gmr = (margin_per_order / aov) if aov != 0 else 0.0

    return {
        "orders": orders,  # conversion unchanged
        "aov": aov,
        "revenue": revenue,
        "gross_margin_rate": gmr,
        "gross_profit": gross_profit,
    }

def compute_price_increase_metrics(b: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, float]:
    sessions = float(b["sessions"])
    base_conv = float(b["base_conversion_rate"])

    main_price = float(b["main_price"])
    main_cost = float(b["main_unit_cost"])

    case_price = float(b["case_price"])
    case_cost = float(b["case_unit_cost"])
    case_attach = float(b["case_attach_rate"])

    warranty_price = float(b["warranty_price"])
    warranty_cost = float(b["warranty_unit_cost"])
    warranty_attach = float(b["warranty_attach_rate"])

    item = s.get("price_increase_5", {}).get("item")
    price_change_pct = float(s.get("price_increase_5", {}).get("price_change_pct", 0.0))
    conversion_multiplier = float(s.get("price_increase_5", {}).get("conversion_multiplier", 1.0))

    # Apply price change to specified item only
    if item == "main":
        main_price = main_price * (1.0 + price_change_pct)
    elif item == "case":
        case_price = case_price * (1.0 + price_change_pct)
    elif item == "warranty":
        warranty_price = warranty_price * (1.0 + price_change_pct)

    conv = base_conv * conversion_multiplier
    orders = sessions * conv

    aov = main_price + case_attach * case_price + warranty_attach * warranty_price
    cogs_per_order = main_cost + case_attach * case_cost + warranty_attach * warranty_cost
    margin_per_order = aov - cogs_per_order
    revenue = aov * orders
    gross_profit = margin_per_order * orders
    gmr = (margin_per_order / aov) if aov != 0 else 0.0

    return {
        "orders": orders,
        "aov": aov,
        "revenue": revenue,
        "gross_margin_rate": gmr,
        "gross_profit": gross_profit,
        "margin_per_order": margin_per_order,
    }

def compute_break_even_pct(b: Dict[str, Any], s: Dict[str, Any]) -> float | None:
    base = compute_baseline_metrics(b)
    baseline_gp = base["gross_profit"]
    baseline_orders = base["orders"]

    # New margin per order with price change applied (attach rates unchanged)
    sessions = float(b["sessions"])  # not used directly for break-even calc
    main_price = float(b["main_price"])
    main_cost = float(b["main_unit_cost"])

    case_price = float(b["case_price"])
    case_cost = float(b["case_unit_cost"])
    case_attach = float(b["case_attach_rate"])

    warranty_price = float(b["warranty_price"])
    warranty_cost = float(b["warranty_unit_cost"])
    warranty_attach = float(b["warranty_attach_rate"])

    item = s.get("price_increase_5", {}).get("item")
    price_change_pct = float(s.get("price_increase_5", {}).get("price_change_pct", 0.0))

    if item == "main":
        main_price = main_price * (1.0 + price_change_pct)
    elif item == "case":
        case_price = case_price * (1.0 + price_change_pct)
    elif item == "warranty":
        warranty_price = warranty_price * (1.0 + price_change_pct)

    new_aov = main_price + case_attach * case_price + warranty_attach * warranty_price
    new_cogs_po = main_cost + case_attach * case_cost + warranty_attach * warranty_cost
    new_margin_per_order = new_aov - new_cogs_po

    if new_margin_per_order <= 0:
        return None

    # 100 × (1 − baseline_gross_profit / (baseline_orders × new_margin_per_order))
    try:
        be_pct = 100.0 * (1.0 - (baseline_gp / (baseline_orders * new_margin_per_order)))
        return be_pct
    except Exception:
        return None

def compare_metrics(actual: Dict[str, Any], expected: Dict[str, float]) -> bool:
    money_tol = 0.5
    rate_tol = 0.002

    ok = True
    ok = ok and is_close(actual.get("orders"), expected["orders"], money_tol)
    ok = ok and is_close(actual.get("aov"), expected["aov"], money_tol)
    ok = ok and is_close(actual.get("revenue"), expected["revenue"], money_tol)
    ok = ok and is_close(actual.get("gross_profit"), expected["gross_profit"], money_tol)
    ok = ok and is_close(actual.get("gross_margin_rate"), expected["gross_margin_rate"], rate_tol)
    return ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        "has_results_json": False,
        "has_report_md": False,
        "schema_results_basics": False,
        "assumptions_aov_def_ok": False,
        "scenarios_three_and_named": False,
        "baseline_numbers_match": False,
        "bundle_numbers_match": False,
        "upsell_numbers_match": False,
        "price_increase_numbers_match": False,
        "break_even_computed_correctly": False,
        "report_has_all_headers": False,
        "report_mentions_all_scenarios": False,
    }

    # Paths
    baseline_path = os.path.join(input_dir, "baseline.json")
    scenarios_path = os.path.join(input_dir, "scenarios.json")
    results_path = os.path.join(output_dir, "results.json")
    report_path = os.path.join(output_dir, "report.md")

    # Presence checks
    if os.path.isfile(results_path):
        checks["has_results_json"] = True
    if os.path.isfile(report_path):
        checks["has_report_md"] = True

    # Early no-op gating: if any required artifact missing, reward must be 0.0
    # Still continue to populate remaining fields for transparency, but reward will be set to 0 later.
    results_obj = None
    if checks["has_results_json"]:
        ok_json, parsed = read_json(results_path)
        if ok_json and isinstance(parsed, dict):
            results_obj = parsed

    # Schema checks if results_obj present
    scenarios_map: Dict[str, Dict[str, Any]] = {}
    if results_obj is not None:
        # assumptions
        assumptions = results_obj.get("assumptions", {})
        if isinstance(assumptions, dict):
            if assumptions.get("aov_definition") == "gross_pre_refund":
                checks["assumptions_aov_def_ok"] = True
        # baseline keys
        baseline_out = results_obj.get("baseline", {})
        baseline_keys = ["orders", "aov", "revenue", "gross_margin_rate", "gross_profit"]
        baseline_ok = isinstance(baseline_out, dict) and all(k in baseline_out for k in baseline_keys)

        # scenarios
        scenarios_list = results_obj.get("scenarios", [])
        scenarios_ok = isinstance(scenarios_list, list) and len(scenarios_list) == 3
        if isinstance(scenarios_list, list):
            for entry in scenarios_list:
                if isinstance(entry, dict) and "name" in entry:
                    scenarios_map[entry["name"]] = entry

        required_names = {"bundle_offer", "upsell_offer", "price_increase_5"}
        if set(scenarios_map.keys()) == required_names and scenarios_ok:
            checks["scenarios_three_and_named"] = True

        # Each scenario must have required numeric fields and delta structure
        scenarios_fields_ok = True
        for nm in required_names:
            ent = scenarios_map.get(nm, {})
            if not isinstance(ent, dict):
                scenarios_fields_ok = False
                break
            for k in baseline_keys:
                if k not in ent:
                    scenarios_fields_ok = False
                    break
            delta = ent.get("delta_vs_baseline", {})
            if not (isinstance(delta, dict) and "aov_abs" in delta and "gross_profit_abs" in delta):
                scenarios_fields_ok = False
                break

        # break_even presence
        be_ok = get_required(results_obj, ["break_even", "price_increase_5", "max_conversion_drop_pct_to_match_baseline_gp"])

        checks["schema_results_basics"] = bool(baseline_ok and scenarios_ok and scenarios_fields_ok and be_ok)

    # Load inputs
    ok_base, base_in = read_json(baseline_path)
    ok_scen, scen_in = read_json(scenarios_path)

    # Numeric validations
    if results_obj is not None and ok_base and ok_scen:
        # Expected baseline
        exp_base = compute_baseline_metrics(base_in)
        if "baseline" in results_obj and isinstance(results_obj["baseline"], dict):
            checks["baseline_numbers_match"] = compare_metrics(results_obj["baseline"], exp_base)

        # bundle
        if "bundle_offer" in scenarios_map:
            exp_bundle = compute_bundle_metrics(base_in, scen_in)
            checks["bundle_numbers_match"] = compare_metrics(scenarios_map["bundle_offer"], exp_bundle)

        # upsell
        if "upsell_offer" in scenarios_map:
            exp_upsell = compute_upsell_metrics(base_in, scen_in)
            checks["upsell_numbers_match"] = compare_metrics(scenarios_map["upsell_offer"], exp_upsell)

        # price increase
        if "price_increase_5" in scenarios_map:
            exp_price = compute_price_increase_metrics(base_in, scen_in)
            # extract only required fields
            exp_price_subset = {
                "orders": exp_price["orders"],
                "aov": exp_price["aov"],
                "revenue": exp_price["revenue"],
                "gross_margin_rate": exp_price["gross_margin_rate"],
                "gross_profit": exp_price["gross_profit"],
            }
            checks["price_increase_numbers_match"] = compare_metrics(scenarios_map["price_increase_5"], exp_price_subset)

            # break-even
            exp_be = compute_break_even_pct(base_in, scen_in)
            be_val = None
            try:
                be_val = results_obj["break_even"]["price_increase_5"]["max_conversion_drop_pct_to_match_baseline_gp"]
            except Exception:
                be_val = None
            if exp_be is not None and be_val is not None:
                checks["break_even_computed_correctly"] = is_close(float(be_val), float(exp_be), 0.2)

    # Report checks
    if checks["has_report_md"]:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = [ln.strip() for ln in content.splitlines()]
            # Normalize header lines by stripping leading '#' and spaces
            def norm_header(s: str) -> str:
                s = s.lstrip("#").strip()
                return s

            required_headers = [
                "Baseline view",
                "Scenario modeling results",
                "Margin and break-even implications",
                "Key risks and weak points",
                "Recommendation",
            ]
            headers_present = set()
            for ln in lines:
                nh = norm_header(ln)
                if nh in required_headers:
                    headers_present.add(nh)
            checks["report_has_all_headers"] = (set(required_headers) <= headers_present)

            # Scenario mentions
            mentions_ok = all(name in content for name in ["bundle_offer", "upsell_offer", "price_increase_5"])
            checks["report_mentions_all_scenarios"] = mentions_ok
        except Exception:
            pass

    # Compute reward
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)

    # If any required artifact missing, reward must be exactly 0.0
    if not (checks["has_results_json"] and checks["has_report_md"]):
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    # Ensure reward bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print single JSON object
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()