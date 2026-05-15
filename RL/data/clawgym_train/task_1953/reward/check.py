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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def to_float_maybe(value):
    if is_number(value):
        return float(value)
    if isinstance(value, str):
        # Extract number like 0.10 from "$0.10" or "0.10 USD"
        m = re.search(r"[-+]?\d+(\.\d+)?", value)
        if m:
            try:
                return float(m.group(0))
            except Exception:
                return None
    return None

def tier_from_expected(expected):
    # Tiers: micro (<0.10), small (0.10–0.50), medium (0.50–2.00), large (>2.00)
    if expected is None:
        return None
    try:
        val = float(expected)
    except Exception:
        return None
    if val < 0.10:
        return "micro"
    if 0.10 <= val <= 0.50:
        return "small"
    if 0.50 < val <= 2.00:
        return "medium"
    return "large"

def deep_collect_strings(obj):
    strings = []
    if isinstance(obj, dict):
        for v in obj.values():
            strings.extend(deep_collect_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            strings.extend(deep_collect_strings(v))
    elif isinstance(obj, str):
        strings.append(obj)
    return strings

def contains_approval_requirement(obj):
    # Look for any string that mentions both "approval" and "require"
    strings = deep_collect_strings(obj)
    for s in strings:
        low = s.lower()
        if "approval" in low and "require" in low:
            return True
    return False

def find_proxy_cap(agent):
    # Search for a numeric cap <= 0.10 in safeguards or spawn_parameters under known keys
    keys = {"max_cost", "cost_cap", "cap", "maxCost", "proxy_cap", "cost_limit"}
    for container_key in ("safeguards", "spawn_parameters"):
        container = agent.get(container_key)
        if isinstance(container, dict):
            for k, v in container.items():
                if k in keys or k.lower() in keys:
                    val = to_float_maybe(v)
                    if val is not None and val <= 0.10:
                        return True
    return False

def validate_agent_fields(agent):
    # Required: id (str), pattern (str), role (str), spawn_parameters.label/task/model (str)
    if not isinstance(agent, dict):
        return False
    if not isinstance(agent.get("id"), str):
        return False
    if not isinstance(agent.get("pattern"), str):
        return False
    if not isinstance(agent.get("role"), str):
        return False
    sp = agent.get("spawn_parameters")
    if not isinstance(sp, dict):
        return False
    if not isinstance(sp.get("label"), str):
        return False
    if not isinstance(sp.get("task"), str):
        return False
    if not isinstance(sp.get("model"), str):
        return False
    return True

def cost_estimate_structure_ok(cost_estimate):
    if not isinstance(cost_estimate, dict):
        return False
    total = cost_estimate.get("total")
    per_agent = cost_estimate.get("per_agent")
    if not isinstance(total, dict):
        return False
    if not isinstance(per_agent, dict):
        return False
    for key in ("min", "expected", "max"):
        if not is_number(total.get(key)):
            return False
    if not isinstance(total.get("tier"), str):
        return False
    for aid, est in per_agent.items():
        if not isinstance(est, dict):
            return False
        for key in ("min", "expected", "max"):
            if not is_number(est.get(key)):
                return False
        if not isinstance(est.get("tier"), str):
            return False
    return True

def tiers_correct(cost_estimate):
    # Verify tiers for total and per_agent
    if not isinstance(cost_estimate, dict):
        return False
    total = cost_estimate.get("total", {})
    total_expected = total.get("expected")
    total_tier = total.get("tier")
    if not (is_number(total_expected) and isinstance(total_tier, str)):
        return False
    if tier_from_expected(total_expected) != total_tier:
        return False
    per_agent = cost_estimate.get("per_agent", {})
    if not isinstance(per_agent, dict):
        return False
    for aid, est in per_agent.items():
        if not isinstance(est, dict):
            return False
        exp = est.get("expected")
        t = est.get("tier")
        if not (is_number(exp) and isinstance(t, str)):
            return False
        if tier_from_expected(exp) != t:
            return False
    return True

def get_approval_threshold(plan):
    try:
        constraints = plan.get("constraints", {})
        th = constraints.get("approval_threshold", None)
        if is_number(th):
            return float(th)
        return None
    except Exception:
        return None

def any_expected_over_threshold(cost_estimate, threshold):
    if threshold is None:
        return False
    try:
        per_agent = cost_estimate.get("per_agent", {})
        for est in per_agent.values():
            exp = est.get("expected")
            if is_number(exp) and float(exp) > threshold:
                return True
    except Exception:
        return False
    return False

def format_currency_two_decimals(value):
    try:
        return f"${float(value):.2f}"
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir potentially used if needed
    # Ensure deterministic check only inspects output files and uses input only for reference if needed.
    plan_path = os.path.join(output_dir, "orchestration", "plan.json")
    templates_path = os.path.join(output_dir, "orchestration", "templates.md")
    quality_path = os.path.join(output_dir, "orchestration", "quality_rubric.json")
    peer_path = os.path.join(output_dir, "orchestration", "peer_review.md")

    checks = {
        "has_plan_json": False,
        "plan_json_valid": False,
        "plan_has_required_keys": False,
        "agents_patterns_and_counts": False,
        "agent_fields_valid": False,
        "cost_estimate_structure": False,
        "cost_tiers_correct": False,
        "constraints_has_approval_threshold": False,
        "gating_rule_present_if_needed": False,
        "security_proxy_cap_present": False,
        "has_templates_md": False,
        "templates_sections_present": False,
        "templates_contains_threshold_string": False,
        "has_quality_rubric_json": False,
        "quality_rubric_dimensions_present": False,
        "quality_rubric_fields_valid": False,
        "quality_rubric_overall_condition_present": False,
        "has_peer_review_md": False,
        "peer_review_contains_required_terms": False,
    }

    plan = None
    if os.path.isfile(plan_path):
        checks["has_plan_json"] = True
        plan = read_json(plan_path)
        if isinstance(plan, dict):
            checks["plan_json_valid"] = True
            # Required keys with expected types
            agents = plan.get("agents")
            constraints = plan.get("constraints")
            cost_estimate = plan.get("cost_estimate")
            risk_alignment = plan.get("risk_alignment")
            cost_log = plan.get("cost_log")
            if isinstance(agents, list) and isinstance(constraints, dict) and isinstance(cost_estimate, dict) and isinstance(risk_alignment, dict) and isinstance(cost_log, dict):
                checks["plan_has_required_keys"] = True

                # Agents patterns and counts and fields
                # At least 7 entries
                pattern_counts_ok = False
                fields_ok = True

                if len(agents) >= 7:
                    # Pattern counts
                    sec_count = sum(1 for a in agents if isinstance(a, dict) and a.get("pattern") == "security-proxy")
                    arch_count = sum(1 for a in agents if isinstance(a, dict) and a.get("pattern") == "architect")
                    coder_count = sum(1 for a in agents if isinstance(a, dict) and a.get("pattern") == "coder")
                    reviewer_count = sum(1 for a in agents if isinstance(a, dict) and a.get("pattern") == "reviewer")
                    researchers = [a for a in agents if isinstance(a, dict) and a.get("pattern") == "researcher"]
                    # Check lenses in researcher roles
                    lenses = {"optimist": False, "pessimist": False, "pragmatist": False}
                    for r in researchers:
                        role = r.get("role", "")
                        lrole = role.lower() if isinstance(role, str) else ""
                        for k in list(lenses.keys()):
                            if k in lrole:
                                lenses[k] = True
                    if sec_count >= 1 and len(researchers) >= 3 and arch_count >= 1 and coder_count >= 1 and reviewer_count >= 1 and all(lenses.values()):
                        pattern_counts_ok = True

                # Validate fields for all agents
                if isinstance(agents, list):
                    for a in agents:
                        if not validate_agent_fields(a):
                            fields_ok = False
                            break

                checks["agents_patterns_and_counts"] = pattern_counts_ok
                checks["agent_fields_valid"] = fields_ok

                # Cost estimate checks
                if cost_estimate_structure_ok(cost_estimate):
                    checks["cost_estimate_structure"] = True
                    if tiers_correct(cost_estimate):
                        checks["cost_tiers_correct"] = True

                # Constraints approval threshold
                approval_threshold = get_approval_threshold(plan)
                if is_number(approval_threshold):
                    checks["constraints_has_approval_threshold"] = True

                # Gating rule if any agent expected > approval_threshold
                if checks["constraints_has_approval_threshold"] and checks["cost_estimate_structure"]:
                    need_gate = any_expected_over_threshold(cost_estimate, approval_threshold)
                    if not need_gate:
                        # If no agent exceeds threshold, gating rule check passes vacuously
                        checks["gating_rule_present_if_needed"] = True
                    else:
                        # Search for a string mentioning approval being required in constraints or cost_estimate
                        if contains_approval_requirement(constraints) or contains_approval_requirement(cost_estimate):
                            checks["gating_rule_present_if_needed"] = True

                # Security proxy cap <= 0.10 present in safeguards or spawn_parameters
                sec_cap_ok = False
                for a in agents:
                    if isinstance(a, dict) and a.get("pattern") == "security-proxy":
                        if find_proxy_cap(a):
                            sec_cap_ok = True
                            break
                checks["security_proxy_cap_present"] = sec_cap_ok

    # templates.md checks
    if os.path.isfile(templates_path):
        checks["has_templates_md"] = True
        tcontent = read_text(templates_path)
        if isinstance(tcontent, str):
            low = tcontent.lower()
            # Section cues
            if ("security proxy" in low and
                "researcher specialists" in low and
                "phased implementation" in low and
                "approval gate" in low):
                checks["templates_sections_present"] = True
            # Threshold string appears as $X.YY
            if isinstance(plan, dict) and checks["plan_json_valid"]:
                threshold = get_approval_threshold(plan)
                if threshold is not None:
                    needle = format_currency_two_decimals(threshold)
                    if needle and needle in tcontent:
                        checks["templates_contains_threshold_string"] = True

    # quality_rubric.json checks
    dims_required = ["specificity", "actionability", "evidence", "structure", "completeness", "clarity", "relevance", "efficiency"]
    if os.path.isfile(quality_path):
        checks["has_quality_rubric_json"] = True
        qrubric = read_json(quality_path)
        if isinstance(qrubric, dict):
            # Dimensions present
            dims_present = [k for k in dims_required if k in qrubric]
            if set(dims_present) == set(dims_required):
                checks["quality_rubric_dimensions_present"] = True
                # Validate fields of each dimension
                fields_ok = True
                for k in dims_required:
                    v = qrubric.get(k)
                    if not isinstance(v, dict):
                        fields_ok = False
                        break
                    if not isinstance(v.get("description"), str):
                        fields_ok = False
                        break
                    ss = v.get("scoring_scale")
                    if not (isinstance(ss, str) or isinstance(ss, dict)):
                        fields_ok = False
                        break
                    if not is_number(v.get("minimum_threshold")):
                        fields_ok = False
                        break
                checks["quality_rubric_fields_valid"] = fields_ok
            # overall_pass_condition string
            if isinstance(qrubric.get("overall_pass_condition"), str):
                checks["quality_rubric_overall_condition_present"] = True

    # peer_review.md checks
    if os.path.isfile(peer_path):
        checks["has_peer_review_md"] = True
        pcontent = read_text(peer_path)
        if isinstance(pcontent, str):
            low = pcontent.lower()
            if ("sanitization" in low and "severity" in low and "structured" in low):
                checks["peer_review_contains_required_terms"] = True

    # Compute reward: proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output directory missing or empty of all four required files, reward should be 0.0
    required_files = [plan_path, templates_path, quality_path, peer_path]
    if not any(os.path.isfile(p) for p in required_files):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()