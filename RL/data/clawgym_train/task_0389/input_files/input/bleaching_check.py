import argparse
import csv
import sys
from datetime import datetime, timedelta
from collections import defaultdict

def parse_csv(path):
    temps = {}
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = datetime.strptime(row['date'], '%Y-%m-%d').date()
            t = float(row['temp_c'])
            temps[d] = t
    return temps

def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)

def week_key(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

def main():
    ap = argparse.ArgumentParser(description='Simple bleaching risk checker')
    ap.add_argument('--csv', required=True, help='Path to reef_temp.csv')
    args = ap.parse_args()

    temps = parse_csv(args.csv)
    if not temps:
        print('ERROR: no data', file=sys.stderr)
        sys.exit(1)

    start = min(temps.keys())
    end = max(temps.keys())

    expected_by_week = defaultdict(set)
    present_by_week = defaultdict(list)

    # Build expected dates per ISO week across the full span
    for d in daterange(start, end):
        expected_by_week[week_key(d)].add(d)

    # Group present dates by week
    for d, t in sorted(temps.items()):
        present_by_week[week_key(d)].append((d, t))

    # Emit warnings for missing days per week
    for wk, exp_days in sorted(expected_by_week.items()):
        present_days = {d for d, _ in present_by_week.get(wk, [])}
        missing = len(exp_days - present_days)
        if missing > 0:
            print(f"WARNING: Missing {missing} day(s) in {wk}", file=sys.stderr)

    # Compute weekly mean and emit risk levels
    for wk in sorted(present_by_week.keys()):
        vals = [t for _, t in present_by_week[wk]]
        if not vals:
            continue
        mean_t = sum(vals) / len(vals)
        if mean_t >= 30.5:
            level = 'HIGH'
            print(f"WARNING: Potential bleaching conditions in {wk} (mean >= 30.5C)", file=sys.stderr)
        elif mean_t >= 30.0:
            level = 'MODERATE'
        else:
            level = 'LOW'
        print(f"RISK[{wk}]={level} (mean={mean_t:.2f}C); days={len(vals)}")

if __name__ == '__main__':
    main()
