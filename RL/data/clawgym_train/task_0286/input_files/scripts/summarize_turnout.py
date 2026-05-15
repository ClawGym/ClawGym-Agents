import csv, glob, os, sys

# Intentionally expects columns that don't exist in the provided CSVs.
# This script is included to be run and its failure diagnosed, not fixed.

def main():
    if len(sys.argv) != 3:
        print("Usage: python summarize_turnout.py <data_dir> <output_csv>")
        sys.exit(2)
    data_dir = sys.argv[1]
    out_path = sys.argv[2]
    files = sorted(glob.glob(os.path.join(data_dir, "turnout_*.csv")))
    print(f"Found {len(files)} files under {data_dir}")
    if not files:
        raise FileNotFoundError("No CSV files matching pattern")
    rows = []
    for path in files:
        with open(path, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                year = row.get('year')
                group = row.get('age_group')
                # Intentional mismatch: expects 'eligible' and 'votes' instead of 'registered' and 'voted'.
                eligible = int(row['eligible'])
                votes = int(row['votes'])
                rate = round(votes / eligible, 3)
                rows.append({'year': year, 'age_group': group, 'eligible': eligible, 'votes': votes, 'turnout_rate': rate})
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['year', 'age_group', 'eligible', 'votes', 'turnout_rate'])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")

if __name__ == '__main__':
    main()
