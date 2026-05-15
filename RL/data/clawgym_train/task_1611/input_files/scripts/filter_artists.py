#!/usr/bin/env python3
import argparse
import json
import csv
import sys
import os

def main():
    parser = argparse.ArgumentParser(description="Filter artists by country and influence keywords.")
    parser.add_argument("--config", required=True, help="Path to JSON config.")
    parser.add_argument("--input", required=True, help="Path to artists JSONL.")
    parser.add_argument("--out-json", required=True, help="Path to write selected artists JSON.")
    parser.add_argument("--out-csv", required=True, help="Path to write selected artists CSV.")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as cf:
        cfg = json.load(cf)
    # Intentionally strict key access to surface misconfigurations clearly
    target_country = cfg["target_country"]
    keywords = cfg["keywords"]

    total = 0
    selected = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            total += 1
            if rec.get("country") != target_country:
                continue
            influences = rec.get("influences", []) or []
            text = " ".join(influences).lower()
            matched = [kw for kw in keywords if kw.lower() in text]
            if matched:
                out = {
                    "name": rec.get("name"),
                    "email": rec.get("email"),
                    "city": rec.get("city"),
                    "country": rec.get("country"),
                    "medium": rec.get("medium"),
                    "influences": influences,
                    "match_reason": ", ".join(matched)
                }
                selected.append(out)

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as jf:
        json.dump(selected, jf, ensure_ascii=False, indent=2)

    with open(args.out_csv, "w", encoding="utf-8", newline="") as cf:
        fieldnames = ["name", "email", "city", "country", "medium", "influences", "match_reason"]
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        for row in selected:
            r = row.copy()
            r["influences"] = "|".join(r.get("influences", []))
            writer.writerow(r)

    print(f"Selected {len(selected)} of {total} artists matching country '{target_country}' and keywords {keywords}")
    print(f"Wrote JSON to {args.out_json}")
    print(f"Wrote CSV to {args.out_csv}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Echo a concise error summary to stderr to aid debugging/logging
        print(f"ERROR: {e.__class__.__name__}: {e}", file=sys.stderr)
        raise
