import sys
import os
import re

REQUIRED_SECTIONS = [
    "Overview",
    "Key Themes",
    "Primary Source Excerpts",
    "Discussion Questions",
    "Further Reading",
]

FLAGGED_TERMS = ["corrupt", "evil", "traitor", "un-american"]


def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def get_lines(text):
    return text.splitlines()


def section_indices(lines):
    idx = {}
    for i, line in enumerate(lines):
        if line.strip().startswith("## "):
            name = line.strip()[3:].strip()
            idx[name] = i
    return idx


def extract_section(lines, heading):
    idx_map = section_indices(lines)
    if heading not in idx_map:
        return []
    start = idx_map[heading] + 1
    # find next section start
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break
    return lines[start:end]


def count_blockquotes(section_lines):
    return sum(1 for ln in section_lines if ln.lstrip().startswith(">"))


def count_bullets(section_lines):
    return sum(1 for ln in section_lines if ln.lstrip().startswith("- "))


def find_flagged_terms(text):
    found = []
    lower = text.lower()
    for term in FLAGGED_TERMS:
        # exact word or hyphenated for un-american
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, lower):
            found.append(term)
    return sorted(set(found))


def main():
    if len(sys.argv) != 2:
        print("ERROR: Provide a single Markdown file path.")
        print("USAGE: python input/checks/handout_lint.py <path-to-markdown>")
        sys.exit(2)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"ERROR: File not found: {path}")
        sys.exit(2)
    text = read_text(path)
    lines = get_lines(text)

    errors = 0
    idx_map = section_indices(lines)

    # Check for required sections
    for sec in REQUIRED_SECTIONS:
        if sec not in idx_map:
            print(f"ERROR: Missing section heading '{sec}'")
            errors += 1

    # Only proceed with content checks if sections exist
    if all(sec in idx_map for sec in REQUIRED_SECTIONS):
        # Primary Source Excerpts: at least 2 blockquotes
        pse_lines = extract_section(lines, "Primary Source Excerpts")
        num_quotes = count_blockquotes(pse_lines)
        if num_quotes < 2:
            print("ERROR: Need at least 2 blockquoted excerpts in 'Primary Source Excerpts'.")
            errors += 1

        # Discussion Questions: at least 3 bullets
        dq_lines = extract_section(lines, "Discussion Questions")
        num_q = count_bullets(dq_lines)
        if num_q < 3:
            print("ERROR: Need at least 3 questions starting with '- ' in 'Discussion Questions'.")
            errors += 1

        # Further Reading: at least 1 bullet
        fr_lines = extract_section(lines, "Further Reading")
        num_fr = count_bullets(fr_lines)
        if num_fr < 1:
            print("ERROR: Need at least 1 item starting with '- ' in 'Further Reading'.")
            errors += 1

    # Flagged terms anywhere in the handout
    flagged = find_flagged_terms(text)
    for term in flagged:
        print(f"ERROR: Flagged partisan term found: '{term}'")
        errors += 1

    if errors == 0:
        print("OK: No issues found.")
        sys.exit(0)
    else:
        print(f"SUMMARY: {errors} error(s) found.")
        sys.exit(1)

if __name__ == "__main__":
    main()
