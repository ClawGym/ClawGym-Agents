import csv
from datetime import datetime
from collections import defaultdict

def parse_date(d: str):
    """Parse a 'YYYY-MM-DD' date string to a date object."""
    return datetime.strptime(d, "%Y-%m-%d").date()

def read_events_csv(path: str):
    """
    Read an events CSV and return a list of dicts.
    The CSV is expected to have headers including: date, governorate, fatalities (others are ignored here).
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

def filter_by_date_range(events, start_date, end_date):
    """
    Return events where start_date <= event_date <= end_date (inclusive end).
    NOTE: The current implementation mistakenly treats the end date as exclusive.
    """
    filtered = []
    for e in events:
        d = parse_date(e["date"]) if isinstance(e["date"], str) else e["date"]
        # BUG: end_date is treated as exclusive here; tests should catch this and the function should be fixed.
        if start_date <= d and d < end_date:
            filtered.append(e)
    return filtered

def aggregate_incidents_by_governorate(events):
    """
    Aggregate events by governorate, counting events and summing fatalities.
    Returns a dict: { governorate: {"event_count": n, "total_fatalities": m} }
    """
    agg = defaultdict(lambda: {"event_count": 0, "total_fatalities": 0})
    for e in events:
        gov = e.get("governorate", "").strip()
        agg[gov]["event_count"] += 1
        try:
            fat = int(e.get("fatalities", 0) or 0)
        except (ValueError, TypeError):
            fat = 0
        agg[gov]["total_fatalities"] += fat
    return dict(agg)

def write_aggregates_csv(agg, output_path: str):
    """Write aggregates dict to CSV with header governorate,event_count,total_fatalities, sorted by governorate."""
    fieldnames = ["governorate", "event_count", "total_fatalities"]
    rows = []
    for gov, vals in agg.items():
        rows.append({
            "governorate": gov,
            "event_count": vals["event_count"],
            "total_fatalities": vals["total_fatalities"],
        })
    rows.sort(key=lambda x: x["governorate"])  # deterministic order
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
