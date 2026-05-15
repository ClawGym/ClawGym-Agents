#!/usr/bin/env python3
"""
Normalize quarterly utility financial CSVs by lowercasing headers and coercing numeric fields.

Usage:
    python3 scripts/normalize_financials.py <input_dir> <output_dir>

- Reads files matching utility_financials_*.csv in <input_dir>
- Writes *_normalized.csv to <output_dir>
- No external dependencies
"""
import sys
import os
import csv
import glob
from typing import List, Dict

NUMERIC_FLOAT_COLS = {"revenue", "opex", "capex", "rate_base", "authorized_roe"}
NUMERIC_INT_COLS = {"year"}


def coerce_row(row: Dict[str, str]) -> Dict[str, object]:
    out = {}
    for k, v in row.items():
        key = k.strip().lower()
        val = v.strip() if isinstance(v, str) else v
        if key in NUMERIC_INT_COLS:
            if val == "" or val is None:
                out[key] = ""
            else:
                try:
                    out[key] = int(val)
                except ValueError:
                    out[key] = int(float(val))
        elif key in NUMERIC_FLOAT_COLS:
            if val == "" or val is None:
                out[key] = ""
            else:
                out[key] = float(val)
        else:
            out[key] = val
    return out


def normalize_file(in_path: str, out_path: str) -> None:
    with open(in_path, newline="", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in)
        # Normalize headers
        fieldnames = [h.strip().lower() for h in reader.fieldnames]
        rows: List[Dict[str, object]] = []
        for raw_row in reader:
            # Remap raw_row to normalized keys
            norm_row = {}
            for h in reader.fieldnames:
                norm_key = h.strip().lower()
                norm_row[norm_key] = raw_row.get(h, "")
            rows.append(coerce_row(norm_row))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        print("Usage: python3 scripts/normalize_financials.py <input_dir> <output_dir>", file=sys.stderr)
        return 2
    in_dir = argv[1]
    out_dir = argv[2]
    if not os.path.isdir(in_dir):
        print(f"Input directory not found: {in_dir}", file=sys.stderr)
        return 2
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(in_dir, "utility_financials_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No matching files found in {in_dir}", file=sys.stderr)
        return 1
    for in_path in files:
        base = os.path.basename(in_path)
        name, _ = os.path.splitext(base)
        out_path = os.path.join(out_dir, f"{name}_normalized.csv")
        normalize_file(in_path, out_path)
        print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
