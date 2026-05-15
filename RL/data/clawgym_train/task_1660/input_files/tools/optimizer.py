#!/usr/bin/env python3
import argparse
import csv
import json
import sys


def parse_config(file_path):
    cfg = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            # strip inline comments (naive)
            if '#' in line:
                parts = line.split('#', 1)
                line = parts[0].strip()
                if not line:
                    continue
            if ':' not in line:
                continue
            k, v = line.split(':', 1)
            k = k.strip()
            v = v.strip()
            # remove surrounding quotes if present
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            lower = v.lower()
            if lower == 'true':
                val = True
            elif lower == 'false':
                val = False
            else:
                try:
                    val = int(v)
                except ValueError:
                    val = v
            cfg[k] = val
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--inventory', required=True)
    ap.add_argument('--sales', required=True)
    args = ap.parse_args()

    errors = 0
    warnings = 0

    # Load config
    try:
        cfg = parse_config(args.config)
    except Exception as e:
        print(f"ERROR: Failed to read config '{args.config}': {e}")
        return 1

    iq = cfg.get('image_quality', None)
    if not isinstance(iq, int):
        print(f"ERROR: Invalid image_quality '{iq}' (expected integer 1-100).")
        errors += 1
    else:
        if not (1 <= iq <= 100):
            print(f"ERROR: image_quality {iq} out of range 1-100.")
            errors += 1

    # Load inventory
    try:
        with open(args.inventory, 'r', encoding='utf-8') as f:
            inv = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to read inventory '{args.inventory}': {e}")
        return 1

    inv_ids = set()
    for item in inv:
        idv = item.get('id')
        inv_ids.add(idv)
        alt = item.get('alt_text')
        if alt is None or (isinstance(alt, str) and alt.strip() == ''):
            print(f"WARN: Artwork {idv} missing alt_text.")
            warnings += 1

    # Load sales
    try:
        with open(args.sales, 'r', encoding='utf-8') as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                sid = (row.get('sale_id') or '').strip()
                art = (row.get('artwork_id') or '').strip()
                if art not in inv_ids:
                    print(f"ERROR: Sale {sid} references unknown artwork_id '{art}'.")
                    errors += 1
    except Exception as e:
        print(f"ERROR: Failed to read sales '{args.sales}': {e}")
        return 1

    print(f"SUMMARY: errors={errors} warnings={warnings}")
    return 1 if errors > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
