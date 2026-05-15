import sys
import csv

USAGE = "Usage: python tools/check_terms.py <glossary_csv> <translation_md>"

def load_spanish_terms(path):
    terms = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        # Expect two columns: english,spanish
        for row in reader:
            if len(row) < 2:
                continue
            es = row[1].strip()
            if es:
                terms.append(es)
    return terms

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    glossary_csv = sys.argv[1]
    translation_md = sys.argv[2]

    try:
        terms = load_spanish_terms(glossary_csv)
    except Exception as e:
        print(f"ERROR Failed to read glossary: {e}")
        sys.exit(1)

    try:
        with open(translation_md, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"ERROR Failed to read translation file: {e}")
        sys.exit(1)

    text_lower = text.lower()
    errors = []

    # Check for glossary terms
    for term in terms:
        if term.lower() not in text_lower:
            errors.append(f"Missing glossary term: {term}")

    # Check for required sustainability line
    has_required_line = False
    for line in text.splitlines():
        if line.strip().lower().startswith("nota de sostenibilidad:"):
            has_required_line = True
            break
    if not has_required_line:
        errors.append("Missing required line: Nota de sostenibilidad:")

    if errors:
        for e in errors:
            print("ERROR " + e)
        print(f"FAILED {len(errors)} issue(s) found.")
        sys.exit(1)
    else:
        print("OK All checks passed for glossary terms and required sustainability line.")
        sys.exit(0)
