import json
import os
import re
import sys

def get_section_text(text, header_name):
    # Find a markdown header matching header_name (case-insensitive), return text until next header
    lines = text.splitlines()
    start_idx = None
    header_regex = re.compile(r'^\s{0,3}#{1,6}\s*' + re.escape(header_name) + r'\s*$', re.IGNORECASE)
    header_line_regex = re.compile(r'^\s{0,3}#{1,6}\s+')
    for i, ln in enumerate(lines):
        if header_regex.match(ln.strip()):
            start_idx = i + 1  # start after the header line
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if header_line_regex.match(lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()

def extract_bullets(section_text):
    bullets = []
    for ln in section_text.splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            bullets.append(s)
    return bullets

def section_contains_value(section_text, value):
    if section_text is None:
        return False
    return value.lower() in section_text.lower()

def bullet_with_conditions(bullets, required_terms=None, any_of_terms=None, severity_levels=None):
    """
    - required_terms: list of terms that must all appear in the same bullet (case-insensitive)
    - any_of_terms: list where at least one must appear in the same bullet (case-insensitive)
    - severity_levels: list of severity keywords (e.g., ["CRITICAL","MAJOR"]) that must appear
    Returns True if such a bullet exists.
    """
    if bullets is None:
        return False
    req = [t.lower() for t in (required_terms or [])]
    anyt = [t.lower() for t in (any_of_terms or [])]
    sever = [s.lower() for s in (severity_levels or [])]
    for b in bullets:
        lb = b.lower()
        # Check severity
        if sever:
            if not any(s in lb for s in sever):
                continue
        # Check required terms (all)
        if req:
            if not all(t in lb for t in req):
                continue
        # Check any-of terms (at least one)
        if anyt:
            if not any(t in lb for t in anyt):
                continue
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected output path
    rel_output_path = os.path.join("qa-gate", "2026-04-16-upgrade-paywall-prd.md")
    expected_output_path = os.path.join(output_dir, rel_output_path)

    checks = {
        "output_file_exists": False,
        "gate_result_fail": False,
        "artifact_type_ok": False,
        "findings_section_present": False,
        "sensitive_data_critical": False,
        "placeholders_major_or_critical": False,
        "structural_heading_major": False,
        "factual_accuracy_issue": False,
        "completeness_missing_section": False,
        "summary_section_present": False,
    }

    # If file doesn't exist, reward must stay 0.0
    if not os.path.isfile(expected_output_path):
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    checks["output_file_exists"] = True

    try:
        with open(expected_output_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        # If cannot read, treat as missing for positive checks
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Sections
    gate_result_section = get_section_text(content, "Gate Result")
    artifact_type_section = get_section_text(content, "Artifact Type")
    findings_section = get_section_text(content, "Findings")
    summary_section = get_section_text(content, "Summary")

    # Gate Result: must be FAIL in the Gate Result section
    if gate_result_section is not None:
        if re.search(r'\bFAIL\b', gate_result_section, re.IGNORECASE):
            checks["gate_result_fail"] = True

    # Artifact Type: includes PRD or Document
    if artifact_type_section is not None:
        if re.search(r'\b(PRD|Document)\b', artifact_type_section, re.IGNORECASE):
            checks["artifact_type_ok"] = True

    # Findings section presence and bullets
    bullets = None
    if findings_section is not None and findings_section.strip():
        checks["findings_section_present"] = True
        bullets = extract_bullets(findings_section)

    # Sensitive data critical: CRITICAL + (sk_live OR "API key" OR "secret")
    if bullets:
        checks["sensitive_data_critical"] = bullet_with_conditions(
            bullets,
            any_of_terms=["sk_live", "api key", "secret"],
            severity_levels=["CRITICAL"]
        )

    # Placeholders: MAJOR or CRITICAL + (TODO or TBD)
    if bullets:
        checks["placeholders_major_or_critical"] = bullet_with_conditions(
            bullets,
            any_of_terms=["todo", "tbd"],
            severity_levels=["MAJOR", "CRITICAL"]
        )

    # Structural heading hierarchy: MAJOR + ("heading hierarchy" or "skipped level")
    if bullets:
        checks["structural_heading_major"] = bullet_with_conditions(
            bullets,
            any_of_terms=["heading hierarchy", "skipped level"],
            severity_levels=["MAJOR"]
        )

    # Factual accuracy: CRITICAL or MAJOR + "14 months"
    if bullets:
        checks["factual_accuracy_issue"] = bullet_with_conditions(
            bullets,
            required_terms=["14 months"],
            severity_levels=["MAJOR", "CRITICAL"]
        )

    # Completeness missing section: MAJOR + "missing section" + "Security Considerations"
    if bullets:
        checks["completeness_missing_section"] = bullet_with_conditions(
            bullets,
            required_terms=["missing section", "security considerations"],
            severity_levels=["MAJOR"]
        )

    # Summary section present
    if summary_section is not None and summary_section.strip():
        checks["summary_section_present"] = True

    # Compute reward: average of checks that depend on output content.
    # If the file does not exist, reward = 0.0 (handled above).
    # Include all boolean checks in the denominator.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["output_file_exists"] else 0.0

    # Ensure reward bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()