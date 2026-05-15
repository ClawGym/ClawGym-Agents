import json
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple, List


EXPECTED_FOSS_LICENSES_PY = '''from typing import Set

def load_approved(path: str) -> Set[str]:
    """Load approved license identifiers from a text file, one per line.
    Lines starting with '#' are ignored.
    """
    approved = set()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            approved.add(line)
    return approved


def is_foss_license(name: str, approved: Set[str]) -> bool:
    """Return True if the given license name is considered FOSS.
    NOTE: This intentionally does NOT normalize inputs (buggy per SPEC.md).
    """
    if name is None:
        return False
    # Bug: exact match only, no trimming/case-folding/synonym mapping
    return name in approved
'''

EXPECTED_CHECK_CSV_PY = '''import sys
import os
import csv
from typing import List

# Local import
import foss_licenses


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("Usage: python src/check_csv.py <deps.csv>", file=sys.stderr)
        return 2
    csv_path = argv[1]
    if not os.path.exists(csv_path):
        print(f"Input CSV not found: {csv_path}", file=sys.stderr)
        return 2

    approved_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'osi_approved.txt'))
    approved = foss_licenses.load_approved(approved_path)

    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get('name') or '').strip()
            license_name = (row.get('license') or '').strip()
            is_foss = foss_licenses.is_foss_license(license_name, approved)
            tag = 'FOSS' if is_foss else 'NOT_FOSS'
            print(f"{tag},{name},{license_name}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
'''


def _safe_read_text(path: Path) -> Tuple[Optional[str], bool]:
    try:
        if not path.exists() or not path.is_file():
            return None, False
        return path.read_text(encoding="utf-8"), True
    except Exception:
        return None, False


def _parse_junit_report(path: Path) -> Tuple[bool, int, int, int]:
    """
    Returns (ok, tests, failures, errors).
    ok=False if file missing or parse error.
    """
    try:
        if not path.exists():
            return False, 0, 0, 0
        tree = ET.parse(str(path))
        root = tree.getroot()
        tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag

        tests = 0
        failures = 0
        errors = 0

        def _collect_from_suite(elem):
            t = int(elem.attrib.get('tests', 0))
            f = int(elem.attrib.get('failures', 0))
            e = int(elem.attrib.get('errors', 0))
            return t, f, e

        if tag == 'testsuite':
            t, f, e = _collect_from_suite(root)
            tests += t
            failures += f
            errors += e
        elif tag == 'testsuites':
            for ts in root.findall(".//testsuite"):
                t, f, e = _collect_from_suite(ts)
                tests += t
                failures += f
                errors += e
        else:
            for ts in root.findall(".//testsuite"):
                t, f, e = _collect_from_suite(ts)
                tests += t
                failures += f
                errors += e

        # Fallback: if attributes are not present, count elements
        if tests == 0:
            tests = len(root.findall(".//testcase"))
        if failures == 0:
            failures = len(root.findall(".//failure"))
        if errors == 0:
            errors = len(root.findall(".//error"))

        return True, tests, failures, errors
    except Exception:
        return False, 0, 0, 0


def _run_check_csv(workspace: Path) -> Tuple[bool, Optional[List[str]]]:
    """
    Run 'python src/check_csv.py data/deps.csv' in workspace, capture stdout lines.
    Returns (ok, lines or None).
    """
    try:
        cmd = [sys.executable, "src/check_csv.py", "data/deps.csv"]
        proc = subprocess.run(cmd, cwd=str(workspace), capture_output=True, text=True)
        if proc.returncode != 0:
            return False, None
        out = proc.stdout
        lines = out.splitlines()
        return True, lines
    except Exception:
        return False, None


def _normalize_lines(text: Optional[str]) -> List[str]:
    return text.splitlines() if text is not None else []


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    # Initialize scores
    scores = {
        "src_files_unmodified": 0.0,
        "tests_file_exists": 0.0,
        "tests_cover_required_cases": 0.0,
        "junit_report_exists": 0.0,
        "junit_report_has_failures": 0.0,
        "audit_log_exists": 0.0,
        "audit_log_matches_expected": 0.0,
        "readme_testing_instructions_present": 0.0,
        "readme_status_mentions_issues": 0.0,
        "upstream_email_mentions_and_repro": 0.0,
        "total_score": 0.0,
    }

    # Determine presence of key deliverables (for gating)
    tests_path = workspace / "tests" / "test_foss_licenses.py"
    junit_path = workspace / "output" / "test-results.xml"
    audit_path = workspace / "output" / "deps_audit.txt"
    email_path = workspace / "output" / "upstream-email.txt"
    readme_path = workspace / "docs" / "README.md"

    tests_text, tests_ok = _safe_read_text(tests_path)
    junit_exists = junit_path.exists() and junit_path.is_file()
    audit_exists = audit_path.exists() and audit_path.is_file()
    email_exists = email_path.exists() and email_path.is_file()
    readme_text, readme_ok = _safe_read_text(readme_path)

    # Tests existence and content checks
    if tests_ok:
        scores["tests_file_exists"] = 1.0
        content = tests_text
        content_lower = content.lower()
        has_assert = "assert" in content_lower
        mentions_func = "is_foss_license" in content
        # Required cases from SPEC.md
        has_mit_lower = ('"mit"' in content_lower) or ("'mit'" in content_lower)
        has_mit_spaces = "  MIT  " in content or "  mit  " in content_lower
        has_apache_20 = "Apache 2.0" in content
        has_bsd_3 = "BSD 3-Clause" in content
        has_gpl_v3_plus = "GPL v3+" in content
        has_proprietary = "Proprietary" in content

        if all([
            has_assert,
            mentions_func,
            has_mit_lower,
            has_mit_spaces,
            has_apache_20,
            has_bsd_3,
            has_gpl_v3_plus,
            has_proprietary
        ]):
            scores["tests_cover_required_cases"] = 1.0

    # JUnit report checks
    junit_ok, tests_count, failures_count, errors_count = _parse_junit_report(junit_path)
    if junit_ok:
        scores["junit_report_exists"] = 1.0
        if (failures_count + errors_count) >= 1 and tests_count >= 1:
            scores["junit_report_has_failures"] = 1.0

    # Audit output exists and matches current implementation behavior
    audit_text, audit_ok = _safe_read_text(audit_path)
    if audit_ok:
        scores["audit_log_exists"] = 1.0
        ran_ok, expected_lines = _run_check_csv(workspace)
        if ran_ok and expected_lines is not None:
            actual_lines = _normalize_lines(audit_text)
            if actual_lines == expected_lines:
                scores["audit_log_matches_expected"] = 1.0

    # README modifications checks
    if readme_ok:
        lower = readme_text.lower()
        todo_absent = "todo" not in lower

        # Testing section with exact commands
        has_testing_header = "## Testing" in readme_text or "## testing" in lower
        cmd_pytest = "pytest -q --junitxml=output/test-results.xml"
        cmd_audit = "python src/check_csv.py data/deps.csv > output/deps_audit.txt"
        includes_pytest_cmd = cmd_pytest in readme_text
        includes_audit_cmd = cmd_audit in readme_text
        if has_testing_header and includes_pytest_cmd and includes_audit_cmd and todo_absent:
            scores["readme_testing_instructions_present"] = 1.0

        # Status section mentioning non-conformance and normalization issues
        has_status_header = "## Status" in readme_text or "## status" in lower
        mentions_nonconformance = "does not conform" in lower
        mentions_spec = "docs/spec.md" in lower or "docs/SPEC.md" in readme_text
        mentions_normalization = "normalization" in lower
        mentions_apache = "Apache 2.0" in readme_text
        mentions_gpl = "GPL v3+" in readme_text
        if has_status_header and mentions_nonconformance and mentions_spec and mentions_normalization and mentions_apache and mentions_gpl and todo_absent:
            scores["readme_status_mentions_issues"] = 1.0

    # Upstream email checks
    email_text, email_ok = _safe_read_text(email_path)
    if email_ok:
        cmd_pytest = "pytest -q --junitxml=output/test-results.xml"
        cmd_checker = "python src/check_csv.py data/deps.csv"
        mentions_apache = "Apache 2.0" in email_text
        mentions_gpl = "GPL v3+" in email_text
        includes_pytest_cmd = cmd_pytest in email_text
        includes_checker_cmd = cmd_checker in email_text
        substantive = len(email_text.strip()) >= 80
        if mentions_apache and mentions_gpl and includes_pytest_cmd and includes_checker_cmd and substantive:
            scores["upstream_email_mentions_and_repro"] = 1.0

    # Check src files unchanged (but do not award points solely for pre-existing input state).
    # Only award if other deliverables are present (tests, outputs, or email/README updates).
    deliverables_present = any([
        scores["tests_file_exists"] > 0.0,
        scores["junit_report_exists"] > 0.0,
        scores["audit_log_exists"] > 0.0,
        scores["readme_testing_instructions_present"] > 0.0 or scores["readme_status_mentions_issues"] > 0.0,
        scores["upstream_email_mentions_and_repro"] > 0.0,
    ])
    foss_path = workspace / "src" / "foss_licenses.py"
    checkcsv_path = workspace / "src" / "check_csv.py"
    foss_text, foss_ok = _safe_read_text(foss_path)
    checkcsv_text, checkcsv_ok = _safe_read_text(checkcsv_path)
    if deliverables_present and foss_ok and checkcsv_ok:
        if foss_text == EXPECTED_FOSS_LICENSES_PY and checkcsv_text == EXPECTED_CHECK_CSV_PY:
            scores["src_files_unmodified"] = 1.0

    # Compute total score as average of individual (excluding total_score itself)
    keys = [k for k in scores.keys() if k != "total_score"]
    if keys:
        total = sum(scores[k] for k in keys) / float(len(keys))
    else:
        total = 0.0
    scores["total_score"] = total

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()