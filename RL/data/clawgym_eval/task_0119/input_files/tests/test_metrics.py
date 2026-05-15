import unittest
from analysis.metrics import compute_metrics

class TestMetrics(unittest.TestCase):
    def test_compute_metrics_values(self):
        m = compute_metrics('data/observations.csv')
        # Expected mean: (0.8 + 0.6 + 1.0 + -0.2 + 0.4) / 5 = 0.52
        self.assertAlmostEqual(m['mean_temp_anomaly'], 0.52, places=2)
        # Expected delta: last - first = 119 - 120 = -1
        self.assertEqual(m['species_richness_delta'], -1)

if __name__ == '__main__':
    unittest.main()
