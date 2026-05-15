import json
import os
import re
import sys
from typing import List, Dict, Any, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def parse_md_entries(text: str, expected_type: str) -> List[Dict[str, Any]]:
    # Entries start with: ## [TYPE-YYYYMMDD-XXX] <rest>
    pattern = re.compile(r'^## \[(LRN|ERR|FEAT)-(\d{8})-(\d{3})\]\s*(.*)$')
    lines = text.splitlines()
    entries: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    current_lines: List[str] = []

    def close_current():
        if current:
            current["body"] = "\n".join(current_lines).strip()
            # Build sections map from '### '
            sections: Dict[str, str] = {}
            body_lines = current["body"].splitlines()
            idx = 0
            current_title = None
            current_section_lines: List[str] = []
            while idx < len(body_lines):
                line = body_lines[idx]
                if line.startswith("### "):
                    # store previous
                    if current_title is not None:
                        sections[current_title] = "\n".join(current_section_lines).strip()
                    current_title = line[4:].strip()
                    current_section_lines = []
                else:
                    current_section_lines.append(line)
                idx += 1
            if current_title is not None:
                sections[current_title] = "\n".join(current_section_lines).strip()
            current["sections"] = sections
            entries.append(current.copy())

    for line in lines:
        m = pattern.match(line.strip())
        if m:
            # New entry
            if current:
                close_current()
                current = {}
                current_lines = []
            type_, date_, seq, rest = m.groups()
            current = {
                "type": type_,
                "date": date_,
                "seq": seq,
                "rest": rest.strip(),
                "header": line.strip(),
            }
            current_lines = []
        else:
            if current:
                current_lines.append(line)
            else:
                # ignore preface text before first entry
                continue
    if current:
        close_current()
    # Filter by expected type to be strict
    filtered = [e for e in entries if e.get("type") == expected_type]
    return filtered

def has_logged_timestamp(entry_text: str) -> bool:
    # Look for **Logged**: 2025-01-15T10:30:00Z (simple regex)
    return re.search(r'\*\*Logged\*\*:\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', entry_text) is not None

def has_priority(entry_text: str, expected: str) -> bool:
    return re.search(r'\*\*Priority\*\*:\s*' + re.escape(expected) + r'\b', entry_text) is not None

def has_status_pending(entry_text: str) -> bool:
    return re.search(r'\*\*Status\*\*:\s*pending\b', entry_text) is not None

def sequence_ok(entries: List[Dict[str, Any]], expected_count: int, start: int = 1) -> bool:
    if len(entries) != expected_count:
        return False
    try:
        seqs = [int(e["seq"]) for e in entries]
    except Exception:
        return False
    # Ensure entries are in document order; verify they cover start..start+count-1
    expected_seqs = list(range(start, start + expected_count))
    return seqs == expected_seqs

def check_required_sections(entries: List[Dict[str, Any]], required_titles: List[str]) -> bool:
    for e in entries:
        sections = e.get("sections", {})
        for t in required_titles:
            if t not in sections:
                return False
    return True

def check_fields(entries: List[Dict[str, Any]], priority: str) -> bool:
    for e in entries:
        body = e.get("body", "")
        if not has_logged_timestamp(body):
            return False
        if not has_priority(body, priority):
            return False
        if not has_status_pending(body):
            return False
    return True

def any_contains(text: str, subs: List[str]) -> bool:
    t = text.lower()
    return all(sub.lower() in t for sub in subs)

def extract_text_for_sections(entry: Dict[str, Any], titles: List[str]) -> str:
    sections = entry.get("sections", {})
    parts = []
    for t in titles:
        if t in sections:
            parts.append(sections[t])
    return "\n".join(parts)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    out_learnings_dir = os.path.join(output_dir, ".learnings")
    learnings_path = os.path.join(out_learnings_dir, "LEARNINGS.md")
    errors_path = os.path.join(out_learnings_dir, "ERRORS.md")
    features_path = os.path.join(out_learnings_dir, "FEATURE_REQUESTS.md")

    checks: Dict[str, bool] = {
        "has_output_learnings_dir": False,
        "has_learnings_file": False,
        "has_errors_file": False,
        "has_features_file": False,
        "learnings_entry_count_2": False,
        "errors_entry_count_2": False,
        "features_entry_count_1": False,
        "learnings_ids_and_seq_ok": False,
        "errors_ids_and_seq_ok": False,
        "features_ids_and_seq_ok": False,
        "learnings_fields_and_sections_ok": False,
        "errors_fields_and_sections_ok": False,
        "features_fields_and_sections_ok": False,
        "learnings_keywords_requirements_ok": False,
        "errors_keywords_requirements_ok": False,
        "features_keywords_requirements_ok": False,
    }

    # Existence checks
    if os.path.isdir(out_learnings_dir):
        checks["has_output_learnings_dir"] = True
    if os.path.isfile(learnings_path):
        checks["has_learnings_file"] = True
    if os.path.isfile(errors_path):
        checks["has_errors_file"] = True
    if os.path.isfile(features_path):
        checks["has_features_file"] = True

    # If any required file is missing, reward should be 0.0 (no-op baseline)
    required_exist = checks["has_output_learnings_dir"] and checks["has_learnings_file"] and checks["has_errors_file"] and checks["has_features_file"]

    if required_exist:
        # Parse files
        learnings_text = read_text(learnings_path)
        errors_text = read_text(errors_path)
        features_text = read_text(features_path)

        learnings_entries = parse_md_entries(learnings_text, "LRN")
        errors_entries = parse_md_entries(errors_text, "ERR")
        features_entries = parse_md_entries(features_text, "FEAT")

        # Counts
        if len(learnings_entries) == 2:
            checks["learnings_entry_count_2"] = True
        if len(errors_entries) == 2:
            checks["errors_entry_count_2"] = True
        if len(features_entries) == 1:
            checks["features_entry_count_1"] = True

        # ID format and sequencing and, for LEARNINGS, category in heading must be "correction"
        def ids_and_seq_ok(entries: List[Dict[str, Any]], expected_count: int, expected_type: str, require_rest: str = None) -> bool:
            if len(entries) != expected_count:
                return False
            # Validate each header format again
            for e in entries:
                header = e.get("header", "")
                m = re.match(r'^## \[' + expected_type + r'-(\d{8})-(\d{3})\]\s*(.*)$', header)
                if not m:
                    return False
                if require_rest is not None:
                    rest = m.group(3).strip()
                    if rest != require_rest:
                        return False
            return sequence_ok(entries, expected_count)

        checks["learnings_ids_and_seq_ok"] = ids_and_seq_ok(learnings_entries, 2, "LRN", require_rest="correction")
        checks["errors_ids_and_seq_ok"] = ids_and_seq_ok(errors_entries, 2, "ERR", require_rest=None)
        checks["features_ids_and_seq_ok"] = ids_and_seq_ok(features_entries, 1, "FEAT", require_rest=None)

        # Fields and sections
        checks["learnings_fields_and_sections_ok"] = (
            check_fields(learnings_entries, "high") and
            check_required_sections(learnings_entries, ["Summary", "Details", "Suggested Action"])
        )
        checks["errors_fields_and_sections_ok"] = (
            check_fields(errors_entries, "high") and
            check_required_sections(errors_entries, ["Summary", "Error", "Context", "Suggested Fix"])
        )
        checks["features_fields_and_sections_ok"] = (
            check_fields(features_entries, "medium") and
            check_required_sections(features_entries, ["Requested Capability", "User Context", "Complexity Estimate"])
        )

        # Keyword presence checks
        # LEARNINGS: one entry with 'tax' and 'shipping' in Summary or Details; another entry with 'discount' and 'before tax' in Summary or Details
        tax_shipping_indices = []
        discount_before_tax_indices = []
        for idx, e in enumerate(learnings_entries):
            text_sd = extract_text_for_sections(e, ["Summary", "Details"])
            if any_contains(text_sd, ["tax", "shipping"]):
                tax_shipping_indices.append(idx)
            if any_contains(text_sd, ["discount", "before tax"]):
                discount_before_tax_indices.append(idx)
        # Ensure they exist and are in different entries
        learnings_kw_ok = False
        if tax_shipping_indices and discount_before_tax_indices:
            # Check if there exist indices that are different
            for i in tax_shipping_indices:
                for j in discount_before_tax_indices:
                    if i != j:
                        learnings_kw_ok = True
                        break
                if learnings_kw_ok:
                    break
        checks["learnings_keywords_requirements_ok"] = learnings_kw_ok

        # ERRORS: one entry with "timeout" in Error section, another with "No such file or directory" in Error section
        timeout_indices = []
        nosuchfile_indices = []
        for idx, e in enumerate(errors_entries):
            err_text = e.get("sections", {}).get("Error", "").lower()
            if "timeout" in err_text:
                timeout_indices.append(idx)
            if "no such file or directory" in err_text:
                nosuchfile_indices.append(idx)
        errors_kw_ok = False
        if timeout_indices and nosuchfile_indices:
            for i in timeout_indices:
                for j in nosuchfile_indices:
                    if i != j:
                        errors_kw_ok = True
                        break
                if errors_kw_ok:
                    break
        checks["errors_keywords_requirements_ok"] = errors_kw_ok

        # FEATURE_REQUESTS: 'export' and 'csv' in capability name line or Requested Capability/User Context
        feat_ok = False
        if features_entries:
            e = features_entries[0]
            head_rest = e.get("rest", "")
            rc = e.get("sections", {}).get("Requested Capability", "")
            uc = e.get("sections", {}).get("User Context", "")
            combined = (head_rest + "\n" + rc + "\n" + uc).lower()
            if "export" in combined and "csv" in combined:
                feat_ok = True
        checks["features_keywords_requirements_ok"] = feat_ok

    # Compute reward
    # If required files are missing, reward is 0.0 explicitly (no-op baseline).
    if not required_exist:
        reward = 0.0
    else:
        # Average of all checks
        bool_values = list(checks.values())
        total = len(bool_values)
        passed = sum(1 for v in bool_values if v)
        reward = passed / total if total > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()