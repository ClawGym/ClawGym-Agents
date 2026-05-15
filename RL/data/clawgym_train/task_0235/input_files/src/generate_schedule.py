import csv
import json
import os

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_meetings(csv_path):
    rows = []
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        # BUG: wrong delimiter; the input file is CSV
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            rows.append(row)
    return rows


def normalize_format(fmt):
    # BUG: does not normalize to the required values
    return fmt


def normalize_time(t):
    # BUG: does not ensure zero-padded HH:MM
    return t


def build_schedule(rows, tz):
    items = []
    for r in rows:
        # Intend to skip cancelled, but field usage and normalization are buggy elsewhere
        if r.get('status', 'active') == 'active':
            try:
                # BUGS: expects wrong field names from CSV
                name = r['name']
                day = r['day']
                time_str = r['time']              # should be 'start_time'
                duration = int(r['duration'])     # should be 'duration_min'
                fmt = r['format']                 # should be 'meeting_format'
                item = {
                    'id': r['id'],
                    'name': name,
                    'day': day,                   # should be title-cased to a known weekday
                    'start': normalize_time(time_str),  # wrong key; should be 'start_time'
                    'len': duration,              # wrong key; should be 'duration_min'
                    'format': normalize_format(fmt),
                    'location': r.get('location', ''),
                    'notes': r.get('notes', ''),
                    'tz': tz                      # wrong key; should be 'timezone'
                }
                items.append(item)
            except Exception:
                # Swallow errors and continue (masking issues)
                continue
    return items


def write_schedule(items, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'schedule.json'), 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def write_summary(items, out_path):
    counts = {}
    for it in items:
        key = (it.get('day', ''), it.get('format', ''))
        counts[key] = counts.get(key, 0) + 1
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        f.write('day,format,count\n')
        for (day, fmt), count in sorted(counts.items()):
            f.write(f'{day},{fmt},{count}\n')


def main():
    conf = load_config('config/config.json')
    # BUGS: wrong keys; should use 'default_timezone' and 'output_dir'
    tz = conf.get('timezone', 'UTC')
    out_dir = conf.get('out_dir', 'out')
    rows = read_meetings('input/meetings.csv')
    schedule = build_schedule(rows, tz)
    # BUG: ignores configured output_dir
    write_schedule(schedule, 'out')
    # BUG: inconsistent path handling
    write_summary(schedule, os.path.join('output', 'summary.csv'))

if __name__ == '__main__':
    main()
