import json
import os
import sys
from decimal import Decimal, InvalidOperation

def to_decimal(val):
    try:
        if isinstance(val, (int, float, str)):
            return Decimal(str(val))
        else:
            return None
    except (InvalidOperation, ValueError):
        return None

def approx_equal(a, b, tol=Decimal("0.005")):
    da = to_decimal(a)
    db = to_decimal(b)
    if da is None or db is None:
        return False
    return abs(da - db) <= tol

def read_json_array(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_string(x):
    return isinstance(x, str)

def is_number_like(x):
    if isinstance(x, (int, float)):
        return True
    if isinstance(x, str):
        try:
            Decimal(x)
            return True
        except Exception:
            return False
    return False

def validate_period_fields(obj):
    required_fields = [
        "id",
        "customer_id",
        "meter_id",
        "period_start",
        "period_end",
        "total_consumption",
        "base_charge",
        "usage_charge",
        "adjustments_total",
        "subtotal",
        "tax_amount",
        "grand_total",
    ]
    for k in required_fields:
        if k not in obj:
            return False
    # Types
    if not (is_string(obj["id"]) and is_string(obj["customer_id"]) and is_string(obj["meter_id"]) and is_string(obj["period_start"]) and is_string(obj["period_end"])):
        return False
    for nk in ["total_consumption", "base_charge", "usage_charge", "adjustments_total", "subtotal", "tax_amount", "grand_total"]:
        if not is_number_like(obj[nk]):
            return False
    return True

def validate_invoice_fields(obj):
    required_fields = ["invoice_id", "customer_id", "billing_period_ids", "subtotal", "tax_amount", "prepaid_applied", "grand_total"]
    for k in required_fields:
        if k not in obj:
            return False
    if not (is_string(obj["invoice_id"]) and is_string(obj["customer_id"]) and isinstance(obj["billing_period_ids"], list) and len(obj["billing_period_ids"]) > 0):
        return False
    for nid in obj["billing_period_ids"]:
        if not is_string(nid):
            return False
    for nk in ["subtotal", "tax_amount", "prepaid_applied", "grand_total"]:
        if not is_number_like(obj[nk]):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "billing_periods_file_exists": False,
        "invoices_file_exists": False,
        "summary_file_exists": False,
        "billing_periods_count_3": False,
        "billing_periods_fields_valid": False,
        "billing_periods_dates_valid": False,
        "period_MTR_E_1_values": False,
        "period_MTR_E_2_values": False,
        "period_MTR_S_1_values": False,
        "invoices_count_2": False,
        "invoices_fields_valid": False,
        "invoice_cust001_values_and_ids": False,
        "invoice_cust002_values_and_ids": False,
        "summary_contains_required_phrases": False,
        "summary_totals_match": False,
        "summary_confirmation_note": False,
    }

    # Paths
    billing_periods_path = os.path.join(output_dir, "billing_periods.json")
    invoices_path = os.path.join(output_dir, "invoices.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Existence
    if os.path.isfile(billing_periods_path):
        checks["billing_periods_file_exists"] = True
    if os.path.isfile(invoices_path):
        checks["invoices_file_exists"] = True
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True

    periods = None
    if checks["billing_periods_file_exists"]:
        periods = read_json_array(billing_periods_path)
        if isinstance(periods, list) and len(periods) == 3:
            checks["billing_periods_count_3"] = True

        # Validate fields and dates
        if isinstance(periods, list):
            all_fields_ok = True
            all_dates_ok = True
            for p in periods:
                if not validate_period_fields(p):
                    all_fields_ok = False
                    break
            if all_fields_ok:
                checks["billing_periods_fields_valid"] = True
                for p in periods:
                    if not (p.get("period_start") == "2026-02-01" and p.get("period_end") == "2026-02-29"):
                        all_dates_ok = False
                        break
                if all_dates_ok:
                    checks["billing_periods_dates_valid"] = True

    # Map periods by (customer_id, meter_id)
    period_map = {}
    period_ids_by_customer = {}
    if checks["billing_periods_fields_valid"]:
        for p in periods:
            key = (p.get("customer_id"), p.get("meter_id"))
            period_map[key] = p
            period_ids_by_customer.setdefault(p.get("customer_id"), set()).add(p.get("id"))

        # Expected specifics
        # MTR-E-1 (CUST-001): consumption 125, usage_charge 12.00, base 15.00, adj 0.00, subtotal 27.00, tax 2.70, grand_total 29.70
        p_e1 = period_map.get(("CUST-001", "MTR-E-1"))
        if p_e1:
            conds = [
                approx_equal(p_e1.get("total_consumption"), 125),
                approx_equal(p_e1.get("usage_charge"), Decimal("12.00")),
                approx_equal(p_e1.get("base_charge"), Decimal("15.00")),
                approx_equal(p_e1.get("adjustments_total"), Decimal("0.00")),
                approx_equal(p_e1.get("subtotal"), Decimal("27.00")),
                approx_equal(p_e1.get("tax_amount"), Decimal("2.70")),
                approx_equal(p_e1.get("grand_total"), Decimal("29.70")),
            ]
            if all(conds):
                checks["period_MTR_E_1_values"] = True

        # MTR-E-2 (CUST-002): consumption 60, usage 6.00, base 15.00, min to 25 before adj; adj -5.00 => subtotal 20.00; tax 2.00; grand 22.00
        p_e2 = period_map.get(("CUST-002", "MTR-E-2"))
        if p_e2:
            conds = [
                approx_equal(p_e2.get("total_consumption"), 60),
                approx_equal(p_e2.get("usage_charge"), Decimal("6.00")),
                approx_equal(p_e2.get("base_charge"), Decimal("15.00")),
                approx_equal(p_e2.get("adjustments_total"), Decimal("-5.00")),
                approx_equal(p_e2.get("subtotal"), Decimal("20.00")),
                approx_equal(p_e2.get("tax_amount"), Decimal("2.00")),
                approx_equal(p_e2.get("grand_total"), Decimal("22.00")),
            ]
            if all(conds):
                checks["period_MTR_E_2_values"] = True

        # MTR-S-1 (CUST-001): consumption 2300, usage 10.20, base 0, adj 0, subtotal 10.20, tax 1.02, grand 11.22
        p_s1 = period_map.get(("CUST-001", "MTR-S-1"))
        if p_s1:
            conds = [
                approx_equal(p_s1.get("total_consumption"), 2300),
                approx_equal(p_s1.get("usage_charge"), Decimal("10.20")),
                approx_equal(p_s1.get("base_charge"), Decimal("0.00")),
                approx_equal(p_s1.get("adjustments_total"), Decimal("0.00")),
                approx_equal(p_s1.get("subtotal"), Decimal("10.20")),
                approx_equal(p_s1.get("tax_amount"), Decimal("1.02")),
                approx_equal(p_s1.get("grand_total"), Decimal("11.22")),
            ]
            if all(conds):
                checks["period_MTR_S_1_values"] = True

    invoices = None
    if checks["invoices_file_exists"]:
        invoices = read_json_array(invoices_path)
        if isinstance(invoices, list) and len(invoices) == 2:
            checks["invoices_count_2"] = True

        if isinstance(invoices, list) and checks["billing_periods_fields_valid"]:
            fields_ok = True
            for inv in invoices:
                if not validate_invoice_fields(inv):
                    fields_ok = False
                    break
            if fields_ok:
                # Validate period id references by customer and coverage
                # Build expected period IDs by customer
                # Only set fields_valid True if billing_period_ids reference valid period ids
                all_refs_ok = True
                cover_map = {cust: set() for cust in period_ids_by_customer.keys()}
                for inv in invoices:
                    cust = inv.get("customer_id")
                    ids_set = set(inv.get("billing_period_ids", []))
                    # All ids must exist and belong to that customer
                    for pid in ids_set:
                        # Check exists in any
                        belongs = False
                        for c, s in period_ids_by_customer.items():
                            if pid in s:
                                belongs = True
                                # If it belongs to different customer, fail
                                if c != cust:
                                    all_refs_ok = False
                                break
                        if not belongs:
                            all_refs_ok = False
                    # Track coverage for this customer
                    if cust in cover_map:
                        cover_map[cust].update(ids_set)
                # Verify coverage equals all for each customer
                for cust, s in period_ids_by_customer.items():
                    if cover_map.get(cust, set()) != s:
                        all_refs_ok = False
                        break
                if all_refs_ok:
                    checks["invoices_fields_valid"] = True

            # Individual invoice value checks
            # Compute expected per-customer sums
            if checks["billing_periods_fields_valid"]:
                expected_cust = {
                    "CUST-001": {
                        "subtotal": Decimal("37.20"),
                        "tax_amount": Decimal("3.72"),
                        "prepaid_applied": Decimal("30.00"),
                        "grand_total": Decimal("10.92"),
                    },
                    "CUST-002": {
                        "subtotal": Decimal("20.00"),
                        "tax_amount": Decimal("2.00"),
                        "prepaid_applied": Decimal("0.00"),
                        "grand_total": Decimal("22.00"),
                    },
                }
                # Build map of invoices by customer
                inv_by_cust = {}
                for inv in invoices:
                    inv_by_cust[inv.get("customer_id")] = inv

                # For CUST-001
                inv1 = inv_by_cust.get("CUST-001")
                if inv1 and checks["invoices_fields_valid"]:
                    v = expected_cust["CUST-001"]
                    ids_set = set(inv1.get("billing_period_ids", []))
                    expected_ids = period_ids_by_customer.get("CUST-001", set())
                    conds = [
                        ids_set == expected_ids and len(ids_set) > 0,
                        approx_equal(inv1.get("subtotal"), v["subtotal"]),
                        approx_equal(inv1.get("tax_amount"), v["tax_amount"]),
                        approx_equal(inv1.get("prepaid_applied"), v["prepaid_applied"]),
                        approx_equal(inv1.get("grand_total"), v["grand_total"]),
                    ]
                    if all(conds):
                        checks["invoice_cust001_values_and_ids"] = True

                # For CUST-002
                inv2 = inv_by_cust.get("CUST-002")
                if inv2 and checks["invoices_fields_valid"]:
                    v = expected_cust["CUST-002"]
                    ids_set = set(inv2.get("billing_period_ids", []))
                    expected_ids = period_ids_by_customer.get("CUST-002", set())
                    conds = [
                        ids_set == expected_ids and len(ids_set) > 0,
                        approx_equal(inv2.get("subtotal"), v["subtotal"]),
                        approx_equal(inv2.get("tax_amount"), v["tax_amount"]),
                        approx_equal(inv2.get("prepaid_applied"), v["prepaid_applied"]),
                        approx_equal(inv2.get("grand_total"), v["grand_total"]),
                    ]
                    if all(conds):
                        checks["invoice_cust002_values_and_ids"] = True

    if checks["summary_file_exists"]:
        summary_text = read_text(summary_path) or ""
        st = summary_text.lower()

        # Must include sections for Acme Bakery and Bright Apartments
        has_customers = ("acme bakery" in st) and ("bright apartments" in st)
        # Must acknowledge 10% tax basis (look for "10%" near "tax" anywhere)
        has_tax_note = ("10%" in st and "tax" in st)
        # Note prepaid credit $30.00 for Acme Bakery
        has_prepaid_note = ("prepaid" in st) and ("$30.00" in summary_text)
        # Minimum charge applied for Bright Apartments’ electricity
        has_min_charge_note = ("minimum charge" in st) and ("bright apartments" in st)
        if has_customers and has_tax_note and has_prepaid_note and has_min_charge_note:
            checks["summary_contains_required_phrases"] = True

        # Totals matching invoice grand_totals
        has_totals = ("$10.92" in summary_text) and ("$22.00" in summary_text)
        if has_totals:
            checks["summary_totals_match"] = True

        # Confirmation note about confirming before bill run or generating invoices
        has_confirm_note = ("confirm" in st) and (("bill" in st) or ("generate invoices" in st) or ("generate invoice" in st))
        if has_confirm_note:
            checks["summary_confirmation_note"] = True

    # Scoring weights
    weights = {
        "billing_periods_file_exists": Decimal("0.02"),
        "invoices_file_exists": Decimal("0.02"),
        "summary_file_exists": Decimal("0.02"),
        "billing_periods_count_3": Decimal("0.06"),
        "billing_periods_fields_valid": Decimal("0.06"),
        "billing_periods_dates_valid": Decimal("0.06"),
        "period_MTR_E_1_values": Decimal("0.08"),
        "period_MTR_E_2_values": Decimal("0.08"),
        "period_MTR_S_1_values": Decimal("0.08"),
        "invoices_count_2": Decimal("0.06"),
        "invoices_fields_valid": Decimal("0.06"),
        "invoice_cust001_values_and_ids": Decimal("0.12"),
        "invoice_cust002_values_and_ids": Decimal("0.12"),
        "summary_contains_required_phrases": Decimal("0.06"),
        "summary_totals_match": Decimal("0.06"),
        "summary_confirmation_note": Decimal("0.06"),
    }
    # Ensure weights sum to 1.0
    total_weight = sum(weights.values())
    # Compute reward
    reward_val = Decimal("0.0")
    for k, w in weights.items():
        if checks.get(k, False):
            reward_val += w
    # Normalize in case of drift
    if total_weight != 0:
        reward = float((reward_val / total_weight).quantize(Decimal("0.0001")))
    else:
        reward = 0.0

    # Ensure range [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print result JSON
    result = {"reward": float(reward)}
    result.update({k: bool(v) for k, v in checks.items()})
    print(json.dumps(result))

if __name__ == "__main__":
    main()