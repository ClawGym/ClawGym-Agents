import sys
import csv

EXPECTED = ['Name','Tradition','Order','Region','BirthYear','DeathYear']

def error(msg, code=1):
    sys.stderr.write(msg + '\n')
    sys.exit(code)

def parse_args():
    if len(sys.argv) == 1:
        return 'input/biographies.csv'
    elif len(sys.argv) == 2:
        return sys.argv[1]
    else:
        error('Usage: python tools/validate_records.py [path/to/file.csv]', code=2)

def main():
    path = parse_args()
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                error('ERROR: Empty or unreadable CSV header')
            # Strict header check
            if reader.fieldnames != EXPECTED:
                error(f"ERROR: Header mismatch. Found {reader.fieldnames}, expected {EXPECTED}")
            row_count = 0
            for idx, row in enumerate(reader, start=2):  # data starts at line 2
                row_count += 1
                by = (row['BirthYear'] or '').strip()
                dy = (row['DeathYear'] or '').strip()
                if by and not by.isdigit():
                    error(f"ERROR on row {idx} ({row['Name']}): non-integer BirthYear='{row['BirthYear']}'. Use digits only (e.g., 1207).")
                if dy and not dy.isdigit():
                    error(f"ERROR on row {idx} ({row['Name']}): non-integer DeathYear='{row['DeathYear']}'. Use digits only (e.g., 1273).")
                if by and dy:
                    b = int(by)
                    d = int(dy)
                    if d < b:
                        error(f"ERROR on row {idx} ({row['Name']}): DeathYear {d} is earlier than BirthYear {b}.")
        print(f"PASS: validated {row_count} rows")
    except FileNotFoundError:
        error(f"ERROR: File not found: {path}")

if __name__ == '__main__':
    main()
