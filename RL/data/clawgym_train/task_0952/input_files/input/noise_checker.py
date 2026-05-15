#!/usr/bin/env python3
import sys
import csv
import os

def main():
    if len(sys.argv) < 2:
        print("ERROR: no CSV path provided", file=sys.stderr)
        return 2
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    warnings = 0
    errors = 0
    total_rows = 0
    valid_rows = 0
    print(f"INFO: Starting analysis for {path}")
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        expected = {'timestamp', 'room', 'decibel'}
        if set(reader.fieldnames) != expected:
            print(f"ERROR: unexpected headers {reader.fieldnames}, expected {sorted(expected)}", file=sys.stderr)
            return 2
        for idx, row in enumerate(reader, start=2):  # start=2 to account for header as row 1
            total_rows += 1
            raw = (row.get('decibel') or '').strip()
            try:
                value = float(raw)
            except Exception:
                errors += 1
                print(f"ERROR: non-numeric decibel at row {idx}: {raw}", file=sys.stderr)
                continue
            if value < 0:
                errors += 1
                print(f"ERROR: negative decibel at row {idx}: {value}", file=sys.stderr)
                continue
            valid_rows += 1
            if value >= 95.0:
                warnings += 1
                print(f"WARNING: very loud spike at t={row.get('timestamp')} in {row.get('room')}: {value} dB")
    print(f"INFO: Processed {total_rows} rows (valid {valid_rows})")
    print(f"INFO: warnings={warnings} errors={errors}")
    print("INFO: Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
