import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(p: Path) -> Optional[List[dict]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        # basic header validation
        required = {"id", "topic", "action", "due_date", "status", "source_note"}
        if not set(reader.fieldnames or []) >= required:
            return None
        return rows
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_reminders(csv_rows: List[dict], as_of_str: str) -> Optional[List[str]]:
    as_of = _parse_iso_date(as_of_str)
    if as_of is None:
        return None
    window_end = as_of + timedelta(days=6)
    items = []
    for row in csv_rows:
        status = (row.get("status") or "").strip().lower()
        if status != "pending":
            continue
        due_str = (row.get("due_date") or "").strip()
        due_dt = _parse_iso_date(due_str)
        if due_dt is None:
            return None
        if as_of <= due_dt <= window_end:
            topic = (row.get("topic") or "").strip()
            action = (row.get("action") or "").strip()
            source = (row.get("source_note") or "").strip()
            basename = Path(source).name
            line = f"{due_str} | {topic} | {action} | {basename}"
            items.append((due_dt, line))
    items.sort(key=lambda x: x[0])
    return [li for _, li in items]


def _run_weekly_script(workspace: Path, as_of_str: str) -> Tuple[bool, str]:
    script = workspace / "scripts" / "weekly_reminder.py"
    if not script.exists():
        return False, ""
    cmds = [
        ["python3", str(script), "--as-of", as_of_str],
        ["python", str(script), "--as-of", as_of_str],
    ]
    for cmd in cmds:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
                encoding="utf-8",
            )
            if proc.returncode == 0:
                return True, proc.stdout
        except Exception:
            continue
    return False, ""


def _split_nonempty_lines(text: str) -> List[str]:
    return [ln.rstrip("\n").strip() for ln in text.splitlines() if ln.strip() != ""]


def _count_nonempty_lines_in_file(p: Path) -> Optional[int]:
    txt = _safe_read_text(p)
    if txt is None:
        return None
    return len(_split_nonempty_lines(txt))


def _extract_paragraphs_after_greeting(lines: List[str], greeting: str) -> List[List[str]]:
    # Find greeting line index
    try:
        greet_idx = next(i for i, ln in enumerate(lines) if ln.strip() == greeting)
    except StopIteration:
        greet_idx = -1
    # Collect lines after greeting
    start = greet_idx + 1 if greet_idx >= 0 else 0
    body = lines[start:]
    paragraphs = []
    current = []
    for ln in body:
        if ln.strip() == "":
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        paragraphs.append(current)
    return paragraphs


def _find_bullet_lines(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* "):
            bullets.append(ln.strip())
    return bullets


def _find_section_bullets(lines: List[str], section_title_patterns: List[str], stop_title_patterns: List[str]) -> List[str]:
    # Find section start
    start_idx = None
    for i, ln in enumerate(lines):
        lns = ln.strip()
        for pat in section_title_patterns:
            if re.fullmatch(pat, lns, flags=re.IGNORECASE):
                start_idx = i + 1
                break
        if start_idx is not None:
            break
    if start_idx is None:
        return []
    bullets = []
    for ln in lines[start_idx:]:
        lns = ln.strip()
        if lns == "":
            # allow blank lines inside section; continue to read until a stop title is found
            pass
        for sp in stop_title_patterns:
            if re.fullmatch(sp, lns, flags=re.IGNORECASE):
                return bullets
        if lns.startswith("- ") or lns.startswith("* "):
            bullets.append(lns)
    return bullets


def _extract_number_after_label(text: str, label_pattern: str) -> Optional[int]:
    m = re.search(label_pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_overdue_entries(lines: List[str]) -> List[Tuple[str, str, str]]:
    entries = []
    pattern = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*[–-]\s*(.+?)\s*[–-]\s*(\d+)\s*$")
    for ln in lines:
        m = pattern.match(ln)
        if m:
            entries.append((m.group(1), m.group(2), m.group(3)))
    return entries


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_script_exists": 0.0,
        "reminders_file_matches_expected": 0.0,
        "weekly_script_run_matches_expected": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_paragraphs_and_references": 0.0,
        "email_three_questions_with_note_dates": 0.0,
        "email_meeting_options": 0.0,
        "themes_section_bullets_valid": 0.0,
        "status_totals_correct": 0.0,
        "overdue_list_correct": 0.0,
        "upcoming_count_and_crosscheck": 0.0,
    }

    # Prepare input data
    csv_path = workspace / "input" / "followups.csv"
    rows = _safe_load_csv(csv_path)
    notes_0312 = workspace / "input" / "notes" / "professor_notes_2026-03-12.md"
    notes_0319 = workspace / "input" / "notes" / "professor_notes_2026-03-19.md"

    # Compute expected reminders for as-of 2026-05-01
    as_of_str = "2026-05-01"
    expected_lines = None
    if rows is not None:
        expected_lines = _compute_expected_reminders(rows, as_of_str)

    # Check script existence
    script_path = workspace / "scripts" / "weekly_reminder.py"
    if script_path.exists() and script_path.is_file():
        scores["weekly_script_exists"] = 1.0

    # Validate output/next_week_reminders.txt against expected
    reminders_file = workspace / "output" / "next_week_reminders.txt"
    if expected_lines is not None:
        txt = _safe_read_text(reminders_file)
        if txt is not None:
            produced_lines = _split_nonempty_lines(txt)
            if produced_lines == expected_lines:
                scores["reminders_file_matches_expected"] = 1.0

    # Run script and compare stdout to expected
    if expected_lines is not None:
        ran, stdout = _run_weekly_script(workspace, as_of_str)
        if ran:
            run_lines = _split_nonempty_lines(stdout)
            if run_lines == expected_lines:
                scores["weekly_script_run_matches_expected"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_professor.md"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = email_text.splitlines()
        # Subject line exact match as first line
        expected_subject = "Subject: Follow-up on golden age cinema anecdotes and art progress"
        subject_ok = len(lines) >= 1 and lines[0].strip() == expected_subject
        # Greeting present
        greeting = "Dear Professor Rivera,"
        greeting_ok = any(ln.strip() == greeting for ln in lines)
        if subject_ok and greeting_ok:
            scores["email_subject_and_greeting"] = 1.0

        # Two short paragraphs referencing at least two concepts
        paragraphs = _extract_paragraphs_after_greeting(lines, greeting)
        # count non-empty paragraphs
        para_count = sum(1 for p in paragraphs if any(ln.strip() for ln in p))
        # concept references (case-insensitive)
        concepts = [
            "italian neorealism",
            "deep focus",
            "german expressionism",
            "kammerspielfilm",
            "soviet montage",
            "french poetic realism",
            "rko lighting",
            "rko",
        ]
        lower_text = email_text.lower()
        concept_hits = set()
        for c in concepts:
            if c in lower_text:
                # normalize some (treat 'rko lighting' and 'rko' as rko)
                if c.startswith("rko"):
                    concept_hits.add("rko")
                else:
                    concept_hits.add(c)
        if para_count >= 2 and len(concept_hits) >= 2:
            scores["email_paragraphs_and_references"] = 1.0

        # Bullet list of exactly three follow-up questions tied to note dates
        bullet_lines = _find_bullet_lines(lines)
        # filter bullets that look like questions and reference a date
        bullets_ok = False
        if len(bullet_lines) == 3:
            bullets_ok = True
            for bl in bullet_lines:
                has_qmark = "?" in bl
                has_date = ("2026-03-12" in bl) or ("2026-03-19" in bl)
                if not (has_qmark and has_date):
                    bullets_ok = False
                    break
        if bullets_ok:
            scores["email_three_questions_with_note_dates"] = 1.0

        # Closing proposing two 30–60 minute meeting options between 2026-05-05 and 2026-05-14
        dates_in_window = set(re.findall(r"2026-05-(0[5-9]|1[0-4])", email_text))
        # We need actual full dates, reconstruct from captures
        full_dates = set()
        for dd in dates_in_window:
            full_dates.add(f"2026-05-{dd}")
        time_window_ok = len(full_dates) >= 2
        duration_ok = re.search(r"30\s*[–-]\s*60", email_text) is not None
        if time_window_ok and duration_ok:
            scores["email_meeting_options"] = 1.0

    # inspiration_progress.md checks
    progress_path = workspace / "output" / "inspiration_progress.md"
    progress_text = _safe_read_text(progress_path)
    if progress_text is not None:
        plines = progress_text.splitlines()

        # Themes section: 3–5 bullets referencing note filename and date
        # Accept both curly and straight apostrophe in the section title
        themes_title_patterns = [
            r"Themes from Professor’s Stories:?",
            r"Themes from Professor's Stories:?",
        ]
        stop_title_patterns = [
            r"Follow-up Status Summary.*",
        ]
        theme_bullets = _find_section_bullets(plines, themes_title_patterns, stop_title_patterns)
        if 3 <= len(theme_bullets) <= 5:
            # Check each bullet references filename and date
            tb_ok = True
            for b in theme_bullets:
                has_file = ("professor_notes_2026-03-12.md" in b) or ("professor_notes_2026-03-19.md" in b)
                has_date = ("2026-03-12" in b) or ("2026-03-19" in b)
                if not (has_file and has_date):
                    tb_ok = False
                    break
            if tb_ok:
                scores["themes_section_bullets_valid"] = 1.0

        # Follow-up Status Summary counts
        # Total pending and done
        totals_ok = False
        if rows is not None:
            expected_pending = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "pending")
            expected_done = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "done")
            # Extract numbers anywhere in file
            pending_num = _extract_number_after_label(progress_text, r"Total pending count[^0-9]*(\d+)")
            done_num = _extract_number_after_label(progress_text, r"Total done count[^0-9]*(\d+)")
            if pending_num == expected_pending and done_num == expected_done:
                totals_ok = True
        if totals_ok:
            scores["status_totals_correct"] = 1.0

        # Overdue list correctness (pending items with due_date < 2026-05-01)
        overdue_ok = False
        if rows is not None:
            as_of = _parse_iso_date(as_of_str)
            if as_of:
                overdue_expected = []
                for r in rows:
                    if (r.get("status") or "").strip().lower() != "pending":
                        continue
                    due = _parse_iso_date((r.get("due_date") or "").strip())
                    if due and due < as_of:
                        overdue_expected.append(((r.get("due_date") or "").strip(), (r.get("topic") or "").strip(), (r.get("id") or "").strip()))
                # Find overdue section lines
                # Gather all candidate lines after an 'Overdue' header
                overdue_lines = []
                capture = False
                for ln in plines:
                    if re.search(r"Overdue\s*\(pending items with due_date <\s*2026-05-01\)", ln, flags=re.IGNORECASE):
                        capture = True
                        continue
                    if capture:
                        # Stop capturing if next section starts
                        if re.search(r"Upcoming within 7 days count", ln, flags=re.IGNORECASE):
                            break
                        overdue_lines.append(ln.strip())
                # Parse entries
                parsed = _parse_overdue_entries(overdue_lines)
                # Filter out empty lines
                parsed = [(d, t, i) for (d, t, i) in parsed]
                # Compare sets
                expected_set = set(overdue_expected)
                parsed_set = set(parsed)
                if expected_set == parsed_set:
                    overdue_ok = True
        if overdue_ok:
            scores["overdue_list_correct"] = 1.0

        # Upcoming within 7 days count and cross-check with reminders file lines
        upcoming_ok = False
        if rows is not None:
            # Compute expected upcoming count
            as_of = _parse_iso_date(as_of_str)
            if as_of:
                window_end = as_of + timedelta(days=6)
                expected_upcoming = 0
                for r in rows:
                    if (r.get("status") or "").strip().lower() != "pending":
                        continue
                    due = _parse_iso_date((r.get("due_date") or "").strip())
                    if due and as_of <= due <= window_end:
                        expected_upcoming += 1
                # Extract reported upcoming within 7 days count
                upcoming_num = _extract_number_after_label(progress_text, r"Upcoming within 7 days count[^0-9]*(\d+)")
                # Cross-check with next_week_reminders.txt
                reminders_count = _count_nonempty_lines_in_file(reminders_file)
                if upcoming_num == expected_upcoming and reminders_count == expected_upcoming:
                    upcoming_ok = True
        if upcoming_ok:
            scores["upcoming_count_and_crosscheck"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()