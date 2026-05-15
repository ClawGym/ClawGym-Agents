import csv
import json
import os
import statistics

def main():
    input_path = os.path.join("input", "pto_snapshot.csv")
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    pto_used = [float(r["pto_used_hours_ytd"]) for r in rows]
    future_days = [int(r["future_days_booked"]) for r in rows]

    avg_pto = round(sum(pto_used)/total, 1) if total else 0.0
    med_pto = round(statistics.median(pto_used), 1) if total else 0.0
    with_future = sum(1 for d in future_days if d > 0)
    percent_future = int(round((with_future/total)*100)) if total else 0

    summary = {
        "total_associates": total,
        "avg_pto_used_hours": avg_pto,
        "median_pto_used_hours": med_pto,
        "percent_with_future_days_booked": percent_future
    }

    out_path = os.path.join(out_dir, "pto_summary.json")
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(summary, out, indent=2)

if __name__ == "__main__":
    main()
