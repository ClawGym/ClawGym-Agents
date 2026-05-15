import json
import os
import re
import sys
import csv
from datetime import datetime

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_currency_to_float(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    # strip $ and other non-numeric except dot and minus
    m = re.findall(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    if not m:
        return None
    try:
        return float(m[0])
    except Exception:
        return None

def normalize_option(opt):
    if not opt:
        return None
    o = str(opt).strip().lower()
    if o in ["scheduled", "schedule", "sched"]:
        return "scheduled"
    if o in ["on_demand", "on-demand", "ondemand", "now", "asap"]:
        return "on_demand"
    return o

def normalize_app(name):
    if not name:
        return None
    return str(name).strip().lower()

def try_get(obj, keys, default=None):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            return obj[k]
    return default

def extract_price_from_obj(d):
    # attempt to extract a base estimate price from an object
    candidates = ["est_price", "estimate", "price", "base_estimate", "base", "amount", "fare", "est_total", "estimated_price"]
    for k in candidates:
        v = try_get(d, [k])
        val = parse_currency_to_float(v)
        if val is not None:
            return val
    return None

def extract_eta_from_obj(d):
    # attempt to extract eta minutes
    for k in ["eta_minutes", "eta", "eta_min", "minutes", "wait_minutes"]:
        v = try_get(d, [k])
        val = parse_currency_to_float(v)
        if val is not None:
            return int(round(val))
    return None

def extract_surge_from_obj(d):
    v = try_get(d, ["surge_multiplier", "surge", "multiplier"])
    if v is None:
        return 1.0
    mv = parse_currency_to_float(v)
    return mv if mv is not None else 1.0

def parse_price_quotes(quotes_json):
    """
    Return list of dicts: {app, option, base_price, surge_multiplier, eta_minutes}
    """
    result = []
    data = quotes_json
    if data is None:
        return result

    def add_record(app, option, block):
        app_n = normalize_app(app)
        opt_n = normalize_option(option)
        price = extract_price_from_obj(block)
        surge = extract_surge_from_obj(block)
        eta = extract_eta_from_obj(block)
        if app_n and opt_n and price is not None:
            result.append({
                "app": app_n,
                "option": opt_n,
                "base_price": price,
                "surge_multiplier": surge,
                "eta_minutes": eta
            })

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            app = try_get(item, ["app", "platform", "service"])
            opt = normalize_option(try_get(item, ["option", "type", "mode"]))
            if app and opt:
                add_record(app, opt, item)
    elif isinstance(data, dict):
        # If nested by app then option
        # Try top-level known container keys
        container = None
        for k in ["quotes", "estimates", "data"]:
            if k in data and isinstance(data[k], (list, dict)):
                container = data[k]
                break
        if container is None:
            container = data

        if isinstance(container, list):
            for item in container:
                if isinstance(item, dict):
                    app = try_get(item, ["app", "platform", "service"])
                    opt = normalize_option(try_get(item, ["option", "type", "mode"]))
                    if app and opt:
                        add_record(app, opt, item)
        elif isinstance(container, dict):
            for app, block in container.items():
                # block may be dict with scheduled/on_demand keys or list of options
                if isinstance(block, dict):
                    # iterate scheduled/on_demand if present
                    found_any = False
                    for opt_key, opt_val in block.items():
                        opt_norm = normalize_option(opt_key)
                        if opt_norm in ("scheduled", "on_demand"):
                            found_any = True
                            if isinstance(opt_val, dict):
                                add_record(app, opt_norm, opt_val)
                            elif isinstance(opt_val, (int, float)):
                                add_record(app, opt_norm, {"estimate": opt_val})
                    # if not found_any but block looks like an item with app/option inside
                    if not found_any:
                        app_field = try_get(block, ["app"])
                        option_field = normalize_option(try_get(block, ["option", "type"]))
                        if app_field and option_field:
                            add_record(app_field, option_field, block)
                elif isinstance(block, list):
                    for item in block:
                        if isinstance(item, dict):
                            app_field = try_get(item, ["app"]) or app
                            option_field = normalize_option(try_get(item, ["option", "type"]))
                            if app_field and option_field:
                                add_record(app_field, option_field, item)
    # dedupe by (app, option) keeping first
    seen = set()
    deduped = []
    for r in result:
        key = (r["app"], r["option"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped

def parse_promos(promos_json):
    """
    Build mapping: app_name_lower -> list of promo dicts with:
      {"id": str, "kind": "percent"|"amount"|"credit", "percent": float or None, "amount": float or None, "max_discount": float or None, "applies_to": set({"scheduled","on_demand"}) or None, "min_fare": float or None}
    """
    promos_by_app = {}
    data = promos_json
    if data is None:
        return promos_by_app

    def add_promo(app, promo):
        app_n = normalize_app(app)
        if not app_n:
            return
        promos_by_app.setdefault(app_n, []).append(promo)

    def normalize_promo_fields(item):
        # Identify id
        pid = None
        for key in ["code", "name", "id", "label"]:
            if key in item and isinstance(item[key], str) and item[key].strip():
                pid = item[key].strip()
                break
        # Identify type and values
        kind = None
        percent = None
        amount = None
        max_discount = None
        min_fare = None
        applies_to = None

        # detect kind/values
        # amount
        for k in ["amount", "value", "discount_amount", "credit", "balance"]:
            if k in item and isinstance(item[k], (int, float, str)):
                val = parse_currency_to_float(item[k])
                if val is not None:
                    amount = val
        # percent
        for k in ["percent", "percentage", "percent_off", "discount_percent"]:
            if k in item and isinstance(item[k], (int, float, str)):
                val = parse_currency_to_float(item[k])
                if val is not None:
                    percent = val
        # explicit type
        t = try_get(item, ["type", "kind"])
        if isinstance(t, str):
            tl = t.lower()
            if "percent" in tl:
                kind = "percent"
            elif "credit" in tl:
                kind = "credit"
            elif "amount" in tl or "fixed" in tl or "dollar" in tl:
                kind = "amount"
        # infer if missing
        if kind is None:
            if percent is not None:
                kind = "percent"
            elif amount is not None:
                # could be amount or credit; assume amount
                kind = "amount"
        # max_discount
        for k in ["max_discount", "cap", "maximum", "max_off"]:
            if k in item:
                md = parse_currency_to_float(item[k])
                if md is not None:
                    max_discount = md
        # min_fare
        for k in ["min_fare", "min_purchase", "min_total"]:
            if k in item:
                mf = parse_currency_to_float(item[k])
                if mf is not None:
                    min_fare = mf
        # applies_to/options
        opts = None
        for k in ["applies_to", "options", "valid_for"]:
            if k in item:
                v = item[k]
                if isinstance(v, str):
                    opts = {normalize_option(v)}
                elif isinstance(v, list):
                    opts = {normalize_option(x) for x in v if normalize_option(x)}
        applies_to = None
        if opts:
            # filter to only recognized
            opts2 = set()
            for x in opts:
                if x in ("scheduled", "on_demand"):
                    opts2.add(x)
            applies_to = opts2 if opts2 else None

        if pid is None:
            # fallback id
            if kind == "percent" and percent is not None:
                pid = f"{int(percent)}PCT"
            elif kind in ("amount", "credit") and amount is not None:
                pid = f"{kind.upper()}-{amount}"
            else:
                pid = "PROMO"
        return {
            "id": pid,
            "kind": kind,
            "percent": percent,
            "amount": amount,
            "max_discount": max_discount,
            "applies_to": applies_to,
            "min_fare": min_fare
        }

    # Support multiple shapes
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                app = try_get(item, ["app", "platform", "service"])
                if app:
                    add_promo(app, normalize_promo_fields(item))
    elif isinstance(data, dict):
        # try keys
        if "apps" in data and isinstance(data["apps"], dict):
            for app, promos in data["apps"].items():
                if isinstance(promos, list):
                    for p in promos:
                        if isinstance(p, dict):
                            add_promo(app, normalize_promo_fields(p))
                elif isinstance(promos, dict):
                    # promos may have "codes" and "credits"
                    for key in ["codes", "promos", "credits", "offers"]:
                        if key in promos and isinstance(promos[key], list):
                            for p in promos[key]:
                                if isinstance(p, dict):
                                    add_promo(app, normalize_promo_fields(p))
        else:
            # dict keyed by app or generic
            for app, promos in data.items():
                if isinstance(promos, list):
                    for p in promos:
                        if isinstance(p, dict):
                            add_promo(app, normalize_promo_fields(p))
                elif isinstance(promos, dict):
                    # same as above
                    for key in ["codes", "promos", "credits", "offers", "items"]:
                        if key in promos and isinstance(promos[key], list):
                            for p in promos[key]:
                                if isinstance(p, dict):
                                    add_promo(app, normalize_promo_fields(p))
    return promos_by_app

def compute_best_discount(app, option, amount_before_promo, promos_by_app):
    app_promos = promos_by_app.get(app, [])
    best = {"discount": 0.0, "id": "none"}
    for p in app_promos:
        applies = True
        if p.get("applies_to"):
            applies = option in p["applies_to"]
        if not applies:
            continue
        if p.get("min_fare") is not None and amount_before_promo < p["min_fare"]:
            continue
        discount = 0.0
        if p.get("kind") == "percent" and p.get("percent") is not None:
            discount = amount_before_promo * (float(p["percent"]) / 100.0)
            if p.get("max_discount") is not None:
                discount = min(discount, float(p["max_discount"]))
        elif p.get("kind") in ("amount", "credit") and p.get("amount") is not None:
            discount = float(p["amount"])
        if discount > best["discount"]:
            best = {"discount": discount, "id": p.get("id", "promo")}
    # Cap to non-negative final
    final = max(amount_before_promo - best["discount"], 0.0)
    return best["discount"], best["id"], final

def load_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None

def parse_csv_with_header(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [r for r in reader]
            return header, rows
    except Exception:
        return None, None

def parse_trips_md(md_text):
    """
    Parse trips.md to identify the last month section '## YYYY-MM' and extract table rows within that section.
    Returns: month (YYYY-MM), rows (list of dict by headers), headers list
    """
    if not md_text:
        return None, [], []
    lines = md_text.splitlines()
    # Find all month headers
    month_indices = []
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(\d{4}-\d{2})\s*$", line.strip())
        if m:
            month_indices.append((i, m.group(1)))
    if not month_indices:
        return None, [], []
    start_idx, month = month_indices[-1]
    # Find end idx
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if re.match(r"^##\s+\d{4}-\d{2}\s*$", lines[i].strip()):
            end_idx = i
            break
    section = lines[start_idx:end_idx]
    # Extract table: find header row starting with |
    header_idx = None
    for i, line in enumerate(section):
        if line.strip().startswith("|") and "Date" in line and "App" in line:
            header_idx = i
            break
    if header_idx is None:
        return month, [], []
    # Next line is separator (---), skip
    data_start = header_idx + 2 if header_idx + 1 < len(section) else header_idx + 1
    hdr_cells = [c.strip() for c in section[header_idx].strip().strip("|").split("|")]
    rows = []
    for i in range(data_start, len(section)):
        line = section[i].strip()
        if not line.startswith("|"):
            # stop at non-table content (e.g., Monthly Summary)
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(hdr_cells):
            # likely end of table
            break
        row = {hdr_cells[j].strip(): cells[j].strip() for j in range(len(hdr_cells))}
        rows.append(row)
    return month, rows, hdr_cells

def recompute_monthly_totals(md_text):
    month, rows, headers = parse_trips_md(md_text)
    if not month:
        return None, None, None
    # column names normalization
    cost_key = None
    cat_key = None
    promo_key = None
    for h in headers:
        hl = h.strip().lower()
        if "cost" in hl:
            cost_key = h
        if "category" in hl:
            cat_key = h
        if "promo" in hl:
            promo_key = h
    total = 0.0
    by_cat = {}
    promo_savings = 0.0
    for r in rows:
        c = parse_currency_to_float(r.get(cost_key, "")) if cost_key else None
        if c is not None:
            total += c
        cat = (r.get(cat_key, "") if cat_key else "").strip() or "uncategorized"
        by_cat[cat] = by_cat.get(cat, 0.0) + (c if c is not None else 0.0)
        # parse promo savings from promo cell if any amounts indicated
        if promo_key:
            pv = r.get(promo_key, "")
            if pv:
                # look for $ amounts; treat negatives or mentions of saved/off as savings
                for m in re.finditer(r"(-)?\$\s*([0-9]+(?:\.[0-9]+)?)", pv.replace(",", "")):
                    sign = m.group(1)
                    val = float(m.group(2))
                    lower = pv.lower()
                    if sign == "-" or "save" in lower or "saved" in lower or "off" in lower or "credit" in lower:
                        promo_savings += val
    # round to cents
    total = round(total + 1e-9, 2)
    for k in list(by_cat.keys()):
        by_cat[k] = round(by_cat[k] + 1e-9, 2)
    promo_savings = round(promo_savings + 1e-9, 2)
    return month, total, by_cat, promo_savings

def parse_recommended_line(line):
    # Format: "N. <app> <option> - $<price> - ETA: <minutes> min"
    m = re.match(r"^\s*(\d+)\.\s+(.+?)\s+(scheduled|on-demand|on_demand|ondemand|now|asap)\s+-\s+\$\s*([0-9]+(?:\.[0-9]+)?)\s+-\s+ETA:\s*([0-9]+)\s*min\s*$", line.strip(), re.IGNORECASE)
    if not m:
        return None
    idx = int(m.group(1))
    app = m.group(2).strip()
    option = normalize_option(m.group(3))
    price = float(m.group(4))
    eta = int(m.group(5))
    return {"index": idx, "app": app, "option": option, "price": price, "eta": eta}

def float_equal(a, b, tol=0.01):
    return abs(float(a) - float(b)) <= tol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_ride_comparison_csv": False,
        "ride_comparison_header_ok": False,
        "ride_comparison_has_required_apps": False,
        "ride_comparison_has_options_for_inputs": False,
        "ride_comparison_promo_prices_valid": False,
        "booking_plan_exists": False,
        "booking_plan_contains_keywords_and_time": False,
        "monthly_summary_exists_and_valid_json": False,
        "monthly_summary_totals_match": False,
        "recommended_order_exists_and_format": False,
        "recommended_order_sorted": False,
        "recommended_vs_csv_consistent": False,
        "learnings_exists_and_format": False,
        "discussion_transcript_valid": False
    }

    # Paths
    ride_csv_path = os.path.join(output_dir, "ride_comparison.csv")
    booking_md_path = os.path.join(output_dir, "booking_plan.md")
    monthly_json_path = os.path.join(output_dir, "monthly_expense_summary.json")
    recommended_txt_path = os.path.join(output_dir, "recommended_order.txt")
    learnings_md_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    discussion_json_path = os.path.join(output_dir, "discussion", "transcript.json")

    # Load inputs for cross-checking
    price_quotes_json = read_json(os.path.join(input_dir, "price_quotes.json"))
    promos_json = read_json(os.path.join(input_dir, "promos.json"))
    trips_md_text = read_text(os.path.join(input_dir, "trips.md"))

    # 1) ride_comparison.csv checks
    header, csv_rows = None, None
    if os.path.isfile(ride_csv_path):
        checks["has_ride_comparison_csv"] = True
        header, csv_rows = parse_csv_with_header(ride_csv_path)
        if header and csv_rows is not None:
            required_cols = ["app", "option", "est_price", "surge_multiplier", "promo_applied", "eta_minutes", "notes"]
            norm_header = [h.strip().lower() for h in header]
            if all(col in norm_header for col in required_cols):
                checks["ride_comparison_header_ok"] = True

            # required apps presence
            if csv_rows:
                apps_present = {normalize_app(r.get("app", "")) for r in csv_rows}
                if all(a in apps_present for a in ["uber", "lyft", "curb"]):
                    checks["ride_comparison_has_required_apps"] = True

            # options coverage vs input price quotes
            quotes = parse_price_quotes(price_quotes_json)
            # Build expected set for target apps only if we parsed any quotes
            expected = set()
            for q in quotes:
                if q["app"] in ("uber", "lyft", "curb"):
                    expected.add((q["app"], q["option"]))
            csv_pairs = set()
            if csv_rows:
                for r in csv_rows:
                    a = normalize_app(r.get("app"))
                    o = normalize_option(r.get("option"))
                    if a and o:
                        csv_pairs.add((a, o))
            # If we have expected pairs, ensure they exist in CSV
            if expected:
                if expected.issubset(csv_pairs):
                    checks["ride_comparison_has_options_for_inputs"] = True
            else:
                # If no expected parsed, we cannot validate; leave as False
                pass

            # Promo price validation
            promos_by_app = parse_promos(promos_json) if promos_json is not None else {}
            # Build mapping of quotes for quick lookup
            quote_map = {(q["app"], q["option"]): q for q in quotes}
            all_valid = True
            any_checked = False
            for r in csv_rows:
                a = normalize_app(r.get("app"))
                o = normalize_option(r.get("option"))
                if not a or not o:
                    continue
                key = (a, o)
                if key in quote_map:
                    any_checked = True
                    q = quote_map[key]
                    base_final = float(q["base_price"]) * float(q.get("surge_multiplier", 1.0))
                    # recompute best discount
                    discount, promo_id, expected_final = compute_best_discount(a, o, base_final, promos_by_app)
                    # parse est_price and promo_applied from CSV
                    est_price_val = parse_currency_to_float(r.get("est_price", ""))
                    promo_applied = (r.get("promo_applied", "") or "").strip()
                    # Tolerance compare
                    if est_price_val is None or (not float_equal(est_price_val, expected_final)):
                        # allow small rounding like 0.01
                        all_valid = False
                    # check promo_applied correctness
                    if discount > 0:
                        if promo_applied.lower() == "none":
                            all_valid = False
                    else:
                        if promo_applied.lower() != "none":
                            # Allow string like "credit" if discount is zero? Not allowed.
                            all_valid = False
            if any_checked and all_valid:
                checks["ride_comparison_promo_prices_valid"] = True

    # 2) booking_plan.md
    if os.path.isfile(booking_md_path):
        content = read_text(booking_md_path) or ""
        if content.strip():
            checks["booking_plan_exists"] = True
            # required words
            required_words = ["scheduled", "on-demand", "backup", "apply"]
            words_ok = all(w.lower() in content.lower() for w in required_words)
            # "book at" followed by a time
            time_ok = re.search(r"book at\s+\d{1,2}:\d{2}\s*(am|pm|AM|PM)?", content) is not None
            if words_ok and time_ok:
                checks["booking_plan_contains_keywords_and_time"] = True

    # 3) monthly_expense_summary.json
    monthly_data = None
    if os.path.isfile(monthly_json_path):
        monthly_data = read_json(monthly_json_path)
        if isinstance(monthly_data, dict):
            keys_ok = all(k in monthly_data for k in ["month", "total", "by_category", "promo_savings"])
            if keys_ok:
                checks["monthly_summary_exists_and_valid_json"] = True
                # recompute
                month, total, by_cat, promo_saved = recompute_monthly_totals(trips_md_text or "")
                if month is not None:
                    # compare values
                    mt_ok = str(monthly_data.get("month")) == str(month)
                    total_ok = float_equal(monthly_data.get("total"), total)
                    # by_category compare: allow missing categories with zero
                    byc_ok = True
                    out_by_cat = monthly_data.get("by_category", {})
                    if not isinstance(out_by_cat, dict):
                        byc_ok = False
                    else:
                        # compare sums by category keys present in input
                        for k, v in by_cat.items():
                            ov = out_by_cat.get(k)
                            if ov is None or not float_equal(ov, v):
                                byc_ok = False
                                break
                    promo_ok = float_equal(monthly_data.get("promo_savings"), promo_saved)
                    if mt_ok and total_ok and byc_ok and promo_ok:
                        checks["monthly_summary_totals_match"] = True

    # 4) recommended_order.txt
    rec_lines = []
    if os.path.isfile(recommended_txt_path):
        txt = read_text(recommended_txt_path) or ""
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        parsed = []
        all_fmt = True
        for ln in lines:
            p = parse_recommended_line(ln)
            if not p:
                all_fmt = False
                break
            parsed.append(p)
        if lines and all_fmt:
            checks["recommended_order_exists_and_format"] = True
            # Check sorting by price, tie by eta
            sorted_ok = True
            for i in range(1, len(parsed)):
                prev = parsed[i-1]
                cur = parsed[i]
                if cur["price"] < prev["price"] - 1e-9:
                    sorted_ok = False
                    break
                if float_equal(cur["price"], prev["price"]) and cur["eta"] < prev["eta"]:
                    sorted_ok = False
                    break
            if sorted_ok:
                checks["recommended_order_sorted"] = True

            # Cross-check with CSV: same set and consistent prices
            if header and csv_rows:
                # map csv prices
                csv_map = {}
                for r in csv_rows:
                    a = normalize_app(r.get("app"))
                    o = normalize_option(r.get("option"))
                    p = parse_currency_to_float(r.get("est_price"))
                    if a and o and p is not None:
                        csv_map[(a, o)] = p
                rec_set = set()
                prices_match = True
                for p in parsed:
                    key = (normalize_app(p["app"]), normalize_option(p["option"]))
                    rec_set.add(key)
                    if key not in csv_map or not float_equal(csv_map[key], p["price"]):
                        prices_match = False
                        break
                # Check same set and counts
                csv_set = set(csv_map.keys())
                same_set = (rec_set == csv_set)
                if same_set and prices_match:
                    checks["recommended_vs_csv_consistent"] = True

    # 5) .learnings/LEARNINGS.md
    if os.path.isfile(learnings_md_path):
        content = read_text(learnings_md_path) or ""
        # Must contain at least one entry with ID regex
        id_match = re.search(r"^## \[LRN-\d{8}-\d{3}\]", content, re.MULTILINE) is not None
        has_summary = "### Summary" in content
        has_details = "### Details" in content
        has_action = "### Suggested Action" in content
        if id_match and has_summary and has_details and has_action:
            checks["learnings_exists_and_format"] = True

    # 6) discussion/transcript.json
    if os.path.isfile(discussion_json_path):
        disc = read_json(discussion_json_path)
        if isinstance(disc, dict):
            fields_ok = all(k in disc for k in ["id", "topic", "participants", "current_round", "max_rounds", "consensus_level", "rounds"])
            participants_ok = False
            rounds_ok = False
            if fields_ok:
                # participants must include SaverAgent and PunctualityAgent
                agents = set()
                if isinstance(disc.get("participants"), list):
                    for p in disc["participants"]:
                        if isinstance(p, dict) and "agent_id" in p:
                            agents.add(p["agent_id"])
                if "SaverAgent" in agents and "PunctualityAgent" in agents:
                    participants_ok = True
                # rounds must be >= 2 and contain messages
                rds = disc.get("rounds")
                rounds_ok = isinstance(rds, list) and len(rds) >= 2
                msgs_ok = True
                if rounds_ok:
                    for rd in rds:
                        # each round should have messages array or be a dict with messages
                        if not isinstance(rd, dict):
                            msgs_ok = False
                            break
                        msgs = rd.get("messages")
                        if not isinstance(msgs, list) or len(msgs) == 0:
                            msgs_ok = False
                            break
                        for m in msgs:
                            if not (isinstance(m, dict)
                                    and isinstance(m.get("sender"), dict)
                                    and "agent_id" in m.get("sender")
                                    and isinstance(m.get("content"), dict)
                                    and "text" in m.get("content")
                                    and "type" in m):
                                msgs_ok = False
                                break
                        if not msgs_ok:
                            break
                if fields_ok and participants_ok and rounds_ok and msgs_ok:
                    # consensus_level in allowed set
                    cl = str(disc.get("consensus_level", "")).lower()
                    if cl in ("none", "partial", "full"):
                        checks["discussion_transcript_valid"] = True

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = passed / total if total > 0 else 0.0

    # No-op baseline: if no relevant outputs exist, ensure reward is 0.0
    # If all artifact-dependent checks are False (e.g., has_ride_comparison_csv False etc.), reward should be 0
    # The above reward will be 0 in that case.
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()