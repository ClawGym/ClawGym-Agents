#!/usr/bin/env python3
import json
import os
import re
import sys

def main():
    config_path = os.path.join("config", "checks.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"CONFIG ERROR: Missing {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"CONFIG ERROR: JSON parse error at line {e.lineno} col {e.colno}: {e.msg}")
        sys.exit(1)

    errors = []

    # python_version must be a string like '3.10'
    if "python_version" not in data:
        errors.append("Missing key 'python_version' (e.g., '3.10').")
    else:
        pv = data["python_version"]
        if not isinstance(pv, str) or re.fullmatch(r"\d+\.\d+", pv) is None:
            errors.append(
                f"Invalid value for python_version: expected string like '3.10', got {type(pv).__name__}={pv!r}."
            )

    # formatting.line_length must be an int between 60 and 120
    if not isinstance(data.get("formatting"), dict):
        errors.append("Missing object 'formatting' with key 'line_length' (int 60-120).")
    else:
        fmt = data["formatting"]
        if "line_length" not in fmt:
            errors.append("Missing key 'formatting.line_length' (int 60-120).")
        else:
            ll = fmt["line_length"]
            if not isinstance(ll, int):
                errors.append(
                    f"Invalid type for formatting.line_length: expected int, got {type(ll).__name__}."
                )
            elif not (60 <= ll <= 120):
                errors.append(
                    f"Invalid value for formatting.line_length: {ll} (must be between 60 and 120)."
                )

    # tests.enabled (bool) and tests.min_coverage (int 0-100)
    if not isinstance(data.get("tests"), dict):
        errors.append(
            "Missing object 'tests' with keys 'enabled' (bool) and 'min_coverage' (int 0-100)."
        )
    else:
        tests = data["tests"]
        if "enabled" not in tests:
            errors.append("Missing key 'tests.enabled' (bool).")
        else:
            en = tests["enabled"]
            if not isinstance(en, bool):
                errors.append(
                    f"Invalid type for tests.enabled: expected bool, got {type(en).__name__}."
                )
        if "min_coverage" not in tests:
            errors.append("Missing key 'tests.min_coverage' (int 0-100).")
        else:
            mc = tests["min_coverage"]
            if not isinstance(mc, int):
                errors.append(
                    f"Invalid type for tests.min_coverage: expected int, got {type(mc).__name__}."
                )
            elif not (0 <= mc <= 100):
                errors.append(
                    f"Invalid value for tests.min_coverage: {mc} (must be 0-100)."
                )

    if errors:
        print("CONFIG ERRORS:")
        for e in errors:
            print(f"- {e}")
        print("Fix the issues in config/checks.json and re-run this script.")
        sys.exit(1)

    print("All checks passed.")
    print(f"python_version={data['python_version']}")
    print(f"formatting.line_length={data['formatting']['line_length']}")
    print(f"tests.enabled={data['tests']['enabled']}")
    print(f"tests.min_coverage={data['tests']['min_coverage']}")
    sys.exit(0)

if __name__ == "__main__":
    main()
