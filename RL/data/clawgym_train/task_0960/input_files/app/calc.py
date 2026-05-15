import json
import os


def load_scale():
    """Load the letter-to-points grading scale from the config directory."""
    here = os.path.dirname(__file__)
    # BUG: wrong filename; the actual file is grading.json
    path = os.path.join(here, '..', 'config', 'grades.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def letter_to_points(letter, scale=None):
    if scale is None:
        scale = load_scale()
    key = str(letter).strip().upper()
    return float(scale[key])


def weighted_gpa(courses, scale=None):
    """
    Compute GPA from a list of courses, each like {'grade': 'A', 'units': 4}.
    Returns a rounded GPA to 2 decimals.
    """
    if scale is None:
        scale = load_scale()
    if not courses:
        return 0.0
    # BUG: incorrectly divides by len(courses) instead of total units
    total_points = 0.0
    for c in courses:
        pts = letter_to_points(c.get('grade'), scale)
        total_points += pts
    gpa = total_points / len(courses)
    return round(gpa, 2)
