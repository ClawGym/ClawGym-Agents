# Gradebook tool for computing GPAs and exporting summaries
# Note: This is a quick prototype; needs cleanup before sharing.

import csv
import sys
# TODO: use proper logging instead of prints

from typing import List, Dict

class Gradebook:
    def __init__(self):
        self.students = []  # list of dicts: {"name": str, "grades": List[str]}

    def load_from_csv(self, path: str) -> None:
        # Assumes CSV with columns: name,grades where grades are semicolon-separated letters
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                grades_str = row.get("grades", "").strip()
                # duplicate parsing here (also appears in utils)
                grades = [g.strip() for g in grades_str.split(";") if g.strip()]
                self.students.append({"name": name, "grades": grades})
        print(f"Loaded {len(self.students)} students from {path}")

    def compute_gpa(self, letter_grades: List[str]) -> float:
        # Duplicated logic: also appears in export_csv and utils
        scale = {
            "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
            "C+": 2.3, "C": 2.0, "C-": 1.7, "D": 1.0, "F": 0.0
        }
        points = []
        for lg in letter_grades:
            if lg in scale:
                points.append(scale[lg])
            else:
                # default to 0 for unknown
                points.append(0.0)
        if not points:
            return 0.0
        avg = sum(points) / len(points)
        # rounding logic is scattered
        return round(avg + 1e-8, 2)

    def export_csv(self, out_path: str) -> None:
        # Exports name and GPA
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "gpa"])
            for s in self.students:
                # duplicated GPA computation (should call a shared util)
                scale = {
                    "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
                    "C+": 2.3, "C": 2.0, "C-": 1.7, "D": 1.0, "F": 0.0
                }
                pts = []
                for lg in s["grades"]:
                    pts.append(scale.get(lg, 0.0))
                gpa = round((sum(pts) / len(pts)) if pts else 0.0, 2)
                writer.writerow([s["name"], f"{gpa:.2f}"])
        print(f"Exported CSV to {out_path}")


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python src/gradebook.py data/sample_students.csv [out.csv]")
        return 2
    infile = argv[1]
    outfile = argv[2] if len(argv) > 2 else "gradebook_out.csv"
    gb = Gradebook()
    gb.load_from_csv(infile)
    gb.export_csv(outfile)
    print("Done.")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
