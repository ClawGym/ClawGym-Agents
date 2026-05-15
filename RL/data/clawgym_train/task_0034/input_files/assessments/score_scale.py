#!/usr/bin/env python3
"""
Score CRSS-5 from a responses CSV.

Usage:
  python assessments/score_scale.py INPUT_CSV --out OUTPUT_CSV

The input CSV must include columns: id, Q1, Q2, Q3, Q4, Q5
The output CSV will include columns: id, total_score
"""
import argparse
import csv
import os

def parse_args():
    ap = argparse.ArgumentParser(description="Score CRSS-5 from responses CSV. Emits CSV with id,total_score.")
    ap.add_argument("input_csv", help="Path to input responses CSV.")
    ap.add_argument("--out", "-o", required=True, help="Path to write output CSV with columns id,total_score.")
    return ap.parse_args()


def score_row(row):
    items = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    # Implementation choice: treat Q3 as reverse-coded on a 0-3 scale.
    # (This is intentionally simple to keep this script focused on IO.)
    rev = set(["Q3"])  # reverse-coded items
    total = 0
    for it in items:
        try:
            val = int(row[it])
        except (KeyError, ValueError):
            val = 0
        if it in rev:
            val = 3 - val
        total += val
    return total


def main():
    args = parse_args()
    with open(args.input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["id", "total_score"])
        for row in rows:
            rid = row.get("id", "")
            total = score_row(row)
            writer.writerow([rid, total])

if __name__ == "__main__":
    main()
