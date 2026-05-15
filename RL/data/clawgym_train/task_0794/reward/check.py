import csv
import json
import os
import re
import sys
from collections import defaultdict

def parse_float_maybe(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if s == "":
        return None
    # Remove common currency symbols and thousands separators
    s = s.replace(",", "")
    s = s.replace("$", "")
    # Extract first numeric pattern
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def parse_int_maybe(s):
    f = parse_float_maybe(s)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None

def read_csv_safe(path):
    with open(path, "r", encoding="utf-8") as f:
        # Detect if file has BOM or unusual dialect
        content = f.read()
    # Re-open using csv over string lines
    lines = content.splitlines()
    if not lines:
        return []
    reader = csv.DictReader(lines)
    return list(reader), [h for h in reader.fieldnames] if reader.fieldnames else []

def round2(x):
    return round(x + 1e-12, 2)

def safe_lower(s):
    return s.lower() if isinstance(s, str) else s

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_master_csv": False,
        "master_csv_readable": False,
        "master_csv_header_ok": False,
        "master_csv_contains_all_creators": False,
        "orders_count_correct_all": False,
        "actual_revenue_correct_all": False,
        "cac_correct_all": False,
        "renewal_rating_present_all": False,
        "master_csv_top_performer_A": False,
        "master_csv_spam_kol_D": False,
        "renewal_notes_exists": False,
        "renewal_notes_attribution_rule_code": False,
        "renewal_notes_mentions_refunds": False,
        "renewal_notes_mentions_roas": False,
        "renewal_notes_has_all_tiers": False,
        "renewal_notes_spamkol_flagged": False,
    }

    # Expected header exact order
    expected_header = ["Influencer ID","Orders attributed","Actual revenue","CAC","Renewal rating"]

    master_csv_path = os.path.join(output_dir, "master_report.csv")
    notes_path = os.path.join(output_dir, "renewal_notes.md")

    # Load reference inputs
    creators_path = os.path.join(input_dir, "creators.csv")
    orders_path = os.path.join(input_dir, "orders.csv")
    refunds_path = os.path.join(input_dir, "refunds.csv")
    clicks_path = os.path.join(input_dir, "clicks.csv")
    config_path = os.path.join(input_dir, "config.json")

    # Prepare reference data containers
    creators_rows = []
    orders_rows = []
    refunds_rows = []
    clicks_rows = []
    config = {}

    # Load inputs if exist (used only for expected calculations; does not give positive reward alone)
    # Missing inputs will naturally cause downstream checks to fail if outputs rely on them.
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        config = {}

    def get_commission_default_fraction():
        val = config.get("commission_percent_default", 0)
        try:
            return float(val) / 100.0
        except Exception:
            return 0.0

    commission_default = get_commission_default_fraction()

    # Load creators
    creators_header = []
    try:
        creators_rows, creators_header = read_csv_safe(creators_path)
    except Exception:
        creators_rows, creators_header = [], []

    # Load orders
    orders_header = []
    try:
        orders_rows, orders_header = read_csv_safe(orders_path)
    except Exception:
        orders_rows, orders_header = [], []

    # Load refunds
    refunds_header = []
    try:
        refunds_rows, refunds_header = read_csv_safe(refunds_path)
    except Exception:
        refunds_rows, refunds_header = [], []

    # Load clicks
    clicks_header = []
    try:
        clicks_rows, clicks_header = read_csv_safe(clicks_path)
    except Exception:
        clicks_rows, clicks_header = [], []

    # Build mappings from creators
    # Expect columns: influencer_id, discount_code, optional fixed_fee, optional commission override
    influencer_to_codes = defaultdict(set)
    code_to_influencer = {}
    influencer_fixed_fee = defaultdict(float)
    influencer_commission_override = {}  # fraction e.g., 0.12

    # Identify potential column names
    def col_lookup(row, names):
        for n in names:
            if n in row and row[n] not in (None, ""):
                return row[n]
        # case-insensitive fallback
        lower_map = {k.lower(): k for k in row.keys()}
        for n in names:
            if n.lower() in lower_map:
                v = row.get(lower_map[n.lower()])
                if v not in (None, ""):
                    return v
        return None

    for r in creators_rows:
        infl = col_lookup(r, ["influencer_id", "influencer", "creator_id", "creator"])
        code = col_lookup(r, ["discount_code", "code"])
        if infl:
            infl = str(infl).strip()
        if code:
            code = str(code).strip()
        if infl and code:
            influencer_to_codes[infl].add(code)
            code_to_influencer[code] = infl
        # fixed fee
        fee_raw = col_lookup(r, ["fixed_fee", "fixedfee", "fee"])
        fee = parse_float_maybe(fee_raw) if fee_raw is not None else None
        if fee is not None:
            # If multiple rows per influencer, accumulate only once by taking max to avoid double counting
            influencer_fixed_fee[infl] = max(influencer_fixed_fee.get(infl, 0.0), float(fee))
        # commission override percent
        comm_raw = col_lookup(r, ["commission_override_percent", "commission_percent_override", "commission_percent", "commission"])
        comm_frac = None
        if comm_raw is not None:
            val = parse_float_maybe(comm_raw)
            if val is not None:
                comm_frac = float(val) / 100.0
        if comm_frac is not None:
            influencer_commission_override[infl] = comm_frac

    # Prepare list of all influencers to include (from creators.csv)
    influencers_list = list(influencer_to_codes.keys())

    # Build refunds map: order_id -> total refund amount
    refunds_by_order = defaultdict(float)
    for r in refunds_rows:
        oid = col_lookup(r, ["order_id", "id"])
        amt = col_lookup(r, ["refund_amount", "amount"])
        if oid is None:
            continue
        amount = parse_float_maybe(amt) or 0.0
        refunds_by_order[str(oid).strip()] += float(amount)

    # Build orders per influencer
    orders_by_influencer = defaultdict(list)
    for r in orders_rows:
        oid = col_lookup(r, ["order_id", "id"])
        code = col_lookup(r, ["discount_code", "code"])
        gross = col_lookup(r, ["gross_revenue", "revenue", "total"])
        if oid is None or code is None:
            continue
        gross_val = parse_float_maybe(gross) or 0.0
        code_str = str(code).strip()
        if code_str in code_to_influencer:
            infl = code_to_influencer[code_str]
            orders_by_influencer[infl].append({
                "order_id": str(oid).strip(),
                "gross": float(gross_val)
            })

    # Clicks per influencer
    clicks_by_influencer = defaultdict(int)
    for r in clicks_rows:
        infl = col_lookup(r, ["influencer_id", "influencer", "creator_id", "creator"])
        clicks_val = col_lookup(r, ["clicks", "click_count"])
        if infl is None:
            continue
        clicks = parse_int_maybe(clicks_val) or 0
        clicks_by_influencer[str(infl).strip()] += int(clicks)

    # Compute expected metrics per influencer
    expected_orders_count = {}
    expected_actual_revenue = {}
    expected_cac = {}
    expected_creator_cost = {}
    expected_commission_fraction = {}

    for infl in influencers_list:
        # orders
        orders = orders_by_influencer.get(infl, [])
        count = 0
        revenue = 0.0
        for o in orders:
            oid = o["order_id"]
            gross = o["gross"]
            refunds = refunds_by_order.get(oid, 0.0)
            net = gross - refunds
            if net < 0:
                net = 0.0
            # Fully refunded: exclude from order count
            if net > 0.0000001:
                count += 1
                revenue += net
            else:
                # net == 0 -> fully refunded; count excluded; revenue contribution 0
                pass
        expected_orders_count[infl] = count
        expected_actual_revenue[infl] = round2(revenue)
        # commission percent
        comm_frac = influencer_commission_override.get(infl, commission_default)
        expected_commission_fraction[infl] = comm_frac
        # creator cost
        fixed_fee = influencer_fixed_fee.get(infl, 0.0)
        creator_cost = float(fixed_fee) + float(comm_frac) * expected_actual_revenue[infl]
        expected_creator_cost[infl] = round2(creator_cost)
        # CAC
        if count > 0:
            expected_cac[infl] = round2(creator_cost / count)
        else:
            expected_cac[infl] = None  # Accept blank/NA/0

    # Determine top-converting creator using clicks vs orders
    # Use conversion rate = orders / clicks if clicks > 0; otherwise ignore for top-performer selection
    top_creator = None
    top_conv = None
    for infl in influencers_list:
        clicks = clicks_by_influencer.get(infl, 0)
        orders_c = expected_orders_count.get(infl, 0)
        if clicks and clicks > 0:
            conv = orders_c / clicks
            if top_conv is None or conv > top_conv:
                top_conv = conv
                top_creator = infl
    # Fallback if no clicks data present or all zero clicks: choose highest orders, then highest revenue
    if top_creator is None:
        best_orders = -1
        best_rev = -1.0
        for infl in influencers_list:
            oc = expected_orders_count.get(infl, 0)
            rev = expected_actual_revenue.get(infl, 0.0)
            if oc > best_orders or (oc == best_orders and rev > best_rev):
                best_orders = oc
                best_rev = rev
                top_creator = infl

    # Read output master CSV and notes
    master_rows = []
    master_header = []
    if os.path.isfile(master_csv_path):
        checks["has_master_csv"] = True
        try:
            master_rows, master_header = read_csv_safe(master_csv_path)
            checks["master_csv_readable"] = True
            if master_header == expected_header:
                checks["master_csv_header_ok"] = True
        except Exception:
            # Keep default False for readable and header
            pass

    # Map master rows by Influencer ID
    master_by_infl = {}
    if checks["master_csv_readable"]:
        for r in master_rows:
            infl = r.get("Influencer ID")
            if infl is None:
                # Try case-insensitive fallback
                lower_map = {k.lower(): k for k in r.keys()}
                infl = r.get(lower_map.get("influencer id", ""))
            if infl is not None:
                infl = str(infl).strip()
                master_by_infl[infl] = r

    # Validate presence of all creators
    if checks["master_csv_readable"]:
        all_present = True
        for infl in influencers_list:
            if infl not in master_by_infl:
                all_present = False
                break
        checks["master_csv_contains_all_creators"] = all_present

    # Validate counts, revenue, CAC, renewal presence
    counts_ok = True
    revenue_ok = True
    cac_ok = True
    renewal_present_ok = True

    if checks["master_csv_contains_all_creators"]:
        for infl in influencers_list:
            row = master_by_infl.get(infl)
            # Orders attributed
            out_orders_raw = row.get("Orders attributed", "")
            out_orders = parse_int_maybe(out_orders_raw)
            if out_orders is None:
                counts_ok = False
            else:
                if out_orders != expected_orders_count.get(infl, 0):
                    counts_ok = False
            # Actual revenue
            out_rev_raw = row.get("Actual revenue", "")
            out_rev = parse_float_maybe(out_rev_raw)
            if out_rev is None:
                revenue_ok = False
            else:
                # Compare within tolerance 0.01
                exp_rev = expected_actual_revenue.get(infl, 0.0)
                if abs(out_rev - exp_rev) > 0.01:
                    revenue_ok = False
            # CAC
            out_cac_raw = row.get("CAC", "")
            out_cac = parse_float_maybe(out_cac_raw)
            exp_cac = expected_cac.get(infl)
            orders_c = expected_orders_count.get(infl, 0)
            if orders_c > 0:
                if out_cac is None:
                    cac_ok = False
                else:
                    if abs(out_cac - exp_cac) > 0.01:
                        cac_ok = False
            else:
                # Accept blank, NA, N/A, 0, 0.00
                if (str(out_cac_raw).strip().lower() in ("", "na", "n/a")):
                    pass
                else:
                    # If numeric provided, accept 0 or very close to 0
                    if out_cac is None or abs(out_cac) > 0.01:
                        cac_ok = False
            # Renewal rating presence
            rr = row.get("Renewal rating", "")
            if rr is None or str(rr).strip() == "":
                renewal_present_ok = False

    checks["orders_count_correct_all"] = counts_ok and checks["master_csv_contains_all_creators"]
    checks["actual_revenue_correct_all"] = revenue_ok and checks["master_csv_contains_all_creators"]
    checks["cac_correct_all"] = cac_ok and checks["master_csv_contains_all_creators"]
    checks["renewal_rating_present_all"] = renewal_present_ok and checks["master_csv_contains_all_creators"]

    # Top performer A rating
    if checks["master_csv_contains_all_creators"] and top_creator is not None and top_creator in master_by_infl:
        rr = master_by_infl[top_creator].get("Renewal rating", "")
        if isinstance(rr, str) and rr.strip().lower().startswith("a"):
            checks["master_csv_top_performer_A"] = True

    # spam_kol D rating
    spam_in_creators = "spam_kol" in influencers_list
    if checks["master_csv_contains_all_creators"] and spam_in_creators and "spam_kol" in master_by_infl:
        rr = master_by_infl["spam_kol"].get("Renewal rating", "")
        if isinstance(rr, str) and rr.strip().lower().startswith("d"):
            checks["master_csv_spam_kol_D"] = True

    # Renewal notes checks
    if os.path.isfile(notes_path):
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes = f.read()
        except Exception:
            notes = ""
        if notes and len(notes.strip()) > 0:
            checks["renewal_notes_exists"] = True
            low = notes.lower()
            # Attribution rule mention with "code" or "discount code"
            if ("attribution rule" in low) and ("code" in low):
                checks["renewal_notes_attribution_rule_code"] = True
            # refund mention
            if "refund" in low:
                checks["renewal_notes_mentions_refunds"] = True
            # ROAS mention
            if "roas" in low:
                checks["renewal_notes_mentions_roas"] = True
            # Tiered rubric substrings
            tiers_ok = all([
                "a (renew strong" in low,
                "b (renew with caps" in low,
                "c (renegotiate" in low,
                "d (pause" in low
            ])
            if tiers_ok:
                checks["renewal_notes_has_all_tiers"] = True
            # spam_kol + concern keyword
            if "spam_kol" in low and (("fraud" in low) or ("low-quality" in low) or ("investigate" in low)):
                checks["renewal_notes_spamkol_flagged"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Print single JSON line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()