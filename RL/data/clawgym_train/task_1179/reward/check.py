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

def parse_id_date(config_path):
    content = read_text(config_path)
    if not content:
        return None
    for line in content.splitlines():
        m = re.match(r'^\s*id_date\s*:\s*(\d{8})\s*$', line)
        if m:
            return m.group(1)
    return None

def find_header_id(content, pattern):
    if not content:
        return None
    for line in content.splitlines():
        if re.search(pattern, line):
            # Extract the ID inside [TYPE-YYYYMMDD-XXX]
            m = re.search(r'\[(\w{3}-\d{8}-\d{3})\]', line)
            if m:
                return m.group(1)
    return None

def section_slice(content, heading):
    """
    Returns the content of a section after a given '### Heading' line
    until the next '### ' heading or end of content.
    """
    lines = content.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("### ") and lines[j].strip() != heading:
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()

def contains_fenced_code_with(content, required_substrings):
    """
    Find the first fenced code block (```) in content and check it contains all required substrings.
    """
    if not content:
        return False
    # Find first code block
    start = content.find("```")
    if start == -1:
        return False
    # Find closing ```
    end = content.find("```", start + 3)
    if end == -1:
        return False
    block = content[start + 3:end]
    return all(s in block for s in required_substrings)

def has_bullet_points(section_text):
    if not section_text:
        return False
    for line in section_text.splitlines():
        if re.match(r'^\s*[-*]\s+\S+', line):
            return True
    return False

def line_matches(content, regex):
    return re.search(regex, content or "", re.MULTILINE) is not None

def extract_complexity_value(section_text):
    if not section_text:
        return None
    # Pick the first non-empty word in the section
    for line in section_text.splitlines():
        val = line.strip().lower()
        if val in {"simple", "medium", "complex"}:
            return val
    # Fallback: search inline tokens
    m = re.search(r'\b(simple|medium|complex)\b', section_text.lower())
    if m:
        return m.group(1)
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    features_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    config_path = os.path.join(input_dir, "config.yaml")

    # Determine expected date from config.yaml, fallback to known date from task if missing
    expected_date = parse_id_date(config_path) or "20250115"

    checks = {
        "errors_file_exists": False,
        "learnings_file_exists": False,
        "features_file_exists": False,
        "claude_file_exists": False,
        "errors_header_ok": False,
        "learnings_header_ok": False,
        "features_header_ok": False,
        "errors_fields_sections_ok": False,
        "errors_error_block_ok": False,
        "learnings_fields_sections_ok": False,
        "learnings_promoted_ok": False,
        "learnings_see_also_ok": False,
        "features_fields_sections_ok": False,
        "features_complexity_ok": False,
        "claude_pnpm_rule_ok": False,
    }

    # Existence checks
    if os.path.isfile(errors_path):
        checks["errors_file_exists"] = True
    if os.path.isfile(learnings_path):
        checks["learnings_file_exists"] = True
    if os.path.isfile(features_path):
        checks["features_file_exists"] = True
    if os.path.isfile(claude_path):
        checks["claude_file_exists"] = True

    errors_id = None

    # ERRORS.md validations
    if checks["errors_file_exists"]:
        errors_content = read_text(errors_path) or ""
        # Header regex: ## [ERR-YYYYMMDD-XXX] <short_name>
        err_header_pattern = r'^## \[ERR-' + re.escape(expected_date) + r'-\d{3}\] .+'
        if re.search(err_header_pattern, errors_content, re.MULTILINE):
            checks["errors_header_ok"] = True
            errors_id = find_header_id(errors_content, err_header_pattern)

        # Fields and sections
        fields_ok = True
        # Logged non-empty
        if not line_matches(errors_content, r'^\*\*Logged\*\*:\s*\S+'):
            fields_ok = False
        # Priority high
        if not line_matches(errors_content, r'^\*\*Priority\*\*:\s*high\b'):
            fields_ok = False
        # Status pending
        if not line_matches(errors_content, r'^\*\*Status\*\*:\s*pending\b'):
            fields_ok = False
        # Area infra or config
        if not line_matches(errors_content, r'^\*\*Area\*\*:\s*(infra|config)\b'):
            fields_ok = False
        # Sections present
        if "### Summary" not in errors_content:
            fields_ok = False
        if "### Error" not in errors_content:
            fields_ok = False
        if "### Context" not in errors_content:
            fields_ok = False
        if "### Suggested Fix" not in errors_content:
            fields_ok = False
        if "### Metadata" not in errors_content:
            fields_ok = False

        # Validate code block in Error section contains required substrings
        error_section = section_slice(errors_content, "### Error")
        code_block_ok = contains_fenced_code_with(error_section or "", ["pnpm-lock.yaml", "npm install"])

        # Validate context bullet points
        context_section = section_slice(errors_content, "### Context")
        if not has_bullet_points(context_section or ""):
            fields_ok = False

        checks["errors_fields_sections_ok"] = fields_ok
        checks["errors_error_block_ok"] = code_block_ok

    # LEARNINGS.md validations
    if checks["learnings_file_exists"]:
        learnings_content = read_text(learnings_path) or ""
        # Header regex: ## [LRN-YYYYMMDD-XXX] (best_practice|correction)
        lrn_header_pattern = r'^## \[LRN-' + re.escape(expected_date) + r'-\d{3}\] (best_practice|correction)'
        if re.search(lrn_header_pattern, learnings_content, re.MULTILINE):
            checks["learnings_header_ok"] = True

        # Fields and sections
        lrn_fields_ok = True
        if not line_matches(learnings_content, r'^\*\*Logged\*\*:\s*\S+'):
            lrn_fields_ok = False
        if not line_matches(learnings_content, r'^\*\*Priority\*\*:\s*medium\b'):
            lrn_fields_ok = False
        # Status promoted
        if not line_matches(learnings_content, r'^\*\*Status\*\*:\s*promoted\b'):
            lrn_fields_ok = False
        # Area infra or config
        if not line_matches(learnings_content, r'^\*\*Area\*\*:\s*(infra|config)\b'):
            lrn_fields_ok = False
        # Required sections
        if "### Summary" not in learnings_content:
            lrn_fields_ok = False
        if "### Details" not in learnings_content:
            lrn_fields_ok = False
        if "### Suggested Action" not in learnings_content:
            lrn_fields_ok = False
        if "### Metadata" not in learnings_content:
            lrn_fields_ok = False

        checks["learnings_fields_sections_ok"] = lrn_fields_ok

        # Promoted note presence
        checks["learnings_promoted_ok"] = ("Promoted: CLAUDE.md" in learnings_content)

        # See Also references the errors ID with same date (ideally the exact one from errors)
        see_also_ok = False
        # Attempt to find See Also line and match
        see_also_match = re.search(r'See Also:\s*(ERR-\d{8}-\d{3})', learnings_content)
        if see_also_match:
            ref_id = see_also_match.group(1)
            if ref_id.startswith(f"ERR-{expected_date}-"):
                if errors_id:
                    # If we have an errors_id, require exact match
                    see_also_ok = (ref_id == errors_id)
                else:
                    # If no errors_id parsed, accept matching date format
                    see_also_ok = True
        checks["learnings_see_also_ok"] = see_also_ok

    # FEATURE_REQUESTS.md validations
    if checks["features_file_exists"]:
        features_content = read_text(features_path) or ""
        # Header regex: ## [FEAT-YYYYMMDD-XXX] log_summarization
        feat_header_pattern = r'^## \[FEAT-' + re.escape(expected_date) + r'-\d{3}\] log_summarization'
        if re.search(feat_header_pattern, features_content, re.MULTILINE):
            checks["features_header_ok"] = True

        feat_fields_ok = True
        if not line_matches(features_content, r'^\*\*Logged\*\*:\s*\S+'):
            feat_fields_ok = False
        if not line_matches(features_content, r'^\*\*Priority\*\*:\s*medium\b'):
            feat_fields_ok = False
        if not line_matches(features_content, r'^\*\*Status\*\*:\s*pending\b'):
            feat_fields_ok = False
        if not line_matches(features_content, r'^\*\*Area\*\*:\s*(docs|infra)\b'):
            feat_fields_ok = False
        # Sections present
        if "### Requested Capability" not in features_content:
            feat_fields_ok = False
        if "### User Context" not in features_content:
            feat_fields_ok = False
        if "### Complexity Estimate" not in features_content:
            feat_fields_ok = False
        if "### Suggested Implementation" not in features_content:
            feat_fields_ok = False
        if "### Metadata" not in features_content:
            feat_fields_ok = False
        checks["features_fields_sections_ok"] = feat_fields_ok

        # Validate complexity value in the section
        complexity_section = section_slice(features_content, "### Complexity Estimate")
        comp_val = extract_complexity_value(complexity_section or "")
        checks["features_complexity_ok"] = comp_val in {"simple", "medium", "complex"}

    # CLAUDE.md validations
    if checks["claude_file_exists"]:
        claude_content = read_text(claude_path) or ""
        if ("pnpm" in claude_content) and ("pnpm install" in claude_content):
            checks["claude_pnpm_rule_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0 if required artifacts are missing
    # This is naturally satisfied since all checks default to False.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()