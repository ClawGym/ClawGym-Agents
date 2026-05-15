#!/usr/bin/env python3
import sys
import os
import csv

def main():
    if len(sys.argv) != 2:
        print("Usage: python tools/translate_lint.py <translated_csv>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        required_base = ['id', 'speaker', 'year', 'source', 'quote_en']
        required_trans = ['es', 'fr']
        header = reader.fieldnames or []
        missing = [c for c in required_base + required_trans if c not in header]
        if missing:
            for c in missing:
                print(f"FATAL MISSING_COLUMN name={c}", file=sys.stderr)
            # Exit with non-zero to signal failure
            sys.exit(2)

        errors = 0
        warnings = 0
        rows = 0

        for row in reader:
            rows += 1
            id_val = (row.get('id') or '').strip() or str(rows)
            en = (row.get('quote_en') or '').strip()

            for lang in required_trans:
                val = (row.get(lang) or '')
                if val.strip() == '':
                    print(f"ROW {id_val} ERROR MISSING_TRANSLATION lang={lang}")
                    errors += 1
                else:
                    if len(en) > 0:
                        ratio = len(val.strip()) / len(en)
                        if ratio < 0.6:
                            print(f"ROW {id_val} WARNING SHORT_TRANSLATION lang={lang} ratio={ratio:.2f}")
                            warnings += 1
                    en_end = en.rstrip()[-1:] if en else ''
                    tr_end = val.rstrip()[-1:] if val else ''
                    if en_end in '.!?':
                        if tr_end not in '.!?':
                            print(f"ROW {id_val} WARNING PUNCTUATION_MISMATCH lang={lang} expected_end={en_end!r} got={tr_end!r}")
                            warnings += 1
                    if 'TODO' in val or 'TBD' in val:
                        print(f"ROW {id_val} ERROR PLACEHOLDER_FOUND lang={lang}")
                        errors += 1

            es = (row.get('es') or '').strip().lower()
            fr = (row.get('fr') or '').strip().lower()
            if es and fr and es == fr:
                print(f"ROW {id_val} WARNING POSSIBLE_COPY_BETWEEN_LANGUAGES")
                warnings += 1

        print(f"SUMMARY rows={rows} errors={errors} warnings={warnings}")
        sys.exit(2 if errors > 0 else 0)

if __name__ == '__main__':
    main()
