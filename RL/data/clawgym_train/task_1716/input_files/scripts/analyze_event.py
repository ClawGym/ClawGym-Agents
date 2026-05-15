#!/usr/bin/env python3
import csv
import json
import os
import collections

# NOTE: This script currently mis-parses inputs and writes to the wrong folder.
# Please fix it to produce correct aggregates and notes under output/.

def load_restaurants(path="data/restaurants.jsonl"):
    with open(path, "r", encoding="utf-8") as f:
        # BUG: restaurants.jsonl is JSON Lines, not a single JSON object/array
        return json.load(f)  # expects a JSON array and will fail


def load_invites(path="data/invitations.csv"):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        # BUG: wrong delimiter; file uses ';'
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def main():
    restaurants = load_restaurants()
    region_by_restaurant = {r["id"]: r["region"] for r in restaurants}
    country_by_restaurant = {r["id"]: r.get("country") for r in restaurants}

    invites = load_invites()

    totals = collections.Counter()
    by_region = {}

    for r in invites:
        status = r.get("status", "").lower()
        if status == "yes":
            totals["yes"] += 1
        elif status == "no":
            totals["no"] += 1
        elif status == "maybe":
            totals["maybe"] += 1
        else:
            totals["no_response"] += 1

        rid = r.get("restaurant_id")
        region = region_by_restaurant.get(rid, "UNKNOWN")
        reg = by_region.setdefault(region, collections.Counter())
        if status == "yes":
            reg["yes"] += 1
        elif status == "no":
            reg["no"] += 1
        elif status == "maybe":
            reg["maybe"] += 1
        else:
            reg["no_response"] += 1

    # BUG: should use unique emails after deduplication by latest timestamp, not raw rows
    totals["invited"] = len(invites)

    # BUG: wrong output directory name and incomplete notes
    outdir = "outputs"
    os.makedirs(outdir, exist_ok=True)
    stats_path = os.path.join(outdir, "stats.json")
    notes_path = os.path.join(outdir, "meeting_notes.md")

    stats = {
        "totals": dict(totals),
        "by_region": {k: dict(v) for k, v in by_region.items()},
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    with open(notes_path, "w", encoding="utf-8") as f:
        f.write("Board Prep Notes\n")
        f.write(f"Invited: {totals['invited']}\n")


if __name__ == "__main__":
    main()
