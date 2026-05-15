#!/usr/bin/env python3
import csv
import json
import os
import sys
from datetime import datetime

INPUT_PATH = os.path.join('input', 'events.csv')
OUTPUT_PATH = os.path.join('output', 'events_normalized.json')

ALLOWED_LEVELS = {"High", "Medium", "Low"}
DATE_FMT = "%Y-%m-%d"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_date(s, rownum, field):
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except Exception as ex:
        eprint(f"ERROR: invalid date format for {field} on row {rownum}: '{s}' (expected {DATE_FMT})")
        raise


def normalize_name(name):
    return name.strip()


def main():
    if not os.path.exists(INPUT_PATH):
        eprint(f"ERROR: missing input file: {INPUT_PATH}")
        sys.exit(1)
    records = []
    with open(INPUT_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        required = {"name", "tradition", "start_date", "end_date", "observance_level", "notes"}
        if not required.issubset(reader.fieldnames or []):
            eprint(f"ERROR: CSV missing required columns. Found: {reader.fieldnames}")
            sys.exit(1)
        for idx, row in enumerate(reader, start=2):  # header is row 1
            name = normalize_name(row["name"] or "")
            tradition = (row["tradition"] or "").strip()
            start_raw = row["start_date"] or ""
            end_raw = row["end_date"] or ""
            level = (row["observance_level"] or "").strip()
            notes = (row["notes"] or "").strip()
            # Validate level
            if level not in ALLOWED_LEVELS:
                eprint(f"ERROR: invalid observance_level on row {idx}: '{level}' (allowed: {sorted(ALLOWED_LEVELS)})")
                sys.exit(1)
            # Parse dates
            try:
                start_dt = parse_date(start_raw, idx, 'start_date')
                end_dt = parse_date(end_raw, idx, 'end_date')
            except Exception:
                sys.exit(1)
            if end_dt < start_dt:
                eprint(f"ERROR: end_date before start_date on row {idx}: {end_raw} < {start_raw}")
                sys.exit(1)
            days = (end_dt - start_dt).days + 1
            rec = {
                "name": name,
                "tradition": tradition,
                "start_date": start_dt.strftime(DATE_FMT),
                "end_date": end_dt.strftime(DATE_FMT),
                "observance_level": level,
                "days": days,
                "notes": notes
            }
            records.append(rec)
    # Deduplicate by (name, start_date, end_date)
    seen = set()
    unique = []
    for r in records:
        key = (r["name"].lower(), r["start_date"], r["end_date"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as out:
        json.dump(unique, out, indent=2, ensure_ascii=False)
    print(f"Wrote {len(unique)} normalized records to {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
