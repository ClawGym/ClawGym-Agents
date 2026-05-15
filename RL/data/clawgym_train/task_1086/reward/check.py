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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv_tasks(path):
    """
    Returns:
      {
        "ok": bool,
        "tasks_all": set of all task names,
        "tasks_rule_based": set of rule-based task names
      }
    Detects likely columns:
      - name column: one of ["task","name","title","task_name","task-title","taskname"]
      - rule-based column: one of ["rule_based","rule-based","is_rule_based","rulebased","rule","rule_flag"]
    """
    result = {"ok": False, "tasks_all": set(), "tasks_rule_based": set()}
    if not os.path.isfile(path):
        return result
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = [h for h in reader.fieldnames] if reader.fieldnames else []
            norm_headers = [normalize_key(h) for h in headers]
            name_idx = None
            rule_idx = None
            name_candidates = {"task","name","title","task_name","task-title","taskname"}
            rule_candidates = {"rule_based","rule-based","is_rule_based","rulebased","rule","rule_flag","rule_flagged"}
            for i, nh in enumerate(norm_headers):
                if name_idx is None and nh in name_candidates:
                    name_idx = i
                if rule_idx is None and nh in rule_candidates:
                    rule_idx = i
            # fallback: if there's a "task" looking header even if not normalized match
            if name_idx is None and headers:
                for i, h in enumerate(headers):
                    if "task" in h.lower():
                        name_idx = i
                        break
            # fallback for rule
            if rule_idx is None and headers:
                for i, h in enumerate(headers):
                    hl = h.lower()
                    if "rule" in hl and ("based" in hl or "flag" in hl):
                        rule_idx = i
                        break
            # If still not found, we cannot reliably parse
            if name_idx is None or rule_idx is None:
                # Try to proceed by heuristics: assume first column is name, and look for any column with "rule" text
                if name_idx is None and headers:
                    name_idx = 0
                if rule_idx is None and headers:
                    for i, h in enumerate(headers):
                        if "rule" in h.lower():
                            rule_idx = i
                            break
            if name_idx is None or rule_idx is None:
                # cannot parse
                for row in reader:
                    pass
                return result
            name_key = headers[name_idx]
            rule_key = headers[rule_idx]
            for row in reader:
                name = (row.get(name_key) or "").strip()
                if not name:
                    continue
                result["tasks_all"].add(name)
                rule_val = (str(row.get(rule_key) or "")).strip().lower()
                if is_truthy(rule_val):
                    result["tasks_rule_based"].add(name)
        result["ok"] = True
        return result
    except Exception:
        return result

def is_truthy(val):
    v = str(val).strip().lower()
    return v in {"yes","true","y","1","t"}

def normalize_key(s):
    return re.sub(r"[\s\-]+", "_", (s or "").strip().lower())

def parse_simple_yaml(path):
    """
    Minimal YAML parser for simple key: value pairs at top level.
    Returns dict of keys to values, tries to coerce numbers.
    Ignores comments and nested structures.
    """
    data = {}
    if not os.path.isfile(path):
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # strip comments
                if "#" in line:
                    line = line.split("#", 1)[0]
                if not line.strip():
                    continue
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # remove quotes
                if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                    val = val[1:-1]
                # try to coerce to number or bool
                if re.fullmatch(r"[-+]?\d+(\.\d+)?", val):
                    try:
                        if "." in val:
                            coerced = float(val)
                        else:
                            coerced = int(val)
                        data[key] = coerced
                        continue
                    except Exception:
                        pass
                lv = val.lower()
                if lv in ("true","false"):
                    data[key] = (lv == "true")
                else:
                    data[key] = val
        return data
    except Exception:
        return {}

def find_hourly_value(yaml_dict):
    # Expected exact key per spec: hourly_value_usd
    # Also accept variants just in case (lowercased)
    cand_keys = ["hourly_value_usd","hourly_value","hourly_rate_usd","hourly_rate"]
    for k in list(yaml_dict.keys()):
        if normalize_key(k) in cand_keys:
            v = yaml_dict[k]
            try:
                return float(v)
            except Exception:
                pass
    # try normalized keys from normalized dict
    norm_map = {normalize_key(k): v for k, v in yaml_dict.items()}
    for ck in cand_keys:
        if ck in norm_map:
            try:
                return float(norm_map[ck])
            except Exception:
                pass
    return None

def find_monthly_budget(yaml_dict):
    # Accept common variants
    cand_keys = [
        "monthly_budget_usd","monthly_budget","budget_usd","budget","tool_budget","automation_budget","automation_monthly_budget"
    ]
    for k in list(yaml_dict.keys()):
        if normalize_key(k) in cand_keys:
            v = yaml_dict[k]
            try:
                return float(v)
            except Exception:
                pass
    norm_map = {normalize_key(k): v for k, v in yaml_dict.items()}
    for ck in cand_keys:
        if ck in norm_map:
            try:
                return float(norm_map[ck])
            except Exception:
                pass
    return None

def approx_equal(a, b, rel_tol=1e-6, abs_tol=1e-6):
    try:
        return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (artifact-dependent default False)
    checks = {
        "has_workflows_json": False,
        "has_summary_md": False,
        "top_source_ok": False,
        "top_currency_ok": False,
        "hourly_value_matches_yaml": False,
        "workflows_len_ok": False,
        "tool_platforms_valid": False,
        "actions_len_ok": False,
        "error_handling_has_alert_notify": False,
        "test_plan_has_edge_or_fail": False,
        "monitoring_plan_has_cadence": False,
        "source_tasks_valid": False,
        "roi_monthly_hours_saved_correct": False,
        "roi_payback_months_correct": False,
        "tool_cost_matches_platform": False,
        "tool_cost_within_budget": False,
        "prioritization_method_ok": False,
        "prioritization_order_ok": False,
        "summary_has_all_headings": False,
        "summary_exec_has_bullet": False,
    }

    # Load inputs
    tasks_csv_path = os.path.join(input_dir, "tasks.csv")
    tooling_yaml_path = os.path.join(input_dir, "tooling_prefs.yaml")
    tasks_info = parse_csv_tasks(tasks_csv_path)
    tooling = parse_simple_yaml(tooling_yaml_path)
    hourly_value_from_yaml = find_hourly_value(tooling)
    budget_from_yaml = find_monthly_budget(tooling)

    # Platform cost map
    platform_cost = {"Zapier": 20.0, "Make": 12.0, "n8n": 0.0}

    # Load outputs
    workflows_path = os.path.join(output_dir, "workflows.json")
    summary_path = os.path.join(output_dir, "summary.md")

    workflows_obj = load_json(workflows_path)
    if workflows_obj is not None and isinstance(workflows_obj, dict):
        checks["has_workflows_json"] = True

    summary_txt = load_text(summary_path)
    if isinstance(summary_txt, str):
        checks["has_summary_md"] = True

    # Validate workflows.json content
    if checks["has_workflows_json"]:
        # top-level fields
        if workflows_obj.get("source") == "automation_audit_v1":
            checks["top_source_ok"] = True
        if workflows_obj.get("currency") == "USD":
            checks["top_currency_ok"] = True
        # hourly value must match yaml
        hvj = workflows_obj.get("hourly_value_usd", None)
        if hourly_value_from_yaml is not None:
            try:
                hvj_f = float(hvj)
                if approx_equal(hvj_f, float(hourly_value_from_yaml)):
                    checks["hourly_value_matches_yaml"] = True
            except Exception:
                pass

        workflows = workflows_obj.get("workflows")
        if isinstance(workflows, list) and len(workflows) >= 3:
            checks["workflows_len_ok"] = True

        # Iterate workflows to validate
        all_platforms_valid = True
        all_actions_len_ok = True
        all_error_handling_ok = True
        all_test_plan_ok = True
        all_monitoring_ok = True
        all_source_tasks_ok = True
        all_roi_saved_ok = True
        all_roi_payback_ok = True
        all_cost_match_ok = True
        all_cost_within_budget_ok = True

        # For prioritization
        recomputed_metrics = []  # list of dicts {name, mhs, payback}

        if isinstance(workflows, list):
            for wf in workflows:
                if not isinstance(wf, dict):
                    all_platforms_valid = False
                    all_actions_len_ok = False
                    all_error_handling_ok = False
                    all_test_plan_ok = False
                    all_monitoring_ok = False
                    all_source_tasks_ok = False
                    all_roi_saved_ok = False
                    all_roi_payback_ok = False
                    all_cost_match_ok = False
                    all_cost_within_budget_ok = False
                    continue

                # platform valid
                platform = None
                tool_choice = wf.get("tool_choice")
                if isinstance(tool_choice, dict):
                    platform = tool_choice.get("platform")
                if platform not in platform_cost:
                    all_platforms_valid = False

                # actions length >= 2
                actions = wf.get("actions")
                if not (isinstance(actions, list) and len(actions) >= 2 and all(isinstance(a, str) and a.strip() for a in actions)):
                    all_actions_len_ok = False

                # error handling includes alert or notify (case-insensitive)
                eh = wf.get("error_handling")
                eh_ok = False
                if isinstance(eh, list) and eh:
                    for item in eh:
                        if isinstance(item, str):
                            s = item.lower()
                            if ("alert" in s) or ("notify" in s):
                                eh_ok = True
                                break
                if not eh_ok:
                    all_error_handling_ok = False

                # test plan includes "edge" or "fail"
                tp = wf.get("test_plan")
                tp_ok = False
                if isinstance(tp, list) and tp:
                    for item in tp:
                        if isinstance(item, str):
                            s = item.lower()
                            if ("edge" in s) or ("fail" in s):
                                tp_ok = True
                                break
                if not tp_ok:
                    all_test_plan_ok = False

                # monitoring plan contains weekly or monthly
                mp = wf.get("monitoring_plan")
                mp_ok = False
                if isinstance(mp, list) and mp:
                    for item in mp:
                        if isinstance(item, str):
                            s = item.lower()
                            if ("weekly" in s) or ("monthly" in s):
                                mp_ok = True
                                break
                if not mp_ok:
                    all_monitoring_ok = False

                # source_tasks validation against input CSV rule-based tasks
                st = wf.get("source_tasks")
                st_ok = True
                if not (isinstance(st, list) and st):
                    st_ok = False
                else:
                    # every entry must be present in tasks.csv and rule_based=yes
                    if not tasks_info["ok"]:
                        st_ok = False
                    else:
                        for t in st:
                            if not isinstance(t, str) or t not in tasks_info["tasks_rule_based"]:
                                st_ok = False
                                break
                if not st_ok:
                    all_source_tasks_ok = False

                # ROI fields
                roi = wf.get("roi", {})
                try:
                    minutes = float(roi.get("minutes_per_occurrence"))
                    freq = float(roi.get("frequency_per_month"))
                    monthly_hours_saved = float(roi.get("monthly_hours_saved"))
                    setup_hours = float(roi.get("setup_hours"))
                    tool_monthly_cost = float(roi.get("tool_monthly_cost"))
                    payback_months = float(roi.get("payback_months"))
                except Exception:
                    all_roi_saved_ok = False
                    all_roi_payback_ok = False
                    all_cost_match_ok = False
                    all_cost_within_budget_ok = False
                    continue

                # monthly_hours_saved recompute
                mhs_expected = (minutes * freq) / 60.0
                if not approx_equal(monthly_hours_saved, mhs_expected):
                    all_roi_saved_ok = False

                # cost match platform
                expected_cost = platform_cost.get(platform, None)
                if expected_cost is None or not approx_equal(tool_monthly_cost, expected_cost):
                    all_cost_match_ok = False

                # cost within budget (per workflow)
                if budget_from_yaml is None:
                    all_cost_within_budget_ok = False
                else:
                    if tool_monthly_cost > float(budget_from_yaml) + 1e-9:
                        all_cost_within_budget_ok = False

                # payback recompute
                if hourly_value_from_yaml is None:
                    all_roi_payback_ok = False
                else:
                    hv = float(hourly_value_from_yaml)
                    denominator = (monthly_hours_saved * hv)
                    # Avoid div by zero: if denominator is zero, the expected payback is infinite; in that case require JSON to be very large?
                    if denominator == 0:
                        # cannot validate; mark as fail
                        all_roi_payback_ok = False
                    else:
                        pb_expected = (setup_hours * hv + tool_monthly_cost) / denominator
                        if not approx_equal(payback_months, pb_expected, rel_tol=1e-6, abs_tol=1e-6):
                            all_roi_payback_ok = False

                # prepare prioritization metrics
                name = wf.get("name")
                if isinstance(name, str) and name.strip():
                    recomputed_metrics.append({
                        "name": name,
                        "mhs": mhs_expected,
                        "payback": ( (setup_hours * (hourly_value_from_yaml if hourly_value_from_yaml is not None else 0.0) + tool_monthly_cost) / (mhs_expected * (hourly_value_from_yaml if hourly_value_from_yaml is not None else 1.0)) ) if (hourly_value_from_yaml not in (None, 0) and mhs_expected != 0) else float("inf")
                    })

            checks["tool_platforms_valid"] = all_platforms_valid
            checks["actions_len_ok"] = all_actions_len_ok
            checks["error_handling_has_alert_notify"] = all_error_handling_ok
            checks["test_plan_has_edge_or_fail"] = all_test_plan_ok
            checks["monitoring_plan_has_cadence"] = all_monitoring_ok
            checks["source_tasks_valid"] = all_source_tasks_ok
            checks["roi_monthly_hours_saved_correct"] = all_roi_saved_ok
            checks["roi_payback_months_correct"] = all_roi_payback_ok
            checks["tool_cost_matches_platform"] = all_cost_match_ok
            checks["tool_cost_within_budget"] = all_cost_within_budget_ok

        # prioritization checks
        prio = workflows_obj.get("prioritization", {})
        if isinstance(prio, dict) and prio.get("method") == "time_saved_then_payback":
            checks["prioritization_method_ok"] = True

        ordered_names = None
        if isinstance(prio, dict):
            ordered_names = prio.get("ordered_workflow_names")
        # Validate ordering and name set
        if isinstance(ordered_names, list) and all(isinstance(x, str) for x in ordered_names) and recomputed_metrics:
            # Validate same set of names
            names_from_wf = [m["name"] for m in recomputed_metrics]
            set_ok = set(ordered_names) == set(names_from_wf)
            # Sort by mhs desc, then payback asc
            sorted_metrics = sorted(recomputed_metrics, key=lambda m: (-m["mhs"], m["payback"]))
            expected_order = [m["name"] for m in sorted_metrics]
            order_ok = ordered_names == expected_order
            checks["prioritization_order_ok"] = bool(set_ok and order_ok)

    # Validate summary.md content
    if checks["has_summary_md"]:
        lines = [ln.rstrip("\n") for ln in summary_txt.splitlines()]
        # Required headings exact lines
        required_headings = [
            "Executive Summary",
            "Selected Automation Candidates",
            "Workflow Specifications",
            "Testing and Monitoring Plan",
            "ROI Summary",
            "Assumptions and Risks",
        ]
        headings_present = {h: False for h in required_headings}
        for ln in lines:
            s = ln.strip()
            if s in headings_present:
                headings_present[s] = True
        checks["summary_has_all_headings"] = all(headings_present.values())

        # At least one bullet under Executive Summary before next heading
        exec_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == "Executive Summary":
                exec_idx = i
                break
        bullet_ok = False
        if exec_idx is not None:
            i = exec_idx + 1
            while i < len(lines):
                s = lines[i].strip()
                if s in required_headings:
                    break
                if s.startswith("- ") or s.startswith("* "):
                    bullet_ok = True
                    break
                i += 1
        checks["summary_exec_has_bullet"] = bullet_ok

    # Compute reward: proportion of passed checks among those that depend on outputs
    # Only count checks that look at output artifacts
    counted_keys = [
        "has_workflows_json",
        "has_summary_md",
        "top_source_ok",
        "top_currency_ok",
        "hourly_value_matches_yaml",
        "workflows_len_ok",
        "tool_platforms_valid",
        "actions_len_ok",
        "error_handling_has_alert_notify",
        "test_plan_has_edge_or_fail",
        "monitoring_plan_has_cadence",
        "source_tasks_valid",
        "roi_monthly_hours_saved_correct",
        "roi_payback_months_correct",
        "tool_cost_matches_platform",
        "tool_cost_within_budget",
        "prioritization_method_ok",
        "prioritization_order_ok",
        "summary_has_all_headings",
        "summary_exec_has_bullet",
    ]
    total = len(counted_keys)
    passed = sum(1 for k in counted_keys if checks.get(k, False))
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure reward is exactly 0.0 if outputs missing or empty
    # If either required file is missing, reward should be 0.0
    if not (checks["has_workflows_json"] and checks["has_summary_md"]):
        reward = 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()