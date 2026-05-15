import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATH_LIBRARY_JSON = os.path.join(ROOT, 'config', 'library.json')
PATH_PROPS = os.path.join(ROOT, 'gradle.properties')
PATH_BUILD = os.path.join(ROOT, 'app', 'build.gradle')
PATH_TESTS = os.path.join(ROOT, 'reports', 'test_results.json')
PATH_DOC_YAML = os.path.join(ROOT, 'config', 'docs.yaml')
PATH_SETUP_MD = os.path.join(ROOT, 'docs', 'SETUP.md')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def parse_library_name():
    data = json.loads(read_text(PATH_LIBRARY_JSON))
    name = data.get('name')
    if not name:
        raise ValueError('Missing name in library.json')
    return name


def parse_version_name():
    text = read_text(PATH_PROPS)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('VERSION_NAME='):
            return line.split('=', 1)[1].strip()
    raise ValueError('VERSION_NAME not found in gradle.properties')


def parse_sdk_versions():
    text = read_text(PATH_BUILD)
    min_match = re.search(r"minSdkVersion\s+(\d+)", text)
    target_match = re.search(r"targetSdkVersion\s+(\d+)", text)
    if not min_match or not target_match:
        raise ValueError('Could not parse minSdkVersion/targetSdkVersion from app/build.gradle')
    return int(min_match.group(1)), int(target_match.group(1))


def parse_test_summary():
    data = json.loads(read_text(PATH_TESTS))
    passed = data.get('passed')
    failed = data.get('failed')
    if passed is None or failed is None:
        raise ValueError('Missing passed/failed in test_results.json')
    return int(passed), int(failed)


def parse_docs_yaml():
    # Minimal YAML parsing for expected keys
    text = read_text(PATH_DOC_YAML)
    doc_title = None
    min_sdk = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('doc_title:'):
            val = line.split(':', 1)[1].strip()
            # strip optional surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            doc_title = val
        elif line.startswith('minSdk:'):
            val = line.split(':', 1)[1].strip()
            try:
                min_sdk = int(val)
            except ValueError:
                pass
    if doc_title is None or min_sdk is None:
        raise ValueError('docs.yaml missing required keys (doc_title, minSdk)')
    return doc_title, min_sdk


def run_checks():
    ok = True
    msgs = []

    # Gather source-of-truth values
    name = parse_library_name()
    version = parse_version_name()
    min_sdk, target_sdk = parse_sdk_versions()
    passed, failed = parse_test_summary()

    # Read docs and config
    if not os.path.exists(PATH_SETUP_MD):
        msgs.append(f"FAIL: {PATH_SETUP_MD} does not exist")
        ok = False
        # still continue to report other issues
        setup_text = ''
    else:
        setup_text = read_text(PATH_SETUP_MD)

    title_expected = f"Setup for {name} v{version}"
    if title_expected in setup_text:
        msgs.append("OK: Title present in SETUP.md")
    else:
        msgs.append(f"FAIL: SETUP.md missing title '{title_expected}'")
        ok = False

    if f"minSdk: {min_sdk}" in setup_text:
        msgs.append("OK: minSdk matches in SETUP.md")
    else:
        msgs.append(f"FAIL: SETUP.md missing or incorrect 'minSdk: {min_sdk}'")
        ok = False

    if f"targetSdk: {target_sdk}" in setup_text:
        msgs.append("OK: targetSdk matches in SETUP.md")
    else:
        msgs.append(f"FAIL: SETUP.md missing or incorrect 'targetSdk: {target_sdk}'")
        ok = False

    if f"passed: {passed}" in setup_text:
        msgs.append("OK: passed count present in SETUP.md")
    else:
        msgs.append(f"FAIL: SETUP.md missing 'passed: {passed}'")
        ok = False

    if f"failed: {failed}" in setup_text:
        msgs.append("OK: failed count present in SETUP.md")
    else:
        msgs.append(f"FAIL: SETUP.md missing 'failed: {failed}'")
        ok = False

    # Validate docs.yaml consistency
    try:
        doc_title, yaml_min = parse_docs_yaml()
        if doc_title == title_expected:
            msgs.append("OK: docs.yaml doc_title matches")
        else:
            msgs.append(f"FAIL: docs.yaml doc_title mismatch (expected '{title_expected}', found '{doc_title}')")
            ok = False
        if yaml_min == min_sdk:
            msgs.append("OK: docs.yaml minSdk matches")
        else:
            msgs.append(f"FAIL: docs.yaml minSdk mismatch (expected {min_sdk}, found {yaml_min})")
            ok = False
    except Exception as e:
        msgs.append(f"FAIL: Error parsing docs.yaml: {e}")
        ok = False

    return ok, msgs


if __name__ == '__main__':
    try:
        success, messages = run_checks()
        for m in messages:
            print(m)
        if success:
            print('All checks passed.')
            sys.exit(0)
        else:
            print('Validation failed.')
            sys.exit(1)
    except Exception as e:
        print(f"Validation error: {e}")
        sys.exit(2)
