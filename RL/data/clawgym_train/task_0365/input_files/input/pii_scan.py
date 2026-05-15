#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\s\(\)]{8,}\d")
DOB_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def scan_file(path):
    try:
        with open(path, 'r', encoding='utf-8-sig') as fh:
            text = fh.read()
    except Exception as e:
        print(f"WARNING: {os.path.basename(path)}: could not read file: {e}", file=sys.stderr)
        return {
            'file': os.path.basename(path),
            'emails': [],
            'phones': [],
            'dob_like': [],
            'warnings': [f'could not read file: {e}']
        }

    emails = sorted(set(EMAIL_RE.findall(text)))
    phones = sorted(set(PHONE_RE.findall(text)))
    dobs = sorted(set(DOB_RE.findall(text)))

    warnings = []
    # Line-based warnings for consent
    for i, line in enumerate(text.splitlines(), start=1):
        l = line.strip().lower()
        if 'consent:' in l:
            if 'consent: no' in l:
                msg = f'record indicates no consent (line {i})'
                warnings.append(msg)
                print(f"WARNING: {os.path.basename(path)}: {msg}", file=sys.stderr)
            elif 'consent: unknown' in l:
                msg = f'consent unknown (line {i})'
                warnings.append(msg)
                print(f"WARNING: {os.path.basename(path)}: {msg}", file=sys.stderr)

    return {
        'file': os.path.basename(path),
        'emails': emails,
        'phones': phones,
        'dob_like': dobs,
        'warnings': warnings
    }


def main():
    ap = argparse.ArgumentParser(description='Simple PII scanner for transcripts')
    ap.add_argument('directory', help='Directory containing .txt transcripts')
    args = ap.parse_args()

    dir_path = args.directory
    if not os.path.isdir(dir_path):
        print(f"ERROR: directory does not exist: {dir_path}", file=sys.stderr)
        sys.exit(2)

    files = [f for f in os.listdir(dir_path) if f.lower().endswith('.txt')]
    files.sort()

    results = []
    total_emails = 0
    total_phones = 0
    total_dobs = 0

    for f in files:
        rec = scan_file(os.path.join(dir_path, f))
        results.append(rec)
        total_emails += len(rec['emails'])
        total_phones += len(rec['phones'])
        total_dobs += len(rec['dob_like'])

    out = {
        'files': results,
        'summary': {
            'files_scanned': len(files),
            'email_count': total_emails,
            'phone_count': total_phones,
            'dob_like_count': total_dobs
        }
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
