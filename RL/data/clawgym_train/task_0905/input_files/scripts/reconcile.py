import argparse
import json
import os
import csv
from decimal import Decimal, ROUND_HALF_UP


def read_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Studio revenue reconciliation")
    parser.add_argument('--config', required=True, help='Path to JSON config')
    args = parser.parse_args()

    cfg = read_config(args.config)
    # Expect required keys; KeyError here should fail loudly if config is wrong
    input_dir = cfg['input_dir']
    output_dir = cfg['output_dir']

    tx_path = os.path.join(input_dir, 'transactions.csv')
    if not os.path.exists(tx_path):
        raise FileNotFoundError(f"transactions.csv not found at {tx_path}")

    os.makedirs(output_dir, exist_ok=True)

    totals = {}
    count = 0
    with open(tx_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            currency = row['currency'].strip()
            amt = Decimal(row['amount']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            totals[currency] = totals.get(currency, Decimal('0.00')) + amt
            count += 1

    out_path = os.path.join(output_dir, 'revenue_summary.csv')
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['currency', 'total_amount'])
        for curr in sorted(totals.keys()):
            writer.writerow([curr, f"{totals[curr]:.2f}"])

    print(f"Processed {count} transactions from {tx_path}")
    print(f"Wrote summary to {out_path}")


if __name__ == '__main__':
    main()
