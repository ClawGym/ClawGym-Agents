import sys
import os

def count_quoted_lines(text):
    count = 0
    for line in text.splitlines():
        if '"' in line.strip():
            count += 1
    return count

def has_aggregates_header(text):
    for line in text.splitlines():
        if line.strip().startswith('|') and 'Grad Year' in line and 'Respondents' in line:
            return True
    return False

def main():
    if len(sys.argv) < 2:
        print('ERROR: Document path argument missing.')
        sys.exit(2)
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f'ERROR: Document not found at {path}')
        sys.exit(2)
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    errors = []
    warnings = []
    if 'Remembering President Bobby Lots' not in text:
        errors.append("Missing title 'Remembering President Bobby Lots'")
    if '## Data Highlights' not in text:
        errors.append("Missing '## Data Highlights' section")
    if '- Total respondents:' not in text:
        errors.append("Missing 'Total respondents' line in Data Highlights")
    if '- Average rating:' not in text:
        errors.append("Missing 'Average rating' line in Data Highlights")
    if '## Quotes' not in text:
        errors.append("Missing '## Quotes' section")
    if count_quoted_lines(text) < 3:
        errors.append('Quotes section must include at least 3 quoted lines')
    if '## Appendix: Aggregates' not in text:
        errors.append("Missing '## Appendix: Aggregates' section")
    if not has_aggregates_header(text):
        errors.append("Aggregates section must include a table header with 'Grad Year' and 'Respondents'")
    if '## Build Log Summary' not in text:
        errors.append("Missing '## Build Log Summary' section")
    if 'TBD' in text or 'todo' in text.lower():
        warnings.append('Found placeholder text (TBD/todo)')
    for w in warnings:
        print(f'WARNING: {w}')
    if errors:
        for e in errors:
            print(f'ERROR: {e}')
        sys.exit(1)
    else:
        print('OK: All required sections present')
        sys.exit(0)

if __name__ == '__main__':
    main()
