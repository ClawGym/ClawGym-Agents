import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_file(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_unittest_output(text: str) -> Optional[Dict[str, Any]]:
    if not text or not isinstance(text, str):
        return None
    # Find "Ran N tests in Xs"
    ran_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9]*\.?[0-9]+)s", text)
    if not ran_match:
        return None
    total_tests = int(ran_match.group(1))
    try:
        time_seconds = float(ran_match.group(2))
    except Exception:
        time_seconds = 0.0

    # Determine failures and errors from summary line
    failures = 0
    errors = 0
    # Look for FAILED summary like "FAILED (failures=1, errors=0)" or variants
    fail_summary = re.search(r"FAILED\s*\((.*?)\)", text)
    if fail_summary:
        content = fail_summary.group(1)
        f_match = re.search(r"failures=(\d+)", content)
        e_match = re.search(r"errors=(\d+)", content)
        if f_match:
            failures = int(f_match.group(1))
        if e_match:
            errors = int(e_match.group(1))
    else:
        # If OK present, assume 0 failures and 0 errors
        ok_match = re.search(r"^OK\b", text, re.MULTILINE)
        if ok_match:
            failures = 0
            errors = 0
        else:
            # Could be "OK (skipped=...)" or "FAILED" without details; try other hints
            ok_alt = re.search(r"^OK\s*\(", text, re.MULTILINE)
            if ok_alt:
                failures = 0
                errors = 0
            else:
                # Try to parse counts of "FAILED (failures=X)" or "ERROR" markers elsewhere
                # Fallback: count occurrence of "ERROR" and "FAIL:" blocks at end (not perfect)
                # If not found, assume parse failure
                # However, as a last resort, set to None to indicate ambiguous
                pass

    return {
        "total_tests": total_tests,
        "time_seconds": time_seconds,
        "failures": failures,
        "errors": errors,
    }


def _calc_pass_rate(total: int, failures: int, errors: int) -> float:
    if total <= 0:
        return 0.0
    passed = total - failures - errors
    return (passed / total) * 100.0


def _find_sections_by_titles(md_text: str, titles: List[str]) -> Dict[str, str]:
    """
    Return a mapping from title to section content (lines after the heading until next heading).
    Headings may be marked with Markdown '#' or just a line with the exact title text.
    """
    lines = md_text.splitlines()
    title_set = set(titles)
    result = {t: "" for t in titles}
    indices = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Normalize heading line: remove leading '#' and spaces
        if stripped.startswith("#"):
            stripped_head = stripped.lstrip("#").strip()
        else:
            stripped_head = stripped
        if stripped_head in title_set:
            indices.append((idx, stripped_head))
    # Build sections
    for i, (start_idx, title) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        # Section content excludes the heading line itself
        content_lines = lines[start_idx + 1:end_idx]
        result[title] = "\n".join(content_lines).strip()
    return result


def _count_sentences(text: str) -> int:
    # Split by sentence-ending punctuation . ! ?
    if not text:
        return 0
    # Replace newlines with spaces for sentence detection
    normalized = re.sub(r"\s+", " ", text.strip())
    # Find sentence enders
    parts = re.split(r"[.!?]+", normalized)
    # Count non-empty segments
    count = sum(1 for p in parts if p.strip())
    return count


def _count_words(text: str) -> int:
    if not text:
        return 0
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def _extract_next_steps_bullets(section_text: str) -> List[str]:
    bullets = []
    for line in section_text.splitlines():
        if re.match(r"^\s*-\s*\[", line):
            bullets.append(line.strip())
    return bullets


def _numbers_as_tokens(text: str) -> List[str]:
    return re.findall(r"[-+]?\d+(?:\.\d+)?", text)


def _test_summary_values_from_json(js: Any) -> Optional[Tuple[int, int, int, float, float]]:
    try:
        total = int(js["total_tests"])
        failures = int(js["failures"])
        errors = int(js["errors"])
        time_seconds = float(js["time_seconds"])
        pass_rate = float(js["pass_rate"])
        return total, failures, errors, time_seconds, pass_rate
    except Exception:
        return None


def _round_nearest_int(x: float) -> int:
    # Python's round uses banker's rounding. This is acceptable for "nearest whole number".
    return int(round(x))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "test_output_present_and_parsable": 0.0,
        "summary_json_fields_and_consistency": 0.0,
        "status_md_structure_and_overview_length": 0.0,
        "status_md_numbers_match_summary": 0.0,
        "status_md_next_steps_correct": 0.0,
        "team_update_rewritten_format_and_numbers": 0.0,
        "mentor_note_rewritten_question_and_length": 0.0,
        "rerun_results_match_summary": 0.0,
    }

    # Paths
    test_output_path = workspace / "artifacts" / "test_output.txt"
    summary_json_path = workspace / "reports" / "test_summary.json"
    status_md_path = workspace / "reports" / "STATUS.md"
    team_update_path = workspace / "comms" / "team_update_rewritten.txt"
    mentor_note_path = workspace / "comms" / "mentor_note_rewritten.txt"
    tasks_json_path = workspace / "planning" / "tasks.json"

    # Parse test output
    test_output_text = _read_text_file(test_output_path)
    parsed_output = None
    if test_output_text is not None:
        parsed_output = _parse_unittest_output(test_output_text)
    if parsed_output is not None:
        scores["test_output_present_and_parsable"] = 1.0

    # Load summary JSON
    summary_json = _load_json_file(summary_json_path)

    # Validate summary JSON and consistency with artifacts/test_output.txt
    if summary_json is not None and parsed_output is not None:
        vals = _test_summary_values_from_json(summary_json)
        if vals is not None:
            total_j, failures_j, errors_j, time_j, pass_rate_j = vals
            # Check types and pass_rate formula
            expected_pass_rate = _calc_pass_rate(total_j, failures_j, errors_j)
            pass_rate_ok = abs(pass_rate_j - expected_pass_rate) <= 1e-6
            # Check consistency with parsed output
            total_ok = (total_j == int(parsed_output["total_tests"]))
            failures_ok = (failures_j == int(parsed_output["failures"]))
            errors_ok = (errors_j == int(parsed_output["errors"]))
            # Time may vary slightly due to formatting; allow small tolerance
            time_ok = abs(float(parsed_output["time_seconds"]) - time_j) <= 1e-3
            if pass_rate_ok and total_ok and failures_ok and errors_ok and time_ok:
                scores["summary_json_fields_and_consistency"] = 1.0

    # STATUS.md checks
    status_text = _read_text_file(status_md_path)
    titles = ["Overview", "Test Summary", "Next Steps"]
    have_structure = False
    sections = {}
    if status_text is not None:
        sections = _find_sections_by_titles(status_text, titles)
        # Structure: ensure all three titles present (non-empty presence in keys) and Overview 1–3 sentences
        if all(title in sections and sections[title] != "" or re.search(rf"(^|\n)\s*#*\s*{re.escape(title)}\s*(\n|$)", status_text) for title in titles):
            # Get Overview and count sentences
            overview_text = sections.get("Overview", "").strip()
            sent_count = _count_sentences(overview_text)
            if 1 <= sent_count <= 3:
                have_structure = True
    if have_structure:
        scores["status_md_structure_and_overview_length"] = 1.0

    # STATUS.md numbers match summary JSON
    if status_text is not None and summary_json is not None:
        vals = _test_summary_values_from_json(summary_json)
        if vals is not None:
            total_j, failures_j, errors_j, _time_j, pass_rate_j = vals
            test_summary_section = sections.get("Test Summary", "")
            numbers_tokens = _numbers_as_tokens(test_summary_section)
            # Check int numbers exact presence
            ints_ok = (str(total_j) in numbers_tokens) and (str(failures_j) in numbers_tokens) and (str(errors_j) in numbers_tokens)
            # Pass rate: accept float token equal or integer string if it's an integer value
            pr_candidates = set()
            # Representations to try
            pr_candidates.add(str(pass_rate_j))
            pr_candidates.add(f"{pass_rate_j:.1f}".rstrip("0").rstrip("."))
            pr_candidates.add(f"{pass_rate_j:.2f}".rstrip("0").rstrip("."))
            # If near integer, include integer form
            if abs(pass_rate_j - round(pass_rate_j)) <= 1e-9:
                pr_candidates.add(str(int(round(pass_rate_j))))
            pass_rate_present = any(c in numbers_tokens for c in pr_candidates)
            if ints_ok and pass_rate_present:
                scores["status_md_numbers_match_summary"] = 1.0

    # STATUS.md Next Steps correctness
    next_steps_ok = False
    tasks = _load_json_file(tasks_json_path)
    if status_text is not None and tasks is not None and isinstance(tasks, list):
        # Compute expected bullets
        try:
            todos = [t for t in tasks if isinstance(t, dict) and t.get("status") == "todo"]
            # Sort by ascending priority, then by id ascending for deterministic order
            todos_sorted = sorted(todos, key=lambda x: (int(x.get("priority", 0)), int(x.get("id", 0))))
            expected_lines = [f"- [{int(t['id'])}] {t['title']} (priority {int(t['priority'])})" for t in todos_sorted]
            next_steps_section = sections.get("Next Steps", "")
            bullet_lines = _extract_next_steps_bullets(next_steps_section)
            if bullet_lines == expected_lines:
                next_steps_ok = True
        except Exception:
            next_steps_ok = False
    if next_steps_ok:
        scores["status_md_next_steps_correct"] = 1.0

    # Team update rewritten checks
    team_text = _read_text_file(team_update_path)
    if team_text is not None and summary_json is not None:
        vals = _test_summary_values_from_json(summary_json)
        if vals is not None:
            total_j, failures_j, errors_j, _time_j, pass_rate_j = vals
            passed = total_j - failures_j - errors_j
            rounded_pr = _round_nearest_int(pass_rate_j)
            word_count = _count_words(team_text)
            # Regex for the required sentence
            pattern = re.compile(r"Test run:\s*(\d+)\/(\d+)\s+passed\s+\((\d+)%\s+pass rate\)\.", re.IGNORECASE)
            matches = list(pattern.finditer(team_text))
            if len(matches) == 1:
                g = matches[0].groups()
                try:
                    passed_s, total_s, pr_s = int(g[0]), int(g[1]), int(g[2])
                    if (passed_s == passed) and (total_s == total_j) and (pr_s == rounded_pr) and (word_count <= 120):
                        scores["team_update_rewritten_format_and_numbers"] = 1.0
                except Exception:
                    pass

    # Mentor note rewritten checks
    mentor_text = _read_text_file(mentor_note_path)
    if mentor_text is not None:
        word_count = _count_words(mentor_text)
        stripped = mentor_text.strip()
        ends_with_q = stripped.endswith("?")
        q_count = stripped.count("?")
        # Extract last sentence (question)
        last_question = ""
        if ends_with_q:
            # Take substring from last sentence-ending punctuation before final '?'
            idx = stripped.rfind("?")
            last_question = stripped[: idx + 1]
            # Extract the last sentence by finding the previous sentence boundary
            # But simpler: take tail after last period/exclamation mark if present
            # For keyword checks we can just use the last question sentence
            # Find start index
            start_idx = max(stripped.rfind(".", 0, idx), stripped.rfind("!", 0, idx))
            if start_idx != -1:
                last_question = stripped[start_idx + 1: idx + 1].strip()
            else:
                last_question = stripped[: idx + 1].strip()
        # Must include keywords in last question
        last_q_lower = last_question.lower()
        keywords_ok = ("todo" in last_q_lower) and ("prioriti" in last_q_lower) and ("next" in last_q_lower) and ("planning/tasks.json" in last_q_lower)
        if (word_count <= 120) and ends_with_q and (q_count == 1) and keywords_ok:
            scores["mentor_note_rewritten_question_and_length"] = 1.0

    # Rerun tests and compare results to summary
    if summary_json is not None:
        vals = _test_summary_values_from_json(summary_json)
        if vals is not None:
            total_j, failures_j, errors_j, _time_j, _pass_rate_j = vals
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    cwd=str(workspace),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=60,
                )
                out = proc.stdout or ""
                parsed_rerun = _parse_unittest_output(out)
                if parsed_rerun is not None:
                    ok_tot = int(parsed_rerun["total_tests"]) == total_j
                    ok_fail = int(parsed_rerun["failures"]) == failures_j
                    ok_err = int(parsed_rerun["errors"]) == errors_j
                    if ok_tot and ok_fail and ok_err:
                        scores["rerun_results_match_summary"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()