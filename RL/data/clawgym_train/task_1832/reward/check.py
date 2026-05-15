import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def parse_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "" or s.lower() in ("na", "n/a", "null", "none"):
        return None
    # Remove currency symbols and commas
    for ch in ["$", ","]:
        s = s.replace(ch, "")
    try:
        return float(s)
    except:
        return None

def approx_equal(a: Optional[float], b: Optional[float], rel_tol: float = 0.01, abs_tol: float = 0.01) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # Handle NaN or inf
    try:
        diff = abs(a - b)
    except:
        return False
    # If numbers are tiny, use abs tolerance
    return diff <= max(abs_tol, rel_tol * max(1.0, abs(b)))

def round2(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        return round(float(x), 2)
    except:
        return None

def read_assumptions(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # normalize gross_margin_pct to decimal if provided as percentage > 1
    g = data.get("gross_margin_pct")
    g_val = parse_float(g)
    if g_val is None:
        gm = None
    else:
        gm = g_val / 100.0 if g_val > 1.0 else g_val
    data["_gross_margin_dec"] = gm
    return data

def normalize_row_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        key = k.strip().lower()
        key = key.replace(" ", "_")
        out[key] = v
    return out

def load_input_months(csv_path: str) -> Dict[str, Dict[str, Any]]:
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            if r is None:
                continue
            r2 = normalize_row_keys(r)
            rows.append(r2)
    months = {}
    for r in rows:
        m = str(r.get("month", "")).strip()
        months[m] = r
    return months

def get_required_float(row: Dict[str, Any], key: str) -> Optional[float]:
    return parse_float(row.get(key))

def compute_monthly_derived(row: Dict[str, Any], gross_margin: Optional[float]) -> Dict[str, Optional[float]]:
    # Required base fields
    start_mrr = get_required_float(row, "start_mrr")
    new_mrr = get_required_float(row, "new_mrr")
    expansion_mrr = get_required_float(row, "expansion_mrr")
    contraction_mrr = get_required_float(row, "contraction_mrr")
    churned_mrr = get_required_float(row, "churned_mrr")
    end_mrr = get_required_float(row, "end_mrr")
    customers_start = get_required_float(row, "customers_start")
    new_customers = get_required_float(row, "new_customers")
    lost_customers = get_required_float(row, "lost_customers")
    customers_end = get_required_float(row, "customers_end")
    sm_spend = get_required_float(row, "sm_spend")
    expenses_total = get_required_float(row, "expenses_total")

    net_new_mrr = None
    if None not in (new_mrr, expansion_mrr, contraction_mrr, churned_mrr):
        net_new_mrr = new_mrr + expansion_mrr - contraction_mrr - churned_mrr

    # arpu = end_mrr / customers_end
    arpu = None
    if end_mrr is not None and customers_end and customers_end != 0:
        arpu = end_mrr / customers_end

    # churn_rate = lost_customers / customers_start
    churn_rate = None
    if lost_customers is not None and customers_start not in (None, 0):
        churn_rate = lost_customers / customers_start

    # cac = sm_spend / new_customers (if new_customers=0 -> null)
    cac = None
    if sm_spend is not None and new_customers not in (None, 0):
        cac = sm_spend / new_customers

    # ltv = arpu × gross_margin_pct × (1 / churn_rate)
    ltv = None
    if arpu is not None and gross_margin not in (None,) and churn_rate not in (None, 0):
        ltv = arpu * gross_margin * (1.0 / churn_rate)

    # ltv_cac = ltv / cac
    ltv_cac = None
    if ltv is not None and cac not in (None, 0):
        ltv_cac = ltv / cac

    # payback_months = cac / (arpu × gross_margin_pct)
    payback_months = None
    if cac is not None and arpu not in (None,) and gross_margin not in (None,) and (arpu * gross_margin) != 0:
        payback_months = cac / (arpu * gross_margin)

    # net_burn = expenses_total − end_mrr
    net_burn = None
    if expenses_total is not None and end_mrr is not None:
        net_burn = expenses_total - end_mrr

    return {
        "net_new_mrr": net_new_mrr,
        "arpu": arpu,
        "churn_rate": churn_rate,
        "cac": cac,
        "ltv": ltv,
        "ltv_cac": ltv_cac,
        "payback_months": payback_months,
        "net_burn": net_burn,
    }

def safe_get(d: Dict[str, Any], k: str) -> Any:
    return d.get(k)

def read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def read_csv_rows(path: str) -> Optional[List[Dict[str, Any]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [normalize_row_keys(r) for r in reader]
    except:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        "has_summary": False,
        "summary_keys_valid": False,
        "summary_values_match": False,
        "has_monthly": False,
        "monthly_columns_valid": False,
        "monthly_rows_valid": False,
        "monthly_formulas_valid": False,
        "has_report": False,
        "report_has_required_terms": False,
    }

    # Paths
    input_csv_path = os.path.join(input_dir, "data_saas_2025H1.csv")
    input_assumptions_path = os.path.join(input_dir, "assumptions.json")
    summary_path = os.path.join(output_dir, "metrics", "summary.json")
    monthly_path = os.path.join(output_dir, "metrics", "monthly.csv")
    report_path = os.path.join(output_dir, "report.md")

    # Load inputs (for expectation computation)
    try:
        months_input = load_input_months(input_csv_path)
    except Exception:
        months_input = {}

    assumptions = {}
    gm = None
    try:
        assumptions = read_assumptions(input_assumptions_path)
        gm = assumptions.get("_gross_margin_dec")
    except Exception:
        gm = None

    # Compute expectations from input
    required_months = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]

    # Prepare expected monthly derived using input data
    expected_monthly: Dict[str, Dict[str, Optional[float]]] = {}
    for m in required_months:
        row = months_input.get(m, {})
        if row:
            derived = compute_monthly_derived(row, gm)
            expected_monthly[m] = derived
        else:
            expected_monthly[m] = {}

    # Compute expected summary metrics
    def get_field(m: str, key: str) -> Optional[float]:
        return get_required_float(months_input.get(m, {}), key)

    may_end = get_field("2025-05", "end_mrr")
    jun_end = get_field("2025-06", "end_mrr")
    jun_customers_end = get_field("2025-06", "customers_end")
    jun_sm_spend = get_field("2025-06", "sm_spend")
    jun_new_customers = get_field("2025-06", "new_customers")
    jun_lost_customers = get_field("2025-06", "lost_customers")
    jun_customers_start = get_field("2025-06", "customers_start")
    jun_expenses_total = get_field("2025-06", "expenses_total")
    jun_cash_end = get_field("2025-06", "cash_balance_end")
    apr_start_mrr = get_field("2025-04", "start_mrr")
    q2_expansion = sum([get_field(m, "expansion_mrr") or 0.0 for m in ["2025-04", "2025-05", "2025-06"]])
    q2_contraction = sum([get_field(m, "contraction_mrr") or 0.0 for m in ["2025-04", "2025-05", "2025-06"]])
    q2_churned = sum([get_field(m, "churned_mrr") or 0.0 for m in ["2025-04", "2025-05", "2025-06"]])
    q1_sm_spend = sum([get_field(m, "sm_spend") or 0.0 for m in ["2025-01", "2025-02", "2025-03"]])
    q2_net_burn_sum = 0.0
    for m in ["2025-04", "2025-05", "2025-06"]:
        e_total = get_field(m, "expenses_total")
        e_end_mrr = get_field(m, "end_mrr")
        if e_total is not None and e_end_mrr is not None:
            q2_net_burn_sum += (e_total - e_end_mrr)
        else:
            q2_net_burn_sum = None
            break

    # Summary expected values
    exp = {}
    exp["as_of"] = "2025-06"
    exp["mrr_june"] = jun_end if jun_end is not None else None
    exp["arr_run_rate"] = (jun_end * 12.0) if jun_end is not None else None
    exp["mom_growth_june"] = None
    if jun_end is not None and may_end not in (None, 0):
        exp["mom_growth_june"] = (jun_end - may_end) / may_end

    arpu_june = None
    if jun_end is not None and jun_customers_end not in (None, 0):
        arpu_june = jun_end / jun_customers_end
    exp["arpu_june"] = arpu_june

    cac_june = None
    if jun_sm_spend is not None and jun_new_customers not in (None, 0):
        cac_june = jun_sm_spend / jun_new_customers
    exp["cac_june"] = cac_june

    churn_rate_june = None
    if jun_lost_customers is not None and jun_customers_start not in (None, 0):
        churn_rate_june = jun_lost_customers / jun_customers_start
    exp["churn_rate_june"] = churn_rate_june

    ltv_june = None
    if arpu_june is not None and gm not in (None,) and churn_rate_june not in (None, 0):
        ltv_june = arpu_june * gm * (1.0 / churn_rate_june)
    exp["ltv_june"] = ltv_june

    ltv_cac_june = None
    if ltv_june is not None and cac_june not in (None, 0):
        ltv_cac_june = ltv_june / cac_june
    exp["ltv_cac_june"] = ltv_cac_june

    payback_months_june = None
    if cac_june is not None and arpu_june not in (None,) and gm not in (None,) and (arpu_june * gm) != 0:
        payback_months_june = cac_june / (arpu_june * gm)
    exp["payback_months_june"] = payback_months_june

    net_burn_june = None
    if jun_expenses_total is not None and jun_end is not None:
        net_burn_june = jun_expenses_total - jun_end
    exp["net_burn_june"] = net_burn_june

    runway_months_june = None
    if jun_cash_end is not None and net_burn_june is not None and net_burn_june > 0:
        runway_months_june = jun_cash_end / net_burn_june
    exp["runway_months_june"] = runway_months_june

    ndr_q2 = None
    if apr_start_mrr not in (None, 0):
        ndr_q2 = (apr_start_mrr + q2_expansion - q2_contraction - q2_churned) / apr_start_mrr
    exp["ndr_q2"] = ndr_q2

    magic_number_q2 = None
    if apr_start_mrr is not None and jun_end is not None:
        growth_arr = (jun_end - apr_start_mrr) * 12.0
        if q1_sm_spend not in (None, 0):
            magic_number_q2 = growth_arr / q1_sm_spend
    exp["magic_number_q2"] = magic_number_q2

    burn_multiple_q2 = None
    if apr_start_mrr is not None and jun_end is not None:
        growth_arr = (jun_end - apr_start_mrr) * 12.0
        if growth_arr not in (None, 0) and q2_net_burn_sum is not None:
            burn_multiple_q2 = q2_net_burn_sum / growth_arr
    exp["burn_multiple_q2"] = burn_multiple_q2

    # SUMMARY CHECKS
    if os.path.isfile(summary_path):
        checks["has_summary"] = True
        summary_json = read_json(summary_path)
        if isinstance(summary_json, dict):
            # Required keys
            required_keys = [
                "as_of", "mrr_june", "arr_run_rate", "mom_growth_june", "arpu_june",
                "cac_june", "churn_rate_june", "ltv_june", "ltv_cac_june",
                "payback_months_june", "net_burn_june", "runway_months_june",
                "ndr_q2", "magic_number_q2", "burn_multiple_q2"
            ]
            keys_present = all(k in summary_json for k in required_keys)
            # as_of must be "2025-06"
            as_of_ok = summary_json.get("as_of") == "2025-06"
            checks["summary_keys_valid"] = keys_present and as_of_ok

            # Compare numeric values within tolerance
            if checks["summary_keys_valid"]:
                nums_ok = True

                def get_json_num_or_none(val):
                    if val is None:
                        return None
                    if isinstance(val, (int, float)):
                        return float(val)
                    try:
                        return float(val)
                    except:
                        return None

                for key in required_keys:
                    if key == "as_of":
                        continue
                    expected_val = exp.get(key)
                    actual_val = get_json_num_or_none(summary_json.get(key))
                    # Additional internal validation for arr_run_rate relation and MoM
                    if expected_val is None and actual_val is None:
                        ok = True
                    else:
                        ok = approx_equal(actual_val, expected_val, rel_tol=0.01, abs_tol=0.01)
                    if not ok:
                        nums_ok = False
                        break

                # Also validate arr_run_rate equals 12*mrr_june and MoM growth based on May/June
                arr_check = True
                mrr_val = get_json_num_or_none(summary_json.get("mrr_june"))
                arr_val = get_json_num_or_none(summary_json.get("arr_run_rate"))
                if mrr_val is not None and arr_val is not None:
                    arr_check = approx_equal(arr_val, mrr_val * 12.0, rel_tol=0.01, abs_tol=0.01)

                mom_check = True
                mom_val = get_json_num_or_none(summary_json.get("mom_growth_june"))
                if may_end not in (None, 0) and jun_end is not None and mom_val is not None:
                    exp_mom = (jun_end - may_end) / may_end
                    mom_check = approx_equal(mom_val, exp_mom, rel_tol=0.01, abs_tol=0.01)

                checks["summary_values_match"] = nums_ok and arr_check and mom_check

    # MONTHLY CSV CHECKS
    if os.path.isfile(monthly_path):
        checks["has_monthly"] = True
        rows = read_csv_rows(monthly_path)
        if rows is not None and isinstance(rows, list) and len(rows) == 6:
            # Check columns
            required_cols = [
                "month", "start_mrr", "new_mrr", "expansion_mrr", "contraction_mrr", "churned_mrr",
                "end_mrr", "net_new_mrr", "customers_start", "new_customers", "lost_customers",
                "customers_end", "sm_spend", "expenses_total", "cash_balance_end",
                "arpu", "churn_rate", "cac", "ltv", "ltv_cac", "payback_months", "net_burn"
            ]
            header_ok = all(required_cols[i] in rows[0] for i in range(len(required_cols)))
            # Validate months and order
            months_ok = True
            for i, r in enumerate(rows):
                m = str(r.get("month", "")).strip()
                if m != required_months[i]:
                    months_ok = False
                    break
            checks["monthly_columns_valid"] = header_ok
            checks["monthly_rows_valid"] = months_ok and len(rows) == 6

            # Validate formulas
            formulas_ok = True
            if checks["monthly_rows_valid"] and checks["monthly_columns_valid"]:
                for r in rows:
                    m = str(r.get("month", "")).strip()
                    # Compute expected derived from the row itself using gross margin from assumptions
                    # Parse base values from the row
                    start_mrr = parse_float(r.get("start_mrr"))
                    new_mrr = parse_float(r.get("new_mrr"))
                    expansion_mrr = parse_float(r.get("expansion_mrr"))
                    contraction_mrr = parse_float(r.get("contraction_mrr"))
                    churned_mrr = parse_float(r.get("churned_mrr"))
                    end_mrr = parse_float(r.get("end_mrr"))
                    customers_start = parse_float(r.get("customers_start"))
                    new_customers = parse_float(r.get("new_customers"))
                    lost_customers = parse_float(r.get("lost_customers"))
                    customers_end = parse_float(r.get("customers_end"))
                    sm_spend = parse_float(r.get("sm_spend"))
                    expenses_total = parse_float(r.get("expenses_total"))

                    # Derived
                    net_new_mrr_exp = None
                    if None not in (new_mrr, expansion_mrr, contraction_mrr, churned_mrr):
                        net_new_mrr_exp = new_mrr + expansion_mrr - contraction_mrr - churned_mrr

                    # Check net_new_mrr
                    net_new_mrr_actual = parse_float(r.get("net_new_mrr"))
                    if not approx_equal(net_new_mrr_actual, net_new_mrr_exp):
                        formulas_ok = False
                        break

                    # Check end_mrr = start_mrr + net_new_mrr
                    if start_mrr is not None and net_new_mrr_exp is not None and end_mrr is not None:
                        if not approx_equal(end_mrr, start_mrr + net_new_mrr_exp):
                            formulas_ok = False
                            break

                    # arpu
                    arpu_exp = None
                    if end_mrr is not None and customers_end not in (None, 0):
                        arpu_exp = end_mrr / customers_end
                    arpu_actual = parse_float(r.get("arpu"))
                    if not approx_equal(arpu_actual, arpu_exp):
                        formulas_ok = False
                        break

                    # churn_rate
                    churn_rate_exp = None
                    if lost_customers is not None and customers_start not in (None, 0):
                        churn_rate_exp = lost_customers / customers_start
                    churn_rate_actual = parse_float(r.get("churn_rate"))
                    if not approx_equal(churn_rate_actual, churn_rate_exp):
                        formulas_ok = False
                        break

                    # cac
                    cac_exp = None
                    if sm_spend is not None and new_customers not in (None, 0):
                        cac_exp = sm_spend / new_customers
                    cac_actual = parse_float(r.get("cac"))
                    if not approx_equal(cac_actual, cac_exp):
                        formulas_ok = False
                        break

                    # ltv
                    ltv_exp = None
                    if arpu_exp is not None and gm not in (None,) and churn_rate_exp not in (None, 0):
                        ltv_exp = arpu_exp * gm * (1.0 / churn_rate_exp)
                    ltv_actual = parse_float(r.get("ltv"))
                    if not approx_equal(ltv_actual, ltv_exp):
                        formulas_ok = False
                        break

                    # ltv_cac
                    ltv_cac_exp = None
                    if ltv_exp is not None and cac_exp not in (None, 0):
                        ltv_cac_exp = ltv_exp / cac_exp
                    ltv_cac_actual = parse_float(r.get("ltv_cac"))
                    if not approx_equal(ltv_cac_actual, ltv_cac_exp):
                        formulas_ok = False
                        break

                    # payback_months
                    payback_exp = None
                    if cac_exp is not None and arpu_exp not in (None,) and gm not in (None,) and (arpu_exp * gm) != 0:
                        payback_exp = cac_exp / (arpu_exp * gm)
                    payback_actual = parse_float(r.get("payback_months"))
                    if not approx_equal(payback_actual, payback_exp):
                        formulas_ok = False
                        break

                    # net_burn
                    net_burn_exp = None
                    if expenses_total is not None and end_mrr is not None:
                        net_burn_exp = expenses_total - end_mrr
                    net_burn_actual = parse_float(r.get("net_burn"))
                    if not approx_equal(net_burn_actual, net_burn_exp):
                        formulas_ok = False
                        break

            checks["monthly_formulas_valid"] = formulas_ok

    # REPORT CHECKS
    if os.path.isfile(report_path):
        checks["has_report"] = True
        content = read_text(report_path) or ""
        lower = content.lower()
        required_terms = [
            "benchmarks",
            "stage assessment",
            "recommendations",
            "risks",
            "ndr",
            "magic number",
            "burn multiple",
            "cac payback",
            "runway",
        ]
        checks["report_has_required_terms"] = all(term in lower for term in required_terms)

    # Compute reward as average of passed checks (only output-dependent checks are included)
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline: if output directory missing or no artifacts, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    any_artifact = False
    for p in [summary_path, monthly_path, report_path]:
        if os.path.isfile(p):
            any_artifact = True
            break
    if not output_exists or not any_artifact:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()