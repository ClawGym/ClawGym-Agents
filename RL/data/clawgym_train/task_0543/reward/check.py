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

def find_entries(content, entry_type_prefix):
    """
    Parse entries with headings like:
    ## [LRN-YYYYMMDD-XXX]
    ## [ERR-YYYYMMDD-XXX]
    ## [FEAT-YYYYMMDD-XXX]
    Returns list of dicts: {id, heading, body, sections, fields}
    sections: map of 'Summary','Details','Suggested Action','Metadata','Error','Context','Suggested Fix'
    fields: map of 'Logged','Priority','Status','Area'
    """
    # Build regex for ID headings
    pattern = re.compile(
        r"^## \[(" + re.escape(entry_type_prefix) + r")-(\d{8})-([A-Za-z0-9]{3})\]\s*$",
        re.MULTILINE,
    )
    entries = []
    for match in pattern.finditer(content):
        start = match.end()
        # Find next heading start or end
        next_match = pattern.search(content, start)
        end = next_match.start() if next_match else len(content)
        entry_text = content[start:end]
        entry_id = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        # Extract fields
        fields = {}
        for field_name in ["Logged", "Priority", "Status", "Area"]:
            m = re.search(rf"\*\*{re.escape(field_name)}\*\*:\s*(.+)", entry_text)
            if m:
                fields[field_name] = m.group(1).strip()
        # Extract sections
        sections = {}
        # Section titles to capture
        titles = [
            "Summary",
            "Details",
            "Suggested Action",
            "Metadata",
            "Error",
            "Context",
            "Suggested Fix",
            "Requested Capability",
            "User Context",
            "Complexity Estimate",
        ]
        # Build positions
        sec_pattern = re.compile(r"^### (.+)\s*$", re.MULTILINE)
        sec_positions = []
        for sec_match in sec_pattern.finditer(entry_text):
            sec_title = sec_match.group(1).strip()
            if sec_title in titles:
                sec_positions.append((sec_title, sec_match.end()))
        # Append sentinel end
        sec_positions_sorted = []
        # Deduplicate titles by keeping first occurrence
        seen_titles = set()
        for t, pos in sec_positions:
            if t not in seen_titles:
                sec_positions_sorted.append((t, pos))
                seen_titles.add(t)
        sec_positions_sorted.sort(key=lambda x: x[1])
        for idx, (title, pos) in enumerate(sec_positions_sorted):
            end_pos = sec_positions_sorted[idx + 1][1] if idx + 1 < len(sec_positions_sorted) else len(entry_text)
            body = entry_text[pos:end_pos].strip()
            sections[title] = body
        entries.append({
            "id": entry_id,
            "heading_start": match.start(),
            "body": entry_text,
            "fields": fields,
            "sections": sections,
        })
    return entries

def has_required_learning_structure(entry):
    fields = entry.get("fields", {})
    sections = entry.get("sections", {})
    required_fields = all(k in fields for k in ["Logged", "Priority", "Status", "Area"])
    required_sections = all(k in sections for k in ["Summary", "Details", "Suggested Action", "Metadata"])
    # Logged must include 'T'
    logged_ok = "Logged" in fields and ("T" in fields["Logged"])
    return required_fields and required_sections and logged_ok

def has_required_error_structure(entry):
    fields = entry.get("fields", {})
    sections = entry.get("sections", {})
    required_fields = all(k in fields for k in ["Logged", "Priority", "Status", "Area"])
    required_sections = all(k in sections for k in ["Summary", "Error", "Context", "Suggested Fix", "Metadata"])
    logged_ok = "Logged" in fields and ("T" in fields["Logged"])
    return required_fields and required_sections and logged_ok

def has_required_feature_structure(entry):
    fields = entry.get("fields", {})
    sections = entry.get("sections", {})
    required_fields = all(k in fields for k in ["Logged", "Priority", "Status", "Area"])
    required_sections = all(k in sections for k in ["Requested Capability", "User Context", "Complexity Estimate", "Suggested Implementation", "Metadata"])
    logged_ok = "Logged" in fields and ("T" in fields["Logged"])
    return required_fields and required_sections and logged_ok

def extract_error_code_block(error_section_text):
    """
    Find the first fenced code block content in the error section.
    Returns the content between the backticks, or None.
    """
    # Find first ```
    start = None
    end = None
    idx = error_section_text.find("```")
    if idx == -1:
        return None
    # Skip optional language spec
    idx2 = error_section_text.find("```", idx + 3)
    if idx2 == -1:
        return None
    # Content between fences
    content = error_section_text[idx + 3:idx2]
    return content.strip()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "out_learnings_dir_exists": False,
        "file_learnings_exists": False,
        "file_errors_exists": False,
        "file_features_exists": False,
        "file_claude_exists": False,
        "learnings_two_structured_entries": False,
        "learnings_has_pattern_key": False,
        "learnings_has_see_also": False,
        "errors_has_entry": False,
        "errors_entry_structured": False,
        "errors_error_block_matches_input": False,
        "errors_metadata_repro_and_related": False,
        "errors_see_also_points_to_learning": False,
        "features_has_entry": False,
        "features_entry_structured": False,
        "features_metadata_has_frequency": False,
        "claude_rule_mentions_pnpm_install": False,
        "learnings_has_promoted_with_claude": False,
        "promoted_entry_mentions_pnpm": False,
    }

    out_learnings_dir = os.path.join(output_dir, ".learnings")
    learnings_path = os.path.join(out_learnings_dir, "LEARNINGS.md")
    errors_path = os.path.join(out_learnings_dir, "ERRORS.md")
    features_path = os.path.join(out_learnings_dir, "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    input_errors_path = os.path.join(input_dir, "errors.txt")

    # Presence checks
    checks["out_learnings_dir_exists"] = os.path.isdir(out_learnings_dir)
    checks["file_learnings_exists"] = os.path.isfile(learnings_path)
    checks["file_errors_exists"] = os.path.isfile(errors_path)
    checks["file_features_exists"] = os.path.isfile(features_path)
    checks["file_claude_exists"] = os.path.isfile(claude_path)

    learnings_text = read_text(learnings_path) if checks["file_learnings_exists"] else None
    errors_text = read_text(errors_path) if checks["file_errors_exists"] else None
    features_text = read_text(features_path) if checks["file_features_exists"] else None
    claude_text = read_text(claude_path) if checks["file_claude_exists"] else None
    input_errors_text = read_text(input_errors_path)

    # LEARNINGS checks
    learning_entries = []
    if learnings_text is not None:
        learning_entries = find_entries(learnings_text, "LRN")
        # At least two entries with required structure
        structured = [e for e in learning_entries if has_required_learning_structure(e)]
        if len(structured) >= 2:
            checks["learnings_two_structured_entries"] = True
        # At least one metadata has Pattern-Key
        pattern_key_found = False
        see_also_found = False
        for e in learning_entries:
            md = e.get("sections", {}).get("Metadata", "")
            if "Pattern-Key:" in md:
                pattern_key_found = True
            # Accept "See Also:" anywhere in metadata
            if re.search(r"See Also:\s*", md):
                see_also_found = True
        checks["learnings_has_pattern_key"] = pattern_key_found
        checks["learnings_has_see_also"] = see_also_found

    # ERRORS checks
    error_entries = []
    if errors_text is not None:
        error_entries = find_entries(errors_text, "ERR")
        if len(error_entries) >= 1:
            checks["errors_has_entry"] = True
            # Use the first error entry for structured checks
            first_err = error_entries[0]
            if has_required_error_structure(first_err):
                checks["errors_entry_structured"] = True
            # Verify error block content
            err_section = first_err.get("sections", {}).get("Error", "")
            code_block_content = extract_error_code_block(err_section) if err_section else None
            if code_block_content is not None and input_errors_text is not None:
                # Compare normalized: input errors must appear as substring within code block
                if input_errors_text.strip() and input_errors_text.strip() in code_block_content:
                    checks["errors_error_block_matches_input"] = True
            # Metadata reproducible and related files with input/errors.txt
            md = first_err.get("sections", {}).get("Metadata", "")
            reproducible_ok = re.search(r"Reproducible:\s*(yes|no|unknown)", md, re.IGNORECASE) is not None
            related_ok = "Related Files:" in md and "input/errors.txt" in md
            checks["errors_metadata_repro_and_related"] = reproducible_ok and related_ok
            # See Also points to a learning ID
            see_also_line = re.search(r"See Also:\s*(.+)", errors_text)
            if see_also_line:
                if re.search(r"LRN-\d{8}-[A-Za-z0-9]{3}", see_also_line.group(1)):
                    checks["errors_see_also_points_to_learning"] = True

    # FEATURE_REQUESTS checks
    feature_entries = []
    if features_text is not None:
        feature_entries = find_entries(features_text, "FEAT")
        if len(feature_entries) >= 1:
            checks["features_has_entry"] = True
            first_feat = feature_entries[0]
            if has_required_feature_structure(first_feat):
                checks["features_entry_structured"] = True
            md = first_feat.get("sections", {}).get("Metadata", "")
            if re.search(r"Frequency:\s*(first_time|recurring|.+)", md):
                checks["features_metadata_has_frequency"] = True

    # Promotion rule checks
    if claude_text is not None:
        text_lower = claude_text.lower()
        if ("pnpm" in text_lower) and ("pnpm install" in text_lower):
            checks["claude_rule_mentions_pnpm_install"] = True

    # Learning promoted with CLAUDE.md
    promoted_entry_id = None
    if learning_entries:
        for e in learning_entries:
            fields = e.get("fields", {})
            if fields.get("Status", "").strip().lower() == "promoted":
                md = e.get("sections", {}).get("Metadata", "")
                if "Promoted: CLAUDE.md" in md:
                    checks["learnings_has_promoted_with_claude"] = True
                    promoted_entry_id = e.get("id")
                    # Check that Summary or Details mention pnpm
                    summary = e.get("sections", {}).get("Summary", "").lower()
                    details = e.get("sections", {}).get("Details", "").lower()
                    if ("pnpm" in summary) or ("pnpm" in details):
                        checks["promoted_entry_mentions_pnpm"] = True
                    break

    # Compute reward
    # Gate: if any required core files are missing, reward must be 0.0 (no-op baseline / missing artifacts)
    required_files_present = all([
        checks["out_learnings_dir_exists"],
        checks["file_learnings_exists"],
        checks["file_errors_exists"],
        checks["file_features_exists"],
        checks["file_claude_exists"],
    ])

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    if not required_files_present:
        reward = 0.0
    else:
        # Deterministic scoring as fraction of passed checks
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()