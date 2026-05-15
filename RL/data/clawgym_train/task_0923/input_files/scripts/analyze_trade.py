import csv

DATA_FILE = 'data/trade_indonesia_neighbors.csv'

# NOTE: This script is a quick prototype. It prints totals but does not write any CSV outputs.
# It also hardcodes the partner and repeats logic for each year/flow combination.

def get_neighborland_rows():
    rows = []
    with open(DATA_FILE, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['partner_country'].lower().strip() == 'neighborland':
                rows.append(row)
    return rows

# Duplicated logic, could be generalized.
def totals_by_sector(rows, year, flow):
    total = 0
    sector_totals = {}
    for row in rows:
        try:
            y = int(row['year'])
            v = int(row['value_usd'])
        except Exception:
            # crude error handling
            continue
        if y == year and row['flow'] == flow:
            total += v
            s = row['product_sector']
            sector_totals[s] = sector_totals.get(s, 0) + v
    return total, sector_totals

# Another custom aggregation that mirrors totals_by_sector (not used elsewhere)
def totals_by_flow(rows, year):
    flows = {}
    for row in rows:
        try:
            y = int(row['year'])
            v = int(row['value_usd'])
        except Exception:
            continue
        if y == year:
            f = row['flow']
            flows[f] = flows.get(f, 0) + v
    return flows

def main():
    rows = get_neighborland_rows()

    total22exp, sec22exp = totals_by_sector(rows, 2022, 'export')
    total22imp, sec22imp = totals_by_sector(rows, 2022, 'import')
    print('2022 export total', total22exp, sec22exp)
    print('2022 import total', total22imp, sec22imp)

    total23exp, sec23exp = totals_by_sector(rows, 2023, 'export')
    total23imp, sec23imp = totals_by_sector(rows, 2023, 'import')
    print('2023 export total', total23exp, sec23exp)
    print('2023 import total', total23imp, sec23imp)

    # Additional print-only summary; not persisted anywhere
    f22 = totals_by_flow(rows, 2022)
    f23 = totals_by_flow(rows, 2023)
    print('2022 flow totals', f22)
    print('2023 flow totals', f23)

if __name__ == '__main__':
    main()
