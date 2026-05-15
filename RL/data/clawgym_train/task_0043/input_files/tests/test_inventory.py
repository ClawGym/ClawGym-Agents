import json
import re
import unittest

class TestInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open('data/inventory.json', 'r', encoding='utf-8') as f:
            cls.items = json.load(f)
        cls.available = [x for x in cls.items if x.get('status') == 'available']

    def test_designer_caps(self):
        for item in self.available:
            with self.subTest(sku=item.get('sku')):
                self.assertEqual(item.get('designer'), 'HVRMINN', f"Designer must be 'HVRMINN' for {item.get('sku')}")

    def test_decade(self):
        for item in self.available:
            with self.subTest(sku=item.get('sku')):
                self.assertEqual(item.get('decade'), '1980s', f"Decade must be '1980s' for {item.get('sku')}")

    def test_sku_format(self):
        pattern = re.compile(r'^HV-198[0-9]-[A-Z0-9]{4}$')
        for item in self.available:
            with self.subTest(sku=item.get('sku')):
                sku = item.get('sku') or ''
                self.assertTrue(bool(pattern.match(sku)), f"Invalid SKU format: {sku}")

if __name__ == '__main__':
    unittest.main(verbosity=2)
