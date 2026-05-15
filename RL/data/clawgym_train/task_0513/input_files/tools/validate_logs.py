import sys
import csv
from datetime import datetime

USAGE = "Usage: python validate_logs.py <path_to_csv>"

TIME_FIELDS = ["scheduled_departure", "scheduled_arrival", "actual_departure", "actual_arrival"]
REQUIRED_FIELDS = [
    "record_id","date","train_id","locomotive_class","origin","destination",
    "scheduled_departure","actual_departure","scheduled_arrival","actual_arrival","distance_miles"
]

def parse_time(t):
    return datetime.strptime(t, "%H:%M")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(USAGE)
        sys.exit(1)
    path = sys.argv[1]
    errors = 0
    rows = 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows += 1
                rid = row.get("record_id", "")
                problems = []

                # Required fields present
                for field in REQUIRED_FIELDS:
                    if (row.get(field) is None) or (str(row.get(field)).strip() == ""):
                        problems.append(f"missing required field: {field}")

                # Time format checks
                times = {}
                if not problems:
                    for field in TIME_FIELDS:
                        try:
                            times[field] = parse_time(row[field])
                        except Exception:
                            problems.append(f"invalid time format in {field}: '{row[field]}'")

                # Logical time order checks
                if not problems and all(k in times for k in TIME_FIELDS):
                    if times["scheduled_arrival"] <= times["scheduled_departure"]:
                        problems.append("scheduled_arrival is not after scheduled_departure")
                    if times["actual_arrival"] < times["actual_departure"]:
                        problems.append("actual_arrival is before actual_departure")

                # Distance checks
                if (row.get("distance_miles") is not None) and (str(row.get("distance_miles")).strip() != ""):
                    try:
                        dist = float(row["distance_miles"])
                        if dist <= 0:
                            problems.append("distance_miles must be > 0")
                    except Exception:
                        problems.append(f"distance_miles not numeric: '{row['distance_miles']}'")

                # Emit errors
                for p in problems:
                    print(f"ERROR record_id={rid}: {p}")
                    errors += 1
        print(f"VALIDATION COMPLETE: {rows} rows checked, {errors} errors")
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}")
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: unexpected exception: {e}")
        sys.exit(3)
