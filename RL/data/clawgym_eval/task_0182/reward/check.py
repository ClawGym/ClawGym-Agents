import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _get_next_rehearsal(event_rows: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    for row in event_rows:
        if str(row.get("next_flag", "")).strip() == "1":
            return row
    return None


def _required_voice_parts_set(req_str: str) -> set:
    # Map letters to full names
    letter_map = {"S": "Soprano", "A": "Alto", "T": "Tenor", "B": "Bass"}
    parts = set()
    for token in re.split(r"[,\s]+", (req_str or "").strip()):
        token = token.strip()
        if not token:
            continue
        if token in letter_map:
            parts.add(letter_map[token])
        else:
            parts.add(token)
    return parts


def _voice_sort_key(voice: str) -> int:
    order = {"Soprano": 0, "Alto": 1, "Tenor": 2, "Bass": 3}
    return order.get(voice, 999)


def _extract_section(text: str, start_key: str, end_key: Optional[str] = None) -> List[str]:
    # Returns the lines between a heading containing start_key and the next heading containing end_key (if provided)
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, ln in enumerate(lines):
        ln_clean = ln.strip().lower()
        if start_key.lower() in re.sub(r"^#+\s*", "", ln_clean):
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    if end_key:
        for j in range(start_idx, len(lines)):
            ln2 = lines[j].strip().lower()
            if end_key.lower() in re.sub(r"^#+\s*", "", ln2):
                end_idx = j
                break
    if end_idx is None:
        end_idx = len(lines)
    return lines[start_idx:end_idx]


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            bullets.append(ln.strip())
    return bullets


def _parse_markdown_table(lines: List[str], header_expected: List[str]) -> List[Dict[str, str]]:
    # Find header row that contains all expected headers
    header_idx = None
    headers = []
    for i, ln in enumerate(lines):
        if '|' in ln:
            cells = [c.strip() for c in ln.strip().strip('|').split('|')]
            lowered = [c.lower() for c in cells]
            if all(h.lower() in lowered for h in header_expected):
                headers = cells
                header_idx = i
                break
    if header_idx is None or not headers:
        return []
    # Next line should be separator (but we won't strictly enforce dashes)
    data_rows = []
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip().startswith("|"):
            # Might be separator line or end of table; if it's separator, continue, else break when non-table found after data
            # Allow one separator then continue
            if re.match(r"^\s*\|?\s*[:\-]+\s*\|", ln):
                continue
            else:
                # If we have no data yet and this is a separator, continue searching
                continue
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        # Skip separator-like rows
        if all(re.match(r"^:?-{3,}:?$", c) or c == "" for c in cells):
            continue
        # Align cells to headers length
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        row = {headers[idx]: cells[idx] for idx in range(len(headers))}
        data_rows.append(row)
    # Filter to only expected columns
    normalized = []
    lower_map = {h.lower(): h for h in headers}
    for row in data_rows:
        record = {}
        ok = True
        for h in header_expected:
            # find matching header key (case-insensitive)
            found_key = None
            for k in row.keys():
                if k.strip().lower() == h.lower():
                    found_key = k
                    break
            if found_key is None:
                ok = False
                break
            record[h] = row.get(found_key, "").strip()
        if ok:
            normalized.append(record)
    return normalized


def _compute_last_three_rehearsal_dates(events: List[Dict[str, str]], next_reh: Dict[str, str]) -> List[str]:
    dates = []
    next_date = _parse_date(next_reh.get("date", ""))
    if next_date is None:
        return []
    for row in events:
        if row.get("type", "").strip() != "Rehearsal":
            continue
        d = _parse_date(row.get("date", ""))
        if d and d < next_date:
            dates.append((d, row.get("date", "").strip()))
    dates.sort(key=lambda x: x[0])
    last_three = [d[1] for d in dates[-3:]]
    # They want sorted by date ascending for analysis; ensure ascending
    last_three.sort()
    return last_three


def _compute_attendance_counts(attendance_rows: List[Dict[str, str]], roster_rows: List[Dict[str, str]], target_dates: List[str]) -> Dict[str, Dict[str, int]]:
    # Return per voice part: {"presents": n, "total_slots": n}
    active_members = [r for r in roster_rows if r.get("status", "").strip() == "active"]
    # Map email to (voice_part)
    email_to_voice = {}
    for r in active_members:
        email_to_voice[r.get("email", "").strip()] = r.get("voice_part", "").strip()
    # initialize counts
    counts = {}
    for vp in {"Soprano", "Alto", "Tenor", "Bass"}:
        counts[vp] = {"presents": 0, "members": 0}
    for r in active_members:
        vp = r.get("voice_part", "").strip()
        if vp not in counts:
            counts[vp] = {"presents": 0, "members": 0}
        counts[vp]["members"] += 1
    # aggregate presents for target dates
    target_set = set(target_dates)
    for row in attendance_rows:
        date = row.get("date", "").strip()
        if date not in target_set:
            continue
        email = row.get("member_email", "").strip()
        present = row.get("present", "").strip()
        vp = email_to_voice.get(email)
        if vp is None:
            continue
        try:
            pres_int = int(present)
        except Exception:
            pres_int = 0
        counts[vp]["presents"] += pres_int
    return counts


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[str]]:
    roster = _read_csv_dicts(workspace / "input" / "choir_roster.csv")
    events = _read_csv_dicts(workspace / "input" / "event_schedule.csv")
    attendance = _read_csv_dicts(workspace / "input" / "attendance_log.csv")
    notes = _read_text(workspace / "input" / "raw_discussion_notes.txt")
    return roster, events, attendance, notes


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_has_sections": 0.0,
        "meeting_notes_decisions_covered": 0.0,
        "meeting_notes_action_items_table_valid": 0.0,
        "reminder_recipients_header_and_count": 0.0,
        "reminder_recipients_sort_and_subject": 0.0,
        "reminder_recipients_body_content": 0.0,
        "follow_up_priority_rows": 0.0,
        "follow_up_priority_ordering": 0.0,
        "status_update_roster_counts": 0.0,
        "status_update_attendance_rates": 0.0,
        "status_update_upcoming_events": 0.0,
        "status_update_follow_up_targets": 0.0,
    }

    roster, events, attendance, notes_text = _load_inputs(workspace)

    # Precompute next rehearsal and dates if possible
    next_reh = None
    required_parts = set()
    next_reh_date = None
    next_reh_time = None
    next_reh_location = None
    next_reh_title = None
    last_three_dates = []
    upcoming_two_events = []
    if events:
        next_reh = _get_next_rehearsal(events)
        if next_reh:
            required_parts = _required_voice_parts_set(next_reh.get("required_voice_parts", ""))
            next_reh_date = next_reh.get("date", "").strip()
            next_reh_time = next_reh.get("time", "").strip()
            next_reh_location = next_reh.get("location", "").strip()
            next_reh_title = next_reh.get("title", "").strip()
            # Last three rehearsal dates before next
            last_three_dates = _compute_last_three_rehearsal_dates(events, next_reh)
            # Upcoming two events starting with next rehearsal by date
            # Sort by date ascending and pick next rehearsal then next by date
            events_sorted = sorted(events, key=lambda r: (_parse_date(r.get("date", "")) or datetime.max))
            # find index of next rehearsal row (by identity match on date/time/title/location/next_flag)
            idx = None
            for i, r in enumerate(events_sorted):
                if all([
                    r.get("date", "").strip() == next_reh_date,
                    r.get("time", "").strip() == next_reh_time,
                    r.get("title", "").strip() == next_reh_title,
                ]):
                    idx = i
                    break
            if idx is not None:
                upcoming_two_events = events_sorted[idx:idx+2]
    # 1) meeting_notes.md checks
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    meeting_notes_text = _read_text(meeting_notes_path)
    if meeting_notes_text is not None:
        # Sections presence
        decisions_section = _extract_section(meeting_notes_text, "Decisions", "Action Items")
        action_items_section = _extract_section(meeting_notes_text, "Action Items", None)
        if decisions_section and action_items_section:
            scores["meeting_notes_has_sections"] = 1.0

        # Decisions coverage: use keyword groups to validate presence in bullets
        bullets = _extract_bullets(decisions_section)
        # Normalize bullets to lowercase for search
        bullets_lc = [b.lower() for b in bullets]
        decision_groups = [
            ["gomidas", "soorp", "der voghormya"],
            ["re-seat", "basses", "tenors"],
            ["tempo", "unified", "vowel"],
        ]
        matched = 0
        for group in decision_groups:
            found = False
            for b in bullets_lc:
                if all(tok in b for tok in group):
                    found = True
                    break
            if found:
                matched += 1
        if matched == len(decision_groups):
            scores["meeting_notes_decisions_covered"] = 1.0

        # Action items table validation
        table_rows = _parse_markdown_table(action_items_section, ["Assignee", "Task", "Due_Date"])
        # Build expected due dates based on next rehearsal
        expected_due_map = {
            "Levon": {"Due_Date": next_reh_date if next_reh_date else "", "task_keywords": ["aravot luso"]},
            "Nareh": {"Due_Date": "2026-05-21", "task_keywords": ["hayr mer"]},
            "Aram": {"Due_Date": next_reh_date if next_reh_date else "", "task_keywords": ["tuning fork"]},
            "Mariam": {"Due_Date": "2026-05-20", "task_keywords": ["sheet", "print"]},
        }
        valid = False
        if table_rows and len(table_rows) >= 4 and next_reh_date:
            # Index by assignee
            rows_by_assignee = {r.get("Assignee", ""): r for r in table_rows}
            all_ok = True
            for assignee, exp in expected_due_map.items():
                row = rows_by_assignee.get(assignee)
                if not row:
                    all_ok = False
                    break
                if row.get("Due_Date") != exp["Due_Date"]:
                    all_ok = False
                    break
                task_lc = (row.get("Task") or "").lower()
                # For Mariam ensure both 'sheet' and 'print' appear; for others ensure listed keywords appear
                if assignee == "Mariam":
                    if not ("sheet" in task_lc and "print" in task_lc):
                        all_ok = False
                        break
                else:
                    if not all(kw in task_lc for kw in exp["task_keywords"]):
                        all_ok = False
                        break
            # also ensure header columns present exactly
            valid = all_ok
        if valid:
            scores["meeting_notes_action_items_table_valid"] = 1.0

    # 2) reminder_recipients.csv checks
    reminder_path = workspace / "output" / "reminder_recipients.csv"
    reminder_rows = _read_csv_dicts(reminder_path) if reminder_path.exists() else None
    expected_recipients: List[Dict[str, str]] = []
    expected_subject: Optional[str] = None
    if roster and next_reh and next_reh_date and next_reh_time and next_reh_location:
        # Filter active and availability Yes and voice part in required
        filtered = []
        for r in roster:
            if r.get("status", "").strip() != "active":
                continue
            if r.get("availability", "").strip() != "Yes":
                continue
            if r.get("voice_part", "").strip() not in required_parts:
                continue
            filtered.append(r)
        # Sort by voice part order, then last_name ascending
        filtered.sort(key=lambda r: (_voice_sort_key(r.get("voice_part", "").strip()),
                                     r.get("last_name", "").strip()))
        expected_subject = f"Reminder: Rehearsal on {next_reh_date} at {next_reh_time} - {next_reh_location}"
        for r in filtered:
            expected_recipients.append({
                "first_name": r.get("first_name", "").strip(),
                "last_name": r.get("last_name", "").strip(),
                "voice_part": r.get("voice_part", "").strip(),
                "email": r.get("email", "").strip(),
                "reminder_subject": expected_subject,
            })

    # Header and count check
    if reminder_rows is not None:
        header_ok = False
        try:
            with (workspace / "output" / "reminder_recipients.csv").open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            header_ok = header_line == "first_name,last_name,voice_part,email,reminder_subject,reminder_body"
        except Exception:
            header_ok = False
        count_ok = False
        if expected_recipients:
            count_ok = len(reminder_rows) == len(expected_recipients)
        if header_ok and count_ok:
            scores["reminder_recipients_header_and_count"] = 1.0

        # Sort and subject checks
        sort_and_subject_ok = False
        if expected_recipients and len(reminder_rows) == len(expected_recipients):
            # Compare the first 5 fields (excluding body)
            all_match = True
            for i, row in enumerate(reminder_rows):
                exp = expected_recipients[i]
                if (row.get("first_name", "").strip() != exp["first_name"] or
                    row.get("last_name", "").strip() != exp["last_name"] or
                    row.get("voice_part", "").strip() != exp["voice_part"] or
                    row.get("email", "").strip() != exp["email"] or
                    row.get("reminder_subject", "").strip() != exp["reminder_subject"]):
                    all_match = False
                    break
            sort_and_subject_ok = all_match
        if sort_and_subject_ok:
            scores["reminder_recipients_sort_and_subject"] = 1.0

        # Body content checks
        body_ok = True
        if expected_subject and next_reh_title and next_reh_date and next_reh_time and next_reh_location:
            for row in reminder_rows:
                body = (row.get("reminder_body") or "")
                first_name = (row.get("first_name") or "")
                if not body.startswith(f"Dear {first_name},"):
                    body_ok = False
                    break
                # Must mention title, date, time, location
                req_subs = [next_reh_title, next_reh_date, next_reh_time, next_reh_location, "Please arrive 10 minutes early."]
                if not all(sub in body for sub in req_subs):
                    body_ok = False
                    break
        else:
            body_ok = False
        if body_ok:
            scores["reminder_recipients_body_content"] = 1.0

    # 3) follow_up_priority.csv checks
    follow_up_path = workspace / "output" / "follow_up_priority.csv"
    follow_rows = _read_csv_dicts(follow_up_path) if follow_up_path.exists() else None
    expected_follow_rows: List[Dict[str, str]] = []
    if roster and attendance and next_reh and last_three_dates:
        # Compute absences for active members
        active_members = [r for r in roster if r.get("status", "").strip() == "active"]
        # Map email to record
        email_to_member = {r.get("email", "").strip(): r for r in active_members}
        # Initialize absences
        absences_count = {r.get("email", "").strip(): 0 for r in active_members}
        target_set = set(last_three_dates)
        for row in attendance:
            if row.get("date", "").strip() not in target_set:
                continue
            email = row.get("member_email", "").strip()
            if email not in email_to_member:
                continue
            try:
                present_int = int(row.get("present", "").strip())
            except Exception:
                present_int = 0
            if present_int == 0:
                absences_count[email] += 1
        # Filter absences >= 2
        filtered = []
        for email, cnt in absences_count.items():
            if cnt >= 2:
                m = email_to_member[email]
                filtered.append({
                    "first_name": m.get("first_name", "").strip(),
                    "last_name": m.get("last_name", "").strip(),
                    "voice_part": m.get("voice_part", "").strip(),
                    "email": email,
                    "absences_last_3": cnt
                })
        # Sort by absences desc, then voice_part alphabetical, then last_name ascending
        filtered.sort(key=lambda r: (-int(r["absences_last_3"]), r["voice_part"], r["last_name"]))
        # Assign ranks
        for idx, r in enumerate(filtered, start=1):
            expected_follow_rows.append({
                "first_name": r["first_name"],
                "last_name": r["last_name"],
                "voice_part": r["voice_part"],
                "email": r["email"],
                "absences_last_3": str(r["absences_last_3"]),
                "priority_rank": str(idx),
            })

    if follow_rows is not None:
        # Header exact
        header_ok = False
        try:
            with follow_up_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            header_ok = header_line == "first_name,last_name,voice_part,email,absences_last_3,priority_rank"
        except Exception:
            header_ok = False
        rows_ok = False
        if expected_follow_rows:
            rows_ok = len(follow_rows) == len(expected_follow_rows)
        if header_ok and rows_ok:
            scores["follow_up_priority_rows"] = 1.0

        # Ordering/content
        ordering_ok = False
        if expected_follow_rows and len(follow_rows) == len(expected_follow_rows):
            all_match = True
            for i, row in enumerate(follow_rows):
                exp = expected_follow_rows[i]
                for k in ["first_name", "last_name", "voice_part", "email", "absences_last_3", "priority_rank"]:
                    if (row.get(k, "").strip() != exp[k]):
                        all_match = False
                        break
                if not all_match:
                    break
            ordering_ok = all_match
        if ordering_ok:
            scores["follow_up_priority_ordering"] = 1.0

    # 4) status_update.md checks
    status_update_path = workspace / "output" / "status_update.md"
    status_text = _read_text(status_update_path)
    if status_text is not None and roster is not None and attendance is not None and next_reh and last_three_dates and upcoming_two_events:
        # Roster overview counts (active per voice_part)
        counts_expected = {}
        for vp in ["Soprano", "Alto", "Tenor", "Bass"]:
            counts_expected[vp] = len([r for r in roster if r.get("status", "").strip() == "active" and r.get("voice_part", "").strip() == vp])

        def find_number_for_keyword(text: str, keyword: str) -> Optional[int]:
            for ln in text.splitlines():
                if keyword.lower() in ln.lower():
                    nums = re.findall(r"\b\d+\b", ln)
                    if nums:
                        try:
                            return int(nums[0])
                        except Exception:
                            continue
            return None

        counts_ok = True
        for vp in ["Soprano", "Alto", "Tenor", "Bass"]:
            num = find_number_for_keyword(status_text, vp)
            if num != counts_expected[vp]:
                counts_ok = False
                break
        if counts_ok:
            scores["status_update_roster_counts"] = 1.0

        # Attendance rates percentages
        attendance_counts = _compute_attendance_counts(attendance, roster, last_three_dates)
        # rates rounded to nearest whole percent
        rates_expected = {}
        for vp in ["Soprano", "Alto", "Tenor", "Bass"]:
            presents = attendance_counts.get(vp, {}).get("presents", 0)
            members = attendance_counts.get(vp, {}).get("members", 0)
            denom = members * 3
            pct = 0
            if denom > 0:
                pct = int(round((presents / denom) * 100))
            rates_expected[vp] = pct

        def find_percent_for_keyword(text: str, keyword: str) -> Optional[int]:
            for ln in text.splitlines():
                if keyword.lower() in ln.lower():
                    m = re.search(r"(\d+)\s*%", ln)
                    if m:
                        try:
                            return int(m.group(1))
                        except Exception:
                            continue
            return None

        rates_ok = True
        for vp in ["Soprano", "Alto", "Tenor", "Bass"]:
            pct = find_percent_for_keyword(status_text, vp)
            if pct != rates_expected[vp]:
                rates_ok = False
                break
        if rates_ok:
            scores["status_update_attendance_rates"] = 1.0

        # Upcoming events: must include next two events by date with date, time, type, title
        up_ok = True
        for ev in upcoming_two_events:
            req_subs = [
                ev.get("date", "").strip(),
                ev.get("time", "").strip(),
                ev.get("type", "").strip(),
                ev.get("title", "").strip(),
            ]
            if not all(sub and (sub in status_text) for sub in req_subs):
                up_ok = False
                break
        if up_ok:
            scores["status_update_upcoming_events"] = 1.0

        # Follow-up targets: names, voice_parts, and absences_last_3 from follow_up_priority.csv
        follow_targets_ok = False
        if follow_rows is not None:
            required_hits = 0
            for row in follow_rows:
                name = f"{row.get('first_name', '').strip()} {row.get('last_name', '').strip()}"
                vp = row.get("voice_part", "").strip()
                absences = row.get("absences_last_3", "").strip()
                # Check that a line exists containing name and voice part, and somewhere the absences number appears
                # We search for both name and voice part in the same line
                found_line = False
                for ln in status_text.splitlines():
                    if name in ln and vp in ln and absences in ln:
                        found_line = True
                        break
                if found_line:
                    required_hits += 1
            follow_targets_ok = (required_hits == len(follow_rows)) and len(follow_rows) > 0
        if follow_targets_ok:
            scores["status_update_follow_up_targets"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()