import argparse
import csv
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return {
        "include_herbs": cfg.get("include_herbs", []),
        "grams_unit": cfg.get("grams_unit", "g"),
    }


def iso_week_monday(date_str):
    dt = datetime.fromisoformat(date_str).date()
    monday = dt - timedelta(days=dt.weekday())  # Monday = 0
    return monday.isoformat()


def load_borrows_csv(path):
    records = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                "date": row["date"].strip(),
                "borrower": row["borrower"].strip(),
                "herb": row["herb"].strip(),
                "grams": float(row["grams"]),
            })
    return records


def compute_weekly_borrows(records, include_herbs):
    """
    TODO: Group by ISO week (Monday-based). For each record, compute the Monday date for its week
    and use that as week_start. If include_herbs is non-empty, only include records whose 'herb'
    is in include_herbs. Sum grams per (week_start, borrower, herb) and return a list of dicts with
    keys: week_start, borrower, herb, total_grams (float).
    """
    raise NotImplementedError("compute_weekly_borrows is not implemented yet")


def write_csv(rows, path):
    fieldnames = ["week_start", "borrower", "herb", "total_grams"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})


def write_json(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, sort_keys=True)


def main():
    ap = argparse.ArgumentParser(description="HerbShare weekly summary prototype")
    ap.add_argument("--config", required=True, help="Path to config JSON (e.g., config/herbshare.json)")
    ap.add_argument("--input", required=True, help="Path to data/herb_borrows.csv")
    ap.add_argument("--out-csv", required=True, help="Path to write weekly CSV summary")
    ap.add_argument("--out-json", required=True, help="Path to write weekly JSON summary")
    args = ap.parse_args()

    cfg = load_config(args.config)
    records = load_borrows_csv(args.input)
    rows = compute_weekly_borrows(records, cfg["include_herbs"])

    write_csv(rows, args.out_csv)
    write_json(rows, args.out_json)


if __name__ == "__main__":
    main()
