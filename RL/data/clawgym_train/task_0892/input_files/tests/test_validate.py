import csv
import json
import math
import os
import sys

ATTENDEES_PATH = os.path.join('input', 'attendees.json')
FEES_PATH = os.path.join('input', 'fees.json')
VENDORS_PATH = os.path.join('input', 'vendors.csv')
REPORT_PATH = os.path.join('output', 'catering_report.csv')
CHOSEN_PATH = os.path.join('output', 'chosen_vendor.json')
NOTES_PATH = os.path.join('docs', 'budget_notes.md')

REQUIRED_REPORT_COLUMNS = {
    'vendor', 'feasible', 'subtotal', 'service_fee', 'tax', 'total', 'cost_per_attendee'
}


def parse_bool(s):
    if isinstance(s, bool):
        return s
    if s is None:
        return False
    return str(s).strip().lower() in ('true', '1', 'yes', 'y')


def read_vendors(path):
    with open(path, newline='', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        rows = [r for r in rdr]
    # Basic header check
    expected_cols = {'vendor', 'per_person', 'fixed_fee', 'vegetarian_supported', 'max_attendees'}
    if set(rdr.fieldnames) != expected_cols:
        raise AssertionError(f'vendors.csv columns mismatch. Expected {expected_cols}, got {set(rdr.fieldnames)}')
    return rows


def read_report(path):
    with open(path, newline='', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        fieldset = set(rdr.fieldnames or [])
        missing = REQUIRED_REPORT_COLUMNS - fieldset
        if missing:
            raise AssertionError(f'Report missing required columns: {missing}')
        rows = [r for r in rdr]
    return rows


def approx(a, b, tol=1e-2):
    return abs(a - b) <= tol


def to_float(x):
    try:
        return float(x)
    except Exception:
        raise AssertionError(f'Value should be numeric, got {x!r}')


def main():
    # Check inputs exist
    for p in [ATTENDEES_PATH, FEES_PATH, VENDORS_PATH]:
        if not os.path.exists(p):
            print(f'Missing input file: {p}', file=sys.stderr)
            sys.exit(1)

    # Check outputs exist
    for p in [REPORT_PATH, CHOSEN_PATH, NOTES_PATH]:
        if not os.path.exists(p):
            print(f'Missing required output file: {p}', file=sys.stderr)
            sys.exit(1)

    with open(ATTENDEES_PATH, 'r', encoding='utf-8') as f:
        attendees_cfg = json.load(f)
    with open(FEES_PATH, 'r', encoding='utf-8') as f:
        fees_cfg = json.load(f)

    attendees = int(attendees_cfg['attendees'])
    service_fee_rate = float(fees_cfg['service_fee_rate'])
    tax_rate = float(fees_cfg['tax_rate'])

    vendors = read_vendors(VENDORS_PATH)
    report_rows = read_report(REPORT_PATH)

    # Map report by vendor
    report_by_vendor = {}
    for r in report_rows:
        name = r['vendor']
        report_by_vendor[name] = r

    if len(report_rows) != len(vendors):
        raise AssertionError('Report should include exactly one row per vendor in input/vendors.csv')

    # Recompute expected values and validate report rows
    feasible_totals = []
    for v in vendors:
        name = v['vendor']
        per_person = float(v['per_person'])
        fixed_fee = float(v['fixed_fee'])
        veg_ok = parse_bool(v['vegetarian_supported'])
        max_cap = int(v['max_attendees'])

        feasible = veg_ok and (max_cap >= attendees)

        subtotal = per_person * attendees + fixed_fee
        service_fee = subtotal * service_fee_rate
        pre_tax = subtotal + service_fee
        tax = pre_tax * tax_rate
        total = pre_tax + tax
        cpp = total / attendees

        if name not in report_by_vendor:
            raise AssertionError(f'Missing vendor in report: {name}')
        rr = report_by_vendor[name]

        rr_feasible = parse_bool(rr['feasible'])
        if rr_feasible != feasible:
            raise AssertionError(f'Feasible flag mismatch for {name}: expected {feasible}, got {rr["feasible"]}')

        for col, expected in (
            ('subtotal', subtotal),
            ('service_fee', service_fee),
            ('tax', tax),
            ('total', total),
            ('cost_per_attendee', cpp),
        ):
            got = to_float(rr[col])
            if not approx(got, expected, tol=1e-2):
                raise AssertionError(f'Column {col} mismatch for {name}: expected ~{expected:.2f}, got {got:.2f}')

        if feasible:
            feasible_totals.append((total, name))

    if not feasible_totals:
        raise AssertionError('No feasible vendors found in report, but at least one should be feasible.')

    feasible_totals.sort()
    expected_total, expected_vendor = feasible_totals[0]

    # Validate chosen_vendor.json
    with open(CHOSEN_PATH, 'r', encoding='utf-8') as f:
        chosen = json.load(f)
    if chosen.get('vendor') != expected_vendor:
        raise AssertionError(f'Chosen vendor mismatch: expected {expected_vendor}, got {chosen.get("vendor")}')
    # Cross-check chosen fields against report
    rr = report_by_vendor[expected_vendor]
    for col in ('subtotal', 'service_fee', 'tax', 'total', 'cost_per_attendee'):
        got_json = to_float(chosen.get(col))
        got_csv = to_float(rr[col])
        if not approx(got_json, got_csv, tol=1e-2):
            raise AssertionError(f'Chosen vendor {col} mismatch between JSON and CSV: {got_json:.2f} vs {got_csv:.2f}')

    # Validate notes mention vendor and total rounded to 2 decimals
    with open(NOTES_PATH, 'r', encoding='utf-8') as f:
        notes = f.read()
    total_str = f"{to_float(rr['total']):.2f}"
    if expected_vendor not in notes:
        raise AssertionError('budget_notes.md does not mention the chosen vendor name')
    if total_str not in notes:
        raise AssertionError('budget_notes.md does not include the total cost (rounded to two decimals)')

    print('All validation checks passed.')


if __name__ == '__main__':
    main()
