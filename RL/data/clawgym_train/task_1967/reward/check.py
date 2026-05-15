import json
import os
import sys
import csv
import re
from decimal import Decimal, ROUND_HALF_UP

# Workspace handling
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Optional dependency: PyYAML
try:
    import yaml
except Exception:
    yaml = None

def round_half_up(n, ndigits=0):
    q = Decimal(10) ** -ndigits
    return float(Decimal(str(n)).quantize(q, rounding=ROUND_HALF_UP))

def round_int_half_up(n):
    return int(Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def read_yaml(path):
    if yaml is None:
        return None, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data, True
    except Exception:
        return None, False

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except Exception:
        return None, False

def read_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows, True
    except Exception:
        return None, False

def word_count(text):
    if not isinstance(text, str):
        return 0
    # Simple whitespace split
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def normalize_text(x):
    if x is None:
        return ""
    if isinstance(x, (list, tuple)):
        return "\n".join([normalize_text(y) for y in x])
    if isinstance(x, dict):
        # Concatenate values
        return "\n".join([normalize_text(v) for v in x.values()])
    return str(x)

def get_company_from_prospect(prospect):
    if not isinstance(prospect, dict):
        return None
    for key in ["company", "company_name", "prospect_company", "prospect", "client", "organization", "companyName"]:
        if key in prospect and isinstance(prospect[key], str) and prospect[key].strip():
            return prospect[key]
    return None

def get_section_text(section_value):
    # Supports either string directly, dict with 'content', list of strings, or nested
    if isinstance(section_value, dict):
        if "content" in section_value:
            return normalize_text(section_value.get("content"))
        else:
            return normalize_text(section_value)
    elif isinstance(section_value, list):
        return "\n".join([normalize_text(x) for x in section_value])
    else:
        return normalize_text(section_value)

def detect_investment_options(inv_value):
    # Return (has_at_least_two_options, has_recommended)
    text = get_section_text(inv_value)
    has_recommended = bool(re.search(r"recommended", text, flags=re.IGNORECASE))
    # Detect options count
    options_count = 0
    if isinstance(inv_value, list):
        options_count = len(inv_value)
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Count lines that look like options
        for ln in lines:
            if re.match(r"^[-*]\s", ln):
                options_count += 1
            elif re.match(r"^\d+[\.\)]\s", ln):
                options_count += 1
            elif re.search(r"\boption\s*\d*\b", ln, flags=re.IGNORECASE):
                options_count += 1
            elif re.search(r"\b(starter|professional|premium)\b", ln, flags=re.IGNORECASE):
                options_count += 1
    return (options_count >= 2, has_recommended)

def parse_amount(x):
    # Try to parse string/number to float
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", "")
        return float(s)
    except Exception:
        return None

def find_niche_column_and_scores(rows):
    if not rows:
        return None, {}
    headers = list(rows[0].keys())
    lower_headers = [h.lower() if h is not None else "" for h in headers]
    niche_col = None
    # Prefer 'niche' column
    for i, h in enumerate(lower_headers):
        if h == "niche":
            niche_col = headers[i]
            break
    if niche_col is None:
        # Default to first column
        niche_col = headers[0]
    scores = {}
    for r in rows:
        niche = (r.get(niche_col) or "").strip()
        total = 0.0
        for h in headers:
            if h == niche_col:
                continue
            val = r.get(h)
            num = parse_amount(val)
            if num is not None:
                total += num
        scores[niche] = total
    return niche_col, scores

def sum_by_client(revenue_rows, client_col_candidates=("client", "client_name", "customer", "company", "name")):
    # Determine client column
    if not revenue_rows:
        return []
    headers = list(revenue_rows[0].keys())
    lower_to_orig = {h.lower(): h for h in headers if h is not None}
    client_col = None
    for cand in client_col_candidates:
        if cand in lower_to_orig:
            client_col = lower_to_orig[cand]
            break
    if client_col is None:
        # Fallback to first non-amount column
        for h in headers:
            if h and h.lower() not in ("amount", "type", "date"):
                client_col = h
                break
        if client_col is None:
            client_col = headers[0]
    agg = {}
    for r in revenue_rows:
        client = (r.get(client_col) or "").strip()
        amt = parse_amount(r.get("amount"))
        if amt is None:
            # Try alternative 'Amount' or other
            amt = parse_amount(r.get("Amount"))
        if amt is None:
            continue
        agg[client] = agg.get(client, 0.0) + amt
    # Convert to list of dicts
    result = [{"client": k, "amount": v} for k, v in agg.items()]
    return result

# Initialize checks (all False)
checks = {
    # Positioning
    "positioning_file_exists": False,
    "positioning_yaml_parse": False,
    "positioning_required_keys": False,
    "positioning_niche_present_in_csv": False,
    "positioning_niche_meets_threshold": False,
    # Packages
    "packages_file_exists": False,
    "packages_yaml_parse": False,
    "packages_required_tiers": False,
    "packages_required_fields_each_tier": False,
    "packages_prices_numeric": False,
    "packages_price_ratios_valid": False,
    "packages_prof_best_for_recommended": False,
    # Pricing
    "pricing_file_exists": False,
    "pricing_json_parse": False,
    "pricing_required_fields": False,
    "pricing_numeric_fields": False,
    "pricing_cost_plus_matches": False,
    "pricing_market_anchor_matches": False,
    "pricing_value_fees_match": False,
    "pricing_value_fee_target_matches": False,
    # Proposal
    "proposal_file_exists": False,
    "proposal_yaml_parse": False,
    "proposal_required_keys": False,
    "proposal_subject_includes_company": False,
    "proposal_word_count_leq_400": False,
    "proposal_no_hourly_language": False,
    "proposal_investment_has_options": False,
    "proposal_investment_has_recommended": False,
    # Onboarding
    "onboarding_file_exists": False,
    "onboarding_yaml_parse": False,
    "onboarding_required_keys": False,
    "onboarding_deposit_30_present": False,
    # Contract
    "contract_file_exists": False,
    "contract_yaml_parse": False,
    "contract_required_keys": False,
    "contract_ip_transfer_final_payment": False,
    # Financial
    "financial_file_exists": False,
    "financial_json_parse": False,
    "financial_required_keys": False,
    "financial_values_match": False,
    "financial_by_client_sums_to_gross": False,
    "financial_months_runway_matches": False,
    # Acquisition
    "acquisition_file_exists": False,
    "acquisition_has_headings": False,
    "acquisition_min_300_words": False,
}

# Early detection of no-op
output_exists = os.path.isdir(output_dir)
output_nonempty = False
if output_exists:
    try:
        for root, dirs, files in os.walk(output_dir):
            if files:
                output_nonempty = True
                break
    except Exception:
        output_nonempty = False

# 1) Positioning
pos_path = os.path.join(output_dir, "positioning.yaml")
if os.path.isfile(pos_path):
    checks["positioning_file_exists"] = True
    pos_yaml, ok = read_yaml(pos_path)
    if ok and isinstance(pos_yaml, dict):
        checks["positioning_yaml_parse"] = True
        required_pos_keys = ["what_i_do", "who_i_serve", "problem_i_solve", "why_me", "proof", "anti_clients"]
        if all(k in pos_yaml for k in required_pos_keys):
            checks["positioning_required_keys"] = True
        who_i_serve = pos_yaml.get("who_i_serve")
        if isinstance(who_i_serve, str) and who_i_serve.strip():
            niche_rows, ok_csv = read_csv_dicts(os.path.join(input_dir, "niche_options.csv"))
            if ok_csv and isinstance(niche_rows, list) and niche_rows:
                _, scores = find_niche_column_and_scores(niche_rows)
                niches = set(scores.keys())
                if who_i_serve in niches:
                    checks["positioning_niche_present_in_csv"] = True
                    total = scores.get(who_i_serve, 0.0)
                    if total >= 20:
                        checks["positioning_niche_meets_threshold"] = True

# 2) Packages
pkg_path = os.path.join(output_dir, "packages.yaml")
if os.path.isfile(pkg_path):
    checks["packages_file_exists"] = True
    pkg_yaml, ok = read_yaml(pkg_path)
    if ok and isinstance(pkg_yaml, dict):
        checks["packages_yaml_parse"] = True
        tiers = ["starter", "professional", "premium"]
        if all(t in pkg_yaml for t in tiers):
            checks["packages_required_tiers"] = True
            required_fields = ["name", "price", "includes", "timeline", "best_for"]
            fields_ok = True
            prices_numeric = True
            try:
                starter_price = pkg_yaml["starter"].get("price")
                prof_price = pkg_yaml["professional"].get("price")
                prem_price = pkg_yaml["premium"].get("price")
            except Exception:
                starter_price = prof_price = prem_price = None
            for t in tiers:
                item = pkg_yaml.get(t)
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                if not all(k in item for k in required_fields):
                    fields_ok = False
                    break
                if not isinstance(item.get("includes"), list):
                    fields_ok = False
                    break
                price_val = item.get("price")
                if not isinstance(price_val, (int, float)):
                    prices_numeric = False
            if fields_ok:
                checks["packages_required_fields_each_tier"] = True
            if prices_numeric:
                checks["packages_prices_numeric"] = True
                try:
                    sp = float(starter_price)
                    pp = float(prof_price)
                    prp = float(prem_price)
                    ratio_prof = (pp >= 2 * sp) and (pp <= 3 * sp)
                    ratio_prem = (prp >= 2 * pp) and (prp <= 3 * pp)
                    if ratio_prof and ratio_prem:
                        checks["packages_price_ratios_valid"] = True
                except Exception:
                    pass
            # professional best_for contains RECOMMENDED
            prof_best = ""
            try:
                prof_best = pkg_yaml["professional"].get("best_for", "")
            except Exception:
                prof_best = ""
            if isinstance(prof_best, str) and re.search(r"recommended", prof_best, flags=re.IGNORECASE):
                checks["packages_prof_best_for_recommended"] = True

# 3) Pricing
pricing_path = os.path.join(output_dir, "pricing.json")
if os.path.isfile(pricing_path):
    checks["pricing_file_exists"] = True
    pricing, ok = read_json(pricing_path)
    if ok and isinstance(pricing, dict):
        checks["pricing_json_parse"] = True
        req_fields = [
            "cost_plus_min_hourly",
            "market_anchor_hourly_min",
            "market_anchor_hourly_max",
            "value_fee_10pct",
            "value_fee_15pct",
            "value_fee_20pct",
            "value_fee_target",
        ]
        if all(k in pricing for k in req_fields):
            checks["pricing_required_fields"] = True
            numeric_ok = all(isinstance(pricing.get(k), (int, float)) for k in req_fields)
            if numeric_ok:
                checks["pricing_numeric_fields"] = True
                # cost-plus recompute
                prof_yaml, ok_prof = read_yaml(os.path.join(input_dir, "freelancer_profile.yaml"))
                if ok_prof and isinstance(prof_yaml, dict) and "annual_income_target" in prof_yaml:
                    annual_income_target = parse_amount(prof_yaml.get("annual_income_target"))
                    if annual_income_target is not None:
                        calc_cost_plus = round_int_half_up((annual_income_target / 1200.0) * 1.30)
                        if int(pricing.get("cost_plus_min_hourly")) == calc_cost_plus:
                            checks["pricing_cost_plus_matches"] = True
                # market anchor
                mr_data, ok_mr = read_json(os.path.join(input_dir, "market_rate_data.json"))
                if ok_mr and isinstance(mr_data, dict):
                    salary = parse_amount(mr_data.get("employed_equivalent_salary"))
                    mult_range = mr_data.get("multiplier_range")
                    if salary is not None and isinstance(mult_range, (list, tuple)) and len(mult_range) == 2:
                        try:
                            mmin = float(mult_range[0])
                            mmax = float(mult_range[1])
                            hourly_min = round_int_half_up((salary / 1200.0) * mmin)
                            hourly_max = round_int_half_up((salary / 1200.0) * mmax)
                            if int(pricing.get("market_anchor_hourly_min")) == hourly_min and int(pricing.get("market_anchor_hourly_max")) == hourly_max:
                                checks["pricing_market_anchor_matches"] = True
                        except Exception:
                            pass
                # value-based fees
                prospect, ok_pb = read_json(os.path.join(input_dir, "prospect_brief.json"))
                if ok_pb and isinstance(prospect, dict):
                    egfy = parse_amount(prospect.get("expected_gain_first_year"))
                    if egfy is None:
                        # Try nested or alternative key
                        for key in ["expected_gain", "expected_gain_year1", "expected_first_year_gain"]:
                            egfy = parse_amount(prospect.get(key))
                            if egfy is not None:
                                break
                    if egfy is not None:
                        v10 = round_int_half_up(egfy * 0.10)
                        v15 = round_int_half_up(egfy * 0.15)
                        v20 = round_int_half_up(egfy * 0.20)
                        if int(pricing.get("value_fee_10pct")) == v10 and int(pricing.get("value_fee_15pct")) == v15 and int(pricing.get("value_fee_20pct")) == v20:
                            checks["pricing_value_fees_match"] = True
                        if int(pricing.get("value_fee_target")) == v15:
                            checks["pricing_value_fee_target_matches"] = True

# 4) Proposal
proposal_path = os.path.join(output_dir, "proposal.yaml")
if os.path.isfile(proposal_path):
    checks["proposal_file_exists"] = True
    proposal_yaml, ok = read_yaml(proposal_path)
    if ok and isinstance(proposal_yaml, dict):
        checks["proposal_yaml_parse"] = True
        subject = proposal_yaml.get("subject")
        sections = proposal_yaml.get("sections")
        required_section_keys = ["hook", "understanding", "approach", "proof", "investment", "next_step"]
        base_keys_ok = subject is not None and isinstance(sections, dict) and all(k in sections for k in required_section_keys)
        if base_keys_ok:
            checks["proposal_required_keys"] = True
            # Subject includes company
            prospect, ok_pb = read_json(os.path.join(input_dir, "prospect_brief.json"))
            company = get_company_from_prospect(prospect) if ok_pb else None
            if isinstance(subject, str) and company and (company in subject):
                checks["proposal_subject_includes_company"] = True
            # Body text and word count
            body_text = ""
            for k in required_section_keys:
                body_text += "\n" + get_section_text(sections.get(k))
            wc = word_count(body_text.strip())
            if wc <= 400:
                checks["proposal_word_count_leq_400"] = True
            # No hourly language
            subject_text = subject if isinstance(subject, str) else ""
            all_text = (subject_text + "\n" + body_text).lower()
            if not any(s in all_text for s in ["/hour", "per hour", "hourly"]):
                checks["proposal_no_hourly_language"] = True
            # Investment options and recommended
            has_opts, has_rec = detect_investment_options(sections.get("investment"))
            if has_opts:
                checks["proposal_investment_has_options"] = True
            if has_rec:
                checks["proposal_investment_has_recommended"] = True

# 5) Onboarding checklist
onboard_path = os.path.join(output_dir, "onboarding_checklist.yaml")
if os.path.isfile(onboard_path):
    checks["onboarding_file_exists"] = True
    onboard_yaml, ok = read_yaml(onboard_path)
    if ok and isinstance(onboard_yaml, dict):
        checks["onboarding_yaml_parse"] = True
        if all(k in onboard_yaml for k in ["before_kickoff", "kickoff_meeting", "after_kickoff"]):
            checks["onboarding_required_keys"] = True
            before = onboard_yaml.get("before_kickoff")
            # before_kickoff can be list or dict with checklist
            found_deposit = False
            if isinstance(before, list):
                items = [normalize_text(x) for x in before]
            elif isinstance(before, dict):
                items = [normalize_text(v) for v in before.values()]
            else:
                items = [normalize_text(before)]
            for it in items:
                itl = it.lower()
                if "deposit received" in itl and "30%" in itl:
                    found_deposit = True
                    break
            if found_deposit:
                checks["onboarding_deposit_30_present"] = True

# 6) Contract clauses
contract_path = os.path.join(output_dir, "contract_clauses.yaml")
if os.path.isfile(contract_path):
    checks["contract_file_exists"] = True
    contract_yaml, ok = read_yaml(contract_path)
    if ok and isinstance(contract_yaml, dict):
        checks["contract_yaml_parse"] = True
        req_keys = ["scope", "payment", "timeline", "ip_and_ownership", "termination", "liability", "other"]
        if all(k in contract_yaml for k in req_keys):
            checks["contract_required_keys"] = True
            ip_val = contract_yaml.get("ip_and_ownership")
            ip_text = normalize_text(ip_val).lower()
            if ("transfer" in ip_text) and ("final payment" in ip_text):
                checks["contract_ip_transfer_final_payment"] = True

# 7) Financial dashboard
fin_path = os.path.join(output_dir, "financial_dashboard.json")
if os.path.isfile(fin_path):
    checks["financial_file_exists"] = True
    fin_data, ok = read_json(fin_path)
    if ok and isinstance(fin_data, dict):
        checks["financial_json_parse"] = True
        # Basic required keys presence
        try:
            rev = fin_data.get("revenue", {})
            exp = fin_data.get("expenses", {})
            prof = fin_data.get("profit", {})
            hlth = fin_data.get("health", {})
            has_keys = (
                isinstance(rev, dict) and "gross_income" in rev and "by_client" in rev and
                isinstance(exp, dict) and "total_expenses" in exp and
                isinstance(prof, dict) and "tax_reserve" in prof and "net_take_home" in prof and
                isinstance(hlth, dict) and "months_runway" in hlth
            )
        except Exception:
            has_keys = False
        if has_keys:
            checks["financial_required_keys"] = True
            # Read input CSV for recomputation
            tx_rows, ok_tx = read_csv_dicts(os.path.join(input_dir, "last_3_months_transactions.csv"))
            prof_yaml, ok_prof = read_yaml(os.path.join(input_dir, "freelancer_profile.yaml"))
            if ok_tx and isinstance(tx_rows, list) and tx_rows and ok_prof and isinstance(prof_yaml, dict):
                # Compute sums
                gross_income = 0.0
                total_expenses = 0.0
                revenue_rows = []
                for r in tx_rows:
                    t = (r.get("type") or r.get("Type") or "").strip().lower()
                    amt = parse_amount(r.get("amount") if "amount" in r else r.get("Amount"))
                    if amt is None:
                        continue
                    if t == "revenue":
                        gross_income += amt
                        revenue_rows.append(r)
                    elif t == "expense":
                        total_expenses += amt
                tax_reserve = round_int_half_up(gross_income * 0.30)
                net_take_home = gross_income - total_expenses - tax_reserve
                # months_runway
                cash_reserve = parse_amount(prof_yaml.get("cash_reserve"))
                avg_monthly_expenses = total_expenses / 3.0 if total_expenses is not None else 0.0
                months_runway_calc = 0.0
                if cash_reserve is not None and avg_monthly_expenses:
                    months_runway_calc = float(Decimal(str(cash_reserve / avg_monthly_expenses)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                # Compare with output
                try:
                    out_gross = parse_amount(rev.get("gross_income"))
                    out_exp_total = parse_amount(exp.get("total_expenses"))
                    out_tax = parse_amount(prof.get("tax_reserve"))
                    out_net = parse_amount(prof.get("net_take_home"))
                    out_mr = float(re.sub(r"[^\d\.]", "", str(hlth.get("months_runway")))) if isinstance(hlth.get("months_runway"), str) else float(hlth.get("months_runway"))
                except Exception:
                    out_gross = out_exp_total = out_tax = out_net = out_mr = None
                if (out_gross is not None and abs(out_gross - gross_income) < 0.5 and
                    out_exp_total is not None and abs(out_exp_total - total_expenses) < 0.5 and
                    out_tax is not None and abs(out_tax - tax_reserve) < 0.5 and
                    out_net is not None and abs(out_net - net_take_home) < 0.5):
                    checks["financial_values_match"] = True
                # by_client sums to gross
                by_client = rev.get("by_client")
                if isinstance(by_client, list):
                    try:
                        sum_by_client_amt = 0.0
                        for item in by_client:
                            if isinstance(item, dict):
                                amt = parse_amount(item.get("amount"))
                                if amt is not None:
                                    sum_by_client_amt += amt
                        if abs(sum_by_client_amt - gross_income) < 0.5:
                            checks["financial_by_client_sums_to_gross"] = True
                    except Exception:
                        pass
                # months runway compare
                try:
                    if out_mr is not None and abs(out_mr - months_runway_calc) < 0.05:
                        checks["financial_months_runway_matches"] = True
                except Exception:
                    pass

# 8) Acquisition plan
acq_path = os.path.join(output_dir, "acquisition_plan.md")
if os.path.isfile(acq_path):
    checks["acquisition_file_exists"] = True
    acq_text, ok = read_text(acq_path)
    if ok and isinstance(acq_text, str):
        # Headings: Week 1-2, Week 3-4, Week 5-8 (allow hyphen or en dash)
        h12 = re.search(r"week\s*1\s*[-–]\s*2", acq_text, flags=re.IGNORECASE)
        h34 = re.search(r"week\s*3\s*[-–]\s*4", acq_text, flags=re.IGNORECASE)
        h58 = re.search(r"week\s*5\s*[-–]\s*8", acq_text, flags=re.IGNORECASE)
        if h12 and h34 and h58:
            checks["acquisition_has_headings"] = True
        if word_count(acq_text) >= 300:
            checks["acquisition_min_300_words"] = True

# Compute reward
# Count total checks
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)

# Default reward as fraction
reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

# Enforce no-op baseline: if output missing or empty, reward = 0.0
if (not output_exists) or (not output_nonempty):
    reward = 0.0

# Clamp to [0,1]
if reward < 0:
    reward = 0.0
elif reward > 1:
    reward = 1.0

# Final output
result = {"reward": float(reward)}
result.update(checks)
print(json.dumps(result))