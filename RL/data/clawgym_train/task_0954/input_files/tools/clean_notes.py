import sys
import argparse
import re

def main():
    p = argparse.ArgumentParser(description="Simple notes quality checker")
    p.add_argument('input_path', help='Path to markdown notes file')
    args = p.parse_args()

    try:
        with open(args.input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        sys.stderr.write(f"ERROR: failed to read {args.input_path}: {e}\n")
        sys.exit(1)

    count = 0
    for idx, line in enumerate(lines, start=1):
        count += 1
        stripped = line.strip()
        low = stripped.lower()
        if stripped.startswith('??:'):
            sys.stderr.write(f"WARNING: Unknown speaker tag on line {idx}\n")
        if ('next fri' in low) or ('next friday' in low) or ('tomorrow' in low):
            sys.stderr.write(f"WARNING: Ambiguous relative date on line {idx}\n")
        if len(stripped) > 200:
            sys.stderr.write(f"WARNING: Very long line (>200 chars) on line {idx}\n")
    sys.stdout.write(f"INFO: processed {count} lines\n")

if __name__ == '__main__':
    main()
