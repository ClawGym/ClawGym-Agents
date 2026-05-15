#!/usr/bin/env python3
import csv
import sys


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "input/gear_inventory.csv"
    errors = 0
    warnings = 0
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_id = (row.get('item_id') or '').strip()
                description = (row.get('description') or '').strip()
                muzzleloader = (row.get('muzzleloader') or '').strip().lower()
                blank_powder = (row.get('blank_powder') or '').strip().lower()
                safety_cert_path = (row.get('safety_cert_path') or '').strip()

                if muzzleloader == 'yes' and blank_powder == 'yes' and safety_cert_path == '':
                    errors += 1
                    print(f"ERROR [CERT_MISSING] item_id={item_id} - muzzleloader with blank powder requires safety_cert_path", file=sys.stderr)

                if description == '':
                    warnings += 1
                    print(f"WARNING [DESC_MISSING] item_id={item_id} - description is empty", file=sys.stderr)

                if blank_powder == 'yes' and muzzleloader == 'no':
                    warnings += 1
                    print(f"WARNING [BP_NO_FIREARM] item_id={item_id} - blank_powder is 'yes' but muzzleloader is 'no'; verify classification and storage", file=sys.stderr)
    except FileNotFoundError:
        print(f"FATAL [FILE_NOT_FOUND] path={path} - CSV file not found", file=sys.stderr)
        sys.exit(2)

    print(f"SUMMARY errors={errors} warnings={warnings}")


if __name__ == "__main__":
    main()
