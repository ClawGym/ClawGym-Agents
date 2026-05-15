import json
import os
import sys
import csv
import math

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abs_path(root, *parts):
    return os.path.join(root, *parts)

def parse_simple_yaml_numbers(path):
    data = {}
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove trailing comments
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            if not val:
                continue
            # Remove possible quotes
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            # Parse number
            try:
                if "." in val or "e" in val.lower():
                    num = float(val)
                else:
                    num = float(int(val))
            except Exception:
                try:
                    num = float(val)
                except Exception:
                    continue
            data[key] = num
    return data

def read_product_pricing_csv(path):
    if not os.path.isfile(path):
        return None
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = ["sku","selling_price","cogs","shipping_cost","payment_fee_pct","platform_fee_pct","discount_rate","refund_rate"]
        if reader.fieldnames is None:
            return None
        # Normalize headers by stripping spaces
        headers = [h.strip() for h in reader.fieldnames]
        if any(h not in headers for h in required):
            # Still attempt to map if present under exact names
            pass
        for raw in reader:
            row = {k.strip(): (raw[k].strip() if raw.get(k) is not None else "") for k in raw}
            try:
                rows.append({
                    "sku": row["sku"],
                    "selling_price": float(row["selling_price"]),
                    "cogs": float(row["cogs"]),
                    "shipping_cost": float(row["shipping_cost"]),
                    "payment_fee_pct": float(row["payment_fee_pct"]),
                    "platform_fee_pct": float(row["platform_fee_pct"]),
                    "discount_rate": float(row["discount_rate"]),
                    "refund_rate": float(row["refund_rate"]),
                })
            except Exception:
                return None
    return rows

def near(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def to_float(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except Exception:
            return None
    return None

def compute_unit_econ(entry):
    selling_price = entry["selling_price"]
    cogs = entry["cogs"]
    shipping_cost = entry["shipping_cost"]
    payment_fee_pct = entry["payment_fee_pct"]
    platform_fee_pct = entry["platform_fee_pct"]
    discount_rate = entry["discount_rate"]
    refund_rate = entry["refund_rate"]

    price_effective = selling_price * (1 - discount_rate)
    payment_fee = payment_fee_pct * price_effective
    platform_fee = platform_fee_pct * price_effective
    variable_cost_per_order = cogs + shipping_cost + payment_fee + platform_fee
    revenue_net_per_order = price_effective * (1 - refund_rate)
    contribution_margin_per_order = revenue_net_per_order - variable_cost_per_order

    return {
        "price_effective": price_effective,
        "payment_fee": payment_fee,
        "platform_fee": platform_fee,
        "variable_cost_per_order": variable_cost_per_order,
        "revenue_net_per_order": revenue_net_per_order,
        "contribution_margin_per_order": contribution_margin_per_order,
    }

def compute_breakeven(entry, overhead, planned_orders):
    ue = compute_unit_econ(entry)
    cm = ue["contribution_margin_per_order"]
    revenue_net = ue["revenue_net_per_order"]
    # Assume cm > 0 as per instructions
    break_even_orders = math.ceil(overhead / cm)
    break_even_revenue_net = break_even_orders * revenue_net
    breakeven_cpa_variable = cm
    fully_loaded_adjustment = overhead / planned_orders
    breakeven_cpa_fully_loaded = cm - fully_loaded_adjustment
    # Handle division by zero or very small
    if abs(breakeven_cpa_variable) > 1e-12:
        breakeven_roas_variable = revenue_net / breakeven_cpa_variable
    else:
        breakeven_roas_variable = float('inf')
    if abs(breakeven_cpa_fully_loaded) > 1e-12:
        breakeven_roas_fully_loaded = revenue_net / breakeven_cpa_fully_loaded
    else:
        # Represent as a very large number to avoid crash; validator likely avoids zero
        breakeven_roas_fully_loaded = float('inf')
    return {
        "break_even_orders": break_even_orders,
        "break_even_revenue_net": break_even_revenue_net,
        "breakeven_cpa_variable": breakeven_cpa_variable,
        "breakeven_cpa_fully_loaded": breakeven_cpa_fully_loaded,
        "breakeven_roas_variable": breakeven_roas_variable,
        "breakeven_roas_fully_loaded": breakeven_roas_fully_loaded,
    }

def decision_label(breakeven_cpa_fully_loaded, target_cpa):
    if breakeven_cpa_fully_loaded >= (target_cpa + 5):
        return "scale"
    elif breakeven_cpa_fully_loaded >= target_cpa:
        return "launch"
    else:
        return "hold"

def compute_sensitivity_deltas(entry):
    base_cm = compute_unit_econ(entry)["contribution_margin_per_order"]
    deltas = {}
    # selling_price +10%
    e = dict(entry); e["selling_price"] = entry["selling_price"] * 1.10
    deltas["selling_price_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # cogs +10%
    e = dict(entry); e["cogs"] = entry["cogs"] * 1.10
    deltas["cogs_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # shipping_cost +10%
    e = dict(entry); e["shipping_cost"] = entry["shipping_cost"] * 1.10
    deltas["shipping_cost_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # payment_fee_pct +10%
    e = dict(entry); e["payment_fee_pct"] = entry["payment_fee_pct"] * 1.10
    deltas["payment_fee_pct_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # platform_fee_pct +10%
    e = dict(entry); e["platform_fee_pct"] = entry["platform_fee_pct"] * 1.10
    deltas["platform_fee_pct_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # discount_rate +10%
    e = dict(entry); e["discount_rate"] = entry["discount_rate"] * 1.10
    deltas["discount_rate_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    # refund_rate +10%
    e = dict(entry); e["refund_rate"] = entry["refund_rate"] * 1.10
    deltas["refund_rate_plus_10pct"] = compute_unit_econ(e)["contribution_margin_per_order"] - base_cm
    return deltas

def check_assumptions(output_path, pricing_rows, yaml_data):
    # Return True if valid, else False
    if not os.path.isfile(output_path):
        return False
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    required_top = ["fixed_overhead_per_month", "planned_orders_per_month", "target_cpa", "skus"]
    for k in required_top:
        if k not in data:
            return False
    # Compare YAML numeric keys exactly (numerically equal, strict small tol)
    tiny_tol = 1e-9
    for k in ["fixed_overhead_per_month", "planned_orders_per_month", "target_cpa"]:
        v = to_float(data.get(k))
        y = yaml_data.get(k)
        if v is None or y is None or not near(v, y, tiny_tol):
            return False
    # Check skus array
    skus = data.get("skus")
    if not isinstance(skus, list):
        return False
    # Build expected map
    exp_map = {}
    for r in pricing_rows:
        exp_map[r["sku"]] = r
    if len(skus) != len(exp_map):
        return False
    seen = set()
    for item in skus:
        if not isinstance(item, dict):
            return False
        sku = item.get("sku")
        if not isinstance(sku, str):
            return False
        if sku in seen:
            return False
        seen.add(sku)
        if sku not in exp_map:
            return False
        exp = exp_map[sku]
        # Check all required fields
        for field in ["selling_price","cogs","shipping_cost","payment_fee_pct","platform_fee_pct","discount_rate","refund_rate"]:
            val = to_float(item.get(field))
            if val is None:
                return False
            if not near(val, exp[field], 1e-9):
                return False
    return True

def check_unit_economics(output_path, pricing_rows):
    if not os.path.isfile(output_path):
        return False
    # Verify header exactly matches
    required_header = "sku,price_effective,payment_fee,platform_fee,variable_cost_per_order,revenue_net_per_order,contribution_margin_per_order"
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line != required_header:
                return False
            f.seek(0)
            reader = csv.DictReader(f)
            # Verify order of fieldnames exactly
            if reader.fieldnames is None:
                return False
            if ",".join(reader.fieldnames) != required_header:
                return False
            rows = list(reader)
    except Exception:
        return False
    # Build expected per SKU
    expected = {}
    for r in pricing_rows:
        ue = compute_unit_econ(r)
        expected[r["sku"]] = ue
    # Validate counts
    if len(rows) != len(expected):
        return False
    seen_skus = set()
    for row in rows:
        sku = row.get("sku", "")
        if not sku or sku in seen_skus:
            return False
        seen_skus.add(sku)
        if sku not in expected:
            return False
        ue = expected[sku]
        # Parse numeric fields and compare with tolerance 0.01
        try:
            pf = float(row["price_effective"])
            pay = float(row["payment_fee"])
            plat = float(row["platform_fee"])
            vc = float(row["variable_cost_per_order"])
            rev = float(row["revenue_net_per_order"])
            cm = float(row["contribution_margin_per_order"])
        except Exception:
            return False
        if not (near(pf, ue["price_effective"], 0.01) and
                near(pay, ue["payment_fee"], 0.01) and
                near(plat, ue["platform_fee"], 0.01) and
                near(vc, ue["variable_cost_per_order"], 0.01) and
                near(rev, ue["revenue_net_per_order"], 0.01) and
                near(cm, ue["contribution_margin_per_order"], 0.01)):
            return False
    return True

def check_breakeven_summary(output_path, pricing_rows, yaml_data):
    if not os.path.isfile(output_path):
        return False
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    if "per_sku" not in data or not isinstance(data["per_sku"], dict):
        return False
    per_sku_out = data["per_sku"]
    # Inputs
    overhead = yaml_data.get("fixed_overhead_per_month")
    planned_orders = yaml_data.get("planned_orders_per_month")
    target_cpa = yaml_data.get("target_cpa")
    if any(v is None for v in [overhead, planned_orders, target_cpa]):
        return False
    # Compute expected per sku
    exp_map = {}
    for r in pricing_rows:
        be = compute_breakeven(r, overhead, planned_orders)
        exp_map[r["sku"]] = {
            **be,
            "decision": decision_label(be["breakeven_cpa_fully_loaded"], target_cpa)
        }
    # Check keys match
    if set(per_sku_out.keys()) != set(exp_map.keys()):
        return False
    # Compare values
    for sku, vals in per_sku_out.items():
        if not isinstance(vals, dict):
            return False
        exp = exp_map[sku]
        # Integer exact for break_even_orders
        beo = vals.get("break_even_orders")
        if not isinstance(beo, int):
            # allow numeric string?
            if isinstance(beo, (float, str)):
                try:
                    beo_int = int(float(beo))
                except Exception:
                    return False
            else:
                return False
            if beo_int != exp["break_even_orders"]:
                return False
        else:
            if beo != exp["break_even_orders"]:
                return False
        # Tolerant checks for money
        money_fields = [
            "break_even_revenue_net",
            "breakeven_cpa_variable",
            "breakeven_cpa_fully_loaded",
            "breakeven_roas_variable",
            "breakeven_roas_fully_loaded",
        ]
        for mf in money_fields:
            v = vals.get(mf)
            if v is None:
                return False
            vnum = to_float(v)
            if vnum is None:
                return False
            if not near(vnum, exp[mf], 0.01):
                return False
        # Decision
        dec = vals.get("decision")
        if dec not in ("scale","launch","hold"):
            return False
        if dec != exp["decision"]:
            return False
    return True

def check_sensitivity(output_path, pricing_rows):
    if not os.path.isfile(output_path):
        return False
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    if "per_sku" not in data or not isinstance(data["per_sku"], dict):
        return False
    per_sku_out = data["per_sku"]
    # Map entries
    pr_map = {r["sku"]: r for r in pricing_rows}
    if set(per_sku_out.keys()) != set(pr_map.keys()):
        return False
    keys_required = [
        "selling_price_plus_10pct",
        "cogs_plus_10pct",
        "shipping_cost_plus_10pct",
        "payment_fee_pct_plus_10pct",
        "platform_fee_pct_plus_10pct",
        "discount_rate_plus_10pct",
        "refund_rate_plus_10pct",
    ]
    for sku, content in per_sku_out.items():
        if not isinstance(content, dict):
            return False
        delta_block = content.get("delta_on_cpa_variable_if")
        if not isinstance(delta_block, dict):
            return False
        # Compute expected deltas
        exp_deltas = compute_sensitivity_deltas(pr_map[sku])
        # Check keys and values
        if set(delta_block.keys()) != set(keys_required):
            return False
        for k in keys_required:
            v = delta_block.get(k)
            vnum = to_float(v)
            if vnum is None:
                return False
            if not near(vnum, exp_deltas[k], 0.01):
                return False
    return True

def main():
    workspace_root = get_workspace_root()
    input_dir = abs_path(workspace_root, "input")
    output_dir = abs_path(workspace_root, "output")

    product_csv = abs_path(input_dir, "product_pricing.csv")
    marketing_yaml = abs_path(input_dir, "marketing_targets.yaml")

    pricing_rows = read_product_pricing_csv(product_csv)
    yaml_data = parse_simple_yaml_numbers(marketing_yaml)

    # If inputs cannot be read, all checks fail but no crashes
    checks = {
        "assumptions_ok": False,
        "unit_economics_ok": False,
        "breakeven_ok": False,
        "sensitivity_ok": False,
    }

    # Only proceed if inputs are parsed
    if pricing_rows is not None and yaml_data is not None:
        # 1) assumptions.json
        assumptions_path = abs_path(output_dir, "assumptions.json")
        checks["assumptions_ok"] = check_assumptions(assumptions_path, pricing_rows, yaml_data)

        # 2) unit_economics.csv
        unit_econ_path = abs_path(output_dir, "unit_economics.csv")
        checks["unit_economics_ok"] = check_unit_economics(unit_econ_path, pricing_rows)

        # 3) breakeven_summary.json
        breakeven_path = abs_path(output_dir, "breakeven_summary.json")
        checks["breakeven_ok"] = check_breakeven_summary(breakeven_path, pricing_rows, yaml_data)

        # 4) sensitivity.json
        sensitivity_path = abs_path(output_dir, "sensitivity.json")
        checks["sensitivity_ok"] = check_sensitivity(sensitivity_path, pricing_rows)

    # Reward: average of four checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()