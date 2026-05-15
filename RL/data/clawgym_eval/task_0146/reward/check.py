import json
import os
import sys
import csv
from decimal import Decimal, getcontext, ROUND_HALF_UP
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def dquant(value, q="0.01"):
    # ensure Decimal with string constructor to avoid float artifacts
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(Decimal(q), rounding=ROUND_HALF_UP)

def fmt2(value):
    return format(dquant(value), "f")

def parse_decimal_safe(s):
    try:
        return Decimal(str(s))
    except Exception:
        # Try stripping commas or spaces
        try:
            return Decimal(str(s).replace(",", "").strip())
        except Exception:
            return None

def compute_fv(principal, rate, years, freq):
    # high precision for compounding
    getcontext().prec = 50
    p = Decimal(str(principal))
    r = Decimal(str(rate))
    f = Decimal(str(freq))
    # (1 + r/f) ** (f * years)
    try:
        base = Decimal("1") + (r / f)
        exp = int(Decimal(str(freq)) * Decimal(str(years)))
        factor = base ** exp
        fv = p * factor
        return fv
    except Exception:
        return None

def build_expected_fv_table(inv):
    # inv expected keys: principal, rates (list), periods (list) or years (list), frequency (int)
    principal = inv.get("principal")
    rates = inv.get("rates", [])
    periods = inv.get("periods", inv.get("years", []))
    freq = inv.get("frequency", inv.get("compounding_frequency", 1))
    try:
        freq_int = int(freq)
    except Exception:
        return None

    try:
        principal_d = Decimal(str(principal))
    except Exception:
        return None

    expected = {}
    for rate in rates:
        try:
            rate_d = Decimal(str(rate))
        except Exception:
            return None
        for yrs in periods:
            try:
                years_int = int(yrs)
            except Exception:
                return None
            fv = compute_fv(principal_d, rate_d, years_int, freq_int)
            if fv is None:
                return None
            total_gain = fv - principal_d
            gain_percent = (total_gain / principal_d) * Decimal("100")
            expected[(rate_d, years_int)] = {
                "final_value": fmt2(fv),
                "total_gain": fmt2(total_gain),
                "gain_percent": fmt2(gain_percent),
            }
    return expected

def check_fv_table(output_fv_path, input_investment_path):
    rows = read_csv_rows(output_fv_path)
    if not rows or len(rows) < 2:
        return False
    header = rows[0]
    if header != ["rate", "years", "final_value", "total_gain", "gain_percent"]:
        return False

    inv = read_json(input_investment_path)
    if not isinstance(inv, dict):
        return False
    expected = build_expected_fv_table(inv)
    if expected is None:
        return False

    found = set()
    for row in rows[1:]:
        if len(row) != 5:
            continue
        rate_s, years_s, fv_s, tg_s, gp_s = [c.strip() for c in row]
        rate_d = parse_decimal_safe(rate_s)
        try:
            years_i = int(years_s)
        except Exception:
            continue
        if rate_d is None:
            continue
        key = None
        # match by numeric equality with expected keys (Decimal exact)
        for (erate, eyears) in expected.keys():
            if eyears == years_i and erate == rate_d:
                key = (erate, eyears)
                break
        if key is None:
            continue
        exp_vals = expected[key]
        # Compare strings exactly for 2-decimal formatting
        if fv_s == exp_vals["final_value"] and tg_s == exp_vals["total_gain"] and gp_s == exp_vals["gain_percent"]:
            found.add(key)

    # All expected combos must be present
    return found == set(expected.keys())

def compute_pricing_for_services(input_services_path):
    rows = read_csv_rows(input_services_path)
    if not rows or len(rows) < 2:
        return None
    header = [h.strip() for h in rows[0]]
    if header != ["service", "cost", "markup_percent"]:
        # The task specifies this exact input format
        return None
    expected = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        service = row[0].strip()
        cost = parse_decimal_safe(row[1])
        mp = parse_decimal_safe(row[2])
        if service == "" or cost is None or mp is None:
            continue
        markup_amount = cost * (mp / Decimal("100"))
        selling_price = cost + markup_amount
        margin_percent = (markup_amount / selling_price) * Decimal("100") if selling_price != 0 else Decimal("0")
        expected[service] = {
            "service": service,
            "cost": row[1].strip(),
            "markup_percent": row[2].strip(),
            "markup_amount": fmt2(markup_amount),
            "selling_price": fmt2(selling_price),
            "margin_percent": fmt2(margin_percent),
        }
    return expected

def check_services_pricing(output_pricing_path, input_services_path):
    out_rows = read_csv_rows(output_pricing_path)
    if not out_rows or len(out_rows) < 2:
        return False
    header = out_rows[0]
    if header != ["service", "cost", "markup_percent", "markup_amount", "selling_price", "margin_percent"]:
        return False

    expected = compute_pricing_for_services(input_services_path)
    if expected is None or not expected:
        return False

    # Build lookup from output by service name
    out_map = {}
    for row in out_rows[1:]:
        if len(row) != 6:
            continue
        svc = row[0].strip()
        out_map[svc] = {
            "service": row[0].strip(),
            "cost": row[1].strip(),
            "markup_percent": row[2].strip(),
            "markup_amount": row[3].strip(),
            "selling_price": row[4].strip(),
            "margin_percent": row[5].strip(),
        }

    # Verify every input row appears correctly in output
    for svc, exp in expected.items():
        got = out_map.get(svc)
        if not got:
            return False
        # cost and markup_percent can be formatted differently; compare numerically
        cost_ok = False
        mp_ok = False
        try:
            cost_ok = dquant(parse_decimal_safe(got["cost"])) == dquant(parse_decimal_safe(exp["cost"]))
            mp_ok = dquant(parse_decimal_safe(got["markup_percent"])) == dquant(parse_decimal_safe(exp["markup_percent"]))
        except Exception:
            cost_ok = False
            mp_ok = False
        if not cost_ok or not mp_ok:
            return False
        # The computed fields must match exactly as 2-decimal strings
        if got["markup_amount"] != exp["markup_amount"]:
            return False
        if got["selling_price"] != exp["selling_price"]:
            return False
        if got["margin_percent"] != exp["margin_percent"]:
            return False
    return True

def extract_investment_line_amount(text):
    # Find the line that starts with "- **Investment:** "
    for line in text.splitlines():
        if line.strip().startswith("- **Investment:**"):
            # Extract $amount pattern
            m = re.search(r"\$[0-9,]+\.[0-9]{2}", line)
            if m:
                amt_str = m.group(0)
                # remove $ and commas
                amt_num = amt_str.replace("$", "").replace(",", "")
                try:
                    return dquant(Decimal(amt_num))
                except Exception:
                    return None
            return None
    return None

def check_proposal(output_proposal_path, input_client_path, input_services_path):
    try:
        with open(output_proposal_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False

    client = read_json(input_client_path)
    if not isinstance(client, dict):
        return False

    # Compute expected selling price for the selected package
    package = client.get("package_to_quote", "")
    pricing = compute_pricing_for_services(input_services_path)
    if not pricing or package not in pricing:
        return False
    expected_price = dquant(Decimal(pricing[package]["selling_price"]))

    # Verify core structure and placeholders
    project_name = client.get("project_name", "")
    client_name = client.get("client_name", "")
    timeline = client.get("timeline", "")
    scope = client.get("project_scope", [])
    freelancer_name = client.get("freelancer_name", "")

    lines = content.splitlines()

    # Basic structure checks
    if not lines:
        return False
    if lines[0].strip() != f"Subject: Proposal for {project_name}":
        return False

    # Ensure greeting line present after a blank line
    # Allow some flexibility in blank lines
    try:
        # Find "Hi {client_name},"
        greeting_idx = None
        for i, ln in enumerate(lines[1:], start=1):
            if ln.strip() == f"Hi {client_name},":
                greeting_idx = i
                break
        if greeting_idx is None:
            return False
    except Exception:
        return False

    # Required labeled lines
    required_project_line = f"- **Project:** {project_name}"
    if required_project_line not in content:
        return False

    if "- **Scope:**" not in content:
        return False

    # Scope items each as its own bulleted line (accept 2 or 4 spaces indent before "-")
    for item in scope:
        pattern_ok = False
        for ln in lines:
            stripped = ln.lstrip()
            # must be a line starting with "- " then the item
            if stripped.startswith(f"- {item}"):
                # Ensure it's under Scope section by position: find scope line then items after it
                pattern_ok = True
                break
        if not pattern_ok:
            return False

    # Investment line and amount
    if "- **Investment:**" not in content:
        return False
    inv_amount = extract_investment_line_amount(content)
    if inv_amount is None:
        return False
    if inv_amount != expected_price:
        return False

    # Timeline line
    if f"- **Timeline:** {timeline}" not in content:
        return False

    # Closing lines
    closing_sentence = ("I am confident that we can achieve the goals we discussed. Please let me know "
                        "if you have any questions or would like to proceed with the next steps.")
    if closing_sentence not in content:
        return False
    if "Best regards," not in content:
        return False
    # Freelancer signature line present
    if freelancer_name not in [ln.strip() for ln in lines]:
        return False

    return True

def check_retainer_gl(output_gl_path, input_client_path, input_services_path):
    data = read_json(output_gl_path)
    if not isinstance(data, dict):
        return False

    client = read_json(input_client_path)
    if not isinstance(client, dict):
        return False

    # Verify voucher fields
    for key in ["voucher_type", "voucher_id", "posting_date", "entries"]:
        if key not in data:
            return False

    if data["voucher_type"] != client.get("voucher_type"):
        return False
    if data["voucher_id"] != client.get("voucher_id"):
        return False
    if data["posting_date"] != client.get("posting_date"):
        return False

    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) != 2:
        return False

    # Compute expected amounts
    package = client.get("package_to_quote", "")
    pricing = compute_pricing_for_services(input_services_path)
    if not pricing or package not in pricing:
        return False
    selling_price = dquant(Decimal(pricing[package]["selling_price"]))
    retainer_percent = parse_decimal_safe(client.get("retainer_percent", 0))
    if retainer_percent is None:
        return False
    retainer_amount = dquant(selling_price * (retainer_percent / Decimal("100")))

    bank_account_name = client.get("bank_account_name", "")
    unearned_revenue_account_name = client.get("unearned_revenue_account_name", "")

    # Validate two entries
    has_bank_debit = False
    has_unearned_credit = False
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for e in entries:
        if not isinstance(e, dict):
            return False
        if set(e.keys()) != {"account_name", "debit", "credit"}:
            return False
        # amounts as Decimals
        debit = parse_decimal_safe(e.get("debit", 0))
        credit = parse_decimal_safe(e.get("credit", 0))
        if debit is None or credit is None:
            return False
        # Sum totals
        total_debit += dquant(debit)
        total_credit += dquant(credit)
        # Check bank line
        if e.get("account_name") == bank_account_name:
            if dquant(debit) == retainer_amount and dquant(credit) == dquant(0):
                has_bank_debit = True
        # Check unearned revenue line
        if e.get("account_name") == unearned_revenue_account_name:
            if dquant(debit) == dquant(0) and dquant(credit) == retainer_amount:
                has_unearned_credit = True

    if not has_bank_debit or not has_unearned_credit:
        return False

    if total_debit != total_credit:
        return False
    if total_debit != retainer_amount:
        return False

    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    investment_path = os.path.join(input_dir, "investment.json")
    services_input_path = os.path.join(input_dir, "services.csv")
    client_path = os.path.join(input_dir, "client.json")

    fv_table_path = os.path.join(output_dir, "fv_table.csv")
    services_pricing_path = os.path.join(output_dir, "pricing", "services_pricing.csv")
    proposal_path = os.path.join(output_dir, "proposal", "proposal.txt")
    retainer_gl_path = os.path.join(output_dir, "accounting", "retainer_gl.json")

    fv_ok = False
    pricing_ok = False
    proposal_ok = False
    gl_ok = False

    # Check 1: FV table
    if os.path.isfile(fv_table_path) and os.path.isfile(investment_path):
        fv_ok = check_fv_table(fv_table_path, investment_path)

    # Check 2: Services pricing
    if os.path.isfile(services_pricing_path) and os.path.isfile(services_input_path):
        pricing_ok = check_services_pricing(services_pricing_path, services_input_path)

    # Check 3: Proposal
    if os.path.isfile(proposal_path) and os.path.isfile(client_path) and os.path.isfile(services_input_path):
        proposal_ok = check_proposal(proposal_path, client_path, services_input_path)

    # Check 4: Retainer GL
    if os.path.isfile(retainer_gl_path) and os.path.isfile(client_path) and os.path.isfile(services_input_path):
        gl_ok = check_retainer_gl(retainer_gl_path, client_path, services_input_path)

    # Reward: equal weight
    total_checks = 4
    passed = sum([fv_ok, pricing_ok, proposal_ok, gl_ok])
    reward = passed / total_checks if passed > 0 else 0.0

    result = {
        "reward": reward,
        "fv_table_ok": bool(fv_ok),
        "services_pricing_ok": bool(pricing_ok),
        "proposal_ok": bool(proposal_ok),
        "retainer_gl_ok": bool(gl_ok),
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()