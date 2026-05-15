import json
import os
import sys
import csv
import math
from typing import Any, Dict, List, Tuple, Optional

def parse_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "" or s.lower() in {"na", "nan", "none", "null"}:
        return None
    # Strip common symbols
    bad = set("$,%")
    s2 = "".join(ch for ch in s if (ch.isdigit() or ch in ".-eE"))
    if s2 == "" or s2 == "-" or s2 == ".":
        # fallback to original if removing symbols empties it
        s2 = s
    try:
        return float(s2)
    except:
        return None

def load_csv_by_month(path: str, key_field: str = "month") -> Dict[str, Dict[str, Any]]:
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # try common month field names
            key = row.get(key_field) or row.get("period") or row.get("date") or row.get("month")
            if key is None:
                # skip if no key
                continue
            key = key.strip()
            data[key] = row
    return data

def load_cohorts_csv(path: str) -> Dict[str, Dict[str, Optional[float]]]:
    res: Dict[str, Dict[str, Optional[float]]] = {}
    if not os.path.isfile(path):
        return res
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Expect columns like: cohort,m0,m1,m3,m6 (names may vary in case)
        # Normalize headers
        field_map = {}
        for field in reader.fieldnames or []:
            low = field.strip().lower()
            field_map[low] = field
        cohort_key = field_map.get("cohort")
        m0_key = field_map.get("m0")
        m1_key = field_map.get("m1")
        m3_key = field_map.get("m3")
        m6_key = field_map.get("m6")
        for row in reader:
            cohort = (row.get(cohort_key) if cohort_key else None) or row.get("cohort")
            if not cohort:
                continue
            vals = {
                "m0": parse_float(row.get(m0_key) if m0_key else row.get("m0")),
                "m1": parse_float(row.get(m1_key) if m1_key else row.get("m1")),
                "m3": parse_float(row.get(m3_key) if m3_key else row.get("m3")),
                "m6": parse_float(row.get(m6_key) if m6_key else row.get("m6")),
            }
            res[cohort] = vals
    return res

def rel_tol_ratio(expected: float, got: float) -> bool:
    # For ratios: 1% relative OR 0.02 absolute, whichever is larger
    if expected is None or got is None:
        return False
    if math.isnan(expected) or math.isnan(got):
        return False
    if expected == 0:
        return abs(got) <= 0.02
    tol = max(0.01 * abs(expected), 0.02)
    return abs(got - expected) <= tol

def rel_tol_dollar(expected: float, got: float) -> bool:
    # For dollar amounts: 2% relative
    if expected is None or got is None:
        return False
    if math.isnan(expected) or math.isnan(got):
        return False
    if expected == 0:
        # accept small absolute noise for zero
        return abs(got) <= 0.01
    tol = 0.02 * abs(expected)
    return abs(got - expected) <= tol

def close_numeric(expected: Optional[float], got: Any, is_dollar: bool) -> bool:
    if expected is None:
        return False
    g = parse_float(got)
    if g is None:
        return False
    if is_dollar:
        return rel_tol_dollar(expected, g)
    else:
        return rel_tol_ratio(expected, g)

def safe_div(n: float, d: float) -> Optional[float]:
    if d == 0:
        return None
    return n / d

def to_margin_fraction(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    # If value looks like percentage (e.g., 80 or 80.0), convert to 0-1
    if x > 1.0:
        return x / 100.0
    return x

def compute_expected(workspace_root: str) -> Dict[str, Any]:
    input_dir = os.path.join(workspace_root, "input")
    mrr_path = os.path.join(input_dir, "mrr_components.csv")
    cust_path = os.path.join(input_dir, "customers.csv")
    sm_path = os.path.join(input_dir, "sales_marketing.csv")
    cash_path = os.path.join(input_dir, "cash.csv")
    cohorts_path = os.path.join(input_dir, "cohorts.csv")

    mrr = load_csv_by_month(mrr_path)
    customers = load_csv_by_month(cust_path)
    sm = load_csv_by_month(sm_path)
    cash = load_csv_by_month(cash_path)
    cohorts = load_cohorts_csv(cohorts_path)

    # Extract required months
    m_2026_03 = "2026-03"
    m_2026_02 = "2026-02"
    m_2025_12 = "2025-12"
    m_2025_10 = "2025-10"
    q4_months = ["2025-10", "2025-11", "2025-12"]
    q1_months = ["2026-01", "2026-02", "2026-03"]

    # Helper to get float from mrr csv
    def mrr_field(month: str, key: str) -> Optional[float]:
        row = mrr.get(month)
        if not row:
            return None
        return parse_float(row.get(key))

    def cust_field(month: str, key: str) -> Optional[float]:
        row = customers.get(month)
        if not row:
            return None
        return parse_float(row.get(key))

    def sm_field(month: str, key: str) -> Optional[float]:
        row = sm.get(month)
        if not row:
            return None
        return parse_float(row.get(key))

    def cash_field(month: str, key: str) -> Optional[float]:
        row = cash.get(month)
        if not row:
            return None
        return parse_float(row.get(key))

    # Compute base values
    end_mrr_03 = mrr_field(m_2026_03, "ending_mrr")
    end_mrr_02 = mrr_field(m_2026_02, "ending_mrr")
    end_mrr_2510 = mrr_field(m_2025_10, "ending_mrr")
    arr_03 = end_mrr_03 * 12 if end_mrr_03 is not None else None

    mom_growth = None
    if end_mrr_03 is not None and end_mrr_02:
        if end_mrr_02 != 0:
            mom_growth = (end_mrr_03 - end_mrr_02) / end_mrr_02
        else:
            mom_growth = None

    cmgr_6m = None
    if end_mrr_03 is not None and end_mrr_2510 and end_mrr_2510 > 0:
        try:
            cmgr_6m = (end_mrr_03 / end_mrr_2510) ** (1.0 / 5.0) - 1.0
        except Exception:
            cmgr_6m = None

    start_mrr_03 = mrr_field(m_2026_03, "starting_mrr")
    exp_mrr_03 = mrr_field(m_2026_03, "expansion_mrr")
    contr_mrr_03 = mrr_field(m_2026_03, "contraction_mrr")
    churned_mrr_03 = mrr_field(m_2026_03, "churned_mrr")

    ndr = None
    gdr = None
    if start_mrr_03 and start_mrr_03 != 0 and exp_mrr_03 is not None and contr_mrr_03 is not None and churned_mrr_03 is not None:
        ndr = (start_mrr_03 + exp_mrr_03 - contr_mrr_03 - churned_mrr_03) / start_mrr_03
        gdr = (start_mrr_03 - contr_mrr_03 - churned_mrr_03) / start_mrr_03

    # CAC
    new_customers_03 = cust_field(m_2026_03, "new_customers")
    sm_spend_03 = sm_field(m_2026_03, "spend") or sm_field(m_2026_03, "sales_marketing_spend") or sm_field(m_2026_03, "s&m_spend")
    cac = None
    if sm_spend_03 is not None and new_customers_03 and new_customers_03 != 0:
        cac = sm_spend_03 / new_customers_03

    # LTV related
    avg_arpu_03 = cust_field(m_2026_03, "avg_arpu")
    gm_pct_03_raw = cust_field(m_2026_03, "gross_margin_pct")
    gm_pct_03 = to_margin_fraction(gm_pct_03_raw) if gm_pct_03_raw is not None else None
    churned_customers_03 = cust_field(m_2026_03, "churned_customers")
    customers_start_03 = cust_field(m_2026_03, "customers_start")
    monthly_logo_churn_rate = None
    if churned_customers_03 is not None and customers_start_03 and customers_start_03 != 0:
        monthly_logo_churn_rate = churned_customers_03 / customers_start_03

    ltv = None
    if avg_arpu_03 is not None and gm_pct_03 is not None and monthly_logo_churn_rate and monthly_logo_churn_rate != 0:
        ltv = avg_arpu_03 * gm_pct_03 * (1.0 / monthly_logo_churn_rate)

    ltv_to_cac = None
    if ltv is not None and cac and cac != 0:
        ltv_to_cac = ltv / cac

    payback_months = None
    if cac is not None and avg_arpu_03 is not None and gm_pct_03 is not None and (avg_arpu_03 * gm_pct_03) != 0:
        payback_months = cac / (avg_arpu_03 * gm_pct_03)

    # Burn multiple Q1 2026
    def net_burn(month: str) -> Optional[float]:
        te = cash_field(month, "total_expenses")
        rr = cash_field(month, "revenue_recognized")
        if te is None or rr is None:
            return None
        return te - rr

    net_burn_q1_vals = [net_burn(m) for m in q1_months]
    sum_net_burn_q1 = None
    if all(v is not None for v in net_burn_q1_vals):
        sum_net_burn_q1 = sum(v for v in net_burn_q1_vals if v is not None)

    end_mrr_2512 = mrr_field(m_2025_12, "ending_mrr")
    arr_2512 = end_mrr_2512 * 12 if end_mrr_2512 is not None else None
    net_new_arr_q1 = None
    if arr_03 is not None and arr_2512 is not None:
        net_new_arr_q1 = arr_03 - arr_2512

    burn_multiple_q1 = None
    if sum_net_burn_q1 is not None and net_new_arr_q1 and net_new_arr_q1 != 0:
        burn_multiple_q1 = sum_net_burn_q1 / net_new_arr_q1

    # Rule of 40 monthly
    rr_03 = cash_field(m_2026_03, "revenue_recognized")
    te_03 = cash_field(m_2026_03, "total_expenses")
    profit_margin_pct = None
    if rr_03 is not None and te_03 is not None:
        if rr_03 != 0:
            profit_margin_pct = ((rr_03 - te_03) / rr_03) * 100.0
        else:
            profit_margin_pct = None

    mom_growth_pct = None
    if mom_growth is not None:
        mom_growth_pct = mom_growth * 100.0

    rule_of_40 = None
    if mom_growth_pct is not None and profit_margin_pct is not None:
        rule_of_40 = mom_growth_pct + profit_margin_pct

    # Magic number Q1 2026
    sm_q4_vals = []
    for m in q4_months:
        v = sm_field(m, "spend") or sm_field(m, "sales_marketing_spend") or sm_field(m, "s&m_spend")
        if v is None:
            sm_q4_vals.append(None)
        else:
            sm_q4_vals.append(v)
    sm_q4_sum = None
    if all(v is not None for v in sm_q4_vals) and len(sm_q4_vals) == 3:
        sm_q4_sum = sum(v for v in sm_q4_vals if v is not None)
    magic_number = None
    if net_new_arr_q1 is not None and sm_q4_sum and sm_q4_sum != 0:
        magic_number = net_new_arr_q1 / sm_q4_sum

    # Runway months
    cash_balance_03 = cash_field(m_2026_03, "cash_balance")
    net_burn_03 = net_burn(m_2026_03)
    runway_months = None
    if cash_balance_03 is not None and net_burn_03 and net_burn_03 > 0:
        runway_months = cash_balance_03 / net_burn_03

    # Customers for cross-check in investor_update
    customers_end_03 = cust_field(m_2026_03, "customers_end")
    # Compose expected dict
    expected = {
        "mrr": end_mrr_03,
        "arr": arr_03,
        "mom_growth": mom_growth,
        "cmgr_6m": cmgr_6m,
        "ndr": ndr,
        "gdr": gdr,
        "cac": cac,
        "ltv": ltv,
        "ltv_to_cac": ltv_to_cac,
        "payback_months": payback_months,
        "burn_multiple_q1_2026": burn_multiple_q1,
        "rule_of_40_monthly": rule_of_40,
        "magic_number_q1_2026": magic_number,
        "runway_months": runway_months,
        "mrr_2026_02": end_mrr_02,
        "arr_2025_12": arr_2512,
        "net_burn_2026_03": net_burn_03,
        "cash_balance_2026_03": cash_balance_03,
        "customers_end_2026_03": customers_end_03,
        "new_customers_2026_03": new_customers_03,
        "churned_customers_2026_03": churned_customers_03,
        "avg_arpu_2026_03": avg_arpu_03,
        "gm_frac_2026_03": gm_pct_03,
        "cohorts": cohorts
    }
    return expected

def parse_metrics_summary(path: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    if not os.path.isfile(path):
        return False, None, "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False, None, "not_object"
        return True, data, ""
    except Exception as e:
        return False, None, f"json_error:{e}"

# Minimal YAML parser for simple nested structures (dicts and lists)
def parse_simple_yaml(text: str) -> Any:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    # Stack of (indent, container, key_for_next_if_any)
    root: Any = None
    stack: List[Tuple[int, Any]] = []

    def parse_scalar(s: str) -> Any:
        s = s.strip()
        # strip quotes if present
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            s = s[1:-1]
        # parse booleans/null
        low = s.lower()
        if low in ("null", "none"):
            return None
        if low in ("true", "false"):
            return True if low == "true" else False
        # parse number
        v = parse_float(s)
        if v is not None and s.replace(".", "", 1).replace("-", "", 1).isdigit() or ("e" in s.lower()):
            # If parse_float succeeded and string looks numeric, return number
            return v
        # else return string
        return s

    def current_container() -> Any:
        return stack[-1][1] if stack else None

    def push(indent: int, container: Any):
        stack.append((indent, container))

    def pop_to_indent(indent: int):
        while stack and stack[-1][0] >= indent:
            stack.pop()

    for raw in lines:
        line = raw
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Determine current container
        if not stack:
            # initialize root
            if line.lstrip().startswith("- "):
                root = []
                push(indent, root)
            else:
                root = {}
                push(indent, root)
        # Adjust stack to current indent
        # For same-level entries, pop containers with indent >= current indent
        pop_to_indent(indent + 1)  # keep parent with lower indent

        cont = current_container()
        stripped = line.strip()

        if stripped.startswith("- "):
            # list item
            item_str = stripped[2:].strip()
            if isinstance(cont, dict):
                # if current container is dict, we need a list under the last key; not tracked here
                # Create a default list at this indent if not present by creating a new list in root if needed
                # This minimal parser expects that a preceding key introduced the list container
                # If not, we fallback by creating a list in place if root is None
                pass
            if not isinstance(cont, list):
                # Create a new list under last key of parent dict
                # Find parent dict
                parent = None
                # pop to find dict with less indent
                # Since we popped to indent+1 earlier, get last dict
                for ind, c in reversed(stack):
                    if isinstance(c, dict):
                        parent = c
                        break
                if parent is None:
                    # fallback: treat root as list
                    if root is None or not isinstance(root, list):
                        root = []
                        stack.clear()
                        push(0, root)
                    cont = root
                else:
                    # We cannot know the key here; so skip malformed structure
                    # For our expected files, list items appear under named keys properly
                    pass
            cont = current_container()
            # Ensure cont is list
            if not isinstance(cont, list):
                # Create a new list if possible
                # Find last dict and last key inserted
                # For simplicity, skip creating improper structures
                continue
            # Parse list item
            if ": " in item_str or item_str.endswith(":"):
                # list item is a mapping start
                # e.g., - key: value OR - key:
                # Build a dict and append
                item_obj: Any = {}
                cont.append(item_obj)
                # If "key: value" on same line, assign
                if item_str.endswith(":"):
                    key = item_str[:-1].strip()
                    # next indented lines will fill this dict
                    push(indent + 2, item_obj)
                else:
                    key, val = item_str.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    item_obj[key] = parse_scalar(val) if val != "" else None
                    push(indent + 2, item_obj)
            elif item_str == "":
                # empty scalar item
                cont.append(None)
            else:
                cont.append(parse_scalar(item_str))
        else:
            # mapping entry
            if ": " in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Ensure container is dict
                if not isinstance(cont, dict):
                    # convert if possible
                    # find parent dict
                    parent = None
                    for ind, c in reversed(stack):
                        if isinstance(c, dict):
                            parent = c
                            break
                    if parent is None:
                        continue
                    cont = parent
                if val == "":
                    # start nested container on next lines
                    # Decide whether it's list or dict in future lines; for now, create dict
                    new_map: Any = {}
                    cont[key] = new_map
                    push(indent + 2, new_map)
                else:
                    cont[key] = parse_scalar(val)
            elif stripped.endswith(":"):
                key = stripped[:-1].strip()
                if not isinstance(cont, dict):
                    continue
                new_map: Any = {}
                cont[key] = new_map
                push(indent + 2, new_map)
            else:
                # scalar at root - ignore
                pass

    return root

def get_from_path(obj: Any, path: List[str]) -> Any:
    cur = obj
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur

def count_list_length_under(obj: Any, key: str) -> int:
    if not isinstance(obj, dict):
        return 0
    v = obj.get(key)
    if isinstance(v, list):
        return len(v)
    return 0

def compare_cohort_retention(input_cohorts: Dict[str, Dict[str, Optional[float]]], out_path: str) -> Tuple[bool, Dict[str, bool], Dict[str, float]]:
    checks_ok = True
    per_cohort_ok: Dict[str, bool] = {}
    expected_spots: Dict[str, float] = {}
    if not os.path.isfile(out_path):
        return False, per_cohort_ok, expected_spots
    # Load output cohorts retention
    out_rows: Dict[str, Dict[str, str]] = {}
    with open(out_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        required_hdrs = ["cohort", "m0_retention", "m1_retention", "m3_retention", "m6_retention"]
        if any(h not in headers for h in required_hdrs):
            return False, per_cohort_ok, expected_spots
        for row in reader:
            cohort = row.get("cohort") or row.get("Cohort") or row.get("COHORT")
            if cohort is None:
                continue
            out_rows[cohort] = row

    # Validate at least those cohorts present and values match
    for cohort, snaps in input_cohorts.items():
        if cohort not in out_rows:
            per_cohort_ok[cohort] = False
            checks_ok = False
            continue
        m0 = snaps.get("m0")
        expected = {}
        for mark in ["m0", "m1", "m3", "m6"]:
            val = snaps.get(mark)
            if m0 is None or m0 == 0 or val is None:
                expected[mark] = None
            else:
                expected[mark] = round(val / m0, 2)
        row = out_rows[cohort]
        row_ok = True
        for mark in ["m0", "m1", "m3", "m6"]:
            key = f"{mark}_retention"
            out_val_str = row.get(key) if row.get(key) is not None else row.get(key.capitalize())
            if expected[mark] is None:
                # Expect blank
                ok = (out_val_str is None) or (str(out_val_str).strip() == "")
            else:
                # Compare numeric within 0.01
                out_v = parse_float(out_val_str)
                ok = out_v is not None and abs(out_v - expected[mark]) <= 0.01
            if not ok:
                row_ok = False
        per_cohort_ok[cohort] = row_ok
        if not row_ok:
            checks_ok = False

    # Spot-checks for specific cohorts if present
    # 2026-01 m1 retention expected ~ value
    if "2026-01" in input_cohorts:
        snaps = input_cohorts["2026-01"]
        m0 = snaps.get("m0")
        m1 = snaps.get("m1")
        if m0 and m1 is not None and m0 != 0:
            expected_spots["2026-01_m1"] = round(m1 / m0, 2)
    if "2025-11" in input_cohorts:
        snaps = input_cohorts["2025-11"]
        m0 = snaps.get("m0"); m3 = snaps.get("m3")
        if m0 and m3 is not None and m0 != 0:
            expected_spots["2025-11_m3"] = round(m3 / m0, 2)

    return checks_ok, per_cohort_ok, expected_spots

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {}

    # Initialize all checks to False
    check_names = [
        # metrics_summary.json checks
        "metrics_summary_exists",
        "metrics_summary_schema",
        "ms_period_ok",
        "ms_mrr_ok",
        "ms_arr_ok",
        "ms_mom_growth_ok",
        "ms_cmgr_ok",
        "ms_ndr_ok",
        "ms_gdr_ok",
        "ms_cac_ok",
        "ms_ltv_ok",
        "ms_ltv_to_cac_ok",
        "ms_payback_ok",
        "ms_burn_multiple_ok",
        "ms_rule40_ok",
        "ms_magic_number_ok",
        "ms_runway_ok",
        # investor_update.yaml checks
        "investor_update_exists",
        "investor_yaml_valid",
        "investor_required_keys",
        "investor_min_lists",
        "investor_arr_current_ok",
        "investor_arr_prior_delta_ok",
        "investor_mrr_current_ok",
        "investor_mrr_growth_ok",
        "investor_ndr_ok",
        "investor_burn_rate_ok",
        "investor_runway_ok",
        "investor_cash_balance_ok",
        "investor_customers_ok",
        # cohort_analysis.csv checks
        "cohort_exists",
        "cohort_header_ok",
        "cohort_at_least_4",
        "cohort_values_match",
        "cohort_spot_2026_01_m1_ok",
        "cohort_spot_2025_11_m3_ok",
        # pulse_diagnostic.md checks
        "pulse_exists",
        "pulse_has_headings",
        "pulse_mentions_months",
        "pulse_mentions_ndr_churn",
        "pulse_experiment_has_success_and_kill",
    ]
    for name in check_names:
        checks[name] = False

    # Compute expected from inputs
    expected = compute_expected(workspace_root)

    # 1) metrics_summary.json
    ms_path = os.path.join(output_dir, "metrics_summary.json")
    ms_ok, ms_obj, _ = parse_metrics_summary(ms_path)
    if ms_ok and isinstance(ms_obj, dict):
        checks["metrics_summary_exists"] = True
        # Validate schema and types
        required_keys = [
            "period", "mrr", "arr", "mom_growth", "cmgr_6m", "ndr", "gdr", "cac",
            "ltv", "ltv_to_cac", "payback_months", "burn_multiple_q1_2026",
            "rule_of_40_monthly", "magic_number_q1_2026", "runway_months"
        ]
        schema_ok = True
        for k in required_keys:
            if k not in ms_obj:
                schema_ok = False
        if ms_obj.get("period") == "2026-03":
            checks["ms_period_ok"] = True
        # Check numeric types (numbers not strings) for metrics
        # period is string key; ignore numeric check for it
        nums_ok = True
        for k in required_keys:
            if k == "period":
                continue
            v = ms_obj.get(k)
            if not isinstance(v, (int, float)):
                # allow strings that parse to float? Spec demands numbers; so fail
                nums_ok = False
        if schema_ok and nums_ok:
            checks["metrics_summary_schema"] = True

        # Compare values with expected
        if expected.get("mrr") is not None and close_numeric(expected["mrr"], ms_obj.get("mrr"), is_dollar=True):
            checks["ms_mrr_ok"] = True
        if expected.get("arr") is not None and close_numeric(expected["arr"], ms_obj.get("arr"), is_dollar=True):
            checks["ms_arr_ok"] = True
        if expected.get("mom_growth") is not None and close_numeric(expected["mom_growth"], ms_obj.get("mom_growth"), is_dollar=False):
            checks["ms_mom_growth_ok"] = True
        if expected.get("cmgr_6m") is not None and close_numeric(expected["cmgr_6m"], ms_obj.get("cmgr_6m"), is_dollar=False):
            checks["ms_cmgr_ok"] = True
        if expected.get("ndr") is not None and close_numeric(expected["ndr"], ms_obj.get("ndr"), is_dollar=False):
            checks["ms_ndr_ok"] = True
        if expected.get("gdr") is not None and close_numeric(expected["gdr"], ms_obj.get("gdr"), is_dollar=False):
            checks["ms_gdr_ok"] = True
        if expected.get("cac") is not None and close_numeric(expected["cac"], ms_obj.get("cac"), is_dollar=True):
            checks["ms_cac_ok"] = True
        if expected.get("ltv") is not None and close_numeric(expected["ltv"], ms_obj.get("ltv"), is_dollar=True):
            checks["ms_ltv_ok"] = True
        if expected.get("ltv_to_cac") is not None and close_numeric(expected["ltv_to_cac"], ms_obj.get("ltv_to_cac"), is_dollar=False):
            checks["ms_ltv_to_cac_ok"] = True
        if expected.get("payback_months") is not None and close_numeric(expected["payback_months"], ms_obj.get("payback_months"), is_dollar=False):
            checks["ms_payback_ok"] = True
        if expected.get("burn_multiple_q1_2026") is not None and close_numeric(expected["burn_multiple_q1_2026"], ms_obj.get("burn_multiple_q1_2026"), is_dollar=False):
            checks["ms_burn_multiple_ok"] = True
        if expected.get("rule_of_40_monthly") is not None and close_numeric(expected["rule_of_40_monthly"], ms_obj.get("rule_of_40_monthly"), is_dollar=False):
            checks["ms_rule40_ok"] = True
        if expected.get("magic_number_q1_2026") is not None and close_numeric(expected["magic_number_q1_2026"], ms_obj.get("magic_number_q1_2026"), is_dollar=False):
            checks["ms_magic_number_ok"] = True
        if expected.get("runway_months") is not None and close_numeric(expected["runway_months"], ms_obj.get("runway_months"), is_dollar=False):
            checks["ms_runway_ok"] = True

    # 2) investor_update.yaml
    iu_path = os.path.join(output_dir, "investor_update.yaml")
    if os.path.isfile(iu_path):
        checks["investor_update_exists"] = True
        try:
            with open(iu_path, "r", encoding="utf-8") as f:
                yaml_text = f.read()
            iu_obj = parse_simple_yaml(yaml_text)
            if isinstance(iu_obj, dict):
                checks["investor_yaml_valid"] = True
                # Required keys check via presence
                required_paths = [
                    ["metrics", "arr", "current"],
                    ["metrics", "arr", "prior_month"],
                    ["metrics", "arr", "delta"],
                    ["metrics", "mrr", "current"],
                    ["metrics", "mrr", "growth_mom"],
                    ["metrics", "customers", "total"],
                    ["metrics", "customers", "new"],
                    ["metrics", "customers", "churned"],
                    ["metrics", "ndr"],
                    ["metrics", "burn_rate"],
                    ["metrics", "runway_months"],
                    ["metrics", "cash_balance"],
                ]
                have_all = True
                for p in required_paths:
                    v = get_from_path(iu_obj, p)
                    if v is None:
                        have_all = False
                        break
                # Also top-level arrays
                highlights_len = count_list_length_under(iu_obj, "highlights")
                wins_len = count_list_length_under(iu_obj, "wins")
                challenges_len = count_list_length_under(iu_obj, "challenges")
                next_len = count_list_length_under(iu_obj, "next_month_priorities")
                asks_len = count_list_length_under(iu_obj, "asks")
                if have_all:
                    checks["investor_required_keys"] = True
                if highlights_len >= 2 and next_len >= 3 and asks_len >= 2:
                    checks["investor_min_lists"] = True

                # Cross-check values with expected and metrics_summary
                # Load ms_obj again for cross reference
                ms = ms_obj if ms_ok else {}
                # ARR current
                arr_current = get_from_path(iu_obj, ["metrics", "arr", "current"])
                if expected.get("arr") is not None and close_numeric(expected["arr"], arr_current, is_dollar=True):
                    checks["investor_arr_current_ok"] = True
                # ARR prior = 12 * mrr_2026_02
                prior_expected = None
                if expected.get("mrr_2026_02") is not None:
                    prior_expected = expected["mrr_2026_02"] * 12.0
                arr_prior = get_from_path(iu_obj, ["metrics", "arr", "prior_month"])
                arr_delta = get_from_path(iu_obj, ["metrics", "arr", "delta"])
                delta_expected = None
                if expected.get("arr") is not None and prior_expected is not None:
                    delta_expected = expected["arr"] - prior_expected
                prior_ok = prior_expected is not None and close_numeric(prior_expected, arr_prior, is_dollar=True)
                delta_ok = delta_expected is not None and close_numeric(delta_expected, arr_delta, is_dollar=True)
                if prior_ok and delta_ok:
                    checks["investor_arr_prior_delta_ok"] = True
                # MRR current
                mrr_current = get_from_path(iu_obj, ["metrics", "mrr", "current"])
                if expected.get("mrr") is not None and close_numeric(expected["mrr"], mrr_current, is_dollar=True):
                    checks["investor_mrr_current_ok"] = True
                # MRR MoM growth
                mrr_growth = get_from_path(iu_obj, ["metrics", "mrr", "growth_mom"])
                if expected.get("mom_growth") is not None and close_numeric(expected["mom_growth"], mrr_growth, is_dollar=False):
                    checks["investor_mrr_growth_ok"] = True
                # NDR
                ndr_v = get_from_path(iu_obj, ["metrics", "ndr"])
                if expected.get("ndr") is not None and close_numeric(expected["ndr"], ndr_v, is_dollar=False):
                    checks["investor_ndr_ok"] = True
                # Burn rate (net burn for 2026-03)
                burn_rate_v = get_from_path(iu_obj, ["metrics", "burn_rate"])
                if expected.get("net_burn_2026_03") is not None and close_numeric(expected["net_burn_2026_03"], burn_rate_v, is_dollar=True):
                    checks["investor_burn_rate_ok"] = True
                # Runway months
                runway_v = get_from_path(iu_obj, ["metrics", "runway_months"])
                if expected.get("runway_months") is not None and close_numeric(expected["runway_months"], runway_v, is_dollar=False):
                    checks["investor_runway_ok"] = True
                # Cash balance
                cash_bal_v = get_from_path(iu_obj, ["metrics", "cash_balance"])
                if expected.get("cash_balance_2026_03") is not None and close_numeric(expected["cash_balance_2026_03"], cash_bal_v, is_dollar=True):
                    checks["investor_cash_balance_ok"] = True
                # Customers numbers
                cust_total_v = get_from_path(iu_obj, ["metrics", "customers", "total"])
                cust_new_v = get_from_path(iu_obj, ["metrics", "customers", "new"])
                cust_churned_v = get_from_path(iu_obj, ["metrics", "customers", "churned"])
                customers_ok = True
                if expected.get("customers_end_2026_03") is not None:
                    ce = expected["customers_end_2026_03"]
                    if parse_float(cust_total_v) != (ce if ce is None else float(ce)):
                        customers_ok = False
                if expected.get("new_customers_2026_03") is not None:
                    if parse_float(cust_new_v) != float(expected["new_customers_2026_03"]):
                        customers_ok = False
                if expected.get("churned_customers_2026_03") is not None:
                    if parse_float(cust_churned_v) != float(expected["churned_customers_2026_03"]):
                        customers_ok = False
                if customers_ok:
                    checks["investor_customers_ok"] = True
        except Exception:
            # parsing failed
            pass

    # 3) cohort_analysis.csv
    cohort_out_path = os.path.join(output_dir, "cohort_analysis.csv")
    if os.path.isfile(cohort_out_path):
        checks["cohort_exists"] = True
        # Check header
        header_ok = False
        rows = []
        with open(cohort_out_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            expected_header = ["cohort", "m0_retention", "m1_retention", "m3_retention", "m6_retention"]
            header_ok = [h.strip().lower() for h in header] == expected_header
            if header_ok:
                checks["cohort_header_ok"] = True
            for r in reader:
                rows.append(r)
        if len(rows) >= 4:
            checks["cohort_at_least_4"] = True
        # Compare values
        cohorts_in = expected.get("cohorts") or {}
        values_match, per_cohort_ok, spot_expected = compare_cohort_retention(cohorts_in, cohort_out_path)
        if values_match:
            checks["cohort_values_match"] = True
        # Spot checks if applicable
        if "2026-01_m1" in spot_expected:
            # Read out value from file
            with open(cohort_out_path, "r", encoding="utf-8") as f:
                dreader = csv.DictReader(f)
                for row in dreader:
                    if (row.get("cohort") or "").strip() == "2026-01":
                        out_v = parse_float(row.get("m1_retention"))
                        if out_v is not None and abs(out_v - spot_expected["2026-01_m1"]) <= 0.01:
                            checks["cohort_spot_2026_01_m1_ok"] = True
                        break
        else:
            # if not present, leave False as per strict requirement
            pass
        if "2025-11_m3" in spot_expected:
            with open(cohort_out_path, "r", encoding="utf-8") as f:
                dreader = csv.DictReader(f)
                for row in dreader:
                    if (row.get("cohort") or "").strip() == "2025-11":
                        out_v = parse_float(row.get("m3_retention"))
                        if out_v is not None and abs(out_v - spot_expected["2025-11_m3"]) <= 0.01:
                            checks["cohort_spot_2025_11_m3_ok"] = True
                        break

    # 4) pulse_diagnostic.md
    pulse_path = os.path.join(output_dir, "pulse_diagnostic.md")
    if os.path.isfile(pulse_path):
        checks["pulse_exists"] = True
        try:
            with open(pulse_path, "r", encoding="utf-8") as f:
                txt = f.read()
            lines = [ln.strip() for ln in txt.splitlines()]
            # headings lines start with exactly the label
            need_heads = ["Pattern", "Upstream", "Leverage", "So-What", "Experiment"]
            heads_ok = all(any(l.startswith(h) for l in lines) for h in need_heads)
            if heads_ok:
                checks["pulse_has_headings"] = True
            # mentions months
            months_ok = ("2026-02" in txt) and ("2026-03" in txt)
            if months_ok:
                checks["pulse_mentions_months"] = True
            # mentions NDR and churn
            if ("NDR" in txt) and ("churn" in txt.lower()):
                checks["pulse_mentions_ndr_churn"] = True
            # experiment contains success metric and kill criteria
            # Extract Experiment section text
            exp_text = ""
            in_exp = False
            for ln in lines:
                if any(ln.startswith(h) for h in need_heads):
                    in_exp = ln.startswith("Experiment")
                else:
                    if in_exp:
                        exp_text += ln + "\n"
            exp_ok = ("success" in exp_text.lower()) and ("kill" in exp_text.lower())
            if exp_ok:
                checks["pulse_experiment_has_success_and_kill"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Enforce no-op baseline: if output directory missing or all four key artifacts missing -> reward 0
    required_artifacts = [
        os.path.join(output_dir, "metrics_summary.json"),
        os.path.join(output_dir, "investor_update.yaml"),
        os.path.join(output_dir, "cohort_analysis.csv"),
        os.path.join(output_dir, "pulse_diagnostic.md"),
    ]
    if not any(os.path.isfile(p) for p in required_artifacts):
        reward = 0.0
    else:
        # Scale reward between 0 and 1
        reward = passed / total if total > 0 else 0.0

    # Print JSON
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()