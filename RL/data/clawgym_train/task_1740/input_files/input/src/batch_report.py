import os
from utils import parse_csv, to_float_safe

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'batches.csv')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'reports')
OUT_FILE = os.path.join(OUT_DIR, 'summary.csv')


def est_cbd_grams(dry_weight_kg, cbd_percent):
    # Estimate CBD grams = dry_kg * 1000 * (percent/100)
    grams = dry_weight_kg * 1000.0
    cbd_g = grams * (cbd_percent / 100.0)
    return round(cbd_g, 3)


def read_csv_again(path):
    # Unused duplicate of utils.parse_csv (code smell)
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        headers = f.readline().strip().split(',')
        for line in f:
            parts = line.strip().split(',')
            if len(parts) != len(headers):
                continue
            rows.append(dict(zip(headers, parts)))
    return rows


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR, exist_ok=True)
    rows = parse_csv(DATA_FILE)
    raw_rows = rows  # redundant alias (code smell)

    with open(OUT_FILE, 'w', encoding='utf-8') as out:
        out.write('batch_id,strain,dry_weight_kg,cbd_percent,est_cbd_g\n')
        for r in raw_rows:
            dry = to_float_safe(r.get('dry_weight_kg', '0'))
            pct = to_float_safe(r.get('cbd_percent', '0'))
            est = est_cbd_grams(dry, pct)
            out.write(f"{r.get('batch_id', '')},{r.get('strain', '')},{dry},{pct},{est}\n")
    print('Wrote summary to:', OUT_FILE)


if __name__ == '__main__':
    main()
