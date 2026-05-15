import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def find_headings(lines):
    # Returns set of heading titles (text after leading #)
    heads = set()
    for ln in lines:
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", ln)
        if m:
            heads.add(m.group(1).strip())
    return heads

def contains_word(text, word):
    # whole word match, case-insensitive
    return re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE) is not None

def parse_table_in_markdown(md_text):
    # Find any markdown table that includes SKU | Price | Total Cost | Net Profit | Margin | Status
    # Return header list and row list (each row is list of cells)
    lines = [ln.rstrip("\n") for ln in md_text.splitlines()]
    tables = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("|") and ln.count("|") >= 6:
            header_cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            normalized_headers = [c.lower() for c in header_cells]
            required = ["sku", "price", "total cost", "net profit", "margin", "status"]
            if all(any(req == h for h in normalized_headers) for req in required):
                # Found header; next line likely separator; then data rows starting with |
                j = i + 1
                # skip separator line(s)
                while j < len(lines) and lines[j].strip().startswith("|") and set(lines[j].replace("|", "").strip()) <= set("-: "):
                    j += 1
                rows = []
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row_cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    if len(row_cells) >= len(header_cells):
                        rows.append(row_cells[:len(header_cells)])
                    else:
                        rows.append(row_cells)
                    j += 1
                tables.append((header_cells, rows))
                i = j
                continue
        i += 1
    return tables

def money_to_float(s):
    s = s.strip()
    s = s.replace("$", "").replace(",", "")
    try:
        return float(s)
    except Exception:
        return None

def percent_to_float(s):
    s = s.strip().replace("%", "")
    try:
        return float(s) / 100.0
    except Exception:
        return None

def get_category_rate(category):
    if not category:
        return 0.15
    c = category.strip().lower()
    if c in ("electronics", "computers", "camera", "photo"):
        return 0.08
    if c in ("automotive", "industrial"):
        return 0.12
    if c in ("clothing", "apparel"):
        return 0.17
    if c in ("jewelry",):
        return 0.20
    return 0.15

def parse_csv_products(csv_path):
    products = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                products.append(row)
    except Exception:
        return None
    return products

def get_float(row, keys, default=0.0):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            try:
                return float(row[k])
            except Exception:
                pass
    return default

def get_str(row, keys, default=""):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return str(row[k])
    return default

def compute_expected_metrics(row):
    # Extract needed fields with fallbacks
    sku = get_str(row, ["sku", "SKU"])
    selling_price = get_float(row, ["selling_price", "price"])
    product_cost = get_float(row, ["product_cost", "cost"])
    shipping_cost = get_float(row, ["shipping_cost", "shipping"])
    fba_fee = get_float(row, ["fba_fee", "fba_fulfillment", "fba_fulfillment_fee"])
    storage_fee = get_float(row, ["storage_fee"])
    ad_ratio = get_float(row, ["ad_ratio", "ad_spend_ratio"])
    return_rate = get_float(row, ["return_rate"])
    return_fee = get_float(row, ["return_fee"])
    other_fees = get_float(row, ["other_fees"])
    category = get_str(row, ["category"])

    referral_rate = get_category_rate(category)
    referral_fee = selling_price * referral_rate
    ad_spend = selling_price * ad_ratio
    returns_cost = return_rate * (return_fee + product_cost * 0.5)

    total_cost = (
        product_cost
        + shipping_cost
        + fba_fee
        + storage_fee
        + referral_fee
        + ad_spend
        + returns_cost
        + other_fees
    )
    net_profit = selling_price - total_cost
    net_margin = (net_profit / selling_price) if selling_price > 0 else 0.0

    # Classification
    if net_margin < 0:
        status = "loss"
    elif net_margin < 0.05:
        status = "danger"
    elif net_margin < 0.20:
        status = "warning"
    else:
        status = "healthy"

    return {
        "sku": sku,
        "price": selling_price,
        "total_cost": total_cost,
        "net_profit": net_profit,
        "net_margin": net_margin,
        "status": status,
    }

def parse_table_map(header, rows):
    # Map column index by normalized header
    norm = [h.strip().lower() for h in header]
    def idx(name):
        try:
            return norm.index(name)
        except ValueError:
            return -1
    col_idx = {
        "sku": idx("sku"),
        "price": idx("price"),
        "total cost": idx("total cost"),
        "net profit": idx("net profit"),
        "margin": idx("margin"),
        "status": idx("status"),
    }
    parsed = {}
    for r in rows:
        if len(r) < len(header):  # skip malformed
            continue
        sku = r[col_idx["sku"]].strip()
        price = money_to_float(r[col_idx["price"]]) if col_idx["price"] >= 0 else None
        total_cost = money_to_float(r[col_idx["total cost"]]) if col_idx["total cost"] >= 0 else None
        net_profit = money_to_float(r[col_idx["net profit"]]) if col_idx["net profit"] >= 0 else None
        margin_cell = r[col_idx["margin"]] if col_idx["margin"] >= 0 else None
        margin = percent_to_float(margin_cell) if margin_cell is not None else None
        status_cell = r[col_idx["status"]].strip().lower() if col_idx["status"] >= 0 else ""
        parsed[sku] = {
            "price": price,
            "total_cost": total_cost,
            "net_profit": net_profit,
            "margin": margin,
            "status": status_cell,
            "raw": r,
        }
    return parsed

def run_checks(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Runbook
        "runbook_exists": False,
        "runbook_tokens": False,
        "runbook_triad_postverify": False,
        # ADR
        "adr_exists": False,
        "adr_sections": False,
        "adr_mentions": False,
        # Session state
        "session_exists": False,
        "session_heading": False,
        "session_contains_all_values": False,
        # Working buffer
        "buffer_exists": False,
        "buffer_header_active": False,
        "buffer_sections_present": False,
        "buffer_human_has_incident": False,
        # Profit report
        "profit_exists": False,
        "profit_table_present": False,
        "profit_skus_present": False,
        "profit_values_correct": False,
        "profit_status_correct": False,
    }

    # 1) Runbook
    runbook_path = os.path.join(output_dir, "docs", "runbooks", "gateway-outage-recovery.md")
    runbook_text = read_text(runbook_path)
    if runbook_text is not None:
        checks["runbook_exists"] = True
        text_lower = runbook_text.lower()

        # Required tokens (use word boundaries for command families)
        tokens_word = ["status", "health", "doctor", "gateway", "node", "nodes", "channels", "message"]
        tokens_flags = ["--json", "--dev", "--profile", "reset", "uninstall", "--force"]
        word_ok = all(contains_word(text_lower, t) for t in tokens_word)
        flag_ok = all(t in runbook_text for t in tokens_flags)
        checks["runbook_tokens"] = word_ok and flag_ok

        # Triage sequence line and post-verification section mentioning checks
        triage_ok = "status -> health -> doctor" in text_lower
        post_verify_ok = (re.search(r"post[- ]verification", runbook_text, flags=re.IGNORECASE) is not None) and ("check" in text_lower)
        checks["runbook_triad_postverify"] = triage_ok and post_verify_ok

    # 2) ADR
    adr_path = os.path.join(output_dir, "docs", "decisions", "001-profile-strategy.md")
    adr_text = read_text(adr_path)
    if adr_text is not None:
        checks["adr_exists"] = True
        lines = adr_text.splitlines()
        headings = set()
        for ln in lines:
            m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", ln)
            if m:
                headings.add(m.group(1).strip().lower())
        needed_sections = {"status", "context", "decision", "consequences", "alternatives"}
        checks["adr_sections"] = needed_sections.issubset(headings)

        low = adr_text.lower()
        mentions = all(x in low for x in ["default profile", "isolated profile", "staging", "dev"])
        checks["adr_mentions"] = mentions

    # 3) SESSION-STATE.md
    session_path = os.path.join(output_dir, "memory", "SESSION-STATE.md")
    session_text = read_text(session_path)
    if session_text is not None:
        checks["session_exists"] = True
        # Heading "Active Incident State"
        checks["session_heading"] = re.search(r"^\s{0,3}#{1,6}\s*Active Incident State\s*$", session_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        need_vals = [
            "19001",
            "staging profile",
            "whatsapp",
            "node-01",
            "+15555550123",
            "status -> health -> doctor",
            "do not restart until triage",
        ]
        low = session_text.lower()
        basic_vals_ok = all(v.lower() in low for v in need_vals)
        # Explicit confirmation rule regarding reset and uninstall
        explicit_rule_ok = ("reset" in low and "uninstall" in low and "explicit confirmation" in low)
        checks["session_contains_all_values"] = basic_vals_ok and explicit_rule_ok

    # 4) working-buffer.md
    buffer_path = os.path.join(output_dir, "memory", "working-buffer.md")
    buffer_text = read_text(buffer_path)
    if buffer_text is not None:
        checks["buffer_exists"] = True
        checks["buffer_header_active"] = ("Working Buffer (Danger Zone Log)" in buffer_text) and ("Status: ACTIVE" in buffer_text)
        # Sections Human and Agent (summary)
        has_human = re.search(r"^\s{0,3}#{2,6}.*Human.*$", buffer_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        has_agent = re.search(r"^\s{0,3}#{2,6}.*Agent\s*\(summary\).*$", buffer_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        checks["buffer_sections_present"] = has_human and has_agent
        # Human section contains the word "Incident:"
        checks["buffer_human_has_incident"] = ("Incident:" in buffer_text)

    # 5) amazon-profit.md
    profit_path = os.path.join(output_dir, "reports", "amazon-profit.md")
    profit_text = read_text(profit_path)
    if profit_text is not None:
        checks["profit_exists"] = True
        # Ensure a "Batch Analysis Summary" table exists
        has_header_phrase = re.search(r"Batch Analysis Summary", profit_text, flags=re.IGNORECASE) is not None
        tables = parse_table_in_markdown(profit_text)
        checks["profit_table_present"] = has_header_phrase and len(tables) > 0

        # Evaluate against input/skus.csv
        skus_csv_path = os.path.join(input_dir, "skus.csv")
        products = parse_csv_products(skus_csv_path)
        if products is not None and len(tables) > 0:
            # Build expected dict
            expected_map = {}
            for row in products:
                exp = compute_expected_metrics(row)
                if exp["sku"]:
                    expected_map[exp["sku"]] = exp

            # Find a table that includes all required SKUs
            parsed_map = {}
            for header, rows in tables:
                pm = parse_table_map(header, rows)
                if all(sku in pm for sku in expected_map.keys()):
                    parsed_map = pm
                    break

            checks["profit_skus_present"] = (len(parsed_map) > 0) and all(sku in parsed_map for sku in expected_map.keys())

            if checks["profit_skus_present"]:
                # Validate values with tolerances
                values_ok = True
                status_ok = True
                for sku, exp in expected_map.items():
                    row = parsed_map.get(sku)
                    if row is None:
                        values_ok = False
                        status_ok = False
                        break
                    # Compare price (not strictly required by spec, so only check if present)
                    # Compare total cost and net profit within +/- 0.05
                    tc = row.get("total_cost")
                    npv = row.get("net_profit")
                    mg = row.get("margin")
                    st = row.get("status", "")
                    if tc is None or npv is None or mg is None:
                        values_ok = False
                        status_ok = False
                        break
                    if abs(tc - exp["total_cost"]) > 0.05:
                        values_ok = False
                    if abs(npv - exp["net_profit"]) > 0.05:
                        values_ok = False
                    if abs(mg - exp["net_margin"]) > 0.005:
                        values_ok = False
                    # status cell may include emoji; ensure it contains our expected status word
                    if exp["status"] not in st:
                        # if no explicit word, try to interpret possible short forms
                        status_ok = False
                checks["profit_values_correct"] = values_ok
                checks["profit_status_correct"] = status_ok

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0
    # Ensure baseline 0 if no outputs
    if not any([
        checks["runbook_exists"],
        checks["adr_exists"],
        checks["session_exists"],
        checks["buffer_exists"],
        checks["profit_exists"],
    ]):
        reward = 0.0

    return reward, checks

if __name__ == "__main__":
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    reward, checks = run_checks(workspace_root)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))