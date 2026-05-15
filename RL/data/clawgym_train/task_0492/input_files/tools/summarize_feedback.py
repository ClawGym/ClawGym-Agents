import sys
import csv

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python tools/summarize_feedback.py <path_to_feedback_tsv>\n")
        sys.exit(1)
    path = sys.argv[1]
    total = 0
    pro = 0
    skipped = 0
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            stance = (row.get('stance') or '').strip()
            if not stance:
                skipped += 1
                continue
            total += 1
            if stance == 'pro_science':
                pro += 1
    print(f"Total_records: {total}")
    print(f"Count_pro_science: {pro}")
    print(f"Count_non_pro_science: {total - pro}")
    if skipped:
        sys.stderr.write(f"WARNING: {skipped} row(s) had missing stance and were ignored.\n")

if __name__ == '__main__':
    main()
