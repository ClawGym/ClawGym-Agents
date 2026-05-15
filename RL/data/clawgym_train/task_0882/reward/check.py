import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_simple_yaml(path):
    """
    Minimal YAML parser for simple key: value pairs (no nesting, lists).
    Assumes UTF-8 text with lines like: key: value
    """
    data = {}
    text, err = read_text(path)
    if err:
        return None, err
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data, None

def approx_equal(a, b, rel_tol=0.005, abs_tol=1e-6):
    try:
        a = float(a)
        b = float(b)
    except Exception:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b), 1.0))

def compute_expected(fin):
    # Extract with defaults (but calculations should only pass if outputs match inputs correctly)
    def getf(key, default=0.0):
        v = fin.get(key, default)
        try:
            return float(v)
        except Exception:
            return float(default)

    mrr = getf("mrr")
    last_mrr = getf("last_month_mrr")
    starting_mrr = getf("starting_mrr")
    expansion_mrr = getf("expansion_mrr")
    contraction_mrr = getf("contraction_mrr")
    churned_mrr = getf("churned_mrr")
    new_mrr = getf("new_mrr")
    new_customers = getf("new_customers")
    sm_spend = getf("sales_marketing_spend")
    arpu = getf("arpu")
    gm_pct = getf("gross_margin_pct")
    headcount = getf("headcount")
    monthly_burn = getf("monthly_burn")
    prior_q_sm_spend = getf("prior_quarter_sm_spend")
    net_new_arr_qoq = getf("net_new_arr_qoq")
    monthly_churn_pct = getf("monthly_churn_pct")
    revenue_growth_pct = getf("revenue_growth_pct")
    ebitda_margin_pct = getf("ebitda_margin_pct")

    arr = mrr * 12.0

    nrr = None
    if starting_mrr != 0:
        nrr = (starting_mrr + expansion_mrr - contraction_mrr - churned_mrr) / starting_mrr * 100.0

    grr = None
    if starting_mrr != 0:
        grr = (starting_mrr - contraction_mrr - churned_mrr) / starting_mrr * 100.0

    rev_per_emp = None
    if headcount != 0:
        rev_per_emp = arr / headcount

    mom_growth_pct = None
    if last_mrr != 0:
        mom_growth_pct = (mrr - last_mrr) / last_mrr * 100.0

    denom_qr = (contraction_mrr + churned_mrr)
    quick_ratio = None
    if denom_qr == 0:
        quick_ratio = float('inf') if (new_mrr + expansion_mrr) > 0 else 0.0
    else:
        quick_ratio = (new_mrr + expansion_mrr) / denom_qr

    magic_number = None
    if prior_q_sm_spend != 0:
        magic_number = net_new_arr_qoq / prior_q_sm_spend

    cac = None
    if new_customers != 0:
        cac = sm_spend / new_customers

    gm_decimal = gm_pct / 100.0 if gm_pct else 0.0
    churn_decimal = monthly_churn_pct / 100.0 if monthly_churn_pct else 0.0

    ltv = None
    if churn_decimal != 0.0:
        ltv = arpu * gm_decimal / churn_decimal

    ltv_cac = None
    if cac not in (None, 0.0):
        ltv_cac = ltv / cac if ltv is not None else None

    cac_payback_months = None
    denom_payback = arpu * gm_decimal
    if denom_payback != 0 and cac is not None:
        cac_payback_months = cac / denom_payback

    gross_margin_pct = gm_pct

    rule_of_40 = revenue_growth_pct + ebitda_margin_pct

    net_new_arr_monthly = 12.0 * (mrr - last_mrr)
    burn_multiple = None
    if net_new_arr_monthly > 0:
        burn_multiple = monthly_burn / net_new_arr_monthly

    return {
        "mrr": mrr,
        "arr": arr,
        "nrr": nrr,
        "grr": grr,
        "revenue_per_employee": rev_per_emp,
        "mom_growth_pct": mom_growth_pct,
        "quick_ratio": quick_ratio,
        "magic_number": magic_number,
        "cac": cac,
        "ltv": ltv,
        "ltv_cac": ltv_cac,
        "cac_payback_months": cac_payback_months,
        "gross_margin_pct": gross_margin_pct,
        "rule_of_40": rule_of_40,
        "burn_multiple": burn_multiple,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "all_required_outputs_present": False,
        "out_dashboard_exists": False,
        "dashboard_json_valid": False,
        "dashboard_schema_ok": False,
        "dashboard_top_fields_ok": False,
        "metrics_keys_ok": False,
        "metrics_units_ok": False,
        "metrics_status_values_ok": False,
        "mrr_value_ok": False,
        "arr_value_ok": False,
        "nrr_value_ok": False,
        "grr_value_ok": False,
        "revenue_per_employee_value_ok": False,
        "mom_growth_value_ok": False,
        "quick_ratio_value_ok": False,
        "magic_number_value_ok": False,
        "cac_value_ok": False,
        "ltv_value_ok": False,
        "ltv_cac_value_ok": False,
        "cac_payback_value_ok": False,
        "gross_margin_value_ok": False,
        "rule_of_40_value_ok": False,
        "burn_multiple_value_ok": False,
        "nrr_status_red_ok": False,
        "ltv_cac_status_green_ok": False,
        "grr_status_green_ok": False,
        "burn_multiple_status_green_ok": False,
        "out_board_summary_exists": False,
        "summary_has_company_month_stage": False,
        "summary_has_legend": False,
        "summary_has_top3_actions_section": False,
        "summary_has_three_numbered_items": False,
        "summary_has_nrr_action_with_target_and_timebound": False,
    }

    # Paths
    fin_path = os.path.join(input_dir, "financials.json")
    company_yaml_path = os.path.join(input_dir, "company.yaml")
    dashboard_path = os.path.join(output_dir, "dashboard.json")
    summary_path = os.path.join(output_dir, "board_summary.md")

    # Read inputs (reference only)
    fin, fin_err = read_json(fin_path)
    company_yaml, comp_err = parse_simple_yaml(company_yaml_path)

    # If input files are missing or invalid, we can still run, but no positive credit without outputs matching.
    expected = None
    company_name = None
    month_str = None
    stage_str = None
    if fin and not fin_err:
        expected = compute_expected(fin)
    if company_yaml and not comp_err:
        company_name = company_yaml.get("company_name")
        month_str = company_yaml.get("month")
        stage_str = company_yaml.get("stage")

    # Check dashboard.json
    if os.path.isfile(dashboard_path):
        checks["out_dashboard_exists"] = True
        dash, dash_err = read_json(dashboard_path)
        if dash and not dash_err and isinstance(dash, dict):
            checks["dashboard_json_valid"] = True
            # Schema: required top-level keys
            required_top_keys = {"company", "month", "stage", "metrics", "benchmark_stage", "notes"}
            top_keys_ok = required_top_keys.issubset(set(dash.keys()))
            types_ok = isinstance(dash.get("company"), str) and isinstance(dash.get("month"), str) and isinstance(dash.get("stage"), str) and isinstance(dash.get("benchmark_stage"), str) and isinstance(dash.get("notes"), str) and isinstance(dash.get("metrics"), dict)
            checks["dashboard_schema_ok"] = bool(top_keys_ok and types_ok)

            # Top fields exact matches
            top_ok = False
            if company_name and month_str and stage_str:
                top_ok = (dash.get("company") == company_name and dash.get("month") == month_str and dash.get("stage") == "Series A" and dash.get("benchmark_stage") == "Series A")
            checks["dashboard_top_fields_ok"] = bool(top_ok)

            # Metrics keys and unit/status presence
            required_metric_keys = [
                "mrr", "arr", "nrr", "grr", "revenue_per_employee", "mom_growth_pct",
                "quick_ratio", "magic_number", "cac", "ltv", "ltv_cac", "cac_payback_months",
                "gross_margin_pct", "rule_of_40", "burn_multiple"
            ]
            metrics_obj = dash.get("metrics") if isinstance(dash.get("metrics"), dict) else {}
            metrics_keys_ok = set(metrics_obj.keys()) == set(required_metric_keys)
            checks["metrics_keys_ok"] = bool(metrics_keys_ok)

            # Units map
            expected_units = {
                "mrr": "usd",
                "arr": "usd",
                "nrr": "percent",
                "grr": "percent",
                "revenue_per_employee": "usd",
                "mom_growth_pct": "percent",
                "quick_ratio": "ratio",
                "magic_number": "ratio",
                "cac": "usd",
                "ltv": "usd",
                "ltv_cac": "ratio",
                "cac_payback_months": "months",
                "gross_margin_pct": "percent",
                "rule_of_40": "index",
                "burn_multiple": "ratio",
            }

            units_ok = True
            status_values_ok = True
            values_extracted = {}
            if metrics_keys_ok:
                for k in required_metric_keys:
                    v = metrics_obj.get(k)
                    if not isinstance(v, dict):
                        units_ok = False
                        status_values_ok = False
                        break
                    # Check presence of keys
                    if "value" not in v or "unit" not in v or "status" not in v:
                        units_ok = False
                        status_values_ok = False
                        break
                    # Unit check
                    if v.get("unit") != expected_units[k]:
                        units_ok = False
                    # Status lowercase and allowed
                    st = v.get("status")
                    if not isinstance(st, str) or st not in ("green", "yellow", "red"):
                        status_values_ok = False
                    # Value numeric
                    try:
                        values_extracted[k] = float(v.get("value"))
                    except Exception:
                        # Non-numeric value
                        pass
            else:
                units_ok = False
                status_values_ok = False

            checks["metrics_units_ok"] = bool(units_ok)
            checks["metrics_status_values_ok"] = bool(status_values_ok)

            # Numeric value checks against expected computations
            if expected and metrics_keys_ok:
                # MRR
                mv = metrics_obj["mrr"].get("value")
                if isinstance(mv, (int, float)) and approx_equal(mv, expected["mrr"]):
                    checks["mrr_value_ok"] = True
                # ARR
                mv = metrics_obj["arr"].get("value")
                if isinstance(mv, (int, float)) and approx_equal(mv, expected["arr"]):
                    checks["arr_value_ok"] = True
                # NRR (percent)
                mv = metrics_obj["nrr"].get("value")
                if expected["nrr"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["nrr"]):
                    checks["nrr_value_ok"] = True
                # GRR
                mv = metrics_obj["grr"].get("value")
                if expected["grr"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["grr"]):
                    checks["grr_value_ok"] = True
                # Revenue per employee
                mv = metrics_obj["revenue_per_employee"].get("value")
                if expected["revenue_per_employee"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["revenue_per_employee"]):
                    checks["revenue_per_employee_value_ok"] = True
                # MoM growth
                mv = metrics_obj["mom_growth_pct"].get("value")
                if expected["mom_growth_pct"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["mom_growth_pct"]):
                    checks["mom_growth_value_ok"] = True
                # Quick ratio
                mv = metrics_obj["quick_ratio"].get("value")
                if expected["quick_ratio"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["quick_ratio"]):
                    checks["quick_ratio_value_ok"] = True
                # Magic number
                mv = metrics_obj["magic_number"].get("value")
                if expected["magic_number"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["magic_number"]):
                    checks["magic_number_value_ok"] = True
                # CAC
                mv = metrics_obj["cac"].get("value")
                if expected["cac"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["cac"]):
                    checks["cac_value_ok"] = True
                # LTV
                mv = metrics_obj["ltv"].get("value")
                if expected["ltv"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["ltv"]):
                    checks["ltv_value_ok"] = True
                # LTV:CAC
                mv = metrics_obj["ltv_cac"].get("value")
                if expected["ltv_cac"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["ltv_cac"]):
                    checks["ltv_cac_value_ok"] = True
                # CAC Payback months
                mv = metrics_obj["cac_payback_months"].get("value")
                if expected["cac_payback_months"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["cac_payback_months"]):
                    checks["cac_payback_value_ok"] = True
                # Gross margin pct
                mv = metrics_obj["gross_margin_pct"].get("value")
                if isinstance(mv, (int, float)) and approx_equal(mv, expected["gross_margin_pct"]):
                    checks["gross_margin_value_ok"] = True
                # Rule of 40
                mv = metrics_obj["rule_of_40"].get("value")
                if isinstance(mv, (int, float)) and approx_equal(mv, expected["rule_of_40"]):
                    checks["rule_of_40_value_ok"] = True
                # Burn multiple
                mv = metrics_obj["burn_multiple"].get("value")
                if expected["burn_multiple"] is not None and isinstance(mv, (int, float)) and approx_equal(mv, expected["burn_multiple"]):
                    checks["burn_multiple_value_ok"] = True

            # Required status checks for certain metrics
            if metrics_keys_ok and status_values_ok:
                nrr_status = metrics_obj["nrr"].get("status")
                ltv_cac_status = metrics_obj["ltv_cac"].get("status")
                grr_status = metrics_obj["grr"].get("status")
                burn_status = metrics_obj["burn_multiple"].get("status")
                if isinstance(nrr_status, str) and nrr_status == "red":
                    checks["nrr_status_red_ok"] = True
                if isinstance(ltv_cac_status, str) and ltv_cac_status == "green":
                    checks["ltv_cac_status_green_ok"] = True
                if isinstance(grr_status, str) and grr_status == "green":
                    checks["grr_status_green_ok"] = True
                if isinstance(burn_status, str) and burn_status == "green":
                    checks["burn_multiple_status_green_ok"] = True

    # Check board_summary.md
    if os.path.isfile(summary_path):
        checks["out_board_summary_exists"] = True
        content, serr = read_text(summary_path)
        if content and not serr:
            lines = content.splitlines()

            # Company + month + stage in one line
            cms_ok = False
            if company_name and month_str and stage_str:
                for line in lines:
                    if (company_name in line) and (month_str in line) and ("Series A" in line):
                        cms_ok = True
                        break
            checks["summary_has_company_month_stage"] = bool(cms_ok)

            # Legend line includes green, yellow, red
            legend_ok = False
            for line in lines:
                low = line.lower()
                if "green" in low and "yellow" in low and "red" in low:
                    legend_ok = True
                    break
            checks["summary_has_legend"] = bool(legend_ok)

            # TOP 3 ACTIONS section
            checks["summary_has_top3_actions_section"] = ("top 3 actions:" in content.lower())

            # Three numbered items (1., 2., 3.)
            numbered = 0
            for line in lines:
                if re.match(r"^\s*1\.\s", line):
                    numbered += 1
                if re.match(r"^\s*2\.\s", line):
                    numbered += 1
                if re.match(r"^\s*3\.\s", line):
                    numbered += 1
            checks["summary_has_three_numbered_items"] = (numbered >= 3)

            # At least one action referencing NRR with 110% target and time-bound phrase
            nrr_action_ok = False
            # Simple heuristic: find line with "NRR" and "110%" (or >110%), and a time-bound word
            time_words = ["within", "by ", "in ", "over ", "before "]
            time_units = ["month", "months", "quarter", "quarters", "week", "weeks", "year", "years"]
            for line in lines:
                if re.match(r"^\s*\d\.\s", line):  # action line
                    if "NRR" in line.upper() and ("110%" in line or ">110%" in line or "110 %" in line):
                        low = line.lower()
                        if any(tw in low for tw in time_words) and any(tu in low for tu in time_units):
                            nrr_action_ok = True
                            break
            checks["summary_has_nrr_action_with_target_and_timebound"] = bool(nrr_action_ok)

    # Required outputs presence gate
    checks["all_required_outputs_present"] = bool(checks["out_dashboard_exists"] and checks["out_board_summary_exists"])

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    if not checks["all_required_outputs_present"]:
        reward = 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()