import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({(k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_agenda(text: str):
    meeting_date = None
    topics = []
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.lower().startswith("date:"):
            date_str = line_stripped.split(":", 1)[1].strip()
            try:
                meeting_date = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                meeting_date = None
        if line_stripped.startswith("- "):
            topics.append(line_stripped[2:].strip())
    return meeting_date, topics


def _parse_markdown_sections(text: str):
    headers = [
        "Meeting Date:",
        "Attendees:",
        "Regrets:",
        "Agenda Topics:",
        "Case Updates:",
        "Carried-Over Actions:",
        "New Action Candidates:",
        "Data Issues:",
        "Sources:",
    ]
    lines = text.splitlines()
    sec_indices = []
    for i, line in enumerate(lines):
        for h in headers:
            if line.strip().startswith(h):
                sec_indices.append((i, h))
                break
    sec_indices.sort()
    sections = {}
    for idx, (start, header) in enumerate(sec_indices):
        end = sec_indices[idx + 1][0] if idx + 1 < len(sec_indices) else len(lines)
        body = lines[start + 1:end]
        sections[header] = [l.rstrip() for l in body]
    return sections


def _safe_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _emails_from_to_line(line: str):
    if not line.lower().startswith("to:"):
        return []
    emails = line.split(":", 1)[1]
    parts = [p.strip() for p in emails.split(",") if p.strip()]
    return parts


def _subject_from_line(line: str):
    if not line.lower().startswith("subject:"):
        return ""
    return line.split(":", 1)[1].strip()


def _parse_email(text: str):
    lines = text.splitlines()
    to_emails = []
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        ls = line.strip()
        if ls.lower().startswith("to:"):
            to_emails = _emails_from_to_line(ls)
        elif ls.lower().startswith("subject:"):
            subject = _subject_from_line(ls)
            body_start = i + 1
            break
    body_lines = lines[body_start:] if body_start else lines
    return to_emails, subject, body_lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_valid": 0.0,
        "meeting_notes_attendees_regrets": 0.0,
        "meeting_notes_agenda_topics_valid": 0.0,
        "meeting_notes_case_updates_correct": 0.0,
        "meeting_notes_carried_over_actions": 0.0,
        "meeting_notes_new_action_candidates_counts": 0.0,
        "meeting_notes_data_issues": 0.0,
        "meeting_notes_sources_listed": 0.0,
        "action_items_exists": 0.0,
        "action_items_headers_valid": 0.0,
        "action_items_carried_over_rows_correct": 0.0,
        "action_items_new_lab_items_correct": 0.0,
        "action_items_new_consent_items_correct": 0.0,
        "action_items_new_huddle_items_correct": 0.0,
        "action_items_row_count_expected": 0.0,
        "email_surgeons_exists": 0.0,
        "email_surgeons_to_list_correct": 0.0,
        "email_surgeons_subject_correct": 0.0,
        "email_surgeons_opening_references_date": 0.0,
        "email_surgeons_upcoming_count_correct": 0.0,
        "email_surgeons_upcoming_cases_listed": 0.0,
        "email_surgeons_huddle_indication_for_upcoming": 0.0,
        "email_coord_lab_exists": 0.0,
        "email_coord_lab_to_list_correct": 0.0,
        "email_coord_lab_subject_correct": 0.0,
        "email_coord_lab_opening_references_date": 0.0,
        "email_coord_lab_carried_over_section_correct": 0.0,
        "email_coord_lab_new_items_section_correct": 0.0,
        "email_coord_lab_closing_next_step_line": 0.0,
    }

    # Load inputs
    agenda_path = workspace / "input" / "agenda.md"
    participants_path = workspace / "input" / "participants.csv"
    cases_path = workspace / "input" / "cases.csv"
    prev_actions_path = workspace / "input" / "previous_actions.csv"

    agenda_text = _read_text(agenda_path)
    participants = _load_csv_dicts(participants_path)
    cases = _load_csv_dicts(cases_path)
    prev_actions = _load_csv_dicts(prev_actions_path)

    if not agenda_text or participants is None or cases is None or prev_actions is None:
        return scores

    meeting_date, agenda_topics = _parse_agenda(agenda_text)
    if meeting_date is None:
        return scores
    date_str = meeting_date.strftime("%Y-%m-%d")

    # Expected outputs paths
    outputs_dir = workspace / "outputs"
    meeting_notes_path = outputs_dir / f"meeting_notes_{date_str}.md"
    action_items_path = outputs_dir / f"action_items_{date_str}.csv"
    email_surgeons_path = outputs_dir / f"email_surgeons_{date_str}.txt"
    email_coord_lab_path = outputs_dir / f"email_coord_lab_{date_str}.txt"

    # Participants derived
    attendees_names = [p.get("name", "") for p in participants if p.get("attending", "").strip().lower() == "yes"]
    regrets_names = [p.get("name", "") for p in participants if p.get("attending", "").strip().lower() == "no"]
    surgeon_emails = sorted([p.get("email", "") for p in participants if p.get("role", "") == "Surgeon"])
    coord_lab_emails = sorted([p.get("email", "") for p in participants if p.get("role", "") in {"Transplant Coordinator", "Lab Liaison"}])
    participant_emails_set = set([p.get("email", "") for p in participants])

    # Helpers
    def _is_yes(val: str) -> bool:
        return str(val).strip().lower() == "yes"

    def _is_no(val: str) -> bool:
        return str(val).strip().lower() == "no"

    labs_no_cases = []
    consent_no_cases = []
    upcoming7_cases = []
    upcoming3_cases = []

    for c in cases:
        cid = c.get("case_id", "")
        labs_no = _is_no(c.get("labs_cleared", ""))
        consent_no = _is_no(c.get("consent_on_file", ""))
        if labs_no:
            labs_no_cases.append(cid)
        if consent_no:
            consent_no_cases.append(cid)
        status = c.get("status", "").strip().lower()
        sdate = _safe_date(c.get("surgery_date", ""))
        if sdate is not None:
            diff_days = (sdate - meeting_date).days
            if status == "scheduled" and 0 <= diff_days <= 7:
                upcoming7_cases.append(cid)
            if status == "scheduled" and 0 <= diff_days <= 3:
                upcoming3_cases.append(cid)

    # Data issues
    data_issue_emails = []
    for c in cases:
        for key in ("assigned_surgeon_email", "assigned_coordinator_email"):
            em = c.get(key, "")
            if em and em not in participant_emails_set:
                data_issue_emails.append(em)
    data_issue_emails = sorted(set(data_issue_emails))

    # Carried over actions selection
    carried_over_actions = [a for a in prev_actions if a.get("status", "").strip() in {"Open", "In Progress"}]

    # Expected action headers
    expected_action_headers = ["id", "description", "owner_email", "due_date", "status", "related_case_id", "source"]

    # Identify Lab Liaison email
    lab_liaison = [p.get("email", "") for p in participants if p.get("role", "") == "Lab Liaison"]
    lab_liaison_email = lab_liaison[0] if lab_liaison else ""

    # Build expected action items rows
    expected_rows = []
    # Carried-over items
    for a in carried_over_actions:
        expected_rows.append({
            "id": f"CO-{a.get('id', '')}",
            "description": a.get("description", ""),
            "owner_email": a.get("owner_email", ""),
            "due_date": a.get("due_date", ""),
            "status": "Carried Over",
            "related_case_id": a.get("related_case_id", ""),
            "source": "carried_over",
        })
    # New LAB items
    for c in cases:
        if _is_no(c.get("labs_cleared", "")):
            cid = c.get("case_id", "")
            desc = f"Complete required labs for {c.get('recipient_name', '')} ({cid})"
            due = (meeting_date + timedelta(days=2)).strftime("%Y-%m-%d")
            expected_rows.append({
                "id": f"N-{cid}-LAB",
                "description": desc,
                "owner_email": lab_liaison_email,
                "due_date": due,
                "status": "Open",
                "related_case_id": cid,
                "source": "new",
            })
    # New CONSENT items
    for c in cases:
        if _is_no(c.get("consent_on_file", "")):
            cid = c.get("case_id", "")
            desc = f"Obtain consent for {c.get('recipient_name', '')} ({cid})"
            due = (meeting_date + timedelta(days=1)).strftime("%Y-%m-%d")
            expected_rows.append({
                "id": f"N-{cid}-CONSENT",
                "description": desc,
                "owner_email": c.get("assigned_coordinator_email", ""),
                "due_date": due,
                "status": "Open",
                "related_case_id": cid,
                "source": "new",
            })
    # New HUDDLE items
    for c in cases:
        cid = c.get("case_id", "")
        sdate = _safe_date(c.get("surgery_date", ""))
        status = c.get("status", "").strip().lower()
        if sdate is None:
            continue
        diff_days = (sdate - meeting_date).days
        if status == "scheduled" and 0 <= diff_days <= 3:
            desc = f"Confirm pre-op huddle for {c.get('recipient_name', '')} ({cid})"
            due = meeting_date.strftime("%Y-%m-%d")
            expected_rows.append({
                "id": f"N-{cid}-HUDDLE",
                "description": desc,
                "owner_email": c.get("assigned_surgeon_email", ""),
                "due_date": due,
                "status": "Open",
                "related_case_id": cid,
                "source": "new",
            })

    # Meeting notes checks
    meeting_notes_text = _read_text(meeting_notes_path)
    if meeting_notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        sections = _parse_markdown_sections(meeting_notes_text)

        # Validate required sections presence
        required_headers = [
            "Meeting Date:", "Attendees:", "Regrets:", "Agenda Topics:",
            "Case Updates:", "Carried-Over Actions:", "New Action Candidates:",
            "Data Issues:", "Sources:",
        ]
        if all(h in sections for h in required_headers):
            scores["meeting_notes_sections_valid"] = 1.0

        # Meeting Date content
        has_meeting_date_line = any(line.strip() == date_str for line in sections.get("Meeting Date:", []))

        # Attendees and Regrets content
        attendees_ok = all(any(name in line for line in sections.get("Attendees:", [])) for name in attendees_names) and has_meeting_date_line
        regrets_ok = all(any(name in line for line in sections.get("Regrets:", [])) for name in regrets_names)
        if attendees_ok and regrets_ok:
            scores["meeting_notes_attendees_regrets"] = 1.0

        # Agenda topics listed
        agenda_sec = sections.get("Agenda Topics:", [])
        agenda_ok = all(any(topic in line for line in agenda_sec) for topic in agenda_topics)
        if agenda_ok:
            scores["meeting_notes_agenda_topics_valid"] = 1.0

        # Case updates
        case_sec = sections.get("Case Updates:", [])
        case_ok_all = True
        for c in cases:
            cid = c.get("case_id", "")
            organ = c.get("organ", "")
            recip = c.get("recipient_name", "")
            sdate = c.get("surgery_date", "")
            status = c.get("status", "")
            matching_lines = [line for line in case_sec if (cid in line and organ in line and recip in line and sdate in line and status in line)]
            if not matching_lines:
                case_ok_all = False
                break
            line = matching_lines[0]
            labs_no = _is_no(c.get("labs_cleared", ""))
            consent_no = _is_no(c.get("consent_on_file", ""))
            if labs_no or consent_no:
                if "Prereqs Pending:" not in line:
                    case_ok_all = False
                    break
                if labs_no and "labs" not in line.lower():
                    case_ok_all = False
                    break
                if consent_no and "consent" not in line.lower():
                    case_ok_all = False
                    break
            sdate_dt = _safe_date(sdate)
            diff_days = (sdate_dt - meeting_date).days if sdate_dt else None
            is_upcoming7 = (status.strip().lower() == "scheduled" and diff_days is not None and 0 <= diff_days <= 7)
            if is_upcoming7:
                if "Upcoming <7d>" not in line:
                    case_ok_all = False
                    break
        if case_ok_all:
            scores["meeting_notes_case_updates_correct"] = 1.0

        # Carried-over actions section
        co_sec = sections.get("Carried-Over Actions:", [])
        co_ok = True
        for a in carried_over_actions:
            if not any(a.get("id", "") in line and a.get("description", "") in line for line in co_sec):
                co_ok = False
                break
        if co_ok:
            scores["meeting_notes_carried_over_actions"] = 1.0

        # New Action Candidates counts
        nac_sec = sections.get("New Action Candidates:", [])
        labs_count_ok = any(("lab" in line.lower() and str(len(labs_no_cases)) in line) for line in nac_sec)
        consent_count_ok = any(("consent" in line.lower() and str(len(consent_no_cases)) in line) for line in nac_sec)
        if labs_count_ok and consent_count_ok:
            scores["meeting_notes_new_action_candidates_counts"] = 1.0

        # Data Issues
        di_sec = sections.get("Data Issues:", [])
        if data_issue_emails:
            di_ok = all(any(email in line for line in di_sec) for email in data_issue_emails)
        else:
            di_ok = any(line.strip().lower() == "none" for line in di_sec)
        if di_ok:
            scores["meeting_notes_data_issues"] = 1.0

        # Sources section must list exact input file paths
        sources_sec = sections.get("Sources:", [])
        src_paths = ["input/agenda.md", "input/participants.csv", "input/cases.csv", "input/previous_actions.csv"]
        src_ok = all(any(sp in line for line in sources_sec) for sp in src_paths)
        if src_ok:
            scores["meeting_notes_sources_listed"] = 1.0

    # Action items checks
    action_rows = _load_csv_dicts(action_items_path)
    if action_rows is not None:
        scores["action_items_exists"] = 1.0
        # header validation
        try:
            with action_items_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
            header_clean = [h.strip() for h in header]
            if header_clean == expected_action_headers:
                scores["action_items_headers_valid"] = 1.0
        except Exception:
            pass

        # Build maps for comparison ignoring order
        def row_key(row: dict):
            return (row.get("id", ""), row.get("description", ""), row.get("owner_email", ""), row.get("due_date", ""),
                    row.get("status", ""), row.get("related_case_id", ""), row.get("source", ""))

        expected_set = set(row_key(r) for r in expected_rows)
        actual_set = set(row_key(r) for r in action_rows)

        # Carried-over rows correct
        expected_co_set = set(row_key(r) for r in expected_rows if r.get("source", "") == "carried_over")
        actual_co_set = set(row_key(r) for r in action_rows if r.get("source", "") == "carried_over")
        if expected_co_set and expected_co_set.issubset(actual_set) and expected_co_set == actual_co_set:
            scores["action_items_carried_over_rows_correct"] = 1.0

        # New LAB items correct
        expected_lab_set = set(row_key(r) for r in expected_rows if r.get("id", "").endswith("-LAB"))
        actual_lab_set = set(row_key(r) for r in action_rows if r.get("id", "").endswith("-LAB"))
        if expected_lab_set and expected_lab_set.issubset(actual_set) and expected_lab_set == actual_lab_set:
            scores["action_items_new_lab_items_correct"] = 1.0

        # New CONSENT items correct
        expected_consent_set = set(row_key(r) for r in expected_rows if r.get("id", "").endswith("-CONSENT"))
        actual_consent_set = set(row_key(r) for r in action_rows if r.get("id", "").endswith("-CONSENT"))
        if expected_consent_set and expected_consent_set.issubset(actual_set) and expected_consent_set == actual_consent_set:
            scores["action_items_new_consent_items_correct"] = 1.0

        # New HUDDLE items correct
        expected_huddle_set = set(row_key(r) for r in expected_rows if r.get("id", "").endswith("-HUDDLE"))
        actual_huddle_set = set(row_key(r) for r in action_rows if r.get("id", "").endswith("-HUDDLE"))
        if expected_huddle_set and expected_huddle_set.issubset(actual_set) and expected_huddle_set == actual_huddle_set:
            scores["action_items_new_huddle_items_correct"] = 1.0

        # Row count expected
        if len(action_rows) == len(expected_rows):
            scores["action_items_row_count_expected"] = 1.0

    # Email to surgeons checks
    email_surgeons_text = _read_text(email_surgeons_path)
    if email_surgeons_text is not None:
        scores["email_surgeons_exists"] = 1.0
        to_emails, subject, body_lines = _parse_email(email_surgeons_text)
        if set(to_emails) == set(surgeon_emails) and len(to_emails) == len(surgeon_emails):
            scores["email_surgeons_to_list_correct"] = 1.0
        expected_subject_surgeons = f"Transplant coordination — surgical updates for {date_str}"
        if subject == expected_subject_surgeons:
            scores["email_surgeons_subject_correct"] = 1.0
        if any(date_str in line for line in body_lines[:3]):
            scores["email_surgeons_opening_references_date"] = 1.0
        upcoming7_ids = set(upcoming7_cases)
        count_str = str(len(upcoming7_ids))
        summary_ok = any(("scheduled" in line.lower() and "7" in line and count_str in line) or ("upcoming" in line.lower() and count_str in line) for line in body_lines)
        if summary_ok:
            scores["email_surgeons_upcoming_count_correct"] = 1.0
        listed_ok_all = True
        huddle_ind_ok_all = True
        case_map = {c["case_id"]: (c.get("recipient_name", ""), c.get("surgery_date", "")) for c in cases}
        action_rows_for_email = _load_csv_dicts(action_items_path)
        action_ids_set = set([r.get("id", "") for r in action_rows_for_email]) if action_rows_for_email is not None else set()
        for cid in upcoming7_ids:
            recip, sdate = case_map.get(cid, ("", ""))
            matching = [line for line in body_lines if (cid in line and recip in line and sdate in line)]
            if not matching:
                listed_ok_all = False
                break
            line = matching[0]
            has_huddle_action = (f"N-{cid}-HUDDLE" in action_ids_set)
            if has_huddle_action:
                if ("HUDDLE" not in line.upper()) and (f"N-{cid}-HUDDLE" not in line):
                    huddle_ind_ok_all = False
                    break
        if listed_ok_all:
            scores["email_surgeons_upcoming_cases_listed"] = 1.0
        if huddle_ind_ok_all:
            scores["email_surgeons_huddle_indication_for_upcoming"] = 1.0

    # Email to coordinators and lab liaison checks
    email_coord_lab_text = _read_text(email_coord_lab_path)
    if email_coord_lab_text is not None:
        scores["email_coord_lab_exists"] = 1.0
        to_emails, subject, body_lines = _parse_email(email_coord_lab_text)
        if set(to_emails) == set(coord_lab_emails) and len(to_emails) == len(coord_lab_emails):
            scores["email_coord_lab_to_list_correct"] = 1.0
        expected_subject_coord = f"Transplant coordination — labs/consents and action items for {date_str}"
        if subject == expected_subject_coord:
            scores["email_coord_lab_subject_correct"] = 1.0
        if any(date_str in line for line in body_lines[:3]):
            scores["email_coord_lab_opening_references_date"] = 1.0

        # Carried-over items assigned to recipients in this email’s To list
        expected_co_ids_for_to = {f"CO-{a['id']}" for a in carried_over_actions if a.get("owner_email", "") in coord_lab_emails}
        carried_over_present = True
        for co_id in expected_co_ids_for_to:
            orig = next((a for a in carried_over_actions if f"CO-{a['id']}" == co_id), None)
            if orig is None:
                carried_over_present = False
                break
            desc = orig.get("description", "")
            due = orig.get("due_date", "")
            if not any((co_id in line and desc in line and due in line) for line in body_lines):
                carried_over_present = False
                break
        if expected_co_ids_for_to == set() or carried_over_present:
            scores["email_coord_lab_carried_over_section_correct"] = 1.0

        # New LAB and CONSENT items listed
        expected_new_ids = []
        for r in expected_rows:
            if r.get("source", "") == "new" and (r.get("id", "").endswith("-LAB") or r.get("id", "").endswith("-CONSENT")):
                expected_new_ids.append(r["id"])
        new_items_present = True
        for nid in expected_new_ids:
            r = next((row for row in expected_rows if row["id"] == nid), None)
            if r is None:
                new_items_present = False
                break
            if not any((nid in line and r["description"] in line and r["owner_email"] in line and r["due_date"] in line) for line in body_lines):
                new_items_present = False
                break
        if new_items_present:
            scores["email_coord_lab_new_items_section_correct"] = 1.0

        # Closing line with next-step reminder
        closing_ok = any(("next-step" in line.lower()) or ("next step" in line.lower()) for line in body_lines[-5:])
        if closing_ok:
            scores["email_coord_lab_closing_next_step_line"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()