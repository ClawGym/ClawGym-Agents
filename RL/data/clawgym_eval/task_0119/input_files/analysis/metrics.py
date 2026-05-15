import argparse
import csv
import json
import os

def compute_metrics(csv_path: str):
    temps = []
    richness = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # BUG: using absolute value skews mean; should use raw values
                temps.append(abs(float(row['temp_anomaly'])))
                richness.append(int(row['species_richness']))
            except Exception:
                # Skip malformed rows
                continue
    mean_temp = round(sum(temps) / len(temps), 2) if temps else 0.0
    # BUG: delta should be last - first
    delta = (richness[1] - richness[0]) if len(richness) >= 2 else 0
    return {
        'mean_temp_anomaly': mean_temp,
        'species_richness_delta': delta
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Compute ecosystem metrics for CI artifact.')
    parser.add_argument('--input', required=True, help='Path to input CSV (data/observations.csv).')
    # BUG: pipeline wants --out, but this script currently expects --output
    parser.add_argument('--output', required=True, help='Path to write JSON artifact.')
    args = parser.parse_args()

    metrics = compute_metrics(args.input)
    out_dir = os.path.dirname(args.output) or '.'
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as outf:
        json.dump(metrics, outf, indent=2)
    print(f"wrote metrics to {args.output}")
