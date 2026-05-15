import sys
import csv

ALLOWED = {
    "academics": "Academics",
    "wellness": "Wellness",
    "finance": "Finance",
    "community": "Community",
}

USAGE = "Usage: python tools/validate_resources.py <path_to_csv>\n"

def main():
    if len(sys.argv) < 2:
        sys.stderr.write(USAGE)
        sys.exit(2)
    path = sys.argv[1]
    errors = 0
    warnings = 0
    required_cols = ["resource_name", "category", "description", "hours", "contact"]
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                print("ERROR: CSV appears to have no header row.")
                print(f"Finished with 1 error(s), 0 warning(s).")
                sys.exit(1)
            missing_cols = [c for c in required_cols if c not in reader.fieldnames]
            if missing_cols:
                for c in missing_cols:
                    print(f"ERROR: Missing required column '{c}'.")
                errors += len(missing_cols)
                print(f"Finished with {errors} error(s), {warnings} warning(s).")
                sys.exit(1)
            for i, row in enumerate(reader, start=2):
                name = (row.get('resource_name') or '').strip() or f'row{i}'
                # Check required values
                for c in required_cols:
                    val = (row.get(c) or '').strip()
                    if val == '':
                        print(f"ERROR: Missing {c} on row {i} ({name}).")
                        errors += 1
                # Check category
                cat = (row.get('category') or '').strip()
                if cat:
                    lc = cat.lower()
                    if lc in ALLOWED:
                        canonical = ALLOWED[lc]
                        if cat != canonical:
                            print(f"WARNING: Category case/style normalized '{cat}' -> '{canonical}' on row {i} ({name}).")
                            warnings += 1
                    else:
                        allowed_list = ', '.join(sorted(ALLOWED.values()))
                        print(f"ERROR: Unknown category '{cat}' on row {i} ({name}); allowed: {allowed_list}.")
                        errors += 1
            print(f"Finished with {errors} error(s), {warnings} warning(s).")
            if errors:
                sys.exit(1)
            else:
                sys.exit(0)
    except FileNotFoundError:
        print(f"ERROR: File not found: {path}")
        print("Finished with 1 error(s), 0 warning(s).")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected exception: {e}")
        print("Finished with 1 error(s), 0 warning(s).")
        sys.exit(1)

if __name__ == '__main__':
    main()
