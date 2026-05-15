"""
Quick and dirty script I wrote to see how much Far Cry I played.
Probably needs cleanup.

Assumes CSV file "input/sessions.csv" exists with columns:
date,game_title,franchise,minutes
"""

import csv
from collections import defaultdict

CSV_PATH = "input/sessions.csv"

# NOTE: This was hacked together. It prints rough averages for Far Cry titles
# but doesn't save anything or compute medians, and uses integer division.

def go():
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                r["minutes"] = int(r.get("minutes", "0"))
            except ValueError:
                r["minutes"] = 0
            rows.append(r)

    sums = defaultdict(int)
    counts = defaultdict(int)

    for r in rows:
        # Only look at Far Cry, but this is hard-coded and a bit brittle
        if "Far Cry" in r.get("franchise", ""):
            key = (r.get("game_title") or "").strip()
            sums[key] += r.get("minutes", 0)
            counts[key] += 1

    print("Far Cry stats (rough):")
    for k in sums:
        avg = 0
        if counts[k] != 0:
            # integer average; not ideal
            avg = sums[k] // counts[k]
        print(k, "minutes:", sums[k], "sessions:", counts[k], "avg:", avg)

if __name__ == "__main__":
    go()
