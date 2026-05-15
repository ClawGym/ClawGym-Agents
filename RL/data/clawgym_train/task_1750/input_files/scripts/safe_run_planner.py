#!/usr/bin/env python3
import sys
import os
import csv
import json

def main():
    if len(sys.argv) != 4:
        print("Usage: python3 safe_run_planner.py <runner_plan.csv> <dog_profile.json> <output.csv>")
        sys.exit(1)

    plan_path, profile_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = json.load(f)
    try:
        max_km = float(profile.get('max_suggested_single_run_km', 0))
    except (TypeError, ValueError):
        max_km = 0.0

    intense = {'intervals', 'tempo'}

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(plan_path, 'r', encoding='utf-8') as in_f, open(out_path, 'w', encoding='utf-8', newline='') as out_f:
        reader = csv.DictReader(in_f)
        fieldnames = ['date', 'planned_distance_km', 'intensity', 'can_join', 'reason']
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            date = (row.get('date') or '').strip()
            intensity = (row.get('intensity') or '').strip().lower()
            try:
                dist = float(row.get('planned_distance_km', 0))
            except (TypeError, ValueError):
                dist = 0.0

            if intensity == 'rest' or dist <= 0:
                can_join = False
                reason = 'rest day'
            elif intensity in intense:
                can_join = False
                reason = 'intensity too high'
            elif dist > max_km:
                can_join = False
                reason = 'distance exceeds max'
            else:
                can_join = True
                reason = 'ok'

            writer.writerow({
                'date': date,
                'planned_distance_km': f"{dist:.1f}",
                'intensity': intensity,
                'can_join': 'true' if can_join else 'false',
                'reason': reason
            })

if __name__ == '__main__':
    main()
