import json
import re
import subprocess
import sys
from pathlib import Path


def _read_text_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _run_unittests(workspace: Path, timeout: int = 60):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "-v"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout if proc.stdout is not None else ""
        stderr = proc.stderr if proc.stderr is not None else ""
        success = (proc.returncode == 0) and ("Ran 2 tests" in stdout) and ("OK" in stdout)
        return success, stdout, stderr
    except Exception as e:
        return False, "", str(e)


def _extract_markdown_sections(text: str) -> dict:
    lines = text.splitlines()
    headings = []
    for idx, line in enumerate(lines):
        m = re.match(r'^\s{0,3}#{1,6}\s*(.+?)\s*$', line)
        if m:
            title = m.group(1).strip().lower()
            headings.append((title, idx))
    sections = {}
    for i, (title, start_idx) in enumerate(headings):
        end_idx = headings[i + 1][1] if i + 1 < len(headings) else len(lines)
        section_text = "\n".join(lines[start_idx + 1 : end_idx]).strip()
        sections[title] = section_text
    return sections


def _count_sentences(text: str) -> int:
    matches = re.findall(r'[.!?](?:\s|$)', text)
    return len(matches)


def _find_bullet_lines(text: str) -> list:
    bullets = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s[2:].strip().lower())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_pass_via_unittest": 0.0,
        "test_results_file_present_and_contains_summary": 0.0,
        "readme_has_correct_unittest_command": 0.0,
        "email_to_ta_content": 0.0,
        "meeting_notes_structure_and_content": 0.0,
    }

    # 1) Run tests using unittest and verify both tests pass with proper summary
    ut_success, ut_stdout, _ = _run_unittests(workspace)
    if ut_success:
        scores["tests_pass_via_unittest"] = 1.0

    # 2) Verify output/test_results.txt exists and contains 'Ran 2 tests' and 'OK'
    test_results_path = workspace / "output" / "test_results.txt"
    ok_tr, tr_text = _read_text_file(test_results_path)
    if ok_tr and ("Ran 2 tests" in tr_text) and ("OK" in tr_text):
        scores["test_results_file_present_and_contains_summary"] = 1.0

    # 3) README.md updated with correct unittest command and without pytest mention
    readme_path = workspace / "README.md"
    ok_readme, readme_text = _read_text_file(readme_path)
    if ok_readme:
        readme_lower = readme_text.lower()
        has_unittest_cmd = "python -m unittest -v" in readme_lower
        mentions_pytest = "pytest" in readme_lower
        if has_unittest_cmd and not mentions_pytest:
            scores["readme_has_correct_unittest_command"] = 1.0

    # 4) Email content checks
    email_path = workspace / "output" / "email_to_ta.txt"
    ok_email, email_text = _read_text_file(email_path)
    if ok_email:
        email_lower = email_text.lower()

        # Root cause(s) and fix(es) indicators:
        # - reference to config/grading.json and the mistaken grades.json
        mentions_correct_file = "config/grading.json" in email_text
        mentions_wrong_file = ("grades.json" in email_lower) or ("wrong file" in email_lower) or ("wrong filename" in email_lower) or ("incorrect path" in email_lower)

        # - weighted GPA issue: mention of total units or len(courses) division or dividing/weighting by units
        mentions_weight_issue = (
            ("len(courses)" in email_lower)
            or ("length of courses" in email_lower)
            or ("total units" in email_lower)
            or ("sum of units" in email_lower)
            or ("divide" in email_lower and "units" in email_lower)
            or ("weighted" in email_lower and "units" in email_lower)
        )

        # Files changed list must include app/calc.py and README.md
        mentions_files_changed = ("app/calc.py" in email_text) and ("README.md" in email_text)

        # Status update referencing output/test_results.txt and states both tests now pass
        mentions_results_path = "output/test_results.txt" in email_text
        states_both_tests_pass = (
            ("both" in email_lower and "tests" in email_lower and ("pass" in email_lower or "passed" in email_lower))
            or ("ran 2 tests" in email_lower and "ok" in email_lower)
        )

        # Polite closing asking if anything else is needed
        asks_anything_else = "anything else" in email_lower

        if mentions_correct_file and mentions_wrong_file and mentions_weight_issue and mentions_files_changed and mentions_results_path and states_both_tests_pass and asks_anything_else:
            scores["email_to_ta_content"] = 1.0

    # 5) Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes.md"
    ok_notes, notes_text = _read_text_file(notes_path)
    if ok_notes:
        sections = _extract_markdown_sections(notes_text)

        summary_ok = False
        evidence_ok = False
        action_ok = False

        if "summary" in sections:
            summary_text = sections.get("summary", "")
            sentence_count = _count_sentences(summary_text)
            summary_ok = 2 <= sentence_count <= 3 and len(summary_text.strip()) > 0

        if "evidence" in sections:
            evidence_text = sections.get("evidence", "")
            e_lower = evidence_text.lower()
            evidence_ok = ("output/test_results.txt" in evidence_text) and ("ran 2 tests" in e_lower) and ("ok" in e_lower)

        if "action items" in sections:
            ai_text = sections.get("action items", "")
            bullets = _find_bullet_lines(ai_text)
            bullet_count_ok = len(bullets) >= 3
            has_invalid_grade = any(("invalid" in b and "grade" in b) for b in bullets)
            has_error_handling = any("error handling" in b for b in bullets)
            has_onboarding = any(("onboarding" in b) or ("new members" in b) for b in bullets)
            action_ok = bullet_count_ok and has_invalid_grade and has_error_handling and has_onboarding

        if summary_ok and evidence_ok and action_ok:
            scores["meeting_notes_structure_and_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order of keys as created in grade()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()