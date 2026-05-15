import csv
import json
import os
import sys
from typing import Dict, Any, Tuple, List

def parse_yaml_minimal(path: str) -> Dict[str, Any]:
    # Minimal YAML parser for simple key: value and nested maps by indentation
    data: Dict[str, Any] = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    # Stack of (indent_level, current_dict)
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, data)]
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        # Find parent context by indent
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            # reset to root if malformed indentation
            stack = [(-1, data)]
        current = stack[-1][1]
        if ":" not in stripped:
            continue
        key_part, val_part = stripped.split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            # nested dict
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            # remove inline comments
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            # strip quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                parsed: Any = val[1:-1]
            else:
                # Try parse int, then float, else string
                try:
                    if "." in val:
                        parsed = float(val)
                    else:
                        parsed = int(val)
                except ValueError:
                    # handle booleans true/false
                    low = val.lower()
                    if low == "true":
                        parsed = True
                    elif low == "false":
                        parsed = False
                    else:
                        parsed = val
            current[key] = parsed
    return data

def load_csv_dicts(path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: v for k, v in r.items()})
    return rows

def month_to_tuple(ym: str) -> Tuple[int, int]:
    y, m = ym.split("-")
    return int(y), int(m)

def month_range(start_ym: str, end_ym: str) -> List[str]:
    y1, m1 = month_to_tuple(start_ym)
    y2, m2 = month_to_tuple(end_ym)
    res = []
    y, m = y1, m1
    while (y < y2) or (y == y2 and m <= m2):
        res.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return res

def to_float(s: str) -> float:
    try:
        return float(s)
    except Exception:
        return 0.0

def to_int_nearest(x: float) -> int:
    try:
        return int(round(x))
    except Exception:
        return 0

def section_class(section: str) -> str:
    if not section:
        return ""
    s = section.strip().lower()
    if "cogs" in s or "cost of goods" in s:
        return "cogs"
    if "op ex" in s or "opex" in s or "operating exp" in s or "operating expenses" in s:
        return "opex"
    if "revenue" in s or "income" in s:
        return "revenue"
    return ""

def coerce_bool_str(s: str) -> Any:
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    v = s.strip().lower()
    if v in ("true", "t", "1", "yes"):
        return True
    if v in ("false", "f", "0", "no"):
        return False
    return None

def parse_variance_pct_value(val: Any) -> Tuple[bool, Any]:
    # returns (is_na, numeric_value or None)
    if isinstance(val, (int, float)):
        return False, float(val)
    if not isinstance(val, str):
        return False, None
    v = val.strip()
    if v == "N/A":
        return True, None
    if v.endswith("%"):
        v = v[:-1].strip()
    try:
        return False, float(v)
    except Exception:
        return False, None

def almost_equal_int(a: int, b: int, tol: int = 1) -> bool:
    return abs(int(a) - int(b)) <= tol

def almost_equal_float(a: float, b: float, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def compute_expected(workspace_root: str) -> Dict[str, Any]:
    input_dir = os.path.join(workspace_root, "input")
    # Load inputs
    budget_rows = load_csv_dicts(os.path.join(input_dir, "budget.csv"))
    actual_rows = load_csv_dicts(os.path.join(input_dir, "actuals.csv"))
    mapping_rows = load_csv_dicts(os.path.join(input_dir, "mapping.csv"))
    period_yaml = parse_yaml_minimal(os.path.join(input_dir, "period.yaml"))

    period = str(period_yaml.get("period", "")).strip()
    period_type = str(period_yaml.get("period_type", "")).strip()
    ytd_start = str(period_yaml.get("ytd_start", "")).strip()

    mat = period_yaml.get("materiality", {}) if isinstance(period_yaml.get("materiality"), dict) else {}
    mat_revenue = mat.get("revenue", {}) if isinstance(mat.get("revenue"), dict) else {}
    mat_expense = mat.get("expense", {}) if isinstance(mat.get("expense"), dict) else {}
    mat_ebitda = mat.get("ebitda", {}) if isinstance(mat.get("ebitda"), dict) else {}

    thresholds = {
        "revenue": {
            "amount": float(mat_revenue.get("amount", 0)),
            "pct": float(mat_revenue.get("pct", 0)),
        },
        "expense": {
            "amount": float(mat_expense.get("amount", 0)),
            "pct": float(mat_expense.get("pct", 0)),
        },
        "ebitda": {
            "amount": float(mat_ebitda.get("amount", 0)),
            "pct": float(mat_ebitda.get("pct", 0)),
        },
    }

    # Build account mapping
    # raw_account -> {line_item, section, subcategory, kind}
    acct_map: Dict[str, Dict[str, str]] = {}
    line_meta: Dict[str, Dict[str, str]] = {}
    for r in mapping_rows:
        raw = (r.get("raw_account") or "").strip()
        li = (r.get("line_item") or "").strip()
        sec = (r.get("section") or "").strip()
        sub = (r.get("subcategory") or "").strip()
        kind = (r.get("kind") or "").strip().lower()
        acct_map[raw] = {"line_item": li, "section": sec, "subcategory": sub, "kind": kind}
        # Record meta by line_item (first wins)
        if li and li not in line_meta:
            line_meta[li] = {"section": sec, "subcategory": sub, "kind": kind}

    # Helper to aggregate by line_item for a set of months
    def aggregate(rows: List[Dict[str, str]], months: List[str]) -> Dict[str, float]:
        sums: Dict[str, float] = {}
        mset = set(months)
        for r in rows:
            date = (r.get("date") or "").strip()
            if date not in mset:
                continue
            raw_account = (r.get("account") or "").strip()
            amt = to_float(r.get("amount") or "0")
            mp = acct_map.get(raw_account)
            if not mp:
                # Skip accounts without mapping
                continue
            li = mp["line_item"]
            if not li:
                continue
            sums[li] = sums.get(li, 0.0) + amt
            # ensure meta present
            if li not in line_meta:
                line_meta[li] = {"section": mp.get("section",""), "subcategory": mp.get("subcategory",""), "kind": (mp.get("kind") or "").lower()}
        return sums

    # Compute monthly and YTD ranges
    monthly_months = [period]
    ytd_months = month_range(ytd_start, period)

    budget_monthly = aggregate(budget_rows, monthly_months)
    actual_monthly = aggregate(actual_rows, monthly_months)
    budget_ytd = aggregate(budget_rows, ytd_months)
    actual_ytd = aggregate(actual_rows, ytd_months)

    # Collect all line_items from mapping (to include lines even if zeroed)
    all_line_items = set(line_meta.keys())

    # Derived totals support: identify revenue, cogs, opex groups via meta
    def classify_groups(meta_by_line: Dict[str, Dict[str, str]]) -> Dict[str, str]:
        group: Dict[str, str] = {}
        for li, md in meta_by_line.items():
            kind = (md.get("kind") or "").lower()
            sec = md.get("section") or ""
            if kind == "revenue":
                group[li] = "revenue"
            else:
                # expenses: decide cogs vs opex by section
                sc = section_class(sec)
                if sc == "cogs":
                    group[li] = "cogs"
                elif sc == "opex":
                    group[li] = "opex"
                else:
                    # default unknown expenses to opex
                    group[li] = "opex"
        return group

    group_map = classify_groups(line_meta)

    # Utility to compute line metrics for a given sums
    def compute_lines(budget_sums: Dict[str, float], actual_sums: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
        # First compute atomic line items
        results: Dict[str, Dict[str, Any]] = {}
        for li in all_line_items:
            b = budget_sums.get(li, 0.0)
            a = actual_sums.get(li, 0.0)
            b_int = to_int_nearest(b)
            a_int = to_int_nearest(a)
            var_abs = a_int - b_int
            # variance pct
            if b_int == 0:
                var_pct = "N/A"
            else:
                pct = (a_int - b_int) / (abs(b_int) if abs(b_int) > 0 else 1) * 100.0
                var_pct = round(pct, 2)
            kind = (line_meta.get(li, {}).get("kind") or "").lower()
            # favorable
            if kind == "revenue":
                favorable = a_int > b_int
                # materiality for revenue
                if var_pct == "N/A":
                    material = abs(var_abs) >= thresholds["revenue"]["amount"]
                else:
                    material = (abs(var_abs) >= thresholds["revenue"]["amount"]) or (abs(float(var_pct)) >= thresholds["revenue"]["pct"])
            else:
                favorable = a_int < b_int
                # materiality for expense
                if var_pct == "N/A":
                    material = abs(var_abs) >= thresholds["expense"]["amount"]
                else:
                    material = (abs(var_abs) >= thresholds["expense"]["amount"]) or (abs(float(var_pct)) >= thresholds["expense"]["pct"])
            results[li] = {
                "line_item": li,
                "section": line_meta.get(li, {}).get("section", ""),
                "subcategory": line_meta.get(li, {}).get("subcategory", ""),
                "kind": kind if kind in ("revenue", "expense") else kind,
                "budget": b_int,
                "actual": a_int,
                "variance_abs": var_abs,
                "variance_pct": var_pct,
                "favorable": favorable,
                "material": material,
                "group": group_map.get(li, "")
            }
        # Totals
        # Total Revenue
        tr_b = sum(results[li]["budget"] for li in results if results[li]["group"] == "revenue")
        tr_a = sum(results[li]["actual"] for li in results if results[li]["group"] == "revenue")
        tr_var = tr_a - tr_b
        tr_pct = "N/A" if tr_b == 0 else round((tr_a - tr_b) / abs(tr_b) * 100.0, 2)
        tr_fav = tr_a > tr_b
        results["Total Revenue"] = {
            "line_item": "Total Revenue",
            "section": "REVENUE",
            "subcategory": "",
            "kind": "revenue",
            "budget": tr_b,
            "actual": tr_a,
            "variance_abs": tr_var,
            "variance_pct": tr_pct,
            "favorable": tr_fav,
            "material": False,
            "group": "revenue"
        }
        # COGS
        cogs_b = sum(results[li]["budget"] for li in results if results[li]["group"] == "cogs")
        cogs_a = sum(results[li]["actual"] for li in results if results[li]["group"] == "cogs")
        cogs_var = cogs_a - cogs_b
        cogs_pct = "N/A" if cogs_b == 0 else round((cogs_a - cogs_b) / abs(cogs_b) * 100.0, 2)
        cogs_fav = cogs_a < cogs_b
        results["COGS"] = {
            "line_item": "COGS",
            "section": "COGS",
            "subcategory": "",
            "kind": "expense",
            "budget": cogs_b,
            "actual": cogs_a,
            "variance_abs": cogs_var,
            "variance_pct": cogs_pct,
            "favorable": cogs_fav,
            "material": False,
            "group": "cogs"
        }
        # Gross Profit
        gp_b = tr_b - cogs_b
        gp_a = tr_a - cogs_a
        gp_var = gp_a - gp_b
        gp_pct = "N/A" if gp_b == 0 else round((gp_a - gp_b) / abs(gp_b) * 100.0, 2)
        gp_fav = gp_a > gp_b
        results["Gross Profit"] = {
            "line_item": "Gross Profit",
            "section": "",
            "subcategory": "",
            "kind": "other",
            "budget": gp_b,
            "actual": gp_a,
            "variance_abs": gp_var,
            "variance_pct": gp_pct,
            "favorable": gp_fav,
            "material": False,
            "group": "gross_profit"
        }
        # Total OpEx
        opex_b = sum(results[li]["budget"] for li in results if results[li]["group"] == "opex")
        opex_a = sum(results[li]["actual"] for li in results if results[li]["group"] == "opex")
        opex_var = opex_a - opex_b
        opex_pct = "N/A" if opex_b == 0 else round((opex_a - opex_b) / abs(opex_b) * 100.0, 2)
        opex_fav = opex_a < opex_b
        results["Total OpEx"] = {
            "line_item": "Total OpEx",
            "section": "OPERATING EXPENSES",
            "subcategory": "",
            "kind": "expense",
            "budget": opex_b,
            "actual": opex_a,
            "variance_abs": opex_var,
            "variance_pct": opex_pct,
            "favorable": opex_fav,
            "material": False,
            "group": "opex"
        }
        # EBITDA
        ebitda_b = gp_b - opex_b
        ebitda_a = gp_a - opex_a
        ebitda_var = ebitda_a - ebitda_b
        ebitda_pct = "N/A" if ebitda_b == 0 else round((ebitda_a - ebitda_b) / abs(ebitda_b) * 100.0, 2)
        ebitda_fav = ebitda_a > ebitda_b
        # materiality for EBITDA
        if ebitda_pct == "N/A":
            ebitda_mat = abs(ebitda_var) >= thresholds["ebitda"]["amount"]
        else:
            ebitda_mat = (abs(ebitda_var) >= thresholds["ebitda"]["amount"]) or (abs(float(ebitda_pct)) >= thresholds["ebitda"]["pct"])
        results["EBITDA"] = {
            "line_item": "EBITDA",
            "section": "",
            "subcategory": "",
            "kind": "other",
            "budget": ebitda_b,
            "actual": ebitda_a,
            "variance_abs": ebitda_var,
            "variance_pct": ebitda_pct,
            "favorable": ebitda_fav,
            "material": ebitda_mat,
            "group": "ebitda"
        }
        return results

    results_monthly = compute_lines(budget_monthly, actual_monthly)
    results_ytd = compute_lines(budget_ytd, actual_ytd)

    expected = {
        "period": period,
        "period_type": period_type,
        "ytd_start": ytd_start,
        "materiality": {
            "revenue": {"amount": thresholds["revenue"]["amount"], "pct": thresholds["revenue"]["pct"]},
            "expense": {"amount": thresholds["expense"]["amount"], "pct": thresholds["expense"]["pct"]},
            "ebitda": {"amount": thresholds["ebitda"]["amount"], "pct": thresholds["ebitda"]["pct"]},
        },
        "monthly": results_monthly,
        "ytd": results_ytd,
    }
    return expected

def read_output_csv(path: str) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    if not os.path.isfile(path):
        return False, [], []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return True, [], []
    header = rows[0]
    dicts: List[Dict[str, Any]] = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue
        row = {header[i]: r[i] if i < len(r) else "" for i in range(len(header))}
        dicts.append(row)
    return True, header, dicts

def build_index_by_line(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        li = (r.get("line_item") or "").strip()
        if li:
            idx[li] = r
    return idx

def validate_csv(schema_required: List[str], rows: List[Dict[str, Any]], expected: Dict[str, Dict[str, Any]], required_line_items: List[str], check_ebitda_material: bool) -> Tuple[bool, bool, bool]:
    schema_ok = True
    # Presence of required lines
    idx = build_index_by_line(rows)
    lines_present_ok = all(li in idx for li in required_line_items)
    # Values correct
    values_ok = True
    # Check each required line if present
    for li in required_line_items:
        if li not in idx:
            values_ok = False
            continue
        out_row = idx[li]
        exp = expected.get(li)
        if not exp:
            values_ok = False
            continue
        # Parse output monetary and boolean fields
        def parse_int_field(val: Any) -> Any:
            try:
                if isinstance(val, (int, float)):
                    return int(val)
                return int(str(val).strip())
            except Exception:
                return None
        ob = parse_int_field(out_row.get("budget"))
        oa = parse_int_field(out_row.get("actual"))
        ov = parse_int_field(out_row.get("variance_abs"))
        # variance pct
        ovp_is_na, ovp_num = parse_variance_pct_value(out_row.get("variance_pct"))
        # booleans
        ofav = coerce_bool_str(out_row.get("favorable"))
        omat = coerce_bool_str(out_row.get("material"))
        # Expected values
        eb = int(exp["budget"])
        ea = int(exp["actual"])
        ev = int(exp["variance_abs"])
        evp = exp["variance_pct"]
        efav = bool(exp["favorable"])
        emat = bool(exp["material"])
        # Compare with tolerances
        if ob is None or not almost_equal_int(ob, eb):
            values_ok = False
        if oa is None or not almost_equal_int(oa, ea):
            values_ok = False
        if ov is None or not almost_equal_int(ov, ev):
            values_ok = False
        if evp == "N/A":
            # must be exactly 'N/A'
            if (out_row.get("variance_pct") or "") != "N/A":
                values_ok = False
        else:
            if ovp_is_na:
                values_ok = False
            else:
                if ovp_num is None or not almost_equal_float(ovp_num, float(evp)):
                    values_ok = False
        if ofav is None or ofav != efav:
            values_ok = False
        # Only enforce EBITDA material if requested, else compare for all
        if check_ebitda_material:
            if li == "EBITDA":
                if omat is None or omat != emat:
                    values_ok = False
        else:
            if omat is None or omat != emat:
                values_ok = False
    return schema_ok, lines_present_ok, values_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Initialize checks
    checks: Dict[str, bool] = {
        "has_march_variance_file": False,
        "has_ytd_variance_file": False,
        "has_bva_json": False,
        "csv_schema_correct_march": False,
        "csv_schema_correct_ytd": False,
        "required_lines_present_march": False,
        "required_lines_present_ytd": False,
        "values_correct_march": False,
        "values_correct_ytd": False,
        "json_structure_valid": False,
        "json_monthly_correct": False,
        "json_ytd_correct": False,
        "ebitda_material_correct_march": False,
        "ebitda_material_correct_ytd": False,
    }

    # Required line items
    required_lines = [
        "Product Sales",
        "Service Fees",
        "Direct Materials",
        "Direct Labor",
        "Advertising",
        "Sales Commissions",
        "Engineering Contractors",
        "Software Tools",
        "Legal & Accounting",
        "Rent",
        "S&M - Conferences",
        "Total Revenue",
        "COGS",
        "Gross Profit",
        "Total OpEx",
        "EBITDA",
    ]

    # Compute expected from inputs
    expected_all = compute_expected(workspace_root)
    expected_monthly = expected_all["monthly"]
    expected_ytd = expected_all["ytd"]

    # Output files
    march_csv_path = os.path.join(output_dir, "march_variance.csv")
    ytd_csv_path = os.path.join(output_dir, "ytd_variance.csv")
    bva_json_path = os.path.join(output_dir, "bva.json")

    # Existence
    checks["has_march_variance_file"] = os.path.isfile(march_csv_path)
    checks["has_ytd_variance_file"] = os.path.isfile(ytd_csv_path)
    checks["has_bva_json"] = os.path.isfile(bva_json_path)

    # If missing any primary outputs, baseline reward must be 0.0
    if not (checks["has_march_variance_file"] and checks["has_ytd_variance_file"] and checks["has_bva_json"]):
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Load and validate CSVs
    march_exists, march_header, march_rows = read_output_csv(march_csv_path)
    ytd_exists, ytd_header, ytd_rows = read_output_csv(ytd_csv_path)

    required_schema = ["line_item", "section", "subcategory", "kind", "budget", "actual", "variance_abs", "variance_pct", "favorable", "material"]

    checks["csv_schema_correct_march"] = march_header == required_schema
    checks["csv_schema_correct_ytd"] = ytd_header == required_schema

    # Validate content presence and values with tolerances
    # For CSV checks, enforce EBITDA material correctness specifically in ebidta_material_correct_* and also as part of values_correct_*
    _, pres_march, vals_march = validate_csv(required_schema, march_rows, expected_monthly, required_lines, check_ebitda_material=False)
    _, pres_ytd, vals_ytd = validate_csv(required_schema, ytd_rows, expected_ytd, required_lines, check_ebitda_material=False)
    checks["required_lines_present_march"] = pres_march
    checks["required_lines_present_ytd"] = pres_ytd
    checks["values_correct_march"] = vals_march
    checks["values_correct_ytd"] = vals_ytd

    # Specifically check EBITDA material in CSVs
    march_idx = build_index_by_line(march_rows)
    ytd_idx = build_index_by_line(ytd_rows)
    def check_ebitda_material(idx_rows: Dict[str, Dict[str, Any]], expected: Dict[str, Dict[str, Any]]) -> bool:
        if "EBITDA" not in idx_rows or "EBITDA" not in expected:
            return False
        out_row = idx_rows["EBITDA"]
        omat = coerce_bool_str(out_row.get("material"))
        return omat is not None and omat == bool(expected["EBITDA"]["material"])
    checks["ebitda_material_correct_march"] = check_ebitda_material(march_idx, expected_monthly)
    checks["ebitda_material_correct_ytd"] = check_ebitda_material(ytd_idx, expected_ytd)

    # Validate JSON
    json_ok = False
    monthly_ok = False
    ytd_ok = False
    try:
        with open(bva_json_path, "r", encoding="utf-8") as f:
            bva = json.load(f)
        # Structure keys
        period = bva.get("period")
        period_type = bva.get("period_type")
        materiality = bva.get("materiality")
        summary = bva.get("summary", {})
        line_items = bva.get("line_items", {})
        if isinstance(materiality, dict) and isinstance(summary, dict) and isinstance(line_items, dict):
            json_ok = (period == expected_all["period"] and period_type == expected_all["period_type"])
            # Verify materiality echoes thresholds used
            exp_mat = expected_all["materiality"]
            def mat_equal(a, b) -> bool:
                try:
                    return (almost_equal_float(float(a.get("amount", 0)), float(b.get("amount", 0))) and
                            almost_equal_float(float(a.get("pct", 0)), float(b.get("pct", 0))))
                except Exception:
                    return False
            if not (isinstance(materiality.get("revenue"), dict) and isinstance(materiality.get("expense"), dict) and isinstance(materiality.get("ebitda"), dict)):
                json_ok = False
            else:
                if not (mat_equal(materiality["revenue"], exp_mat["revenue"]) and mat_equal(materiality["expense"], exp_mat["expense"]) and mat_equal(materiality["ebitda"], exp_mat["ebitda"])):
                    json_ok = False

            # Summaries
            summ_m = summary.get("monthly", {})
            summ_y = summary.get("ytd", {})
            # Compute expected summaries
            em_tr_b = int(expected_monthly["Total Revenue"]["budget"])
            em_tr_a = int(expected_monthly["Total Revenue"]["actual"])
            em_tr_v = int(expected_monthly["Total Revenue"]["variance_abs"])
            em_tr_p = expected_monthly["Total Revenue"]["variance_pct"]
            em_eb_b = int(expected_monthly["EBITDA"]["budget"])
            em_eb_a = int(expected_monthly["EBITDA"]["actual"])
            em_eb_v = int(expected_monthly["EBITDA"]["variance_abs"])
            em_eb_p = expected_monthly["EBITDA"]["variance_pct"]

            ey_tr_b = int(expected_ytd["Total Revenue"]["budget"])
            ey_tr_a = int(expected_ytd["Total Revenue"]["actual"])
            ey_tr_v = int(expected_ytd["Total Revenue"]["variance_abs"])
            ey_tr_p = expected_ytd["Total Revenue"]["variance_pct"]
            ey_eb_b = int(expected_ytd["EBITDA"]["budget"])
            ey_eb_a = int(expected_ytd["EBITDA"]["actual"])
            ey_eb_v = int(expected_ytd["EBITDA"]["variance_abs"])
            ey_eb_p = expected_ytd["EBITDA"]["variance_pct"]

            def check_summary(s: Dict[str, Any], tr_b, tr_a, tr_v, tr_p, eb_b, eb_a, eb_v, eb_p) -> bool:
                try:
                    ok = True
                    if not almost_equal_int(int(s.get("total_revenue_budget")), tr_b): ok = False
                    if not almost_equal_int(int(s.get("total_revenue_actual")), tr_a): ok = False
                    if not almost_equal_int(int(s.get("total_revenue_variance_abs")), tr_v): ok = False
                    if tr_p == "N/A":
                        if s.get("total_revenue_variance_pct") != "N/A":
                            ok = False
                    else:
                        vp = s.get("total_revenue_variance_pct")
                        if isinstance(vp, str) and vp.endswith("%"):
                            vp = vp[:-1].strip()
                        if vp is None:
                            ok = False
                        else:
                            try:
                                if not almost_equal_float(float(vp), float(tr_p)):
                                    ok = False
                            except Exception:
                                ok = False
                    if not almost_equal_int(int(s.get("ebitda_budget")), eb_b): ok = False
                    if not almost_equal_int(int(s.get("ebitda_actual")), eb_a): ok = False
                    if not almost_equal_int(int(s.get("ebitda_variance_abs")), eb_v): ok = False
                    if eb_p == "N/A":
                        if s.get("ebitda_variance_pct") != "N/A":
                            ok = False
                    else:
                        vp2 = s.get("ebitda_variance_pct")
                        if isinstance(vp2, str) and vp2.endswith("%"):
                            vp2 = vp2[:-1].strip()
                        if vp2 is None:
                            ok = False
                        else:
                            try:
                                if not almost_equal_float(float(vp2), float(eb_p)):
                                    ok = False
                            except Exception:
                                ok = False
                    return ok
                except Exception:
                    return False

            monthly_ok = check_summary(summ_m, em_tr_b, em_tr_a, em_tr_v, em_tr_p, em_eb_b, em_eb_a, em_eb_v, em_eb_p)
            ytd_ok = check_summary(summ_y, ey_tr_b, ey_tr_a, ey_tr_v, ey_tr_p, ey_eb_b, ey_eb_a, ey_eb_v, ey_eb_p)

            # Line items arrays
            li_m = line_items.get("monthly", [])
            li_y = line_items.get("ytd", [])
            # Build index by name
            idx_m = {d.get("name"): d for d in li_m if isinstance(d, dict) and d.get("name")}
            idx_y = {d.get("name"): d for d in li_y if isinstance(d, dict) and d.get("name")}

            # Validate required lines exist and match expected values
            def validate_json_lines(idx: Dict[str, Dict[str, Any]], expected: Dict[str, Dict[str, Any]]) -> bool:
                ok = True
                for li in [
                    "Product Sales",
                    "Service Fees",
                    "Direct Materials",
                    "Direct Labor",
                    "Advertising",
                    "Sales Commissions",
                    "Engineering Contractors",
                    "Software Tools",
                    "Legal & Accounting",
                    "Rent",
                    "S&M - Conferences",
                    "Total Revenue",
                    "COGS",
                    "Gross Profit",
                    "Total OpEx",
                    "EBITDA",
                ]:
                    if li not in idx or li not in expected:
                        ok = False
                        continue
                    obj = idx[li]
                    exp = expected[li]
                    # budget, actual, variance_abs ints within tolerance
                    try:
                        jb = int(obj.get("budget"))
                        ja = int(obj.get("actual"))
                        jv = int(obj.get("variance_abs"))
                    except Exception:
                        ok = False
                        continue
                    if not almost_equal_int(jb, int(exp["budget"])): ok = False
                    if not almost_equal_int(ja, int(exp["actual"])): ok = False
                    if not almost_equal_int(jv, int(exp["variance_abs"])): ok = False
                    # variance_pct
                    evp = exp["variance_pct"]
                    jvp = obj.get("variance_pct")
                    if evp == "N/A":
                        if jvp != "N/A":
                            ok = False
                    else:
                        if isinstance(jvp, str) and jvp.endswith("%"):
                            jvp = jvp[:-1].strip()
                        try:
                            if not almost_equal_float(float(jvp), float(evp)):
                                ok = False
                        except Exception:
                            ok = False
                    # favorable and material
                    if bool(obj.get("favorable")) != bool(exp["favorable"]): ok = False
                    if bool(obj.get("material")) != bool(exp["material"]): ok = False
                return ok

            # Update monthly_ok and ytd_ok to include line item validation too
            monthly_ok = monthly_ok and validate_json_lines(idx_m, expected_monthly)
            ytd_ok = ytd_ok and validate_json_lines(idx_y, expected_ytd)
    except Exception:
        json_ok = False
        monthly_ok = False
        ytd_ok = False

    checks["json_structure_valid"] = json_ok
    checks["json_monthly_correct"] = monthly_ok
    checks["json_ytd_correct"] = ytd_ok

    # Compute reward
    # Baseline: if required files missing -> 0.0 (already handled above)
    # Otherwise, fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # To encourage full correctness, weight: reward = passed / total_checks
    reward = passed / total_checks if total_checks > 0 else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()