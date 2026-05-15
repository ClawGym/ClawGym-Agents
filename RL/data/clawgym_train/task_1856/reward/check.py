import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_metrics_blocks(yaml_text):
    # Very lightweight YAML-like parsing to find metric entries with name, threshold, alert
    metrics = {}
    if not yaml_text:
        return metrics
    lines = yaml_text.splitlines()
    current_name = None
    for i, line in enumerate(lines):
        name_match = re.match(r'^\s*-\s*name\s*:\s*([A-Za-z0-9_\-\.]+)\s*$', line)
        if name_match:
            current_name = name_match.group(1)
            metrics[current_name] = {"threshold_numeric": False, "alert_present": False}
            continue
        if current_name is not None:
            thr = re.match(r'^\s*threshold\s*:\s*(-?\d+(?:\.\d+)?)\s*$', line)
            if thr:
                metrics[current_name]["threshold_numeric"] = True
            al = re.match(r'^\s*alert\s*:\s*.+$', line)
            if al:
                metrics[current_name]["alert_present"] = True
            # End block when next item starts (another "- name:" or "- " at same indent) - rely on encountering next "- name:" above
    return metrics

def line_contains_any(text, patterns):
    return all(p in text for p in patterns)

def extract_function_block(src, func_name):
    # Return the text of a function block named func_name
    pattern = re.compile(r'(^def\s+' + re.escape(func_name) + r'\s*\(\s*action\s*\)\s*:\s*)([\s\S]*?)(?=^def\s|\Z)', re.MULTILINE)
    m = pattern.search(src)
    if not m:
        return None
    return m.group(0)

def check_cost_limit_function(src):
    block = extract_function_block(src, "enforce_cost_limit")
    if not block:
        return False
    # Must reference cost or estimate_cost, THRESHOLD, escalation mention, and a False path when cost > THRESHOLD
    has_cost_ref = ("estimate_cost" in block) or re.search(r'\bcost\b', block) is not None
    has_threshold_const = "THRESHOLD" in src
    mentions_escalate = "escalat" in block or "escalat" in src  # allow mention anywhere
    # Look for condition comparing to THRESHOLD and returning False inside
    has_block_condition = re.search(r'>\s*THRESHOLD', block) is not None and re.search(r'return\s+False', block) is not None
    return has_cost_ref and has_threshold_const and mentions_escalate and has_block_condition

def check_read_only_financial_function(src):
    block = extract_function_block(src, "enforce_read_only_financial")
    if not block:
        return False
    has_financial_systems = "FINANCIAL_SYSTEMS" in src or "FINANCIAL_SYSTEMS" in block
    has_get_check = ("GET" in block) or re.search(r'["\']GET["\']', block) is not None
    # Look for a condition indicating non-GET and resource in FINANCIAL_SYSTEMS leading to return False
    has_non_get_deny = (re.search(r'FINANCIAL_SYSTEMS', block) is not None) and (re.search(r'return\s+False', block) is not None) and (re.search(r'!=\s*["\']GET["\']', block) or "method != \"GET\"" in block or "method != 'GET'" in block)
    return has_financial_systems and has_get_check and has_non_get_deny

def json_has_keys(obj, keys):
    return isinstance(obj, dict) and all(k in obj for k in keys)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_monitoring_yaml": False,
        "monitoring_has_required_metrics": False,
        "monitoring_thresholds_numeric_for_required": False,
        "monitoring_alerts_for_required": False,
        "monitoring_has_dashboards": False,

        "has_constraints_py": False,
        "constraints_enforce_cost_limit_valid": False,
        "constraints_enforce_read_only_financial_valid": False,

        "has_escalation_yaml": False,
        "escalation_has_triggers": False,
        "escalation_has_routes": False,
        "escalation_has_ticket_template": False,

        "has_audit_schema_json": False,
        "audit_schema_has_required_fields": False,

        "has_continuous_evaluation_md": False,
        "continuous_eval_has_required_substrings": False,

        "has_model_routing_rules_yaml": False,
        "model_routing_has_tiers": False,
        "model_routing_has_rules_mapping": False,
        "model_routing_has_escalate": False,

        "has_oversight_rationale_md": False,
        "oversight_rationale_mentions_inputs": False,
        "oversight_rationale_has_threshold_and_incident": False,
    }

    # 1) monitoring.yaml
    monitoring_path = os.path.join(output_dir, "monitoring.yaml")
    mon_text = read_text(monitoring_path)
    if mon_text is not None:
        checks["has_monitoring_yaml"] = True
        metrics = parse_metrics_blocks(mon_text)
        required_metric_names = ["decision_quality", "token_usage", "error_rate"]
        if all(name in metrics for name in required_metric_names):
            checks["monitoring_has_required_metrics"] = True
            thr_all = all(metrics[name]["threshold_numeric"] for name in required_metric_names)
            al_all = all(metrics[name]["alert_present"] for name in required_metric_names)
            checks["monitoring_thresholds_numeric_for_required"] = thr_all
            checks["monitoring_alerts_for_required"] = al_all

        # dashboards presence
        dashboards_ok = ("- real_time_agent_health" in mon_text) and ("- decision_audit_trail" in mon_text)
        checks["monitoring_has_dashboards"] = dashboards_ok

    # 2) constraints.py
    constraints_path = os.path.join(output_dir, "constraints.py")
    cons_text = read_text(constraints_path)
    if cons_text is not None:
        checks["has_constraints_py"] = True
        checks["constraints_enforce_cost_limit_valid"] = check_cost_limit_function(cons_text)
        checks["constraints_enforce_read_only_financial_valid"] = check_read_only_financial_function(cons_text)

    # 3) escalation.yaml
    escalation_path = os.path.join(output_dir, "escalation.yaml")
    esc_text = read_text(escalation_path)
    if esc_text is not None:
        checks["has_escalation_yaml"] = True
        # triggers
        trig_required = ["cost_exceeded", "low_confidence", "policy_violation", "anomaly", "human_request"]
        checks["escalation_has_triggers"] = all(t in esc_text for t in trig_required)
        # routes
        has_routes = ("routes:" in esc_text) and ("support_team:" in esc_text) and (("security_team:" in esc_text) or ("on_call_manager:" in esc_text))
        checks["escalation_has_routes"] = has_routes
        # ticket template
        ttpl_ok = ("ticket_template:" in esc_text) and all(f + ":" in esc_text for f in ["id", "created_at", "severity", "summary", "context_refs"])
        checks["escalation_has_ticket_template"] = ttpl_ok

    # 4) audit_schema.json
    audit_path = os.path.join(output_dir, "audit_schema.json")
    aud_text = read_text(audit_path)
    if aud_text is not None:
        try:
            obj = json.loads(aud_text)
            checks["has_audit_schema_json"] = True
            required_keys = ["action", "reasoning", "constraints_checked", "information_considered", "approver", "outcome", "confidence", "alternatives"]
            checks["audit_schema_has_required_fields"] = json_has_keys(obj, required_keys)
        except Exception:
            # remains False
            pass

    # 5) continuous_evaluation.md
    cont_path = os.path.join(output_dir, "continuous_evaluation.md")
    cont_text = read_text(cont_path)
    if cont_text is not None:
        checks["has_continuous_evaluation_md"] = True
        substrings = [
            "task_success_rate",
            "user_satisfaction",
            "constraint_adherence",
            "cost_efficiency",
            "speed",
            "feedback loop",
            "quarterly review",
        ]
        checks["continuous_eval_has_required_substrings"] = all(s in cont_text for s in substrings)

    # 6) model_routing_rules.yaml
    routing_path = os.path.join(output_dir, "model_routing_rules.yaml")
    routing_text = read_text(routing_path)
    if routing_text is not None:
        checks["has_model_routing_rules_yaml"] = True
        checks["model_routing_has_tiers"] = ("flash:" in routing_text) and ("standard:" in routing_text) and ("plus:" in routing_text)
        # rules mapping keywords
        map_flash = ("flash" in routing_text.lower()) and (("Q&A" in routing_text) or ("simple" in routing_text.lower()) or ("1-2 sentence" in routing_text) or ("1–2 sentence" in routing_text))
        map_standard = ("standard" in routing_text.lower()) and (("code" in routing_text.lower()) and ("analysis" in routing_text.lower()) and ("planning" in routing_text.lower()))
        map_plus = ("plus" in routing_text.lower()) and (("architecture" in routing_text.lower()) or ("nuanced" in routing_text.lower())) and ("critical" in routing_text.lower())
        checks["model_routing_has_rules_mapping"] = map_flash and map_standard and map_plus
        checks["model_routing_has_escalate"] = ("escalate" in routing_text.lower())

    # 7) oversight_rationale.md
    rationale_path = os.path.join(output_dir, "oversight_rationale.md")
    r_text = read_text(rationale_path)
    if r_text is not None:
        checks["has_oversight_rationale_md"] = True
        # Must mention all four input paths literally
        paths_required = [
            "input/agent_profile.yaml",
            "input/policies.md",
            "input/incidents.jsonl",
            "input/baseline_metrics.csv",
        ]
        checks["oversight_rationale_mentions_inputs"] = all(p in r_text for p in paths_required)
        # must include word "threshold" and substring "incident"
        checks["oversight_rationale_has_threshold_and_incident"] = ("threshold" in r_text.lower()) and ("incident" in r_text.lower())

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = round(passed / total_checks, 6)

    # No-op baseline: if output dir missing or empty, ensure reward is 0.0
    if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir) if not name.startswith('.')]) == 0):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()