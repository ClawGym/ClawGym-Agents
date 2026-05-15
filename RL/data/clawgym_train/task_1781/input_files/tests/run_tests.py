import argparse
import json
import os
import sys
import hashlib

# Ensure project root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.validator import load_config, validate_inputs, compute_sha256


def test_load_config_fields(cfg_path, results):
    name = 'load_config_has_required_keys'
    try:
        cfg = load_config(cfg_path)
        assert 'required_metadata_fields' in cfg
        assert 'required_columns' in cfg
        assert isinstance(cfg.get('config_version', ''), str)
        results.append({'name': name, 'passed': True, 'message': ''})
        return True
    except Exception as e:
        results.append({'name': name, 'passed': False, 'message': str(e)})
        return False


def test_validate_no_missing(cfg_path, meta_path, data_path, results):
    name = 'validate_no_missing_fields_or_columns'
    try:
        cfg = load_config(cfg_path)
        report = validate_inputs(meta_path, data_path, cfg)
        assert report['required_fields_present'] is True
        assert report['missing_fields'] == []
        assert report['required_columns_present'] is True
        assert report['missing_columns'] == []
        # row count check via independent CSV read
        import csv
        with open(data_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = sum(1 for _ in reader)
        assert report['row_count'] == rows
        results.append({'name': name, 'passed': True, 'message': ''})
        return True
    except Exception as e:
        results.append({'name': name, 'passed': False, 'message': str(e)})
        return False


def test_sha256_independent(data_path, results):
    name = 'sha256_consistency_independent'
    try:
        # Independent hash
        h = hashlib.sha256()
        with open(data_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        independent = h.hexdigest()
        func_hash = compute_sha256(data_path)
        assert independent == func_hash
        results.append({'name': name, 'passed': True, 'message': ''})
        return True
    except Exception as e:
        results.append({'name': name, 'passed': False, 'message': str(e)})
        return False


def test_config_version_propagation(cfg_path, meta_path, data_path, results):
    name = 'config_version_propagated_to_report'
    try:
        cfg = load_config(cfg_path)
        report = validate_inputs(meta_path, data_path, cfg)
        assert report.get('config_version') == cfg.get('config_version')
        results.append({'name': name, 'passed': True, 'message': ''})
        return True
    except Exception as e:
        results.append({'name': name, 'passed': False, 'message': str(e)})
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=False, default='output/test_results.json', help='Path to write test results JSON')
    args = parser.parse_args()

    cfg_path = os.path.join(ROOT, 'config', 'validation.json')
    meta_path = os.path.join(ROOT, 'input', 'metadata.json')
    data_path = os.path.join(ROOT, 'input', 'observations.csv')

    test_results = []
    total = 0
    passed = 0

    for test in [
        lambda r: test_load_config_fields(cfg_path, r),
        lambda r: test_validate_no_missing(cfg_path, meta_path, data_path, r),
        lambda r: test_sha256_independent(data_path, r),
        lambda r: test_config_version_propagation(cfg_path, meta_path, data_path, r)
    ]:
        total += 1
        if test(test_results):
            passed += 1

    summary = {
        'total': total,
        'passed': passed,
        'failed': total - passed,
        'tests': test_results
    }

    out_path = os.path.abspath(args.out)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    # Exit nonzero if any failed
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
