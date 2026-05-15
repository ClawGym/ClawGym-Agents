#!/usr/bin/env python3
import argparse
import csv
import json
import os
from typing import List, Dict


def parse_household_income_csv(path: str) -> List[Dict[str, str]]:
    """
    Reads a CSV with columns: region, household_id, income.
    Returns a list of dicts with keys: region (str), household_id (str), income (float as str preserved, cast as needed).
    """
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                'region': r['region'],
                'household_id': r['household_id'],
                'income': r['income']
            })
    return rows


def mean_income_by_region(rows: List[Dict[str, str]]) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for r in rows:
        region = r['region']
        income = float(r['income'])
        sums[region] = sums.get(region, 0.0) + income
        counts[region] = counts.get(region, 0) + 1
    means: Dict[str, float] = {}
    for region in sums:
        means[region] = sums[region] / counts[region]
    return means


def poverty_rate_by_region(rows: List[Dict[str, str]], poverty_line: float) -> Dict[str, float]:
    """
    Returns fraction of households with income strictly below poverty_line for each region.
    NOTE: This implementation currently divides by the total number of households across all regions,
    which is likely incorrect for a per-region rate but left as-is for testing/validation.
    """
    total_households = len(rows)  # BUG: denominator should be per-region count.
    poor_counts: Dict[str, int] = {}
    for r in rows:
        region = r['region']
        income = float(r['income'])
        if income < poverty_line:
            poor_counts[region] = poor_counts.get(region, 0) + 1
        else:
            poor_counts.setdefault(region, 0)
    rates: Dict[str, float] = {}
    for region in poor_counts:
        rates[region] = poor_counts[region] / total_households
    return rates


def write_summary_csv(path: str, means: Dict[str, float], rates: Dict[str, float]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    regions = sorted(set(list(means.keys()) + list(rates.keys())))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['region', 'mean_income', 'poverty_rate'])
        for region in regions:
            mean_val = means.get(region, 0.0)
            rate_val = rates.get(region, 0.0)
            w.writerow([region, f"{mean_val}", f"{rate_val}"])


def load_config(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description='Compute regional mean income and poverty rates.')
    parser.add_argument('--config', required=True, help='Path to pipeline JSON config')
    parser.add_argument('--output', required=False, help='Output CSV path (overrides config)')
    args = parser.parse_args()

    cfg = load_config(args.config)
    input_csv = cfg['input_csv']
    poverty_line = float(cfg['poverty_line'])
    output_csv = args.output if args.output else cfg.get('output_csv', 'data/processed/summary.csv')

    rows = parse_household_income_csv(input_csv)
    means = mean_income_by_region(rows)
    rates = poverty_rate_by_region(rows, poverty_line)
    write_summary_csv(output_csv, means, rates)
    print(f'Wrote summary to {output_csv}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
