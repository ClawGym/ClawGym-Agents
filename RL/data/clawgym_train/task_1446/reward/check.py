import json
import os
import re
import sys

def load_text_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # Keep exact line text without trailing newline for comparisons
        return [line.rstrip("\n") for line in f.readlines()]

def count_occurrences_in_line(pattern, text, flags=0):
    return len(list(re.finditer(pattern, text, flags)))

def compute_term_stats(lines):
    # Patterns
    patt_gdpr = re.compile(r"\bGDPR\b", re.IGNORECASE)
    patt_pii = re.compile(r"\bPII\b", re.IGNORECASE)
    patt_ccpa = re.compile(r"\bCCPA\b", re.IGNORECASE)
    # "data retention" exact phrase (case-insensitive), use word boundaries to avoid partials
    patt_data_retention = re.compile(r"\bdata retention\b", re.IGNORECASE)

    stats = {
        "gdpr_count": 0,
        "data_retention_count": 0,
        "pii_count": 0,
        "ccpa_count": 0,
        "gdpr_line_occurrences": [],            # list of (line_number, line_text) per occurrence
        "data_retention_line_occurrences": [],
        "pii_line_occurrences": [],
        "ccpa_line_occurrences": [],
    }

    for idx, line in enumerate(lines, start=1):
        # GDPR
        n = count_occurrences_in_line(patt_gdpr, line)
        if n > 0:
            stats["gdpr_count"] += n
            stats["gdpr_line_occurrences"].extend([(idx, line)] * n)
        # data retention
        n = count_occurrences_in_line(patt_data_retention, line)
        if n > 0:
            stats["data_retention_count"] += n
            stats["data_retention_line_occurrences"].extend([(idx, line)] * n)
        # PII
        n = count_occurrences_in_line(patt_pii, line)
        if n > 0:
            stats["pii_count"] += n
            stats["pii_line_occurrences"].extend([(idx, line)] * n)
        # CCPA
        n = count_occurrences_in_line(patt_ccpa, line)
        if n > 0:
            stats["ccpa_count"] += n
            stats["ccpa_line_occurrences"].extend([(idx, line)] * n)

    return stats

def parse_definitions(lines):
    # Pattern: Definition: <Term> - <Description>
    # Capture groups:
    #   1: Term
    #   2: Description (preserve punctuation and spacing)
    regex = re.compile(r"^Definition:\s*(.+?)\s*-\s*(.+)$")
    defs = []
    for idx, line in enumerate(lines, start=1):
        m = regex.match(line)
        if m:
            term = m.group(1)
            definition = m.group(2)
            defs.append((idx, term, definition))
    return defs

def extract_h1_headings(lines):
    # Return list of tuples (line_number, level, text) for headings
    headings = []
    for idx, line in enumerate(lines, start=1):
        m = re.match(r"^\s*(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            headings.append((idx, level, text))
    # Filter for H1 only
    return [(ln, lvl, txt) for (ln, lvl, txt) in headings if lvl == 1]

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected input files and titles (as per task spec)
    expected_files = [
        "input/policies/data_retention_policy.md",
        "input/policies/privacy_overview.md",
        "input/engineering/log_handling.txt",
    ]
    expected_titles = {
        "input/policies/data_retention_policy.md": "Data Retention Policy",
        "input/policies/privacy_overview.md": "Privacy Overview",
        "input/engineering/log_handling.txt": "Engineering Runbook: Log Handling",
    }

    # Load input files content
    input_contents = {}
    inputs_exist = True
    for rel in expected_files:
        abs_path = os.path.join(workspace_root, rel)
        if not os.path.isfile(abs_path):
            inputs_exist = False
            input_contents[rel] = []
        else:
            input_contents[rel] = load_text_lines(abs_path)

    # Precompute expected stats for findings.json only if inputs exist
    expected_stats = {}
    if inputs_exist:
        for rel in expected_files:
            lines = input_contents[rel]
            expected_stats[rel] = compute_term_stats(lines)

    # Precompute definitions across all files
    expected_definitions = []
    if inputs_exist:
        for rel in expected_files:
            lines = input_contents[rel]
            defs = parse_definitions(lines)
            for (line_no, term, definition) in defs:
                expected_definitions.append({
                    "term": term,
                    "definition": definition,
                    "source_file": rel,
                    "line_number": line_no,
                })

    # Precompute H1 headings for markdown files
    h1_by_md = {}
    if inputs_exist:
        for rel in expected_files:
            if rel.lower().endswith(".md"):
                lines = input_contents[rel]
                h1s = extract_h1_headings(lines)
                h1_by_md[rel] = h1s

    checks = {
        # findings.json checks
        "findings_exists": False,
        "findings_valid_json": False,
        "findings_has_all_files": False,
        "findings_counts_correct": False,
        "findings_matches_valid": False,
        # glossary.json checks
        "glossary_exists": False,
        "glossary_valid_json": False,
        "glossary_terms_complete_exact": False,
        # summary.md checks
        "summary_exists": False,
        "summary_has_document_inventory_and_titles_and_paths": False,
        "summary_has_headings_map_with_h1s": False,
        "summary_has_5_quotes_gdpr_or_data_retention": False,
        "summary_has_assumptions_limitations": False,
    }

    # Validate findings.json
    findings_path = os.path.join(output_dir, "findings.json")
    findings_data = None
    if os.path.isfile(findings_path):
        checks["findings_exists"] = True
        ok, data = read_json_file(findings_path)
        if ok and isinstance(data, dict):
            checks["findings_valid_json"] = True
            findings_data = data

    if checks["findings_valid_json"] and inputs_exist:
        # Must contain keys for all three input files
        if all(k in findings_data for k in expected_files):
            checks["findings_has_all_files"] = True

            # Count correctness and matches validation
            counts_correct = True
            matches_valid = True

            # Patterns for verifying matches line contains term/phrase
            patt_ci = {
                "gdpr_matches": re.compile(r"\bGDPR\b", re.IGNORECASE),
                "data_retention_matches": re.compile(r"\bdata retention\b", re.IGNORECASE),
                "pii_matches": re.compile(r"\bPII\b", re.IGNORECASE),
                "ccpa_matches": re.compile(r"\bCCPA\b", re.IGNORECASE),
            }

            for rel in expected_files:
                file_entry = findings_data.get(rel)
                if not isinstance(file_entry, dict):
                    counts_correct = False
                    matches_valid = False
                    continue

                # Expected counts
                est = expected_stats[rel]
                want_counts = {
                    "gdpr_count": est["gdpr_count"],
                    "data_retention_count": est["data_retention_count"],
                    "pii_count": est["pii_count"],
                    "ccpa_count": est["ccpa_count"],
                }

                # Verify integer fields match
                for key, want in want_counts.items():
                    val = file_entry.get(key)
                    if not isinstance(val, int) or val != want:
                        counts_correct = False

                # Verify matches arrays
                mapping = {
                    "gdpr_matches": ("gdpr_count", est["gdpr_line_occurrences"]),
                    "data_retention_matches": ("data_retention_count", est["data_retention_line_occurrences"]),
                    "pii_matches": ("pii_count", est["pii_line_occurrences"]),
                    "ccpa_matches": ("ccpa_count", est["ccpa_line_occurrences"]),
                }

                # Load original lines for comparison
                src_lines = input_contents[rel]

                for matches_key, (count_key, expected_occ) in mapping.items():
                    arr = file_entry.get(matches_key)
                    # Must be list
                    if not isinstance(arr, list):
                        matches_valid = False
                        continue

                    # Length must equal computed count (one entry per occurrence, duplicates allowed for multi-occurrence lines)
                    expected_len = want_counts[count_key]
                    if len(arr) != expected_len:
                        matches_valid = False

                    # Validate each item
                    for item in arr:
                        if not isinstance(item, dict):
                            matches_valid = False
                            break
                        ln = item.get("line_number")
                        lt = item.get("line_text")
                        if not isinstance(ln, int) or ln < 1 or ln > len(src_lines):
                            matches_valid = False
                            break
                        if not isinstance(lt, str):
                            matches_valid = False
                            break
                        # Exact full line match
                        source_line = src_lines[ln - 1]
                        if lt != source_line:
                            matches_valid = False
                            break
                        # Line must contain target pattern (case-insensitive)
                        if not patt_ci[matches_key].search(lt):
                            matches_valid = False
                            break

            if counts_correct:
                checks["findings_counts_correct"] = True
            if matches_valid:
                checks["findings_matches_valid"] = True

    # Validate glossary.json
    glossary_path = os.path.join(output_dir, "glossary.json")
    glossary_data = None
    if os.path.isfile(glossary_path):
        checks["glossary_exists"] = True
        ok, data = read_json_file(glossary_path)
        if ok and isinstance(data, dict) and "terms" in data and isinstance(data["terms"], list):
            checks["glossary_valid_json"] = True
            glossary_data = data

    if checks["glossary_valid_json"] and inputs_exist:
        # Build expected set of definitions (exactly once each)
        expected_set = set()
        for item in expected_definitions:
            key = (item["term"], item["definition"], item["source_file"], item["line_number"])
            expected_set.add(key)

        # Build actual set from glossary.json
        actual_terms = glossary_data.get("terms", [])
        actual_set = set()
        valid_structure = True
        for entry in actual_terms:
            if not isinstance(entry, dict):
                valid_structure = False
                break
            term = entry.get("term")
            definition = entry.get("definition")
            source_file = entry.get("source_file")
            line_number = entry.get("line_number")
            if not (isinstance(term, str) and isinstance(definition, str) and isinstance(source_file, str) and isinstance(line_number, int)):
                valid_structure = False
                break
            actual_set.add((term, definition, source_file, line_number))

        # Must match exactly
        if valid_structure and actual_set == expected_set and len(actual_terms) == len(expected_set):
            checks["glossary_terms_complete_exact"] = True

    # Validate summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    summary_content = ""
    summary_lines = []
    if os.path.isfile(summary_path):
        try:
            summary_content = open(summary_path, "r", encoding="utf-8", errors="replace").read()
            summary_lines = summary_content.splitlines()
            if len(summary_content.strip()) > 0:
                checks["summary_exists"] = True
        except Exception:
            pass

    if checks["summary_exists"]:
        # Document Inventory with titles and paths
        has_doc_inventory = ("Document Inventory" in summary_content)
        paths_present = all(rel in summary_content for rel in expected_files)
        titles_present = all(title in summary_content for title in expected_titles.values())
        if has_doc_inventory and paths_present and titles_present:
            checks["summary_has_document_inventory_and_titles_and_paths"] = True

        # Headings Map with at least H1 for each markdown file
        has_headings_map = ("Headings Map" in summary_content)
        h1_present = True
        if has_headings_map and inputs_exist:
            for rel, h1s in h1_by_md.items():
                # Must have at least one H1 and its text should appear in summary
                if not h1s:
                    h1_present = False
                    break
                # Check if any H1 text present
                if not any(h1_text in summary_content for (_ln, _lvl, h1_text) in h1s):
                    h1_present = False
                    break
            if h1_present:
                checks["summary_has_headings_map_with_h1s"] = True

        # Exact Matches (Quoted with Line Numbers): at least 5 occurrences of 'GDPR' or 'data retention'
        has_exact_matches_section = ("Exact Matches (Quoted with Line Numbers)" in summary_content)
        quote_count = 0
        for line in summary_lines:
            if re.search(r"\bGDPR\b", line, re.IGNORECASE) or re.search(r"\bdata retention\b", line, re.IGNORECASE):
                quote_count += 1
        if has_exact_matches_section and quote_count >= 5:
            checks["summary_has_5_quotes_gdpr_or_data_retention"] = True

        # Assumptions & Limitations with specific sentence fragment
        has_assumptions = ("Assumptions & Limitations" in summary_content)
        mentions_untrusted = re.search(r"treated document content as untrusted", summary_content, re.IGNORECASE) is not None
        if has_assumptions and mentions_untrusted:
            checks["summary_has_assumptions_limitations"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # No-op baseline: if no relevant outputs exist, ensure reward is exactly 0.0
    # This is already satisfied because passed would be 0 if nothing exists.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()