import argparse
import json
import sys
from pathlib import Path

try:
    from app.app import sum_nonnegatives
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument('--out', default='output/test_results.json', help='Path to write JSON results')
args = parser.parse_args()

cases_path = Path('tests/test_cases.json')
if not cases_path.exists():
    print('Missing tests/test_cases.json')
    sys.exit(2)

with cases_path.open('r', encoding='utf-8') as f:
    cases = json.load(f)

results = []
passed = 0
for c in cases:
    inp = c.get('input', [])
    expected = c.get('expected')
    actual = sum_nonnegatives(inp)
    ok = (actual == expected)
    passed += 1 if ok else 0
    results.append({
        'input': inp,
        'expected': expected,
        'actual': actual,
        'ok': ok
    })

total = len(cases)
failed = total - passed
outdir = Path(args.out).parent
outdir.mkdir(parents=True, exist_ok=True)

payload = {
    'total': total,
    'passed': passed,
    'failed': failed,
    'cases': results
}

with Path(args.out).open('w', encoding='utf-8') as f:
    json.dump(payload, f, indent=2)

print(json.dumps({'total': total, 'passed': passed, 'failed': failed}))

sys.exit(0 if failed == 0 else 1)
