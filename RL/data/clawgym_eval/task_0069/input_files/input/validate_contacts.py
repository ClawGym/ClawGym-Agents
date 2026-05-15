import csv
import os
import re
import sys

def is_valid(email):
    # Simple email check: something@something.withdot
    if not email:
        return False
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

def main():
    in_path = os.path.join('input', 'contacts.csv')
    out_clean_dir = os.path.join('output', 'clean')
    out_logs_dir = os.path.join('output', 'logs')
    os.makedirs(out_clean_dir, exist_ok=True)
    os.makedirs(out_logs_dir, exist_ok=True)

    total = 0
    valid_count = 0
    cleaned_path = os.path.join(out_clean_dir, 'contacts_clean.csv')

    with open(in_path, newline='', encoding='utf-8') as f_in, open(cleaned_path, 'w', newline='', encoding='utf-8') as f_out:
        reader = csv.DictReader(f_in)
        fieldnames = reader.fieldnames + ['valid']
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            total += 1
            ok = is_valid(row.get('email', ''))
            row['valid'] = 'true' if ok else 'false'
            writer.writerow(row)
            if ok:
                valid_count += 1

    invalid_count = total - valid_count
    with open(os.path.join(out_logs_dir, 'validation.log'), 'w', encoding='utf-8') as log:
        log.write(f'total={total}\n')
        log.write(f'valid={valid_count}\n')
        log.write(f'invalid={invalid_count}\n')

if __name__ == '__main__':
    sys.exit(main())
