import sys, csv, json
from datetime import datetime

# NOTE: This script attempts to list late deliveries and print a top-5 summary.
# It's brittle and assumes old column names.

def minutes_between(a, b):
    return int((b - a).total_seconds() / 60)

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not csv_path:
        print("Usage: python delivery_stats.py <csv_path>")
        sys.exit(1)

    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # BUG: expects 'date' and 'time' columns (the file now has different headers)
            sched_dt = datetime.strptime(r['date'] + ' ' + r['time'], "%Y-%m-%d %H:%M")
            arr_dt = None
            # BUG: expects 'arrived' instead of current arrival column name
            if r.get('arrived'):
                arr_dt = datetime.strptime(r['date'] + ' ' + r['arrived'], "%Y-%m-%d %H:%M")
            if arr_dt:
                late = minutes_between(sched_dt, arr_dt)
                rows.append({
                    # BUG: old column name 'job' instead of 'job_id'
                    'job_id': r.get('job'),
                    'driver': r.get('driver'),
                    'vendor': r.get('vendor'),
                    'scheduled_time': str(sched_dt),
                    'arrival_time': str(arr_dt),
                    'late_mins': late if late > 0 else 0
                })
                if late > 0:
                    print("LATE: driver {} blew it by {} minutes".format(r.get('driver'), late))
            else:
                print("Missing arrival, skipping row for job {}".format(r.get('job')))

    # Summarize top 5 late deliveries
    top = sorted(rows, key=lambda x: x['late_mins'], reverse=True)[:5]
    print("Top late deliveries:", [t['job_id'] for t in top])
    with open("output.json", "w") as out:
        json.dump({'top': top, 'count': len(rows)}, out)
