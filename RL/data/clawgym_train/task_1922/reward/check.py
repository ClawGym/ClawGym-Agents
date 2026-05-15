import json
import os
import sys
from typing import Any, Dict, List, Tuple, Union

def read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def rating_for_score(score: float) -> str:
    # Closed intervals per spec
    if 80 <= score <= 100:
        return "Production-grade"
    if 60 <= score <= 79:
        return "Operational"
    if 40 <= score <= 59:
        return "Risky"
    if 0 <= score <= 39:
        return "Blind"
    # Out of bounds, return empty to fail checks
    return ""

def within(v: float, target: float, tol: float) -> bool:
    return abs(v - target) <= tol

def collect_strings(value: Any) -> List[str]:
    """Collect all string-like leaf values from nested lists/dicts for flexible matching."""
    strings = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(collect_strings(item))
    elif isinstance(value, dict):
        for k, v in value.items():
            # include keys and values as strings for broad coverage
            if isinstance(k, str):
                strings.append(k)
            strings.extend(collect_strings(v))
    return strings

def validate_assessment(assessment: Dict[str, Any], checks: Dict[str, bool]) -> None:
    required_top_keys = ["score", "rating", "dimensions", "benchmarks", "industry_adjustments"]
    # presence and types
    top_keys_present = all(k in assessment for k in required_top_keys)
    if not top_keys_present:
        return
    checks["assessment_fields_present"] = True

    # score
    score = assessment.get("score")
    if not is_number(score) or not (0 <= float(score) <= 100):
        return
    score = float(score)

    # dimensions ranges and presence
    dims = assessment.get("dimensions")
    if not isinstance(dims, dict):
        return
    dim_specs = {
        "execution_visibility": 20,
        "cost_attribution": 20,
        "output_quality": 15,
        "failure_recovery": 15,
        "security_boundaries": 15,
        "fleet_coordination": 15,
    }
    dims_present = all(k in dims for k in dim_specs.keys())
    if not dims_present:
        return

    ranges_ok = True
    dim_sum = 0.0
    for k, maxv in dim_specs.items():
        v = dims.get(k)
        if not is_number(v):
            ranges_ok = False
            break
        v = float(v)
        if not (0 <= v <= maxv):
            ranges_ok = False
            break
        dim_sum += v
    if ranges_ok:
        checks["dimension_ranges_valid"] = True
    else:
        return

    # sum equals overall score within ±0.5
    if within(dim_sum, score, 0.5):
        checks["dimension_sum_matches"] = True

    # rating correctness
    rating = assessment.get("rating")
    if isinstance(rating, str):
        expected_rating = rating_for_score(score)
        if expected_rating and rating == expected_rating:
            checks["rating_correct"] = True

    # benchmarks object
    if isinstance(assessment.get("benchmarks"), dict):
        # included in fields_present; no extra scoring beyond dependent on output
        pass
    else:
        # invalidate fields_present if benchmarks wrong
        checks["assessment_fields_present"] = False

    # industry_adjustments array and content check
    ind_adj = assessment.get("industry_adjustments")
    if isinstance(ind_adj, list):
        all_text = " ".join(collect_strings(ind_adj)).lower()
        has_industry = ("ecommerce" in all_text) or ("saas" in all_text)
        has_cost_attr = "cost attribution" in all_text
        has_fleet_coord = "fleet coordination" in all_text
        if has_industry and has_cost_attr and has_fleet_coord:
            checks["industry_adjustments_ok"] = True

def validate_remediation(remediation_text: str, checks: Dict[str, bool]) -> None:
    # Must contain heading "90-Day Monitoring Roadmap"
    if "90-Day Monitoring Roadmap" in remediation_text:
        checks["remediation_has_heading"] = True
    # Must include section labels
    required_sections = ["Week 1-2", "Week 3-4", "Month 2", "Month 3"]
    if all(s in remediation_text for s in required_sections):
        checks["remediation_sections_present"] = True
    # Must contain both phrases
    if ("failure detection <5 min" in remediation_text) and ("cost anomaly" in remediation_text):
        checks["remediation_has_required_phrases"] = True

def validate_cost_savings(cs: Dict[str, Any], checks: Dict[str, bool]) -> None:
    required_keys = [
        "company_size_bracket",
        "unmonitored_waste_usd",
        "monitoring_investment_usd",
        "net_savings_usd",
        "current_spend_usd",
        "estimate_method",
    ]
    if not all(k in cs for k in required_keys):
        return

    # bracket
    if cs.get("company_size_bracket") == "20-100 agents":
        checks["cost_savings_bracket_correct"] = True

    # current spend
    cur_spend = cs.get("current_spend_usd")
    if is_number(cur_spend) and float(cur_spend) >= 0:
        pass
    else:
        return

    # estimate_method contains "2026"
    method = cs.get("estimate_method")
    if isinstance(method, str) and "2026" in method:
        checks["cost_savings_method_2026"] = True

    # ranges
    def valid_range(obj: Any, low: float, high: float) -> Tuple[bool, Union[float, None], Union[float, None]]:
        if not isinstance(obj, dict):
            return (False, None, None)
        mn = obj.get("min")
        mx = obj.get("max")
        if not (is_number(mn) and is_number(mx)):
            return (False, None, None)
        mn = float(mn); mx = float(mx)
        if mn > mx:
            return (False, None, None)
        if not (low <= mn <= high and low <= mx <= high):
            return (False, None, None)
        return (True, mn, mx)

    uw_ok, uw_min, uw_max = valid_range(cs.get("unmonitored_waste_usd"), 45000, 200000)
    inv_ok, inv_min, inv_max = valid_range(cs.get("monitoring_investment_usd"), 8000, 20000)
    ns_ok, ns_min, ns_max = valid_range(cs.get("net_savings_usd"), -1e12, 1e12)  # validate structure first

    if uw_ok and inv_ok and ns_ok:
        checks["cost_savings_ranges_valid"] = True
        # net savings consistency within ±1
        if within(ns_min, uw_min - inv_min, 1.0) and within(ns_max, uw_max - inv_max, 1.0):
            checks["cost_savings_net_savings_consistent"] = True

def validate_compliance(cm: Dict[str, Any], checks: Dict[str, bool]) -> None:
    if not isinstance(cm, dict):
        return
    if not ("frameworks" in cm and "mappings" in cm and "notes" in cm):
        return
    frameworks = cm.get("frameworks")
    mappings = cm.get("mappings")
    notes = cm.get("notes")
    if not (isinstance(frameworks, list) and isinstance(mappings, dict) and isinstance(notes, str)):
        return

    need = {"OWASP Agentic Top 10", "NIST AI RMF"}
    has_needed = need.issubset(set([x for x in frameworks if isinstance(x, str)]))
    if has_needed:
        checks["compliance_frameworks_ok"] = True

    def framework_ok(name: str) -> bool:
        if name not in mappings:
            return False
        entry = mappings[name]
        if not isinstance(entry, dict):
            return False
        coverage = entry.get("coverage")
        status = entry.get("status")
        controls = entry.get("controls")
        if not (is_number(coverage) and 0 <= float(coverage) <= 100):
            return False
        if not isinstance(status, str):
            return False
        if not isinstance(controls, list) or len(controls) == 0:
            return False
        ctrl_ok = False
        for c in controls:
            if isinstance(c, dict) and "id" in c and "status" in c and isinstance(c["id"], str) and isinstance(c["status"], str):
                ctrl_ok = True
                break
        return ctrl_ok

    if has_needed and all(framework_ok(n) for n in need):
        checks["compliance_mappings_ok"] = True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # assessment.json
        "assessment_exists": False,
        "assessment_json_valid": False,
        "assessment_fields_present": False,
        "dimension_ranges_valid": False,
        "dimension_sum_matches": False,
        "rating_correct": False,
        "industry_adjustments_ok": False,
        # remediation.md
        "remediation_exists": False,
        "remediation_has_heading": False,
        "remediation_sections_present": False,
        "remediation_has_required_phrases": False,
        # cost_savings.json
        "cost_savings_exists": False,
        "cost_savings_json_valid": False,
        "cost_savings_bracket_correct": False,
        "cost_savings_ranges_valid": False,
        "cost_savings_net_savings_consistent": False,
        "cost_savings_method_2026": False,
        # compliance_mapping.json
        "compliance_exists": False,
        "compliance_json_valid": False,
        "compliance_frameworks_ok": False,
        "compliance_mappings_ok": False,
    }

    # assessment.json
    assessment_path = os.path.join(output_dir, "assessment.json")
    if os.path.isfile(assessment_path):
        checks["assessment_exists"] = True
        assessment, err = read_json_file(assessment_path)
        if isinstance(assessment, dict):
            checks["assessment_json_valid"] = True
            validate_assessment(assessment, checks)

    # remediation.md
    remediation_path = os.path.join(output_dir, "remediation.md")
    if os.path.isfile(remediation_path):
        # Non-empty check
        content, err = read_text_file(remediation_path)
        if content is not None and len(content.strip()) > 0:
            checks["remediation_exists"] = True
            validate_remediation(content, checks)

    # cost_savings.json
    cs_path = os.path.join(output_dir, "cost_savings.json")
    if os.path.isfile(cs_path):
        checks["cost_savings_exists"] = True
        cs, err = read_json_file(cs_path)
        if isinstance(cs, dict):
            checks["cost_savings_json_valid"] = True
            validate_cost_savings(cs, checks)

    # compliance_mapping.json
    cm_path = os.path.join(output_dir, "compliance_mapping.json")
    if os.path.isfile(cm_path):
        checks["compliance_exists"] = True
        cm, err = read_json_file(cm_path)
        if isinstance(cm, dict):
            checks["compliance_json_valid"] = True
            validate_compliance(cm, checks)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure reward bounded [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()