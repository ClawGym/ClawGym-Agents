import unittest

from climate_tools.emissions import compute_net_emissions, compute_carbon_budget


class TestEmissions(unittest.TestCase):
    def test_basic_net_emissions(self):
        self.assertEqual(compute_net_emissions([10, 5], [3]), 12)

    def test_zero_offsets(self):
        self.assertEqual(compute_net_emissions([0, 0], [0, 0]), 0)

    def test_carbon_budget(self):
        self.assertEqual(compute_carbon_budget(100.0, 70.5), 29.5)


if __name__ == "__main__":
    unittest.main()
