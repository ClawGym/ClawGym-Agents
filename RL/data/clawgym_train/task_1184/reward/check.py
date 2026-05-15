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

def split_entries(text, header_regex):
    entries = []
    matches = list(re.finditer(header_regex, text, flags=re.MULTILINE))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        entries.append(text[start:end])
    return entries

def has_field(block, field_name):
    # Accept either "Field:" or "**Field**:"
    pattern_plain = re.compile(rf"^\s*{re.escape(field_name)}\s*:\s*", flags=re.IGNORECASE | re.MULTILINE)
    pattern_bold = re.compile(rf"^\s*\*\*\s*{re.escape(field_name)}\s*\*\*\s*:\s*", flags=re.IGNORECASE | re.MULTILINE)
    return bool(pattern_plain.search(block) or pattern_bold.search(block))

def has_section(block, section_title):
    return re.search(rf"^\s*###\s+{re.escape(section_title)}\s*$", block, flags=re.IGNORECASE | re.MULTILINE) is not None

def error_block_has_code_after_error(block):
    # Find "### Error" line, then check for a fenced code block following it
    m = re.search(r"^\s*###\s+Error\s*$", block, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return False
    after = block[m.end():]
    fence_start = after.find("```")
    if fence_start == -1:
        return False
    after_fence = after[fence_start + 3:]
    fence_end = after_fence.find("```")
    if fence_end == -1:
        return False
    code_content = after_fence[:fence_end].strip()
    return len(code_content) > 0

def features_has_required_sections(block):
    required = [
        "Requested Capability",
        "User Context",
        "Complexity Estimate",
        "Suggested Implementation",
        "Metadata",
    ]
    return all(has_section(block, t) for t in required)

def learnings_has_required_sections(block):
    required = ["Summary", "Details", "Suggested Action"]
    return all(has_section(block, t) for t in required)

def block_has_required_fields(block):
    return all(has_field(block, f) for f in ["Logged", "Priority", "Status", "Area"])

def any_status_promoted(text):
    # Look for a Status line containing "promoted"
    return re.search(r"^\s*(?:\*\*Status\*\*|Status)\s*:\s*.*promoted.*$", text, flags=re.IGNORECASE | re.MULTILINE) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to check
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    features_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")

    checks = {
        # Existence checks
        "out_learnings_exists": False,
        "out_errors_exists": False,
        "out_feature_requests_exists": False,
        "out_claude_exists": False,
        # LEARNINGS content checks
        "learnings_two_entries_pattern": False,
        "learnings_has_correction_and_other_category": False,
        "learnings_fields_and_sections": False,
        "learnings_promotion_present": False,
        # ERRORS content checks
        "errors_entry_pattern": False,
        "errors_fields_sections_codeblock": False,
        # FEATURES content checks
        "features_entry_pattern": False,
        "features_fields_and_sections": False,
        # CLAUDE content check
        "claude_contains_pnpm_bullet": False,
    }

    # Read files if they exist
    learnings_text = read_text(learnings_path)
    errors_text = read_text(errors_path)
    features_text = read_text(features_path)
    claude_text = read_text(claude_path)

    # Existence
    if learnings_text is not None:
        checks["out_learnings_exists"] = True
    if errors_text is not None:
        checks["out_errors_exists"] = True
    if features_text is not None:
        checks["out_feature_requests_exists"] = True
    if claude_text is not None:
        checks["out_claude_exists"] = True

    # LEARNINGS validations
    if checks["out_learnings_exists"]:
        # Entries header pattern
        lrn_header_regex = r"^## \[LRN-\d{8}-[A-Za-z0-9]{3,}\] .+$"
        lrn_headers = re.findall(lrn_header_regex, learnings_text, flags=re.MULTILINE)
        if len(lrn_headers) >= 2:
            checks["learnings_two_entries_pattern"] = True

        # Category presence in heading lines
        has_correction = any(re.search(r"correction", h, flags=re.IGNORECASE) for h in lrn_headers)
        has_other = any(re.search(r"(best_practice|knowledge_gap)", h, flags=re.IGNORECASE) for h in lrn_headers)
        if has_correction and has_other:
            checks["learnings_has_correction_and_other_category"] = True

        # Fields and sections for at least two entries
        lrn_entries = split_entries(learnings_text, lrn_header_regex)
        valid_entries = 0
        for block in lrn_entries:
            if block_has_required_fields(block) and learnings_has_required_sections(block):
                valid_entries += 1
        if valid_entries >= 2:
            checks["learnings_fields_and_sections"] = True

        # Promotion checks: contains "Promoted: CLAUDE.md" and Status promoted somewhere
        has_promoted_note = "Promoted: CLAUDE.md" in learnings_text
        has_promoted_status = any_status_promoted(learnings_text)
        if has_promoted_note and has_promoted_status:
            checks["learnings_promotion_present"] = True

    # ERRORS validations
    if checks["out_errors_exists"]:
        err_header_regex = r"^## \[ERR-\d{8}-[A-Za-z0-9]{3,}\] .+$"
        err_headers = re.findall(err_header_regex, errors_text, flags=re.MULTILINE)
        if len(err_headers) >= 1:
            checks["errors_entry_pattern"] = True

        err_entries = split_entries(errors_text, err_header_regex)
        has_valid_error = False
        for block in err_entries:
            if not block_has_required_fields(block):
                continue
            if not has_section(block, "Summary"):
                continue
            if not has_section(block, "Error"):
                continue
            if not error_block_has_code_after_error(block):
                continue
            if not has_section(block, "Context"):
                continue
            if not has_section(block, "Suggested Fix"):
                continue
            has_valid_error = True
            break
        if has_valid_error:
            checks["errors_fields_sections_codeblock"] = True

    # FEATURE_REQUESTS validations
    if checks["out_feature_requests_exists"]:
        feat_header_regex = r"^## \[FEAT-\d{8}-[A-Za-z0-9]{3,}\] .+$"
        feat_headers = re.findall(feat_header_regex, features_text, flags=re.MULTILINE)
        if len(feat_headers) >= 1:
            checks["features_entry_pattern"] = True

        feat_entries = split_entries(features_text, feat_header_regex)
        has_valid_feature = False
        for block in feat_entries:
            if not block_has_required_fields(block):
                continue
            if not features_has_required_sections(block):
                continue
            has_valid_feature = True
            break
        if has_valid_feature:
            checks["features_fields_and_sections"] = True

    # CLAUDE content validation
    if checks["out_claude_exists"] and isinstance(claude_text, str):
        if ("Package manager: pnpm (not npm)" in claude_text) and ("pnpm install" in claude_text):
            checks["claude_contains_pnpm_bullet"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or all four required files missing, reward must be 0.0
    # Here, if none of the existence checks are true, force reward to 0.0
    if not any([checks["out_learnings_exists"], checks["out_errors_exists"], checks["out_feature_requests_exists"], checks["out_claude_exists"]]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()