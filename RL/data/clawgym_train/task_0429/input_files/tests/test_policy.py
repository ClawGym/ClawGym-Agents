import os
import sys
import json

# Ensure we can import from project root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from tools.policy_enforcer import compute_remediation
except Exception as e:
    print("Import error:", e)
    raise


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    baseline_path = os.path.join(REPO_ROOT, 'input', 'policy_baseline.json')
    state_path = os.path.join(REPO_ROOT, 'input', 'sample_device_state.json')

    baseline = load_json(baseline_path)
    state = load_json(state_path)

    if 'requirements' not in baseline:
        raise AssertionError("Baseline JSON must contain 'requirements' key")

    result = compute_remediation(state, baseline['requirements'])

    # Basic structure checks
    assert isinstance(result, list), 'Result must be a list'
    for item in result:
        assert isinstance(item, dict), 'Each remediation item must be a dict'
        for k in ('setting', 'current', 'required'):
            assert k in item, f"Missing key '{k}' in remediation item"

    # Convert to mapping by setting
    by_setting = {item['setting']: item for item in result}

    expected_settings = {'screen_lock_minutes', 'full_disk_encryption', 'guest_account'}
    assert set(by_setting.keys()) == expected_settings, (
        f"Expected settings {expected_settings}, got {set(by_setting.keys())}")

    # Expect specific remediations based on provided inputs
    assert by_setting['screen_lock_minutes']['current'] == 15
    assert by_setting['screen_lock_minutes']['required'] == 10

    assert by_setting['full_disk_encryption']['current'] is False
    assert by_setting['full_disk_encryption']['required'] is True

    assert by_setting['guest_account']['current'] == 'enabled'
    assert by_setting['guest_account']['required'] == 'disabled'

    print('All tests passed')


if __name__ == '__main__':
    main()
