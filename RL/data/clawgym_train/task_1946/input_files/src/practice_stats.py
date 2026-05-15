import sys
import csv

# Quick-and-dirty script to total practice minutes by student.
# NOTE: I slapped this together and haven't cleaned it up.

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python src/practice_stats.py <logs_csv> <students_csv>")
        sys.exit(1)

    logs_csv = sys.argv[1]
    students_csv = sys.argv[2]

    students = {}
    with open(students_csv, newline="") as sf:
        r = csv.DictReader(sf)
        for row in r:
            students[row.get("student_id")] = row.get("student_name")

    totals = {}
    count = 0
    with open(logs_csv, newline="") as lf:
        r = csv.DictReader(lf)
        for row in r:
            # BUG: our data uses 'minutes', not 'duration_minutes'.
            m = int(row["duration_minutes"])  # This will raise KeyError on the provided data.
            sid = row["student_id"]
            totals[sid] = totals.get(sid, 0) + m
            count += 1

    print("Read rows:", count)
    print("Totals by student:")
    for sid, total in totals.items():
        nm = students.get(sid, "Unknown")
        print(sid, nm, total)
