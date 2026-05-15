#!/usr/bin/env python3
import sys
import csv

ALLOWED_STATES = {"CA", "NY", "TX", "WA"}

USAGE = "Usage: python tools/nexus_cli.py <sales_csv_path>"

def main():
    if len(sys.argv) != 2:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            errors = 0
            warnings = 0
            info = 0
            processed = 0
            for row in reader:
                processed += 1
                state = (row.get("state") or "").strip()
                order_id = (row.get("order_id") or "").strip()
                zip_code = (row.get("customer_zip") or "").strip()
                taxable_raw = (row.get("taxable_amount") or "0").strip()
                try:
                    taxable = float(taxable_raw)
                except ValueError:
                    taxable = 0.0
                if state not in ALLOWED_STATES:
                    print(f"ERROR: Unknown state code '{state}' on order_id {order_id}", file=sys.stderr)
                    errors += 1
                    continue
                if zip_code == "":
                    print(f"WARNING: Missing ZIP on order_id {order_id} (state {state})")
                    warnings += 1
                if taxable == 0:
                    print(f"INFO: Non-taxable order order_id {order_id} (state {state})")
                    info += 1
            print(f"SUMMARY: processed {processed} rows; errors {errors}; warnings {warnings}; info {info}")
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected exception: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
