#!/usr/bin/env python3
import csv
import sys

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python validate_critiques.py <csv_path>\n")
        sys.exit(2)
    path = sys.argv[1]
    errors = 0
    rows_checked = 0
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                sys.stderr.write("Empty file.\n")
                sys.exit(1)
            expected_cols = 7
            if len(header) != expected_cols:
                sys.stderr.write(f"HEADER: expected {expected_cols} columns, got {len(header)}\n")
            for i, row in enumerate(reader, start=2):
                rows_checked += 1
                if len(row) != expected_cols:
                    sys.stderr.write(f"ROW {i}: expected {expected_cols} columns, got {len(row)}\n")
                    errors += 1
                    continue
                def parse_score(val, label):
                    try:
                        v = float(val)
                    except Exception:
                        sys.stderr.write(f"ROW {i}: non-numeric {label} '{val}'\n")
                        return None
                    if not (1 <= v <= 5):
                        sys.stderr.write(f"ROW {i}: {label} out of range (1-5): {v}\n")
                        return None
                    return v
                fi = parse_score(row[4], "faith_integration_score")
                ae = parse_score(row[5], "aesthetic_score")
                if fi is None or ae is None:
                    errors += 1
            if errors == 0:
                sys.stdout.write(f"Validation passed: {rows_checked} rows checked, 0 errors\n")
                sys.exit(0)
            else:
                sys.stderr.write(f"Found {errors} invalid row(s).\n")
                sys.exit(1)
    except FileNotFoundError:
        sys.stderr.write(f"File not found: {path}\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
