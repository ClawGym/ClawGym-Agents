"""
Quick and dirty order total calculator for VIC shipping (pre-move).
Assumes 8% surcharge for VIC regardless of the customer's state.
TODO: Make state-aware after relocation.
"""
import csv
import json
import os

# Hardcoded assumptions for VIC
SURCHARGE = 0.08  # 8% surcharge
PROCESSING_FEE = 1.50


def calc_total(subtotal: float) -> float:
    """Compute total by applying a flat surcharge and processing fee.
    This intentionally ignores per-state differences.
    """
    return round(subtotal + subtotal * SURCHARGE + PROCESSING_FEE, 2)


def main() -> None:
    # Reads config only for output directory; ignores other values for now.
    with open('config/app.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    out_dir = cfg.get('output_dir', 'output')
    os.makedirs(out_dir, exist_ok=True)

    in_path = 'data/orders.csv'
    out_path = os.path.join(out_dir, 'totals_old.csv')

    with open(in_path, 'r', encoding='utf-8', newline='') as infile, \
         open(out_path, 'w', encoding='utf-8', newline='') as outfile:
        rdr = csv.DictReader(infile)
        fieldnames = ['order_id', 'customer_state', 'subtotal', 'total']
        w = csv.DictWriter(outfile, fieldnames=fieldnames)
        w.writeheader()
        for row in rdr:
            try:
                subtotal = float(row.get('subtotal', '0'))
            except ValueError:
                continue
            total = calc_total(subtotal)
            w.writerow({
                'order_id': row.get('order_id', ''),
                'customer_state': row.get('customer_state', 'VIC'),
                'subtotal': f"{subtotal:.2f}",
                'total': f"{total:.2f}"
            })


if __name__ == '__main__':
    main()
