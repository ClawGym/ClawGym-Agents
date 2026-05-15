#!/usr/bin/env python3
import os
import json
import csv
from datetime import datetime

"""
A small script to build a timeline of Baroness Helene von Vetsera from a CSV.
Current issues (to be fixed):
- Uses wrong configuration keys for input and output paths.
- Crashes on invalid date entries due to lack of error handling.
"""

def main():
    config_path = os.path.join("input", "config", "site.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # BUG: wrong configuration keys
    csv_path = config["input_path"]  # should reference the correct key in config
    out_dir = config["output_dir"]   # expects a directory, but config provides a file path
    out_file = os.path.join(out_dir, "timeline.json")

    if not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    events = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # BUG: no error handling for bad date values
            dt = datetime.strptime(row["date"], config["date_format"])  # crashes if date is invalid
            events.append({
                "date": dt.strftime("%Y-%m-%d"),
                "title": row.get("title", "").strip(),
                "notes": row.get("notes", "").strip()
            })

    events.sort(key=lambda e: e["date"])  # sort by ISO date string

    payload = {
        "events": events,
        "event_count": len(events)
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
