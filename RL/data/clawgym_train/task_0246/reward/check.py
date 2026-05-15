import json
import sys
import re
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            # Ensure headers are present
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_agenda(md_text: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    title = None
    date = None
    items: List[str] = []
    lines = md_text.splitlines()
    in_agenda = False
    for line in lines:
        if line.strip().startswith("#"):
            # Title as the first heading line
            if title is None:
                title = line.strip().lstrip("#").strip()
        if line.strip().lower().startswith("date:"):
            date = line.split(":", 1)[1].strip()
        if line.strip().lower().startswith("agenda"):
            in_agenda = True
            continue
        if in_agenda and line.strip().startswith("-"):
            items.append(line.strip()[1:].strip())
    return title, date, items


def _parse_notes(notes_text: str) -> Dict[str, object]:
    decisions: List[str] = []
    actions: List[Dict[str, str]] = []
    next_meeting: Optional[str] = None
    for raw_line in notes_text.splitlines():
        line = raw_line.strip()
        if line.startswith("DECISION:"):
            decisions.append(line[len("DECISION:"):].strip())
        if line.startswith("ACTION:"):
            action_body = line[len("ACTION:"):].strip()
            # Extract due date
            due_match = re.search(r";\s*due\s*(\d{4}-\d{2}-\d{2})\.?", action_body, flags=re.IGNORECASE)
            due = due_match.group(1) if due_match else None
            # Extract summary (before ; due)
            summary = re.split(r";\s*due\s*\d{4}-\d{2}-\d{2}\.?", action_body, flags=re.IGNORECASE)[0].strip()
            # Owner is before first " to "
            owner = None
            parts = summary.split(" to ", 1)
            if len(parts) == 2:
                owner = parts[0].strip()
            actions.append({
                "line": action_body,
                "summary": summary,
                "owner": owner if owner else "",
                "due": due if due else ""
            })
        if next_meeting is None:
            nm = re.search(r"Next meeting.*?(\d{4}-\d{2}-\d{2})", line, flags=re.IGNORECASE)
            if nm:
                next_meeting = nm.group(1)
    return {"decisions": decisions, "actions": actions, "next_meeting": next_meeting}


def _tokenize_significant(text: str, min_len: int = 4) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z]{%d,}" % min_len, text)]


def _agenda_item_addressed(item: str, notes_text: str) -> bool:
    tokens = _tokenize_significant(item, min_len=4)
    if not tokens:
        return False
    nlower = notes_text.lower()
    for t in tokens:
        if t in nlower:
            return True
    return False


def _emails_from_attendees(attendees_rows: List[Dict[str, str]]) -> List[str]:
    emails: List[str] = []
    for row in attendees_rows:
        if "Email" in row and row["Email"]:
            emails.append(row["Email"].strip())
    return emails


def _names_from_attendees(attendees_rows: List[Dict[str, str]]) -> List[str]:
    names: List[str] = []
    for row in attendees_rows:
        if "Name" in row and row["Name"]:
            names.append(row["Name"].strip())
    return names


def _assets_from_csv(asset_rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    assets: List[Dict[str, object]] = []
    for row in asset_rows:
        try:
            name = row.get("name", "").strip()
            prio = int(row.get("priority", ""))
            assets.append({"name": name, "priority": prio, "type": row.get("type", ""), "description": row.get("description", "")})
        except Exception:
            return []
    return assets


def _find_to_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("to:"):
            return line.strip()
    return None


def _find_subject_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith("subject:"):
            return line.strip()
    return None


def _check_to_line_has_emails_in_order(to_line: str, emails: List[str]) -> bool:
    # Normalize: remove "To:" and split by commas
    if to_line is None:
        return False
    after = to_line.split(":", 1)[1] if ":" in to_line else ""
    listed = [e.strip() for e in after.split(",") if e.strip()]
    return [e.lower() for e in listed] == [e.lower() for e in emails]


def _text_contains_terms(text: str, ref: str, min_terms: int = 2) -> bool:
    tokens = _tokenize_significant(ref, min_len=5)
    if not tokens:
        return False
    t = text.lower()
    count = sum(1 for tok in set(tokens) if tok in t)
    return count >= min_terms


def _find_lines_with(text: str, needle: str) -> List[str]:
    found = []
    low_needle = needle.lower()
    for line in text.splitlines():
        if low_needle in line.lower():
            found.append(line)
    return found


def _line_contains_both(line: str, a: str, b: str) -> bool:
    return a.lower() in line.lower() and b.lower() in line.lower()


def _extract_number_from_line(line: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b\d+\b", line)]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_exists": 0.0,
        "summary_sections_present": 0.0,
        "summary_meeting_title_and_date_correct": 0.0,
        "summary_attendees_complete": 0.0,
        "summary_agenda_coverage_accuracy": 0.0,
        "summary_decisions_extracted": 0.0,
        "summary_action_items_extracted_with_status_and_due": 0.0,
        "summary_internal_external_count_correct": 0.0,
        "summary_attractions_with_priority_correct": 0.0,
        "summary_next_meeting_date_correct": 0.0,
        "summary_sources_listed_and_count": 0.0,
        "attendees_email_file_exists": 0.0,
        "attendees_email_to_line_complete": 0.0,
        "attendees_email_subject_includes_date": 0.0,
        "attendees_email_decisions_summarized": 0.0,
        "attendees_email_actions_by_owner_with_due_dates": 0.0,
        "attendees_email_mentions_next_meeting": 0.0,
        "hotel_email_file_exists": 0.0,
        "hotel_email_subject_proposes_partnership_package": 0.0,
        "hotel_email_references_at_least_two_attractions": 0.0,
        "hotel_email_cta_proposals_with_due_date": 0.0,
    }

    # Input paths
    meeting_dir = workspace / "input" / "meetings" / "2026-04-15"
    agenda_path = meeting_dir / "agenda.md"
    attendees_path = meeting_dir / "attendees.csv"
    notes_path = meeting_dir / "notes.txt"
    assets_path = workspace / "input" / "resources" / "gwandum_assets.csv"

    # Load inputs
    agenda_text = _safe_read_text(agenda_path) or ""
    attendees_rows = _safe_read_csv_dicts(attendees_path)
    notes_text = _safe_read_text(notes_path) or ""
    assets_rows = _safe_read_csv_dicts(assets_path)

    # Parse inputs safely
    title, date_str, agenda_items = (None, None, [])
    if agenda_text:
        t, d, items = _parse_agenda(agenda_text)
        title, date_str, agenda_items = (t, d, items)

    attendees_valid = attendees_rows is not None and len(attendees_rows) > 0 and "Name" in attendees_rows[0] and "Email" in attendees_rows[0] and "Role" in attendees_rows[0]
    assets_valid = assets_rows is not None and len(assets_rows) > 0 and "name" in assets_rows[0]
    parsed_notes = _parse_notes(notes_text) if notes_text else {"decisions": [], "actions": [], "next_meeting": None}
    decisions = parsed_notes.get("decisions", [])
    actions = parsed_notes.get("actions", [])
    next_meeting = parsed_notes.get("next_meeting")

    attendee_names = _names_from_attendees(attendees_rows) if attendees_valid else []
    attendee_emails = _emails_from_attendees(attendees_rows) if attendees_valid else []
    assets = _assets_from_csv(assets_rows) if assets_valid else []
    asset_name_to_priority = {a["name"]: int(a["priority"]) for a in assets}

    # Determine agenda coverage expectations
    agenda_coverage_expected = {}
    if agenda_items and notes_text:
        for item in agenda_items:
            agenda_coverage_expected[item] = "Addressed" if _agenda_item_addressed(item, notes_text) else "Unaddressed"

    # Determine attractions mentioned in notes
    mentioned_assets = []
    if assets and notes_text:
        for a in assets:
            if a["name"] and a["name"] in notes_text:
                mentioned_assets.append(a["name"])

    # Output paths
    summary_path = workspace / "output" / "2026-04-15_gwandum_promo_meeting_summary.md"
    attendees_email_path = workspace / "output" / "draft_emails" / "attendees_followup_email.txt"
    hotel_email_path = workspace / "output" / "draft_emails" / "hotel_outreach_email.txt"

    # Summary file checks
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0

        # Sections presence
        required_sections = [
            "Meeting Details", "Attendees", "Agenda Coverage", "Decisions",
            "Action Items", "Attractions mentioned", "Next meeting", "Sources"
        ]
        if all(rs.lower() in summary_text.lower() for rs in required_sections):
            scores["summary_sections_present"] = 1.0

        # Meeting title and date
        expected_date = "2026-04-15"
        title_ok = (title is None) or (title and title in summary_text)
        date_ok = expected_date in summary_text
        if title_ok and date_ok:
            scores["summary_meeting_title_and_date_correct"] = 1.0

        # Attendees listed (Name and Role)
        attendees_ok = False
        if attendees_valid:
            attendees_ok = True
            for row in attendees_rows:
                name = row.get("Name", "").strip()
                role = row.get("Role", "").strip()
                line_found = False
                for line in summary_text.splitlines():
                    if name in line and role in line:
                        line_found = True
                        break
                if not line_found:
                    attendees_ok = False
                    break
        if attendees_ok:
            scores["summary_attendees_complete"] = 1.0

        # Agenda coverage accuracy
        agenda_ok = False
        if agenda_coverage_expected:
            all_ok = True
            for item, status in agenda_coverage_expected.items():
                found_match = False
                for line in summary_text.splitlines():
                    if item.lower() in line.lower() and status.lower() in line.lower():
                        found_match = True
                        break
                if not found_match:
                    all_ok = False
                    break
            agenda_ok = all_ok
        if agenda_ok:
            scores["summary_agenda_coverage_accuracy"] = 1.0

        # Decisions extracted (exact lines after DECISION: should appear)
        decisions_ok = False
        if decisions:
            decisions_ok = all(d in summary_text for d in decisions)
        if decisions_ok:
            scores["summary_decisions_extracted"] = 1.0

        # Action items extracted with status and due date
        actions_ok = False
        internal_names_set = set(attendee_names)
        if actions:
            all_ok = True
            for action in actions:
                owner = action.get("owner", "")
                due = action.get("due", "")
                # Check that summary contains at least owner and due
                if owner and due:
                    owner_found = owner in summary_text
                    due_found = due in summary_text
                    # Check status Internal/External based on exact match
                    status_expected = "Internal" if owner in internal_names_set else "External"
                    status_found = status_expected in summary_text
                    if not (owner_found and due_found and status_found):
                        all_ok = False
                        break
                else:
                    all_ok = False
                    break
            actions_ok = all_ok
        if actions_ok:
            scores["summary_action_items_extracted_with_status_and_due"] = 1.0

        # Internal/External count summary line like: Internal N / External M
        count_ok = False
        if actions:
            internal_count = 0
            external_count = 0
            for action in actions:
                owner = action.get("owner", "")
                if owner in internal_names_set:
                    internal_count += 1
                else:
                    external_count += 1
            m = re.search(r"Internal\s+(\d+)\s*/\s*External\s+(\d+)", summary_text, flags=re.IGNORECASE)
            if m:
                try:
                    i_num = int(m.group(1))
                    e_num = int(m.group(2))
                    if i_num == internal_count and e_num == external_count:
                        count_ok = True
                except Exception:
                    count_ok = False
        if count_ok:
            scores["summary_internal_external_count_correct"] = 1.0

        # Attractions mentioned with priority
        attractions_ok = False
        if assets:
            if mentioned_assets:
                # For each mentioned asset, ensure a line contains both name and priority
                all_ok = True
                for name in mentioned_assets:
                    prio = asset_name_to_priority.get(name)
                    found = False
                    if prio is None:
                        all_ok = False
                        break
                    for line in summary_text.splitlines():
                        if name in line and re.search(rf"\b{prio}\b", line):
                            found = True
                            break
                    if not found:
                        all_ok = False
                        break
                attractions_ok = all_ok
            else:
                # Expect "None mentioned"
                attractions_ok = "None mentioned".lower() in summary_text.lower()
        if attractions_ok:
            scores["summary_attractions_with_priority_correct"] = 1.0

        # Next meeting date correct
        next_meeting_ok = False
        expected_next = next_meeting if next_meeting else "TBD"
        # Check presence of expected next meeting
        if expected_next in summary_text:
            next_meeting_ok = True
        if next_meeting_ok:
            scores["summary_next_meeting_date_correct"] = 1.0

        # Sources listed and count
        sources_ok = False
        if agenda_text and attendees_valid and notes_text and assets:
            expected_paths = [
                "input/meetings/2026-04-15/agenda.md",
                "input/meetings/2026-04-15/attendees.csv",
                "input/meetings/2026-04-15/notes.txt",
                "input/resources/gwandum_assets.csv",
            ]
            paths_ok = all(p in summary_text for p in expected_paths)
            # Count files under meeting dir
            meeting_files_count = len([p for p in meeting_dir.iterdir() if p.is_file()]) if meeting_dir.exists() else 0
            # Look for a line mentioning the directory and the count, or "number/count/total" with the count
            count_found = False
            for line in summary_text.splitlines():
                if "input/meetings/2026-04-15" in line and str(meeting_files_count) in line:
                    count_found = True
                    break
            if not count_found:
                for line in summary_text.splitlines():
                    if re.search(r"(number|count|total)", line, flags=re.IGNORECASE):
                        nums = _extract_number_from_line(line)
                        if meeting_files_count in nums:
                            count_found = True
                            break
            sources_ok = paths_ok and count_found
        if sources_ok:
            scores["summary_sources_listed_and_count"] = 1.0

    # Attendees follow-up email checks
    attendees_email_text = _safe_read_text(attendees_email_path)
    if attendees_email_text is not None:
        scores["attendees_email_file_exists"] = 1.0
        to_line = _find_to_line(attendees_email_text)
        if attendees_valid and to_line and _check_to_line_has_emails_in_order(to_line, attendee_emails):
            scores["attendees_email_to_line_complete"] = 1.0

        subject_line = _find_subject_line(attendees_email_text)
        if subject_line and "2026-04-15" in subject_line:
            scores["attendees_email_subject_includes_date"] = 1.0

        # Decisions summarized in body: check after subject/to lines
        body_text = attendees_email_text
        if to_line:
            body_text = body_text.replace(to_line, "")
        if subject_line:
            body_text = body_text.replace(subject_line, "")

        decisions_cov_ok = False
        if decisions:
            all_ok = True
            for d in decisions:
                if not _text_contains_terms(body_text, d, min_terms=2):
                    all_ok = False
                    break
            decisions_cov_ok = all_ok
        if decisions_cov_ok:
            scores["attendees_email_decisions_summarized"] = 1.0

        # Actions by owner with due dates present in body
        actions_email_ok = False
        if actions:
            all_ok = True
            for a in actions:
                owner = a.get("owner", "")
                due = a.get("due", "")
                if not (owner and due and (owner in attendees_email_text) and (due in attendees_email_text)):
                    all_ok = False
                    break
            actions_email_ok = all_ok
        if actions_email_ok:
            scores["attendees_email_actions_by_owner_with_due_dates"] = 1.0

        # Mention next meeting date if present
        if next_meeting and next_meeting in attendees_email_text:
            scores["attendees_email_mentions_next_meeting"] = 1.0
        elif not next_meeting:
            # If not present in notes, not required; consider it satisfied if no next meeting
            scores["attendees_email_mentions_next_meeting"] = 1.0

    # Hotel outreach email checks
    hotel_email_text = _safe_read_text(hotel_email_path)
    if hotel_email_text is not None:
        scores["hotel_email_file_exists"] = 1.0
        subject_line = _find_subject_line(hotel_email_text)
        subj_ok = False
        if subject_line:
            subj_ok = ("gwandum weekend discovery".lower() in subject_line.lower()) and ("partnership" in subject_line.lower())
        if subj_ok:
            scores["hotel_email_subject_proposes_partnership_package"] = 1.0

        # References at least two attractions
        attractions_ref_ok = False
        if assets:
            intersection = [n for n in mentioned_assets]
            # Determine required set
            required_names: List[str] = []
            if len(intersection) >= 2:
                required_names = intersection
                # Only need at least two referenced
                count_present = sum(1 for name in intersection if name in hotel_email_text)
                attractions_ref_ok = count_present >= 2
            else:
                # Use top two by lowest priority
                sorted_assets = sorted(assets, key=lambda x: int(x["priority"]))
                top_two = [sorted_assets[0]["name"], sorted_assets[1]["name"]] if len(sorted_assets) >= 2 else [sorted_assets[0]["name"]] if sorted_assets else []
                count_present = sum(1 for name in top_two if name in hotel_email_text)
                attractions_ref_ok = count_present >= min(2, len(top_two))
        if attractions_ref_ok:
            scores["hotel_email_references_at_least_two_attractions"] = 1.0

        # Call to action asking for package rate proposals by due date of partnership outreach action
        # Find due date for partnership outreach action
        outreach_due = None
        for a in actions:
            summ = a.get("summary", "").lower()
            if any(k in summ for k in ["hotel", "hotels", "partnership", "package rate", "package rates"]):
                if a.get("due"):
                    outreach_due = a.get("due")
                    break
        cta_ok = False
        if outreach_due:
            cta_ok = ("proposal" in hotel_email_text.lower() or "proposals" in hotel_email_text.lower()) and (outreach_due in hotel_email_text)
        if cta_ok:
            scores["hotel_email_cta_proposals_with_due_date"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()