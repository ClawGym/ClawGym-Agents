import json
import os
import sys
import re

def is_number(value):
    # Ensure numeric but not boolean (bool is subclass of int)
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text(path, encoding="utf-8"):
    try:
        with open(path, "r", encoding=encoding) as f:
            return True, f.read()
    except Exception:
        return False, ""

def read_lines(path, encoding="utf-8"):
    ok, text = read_text(path, encoding=encoding)
    if not ok:
        return False, []
    return True, text.splitlines()

def validate_recommendation(value):
    if not isinstance(value, str):
        return False
    val = value.strip().lower()
    return val in {"go", "no-go", "consider"}

def validate_viability_list(lst):
    if not isinstance(lst, list):
        return False
    if len(lst) != 10:
        return False
    def item_ok(x):
        if isinstance(x, bool):
            return True
        if isinstance(x, str):
            s = x.strip().lower()
            return s in {"pass", "fail"}
        return False
    return all(item_ok(x) for x in lst)

def validate_rate(value):
    if not is_number(value):
        return False
    # Accept 0-1 or 0-100 ranges
    if 0.0 <= value <= 1.0:
        return True
    if 0.0 <= value <= 100.0:
        return True
    return False

def validate_report(report_data, checks):
    # Initialize all report-related checks to False
    checks["report_exists"] = False
    checks["report_valid_json"] = False
    checks["report_has_required_keys"] = False
    checks["report_product_overview_fields_valid"] = False
    checks["report_opportunity_score_valid"] = False
    checks["report_competitive_landscape_valid_count"] = False
    checks["report_competitive_landscape_items_fields_valid"] = False
    checks["report_revenue_estimate_valid"] = False
    checks["report_margin_analysis_valid"] = False
    checks["report_viability_checklist_valid"] = False
    checks["report_recommendation_valid"] = False
    checks["report_next_steps_present"] = False

    if report_data is None:
        return

    checks["report_exists"] = True
    if not isinstance(report_data, dict):
        return

    checks["report_valid_json"] = True

    required_keys = [
        "product_overview",
        "opportunity_score",
        "competitive_landscape",
        "revenue_estimate",
        "margin_analysis",
        "viability_checklist",
        "recommendation",
        "next_steps",
    ]
    if all(k in report_data for k in required_keys):
        checks["report_has_required_keys"] = True

    # product_overview
    po_ok = False
    po = report_data.get("product_overview")
    if isinstance(po, dict):
        name = po.get("name")
        category = po.get("category")
        target_price = po.get("target_price")
        market_revenue = po.get("market_revenue")
        if isinstance(name, str) and name.strip() and isinstance(category, str) and category.strip() and is_number(target_price) and is_number(market_revenue):
            po_ok = True
    checks["report_product_overview_fields_valid"] = po_ok

    # opportunity_score
    os_ok = False
    opp = report_data.get("opportunity_score")
    if isinstance(opp, dict):
        total = opp.get("total")
        factors = opp.get("factors")
        if is_number(total) and 0.0 <= float(total) <= 100.0 and isinstance(factors, list) and len(factors) == 10:
            os_ok = True
    checks["report_opportunity_score_valid"] = os_ok

    # competitive_landscape
    cl = report_data.get("competitive_landscape")
    cl_count_ok = False
    cl_items_ok = False
    if isinstance(cl, list) and len(cl) >= 10:
        cl_count_ok = True
        # Validate each item has required fields with correct types (numbers must be numeric)
        required_item_fields = [
            ("rank", is_number),
            ("title", lambda v: isinstance(v, str)),
            ("price", is_number),
            ("bsr", is_number),
            ("reviews", is_number),
            ("estimated_monthly_sales", is_number),
            ("estimated_monthly_revenue", is_number),
        ]
        per_item_valid = True
        for item in cl:
            if not isinstance(item, dict):
                per_item_valid = False
                break
            for key, validator in required_item_fields:
                if key not in item or not validator(item.get(key)):
                    per_item_valid = False
                    break
            if not per_item_valid:
                break
        cl_items_ok = per_item_valid
    checks["report_competitive_landscape_valid_count"] = cl_count_ok
    checks["report_competitive_landscape_items_fields_valid"] = cl_items_ok

    # revenue_estimate
    re_ok = False
    re = report_data.get("revenue_estimate")
    if isinstance(re, dict) and is_number(re.get("total_market_revenue")):
        re_ok = True
    checks["report_revenue_estimate_valid"] = re_ok

    # margin_analysis
    ma_ok = False
    ma = report_data.get("margin_analysis")
    if isinstance(ma, dict):
        assumptions = ma.get("assumptions")
        fba_fee = ma.get("fba_fee")
        referral_fee_rate = ma.get("referral_fee_rate")
        cogs = ma.get("cogs")
        ppc_rate = ma.get("ppc_rate")
        net_profit_per_unit = ma.get("net_profit_per_unit")
        net_margin = ma.get("net_margin")
        assumptions_ok = isinstance(assumptions, (str, dict))
        fields_ok = (
            is_number(fba_fee)
            and validate_rate(referral_fee_rate)
            and is_number(cogs)
            and validate_rate(ppc_rate)
            and is_number(net_profit_per_unit)
            and validate_rate(net_margin)
        )
        if assumptions_ok and fields_ok:
            ma_ok = True
    checks["report_margin_analysis_valid"] = ma_ok

    # viability_checklist
    vc_ok = validate_viability_list(report_data.get("viability_checklist"))
    checks["report_viability_checklist_valid"] = vc_ok

    # recommendation
    rec_ok = validate_recommendation(report_data.get("recommendation"))
    checks["report_recommendation_valid"] = rec_ok

    # next_steps (present and non-empty string or non-empty list)
    ns_ok = False
    if "next_steps" in report_data:
        ns = report_data.get("next_steps")
        if isinstance(ns, str):
            ns_ok = len(ns.strip()) > 0
        elif isinstance(ns, list):
            ns_ok = len(ns) > 0
        else:
            # accept any non-null value for presence
            ns_ok = ns is not None
    checks["report_next_steps_present"] = ns_ok

def validate_csv(csv_path, checks):
    checks["csv_exists"] = False
    checks["csv_header_valid"] = False
    checks["csv_has_10_rows"] = False

    if not os.path.isfile(csv_path):
        return

    checks["csv_exists"] = True

    # Read with utf-8-sig to strip potential BOM
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            lines = [ln.rstrip("\n\r") for ln in f.readlines()]
    except Exception:
        return

    if not lines:
        return

    header_expected = "rank,title,price,bsr,reviews,estimated_monthly_sales,estimated_monthly_revenue"
    header = lines[0].strip()
    if header == header_expected:
        checks["csv_header_valid"] = True

    data_rows = [ln for ln in lines[1:] if ln.strip() != ""]
    if len(data_rows) >= 10:
        checks["csv_has_10_rows"] = True

def validate_summary_md(md_path, checks):
    checks["summary_exists"] = False
    checks["summary_has_product_overview_heading"] = False
    checks["summary_has_opportunity_score_heading"] = False
    checks["summary_has_top10_heading"] = False
    checks["summary_has_revenue_estimate_heading"] = False
    checks["summary_has_margin_analysis_heading"] = False
    checks["summary_has_viability_checklist_heading"] = False
    checks["summary_has_recommendation_heading"] = False
    checks["summary_has_next_steps_heading"] = False

    if not os.path.isfile(md_path):
        return

    ok, lines = read_lines(md_path, encoding="utf-8")
    if not ok:
        return

    checks["summary_exists"] = True

    # Normalize to lines with exact match
    line_set = set(line.strip() for line in lines)

    checks["summary_has_product_overview_heading"] = "Product Overview" in line_set
    checks["summary_has_opportunity_score_heading"] = "Opportunity Score" in line_set
    checks["summary_has_top10_heading"] = "Top 10 Competitive Landscape" in line_set
    checks["summary_has_revenue_estimate_heading"] = "Revenue Estimate" in line_set
    checks["summary_has_margin_analysis_heading"] = "Margin Analysis" in line_set
    checks["summary_has_viability_checklist_heading"] = "Viability Checklist" in line_set
    checks["summary_has_recommendation_heading"] = "Go/No-Go Recommendation" in line_set
    checks["summary_has_next_steps_heading"] = "Next Steps" in line_set

def extract_labeled_line(lines, label_prefix):
    for line in lines:
        if line.strip().startswith(label_prefix):
            return line.strip()
    return None

def validate_assumptions(txt_path, checks):
    checks["assumptions_exists"] = False
    checks["assumptions_seasonality_valid"] = False
    checks["assumptions_fba_fee_valid"] = False
    checks["assumptions_cogs_valid"] = False
    checks["assumptions_ppc_valid"] = False

    if not os.path.isfile(txt_path):
        return

    ok, lines = read_lines(txt_path, encoding="utf-8")
    if not ok:
        return

    checks["assumptions_exists"] = True

    # Labels
    seasonality_label = "Seasonality adjustment:"
    fba_label = "FBA fee:"
    cogs_label = "COGS:"
    ppc_label = "PPC cost%:"

    # Seasonality
    season_line = extract_labeled_line(lines, seasonality_label)
    if season_line is not None:
        rest = season_line[len(seasonality_label):].strip()
        # Expect a signed percentage within -30%..+30% (allow unsigned for 0)
        m = re.match(r'^([+\-]?\d+(?:\.\d+)?)\s*%$', rest)
        if m:
            try:
                val = float(m.group(1))
                if -30.0 <= val <= 30.0:
                    checks["assumptions_seasonality_valid"] = True
            except ValueError:
                pass

    # FBA fee: expect a dollar amount
    fba_line = extract_labeled_line(lines, fba_label)
    if fba_line is not None:
        rest = fba_line[len(fba_label):].strip()
        # dollar amount pattern like $3.22 or $10
        if re.search(r'\$\s*\d+(\.\d+)?', rest):
            checks["assumptions_fba_fee_valid"] = True

    # COGS: expect a dollar amount
    cogs_line = extract_labeled_line(lines, cogs_label)
    if cogs_line is not None:
        rest = cogs_line[len(cogs_label):].strip()
        if re.search(r'\$\s*\d+(\.\d+)?', rest):
            checks["assumptions_cogs_valid"] = True

    # PPC: expect a percentage value
    ppc_line = extract_labeled_line(lines, ppc_label)
    if ppc_line is not None:
        rest = ppc_line[len(ppc_label):].strip()
        if re.match(r'^[+\-]?\d+(\.\d+)?\s*%$', rest):
            checks["assumptions_ppc_valid"] = True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    report_path = os.path.join(output_dir, "report.json")
    csv_path = os.path.join(output_dir, "competitive_landscape.csv")
    summary_path = os.path.join(output_dir, "summary.md")
    assumptions_path = os.path.join(output_dir, "assumptions.txt")

    # Validate report.json
    report_data = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True  # will be overwritten by validate_report
        ok, data = load_json_file(report_path)
        if ok:
            report_data = data
    validate_report(report_data, checks)

    # Validate CSV
    validate_csv(csv_path, checks)

    # Validate summary.md
    validate_summary_md(summary_path, checks)

    # Validate assumptions.txt
    validate_assumptions(assumptions_path, checks)

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure no-op baseline: if output directory missing or all four required files missing, reward must be 0.0
    required_files = [
        os.path.isfile(report_path),
        os.path.isfile(csv_path),
        os.path.isfile(summary_path),
        os.path.isfile(assumptions_path),
    ]
    if not any(required_files):
        reward = 0.0
        # Also ensure checks defaulted to False are present (already done)

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()