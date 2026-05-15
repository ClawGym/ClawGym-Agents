import csv
import json
import os
import re
import sys
from glob import glob

def read_csv_dicts(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
        for row in reader:
            # Normalize keys by stripping whitespace
            normalized = {}
            for k, v in row.items():
                if k is None:
                    continue
                nk = k.strip()
                nv = v.strip() if isinstance(v, str) else v
                normalized[nk] = nv
            rows.append(normalized)
    return fieldnames, rows

def is_two_decimal_number_string(s):
    if s is None:
        return False
    s = s.strip()
    # Allow non-negative numbers with exactly two decimals
    return re.fullmatch(r"\d+\.\d{2}", s) is not None

def safe_float(s):
    try:
        return float(s)
    except:
        return None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Aging analysis
        "aging_exists": False,
        "aging_columns_ok": False,
        "aging_priority_two_decimals": False,
        "aging_sorted_desc": False,
        "aging_bucket_values_valid": False,
        "aging_action_mapping_ok": False,
        "aging_expected_recovery_ok": False,
        # Letters
        "letters_dir_exists": False,
        "letters_exactly_15_md": False,
        "letters_filenames_pattern_ok": False,
        "letters_minimiranda_all": False,
        "letters_contains_invoice_and_amount_all": False,
        # Payment plans
        "payment_file_single": False,
        "payment_columns_ok": False,
        "payment_four_rows_ok": False,
        "payment_plan_names_ok": False,
        "payment_durations_ok": False,
        "payment_apr_ok": False,
        "payment_decimal_format_ok": False,
        # Statute of limitations
        "statute_exists": False,
        "statute_columns_ok": False,
        "statute_states_subset_ok": False,
        "statute_values_match_ok": False,
        # FDCPA checklist
        "fdcpa_exists": False,
        "fdcpa_nine_items_ok": False,
        # Write-off policy
        "writeoff_exists": False,
        "writeoff_five_criteria_ok": False,
        # Executive summary
        "executive_exists": False,
        "executive_sections_ok": False,
    }

    # 1) aging_analysis.csv checks
    aging_path = os.path.join(output_dir, "aging_analysis.csv")
    required_cols_aging = {
        "account_id",
        "customer_name",
        "amount_due",
        "days_past_due",
        "customer_value_score",
        "payment_history_score",
        "bucket",
        "priority_score",
        "recommended_action",
        "expected_recovery_range",
    }
    bucket_set = {"Current", "31-60", "61-90", "91-120", "120+"}
    bucket_to_action = {
        "Current": "Auto-reminder",
        "31-60": "Phone + email",
        "61-90": "Escalation letter",
        "91-120": "Collection agency",
        "120+": "Legal/write-off review",
    }
    bucket_to_recovery = {
        "Current": "95-98%",
        "31-60": "85-90%",
        "61-90": "70-75%",
        "91-120": "40-50%",
        "120+": "15-25%",
    }
    if os.path.isfile(aging_path):
        checks["aging_exists"] = True
        try:
            fieldnames, rows = read_csv_dicts(aging_path)
            if fieldnames:
                # Normalize header set
                header_set = set([h.strip() for h in fieldnames])
                if required_cols_aging.issubset(header_set):
                    checks["aging_columns_ok"] = True

            if rows:
                # priority two decimals and numeric
                prio_strings_ok = True
                prio_values = []
                buckets_ok = True
                action_map_ok = True
                recovery_map_ok = True

                for r in rows:
                    ps = r.get("priority_score")
                    if not is_two_decimal_number_string(ps):
                        prio_strings_ok = False
                    val = safe_float(ps)
                    if val is None:
                        prio_strings_ok = False
                    else:
                        prio_values.append(val)

                    b = (r.get("bucket") or "").strip()
                    if b not in bucket_set:
                        buckets_ok = False

                    ra = (r.get("recommended_action") or "").strip()
                    expected_ra = bucket_to_action.get(b)
                    if expected_ra is None or ra != expected_ra:
                        action_map_ok = False

                    er = (r.get("expected_recovery_range") or "").strip()
                    expected_er = bucket_to_recovery.get(b)
                    if expected_er is None or er != expected_er:
                        recovery_map_ok = False

                if prio_strings_ok and len(prio_values) == len(rows):
                    checks["aging_priority_two_decimals"] = True

                    # sorted descending check
                    sorted_desc = True
                    for i in range(len(prio_values) - 1):
                        if prio_values[i] < prio_values[i + 1]:
                            sorted_desc = False
                            break
                    if sorted_desc:
                        checks["aging_sorted_desc"] = True

                if buckets_ok:
                    checks["aging_bucket_values_valid"] = True
                if action_map_ok:
                    checks["aging_action_mapping_ok"] = True
                if recovery_map_ok:
                    checks["aging_expected_recovery_ok"] = True
        except Exception:
            pass

    # 2) letters checks
    letters_dir = os.path.join(output_dir, "letters")
    minimiranda_line = "This is an attempt to collect a debt, and any information obtained will be used for that purpose."
    if os.path.isdir(letters_dir):
        checks["letters_dir_exists"] = True
        md_files = [f for f in os.listdir(letters_dir) if f.endswith(".md") and os.path.isfile(os.path.join(letters_dir, f))]
        if len(md_files) == 15:
            checks["letters_exactly_15_md"] = True
        # Filenames pattern
        pattern_ok = True
        minimiranda_all = True
        content_terms_all = True
        pattern = re.compile(r"^.+_stage([1-5])\.md$")
        for fname in md_files:
            if not pattern.match(fname):
                pattern_ok = False
            fpath = os.path.join(letters_dir, fname)
            content = load_text(fpath)
            if minimiranda_line not in content:
                minimiranda_all = False
            # Must contain "Invoice" and "amount" terms somewhere (case-insensitive)
            lc = content.lower()
            if ("invoice" not in lc) or ("amount" not in lc):
                content_terms_all = False
        if pattern_ok and len(md_files) == 15:
            checks["letters_filenames_pattern_ok"] = True
        if minimiranda_all and len(md_files) == 15:
            checks["letters_minimiranda_all"] = True
        if content_terms_all and len(md_files) == 15:
            checks["letters_contains_invoice_and_amount_all"] = True

    # 3) payment plans checks
    payment_glob = os.path.join(output_dir, "payment_plans_*.csv")
    payment_files = glob(payment_glob)
    if len(payment_files) == 1:
        checks["payment_file_single"] = True
        ppath = payment_files[0]
        try:
            fieldnames, rows = read_csv_dicts(ppath)
            needed_cols = {"plan_name", "duration_months", "apr_percent", "monthly_payment", "total_paid"}
            if fieldnames and needed_cols.issubset(set([h.strip() for h in fieldnames])):
                checks["payment_columns_ok"] = True
            # Must have exactly 4 rows
            if len(rows) == 4:
                checks["payment_four_rows_ok"] = True
            # Validate plan names and mappings
            expected_plans = {"Quick": 3, "Standard": 6, "Extended": 12, "Hardship": 18}
            expected_apr = {"Quick": 0, "Standard": 5, "Extended": 8, "Hardship": 0}
            names_ok = True
            durations_ok = True
            apr_ok = True
            decimals_ok = True
            seen_plans = set()
            for r in rows:
                name = (r.get("plan_name") or "").strip()
                seen_plans.add(name)
                # duration
                d = r.get("duration_months")
                # apr
                a = r.get("apr_percent")
                # decimals for payments
                mp = r.get("monthly_payment")
                tp = r.get("total_paid")
                if name not in expected_plans:
                    names_ok = False
                # durations
                try:
                    d_int = int(str(d).strip())
                except:
                    durations_ok = False
                    d_int = None
                if d_int is not None and name in expected_plans and d_int != expected_plans[name]:
                    durations_ok = False
                # apr
                try:
                    a_int = int(str(a).strip())
                except:
                    apr_ok = False
                    a_int = None
                if a_int is not None and name in expected_apr and a_int != expected_apr[name]:
                    apr_ok = False
                # decimal formats
                if not (is_two_decimal_number_string(str(mp).strip()) and is_two_decimal_number_string(str(tp).strip())):
                    decimals_ok = False
            if names_ok and seen_plans == set(expected_plans.keys()):
                checks["payment_plan_names_ok"] = True
            if durations_ok and len(rows) == 4:
                checks["payment_durations_ok"] = True
            if apr_ok and len(rows) == 4:
                checks["payment_apr_ok"] = True
            if decimals_ok and len(rows) == 4:
                checks["payment_decimal_format_ok"] = True
        except Exception:
            pass

    # 4) statute_of_limitations.csv checks
    statute_path = os.path.join(output_dir, "statute_of_limitations.csv")
    allowed_states = {
        "California": (4, 2, 4),
        "New York": (6, 6, 6),
        "Texas": (4, 4, 4),
        "Florida": (5, 4, 4),
        "Illinois": (10, 5, 5),
        "Pennsylvania": (4, 4, 4),
        "Ohio": (8, 6, 6),
        "Georgia": (6, 4, 4),
        "Michigan": (6, 6, 6),
        "North Carolina": (3, 3, 3),
    }
    if os.path.isfile(statute_path):
        checks["statute_exists"] = True
        try:
            fieldnames, rows = read_csv_dicts(statute_path)
            needed_cols = {"state", "written_contract_years", "oral_contract_years", "open_account_years"}
            if fieldnames and needed_cols.issubset(set([h.strip() for h in fieldnames])):
                checks["statute_columns_ok"] = True
            subset_ok = True
            values_ok = True
            for r in rows:
                st = (r.get("state") or "").strip()
                if st not in allowed_states:
                    subset_ok = False
                else:
                    wc = r.get("written_contract_years")
                    oc = r.get("oral_contract_years")
                    oa = r.get("open_account_years")
                    try:
                        wc_i = int(str(wc).strip())
                        oc_i = int(str(oc).strip())
                        oa_i = int(str(oa).strip())
                    except:
                        values_ok = False
                        continue
                    expected_tuple = allowed_states[st]
                    if (wc_i, oc_i, oa_i) != expected_tuple:
                        values_ok = False
            if subset_ok and rows:
                checks["statute_states_subset_ok"] = True
            if values_ok and rows:
                checks["statute_values_match_ok"] = True
        except Exception:
            pass

    # 5) FDCPA checklist
    fdcpa_path = os.path.join(output_dir, "fdcpa_checklist.md")
    if os.path.isfile(fdcpa_path):
        checks["fdcpa_exists"] = True
        content = load_text(fdcpa_path)
        lines = content.splitlines()
        def has_check_line(phrase):
            for ln in lines:
                if re.match(r"^\s*-\s*\[(?: |x|X)\]", ln) and (phrase in ln):
                    return True
            return False
        phrases = [
            "Initial validation notice sent within 5 days of first contact",
            "Debtor's right to dispute within 30 days clearly stated",
            "No contact before 8 AM or after 9 PM local time",
            "No contact at workplace if debtor objects",
            "No threats of actions you can't/won't take",
            "No misrepresentation of amount owed",
            "No harassment, oppression, or abuse",
            "Cease communication upon written request (except legal notices)",
            "Mini-Miranda warning included in all communications",
        ]
        if all(has_check_line(p) for p in phrases):
            checks["fdcpa_nine_items_ok"] = True

    # 6) Write-off policy
    writeoff_path = os.path.join(output_dir, "write_off_policy.md")
    if os.path.isfile(writeoff_path):
        checks["writeoff_exists"] = True
        c = load_text(writeoff_path).lower()
        crit1 = "180+ days past due" in c
        crit2 = ("5+ contacts" in c) or ("minimum 5 contacts" in c)
        crit3 = ("skip tracing" in c) and ("no viable contact" in c)
        crit4 = "below legal action threshold" in c
        crit5 = "cost exceeds expected recovery" in c
        if crit1 and crit2 and crit3 and crit4 and crit5:
            checks["writeoff_five_criteria_ok"] = True

    # 7) Executive summary
    exec_path = os.path.join(output_dir, "executive_summary.md")
    if os.path.isfile(exec_path):
        checks["executive_exists"] = True
        c = load_text(exec_path).lower()
        needed_sections = ["aging summary", "letters generated", "payment plans", "compliance", "next steps"]
        if all(s in c for s in needed_sections):
            checks["executive_sections_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Enforce no-op baseline: if output dir missing or empty and nothing passed, reward stays 0.0
    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()