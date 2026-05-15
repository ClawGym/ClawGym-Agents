import argparse
import csv
import json
import os
from collections import Counter, defaultdict

STATUSES = ["todo", "in_progress", "done", "blocked"]

def compute_summary(csv_path: str) -> dict:
    by_status = Counter({s: 0 for s in STATUSES})
    by_assignee = defaultdict(int)
    total = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            status = (row.get("status") or "").strip()
            assignee = (row.get("assignee") or "").strip()
            if status in STATUSES:
                by_status[status] += 1
            else:
                # Count unknown statuses under 'todo' to avoid crashing, but keep keys stable
                by_status["todo"] += 1
            if assignee:
                by_assignee[assignee] += 1
    # Ensure all status keys exist
    for s in STATUSES:
        by_status.setdefault(s, 0)
    return {
        "total_tasks": total,
        "by_status": dict(by_status),
        "by_assignee": dict(by_assignee),
    }

def main():
    parser = argparse.ArgumentParser(description="Summarize volunteer tasks")
    parser.add_argument("--in", dest="inp", required=True, help="Path to tasks.csv")
    parser.add_argument("--out", dest="out", required=True, help="Path to write summary.json")
    args = parser.parse_args()
    summary = compute_summary(args.inp)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)

if __name__ == "__main__":
    main()
