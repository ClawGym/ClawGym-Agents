import sys, csv, json

USAGE = "Usage: python validate_citations.py <studies_csv> <citation_index_json>"

def load_csv_codes(path):
    codes = set()
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get('citation_code') or '').strip()
            if code:
                codes.add(code)
    return codes

def main():
    if len(sys.argv) != 3:
        sys.stderr.write(USAGE + "\n")
        sys.exit(64)
    studies_csv = sys.argv[1]
    citation_json = sys.argv[2]
    try:
        csv_codes = load_csv_codes(studies_csv)
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: studies CSV not found: {studies_csv}\n")
        sys.exit(66)
    except Exception as e:
        sys.stderr.write(f"ERROR reading CSV: {e}\n")
        sys.exit(65)
    try:
        with open(citation_json, encoding='utf-8') as f:
            index = json.load(f)
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: citation index JSON not found: {citation_json}\n")
        sys.exit(66)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR parsing JSON: {e}\n")
        sys.exit(65)
    except Exception as e:
        sys.stderr.write(f"ERROR reading JSON: {e}\n")
        sys.exit(65)

    index_codes = set(index.keys())
    missing = sorted(csv_codes - index_codes)
    extra = sorted(index_codes - csv_codes)

    sys.stdout.write(f"CSV citations: {len(csv_codes)} | Index entries: {len(index_codes)}\n")
    if extra:
        sys.stdout.write("Unused citations in index: " + ", ".join(extra) + "\n")

    if missing:
        sys.stderr.write("Unresolved citations: " + ", ".join(missing) + "\n")
        sys.exit(2)
    else:
        sys.stdout.write("All citations resolved.\n")
        sys.exit(0)

if __name__ == '__main__':
    main()
