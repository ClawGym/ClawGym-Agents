import json
import os
import unittest

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=os.path.dirname(__file__) or ".", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    tests_run = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passes = tests_run - failures - errors

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "tests_run": tests_run,
            "failures": failures,
            "errors": errors,
            "passes": passes
        }, f, indent=2)

    print(f"Wrote summary to {out_path}")
