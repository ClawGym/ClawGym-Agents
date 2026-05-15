import json, os, sys

FINDINGS_PATH = os.path.join('outputs', 'findings.json')
VALIDATION_OK = os.path.join('outputs', 'validation_ok.txt')

EXPECTED = {
    'input/materials/marketing.txt': {
        'missing': [
            'for entertainment purposes only',
            'no guarantee of paranormal activity',
            'tours end by 10:00 PM',
            'please keep noise to a respectful level',
        ],
        'prohibited': [
            'we promise you will see a ghost'
        ]
    },
    'input/materials/tour_script.md': {
        'missing': [
            "follow the guide's instructions at all times",
            'do not enter restricted or private areas',
            'stay with the group',
        ],
        'prohibited': []
    },
    'input/materials/waiver.txt': {
        'missing': [
            'photo/video consent optional',
            'parent/guardian consent for minors',
        ],
        'prohibited': []
    },
}

EXPECTED_ERRORS = sum(len(v['missing']) for v in EXPECTED.values())
EXPECTED_WARNINGS = sum(len(v['prohibited']) for v in EXPECTED.values())
EXPECTED_FILES = len(EXPECTED)
EXPECTED_FILES_PASSED = 0


def load_findings(path):
    if not os.path.exists(path):
        print(f'Expected findings file not found: {path}', file=sys.stderr)
        sys.exit(2)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def issues_by_file(findings):
    by_file = {}
    for item in findings.get('files', []):
        file_path = item.get('file_path')
        issues = item.get('issues', [])
        by_file[file_path] = issues
    return by_file


def check_structure(findings):
    # Basic top-level keys
    if 'files' not in findings or 'summary' not in findings:
        print('Missing top-level keys in findings.json (files, summary required).', file=sys.stderr)
        return False
    # Check summary fields
    summary = findings['summary']
    for k in ['errors', 'warnings', 'files_checked', 'files_passed']:
        if k not in summary or not isinstance(summary[k], int):
            print(f'Summary missing integer field: {k}', file=sys.stderr)
            return False
    return True


def check_expected(findings):
    ok = True
    by_file = issues_by_file(findings)
    # Check counts
    summary = findings['summary']
    if summary.get('errors') != EXPECTED_ERRORS:
        print(f"Expected errors={EXPECTED_ERRORS}, got {summary.get('errors')}.", file=sys.stderr)
        ok = False
    if summary.get('warnings') != EXPECTED_WARNINGS:
        print(f"Expected warnings={EXPECTED_WARNINGS}, got {summary.get('warnings')}.", file=sys.stderr)
        ok = False
    if summary.get('files_checked') != EXPECTED_FILES:
        print(f"Expected files_checked={EXPECTED_FILES}, got {summary.get('files_checked')}.", file=sys.stderr)
        ok = False
    if summary.get('files_passed') != EXPECTED_FILES_PASSED:
        print(f"Expected files_passed={EXPECTED_FILES_PASSED}, got {summary.get('files_passed')}.", file=sys.stderr)
        ok = False

    # Verify each expected missing/prohibited phrase is reflected in issues with correct codes
    for fpath, expectations in EXPECTED.items():
        issues = by_file.get(fpath)
        if issues is None:
            print(f'Missing file entry in findings: {fpath}', file=sys.stderr)
            ok = False
            continue
        # Build quick lookup sets by code
        missing_phr = {i.get('phrase') for i in issues if i.get('code') == 'MISSING_REQUIRED_PHRASE'}
        prohibited_phr = {i.get('phrase') for i in issues if i.get('code') == 'PROHIBITED_PHRASE'}
        for p in expectations['missing']:
            if p not in missing_phr:
                print(f"Expected missing phrase not reported for {fpath}: '{p}'", file=sys.stderr)
                ok = False
        for p in expectations['prohibited']:
            if p not in prohibited_phr:
                print(f"Expected prohibited phrase not reported for {fpath}: '{p}'", file=sys.stderr)
                ok = False
    return ok


def main():
    findings = load_findings(FINDINGS_PATH)
    if not check_structure(findings):
        sys.exit(3)
    if not check_expected(findings):
        sys.exit(4)
    os.makedirs('outputs', exist_ok=True)
    with open(VALIDATION_OK, 'w', encoding='utf-8') as f:
        f.write('VALIDATION PASSED\n')
    print('VALIDATION PASSED')


if __name__ == '__main__':
    main()
