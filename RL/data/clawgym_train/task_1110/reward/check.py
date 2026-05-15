import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_employees_csv(csv_path):
    count = 0
    states = set()
    if not os.path.isfile(csv_path):
        return count, states
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Determine the likely state column
            state_key = None
            # Pre-scan fieldnames
            if reader.fieldnames:
                lower_map = {k: k for k in reader.fieldnames}
                # Priority list of exact matches (case-insensitive)
                priority = ["state", "work_state", "home_state", "state_code"]
                for p in priority:
                    for k in reader.fieldnames:
                        if k.strip().lower() == p:
                            state_key = k
                            break
                    if state_key:
                        break
                # If still not found, fallback to any column containing 'state' but not 'status'
                if not state_key:
                    for k in reader.fieldnames:
                        kl = k.strip().lower()
                        if "state" in kl and "status" not in kl:
                            state_key = k
                            break
            for row in reader:
                count += 1
                if state_key and row.get(state_key) is not None:
                    code = str(row.get(state_key)).strip()
                    if code:
                        states.add(code.upper())
    except Exception:
        # On parse error, return what we have
        pass
    return count, states

def line_value_by_label(text, label):
    # returns first matching value after "Label:" on its line
    if text is None:
        return None
    pattern = rf'^{re.escape(label)}\s*:\s*(.+)$'
    m = re.search(pattern, text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None

def count_checkboxes(text):
    if text is None:
        return 0
    return len(re.findall(r'^\s*-\s\[\s\]\s', text, flags=re.MULTILINE))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    report_path = os.path.join(output_dir, "audit_report.md")
    summary_path = os.path.join(output_dir, "audit_summary.json")
    checklist_path = os.path.join(output_dir, "compliance_checklist.md")

    period_path = os.path.join(input_dir, "period.txt")
    employees_csv_path = os.path.join(input_dir, "employees.csv")
    company_yaml_path = os.path.join(input_dir, "company.yaml")  # reference only if needed

    # Initialize checks
    checks = {
        # Existence
        "has_report": False,
        "has_summary": False,
        "has_checklist": False,

        # Report structure checks
        "report_has_heading": False,
        "report_has_company_label": False,
        "report_has_period_label": False,
        "report_has_employees_label": False,
        "report_has_states_label": False,
        "report_has_exec_summary_section": False,
        "report_has_findings_section": False,
        "report_has_recommendations_section": False,

        # Report content references
        "report_mentions_irs_20_factor": False,
        "report_mentions_behavioral_control": False,
        "report_mentions_financial_control": False,
        "report_mentions_relationship_type": False,
        "report_mentions_flsa": False,

        # Findings IDs
        "report_has_three_finding_ids": False,

        # Report period matches input
        "report_period_matches_input": False,

        # Report employees count matches CSV
        "report_employees_count_matches": False,

        # State-specific mentions (conditionally required)
        "report_mentions_california_if_CA": False,
        "report_mentions_new_york_if_NY": False,
        "report_mentions_washington_if_WA": False,

        # Checklist checks
        "checklist_has_monthly": False,
        "checklist_has_quarterly": False,
        "checklist_has_annual": False,
        "checklist_has_three_checkboxes": False,

        # Summary checks
        "summary_company_present": False,
        "summary_period_matches": False,
        "summary_employees_count_matches": False,
        "summary_states_match": False,
        "summary_overall_risk_valid": False,
        "summary_issues_found_valid": False,
        "summary_estimated_exposure_valid": False,
        "summary_categories_include_required": False,
    }

    # Input-derived expected values
    period_label = None
    if os.path.isfile(period_path):
        period_text = read_text(period_path)
        if period_text is not None:
            period_label = period_text.strip()

    employees_count, state_codes = parse_employees_csv(employees_csv_path)

    # Existence checks
    if os.path.isfile(report_path):
        checks["has_report"] = True
    if os.path.isfile(summary_path):
        checks["has_summary"] = True
    if os.path.isfile(checklist_path):
        checks["has_checklist"] = True

    # Load outputs if exist
    report_text = read_text(report_path) if checks["has_report"] else None
    summary_obj = read_json(summary_path) if checks["has_summary"] else None
    checklist_text = read_text(checklist_path) if checks["has_checklist"] else None

    # Report structure validations
    if report_text is not None:
        if "PAYROLL COMPLIANCE AUDIT REPORT" in report_text:
            checks["report_has_heading"] = True
        # Labeled fields
        if re.search(r'^Company:\s*', report_text, flags=re.MULTILINE):
            checks["report_has_company_label"] = True
        if re.search(r'^Period:\s*', report_text, flags=re.MULTILINE):
            checks["report_has_period_label"] = True
        if re.search(r'^Employees:\s*', report_text, flags=re.MULTILINE):
            checks["report_has_employees_label"] = True
        if re.search(r'^States:\s*', report_text, flags=re.MULTILINE):
            checks["report_has_states_label"] = True
        # Sections
        if "EXECUTIVE SUMMARY" in report_text:
            checks["report_has_exec_summary_section"] = True
        if "FINDINGS" in report_text:
            checks["report_has_findings_section"] = True
        if "RECOMMENDATIONS" in report_text:
            checks["report_has_recommendations_section"] = True
        # References
        if "IRS 20-factor test" in report_text:
            checks["report_mentions_irs_20_factor"] = True
        if "Behavioral Control" in report_text:
            checks["report_mentions_behavioral_control"] = True
        if "Financial Control" in report_text:
            checks["report_mentions_financial_control"] = True
        if "Relationship Type" in report_text:
            checks["report_mentions_relationship_type"] = True
        if "FLSA" in report_text:
            checks["report_mentions_flsa"] = True
        # Findings IDs
        ids = set(re.findall(r'\[F-\d{3,}\]', report_text))
        if len(ids) >= 3:
            checks["report_has_three_finding_ids"] = True
        # Period matches input (if input period available)
        if period_label is not None:
            period_in_report = line_value_by_label(report_text, "Period")
            if period_in_report is not None and period_in_report == period_label:
                checks["report_period_matches_input"] = True
        # Employees count matches CSV
        emp_in_report = line_value_by_label(report_text, "Employees")
        if emp_in_report is not None:
            m = re.match(r'^\s*(\d+)\b', emp_in_report)
            if m:
                try:
                    val = int(m.group(1))
                    if val == employees_count:
                        checks["report_employees_count_matches"] = True
                except Exception:
                    pass
        # State-specific mentions (conditional)
        # Only require mention if the state code appears in CSV; otherwise pass if report exists.
        if "CA" in state_codes:
            checks["report_mentions_california_if_CA"] = "California" in report_text
        else:
            # Not applicable but tie to output existence to avoid vacuous pass
            checks["report_mentions_california_if_CA"] = True
        if "NY" in state_codes:
            checks["report_mentions_new_york_if_NY"] = "New York" in report_text
        else:
            checks["report_mentions_new_york_if_NY"] = True
        if "WA" in state_codes:
            checks["report_mentions_washington_if_WA"] = "Washington" in report_text
        else:
            checks["report_mentions_washington_if_WA"] = True

    # Checklist validations
    if checklist_text is not None:
        if "Monthly" in checklist_text:
            checks["checklist_has_monthly"] = True
        if "Quarterly" in checklist_text:
            checks["checklist_has_quarterly"] = True
        if "Annual" in checklist_text:
            checks["checklist_has_annual"] = True
        if count_checkboxes(checklist_text) >= 3:
            checks["checklist_has_three_checkboxes"] = True

    # Summary validations
    if summary_obj is not None and isinstance(summary_obj, dict):
        # company present
        if isinstance(summary_obj.get("company"), str) and summary_obj.get("company").strip() != "":
            checks["summary_company_present"] = True
        # period matches
        if period_label is not None and isinstance(summary_obj.get("period"), str) and summary_obj.get("period") == period_label:
            checks["summary_period_matches"] = True
        # employees_count matches
        ec = summary_obj.get("employees_count")
        if isinstance(ec, int) and ec == employees_count:
            checks["summary_employees_count_matches"] = True
        # states match (order-insensitive)
        states_json = summary_obj.get("states")
        if isinstance(states_json, list):
            try:
                json_states_set = set([str(s).strip().upper() for s in states_json if isinstance(s, (str, int))])
                if json_states_set == set([s.upper() for s in state_codes]):
                    checks["summary_states_match"] = True
            except Exception:
                pass
        # overall_risk valid
        if summary_obj.get("overall_risk") in {"Low", "Medium", "High", "Critical"}:
            checks["summary_overall_risk_valid"] = True
        # issues_found valid
        if isinstance(summary_obj.get("issues_found"), int) and summary_obj.get("issues_found") >= 0:
            checks["summary_issues_found_valid"] = True
        # estimated_exposure valid
        est = summary_obj.get("estimated_exposure")
        if isinstance(est, (int, float)) and est >= 0:
            checks["summary_estimated_exposure_valid"] = True
        # categories include required
        cats = summary_obj.get("categories")
        required_cats = {"Worker Classification", "Overtime Compliance", "Tax Withholding", "Compliance Checklist"}
        if isinstance(cats, list):
            catset = set([str(c) for c in cats])
            if required_cats.issubset(catset):
                checks["summary_categories_include_required"] = True

    # Compute reward
    # If any required output file is missing, overall reward must be 0.0
    required_outputs_present = checks["has_report"] and checks["has_summary"] and checks["has_checklist"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_outputs_present:
        reward = 0.0
    else:
        # Average of all checks
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()