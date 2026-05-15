#!/usr/bin/env python3
import sys
import csv
import argparse
from collections import defaultdict

def read_schedule(path):
    schedule = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        expected = ['date', 'start_time', 'theme', 'venue', 'capacity']
        if reader.fieldnames != expected:
            print(f"ERROR: schedule header mismatch: {reader.fieldnames} != {expected}", file=sys.stderr)
            return None
        for row in reader:
            date = row['date'].strip()
            cap = row['capacity'].strip()
            try:
                capacity = int(cap)
            except ValueError:
                print(f"ERROR: invalid capacity for {date}: {cap}", file=sys.stderr)
                continue
            schedule[date] = capacity
    return schedule

def read_attendance(path):
    counts = defaultdict(int)
    unique = set()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row['date'].strip()
            name = row['name'].strip()
            if not date or not name:
                print(f"ERROR: blank field in attendance row: {row}", file=sys.stderr)
                continue
            counts[date] += 1
            unique.add(name)
    return counts, unique

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--attendance', required=True)
    ap.add_argument('--schedule', required=True)
    args = ap.parse_args()

    errors = False
    schedule = read_schedule(args.schedule)
    if schedule is None:
        sys.exit(2)
    counts, unique = read_attendance(args.attendance)

    dates = sorted(counts.keys())
    total = sum(counts[d] for d in dates)
    num_dates = len(dates)
    avg = (total / num_dates) if num_dates else 0.0

    # Summary to stdout
    print(f"SUMMARY DATES {num_dates} UNIQUE {len(unique)} AVG {avg:.2f}")

    for d in dates:
        cap = schedule.get(d)
        if cap is None:
            print(f"ERROR {d} not in schedule", file=sys.stderr)
            print(f"DATE {d} COUNT {counts[d]} CAPACITY N/A")
            errors = True
        else:
            print(f"DATE {d} COUNT {counts[d]} CAPACITY {cap}")
            if counts[d] > cap:
                print(f"WARNING {d} attendees {counts[d]} exceed capacity {cap}", file=sys.stderr)

    sys.exit(1 if errors else 0)
