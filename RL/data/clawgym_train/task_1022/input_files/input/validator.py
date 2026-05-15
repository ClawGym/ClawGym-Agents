import sys
import re
from typing import List

USAGE = "Usage: python input/validator.py <path-to-markdown>"

def read_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def find_present_terms(text: str, terms: List[str]) -> List[str]:
    present = []
    for t in terms:
        if re.search(re.escape(t), text, flags=re.IGNORECASE):
            present.append(t)
    return present

def count_citations(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip().lower().startswith("citation:"):
            count += 1
    return count

def main():
    if len(sys.argv) != 2:
        sys.stderr.write(USAGE + "\n")
        sys.exit(2)
    path = sys.argv[1]
    try:
        text = read_text(path)
    except Exception as e:
        sys.stderr.write(f"Error: cannot read file: {e}\n")
        sys.exit(2)

    evidence_terms = ["evidence", "randomized", "trial", "peer-reviewed", "systematic", "placebo", "control"]
    present = find_present_terms(text, evidence_terms)
    citations = count_citations(text)

    # stdout informational lines
    sys.stdout.write(f"Validated {path}: {len(present)} evidence-centric term groups present\n")
    sys.stdout.write(f"Citations found: {citations}\n")

    # stderr warnings for each unique present evidence term
    for term in present:
        sys.stderr.write(f"Warning: evidence-centric term '{term}' found\n")

    # error if no citations
    exit_code = 0
    if citations == 0:
        sys.stderr.write("Error: missing citations\n")
        exit_code = 1

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
