import sys
import os
import csv
import json

# Usage: python scripts/aggregate.py [input_tsv] [output_json]
# Defaults: input/entrepreneurship.tsv -> data/summary.json

def read_tsv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for r in reader:
            rows.append({
                'region': r['region'],
                'population': int(r['population']),
                'new_businesses': int(r['new_businesses'])
            })
    return rows

def compute_summary(rows):
    # Compute per-1000 rates per region, rounded to 2 decimals
    per_region = []
    total_pop = 0
    total_new = 0
    for r in rows:
        rate = (r['new_businesses'] / r['population']) * 1000.0
        rate_rounded = round(rate, 2)
        per_region.append({'region': r['region'], 'rate_per_1000': rate_rounded})
        total_pop += r['population']
        total_new += r['new_businesses']
    overall_rate = (total_new / total_pop) * 1000.0
    overall_rounded = round(overall_rate, 2)
    # Sort regions by rate desc and take top 3
    per_region_sorted = sorted(per_region, key=lambda x: x['rate_per_1000'], reverse=True)[:3]
    return {
        'source_file': 'input/entrepreneurship.tsv',
        'year': 2023,
        'overall_avg_new_business_rate_per_1000': overall_rounded,
        'top_regions_by_rate': per_region_sorted
    }

def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else 'input/entrepreneurship.tsv'
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'data/summary.json'
    rows = read_tsv(in_path)
    summary = compute_summary(rows)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote summary to {out_path}")

if __name__ == '__main__':
    main()
