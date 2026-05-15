import csv
import json
import os
from collections import defaultdict

def load_config(path="config/newsletter_config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_rows(csv_path="input/data/constituent_contacts.csv"):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

def ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def month_key(datestr):
    # Expecting YYYY-MM-DD
    return datestr[:7]

def main():
    cfg = load_config()
    rows = read_rows()

    # Filter by region if configured
    region = cfg.get("region_filter", "All")
    if region and region != "All":
        rows = [r for r in rows if r.get("region") == region]

    # Current behavior: only compute total monthly counts and write to summary_path
    monthly_counts = defaultdict(int)
    for r in rows:
        m = month_key(r.get("date", ""))
        if m:
            monthly_counts[m] += 1

    out_summary = cfg.get("summary_path", "output/summary.csv")
    ensure_dir(out_summary)
    with open(out_summary, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "total_contacts"]) 
        for m in sorted(monthly_counts.keys()):
            w.writerow([m, monthly_counts[m]])

if __name__ == "__main__":
    main()
