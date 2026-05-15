import json
import os
import re
import sys

def read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def contains_all(substrings, text_lower):
    return all(s.lower() in text_lower for s in substrings)

def dependency_policy_present(text_lower: str) -> bool:
    patterns = [
        r"do\s+not\s+install\s+new\s+dependenc",
        r"do\s+not\s+add\s+dependenc",
        r"\bno\s+new\s+dependenc",
        r"\bno\s+new\s+deps\b",
    ]
    for pat in patterns:
        if re.search(pat, text_lower):
            return True
    # Fallback: mentions dependencies + approval requirement
    if "dependenc" in text_lower and ("approval" in text_lower or "approv" in text_lower) and ("without" in text_lower or "require" in text_lower):
        return True
    return False

def hardcoded_secrets_forbidden(text_lower: str) -> bool:
    # Accept variants like "hardcode", "hard-coded", "hardcoded"
    return ("secret" in text_lower) and re.search(r"hard[- ]?cod", text_lower) is not None and ("do not" in text_lower or "must not" in text_lower or "forbid" in text_lower or "prohibit" in text_lower)

def has_numeric_limit(label_regex: str, text: str) -> bool:
    # Require phrase like "max function length: 50 lines" with a number
    return re.search(label_regex, text, flags=re.IGNORECASE) is not None

def extract_section(text: str, start_label: str, end_labels: list) -> str:
    tl = text.lower()
    start_idx = tl.find(start_label.lower())
    if start_idx == -1:
        return ""
    end_idx = len(text)
    for lbl in end_labels:
        pos = tl.find(lbl.lower(), start_idx + 1)
        if pos != -1:
            end_idx = min(end_idx, pos)
    return text[start_idx:end_idx]

def decision_matrix_score(text: str):
    # Look for "Decision Matrix" and a "Score: <digit>" where digit 0-6
    if "decision matrix" not in text.lower():
        return None
    m = re.search(r"score\s*:\s*([0-9]+)", text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        val = int(m.group(1))
        if 0 <= val <= 6:
            return val
    except ValueError:
        return None
    return None

def count_universe_sections(text: str) -> int:
    # Count lines that look like Universe section labels
    # Matches headings like "### Universe X" or a line starting with "Universe"
    pattern = r"(?mi)^\s{0,3}(?:#+\s*)?Universe\b"
    return len(re.findall(pattern, text))

def has_table_with_universe(text: str) -> bool:
    for line in text.splitlines():
        if line.strip().startswith("|") and ("universe" in line.lower()):
            return True
    return False

def pyramid_layers_present(text_lower: str) -> bool:
    # Must include unit, integration, and either e2e or end-to-end
    has_unit = "unit" in text_lower
    has_integration = "integration" in text_lower
    has_e2e = ("e2e" in text_lower) or ("end-to-end" in text_lower)
    return has_unit and has_integration and has_e2e

def mentions_test_first(text_lower: str) -> bool:
    if "test-first" in text_lower:
        return True
    if "write tests before implementation" in text_lower:
        return True
    if "write tests first" in text_lower:
        return True
    return False

def status_markers_present(text_lower: str) -> bool:
    matches = re.findall(r"\b(pass|fail|n/?a)\b", text_lower, flags=re.IGNORECASE)
    return len(matches) >= 2

def implement_mentions_200_line_rule(text: str) -> bool:
    # Try to limit to Implement section when possible
    section = extract_section(text, "implement", ["validate", "research", "plan", "decision"])
    target_text = section if section else text
    return re.search(r"200\s*[- ]?\s*line", target_text, flags=re.IGNORECASE) is not None

def rules_has_sections(text_lower: str) -> bool:
    required = ["stack", "code style", "architecture", "testing", "do not", "when unsure"]
    return contains_all(required, text_lower)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # File paths
    project_rules_path = os.path.join(output_dir, "PROJECT_RULES.md")
    rpiv_plan_path = os.path.join(output_dir, "RPIV_PLAN.md")
    design_decision_path = os.path.join(output_dir, "DESIGN_DECISION.md")
    test_strategy_path = os.path.join(output_dir, "TEST_STRATEGY.md")
    production_checklist_path = os.path.join(output_dir, "PRODUCTION_CHECKLIST.md")

    # 1) PROJECT_RULES.md checks
    checks["present_PROJECT_RULES"] = False
    checks["rules_has_required_sections"] = False
    checks["rules_has_max_function_length"] = False
    checks["rules_has_max_file_length"] = False
    checks["rules_has_dependency_policy"] = False
    checks["rules_forbid_hardcoded_secrets"] = False

    if os.path.isfile(project_rules_path):
        checks["present_PROJECT_RULES"] = True
        pr_text = read_text_file(project_rules_path)
        pr_lower = pr_text.lower()

        if rules_has_sections(pr_lower):
            checks["rules_has_required_sections"] = True

        # Numeric limits
        if has_numeric_limit(r"max\s*function\s*length[^0-9]{0,40}([0-9]+)", pr_text):
            checks["rules_has_max_function_length"] = True
        if has_numeric_limit(r"max\s*file\s*length[^0-9]{0,40}([0-9]+)", pr_text):
            checks["rules_has_max_file_length"] = True

        if dependency_policy_present(pr_lower):
            checks["rules_has_dependency_policy"] = True

        if hardcoded_secrets_forbidden(pr_lower):
            checks["rules_forbid_hardcoded_secrets"] = True

    # 2) RPIV_PLAN.md checks
    checks["present_RPIV_PLAN"] = False
    checks["rpiv_has_decision_matrix_score_0_6"] = False
    checks["rpiv_has_sections_research_plan_implement_validate"] = False
    checks["rpiv_research_references_all_inputs"] = False
    checks["rpiv_implement_mentions_200_line"] = False

    if os.path.isfile(rpiv_plan_path):
        checks["present_RPIV_PLAN"] = True
        rpiv_text = read_text_file(rpiv_plan_path)
        rpiv_lower = rpiv_text.lower()

        # Decision Matrix score 0-6
        score = decision_matrix_score(rpiv_text)
        if score is not None and 0 <= score <= 6:
            checks["rpiv_has_decision_matrix_score_0_6"] = True

        # Has labeled sections
        if all(lbl in rpiv_lower for lbl in ["research", "plan", "implement", "validate"]):
            checks["rpiv_has_sections_research_plan_implement_validate"] = True

        # Research references all five input filenames
        required_files = [
            "project-brief.md",
            "existing-structure.json",
            "ambiguous-decision.md",
            "nonfunctional-requirements.yaml",
            "security-checklist.md",
        ]
        if all(name in rpiv_lower for name in required_files):
            checks["rpiv_research_references_all_inputs"] = True

        # Implement mentions 200-line rule (prefer within Implement section)
        if implement_mentions_200_line_rule(rpiv_text):
            checks["rpiv_implement_mentions_200_line"] = True

    # 3) DESIGN_DECISION.md checks
    checks["present_DESIGN_DECISION"] = False
    checks["design_has_3plus_universe_sections"] = False
    checks["design_has_comparison_matrix"] = False
    checks["design_has_decision_section"] = False
    checks["design_has_implementation_plan_section"] = False

    if os.path.isfile(design_decision_path):
        checks["present_DESIGN_DECISION"] = True
        dd_text = read_text_file(design_decision_path)
        dd_lower = dd_text.lower()

        if count_universe_sections(dd_text) >= 3:
            checks["design_has_3plus_universe_sections"] = True

        if has_table_with_universe(dd_text):
            checks["design_has_comparison_matrix"] = True

        # "## Decision" and "## Implementation plan"
        if re.search(r"(?mi)^\s*##\s*Decision\b", dd_text):
            checks["design_has_decision_section"] = True
        if re.search(r"(?mi)^\s*##\s*Implementation\s+plan\b", dd_text):
            checks["design_has_implementation_plan_section"] = True

    # 4) TEST_STRATEGY.md checks
    checks["present_TEST_STRATEGY"] = False
    checks["test_strategy_references_pyramid_layers"] = False
    checks["test_strategy_has_percentage_targets"] = False
    checks["test_strategy_mentions_test_first"] = False

    if os.path.isfile(test_strategy_path):
        checks["present_TEST_STRATEGY"] = True
        ts_text = read_text_file(test_strategy_path)
        ts_lower = ts_text.lower()

        if pyramid_layers_present(ts_lower):
            checks["test_strategy_references_pyramid_layers"] = True

        if "%" in ts_text:
            checks["test_strategy_has_percentage_targets"] = True

        if mentions_test_first(ts_lower):
            checks["test_strategy_mentions_test_first"] = True

    # 5) PRODUCTION_CHECKLIST.md checks
    checks["present_PRODUCTION_CHECKLIST"] = False
    checks["production_checklist_has_P0_P1_P2_P3"] = False
    checks["production_checklist_has_status_markers"] = False

    if os.path.isfile(production_checklist_path):
        checks["present_PRODUCTION_CHECKLIST"] = True
        pc_text = read_text_file(production_checklist_path)
        pc_lower = pc_text.lower()

        if all(p in pc_text for p in ["P0", "P1", "P2", "P3"]):
            checks["production_checklist_has_P0_P1_P2_P3"] = True

        if status_markers_present(pc_lower):
            checks["production_checklist_has_status_markers"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Output single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()