import json
import os
import sys
import re
import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

def read_text(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()

def parse_business_rules_yaml(path):
    # Minimal targeted YAML parser for expected fields
    data = {
        "days_until_due": None,
        "seller": {},
        "vat_rates": {},
        "sells_digital_services": None
    }
    if not os.path.isfile(path):
        return data
    lines = []
    with open(path, 'r', encoding='utf-8') as f:
        for ln in f:
            # strip comments
            s = ln.rstrip('\n')
            if '#' in s:
                s = s.split('#', 1)[0]
            s = s.rstrip()
            if not s.strip():
                continue
            lines.append(s)

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # top-level scalar: key: value
        m = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*:\s*(.+?)\s*$', line)
        if m:
            key = m.group(1)
            val = m.group(2)
            if key in ("seller", "vat_rates"):
                # nested block begins if val empty or val == {}
                if val == "" or val == "{}":
                    i += 1
                else:
                    # unexpected inline, skip
                    i += 1
                # parse nested indented mappings
                while i < n:
                    sub = lines[i]
                    if not sub.startswith(' ') and not sub.startswith('\t'):
                        break
                    sm = re.match(r'^\s+([A-Za-z0-9_\-]+)\s*:\s*(.*?)\s*$', sub)
                    if sm:
                        sk = sm.group(1)
                        sv = sm.group(2)
                        sv = sv.strip()
                        if sv.startswith(("'", '"')) and sv.endswith(("'", '"')) and len(sv) >= 2:
                            sv = sv[1:-1]
                        if key == "seller":
                            data["seller"][sk] = coerce_yaml_scalar(sv)
                        elif key == "vat_rates":
                            # rates can be int or decimal
                            try:
                                rate = Decimal(str(sv))
                            except Exception:
                                try:
                                    rate = Decimal(re.sub(r'[^0-9\.]', '', sv))
                                except Exception:
                                    rate = Decimal(0)
                            data["vat_rates"][sk] = rate
                    i += 1
                continue
            else:
                sval = val.strip()
                if sval.startswith(("'", '"')) and sval.endswith(("'", '"')) and len(sval) >= 2:
                    sval = sval[1:-1]
                cval = coerce_yaml_scalar(sval)
                if key in ("days_until_due", "payment_terms_days"):
                    data["days_until_due"] = int(cval) if isinstance(cval, int) or (isinstance(cval, str) and cval.isdigit()) else data["days_until_due"]
                elif key in ("sells_digital_services", "sellsDigitalServices"):
                    data["sells_digital_services"] = boolify(cval)
                else:
                    # store any other top-level if needed later
                    data[key] = cval
        else:
            # handle section headers without immediate value e.g., "seller:"
            m2 = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*:\s*$', line)
            if m2:
                key = m2.group(1)
                if key in ("seller", "vat_rates"):
                    i += 1
                    while i < n:
                        sub = lines[i]
                        if not sub.startswith(' ') and not sub.startswith('\t'):
                            break
                        sm = re.match(r'^\s+([A-Za-z0-9_\-]+)\s*:\s*(.*?)\s*$', sub)
                        if sm:
                            sk = sm.group(1)
                            sv = sm.group(2)
                            sv = sv.strip()
                            if sv.startswith(("'", '"')) and sv.endswith(("'", '"')) and len(sv) >= 2:
                                sv = sv[1:-1]
                            if key == "seller":
                                data["seller"][sk] = coerce_yaml_scalar(sv)
                            elif key == "vat_rates":
                                try:
                                    rate = Decimal(str(sv))
                                except Exception:
                                    try:
                                        rate = Decimal(re.sub(r'[^0-9\.]', '', sv))
                                    except Exception:
                                        rate = Decimal(0)
                                data["vat_rates"][sk] = rate
                        i += 1
                    continue
        i += 1
    return data

def coerce_yaml_scalar(val):
    v = val.strip()
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if re.fullmatch(r'-?\d+', v):
        try:
            return int(v)
        except Exception:
            pass
    # leave as string
    return v

def boolify(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return False

EU_COUNTRIES = {
    'AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE','IT','LV','LT','LU','MT','NL','PL','PT','RO','SK','SI','ES','SE'
}

def is_eu(code):
    return code.upper() in EU_COUNTRIES

def parse_customers_csv(path):
    customers = []
    if not os.path.isfile(path):
        return customers
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # normalize keys
            norm = { (k.strip().lower() if k is not None else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items() }
            customers.append(norm)
    return customers

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_jsonl(path):
    objects = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                return None
            objects.append(obj)
    return objects

def integer_money(value):
    return isinstance(value, int) and not isinstance(value, bool)

def parse_iso_date(s):
    try:
        # Accept date or datetime ISO-8601
        datetime.fromisoformat(s.replace('Z', '+00:00') if isinstance(s, str) else '')
        return True
    except Exception:
        return False

def compute_expected_tax(net_cents, rate_percent):
    # rate_percent: Decimal
    # tax = round_half_up(net_cents * rate / 100) to integer cents
    n = Decimal(int(net_cents))
    tax = (n * rate_percent) / Decimal(100)
    # Use half up to nearest integer
    return int(tax.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "invoices_exists": False,
        "invoices_line_count_match": False,
        "invoices_json_valid_and_fields": False,
        "invoices_money_integers": False,
        "invoices_days_until_due_correct": False,
        "invoices_seller_fields_match": False,
        "invoices_line_items_valid": False,
        "invoices_totals_correct": False,
        "tax_case_ie_b2c_monthly": False,
        "tax_case_de_b2b_valid_annual": False,
        "tax_case_de_b2c_monthly": False,
        "tax_case_us_b2b_annual": False,
        "revenue_exists": False,
        "revenue_annual_only_and_complete": False,
        "revenue_fields_and_math": False,
        "webhook_exists": False,
        "webhook_signature_and_keywords": False,
        "policies_exists": False,
        "policies_required_content": False,
        "internal_error": False
    }

    try:
        # Load inputs
        business_yaml = os.path.join(input_dir, "business_rules.yaml")
        pricing_json = os.path.join(input_dir, "pricing.json")
        customers_csv = os.path.join(input_dir, "customers.csv")

        rules = parse_business_rules_yaml(business_yaml)
        seller = rules.get("seller", {}) or {}
        vat_rates = rules.get("vat_rates", {}) or {}
        days_until_due_expected = rules.get("days_until_due")
        sells_digital = rules.get("sells_digital_services")
        try:
            pricing = load_json(pricing_json)
        except Exception:
            pricing = {}
        customers = parse_customers_csv(customers_csv)

        # Normalize pricing to dict keyed by plan name
        # Expect structure: { "plans": [ { "name": ..., "amount_cents": ..., "currency": ..., "term_months": ...}, ... ] } or a dict keyed by name
        plans = {}
        if isinstance(pricing, dict) and "plans" in pricing and isinstance(pricing["plans"], list):
            for p in pricing["plans"]:
                if isinstance(p, dict) and "name" in p:
                    plans[str(p["name"])] = p
        elif isinstance(pricing, dict):
            # assume mapping plan_name -> plan_details
            for k, v in pricing.items():
                if isinstance(v, dict):
                    v2 = v.copy()
                    v2["name"] = v2.get("name", k)
                    plans[str(k)] = v2

        # 1) invoices.jsonl checks
        invoices_path = os.path.join(output_dir, "invoices.jsonl")
        invoices = None
        if os.path.isfile(invoices_path):
            checks["invoices_exists"] = True
            invoices = parse_jsonl(invoices_path)

        if invoices is not None:
            # line count
            if len(invoices) == len(customers):
                checks["invoices_line_count_match"] = True

            # validate per-invoice fields and money types
            all_fields_ok = True
            all_money_int_ok = True
            all_days_ok = True
            seller_ok_all = True
            line_item_ok_all = True
            totals_ok_all = True

            # build map by buyer id for scenario checks
            invoices_by_buyer_id = {}
            for inv in invoices:
                # required keys presence
                required_keys = ["invoice_number", "issue_date", "days_until_due", "seller", "buyer", "currency", "line_items", "totals", "vat"]
                if not all(k in inv for k in required_keys):
                    all_fields_ok = False
                    continue
                # types and sub-keys
                if not isinstance(inv["seller"], dict) or not isinstance(inv["buyer"], dict) or not isinstance(inv["line_items"], list) or not isinstance(inv["totals"], dict) or not isinstance(inv["vat"], dict):
                    all_fields_ok = False
                # issue_date ISO
                if not parse_iso_date(inv.get("issue_date", "")):
                    all_fields_ok = False
                # days_until_due equals expected
                if days_until_due_expected is not None and inv.get("days_until_due") == days_until_due_expected:
                    pass
                else:
                    all_days_ok = False
                # seller fields
                for sk in ("name", "country", "vat_id", "address"):
                    if sk not in inv["seller"]:
                        seller_ok_all = False
                # if rules seller provided, verify match on name, country, vat_id
                # Address can vary but must be present
                if seller:
                    for sk in ("name", "country", "vat_id"):
                        if sk in seller and inv["seller"].get(sk) != seller.get(sk):
                            seller_ok_all = False
                # buyer fields
                for bk in ("id", "name", "email", "country", "vat_number", "vat_valid"):
                    if bk not in inv["buyer"]:
                        all_fields_ok = False
                # line_items validation: exactly one item, quantity = 1, unit_price_cents integer
                if not isinstance(inv["line_items"], list) or len(inv["line_items"]) != 1:
                    line_item_ok_all = False
                else:
                    li = inv["line_items"][0]
                    if not (isinstance(li, dict) and li.get("quantity") == 1 and integer_money(li.get("unit_price_cents"))):
                        line_item_ok_all = False
                # money integer checks
                if not (integer_money(inv["totals"].get("net_cents")) and integer_money(inv["totals"].get("tax_cents")) and integer_money(inv["totals"].get("total_cents"))):
                    all_money_int_ok = False
                # totals math
                if integer_money(inv["totals"].get("net_cents")) and integer_money(inv["totals"].get("tax_cents")) and integer_money(inv["totals"].get("total_cents")):
                    if inv["totals"]["net_cents"] + inv["totals"]["tax_cents"] != inv["totals"]["total_cents"]:
                        totals_ok_all = False
                else:
                    totals_ok_all = False

                # collect by buyer id
                b = inv.get("buyer", {})
                bid = str(b.get("id")) if "id" in b else None
                if bid:
                    invoices_by_buyer_id[bid] = inv

            checks["invoices_json_valid_and_fields"] = all_fields_ok
            checks["invoices_money_integers"] = all_money_int_ok
            checks["invoices_days_until_due_correct"] = all_days_ok
            checks["invoices_seller_fields_match"] = seller_ok_all
            checks["invoices_line_items_valid"] = line_item_ok_all
            checks["invoices_totals_correct"] = totals_ok_all

            # Scenario-specific tax checks
            # Build map customers by id
            cust_by_id = {}
            for c in customers:
                cid = str(c.get("id") or c.get("customer_id") or "")
                if cid:
                    cust_by_id[cid] = c

            # Helper to get plan details
            def plan_of(cust):
                plan_name = cust.get("plan") or cust.get("selected_plan") or cust.get("price") or cust.get("plan_name")
                return plans.get(plan_name) if plan_name else None

            # Iterate through customers and verify expected tax per scenario
            for cid, cust in cust_by_id.items():
                inv = invoices_by_buyer_id.get(cid)
                if not inv:
                    continue
                plan = plan_of(cust)
                if not plan:
                    continue
                buyer_country = (cust.get("country") or "").upper()
                seller_country = (seller.get("country") or "").upper()
                vat_valid_str = cust.get("vat_valid") or cust.get("vat_validated") or ""
                vat_valid = boolify(vat_valid_str)
                vat_number = cust.get("vat_number") or cust.get("vat") or cust.get("vat_id") or ""

                # Validate net equals plan amount
                expected_net = plan.get("amount_cents")
                if isinstance(expected_net, (int,)) and inv.get("totals", {}).get("net_cents") != expected_net:
                    continue  # cannot validate tax reliably if net mismatched

                # Validate currency match plan
                if plan.get("currency") and inv.get("currency") != plan.get("currency"):
                    continue

                # Determine expected tax based on rules
                scenario = None
                expected_rate = Decimal(0)
                expected_tax = 0
                expected_type = None
                expected_reverse_charge = False

                if buyer_country == seller_country:
                    scenario = "domestic"
                    expected_type = "domestic"
                    rate = vat_rates.get(seller_country)
                    if rate is None:
                        rate = Decimal(0)
                    expected_rate = rate
                    expected_tax = compute_expected_tax(inv["totals"]["net_cents"], expected_rate)
                elif is_eu(buyer_country) and is_eu(seller_country):
                    if vat_valid and vat_number:
                        scenario = "eu_b2b_valid"
                        expected_type = "reverse"
                        expected_rate = Decimal(0)
                        expected_tax = 0
                        expected_reverse_charge = True
                    else:
                        scenario = "eu_b2c"
                        expected_type = "moss"
                        rate = vat_rates.get(buyer_country)
                        if rate is None:
                            rate = Decimal(0)
                        expected_rate = rate
                        expected_tax = compute_expected_tax(inv["totals"]["net_cents"], expected_rate)
                else:
                    scenario = "export"
                    expected_type = "export"
                    expected_rate = Decimal(0)
                    expected_tax = 0

                vat_field = inv.get("vat", {}) if isinstance(inv.get("vat"), dict) else {}
                tax_ok = integer_money(inv["totals"].get("tax_cents")) and inv["totals"]["tax_cents"] == expected_tax
                type_ok = False
                if isinstance(vat_field.get("type"), str):
                    t = vat_field.get("type").lower()
                    if expected_type == "domestic":
                        type_ok = t == "domestic"
                    elif expected_type == "reverse":
                        type_ok = "reverse" in t
                    elif expected_type == "moss":
                        type_ok = "moss" in t
                    elif expected_type == "export":
                        type_ok = "export" in t
                rate_ok = True  # do not enforce exact rate representation type, but if provided, ensure numeric matches expected
                if "rate_percent" in vat_field:
                    try:
                        rp = Decimal(str(vat_field.get("rate_percent")))
                        rate_ok = (rp == expected_rate)
                    except Exception:
                        rate_ok = False
                rc_ok = True
                if expected_reverse_charge:
                    rc_ok = bool(vat_field.get("reverse_charge", False)) is True

                # Identify plan term
                term_months = plan.get("term_months")
                # Set scenario-specific booleans
                # IE B2C monthly: buyer IE, not valid VAT, monthly (term != 12)
                if buyer_country == "IE" and scenario == "domestic" and isinstance(term_months, int) and term_months != 12:
                    if tax_ok and type_ok and rate_ok:
                        checks["tax_case_ie_b2c_monthly"] = True
                # DE B2B valid VAT annual: buyer DE, EU B2B valid, annual
                if buyer_country == "DE" and scenario == "eu_b2b_valid" and isinstance(term_months, int) and term_months == 12:
                    if tax_ok and type_ok and rate_ok and rc_ok:
                        checks["tax_case_de_b2b_valid_annual"] = True
                # DE B2C monthly: buyer DE, EU B2C, monthly
                if buyer_country == "DE" and scenario == "eu_b2c" and isinstance(term_months, int) and term_months != 12:
                    if tax_ok and type_ok and rate_ok:
                        checks["tax_case_de_b2c_monthly"] = True
                # US B2B annual: buyer US (non-EU), annual
                if buyer_country == "US" and scenario == "export" and isinstance(term_months, int) and term_months == 12:
                    if tax_ok and type_ok and rate_ok:
                        checks["tax_case_us_b2b_annual"] = True

        # 2) revenue_schedule.json checks
        revenue_path = os.path.join(output_dir, "revenue_schedule.json")
        revenue_data = None
        if os.path.isfile(revenue_path):
            checks["revenue_exists"] = True
            try:
                revenue_data = load_json(revenue_path)
            except Exception:
                revenue_data = None

        if isinstance(revenue_data, list):
            # determine annual customers from input
            annual_customers = []
            for c in customers:
                plan_name = c.get("plan") or c.get("selected_plan") or c.get("price") or c.get("plan_name")
                if plan_name and plan_name in plans:
                    if int(plans[plan_name].get("term_months", 0)) == 12:
                        annual_customers.append(str(c.get("id") or c.get("customer_id") or ""))

            # Check array contains entries only for annual customers
            ids_in_revenue = set()
            annual_set = set([i for i in annual_customers if i])
            only_annual = True
            for entry in revenue_data:
                if not isinstance(entry, dict):
                    only_annual = False
                    break
                cid = str(entry.get("customer_id", ""))
                if cid:
                    ids_in_revenue.add(cid)
                # if any id not in annual_set, fail
                if cid and cid not in annual_set:
                    only_annual = False
            # must match exactly
            if ids_in_revenue == annual_set:
                checks["revenue_annual_only_and_complete"] = True if only_annual else False

            # per-entry field checks and math
            fields_math_ok = True
            for entry in revenue_data:
                if not isinstance(entry, dict):
                    fields_math_ok = False
                    break
                required = ["customer_id", "plan", "subscription_term_months", "total_amount_cents", "monthly_recognition_cents"]
                if not all(k in entry for k in required):
                    fields_math_ok = False
                    break
                # integers
                if not (integer_money(entry.get("subscription_term_months")) and integer_money(entry.get("total_amount_cents")) and integer_money(entry.get("monthly_recognition_cents"))):
                    fields_math_ok = False
                    break
                # match pricing
                plan_name = entry.get("plan")
                if plan_name not in plans:
                    fields_math_ok = False
                    break
                expected_term = int(plans[plan_name].get("term_months", 0))
                expected_total = int(plans[plan_name].get("amount_cents", 0))
                if entry["subscription_term_months"] != expected_term or entry["total_amount_cents"] != expected_total:
                    fields_math_ok = False
                    break
                # math exact
                if entry["monthly_recognition_cents"] * entry["subscription_term_months"] != entry["total_amount_cents"]:
                    fields_math_ok = False
                    break
            checks["revenue_fields_and_math"] = fields_math_ok

        # 3) webhook_handler.py checks
        webhook_path = os.path.join(output_dir, "webhook_handler.py")
        if os.path.isfile(webhook_path):
            checks["webhook_exists"] = True
            try:
                content = read_text(webhook_path)
            except Exception:
                content = ""
            sig = re.search(r'def\s+handle_webhook\s*\(\s*raw_body\s*,\s*headers\s*,\s*secret\s*\)\s*:', content) is not None
            has_hmac = ("hmac" in content.lower()) and ("sha256" in content.lower())
            has_header = "Payment-Signature" in content
            has_idempot = "idempot" in content.lower()
            has_event_id = ("event" in content.lower() and "id" in content.lower())
            has_types = ("invoice.paid" in content) and ("customer.subscription.updated" in content)
            has_states = all(s in content for s in ["'trialing'", "'active'", "'past_due'", "'canceled'", "'unpaid'"])
            has_cpe = "current_period_end" in content
            mentions_out_of_order = ("out-of-order" in content.lower()) or ("out of order" in content.lower())
            checks["webhook_signature_and_keywords"] = all([sig, has_hmac, has_header, has_idempot, has_event_id, has_types, has_states, has_cpe, mentions_out_of_order])

        # 4) subscription_policies.md checks
        policies_path = os.path.join(output_dir, "subscription_policies.md")
        if os.path.isfile(policies_path):
            checks["policies_exists"] = True
            try:
                pol = read_text(policies_path)
            except Exception:
                pol = ""
            has_cancel_at_period_end = "cancel_at_period_end" in pol
            mentions_immediate = ("immediate" in pol.lower()) or ("delete" in pol.lower())
            mentions_access = "access" in pol.lower()
            has_proration_options = all(x in pol for x in ["create_prorations", "none", "always_invoice"])
            mentions_cents = ("cents" in pol.lower()) and ("integer" in pol.lower() or "smallest currency units" in pol.lower())
            mentions_cpe = "current_period_end" in pol
            has_states_listed = all(s in pol for s in ["trialing", "active", "past_due", "canceled", "unpaid"])
            checks["policies_required_content"] = all([has_cancel_at_period_end, mentions_immediate, mentions_access, has_proration_options, mentions_cents, mentions_cpe, has_states_listed])

    except Exception:
        checks["internal_error"] = True

    # Compute reward as average of True checks over all non-internal-error checks
    score_checks = [k for k in checks.keys() if k != "internal_error"]
    if any(checks.values()):
        # baseline: if no output files at all, ensure 0
        # If none of the primary artifacts exist, reward = 0
        primary_exist = checks["invoices_exists"] or checks["revenue_exists"] or checks["webhook_exists"] or checks["policies_exists"]
        if not primary_exist:
            reward = 0.0
        else:
            total = len(score_checks)
            passed = sum(1 for k in score_checks if checks[k])
            reward = passed / float(total) if total > 0 else 0.0
    else:
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()