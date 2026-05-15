# Utility functions (some not consistently used)
from typing import List

# TODO: consolidate GPA calculation and remove duplication with gradebook.py

def parse_grade_list(grades_str: str) -> List[str]:
    # Inconsistently used; similar parsing exists in gradebook.load_from_csv
    return [g.strip() for g in grades_str.split(";") if g.strip()]

# This mapping duplicates logic in gradebook
LETTER_POINTS = {
    "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7, "D": 1.0, "F": 0.0
}

def letter_to_points(letter: str) -> float:
    return LETTER_POINTS.get(letter, 0.0)

# Unused helper
def average(nums: List[float]) -> float:
    return (sum(nums) / len(nums)) if nums else 0.0
