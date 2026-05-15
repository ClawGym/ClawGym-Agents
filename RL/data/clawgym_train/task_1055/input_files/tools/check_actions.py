#!/usr/bin/env python3
import sys
import csv
import re
from datetime import datetime

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_COLS = ["meeting_date", "context", "task", "owner", "due_date", "status"]
VALID_STATUS = {"open", "in-progress", "done"}

def parse_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def main():
    if len(sys.argv) != 2:
        print("USAGE: python3 tools/check_actions.py <path/to/action_items.csv>")
        sys.exit(2)
    path = sys.argv[1]
    errors = 0
    warnings = 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLS if c not in header]
            if missing:
                print(f"ERROR: missing required columns: {', '.join(missing)}")
                sys.exit(1)
            rows = list(reader)
            for i, row in enumerate(rows, start=2):  # data starts at row 2
                # meeting_date
                md = (row.get("meeting_date") or "").strip()
                if not md:
                    print(f"ERROR row {i}: meeting_date is blank")
                    errors += 1
                elif not RE_DATE.match(md) or not parse_date(md):
                    print(f"ERROR row {i}: meeting_date not in YYYY-MM-DD ({md})")
                    errors += 1
                # context
                ctx = (row.get("context") or "").strip()
                if not ctx:
                    print(f"ERROR row {i}: context is blank")
                    errors += 1
                # task
                task = (row.get("task") or "").strip()
                if not task:
                    print(f"ERROR row {i}: task is blank")
                    errors += 1
                # owner
                owner = (row.get("owner") or "").strip()
                if owner.lower() == "tbd" or owner == "":
                    print(f"ERROR row {i}: owner missing or TBD")
                    errors += 1
                # due_date
                due = (row.get("due_date") or "").strip()
                if not due:
                    print(f"ERROR row {i}: due_date is blank")
                    errors += 1
                elif not RE_DATE.match(due) or not parse_date(due):
                    print(f"ERROR row {i}: due_date not in YYYY-MM-DD ({due})")
                    errors += 1
                # status
                status = (row.get("status") or "").strip().lower()
                if status not in VALID_STATUS:
                    print(f"ERROR row {i}: status must be one of {sorted(VALID_STATUS)} (got '{status}')")
                    errors += 1
                # additional checks: due_date earlier than meeting_date -> warning
                if RE_DATE.match(md) and RE_DATE.match(due) and parse_date(md) and parse_date(due):
                    d_md = datetime.strptime(md, "%Y-%m-%d")
                    d_due = datetime.strptime(due, "%Y-%m-%d")
                    if d_due < d_md:
                        print(f"WARNING row {i}: due_date {due} is before meeting_date {md}")
                        warnings += 1
            print(f"SUMMARY: rows={len(rows)} errors={errors} warnings={warnings}")
            if errors == 0:
                print("VALID: 0 errors")
            else:
                print("INVALID: see errors above")
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: failed to read/parse CSV: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
