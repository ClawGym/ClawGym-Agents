import json
import os
import sys
import re

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def file_nonempty(path):
    try:
        if not os.path.isfile(path):
            return False
        return os.path.getsize(path) > 0
    except Exception:
        return False

def str_is_nonempty(s):
    return isinstance(s, str) and len(s.strip()) > 0

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def count_week_sprint_lines(text):
    count = 0
    for line in text.splitlines():
        if re.search(r'\b(week|sprint)\b', line, flags=re.IGNORECASE):
            count += 1
    return count

def find_owners_in_text(lines, allowed):
    owners_found = set()
    pattern = re.compile(r'\b(' + '|'.join(re.escape(a) for a in allowed) + r')\b', flags=re.IGNORECASE)
    for line in lines:
        m = pattern.search(line)
        if m:
            owners_found.add(m.group(1).lower())
    return owners_found

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Allowed sets
    allowed_stage = {"pre-PMF", "post-PMF"}
    allowed_functions = {"product", "engineering", "design", "marketing", "finance", "legal", "sales"}
    allowed_traps = {
        "building before retention",
        "hiring before overwhelm",
        "optimizing revenue before PMF",
        "scaling sales before repeatability",
        "spending on brand before distribution",
    }

    # 1) diagnosis.json checks
    diag_path = os.path.join(output_dir, "strategy", "diagnosis.json")
    checks["diagnosis_exists"] = os.path.isfile(diag_path)
    diag_data = None
    if checks["diagnosis_exists"]:
        diag_data, diag_err = load_json_file(diag_path)
        checks["diagnosis_valid_json"] = diag_data is not None and isinstance(diag_data, dict)
    else:
        checks["diagnosis_valid_json"] = False

    # Initialize dependent checks to False
    checks["diagnosis_has_required_keys"] = False
    checks["diagnosis_stage_valid"] = False
    checks["diagnosis_retention_questions_booleans"] = False
    checks["diagnosis_justification_string"] = False
    checks["diagnosis_computed_metrics_numbers"] = False
    checks["diagnosis_priorities_min_items"] = False
    checks["diagnosis_priorities_items_valid"] = False
    checks["diagnosis_decision_routing_min_items"] = False
    checks["diagnosis_decision_routing_items_valid"] = False
    checks["diagnosis_traps_flagged_valid"] = False
    checks["diagnosis_data_sources_contains_metrics"] = False

    if checks["diagnosis_valid_json"]:
        required_keys = [
            "stage",
            "retention_questions",
            "justification",
            "computed_metrics",
            "priorities",
            "decision_routing",
            "traps_flagged",
            "data_sources",
        ]
        has_keys = all(k in diag_data for k in required_keys)
        checks["diagnosis_has_required_keys"] = has_keys

        if has_keys:
            # stage
            stage = diag_data.get("stage")
            checks["diagnosis_stage_valid"] = isinstance(stage, str) and stage in allowed_stage

            # retention_questions
            rq = diag_data.get("retention_questions")
            if isinstance(rq, dict):
                r_keys = ["returning_users", "upset_if_gone", "word_of_mouth"]
                rq_present = all(k in rq for k in r_keys)
                rq_bools = rq_present and all(isinstance(rq.get(k), bool) for k in r_keys)
                checks["diagnosis_retention_questions_booleans"] = bool(rq_bools)
            else:
                checks["diagnosis_retention_questions_booleans"] = False

            # justification
            checks["diagnosis_justification_string"] = str_is_nonempty(diag_data.get("justification"))

            # computed_metrics
            cm = diag_data.get("computed_metrics")
            if isinstance(cm, dict):
                cm_keys = ["waus", "day7_retention", "month1_retention"]
                cm_present = all(k in cm for k in cm_keys)
                cm_nums = cm_present and all(is_number(cm.get(k)) for k in cm_keys)
                checks["diagnosis_computed_metrics_numbers"] = bool(cm_nums)
            else:
                checks["diagnosis_computed_metrics_numbers"] = False

            # priorities
            pr = diag_data.get("priorities")
            if isinstance(pr, list) and len(pr) >= 3:
                checks["diagnosis_priorities_min_items"] = True
                # Validate each item
                items_ok = True
                for item in pr:
                    if not isinstance(item, dict):
                        items_ok = False
                        break
                    title = item.get("title")
                    owner = item.get("owner")
                    time_cost = item.get("time_cost")
                    if not str_is_nonempty(title):
                        items_ok = False
                        break
                    if not isinstance(owner, str) or owner.lower() not in allowed_functions:
                        items_ok = False
                        break
                    if not str_is_nonempty(time_cost):
                        items_ok = False
                        break
                checks["diagnosis_priorities_items_valid"] = items_ok
            else:
                checks["diagnosis_priorities_min_items"] = False
                checks["diagnosis_priorities_items_valid"] = False

            # decision_routing
            dr = diag_data.get("decision_routing")
            if isinstance(dr, dict):
                rev = dr.get("reversible")
                irrev = dr.get("irreversible")
                has_min = isinstance(rev, list) and len(rev) >= 1 and isinstance(irrev, list) and len(irrev) >= 1
                checks["diagnosis_decision_routing_min_items"] = bool(has_min)
                items_ok = True
                if has_min:
                    for arr in (rev, irrev):
                        for item in arr:
                            if not isinstance(item, dict):
                                items_ok = False
                                break
                            title = item.get("title")
                            owner = item.get("owner")
                            if not str_is_nonempty(title):
                                items_ok = False
                                break
                            if not isinstance(owner, str) or owner.lower() not in allowed_functions:
                                items_ok = False
                                break
                        if not items_ok:
                            break
                else:
                    items_ok = False
                checks["diagnosis_decision_routing_items_valid"] = items_ok
            else:
                checks["diagnosis_decision_routing_min_items"] = False
                checks["diagnosis_decision_routing_items_valid"] = False

            # traps_flagged
            traps = diag_data.get("traps_flagged")
            if isinstance(traps, list):
                # Count unique allowed traps present
                match_count = len({t for t in traps if isinstance(t, str) and t in allowed_traps})
                checks["diagnosis_traps_flagged_valid"] = match_count >= 2
            else:
                checks["diagnosis_traps_flagged_valid"] = False

            # data_sources includes at least "input/metrics.csv"
            ds = diag_data.get("data_sources")
            if isinstance(ds, list) and any(isinstance(x, str) and x == "input/metrics.csv" for x in ds):
                checks["diagnosis_data_sources_contains_metrics"] = True
            else:
                checks["diagnosis_data_sources_contains_metrics"] = False

    # 2) 90_day_plan.md checks
    plan90_path = os.path.join(output_dir, "plan", "90_day_plan.md")
    checks["plan90_exists"] = os.path.isfile(plan90_path)
    checks["plan90_non_empty"] = file_nonempty(plan90_path)
    checks["plan90_has_weeks_or_sprints_count_ge6"] = False
    checks["plan90_mentions_founders_time_budget"] = False
    checks["plan90_contains_manual_first_phrase"] = False
    checks["plan90_contains_automate_when_it_hurts"] = False

    plan90_text = ""
    if checks["plan90_non_empty"]:
        try:
            with open(plan90_path, "r", encoding="utf-8") as f:
                plan90_text = f.read()
        except Exception:
            plan90_text = ""
    if plan90_text:
        # Count lines containing "Week" or "Sprint" (case-insensitive)
        count_ws = count_week_sprint_lines(plan90_text)
        checks["plan90_has_weeks_or_sprints_count_ge6"] = count_ws >= 6

        # Founders' time budget mention (accept ASCII or curly apostrophe)
        if re.search(r"founders[’'] time budget", plan90_text, flags=re.IGNORECASE):
            checks["plan90_mentions_founders_time_budget"] = True

        # Exact phrases
        checks["plan90_contains_manual_first_phrase"] = "Manual-first" in plan90_text
        checks["plan90_contains_automate_when_it_hurts"] = "Automate when it hurts" in plan90_text

    # 3) spawn_plan.json checks
    spawn_path = os.path.join(output_dir, "plan", "spawn_plan.json")
    checks["spawn_plan_exists"] = os.path.isfile(spawn_path)
    spawn_data = None
    if checks["spawn_plan_exists"]:
        spawn_data, spawn_err = load_json_file(spawn_path)
        checks["spawn_plan_valid_json"] = spawn_data is not None and isinstance(spawn_data, dict)
    else:
        checks["spawn_plan_valid_json"] = False

    checks["spawn_plan_tasks_min5"] = False
    checks["spawn_plan_tasks_items_valid"] = False
    checks["spawn_plan_functions_coverage_ge4"] = False
    checks["spawn_plan_contains_product_and_marketing"] = False

    if checks["spawn_plan_valid_json"]:
        tasks = spawn_data.get("tasks")
        if isinstance(tasks, list) and len(tasks) >= 5:
            checks["spawn_plan_tasks_min5"] = True
            items_ok = True
            all_funcs = set()
            for t in tasks:
                if not isinstance(t, dict):
                    items_ok = False
                    break
                title = t.get("title")
                funcs = t.get("functions")
                if not str_is_nonempty(title) or not isinstance(funcs, list) or len(funcs) == 0:
                    items_ok = False
                    break
                # Validate functions
                for fn in funcs:
                    if not isinstance(fn, str) or fn.lower() not in allowed_functions:
                        items_ok = False
                        break
                    all_funcs.add(fn.lower())
                if not items_ok:
                    break
            checks["spawn_plan_tasks_items_valid"] = items_ok
            if items_ok:
                checks["spawn_plan_functions_coverage_ge4"] = len(all_funcs) >= 4
                checks["spawn_plan_contains_product_and_marketing"] = ("product" in all_funcs and "marketing" in all_funcs)
        else:
            checks["spawn_plan_tasks_min5"] = False
            checks["spawn_plan_tasks_items_valid"] = False
            checks["spawn_plan_functions_coverage_ge4"] = False
            checks["spawn_plan_contains_product_and_marketing"] = False

    # 4) decision_log.md checks
    dlog_path = os.path.join(output_dir, "decisions", "decision_log.md")
    checks["decisions_exists"] = os.path.isfile(dlog_path)
    checks["decisions_non_empty"] = file_nonempty(dlog_path)
    checks["decisions_contains_reversible_heading"] = False
    checks["decisions_contains_irreversible_heading"] = False
    checks["decisions_at_least_3_bullets"] = False
    checks["decisions_owners_at_least_2"] = False

    dlog_text = ""
    if checks["decisions_non_empty"]:
        try:
            with open(dlog_path, "r", encoding="utf-8") as f:
                dlog_text = f.read()
        except Exception:
            dlog_text = ""
    if dlog_text:
        if re.search(r"reversible decisions", dlog_text, flags=re.IGNORECASE):
            checks["decisions_contains_reversible_heading"] = True
        if re.search(r"irreversible decisions", dlog_text, flags=re.IGNORECASE):
            checks["decisions_contains_irreversible_heading"] = True
        bullet_lines = [ln for ln in dlog_text.splitlines() if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* ")]
        checks["decisions_at_least_3_bullets"] = len(bullet_lines) >= 3
        owners_found = find_owners_in_text(bullet_lines, allowed_functions)
        checks["decisions_owners_at_least_2"] = len(owners_found) >= 2

    # Compute reward as fraction of passed checks
    # Ensure no-op baseline: if output/ is missing or empty, many checks will be False -> reward 0.0
    bool_checks = {k: v for k, v in checks.items() if isinstance(v, bool)}
    total = len(bool_checks)
    passed = sum(1 for v in bool_checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()