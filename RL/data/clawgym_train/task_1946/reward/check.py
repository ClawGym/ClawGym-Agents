import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        try:
            with path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return rows, reader.fieldnames
        except Exception:
            return None, None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_expected_aggregates(students_csv: Path, logs_csv: Path) -> Optional[Dict[str, Dict[str, object]]]:
    students_rows, students_fields = _load_csv_dicts(students_csv)
    logs_rows, logs_fields = _load_csv_dicts(logs_csv)
    if not students_rows or not logs_rows:
        return None

    # Build student info map
    student_info: Dict[str, Dict[str, str]] = {}
    for row in students_rows:
        sid = row.get("student_id")
        name = row.get("student_name")
        instrument = row.get("instrument")
        if sid is None or name is None or instrument is None:
            # missing required columns -> cannot compute
            return None
        student_info[sid] = {"student_name": name, "instrument": instrument}

    totals: Dict[str, int] = {}
    session_counts: Dict[str, int] = {}
    unique_days: Dict[str, set] = {}

    for row in logs_rows:
        sid = row.get("student_id")
        date = row.get("date")
        minutes_str = row.get("minutes")
        if sid is None or date is None or minutes_str is None:
            return None
        mins = _parse_int(minutes_str)
        if mins is None:
            return None
        totals[sid] = totals.get(sid, 0) + mins
        session_counts[sid] = session_counts.get(sid, 0) + 1
        unique_days.setdefault(sid, set()).add(date)

    # Only include students that appear in logs
    expected: Dict[str, Dict[str, object]] = {}
    for sid, total in totals.items():
        scount = session_counts.get(sid, 0)
        if scount == 0:
            continue
        avg = total / scount
        ucount = len(unique_days.get(sid, set()))
        info = student_info.get(sid, {"student_name": "Unknown", "instrument": ""})
        expected[sid] = {
            "student_id": sid,
            "student_name": info["student_name"],
            "instrument": info["instrument"],
            "session_count": scount,
            "total_minutes": total,
            "avg_minutes_per_session": avg,
            "unique_days_practiced": ucount,
        }
    return expected


def _load_summary(summary_csv: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return _load_csv_dicts(summary_csv)


def _rows_sorted_desc_by_key_int(rows: List[Dict[str, str]], key: str) -> bool:
    try:
        values = []
        for r in rows:
            v = _parse_int(str(r.get(key, "")))
            if v is None:
                return False
            values.append(v)
        return values == sorted(values, reverse=True)
    except Exception:
        return False


def _compare_summary_to_expected(rows: List[Dict[str, str]], expected: Dict[str, Dict[str, object]]) -> bool:
    # Build mapping by student_id from summary
    try:
        seen_ids = set()
        for r in rows:
            sid = r.get("student_id")
            if sid is None:
                return False
            seen_ids.add(sid)
        if set(expected.keys()) != seen_ids:
            return False

        for r in rows:
            sid = r["student_id"]
            exp = expected.get(sid)
            if exp is None:
                return False

            # Check name and instrument exact
            if r.get("student_name") != exp["student_name"]:
                return False
            if r.get("instrument") != exp["instrument"]:
                return False

            # Check integer fields
            sc = _parse_int(r.get("session_count", ""))
            tm = _parse_int(r.get("total_minutes", ""))
            ud = _parse_int(r.get("unique_days_practiced", ""))
            if sc is None or tm is None or ud is None:
                return False
            if sc != int(exp["session_count"]):
                return False
            if tm != int(exp["total_minutes"]):
                return False
            if ud != int(exp["unique_days_practiced"]):
                return False

            # Check avg within small tolerance
            av = _parse_float(r.get("avg_minutes_per_session", ""))
            if av is None:
                return False
            if abs(av - float(exp["avg_minutes_per_session"])) > 1e-6:
                return False
        return True
    except Exception:
        return False


def _extract_after_run_counts(text: str) -> Tuple[Optional[int], Optional[int]]:
    # Expect "Wrote summary to output/summary.csv (students: N, sessions: M)"
    # Extract N and M
    if text is None:
        return None, None
    # Try to find students count
    m_stu = re.search(r"students:\s*(\d+)", text)
    m_ses = re.search(r"sessions:\s*(\d+)", text)
    stu = int(m_stu.group(1)) if m_stu else None
    ses = int(m_ses.group(1)) if m_ses else None
    return stu, ses


def _email_has_failure_explanation(text: str) -> bool:
    if text is None:
        return False
    low = text.lower()
    # Look for mention of the wrong column "duration_minutes" vs correct "minutes"
    cond_cols = ("duration_minutes" in low) and ("minutes" in low)
    # Look for either explicit error name or mention of missing column/field
    cond_err = ("keyerror" in low) or (("missing" in low) and ("column" in low or "field" in low))
    return cond_cols and cond_err


def _compute_stats_from_summary(rows: List[Dict[str, str]]) -> Tuple[int, int, float, List[Tuple[str, int]]]:
    # Returns: total_students, total_sessions, avg_minutes_per_session, top2 [(name, total)]
    total_students = len(rows)
    total_sessions = 0
    total_minutes = 0
    per_student_totals: List[Tuple[str, int]] = []
    for r in rows:
        sc = _parse_int(r.get("session_count", ""))
        tm = _parse_int(r.get("total_minutes", ""))
        name = r.get("student_name", "")
        if sc is None or tm is None:
            raise ValueError("Malformed summary.csv numeric fields.")
        total_sessions += sc
        total_minutes += tm
        per_student_totals.append((name, tm))
    avg = (total_minutes / total_sessions) if total_sessions > 0 else 0.0
    per_student_totals.sort(key=lambda x: x[1], reverse=True)
    top2 = per_student_totals[:2]
    return total_students, total_sessions, avg, top2


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "before_run_log_captured_error": 0.0,
        "refactored_script_has_argparse_and_flags": 0.0,
        "refactored_script_uses_functions_and_docstrings": 0.0,
        "refactored_script_has_type_hints": 0.0,
        "summary_csv_header_order": 0.0,
        "summary_csv_aggregates_correct": 0.0,
        "summary_csv_sorted_by_total_minutes_desc": 0.0,
        "after_run_stdout_confirmation_correct": 0.0,
        "after_run_stdout_counts_match_summary": 0.0,
        "email_update_has_subject_and_attachment": 0.0,
        "email_update_explains_original_failure": 0.0,
        "email_update_reports_correct_stats": 0.0,
    }

    # 1) before_run.log should contain the KeyError and duration_minutes
    before_log_path = workspace / "output" / "before_run.log"
    before_text = _read_text_safe(before_log_path)
    if before_text is not None:
        has_keyerror = "KeyError" in before_text or "KeyError".lower() in before_text.lower()
        has_duration = "duration_minutes" in before_text
        has_traceback = "Traceback" in before_text
        if has_keyerror and has_duration and has_traceback:
            scores["before_run_log_captured_error"] = 1.0

    # 2) Refactored script structure checks
    refactored_path = workspace / "src" / "practice_stats_refactored.py"
    refactored_text = _read_text_safe(refactored_path)
    if refactored_text is not None:
        # argparse and flags
        has_argparse = ("import argparse" in refactored_text) or ("from argparse import" in refactored_text)
        has_logs_flag = "--logs" in refactored_text
        has_students_flag = "--students" in refactored_text
        has_outcsv_flag = "--out-csv" in refactored_text
        if has_argparse and has_logs_flag and has_students_flag and has_outcsv_flag:
            scores["refactored_script_has_argparse_and_flags"] = 1.0

        # functions and docstrings
        has_def = "def " in refactored_text
        has_docstring = '"""' in refactored_text or "'''" in refactored_text
        if has_def and has_docstring:
            scores["refactored_script_uses_functions_and_docstrings"] = 1.0

        # type hints: look for "->" in def lines
        has_return_hint = re.search(r"def\s+\w+\(.*\)\s*->\s*[\w\[\], \.]+:", refactored_text) is not None
        if has_return_hint:
            scores["refactored_script_has_type_hints"] = 1.0

    # 3) Summary CSV checks
    summary_path = workspace / "output" / "summary.csv"
    summary_rows, summary_fields = _load_csv_dicts(summary_path)
    if summary_rows is not None and summary_fields is not None:
        expected_header = [
            "student_id",
            "student_name",
            "instrument",
            "session_count",
            "total_minutes",
            "avg_minutes_per_session",
            "unique_days_practiced",
        ]
        if summary_fields == expected_header:
            scores["summary_csv_header_order"] = 1.0

        # Aggregates correctness
        expected = _compute_expected_aggregates(workspace / "input" / "students.csv", workspace / "input" / "practice_logs.csv")
        if expected is not None and _compare_summary_to_expected(summary_rows, expected):
            scores["summary_csv_aggregates_correct"] = 1.0

        # Sorted descending by total_minutes
        if _rows_sorted_desc_by_key_int(summary_rows, "total_minutes"):
            scores["summary_csv_sorted_by_total_minutes_desc"] = 1.0

    # 4) After run stdout checks
    after_run_path = workspace / "output" / "after_run.txt"
    after_text = _read_text_safe(after_run_path)
    if after_text is not None:
        path_phrase = "Wrote summary to output/summary.csv"
        has_phrase = path_phrase in after_text
        stu_count, ses_count = _extract_after_run_counts(after_text)
        if has_phrase and (stu_count is not None) and (ses_count is not None):
            scores["after_run_stdout_confirmation_correct"] = 1.0

        # Match counts to summary.csv if available
        if summary_rows is not None and summary_fields is not None and stu_count is not None and ses_count is not None:
            try:
                total_students, total_sessions, _, _ = _compute_stats_from_summary(summary_rows)
                if stu_count == total_students and ses_count == total_sessions:
                    scores["after_run_stdout_counts_match_summary"] = 1.0
            except Exception:
                pass

    # 5) Email update checks
    email_path = workspace / "output" / "email_update.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        has_subject = email_text.strip().lower().startswith("subject:") or "subject:" in email_text.lower()
        mentions_attachment = "output/summary.csv" in email_text
        if has_subject and mentions_attachment:
            scores["email_update_has_subject_and_attachment"] = 1.0

        if _email_has_failure_explanation(email_text):
            scores["email_update_explains_original_failure"] = 1.0

        # Stats correctness based on summary.csv
        if summary_rows is not None:
            try:
                total_students, total_sessions, avg_all, top2 = _compute_stats_from_summary(summary_rows)
                total_minutes_all = sum(_parse_int(r.get("total_minutes", "0")) or 0 for r in summary_rows)
                avg_str = f"{avg_all:.1f}"
                # top2 list of tuples (name, total)
                # Check presence of numbers and names
                has_total_minutes = str(total_minutes_all) in email_text
                has_avg = avg_str in email_text
                top2_ok = True
                for name, total in top2:
                    if (name not in email_text) or (str(total) not in email_text):
                        top2_ok = False
                        break
                if has_total_minutes and has_avg and top2_ok:
                    scores["email_update_reports_correct_stats"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()