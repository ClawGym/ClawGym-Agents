import sys
import csv
import json

def main():
    if len(sys.argv) != 4:
        print("Usage: python tools/validate_report.py <input_csv> <thresholds_json> <output_json>")
        sys.exit(1)
    input_csv, thresholds_json, output_json = sys.argv[1:4]

    with open(thresholds_json, 'r', encoding='utf-8') as f:
        thresholds = json.load(f)
    max_c = float(thresholds['produce']['max_celsius'])

    timestamps = []
    sensor_id = None
    temps = []
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row['timestamp']
            timestamps.append(ts)
            if sensor_id is None:
                sensor_id = row.get('sensor_id')
            temps.append(float(row['celsius']))

    total = len(temps)
    max_obs = max(temps) if temps else None
    violations = sum(1 for t in temps if t > max_c)
    window_start = min(timestamps) if timestamps else None
    window_end = max(timestamps) if timestamps else None

    report = {
        'sensor_id': sensor_id,
        'threshold_celsius': max_c,
        'max_observed_celsius': max_obs,
        'total_readings': total,
        'violations': violations,
        'window_start': window_start,
        'window_end': window_end
    }

    with open(output_json, 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=2)

if __name__ == '__main__':
    main()
