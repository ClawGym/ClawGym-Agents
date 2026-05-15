import argparse
import json
import csv
import os
import sys

"""
Prototype script to calculate employer costs for health plans.
NOTE: This script contains intentional key name mistakes to emulate an early prototype.
The agent should run it, read the error output, fix the key references, and rerun.
"""

def main():
    parser = argparse.ArgumentParser(description="Compute employer monthly costs for health plans")
    parser.add_argument("--plans", required=True, help="Path to plans JSON file")
    parser.add_argument("--company", required=True, help="Path to company profile JSON file")
    parser.add_argument("--out", required=True, help="Path to output CSV file")
    args = parser.parse_args()

    try:
        with open(args.plans, "r", encoding="utf-8") as f:
            plans = json.load(f)
        with open(args.company, "r", encoding="utf-8") as f:
            company = json.load(f)
    except Exception as e:
        print(f"Failed to load input files: {e}", file=sys.stderr)
        sys.exit(1)

    # Intentional mistakes to trigger KeyError and guide debugging
    emp_count = company["employees"]  # should be 'employee_count'
    budget = company["monthly_benefits_budget"]
    prefs = company["preferences"]

    rows = []
    for p in plans:
        monthly = p["employee_premium_monthly"]  # should be 'monthly_premium_employee'
        employer_share = p["employer_share"]      # should be 'employer_share_percent'
        monthly_employer_cost_per_employee = monthly * (employer_share / 100.0)
        total = monthly_employer_cost_per_employee * emp_count
        meets_budget = total <= budget
        meets_preferences = (p["deductible"] <= prefs["max_deductible"] and p["network_size"] >= prefs["min_network_size"])
        rows.append([
            p["plan_id"],
            p["name"],
            monthly,
            employer_share,
            monthly_employer_cost_per_employee,
            total,
            meets_budget,
            meets_preferences,
        ])

    headers = [
        "plan_id",
        "name",
        "monthly_premium_employee",
        "employer_share_percent",
        "monthly_employer_cost_per_employee",
        "total_monthly_employer_cost",
        "meets_budget",
        "meets_preferences",
    ]

    outdir = os.path.dirname(args.out)
    if outdir and not os.path.exists(outdir):
        os.makedirs(outdir, exist_ok=True)

    try:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
    except Exception as e:
        print(f"Failed to write CSV: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote {len(rows)} rows to {args.out}")

if __name__ == "__main__":
    main()
