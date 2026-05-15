import json
import os
import sys
import csv
from math import ceil, isfinite
from datetime import datetime, timedelta

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_yaml_simple(yaml_text):
    # Minimal YAML parser for simple key: value and nested mappings via indentation
    # Supports:
    # - comments starting with '#'
    # - scalar values (int/float/str/bool/null)
    # - nested dicts via indentation
    # - flat dicts of dicts (no sequences/lists support)
    def parse_value(val):
        sval = val.strip()
        if sval == "":
            return ""
        low = sval.lower()
        if low in ("true", "false"):
            return low == "true"
        if low in ("null", "none", "~"):
            return None
        # numeric
        try:
            if "." in sval or "e" in sval.lower():
                return float(sval)
            else:
                return int(sval)
        except ValueError:
            pass
        # strip surrounding quotes
        if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
            return sval[1:-1]
        return sval

    lines = yaml_text.splitlines()
    root = {}
    stack = [(root, -1)]  # list of (container_dict, indent_level)
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        # strip comments
        if "#" in line:
            hash_index = line.find("#")
            if hash_index == 0 or line[:hash_index].strip() == "":
                line = line[:hash_index]
            else:
                # allow inline comment after value; keep value
                line = line[:hash_index]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Adjust stack to current indent
        while stack and indent <= stack[-1][1]:
            stack.pop()
        current = stack[-1][0]
        # Only handle mappings: "key: value" or "key:" starting nested map
        if ":" not in line:
            # Unsupported (e.g., list item); skip gracefully
            continue
        key, sep, rest = line.lstrip().partition(":")
        key = key.strip()
        val = rest.strip()
        if val == "":
            # start a new nested dict
            new_map = {}
            current[key] = new_map
            stack.append((new_map, indent))
        else:
            current[key] = parse_value(val)
    return root

def to_iso_date(s):
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        # Try common formats
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
    return None

def round_float(x):
    try:
        return float(x)
    except Exception:
        return None

def cmp_num(a, b):
    if a is None or b is None:
        return False
    try:
        a = float(a); b = float(b)
    except Exception:
        return False
    tol = max(0.01 * abs(b), 5.0)
    return abs(a - b) <= tol

def get_carton_dims_cm(product):
    # try nested dict
    dims = None
    for key in ["carton_dimensions_cm", "carton", "master_carton", "carton_dims_cm"]:
        if isinstance(product.get(key), dict):
            dims = product.get(key)
            break
    if dims:
        # Support keys L/W/H or length/width/height
        L = dims.get("L") or dims.get("l") or dims.get("length") or dims.get("length_cm") or dims.get("Length")
        W = dims.get("W") or dims.get("w") or dims.get("width") or dims.get("width_cm") or dims.get("Width")
        H = dims.get("H") or dims.get("h") or dims.get("height") or dims.get("height_cm") or dims.get("Height")
        if L is not None and W is not None and H is not None:
            return float(L), float(W), float(H)
    # flat keys
    candidates = [
        ("carton_L_cm", "carton_W_cm", "carton_H_cm"),
        ("carton_length_cm", "carton_width_cm", "carton_height_cm"),
        ("master_carton_length_cm", "master_carton_width_cm", "master_carton_height_cm")
    ]
    for a, b, c in candidates:
        if a in product and b in product and c in product:
            return float(product[a]), float(product[b]), float(product[c])
    return None, None, None

def normalize_destination(dest):
    if not dest:
        return None
    d = str(dest).strip().lower()
    if "united states" in d or d == "us" or "usa" in d or "u.s." in d:
        return "US"
    if "germany" in d or d == "de" or "deutschland" in d:
        return "DE"
    # other codes passthrough uppercase
    return dest.upper()

def is_china_origin(origin_str):
    if not origin_str:
        return False
    s = str(origin_str).lower()
    return "china" in s or "prc" in s or s.strip() in ("cn", "china", "prc")

def compute_expected_for_method(shipment, product, rates, method):
    # Extract needed parameters safely
    quantity = int(shipment.get("quantity") or shipment.get("units") or 0)
    units_per_carton = int(product.get("units_per_carton") or product.get("unitsPerCarton") or product.get("per_carton_units") or 0)
    unit_weight_kg = float(product.get("unit_weight_kg") or product.get("unitWeightKg") or product.get("weight_kg") or 0.0)
    unit_cost_usd = float(product.get("unit_cost_usd") or product.get("unitCostUsd") or 0.0)
    duty_category = product.get("duty_category") or product.get("hs_category") or product.get("hs_code_category")
    L_cm, W_cm, H_cm = get_carton_dims_cm(product)
    if not (units_per_carton and quantity and unit_weight_kg is not None and unit_cost_usd is not None and L_cm and W_cm and H_cm and duty_category):
        return None  # insufficient input to compute

    # Derived
    total_cartons = ceil(quantity / units_per_carton)
    carton_cbm = (L_cm * W_cm * H_cm) / 1_000_000.0
    volume_cbm = carton_cbm * total_cartons
    actual_weight_kg = quantity * unit_weight_kg
    volumetric_divisor = float(rates.get("volumetric_divisor", 6000))
    volumetric_weight_kg = total_cartons * ((L_cm * W_cm * H_cm) / volumetric_divisor)
    if method in ("air", "express"):
        chargeable_weight_kg = max(actual_weight_kg, volumetric_weight_kg)
    else:
        chargeable_weight_kg = actual_weight_kg  # sea can set to actual (ignored in freight calc)

    # Freight rates
    sea_rate = float(rates.get("sea_lcl_usd_per_cbm", 0.0))
    air_rate = float(rates.get("air_usd_per_kg", 0.0))
    express_rate = float(rates.get("express_usd_per_kg", 0.0))
    if method == "sea":
        freight_cost_usd = sea_rate * volume_cbm
    elif method == "air":
        freight_cost_usd = air_rate * chargeable_weight_kg
    else:
        freight_cost_usd = express_rate * chargeable_weight_kg

    product_cost_usd = unit_cost_usd * quantity

    # Duty and VAT
    duty_rates = rates.get("duty_rates") or {}
    base_duty_rate = float(duty_rates.get(duty_category, 0.0))
    s301 = float(rates.get("section_301_cn_extra", 0.0)) if is_china_origin(shipment.get("origin") or shipment.get("origin_country")) else 0.0
    duty_rate_total = base_duty_rate + s301
    customs_duty_usd = product_cost_usd * duty_rate_total

    vat_rates = rates.get("vat_rates") or {}
    dest_key = normalize_destination(shipment.get("destination") or shipment.get("destination_country"))
    vat_rate = float(vat_rates.get(dest_key, 0.0))
    vat_base = product_cost_usd + freight_cost_usd + customs_duty_usd
    vat_usd = vat_base * vat_rate

    # Fees
    customs_broker_fee_usd = float(rates.get("customs_broker_flat_usd", 0.0))
    port_handling_usd = float(rates.get("port_handling_usd", 0.0))
    inland_delivery_usd = float(rates.get("inland_to_fba_usd_per_carton", 0.0)) * total_cartons
    fba_inbound_placement_usd = float(rates.get("fba_inbound_placement_usd_per_unit", 0.0)) * quantity

    total_landed_cost_usd = product_cost_usd + freight_cost_usd + customs_duty_usd + vat_usd + customs_broker_fee_usd + port_handling_usd + inland_delivery_usd + fba_inbound_placement_usd
    landed_cost_per_unit_usd = total_landed_cost_usd / quantity if quantity else 0.0

    # timeline fields
    transit_days_map = rates.get("transit_days") or {}
    clearance_days_map = rates.get("clearance_days") or {}
    transit_days = int((transit_days_map.get(method) or transit_days_map.get(method.capitalize()) or 0))
    clearance_days = int((clearance_days_map.get(method) or clearance_days_map.get(method.capitalize()) or 0))

    # other timeline offsets
    export_loading_days = int(rates.get("export_loading_days", 0))
    production_lead_time_days = int(rates.get("production_lead_time_days", 0))
    fba_receiving_buffer_days = int(rates.get("fba_receiving_buffer_days", 0))
    port_to_fba_days = int(rates.get("port_to_fba_days", 0))

    target_instock_date = to_iso_date(shipment.get("target_instock_date") or shipment.get("target_in_stock_date") or "")
    ship_by_date = None
    if target_instock_date:
        days_to_subtract = fba_receiving_buffer_days + port_to_fba_days + clearance_days + transit_days + export_loading_days + production_lead_time_days
        ship_by_date = target_instock_date - timedelta(days=days_to_subtract)

    return {
        "quantity": quantity,
        "units_per_carton": units_per_carton,
        "carton_cbm": carton_cbm,
        "total_cartons": total_cartons,
        "volume_cbm": volume_cbm,
        "actual_weight_kg": actual_weight_kg,
        "volumetric_weight_kg": volumetric_weight_kg,
        "chargeable_weight_kg": chargeable_weight_kg,
        "freight_cost_usd": freight_cost_usd,
        "product_cost_usd": product_cost_usd,
        "customs_duty_usd": customs_duty_usd,
        "vat_usd": vat_usd,
        "customs_broker_fee_usd": float(rates.get("customs_broker_flat_usd", 0.0)),
        "port_handling_usd": float(rates.get("port_handling_usd", 0.0)),
        "inland_delivery_usd": inland_delivery_usd,
        "fba_inbound_placement_usd": fba_inbound_placement_usd,
        "total_landed_cost_usd": total_landed_cost_usd,
        "landed_cost_per_unit_usd": landed_cost_per_unit_usd,
        "ship_by_date": ship_by_date,
        "transit_days": transit_days,
        "clearance_days": clearance_days,
        "assumptions": {
            "duty_rate": duty_rate_total,
            "section_301_applied": s301 > 0.0,
            "vat_rate": vat_rate,
            "volumetric_divisor": float(rates.get("volumetric_divisor", 6000)),
            "inland_per_carton_usd": float(rates.get("inland_to_fba_usd_per_carton", 0.0)),
            "fba_inbound_per_unit_usd": float(rates.get("fba_inbound_placement_usd_per_unit", 0.0)),
        }
    }

def verify_csv(file_path, expected_by_method):
    results = {
        "structure_ok": False,
        "methods_ok": False,
        "ship_by_dates_valid": False,
        "numeric_values_ok": False,
        "ship_by_dates_match": False
    }
    required_header = ["method","transit_days","volume_cbm","total_cartons","actual_weight_kg","chargeable_weight_kg","freight_cost_usd","product_cost_usd","customs_duty_usd","vat_usd","customs_broker_fee_usd","port_handling_usd","inland_delivery_usd","fba_inbound_placement_usd","total_landed_cost_usd","landed_cost_per_unit_usd","ship_by_date"]
    if not os.path.isfile(file_path):
        return results

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return results

    if not rows:
        return results
    header = rows[0]
    data_rows = rows[1:]
    if header == required_header and len(data_rows) == 3:
        results["structure_ok"] = True

    # parse rows into dicts
    methods_seen = set()
    methods_ok = True
    ship_by_dates_valid = True
    ship_by_match_all = True
    numeric_ok_all = True

    # Create mapping for expected by method
    expect = expected_by_method  # dict method->expected dict

    for r in data_rows:
        if len(r) != len(required_header):
            numeric_ok_all = False
            ship_by_dates_valid = False
            methods_ok = False
            continue
        row = {required_header[i]: r[i] for i in range(len(required_header))}
        method_val = (row["method"] or "").strip().lower()
        if method_val not in ("sea", "air", "express"):
            methods_ok = False
        methods_seen.add(method_val)

        # check ship_by_date is valid ISO
        sd = to_iso_date(row["ship_by_date"])
        if sd is None:
            ship_by_dates_valid = False

        # Compare numeric values to expected
        exp = expect.get(method_val)
        if not exp:
            numeric_ok_all = False
            ship_by_match_all = False
            continue

        fields_to_check = [
            ("transit_days", exp["transit_days"], int),
            ("volume_cbm", exp["volume_cbm"], float),
            ("total_cartons", exp["total_cartons"], int),
            ("actual_weight_kg", exp["actual_weight_kg"], float),
            ("chargeable_weight_kg", exp["chargeable_weight_kg"], float),
            ("freight_cost_usd", exp["freight_cost_usd"], float),
            ("product_cost_usd", exp["product_cost_usd"], float),
            ("customs_duty_usd", exp["customs_duty_usd"], float),
            ("vat_usd", exp["vat_usd"], float),
            ("customs_broker_fee_usd", exp["customs_broker_fee_usd"], float),
            ("port_handling_usd", exp["port_handling_usd"], float),
            ("inland_delivery_usd", exp["inland_delivery_usd"], float),
            ("fba_inbound_placement_usd", exp["fba_inbound_placement_usd"], float),
            ("total_landed_cost_usd", exp["total_landed_cost_usd"], float),
            ("landed_cost_per_unit_usd", exp["landed_cost_per_unit_usd"], float),
        ]
        for field, expected_val, _typ in fields_to_check:
            csv_val = row[field]
            try:
                # Transit days should be exact integer match; others use tolerance
                if field == "transit_days" or field == "total_cartons":
                    if int(float(csv_val)) != int(expected_val):
                        numeric_ok_all = False
                else:
                    if not cmp_num(float(csv_val), float(expected_val)):
                        numeric_ok_all = False
            except Exception:
                numeric_ok_all = False

        # ship_by_date match
        exp_date = exp.get("ship_by_date")
        if exp_date is None or sd is None or sd != exp_date:
            ship_by_match_all = False

    if methods_seen == {"sea", "air", "express"}:
        results["methods_ok"] = methods_ok
    else:
        results["methods_ok"] = False

    results["ship_by_dates_valid"] = ship_by_dates_valid
    results["numeric_values_ok"] = numeric_ok_all
    results["ship_by_dates_match"] = ship_by_match_all
    return results

def verify_breakdown(file_path, expected_by_method, rates, shipment):
    res = {
        "structure_ok": False,
        "assumptions_present": False,
        "totals_match_any_method": False
    }
    if not os.path.isfile(file_path):
        return res
    data = load_json(file_path)
    if not isinstance(data, dict):
        return res
    # structure
    required_totals = ["product_cost_usd","freight_cost_usd","customs_duty_usd","vat_usd","fees_usd","total_landed_cost_usd","landed_cost_per_unit_usd"]
    required_assump = ["duty_rate","section_301_applied","vat_rate","volumetric_divisor","inland_per_carton_usd","fba_inbound_per_unit_usd"]
    if ("shipment_id" in data
        and isinstance(data.get("line_items"), list)
        and isinstance(data.get("totals"), dict)
        and isinstance(data.get("assumptions"), dict)
        and all(k in data["totals"] for k in required_totals)):
        res["structure_ok"] = True
    # assumptions presence and match
    ass = data.get("assumptions") or {}
    if all(k in ass for k in required_assump):
        res["assumptions_present"] = True
        # Optionally validate key assumptions against computed
        any_method = next(iter(expected_by_method.values()))
        exp_ass = any_method["assumptions"]
        def approx(a,b):
            try: return cmp_num(float(a), float(b))
            except: return False
        # duty_rate
        # section_301_applied
        # vat_rate etc.
        # We do not flip to False if mismatched, we already set presence True based on keys.

    # reconcile totals with any method's CSV totals
    totals = data.get("totals") or {}
    # compute fees_usd expected as sum of fees (broker + port + inland + fba inbound)
    matched = False
    for method, exp in expected_by_method.items():
        fees_exp = exp["customs_broker_fee_usd"] + exp["port_handling_usd"] + exp["inland_delivery_usd"] + exp["fba_inbound_placement_usd"]
        checks = [
            cmp_num(totals.get("product_cost_usd"), exp["product_cost_usd"]),
            cmp_num(totals.get("freight_cost_usd"), exp["freight_cost_usd"]),
            cmp_num(totals.get("customs_duty_usd"), exp["customs_duty_usd"]),
            cmp_num(totals.get("vat_usd"), exp["vat_usd"]),
            cmp_num(totals.get("fees_usd"), fees_exp),
            cmp_num(totals.get("total_landed_cost_usd"), exp["total_landed_cost_usd"]),
            cmp_num(totals.get("landed_cost_per_unit_usd"), exp["landed_cost_per_unit_usd"]),
        ]
        if all(checks):
            matched = True
            break
    res["totals_match_any_method"] = matched
    return res

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Required output files
    path_comparison_US = os.path.join(output_dir, "comparison_US.csv")
    path_comparison_DE = os.path.join(output_dir, "comparison_DE.csv")
    path_breakdown_US = os.path.join(output_dir, "landed_breakdown_US.json")
    path_breakdown_DE = os.path.join(output_dir, "landed_breakdown_DE.json")
    path_timeline = os.path.join(output_dir, "timeline_plan.md")
    path_recommendation = os.path.join(output_dir, "recommendation.md")
    path_red_flags = os.path.join(output_dir, "red_flags.txt")

    checks["has_comparison_US_csv"] = os.path.isfile(path_comparison_US)
    checks["has_comparison_DE_csv"] = os.path.isfile(path_comparison_DE)
    checks["has_landed_breakdown_US_json"] = os.path.isfile(path_breakdown_US)
    checks["has_landed_breakdown_DE_json"] = os.path.isfile(path_breakdown_DE)
    checks["has_timeline_plan_md"] = os.path.isfile(path_timeline)
    checks["has_recommendation_md"] = os.path.isfile(path_recommendation)
    checks["has_red_flags_txt"] = os.path.isfile(path_red_flags)

    # Load inputs
    product = load_json(os.path.join(input_dir, "product.json")) or {}
    shipments_data = load_json(os.path.join(input_dir, "shipments.json")) or {}
    rates_text = read_text(os.path.join(input_dir, "rates.yaml")) or ""
    rates = parse_yaml_simple(rates_text) if rates_text else {}

    # Collect shipments list
    shipments = []
    if isinstance(shipments_data, list):
        shipments = shipments_data
    elif isinstance(shipments_data, dict):
        if isinstance(shipments_data.get("shipments"), list):
            shipments = shipments_data.get("shipments")
        else:
            # maybe contains two keys
            shipments = [v for v in shipments_data.values() if isinstance(v, dict)]
    # Map shipments by destination
    by_dest = {}
    for s in shipments:
        dest = normalize_destination(s.get("destination") or s.get("destination_country"))
        if dest:
            by_dest[dest] = s
    shipment_US = by_dest.get("US")
    shipment_DE = by_dest.get("DE")

    # Precompute expected for each shipment and method if possible
    def compute_expected_for_shipment(shipment):
        if not isinstance(shipment, dict):
            return None
        exp = {}
        for m in ("sea", "air", "express"):
            comp = compute_expected_for_method(shipment, product, rates, m)
            if comp is None:
                return None
            exp[m] = comp
        return exp

    expected_US = compute_expected_for_shipment(shipment_US) if shipment_US else None
    expected_DE = compute_expected_for_shipment(shipment_DE) if shipment_DE else None

    # CSV verifications
    csv_US = verify_csv(path_comparison_US, expected_US or {})
    csv_DE = verify_csv(path_comparison_DE, expected_DE or {})

    checks["comparison_US_structure"] = csv_US["structure_ok"]
    checks["comparison_DE_structure"] = csv_DE["structure_ok"]
    checks["comparison_US_methods_valid"] = csv_US["methods_ok"]
    checks["comparison_DE_methods_valid"] = csv_DE["methods_ok"]
    checks["comparison_US_ship_by_date_valid"] = csv_US["ship_by_dates_valid"]
    checks["comparison_DE_ship_by_date_valid"] = csv_DE["ship_by_dates_valid"]
    checks["comparison_US_values_match"] = csv_US["numeric_values_ok"] if expected_US else False
    checks["comparison_DE_values_match"] = csv_DE["numeric_values_ok"] if expected_DE else False
    checks["comparison_US_ship_by_date_match"] = csv_US["ship_by_dates_match"] if expected_US else False
    checks["comparison_DE_ship_by_date_match"] = csv_DE["ship_by_dates_match"] if expected_DE else False

    # Breakdown verifications
    bd_US = verify_breakdown(path_breakdown_US, expected_US or {}, rates, shipment_US or {})
    bd_DE = verify_breakdown(path_breakdown_DE, expected_DE or {}, rates, shipment_DE or {})
    checks["breakdown_US_structure"] = bd_US["structure_ok"]
    checks["breakdown_DE_structure"] = bd_DE["structure_ok"]
    checks["breakdown_US_assumptions_present"] = bd_US["assumptions_present"]
    checks["breakdown_DE_assumptions_present"] = bd_DE["assumptions_present"]
    checks["breakdown_US_totals_match_csv"] = bd_US["totals_match_any_method"]
    checks["breakdown_DE_totals_match_csv"] = bd_DE["totals_match_any_method"]

    # Timeline plan checks
    timeline_text = read_text(path_timeline) if os.path.isfile(path_timeline) else ""
    ids_in_shipments = []
    for s in shipments:
        sid = s.get("shipment_id") or s.get("id") or s.get("name")
        if sid:
            ids_in_shipments.append(str(sid))
    timeline_has_ids = True
    if ids_in_shipments:
        for sid in ids_in_shipments:
            if timeline_text.find(sid) == -1:
                timeline_has_ids = False
                break
    else:
        timeline_has_ids = False
    checks["timeline_contains_shipment_ids"] = timeline_has_ids

    # Check order placement dates present and match
    def expected_order_dates(exp):
        if not exp:
            return []
        out = []
        for m in ("sea", "air", "express"):
            d = exp[m].get("ship_by_date")
            if d:
                out.append(d.strftime("%Y-%m-%d"))
        return out

    expected_dates = set(expected_order_dates(expected_US) + expected_order_dates(expected_DE))
    timeline_dates_match = False
    if timeline_text and expected_dates:
        found = 0
        for d in expected_dates:
            if f"Order placement date: {d}" in timeline_text:
                found += 1
        # require all expected dates to be present
        timeline_dates_match = (found == len(expected_dates))
    checks["timeline_order_dates_match"] = timeline_dates_match

    # Recommendation checks
    rec_text = read_text(path_recommendation) if os.path.isfile(path_recommendation) else ""
    rec_ok = False
    if rec_text:
        # must contain both shipment identifiers and for each, a method recommendation with reasoning keywords
        methods_words = ("Sea", "Air", "Express")
        reason_ok = (" because " in rec_text.lower()) or (" due to " in rec_text.lower())
        cost_ok = ("cost" in rec_text.lower())
        transit_ok = ("transit" in rec_text.lower()) or ("timeline" in rec_text.lower())
        ids_present = True
        for s in shipments:
            sid = s.get("shipment_id") or s.get("id") or s.get("name")
            if sid and (str(sid) not in rec_text):
                ids_present = False
        methods_present = sum(1 for w in methods_words if w.lower() in rec_text.lower()) >= 2  # at least two mentions across two shipments
        rec_ok = ids_present and reason_ok and cost_ok and transit_ok and methods_present
    checks["recommendation_content_ok"] = rec_ok

    # Red flags checks
    rf_text = read_text(path_red_flags) if os.path.isfile(path_red_flags) else ""
    rf_ok = False
    if rf_text:
        s301_or_23 = ("section 301" in rf_text.lower()) or ("23 kg" in rf_text.lower()) or ("23kg" in rf_text.lower())
        fba_note = ("placement fee" in rf_text.lower()) or ("labels" in rf_text.lower()) or ("label" in rf_text.lower())
        rf_ok = s301_or_23 and fba_note
    checks["red_flags_content_ok"] = rf_ok

    # Compute reward as fraction of passed checks (only output-dependent checks are included)
    passed = sum(1 for v in checks.values() if v is True)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty required artifacts, ensure reward is 0.0
    required_any = any([
        checks["has_comparison_US_csv"], checks["has_comparison_DE_csv"],
        checks["has_landed_breakdown_US_json"], checks["has_landed_breakdown_DE_json"],
        checks["has_timeline_plan_md"], checks["has_recommendation_md"], checks["has_red_flags_txt"]
    ])
    if not required_any:
        reward = 0.0

    # Print JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()