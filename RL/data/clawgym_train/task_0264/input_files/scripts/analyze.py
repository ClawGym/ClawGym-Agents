#!/usr/bin/env python3
import sys
import os
import json
import csv
from datetime import datetime
from statistics import mean, median


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_pm25(csv_path):
    records = []
    bad_rows = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = datetime.strptime(row['date'], '%Y-%m-%d').date()
                v = float(row['pm25'])
                records.append((d, v))
            except Exception:
                bad_rows += 1
                continue
    print(f"Loaded {len(records)} valid rows from {csv_path} (skipped {bad_rows} malformed rows)")
    return records


def group_by_month(records):
    buckets = {}
    for d, v in records:
        key = (d.year, d.month)
        buckets.setdefault(key, []).append(v)
    return buckets


def group_by_year(records):
    buckets = {}
    for d, v in records:
        key = d.year
        buckets.setdefault(key, []).append(v)
    return buckets


def summarize(values, threshold):
    if not values:
        return {
            'days': 0,
            'mean_pm25': '',
            'median_pm25': '',
            'min_pm25': '',
            'max_pm25': '',
            'days_exceeding_threshold': 0,
        }
    return {
        'days': len(values),
        'mean_pm25': round(mean(values), 3),
        'median_pm25': round(median(values), 3),
        'min_pm25': round(min(values), 3),
        'max_pm25': round(max(values), 3),
        'days_exceeding_threshold': sum(1 for x in values if x > threshold),
    }


def write_monthly(buckets, threshold, out_path):
    fieldnames = [
        'year', 'month', 'days', 'mean_pm25', 'median_pm25', 'min_pm25', 'max_pm25', 'days_exceeding_threshold'
    ]
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for (y, m) in sorted(buckets.keys()):
            stats = summarize(buckets[(y, m)], threshold)
            row = {'year': y, 'month': m}
            row.update(stats)
            w.writerow(row)
    print(f"Wrote monthly summary to {out_path}")


def write_yearly(buckets, threshold, out_path):
    fieldnames = [
        'year', 'days', 'mean_pm25', 'median_pm25', 'min_pm25', 'max_pm25', 'days_exceeding_threshold'
    ]
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for y in sorted(buckets.keys()):
            stats = summarize(buckets[y], threshold)
            row = {'year': y}
            row.update(stats)
            w.writerow(row)
    print(f"Wrote yearly summary to {out_path}")


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 scripts/analyze.py <path_to_config.json>')
        sys.exit(1)

    cfg_path = sys.argv[1]
    cfg = load_config(cfg_path)

    # Expected config keys (intentionally strict):
    input_csv = cfg['input_csv']          # path to input CSV
    output_dir = cfg['output_dir']        # directory to write outputs
    threshold = float(cfg.get('exceedance_threshold', 25.0))

    os.makedirs(output_dir, exist_ok=True)

    records = read_pm25(input_csv)
    if not records:
        print('No valid records found. Exiting.')
        sys.exit(2)

    monthly = group_by_month(records)
    yearly = group_by_year(records)

    monthly_path = os.path.join(output_dir, 'monthly_summary.csv')
    yearly_path = os.path.join(output_dir, 'yearly_summary.csv')

    write_monthly(monthly, threshold, monthly_path)
    write_yearly(yearly, threshold, yearly_path)

    print(f"Processed {len(records)} total readings across {len(monthly)} months and {len(yearly)} years.")
    print(f"Threshold for exceedance: {threshold}")


if __name__ == '__main__':
    main()
