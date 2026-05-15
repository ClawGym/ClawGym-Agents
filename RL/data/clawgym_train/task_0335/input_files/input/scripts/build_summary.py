import argparse
import csv
import os
import re
import sys
from datetime import datetime

OPEN_ITEM_RE = re.compile(r"^\s*-\s\[ \]\s")

def parse_note(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()

    title = None
    date_str = None
    tags = []

    # Check first non-empty line is a level-1 title
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if s == "":
            continue
        if s.startswith('# '):
            title = s[2:].strip()
        else:
            sys.stderr.write(f"ERROR {os.path.basename(path)}: First non-empty line must start with '# ' for the title.\n")
            return None
        break

    # Find Date and Tags lines anywhere in the file
    for raw in lines:
        s = raw.strip()
        if s.startswith('Date:'):
            value = s[len('Date:'):].strip()
            try:
                # require ISO YYYY-MM-DD
                datetime.strptime(value, '%Y-%m-%d')
                date_str = value
            except Exception:
                sys.stderr.write(f"ERROR {os.path.basename(path)}: Missing or invalid Date in ISO format YYYY-MM-DD.\n")
                return None
        elif s.startswith('Tags:'):
            value = s[len('Tags:'):].strip()
            tags = [t.strip() for t in value.split(',') if t.strip()]

    if title is None:
        sys.stderr.write(f"ERROR {os.path.basename(path)}: Missing title heading. First non-empty line must start with '# '.\n")
        return None
    if date_str is None:
        sys.stderr.write(f"ERROR {os.path.basename(path)}: Missing or invalid Date in ISO format YYYY-MM-DD.\n")
        return None

    # Count open action items (unchecked checkboxes)
    open_items = 0
    for raw in lines:
        if OPEN_ITEM_RE.search(raw):
            open_items += 1

    return {
        'file': os.path.basename(path),
        'date': date_str,
        'title': title,
        'tags': ';'.join(tags),
        'open_action_items': str(open_items)
    }

def main():
    ap = argparse.ArgumentParser(description='Build a summary CSV from meeting notes.')
    ap.add_argument('--src', required=True, help='Directory of markdown notes')
    ap.add_argument('--out', required=True, help='Output CSV path')
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        sys.stderr.write(f"ERROR: src directory not found: {args.src}\n")
        sys.exit(2)

    md_files = []
    for root, _, files in os.walk(args.src):
        for name in files:
            if name.lower().endswith('.md'):
                md_files.append(os.path.join(root, name))
    md_files.sort()

    rows = []
    for path in md_files:
        rec = parse_note(path)
        if rec is None:
            sys.exit(2)
        rows.append(rec)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, 'w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=['file','date','title','tags','open_action_items'])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote summary to {args.out} with {len(rows)} notes.")

if __name__ == '__main__':
    main()
