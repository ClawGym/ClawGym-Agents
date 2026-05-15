import json
import os
import sys
import csv
import math
import re

def parse_simple_yaml(path):
    data = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                # Handle simple "key: value" pairs; ignore nested structures
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip()
                    val = val.strip()
                    # Remove inline comments after value
                    if '#' in val:
                        val = val.split('#', 1)[0].strip()
                    # Strip quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    # Try to cast to float or int
                    v = val
                    if v.lower() in ('true', 'false'):
                        data[key] = (v.lower() == 'true')
                    else:
                        try:
                            if '.' in v or 'e' in v.lower():
                                data[key] = float(v)
                            else:
                                data[key] = int(v)
                        except ValueError:
                            data[key] = val
    except Exception:
        pass
    return data

def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None

def is_truthy(x):
    s = str(x).strip().lower()
    return s in ('true', '1', 'yes', 'y', 't')

def detect_arm(rows):
    # Detect presence of ARM in input CSV
    for row in rows:
        # explicit flag
        if 'is_arm' in row and is_truthy(row['is_arm']):
            return True
        # type fields
        for key in ('loan_type', 'product_type', 'type'):
            if key in row and isinstance(row[key], str) and ('arm' in row[key].lower()):
                return True
        # arm_* columns present with any non-empty value
        for k in row.keys():
            if 'arm' in k.lower():
                # If any field with 'arm' exists, assume ARM present
                return True
    return False

def amortization_payment(L, r, n):
    # r monthly rate; if r==0, straight-line
    if r == 0:
        return L / n
    return L * r / (1 - (1 + r) ** (-n))

def remaining_balance(L, r, n, k, P):
    # After k payments (k <= n)
    if k <= 0:
        return L
    if r == 0:
        return max(0.0, L - P * k)
    return L * (1 + r) ** k - P * (((1 + r) ** k - 1) / r)

def read_csv_dict(path):
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        pass
    return rows

def read_output_comparison(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            lines = list(reader)
        if not lines:
            return None, []
        header = lines[0]
        data_rows = []
        for r in lines[1:]:
            if not r or all([str(x).strip()=='' for x in r]):
                continue
            data_rows.append(r)
        return header, data_rows
    except Exception:
        return None, []

def parse_output_row(row, header):
    # Return dict mapping output columns to values
    result = {}
    for i, col in enumerate(header):
        if i < len(row):
            result[col] = row[i]
        else:
            result[col] = ''
    return result

def last_nonempty_line(text):
    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else ''

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_comparison_csv": False,
        "comparison_header_ok": False,
        "comparison_contains_A": False,
        "comparison_contains_B": False,
        "monthly_PI_values_ok": False,
        "monthly_PITI_values_ok": False,
        "total_interest_5y_values_ok": False,
        "upfront_cost_values_ok": False,
        "has_summary_json": False,
        "summary_structure_ok": False,
        "has_report_md": False,
        "report_has_sections": False,
        "report_mentions_arm_rate_risk_if_arm_present": False,
        "report_mentions_loan_estimates": False,
    }

    # Load inputs
    loan_csv_path = os.path.join(input_dir, "loan_options.csv")
    assumptions_path = os.path.join(input_dir, "assumptions.yaml")
    loan_rows = read_csv_dict(loan_csv_path)
    assumptions = parse_simple_yaml(assumptions_path)

    # Compute escrow monthly from assumptions
    escrow_keys_present = all(k in assumptions for k in ("property_tax_annual", "homeowners_insurance_annual", "hoa_monthly"))
    escrow_monthly = None
    if escrow_keys_present:
        try:
            property_tax_annual = float(assumptions["property_tax_annual"])
            homeowners_insurance_annual = float(assumptions["homeowners_insurance_annual"])
            hoa_monthly = float(assumptions["hoa_monthly"])
            escrow_monthly = (property_tax_annual + homeowners_insurance_annual) / 12.0 + hoa_monthly
        except Exception:
            escrow_monthly = None

    # Detect ARM presence in input
    arm_present = detect_arm(loan_rows)

    # Prepare input products by product_id
    # Expect product_id A and B
    products_by_id = {}
    for row in loan_rows:
        pid = row.get("product_id", "").strip()
        if pid:
            products_by_id[pid] = row

    # Read outputs
    comparison_path = os.path.join(output_dir, "comparison.csv")
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "report.md")

    # Check comparison.csv existence and header
    if os.path.isfile(comparison_path):
        checks["has_comparison_csv"] = True
        header, data_rows = read_output_comparison(comparison_path)
        expected_header = ["product_id", "monthly_PI", "monthly_PITI", "total_interest_5y", "upfront_cost"]
        if header == expected_header:
            checks["comparison_header_ok"] = True

        # Build mapping for output rows
        out_rows_by_pid = {}
        for r in data_rows:
            out_obj = parse_output_row(r, header if header else [])
            pid = (out_obj.get("product_id") or "").strip()
            if pid:
                out_rows_by_pid[pid] = out_obj

        # Check presence of A and B
        if "A" in out_rows_by_pid:
            checks["comparison_contains_A"] = True
        if "B" in out_rows_by_pid:
            checks["comparison_contains_B"] = True

        # If we have rows for A and B, validate numbers
        # Tolerances
        tol_pi = 5.0
        tol_piti = 3.0
        tol_interest_5y = 500.0
        tol_upfront = 1.0

        all_pi_ok = True
        all_piti_ok = True
        all_interest_ok = True
        all_upfront_ok = True

        for pid in ("A", "B"):
            if pid not in out_rows_by_pid or pid not in products_by_id:
                all_pi_ok = False
                all_piti_ok = False
                all_interest_ok = False
                all_upfront_ok = False
                continue

            in_row = products_by_id[pid]
            out_row = out_rows_by_pid[pid]

            # Required input fields
            try:
                L = float(in_row["loan_amount"])
                term_months = int(in_row["term_months"])
                rate_annual_percent = float(in_row["interest_rate_annual_percent"])
                points_percent = float(in_row.get("points_percent", "0"))
                upfront_fees_usd = float(in_row.get("upfront_fees_usd", "0"))
            except Exception:
                all_pi_ok = False
                all_piti_ok = False
                all_interest_ok = False
                all_upfront_ok = False
                continue

            # Interpret monthly rate in two possible ways; pick variant closest to reported monthly_PI
            reported_pi = safe_float(out_row.get("monthly_PI"))
            if reported_pi is None:
                all_pi_ok = False
                # If monthly_PI missing, PITI and interest checks will also fail
                all_piti_ok = False
                all_interest_ok = False
                # Upfront cost can still be checked
            # Two interpretations
            r_month_percent = (rate_annual_percent / 100.0) / 12.0
            r_month_nominal = rate_annual_percent / 12.0

            P1 = amortization_payment(L, r_month_percent, term_months)
            P2 = amortization_payment(L, r_month_nominal, term_months)

            # Decide which interpretation to use for subsequent checks
            chosen_r = None
            chosen_P = None
            if reported_pi is not None:
                diff1 = abs(reported_pi - P1)
                diff2 = abs(reported_pi - P2)
                if diff1 <= diff2:
                    chosen_r = r_month_percent
                    chosen_P = P1
                else:
                    chosen_r = r_month_nominal
                    chosen_P = P2

                if abs(reported_pi - chosen_P) <= tol_pi:
                    pass
                else:
                    all_pi_ok = False

            # total_interest_5y
            reported_interest_5y = safe_float(out_row.get("total_interest_5y"))
            if (reported_interest_5y is None) or (chosen_r is None) or (chosen_P is None):
                all_interest_ok = False
            else:
                k = 60
                balance_k = remaining_balance(L, chosen_r, term_months, k, chosen_P)
                expected_interest_5y = (chosen_P * k) + balance_k - L
                if abs(reported_interest_5y - expected_interest_5y) <= tol_interest_5y:
                    pass
                else:
                    all_interest_ok = False

            # monthly_PITI: compare to (reported monthly_PI + escrow), within ±$3
            reported_piti = safe_float(out_row.get("monthly_PITI"))
            if (reported_piti is None) or (reported_pi is None) or (escrow_monthly is None):
                all_piti_ok = False
            else:
                expected_piti_from_reported = reported_pi + escrow_monthly
                if abs(reported_piti - expected_piti_from_reported) <= tol_piti:
                    pass
                else:
                    all_piti_ok = False

            # upfront_cost: support two interpretations for points (percent vs fraction)
            reported_upfront = safe_float(out_row.get("upfront_cost"))
            if reported_upfront is None:
                all_upfront_ok = False
            else:
                upfront1 = (points_percent / 100.0) * L + upfront_fees_usd
                upfront2 = points_percent * L + upfront_fees_usd
                if (abs(reported_upfront - upfront1) <= tol_upfront) or (abs(reported_upfront - upfront2) <= tol_upfront):
                    pass
                else:
                    all_upfront_ok = False

        if all_pi_ok:
            checks["monthly_PI_values_ok"] = True
        if all_piti_ok:
            checks["monthly_PITI_values_ok"] = True
        if all_interest_ok:
            checks["total_interest_5y_values_ok"] = True
        if all_upfront_ok:
            checks["upfront_cost_values_ok"] = True

    # Check summary.json
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            rec = summary.get("recommendation")
            if isinstance(rec, dict):
                pid = rec.get("product_id")
                reason = rec.get("reason")
                if pid in ("A", "B") and isinstance(reason, str) and reason.strip() != "":
                    checks["summary_structure_ok"] = True
        except Exception:
            pass

    # Check report.md
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report_text = f.read()
            # Sections presence (case-insensitive)
            has_assumptions = re.search(r'assumptions', report_text, re.IGNORECASE) is not None
            has_methodology = re.search(r'methodology', report_text, re.IGNORECASE) is not None
            has_risks = re.search(r'risks', report_text, re.IGNORECASE) is not None
            has_recommendation = re.search(r'recommendation', report_text, re.IGNORECASE) is not None
            if has_assumptions and has_methodology and has_risks and has_recommendation:
                checks["report_has_sections"] = True

            # ARM rate risk mention if ARM present
            arm_risk_ok = False
            if arm_present:
                # Check any line containing both "arm" and "rate", or phrase "rate risk"
                for line in report_text.splitlines():
                    l = line.lower()
                    if ('arm' in l and 'rate' in l) or ('rate risk' in l):
                        arm_risk_ok = True
                        break
                # Must explicitly discuss ARM rate risk and caps; our check focuses on "ARM" and "rate" mention
                checks["report_mentions_arm_rate_risk_if_arm_present"] = arm_risk_ok
            else:
                # If no ARM present, mark true only if report exists (to avoid vacuous pass without output)
                checks["report_mentions_arm_rate_risk_if_arm_present"] = True

            # Loan Estimates guidance
            if re.search(r'loan\s+estimate', report_text, re.IGNORECASE):
                checks["report_mentions_loan_estimates"] = True
        except Exception:
            pass

    # Compute reward: proportion of checks passed, but ensure baseline no-op yields 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Clamp
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()