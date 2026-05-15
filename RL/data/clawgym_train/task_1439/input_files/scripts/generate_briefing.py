#!/usr/bin/env python3
import argparse
import json
import csv
import sys
import os
from datetime import datetime, timedelta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to briefing config JSON")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Expected keys; will raise KeyError if misconfigured
    input_csv = cfg["input_csv_path"]
    output_json = cfg["output_json_path"]
    reference_date_str = cfg["reference_date"]
    run_time = cfg.get("run_time", "06:00")

    try:
        ref_dt = datetime.strptime(reference_date_str, "%Y-%m-%d")
    except ValueError:
        print(
            f"Invalid reference_date format: {reference_date_str}. Expected YYYY-MM-DD.",
            file=sys.stderr,
        )
        raise

    target_date = (ref_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    tours = []
    with open(input_csv, newline="", encoding="utf-8") as cf:
        reader = csv.DictReader(cf)
        for row in reader:
            if row.get("date") == target_date:
                tours.append(
                    {
                        "time": row.get("time"),
                        "theme": row.get("theme"),
                        "location": row.get("location"),
                        "survivor_present": str(row.get("survivor_present", "")).strip().lower()
                        in ("true", "yes", "y", "1"),
                        "max_attendees": int(row.get("max_attendees") or 0),
                        "notes": row.get("notes", ""),
                    }
                )

    result = {"date": target_date, "tours": sorted(tours, key=lambda t: t["time"] or "")}

    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)

    print(
        f"Wrote briefing to {output_json} ({len(result['tours'])} tours for {target_date})."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Let full traceback surface so it appears in captured logs
        raise
