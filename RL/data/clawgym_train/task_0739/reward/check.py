import json
import os
import re
import sys
from typing import List, Tuple, Dict

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def list_all_files(root: str) -> List[str]:
    files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            files.append(os.path.join(dirpath, fn))
    return files

def split_entries(md: str, entry_type: str) -> List[Tuple[str, str, str]]:
    """
    Return list of (id, category_or_name, content_block), where category_or_name
    is the second part of the heading line after the ID.
    entry_type in {"LRN","ERR","FEAT"}.
    """
    if entry_type not in {"LRN","ERR","FEAT"}:
        return []
    pattern = rf"^## \[({entry_type}-\d{{8}}-[A-Z0-9]{{3}})\]\s+([^\n]+)"
    matches = list(re.finditer(pattern, md, flags=re.M))
    entries = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(md)
        block = md[start:end]
        entries.append((m.group(1), m.group(2).strip(), block))
    return entries

def has_iso8601_z(text: str) -> bool:
    return re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text) is not None

def lrn_entry_has_required_sections(block: str) -> bool:
    # Required fields: Logged, Priority, Status, Area
    # Sections: Summary, Details, Suggested Action
    # "### Metadata" with at least Source
    fields_ok = all(k in block for k in ["Logged", "Priority", "Status", "Area"])
    ts_ok = has_iso8601_z(block)
    sections_ok = all(h in block for h in ["### Summary", "### Details", "### Suggested Action"])
    metadata_ok = "### Metadata" in block and re.search(r"(?im)^\s*-\s*Source:", block) is not None
    return fields_ok and ts_ok and sections_ok and metadata_ok

def err_entry_has_required_sections(block: str) -> bool:
    # Sections: Summary, Error (fenced), Context, Suggested Fix, Metadata
    sections_ok = all(h in block for h in ["### Summary", "### Error", "### Context", "### Suggested Fix", "### Metadata"])
    fenced_code = "```" in block
    fields_ok = all(k in block for k in ["Logged", "Priority", "Status", "Area"])
    ts_ok = has_iso8601_z(block)
    return sections_ok and fenced_code and fields_ok and ts_ok

def feat_entry_has_required_sections(block: str) -> bool:
    # Sections: Requested Capability, User Context, Complexity Estimate, Suggested Implementation, Metadata
    sections_ok = all(h in block for h in ["### Requested Capability", "### User Context", "### Complexity Estimate", "### Suggested Implementation", "### Metadata"])
    fields_ok = all(k in block for k in ["Logged", "Priority", "Status", "Area"])
    ts_ok = has_iso8601_z(block)
    # Must include Frequency in Metadata
    freq_ok = "Frequency:" in block
    return sections_ok and fields_ok and ts_ok and freq_ok

def extract_secret_candidates(text: str) -> List[str]:
    candidates = set()
    # Specific patterns for api key/token/secret assignments
    for m in re.finditer(r"(?i)(api[_\-]?key|token|secret)\s*[:=]\s*([A-Za-z0-9_\-]{8,})", text):
        candidates.add(m.group(2))
    # URL query like ...api_key=XXXX or token=XXXX
    for m in re.finditer(r"(?i)(api[_\-]?key|token|secret)=([A-Za-z0-9_\-]{8,})", text):
        candidates.add(m.group(2))
    # Generic long tokens (avoid purely numeric)
    for m in re.finditer(r"\b([A-Za-z0-9_\-]{20,})\b", text):
        token = m.group(1)
        if not token.isdigit():
            candidates.add(token)
    # Sort by length desc to put the most secret-looking first
    return sorted(candidates, key=len, reverse=True)

def count_headings(md: str, entry_type: str) -> int:
    return len(split_entries(md, entry_type))

def ids_from_entries(entries: List[Tuple[str, str, str]]) -> List[str]:
    return [e[0] for e in entries]

def id_regex_match(s: str) -> bool:
    return re.fullmatch(r"(LRN|ERR|FEAT)-\d{8}-[A-Z0-9]{3}", s or "") is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    # Initialize checks dict with all False
    checks: Dict[str, bool] = {
        "learnings_file_exists": False,
        "learnings_min_three": False,
        "learnings_well_formed_three": False,
        "learnings_has_best_practice": False,
        "learnings_has_correction_or_kg": False,
        "learnings_promoted_soul_redact": False,
        "learnings_recurring_pattern_updated": False,
        "errors_file_exists": False,
        "errors_exactly_one": False,
        "errors_sections_and_fence": False,
        "errors_contains_redacted": False,
        "errors_no_secret_leak": False,
        "feature_file_exists": False,
        "feature_exactly_one": False,
        "feature_sections_and_frequency": False,
        "feature_contains_redact": False,
        "soul_file_exists": False,
        "soul_rule_valid": False,
        "logging_summary_exists": False,
        "logging_summary_valid_json": False,
        "logging_summary_counts_match": False,
        "logging_summary_ids_cover_outputs": False,
        "no_extra_output_files": False,
    }

    # Paths
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feat_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    soul_path = os.path.join(output_dir, "SOUL.md")
    summary_path = os.path.join(output_dir, "logging_summary.json")
    error_input_path = os.path.join(input_dir, "error_log.txt")

    # Check existence of files
    learnings_md = ""
    if os.path.isfile(learnings_path):
        checks["learnings_file_exists"] = True
        learnings_md = read_text(learnings_path)

    errors_md = ""
    if os.path.isfile(errors_path):
        checks["errors_file_exists"] = True
        errors_md = read_text(errors_path)

    feat_md = ""
    if os.path.isfile(feat_path):
        checks["feature_file_exists"] = True
        feat_md = read_text(feat_path)

    soul_md = ""
    if os.path.isfile(soul_path):
        checks["soul_file_exists"] = True
        soul_md = read_text(soul_path)

    # Parse LEARNINGS.md
    lrn_entries = []
    if checks["learnings_file_exists"]:
        lrn_entries = split_entries(learnings_md, "LRN")
        if len(lrn_entries) >= 3:
            checks["learnings_min_three"] = True

        # Count how many entries appear well-formed according to required sections/fields
        well_formed_count = sum(1 for _, _, block in lrn_entries if lrn_entry_has_required_sections(block))
        if well_formed_count >= 3:
            checks["learnings_well_formed_three"] = True

        # At least one best_practice
        if any(category.strip().lower() == "best_practice" for _, category, _ in lrn_entries):
            checks["learnings_has_best_practice"] = True

        # At least one correction or knowledge_gap
        if any(category.strip().lower() in {"correction", "knowledge_gap"} for _, category, _ in lrn_entries):
            checks["learnings_has_correction_or_kg"] = True

        # Promoted entry check: Status: promoted + "Promoted: SOUL.md" + contains "redact"
        promoted_ok = False
        for _, _, block in lrn_entries:
            status_promoted = re.search(r"(?im)^\s*\*\*Status\*\*:\s*promoted\b", block) or re.search(r"(?im)\bStatus:\s*promoted\b", block)
            promoted_line = re.search(r"(?i)Promoted:\s*SOUL\.md", block)
            redact_word = re.search(r"(?i)\bredact\b", block)
            if status_promoted and promoted_line and redact_word:
                promoted_ok = True
                break
        if promoted_ok:
            checks["learnings_promoted_soul_redact"] = True

        # Recurring pattern updated check
        # We need an entry containing:
        # - Pattern-Key: harden.input_validation
        # - Recurrence-Count: >= 3
        # - See Also: LRN-20260101-001
        recurring_ok = False
        for _, _, block in lrn_entries:
            if "Pattern-Key: harden.input_validation" in block:
                rec_m = re.search(r"(?i)Recurrence-Count:\s*(\d+)", block)
                see_also = re.search(r"(?i)See Also:\s*LRN-20260101-001", block)
                if rec_m and int(rec_m.group(1)) >= 3 and see_also:
                    recurring_ok = True
                    break
        if recurring_ok:
            checks["learnings_recurring_pattern_updated"] = True

    # Parse ERRORS.md
    if checks["errors_file_exists"]:
        err_entries = split_entries(errors_md, "ERR")
        if len(err_entries) == 1:
            checks["errors_exactly_one"] = True

        # Sections and fenced code block
        if len(err_entries) == 1 and err_entry_has_required_sections(err_entries[0][2]):
            checks["errors_sections_and_fence"] = True

        # Must contain 'REDACTED'
        if "REDACTED" in errors_md:
            checks["errors_contains_redacted"] = True

        # Ensure secret from input is not leaked
        error_input_text = read_text(error_input_path)
        secret_candidates = extract_secret_candidates(error_input_text)
        no_leak = True
        if secret_candidates:
            for c in secret_candidates:
                if c and c in errors_md:
                    no_leak = False
                    break
        # If no candidates found, we still require REDACTED presence (already checked above); consider no_leak True
        if no_leak:
            checks["errors_no_secret_leak"] = True

    # Parse FEATURE_REQUESTS.md
    if checks["feature_file_exists"]:
        feat_entries = split_entries(feat_md, "FEAT")
        if len(feat_entries) == 1:
            checks["feature_exactly_one"] = True
        if len(feat_entries) == 1 and feat_entry_has_required_sections(feat_entries[0][2]):
            checks["feature_sections_and_frequency"] = True
        # Content must include the word "redact"
        if re.search(r"(?i)\bredact\b", feat_md):
            checks["feature_contains_redact"] = True

    # SOUL.md
    if checks["soul_file_exists"]:
        # Must include phrase "redact secrets" (case-insensitive) and at least one bullet "- "
        has_phrase = re.search(r"(?i)redact secrets", soul_md) is not None
        has_bullet = re.search(r"(?m)^\s*-\s+", soul_md) is not None
        if has_phrase and has_bullet:
            checks["soul_rule_valid"] = True

    # logging_summary.json
    summary_data = None
    if os.path.isfile(summary_path):
        checks["logging_summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
            # Validate fields
            if (
                isinstance(summary_data, dict)
                and isinstance(summary_data.get("learnings_count"), int)
                and isinstance(summary_data.get("errors_count"), int)
                and isinstance(summary_data.get("feature_requests_count"), int)
                and isinstance(summary_data.get("ids"), list)
                and all(isinstance(x, str) and id_regex_match(x) for x in summary_data["ids"])
            ):
                checks["logging_summary_valid_json"] = True
        except Exception:
            summary_data = None

    # Counts consistency and IDs coverage
    if checks["logging_summary_valid_json"]:
        # Gather counts from files
        lrn_count = count_headings(learnings_md, "LRN") if checks["learnings_file_exists"] else 0
        err_count = count_headings(errors_md, "ERR") if checks["errors_file_exists"] else 0
        feat_count = count_headings(feat_md, "FEAT") if checks["feature_file_exists"] else 0

        if (
            summary_data.get("learnings_count") == lrn_count
            and summary_data.get("errors_count") == err_count
            and summary_data.get("feature_requests_count") == feat_count
            and lrn_count >= 3
            and err_count == 1
            and feat_count == 1
        ):
            checks["logging_summary_counts_match"] = True

        # IDs coverage: ensure all IDs found in outputs are present in summary ids
        found_ids = set()
        if checks["learnings_file_exists"]:
            found_ids.update(ids_from_entries(split_entries(learnings_md, "LRN")))
        if checks["errors_file_exists"]:
            found_ids.update(ids_from_entries(split_entries(errors_md, "ERR")))
        if checks["feature_file_exists"]:
            found_ids.update(ids_from_entries(split_entries(feat_md, "FEAT")))
        summary_ids = set(summary_data.get("ids", []))
        if found_ids and found_ids.issubset(summary_ids):
            checks["logging_summary_ids_cover_outputs"] = True

    # No extra output files: only the specified files should exist
    allowed = {
        os.path.join(output_dir, ".learnings", "LEARNINGS.md"),
        os.path.join(output_dir, ".learnings", "ERRORS.md"),
        os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md"),
        os.path.join(output_dir, "SOUL.md"),
        os.path.join(output_dir, "logging_summary.json"),
    }
    # Also allow the .learnings directory itself
    existing_files = set(list_all_files(output_dir)) if os.path.isdir(output_dir) else set()
    # If output_dir doesn't exist and no files, no_extra_output_files should be False (baseline)
    if existing_files:
        # Validate no files outside allowed set
        no_extra = all(path in allowed for path in existing_files)
        checks["no_extra_output_files"] = no_extra

    # Compute reward as fraction passed. Baseline: if no outputs or missing required artifacts, reward should be 0.
    # We enforce 0 if the core artifacts are missing:
    core_required = [
        "learnings_file_exists",
        "errors_file_exists",
        "feature_file_exists",
        "soul_file_exists",
        "logging_summary_exists",
    ]
    if not all(checks[k] for k in core_required):
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()