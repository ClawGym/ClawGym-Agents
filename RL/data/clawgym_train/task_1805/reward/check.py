import os
import sys
import json
import csv
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

def d2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def to_decimal(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        s = s.replace("€", "").replace(",", "").strip()
        if s == "":
            return None
        try:
            return Decimal(s)
        except Exception:
            return None
    return None

def rate_to_decimal(rate):
    # Accept 0.21 or 21 or "21%" or "0.21"
    if rate is None:
        return None
    if isinstance(rate, str):
        s = rate.strip().replace("%", "").strip()
        if s == "":
            return None
        try:
            val = Decimal(s)
        except Exception:
            return None
    else:
        val = Decimal(str(rate))
    # Interpret as percentage if > 1
    if val > 1:
        val = (val / Decimal("100"))
    return val

def rate_to_percent_str(rate_decimal):
    # 0.21 -> "21%", 0.075 -> "7.5%"
    if rate_decimal is None:
        return ""
    pct = (rate_decimal * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # remove trailing zeros
    s = f"{pct.normalize()}"
    # normalize() may produce scientific; guard that
    if "E" in s or "e" in s:
        s = f"{pct:.2f}"
    # strip trailing .00 or .0
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return f"{s}%"

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv(path):
    try:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
        return rows
    except Exception:
        return None

def get_config_fields(cfg):
    # issuer info
    issuer = {}
    issuer_obj = {}
    for key in ["issuer", "business", "company"]:
        if isinstance(cfg.get(key), dict):
            issuer_obj = cfg[key]
            break
    issuer["name"] = issuer_obj.get("name") or cfg.get("business_name") or cfg.get("name")
    issuer["tax_id"] = issuer_obj.get("tax_id") or issuer_obj.get("nif") or cfg.get("issuer_tax_id") or cfg.get("tax_id") or cfg.get("nif")
    iban = issuer_obj.get("iban") or cfg.get("iban")
    if not iban and isinstance(cfg.get("bank"), dict):
        iban = cfg["bank"].get("iban")
    issuer["iban"] = iban

    # tax rates
    vat = None
    irpf = None
    # try nested tax object
    tax_obj = cfg.get("tax") if isinstance(cfg.get("tax"), dict) else {}
    vat = tax_obj.get("default_vat_rate") or cfg.get("default_vat_rate") or cfg.get("vat_rate") or cfg.get("vat") or tax_obj.get("vat")
    irpf = tax_obj.get("retention_rate") or cfg.get("retention_rate") or cfg.get("irpf") or tax_obj.get("irpf_rate") or tax_obj.get("irpf")

    vat_rate = rate_to_decimal(vat)
    irpf_rate = rate_to_decimal(irpf)

    # series
    series = {}
    series_prefix = None
    counter_width = None

    ser = cfg.get("series") if isinstance(cfg.get("series"), dict) else {}
    for key in ["series_prefix", "prefix", "format", "series_format", "template"]:
        if isinstance(ser.get(key), str):
            series_prefix = ser.get(key)
            break
    if not series_prefix:
        for key in ["series_prefix", "series_format", "format", "prefix", "template"]:
            if isinstance(cfg.get(key), str):
                series_prefix = cfg.get(key)
                break
    for key in ["counter_width", "padding", "pad_width", "width"]:
        cw = ser.get(key) if key in ser else cfg.get(key)
        if isinstance(cw, int):
            counter_width = cw
            break
        if isinstance(cw, str) and cw.isdigit():
            counter_width = int(cw)
            break

    # default if still missing
    if counter_width is None:
        counter_width = 3

    series["prefix_template"] = series_prefix
    series["counter_width"] = counter_width

    return issuer, vat_rate, irpf_rate, series

def render_series_prefix(prefix_template, year):
    if not prefix_template:
        # default
        return f"F-{year}-"
    # Replace common placeholders
    s = prefix_template
    s = s.replace("{year}", str(year))
    s = s.replace("YYYY", str(year))
    s = s.replace("{YYYY}", str(year))
    # If template already contains a specific year, keep it
    return s

def series_key_from_prefix(prefix):
    # Typically "F-2026-006" uses counter stored under "F-2026"
    # Remove trailing hyphen if present
    if prefix.endswith("-"):
        return prefix[:-1]
    return prefix

def find_client(clients_data, target):
    # target may be id or name
    if not clients_data:
        return None
    arr = []
    if isinstance(clients_data, dict) and isinstance(clients_data.get("clients"), list):
        arr = clients_data["clients"]
    elif isinstance(clients_data, list):
        arr = clients_data
    t = (target or "").strip().lower()
    best = None
    # exact id
    for c in arr:
        if str(c.get("id", "")).strip().lower() == t:
            return c
    # exact name
    for c in arr:
        if str(c.get("name", "")).strip().lower() == t:
            return c
    # partial match by name
    for c in arr:
        if t and t in str(c.get("name", "")).strip().lower():
            best = c
            break
    return best

def load_series_counter(series_input_path, key):
    data = load_json(series_input_path)
    if data is None:
        return None, None
    candidates = []
    if key in data and isinstance(data.get(key), int):
        return data.get(key), data
    if isinstance(data.get("series"), dict):
        series_map = data["series"]
        if key in series_map and isinstance(series_map.get(key), int):
            return series_map.get(key), data
    # Try keys that start with key
    for k, v in (data.get("series", data) or {}).items():
        if isinstance(v, int) and str(k) == key:
            return v, data
    return None, data

def compute_expected_from_inputs(input_dir):
    # Load all inputs
    cfg = load_json(os.path.join(input_dir, "config.json"))
    clients = load_json(os.path.join(input_dir, "clients", "index.json"))
    svc_rows = load_csv(os.path.join(input_dir, "services.csv"))
    inv_req = load_json(os.path.join(input_dir, "invoice_request.json"))
    series_in_path = os.path.join(input_dir, "series.json")

    if not all([cfg, clients, svc_rows, inv_req]):
        return None

    issuer, vat_rate, irpf_rate, series_cfg = get_config_fields(cfg)
    invoice_date_str = inv_req.get("invoice_date")
    try:
        invoice_date = datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    year = invoice_date.year
    prefix = render_series_prefix(series_cfg.get("prefix_template"), year)
    base_series_key = series_key_from_prefix(prefix)

    current_counter, series_in_data = load_series_counter(series_in_path, base_series_key)
    if current_counter is None:
        # If not found, assume 0 to start
        current_counter = 0
    next_counter = current_counter + 1
    width = series_cfg.get("counter_width") or 3
    invoice_number = f"{prefix}{str(next_counter).zfill(width)}"

    # client
    target_client = inv_req.get("client") or inv_req.get("client_id") or inv_req.get("client_name")
    client = find_client(clients, target_client)

    # payment terms
    client_terms = None
    if client and isinstance(client.get("payment_terms"), int):
        client_terms = client.get("payment_terms")
    if client_terms is None:
        # config default
        client_terms = cfg.get("default_payment_terms")
        if isinstance(cfg.get("payments"), dict) and client_terms is None:
            client_terms = cfg["payments"].get("default_terms")
        if client_terms is None:
            client_terms = 30
    try:
        client_terms = int(client_terms)
    except Exception:
        client_terms = 30
    due_date = invoice_date + timedelta(days=client_terms)
    due_date_str = due_date.isoformat()

    # subtotal
    subtotal = Decimal("0")
    per_line_rates = []
    overrides_present = False
    for r in svc_rows:
        qty = to_decimal(r.get("quantity")) or Decimal("0")
        unit = to_decimal(r.get("unit_price_eur") or r.get("unit_price") or r.get("price")) or Decimal("0")
        line_sub = qty * unit
        subtotal += line_sub
        # tax rate override on line?
        line_rate_raw = r.get("tax_rate")
        line_rate = rate_to_decimal(line_rate_raw) if line_rate_raw is not None and str(line_rate_raw).strip() != "" else vat_rate
        per_line_rates.append((line_sub, line_rate))
        if line_rate is not None and vat_rate is not None and line_rate != vat_rate:
            overrides_present = True
    subtotal_q = d2(subtotal)

    # tax amount
    if overrides_present:
        tax_total = Decimal("0")
        for base, lr in per_line_rates:
            if lr is None:
                lr = Decimal("0")
            tax_total += (base * lr)
        tax_amount_q = d2(tax_total)
    else:
        vr = vat_rate or Decimal("0")
        tax_amount_q = d2(subtotal * vr)

    # retention
    rr = irpf_rate or Decimal("0")
    retention_amount_q = d2(subtotal * rr)

    total_q = d2(subtotal_q + tax_amount_q)
    amount_due_q = d2(total_q - retention_amount_q)

    # issuer/client IDs expected
    expected_issuer_tax_id = (issuer.get("tax_id") or "").strip() if issuer else ""
    expected_issuer_name = (issuer.get("name") or "").strip() if issuer else ""
    expected_iban = (issuer.get("iban") or "").strip().replace(" ", "").upper()
    expected_client_tax_id = (client.get("tax_id") or client.get("nif") or "").strip() if client else ""
    expected_client_name = (client.get("name") or "").strip() if client else ""

    return {
        "issuer": issuer,
        "vat_rate": vat_rate,
        "irpf_rate": irpf_rate,
        "series_prefix": prefix,
        "series_key": base_series_key,
        "counter_width": width,
        "current_counter": current_counter,
        "next_counter": next_counter,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date_str,
        "due_date": due_date_str,
        "subtotal": subtotal_q,
        "tax_amount": tax_amount_q,
        "retention_amount": retention_amount_q,
        "total": total_q,
        "amount_due": amount_due_q,
        "overrides_present": overrides_present,
        "expected_issuer_tax_id": expected_issuer_tax_id,
        "expected_issuer_name": expected_issuer_name,
        "expected_iban": expected_iban,
        "expected_client_tax_id": expected_client_tax_id,
        "expected_client_name": expected_client_name,
        "clients": clients,
        "cfg": cfg
    }

def decimal_equal(a, b):
    if a is None or b is None:
        return False
    try:
        da = d2(Decimal(str(a)))
        db = d2(Decimal(str(b)))
        return da == db
    except Exception:
        return False

def extract_number(val):
    try:
        return Decimal(str(val))
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # invoice.json checks
        "invoice_json_exists": False,
        "invoice_json_valid": False,
        "invoice_number_correct": False,
        "subtotal_correct": False,
        "vat_rate_matches_default_when_no_overrides": False,
        "tax_amount_correct": False,
        "retention_rate_correct": False,
        "retention_amount_correct": False,
        "total_correct": False,
        "amount_due_correct": False,
        "due_date_correct": False,
        "issuer_tax_id_matches_input": False,
        "client_tax_id_matches_input": False,
        # HTML checks
        "html_exists": False,
        "html_contains_invoice_number": False,
        "html_contains_issuer_and_client_names": False,
        "html_contains_vat_label_with_percentage": False,
        "html_contains_irpf_label_with_negative": False,
        "html_contains_totals_values": False,
        "html_contains_iban": False,
        "html_contains_required_note": False,
        # Markdown checks
        "md_exists": False,
        "md_starts_with_invoice_number_line": False,
        "md_contains_due_date": False,
        "md_contains_totals_consistent": False,
        # series state checks
        "series_state_exists": False,
        "series_counter_incremented": False,
        "series_matches_invoice_number": False,
    }

    expected = compute_expected_from_inputs(input_dir)
    # If we cannot compute expected due to missing inputs, we still do not award any points.
    # Proceed to check outputs conditionally.
    invoice_json_path = os.path.join(output_dir, "invoice.json")
    invoice = None
    if os.path.isfile(invoice_json_path):
        checks["invoice_json_exists"] = True
        try:
            with open(invoice_json_path, "r", encoding="utf-8") as f:
                invoice = json.load(f)
            checks["invoice_json_valid"] = isinstance(invoice, dict)
        except Exception:
            checks["invoice_json_valid"] = False

    if expected and checks["invoice_json_valid"]:
        # invoice number correctness
        inv_num = invoice.get("invoice_number")
        if isinstance(inv_num, str) and inv_num == expected["invoice_number"]:
            checks["invoice_number_correct"] = True

        # subtotal
        inv_subtotal = extract_number(invoice.get("subtotal"))
        if inv_subtotal is not None and d2(inv_subtotal) == expected["subtotal"]:
            checks["subtotal_correct"] = True

        # vat rate
        inv_vat_rate = rate_to_decimal(invoice.get("tax_rate"))
        if not expected["overrides_present"]:
            if inv_vat_rate is not None and expected["vat_rate"] is not None and d2(inv_vat_rate) == d2(expected["vat_rate"]):
                checks["vat_rate_matches_default_when_no_overrides"] = True
        # tax amount
        inv_tax_amount = extract_number(invoice.get("tax_amount"))
        if inv_tax_amount is not None and d2(inv_tax_amount) == expected["tax_amount"]:
            checks["tax_amount_correct"] = True

        # retention rate
        inv_ret_rate = rate_to_decimal(invoice.get("retention_rate"))
        if inv_ret_rate is not None and expected["irpf_rate"] is not None and d2(inv_ret_rate) == d2(expected["irpf_rate"]):
            checks["retention_rate_correct"] = True

        # retention amount
        inv_ret_amount = extract_number(invoice.get("retention_amount"))
        if inv_ret_amount is not None and d2(inv_ret_amount) == expected["retention_amount"]:
            checks["retention_amount_correct"] = True

        # total
        inv_total = extract_number(invoice.get("total"))
        if inv_total is not None and d2(inv_total) == expected["total"]:
            checks["total_correct"] = True

        # amount due
        inv_due = extract_number(invoice.get("amount_due") or invoice.get("amount_to_receive"))
        if inv_due is not None and d2(inv_due) == expected["amount_due"]:
            checks["amount_due_correct"] = True

        # due date
        inv_due_date = invoice.get("due_date")
        if isinstance(inv_due_date, str) and inv_due_date == expected["due_date"]:
            checks["due_date_correct"] = True

        # issuer/client tax ids
        inv_issuer_tid = ""
        inv_client_tid = ""
        try:
            inv_issuer_tid = (invoice.get("issuer", {}) or {}).get("tax_id", "") or (invoice.get("issuer_tax_id") or "")
            inv_client_tid = (invoice.get("client", {}) or {}).get("tax_id", "") or (invoice.get("client_tax_id") or "")
        except Exception:
            pass
        if expected["expected_issuer_tax_id"] and isinstance(inv_issuer_tid, str) and inv_issuer_tid.strip() == expected["expected_issuer_tax_id"]:
            checks["issuer_tax_id_matches_input"] = True
        if expected["expected_client_tax_id"] and isinstance(inv_client_tid, str) and inv_client_tid.strip() == expected["expected_client_tax_id"]:
            checks["client_tax_id_matches_input"] = True

        # HTML checks
        # Year directory determined from invoice date year (expected year)
        year_dir = str(datetime.strptime(expected["invoice_date"], "%Y-%m-%d").year)
        html_path = os.path.join(output_dir, "sent", year_dir, f"{expected['invoice_number']}.html")
        if os.path.isfile(html_path):
            checks["html_exists"] = True
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
            except Exception:
                html = ""
            # invoice number
            if expected["invoice_number"] in html:
                checks["html_contains_invoice_number"] = True
            # issuer and client names
            issuer_name = expected["expected_issuer_name"]
            client_name = expected["expected_client_name"]
            if issuer_name and client_name and (issuer_name in html) and (client_name in html):
                checks["html_contains_issuer_and_client_names"] = True
            # VAT/IVA label with percentage
            vat_pct = rate_to_percent_str(expected["vat_rate"])
            pattern_vat = re.compile(rf"(VAT|IVA)\s*\(\s*{re.escape(vat_pct)}\s*\)", re.IGNORECASE)
            if pattern_vat.search(html):
                checks["html_contains_vat_label_with_percentage"] = True
            # IRPF with negative percentage
            irpf_pct = rate_to_percent_str(expected["irpf_rate"])
            pattern_irpf = re.compile(rf"IRPF\s*\(\s*-\s*{re.escape(irpf_pct)}\s*\)", re.IGNORECASE)
            if pattern_irpf.search(html):
                checks["html_contains_irpf_label_with_negative"] = True
            # totals presence: subtotal, tax_amount, total, amount_due
            s_sub = f"{expected['subtotal']:.2f}"
            s_tax = f"{expected['tax_amount']:.2f}"
            s_total = f"{expected['total']:.2f}"
            s_due = f"{expected['amount_due']:.2f}"
            if (s_sub in html) and (s_tax in html) and (s_total in html) and (s_due in html):
                checks["html_contains_totals_values"] = True
            # IBAN
            iban_expected = expected["expected_iban"]
            if iban_expected:
                html_compact = re.sub(r"\s+", "", html).upper()
                if iban_expected in html_compact:
                    checks["html_contains_iban"] = True
            # required note
            note = "This invoice includes IRPF retention as per Spanish freelancer rules."
            if note in html:
                checks["html_contains_required_note"] = True

        # Markdown checks
        md_path = os.path.join(output_dir, "drafts", "acme", "versions", "v001.md")
        if os.path.isfile(md_path):
            checks["md_exists"] = True
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    md = f.read()
            except Exception:
                md = ""
            first_line = md.splitlines()[0] if md.splitlines() else ""
            if first_line.strip() == f"INVOICE {expected['invoice_number']}":
                checks["md_starts_with_invoice_number_line"] = True
            if expected["due_date"] in md:
                checks["md_contains_due_date"] = True
            # totals consistent
            s_sub = f"{expected['subtotal']:.2f}"
            s_tax = f"{expected['tax_amount']:.2f}"
            s_total = f"{expected['total']:.2f}"
            s_due = f"{expected['amount_due']:.2f}"
            md_has = all(s in md for s in [s_sub, s_tax, s_total, s_due])
            if md_has:
                checks["md_contains_totals_consistent"] = True

        # series state
        series_out_path = os.path.join(output_dir, "state", "series.json")
        if os.path.isfile(series_out_path):
            checks["series_state_exists"] = True
            series_out = load_json(series_out_path) or {}
            out_counter = None
            # find counter at series_key
            if expected["series_key"] in series_out and isinstance(series_out.get(expected["series_key"]), int):
                out_counter = series_out.get(expected["series_key"])
            elif isinstance(series_out.get("series"), dict):
                out_counter = series_out["series"].get(expected["series_key"])
            # incremented
            if isinstance(out_counter, int) and out_counter == expected["current_counter"] + 1:
                checks["series_counter_incremented"] = True
            # matches invoice number
            # extract counter from invoice_number
            m = re.search(r"(\d+)$", expected["invoice_number"])
            inv_counter_num = int(m.group(1)) if m else None
            if isinstance(out_counter, int) and inv_counter_num is not None and out_counter == inv_counter_num:
                checks["series_matches_invoice_number"] = True

    # Compute reward
    # Only artifact-dependent checks are included; if no outputs exist, reward should be 0.0.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if any(checks.values()):
        reward = passed / total_checks
    else:
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()