import json
import os
import sys
from typing import Any, Dict, List, Set, Tuple

def load_yaml_like(path: str) -> Tuple[bool, Any]:
    """
    Try to parse a YAML file. Falls back to JSON (valid YAML subset) if PyYAML is unavailable.
    Returns (success, data_or_error).
    """
    try:
        import yaml  # type: ignore
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return True, data
        except Exception as e:
            return False, f"YAML parse error: {e}"
    except Exception:
        # Fallback to JSON (YAML is a superset of JSON)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return True, data
        except Exception as e:
            return False, f"JSON fallback parse error: {e}"

def read_text(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception as e:
        return False, str(e)

def is_int_in_range(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and low <= value <= high

def extract_frameworks_from_comp_yaml(data: Any) -> Set[str]:
    """
    Extract compliance frameworks (strings) from known keys in compliance.yaml.
    Looks for lists under keys: frameworks, standards, compliance, compliance_requirements, requirements.
    """
    targets = {"frameworks", "standards", "compliance", "compliance_requirements", "requirements"}
    found: Set[str] = set()

    def walk(obj: Any, parent_key: str = ""):
        nonlocal found
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_lower = str(k).strip().lower()
                if key_lower in targets:
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                s = item.strip()
                                if s:
                                    found.add(s)
                            # Also handle list of dicts with 'name' field
                            elif isinstance(item, dict):
                                name = item.get("name")
                                if isinstance(name, str) and name.strip():
                                    found.add(name.strip())
                    elif isinstance(v, dict):
                        # Sometimes nested under e.g., requirements: { frameworks: [...] }
                        walk(v, key_lower)
                else:
                    walk(v, key_lower)
        elif isinstance(obj, list):
            for it in obj:
                walk(it, parent_key)

    walk(data)
    return found

def get_assessment_sections(assessment_obj: Any) -> Dict[str, Any]:
    """
    Helper to safely access nested sections with flexibility for third_parties location.
    Returns a dict of key parts for checking.
    """
    result = {
        "name": None,
        "date": None,
        "assessor": None,
        "scope": None,
        "applications": None,
        "infrastructure": None,
        "third_parties": None,  # try in scope then at assessment level
        "compliance_requirements": None,
        "previous_incidents": None,
        "risk_tolerance": None,
    }
    if not isinstance(assessment_obj, dict):
        return result
    result["name"] = assessment_obj.get("name")
    result["date"] = assessment_obj.get("date")
    result["assessor"] = assessment_obj.get("assessor")
    scope = assessment_obj.get("scope")
    result["scope"] = scope
    if isinstance(scope, dict):
        result["applications"] = scope.get("applications")
        result["infrastructure"] = scope.get("infrastructure")
        # Preferred location in template: under scope
        tp = scope.get("third_parties")
        result["third_parties"] = tp
    # Accept third_parties at top-level under assessment as well
    if result["third_parties"] is None:
        result["third_parties"] = assessment_obj.get("third_parties")

    result["compliance_requirements"] = assessment_obj.get("compliance_requirements")
    result["previous_incidents"] = assessment_obj.get("previous_incidents")
    result["risk_tolerance"] = assessment_obj.get("risk_tolerance")
    return result

def compute_weighted_total(dimensions: Dict[str, Dict[str, Any]]) -> Tuple[bool, float, str]:
    try:
        total = 0.0
        weight_sum = 0
        for k, v in dimensions.items():
            score = v.get("score")
            weight = v.get("weight")
            if not (isinstance(score, (int, float)) and isinstance(weight, int)):
                return False, 0.0, f"Invalid score/weight types for {k}"
            weight_sum += weight
            total += float(score) * float(weight)
        if weight_sum != 100:
            return False, 0.0, "Weights do not sum to 100"
        # Validator uses S = sum(score_i * weight_i) / 10
        return True, total / 10.0, ""
    except Exception as e:
        return False, 0.0, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # assessment.yaml checks
        "assessment_exists": False,
        "assessment_parsed": False,
        "assessment_required_keys": False,
        "assessment_compliance_includes_all": False,
        # threats.yaml checks
        "threats_exists": False,
        "threats_parsed": False,
        "threats_min_items": False,
        "threats_all_fields_present": False,
        "threats_risk_score_correct": False,
        "threats_priorities_have_p0": False,
        "threats_priorities_have_p1": False,
        "threats_all_stride_categories_present": False,
        # security_headers.md checks
        "headers_exists": False,
        "headers_all_required_present": False,
        # security_program.md checks
        "program_exists": False,
        "program_has_incident_response": False,
        "program_has_vuln_management": False,
        "program_has_sev1": False,
        "program_has_cvss": False,
        # ADRs checks
        "adrs_token_exists": False,
        "adrs_token_sections": False,
        "adrs_edge_exists": False,
        "adrs_edge_sections": False,
        # score.json checks
        "score_exists": False,
        "score_parsed": False,
        "score_dimensions_present": False,
        "score_weights_sum_100": False,
        "score_total_consistent": False,
        # readme checks
        "readme_exists": False,
        "readme_has_owasp_top10": False,
        "readme_has_top3": False,
    }

    # 1) assessment.yaml
    assessment_path = os.path.join(output_dir, "assessment.yaml")
    if os.path.isfile(assessment_path):
        checks["assessment_exists"] = True
        ok, assessment_data = load_yaml_like(assessment_path)
        if ok and isinstance(assessment_data, dict):
            checks["assessment_parsed"] = True
            # Find 'assessment' key
            assessment_section = assessment_data.get("assessment")
            if isinstance(assessment_section, dict):
                parts = get_assessment_sections(assessment_section)
                # Required presence
                required_ok = True
                required_ok = required_ok and isinstance(parts["name"], (str,))
                required_ok = required_ok and isinstance(parts["date"], (str,))
                required_ok = required_ok and isinstance(parts["assessor"], (str,))
                required_ok = required_ok and isinstance(parts["scope"], dict)
                required_ok = required_ok and isinstance(parts["applications"], list)
                required_ok = required_ok and isinstance(parts["infrastructure"], list)
                tp_ok = isinstance(parts["third_parties"], list)
                required_ok = required_ok and tp_ok
                required_ok = required_ok and isinstance(parts["compliance_requirements"], list)
                required_ok = required_ok and isinstance(parts["previous_incidents"], list)
                required_ok = required_ok and (isinstance(parts["risk_tolerance"], str) or isinstance(parts["risk_tolerance"], bool))
                checks["assessment_required_keys"] = required_ok

                # Load input compliance.yaml to verify frameworks coverage
                compliance_input_path = os.path.join(input_dir, "compliance.yaml")
                frameworks_required: Set[str] = set()
                if os.path.isfile(compliance_input_path):
                    okc, comp_data = load_yaml_like(compliance_input_path)
                    if okc:
                        frameworks_required = extract_frameworks_from_comp_yaml(comp_data)
                # Validate inclusion
                if isinstance(parts["compliance_requirements"], list):
                    out_frameworks = set([str(x).strip() for x in parts["compliance_requirements"] if isinstance(x, (str, int, float))])
                    # acceptance if all from input are contained (or none in input)
                    if frameworks_required.issubset(out_frameworks):
                        checks["assessment_compliance_includes_all"] = True

    # 2) threats.yaml
    threats_path = os.path.join(output_dir, "threats.yaml")
    if os.path.isfile(threats_path):
        checks["threats_exists"] = True
        ok, threats_data = load_yaml_like(threats_path)
        if ok and isinstance(threats_data, dict):
            checks["threats_parsed"] = True
            threats_list = threats_data.get("threats")
            if isinstance(threats_list, list):
                if len(threats_list) >= 10:
                    checks["threats_min_items"] = True
                # Per-item checks
                required_fields = {
                    "id",
                    "component",
                    "category",
                    "description",
                    "attacker_profile",
                    "likelihood",
                    "impact",
                    "risk_score",
                    "existing_controls",
                    "residual_risk",
                    "mitigation",
                    "priority",
                    "owner",
                    "status",
                }
                all_fields_ok = True
                risk_score_ok = True
                has_p0 = False
                has_p1 = False
                categories_seen: Set[str] = set()
                for item in threats_list:
                    if not isinstance(item, dict):
                        all_fields_ok = False
                        risk_score_ok = False
                        continue
                    # fields present
                    if not required_fields.issubset(item.keys()):
                        all_fields_ok = False
                    # risk math
                    likelihood = item.get("likelihood")
                    impact = item.get("impact")
                    risk_score = item.get("risk_score")
                    if not (is_int_in_range(likelihood, 1, 5) and is_int_in_range(impact, 1, 5) and isinstance(risk_score, int)):
                        risk_score_ok = False
                    else:
                        if risk_score != likelihood * impact:
                            risk_score_ok = False
                    # priority presence
                    pr = str(item.get("priority"))
                    if pr == "P0":
                        has_p0 = True
                    if pr == "P1":
                        has_p1 = True
                    # categories union
                    cat = str(item.get("category")).strip().upper()
                    if cat in {"S", "T", "R", "I", "D", "E"}:
                        categories_seen.add(cat)
                if isinstance(threats_list, list):
                    checks["threats_all_fields_present"] = all_fields_ok
                    checks["threats_risk_score_correct"] = risk_score_ok
                    checks["threats_priorities_have_p0"] = has_p0
                    checks["threats_priorities_have_p1"] = has_p1
                    checks["threats_all_stride_categories_present"] = categories_seen.issuperset({"S", "T", "R", "I", "D", "E"})

    # 3) security_headers.md
    headers_path = os.path.join(output_dir, "security_headers.md")
    if os.path.isfile(headers_path):
        checks["headers_exists"] = True
        ok, content = read_text(headers_path)
        if ok:
            required_headers = [
                "Strict-Transport-Security",
                "Content-Security-Policy",
                "X-Content-Type-Options",
                "X-Frame-Options",
                "Referrer-Policy",
                "Permissions-Policy",
                "Cross-Origin-Opener-Policy",
                "Cross-Origin-Resource-Policy",
                "X-XSS-Protection",
            ]
            all_present = all(h in content for h in required_headers)
            checks["headers_all_required_present"] = all_present

    # 4) security_program.md
    program_path = os.path.join(output_dir, "security_program.md")
    if os.path.isfile(program_path):
        checks["program_exists"] = True
        ok, content = read_text(program_path)
        if ok:
            if "Incident Response" in content:
                checks["program_has_incident_response"] = True
            if "Vulnerability Management" in content:
                checks["program_has_vuln_management"] = True
            if "SEV-1" in content:
                checks["program_has_sev1"] = True
            if "CVSS" in content:
                checks["program_has_cvss"] = True

    # 5) ADRs
    adrs_token_path = os.path.join(output_dir, "adrs", "0001-security-token-lifecycle.md")
    if os.path.isfile(adrs_token_path):
        checks["adrs_token_exists"] = True
        ok, content = read_text(adrs_token_path)
        if ok:
            needed = ["Status", "Context", "Decision", "Consequences", "Alternatives"]
            checks["adrs_token_sections"] = all(s in content for s in needed)

    adrs_edge_path = os.path.join(output_dir, "adrs", "0002-edge-protection-and-tls.md")
    if os.path.isfile(adrs_edge_path):
        checks["adrs_edge_exists"] = True
        ok, content = read_text(adrs_edge_path)
        if ok:
            needed = ["Status", "Context", "Decision", "Consequences", "Alternatives"]
            checks["adrs_edge_sections"] = all(s in content for s in needed)

    # 6) score.json
    score_path = os.path.join(output_dir, "score.json")
    if os.path.isfile(score_path):
        checks["score_exists"] = True
        try:
            with open(score_path, "r", encoding="utf-8") as f:
                score_data = json.load(f)
            checks["score_parsed"] = True
            # Dimensions presence
            dims_required = [
                "authentication_access",
                "data_protection",
                "vulnerability_management",
                "infrastructure_security",
                "logging_monitoring",
                "incident_response",
                "code_security",
                "supply_chain",
            ]
            dims_ok = all(k in score_data for k in dims_required)
            checks["score_dimensions_present"] = dims_ok
            weights_ok = False
            total_consistent = False
            if dims_ok:
                subset = {k: score_data.get(k) for k in dims_required}
                # type check
                if all(isinstance(v, dict) for v in subset.values()):
                    weight_ok, computed_total, _ = compute_weighted_total(subset)  # also checks weights sum to 100
                    checks["score_weights_sum_100"] = weight_ok
                    weights_ok = weight_ok
                    if isinstance(score_data.get("total_score"), (int, float)) and weights_ok:
                        given_total = float(score_data["total_score"])
                        # within ±2 points
                        if abs(given_total - computed_total) <= 2.0:
                            total_consistent = True
                    checks["score_total_consistent"] = total_consistent
        except Exception:
            checks["score_parsed"] = False

    # 7) README.md
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        ok, content = read_text(readme_path)
        if ok:
            if "OWASP Top 10" in content:
                checks["readme_has_owasp_top10"] = True
            if "Top 3" in content:
                checks["readme_has_top3"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline is 0.0 (if nothing exists, passed_checks will be 0)
    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()