import csv
import json
import subprocess
import sys
from pathlib import Path


def parse_bool(s):
    if isinstance(s, bool):
        return s
    if s is None:
        return False
    return str(s).strip().lower() in ('true', '1', 'yes', 'y')


def approx(a, b, tol=1e-2):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def safe_read_json(path: Path):
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv_dict(path: Path):
    try:
        with path.open('r', encoding='utf-8', newline='') as f:
            rdr = csv.DictReader(f)
            fieldnames = list(rdr.fieldnames or [])
            rows = [r for r in rdr]
        return fieldnames, rows
    except Exception:
        return None


def required_report_columns():
    return {'vendor', 'feasible', 'subtotal', 'service_fee', 'tax', 'total', 'cost_per_attendee'}


def compute_expected(vendors_rows, attendees, service_fee_rate, tax_rate):
    expected = {}
    feasible_totals = []
    for v in vendors_rows:
        name = v.get('vendor')
        try:
            per_person = float(v.get('per_person'))
            fixed_fee = float(v.get('fixed_fee'))
            veg_ok = parse_bool(v.get('vegetarian_supported'))
            max_cap = int(float(v.get('max_attendees')))
        except Exception:
            # Malformed vendor row; mark as invalid by skipping computations
            return None, None
        feasible = veg_ok and (max_cap >= attendees)

        subtotal = per_person * attendees + fixed_fee
        service_fee = subtotal * service_fee_rate
        pre_tax = subtotal + service_fee
        tax = pre_tax * tax_rate
        total = pre_tax + tax
        cpp = total / attendees

        expected[name] = {
            'feasible': feasible,
            'subtotal': subtotal,
            'service_fee': service_fee,
            'tax': tax,
            'total': total,
            'cost_per_attendee': cpp,
        }
        if feasible:
            feasible_totals.append((total, name))
    feasible_totals.sort(key=lambda x: x[0])
    expected_chosen = feasible_totals[0][1] if feasible_totals else None
    return expected, expected_chosen


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_structure": 0.0,
        "feasibility_flags_correct": 0.0,
        "calculations_correct": 0.0,
        "chosen_vendor_correct": 0.0,
        "chosen_json_matches_report_and_attendees": 0.0,
        "notes_mentions_vendor_and_total": 0.0,
        "tests_passed": 0.0,
    }

    # Paths
    attendees_path = workspace / 'input' / 'attendees.json'
    fees_path = workspace / 'input' / 'fees.json'
    vendors_path = workspace / 'input' / 'vendors.csv'
    report_path = workspace / 'output' / 'catering_report.csv'
    chosen_path = workspace / 'output' / 'chosen_vendor.json'
    notes_path = workspace / 'docs' / 'budget_notes.md'
    tests_path = workspace / 'tests' / 'test_validate.py'

    # Load inputs
    attendees_cfg = safe_read_json(attendees_path) if attendees_path.exists() else None
    fees_cfg = safe_read_json(fees_path) if fees_path.exists() else None
    vendors_load = safe_read_csv_dict(vendors_path) if vendors_path.exists() else None

    attendees = None
    service_fee_rate = None
    tax_rate = None
    vendors_rows = None
    vendors_names = set()

    if attendees_cfg is not None and 'attendees' in attendees_cfg:
        try:
            attendees = int(float(attendees_cfg.get('attendees')))
        except Exception:
            attendees = None

    if fees_cfg is not None:
        try:
            service_fee_rate = float(fees_cfg.get('service_fee_rate'))
            tax_rate = float(fees_cfg.get('tax_rate'))
        except Exception:
            service_fee_rate = None
            tax_rate = None

    if vendors_load is not None:
        _, vendors_rows = vendors_load
        try:
            vendors_names = {r.get('vendor') for r in vendors_rows if 'vendor' in r}
        except Exception:
            vendors_names = set()

    # Load report
    report_fieldnames = []
    report_rows = []
    report_by_vendor = {}
    if report_path.exists():
        report_data = safe_read_csv_dict(report_path)
        if report_data:
            report_fieldnames, report_rows = report_data
            try:
                for r in report_rows:
                    name = r.get('vendor')
                    if name is not None:
                        report_by_vendor[name] = r
            except Exception:
                report_by_vendor = {}

    # Compute expected values
    expected_map = None
    expected_chosen_vendor = None
    if attendees is not None and service_fee_rate is not None and tax_rate is not None and vendors_rows is not None:
        expected_map, expected_chosen_vendor = compute_expected(vendors_rows, attendees, service_fee_rate, tax_rate)

    # report_structure: check existence, required columns, row count, and vendor set match
    report_ok = False
    try:
        if report_rows and report_fieldnames:
            cols = set(report_fieldnames)
            req = required_report_columns()
            has_required = req.issubset(cols)
            count_match = vendors_rows is not None and len(report_rows) == len(vendors_rows)
            names_match = vendors_names and set(report_by_vendor.keys()) == vendors_names
            if has_required and count_match and names_match:
                report_ok = True
    except Exception:
        report_ok = False
    scores["report_structure"] = 1.0 if report_ok else 0.0

    # feasibility_flags_correct
    feas_ok = False
    if expected_map is not None and report_by_vendor and vendors_names:
        feas_ok = True
        for name in vendors_names:
            if name not in expected_map or name not in report_by_vendor:
                feas_ok = False
                break
            expected_feasible = expected_map[name]['feasible']
            rr = report_by_vendor[name]
            rr_feasible = parse_bool(rr.get('feasible'))
            if rr_feasible != expected_feasible:
                feas_ok = False
                break
    scores["feasibility_flags_correct"] = 1.0 if feas_ok else 0.0

    # calculations_correct
    calc_ok = False
    if expected_map is not None and report_by_vendor and vendors_names:
        calc_ok = True
        for name in vendors_names:
            if name not in expected_map or name not in report_by_vendor:
                calc_ok = False
                break
            rr = report_by_vendor[name]
            for col in ('subtotal', 'service_fee', 'tax', 'total', 'cost_per_attendee'):
                ev = expected_map[name][col]
                gv = rr.get(col)
                gv_float = to_float(gv)
                if gv_float is None or not approx(gv_float, ev, tol=1e-2):
                    calc_ok = False
                    break
            if not calc_ok:
                break
    scores["calculations_correct"] = 1.0 if calc_ok else 0.0

    # chosen_vendor_correct
    chosen_vendor_ok = False
    chosen_json = None
    if chosen_path.exists():
        chosen_json = safe_read_json(chosen_path)
    if chosen_json is not None and expected_chosen_vendor is not None:
        chosen_vendor_ok = (chosen_json.get('vendor') == expected_chosen_vendor)
    scores["chosen_vendor_correct"] = 1.0 if chosen_vendor_ok else 0.0

    # chosen_json_matches_report_and_attendees
    chosen_match_ok = False
    if chosen_vendor_ok and report_by_vendor and attendees is not None:
        rr = report_by_vendor.get(expected_chosen_vendor)
        if rr is not None:
            try:
                att_ok = int(float(chosen_json.get('attendees'))) == attendees
            except Exception:
                att_ok = False
            nums_ok = True
            for col in ('subtotal', 'service_fee', 'tax', 'total', 'cost_per_attendee'):
                gv_json = to_float(chosen_json.get(col))
                gv_csv = to_float(rr.get(col))
                if gv_json is None or gv_csv is None or not approx(gv_json, gv_csv, tol=1e-2):
                    nums_ok = False
                    break
            chosen_match_ok = att_ok and nums_ok
    scores["chosen_json_matches_report_and_attendees"] = 1.0 if chosen_match_ok else 0.0

    # notes_mentions_vendor_and_total
    notes_ok = False
    if notes_path.exists() and chosen_vendor_ok and report_by_vendor:
        rr = report_by_vendor.get(expected_chosen_vendor)
        if rr is not None:
            total_val = to_float(rr.get('total'))
            if total_val is not None:
                total_str = f"{total_val:.2f}"
                try:
                    content = notes_path.read_text(encoding='utf-8')
                except Exception:
                    content = None
                if content is not None:
                    vendor_in = expected_chosen_vendor in content
                    total_in = total_str in content
                    no_todos = ('TODO_VENDOR' not in content) and ('TODO_TOTAL' not in content) and ('TODO_REASON' not in content)
                    notes_ok = vendor_in and total_in and no_todos
    scores["notes_mentions_vendor_and_total"] = 1.0 if notes_ok else 0.0

    # tests_passed
    tests_ok = False
    if tests_path.exists():
        try:
            # Run the provided validation tests
            res = subprocess.run([sys.executable, str(tests_path.name)], cwd=str(tests_path.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            tests_ok = (res.returncode == 0)
        except Exception:
            tests_ok = False
    else:
        tests_ok = False
    scores["tests_passed"] = 1.0 if tests_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()