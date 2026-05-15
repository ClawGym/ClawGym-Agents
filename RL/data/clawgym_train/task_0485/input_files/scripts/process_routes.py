#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
from collections import Counter


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def load_config(path):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        eprint(f"ERROR: Config file not found: {path}")
        sys.exit(1)
    except json.JSONDecodeError as ex:
        eprint(f"ERROR: Failed to parse JSON config {path}: {ex}")
        sys.exit(1)


def validate_mapping(fieldnames, mapping):
    required = ["mode", "start_year"]  # minimal fields needed for aggregation
    missing = []
    for key in required:
        col = mapping.get(key)
        if not col or col not in fieldnames:
            missing.append((key, col))
    if missing:
        msg_lines = [
            "ERROR: Missing columns in CSV per field mapping:",
        ]
        for key, col in missing:
            msg_lines.append(f"  - {key}: expected column '{col}' present in CSV header")
        eprint("\n".join(msg_lines))
        sys.exit(2)


def parse_int(value, field_name, rownum):
    try:
        return int(value)
    except Exception:
        raise ValueError(f"Non-integer value '{value}' in field '{field_name}' at row {rownum}")


def aggregate(data_path, mapping):
    counts = Counter()
    bad_years = []
    with open(data_path, 'r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        validate_mapping(fieldnames, mapping)
        mode_col = mapping["mode"]
        year_col = mapping["start_year"]
        for i, row in enumerate(reader, start=2):  # account for header line
            mode = (row.get(mode_col) or '').strip()
            year_raw = (row.get(year_col) or '').strip()
            if not mode or not year_raw:
                # Skip rows with missing essential data
                continue
            try:
                year = parse_int(year_raw, year_col, i)
            except ValueError as ex:
                bad_years.append(str(ex))
                continue
            counts[(mode, year)] += 1
    if bad_years:
        eprint("ERROR: Found non-integer start_year values:")
        for msg in bad_years[:5]:
            eprint(f"  - {msg}")
        sys.exit(3)
    return counts


def write_summary(counts, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rows = sorted([(m, y, c) for (m, y), c in counts.items()], key=lambda t: (t[0], t[1]))
    with open(out_path, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(["mode", "start_year", "count"])
        for m, y, c in rows:
            writer.writerow([m, y, c])
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Aggregate transport routes by mode and start year")
    parser.add_argument('--config', required=True, help='Path to JSON config file')
    args = parser.parse_args()

    cfg = load_config(args.config)
    data_path = cfg.get('data_path')
    output_dir = cfg.get('output_dir', 'output')
    mapping = cfg.get('fields', {})

    if not data_path:
        eprint("ERROR: data_path is missing in config")
        sys.exit(1)
    if not os.path.exists(data_path):
        eprint(f"ERROR: Data file does not exist: {data_path}")
        sys.exit(1)

    print(f"Reading data from {data_path}")
    print("Validating field mapping and data types...")
    counts = aggregate(data_path, mapping)
    out_path = os.path.join(output_dir, 'summary_by_mode_year.csv')
    n = write_summary(counts, out_path)
    print(f"OK: wrote {out_path} with {n} rows")


if __name__ == '__main__':
    main()
