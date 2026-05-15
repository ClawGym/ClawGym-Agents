# NOTE: This is the original quick-and-dirty script for skin reaction analysis.
# Issues to address in refactor:
# - Hardcoded thresholds and no config support
# - No filtering by date or environment
# - Repetitive loops and limited testability
# - Output format not structured for downstream use

import csv
import os

THRESH_RED = 4.0
THRESH_ITCH = 3.0
THRESH_BREAK = 0.8

# quick script, not production quality

def main():
    path = 'input/product_logs.csv'
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # aggregate
    counts = {}
    red_sum = {}
    itch_sum = {}
    brk = {}

    for row in rows:
        p = row['product_name']
        counts[p] = counts.get(p, 0) + 1
        try:
            red = float(row['redness_score'])
        except Exception:
            red = 0.0
        try:
            itch = float(row['itch_score'])
        except Exception:
            itch = 0.0
        red_sum[p] = red_sum.get(p, 0.0) + red
        itch_sum[p] = itch_sum.get(p, 0.0) + itch
        if row.get('breakout', '0') == '1':
            brk[p] = brk.get(p, 0) + 1
        else:
            brk[p] = brk.get(p, 0)

    lines = []
    for p in counts:
        uses = counts[p]
        avg_r = red_sum[p] / uses if uses else 0.0
        avg_i = itch_sum[p] / uses if uses else 0.0
        rate = (brk.get(p, 0) / uses) if uses else 0.0
        suspect = False
        if avg_r >= THRESH_RED:
            suspect = True
        if avg_i >= THRESH_ITCH:
            suspect = True
        if rate >= THRESH_BREAK:
            suspect = True
        lines.append(f"{p}: uses={uses} avg_red={round(avg_r, 3)} avg_itch={round(avg_i, 3)} breakout_rate={round(rate, 3)} suspect={suspect}")

    os.makedirs('reports', exist_ok=True)
    with open('reports/old_report.txt', 'w') as out:
        out.write('\n'.join(lines))

    # also print
    for ln in lines:
        print(ln)

if __name__ == '__main__':
    main()
