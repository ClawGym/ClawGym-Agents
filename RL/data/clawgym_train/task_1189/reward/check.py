import csv
import json
import os
import re
import sys
from datetime import datetime

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def load_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            sniffer_sample = f.read(4096)
            f.seek(0)
            # Try to handle common delimiters
            dialect = None
            try:
                dialect = csv.Sniffer().sniff(sniffer_sample, delimiters=",;\t")
            except Exception:
                pass
            if dialect:
                reader = csv.DictReader(f, dialect=dialect)
            else:
                reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys to lowercase for easier matching
                norm = {}
                for k, v in row.items():
                    lk = k.strip().lower() if isinstance(k, str) else k
                    norm[lk] = v
                rows.append(norm)
            return rows
    except Exception:
        return []

def to_number(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    # Remove $ and commas and whitespace
    s = s.replace("$", "").replace(",", "").strip()
    # Parentheses denote negative
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    # Allow trailing/leading +/- signs
    try:
        num = float(s)
        return -num if neg else num
    except Exception:
        # Try to find a numeric substring
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            try:
                num = float(m.group(0))
                return -num if neg else num
            except Exception:
                return None
        return None

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def normalize_name(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())

def find_account_amount(csv_path, target_account_names):
    rows = load_csv_rows(csv_path)
    if not rows:
        return None
    # Candidate columns for account and amount
    account_cols = ["account", "account name", "name", "qbo account", "account_title", "accounttitle"]
    amount_cols = ["balance", "amount", "ending balance", "total", "value"]
    # Build normalized list of target names
    targets = [normalize_name(t) for t in target_account_names]
    for row in rows:
        # Find account field
        acct_val = None
        for ac in account_cols:
            if ac in row and row[ac] not in (None, ""):
                acct_val = row[ac]
                break
        if acct_val is None:
            continue
        acct_norm = normalize_name(acct_val)
        if acct_norm in targets:
            # Find first available numeric column
            for amc in amount_cols:
                if amc in row:
                    n = to_number(row[amc])
                    if n is not None:
                        return n
    return None

def get_tb_atb_balance(tb_path, atb_path, account_targets):
    tb_val = find_account_amount(tb_path, account_targets)
    atb_val = find_account_amount(atb_path, account_targets)
    return tb_val, atb_val

def aje_parse_effects(csv_path):
    """Parse AJE csv and compute net effect per account: sum(debits) - sum(credits)."""
    rows = load_csv_rows(csv_path)
    effects = {}
    if not rows:
        return effects
    # Candidate columns
    account_cols = ["account", "account name", "name", "account_title", "accounttitle"]
    debit_cols = ["debit", "dr"]
    credit_cols = ["credit", "cr"]
    amount_cols = ["amount", "value"]
    type_cols = ["type", "dc", "debit/credit", "entry type"]
    for row in rows:
        # Get account name
        acct = None
        for ac in account_cols:
            if ac in row and row[ac]:
                acct = row[ac]
                break
        if not acct:
            continue
        acct_norm = normalize_name(acct)
        debit = None
        credit = None
        # Prefer explicit debit/credit columns
        for dc in debit_cols:
            if dc in row and row[dc] not in (None, ""):
                debit = to_number(row[dc])
                break
        for cc in credit_cols:
            if cc in row and row[cc] not in (None, ""):
                credit = to_number(row[cc])
                break
        # If only amount and type provided
        if debit is None and credit is None:
            amt = None
            for amc in amount_cols:
                if amc in row and row[amc] not in (None, ""):
                    amt = to_number(row[amc])
                    break
            if amt is not None:
                # Determine side from type columns; default positive as debit
                side = None
                for tc in type_cols:
                    if tc in row and row[tc]:
                        t = normalize_name(row[tc])
                        if "credit" in t or t == "cr":
                            side = "credit"
                        elif "debit" in t or t == "dr":
                            side = "debit"
                        break
                if side == "credit":
                    credit = abs(amt)
                else:
                    debit = abs(amt)
        d = debit if isinstance(debit, (int, float)) else 0.0
        c = credit if isinstance(credit, (int, float)) else 0.0
        net = d - c
        effects[acct_norm] = effects.get(acct_norm, 0.0) + net
    return effects

def aje_has_entry(csv_path, account_predicate, expected_debit=None, expected_credit=None, tol=0.01):
    """Check for presence of rows where a specific account has a debit or credit amount."""
    rows = load_csv_rows(csv_path)
    if not rows:
        return False
    # Locate debit and credit columns
    debit_cols = [c for c in rows[0].keys() if c in ("debit", "dr")]
    credit_cols = [c for c in rows[0].keys() if c in ("credit", "cr")]
    amount_cols = [c for c in rows[0].keys() if c in ("amount", "value")]
    type_cols = [c for c in rows[0].keys() if c in ("type", "dc", "debit/credit", "entry type")]
    account_cols = [c for c in rows[0].keys() if c in ("account", "account name", "name", "account_title", "accounttitle")]
    for row in rows:
        acct_val = None
        for ac in account_cols:
            if ac in row and row[ac]:
                acct_val = row[ac]
                break
        if acct_val is None:
            continue
        if not account_predicate(normalize_name(acct_val)):
            continue
        # Determine debit/credit amounts for this row
        deb = None
        cred = None
        for dc in debit_cols:
            if dc in row and row[dc]:
                deb = to_number(row[dc])
                break
        for cc in credit_cols:
            if cc in row and row[cc]:
                cred = to_number(row[cc])
                break
        if deb is None and cred is None:
            # Try amount + type
            amt = None
            for amc in amount_cols:
                if amc in row and row[amc]:
                    amt = to_number(row[amc])
                    break
            side = None
            for tc in type_cols:
                if tc in row and row[tc]:
                    t = normalize_name(row[tc])
                    if "credit" in t or t == "cr":
                        side = "credit"
                    elif "debit" in t or t == "dr":
                        side = "debit"
                    break
            if amt is not None:
                if side == "credit":
                    cred = abs(amt)
                else:
                    deb = abs(amt)
        # Compare to expected
        ok = True
        if expected_debit is not None:
            ok = ok and deb is not None and approx_equal(deb, expected_debit, tol)
        if expected_credit is not None:
            ok = ok and cred is not None and approx_equal(cred, expected_credit, tol)
        if ok:
            return True
    return False

def schc_find_amount(csv_path, identifiers, expected_amount):
    rows = load_csv_rows(csv_path)
    if not rows:
        return False
    # Potential amount columns
    amount_cols = ["amount", "value", "total", "balance"]
    for row in rows:
        # Build a searchable string of the row labels/fields
        hay = " ".join([str(v) for k, v in row.items() if v is not None]).lower()
        if all(idf.lower() in hay for idf in identifiers):
            # Find an amount
            for amc in amount_cols:
                if amc in row:
                    val = to_number(row[amc])
                    if val is not None and approx_equal(val, expected_amount, 0.01):
                        return True
            # Fallback: try any numeric in row equals expected
            for v in row.values():
                num = to_number(v)
                if num is not None and approx_equal(num, expected_amount, 0.01):
                    return True
    return False

def fixed_assets_has_roof(csv_path):
    rows = load_csv_rows(csv_path)
    if not rows:
        return False
    # Identify columns
    date_cols = ["date", "placed in service", "placed_in_service", "pis", "in service date", "placed-in-service", "placed"]
    desc_cols = ["description", "asset", "asset name", "asset_name", "item", "detail"]
    cost_cols = ["cost", "basis", "amount", "value", "purchase cost"]
    sec179_cols = ["section 179", "sec179", "179", "section179", "sec 179"]
    for row in rows:
        # Check description contains 'roof'
        desc = None
        for dc in desc_cols:
            if dc in row and row[dc]:
                desc = str(row[dc])
                break
        if not desc or "roof" not in desc.lower():
            continue
        # Check date is 2025-06-10
        date_ok = False
        for dcol in date_cols:
            if dcol in row and row[dcol]:
                val = str(row[dcol]).strip()
                if "2025-06-10" in val:
                    date_ok = True
                    break
        if not date_ok:
            continue
        # Check cost is 3200
        cost_ok = False
        for cc in cost_cols:
            if cc in row and row[cc]:
                num = to_number(row[cc])
                if num is not None and approx_equal(num, 3200.0, 0.01):
                    cost_ok = True
                    break
        if not cost_ok:
            continue
        # Check section 179 column exists for the row (any non-empty string acceptable)
        has_179_col = any(col in row for col in sec179_cols)
        if not has_179_col:
            continue
        return True
    return False

def crypto_check(csv_path):
    rows = load_csv_rows(csv_path)
    if not rows:
        return {"sale1": False, "sale2": False, "summary": False}
    # Identify columns
    date_cols = ["date"]
    type_cols = ["type", "action"]
    units_cols = ["units", "qty", "quantity", "amount"]
    proceeds_cols = ["proceeds", "sale proceeds", "gross proceeds"]
    cost_cols = ["cost basis", "basis", "cost", "cost_basis"]
    gain_cols = ["gain/loss", "gain", "pnl", "profit"]
    term_cols = ["term", "holding period", "gain type"]
    # Helpers to get field
    def get_val(row, candidates):
        for c in candidates:
            if c in row and row[c] not in (None, ""):
                return row[c]
        return None
    # Normalize rows
    sale1_ok = False
    sale2_ok = False
    # Track computed total short-term gain from per-transaction rows
    total_st = 0.0
    st_any = False
    for row in rows:
        date_str = str(get_val(row, date_cols) or "").strip()
        rtype = str(get_val(row, type_cols) or "").strip().lower()
        proceeds = to_number(get_val(row, proceeds_cols))
        cost = to_number(get_val(row, cost_cols))
        gain = to_number(get_val(row, gain_cols))
        term = str(get_val(row, term_cols) or "").strip().lower()
        if term:
            if "short" in term:
                if gain is not None:
                    total_st += gain
                    st_any = True
        # Identify sales
        is_sale = ("sale" in rtype) or ("sell" in rtype) or (gain is not None and proceeds is not None and cost is not None)
        if not is_sale:
            continue
        # Check 2025-09-15 sale
        if "2025-09-15" in date_str:
            if proceeds is not None and cost is not None and gain is not None and term:
                if approx_equal(proceeds, 17750.0) and approx_equal(cost, 12000.0) and approx_equal(gain, 5750.0) and ("short" in term):
                    sale1_ok = True
        # Check 2025-11-30 sale
        if "2025-11-30" in date_str:
            if proceeds is not None and cost is not None and gain is not None and term:
                if approx_equal(proceeds, 23750.0) and approx_equal(cost, 12000.0) and approx_equal(gain, 11750.0) and ("short" in term):
                    sale2_ok = True
    # Summary check: either an explicit summary row with short=17500, or computed total short-term gains == 17500
    summary_ok = False
    # Try to detect explicit summary row
    for row in rows:
        row_text = " ".join([str(v) for v in row.values() if v is not None]).lower()
        if "total" in row_text and "short" in row_text:
            # Look for any numeric 17500 in row
            for v in row.values():
                num = to_number(v)
                if num is not None and approx_equal(num, 17500.0):
                    summary_ok = True
                    break
        if summary_ok:
            break
    if not summary_ok and st_any and approx_equal(total_st, 17500.0):
        summary_ok = True
    return {"sale1": sale1_ok, "sale2": sale2_ok, "summary": summary_ok}

def contractors_check(csv_path):
    rows = load_csv_rows(csv_path)
    if not rows:
        return {"alice": False, "bob": False, "acme": False}
    name_cols = ["vendor", "name", "contractor", "payee"]
    total_cols = ["total", "amount", "paid", "sum", "value"]
    flag_cols = ["requires_1099", "requires 1099", "1099", "need_1099", "require_1099"]
    status = {"alice": False, "bob": False, "acme": False}
    for row in rows:
        # Get name
        nm = None
        for nc in name_cols:
            if nc in row and row[nc]:
                nm = str(row[nc]).strip()
                break
        if not nm:
            continue
        nm_lower = nm.lower()
        total = to_number(next((row[c] for c in total_cols if c in row), None))
        flag_val = None
        for fc in flag_cols:
            if fc in row:
                flag_val = str(row[fc]).strip().lower()
                break
        def yes_flag(v):
            if v is None:
                return False
            return v in ("yes", "y", "true", "1")
        if "alice" in nm_lower and "va" in nm_lower:
            # Expect NO and amount 450
            ok_amount = total is not None and approx_equal(total, 450.0)
            ok_flag = flag_val is not None and not yes_flag(flag_val)
            status["alice"] = ok_amount and ok_flag
        if "bob" in nm_lower and "designer" in nm_lower:
            ok_amount = total is not None and approx_equal(total, 1200.0)
            ok_flag = flag_val is not None and yes_flag(flag_val)
            status["bob"] = ok_amount and ok_flag
        if "acme" in nm_lower and "contractors" in nm_lower:
            ok_amount = total is not None and approx_equal(total, 7500.0)
            ok_flag = flag_val is not None and yes_flag(flag_val)
            status["acme"] = ok_amount and ok_flag
    return status

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = {}
    # Required output files
    required_files = [
        "workpaper_header.md",
        "TB.csv",
        "AJE.csv",
        "ATB.csv",
        "Sch-C.csv",
        "Fixed-Assets.csv",
        "Crypto.csv",
        "1099.csv",
    ]
    present = {fn: os.path.isfile(os.path.join(output_dir, fn)) for fn in required_files}
    checks["all_required_outputs_present"] = all(present.values())
    # Also track individual presence
    for fn, exists in present.items():
        key = f"present_{fn.replace('.', '_')}"
        checks[key] = exists

    # Header checks
    header_path = os.path.join(output_dir, "workpaper_header.md")
    if present["workpaper_header.md"]:
        header_text = read_text(header_path)
        checks["header_client"] = "Client: Pixel Pioneers Studio LLC" in header_text
        checks["header_ein"] = "EIN: 87-1234567" in header_text
        checks["header_tax_year"] = "Tax Year: 2025" in header_text
        checks["header_preparer_ptin"] = ("Prepared By:" in header_text and "PTIN: P12345678" in header_text)
        checks["header_purpose_schedule_c"] = ("Purpose:" in header_text and ("Schedule C" in header_text or "Schedule C (Form 1040)" in header_text))
    else:
        checks["header_client"] = False
        checks["header_ein"] = False
        checks["header_tax_year"] = False
        checks["header_preparer_ptin"] = False
        checks["header_purpose_schedule_c"] = False

    # AJE checks
    aje_path = os.path.join(output_dir, "AJE.csv")
    if present["AJE.csv"]:
        # Roof reclass: debit Fixed Assets 3200, credit Repairs & Maintenance 3200
        checks["aje_roof_debit_fixed_assets"] = aje_has_entry(
            aje_path,
            account_predicate=lambda n: "fixed asset" in n,
            expected_debit=3200.0,
            expected_credit=None,
        )
        checks["aje_roof_credit_repairs"] = aje_has_entry(
            aje_path,
            account_predicate=lambda n: ("repairs" in n and "maintenance" in n),
            expected_debit=None,
            expected_credit=3200.0,
        )
        # Meals haircut: credit Meals (Business) 1200, debit Meals Disallowed 1200
        checks["aje_meals_credit_meals"] = aje_has_entry(
            aje_path,
            account_predicate=lambda n: "meals" in n and "business" in n,
            expected_debit=None,
            expected_credit=1200.0,
        )
        checks["aje_meals_debit_disallowed"] = aje_has_entry(
            aje_path,
            account_predicate=lambda n: "meals" in n and "disallow" in n,
            expected_debit=1200.0,
            expected_credit=None,
        )
    else:
        checks["aje_roof_debit_fixed_assets"] = False
        checks["aje_roof_credit_repairs"] = False
        checks["aje_meals_credit_meals"] = False
        checks["aje_meals_debit_disallowed"] = False

    # ATB checks
    tb_path = os.path.join(output_dir, "TB.csv")
    atb_path = os.path.join(output_dir, "ATB.csv")
    if present["ATB.csv"]:
        # Repairs & Maintenance equals 900
        repairs_atb = find_account_amount(atb_path, ["repairs & maintenance", "repairs and maintenance"])
        checks["atb_repairs_900"] = repairs_atb is not None and approx_equal(repairs_atb, 900.0, 0.01)
        # Meals (Business) equals 1200
        meals_atb = find_account_amount(atb_path, ["meals (business)", "meals - business", "meals business"])
        checks["atb_meals_1200"] = meals_atb is not None and approx_equal(meals_atb, 1200.0, 0.01)
        # Fixed Assets increased by 3200 relative to TB (or equals 3200 if absent in TB)
        tb_fixed, atb_fixed = get_tb_atb_balance(tb_path, atb_path, ["fixed assets", "fixed asset"])
        # If TB missing, treat 0
        base = tb_fixed if tb_fixed is not None else 0.0
        fixed_increase_ok = (atb_fixed is not None) and approx_equal(atb_fixed - base, 3200.0, 0.01)
        checks["atb_fixed_assets_increase_3200"] = fixed_increase_ok
    else:
        checks["atb_repairs_900"] = False
        checks["atb_meals_1200"] = False
        checks["atb_fixed_assets_increase_3200"] = False

    # Schedule C checks
    schc_path = os.path.join(output_dir, "Sch-C.csv")
    if present["Sch-C.csv"]:
        checks["schc_line1_150000"] = schc_find_amount(schc_path, ["line 1", "gross receipts"], 150000.0)
        checks["schc_line2_2000"] = schc_find_amount(schc_path, ["line 2", "returns"], 2000.0)
        checks["schc_line4_40000"] = schc_find_amount(schc_path, ["line 4", "cogs"], 40000.0) or schc_find_amount(schc_path, ["line 4", "cost of goods"], 40000.0)
        checks["schc_line8_3000"] = schc_find_amount(schc_path, ["line 8", "advertising"], 3000.0)
        checks["schc_line11_5800"] = schc_find_amount(schc_path, ["line 11", "contract labor"], 5800.0)
        checks["schc_line17_2400"] = schc_find_amount(schc_path, ["line 17", "legal"], 2400.0) or schc_find_amount(schc_path, ["line 17", "professional"], 2400.0)
        checks["schc_line20b_12000"] = schc_find_amount(schc_path, ["line 20b", "rent"], 12000.0)
        checks["schc_line21_900"] = schc_find_amount(schc_path, ["line 21", "repairs"], 900.0)
        checks["schc_line24a_2200"] = schc_find_amount(schc_path, ["line 24a", "travel"], 2200.0)
        checks["schc_line24b_1200"] = schc_find_amount(schc_path, ["line 24b", "meals"], 1200.0)
        checks["schc_line25_1800"] = schc_find_amount(schc_path, ["line 25", "utilities"], 1800.0)
    else:
        checks["schc_line1_150000"] = False
        checks["schc_line2_2000"] = False
        checks["schc_line4_40000"] = False
        checks["schc_line8_3000"] = False
        checks["schc_line11_5800"] = False
        checks["schc_line17_2400"] = False
        checks["schc_line20b_12000"] = False
        checks["schc_line21_900"] = False
        checks["schc_line24a_2200"] = False
        checks["schc_line24b_1200"] = False
        checks["schc_line25_1800"] = False

    # Fixed assets file checks
    fa_path = os.path.join(output_dir, "Fixed-Assets.csv")
    if present["Fixed-Assets.csv"]:
        checks["fixed_assets_roof_entry"] = fixed_assets_has_roof(fa_path)
    else:
        checks["fixed_assets_roof_entry"] = False

    # Crypto checks
    crypto_path = os.path.join(output_dir, "Crypto.csv")
    if present["Crypto.csv"]:
        cr = crypto_check(crypto_path)
        checks["crypto_sale1_correct"] = cr["sale1"]
        checks["crypto_sale2_correct"] = cr["sale2"]
        checks["crypto_summary_short_term_17500"] = cr["summary"]
    else:
        checks["crypto_sale1_correct"] = False
        checks["crypto_sale2_correct"] = False
        checks["crypto_summary_short_term_17500"] = False

    # 1099 checks
    f1099_path = os.path.join(output_dir, "1099.csv")
    if present["1099.csv"]:
        cstat = contractors_check(f1099_path)
        checks["1099_alice_no"] = cstat["alice"]
        checks["1099_bob_yes"] = cstat["bob"]
        checks["1099_acme_yes"] = cstat["acme"]
    else:
        checks["1099_alice_no"] = False
        checks["1099_bob_yes"] = False
        checks["1099_acme_yes"] = False

    # Compute reward
    # Gate: if any required output is missing, reward must be 0.0
    # Define content checks (exclude presence-only and the all_required flag)
    presence_keys = [f"present_{fn.replace('.', '_')}" for fn in required_files]
    content_keys = [k for k in checks.keys() if k not in presence_keys and k != "all_required_outputs_present"]
    if not checks["all_required_outputs_present"]:
        reward = 0.0
    else:
        passed = sum(1 for k in content_keys if checks.get(k, False))
        total = len(content_keys)
        reward = (passed / total) if total > 0 else 0.0

    # Ensure reward bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    # Merge checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()