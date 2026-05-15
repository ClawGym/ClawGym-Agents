import json
import os
import sys
import csv
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [row for row in reader]
        return header, rows
    except Exception:
        return None, None

def try_parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None

def check_workflow_yaml(path):
    # Returns dict of checks and helper data
    checks = {
        "workflow_yaml_exists": False,
        "workflow_yaml_has_keys": False,
        "workflow_yaml_actions_len_ge_4": False,
    }
    content = load_text(path)
    if content is None:
        return checks, None

    checks["workflow_yaml_exists"] = True

    # First try to parse as JSON (which is valid YAML)
    data = try_parse_json(content)
    actions_len = 0
    required_keys = ["rationale", "trigger", "conditions", "actions", "error_handling"]

    if isinstance(data, dict):
        has_keys = all(k in data for k in required_keys)
        checks["workflow_yaml_has_keys"] = bool(has_keys)
        if has_keys and isinstance(data.get("actions"), list):
            actions_len = len(data["actions"])
            if actions_len >= 4:
                checks["workflow_yaml_actions_len_ge_4"] = True
        else:
            # if actions present but not a list, fail the length check
            pass
        return checks, {"actions_len": actions_len}

    # Fallback: minimal structural YAML-ish parsing for top-level keys and actions list count
    # This does not fully validate YAML but ensures presence of top-level keys and counts list items under "actions".
    lines = content.splitlines()
    keys_found = set()
    actions_count = 0
    i = 0
    # Regex for a top-level key: starts at column 0 (no leading spaces), not a comment, has "key:" form
    top_key_re = re.compile(r'^([A-Za-z0-9_-]+)\s*:\s*(.*)$')
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = top_key_re.match(line)
        if m and (line == line.lstrip()):  # top-level
            key = m.group(1).strip()
            key_lower = key.lower()
            if key_lower in [k.lower() for k in required_keys]:
                keys_found.add(key_lower)
            if key_lower == "actions":
                # Count list items under actions indentation
                i += 1
                while i < len(lines):
                    sub = lines[i]
                    if not sub.strip() or sub.lstrip().startswith("#"):
                        i += 1
                        continue
                    # Stop if next top-level key appears
                    if sub == sub.lstrip() and top_key_re.match(sub):
                        break
                    if re.match(r'^\s*-\s+', sub):
                        actions_count += 1
                    i += 1
                continue
        i += 1
    # Evaluate keys presence
    checks["workflow_yaml_has_keys"] = all(k.lower() in keys_found for k in [rk.lower() for rk in required_keys])
    checks["workflow_yaml_actions_len_ge_4"] = actions_count >= 4
    return checks, {"actions_len": actions_count}

def check_haccp_plan_csv(path):
    checks = {
        "haccp_plan_csv_exists_and_header": False,
        "haccp_plan_has_all_steps": False,
        "haccp_plan_has_significant_yes": False,
    }
    header, rows = read_csv_dicts(path)
    expected_header = ["Step","Biological","Chemical","Physical","Significant","Justification","Control Measure"]
    if header is None:
        return checks
    # Exact header match
    if header == expected_header:
        checks["haccp_plan_csv_exists_and_header"] = True
    # Check required steps present
    required_steps = {"Receiving","Storage","Prep","Cook","Cool","Package","Ship"}
    steps_present = set()
    significant_yes = False
    if rows is not None:
        for row in rows:
            step = (row.get("Step") or "").strip()
            if step in required_steps:
                steps_present.add(step)
            sig = (row.get("Significant") or "").strip().lower()
            if sig in ("yes", "y", "true"):
                significant_yes = True
    checks["haccp_plan_has_all_steps"] = steps_present == required_steps
    checks["haccp_plan_has_significant_yes"] = significant_yes
    return checks

def check_critical_limits_csv(path):
    checks = {
        "critical_limits_csv_exists_and_header": False,
        "critical_limits_has_required_ccps": False,
        "critical_limits_content_substrings_and_citation": False,
    }
    header, rows = read_csv_dicts(path)
    expected_header = ["CCP","Hazard","Critical Limit","Scientific Basis"]
    if header is None:
        return checks
    if header == expected_header:
        checks["critical_limits_csv_exists_and_header"] = True

    # Build map of CCP lower->row for required ones
    required_ccps = ["Cold holding","Hot holding","Cooling","Cooking"]
    found = {}
    if rows is not None:
        for row in rows:
            ccp_val = (row.get("CCP") or "").strip()
            ccp_key = ccp_val.lower()
            if ccp_val:
                found.setdefault(ccp_key, row)
    has_all = all(ccp.lower() in found for ccp in required_ccps)
    checks["critical_limits_has_required_ccps"] = has_all

    # Validate content substrings and citation for each required CCP row
    content_ok = True
    if has_all:
        # Cold holding: Critical Limit contains "41°F", Scientific Basis contains "FDA"
        row = found["cold holding"]
        cl = (row.get("Critical Limit") or "")
        sb = (row.get("Scientific Basis") or "")
        if "41°F" not in cl or ("FDA" not in sb and "CFR" not in sb):
            content_ok = False
        # Hot holding: "135°F"
        row = found["hot holding"]
        cl = (row.get("Critical Limit") or "")
        sb = (row.get("Scientific Basis") or "")
        if "135°F" not in cl or ("FDA" not in sb and "CFR" not in sb):
            content_ok = False
        # Cooling: "135°F" and "70°F" and "41°F"
        row = found["cooling"]
        cl = (row.get("Critical Limit") or "")
        sb = (row.get("Scientific Basis") or "")
        need_subs = ["135°F","70°F","41°F"]
        if not all(s in cl for s in need_subs) or ("FDA" not in sb and "CFR" not in sb):
            content_ok = False
        # Cooking: "165°F"
        row = found["cooking"]
        cl = (row.get("Critical Limit") or "")
        sb = (row.get("Scientific Basis") or "")
        if "165°F" not in cl or ("FDA" not in sb and "CFR" not in sb):
            content_ok = False
    else:
        content_ok = False
    checks["critical_limits_content_substrings_and_citation"] = content_ok
    return checks

def float_eq(a, b, tol=1e-4):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def check_roi_json(path):
    checks = {
        "roi_json_exists_and_valid": False,
        "roi_json_fields_present": False,
        "roi_json_formulas_consistent": False,
    }
    text = load_text(path)
    if text is None:
        return checks, []
    try:
        data = json.loads(text)
    except Exception:
        return checks, []
    if not isinstance(data, list):
        return checks, []
    checks["roi_json_exists_and_valid"] = True

    required_keys = [
        "task",
        "minutes_per_task",
        "frequency_per_month",
        "setup_hours",
        "tool_monthly_cost",
        "time_saved_hours_per_month",
        "monthly_value_saved",
        "setup_cost",
        "payback_months",
    ]
    fields_present = True
    formulas_ok = True
    processed = []
    for obj in data:
        if not isinstance(obj, dict):
            fields_present = False
            formulas_ok = False
            continue
        if not all(k in obj for k in required_keys):
            fields_present = False
        # Extract numbers
        mpt = to_float(obj.get("minutes_per_task"))
        fpm = to_float(obj.get("frequency_per_month"))
        sh = to_float(obj.get("setup_hours"))
        tmc = to_float(obj.get("tool_monthly_cost"))
        tsh = to_float(obj.get("time_saved_hours_per_month"))
        mvs = to_float(obj.get("monthly_value_saved"))
        sc = to_float(obj.get("setup_cost"))
        pm = to_float(obj.get("payback_months"))
        if None in (mpt, fpm, sh, tmc, tsh, mvs, sc, pm):
            formulas_ok = False
        else:
            calc_tsh = (mpt / 60.0) * fpm
            calc_mvs = calc_tsh * 50.0
            calc_sc = sh * 50.0
            denom = (calc_mvs - tmc)
            if denom <= 0:
                # If denominator non-positive, cannot compute sensible payback; mark as formula fail
                formulas_ok = False
                calc_pm = None
            else:
                calc_pm = calc_sc / denom
            # Compare
            if not float_eq(tsh, calc_tsh):
                formulas_ok = False
            if not float_eq(mvs, calc_mvs):
                formulas_ok = False
            if not float_eq(sc, calc_sc):
                formulas_ok = False
            if calc_pm is None or not float_eq(pm, calc_pm):
                formulas_ok = False
        processed.append({
            "task": obj.get("task"),
            "payback_months": pm if pm is not None else float("inf"),
        })
    checks["roi_json_fields_present"] = fields_present
    checks["roi_json_formulas_consistent"] = formulas_ok
    return checks, processed

def check_roi_summary(path, roi_items):
    checks = {
        "roi_summary_md_exists_and_top3_fastest": False,
        "roi_summary_mentions_slow_over_6_months_when_applicable": False,
    }
    content = load_text(path)
    if content is None:
        return checks
    checks["roi_summary_md_exists_and_top3_fastest"] = False  # will set True if conditions met
    # Identify tasks with payback < 3 and > 6
    fast = [item for item in roi_items if isinstance(item.get("payback_months"), (int, float)) and item["payback_months"] is not None and item["payback_months"] < 3.0 and isinstance(item.get("task"), str)]
    slow = [item for item in roi_items if isinstance(item.get("payback_months"), (int, float)) and item["payback_months"] is not None and item["payback_months"] > 6.0 and isinstance(item.get("task"), str)]
    # Must list at least 3 items with payback <3 months that appear in roi.json (by matching task names)
    content_lower = content.lower()
    fast_mentions = 0
    for it in fast:
        task = it["task"]
        if task and task.strip() and task.lower() in content_lower:
            fast_mentions += 1
    if len(fast) >= 3 and fast_mentions >= 3:
        checks["roi_summary_md_exists_and_top3_fastest"] = True

    # Must mention any items with payback >6 months (we require all to be mentioned if any exist)
    if slow:
        all_slow_mentioned = True
        for it in slow:
            task = it["task"]
            if not task or task.strip().lower() not in content_lower:
                all_slow_mentioned = False
                break
        checks["roi_summary_mentions_slow_over_6_months_when_applicable"] = all_slow_mentioned
    else:
        # If none exist, consider this check as True (nothing to mention)
        checks["roi_summary_mentions_slow_over_6_months_when_applicable"] = True

    return checks

def check_pipeline_md(path):
    checks = {
        "pipeline_md_includes_roles_handoff_success": False
    }
    content = load_text(path)
    if content is None:
        return checks
    c = content.lower()
    roles_ok = all(word in c for word in ["planner", "developer", "verifier", "tester", "reviewer"])
    has_handoff = "handoff" in c
    has_success = "success criteria" in c
    checks["pipeline_md_includes_roles_handoff_success"] = roles_ok and has_handoff and has_success
    return checks

def check_maintenance_md(path):
    checks = {
        "maintenance_md_has_sections_and_alerts": False
    }
    content = load_text(path)
    if content is None:
        return checks
    c = content.lower()
    has_weekly = "weekly check" in c
    has_monthly = "monthly audit" in c
    has_alerts = "error alerts" in c
    checks["maintenance_md_has_sections_and_alerts"] = has_weekly and has_monthly and has_alerts
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # Not used in scoring

    # Initialize checks dict with all False
    checks = {
        # workflow
        "workflow_yaml_exists": False,
        "workflow_yaml_has_keys": False,
        "workflow_yaml_actions_len_ge_4": False,
        # haccp
        "haccp_plan_csv_exists_and_header": False,
        "haccp_plan_has_all_steps": False,
        "haccp_plan_has_significant_yes": False,
        # critical limits
        "critical_limits_csv_exists_and_header": False,
        "critical_limits_has_required_ccps": False,
        "critical_limits_content_substrings_and_citation": False,
        # roi json
        "roi_json_exists_and_valid": False,
        "roi_json_fields_present": False,
        "roi_json_formulas_consistent": False,
        # roi summary
        "roi_summary_md_exists_and_top3_fastest": False,
        "roi_summary_mentions_slow_over_6_months_when_applicable": False,
        # pipeline
        "pipeline_md_includes_roles_handoff_success": False,
        # maintenance
        "maintenance_md_has_sections_and_alerts": False,
    }

    # If output directory doesn't exist or is empty, we will end up with zero reward
    # Workflow YAML
    workflow_path = os.path.join(output_dir, "workflow_spec.yaml")
    wf_checks, _wf_info = check_workflow_yaml(workflow_path)
    checks.update(wf_checks)

    # HACCP plan CSV
    haccp_path = os.path.join(output_dir, "haccp_plan.csv")
    checks.update(check_haccp_plan_csv(haccp_path))

    # Critical limits CSV
    crit_path = os.path.join(output_dir, "critical_limits.csv")
    checks.update(check_critical_limits_csv(crit_path))

    # ROI JSON
    roi_json_path = os.path.join(output_dir, "roi.json")
    roi_checks, roi_items = check_roi_json(roi_json_path)
    checks.update(roi_checks)

    # ROI summary MD
    roi_summary_path = os.path.join(output_dir, "roi_summary.md")
    checks.update(check_roi_summary(roi_summary_path, roi_items))

    # Pipeline MD
    pipeline_path = os.path.join(output_dir, "pipeline.md")
    checks.update(check_pipeline_md(pipeline_path))

    # Maintenance MD
    maintenance_path = os.path.join(output_dir, "maintenance.md")
    checks.update(check_maintenance_md(maintenance_path))

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if no outputs contributed (i.e., output is missing or no file-based checks passed), reward should be 0.0
    # Our calculation already yields 0.0 if none passed.

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()