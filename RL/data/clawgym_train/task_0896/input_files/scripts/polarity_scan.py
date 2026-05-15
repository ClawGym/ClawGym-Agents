#!/usr/bin/env python3
import argparse
import csv
import os
import re
import sys
from typing import List, Tuple

def load_lexicon(path: str) -> List[Tuple[str, str, re.Pattern]]:
    terms = []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = row['term'].strip()
            cat = row.get('category', '').strip() or 'unknown'
            if not term:
                continue
            # Word boundary match for exact term/phrase, case-insensitive
            pattern = re.compile(r"\\b" + re.escape(term) + r"\\b", re.IGNORECASE)
            terms.append((term, cat, pattern))
    return terms

def iter_txt_files(root: str):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith('.txt'):
                yield os.path.join(dirpath, fn)

def scan(in_dir: str, lex_path: str, out_csv: str) -> Tuple[int, int]:
    lex = load_lexicon(lex_path)
    files_scanned = 0
    flags = []
    for path in sorted(iter_txt_files(in_dir)):
        files_scanned += 1
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, start=1):
                    for term, cat, pat in lex:
                        if pat.search(line):
                            flags.append((path, i, term, cat, line.rstrip('\n')))
        except Exception as e:
            print(f"Error reading {path}: {e}", file=sys.stderr)
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['file', 'line_no', 'term', 'category', 'line_text'])
        for row in flags:
            writer.writerow(row)
    return files_scanned, len(flags)

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='polarity_scan.py',
        description='Scan .txt files for occurrences of terms from a lexicon CSV.'
    )
    parser.add_argument('--in', dest='in_dir', help='Input directory containing .txt files', required=False)
    parser.add_argument('--lex', dest='lex', help='CSV lexicon with columns: term,category', required=False)
    parser.add_argument('--out', dest='out', help='Output CSV path', required=False)
    args = parser.parse_args(argv)

    if not args.in_dir or not args.lex or not args.out:
        print('Usage: python3 scripts/polarity_scan.py --in <dir> --lex <csv> --out <csv>', file=sys.stderr)
        return 2
    if not os.path.isdir(args.in_dir):
        print(f"Input directory not found: {args.in_dir}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.lex):
        print(f"Lexicon file not found: {args.lex}", file=sys.stderr)
        return 2
    files_scanned, flags_count = scan(args.in_dir, args.lex, args.out)
    print(f"Scanned {files_scanned} files, found {flags_count} flagged occurrences. Output: {args.out}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
