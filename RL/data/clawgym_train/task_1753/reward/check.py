import csv
import json
import os
import sys
from typing import Dict, List, Tuple, Any

def nearly_equal(a: float, b: float, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def to_float(val, default=0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except Exception:
            return default
    try:
        f = float(s)
        return f
    except Exception:
        return default

def to_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "t")

def round2(x: float) -> float:
    # stable rounding to 2 decimals
    return round(float(x) + 1e-12, 2)

def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_csv_dicts(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]

def write_debug(reward_dir: str, name: str, data: Any):
    # Optional internal debugging (not used for scoring)
    try:
        dbg_path = os.path.join(reward_dir, f"_debug_{name}.json")
        with open(dbg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def parse_rates(rows: List[Dict[str, str]]) -> Dict[str, Tuple[float, float]]:
    result = {}
    for r in rows:
        # normalize keys
        lk = {k.lower().strip(): k for k in r.keys()}
        cls_key = next((lk[k] for k in lk if "classification" in k), None)
        base_key = None
        fringe_key = None
        for cand in ["base", "base_rate", "basic", "basic_rate"]:
            if cand in lk:
                base_key = lk[cand]
                break
        for cand in ["fringe", "fringe_rate"]:
            if cand in lk:
                fringe_key = lk[cand]
                break
        if not cls_key or not base_key or not fringe_key:
            # skip malformed row
            continue
        classification = str(r[cls_key]).strip()
        base = to_float(r[base_key], 0.0)
        fringe = to_float(r[fringe_key], 0.0)
        result[classification] = (base, fringe)
    return result

def parse_employees(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        # Expect typical fields
        name = str(r.get("name", "")).strip()
        last4 = str(r.get("last4", "")).strip()
        classification = str(r.get("classification", "")).strip()
        apprentice_flag = to_bool(r.get("apprentice_flag", False))
        apprentice_pct = to_float(r.get("apprentice_pct", 0.0))
        # normalize apprentice_pct if looks like >1 (assume percent)
        if apprentice_pct > 1.0:
            apprentice_pct = apprentice_pct / 100.0
        st_hours = to_float(r.get("st_hours", 0.0), 0.0)
        ot_hours = to_float(r.get("ot_hours", 0.0), 0.0)
        # plan credit field tolerant names
        plan_credit = None
        for key in ["plan_credit_per_hour", "fringe_plan_credit_per_hour", "plan_credit", "plan_fringe_credit_per_hour"]:
            if key in r:
                plan_credit = to_float(r.get(key, 0.0), 0.0)
                break
        if plan_credit is None:
            plan_credit = 0.0
        deductions_total = to_float(r.get("deductions_total", 0.0), 0.0)
        out.append({
            "name": name,
            "last4": last4,
            "classification": classification,
            "apprentice_flag": apprentice_flag,
            "apprentice_pct": apprentice_pct,
            "st_hours": st_hours,
            "ot_hours": ot_hours,
            "plan_credit_per_hour": plan_credit,
            "deductions_total": deductions_total,
        })
    return out

def parse_ratio_limit(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            a = float(parts[0].strip())
            b = float(parts[1].strip())
            if b == 0:
                return float("inf")
            return a / b
        except Exception:
            return 0.0
    if "/" in s:
        parts = s.split("/")
        try:
            a = float(parts[0].strip())
            b = float(parts[1].strip())
            if b == 0:
                return float("inf")
            return a / b
        except Exception:
            return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def compute_expected_for_employee(emp: Dict[str, Any], rates: Dict[str, Tuple[float, float]]) -> Dict[str, Any]:
    classification = emp["classification"]
    if classification not in rates:
        return {"ok": False, "reason": "classification_missing"}
    base, fringe = rates[classification]
    if emp["apprentice_flag"]:
        pct = emp["apprentice_pct"]
        base = base * pct
        fringe = fringe * pct
    st = emp["st_hours"]
    ot = emp["ot_hours"]
    plan_credit = emp["plan_credit_per_hour"]
    required_fringe = fringe
    cash_fringe_per_hour = max(0.0, required_fringe - plan_credit)
    base_rate_out = round2(base)
    fringe_hourly_cash_out = round2(cash_fringe_per_hour)
    base_wages = st * base + ot * (1.5 * base)
    cash_fringe_total = (st + ot) * cash_fringe_per_hour
    gross = base_wages + cash_fringe_total
    gross_out = round2(gross)
    deductions = emp["deductions_total"]
    net = gross - deductions
    net_out = round2(net)
    return {
        "ok": True,
        "base_rate": base_rate_out,
        "fringe_hourly_cash": fringe_hourly_cash_out,
        "gross_pay": gross_out,
        "net_pay": net_out,
        "base_wages": round2(base_wages),
        "cash_fringe_total": round2(cash_fringe_total),
    }

def read_wh347(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
        headers = reader.fieldnames or []
        return rows, headers

def get_item_result_from_md(lines: List[str], keywords: List[str]) -> str:
    # returns "pass", "fail" or ""
    for line in lines:
        lc = line.lower()
        if all(kw in lc for kw in keywords):
            if " pass" in f" {lc}" or lc.strip().endswith("pass"):
                return "pass"
            if " fail" in f" {lc}" or lc.strip().endswith("fail"):
                return "fail"
    return ""

def contains_any(text: str, needles: List[str]) -> bool:
    t = text.lower()
    return any(n.lower() in t for n in needles)

def find_line_with_keywords(lines: List[str], keywords: List[str]) -> str:
    for line in lines:
        if all(kw.lower() in line.lower() for kw in keywords):
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # wh347 checks
        "wh347_exists": False,
        "wh347_header_ok": False,
        "wh347_rowcount_ok": False,
        "wh347_wd_fields_ok": False,
        "wh347_calculations_ok": False,
        # wd_used.json
        "wd_used_exists": False,
        "wd_used_metadata_ok": False,
        "wd_used_rates_ok": False,
        # wage_cost_summary.json
        "wage_summary_exists": False,
        "wage_summary_totals_ok": False,
        "wage_summary_by_class_ok": False,
        # compliance_checklist.md
        "compliance_exists": False,
        "compliance_has_identifiers": False,
        "compliance_required_items_present": False,
        "compliance_apprenticeship_ratio_fail_if_exceeds": False,
        "compliance_corrective_action_if_fail": False,
        "compliance_missing_craft_flagged": False,
        # risk_assessment.json
        "risk_exists": False,
        "risk_fields_ok": False,
        "risk_monetary_ok": False,
    }

    # Load inputs
    project_path = os.path.join(input_dir, "project.json")
    rates_path = os.path.join(input_dir, "wd_rates.csv")
    employees_path = os.path.join(input_dir, "employees.csv")

    # If inputs are missing, we still must not award any credit based on outputs alone,
    # but many checks require these to validate outputs. If missing, most checks will remain False.
    if not (os.path.isfile(project_path) and os.path.isfile(rates_path) and os.path.isfile(employees_path)):
        # print result with all False checks
        print(json.dumps({"reward": 0.0, **checks}))
        return

    project = read_json(project_path)
    rates_rows = read_csv_dicts(rates_path)
    employees_rows = read_csv_dicts(employees_path)

    rates_map = parse_rates(rates_rows)
    employees = parse_employees(employees_rows)

    # Useful project fields
    proj_wd_number = str(project.get("wd_number", "")).strip()
    proj_wd_type = str(project.get("wd_type", "")).strip()
    proj_county = str(project.get("county", "")).strip()
    proj_state = str(project.get("state", "")).strip()
    proj_week_ending = str(project.get("week_ending", "")).strip()
    appr_limit_val = parse_ratio_limit(project.get("apprenticeship_ratio_limit", 0))
    appr_basis = str(project.get("apprenticeship_ratio_basis", "hours")).strip().lower()

    # Determine missing crafts
    employee_classifications = set(e["classification"] for e in employees if e.get("classification"))
    missing_crafts = sorted([c for c in employee_classifications if c not in rates_map])

    # 1) Validate wh347_week1.csv
    wh347_path = os.path.join(output_dir, "wh347_week1.csv")
    wh347_rows = []
    wh347_headers = []
    if os.path.isfile(wh347_path):
        checks["wh347_exists"] = True
        try:
            wh347_rows, wh347_headers = read_wh347(wh347_path)
            required_headers = [
                "name","last4","classification","apprentice_flag","apprentice_pct",
                "st_hours","ot_hours","base_rate","fringe_hourly_cash","gross_pay",
                "deductions_total","net_pay","wd_number","week_ending"
            ]
            if wh347_headers == required_headers:
                checks["wh347_header_ok"] = True

            # rowcount check
            if len(wh347_rows) == len(employees):
                checks["wh347_rowcount_ok"] = True

            # Build mapping for rows by (name,last4)
            wh_map: Dict[Tuple[str, str], Dict[str, str]] = {}
            for r in wh347_rows:
                key = (str(r.get("name","")).strip(), str(r.get("last4","")).strip())
                wh_map[key] = r

            # Compute expected values and compare
            all_calc_ok = True
            wd_fields_ok = True
            for emp in employees:
                key = (emp["name"], emp["last4"])
                if key not in wh_map:
                    all_calc_ok = False
                    wd_fields_ok = False
                    break
                out_row = wh_map[key]
                # check wd fields
                if str(out_row.get("wd_number","")).strip() != proj_wd_number or str(out_row.get("week_ending","")).strip() != proj_week_ending:
                    wd_fields_ok = False
                # expected calculations
                exp = compute_expected_for_employee(emp, rates_map)
                if not exp["ok"]:
                    # If classification missing, we cannot validate; treat as calculation not ok
                    all_calc_ok = False
                else:
                    try:
                        base_rate_out = to_float(out_row.get("base_rate", "0"))
                        fringe_hourly_cash_out = to_float(out_row.get("fringe_hourly_cash", "0"))
                        gross_pay_out = to_float(out_row.get("gross_pay", "0"))
                        net_pay_out = to_float(out_row.get("net_pay", "0"))
                        st_hours_out = to_float(out_row.get("st_hours", "0"))
                        ot_hours_out = to_float(out_row.get("ot_hours", "0"))
                        # hours must match input
                        if not nearly_equal(st_hours_out, emp["st_hours"]) or not nearly_equal(ot_hours_out, emp["ot_hours"]):
                            all_calc_ok = False
                        # compare monetary
                        if not nearly_equal(base_rate_out, exp["base_rate"]):
                            all_calc_ok = False
                        if not nearly_equal(fringe_hourly_cash_out, exp["fringe_hourly_cash"]):
                            all_calc_ok = False
                        if not nearly_equal(gross_pay_out, exp["gross_pay"]):
                            all_calc_ok = False
                        # deductions from employees.csv should be used; net = gross - deductions
                        deductions_out = to_float(out_row.get("deductions_total", "0"))
                        if not nearly_equal(deductions_out, emp["deductions_total"]):
                            all_calc_ok = False
                        if not nearly_equal(net_pay_out, exp["net_pay"]):
                            all_calc_ok = False
                    except Exception:
                        all_calc_ok = False
            if wd_fields_ok:
                checks["wh347_wd_fields_ok"] = True
            if all_calc_ok:
                checks["wh347_calculations_ok"] = True

        except Exception:
            pass

    # 2) wd_used.json
    wd_used_path = os.path.join(output_dir, "wd_used.json")
    if os.path.isfile(wd_used_path):
        checks["wd_used_exists"] = True
        try:
            wd_used = read_json(wd_used_path)
            meta_ok = (
                str(wd_used.get("wd_number","")).strip() == proj_wd_number and
                str(wd_used.get("wd_type","")).strip() == proj_wd_type and
                str(wd_used.get("county","")).strip() == proj_county and
                str(wd_used.get("state","")).strip() == proj_state and
                str(wd_used.get("week_ending","")).strip() == proj_week_ending
            )
            if meta_ok:
                checks["wd_used_metadata_ok"] = True

            # rates mirror
            rates_used = wd_used.get("rates", [])
            # Build dict from rates_used
            used_map = {}
            for r in rates_used:
                cls = str(r.get("classification","")).strip()
                base = to_float(r.get("base", 0.0))
                fringe = to_float(r.get("fringe", 0.0))
                if cls:
                    used_map[cls] = (base, fringe)
            # compare sets and values
            rates_ok = True
            if set(used_map.keys()) != set(rates_map.keys()):
                rates_ok = False
            else:
                for cls, (base, fringe) in rates_map.items():
                    ub, uf = used_map.get(cls, (None, None))
                    if ub is None:
                        rates_ok = False
                        break
                    if not (nearly_equal(ub, base) and nearly_equal(uf, fringe)):
                        rates_ok = False
                        break
            if rates_ok:
                checks["wd_used_rates_ok"] = True

        except Exception:
            pass

    # 3) wage_cost_summary.json
    wage_sum_path = os.path.join(output_dir, "wage_cost_summary.json")
    if os.path.isfile(wage_sum_path):
        checks["wage_summary_exists"] = True
        try:
            wage_sum = read_json(wage_sum_path)
            # recompute from wh347 (must exist and be valid mapping)
            totals_ok = False
            by_class_ok = False
            if checks["wh347_exists"]:
                # Aggregate from wh347 file
                total_st = 0.0
                total_ot = 0.0
                total_base_wages = 0.0
                total_cash_fringe = 0.0
                total_gross = 0.0
                total_deductions = 0.0
                total_net = 0.0
                by_class: Dict[str, Dict[str, float]] = {}
                try:
                    for r in wh347_rows:
                        cls = str(r.get("classification","")).strip()
                        st = to_float(r.get("st_hours", 0.0))
                        ot = to_float(r.get("ot_hours", 0.0))
                        base_rate = to_float(r.get("base_rate", 0.0))
                        fringe_cash = to_float(r.get("fringe_hourly_cash", 0.0))
                        gross = to_float(r.get("gross_pay", 0.0))
                        ded = to_float(r.get("deductions_total", 0.0))
                        net = to_float(r.get("net_pay", 0.0))
                        base_wages = st * base_rate + ot * (1.5 * base_rate)
                        cash_fringe = (st + ot) * fringe_cash

                        total_st += st
                        total_ot += ot
                        total_base_wages += base_wages
                        total_cash_fringe += cash_fringe
                        total_gross += gross
                        total_deductions += ded
                        total_net += net

                        if cls not in by_class:
                            by_class[cls] = {"st_hours": 0.0, "ot_hours": 0.0, "base_wages": 0.0, "cash_fringe": 0.0, "gross": 0.0}
                        by_class[cls]["st_hours"] += st
                        by_class[cls]["ot_hours"] += ot
                        by_class[cls]["base_wages"] += base_wages
                        by_class[cls]["cash_fringe"] += cash_fringe
                        by_class[cls]["gross"] += gross

                    # Compare totals
                    totals_ok = (
                        nearly_equal(to_float(wage_sum.get("total_st_hours", 0.0)), round2(total_st)) and
                        nearly_equal(to_float(wage_sum.get("total_ot_hours", 0.0)), round2(total_ot)) and
                        nearly_equal(to_float(wage_sum.get("total_base_wages", 0.0)), round2(total_base_wages)) and
                        nearly_equal(to_float(wage_sum.get("total_cash_fringe", 0.0)), round2(total_cash_fringe)) and
                        nearly_equal(to_float(wage_sum.get("total_gross", 0.0)), round2(total_gross)) and
                        nearly_equal(to_float(wage_sum.get("total_deductions", 0.0)), round2(total_deductions)) and
                        nearly_equal(to_float(wage_sum.get("total_net", 0.0)), round2(total_net))
                    )
                    if totals_ok:
                        checks["wage_summary_totals_ok"] = True

                    # Compare by_classification
                    ws_by_class = wage_sum.get("by_classification", {})
                    # keys must match
                    if set(ws_by_class.keys()) == set(by_class.keys()):
                        per_ok = True
                        for cls, vals in by_class.items():
                            target = ws_by_class.get(cls, {})
                            if not (
                                nearly_equal(to_float(target.get("st_hours", 0.0)), round2(vals["st_hours"])) and
                                nearly_equal(to_float(target.get("ot_hours", 0.0)), round2(vals["ot_hours"])) and
                                nearly_equal(to_float(target.get("base_wages", 0.0)), round2(vals["base_wages"])) and
                                nearly_equal(to_float(target.get("cash_fringe", 0.0)), round2(vals["cash_fringe"])) and
                                nearly_equal(to_float(target.get("gross", 0.0)), round2(vals["gross"]))
                            ):
                                per_ok = False
                                break
                        if per_ok:
                            checks["wage_summary_by_class_ok"] = True
                except Exception:
                    pass
        except Exception:
            pass

    # 4) compliance_checklist.md
    compliance_path = os.path.join(output_dir, "compliance_checklist.md")
    compliance_lines: List[str] = []
    if os.path.isfile(compliance_path):
        checks["compliance_exists"] = True
        try:
            with open(compliance_path, "r", encoding="utf-8") as f:
                compliance_lines = [line.rstrip("\n") for line in f.readlines()]
            text_all = "\n".join(compliance_lines)
            # identifiers
            has_wd = proj_wd_number in text_all
            has_week = proj_week_ending in text_all
            if has_wd and has_week:
                checks["compliance_has_identifiers"] = True

            # required items
            res_class_rates = get_item_result_from_md(compliance_lines, ["classification", "wd", "rate"])
            res_fringe = get_item_result_from_md(compliance_lines, ["fringe"])
            res_ot = get_item_result_from_md(compliance_lines, ["overtime"])
            res_appr = get_item_result_from_md(compliance_lines, ["apprentice"])
            res_wh347 = get_item_result_from_md(compliance_lines, ["wh-347", "statement"])
            res_posting = get_item_result_from_md(compliance_lines, ["posting"])
            # also ensure "record retention" presence in posting line if available
            required_present = all(v in ("pass", "fail") for v in [res_class_rates, res_fringe, res_ot, res_appr, res_wh347, res_posting])
            if required_present:
                checks["compliance_required_items_present"] = True

            # apprenticeship ratio computation
            # Filter Electrician craft employees
            electricians = [e for e in employees if "electrician" in str(e.get("classification","")).strip().lower()]
            appr_emps = [e for e in electricians if e.get("apprentice_flag", False)]
            jw_emps = [e for e in electricians if not e.get("apprentice_flag", False)]
            if appr_basis == "hours":
                appr_qty = sum((e.get("st_hours", 0.0) + e.get("ot_hours", 0.0)) for e in appr_emps)
                jw_qty = sum((e.get("st_hours", 0.0) + e.get("ot_hours", 0.0)) for e in jw_emps)
            else:
                # default to headcount if not "hours"
                appr_qty = float(len(appr_emps))
                jw_qty = float(len(jw_emps))
            if jw_qty == 0.0:
                ratio = float("inf") if appr_qty > 0 else 0.0
            else:
                ratio = appr_qty / jw_qty
            exceeds = ratio > appr_limit_val if appr_limit_val != float("inf") else False

            # verify apprenticeship item marked Fail if exceeds
            if exceeds and res_appr == "fail":
                checks["compliance_apprenticeship_ratio_fail_if_exceeds"] = True
            elif not exceeds:
                # If not exceeding, we do not require fail; mark as passed check (no penalty)
                checks["compliance_apprenticeship_ratio_fail_if_exceeds"] = True

            # corrective action present when non-compliant
            if exceeds:
                if contains_any(text_all, ["corrective action", "corrective-action", "corrective step", "fix by"]):
                    checks["compliance_corrective_action_if_fail"] = True
            else:
                # Not applicable; treat as passed
                checks["compliance_corrective_action_if_fail"] = True

            # missing craft flagged with SF-1444 mention when applicable
            if missing_crafts:
                # classifications/rates should be Fail and mention SF-1444 or conformance
                mentions = contains_any(text_all, ["sf-1444", "conformance"])
                if res_class_rates == "fail" and mentions:
                    checks["compliance_missing_craft_flagged"] = True
            else:
                # no missing craft -> pass
                checks["compliance_missing_craft_flagged"] = True

        except Exception:
            pass

    # 5) risk_assessment.json
    risk_path = os.path.join(output_dir, "risk_assessment.json")
    if os.path.isfile(risk_path):
        checks["risk_exists"] = True
        try:
            risk = read_json(risk_path)
            # identify Electrician apprentice in employees
            elec_apprs = [e for e in employees if ("electrician" in str(e.get("classification","")).lower()) and e.get("apprentice_flag", False)]
            # If multiple, match by name if provided in risk
            risk_emp_name = str(risk.get("employee","")).strip()
            matched_emp = None
            if risk_emp_name:
                for e in elec_apprs:
                    if str(e.get("name","")).strip() == risk_emp_name:
                        matched_emp = e
                        break
            if matched_emp is None and elec_apprs:
                matched_emp = elec_apprs[0]

            fields_ok = True
            if matched_emp is None:
                fields_ok = False
            else:
                # Basic fields
                if str(risk.get("craft","")).strip().lower() != "electrician":
                    fields_ok = False
                if not to_bool(risk.get("apprentice_flag", False)):
                    fields_ok = False
                # apprentice_pct approx equals employee's apprentice_pct
                if not nearly_equal(to_float(risk.get("apprentice_pct", 0.0)), matched_emp.get("apprentice_pct", 0.0)):
                    fields_ok = False
                # hours match
                hrs = risk.get("hours", {})
                if not nearly_equal(to_float(hrs.get("st",0.0)), matched_emp.get("st_hours", 0.0)):
                    fields_ok = False
                if not nearly_equal(to_float(hrs.get("ot",0.0)), matched_emp.get("ot_hours", 0.0)):
                    fields_ok = False
            if fields_ok:
                checks["risk_fields_ok"] = True

            # monetary checks
            monetary_ok = False
            if matched_emp is not None and checks["wh347_exists"]:
                # find corresponding wh347 row for paid gross
                wh347_rows_map = {}
                for r in wh347_rows:
                    key = (str(r.get("name","")).strip(), str(r.get("last4","")).strip())
                    wh347_rows_map[key] = r
                key = (matched_emp["name"], matched_emp["last4"])
                if key in wh347_rows_map and "Electrician" in matched_emp["classification"]:
                    paid_gross = to_float(wh347_rows_map[key].get("gross_pay", 0.0))
                    # journeyworker rates
                    # Use classification "Electrician" lookup (strip to base craft name "Electrician")
                    jw_cls = None
                    # try exact match "Electrician"
                    if "Electrician" in rates_map:
                        jw_cls = "Electrician"
                    else:
                        # find first rates key containing "Electrician"
                        for cls in rates_map.keys():
                            if "electrician" in cls.lower():
                                jw_cls = cls
                                break
                    if jw_cls is not None:
                        jw_base, jw_fringe = rates_map[jw_cls]
                        st = matched_emp["st_hours"]
                        ot = matched_emp["ot_hours"]
                        jw_gross = st * (jw_base + jw_fringe) + ot * (1.5 * jw_base + jw_fringe)
                        jw_gross = round2(jw_gross)
                        back_wages = round2(jw_gross - round2(paid_gross))
                        if back_wages < 0:
                            back_wages = round2(0.0) if back_wages > -0.02 else back_wages  # tolerate tiny negatives
                        liq_dam = round2(back_wages)
                        total_exposure = round2(back_wages + liq_dam)
                        # Now compare to risk json
                        if (
                            nearly_equal(to_float(risk.get("paid_gross", 0.0)), round2(paid_gross)) and
                            nearly_equal(to_float(risk.get("journeyworker_gross", 0.0)), jw_gross) and
                            nearly_equal(to_float(risk.get("back_wages_due", 0.0)), back_wages) and
                            nearly_equal(to_float(risk.get("liquidated_damages", 0.0)), liq_dam) and
                            nearly_equal(to_float(risk.get("total_exposure", 0.0)), total_exposure)
                        ):
                            monetary_ok = True
            if monetary_ok:
                checks["risk_monetary_ok"] = True

        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure 0.0 if no output files present (no-op baseline)
    any_output = any(os.path.isfile(os.path.join(output_dir, fn)) for fn in [
        "wh347_week1.csv", "wd_used.json", "wage_cost_summary.json", "compliance_checklist.md", "risk_assessment.json"
    ])
    if not any_output:
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()