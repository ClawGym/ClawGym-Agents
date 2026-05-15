#!/usr/bin/env python3
import sys
import csv
import json
from datetime import datetime

USAGE = (
    "Usage: python input/scripts/summarize_finances.py "
    "<transactions_csv> <category_map_json> <output_csv>\n"
)

def load_category_map(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    mapping = {}
    for t, cfg in data.items():
        pol = cfg.get('polarity')
        if pol not in ('income', 'expense'):
            raise ValueError(f"Invalid polarity for type '{t}': {pol}")
        mapping[t] = pol
    return mapping

def main(argv):
    if len(argv) != 4:
        sys.stderr.write(USAGE)
        return 2
    tx_path, map_path, out_path = argv[1], argv[2], argv[3]

    try:
        mapping = load_category_map(map_path)
    except Exception as e:
        sys.stderr.write(f"ERROR: failed to load category map '{map_path}': {e}\n")
        return 1

    sums = {}  # year -> dict
    unknowns = []  # list of (year, date, ttype, amount, desc)
    total_rows = 0

    try:
        with open(tx_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                date_str = row.get('date', '').strip()
                ttype = row.get('type', '').strip()
                desc = row.get('description', '').strip()
                amt_str = row.get('amount', '').strip()
                try:
                    year = datetime.strptime(date_str, '%Y-%m-%d').year
                except Exception:
                    sys.stderr.write(f"WARNING: skipping row with invalid date '{date_str}': {row}\n")
                    continue
                try:
                    amt = float(amt_str)
                except Exception:
                    sys.stderr.write(f"WARNING: skipping row with invalid amount '{amt_str}' on {date_str}: {row}\n")
                    continue

                if year not in sums:
                    sums[year] = {
                        'income_total': 0.0,
                        'expense_total': 0.0,
                        'dues_total': 0.0,
                        'strike_support_total': 0.0,
                    }
                if ttype not in mapping:
                    sys.stderr.write(
                        f"WARNING: unknown type '{ttype}' in {date_str} (amount {amt:.2f}) — excluded from totals.\n"
                    )
                    unknowns.append((year, date_str, ttype, amt, desc))
                    continue

                pol = mapping[ttype]
                if pol == 'income':
                    sums[year]['income_total'] += amt
                elif pol == 'expense':
                    sums[year]['expense_total'] += amt
                if ttype == 'dues':
                    sums[year]['dues_total'] += amt
                if ttype == 'strike_support':
                    sums[year]['strike_support_total'] += amt
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: transactions file not found: {tx_path}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"ERROR: failed while reading transactions: {e}\n")
        return 1

    years = sorted(sums.keys())
    try:
        with open(out_path, 'w', encoding='utf-8', newline='') as out:
            writer = csv.writer(out)
            writer.writerow([
                'year', 'income_total', 'expense_total', 'net',
                'dues_total', 'strike_support_total', 'percent_dues_to_strike_support'
            ])
            for y in years:
                inc = sums[y]['income_total']
                exp = sums[y]['expense_total']
                net = inc - exp
                dues = sums[y]['dues_total']
                strike = sums[y]['strike_support_total']
                pct = '' if dues == 0 else round((strike / dues) * 100.0, 1)
                writer.writerow([y, f"{inc:.2f}", f"{exp:.2f}", f"{net:.2f}", f"{dues:.2f}", f"{strike:.2f}", pct])
    except Exception as e:
        sys.stderr.write(f"ERROR: failed to write output CSV '{out_path}': {e}\n")
        return 1

    sys.stdout.write(f"Processed {total_rows} transaction rows across {len(years)} years.\n")
    sys.stdout.write(f"Wrote summary to {out_path}.\n")

    if unknowns:
        # Summarize unknown types by name
        counts = {}
        for (_, _, ttype, _, _) in unknowns:
            counts[ttype] = counts.get(ttype, 0) + 1
        details = ", ".join([f"{k}={v}" for k, v in sorted(counts.items())])
        sys.stderr.write(
            f"SUMMARY: found {len(unknowns)} transactions with unknown types ({details}). These were excluded from totals.\n"
        )

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
