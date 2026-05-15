import sys
import csv
import json

# Usage: python tests/validate_summary.py [summary_json]
# Defaults to data/summary.json

def read_tsv(path):
    rows = []
    with open('input/entrepreneurship.tsv', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for r in reader:
            rows.append({
                'region': r['region'],
                'population': int(r['population']),
                'new_businesses': int(r['new_businesses'])
            })
    return rows

def compute_expected(rows):
    total_pop = sum(r['population'] for r in rows)
    total_new = sum(r['new_businesses'] for r in rows)
    overall = round((total_new / total_pop) * 1000.0, 2)
    per_region = []
    for r in rows:
        rate = round((r['new_businesses'] / r['population']) * 1000.0, 2)
        per_region.append({'region': r['region'], 'rate_per_1000': rate})
    top3 = sorted(per_region, key=lambda x: x['rate_per_1000'], reverse=True)[:3]
    return overall, top3

def approx_equal(a, b):
    return round(float(a), 2) == round(float(b), 2)

def main():
    summary_path = sys.argv[1] if len(sys.argv) > 1 else 'data/summary.json'
    with open(summary_path) as f:
        summary = json.load(f)
    rows = read_tsv('input/entrepreneurship.tsv')
    exp_overall, exp_top3 = compute_expected(rows)
    ok = True
    if 'overall_avg_new_business_rate_per_1000' not in summary:
        print('Missing overall_avg_new_business_rate_per_1000')
        ok = False
    else:
        if not approx_equal(summary['overall_avg_new_business_rate_per_1000'], exp_overall):
            print(f"Overall mismatch: got {summary['overall_avg_new_business_rate_per_1000']}, expected {exp_overall}")
            ok = False
    if 'top_regions_by_rate' not in summary or not isinstance(summary['top_regions_by_rate'], list) or len(summary['top_regions_by_rate']) != 3:
        print('top_regions_by_rate missing or wrong length')
        ok = False
    else:
        got = summary['top_regions_by_rate']
        for (g, e) in zip(got, exp_top3):
            if g['region'] != e['region'] or not approx_equal(g['rate_per_1000'], e['rate_per_1000']):
                print(f"Top region mismatch: got {g}, expected {e}")
                ok = False
                break
    if ok:
        print('OK')
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
