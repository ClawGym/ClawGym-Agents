import os
import sys
import unittest

# Ensure the src/ directory is on the path regardless of CWD
CURRENT_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..', 'src'))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import math_utils as mu


class TestMathUtils(unittest.TestCase):
    def test_add(self):
        self.assertEqual(mu.add(2, 3), 5)
        self.assertAlmostEqual(mu.add(-1.5, 1.5), 0.0, places=7)

    def test_subtract(self):
        self.assertEqual(mu.subtract(5, 3), 2)
        self.assertEqual(mu.subtract(-2, -5), 3)

    def test_mean_basic(self):
        self.assertEqual(mu.mean([2, 4, 6]), 4)
        self.assertAlmostEqual(mu.mean([0.5, 1.5]), 1.0, places=7)

    def test_mean_empty(self):
        with self.assertRaises(ValueError):
            mu.mean([])


if __name__ == '__main__':
    unittest.main(verbosity=2)
