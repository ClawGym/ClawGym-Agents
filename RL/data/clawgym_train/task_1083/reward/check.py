import json
import sys
import subprocess
import re
import os
from pathlib import Path
from typing import Optional, Tuple, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _run_pytest(workspace: Path, timeout: int = 60) -> Tuple[bool, str]:
    """
    Run pytest in quiet mode and return (ran, output_text).
    'ran' indicates the command executed; output includes stdout/stderr merged.
    """
    cmd = [sys.executable, "-m", "pytest", "-q"]
    try:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            env=env,
        )
        output = proc.stdout or ""
        return True, output
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _contains_passing_summary(text: Optional[str], expected_passed: int = 2) -> bool:
    """
    Check for pytest passing summary with the expected number of passed tests
    and ensure no failures/errors are present.
    """
    if not text:
        return False
    lower = text.lower()
    # Disallow any failures or errors in the summary
    if re.search(r"\bfailed\b", lower) or re.search(r"\berror\b", lower):
        return False
    pattern = rf"\b{expected_passed}\s+passed\b"
    return re.search(pattern, lower) is not None


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _extract_bullets(text: str) -> List[str]:
    bullets: List[str] = []
    if not text:
        return bullets
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_pass_pytest_run": 0.0,
        "test_output_file_contains_passing_summary": 0.0,
        "readme_fixed_note_with_verification": 0.0,
        "readme_known_issues_removed": 0.0,
        "email_summarizes_fix_and_verification": 0.0,
        "meeting_notes_with_actions_and_owners": 0.0,
        "bug_fix_applied_in_search_code": 0.0,
    }

    # 1) Tests pass locally with python -m pytest -q
    ran, pytest_output = _run_pytest(workspace)
    if ran and _contains_passing_summary(pytest_output, expected_passed=2):
        scores["tests_pass_pytest_run"] = 1.0

    # 2) Saved test output contains the passing summary
    test_output_path = workspace / "output" / "test_output.txt"
    test_output_text = _read_text(test_output_path)
    if _contains_passing_summary(test_output_text, expected_passed=2):
        scores["test_output_file_contains_passing_summary"] = 1.0

    # 3) README updated with "Fixed" note and "How to verify" snippet showing command and expected summary line
    readme_path = workspace / "README.md"
    readme_text = _read_text(readme_path) or ""
    fixed_present = bool(re.search(r"\bfixed\b", readme_text, flags=re.IGNORECASE))
    how_to_verify_present = bool(re.search(r"how to verify", readme_text, flags=re.IGNORECASE))
    cmd_present = "python -m pytest -q" in readme_text
    passed_line_present = re.search(r"\b2\s+passed\b", readme_text, flags=re.IGNORECASE) is not None
    if fixed_present and how_to_verify_present and cmd_present and passed_line_present:
        scores["readme_fixed_note_with_verification"] = 1.0

    # 4) README no longer claims the available-only filter is inconsistent
    # Strictly check that the specific old note string is not present.
    old_note_phrase = 'The "available only" filter may behave inconsistently'
    if readme_text and old_note_phrase not in readme_text:
        scores["readme_known_issues_removed"] = 1.0

    # 5) Email to teammate: <=200 words, includes test command, mentions changed file(s), and summarizes root cause
    email_path = workspace / "outgoing" / "email_to_teammate.txt"
    email_text = _read_text(email_path) or ""
    if email_text:
        wc = _word_count(email_text)
        within_limit = wc <= 200
        has_test_cmd = "python -m pytest -q" in email_text
        mentions_changed_file = any(
            p in email_text for p in ["app/search.py", "app/config.json", "README.md", "tests/test_search.py"]
        )
        cause_keywords = [
            "root cause", "cause", "bug", "boolean", "string", "config", "available", "compare", "filter", "logic"
        ]
        has_cause = any(kw.lower() in email_text.lower() for kw in cause_keywords)
        if within_limit and has_test_cmd and mentions_changed_file and has_cause:
            scores["email_summarizes_fix_and_verification"] = 1.0

    # 6) Meeting notes with header and action items (3–5 bullets), each with Owner and rationale, and mentions UX and tests
    meeting_path = workspace / "output" / "meeting_notes.md"
    meeting_text = _read_text(meeting_path) or ""
    if meeting_text:
        has_header = re.search(r"next review date\s*:", meeting_text, flags=re.IGNORECASE) is not None
        bullets = _extract_bullets(meeting_text)
        bullet_count_ok = 3 <= len(bullets) <= 5
        owners_ok = False
        rationale_ok = False
        if bullets:
            owners_ok = all(re.search(r"owner\s*:", b, flags=re.IGNORECASE) is not None for b in bullets)
            rationale_ok = all(
                (re.search(r"rationale\s*:", b, flags=re.IGNORECASE) is not None)
                or ("because" in b.lower()) or ("so that" in b.lower())
                for b in bullets
            )
        mentions_ux = ("ux" in meeting_text.lower()) or ("user" in meeting_text.lower())
        mentions_test = "test" in meeting_text.lower()
        if has_header and bullet_count_ok and owners_ok and rationale_ok and mentions_ux and mentions_test:
            scores["meeting_notes_with_actions_and_owners"] = 1.0

    # 7) Bug fix applied in search code: ensure no string comparison to 'true' for availability
    search_path = workspace / "app" / "search.py"
    search_text = _read_text(search_path) or ""
    if search_text:
        wrong_pattern = re.compile(r"get\(\s*['\"]available['\"]\s*\)\s*==\s*['\"]true['\"]")
        if not wrong_pattern.search(search_text):
            scores["bug_fix_applied_in_search_code"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()