import csv
import json
import os
from collections import Counter

SCRIPT_VERSION = "1.0.0"

INPUT_EVENTS = os.path.join("input", "community_events.csv")
INPUT_CAR = os.path.join("input", "car_help_log.csv")
DERIVED_DIR = os.path.join("derived")
OUTPUT_METRICS = os.path.join(DERIVED_DIR, "metrics.json")

def read_events(path):
    total_hours = 0.0
    total_events = 0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                hours = float(row.get("hours_contributed", 0) or 0)
            except ValueError:
                hours = 0.0
            total_hours += hours
            total_events += 1
    return total_hours, total_events


def read_car_help(path):
    task_type_counts = Counter()
    helper_counts = Counter()
    total_tasks = 0
    total_parts_cost = 0.0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_tasks += 1
            task = row.get("task_type", "").strip()
            helper = row.get("helper_name", "").strip()
            task_type_counts[task] += 1
            helper_counts[helper] += 1
            try:
                cost = float(row.get("parts_cost", 0) or 0)
            except ValueError:
                cost = 0.0
            total_parts_cost += cost
    return total_tasks, round(total_parts_cost, 2), dict(task_type_counts), dict(helper_counts)


def main():
    hours, n_events = read_events(INPUT_EVENTS)
    total_tasks, parts_cost, task_counts, helper_counts = read_car_help(INPUT_CAR)

    # Determine top task type
    if task_counts:
        top_name, top_count = max(task_counts.items(), key=lambda kv: kv[1])
    else:
        top_name, top_count = None, 0

    metrics = {
        "script_version": SCRIPT_VERSION,
        "totals": {
            "community_hours": round(hours, 2),
            "events": n_events,
            "car_tasks": total_tasks,
            "parts_cost": parts_cost
        },
        "task_type_counts": task_counts,
        "helper_counts": helper_counts,
        "top_task_type": {
            "name": top_name,
            "count": top_count
        }
    }

    os.makedirs(DERIVED_DIR, exist_ok=True)
    with open(OUTPUT_METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print(f"Wrote metrics to {OUTPUT_METRICS}")

if __name__ == "__main__":
    main()
