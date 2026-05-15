#!/usr/bin/env python3
import csv
import re
import sys

# Simple validator: checks date format is YYYY-MM-DD. Prints warnings to stderr for invalid rows.
# Usage: python tools/validate_events.py input/events.csv

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("ERROR: expected exactly one CSV path.\n")
        sys.exit(1)
    path = sys.argv[1]
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            invalid_count = 0
            row_index = 1  # header is line 1
            for row_index, row in enumerate(reader, start=2):  # data lines start at 2
                event_id = row.get('event_id', '').strip()
                date_str = row.get('date', '').strip()
                if not date_re.match(date_str):
                    sys.stderr.write(f"WARNING: invalid date format at row {row_index} (event_id={event_id}): '{date_str}'\n")
                    invalid_count += 1
        sys.stdout.write("Validation complete.\n")
        # Exit 0 even with warnings to allow downstream processing.
        return 0
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: file not found: {path}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"ERROR: unexpected exception: {e}\n")
        return 3

if __name__ == '__main__':
    sys.exit(main())
