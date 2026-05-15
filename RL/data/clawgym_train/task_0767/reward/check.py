import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[object]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv(p: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
            if header is None:
                return None
            rows = list(r)
            return header, rows
    except Exception:
        return None


def _parse_unittest_summary(text: str) -> Dict[str, Optional[int]]:
    """
    Parse unittest output to find:
    - ran: int or None
    - ok: bool
    - failures: int or None
    - errors: int or None
    """
    result = {
        "ran": None,
        "ok": False,
        "failures": None,
        "errors": None,
    }
    if not text:
        return result
    m_ran = re.search(r'Ran\s+(\d+)\s+tests?', text)
    if m_ran:
        try:
            result["ran"] = int(m_ran.group(1))
        except Exception:
            result["ran"] = None
    if re.search(r'^\s*OK\s*$', text, flags=re.MULTILINE):
        result["ok"] = True
    m_failed = re.search(r'FAILED\s*\(([^)]*)\)', text)
    if m_failed:
        inside = m_failed.group(1)
        m_f = re.search(r'failures\s*=\s*(\d+)', inside)
        m_e = re.search(r'errors\s*=\s*(\d+)', inside)
        if m_f:
            try:
                result["failures"] = int(m_f.group(1))
            except Exception:
                result["failures"] = None
        if m_e:
            try:
                result["errors"] = int(m_e.group(1))
            except Exception:
                result["errors"] = None
    # Also detect any explicit FAIL/ERROR markers
    if result["failures"] is None and re.search(r'^\s*FAIL:', text, flags=re.MULTILINE):
        # if at least one FAIL line present, mark nonzero
        result["failures"] = 1
    if result["errors"] is None and re.search(r'^\s*ERROR:', text, flags=re.MULTILINE):
        result["errors"] = 1
    return result


def _extract_section(text: str, name: str, all_names: List[str]) -> List[str]:
    """
    Extract lines belonging to a Markdown-like section titled `name`.
    Recognizes headings like "## Name" or "Name:" on a line by itself.
    """
    lines = text.splitlines()
    def is_header(line: str, target: str) -> bool:
        s = line.strip()
        s = re.sub(r'^\s*#+\s*', '', s)  # remove leading hashes
        s = s.rstrip(':').strip()
        return s.lower() == target.lower()
    start_idx = None
    for i, line in enumerate(lines):
        if is_header(line, name):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    other_names = [n for n in all_names if n.lower() != name.lower()]
    for j in range(start_idx, len(lines)):
        for other in other_names:
            if is_header(lines[j], other):
                end_idx = j
                break
        if end_idx != len(lines) and j >= end_idx:
            break
    return lines[start_idx:end_idx]


def _section_bullets(section_lines: List[str]) -> List[str]:
    bullets = []
    for line in section_lines:
        if re.match(r'^\s*[-*]\s+', line):
            bullets.append(line.strip())
    return bullets


def _count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]+', text)
    return sum(1 for p in parts if p.strip())


def _parse_failure_method_names(unittest_text: str) -> List[str]:
    """
    Extract failing unittest method names exactly as they appear after FAIL:/ERROR: lines.
    Typically lines look like:
      FAIL: test_method_name (tests.test_module.TestClass)
      ERROR: test_other_name (tests.test_module.TestClass)
    Returns list of method names like 'test_method_name'.
    """
    names: List[str] = []
    if not unittest_text:
        return names
    for line in unittest_text.splitlines():
        m = re.match(r'^\s*(FAIL|ERROR):\s+([A-Za-z_][\w]*)\s*\(', line)
        if m:
            names.append(m.group(2))
    return names


def _extract_counts_from_test_results_section(text: str) -> Dict[str, Optional[int]]:
    """
    From the 'Test results' section, attempt to parse integers for:
    - ran
    - passed
    - failed
    Accepts phrasing variations around words 'ran'/'run', 'passed', 'failed'.
    """
    result = {"ran": None, "passed": None, "failed": None}
    tl = text.lower()
    # Find 'ran' or 'run' counts
    m_ran = re.search(r'\b(ran|run)\b[^0-9]{0,10}(\d+)\s+tests?', tl)
    if m_ran:
        try:
            result["ran"] = int(m_ran.group(2))
        except Exception:
            result["ran"] = None
    # Find 'passed' count
    m_passed = re.search(r'(\d+)\s+passed', tl)
    if m_passed:
        try:
            result["passed"] = int(m_passed.group(1))
        except Exception:
            result["passed"] = None
    # Find 'failed' count
    m_failed = re.search(r'(\d+)\s+failed', tl)
    if m_failed:
        try:
            result["failed"] = int(m_failed.group(1))
        except Exception:
            result["failed"] = None
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "before_run_exists_and_has_failures": 0.0,
        "after_run_exists_and_all_tests_passing": 0.0,
        "after_run_no_failures_or_errors": 0.0,
        "export_csv_exists_with_correct_header_and_rows": 0.0,
        "export_csv_matches_tasks_json": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_failures_listed": 0.0,
        "meeting_notes_fixes_mapped_to_failures": 0.0,
        "meeting_notes_test_results_counts_consistent": 0.0,
        "meeting_notes_next_actions_count_valid": 0.0,
        "meeting_notes_summary_sentence_count_valid": 0.0,
    }

    # Paths
    before_path = workspace / "artifacts" / "test_results_before.txt"
    after_path = workspace / "artifacts" / "test_results_after.txt"
    export_path = workspace / "artifacts" / "export.csv"
    data_json_path = workspace / "data" / "tasks.json"
    notes_path = workspace / "docs" / "meeting_notes.md"

    # Parse before run output
    before_text = _read_text(before_path) if before_path.exists() else None
    if before_text:
        summary_b = _parse_unittest_summary(before_text)
        has_fail = False
        # Consider failures or errors present if explicit FAILED line or FAIL/ERROR markers
        if (summary_b.get("failures") or 0) > 0 or (summary_b.get("errors") or 0) > 0:
            has_fail = True
        if has_fail:
            scores["before_run_exists_and_has_failures"] = 1.0

    # Parse after run output
    after_text = _read_text(after_path) if after_path.exists() else None
    if after_text:
        summary_a = _parse_unittest_summary(after_text)
        if summary_a.get("ok") and summary_a.get("ran") == 6:
            scores["after_run_exists_and_all_tests_passing"] = 1.0
        # No FAIL/ERROR markers and no FAILED summary
        no_fail_err = True
        if re.search(r'^\s*(FAIL|ERROR):', after_text, flags=re.MULTILINE):
            no_fail_err = False
        if re.search(r'FAILED\s*\(', after_text):
            no_fail_err = False
        if summary_a.get("ok") and no_fail_err:
            scores["after_run_no_failures_or_errors"] = 1.0

    # Validate export CSV exists and structure
    if export_path.exists():
        csv_parsed = _read_csv(export_path)
        if csv_parsed is not None:
            header, rows = csv_parsed
            if header == ["id", "title", "status", "priority"] and len(rows) == 6:
                scores["export_csv_exists_with_correct_header_and_rows"] = 1.0
            # Match content against tasks.json if available
            data = _load_json(data_json_path)
            if isinstance(data, list) and len(data) == 6:
                # Build expected set of row tuples (as strings to compare CSV)
                exp_rows = []
                valid = True
                for item in data:
                    try:
                        rid = int(item["id"])
                        title = str(item["title"])
                        status = str(item["status"])
                        prio = int(item["priority"])
                        exp_rows.append((str(rid), title, status, str(prio)))
                    except Exception:
                        valid = False
                        break
                if valid:
                    act_rows = [tuple(r) for r in rows]
                    if set(exp_rows) == set(act_rows) and len(act_rows) == len(exp_rows) == 6:
                        scores["export_csv_matches_tasks_json"] = 1.0

    # Meeting notes checks
    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text:
        section_names = ["Summary", "Failures observed", "Fixes made", "Test results", "Next actions"]
        # Sections present?
        sections_present = True
        for nm in section_names:
            sec_lines = _extract_section(notes_text, nm, section_names)
            # Accept empty lines but require header presence
            header_present = re.search(rf'^\s*#*\s*{re.escape(nm)}\b', notes_text, flags=re.IGNORECASE | re.MULTILINE) is not None
            if not header_present:
                sections_present = False
                break
        if sections_present:
            scores["meeting_notes_sections_present"] = 1.0

        # Failures observed contains method names from before run
        if before_text:
            fail_names = _parse_failure_method_names(before_text)
            failures_section = _extract_section(notes_text, "Failures observed", section_names)
            failures_bullets = _section_bullets(failures_section)
            if fail_names and failures_bullets:
                all_listed = all(any(name in b for b in failures_bullets) for name in fail_names)
                if all_listed:
                    scores["meeting_notes_failures_listed"] = 1.0

            # Fixes made maps to failures
            fixes_section = _extract_section(notes_text, "Fixes made", section_names)
            fixes_bullets = _section_bullets(fixes_section)
            if fail_names and fixes_bullets:
                all_mapped = all(any(name in b for b in fixes_bullets) for name in fail_names)
                if all_mapped:
                    scores["meeting_notes_fixes_mapped_to_failures"] = 1.0

        # Test results counts consistent with after run
        tr_section = _extract_section(notes_text, "Test results", section_names)
        tr_text = "\n".join(tr_section)
        counts = _extract_counts_from_test_results_section(tr_text)
        if after_text:
            summary_a = _parse_unittest_summary(after_text)
            ran_a = summary_a.get("ran")
            ok_a = summary_a.get("ok")
            if ran_a is not None and ok_a:
                ran_ok = counts.get("ran") == ran_a
                passed_ok = counts.get("passed") == ran_a if counts.get("passed") is not None else False
                failed_ok = counts.get("failed") == 0 if counts.get("failed") is not None else False
                if ran_ok and passed_ok and failed_ok:
                    scores["meeting_notes_test_results_counts_consistent"] = 1.0

        # Next actions count between 3 and 5
        next_section = _extract_section(notes_text, "Next actions", section_names)
        next_bullets = _section_bullets(next_section)
        if 3 <= len(next_bullets) <= 5:
            scores["meeting_notes_next_actions_count_valid"] = 1.0

        # Summary sentence count 1-3 sentences
        summary_section = _extract_section(notes_text, "Summary", section_names)
        summary_text = " ".join([ln.strip() for ln in summary_section if ln.strip()])
        if summary_text:
            n_sent = _count_sentences(summary_text)
            if 1 <= n_sent <= 3:
                scores["meeting_notes_summary_sentence_count_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()