import argparse
import json
import csv
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Simple content schedule generator")
    parser.add_argument("--config", required=True, help="Path to campaign_config.json")
    parser.add_argument("--drafts", required=True, help="Path to drafts.csv")
    parser.add_argument("--out", required=True, help="Output path for schedule CSV")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Expect 'timezone' (intentional: will raise KeyError with current config)
    tz = cfg["timezone"]
    day_themes = cfg.get("day_themes", {})

    rows = []
    with open(args.drafts, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Validate date format
            dt = datetime.fromisoformat(r["intended_date"])  # raises if bad format
            # Weekday name computed but not used yet
            weekday_name = dt.strftime("%A")

            rows.append({
                "id": r["id"],
                "intended_date": r["intended_date"],
                "platform": r["platform"],
                "timezone": tz
                # 'theme' intentionally omitted; you will add it per task
            })

    fieldnames = ["id", "intended_date", "platform", "timezone"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.out}")

if __name__ == "__main__":
    main()
