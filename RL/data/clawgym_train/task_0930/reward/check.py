#!/usr/bin/env python3
import json
import os
import sys
import csv
import math

def build_paths(workspace_root):
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")
    return input_dir, output_dir, reward_dir

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def to_number(val):
    # Convert strings like "1,234,567" or "1_234_567" to float
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace(",", "").replace("_", "")
        # Handle currency like $1,234, only digits, dot
        if s.startswith("$"):
            s = s[1:]
        try:
            return float(s)
        except Exception:
            return None
    return None

def parse_csv_required_columns(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None

def simple_yaml_parse(path):
    # Minimal YAML parser for simple key: value and nested dicts (two-space indents).
    # Ignores lists and complex YAML features.
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    root = {}
    stack = [( -1, root )]  # (indent, container)
    last_key_at_indent = {}
    for raw in lines:
        # Strip comments
        line = raw.rstrip("\n")
        if "#" in line:
            # Remove comments only if not inside quotes (simple approach: split on # once)
            parts = line.split("#", 1)
            line = parts[0]
        if not line.strip():
            continue
        # Skip list items (not needed for this task)
        stripped = line.lstrip(" ")
        if stripped.startswith("- "):
            # Not building lists; skip
            continue
        indent = len(line) - len(stripped)
        # Adjust stack to current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            # Reset to root
            stack = [( -1, root )]
        container = stack[-1][1]
        # Parse key: value or key:
        if ":" in stripped:
            key, after = stripped.split(":", 1)
            key = key.strip()
            value_str = after.strip()
            if value_str == "":
                # Start a nested dict
                new_dict = {}
                container[key] = new_dict
                stack.append((indent, new_dict))
                last_key_at_indent[indent] = key
            else:
                # Scalar value; try to coerce
                val = value_str
                # Remove quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                # Coerce booleans and nulls
                low = val.lower()
                if low in ("true", "yes"):
                    coerced = True
                elif low in ("false", "no"):
                    coerced = False
                elif low in ("null", "none", "~"):
                    coerced = None
                else:
                    num = to_number(val)
                    coerced = num if num is not None else val
                container[key] = coerced
                last_key_at_indent[indent] = key
        else:
            # Unsupported format; ignore
            continue
    return root

def norm_key(s):
    return str(s).strip().lower().replace(" ", "_").replace("-", "_")

def approx_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def sum_close(a, b, tol=0.5):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def get_nested(d, path_list):
    cur = d
    for p in path_list:
        if not isinstance(cur, dict):
            return None
        if p in cur:
            cur = cur[p]
        else:
            # try normalized lookup
            pn = None
            for k in cur.keys():
                if norm_key(k) == norm_key(p):
                    pn = k
                    break
            if pn is None:
                return None
            cur = cur[pn]
    return cur

def roles_from_output_succession(obj):
    # Try common keys
    candidates = []
    for k in obj.keys():
        v = obj.get(k)
        if isinstance(v, list):
            candidates.append((k, v))
    # Prefer "critical_roles" if present
    array = None
    for k, v in candidates:
        if norm_key(k) == "critical_roles":
            array = v
            break
    if array is None and candidates:
        # fall back to first list
        array = candidates[0][1]
    roles = {}
    if isinstance(array, list):
        for item in array:
            if not isinstance(item, dict):
                continue
            # role name may be under "role" or "title" or "name"
            name = None
            for key_option in ["role", "title", "name"]:
                if key_option in item:
                    name = str(item[key_option])
                    break
                else:
                    # try normalized
                    for k in item.keys():
                        if norm_key(k) == norm_key(key_option):
                            name = str(item[k])
                            break
                    if name:
                        break
            if not name:
                continue
            # successors
            succ = None
            for s_key in ["successors", "candidate_successors", "successor_list"]:
                if s_key in item and isinstance(item[s_key], list):
                    succ = item[s_key]
                    break
                else:
                    for kk in item.keys():
                        if norm_key(kk) == norm_key(s_key) and isinstance(item[kk], list):
                            succ = item[kk]
                            break
                    if succ:
                        break
            roles[name] = {
                "item": item,
                "successors": succ if isinstance(succ, list) else []
            }
    # ready_now_count
    ready_now_count = None
    for key in obj.keys():
        if norm_key(key) == "ready_now_count":
            try:
                ready_now_count = int(obj[key])
            except Exception:
                try:
                    ready_now_count = int(float(obj[key]))
                except Exception:
                    ready_now_count = None
            break
    return roles, ready_now_count

def has_ready_now(successors):
    # Determine if any successor has readiness ~ ready_now
    for s in successors:
        if not isinstance(s, dict):
            continue
        # readiness field
        readiness = None
        for rk in s.keys():
            if norm_key(rk) in ("readiness", "ready", "status"):
                readiness = s[rk]
                break
        if readiness is None:
            continue
        r = str(readiness).strip().lower().replace(" ", "_").replace("-", "_")
        if "ready" in r and "now" in r:
            return True
        if r in ("ready_now", "now"):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = build_paths(workspace_root)

    # Initialize checks
    checks = {
        "workforce_plan_structure": False,                 # 1
        "rpe_computation_valid": False,                    # 2
        "driver_support_agents_needed_valid": False,       # 3
        "driver_engineering_engineers_needed_valid": False,# 4
        "managerial_span_support_valid": False,            # 5
        "dept_gap_calculations_valid": False,              # 6
        "contingent_mix_sums_to_100": False,               # 7
        "hiring_plan_headers_and_coverage": False,         # 8
        "succession_risks_roles_and_ready_now_count": False,# 9
        "quarterly_review_has_qs": False                   # 10
    }

    # Paths
    company_targets_yaml = os.path.join(input_dir, "company_targets.yaml")
    current_workforce_csv = os.path.join(input_dir, "current_workforce.csv")
    skills_inventory_json = os.path.join(input_dir, "skills_inventory.json")
    succession_crit_roles_json = os.path.join(input_dir, "succession_critical_roles.json")
    cost_assumptions_json = os.path.join(input_dir, "cost_assumptions.json")

    workforce_plan_json = os.path.join(output_dir, "workforce_plan.json")
    hiring_plan_csv = os.path.join(output_dir, "hiring_plan.csv")
    quarterly_review_md = os.path.join(output_dir, "quarterly_review.md")
    succession_risks_json = os.path.join(output_dir, "succession_risks.json")

    # Load inputs
    company = simple_yaml_parse(company_targets_yaml) or {}
    # Read current workforce departments
    input_depts = set()
    headers_in, rows_in = parse_csv_required_columns(current_workforce_csv)
    if rows_in is not None:
        for r in rows_in:
            dept = (r.get("department") or r.get("Department") or "").strip()
            if dept:
                input_depts.add(dept)

    # Top-level structure check for workforce_plan.json
    wp = read_json(workforce_plan_json)
    required_top_keys = [
        "executive_summary",
        "demand_forecasting",
        "department_plans",
        "gap_analysis",
        "contingent_workforce",
        "succession_pipeline",
        "risks_and_mitigations",
    ]
    if isinstance(wp, dict):
        if all(any(k2 == k or norm_key(k2) == norm_key(k) for k2 in wp.keys()) for k in required_top_keys):
            checks["workforce_plan_structure"] = True

    # 2) RPE computation validation
    if checks["workforce_plan_structure"]:
        df = get_nested(wp, ["demand_forecasting"]) or {}
        rpe = get_nested(df, ["revenue_per_employee"])
        if isinstance(rpe, dict):
            sector_out = get_nested(rpe, ["sector"])
            tr_out = get_nested(rpe, ["target_revenue"])
            assumed_rpe = get_nested(rpe, ["assumed_rpe"])
            required_headcount_out = get_nested(rpe, ["required_headcount"])
            # Get target_revenue from input
            sector_in = company.get("sector")
            target_revenue_in = company.get("target_revenue")
            tr_val = to_number(target_revenue_in)
            assumed_rpe_val = to_number(assumed_rpe)
            rhc_val_out = to_number(required_headcount_out)
            # Range check for SaaS
            rpe_range_ok = True
            # If sector is SaaS in inputs or output, enforce range
            is_saas = False
            if isinstance(sector_in, str) and sector_in.strip().lower() == "saas":
                is_saas = True
            if isinstance(sector_out, str) and sector_out.strip().lower() == "saas":
                is_saas = True
            if is_saas:
                if assumed_rpe_val is None or not (200000 <= assumed_rpe_val <= 350000):
                    rpe_range_ok = False
            # Compute required headcount
            rhc_ok = False
            if tr_val is not None and assumed_rpe_val is not None and rhc_val_out is not None and assumed_rpe_val != 0:
                expected_rhc = math.ceil(tr_val / assumed_rpe_val)
                if approx_equal(expected_rhc, rhc_val_out, tol=1e-6):
                    rhc_ok = True
            if (sector_out is not None) and (tr_out is not None) and (assumed_rpe is not None) and (required_headcount_out is not None) and rpe_range_ok and rhc_ok:
                checks["rpe_computation_valid"] = True

    # 3) Driver-based Support agents_needed validation
    if checks["workforce_plan_structure"]:
        df = get_nested(wp, ["demand_forecasting"]) or {}
        driver = get_nested(df, ["driver_based"])
        if isinstance(driver, dict):
            support = get_nested(driver, ["support"])
            if isinstance(support, dict):
                pc = to_number(get_nested(support, ["projected_customers"]))
                tpcm = to_number(get_nested(support, ["tickets_per_customer_per_month"]))
                tpam = to_number(get_nested(support, ["tickets_per_agent_per_month"]))
                agents_needed_out = to_number(get_nested(support, ["agents_needed"]))
                pc_in = to_number(company.get("projected_customers"))
                tpcm_in = to_number(company.get("tickets_per_customer_per_month"))
                tpam_in = to_number(company.get("tickets_per_agent_per_month"))
                if None not in (pc, tpcm, tpam, agents_needed_out, pc_in, tpcm_in, tpam_in) and tpam_in != 0:
                    expected_agents = math.ceil(pc_in * tpcm_in / tpam_in)
                    if approx_equal(expected_agents, agents_needed_out):
                        checks["driver_support_agents_needed_valid"] = True

    # 4) Driver-based Engineering engineers_needed validation
    if checks["workforce_plan_structure"]:
        df = get_nested(wp, ["demand_forecasting"]) or {}
        driver = get_nested(df, ["driver_based"])
        if isinstance(driver, dict):
            eng = get_nested(driver, ["engineering"])
            if isinstance(eng, dict):
                pf = to_number(get_nested(eng, ["planned_features"]))
                dwepf = to_number(get_nested(eng, ["dev_weeks_per_feature"]))  # output value presence
                adewpq = to_number(get_nested(eng, ["available_dev_weeks_per_engineer_per_quarter"]))
                engineers_needed_out = to_number(get_nested(eng, ["engineers_needed"]))
                # Input values
                pf_in = to_number(company.get("planned_features"))
                dwepf_in = to_number(company.get("dev_weeks_per_feature"))
                adewpq_in = to_number(company.get("available_dev_weeks_per_engineer_per_quarter"))
                if None not in (pf_in, dwepf_in, adewpq_in, engineers_needed_out) and adewpq_in != 0:
                    expected_eng = math.ceil(pf_in * dwepf_in / adewpq_in)
                    if approx_equal(expected_eng, engineers_needed_out):
                        checks["driver_engineering_engineers_needed_valid"] = True

    # 5) Managerial span Support managers_needed validation
    if checks["workforce_plan_structure"]:
        df = get_nested(wp, ["demand_forecasting"]) or {}
        man = get_nested(df, ["managerial_span"])
        dept_plans = get_nested(wp, ["department_plans"])
        if isinstance(man, dict) and isinstance(dept_plans, dict):
            spans = get_nested(man, ["target_spans_by_function"])
            managers_needed = get_nested(man, ["managers_needed"])
            # Ensure target spans copied from input (at least Support exists and numeric)
            spans_in = company.get("target_spans_by_function") if isinstance(company, dict) else None
            support_span_in = None
            if isinstance(spans_in, dict):
                # find Support
                for k, v in spans_in.items():
                    if norm_key(k) == "support":
                        support_span_in = to_number(v)
                        break
            # Use output's target spans for formula (require presence) and compare with dept_plans Support demand
            support_span_out = None
            if isinstance(spans, dict):
                for k, v in spans.items():
                    if norm_key(k) == "support":
                        support_span_out = to_number(v)
                        break
            support_demand = None
            support_plan = None
            for k, v in dept_plans.items():
                if norm_key(k) == "support" and isinstance(v, dict):
                    support_plan = v
                    break
            if isinstance(support_plan, dict):
                support_demand = to_number(get_nested(support_plan, ["demand_forecast_headcount"]))
            manager_needed_out = None
            if isinstance(managers_needed, dict):
                for k, v in managers_needed.items():
                    if norm_key(k) == "support":
                        manager_needed_out = to_number(v)
                        break
            # Validate
            if None not in (support_span_out, support_demand, manager_needed_out) and support_span_out != 0:
                expected_mgrs = math.ceil(support_demand / support_span_out)
                # Also ensure input target spans include Support (presence), though not strictly required
                if approx_equal(expected_mgrs, manager_needed_out) and (support_span_in is None or approx_equal(support_span_in, support_span_out)):
                    checks["managerial_span_support_valid"] = True

    # 6) Department gaps for Engineering and Support
    if checks["workforce_plan_structure"]:
        dept_plans = get_nested(wp, ["department_plans"])
        ok_gap = True
        for dept_name in ["Engineering", "Support"]:
            dp = None
            if isinstance(dept_plans, dict):
                for k, v in dept_plans.items():
                    if norm_key(k) == norm_key(dept_name):
                        dp = v
                        break
            if not isinstance(dp, dict):
                ok_gap = False
                break
            demand = to_number(get_nested(dp, ["demand_forecast_headcount"]))
            current_fte = to_number(get_nested(dp, ["current_FTEs"])) or to_number(get_nested(dp, ["current_fte"]))
            pipeline = to_number(get_nested(dp, ["pipeline_hires"]))
            gap_out = to_number(get_nested(dp, ["headcount_gap"]))
            if None in (demand, current_fte, pipeline, gap_out):
                ok_gap = False
                break
            expected_gap = demand - (current_fte + pipeline)
            if not approx_equal(expected_gap, gap_out):
                ok_gap = False
                break
        if ok_gap:
            checks["dept_gap_calculations_valid"] = True

    # 7) Contingent workforce mix sums to 100
    if checks["workforce_plan_structure"]:
        cw = get_nested(wp, ["contingent_workforce"])
        if isinstance(cw, dict):
            tm = get_nested(cw, ["target_mix"])
            if isinstance(tm, dict):
                vals = {}
                for k, v in tm.items():
                    nk = norm_key(k)
                    if nk in ("fte", "contractors", "outsourced", "ai_agents"):
                        vals[nk] = to_number(v)
                if all(key in vals and vals[key] is not None for key in ("fte", "contractors", "outsourced", "ai_agents")):
                    total = vals["fte"] + vals["contractors"] + vals["outsourced"] + vals["ai_agents"]
                    if sum_close(total, 100.0, tol=0.5):
                        checks["contingent_mix_sums_to_100"] = True

    # 8) Hiring plan CSV: headers and coverage of departments
    headers_out, rows_out = parse_csv_required_columns(hiring_plan_csv)
    if headers_out is not None and rows_out is not None:
        req_cols = ["department", "role", "type", "quarter", "priority_score", "cost_estimate_fully_loaded"]
        has_all_headers = all(any(norm_key(h) == norm_key(rc) for h in headers_out) for rc in req_cols)
        coverage_ok = False
        if has_all_headers:
            # Build mapping for department column
            dept_col = None
            for h in headers_out:
                if norm_key(h) == "department":
                    dept_col = h
                    break
            if dept_col:
                covered = set()
                for r in rows_out:
                    dept_val = (r.get(dept_col) or "").strip()
                    if dept_val:
                        covered.add(dept_val)
                # input_depts may be empty (if input missing), require coverage only when input has departments
                if input_depts:
                    coverage_ok = input_depts.issubset(covered)
                else:
                    coverage_ok = len(covered) > 0
        if has_all_headers and coverage_ok:
            checks["hiring_plan_headers_and_coverage"] = True

    # 9) Succession risks JSON
    sr = read_json(succession_risks_json)
    input_roles = set()
    input_sr = read_json(succession_crit_roles_json)
    if isinstance(input_sr, list):
        for item in input_sr:
            if isinstance(item, dict):
                role = item.get("role") or item.get("title") or item.get("name")
                if not role:
                    # try normalized search
                    for k in item.keys():
                        if norm_key(k) in ("role", "title", "name"):
                            role = item[k]
                            break
                if role:
                    input_roles.add(str(role))
    elif isinstance(input_sr, dict):
        # Some inputs may wrap roles under a key
        for k, v in input_sr.items():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        role = item.get("role") or item.get("title") or item.get("name")
                        if not role:
                            for kk in item.keys():
                                if norm_key(kk) in ("role", "title", "name"):
                                    role = item[kk]
                                    break
                        if role:
                            input_roles.add(str(role))
    if isinstance(sr, dict) and input_roles:
        out_roles_map, ready_now_count_out = roles_from_output_succession(sr)
        # Contains all roles
        contains_all = all(any(str(ir) == orr for orr in out_roles_map.keys()) for ir in input_roles)
        # Each role has successors with readiness field present
        readiness_ok = True
        ready_now_count_calc = 0
        for ir in input_roles:
            if ir not in out_roles_map:
                readiness_ok = False
                break
            successors = out_roles_map[ir]["successors"]
            if not isinstance(successors, list) or len(successors) == 0:
                readiness_ok = False
                break
            # Ensure at least readiness field present in each successor
            has_readiness = any(any(norm_key(k) in ("readiness", "ready", "status") for k in s.keys()) for s in successors if isinstance(s, dict))
            if not has_readiness:
                readiness_ok = False
                break
            if has_ready_now(successors):
                ready_now_count_calc += 1
        count_ok = (ready_now_count_out is not None and ready_now_count_calc == ready_now_count_out)
        if contains_all and readiness_ok and count_ok:
            checks["succession_risks_roles_and_ready_now_count"] = True

    # 10) Quarterly review has Q1-Q4 strings
    qr_txt = read_text(quarterly_review_md)
    if isinstance(qr_txt, str):
        if all(q in qr_txt for q in ["Q1", "Q2", "Q3", "Q4"]):
            checks["quarterly_review_has_qs"] = True

    # Compute reward: fraction of checks passed (0..1). Baseline with no outputs yields 0.
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0
    # Ensure exact 0.0 if no outputs or missing required artifacts
    # If all checks are False, reward is already 0.0
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()