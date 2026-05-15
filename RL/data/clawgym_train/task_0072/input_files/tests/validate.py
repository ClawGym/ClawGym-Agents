import json
import os
import sys

TRACE_PATH = os.path.join('output', 'review', 'trace.json')
REPORT_PATH = os.path.join('output', 'review', 'report.md')

FAILURES = []

def fail(msg):
    FAILURES.append(msg)


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"Missing file: {path}")
    except Exception as e:
        fail(f"Failed to read JSON {path}: {e}")
    return None


def check_trace(trace):
    # Required claim ids
    required_ids = ['c1', 'c2', 'c3']
    for cid in required_ids:
        if cid not in trace:
            fail(f"trace.json missing claim_id {cid}")
    if FAILURES:
        return

    # c1 expectations
    c1 = trace['c1']
    if c1.get('status') != 'supported':
        fail("c1 should be supported")
    if c1.get('source') != 'budget':
        fail("c1 source should be 'budget'")
    row = (c1.get('evidence') or {}).get('row')
    if not isinstance(row, dict):
        fail("c1 evidence.row missing or not an object")
    else:
        # Tolerate strings or ints for Amount/Year
        try:
            amt = int(row.get('Amount')) if row.get('Amount') is not None else None
        except Exception:
            amt = None
        try:
            yr = int(row.get('Year')) if row.get('Year') is not None else None
        except Exception:
            yr = None
        cat = (row.get('Category') or '').lower()
        if yr != 2024:
            fail(f"c1 evidence Year expected 2024, got {yr}")
        if amt != 23000:
            fail(f"c1 evidence Amount expected 23000, got {amt}")
        if 'after-school program' not in cat:
            fail(f"c1 evidence Category should mention 'After-school program', got '{row.get('Category')}'")

    # c2 expectations
    c2 = trace['c2']
    if c2.get('status') != 'unsupported':
        fail("c2 should be unsupported")
    if c2.get('source') != 'budget':
        fail("c2 source should be 'budget'")

    # c3 expectations
    c3 = trace['c3']
    if c3.get('status') != 'supported':
        fail("c3 should be supported")
    if c3.get('source') != 'notes':
        fail("c3 source should be 'notes'")
    line = (c3.get('evidence') or {}).get('line')
    if not isinstance(line, str) or '7:30 AM'.lower() not in line.lower():
        fail("c3 evidence.line should include the exact time '7:30 AM'")


def check_report(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [ln.strip().lower() for ln in f.readlines()]
    except FileNotFoundError:
        fail(f"Missing file: {path}")
        return
    except Exception as e:
        fail(f"Failed to read report.md: {e}")
        return

    def has_status(cid, expected):
        for ln in lines:
            if cid in ln and expected in ln:
                return True
        return False

    if not has_status('c1', 'supported'):
        fail("report.md should clearly mark c1 as supported")
    if not has_status('c2', 'unsupported'):
        fail("report.md should clearly mark c2 as unsupported")
    if not has_status('c3', 'supported'):
        fail("report.md should clearly mark c3 as supported")


def main():
    trace = load_json(TRACE_PATH)
    if trace is not None:
        check_trace(trace)
    check_report(REPORT_PATH)

    if FAILURES:
        print("\nValidation FAILED:")
        for i, msg in enumerate(FAILURES, 1):
            print(f"{i}. {msg}")
        sys.exit(1)
    else:
        print("All checks passed. ✔")
        sys.exit(0)

if __name__ == '__main__':
    main()
