import csv
import yaml
from datetime import date, timedelta
import os

# Simple deterministic scheduler: reads events and a date window from YAML,
# then emits reminder send dates based on each channel's days_before list.

def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())

with open('config/reminders.yaml', 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

window_start = parse_date(cfg['window']['start'])
window_end = parse_date(cfg['window']['end'])

# Load events
events = []
with open('input/events.csv', 'r', encoding='utf-8', newline='') as f:
    rdr = csv.DictReader(f)
    for row in rdr:
        row['event_date'] = parse_date(row['event_date'])
        events.append(row)

rows = []
for ev in events:
    status = (ev.get('status') or '').strip().lower()
    if status != 'planned':
        continue
    if not (window_start <= ev['event_date'] <= window_end):
        continue
    for ch in cfg['channels']:
        # EXPECTED KEY: 'days_before' (list of integers)
        offsets = ch['days_before']  # KeyError if misconfigured; fix YAML rather than code
        for d in offsets:
            send_dt = ev['event_date'] - timedelta(days=int(d))
            rows.append({
                'event_name': ev['event_name'],
                'event_date': ev['event_date'].isoformat(),
                'channel': ch['name'],
                'send_date': send_dt.isoformat(),
                'template_path': ch['template']
            })

# Ensure output directory exists and write schedule
os.makedirs('out', exist_ok=True)
with open('out/scheduled_reminders.csv', 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['event_name', 'event_date', 'channel', 'send_date', 'template_path']
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in sorted(rows, key=lambda r: (r['send_date'], r['channel'], r['event_name'])):
        w.writerow(r)
