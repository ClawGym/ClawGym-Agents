#!/usr/bin/env python3
import json, csv, os
from datetime import datetime, timedelta


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%H:%M")


def fmt_time(t: datetime) -> str:
    return t.strftime("%H:%M")


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_json("config/schedule.json")
    staff = load_json("data/staff.json")["staff"]

    date = cfg["date"]
    k_start = parse_time(cfg["kitchen_hours"]["start"])
    k_end = parse_time(cfg["kitchen_hours"]["end"])

    # Baseline: naive assignment by preferred window start; chooses first eligible staff.
    # This version DOES NOT enforce breaks, overlap checks, or strict availability.
    assignments = []
    tasks = cfg["tasks"]
    tasks_sorted = sorted(tasks, key=lambda t: t["preferred_window"]["start"])

    for task in tasks_sorted:
        role = task["required_role"]
        eligible = [s for s in staff if s["role"] == role]
        assignee = eligible[0] if eligible else None

        window_start = parse_time(task["preferred_window"]["start"])
        start = max(
            k_start,
            parse_time(assignee["availability"]["start"]) if assignee else k_start,
            window_start,
        )
        duration = timedelta(minutes=task["duration_minutes"])
        end = start + duration

        assignments.append({
            "date": date,
            "task_id": task["id"],
            "task_name": task["name"],
            "staff_name": assignee["name"] if assignee else "",
            "role": role,
            "start": fmt_time(start),
            "end": fmt_time(end),
            "intensity": task.get("intensity", "light"),
        })

    os.makedirs("output", exist_ok=True)
    with open("output/schedule.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "task_id", "task_name", "staff_name", "role", "start", "end", "intensity"],
        )
        writer.writeheader()
        for row in assignments:
            writer.writerow(row)

    # Note: No validation report is generated in this baseline.
    # You will modify this script to enforce breaks, avoid overlaps, and output a validation report.


if __name__ == "__main__":
    main()
