#!/usr/bin/env python3
import json, os, sys

IN_DESIRED = "input/desired_night_settings.json"
IN_MOCK = "input/mock_os_state.json"
OUT_STATE = "output/applied_os_state.json"
OUT_LOG = "output/apply.log"

def load_json(path, name):
    if not os.path.exists(path):
        print(f"FAIL: expected {name} at {path} but not found.")
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"FAIL: could not parse {name} JSON at {path}: {e}")
        sys.exit(2)

def main():
    desired = load_json(IN_DESIRED, "desired settings")
    mock = load_json(IN_MOCK, "mock OS state")
    if not os.path.exists(OUT_STATE):
        print(f"FAIL: expected applied state at {OUT_STATE} but not found.")
        sys.exit(2)
    try:
        with open(OUT_STATE, "r", encoding="utf-8") as f:
            applied = json.load(f)
    except Exception as e:
        print(f"FAIL: could not parse applied state JSON: {e}")
        sys.exit(2)

    # compute expected merged state
    expected = dict(mock)
    for k, v in desired.items():
        expected[k] = v

    # Compare keys and values
    exp_keys = set(expected.keys())
    app_keys = set(applied.keys())
    missing = exp_keys - app_keys
    extra = app_keys - exp_keys
    diffs = []
    for k in sorted(exp_keys & app_keys):
        if applied[k] != expected[k]:
            diffs.append(f"value mismatch for '{k}': expected {expected[k]!r}, got {applied[k]!r}")
    if missing or extra or diffs:
        if missing:
            print("FAIL: applied state missing keys:", ", ".join(sorted(missing)))
        if extra:
            print("FAIL: applied state has unexpected keys:", ", ".join(sorted(extra)))
        for d in diffs:
            print("FAIL:", d)
        sys.exit(3)

    # Validate log content
    if not os.path.exists(OUT_LOG):
        print(f"FAIL: expected log at {OUT_LOG} but not found.")
        sys.exit(2)
    with open(OUT_LOG, "r", encoding="utf-8") as f:
        log = f.read()

    # Required lines for this specific input set
    required_exact = [
        "changed key brightness: 50 -> 20",
        "changed key color_temperature: 5000 -> 3000",
        "changed key keyboard_backlight: 1 -> 0",
        "added key star_chart_app_theme: red",
    ]
    for line in required_exact:
        if line not in log:
            print(f"FAIL: log missing required line: {line!r}")
            sys.exit(3)

    # For the unchanged boolean, allow either 'false' or 'False' in the value, or omit the value check
    if "unchanged key notifications_enabled" not in log:
        print("FAIL: log missing an 'unchanged key notifications_enabled' line.")
        sys.exit(3)

    print("All validations passed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
