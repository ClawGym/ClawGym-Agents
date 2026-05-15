import os
import csv
import glob

def main():
    base_dir = os.path.join('input', 'data')
    files = sorted(glob.glob(os.path.join(base_dir, '*.csv')))
    wins = 0
    losses = 0
    ties = 0
    points_for = 0
    points_against = 0
    rows = 0
    for fp in files:
        print(f"Processing: {fp}")
        with open(fp, newline='') as f:
            reader = csv.DictReader(f, delimiter=',')
            for row in reader:
                rows += 1
                points_for += int(row['OLSM_Score'])
                points_against += int(row['Opp_Score'])  # Expected to fail if header/delimiter differs
                r = row['Result']
                if r == 'W':
                    wins += 1
                elif r == 'L':
                    losses += 1
                elif r == 'T':
                    ties += 1
    print(f"Processed {rows} rows across {len(files)} files.")
    print(f"Record: {wins}-{losses}-{ties}")
    print(f"Points For: {points_for} | Points Against: {points_against}")

if __name__ == '__main__':
    main()
