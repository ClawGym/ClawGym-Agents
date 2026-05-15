import argparse
import json
import csv
import os
import sys


def read_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='Compute simple text metrics for each row in a CSV file.')
    parser.add_argument('--config', required=True, help='Path to JSON config')
    parser.add_argument('--input', required=True, help='Path to input CSV with an id and text column')
    parser.add_argument('--out', required=True, help='Path to output CSV to write metrics')
    args = parser.parse_args()

    cfg = read_json(args.config)
    # Expecting 'text_column' in config, but the current config uses a different key.
    text_col = cfg['text_column']  # Will raise KeyError with the current config
    do_lower = bool(cfg.get('lowercase', False))

    rows = []
    with open(args.input, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row[text_col]
            if do_lower:
                t = t.lower()
            # Duplicate, inlined metrics logic (intentionally verbose for refactoring)
            chars = len(t)
            words = len([w for w in t.split(' ') if w != ''])
            sents = 0
            for ch in t:
                if ch in '.!?':
                    sents += 1
            rows.append({
                'id': row.get('id', ''),
                'chars': chars,
                'words': words,
                'sentences': sents
            })

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'chars', 'words', 'sentences'])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == '__main__':
    sys.exit(main() or 0)
