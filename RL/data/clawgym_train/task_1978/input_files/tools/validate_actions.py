#!/usr/bin/env python3
import sys
import os
import csv

def main():
    if len(sys.argv) != 2:
        print("Usage: validate_actions.py <actions_csv>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    errors = 0
    warnings = 0
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=2):  # start=2 accounts for header row at 1
                aid = (row.get('action_id') or '').strip()
                title = (row.get('action_title') or '').strip()
                pr = (row.get('priority') or '').strip()
                st = (row.get('status') or '').strip()
                if not title:
                    print(f"ERROR: row {idx} (action_id={aid}): missing action_title")
                    errors += 1
                valid_priorities = {'low', 'medium', 'high'}
                if pr.lower() not in valid_priorities:
                    if pr:
                        print(f"WARNING: row {idx} (action_id={aid}): priority '{pr}' not recognized; defaulting to 'medium'")
                    else:
                        print(f"WARNING: row {idx} (action_id={aid}): priority missing; defaulting to 'medium'")
                    warnings += 1
                valid_status = {'planned', 'active', 'done'}
                if st.lower() not in valid_status:
                    if st:
                        print(f"WARNING: row {idx} (action_id={aid}): status '{st}' not recognized; defaulting to 'planned'")
                    else:
                        print(f"WARNING: row {idx} (action_id={aid}): status missing; defaulting to 'planned'")
                    warnings += 1
    except Exception as e:
        print(f"ERROR: failed to read CSV: {e}")
        return 2
    print(f"SUMMARY: errors={errors} warnings={warnings}")
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
