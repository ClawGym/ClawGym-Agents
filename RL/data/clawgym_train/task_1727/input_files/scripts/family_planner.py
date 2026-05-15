#!/usr/bin/env python3
import argparse
import csv
import sys
from typing import List, Dict

try:
    import yaml  # PyYAML (assume available in local environment)
except Exception as e:
    yaml = None

# NOTE: This script is intentionally flawed and needs refactoring.
# Problems to address:
# - Config keys are inconsistent (time_fmt / canceled_tag / include_canceled) and not documented.
# - Duration calculation is wrong (string math).
# - No de-duplication or sorting.
# - Cancelled items are included by default.


def load_config(path: str) -> Dict:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load configuration.")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def read_events(csv_path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Minimal normalization
            row = {
                'date': (r.get('date') or '').strip(),
                'start_time': (r.get('start_time') or '').strip(),
                'end_time': (r.get('end_time') or '').strip(),
                'title': (r.get('title') or '').strip(),
            }
            rows.append(row)
    return rows


def naive_duration_minutes(start_time: str, end_time: str) -> int:
    # INCORRECT: Treats HH:MM as an integer like 1830 and subtracts directly.
    # This fails for anything beyond simple hours and ignores minutes properly.
    try:
        a = int(start_time.replace(':', ''))
        b = int(end_time.replace(':', ''))
        diff = b - a
        if diff < 0:
            return 0
        # Pretend the last two digits are minutes without carry handling.
        hours = diff // 100
        mins = diff % 100
        return hours * 60 + mins
    except Exception:
        return 0


def write_agenda(out_path: str, rows: List[Dict[str, str]], columns: List[str]):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            out_row = {c: r.get(c, '') for c in columns}
            writer.writerow(out_row)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Family agenda generator (needs refactor).')
    parser.add_argument('--config', required=True)
    parser.add_argument('--in', dest='infile', required=True)
    parser.add_argument('--out', dest='outfile', required=True)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    # Current (buggy) config keys
    time_fmt = cfg.get('time_fmt', '%Y/%m/%d %H-%M')
    canceled_tag = cfg.get('canceled_tag', '[canceled]')
    include_canceled = cfg.get('include_canceled', True)
    output_columns = cfg.get('output_columns', ['date', 'start_time', 'end_time', 'title', 'duration_minutes'])

    rows = read_events(args.infile)

    # No sorting, no dedupe. Optional filtering only if include_canceled is False.
    filtered: List[Dict[str, str]] = []
    for r in rows:
        title = r.get('title', '')
        if (not include_canceled) and (canceled_tag in title):
            continue
        # Wrong duration calculation
        r['duration_minutes'] = str(naive_duration_minutes(r.get('start_time', ''), r.get('end_time', '')))
        filtered.append(r)

    write_agenda(args.outfile, filtered, output_columns)
    return 0


if __name__ == '__main__':
    sys.exit(main())
