import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def parse_week4_from_syllabus(syllabus_text: str) -> Dict[str, Optional[object]]:
    lines = [ln.rstrip("\n") for ln in syllabus_text.splitlines()]
    week_idx = None
    topic = None
    readings: List[str] = []
    deliverable_title = None
    deliverable_due = None
    # Find Week 4 line
    for i, ln in enumerate(lines):
        m = re.match(r"^Week\s*4\s*\([0-9]{4}-[0-9]{2}-[0-9]{2}\):\s*(.+)$", ln.strip())
        if m:
            week_idx = i
            topic = m.group(1).strip()
            break
    if week_idx is None:
        return {"topic": None, "readings": [], "deliverable_title": None, "deliverable_due": None}
    # Parse following lines until next "Week " starts
    i = week_idx + 1
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("Week "):
            break
        m_read = re.match(r"^-\s*Readings:\s*(.+)$", ln)
        if m_read:
            # Split by semicolons that separate readings
            raw = m_read.group(1).strip()
            # The readings are separated by ';'
            parts = [p.strip() for p in raw.split(";")]
            # Filter out empty parts
            readings = [p for p in parts if p]
        m_deliv = re.match(r"^-\s*Deliverables:\s*(.+)$", ln)
        if m_deliv:
            val = m_deliv.group(1).strip()
            if val.lower() != "none":
                md = re.match(r"^(.*?)\s+due\s+(.+)$", val, flags=re.IGNORECASE)
                if md:
                    deliverable_title = md.group(1).strip()
                    deliverable_due = md.group(2).strip()
        i += 1
    return {
        "topic": topic,
        "readings": readings,
        "deliverable_title": deliverable_title,
        "deliverable_due": deliverable_due,
    }


def extract_open_questions(notes_text: str) -> List[str]:
    lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]
    oq_start = None
    for i, ln in enumerate(lines):
        if re.match(r"^##\s*Open questions for next time", ln, flags=re.IGNORECASE):
            oq_start = i + 1
            break
    if oq_start is None:
        return []
    questions: List[str] = []
    i = oq_start
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^##\s", ln) or re.match(r"^#\s", ln):
            break
        m = re.match(r"^\s*-\s+(.*)$", ln)
        if m:
            questions.append(m.group(1).strip())
        i += 1
    return questions


def parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def parse_datetime(dt_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    except Exception:
        return None


def within_date_range(date_obj: datetime, start_date: datetime, end_date: datetime) -> bool:
    return start_date.date() <= date_obj.date() <= end_date.date()


def line_contains_tokens(line: str, tokens: List[str]) -> bool:
    s = line.strip()
    return all(tok in s for tok in tokens)


def split_summary_sections(summary_text: str, headings: List[str]) -> Optional[Dict[str, List[str]]]:
    lines = [ln.rstrip("\n") for ln in summary_text.splitlines()]
    # Find indices of exact-heading lines
    indices = []
    for h in headings:
        found = None
        for idx, ln in enumerate(lines):
            if ln.strip() == h:
                if idx in [pos for pos, _ in indices]:
                    continue
                found = idx
                break
        if found is None:
            return None
        indices.append((found, h))
    # Ensure order is strictly increasing
    idx_positions = [pos for pos, _ in indices]
    if idx_positions != sorted(idx_positions):
        return None
    # Build sections
    sections: Dict[str, List[str]] = {}
    for i, (pos, h) in enumerate(indices):
        end = idx_positions[i + 1] if i + 1 < len(idx_positions) else len(lines)
        content_lines = lines[pos + 1 : end]
        sections[h] = content_lines
    return sections


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "summary_file_exists": 0.0,
        "summary_has_required_headings_and_order": 0.0,
        "summary_week_section_correct": 0.0,
        "summary_meetings_listed_correctly": 0.0,
        "summary_readings_week4_listed": 0.0,
        "summary_deadlines_in_range_listed_correctly": 0.0,
        "summary_open_questions_listed": 0.0,
        "summary_discrepancies_section_correct": 0.0,
        "email_file_exists": 0.0,
        "email_to_line_correct": 0.0,
        "email_subject_line_correct": 0.0,
        "email_body_mentions_earliest_meeting": 0.0,
        "email_includes_readings_bullets": 0.0,
        "email_includes_deadlines_bullets": 0.0,
        "email_includes_open_questions_bullets": 0.0,
        "email_excludes_out_of_range_deadline": 0.0,
    }

    # Input files
    syllabus_path = workspace / "input" / "syllabus.md"
    meeting_csv_path = workspace / "input" / "meeting_times.csv"
    tasks_json_path = workspace / "input" / "tasks.json"
    notes_path = workspace / "input" / "notes.md"
    roster_csv_path = workspace / "input" / "roster.csv"

    syllabus_text = safe_read_text(syllabus_path) or ""
    meeting_rows = safe_load_csv_dicts(meeting_csv_path)
    tasks_list = safe_load_json(tasks_json_path)
    notes_text = safe_read_text(notes_path) or ""
    roster_rows = safe_load_csv_dicts(roster_csv_path)

    # Expected derived data
    week4 = parse_week4_from_syllabus(syllabus_text) if syllabus_text else {"topic": None, "readings": [], "deliverable_title": None, "deliverable_due": None}
    open_questions = extract_open_questions(notes_text) if notes_text else []

    # Meeting filtering
    start_date = parse_date("2024-10-14")
    end_date = parse_date("2024-10-20")
    meetings_in_range: List[Dict[str, str]] = []
    if meeting_rows is not None and start_date and end_date:
        for row in meeting_rows:
            d = parse_date(row.get("date", ""))
            if d and within_date_range(d, start_date, end_date):
                meetings_in_range.append(row)

    # Determine earliest meeting
    earliest = None
    if meetings_in_range:
        try:
            earliest = sorted(meetings_in_range, key=lambda r: (r.get("date", ""), r.get("start_time", "")))[0]
        except Exception:
            earliest = None

    # Tasks filtering
    tasks_in_range: List[Dict[str, str]] = []
    if isinstance(tasks_list, list) and start_date and end_date:
        for item in tasks_list:
            due_str = item.get("due", "")
            dt = parse_datetime(due_str)
            if dt and within_date_range(dt, start_date, end_date):
                tasks_in_range.append(item)

    # Build email list
    emails_in_order: List[str] = []
    if roster_rows is not None:
        for row in roster_rows:
            if "email" in row and row["email"]:
                emails_in_order.append(row["email"].strip())

    # Outputs
    summary_path = workspace / "outputs" / "weekly" / "2024-10-14_summary.md"
    email_path = workspace / "outputs" / "weekly" / "2024-10-14_email_draft.txt"

    summary_text = safe_read_text(summary_path)
    email_text = safe_read_text(email_path)

    # summary_file_exists
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0

    # summary_has_required_headings_and_order
    section_headings = ["Week", "Meetings", "Readings", "Deadlines", "Open Questions", "Discrepancies"]
    sections = None
    if summary_text is not None:
        sections = split_summary_sections(summary_text, section_headings)
        if sections is not None and all(h in sections for h in section_headings):
            scores["summary_has_required_headings_and_order"] = 1.0

    # summary_week_section_correct
    if sections is not None and week4.get("topic"):
        week_lines = sections.get("Week", [])
        week_content = "\n".join(week_lines)
        has_range = "2024-10-14 to 2024-10-20" in week_content
        has_topic = week4["topic"] in week_content
        if has_range and has_topic:
            scores["summary_week_section_correct"] = 1.0

    # summary_meetings_listed_correctly
    if sections is not None and meeting_rows is not None and start_date and end_date:
        meet_lines = sections.get("Meetings", [])
        found_all = True
        # Check included ones
        for m in meetings_in_range:
            tokens = [m.get("date", ""), m.get("start_time", ""), m.get("end_time", ""), m.get("location", "")]
            if not any(line_contains_tokens(ln, tokens) for ln in meet_lines):
                found_all = False
                break
        # Ensure excluded not present
        excluded_ok = True
        for row in meeting_rows:
            d = parse_date(row.get("date", ""))
            if d and not within_date_range(d, start_date, end_date):
                # If out-of-range meeting appears in section, fail
                if any(row.get("date", "") in ln for ln in meet_lines):
                    excluded_ok = False
                    break
        if found_all and excluded_ok and len(meetings_in_range) > 0:
            scores["summary_meetings_listed_correctly"] = 1.0

    # summary_readings_week4_listed
    if sections is not None and week4.get("readings") is not None:
        read_lines = sections.get("Readings", [])
        has_all = all(any(r in ln for ln in read_lines) for r in week4["readings"])
        # Ensure readings from other weeks not present
        other_week_markers = ["Anselm", "Aquinas", "Gustavo Gutiérrez"]
        others_absent = not any(any(marker in ln for marker in other_week_markers) for ln in read_lines)
        if has_all and others_absent and len(week4["readings"]) > 0:
            scores["summary_readings_week4_listed"] = 1.0

    # summary_deadlines_in_range_listed_correctly
    if sections is not None and isinstance(tasks_list, list):
        deadline_lines = sections.get("Deadlines", [])
        # Check included tasks present with title and due on same line
        ok_included = True
        for t in tasks_in_range:
            title = t.get("title", "")
            due = t.get("due", "")
            if not any(title in ln and due in ln for ln in deadline_lines):
                ok_included = False
                break
        # Check excluded tasks not present
        ok_excluded = True
        for t in tasks_list:
            due_str = t.get("due", "")
            dt = parse_datetime(due_str)
            if not (dt and start_date and end_date and within_date_range(dt, start_date, end_date)):
                # If out-of-range appears, fail
                if any(t.get("title", "") in ln for ln in deadline_lines):
                    ok_excluded = False
                    break
        if ok_included and ok_excluded and len(tasks_in_range) > 0:
            scores["summary_deadlines_in_range_listed_correctly"] = 1.0

    # summary_open_questions_listed
    if sections is not None and open_questions:
        oq_lines = sections.get("Open Questions", [])
        oq_ok = all(any(q in ln for ln in oq_lines) for q in open_questions)
        if oq_ok:
            scores["summary_open_questions_listed"] = 1.0

    # summary_discrepancies_section_correct
    if sections is not None and week4.get("deliverable_title") and week4.get("deliverable_due") is not None and isinstance(tasks_list, list):
        # Find matching task in tasks.json for reflection journal #2 (case-insensitive contains)
        syllabus_title = week4["deliverable_title"]
        syllabus_due = week4["deliverable_due"]
        # We check if any task has title containing "Reflection journal #2" case-insensitive
        match_tasks = [t for t in tasks_list if "title" in t and re.search(r"reflection journal #2", t["title"], flags=re.IGNORECASE)]
        # Determine expected message
        expected_msg = "No date discrepancies found for Reflection journal #2."
        discrepancy_ok = False
        disc_lines = sections.get("Discrepancies", [])
        disc_text = "\n".join(disc_lines)
        if match_tasks:
            # If any match has due equal to syllabus due, we expect the exact sentence
            if any(t.get("due", "") == syllabus_due for t in match_tasks):
                # Check exact sentence present on its own line
                if any(ln.strip() == expected_msg for ln in disc_lines):
                    discrepancy_ok = True
        # If no matching tasks or mismatch, we expect listing both dates/times; but for grading deterministically, we require the exact "No date..." when inputs match.
        if discrepancy_ok:
            scores["summary_discrepancies_section_correct"] = 1.0

    # email_file_exists
    if email_text is not None:
        scores["email_file_exists"] = 1.0

    # email_to_line_correct
    if email_text is not None and emails_in_order:
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if len(email_lines) >= 1:
            expected_to = "To: " + ";".join(emails_in_order)
            if email_lines[0].strip() == expected_to:
                scores["email_to_line_correct"] = 1.0

    # email_subject_line_correct
    if email_text is not None and week4.get("topic"):
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if len(email_lines) >= 2:
            expected_subject = "Subject: Study Group – Week of 2024-10-14: " + week4["topic"]
            if email_lines[1].strip() == expected_subject:
                scores["email_subject_line_correct"] = 1.0

    # email_body_mentions_earliest_meeting
    if email_text is not None and earliest:
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        body = "\n".join(email_lines[2:]) if len(email_lines) > 2 else ""
        tokens = [earliest.get("date", ""), earliest.get("start_time", ""), earliest.get("end_time", ""), earliest.get("location", "")]
        if all(tok in body for tok in tokens):
            scores["email_body_mentions_earliest_meeting"] = 1.0

    # email_includes_readings_bullets
    if email_text is not None and week4.get("readings"):
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        body_lines = email_lines[2:] if len(email_lines) > 2 else []
        bullet_lines = [ln for ln in body_lines if re.match(r"^\s*[-*]\s", ln)]
        ok_reads = all(any(r in bl for bl in bullet_lines) for r in week4["readings"])
        if ok_reads:
            scores["email_includes_readings_bullets"] = 1.0

    # email_includes_deadlines_bullets
    if email_text is not None and tasks_in_range:
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        body_lines = email_lines[2:] if len(email_lines) > 2 else []
        bullet_lines = [ln for ln in body_lines if re.match(r"^\s*[-*]\s", ln)]
        ok_deadlines = True
        for t in tasks_in_range:
            title = t.get("title", "")
            due = t.get("due", "")
            if not any(title in bl and due in bl for bl in bullet_lines):
                ok_deadlines = False
                break
        if ok_deadlines:
            scores["email_includes_deadlines_bullets"] = 1.0

    # email_includes_open_questions_bullets
    if email_text is not None and open_questions:
        email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        body_lines = email_lines[2:] if len(email_lines) > 2 else []
        bullet_lines = [ln for ln in body_lines if re.match(r"^\s*[-*]\s", ln)]
        ok_oq = all(any(q in bl for bl in bullet_lines) for q in open_questions)
        if ok_oq:
            scores["email_includes_open_questions_bullets"] = 1.0

    # email_excludes_out_of_range_deadline
    if email_text is not None and isinstance(tasks_list, list):
        # Ensure "Midterm essay outline" (due 2024-10-27) is not included
        out_title = None
        for t in tasks_list:
            if t.get("title") == "Midterm essay outline":
                out_title = t.get("title")
                break
        if out_title:
            if out_title not in email_text:
                scores["email_excludes_out_of_range_deadline"] = 1.0
        else:
            # If not present in inputs, treat as pass (no out-of-range to exclude)
            scores["email_excludes_out_of_range_deadline"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()