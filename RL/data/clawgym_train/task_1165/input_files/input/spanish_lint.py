import sys
import re

def main():
    if len(sys.argv) < 2:
        print("ERROR: provide path to Spanish text file")
        print("WARNINGS: 1")
        return 1
    path = sys.argv[1]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception as e:
        print(f"ERROR: could not read file: {e}")
        print("WARNINGS: 1")
        return 1

    warnings = []

    # Require formal greeting
    if not re.search(r'(?i)estimad[oa]', txt):
        warnings.append("Missing formal greeting 'Estimado/Estimada'.")

    # Require specific phrase with accent
    if not re.search(r'(?i)equipo de pediatría', txt):
        warnings.append("Missing required phrase 'equipo de pediatría' (with accent).")

    # Discourage informal second-person forms
    if re.search(r'(?i)\b(tu|tú|vos)\b', txt):
        warnings.append("Use formal tone; avoid 'tú/tu/vos'.")

    # Flag placeholders
    if re.search(r'\[|\]|<|>|TODO', txt):
        warnings.append("Remove placeholders like brackets '< > [ ]' or 'TODO'.")

    # Require an explicit expression of gratitude
    if not re.search(r'(?i)\b(gracias|agradezco|agradecimiento|agradecidos?)\b', txt):
        warnings.append("Add an explicit expression of gratitude (e.g., 'gracias'/'agradezco').")

    for w in warnings:
        print("WARNING:", w)
    print(f"WARNINGS: {len(warnings)}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
