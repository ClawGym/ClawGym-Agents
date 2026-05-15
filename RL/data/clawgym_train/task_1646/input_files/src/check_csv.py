import sys
import os
import csv
from typing import List

# Local import
import foss_licenses


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("Usage: python src/check_csv.py <deps.csv>", file=sys.stderr)
        return 2
    csv_path = argv[1]
    if not os.path.exists(csv_path):
        print(f"Input CSV not found: {csv_path}", file=sys.stderr)
        return 2

    approved_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'osi_approved.txt'))
    approved = foss_licenses.load_approved(approved_path)

    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get('name') or '').strip()
            license_name = (row.get('license') or '').strip()
            is_foss = foss_licenses.is_foss_license(license_name, approved)
            tag = 'FOSS' if is_foss else 'NOT_FOSS'
            print(f"{tag},{name},{license_name}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
