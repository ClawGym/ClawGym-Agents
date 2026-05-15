import json
import os
import sys
import csv
import re

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def normalize_key(s):
    return re.sub(r"[\s_\-]+", "", s.strip().lower())

def find_dimension_value(vendor_entry, dim_name_norm):
    # Find value for a dimension by normalized key
    for k, v in vendor_entry.items():
        if normalize_key(k) == dim_name_norm:
            fv = safe_float(v)
            if fv is not None:
                return fv
    return None

def parse_vendors(vendors_data):
    # Return dict: {vendor_name: {dimension: value,...}}
    vendors = {}
    if isinstance(vendors_data, dict):
        if "vendors" in vendors_data and isinstance(vendors_data["vendors"], list):
            for entry in vendors_data["vendors"]:
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("vendor") or entry.get("vendor_name")
                    if isinstance(name, str):
                        vendors[name] = entry
        else:
            # assume mapping of name -> metrics dict
            for k, v in vendors_data.items():
                if isinstance(v, dict):
                    vendors[k] = v
    elif isinstance(vendors_data, list):
        for entry in vendors_data:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("vendor") or entry.get("vendor_name")
                if isinstance(name, str):
                    vendors[name] = entry
    return vendors

def compute_weighted_scores(vendors_map, weights):
    scores = {}
    for name, metrics in vendors_map.items():
        total = 0.0
        ok = True
        for dim, w in weights.items():
            val = find_dimension_value(metrics, dim)
            if val is None:
                ok = False
                break
            total += val * w
        scores[name] = total if ok else None
    return scores

def to_two_dec(x):
    return f"{x:.2f}"

def extract_vendor_scores_from_md(md_text, vendor_names):
    # For each vendor, find first line containing vendor name and a two-decimal number, return mapping
    lines = md_text.splitlines()
    vendor_lines_index = {}
    vendor_reported = {}
    vendor_reported_raw = {}
    for idx, line in enumerate(lines):
        lcline = line.lower()
        for name in vendor_names:
            if name.lower() in lcline and name not in vendor_lines_index:
                # find two-decimal numbers in the line
                nums = re.findall(r"(\d{1,3}\.\d{2})", line)
                if nums:
                    # choose the largest number in the line as the likely total score
                    vals = [float(n) for n in nums]
                    max_idx = max(range(len(vals)), key=lambda i: vals[i])
                    vendor_reported[name] = vals[max_idx]
                    vendor_reported_raw[name] = nums[max_idx]
                    vendor_lines_index[name] = idx
    return vendor_reported, vendor_reported_raw, vendor_lines_index

def get_items_from_vendor_offers(vendor_offers):
    # Try to extract an items list [{sku, description?, quantity, ...}]
    items = []
    if isinstance(vendor_offers, dict):
        if isinstance(vendor_offers.get("items"), list):
            for it in vendor_offers["items"]:
                if isinstance(it, dict) and "sku" in it and "quantity" in it:
                    items.append(it)
    elif isinstance(vendor_offers, list):
        # If the whole file is a list of items
        for it in vendor_offers:
            if isinstance(it, dict) and "sku" in it and "quantity" in it:
                items.append(it)
    return items

def build_vendor_price_lookup(vendor_offers):
    # Returns a function price_for(vendor_name, sku, item_obj) -> float|None
    # Support structures:
    # 1) Top-level vendor map: {"vendors": {"Vendor A": {"SKU1": 10.0, ...}, ...}, "items":[...]}
    top_vendor_map = {}
    if isinstance(vendor_offers, dict) and isinstance(vendor_offers.get("vendors"), dict):
        for vname, sku_map in vendor_offers["vendors"].items():
            if isinstance(sku_map, dict):
                top_vendor_map[vname] = {}
                for sku, price in sku_map.items():
                    pf = safe_float(price)
                    if pf is not None:
                        top_vendor_map[vname][str(sku)] = pf

    def price_for(vendor_name, sku, item_obj):
        # Try top-level vendor map first
        if vendor_name in top_vendor_map and str(sku) in top_vendor_map[vendor_name]:
            return top_vendor_map[vendor_name][str(sku)]
        # Try per-item vendor price maps: keys such as 'offers', 'prices', 'vendor_prices', 'per_vendor', 'vendors'
        candidate_keys = ["offers", "prices", "vendor_prices", "per_vendor", "vendors", "unit_prices"]
        for ck in candidate_keys:
            if isinstance(item_obj.get(ck), dict):
                pf = safe_float(item_obj[ck].get(vendor_name))
                if pf is not None:
                    return pf
        # Try if vendor name is directly a key on item
        if vendor_name in item_obj:
            pf = safe_float(item_obj[vendor_name])
            if pf is not None:
                return pf
        return None

    return price_for

def money_close(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol

def compute_approval_keyword(total_amount):
    if total_amount is None:
        return None
    if total_amount < 5000:
        return "Department lead"
    elif total_amount >= 5000 and total_amount < 25000:
        return "VP/Director"
    elif total_amount >= 25000 and total_amount <= 100000:
        return "CFO"
    else:
        return "Board"

def parse_benchmarks_csv(path):
    # Not used for scoring; ensure file can be opened if needed
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            rows.append(r)
    return rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "scorecard_exists": False,
        "scorecard_scores_correct": False,
        "scorecard_two_decimals": False,
        "scorecard_order_correct": False,
        "scorecard_recommendation_top": False,
        "po_markdown_exists": False,
        "po_json_exists": False,
        "po_filename_correct": False,
        "po_json_po_number_correct": False,
        "po_json_vendor_correct": False,
        "po_json_items_match": False,
        "po_json_totals_correct": False,
        "po_json_fields_present": False,
        "po_md_approval_correct": False,
        "negotiation_exists": False,
        "negotiation_headings_present": False,
        "negotiation_mentions_runner_up": False,
    }

    # Prepare expected inputs
    vendors_json_path = os.path.join(input_dir, "vendors.json")
    vendor_offers_path = os.path.join(input_dir, "vendor_offers.json")
    purchase_request_path = os.path.join(input_dir, "purchase_request.json")
    market_benchmarks_path = os.path.join(input_dir, "market_benchmarks.csv")

    # Default values if inputs missing (though they are required for this task)
    weights = {
        "price": 0.25,
        "quality": 0.20,
        "reliability": 0.15,
        "terms": 0.15,
        "support": 0.10,
        "scalability": 0.10,
        "risk": 0.05,
    }
    # Normalize weight keys in advance
    weights = {normalize_key(k): v for k, v in weights.items()}

    # Load inputs
    try:
        vendors_data = read_json(vendors_json_path)
        vendor_offers = read_json(vendor_offers_path)
        purchase_request = read_json(purchase_request_path)
        # market_benchmarks not needed for deterministic checks beyond existence in negotiation doc
    except Exception:
        vendors_data = {}
        vendor_offers = {}
        purchase_request = {}

    vendors_map = parse_vendors(vendors_data)
    expected_scores = compute_weighted_scores(vendors_map, weights)
    # Filter out None scores (missing metrics)
    expected_scores_clean = {k: v for k, v in expected_scores.items() if v is not None}

    # Determine expected rank order and top/runner-up
    sorted_expected = sorted(expected_scores_clean.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    expected_vendor_order = [name for name, _ in sorted_expected]
    expected_top_vendor = expected_vendor_order[0] if expected_vendor_order else None
    expected_runner_up_vendor = expected_vendor_order[1] if len(expected_vendor_order) > 1 else None

    # 1) Vendor scorecard checks
    scorecard_path = os.path.join(output_dir, "vendor_scorecard.md")
    if os.path.isfile(scorecard_path):
        checks["scorecard_exists"] = True
        try:
            with open(scorecard_path, "r", encoding="utf-8") as f:
                score_md = f.read()
        except Exception:
            score_md = ""

        if expected_scores_clean:
            reported_scores, reported_raw, vendor_lines_index = extract_vendor_scores_from_md(score_md, list(expected_scores_clean.keys()))
            # Verify we have a reported score for every vendor with expected score
            all_present = all(name in reported_scores for name in expected_scores_clean.keys())
            # Check numeric correctness within ±0.1
            if all_present:
                all_close = True
                for name, exp_val in expected_scores_clean.items():
                    rep = reported_scores.get(name)
                    if rep is None or abs(rep - exp_val) > 0.1:
                        all_close = False
                        break
                checks["scorecard_scores_correct"] = all_close
                # Check two decimals formatting (based on captured raw having two decimals)
                all_twodec = all(reported_raw.get(name) is not None and re.fullmatch(r"\d{1,3}\.\d{2}", reported_raw.get(name)) for name in expected_scores_clean.keys())
                checks["scorecard_two_decimals"] = all_twodec
                # Check order correctness: compare order of first vendor lines containing name and a two-dec number
                if len(vendor_lines_index) == len(expected_scores_clean):
                    order_by_line = sorted(vendor_lines_index.items(), key=lambda kv: kv[1])
                    observed_order = [name for name, _ in order_by_line]
                    checks["scorecard_order_correct"] = (observed_order == expected_vendor_order)
                else:
                    checks["scorecard_order_correct"] = False
            else:
                checks["scorecard_scores_correct"] = False
                checks["scorecard_two_decimals"] = False
                checks["scorecard_order_correct"] = False

            # Recommendation line includes top vendor
            if expected_top_vendor:
                rec_lines = [ln for ln in score_md.splitlines() if "recommend" in ln.lower()]
                if rec_lines:
                    top_in_rec = any(expected_top_vendor.lower() in ln.lower() for ln in rec_lines)
                    checks["scorecard_recommendation_top"] = top_in_rec
                else:
                    checks["scorecard_recommendation_top"] = False
    # 2) Purchase order checks
    po_date = purchase_request.get("po_date")
    tax_rate = safe_float(purchase_request.get("tax_rate"))
    # Build expected PO markdown filename
    expected_po_md_filename = f"PO-{po_date}-001.md" if isinstance(po_date, str) else None
    expected_po_md_path = os.path.join(output_dir, expected_po_md_filename) if expected_po_md_filename else None
    if expected_po_md_path and os.path.isfile(expected_po_md_path):
        checks["po_markdown_exists"] = True
        checks["po_filename_correct"] = True
    else:
        # If the expected filename is determined but file not found, po_markdown_exists remains False
        if expected_po_md_filename is not None and os.path.isfile(os.path.join(output_dir, expected_po_md_filename or "")):
            checks["po_markdown_exists"] = True
        # filename correctness can only be true if path is correct and exists
        checks["po_filename_correct"] = False

    po_json_path = os.path.join(output_dir, "po.json")
    if os.path.isfile(po_json_path):
        checks["po_json_exists"] = True
        try:
            po_json = read_json(po_json_path)
        except Exception:
            po_json = {}
        # po_number correctness
        expected_po_number = f"PO-{po_date}-001" if isinstance(po_date, str) else None
        if expected_po_number and isinstance(po_json.get("po_number"), str) and po_json["po_number"] == expected_po_number:
            checks["po_json_po_number_correct"] = True

        # vendor correctness
        if expected_top_vendor and isinstance(po_json.get("vendor"), str):
            if po_json["vendor"].strip().lower() == expected_top_vendor.strip().lower():
                checks["po_json_vendor_correct"] = True

        # items match SKUs and quantities/prices
        items_input = get_items_from_vendor_offers(vendor_offers)
        price_lookup = build_vendor_price_lookup(vendor_offers)
        items_expected = {}
        if expected_top_vendor and items_input:
            all_prices_found = True
            for it in items_input:
                sku = str(it.get("sku"))
                qty = safe_float(it.get("quantity"))
                price = price_lookup(expected_top_vendor, sku, it)
                if sku is None or qty is None or price is None:
                    all_prices_found = False
                    break
                items_expected[sku] = {"quantity": qty, "unit_price": price, "description": it.get("description")}
            # Compare with po.json items
            po_items = po_json.get("items")
            if all_prices_found and isinstance(po_items, list) and len(po_items) == len(items_expected):
                ok_items = True
                for pit in po_items:
                    if not isinstance(pit, dict):
                        ok_items = False
                        break
                    psku = str(pit.get("sku"))
                    pqty = safe_float(pit.get("quantity"))
                    pprice = safe_float(pit.get("unit_price"))
                    if psku not in items_expected:
                        ok_items = False
                        break
                    exp = items_expected[psku]
                    if not money_close(pqty, exp["quantity"], tol=0.0):
                        ok_items = False
                        break
                    if not money_close(pprice, exp["unit_price"], tol=0.01):
                        ok_items = False
                        break
                checks["po_json_items_match"] = ok_items

                # Totals check
                if tax_rate is not None:
                    subtotal_expected = 0.0
                    for sku, exp in items_expected.items():
                        subtotal_expected += exp["quantity"] * exp["unit_price"]
                    tax_expected = subtotal_expected * tax_rate
                    total_expected = subtotal_expected + tax_expected
                    subtotal_ok = money_close(safe_float(po_json.get("subtotal")), subtotal_expected, tol=0.01)
                    tax_ok = money_close(safe_float(po_json.get("tax")), tax_expected, tol=0.01)
                    total_ok = money_close(safe_float(po_json.get("total")), total_expected, tol=0.01)
                    checks["po_json_totals_correct"] = (subtotal_ok and tax_ok and total_ok)

                    # Approval Routing in markdown: verify correct approver keyword
                    if checks["po_markdown_exists"] and expected_po_md_path:
                        try:
                            with open(expected_po_md_path, "r", encoding="utf-8") as f:
                                po_md_text = f.read()
                        except Exception:
                            po_md_text = ""
                        expected_approver = compute_approval_keyword(total_expected)
                        if expected_approver:
                            # The section must contain the correct approver keyword
                            if expected_approver.lower() in po_md_text.lower():
                                checks["po_md_approval_correct"] = True

        # Fields present (payment_terms, delivery_date, ship_to, bill_to)
        fields_present = all(
            key in po_json and po_json.get(key) not in (None, "", [])
            for key in ["payment_terms", "delivery_date", "ship_to", "bill_to"]
        )
        checks["po_json_fields_present"] = fields_present

    # 3) Negotiation brief
    negotiation_path = os.path.join(output_dir, "negotiation_brief.md")
    if os.path.isfile(negotiation_path):
        checks["negotiation_exists"] = True
        try:
            with open(negotiation_path, "r", encoding="utf-8") as f:
                neg_text = f.read()
        except Exception:
            neg_text = ""
        # Headings present
        required_titles = ["Market Benchmarks", "Leverage Points", "Counter-Offer", "Walk-Away Price", "BATNA"]
        headings_ok = True
        lines = [ln.strip() for ln in neg_text.splitlines()]
        for title in required_titles:
            found = False
            for ln in lines:
                if ln == title:
                    found = True
                    break
                if ln.startswith("#") and ln.lstrip("#").strip() == title:
                    found = True
                    break
            if not found:
                headings_ok = False
                break
        checks["negotiation_headings_present"] = headings_ok

        # Runner-up vendor mentioned
        if expected_runner_up_vendor:
            if expected_runner_up_vendor.lower() in neg_text.lower():
                checks["negotiation_mentions_runner_up"] = True

    # Compute reward as average of checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    output_has_files = False
    if output_exists:
        for _, _, files in os.walk(output_dir):
            if files:
                output_has_files = True
                break
    if not output_has_files:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()