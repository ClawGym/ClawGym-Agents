import sys
import csv

# NOTE: This is the baseline script provided by a volunteer.
# It is intentionally naive and will likely crash on the provided CSV.
# Your task is to run it once (capturing its error output), then refactor a fixed version separately.

def load_requests(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Intentional mistakes below (wrong headers, wrong types)
            qty = int(r['qty'])  # should be 'quantity'
            students = int(r['students'])  # should be 'student_count'
            price = float(r['unit_cost'])
            impact = float(r.get('impact_score', '0'))
            total = qty * price
            if students == 0:
                cps = 0
            else:
                cps = total / students
            priority = impact / cps if cps else 0
            # store as string (bad idea)
            r['priority'] = str(priority)
            rows.append(r)
    return rows

def sort_requests(rows):
    # Sort as strings ascending instead of numeric descending (not appropriate)
    return sorted(rows, key=lambda r: r['priority'])

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'data/requests.csv'
    rows = load_requests(path)
    ranked = sort_requests(rows)
    # Print top 5 (but with the current logic, will be incorrect types/order)
    for r in ranked[:5]:
        print(r.get('request_id', ''), r.get('priority', ''))

if __name__ == '__main__':
    main()
