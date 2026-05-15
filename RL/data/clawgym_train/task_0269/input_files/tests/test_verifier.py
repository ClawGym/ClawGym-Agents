import os
import json
import unittest

# Ensure import works when running tests from project root
from tools.verify_claims import main as run_verifier, REPORT_PATH


class TestVerifier(unittest.TestCase):
    def test_report_counts_and_supported_claim(self):
        # Run the verifier; requires correct config field mapping
        run_verifier()
        self.assertTrue(os.path.exists(REPORT_PATH), 'verification_report.json was not created')
        with open(REPORT_PATH, 'r', encoding='utf-8') as f:
            results = json.load(f)
        counts = {}
        for r in results:
            counts[r['status']] = counts.get(r['status'], 0) + 1
        # Expected based on the provided inputs
        self.assertEqual(counts.get('supported', 0), 1)
        self.assertEqual(counts.get('contradicted', 0), 3)
        self.assertEqual(counts.get('not_found', 0), 1)
        self.assertEqual(counts.get('insufficient', 0), 0)

        # Check that claim c1 is supported and evidence matches SKU 2281
        c1 = next((r for r in results if r.get('claim_id') == 'c1'), None)
        self.assertIsNotNone(c1, 'c1 result missing')
        self.assertEqual(c1['status'], 'supported')
        self.assertEqual(c1['evidence']['sku'], '2281')
        self.assertEqual(c1['evidence']['intro_year'], 1999)
        self.assertEqual(c1['evidence']['retire_year'], 2003)
        self.assertEqual(c1['evidence']['line'], 'Boyds Bears')


if __name__ == '__main__':
    unittest.main()
