import sys
import os
from datetime import datetime

USAGE = "Usage: python3 validate_updates.py <updates_dir>"

def validate_file(path):
    warnings = 0
    print(f"FILE: {os.path.basename(path)}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for idx, raw in enumerate(f, start=1):
                line = raw.strip('\n')
                if not line or line.strip().startswith('#'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) != 4:
                    print(f"WARNING: {os.path.basename(path)}:{idx} expected 4 fields but got {len(parts)} -> {line}")
                    warnings += 1
                    continue
                date_s, country, headline, source = parts
                try:
                    datetime.strptime(date_s, '%Y-%m-%d')
                except Exception:
                    print(f"WARNING: {os.path.basename(path)}:{idx} invalid date '{date_s}' -> {line}")
                    warnings += 1
                if not country:
                    print(f"WARNING: {os.path.basename(path)}:{idx} empty country -> {line}")
                    warnings += 1
                if not headline:
                    print(f"WARNING: {os.path.basename(path)}:{idx} empty headline -> {line}")
                    warnings += 1
                if not source:
                    print(f"WARNING: {os.path.basename(path)}:{idx} empty source -> {line}")
                    warnings += 1
    except FileNotFoundError:
        print(f"ERROR: file not found {path}")
        return 1
    if warnings == 0:
        print("OK: no issues detected")
    else:
        print(f"TOTAL WARNINGS: {warnings}")
    return 0


def main():
    if len(sys.argv) != 2:
        print(USAGE)
        return 2
    updates_dir = sys.argv[1]
    if not os.path.isdir(updates_dir):
        print(f"ERROR: not a directory: {updates_dir}")
        return 2
    files = [os.path.join(updates_dir, fn) for fn in os.listdir(updates_dir) if fn.endswith('.txt')]
    files.sort()
    exit_code = 0
    for f in files:
        rc = validate_file(f)
        exit_code = max(exit_code, rc)
    print(f"SUMMARY: files={len(files)}")
    return exit_code

if __name__ == '__main__':
    sys.exit(main())
