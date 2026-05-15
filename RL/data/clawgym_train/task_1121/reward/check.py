import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def to_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def compute_per_1m_prices(models_data):
    # Accept either a list of models or an object with "data" list
    if isinstance(models_data, dict) and "data" in models_data and isinstance(models_data["data"], list):
        models_list = models_data["data"]
    elif isinstance(models_data, list):
        models_list = models_data
    else:
        # try fallback: dict of id->obj
        if isinstance(models_data, dict):
            models_list = []
            for k, v in models_data.items():
                if isinstance(v, dict):
                    v = dict(v)
                    v.setdefault("id", k)
                    models_list.append(v)
        else:
            models_list = []

    per_1m = {}
    for m in models_list:
        mid = m.get("id")
        pricing = m.get("pricing") if isinstance(m, dict) else None
        completion = None
        if isinstance(pricing, dict):
            completion = to_float(pricing.get("completion"))
        # If completion provided as per-token USD, per-1M = completion * 1e6
        if mid and completion is not None:
            per_1m[mid] = completion * 1_000_000.0
    return per_1m

def extract_tasks(tasks_data):
    # Accept either list or {"tasks": [...]}
    tasks = []
    if isinstance(tasks_data, list):
        tasks = tasks_data
    elif isinstance(tasks_data, dict) and "tasks" in tasks_data and isinstance(tasks_data["tasks"], list):
        tasks = tasks_data["tasks"]
    return tasks

def find_markdown_table_header_has(line, required_terms):
    low = line.lower()
    if "|" not in line:
        return False
    return all(term.lower() in low for term in required_terms)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "parsed_inputs": False,  # informational; not counted toward reward
        "outputs_present_routing_plan": False,
        "outputs_present_config_patch": False,
        "outputs_present_summary": False,
        "outputs_present_ops_plan": False,
        "summary_fields_valid": False,
        "baseline_model_correct": False,
        "totals_within_tolerance": False,
        "savings_percent_within_tolerance_and_positive": False,
        "simple_price_discipline": False,
        "config_patch_structure_valid": False,
        "config_patch_contains_models_fallbacks": False,
        "routing_plan_has_required_sections": False,
        "ops_plan_has_self_healing_rules": False,
    }

    # Load inputs
    models_path = os.path.join(input_dir, "models.json")
    tasks_path = os.path.join(input_dir, "tasks.json")
    models_json, models_ok = load_json(models_path)
    tasks_json, tasks_ok = load_json(tasks_path)

    per_1m_prices = {}
    tasks = []
    if models_ok and tasks_ok:
        per_1m_prices = compute_per_1m_prices(models_json)
        tasks = extract_tasks(tasks_json)
        checks["parsed_inputs"] = True

    # Paths to required outputs
    routing_plan_path = os.path.join(output_dir, "routing_plan.md")
    config_patch_path = os.path.join(output_dir, "config_patch.json")
    summary_path = os.path.join(output_dir, "summary.json")
    ops_plan_path = os.path.join(output_dir, "ops_plan.md")

    # Check existence of required output files
    if os.path.isfile(routing_plan_path):
        checks["outputs_present_routing_plan"] = True
    if os.path.isfile(config_patch_path):
        checks["outputs_present_config_patch"] = True
    if os.path.isfile(summary_path):
        checks["outputs_present_summary"] = True
    if os.path.isfile(ops_plan_path):
        checks["outputs_present_ops_plan"] = True

    # Early preparation for further checks
    summary = None
    assignments = {}
    baseline_model_from_summary = None
    currency_from_summary = None
    baseline_total_from_summary = None
    optimized_total_from_summary = None
    savings_percent_from_summary = None

    if checks["outputs_present_summary"]:
        summary, summary_ok = load_json(summary_path)
        if summary_ok and isinstance(summary, dict):
            # Validate summary fields existence and types
            baseline_model_from_summary = summary.get("baseline_model")
            currency_from_summary = summary.get("currency")
            baseline_total_from_summary = summary.get("baseline_total")
            optimized_total_from_summary = summary.get("optimized_total")
            savings_percent_from_summary = summary.get("savings_percent")
            assignments = summary.get("assignments") if isinstance(summary.get("assignments"), dict) else {}

            fields_ok = (
                isinstance(baseline_model_from_summary, str) and
                isinstance(currency_from_summary, str) and currency_from_summary == "USD" and
                (isinstance(baseline_total_from_summary, (int, float))) and
                (isinstance(optimized_total_from_summary, (int, float))) and
                (isinstance(savings_percent_from_summary, (int, float))) and
                0 <= float(savings_percent_from_summary) <= 100 and
                isinstance(assignments, dict)
            )
            checks["summary_fields_valid"] = fields_ok

            # Baseline model correct exact match
            if isinstance(baseline_model_from_summary, str) and baseline_model_from_summary == "anthropic/claude-3.5-sonnet":
                checks["baseline_model_correct"] = True

    # Compute totals and verify tolerances
    baseline_total_ref = None
    optimized_total_ref = None

    if checks["summary_fields_valid"] and checks["parsed_inputs"]:
        # Need baseline per-1M price from models.json
        baseline_model_id = "anthropic/claude-3.5-sonnet"
        baseline_per_1m_price = per_1m_prices.get(baseline_model_id)

        # Compute baseline total
        if baseline_per_1m_price is not None and isinstance(tasks, list):
            bt = 0.0
            for t in tasks:
                tokens = t.get("estimated_output_tokens", 1000)
                tokens = to_float(tokens, 1000.0)
                if tokens is None:
                    tokens = 1000.0
                bt += (tokens / 1_000_000.0) * baseline_per_1m_price
            baseline_total_ref = bt

        # Compute optimized total using assignments
        if isinstance(tasks, list) and isinstance(assignments, dict):
            ot = 0.0
            valid = True
            for t in tasks:
                tid = t.get("id")
                # Convert task id to string for assignments mapping
                tid_key = str(tid) if tid is not None else None
                model_id = assignments.get(tid_key) if tid_key is not None else None
                if not model_id or model_id not in per_1m_prices:
                    valid = False
                    break
                tokens = t.get("estimated_output_tokens", 1000)
                tokens = to_float(tokens, 1000.0)
                if tokens is None:
                    tokens = 1000.0
                m_per_1m = per_1m_prices.get(model_id)
                if m_per_1m is None:
                    valid = False
                    break
                ot += (tokens / 1_000_000.0) * m_per_1m
            if valid:
                optimized_total_ref = ot

        # Compare tolerances only if we computed both references
        if (baseline_total_ref is not None and optimized_total_ref is not None and
            isinstance(baseline_total_from_summary, (int, float)) and isinstance(optimized_total_from_summary, (int, float))):
            # Relative error within 10%
            def rel_err(a, b):
                denom = abs(a) if abs(a) > 1e-12 else 1.0
                return abs(b - a) / denom

            baseline_ok = rel_err(baseline_total_ref, float(baseline_total_from_summary)) <= 0.10
            optimized_ok = rel_err(optimized_total_ref, float(optimized_total_from_summary)) <= 0.10
            checks["totals_within_tolerance"] = bool(baseline_ok and optimized_ok)

            # Savings percent check within ±5 percentage points and baseline > optimized
            if baseline_total_ref > 0:
                computed_savings = ((baseline_total_ref - optimized_total_ref) / baseline_total_ref) * 100.0
                savings_diff = abs(float(savings_percent_from_summary) - computed_savings)
                checks["savings_percent_within_tolerance_and_positive"] = bool(
                    (baseline_total_ref > optimized_total_ref) and (savings_diff <= 5.0)
                )

    # Simple task price discipline
    if checks["summary_fields_valid"] and checks["parsed_inputs"]:
        simple_ok = True
        if isinstance(tasks, list):
            for t in tasks:
                cat = t.get("category_hint")
                if isinstance(cat, str) and cat.lower().strip() == "simple":
                    tid = t.get("id")
                    tid_key = str(tid) if tid is not None else None
                    model_id = assignments.get(tid_key) if tid_key is not None else None
                    if not model_id or model_id not in per_1m_prices:
                        simple_ok = False
                        break
                    if per_1m_prices[model_id] > 1.25:
                        simple_ok = False
                        break
        else:
            simple_ok = False
        checks["simple_price_discipline"] = bool(simple_ok)

    # Validate config_patch.json structure and content
    config_patch = None
    models_section = None
    fallbacks_section = None
    if checks["outputs_present_config_patch"]:
        config_patch, cfg_ok = load_json(config_patch_path)
        if cfg_ok and isinstance(config_patch, dict):
            try:
                agents = config_patch.get("agents", {})
                defaults = agents.get("defaults", {})
                models_section = defaults.get("models", None)
                model_section = defaults.get("model", {})
                fallbacks_section = model_section.get("fallbacks", None)
                if isinstance(models_section, dict) and isinstance(fallbacks_section, list):
                    checks["config_patch_structure_valid"] = True
            except Exception:
                pass

    if checks["config_patch_structure_valid"] and checks["summary_fields_valid"]:
        assigned_model_ids = set(assignments.values()) if isinstance(assignments, dict) else set()
        required_keys = {f"openrouter/{mid}" for mid in assigned_model_ids if isinstance(mid, str)}
        # Models keys presence
        models_keys_ok = required_keys.issubset(set(models_section.keys())) if isinstance(models_section, dict) else False
        # Fallbacks presence
        fallbacks_set = set()
        if isinstance(fallbacks_section, list):
            for x in fallbacks_section:
                if isinstance(x, str):
                    fallbacks_set.add(x)
        fallbacks_ok = required_keys.issubset(fallbacks_set)
        checks["config_patch_contains_models_fallbacks"] = bool(models_keys_ok and fallbacks_ok)

    # routing_plan.md required sections/strings
    if checks["outputs_present_routing_plan"]:
        try:
            with open(routing_plan_path, "r", encoding="utf-8") as f:
                rp_content = f.read()
            rp_lines = rp_content.splitlines()
            header_ok = any(find_markdown_table_header_has(line, ["Task ID", "Model"]) for line in rp_lines)
            sum_low = rp_content.lower()
            summary_ok = all(s.lower() in sum_low for s in [
                "Baseline", "Total Baseline Cost", "Total Optimized Cost", "Savings"
            ])
            checks["routing_plan_has_required_sections"] = bool(header_ok and summary_ok)
        except Exception:
            pass

    # ops_plan.md self-healing rules
    if checks["outputs_present_ops_plan"]:
        try:
            with open(ops_plan_path, "r", encoding="utf-8") as f:
                op_content = f.read()
            lines = op_content.splitlines()
            has_header = any("self-healing rules" in line.strip().lower() for line in lines)
            bullet_if_then = 0
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("-") or stripped.startswith("*"):
                    low = stripped.lower()
                    if "if" in low and "then" in low:
                        bullet_if_then += 1
                if bullet_if_then >= 2:
                    break
            checks["ops_plan_has_self_healing_rules"] = bool(has_header and bullet_if_then >= 2)
        except Exception:
            pass

    # Compute reward as fraction of passed output-dependent checks
    output_checks = [
        "outputs_present_routing_plan",
        "outputs_present_config_patch",
        "outputs_present_summary",
        "outputs_present_ops_plan",
        "summary_fields_valid",
        "baseline_model_correct",
        "totals_within_tolerance",
        "savings_percent_within_tolerance_and_positive",
        "simple_price_discipline",
        "config_patch_structure_valid",
        "config_patch_contains_models_fallbacks",
        "routing_plan_has_required_sections",
        "ops_plan_has_self_healing_rules",
    ]
    passed = sum(1 for k in output_checks if checks.get(k, False))
    total = len(output_checks)
    reward = (passed / total) if total > 0 else 0.0

    # Enforce no-op baseline: if output/ missing or empty, reward must be 0.0
    # If none of the output presence checks are true, force reward 0.
    if not any(checks[k] for k in ["outputs_present_routing_plan", "outputs_present_config_patch", "outputs_present_summary", "outputs_present_ops_plan"]):
        reward = 0.0

    # Emit JSON result with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()