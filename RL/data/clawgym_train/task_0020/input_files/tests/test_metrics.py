import unittest
from app.metrics import compute_tss

class TestMetrics(unittest.TestCase):
    def test_basic(self):
        # 60 min at FTP => TSS 100
        self.assertAlmostEqual(compute_tss(60, 250, 250), 100.0, places=5)

    def test_zero_duration(self):
        self.assertAlmostEqual(compute_tss(0, 200, 250), 0.0, places=5)

    def test_low_intensity(self):
        # 120 min at 60% FTP => 120/60 * 0.6^2 * 100 = 2 * 0.36 * 100 = 72
        self.assertAlmostEqual(compute_tss(120, 0.6*300, 300), 72.0, places=5)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            compute_tss(-10, 200, 250)
        with self.assertRaises(ValueError):
            compute_tss(60, -1, 250)
        with self.assertRaises(ValueError):
            compute_tss(60, 200, 0)

if __name__ == "__main__":
    unittest.main()
