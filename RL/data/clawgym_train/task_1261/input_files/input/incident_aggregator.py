import json
import csv
import os

# Simple incident aggregator with known issues around deduplication and label casing.
# Reads events from input/logs/events.jsonl and writes a CSV summary.

def load_events(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]
    return [json.loads(line) for line in lines]

def aggregate(events):
    # Title-cased severities used throughout (inconsistent with desired uppercase)
    severities = ["Low", "Medium", "High", "Critical"]
    counts = {s: {"total": 0, "unique": 0} for s in severities}
    high_seen = set()  # BUG: dedup only applied to High
    for ev in events:
        sev = ev.get("severity", "").title()  # Normalizes to title case only
        if sev not in counts:
            # Drop anything not in the list
            continue
        counts[sev]["total"] += 1
        # BUG: Only High is deduplicated; others increment unique per event
        if sev == "High":
            aid = ev.get("alert_id")
            if aid and aid not in high_seen:
                counts[sev]["unique"] += 1
                high_seen.add(aid)
        else:
            counts[sev]["unique"] += 1
    return counts

def write_csv(counts, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["severity", "total_events", "unique_alerts"])
        # Writes in title case and a fixed order
        for sev in ["Critical", "High", "Medium", "Low"]:
            data = counts.get(sev, {"total": 0, "unique": 0})
            w.writerow([sev, data["total"], data["unique"]])


def main():
    events = load_events("input/logs/events.jsonl")
    counts = aggregate(events)
    write_csv(counts, "output/before_summary.csv")

if __name__ == "__main__":
    main()
