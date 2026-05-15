import json
import os
import sys

# Make sure the project root is in sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import calc  # noqa


def run():
    results = []
    # Test 1: add positive numbers
    try:
        ok = (calc.add(1, 2) == 3)
        results.append({"name": "add_positive", "passed": bool(ok), "message": "ok" if ok else "expected 3"})
    except Exception as e:
        results.append({"name": "add_positive", "passed": False, "message": f"exception: {e}"})

    # Test 2: add resulting in zero
    try:
        ok = (calc.add(-1, 1) == 0)
        results.append({"name": "add_zero_sum", "passed": bool(ok), "message": "ok" if ok else "expected 0"})
    except Exception as e:
        results.append({"name": "add_zero_sum", "passed": False, "message": f"exception: {e}"})

    # Test 3: environment is prod
    env_val = os.environ.get('APP_ENV')
    is_prod = (env_val == 'prod')
    results.append({"name": "env_is_prod", "passed": bool(is_prod), "message": "ok" if is_prod else "APP_ENV must be 'prod'"})

    tests_run = len(results)
    tests_passed = sum(1 for r in results if r['passed'])
    tests_failed = tests_run - tests_passed

    payload = {
        "env": {"APP_ENV": env_val},
        "results": results,
        "summary": {
            "tests_run": tests_run,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed
        }
    }

    out_path = os.path.join(ROOT, 'output', 'test_results.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

    return 0 if tests_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(run())
