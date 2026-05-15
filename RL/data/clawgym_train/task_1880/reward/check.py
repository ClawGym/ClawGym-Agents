import json
import os
import re
import sys
from typing import List, Dict, Tuple, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_entries(content: str, kind: str) -> List[Dict]:
    # kind in {"learnings","errors","features"}
    if kind == "learnings":
        header_re = re.compile(r'^## \[(LRN-\d{8}-[A-Za-z0-9]{3})\]\s+(\w+)\s*$', re.MULTILINE)
    elif kind == "errors":
        header_re = re.compile(r'^## \[(ERR-\d{8}-[A-Za-z0-9]{3})\]\s+(\S+)\s*$', re.MULTILINE)
    elif kind == "features":
        header_re = re.compile(r'^## \[(FEAT-\d{8}-[A-Za-z0-9]{3})\]\s+(\S+)\s*$', re.MULTILINE)
    else:
        return []

    entries = []
    matches = list(header_re.finditer(content))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        entry_text = content[start:end]
        entries.append({
            "id": m.group(1),
            "title": m.group(2),
            "text": entry_text
        })
    return entries

def has_required_fields(entry_text: str, fields: List[str]) -> bool:
    for field in fields:
        pattern = r'\*\*' + re.escape(field) + r'\*\*:\s*.+'
        if not re.search(pattern, entry_text):
            return False
    return True

def has_sections(entry_text: str, sections: List[str]) -> bool:
    for section in sections:
        if f"### {section}" not in entry_text:
            return False
    return True

def section_content(entry_text: str, section_name: str) -> str:
    # Find content from "### section_name" to next "### " or end
    start_match = re.search(r'^### ' + re.escape(section_name) + r'\s*$', entry_text, re.MULTILINE)
    if not start_match:
        return ""
    start_idx = start_match.end()
    next_match = re.search(r'^### ', entry_text[start_idx:], re.MULTILINE)
    end_idx = start_idx + next_match.start() if next_match else len(entry_text)
    return entry_text[start_idx:end_idx]

def contains_fenced_code(block_text: str) -> bool:
    return "```" in block_text

def extract_ids(entries: List[Dict]) -> List[str]:
    return [e["id"] for e in entries]

def unique_ids(ids: List[str]) -> bool:
    return len(ids) == len(set(ids))

def find_simplify_and_harden_entry(entries: List[Dict]) -> bool:
    # Must include in Metadata: "Source: simplify-and-harden", "Pattern-Key:", "Recurrence-Count:" >= 3
    for e in entries:
        text = e["text"]
        if "### Metadata" not in text:
            continue
        if re.search(r'^\s*-\s*Source:\s*simplify-and-harden\s*$', text, re.MULTILINE):
            pk = re.search(r'^\s*-\s*Pattern-Key:\s*.+', text, re.MULTILINE)
            rc = re.search(r'^\s*-\s*Recurrence-Count:\s*(\d+)\s*', text, re.MULTILINE)
            if pk and rc:
                try:
                    count = int(rc.group(1))
                    if count >= 3:
                        return True
                except ValueError:
                    pass
    return False

def find_promoted_entry(entries: List[Dict]) -> Tuple[bool, Optional[str], Optional[Dict]]:
    # Return (has_promoted, target_file_name, entry_dict)
    for e in entries:
        text = e["text"]
        status_promoted = re.search(r'\*\*Status\*\*:\s*promoted\b', text)
        if not status_promoted:
            continue
        # Promoted field referencing CLAUDE.md or AGENTS.md
        m = re.search(r'^\s*-\s*Promoted:\s*(CLAUDE\.md|AGENTS\.md)\s*$', text, re.MULTILINE)
        if not m:
            continue
        target = m.group(1)
        # Resolution block with Resolved timestamp line
        if "### Resolution" in text and re.search(r'Resolved\s*:\s*', text):
            return True, target, e
        # If resolution missing, we still report promoted presence elsewhere; handled separately
        return True, target, e
    return False, None, None

def has_resolution_block(entry_text: str) -> bool:
    if "### Resolution" not in entry_text:
        return False
    # Look for a line with "Resolved:"
    return re.search(r'Resolved\s*:\s*', entry_text) is not None

def cross_linking_ok(learnings_content: str, error_ids: List[str]) -> bool:
    if not error_ids:
        return False
    # Look for "See Also: ERR-..." referencing an existing ERR id
    pattern = re.compile(r'See Also:\s*(ERR-\d{8}-[A-Za-z0-9]{3})')
    refs = pattern.findall(learnings_content)
    for ref in refs:
        if ref in error_ids:
            return True
    return False

def promoted_file_has_rule(output_dir: str, file_name: str) -> bool:
    path = os.path.join(output_dir, file_name)
    content = read_text(path)
    if content is None:
        return False
    # At least one short rule line: either "- something" or any non-empty line
    for line in content.splitlines():
        if re.match(r'^\s*-\s+.+', line):
            return True
    # Fallback: any non-empty line counts
    for line in content.splitlines():
        if line.strip():
            return True
    return False

def count_well_formed(entries: List[Dict], kind: str) -> int:
    count = 0
    for e in entries:
        t = e["text"]
        if kind == "learnings":
            if not has_required_fields(t, ["Logged", "Priority", "Status", "Area"]):
                continue
            if not has_sections(t, ["Summary", "Details", "Suggested Action", "Metadata"]):
                continue
            count += 1
        elif kind == "errors":
            if not has_required_fields(t, ["Logged", "Priority", "Status", "Area"]):
                continue
            if not has_sections(t, ["Summary", "Error", "Context", "Suggested Fix", "Metadata"]):
                continue
            err_block = section_content(t, "Error")
            if not contains_fenced_code(err_block):
                continue
            count += 1
        elif kind == "features":
            if not has_required_fields(t, ["Logged", "Priority", "Status", "Area"]):
                continue
            if not has_sections(t, ["Requested Capability", "User Context", "Complexity Estimate", "Suggested Implementation", "Metadata"]):
                continue
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        "has_learnings_file": False,
        "has_errors_file": False,
        "has_feature_requests_file": False,
        "learnings_min_two_well_formed": False,
        "errors_min_two_well_formed": False,
        "feature_requests_min_one_well_formed": False,
        "unique_ids_learnings": False,
        "unique_ids_errors": False,
        "unique_ids_features": False,
        "simplify_and_harden_entry": False,
        "promoted_learning_present": False,
        "promoted_resolution_block": False,
        "promoted_file_exists_with_rule": False,
        "cross_linking_see_also": False,
        "changelog_ok": False,
    }

    # Paths
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    features_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    changelog_path = os.path.join(output_dir, "CHANGELOG.md")

    learnings_content = read_text(learnings_path)
    errors_content = read_text(errors_path)
    features_content = read_text(features_path)

    if learnings_content is not None:
        checks["has_learnings_file"] = True
        learnings_entries = parse_entries(learnings_content, "learnings")
        # Well-formed entries count
        if count_well_formed(learnings_entries, "learnings") >= 2:
            checks["learnings_min_two_well_formed"] = True
        # Unique IDs
        checks["unique_ids_learnings"] = unique_ids(extract_ids(learnings_entries))
        # Simplify-and-harden entry
        checks["simplify_and_harden_entry"] = find_simplify_and_harden_entry(learnings_entries)
        # Promoted learning presence and resolution
        promoted_present, promoted_target, promoted_entry = find_promoted_entry(learnings_entries)
        if promoted_present:
            checks["promoted_learning_present"] = True
            # Resolution block
            if promoted_entry and has_resolution_block(promoted_entry["text"]):
                checks["promoted_resolution_block"] = True
            # Promoted file with rule
            if promoted_target:
                if promoted_file_has_rule(output_dir, promoted_target):
                    checks["promoted_file_exists_with_rule"] = True
    else:
        learnings_entries = []

    if errors_content is not None:
        checks["has_errors_file"] = True
        errors_entries = parse_entries(errors_content, "errors")
        if count_well_formed(errors_entries, "errors") >= 2:
            checks["errors_min_two_well_formed"] = True
        checks["unique_ids_errors"] = unique_ids(extract_ids(errors_entries))
    else:
        errors_entries = []

    if features_content is not None:
        checks["has_feature_requests_file"] = True
        features_entries = parse_entries(features_content, "features")
        if count_well_formed(features_entries, "features") >= 1:
            checks["feature_requests_min_one_well_formed"] = True
        checks["unique_ids_features"] = unique_ids(extract_ids(features_entries))
    else:
        features_entries = []

    # Cross-linking: See Also in LEARNINGS referencing ERR ids that exist
    if learnings_content is not None and errors_entries:
        err_ids = extract_ids(errors_entries)
        checks["cross_linking_see_also"] = cross_linking_ok(learnings_content, err_ids)

    # Changelog
    changelog_content = read_text(changelog_path)
    if changelog_content is not None:
        required_terms = ["LEARNINGS", "ERRORS", "FEATURE_REQUESTS", "promoted"]
        if all(term in changelog_content for term in required_terms):
            checks["changelog_ok"] = True

    # Compute reward as fraction of passed deterministic checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if no relevant output files and nothing passed, reward should be 0.0
    # Our computation already yields 0.0 when passed == 0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()