import json
import os
import sys
import csv
from datetime import datetime, timedelta
import re
from collections import defaultdict, OrderedDict

def parse_float(x, percent=False):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "":
        return None
    # Remove currency symbols and commas
    s2 = s.replace("$", "").replace(",", "").strip()
    if s2.endswith("%"):
        try:
            val = float(s2[:-1].strip())
            return val / 100.0 if percent else val
        except:
            pass
    try:
        return float(s2)
    except:
        return None

def read_csv_dicts(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        header = reader.fieldnames if hasattr(reader, "fieldnames") else None
    return header, rows

def write_debug(path, content):
    # Helper for potential debugging (not used to score)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except:
        pass

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def compute_days_past_due(as_of_date, due_date):
    return (as_of_date - due_date).days

def bucket_for_dpd(days_past_due):
    if days_past_due <= 0:
        return "Current"
    elif 1 <= days_past_due <= 30:
        return "1-30"
    elif 31 <= days_past_due <= 60:
        return "31-60"
    elif 61 <= days_past_due <= 90:
        return "61-90"
    elif 91 <= days_past_due <= 120:
        return "91-120"
    else:
        return "120+"

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except:
        return False

def extract_first_float_in_line(line):
    # Finds first number including decimals and optional %; returns float (percentage stripped of %)
    m = re.search(r"([-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(\s*%)?", line)
    if not m:
        return None, False
    num_str = m.group(1).replace(",", "")
    perc = bool(m.group(2) and "%" in m.group(2))
    try:
        val = float(num_str)
        return (val, perc)
    except:
        return None, False

def find_line_with_keyword(lines, keyword):
    for line in lines:
        if keyword.lower() in line.lower():
            return line
    return None

def amounts_in_text_include(text, amount_value):
    # Check if the text contains a number equal to amount_value within 0.01
    # Extract all numeric tokens; if any match within tolerance, pass.
    nums = re.findall(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", text)
    for token in nums:
        try:
            v = float(token.replace(",", ""))
            if approx_equal(v, amount_value, tol=0.01):
                return True
        except:
            continue
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # Initialize all checks to False (artifact-dependent)
    check_keys = [
        # Aging report
        "aging_exists", "aging_header_ok", "aging_all_customers_present", "aging_values_match", "aging_total_row_ok",
        # Priority list
        "priority_exists", "priority_headers_ok", "priority_all_customers_present", "priority_sorted_desc", "priority_top_risk_position_ok",
        # Email drafts
        "drafts_exists", "drafts_valid_json", "drafts_count_match", "drafts_fields_ok", "drafts_tiers_ok", "drafts_subject_body_include_values", "drafts_exclude_current",
        # KPI dashboard
        "kpi_exists", "kpi_has_dso_line", "kpi_dso_value_ok", "kpi_has_cei_line", "kpi_cei_value_ok", "kpi_has_bpds0_and_bucket_text",
        # Bad debt reserve schedule + journal
        "reserve_exists", "reserve_header_ok", "reserve_rows_complete", "reserve_amounts_ok", "reserve_total_ok", "journal_exists", "journal_lines_ok",
        # Follow-up schedule
        "followup_exists", "followup_headers_ok", "followup_rows_cover_inputs", "followup_dates_ok", "followup_broken_has_escalate_note"
    ]
    for k in check_keys:
        checks[k] = False

    # Load inputs
    try:
        with open(os.path.join(input_dir, "as_of.json"), "r", encoding="utf-8") as f:
            as_of = json.load(f)
        as_of_date = parse_date(as_of["as_of_date"])
    except Exception:
        as_of_date = None

    try:
        inv_header, invoices = read_csv_dicts(os.path.join(input_dir, "invoices.csv"))
    except Exception:
        inv_header, invoices = None, []

    try:
        cs_header, credit_sales_rows = read_csv_dicts(os.path.join(input_dir, "credit_sales.csv"))
    except Exception:
        cs_header, credit_sales_rows = None, []

    try:
        with open(os.path.join(input_dir, "promises.json"), "r", encoding="utf-8") as f:
            promises = json.load(f)
            if not isinstance(promises, list):
                promises = []
    except Exception:
        promises = []

    try:
        with open(os.path.join(input_dir, "reserve_config.json"), "r", encoding="utf-8") as f:
            reserve_cfg = json.load(f)
    except Exception:
        reserve_cfg = {}

    try:
        with open(os.path.join(input_dir, "beginning_ar.json"), "r", encoding="utf-8") as f:
            beginning_ar = json.load(f)
    except Exception:
        beginning_ar = {}

    # Precompute invoice enrichments if possible
    enriched_invoices = []
    if as_of_date is not None and invoices:
        for row in invoices:
            try:
                due = parse_date(row["due_date"])
            except Exception:
                continue
            dpd = compute_days_past_due(as_of_date, due)
            bucket = bucket_for_dpd(dpd)
            amt_due = parse_float(row.get("amount_due"))
            if amt_due is None:
                amt_due = 0.0
            enriched_invoices.append({
                "invoice_id": row.get("invoice_id"),
                "customer": row.get("customer"),
                "invoice_date": row.get("invoice_date"),
                "due_date": row.get("due_date"),
                "amount": parse_float(row.get("amount")),
                "amount_due": amt_due,
                "status": row.get("status"),
                "dpd": dpd,
                "bucket": bucket
            })

    # Compute per-customer bucket sums and totals
    bucket_names = ["Current", "1-30", "31-60", "61-90", "91-120", "120+"]
    customer_buckets = {}
    customer_totals = {}
    all_customers = set()
    if enriched_invoices:
        for inv in enriched_invoices:
            cust = inv["customer"]
            if cust is None:
                continue
            all_customers.add(cust)
            if cust not in customer_buckets:
                customer_buckets[cust] = {b: 0.0 for b in bucket_names}
            customer_buckets[cust][inv["bucket"]] += inv["amount_due"]
        for cust in all_customers:
            customer_totals[cust] = sum(customer_buckets[cust].values())

    # Compute high-risk per spec: balance > $5k and 60+ days past due OR any invoice 120+ days
    high_risk_customers = set()
    if customer_buckets:
        for cust in all_customers:
            total_bal = customer_totals.get(cust, 0.0)
            bal_61_90 = customer_buckets[cust].get("61-90", 0.0)
            bal_91_120 = customer_buckets[cust].get("91-120", 0.0)
            bal_120p = customer_buckets[cust].get("120+", 0.0)
            sixty_plus = (bal_61_90 + bal_91_120 + bal_120p) > 0.0
            any_120 = bal_120p > 0.0
            if any_120 or (total_bal > 5000.0 and sixty_plus):
                high_risk_customers.add(cust)

    # 1) Validate ar_aging_report.csv
    aging_path = os.path.join(output_dir, "reports", "ar_aging_report.csv")
    if os.path.isfile(aging_path):
        checks["aging_exists"] = True
        try:
            header, rows = read_csv_dicts(aging_path)
        except Exception:
            header, rows = None, []
        expected_header = ["Customer", "Current", "1-30", "31-60", "61-90", "91-120", "120+", "Total"]
        if header == expected_header:
            checks["aging_header_ok"] = True

        # Build map from customer to row values
        def parse_row_amount(v):
            val = parse_float(v)
            return 0.0 if val is None else val

        row_map = {}
        total_row = None
        for r in rows:
            cust = r.get("Customer")
            if cust == "Total":
                total_row = r
                continue
            if cust is not None and cust != "":
                row_map[cust] = {
                    "Current": parse_row_amount(r.get("Current")),
                    "1-30": parse_row_amount(r.get("1-30")),
                    "31-60": parse_row_amount(r.get("31-60")),
                    "61-90": parse_row_amount(r.get("61-90")),
                    "91-120": parse_row_amount(r.get("91-120")),
                    "120+": parse_row_amount(r.get("120+")),
                    "Total": parse_row_amount(r.get("Total")),
                }

        # Check all customers present
        if all_customers and all(c in row_map for c in all_customers):
            checks["aging_all_customers_present"] = True

        # Check per-customer values
        values_ok = True
        if all_customers:
            for cust in all_customers:
                if cust not in row_map:
                    values_ok = False
                    break
                out_vals = row_map[cust]
                for b in bucket_names:
                    expected_val = customer_buckets.get(cust, {}).get(b, 0.0)
                    if not approx_equal(out_vals.get(b, 0.0), expected_val, tol=0.01):
                        values_ok = False
                        break
                if not approx_equal(out_vals.get("Total", 0.0), customer_totals.get(cust, 0.0), tol=0.01):
                    values_ok = False
                if not values_ok:
                    break
        if values_ok and all_customers:
            checks["aging_values_match"] = True

        # Check Total row sums
        if total_row is not None and row_map:
            sums = {b: 0.0 for b in bucket_names}
            sum_total = 0.0
            for cust in row_map:
                for b in bucket_names:
                    sums[b] += row_map[cust][b]
                sum_total += row_map[cust]["Total"]
            total_ok = True
            for b in bucket_names:
                if not approx_equal(parse_row_amount(total_row.get(b)), sums[b], tol=0.01):
                    total_ok = False
                    break
            if not approx_equal(parse_row_amount(total_row.get("Total")), sum_total, tol=0.01):
                total_ok = False
            if total_ok:
                checks["aging_total_row_ok"] = True

    # 2) Validate priority_list.csv
    priority_path = os.path.join(output_dir, "reports", "priority_list.csv")
    if os.path.isfile(priority_path):
        checks["priority_exists"] = True
        try:
            p_header, p_rows = read_csv_dicts(priority_path)
        except Exception:
            p_header, p_rows = None, []
        # Header includes Customer and PriorityScore
        if p_header and ("Customer" in p_header) and ("PriorityScore" in p_header):
            checks["priority_headers_ok"] = True

        # All customers present
        out_customers = [r.get("Customer") for r in p_rows if r.get("Customer")]
        if all_customers and set(out_customers) >= set(all_customers):
            checks["priority_all_customers_present"] = True

        # Sorted descending by PriorityScore
        try:
            scores = [parse_float(r.get("PriorityScore")) if r.get("PriorityScore") is not None else None for r in p_rows]
            if all(s is not None for s in scores):
                sorted_ok = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
                if sorted_ok:
                    checks["priority_sorted_desc"] = True
        except Exception:
            pass

        # Top risk position check
        # If >=3 high risk customers, top 3 must be all in high risk set.
        # If <3, then first N rows must be exactly the high risk set (order may vary).
        if p_rows:
            top3 = [r.get("Customer") for r in p_rows[:3] if r.get("Customer")]
            if len(high_risk_customers) >= 3:
                if set(top3).issubset(high_risk_customers) and len(top3) == 3:
                    checks["priority_top_risk_position_ok"] = True
            else:
                n = len(high_risk_customers)
                firstn = [r.get("Customer") for r in p_rows[:n] if r.get("Customer")]
                if set(firstn) == set(high_risk_customers):
                    checks["priority_top_risk_position_ok"] = True

    # 3) Validate email drafts
    drafts_path = os.path.join(output_dir, "drafts", "email_drafts.json")
    drafts_data = None
    if os.path.isfile(drafts_path):
        checks["drafts_exists"] = True
        try:
            with open(drafts_path, "r", encoding="utf-8") as f:
                drafts_data = json.load(f)
            if isinstance(drafts_data, list):
                checks["drafts_valid_json"] = True
        except Exception:
            drafts_data = None

    overdue_invoices = []
    overdue_map = {}  # invoice_id -> invoice data
    if enriched_invoices:
        for inv in enriched_invoices:
            if inv["dpd"] > 0 and inv["amount_due"] > 0.0:
                overdue_invoices.append(inv)
                if inv.get("invoice_id"):
                    overdue_map[inv["invoice_id"]] = inv

    if drafts_data is not None and isinstance(drafts_data, list):
        # One draft per overdue invoice (exclude Current)
        draft_ids = [d.get("invoice_id") for d in drafts_data if isinstance(d, dict)]
        # Ensure drafts only for overdue invoice ids
        drafts_only_overdue = all((i_id in overdue_map) for i_id in draft_ids if i_id is not None)
        # Ensure coverage and no duplicates/extra
        coverage_ok = set(draft_ids) == set([inv.get("invoice_id") for inv in overdue_invoices if inv.get("invoice_id")])
        if coverage_ok:
            checks["drafts_count_match"] = True
        # Exclude current invoices
        if drafts_only_overdue:
            checks["drafts_exclude_current"] = True

        # Fields verification and tier mapping etc.
        fields_ok = True
        tiers_ok = True
        sb_include_ok = True
        for d in drafts_data:
            if not isinstance(d, dict):
                fields_ok = False
                tiers_ok = False
                sb_include_ok = False
                break
            required_fields = ["customer", "invoice_id", "tier", "subject", "body", "amount", "due_date", "days_past_due"]
            for rf in required_fields:
                if rf not in d:
                    fields_ok = False
            inv_id = d.get("invoice_id")
            if inv_id not in overdue_map:
                # If the draft references non-overdue or missing invoice, then fail relevant checks
                tiers_ok = False
                fields_ok = False
                sb_include_ok = False
                continue
            inv = overdue_map[inv_id]
            # Tier mapping
            dpd = inv["dpd"]
            expected_bucket = bucket_for_dpd(dpd)
            expected_tier = {"1-30":1, "31-60":2, "61-90":3, "91-120":4, "120+":5}.get(expected_bucket, None)
            try:
                tier_val = int(d.get("tier"))
            except Exception:
                tier_val = None
            if expected_tier is None or tier_val != expected_tier:
                tiers_ok = False
            # Amount matches amount_due
            amt_field = parse_float(d.get("amount"))
            if amt_field is None or not approx_equal(amt_field, inv["amount_due"], tol=0.01):
                fields_ok = False
            # days_past_due matches
            try:
                dpd_field = int(d.get("days_past_due"))
            except Exception:
                dpd_field = None
            if dpd_field != dpd:
                fields_ok = False
            # due_date matches
            if str(d.get("due_date")) != str(inv["due_date"]):
                fields_ok = False
            # subject/body include invoice_id and amount value and payment link placeholder
            subj = str(d.get("subject", ""))
            body = str(d.get("body", ""))

            if (inv_id is None) or (inv_id not in subj) or (inv_id not in body):
                sb_include_ok = False
            # check amount presence by numeric detection
            if not amounts_in_text_include(subj, inv["amount_due"]) or not amounts_in_text_include(body, inv["amount_due"]):
                sb_include_ok = False
            # payment link placeholder presence in subject or body (prefer body)
            if "{{PAYMENT_LINK}}" not in subj and "{{PAYMENT_LINK}}" not in body:
                sb_include_ok = False

        if fields_ok:
            checks["drafts_fields_ok"] = True
        if tiers_ok:
            checks["drafts_tiers_ok"] = True
        if sb_include_ok:
            checks["drafts_subject_body_include_values"] = True

    # 4) KPI dashboard
    kpi_path = os.path.join(output_dir, "reports", "kpi_dashboard.md")
    if os.path.isfile(kpi_path):
        checks["kpi_exists"] = True
        try:
            with open(kpi_path, "r", encoding="utf-8") as f:
                kpi_text = f.read()
        except Exception:
            kpi_text = ""

        kpi_lines = kpi_text.splitlines()

        # Compute expected DSO and CEI
        ending_ar = 0.0
        if enriched_invoices:
            for inv in enriched_invoices:
                if inv["amount_due"] is not None and inv["amount_due"] > 0:
                    ending_ar += inv["amount_due"]
        total_credit_sales = 0.0
        for r in credit_sales_rows:
            total_credit_sales += parse_float(r.get("amount")) or 0.0

        expected_dso = None
        if total_credit_sales > 0:
            expected_dso = (ending_ar / total_credit_sales) * 90.0

        beg_ar = beginning_ar.get("beginning_ar")
        cur_end_ar = beginning_ar.get("current_ending_ar")
        beg_ar_val = float(beg_ar) if isinstance(beg_ar, (int, float)) else parse_float(beg_ar)
        cur_end_ar_val = float(cur_end_ar) if isinstance(cur_end_ar, (int, float)) else parse_float(cur_end_ar)
        expected_cei = None
        if beg_ar_val is not None and cur_end_ar_val is not None and (beg_ar_val + total_credit_sales - cur_end_ar_val) != 0:
            numerator = (beg_ar_val + total_credit_sales - ending_ar)
            denominator = (beg_ar_val + total_credit_sales - cur_end_ar_val)
            expected_cei = (numerator / denominator) * 100.0

        # Find DSO line
        dso_line = find_line_with_keyword(kpi_lines, "DSO")
        if dso_line is not None:
            checks["kpi_has_dso_line"] = True
            val, is_percent = extract_first_float_in_line(dso_line)
            if val is not None and expected_dso is not None and not is_percent:
                if abs(val - expected_dso) <= 0.2:
                    checks["kpi_dso_value_ok"] = True

        # Find CEI line
        cei_line = find_line_with_keyword(kpi_lines, "CEI")
        if cei_line is not None:
            checks["kpi_has_cei_line"] = True
            val, is_percent = extract_first_float_in_line(cei_line)
            if val is not None and expected_cei is not None:
                # The extracted number may be a percent (e.g., 88). expected_cei is already percent
                if abs(val - expected_cei) <= 0.5:
                    checks["kpi_cei_value_ok"] = True

        # Must include "BPDSO" and "% AR by bucket"
        if ("BPDSO" in kpi_text) and ("% AR by bucket" in kpi_text):
            checks["kpi_has_bpds0_and_bucket_text"] = True

    # 5) Bad debt reserve schedule and journal
    reserve_path = os.path.join(output_dir, "reports", "bad_debt_schedule.csv")
    journal_path = os.path.join(output_dir, "reports", "bad_debt_journal.md")
    if os.path.isfile(reserve_path):
        checks["reserve_exists"] = True
        try:
            r_header, r_rows = read_csv_dicts(reserve_path)
        except Exception:
            r_header, r_rows = None, []
        expected_res_header = ["Bucket", "Balance", "ReservePercent", "ReserveAmount"]
        if r_header == expected_res_header:
            checks["reserve_header_ok"] = True

        # Build expected balances and percents
        expected_balances = {b: 0.0 for b in bucket_names}
        if enriched_invoices:
            for inv in enriched_invoices:
                expected_balances[inv["bucket"]] += inv["amount_due"]

        # Config percents as decimals
        cfg_map = {
            "Current": reserve_cfg.get("current"),
            "1-30": reserve_cfg.get("d1_30"),
            "31-60": reserve_cfg.get("d31_60"),
            "61-90": reserve_cfg.get("d61_90"),
            "91-120": reserve_cfg.get("d91_120"),
            "120+": reserve_cfg.get("d120_plus"),
        }
        # Convert to float
        for k in list(cfg_map.keys()):
            cfg_map[k] = parse_float(cfg_map[k])

        # Extract rows into dict
        res_map = {}
        total_row = None
        for r in r_rows:
            b = r.get("Bucket")
            if b == "Total":
                total_row = r
                continue
            if b in bucket_names:
                bal = parse_float(r.get("Balance")) or 0.0
                rp = r.get("ReservePercent")
                rp_val = parse_float(rp)
                # If the string includes %, parse_float returns percent as value, not decimal unless we allow percent flag.
                # Our parse_float treats % as numeric (e.g., "6%" -> 6.0), so convert to decimal if it looks like a percent.
                if isinstance(rp, str) and "%" in rp:
                    rp_val = (parse_float(rp, percent=True) or 0.0)
                res_amt = parse_float(r.get("ReserveAmount")) or 0.0
                res_map[b] = {"Balance": bal, "ReservePercent": rp_val, "ReserveAmount": res_amt}

        # Rows complete
        if set(res_map.keys()) == set(bucket_names):
            checks["reserve_rows_complete"] = True

        # Amounts and percents ok
        amounts_ok = True
        for b in bucket_names:
            if b not in res_map:
                amounts_ok = False
                break
            out_bal = res_map[b]["Balance"]
            out_rp = res_map[b]["ReservePercent"]
            out_amt = res_map[b]["ReserveAmount"]
            exp_bal = expected_balances.get(b, 0.0)
            exp_rp = cfg_map.get(b, None)
            if not approx_equal(out_bal, exp_bal, tol=0.01):
                amounts_ok = False
                break
            if exp_rp is None:
                amounts_ok = False
                break
            # Compare reserve percent with tolerance 1e-4
            try:
                if abs(float(out_rp) - float(exp_rp)) > 1e-4:
                    amounts_ok = False
                    break
            except:
                amounts_ok = False
                break
            # Compare reserve amount
            exp_amt = exp_bal * exp_rp
            if not approx_equal(out_amt, exp_amt, tol=0.01):
                amounts_ok = False
                break
        if amounts_ok and res_map:
            checks["reserve_amounts_ok"] = True

        # Total row ok
        if total_row is not None and res_map:
            total_bal_calc = sum(res_map[b]["Balance"] for b in bucket_names)
            total_amt_calc = sum(res_map[b]["ReserveAmount"] for b in bucket_names)
            out_total_bal = parse_float(total_row.get("Balance")) or 0.0
            out_total_amt = parse_float(total_row.get("ReserveAmount")) or 0.0
            total_ok = approx_equal(out_total_bal, total_bal_calc, tol=0.01) and approx_equal(out_total_amt, total_amt_calc, tol=0.01)
            if total_ok:
                checks["reserve_total_ok"] = True

    if os.path.isfile(journal_path):
        checks["journal_exists"] = True
        try:
            with open(journal_path, "r", encoding="utf-8") as f:
                journal_text = f.read()
        except Exception:
            journal_text = ""
        # Check both lines and include the total reserve amount
        # Compute expected total reserve
        total_reserve_expected = None
        if enriched_invoices and reserve_cfg:
            cfg_map = {
                "Current": parse_float(reserve_cfg.get("current")),
                "1-30": parse_float(reserve_cfg.get("d1_30")),
                "31-60": parse_float(reserve_cfg.get("d31_60")),
                "61-90": parse_float(reserve_cfg.get("d61_90")),
                "91-120": parse_float(reserve_cfg.get("d91_120")),
                "120+": parse_float(reserve_cfg.get("d120_plus")),
            }
            balances = {b: 0.0 for b in bucket_names}
            for inv in enriched_invoices:
                balances[inv["bucket"]] += inv["amount_due"]
            total_reserve_expected = 0.0
            for b in bucket_names:
                rp = cfg_map.get(b) or 0.0
                total_reserve_expected += balances[b] * rp

        lines = journal_text.splitlines()
        dr_line = None
        cr_line = None
        for ln in lines:
            if ln.strip().startswith("DR Bad Debt Expense"):
                dr_line = ln
            if ln.strip().startswith("CR Allowance for Doubtful Accounts"):
                cr_line = ln
        if dr_line and cr_line and total_reserve_expected is not None:
            # Check the numeric appears in both lines
            amt_str = f"{total_reserve_expected:.2f}"
            present = (amt_str in dr_line) and (amt_str in cr_line)
            if present:
                checks["journal_lines_ok"] = True

    # 6) Follow-up schedule
    follow_path = os.path.join(output_dir, "reports", "follow_up_schedule.csv")
    if os.path.isfile(follow_path):
        checks["followup_exists"] = True
        try:
            f_header, f_rows = read_csv_dicts(follow_path)
        except Exception:
            f_header, f_rows = None, []
        required_cols = ["customer", "invoice_id", "amount", "promise_date", "follow_up_date", "status", "notes"]
        if f_header and all(col in f_header for col in required_cols):
            checks["followup_headers_ok"] = True

        # Build index for matching: (customer, invoice_id, promise_date) -> row
        f_index = {}
        for r in f_rows:
            key = (str(r.get("customer")), str(r.get("invoice_id")), str(r.get("promise_date")))
            f_index[key] = r

        # For each promise with status != kept, verify row exists and date is -3 days
        cover_ok = True
        dates_ok = True
        broken_escalate_ok = True
        for p in promises:
            status = str(p.get("status", "")).lower()
            cust = str(p.get("customer"))
            inv_id = str(p.get("invoice_id"))
            pdate = str(p.get("promise_date"))
            if status != "kept":
                key = (cust, inv_id, pdate)
                if key not in f_index:
                    cover_ok = False
                    continue
                out = f_index[key]
                try:
                    pd = parse_date(pdate)
                    expected_follow = pd - timedelta(days=3)
                    out_follow = str(out.get("follow_up_date"))
                    if out_follow != expected_follow.strftime("%Y-%m-%d"):
                        dates_ok = False
                except Exception:
                    dates_ok = False
                if status == "broken":
                    notes = str(out.get("notes", ""))
                    if "escalate" not in notes.lower():
                        broken_escalate_ok = False

        if cover_ok and promises:
            checks["followup_rows_cover_inputs"] = True
        if dates_ok and promises:
            checks["followup_dates_ok"] = True
        if broken_escalate_ok:
            checks["followup_broken_has_escalate_note"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline guard: if no outputs at all, reward must be 0.0
    # If all main outputs are missing, ensure reward = 0.0
    main_outputs_exist = any([
        checks["aging_exists"],
        checks["priority_exists"],
        checks["drafts_exists"],
        checks["kpi_exists"],
        checks["reserve_exists"] or checks["journal_exists"],
        checks["followup_exists"],
    ])
    if not main_outputs_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()