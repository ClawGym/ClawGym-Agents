import os
import sys
import unittest

# Ensure src/ is on the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from math_utils import is_prime, factorial, mean


class TestMathUtils(unittest.TestCase):
    def test_is_prime_small(self):
        self.assertFalse(is_prime(1))
        self.assertTrue(is_prime(2))
        self.assertTrue(is_prime(13))
        self.assertFalse(is_prime(9))

    def test_is_prime_even(self):
        for n in [4, 6, 8, 10, 12, 14]:
            self.assertFalse(is_prime(n))

    def test_factorial_base(self):
        self.assertEqual(factorial(0), 1)
        self.assertEqual(factorial(5), 120)

    def test_factorial_invalid(self):
        with self.assertRaises(ValueError):
            factorial(-1)

    def test_mean_integers(self):
        self.assertAlmostEqual(mean([1, 2, 3, 4]), 2.5)

    def test_mean_floats_and_ints(self):
        self.assertAlmostEqual(mean([1, 2.0, 3.0]), 2.0)
        with self.assertRaises(ValueError):
            mean([])


if __name__ == '__main__':
    unittest.main()
