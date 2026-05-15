import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_time(s: str) -> Optional[datetime.time]:
    try:
        return datetime.strptime(s, "%H:%M").time()
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _agenda_selection_marked(line: str) -> bool:
    lower = line.lower()
    if "selected" in lower or "chosen" in lower:
        return True
    # look for common markers around selection
    markers = ["->", "=>", "[x]", "[X]", "(selected)", "(chosen)"]
    for m in markers:
        if m in line:
            return True
    # leading star can be a marker
    if re.match(r"^\s*[\*\u2022]\s*", line):
        return True
    return False


def _lines_contain_action_for(lines: List[str], task: str, assignee: Optional[str], due_date: str, due_time: str) -> bool:
    # Find a line with the task name; then in a small window ensure due date and time are present.
    # If assignee is provided, also ensure it's present in the window.
    for i, line in enumerate(lines):
        if task.lower() in line.lower():
            window = "\n".join(lines[i:i+2])  # current line and next line
            if due_date in window and due_time in window:
                if assignee is None or (assignee.lower() in window.lower()):
                    return True
    return False


def _compute_expected_schedule(workspace: Path) -> Optional[List[Dict[str, str]]]:
    tasks_path = workspace / "input" / "tasks.csv"
    events_path = workspace / "input" / "events.csv"
    tasks = _safe_load_csv(tasks_path)
    events = _safe_load_csv(events_path)
    if tasks is None or events is None:
        return None

    start_date = _parse_date("2026-04-18")
    end_date = _parse_date("2026-04-25")
    if start_date is None or end_date is None:
        return None

    combined = []

    # Events
    for ev in events:
        d = _parse_date(ev.get("date", ""))
        if d is None:
            continue
        if start_date <= d <= end_date:
            row = {
                "kind": "event",
                "id": ev.get("id", ""),
                "title_or_task": ev.get("title", ""),
                "course": ev.get("course", ""),
                "date": ev.get("date", ""),
                "time": ev.get("time", ""),
                "location": ev.get("location", "") if ev.get("location", "") is not None else "",
                "assigned_to": "",
                "score": str(ev.get("importance", "")).strip(),
            }
            combined.append(row)

    # Tasks
    for t in tasks:
        d = _parse_date(t.get("due_date", ""))
        if d is None:
            continue
        if start_date <= d <= end_date:
            row = {
                "kind": "task",
                "id": t.get("id", ""),
                "title_or_task": t.get("task", ""),
                "course": t.get("course", ""),
                "date": t.get("due_date", ""),
                "time": t.get("due_time", ""),
                "location": "",
                "assigned_to": t.get("assigned_to", "") if t.get("assigned_to", "") is not None else "",
                "score": str(t.get("priority", "")).strip(),
            }
            combined.append(row)

    def sort_key(r: Dict[str, str]):
        # score desc, then date/time asc
        try:
            score = int(str(r.get("score", "0")).strip())
        except Exception:
            score = -10**9
        d = _parse_date(r.get("date", ""))
        tm = _parse_time(r.get("time", "00:00"))
        # If parsing fails, push to end for asc sorts
        d_tuple = (d or datetime(2999, 12, 31).date())
        t_tuple = (tm or datetime.strptime("23:59", "%H:%M").time())
        return (-score, d_tuple, t_tuple)

    combined.sort(key=sort_key)
    # Assign rank
    for idx, r in enumerate(combined, start=1):
        r["rank"] = str(idx)

    return combined


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "week_schedule_exists_and_columns": 0.0,
        "week_schedule_row_count": 0.0,
        "week_schedule_filter_and_values": 0.0,
        "week_schedule_sort_and_rank": 0.0,
        "agenda_choice_listed_files": 0.0,
        "agenda_choice_selected_file": 0.0,
        "meeting_notes_title_time_location_purpose": 0.0,
        "meeting_notes_agenda_items": 0.0,
        "meeting_notes_attendees": 0.0,
        "meeting_notes_action_items": 0.0,
        "student_emails_subject_and_body": 0.0,
        "student_emails_action_items": 0.0,
        "advisor_email_content": 0.0,
    }

    # Prepare expected computed artifacts
    expected_schedule = _compute_expected_schedule(workspace)
    expected_ids = set()
    expected_by_id = {}
    expected_order_ids = []
    if expected_schedule is not None:
        for r in expected_schedule:
            expected_ids.add(r["id"])
            expected_by_id[r["id"]] = r
            expected_order_ids.append(r["id"])

    # 1) Check week_schedule.csv
    week_schedule_path = workspace / "output" / "week_schedule.csv"
    required_columns = ["kind", "id", "title_or_task", "course", "date", "time", "location", "assigned_to", "score", "rank"]
    actual_rows = None
    if week_schedule_path.exists():
        actual_rows = _safe_load_csv(week_schedule_path)
    if actual_rows is not None and isinstance(actual_rows, list) and len(actual_rows) >= 0:
        actual_fieldnames = []
        try:
            with week_schedule_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                actual_fieldnames = header if header else []
        except Exception:
            actual_fieldnames = []

        if all(col in actual_fieldnames for col in required_columns):
            scores["week_schedule_exists_and_columns"] = 1.0

        # row count
        if expected_schedule is not None and len(actual_rows) == len(expected_schedule):
            scores["week_schedule_row_count"] = 1.0

        # filter and values
        if expected_schedule is not None:
            actual_ids = [r.get("id", "") for r in actual_rows]
            if set(actual_ids) == expected_ids:
                # verify values for required columns
                values_ok = True
                for r in actual_rows:
                    eid = r.get("id", "")
                    exp = expected_by_id.get(eid)
                    if exp is None:
                        values_ok = False
                        break
                    for col in ["kind", "title_or_task", "course", "date", "time", "location", "assigned_to", "score"]:
                        aval = "" if r.get(col) is None else str(r.get(col))
                        evals = "" if exp.get(col) is None else str(exp.get(col))
                        if aval != evals:
                            values_ok = False
                            break
                    if not values_ok:
                        break
                if values_ok:
                    scores["week_schedule_filter_and_values"] = 1.0

            # sort and rank
            if set(actual_ids) == expected_ids:
                # Check order equals expected order
                order_ok = [r.get("id", "") for r in actual_rows] == expected_order_ids
                # Check rank sequence 1..N in order
                rank_ok = True
                for idx, r in enumerate(actual_rows, start=1):
                    if str(r.get("rank", "")).strip() != str(idx):
                        rank_ok = False
                        break
                if order_ok and rank_ok:
                    scores["week_schedule_sort_and_rank"] = 1.0

    # 2) Agenda choice
    agendas_dir = workspace / "input" / "agendas"
    expected_agenda_files = []
    if agendas_dir.exists():
        for p in sorted(agendas_dir.glob("*")):
            if p.is_file():
                expected_agenda_files.append(p.name)
    chosen_expected_filename = "agenda_2026-04-22_team_meeting.md"
    nonchosen_filename = "agenda_2026-04-15_team_meeting.md"
    agenda_choice_path = workspace / "output" / "inspected" / "agenda_choice.txt"
    agenda_choice_text = _safe_read_text(agenda_choice_path) if agenda_choice_path.exists() else None
    if agenda_choice_text is not None:
        # Listed files check: ensure all agenda files are mentioned
        listed_ok = True
        for fname in expected_agenda_files:
            if fname not in agenda_choice_text:
                listed_ok = False
                break
        if expected_agenda_files and listed_ok:
            scores["agenda_choice_listed_files"] = 1.0

        # Selected file check: ensure chosen_expected_filename is indicated as selected and the other is not.
        lines = _normalize_text(agenda_choice_text).split("\n")
        chosen_line_marked = False
        nonchosen_line_marked = False
        # Any line holding filename and marked
        for line in lines:
            if chosen_expected_filename in line and _agenda_selection_marked(line):
                chosen_line_marked = True
            if nonchosen_filename in line and _agenda_selection_marked(line):
                nonchosen_line_marked = True
        if chosen_line_marked and not nonchosen_line_marked:
            scores["agenda_choice_selected_file"] = 1.0

    # 3) Meeting notes checks
    meeting_event = {
        "title": "Capstone weekly sync",
        "date": "2026-04-22",
        "time": "16:00",
        "location": "FabLab Room 2",
    }
    agenda_items = [
        "Progress updates on prototype",
        "Decisions on motor selection",
        "Risk register review",
        "Next sprint planning",
    ]
    notes_path = workspace / "output" / "meeting_notes" / "notes_2026-04-22.md"
    notes_text = _safe_read_text(notes_path) if notes_path.exists() else None
    if notes_text is not None:
        notes_norm = _normalize_text(notes_text)
        notes_lower = notes_norm.lower()
        title_ok = all([
            meeting_event["title"].lower() in notes_lower,
            meeting_event["date"] in notes_norm,
            meeting_event["time"] in notes_norm,
            meeting_event["location"].lower() in notes_lower,
            "purpose" in notes_lower,
        ])
        if title_ok:
            scores["meeting_notes_title_time_location_purpose"] = 1.0

        agenda_ok = all([(item.lower() in notes_lower) for item in agenda_items])
        if agenda_ok:
            scores["meeting_notes_agenda_items"] = 1.0

        attendees_ok = all([
            "Miguel Santos".lower() in notes_lower,
            "Ana Rivera".lower() in notes_lower,
            "Carlos López".lower() in notes_lower,
        ])
        if attendees_ok:
            scores["meeting_notes_attendees"] = 1.0

        # Action items: top 3 Capstone tasks by expected rank: T8, T2, T4
        # Define expected tasks details
        capstone_tasks_expected = [
            {"task": "3D print prototype v1", "assignee": "Carlos López", "due_date": "2026-04-25", "due_time": "16:00"},
            {"task": "Motor selection analysis (prep)", "assignee": "Carlos López", "due_date": "2026-04-22", "due_time": "12:00"},
            {"task": "Risk register update", "assignee": "Miguel Santos", "due_date": "2026-04-24", "due_time": "18:00"},
        ]
        lines = notes_norm.split("\n")
        ai_ok = True
        for t in capstone_tasks_expected:
            if not _lines_contain_action_for(lines, t["task"], t["assignee"], t["due_date"], t["due_time"]):
                ai_ok = False
                break
        if ai_ok:
            scores["meeting_notes_action_items"] = 1.0

    # 4) Draft messages for students
    roster_path = workspace / "input" / "team_roster.csv"
    roster = _safe_load_csv(roster_path) if roster_path.exists() else None
    students = []
    advisor = None
    if roster:
        for r in roster:
            role = (r.get("role") or "").strip().lower()
            if role == "student":
                students.append({"name": r.get("name", ""), "email": r.get("email", "")})
            elif role == "advisor":
                advisor = {"name": r.get("name", ""), "email": r.get("email", "")}

    student_email_checks_ok = True
    student_ai_checks_ok = True
    subject_expected = "Subject: Capstone 2026-04-22 meeting notes & your action items"
    for s in students:
        email_file = workspace / "output" / "emails" / "team" / (s["email"] + ".txt")
        content = _safe_read_text(email_file) if email_file.exists() else None
        if content is None:
            student_email_checks_ok = False
            student_ai_checks_ok = False
            continue
        content_norm = _normalize_text(content)
        content_lower = content_norm.lower()

        # Subject line and body basics
        has_subject = any(line.strip() == subject_expected for line in content_norm.split("\n"))
        has_dtloc = ("2026-04-22" in content_norm) and ("16:00" in content_norm) and ("FabLab Room 2".lower() in content_lower)
        has_agenda_items = all([(item.lower() in content_lower) for item in agenda_items])
        if not (has_subject and has_dtloc and has_agenda_items):
            student_email_checks_ok = False

        # Action items for each student
        # Map expected assignments
        expected_student_tasks = {}
        expected_student_tasks["Carlos López".lower()] = [
            {"task": "3D print prototype v1", "due_date": "2026-04-25", "due_time": "16:00"},
            {"task": "Motor selection analysis (prep)", "due_date": "2026-04-22", "due_time": "12:00"},
        ]
        expected_student_tasks["Miguel Santos".lower()] = [
            {"task": "Risk register update", "due_date": "2026-04-24", "due_time": "18:00"},
        ]
        expected_student_tasks["Ana Rivera".lower()] = []  # none assigned

        student_key = s["name"].lower()
        lines = content_norm.split("\n")
        if student_key in expected_student_tasks:
            tasks_for_student = expected_student_tasks[student_key]
            if len(tasks_for_student) == 0:
                # Must include no new action items line
                if "no new action items assigned" not in content_lower:
                    student_ai_checks_ok = False
            else:
                for t in tasks_for_student:
                    # We only require task and due info; assignee may be omitted in student-specific email
                    if not _lines_contain_action_for(lines, t["task"], None, t["due_date"], t["due_time"]):
                        student_ai_checks_ok = False
                        break
        else:
            # if not found in mapping, fail this check as we cannot verify
            student_ai_checks_ok = False

    if student_email_checks_ok:
        scores["student_emails_subject_and_body"] = 1.0
    if student_ai_checks_ok:
        scores["student_emails_action_items"] = 1.0

    # Advisor summary
    advisor_ok = False
    advisor_file = workspace / "output" / "emails" / "advisor.txt"
    advisor_content = _safe_read_text(advisor_file) if advisor_file.exists() else None
    if advisor_content is not None:
        adv_norm = _normalize_text(advisor_content)
        adv_lower = adv_norm.lower()
        # Addressed to advisor (by name or email)
        addressed = False
        if advisor:
            if (advisor["name"] and advisor["name"].lower() in adv_lower) or (advisor["email"] and advisor["email"].lower() in adv_lower):
                addressed = True
        else:
            addressed = True  # if roster missing, skip this part

        has_dtloc = ("2026-04-22" in adv_norm) and ("16:00" in adv_norm) and ("FabLab Room 2".lower() in adv_lower)
        has_agenda_items = all([(item.lower() in adv_lower) for item in agenda_items])

        # Action items list for advisor should include assignee, task, due date/time
        action_items_ok = True
        advisor_lines = adv_norm.split("\n")
        advisor_expected_actions = [
            {"task": "3D print prototype v1", "assignee": "Carlos López", "due_date": "2026-04-25", "due_time": "16:00"},
            {"task": "Motor selection analysis (prep)", "assignee": "Carlos López", "due_date": "2026-04-22", "due_time": "12:00"},
            {"task": "Risk register update", "assignee": "Miguel Santos", "due_date": "2026-04-24", "due_time": "18:00"},
        ]
        for t in advisor_expected_actions:
            if not _lines_contain_action_for(advisor_lines, t["task"], t["assignee"], t["due_date"], t["due_time"]):
                action_items_ok = False
                break

        if addressed and has_dtloc and has_agenda_items and action_items_ok:
            advisor_ok = True

    if advisor_ok:
        scores["advisor_email_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()