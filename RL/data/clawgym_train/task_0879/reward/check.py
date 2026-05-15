import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def within(value, target, tol):
    try:
        v = float(value)
        return (target - tol) <= v <= (target + tol)
    except Exception:
        return False

def between(value, lo, hi):
    try:
        v = float(value)
        return lo <= v <= hi
    except Exception:
        return False

def is_separator_row(line):
    # Detect markdown table separator rows like |---|:---:|----|
    s = line.strip()
    if not s.startswith("|"):
        return False
    stripped = s.replace("|", "").replace("-", "").replace(":", "").strip()
    return stripped == ""

def find_section_content(md_text, section_name):
    # Find content under a header that contains section_name (case-insensitive)
    lines = md_text.splitlines()
    indices = []
    pat = re.compile(r"^\s{0,3}#{1,6}\s*(.+)$")
    headers = []
    for i, line in enumerate(lines):
        m = pat.match(line)
        if m:
            title = m.group(1).strip()
            headers.append((i, title))
    # Locate the first header that includes the section_name (case-insensitive)
    start_idx = None
    for i, title in headers:
        if section_name.lower() in title.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # Determine end index as next header after start_idx
    end_idx = len(lines)
    for i, _title in headers:
        if i > start_idx:
            end_idx = i
            break
    # Return joined content between headers (excluding the header line itself)
    content = "\n".join(lines[start_idx+1:end_idx])
    return content

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    report_path = os.path.join(output_dir, "nimbusai_annual_report_2025.md")
    kpi_path = os.path.join(output_dir, "nimbusai_kpis_2025.json")

    checks = {
        "has_report_file": False,
        "report_has_executive_section": False,
        "report_has_financial_section": False,
        "report_has_operational_section": False,
        "report_has_strategic_section": False,
        "report_has_risk_section": False,
        "report_has_guidance_section": False,
        "report_mentions_segments": False,
        "guidance_has_bear_base_bull": False,
        "risk_table_min_5_rows": False,
        "has_kpi_file": False,
        "kpi_valid_json": False,
        "kpi_has_required_keys": False,
        "kpi_fiscal_year_2025": False,
        "kpi_total_revenue_ok": False,
        "kpi_total_cogs_ok": False,
        "kpi_gross_margin_pct_ok": False,
        "kpi_ebitda_ok": False,
        "kpi_ebitda_margin_pct_ok": False,
        "kpi_yoy_revenue_growth_pct_ok": False,
        "kpi_rule_of_40_ok": False,
        "kpi_burn_multiple_ok": False,
        "kpi_cac_payback_ok": False,
        "kpi_ltv_ok": False,
        "kpi_revenue_per_employee_ok": False,
        "kpi_nrr_exact": False,
        "kpi_churn_logo_exact": False,
        "kpi_nps_exact": False,
    }

    # Load and analyze report
    report_text = None
    if os.path.isfile(report_path):
        checks["has_report_file"] = True
        report_text = read_text(report_path)

    if report_text:
        # Section presence (case-insensitive substring match)
        if "executive summary".lower() in report_text.lower():
            checks["report_has_executive_section"] = True
        if "financial performance".lower() in report_text.lower():
            checks["report_has_financial_section"] = True
        if "operational review".lower() in report_text.lower():
            checks["report_has_operational_section"] = True
        if "strategic highlights".lower() in report_text.lower():
            checks["report_has_strategic_section"] = True
        if "risk register".lower() in report_text.lower():
            checks["report_has_risk_section"] = True
        if "forward guidance".lower() in report_text.lower():
            checks["report_has_guidance_section"] = True

        # Revenue segments mention
        lower = report_text.lower()
        core_ok = "core saas" in lower
        # Accept "enterprise add-ons" or "enterprise add ons"
        enterprise_ok = ("enterprise add-ons" in lower) or ("enterprise add ons" in lower)
        services_ok = "services" in lower
        if core_ok and enterprise_ok and services_ok:
            checks["report_mentions_segments"] = True

        # Forward guidance content: bear, base, bull within the Forward Guidance section
        fg_content = find_section_content(report_text, "Forward Guidance")
        if fg_content:
            lc = fg_content.lower()
            if ("bear" in lc) and ("base" in lc) and ("bull" in lc):
                checks["guidance_has_bear_base_bull"] = True

        # Risk table detection: header row and at least 5 subsequent table rows
        # Find header line containing "Risk|Likelihood|Impact|Mitigation"
        lines = report_text.splitlines()
        header_idx = None
        header_pattern = re.compile(r"\|\s*Risk\s*\|\s*Likelihood\s*\|\s*Impact\s*\|\s*Mitigation", re.IGNORECASE)
        for i, line in enumerate(lines):
            if header_pattern.search(line):
                header_idx = i
                break
        if header_idx is not None:
            # Count subsequent data rows starting with '|' and not just a separator row, and not the header itself
            count_rows = 0
            for j in range(header_idx + 1, len(lines)):
                l = lines[j]
                if l.strip().startswith("|"):
                    if is_separator_row(l):
                        continue
                    # treat as data row
                    count_rows += 1
                else:
                    # Stop when table likely ends
                    # but allow continuing if blank lines or non-table lines appear; per requirement, count rows anywhere after header
                    # However, to be conservative, break at first non-table line
                    break
            if count_rows >= 5:
                checks["risk_table_min_5_rows"] = True

    # KPI JSON checks
    kpi_data = None
    if os.path.isfile(kpi_path):
        checks["has_kpi_file"] = True
        kpi_data = load_json(kpi_path)
        if isinstance(kpi_data, dict):
            checks["kpi_valid_json"] = True

    required_keys = [
        "fiscal_year",
        "total_revenue",
        "total_cogs",
        "gross_margin_pct",
        "ebitda",
        "ebitda_margin_pct",
        "yoy_revenue_growth_pct",
        "rule_of_40",
        "burn_multiple",
        "cac_payback_months",
        "ltv",
        "revenue_per_employee",
        "nrr_pct",
        "churn_logo_pct",
        "nps",
    ]

    if checks["kpi_valid_json"]:
        if all(k in kpi_data for k in required_keys):
            checks["kpi_has_required_keys"] = True

        # Only proceed with numeric validations if keys exist
        if checks["kpi_has_required_keys"]:
            # fiscal year
            try:
                fy = int(kpi_data.get("fiscal_year"))
                if fy == 2025:
                    checks["kpi_fiscal_year_2025"] = True
            except Exception:
                pass

            # Numeric tolerances (expected values)
            checks["kpi_total_revenue_ok"] = within(kpi_data.get("total_revenue"), 10380000.0, 1000.0)
            checks["kpi_total_cogs_ok"] = within(kpi_data.get("total_cogs"), 2280000.0, 1000.0)
            checks["kpi_gross_margin_pct_ok"] = within(kpi_data.get("gross_margin_pct"), 78.0, 0.5)
            checks["kpi_ebitda_ok"] = within(kpi_data.get("ebitda"), 1350000.0, 20000.0)
            checks["kpi_ebitda_margin_pct_ok"] = within(kpi_data.get("ebitda_margin_pct"), 13.0, 0.5)
            checks["kpi_yoy_revenue_growth_pct_ok"] = within(kpi_data.get("yoy_revenue_growth_pct"), 36.2, 0.5)
            checks["kpi_rule_of_40_ok"] = within(kpi_data.get("rule_of_40"), 49.2, 1.0)
            checks["kpi_burn_multiple_ok"] = within(kpi_data.get("burn_multiple"), 0.30, 0.05)
            checks["kpi_cac_payback_ok"] = between(kpi_data.get("cac_payback_months"), 17.5, 19.5)
            # LTV within ±10% of 108333.33
            try:
                ltv_val = float(kpi_data.get("ltv"))
                ltv_target = 108333.33
                ltv_lo = ltv_target * 0.9
                ltv_hi = ltv_target * 1.1
                checks["kpi_ltv_ok"] = ltv_lo <= ltv_val <= ltv_hi
            except Exception:
                checks["kpi_ltv_ok"] = False

            checks["kpi_revenue_per_employee_ok"] = within(kpi_data.get("revenue_per_employee"), 129750.0, 1000.0)

            # Exact matches
            checks["kpi_nrr_exact"] = (kpi_data.get("nrr_pct") == 114) or (kpi_data.get("nrr_pct") == 114.0)
            checks["kpi_churn_logo_exact"] = (kpi_data.get("churn_logo_pct") == 8.5)
            checks["kpi_nps_exact"] = (kpi_data.get("nps") == 45) or (kpi_data.get("nps") == 45.0)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Print single JSON object
    result = {"reward": reward}
    # Maintain insertion order of checks
    for k, v in checks.items():
        result[k] = bool(v)
    print(json.dumps(result))

if __name__ == "__main__":
    main()