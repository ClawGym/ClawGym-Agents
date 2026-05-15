import sys
import csv


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_projects.py <projects.csv>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for i, row in enumerate(reader, start=2):  # start=2 to account for header
            val = (row.get('estimated_cost_usd') or '').strip()
            if val == '':
                raise ValueError(f"Invalid estimated_cost_usd at row {i}: empty")
            try:
                cost = float(val)
            except Exception:
                raise ValueError(f"Invalid estimated_cost_usd at row {i}: {val}")
            if cost <= 0:
                raise ValueError(f"Invalid estimated_cost_usd at row {i}: {val}")
            count += 1
    print(f"OK: {count} projects validated")


if __name__ == '__main__':
    main()
