#!/usr/bin/env python3
import json
import os
import sys

# Make sure we can import the app module from the project directory
sys.path.insert(0, os.path.join(os.getcwd(), 'project'))
import app  # noqa: E402


def run_tests():
    cases = []
    total = 2
    passed = 0

    # Case 1
    try:
        assert app.add(2, 3) == 5
        cases.append({"name": "add positive numbers", "status": "passed"})
        passed += 1
    except AssertionError:
        cases.append({"name": "add positive numbers", "status": "failed"})

    # Case 2
    try:
        assert app.add(-1, 1) == 0
        cases.append({"name": "add negative and positive", "status": "passed"})
        passed += 1
    except AssertionError:
        cases.append({"name": "add negative and positive", "status": "failed"})

    results = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "cases": cases
    }

    os.makedirs('out', exist_ok=True)
    with open(os.path.join('out', 'test_results.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results))


if __name__ == '__main__':
    run_tests()
