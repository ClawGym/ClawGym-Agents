import re
import json

# Checks that docs/policy_brief.md contains a Data Summary section consistent with data/summary.json.
# Usage: python tests/check_brief_consistency.py

def extract_section(text):
    m = re.search(r"<!-- START DATA SUMMARY -->(.*?)<!-- END DATA SUMMARY -->", text, re.DOTALL)
    return m.group(1).strip() if m else None

def main():
    with open('data/summary.json') as f:
        summary = json.load(f)
    avg = float(summary['overall_avg_new_business_rate_per_1000'])
    avg_str = f"{avg:.2f}"
    top = summary['top_regions_by_rate']
    # Expect exact lines in order
    expected_lines = [
        f"Overall average new business formation rate per 1,000 residents: {avg_str}",
        f"1) {top[0]['region']}: {top[0]['rate_per_1000']:.2f} per 1,000",
        f"2) {top[1]['region']}: {top[1]['rate_per_1000']:.2f} per 1,000",
        f"3) {top[2]['region']}: {top[2]['rate_per_1000']:.2f} per 1,000",
    ]
    with open('docs/policy_brief.md') as f:
        brief = f.read()
    section = extract_section(brief)
    if section is None:
        print('Data Summary section markers not found')
        raise SystemExit(1)
    # Normalize whitespace and compare presence and order
    # We'll check that each expected line appears and in the correct order.
    lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
    # Must contain at least 4 lines in this exact order
    if len(lines) < 4:
        print('Data Summary section has fewer than 4 non-empty lines')
        raise SystemExit(1)
    for i, exp in enumerate(expected_lines):
        if i >= len(lines) or lines[i] != exp:
            print(f"Mismatch at line {i+1}: got '{lines[i] if i < len(lines) else '(missing)'}', expected '{exp}'")
            raise SystemExit(1)
    print('CONSISTENT')

if __name__ == '__main__':
    main()
