#!/usr/bin/env python3
import csv
import json
import sys
import argparse
from datetime import datetime

def is_valid_date(s: str):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def main():
    ap = argparse.ArgumentParser(description="Generate reminders from agenda and attendees.")
    ap.add_argument("--agenda", default="input/agenda_2026-04-20.csv", help="Path to agenda CSV")
    ap.add_argument("--attendees", default="input/attendees.json", help="Path to attendees JSON")
    args = ap.parse_args()

    try:
        with open(args.attendees, "r", encoding="utf-8") as f:
            attendees_list = json.load(f)
    except Exception as e:
        sys.stderr.write(f"ERROR failed_to_load_attendees {e}\n")
        sys.exit(1)

    emails = {a.get("name", ""): (a.get("email") or "").strip() for a in attendees_list}

    try:
        fh = open(args.agenda, "r", encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"ERROR failed_to_load_agenda {e}\n")
        sys.exit(1)

    warn_counts = {"UNKNOWN_OWNER": 0, "MISSING_DUE": 0, "NO_EMAIL": 0}
    ok_count = 0

    with fh:
        reader = csv.DictReader(fh)
        for row in reader:
            item_id = (row.get("item_id") or "").strip()
            owner = (row.get("owner") or "").strip()
            due = (row.get("due_date") or "").strip()
            topic = (row.get("topic") or "").strip()

            if owner not in emails:
                sys.stderr.write(f"WARN UNKNOWN_OWNER {item_id} {owner}\n")
                warn_counts["UNKNOWN_OWNER"] += 1
                continue

            email = emails.get(owner, "")
            if (not due) or (due.upper() == "TBD") or (not is_valid_date(due)):
                sys.stderr.write(f"WARN MISSING_DUE {item_id} {owner}\n")
                warn_counts["MISSING_DUE"] += 1

            if not email:
                sys.stderr.write(f"WARN NO_EMAIL {item_id} {owner}\n")
                warn_counts["NO_EMAIL"] += 1

            if email and due and due.upper() != "TBD" and is_valid_date(due):
                sys.stdout.write(f"REMINDER,{item_id},{owner},{due},{topic}\n")
                ok_count += 1

    total_warn = warn_counts["UNKNOWN_OWNER"] + warn_counts["MISSING_DUE"] + warn_counts["NO_EMAIL"]
    sys.stderr.write(
        f"SUMMARY reminders={ok_count} warnings_total={total_warn} "
        f"UNKNOWN_OWNER={warn_counts['UNKNOWN_OWNER']} "
        f"MISSING_DUE={warn_counts['MISSING_DUE']} "
        f"NO_EMAIL={warn_counts['NO_EMAIL']}\n"
    )

if __name__ == "__main__":
    main()
