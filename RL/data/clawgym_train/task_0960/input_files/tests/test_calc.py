import os
import sys
import unittest

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.calc import weighted_gpa


class TestCalc(unittest.TestCase):
    def test_weighted_gpa_basic(self):
        courses = [
            {"grade": "A", "units": 4},
            {"grade": "B+", "units": 3},
            {"grade": "A-", "units": 2},
        ]
        # (4.0*4 + 3.3*3 + 3.7*2) / 9 = 3.70
        self.assertAlmostEqual(weighted_gpa(courses), 3.70, places=2)

    def test_case_insensitive(self):
        courses = [
            {"grade": "a", "units": 4},
            {"grade": "b", "units": 4},
        ]
        # (4.0*4 + 3.0*4) / 8 = 3.50
        self.assertAlmostEqual(weighted_gpa(courses), 3.50, places=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
