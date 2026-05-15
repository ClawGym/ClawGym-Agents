import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def get_h2_titles(markdown_text):
    titles = []
    for line in markdown_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("## ") and not stripped.startswith("###"):
            titles.append(stripped[3:].strip())
    return titles

def extract_section(text, header_title):
    # Extract content under the given H2 header until the next H2 or end
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("## ") and not line.lstrip().startswith("###"):
            title = line.lstrip()[3:].strip()
            if title == header_title:
                start_idx = i
                break
    if start_idx is None:
        return ""
    # Find next H2 after start
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("## ") and not lines[j].lstrip().startswith("###"):
            end_idx = j
            break
    section_content = "\n".join(lines[start_idx + 1:end_idx])
    return section_content

def has_ascii_diagram_block(section_text):
    # Must contain the literal line "ASCII Diagram:" followed by a fenced code block (``` ... ```)
    idx = section_text.find("ASCII Diagram:")
    if idx == -1:
        return False
    after = section_text[idx + len("ASCII Diagram:"):]
    first = after.find("```")
    if first == -1:
        return False
    second = after.find("```", first + 3)
    if second == -1:
        return False
    return True

def contains_all_substrings(text, substrings):
    return all(sub in text for sub in substrings)

def adr_has_required_sections(text):
    required = ["## Status", "## Context", "## Decision", "## Consequences", "## Alternatives Considered"]
    return contains_all_substrings(text, required)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    solution_path = os.path.join(output_dir, "architecture", "solution.md")
    adr1_path = os.path.join(output_dir, "architecture", "adrs", "0001-choose-architecture.md")
    adr2_path = os.path.join(output_dir, "architecture", "adrs", "0002-select-database.md")

    # Initialize checks (all False by default)
    checks = {
        "solution_exists": False,
        "solution_has_exact_headers": False,
        "high_level_has_ascii_diagram_block": False,
        "solution_references_adr1": False,
        "solution_references_adr2": False,
        "mentions_nfr_categories": False,
        "adr1_exists": False,
        "adr1_has_sections": False,
        "adr2_exists": False,
        "adr2_has_sections": False,
    }

    # Expected H2 headers in exact order
    expected_h2 = [
        "Requirements Summary",
        "High-Level Architecture",
        "Non-Functional Requirements",
        "Key Decisions",
        "Technology Recommendations",
        "Risks and Mitigations",
        "Scaling Strategy",
        "Failure Modes",
    ]

    # Check solution file
    if os.path.isfile(solution_path):
        checks["solution_exists"] = True
        sol_text = read_text(solution_path) or ""
        # H2 headers exact match
        h2_titles = get_h2_titles(sol_text)
        if h2_titles == expected_h2:
            checks["solution_has_exact_headers"] = True

        # High-Level Architecture section must contain ASCII Diagram followed by fenced code block
        if checks["solution_has_exact_headers"] or "High-Level Architecture" in h2_titles:
            section_text = extract_section(sol_text, "High-Level Architecture")
            if has_ascii_diagram_block(section_text):
                checks["high_level_has_ascii_diagram_block"] = True

        # References to ADRs by exact relative path
        if "output/architecture/adrs/0001-choose-architecture.md" in sol_text:
            checks["solution_references_adr1"] = True
        if "output/architecture/adrs/0002-select-database.md" in sol_text:
            checks["solution_references_adr2"] = True

        # Mentions NFR categories (anywhere in file)
        lowered = sol_text.lower()
        nfr_terms = ["performance", "scalability", "availability", "security"]
        if all(term in lowered for term in nfr_terms):
            checks["mentions_nfr_categories"] = True

    # Check ADR 1
    if os.path.isfile(adr1_path):
        checks["adr1_exists"] = True
        adr1_text = read_text(adr1_path) or ""
        if adr_has_required_sections(adr1_text):
            checks["adr1_has_sections"] = True

    # Check ADR 2
    if os.path.isfile(adr2_path):
        checks["adr2_exists"] = True
        adr2_text = read_text(adr2_path) or ""
        if adr_has_required_sections(adr2_text):
            checks["adr2_has_sections"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir is missing or empty of required files, ensure reward 0.0
    if not checks["solution_exists"] and not checks["adr1_exists"] and not checks["adr2_exists"]:
        reward = 0.0

    # Print result JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()