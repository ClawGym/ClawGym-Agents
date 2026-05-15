import csv
import json
import os
import sys
from typing import Dict, Any, List, Tuple

def parse_number(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "" or s.lower() == "na" or s.lower() == "null":
        return None
    # remove currency, commas, percent
    s = s.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None

def parse_int(val):
    f = parse_number(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None

def parse_bool(val):
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "on")

def load_company_profile(path: str) -> Dict[str, Any]:
    # Minimal YAML parser for simple key: value pairs
    profile = {}
    if not os.path.isfile(path):
        return profile
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#") or raw.startswith("---"):
                continue
            # handle "key: value" simple scalars
            if ":" in raw:
                key, val = raw.split(":", 1)
                key = key.strip()
                val = val.strip()
                # remove quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                # attempt to coerce
                # Keep original string for name/period; numeric for revenue/employee_count
                if key in ("revenue_monthly", "employee_count"):
                    num = parse_number(val)
                    if key == "employee_count":
                        profile[key] = int(num) if num is not None else None
                    else:
                        profile[key] = num
                else:
                    profile[key] = val
    return profile

def load_inventory_csv(path: str) -> List[Dict[str, Any]]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Normalize keys: strip whitespace
            norm = { (k.strip() if k is not None else k): (v.strip() if isinstance(v, str) else v) for k, v in r.items() }
            rows.append(norm)
    return rows

def compute_scores(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Build capability group counts across the full inventory (by group name)
    group_counts: Dict[str, int] = {}
    for r in rows:
        group = (r.get("capability_group") or "").strip()
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
    # Prepare computed dict by tool name
    computed: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        category = (r.get("category") or "").strip()
        monthly_cost = parse_number(r.get("monthly_cost"))
        licensed_users = parse_int(r.get("licensed_users"))
        active_users = parse_int(r.get("active_users"))
        utilization_pct = parse_number(r.get("utilization_pct"))
        roi_mult = parse_number(r.get("measured_roi_multiplier"))
        capability_group = (r.get("capability_group") or "").strip()

        # Usage score
        usage = 10  # default
        if licensed_users is not None and licensed_users > 0:
            # If active_users missing, treat as 0 for deterministic handling
            au = 0 if active_users is None else active_users
            if au == 0:
                usage = 0
            else:
                rratio = au / float(licensed_users) if licensed_users > 0 else 0.0
                if rratio < 0.25:
                    usage = 10
                elif rratio <= 0.75:
                    usage = 20
                else:
                    usage = 30
        elif utilization_pct is not None:
            if utilization_pct == 0:
                usage = 0
            elif utilization_pct < 25:
                usage = 10
            elif utilization_pct <= 75:
                usage = 20
            else:
                usage = 30
        else:
            usage = 10

        # ROI score
        roi_score = 0
        if roi_mult is None or roi_mult < 1.0:
            roi_score = 0
        elif 1.0 <= roi_mult < 2.0:
            roi_score = 10
        elif 2.0 <= roi_mult <= 5.0:
            roi_score = 30
        else:  # > 5.0
            roi_score = 40

        # Replaceability score
        repl = 20
        if category in ("Foundation Models", "SaaS with AI"):
            if capability_group:
                cnt = group_counts.get(capability_group, 1)
            else:
                cnt = 1
            if cnt >= 3:
                repl = 0
            elif cnt == 2:
                repl = 10
            else:
                repl = 20
        else:
            repl = 20

        total = float(usage + roi_score + repl)

        if total <= 30:
            action = "CUT"
        elif 31 <= total <= 50:
            action = "REVIEW"
        elif 51 <= total <= 70:
            action = "OPTIMIZE"
        else:
            action = "KEEP"

        computed[name] = {
            "name": name,
            "category": category,
            "capability_group": capability_group,
            "monthly_cost": monthly_cost if monthly_cost is not None else 0.0,
            "usage_score": float(usage),
            "roi_score": float(roi_score),
            "replaceability_score": float(repl),
            "total_score": float(total),
            "action": action,
        }
    return computed

def compute_waste(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    unused = 0.0
    overprov = 0.0
    model_downgrade = 0.0
    # Group by capability_group for vendor consolidation
    group_costs: Dict[str, float] = {}
    group_counts: Dict[str, int] = {}

    for r in rows:
        monthly_cost = parse_number(r.get("monthly_cost")) or 0.0
        licensed_users = parse_int(r.get("licensed_users"))
        active_users = parse_int(r.get("active_users"))
        utilization_pct = parse_number(r.get("utilization_pct"))
        environment = (r.get("environment") or "").strip().lower()
        always_on = parse_bool(r.get("always_on"))
        category = (r.get("category") or "").strip()
        cheaper_model_available = parse_bool(r.get("cheaper_model_available"))
        capability_group = (r.get("capability_group") or "").strip()

        # Unused licenses (licensed_users > 0)
        if licensed_users is not None and licensed_users > 0:
            au = 0 if active_users is None else active_users
            try:
                unused += monthly_cost * (1.0 - (au / float(licensed_users)))
            except ZeroDivisionError:
                pass

        # Over-provisioned infra (numeric utilization_pct)
        if utilization_pct is not None:
            if utilization_pct < 50:
                overprov += monthly_cost * (0.5 - utilization_pct / 100.0)
            # Plus dev always_on add
            if environment == "dev" and always_on:
                overprov += 0.2 * monthly_cost

        # Model tier downgrades (Foundation Models only)
        if category == "Foundation Models" and cheaper_model_available:
            model_downgrade += 0.3 * monthly_cost

        # Vendor consolidation grouping (non-empty groups)
        if capability_group:
            group_costs[capability_group] = group_costs.get(capability_group, 0.0) + monthly_cost
            group_counts[capability_group] = group_counts.get(capability_group, 0) + 1

    vendor_consol = 0.0
    for g, cnt in group_counts.items():
        if cnt > 1:
            vendor_consol += 0.3 * group_costs.get(g, 0.0)

    total_recoverable = unused + overprov + model_downgrade + vendor_consol
    return {
        "unused_licenses": round(unused, 2),
        "over_provisioned_infra": round(overprov, 2),
        "model_tier_downgrades": round(model_downgrade, 2),
        "vendor_consolidation": round(vendor_consol, 2),
        "total_recoverable": round(total_recoverable, 2),
    }

def approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol

def get_float_from(obj: Any) -> float:
    if isinstance(obj, (int, float)):
        return float(obj)
    return parse_number(obj) or 0.0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not needed for logic but computed per guidelines
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "files_exist": False,
        "report_json_valid": False,
        "scores_csv_header_ok": False,
        "totals_monthly_ok": False,
        "totals_annual_ok": False,
        "totals_percent_ok": False,
        "tool_counts_match": False,
        "tool_names_match": False,
        "scores_ranges_ok": False,
        "actions_mapping_ok": False,
        "scores_crossfile_match": False,
        "waste_unused_ok": False,
        "waste_overprov_ok": False,
        "waste_model_downgrade_ok": False,
        "waste_vendor_consol_ok": False,
        "waste_total_recoverable_ok": False,
        "benchmarks_ok": False,
        "plan_present_ok": False,
        "vendor_consolidation_md_mappings_ok": False,
        "assumptions_mentions_ok": False,
    }

    # Paths
    inv_path = os.path.join(input_dir, "ai_inventory.csv")
    profile_path = os.path.join(input_dir, "company_profile.yaml")
    report_path = os.path.join(output_dir, "report.json")
    scores_path = os.path.join(output_dir, "scores.csv")
    vendor_md_path = os.path.join(output_dir, "vendor_consolidation.md")
    assumptions_md_path = os.path.join(output_dir, "assumptions.md")

    # Check existence
    files_exist = all(os.path.isfile(p) for p in [report_path, scores_path, vendor_md_path, assumptions_md_path])
    if not files_exist:
        # Early end with zero reward; print results
        checks["files_exist"] = False
        print(json.dumps({"reward": 0.0, **checks}))
        return
    checks["files_exist"] = True

    # Load inputs
    inv_rows = load_inventory_csv(inv_path)
    profile = load_company_profile(profile_path)

    # Parse report.json
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        checks["report_json_valid"] = True
    except Exception:
        report = {}

    # Validate scores.csv header and rows
    expected_header = ["name","category","monthly_cost","capability_group","usage_score","roi_score","replaceability_score","total_score","action"]
    scores_rows: List[Dict[str, Any]] = []
    try:
        with open(scores_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            # Compare exact header
            checks["scores_csv_header_ok"] = header == expected_header
        with open(scores_path, "r", encoding="utf-8") as f:
            dict_reader = csv.DictReader(f)
            for r in dict_reader:
                scores_rows.append(r)
    except Exception:
        checks["scores_csv_header_ok"] = False

    # Totals and percentages
    total_monthly = 0.0
    for r in inv_rows:
        total_monthly += parse_number(r.get("monthly_cost")) or 0.0
    total_monthly = round(total_monthly, 2)
    total_annual = round(total_monthly * 12.0, 2)
    revenue_monthly = parse_number(profile.get("revenue_monthly")) or 0.0
    percent = round(((total_monthly / revenue_monthly) * 100.0) if revenue_monthly > 0 else 0.0, 2)

    if checks["report_json_valid"]:
        rep_totals = report.get("totals", {})
        rep_total_monthly = get_float_from(rep_totals.get("total_monthly_spend"))
        rep_total_annual = get_float_from(rep_totals.get("total_annual_spend"))
        rep_percent = get_float_from(rep_totals.get("ai_spend_percent_of_monthly_revenue"))
        # Tolerances
        if approx_equal(rep_total_monthly, total_monthly, 0.01):
            checks["totals_monthly_ok"] = True
        if approx_equal(rep_total_annual, total_annual, 0.01):
            checks["totals_annual_ok"] = True
        if approx_equal(rep_percent, percent, 0.05):
            checks["totals_percent_ok"] = True

    # Tool coverage and scoring correctness
    # Counts
    n_inv = len(inv_rows)
    tools_list = report.get("tools", []) if isinstance(report, dict) else []
    if isinstance(tools_list, list) and len(tools_list) == n_inv and len(scores_rows) == n_inv:
        checks["tool_counts_match"] = True

    inv_names = [ (r.get("name") or "").strip() for r in inv_rows ]
    rep_names = [ (t.get("name") or "").strip() for t in tools_list ] if isinstance(tools_list, list) else []
    csv_names = [ (r.get("name") or "").strip() for r in scores_rows ]

    if set(inv_names) == set(rep_names) == set(csv_names) and len(inv_names) == len(set(inv_names)):
        checks["tool_names_match"] = True

    # Compute our scores and actions
    computed = compute_scores(inv_rows)

    # Verify scores ranges, actions mapping, cross-file matches
    ranges_ok = True
    actions_ok = True
    cross_ok = True
    # Build helper maps from outputs
    rep_map = { (t.get("name") or "").strip(): t for t in tools_list } if isinstance(tools_list, list) else {}
    csv_map = { (r.get("name") or "").strip(): r for r in scores_rows }

    for name, comp in computed.items():
        # ranges
        u = comp["usage_score"]; rscore = comp["roi_score"]; rep = comp["replaceability_score"]; tot = comp["total_score"]
        if not (0 <= u <= 30 and 0 <= rscore <= 40 and 0 <= rep <= 30 and approx_equal(tot, u + rscore + rep, 0.01)):
            ranges_ok = False
            break
        # mapping
        mapped = "CUT" if tot <= 30 else ("REVIEW" if 31 <= tot <= 50 else ("OPTIMIZE" if 51 <= tot <= 70 else "KEEP"))
        if comp["action"] != mapped:
            actions_ok = False
            break
        # cross-file compare
        rep_item = rep_map.get(name)
        csv_item = csv_map.get(name)
        if not rep_item or not csv_item:
            cross_ok = False
            break
        # compare scores with tolerance
        rep_scores = rep_item.get("scores", {})
        rep_u = get_float_from(rep_scores.get("usage"))
        rep_r = get_float_from(rep_scores.get("roi"))
        rep_repl = get_float_from(rep_scores.get("replaceability"))
        rep_total = get_float_from(rep_scores.get("total"))
        # Compare to CSV values
        csv_u = get_float_from(csv_item.get("usage_score"))
        csv_r = get_float_from(csv_item.get("roi_score"))
        csv_repl = get_float_from(csv_item.get("replaceability_score"))
        csv_total = get_float_from(csv_item.get("total_score"))
        csv_action = (csv_item.get("action") or "").strip()
        rep_action = (rep_item.get("action") or "").strip()

        if not (approx_equal(rep_u, u, 0.01) and approx_equal(csv_u, u, 0.01) and
                approx_equal(rep_r, rscore, 0.01) and approx_equal(csv_r, rscore, 0.01) and
                approx_equal(rep_repl, rep, 0.01) and approx_equal(csv_repl, rep, 0.01) and
                approx_equal(rep_total, tot, 0.01) and approx_equal(csv_total, tot, 0.01) and
                csv_action == comp["action"] and rep_action == comp["action"]):
            cross_ok = False
            break

    if n_inv > 0:
        checks["scores_ranges_ok"] = ranges_ok
        checks["actions_mapping_ok"] = actions_ok
        checks["scores_crossfile_match"] = cross_ok

    # Waste recomputation checks
    waste_calc = compute_waste(inv_rows)
    rep_waste = (report.get("waste_identified") or {}) if isinstance(report, dict) else {}
    # Compare each component and total
    rep_unused = get_float_from(rep_waste.get("unused_licenses"))
    rep_overprov = get_float_from(rep_waste.get("over_provisioned_infra"))
    rep_model = get_float_from(rep_waste.get("model_tier_downgrades"))
    rep_vendor = get_float_from(rep_waste.get("vendor_consolidation"))
    rep_total_rec = get_float_from(rep_waste.get("total_recoverable"))

    if approx_equal(rep_unused, waste_calc["unused_licenses"], 0.01):
        checks["waste_unused_ok"] = True
    if approx_equal(rep_overprov, waste_calc["over_provisioned_infra"], 0.01):
        checks["waste_overprov_ok"] = True
    if approx_equal(rep_model, waste_calc["model_tier_downgrades"], 0.01):
        checks["waste_model_downgrade_ok"] = True
    if approx_equal(rep_vendor, waste_calc["vendor_consolidation"], 0.01):
        checks["waste_vendor_consol_ok"] = True
    if approx_equal(rep_total_rec, waste_calc["total_recoverable"], 0.01):
        checks["waste_total_recoverable_ok"] = True

    # Benchmarks
    bracket = None
    waste_range = None
    emp = profile.get("employee_count")
    try:
        emp_val = int(emp) if emp is not None else None
    except Exception:
        emp_val = None
    if emp_val is not None:
        if 10 <= emp_val <= 25:
            bracket = "10-25"
            waste_range = "35-50%"
        elif 25 < emp_val <= 50:
            bracket = "25-50"
            waste_range = "30-45%"
        elif 50 < emp_val <= 200:
            bracket = "50-200"
            waste_range = "25-40%"
        elif 200 < emp_val <= 500:
            bracket = "200-500"
            waste_range = "20-35%"
        elif emp_val > 500:
            bracket = "500+"
            waste_range = "15-30%"

    rep_bench = report.get("benchmarks", {}) if isinstance(report, dict) else {}
    rep_bracket = rep_bench.get("company_size_bracket")
    rep_range = rep_bench.get("typical_waste_range")
    if bracket is not None and rep_bracket == bracket and rep_range == waste_range:
        checks["benchmarks_ok"] = True

    # Plan presence
    plan = report.get("plan_90_day", {}) if isinstance(report, dict) else {}
    plan_keys_ok = True
    for k in ("weeks_1_2", "weeks_3_4", "weeks_5_8", "weeks_9_12"):
        v = plan.get(k)
        if not isinstance(v, list) or len(v) == 0:
            plan_keys_ok = False
            break
    checks["plan_present_ok"] = plan_keys_ok

    # Vendor consolidation md lines: at least 3 lines including "->"
    try:
        with open(vendor_md_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        arrow_lines = [ln for ln in lines if "->" in ln]
        checks["vendor_consolidation_md_mappings_ok"] = len(arrow_lines) >= 3
    except Exception:
        checks["vendor_consolidation_md_mappings_ok"] = False

    # Assumptions mentions
    try:
        with open(assumptions_md_path, "r", encoding="utf-8") as f:
            txt = f.read()
        low = txt.lower()
        has_usage = "usage score" in low
        has_roi = "roi score" in low
        has_repl = "replaceability" in low
        has_30 = "30%" in low
        checks["assumptions_mentions_ok"] = all([has_usage, has_roi, has_repl, has_30])
    except Exception:
        checks["assumptions_mentions_ok"] = False

    # Compute reward as average of passed checks, but if files missing or outputs empty -> 0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if checks["files_exist"]:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward in [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()