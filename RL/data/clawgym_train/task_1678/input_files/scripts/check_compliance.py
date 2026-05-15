import json
import csv
import os
from collections import defaultdict


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_items_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "item_id": r["item_id"].strip(),
                "item_name": r["item_name"].strip(),
                "supplier_id": r["supplier_id"].strip(),
                "distance_miles": float(r["distance_miles"]),
                "claimed_labels": [s.strip() for s in r["claimed_labels"].split(";") if s.strip()]
            })
    return rows


def main():
    policy = load_json("config/policy.json")
    suppliers = {s["supplier_id"]: s for s in load_json("data/suppliers.json")}
    items = load_items_csv("data/items.csv")

    print(f"Loaded {len(items)} items and {len(suppliers)} suppliers.")
    print("Current policy:", policy)

    # Placeholder: This script currently does not implement compliance checks or write reports.
    # Extend it to produce compliance reports per the updated policy.

    os.makedirs("output", exist_ok=True)
    with open("output/README.txt", "w", encoding="utf-8") as f:
        f.write("Placeholder output. Implement compliance reporting as needed.\n")


if __name__ == "__main__":
    main()
