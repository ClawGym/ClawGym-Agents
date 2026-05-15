#!/usr/bin/env python3
"""
Skeleton extractor for RFC normative statements.
Extend this script to:
  - Scan downloaded/*.txt
  - Extract sentences containing RFC 2119 keywords (MUST, MUST NOT, SHOULD, SHOULD NOT, MAY)
  - Write output/requirements.json and output/requirements_summary.csv as described in the task
"""
import os
import re
import json
from pathlib import Path
from collections import defaultdict

RFC_DIR = Path('downloaded')
OUT_JSON = Path('output/requirements.json')
OUT_SUMMARY = Path('output/requirements_summary.csv')

RFC_KEYWORDS = ["MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY"]

# Very naive sentence split; you may improve as needed.
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')

# Optional section header pattern (e.g., "3.1" or "2." at line starts)
SECTION_RE = re.compile(r'^(\d+(?:\.\d+)*)\s')


def extract_from_text(rfc_name, text):
    # TODO: implement extraction logic
    return []


def main():
    os.makedirs('output', exist_ok=True)
    entries = []
    for p in RFC_DIR.glob('*.txt'):
        rfc_name = p.stem.upper()  # e.g., RFC7844
        with p.open('r', encoding='utf-8', errors='ignore') as f:
            txt = f.read()
        # TODO: replace with real extraction
        # Placeholder extracts nothing to force implementation
        data = extract_from_text(rfc_name, txt)
        entries.extend(data)

    # Write empty outputs by default (to be replaced once implemented)
    with OUT_JSON.open('w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2)

    # Summary CSV header
    with OUT_SUMMARY.open('w', encoding='utf-8') as f:
        f.write('rfc,keyword,count\n')
        # TODO: aggregate and write counts once implemented


if __name__ == '__main__':
    main()
