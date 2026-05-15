import sys
from app.detector import find_suspects

def t_equal(name, got, exp):
    if got != exp:
        raise AssertionError(f"{name} failed: got={got!r} exp={exp!r}")


def run():
    total = 0
    failed = 0
    # Test 1: basic thresholding
    total += 1
    try:
        events = ['alice', 'bob', 'alice', 'carol', 'alice']
        exp = ['alice']
        got = find_suspects(events, threshold=2)
        t_equal('T1', got, exp)
    except Exception:
        failed += 1

    # Test 2: multiple suspects and sorting
    total += 1
    try:
        events = ['x', 'y', 'x', 'z', 'y', 'z', 'y']
        exp = ['x', 'y']  # x(2), y(3) meet threshold=2; sorted
        got = find_suspects(events, threshold=2)
        t_equal('T2', got, exp)
    except Exception:
        failed += 1

    # Test 3: empty input
    total += 1
    try:
        events = []
        exp = []
        got = find_suspects(events, threshold=1)
        t_equal('T3', got, exp)
    except Exception:
        failed += 1

    passed = total - failed
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(run())
