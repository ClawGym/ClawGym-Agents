import sys, csv, json

def main():
    if len(sys.argv) != 3:
        print("Usage: python tools/availability_validator.py <input_csv> <output_json>")
        sys.exit(2)
    in_csv = sys.argv[1]
    out_json = sys.argv[2]
    with open(in_csv, newline='') as f:
        reader = csv.DictReader(f)
        required = {'date', 'city', 'work_hours'}
        if reader.fieldnames is None:
            raise ValueError('No header row found')
        missing = [c for c in required if c not in reader.fieldnames]
        if missing:
            raise ValueError(f"Missing required column: {missing[0]}")
        city_counts = {}
        rows = 0
        for row in reader:
            rows += 1
            c = (row.get('city') or '').strip()
            if not c:
                continue
            city_counts[c] = city_counts.get(c, 0) + 1
    unique_cities = sorted(city_counts.keys())
    with open(out_json, 'w') as out:
        json.dump({
            'rows': rows,
            'unique_cities': unique_cities,
            'city_counts': city_counts
        }, out, indent=2)
    print(f"OK: availability computed for {len(unique_cities)} unique cities and {rows} rows")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
