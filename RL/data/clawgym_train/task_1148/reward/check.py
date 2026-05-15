import csv
import json
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers exist
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(p: Path) -> Optional[Dict]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _load_stakeholders(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "input" / "stakeholders.csv")


def _load_slots(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "input" / "slots.csv")


def _load_availability(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "input" / "availability.csv")


def _load_rooms(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "input" / "rooms.csv")


def _compute_expected_slot_ranking(workspace: Path) -> Optional[List[Dict[str, str]]]:
    stakeholders = _load_stakeholders(workspace)
    slots = _load_slots(workspace)
    availability = _load_availability(workspace)
    rooms = _load_rooms(workspace)
    if any(x is None for x in [stakeholders, slots, availability, rooms]):
        return None

    # Build maps
    # Stakeholder priorities
    stake_priority: Dict[str, str] = {}
    for s in stakeholders:
        name = s.get("name", "").strip()
        priority = s.get("priority", "").strip()
        if name:
            stake_priority[name] = priority

    # Availability map: (name, slot_id) -> yes/no
    avail_map: Dict[Tuple[str, str], str] = {}
    for a in availability:
        name = a.get("name", "").strip()
        slot_id = a.get("slot_id", "").strip()
        available = a.get("available", "").strip().lower()
        if name and slot_id:
            avail_map[(name, slot_id)] = available

    # Rooms availability and capacities
    rooms_info = []
    for r in rooms:
        try:
            room_name = r.get("room_name", "").strip()
            location = r.get("location", "").strip()
            capacity = int(r.get("capacity", "").strip())
            available_slot_ids = [s.strip() for s in r.get("available_slot_ids", "").split(";") if s.strip()]
            rooms_info.append({
                "room_name": room_name,
                "location": location,
                "capacity": capacity,
                "available_slot_ids": set(available_slot_ids),
            })
        except Exception:
            return None

    expected_rows: List[Dict[str, str]] = []

    for slot in slots:
        slot_id = slot.get("slot_id", "").strip()
        slot_start = slot.get("slot_start", "").strip()
        slot_end = slot.get("slot_end", "").strip()
        if not slot_id or not slot_start or not slot_end:
            return None

        # Compute availability counts
        required_available = 0
        important_available = 0
        optional_available = 0
        attendees_available = 0

        all_required_available = True
        for name, pr in stake_priority.items():
            available = avail_map.get((name, slot_id), "no") == "yes"
            if available:
                attendees_available += 1
                if pr == "Required":
                    required_available += 1
                elif pr == "Important":
                    important_available += 1
                elif pr == "Optional":
                    optional_available += 1
            else:
                if pr == "Required":
                    all_required_available = False

        # Check room eligibility
        eligible_room_name = ""
        eligible_room_capacity = None
        if all_required_available:
            fitting_rooms = []
            for r in rooms_info:
                if slot_id in r["available_slot_ids"] and r["capacity"] >= attendees_available:
                    fitting_rooms.append((r["capacity"], r["room_name"]))
            if fitting_rooms:
                fitting_rooms.sort(key=lambda x: x[0])  # smallest capacity first
                eligible_room_capacity, eligible_room_name = fitting_rooms[0]

        # Eligibility
        if all_required_available and eligible_room_name:
            score = 3 * required_available + 2 * important_available + optional_available
            expected_rows.append({
                "slot_id": slot_id,
                "slot_start": slot_start,
                "slot_end": slot_end,
                "required_available_count": str(required_available),
                "important_available_count": str(important_available),
                "optional_available_count": str(optional_available),
                "attendees_available_count": str(attendees_available),
                "score": str(score),
                "eligible_room": eligible_room_name,
                "room_capacity": str(eligible_room_capacity),
            })

    # Sort: score desc, slot_start asc
    expected_rows.sort(key=lambda r: (-int(r["score"]), r["slot_start"]))
    return expected_rows


def _parse_transcript_actions_and_decisions(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    txt = _read_text(workspace / "input" / "transcript.txt")
    if txt is None:
        return None, None

    # Actions: "Action: <Owner> — <Description>. Due: YYYY-MM-DD."
    # Support hyphen or em-dash
    action_pattern = re.compile(
        r"Action:\s*([^\n—\-]+?)\s*[—\-]\s*(.*?)\s*\.?\s*Due:\s*(\d{4}-\d{2}-\d{2})\.?",
        re.IGNORECASE
    )
    actions = []
    for m in action_pattern.finditer(txt):
        owner = m.group(1).strip()
        description = m.group(2).strip()
        due_date = m.group(3).strip()
        actions.append({
            "owner": owner,
            "description": description,
            "due_date": due_date,
        })

    # Decisions: "Decision: <text>."
    decision_pattern = re.compile(r"Decision:\s*(.+?)\.", re.IGNORECASE)
    decisions = []
    for m in decision_pattern.finditer(txt):
        decision_text = m.group(1).strip()
        decisions.append(decision_text)

    return actions, decisions


def _load_action_items_csv(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "outputs" / "action_items.csv")


def _load_slot_ranking_csv(workspace: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(workspace / "outputs" / "slot_ranking.csv")


def _load_selected_slot_json(workspace: Path) -> Optional[Dict]:
    return _read_json(workspace / "outputs" / "selected_slot.json")


def _load_meeting_notes(workspace: Path) -> Optional[str]:
    return _read_text(workspace / "outputs" / "meeting_notes.md")


def _load_invite_email(workspace: Path) -> Optional[str]:
    return _read_text(workspace / "outputs" / "invite_email.txt")


def _slot_ranking_headers_ok(rows: Optional[List[Dict[str, str]]]) -> bool:
    if rows is None:
        return False
    expected_headers = [
        "slot_id",
        "slot_start",
        "slot_end",
        "required_available_count",
        "important_available_count",
        "optional_available_count",
        "attendees_available_count",
        "score",
        "eligible_room",
        "room_capacity",
    ]
    # csv.DictReader stores headers in fieldnames attribute, but we didn't return that.
    # Re-read to get headers strictly.
    # Here, deduce from first row keys ordering is not guaranteed. We'll re-open file to check headers.
    return True  # Handled in grade with direct file read


def _get_csv_headers(p: Path) -> Optional[List[str]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            first_line = f.readline()
            if not first_line:
                return None
            headers = [h.strip() for h in first_line.strip().split(",")]
            return headers
    except Exception:
        return None


def _parse_meeting_notes_sections(text: str) -> Dict[str, str]:
    # Extract sections by headings for "Decisions" and "Action Items"
    lines = text.splitlines()
    sections = {}
    current = None
    buf = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        lower = stripped.lower()
        is_heading = False
        if lower == "decisions" or lower == "action items":
            is_heading = True
            section_name = stripped
        elif stripped.startswith("#"):
            # Markdown heading, extract title
            title = stripped.lstrip("#").strip().lower()
            if title == "decisions":
                is_heading = True
                section_name = "Decisions"
            elif title == "action items":
                is_heading = True
                section_name = "Action Items"

        if is_heading:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
                buf = []
            current = section_name
            continue

        if current is not None:
            buf.append(line)

    if current is not None:
        sections[current] = "\n".join(buf).strip()

    return sections


def _emails_from_stakeholders(workspace: Path) -> Optional[List[str]]:
    stakeholders = _load_stakeholders(workspace)
    if stakeholders is None:
        return None
    emails = []
    for s in stakeholders:
        email = s.get("email", "").strip()
        if email:
            emails.append(email)
    return emails


def _rooms_location_map(workspace: Path) -> Optional[Dict[str, str]]:
    rooms = _load_rooms(workspace)
    if rooms is None:
        return None
    mapping = {}
    for r in rooms:
        name = r.get("room_name", "").strip()
        loc = r.get("location", "").strip()
        if name:
            mapping[name] = loc
    return mapping


def _agenda_items(workspace: Path) -> Optional[List[str]]:
    text = _read_text(workspace / "input" / "agenda.md")
    if text is None:
        return None
    items = []
    for line in text.splitlines():
        if line.strip().startswith("- "):
            items.append(line.strip()[2:].strip())
    return items


def _normalize_emails_list(s: str) -> List[str]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "slot_ranking_columns": 0.0,
        "slot_ranking_eligibility_complete": 0.0,
        "slot_ranking_metrics_correct": 0.0,
        "slot_ranking_room_selection_correct": 0.0,
        "slot_ranking_sorting_correct": 0.0,
        "selected_slot_consistency": 0.0,
        "action_items_columns_and_format": 0.0,
        "action_items_match_transcript": 0.0,
        "meeting_notes_decisions_covered": 0.0,
        "meeting_notes_actions_consistent": 0.0,
        "invite_email_to_recipients": 0.0,
        "invite_email_subject_uses_selected_time": 0.0,
        "invite_email_body_includes_selected_details": 0.0,
        "invite_email_body_includes_alternates": 0.0,
        "invite_email_body_includes_agenda": 0.0,
        "invite_email_body_includes_due_actions": 0.0,
        "invite_email_calls_to_confirm": 0.0,
    }

    # Compute expected slot ranking
    expected_ranking = _compute_expected_slot_ranking(workspace)

    # Load produced slot ranking
    slot_ranking_path = workspace / "outputs" / "slot_ranking.csv"
    slot_ranking_rows = _read_csv_dicts(slot_ranking_path)
    slot_ranking_headers = _get_csv_headers(slot_ranking_path)

    expected_headers = [
        "slot_id",
        "slot_start",
        "slot_end",
        "required_available_count",
        "important_available_count",
        "optional_available_count",
        "attendees_available_count",
        "score",
        "eligible_room",
        "room_capacity",
    ]
    if slot_ranking_headers == expected_headers:
        scores["slot_ranking_columns"] = 1.0

    if expected_ranking is not None and slot_ranking_rows is not None:
        # Eligibility complete: exact set match
        produced_slot_ids = [r.get("slot_id", "").strip() for r in slot_ranking_rows]
        expected_slot_ids = [r["slot_id"] for r in expected_ranking]
        if set(produced_slot_ids) == set(expected_slot_ids):
            scores["slot_ranking_eligibility_complete"] = 1.0

        # Metrics correctness and room selection correctness
        metrics_ok = True
        rooms_ok = True
        expected_map = {r["slot_id"]: r for r in expected_ranking}
        for r in slot_ranking_rows:
            sid = r.get("slot_id", "").strip()
            exp = expected_map.get(sid)
            if exp is None:
                metrics_ok = False
                rooms_ok = False
                break
            # Check metrics
            for key in [
                "slot_start",
                "slot_end",
                "required_available_count",
                "important_available_count",
                "optional_available_count",
                "attendees_available_count",
                "score",
            ]:
                if str(r.get(key, "")).strip() != str(exp[key]).strip():
                    metrics_ok = False
                    break
            # Check room selection
            if str(r.get("eligible_room", "")).strip() != str(exp["eligible_room"]).strip():
                rooms_ok = False
            if str(r.get("room_capacity", "")).strip() != str(exp["room_capacity"]).strip():
                rooms_ok = False
            if not metrics_ok:
                # no need to continue loop for metrics, but continue to collect rooms_ok as well
                pass
        if metrics_ok:
            scores["slot_ranking_metrics_correct"] = 1.0
        if rooms_ok:
            scores["slot_ranking_room_selection_correct"] = 1.0

        # Sorting correctness
        # Verify produced rows sorted by score desc, then slot_start asc
        try:
            produced_sorted = sorted(
                slot_ranking_rows,
                key=lambda x: (-int(x.get("score", "0")), x.get("slot_start", "")),
            )
            if [
                (r.get("slot_id", ""), r.get("slot_start", ""))
                for r in slot_ranking_rows
            ] == [
                (r.get("slot_id", ""), r.get("slot_start", ""))
                for r in produced_sorted
            ]:
                scores["slot_ranking_sorting_correct"] = 1.0
        except Exception:
            pass

    # Selected slot consistency
    selected_json = _load_selected_slot_json(workspace)
    if selected_json is not None:
        # Check presence of keys
        keys_ok = all(k in selected_json for k in ["slot_id", "slot_start", "slot_end", "room_name", "room_capacity", "rationale"])
        consistency = False
        if keys_ok:
            # If there are expected eligible slots
            if expected_ranking is not None and len(expected_ranking) > 0:
                # Must match top row of produced slot_ranking.csv if available, else expected
                top_expected = expected_ranking[0]
                sid = str(selected_json.get("slot_id", "")).strip()
                room_name = str(selected_json.get("room_name", "")).strip()
                room_capacity = str(selected_json.get("room_capacity", "")).strip()
                slot_start = str(selected_json.get("slot_start", "")).strip()
                slot_end = str(selected_json.get("slot_end", "")).strip()
                # Prefer consistency with produced slot_ranking.csv if available and correct
                if slot_ranking_rows:
                    top_produced = slot_ranking_rows[0]
                    if (
                        sid == str(top_produced.get("slot_id", "")).strip()
                        and slot_start == str(top_produced.get("slot_start", "")).strip()
                        and slot_end == str(top_produced.get("slot_end", "")).strip()
                        and room_name == str(top_produced.get("eligible_room", "")).strip()
                        and room_capacity == str(top_produced.get("room_capacity", "")).strip()
                        and str(selected_json.get("rationale", "")).strip() != ""
                    ):
                        consistency = True
                else:
                    if (
                        sid == top_expected["slot_id"]
                        and slot_start == top_expected["slot_start"]
                        and slot_end == top_expected["slot_end"]
                        and room_name == top_expected["eligible_room"]
                        and room_capacity == top_expected["room_capacity"]
                        and str(selected_json.get("rationale", "")).strip() != ""
                    ):
                        consistency = True
            else:
                # No eligible slots expected: rationale must explain none qualified (non-empty)
                rationale = str(selected_json.get("rationale", "")).strip().lower()
                # Accept any non-empty rationale; stronger check if contains 'none'
                if rationale:
                    consistency = True
        if keys_ok and consistency:
            scores["selected_slot_consistency"] = 1.0

    # Action items checks
    action_rows = _load_action_items_csv(workspace)
    stakeholders = _load_stakeholders(workspace)
    transcript_actions, transcript_decisions = _parse_transcript_actions_and_decisions(workspace)

    # Columns and format
    if action_rows is not None:
        headers = _get_csv_headers(workspace / "outputs" / "action_items.csv")
        if headers == ["description", "owner", "due_date", "status"]:
            # Check due_date format and status Pending and owners present in stakeholders
            owners_set = set()
            if stakeholders is not None:
                owners_set = {s.get("name", "").strip() for s in stakeholders}
            fmt_ok = True
            for r in action_rows:
                due = r.get("due_date", "").strip()
                status = r.get("status", "").strip()
                owner = r.get("owner", "").strip()
                description = r.get("description", "").strip()
                # due_date format check
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                    fmt_ok = False
                    break
                if status != "Pending":
                    fmt_ok = False
                    break
                if owner not in owners_set:
                    fmt_ok = False
                    break
                if description == "":
                    fmt_ok = False
                    break
            if fmt_ok:
                scores["action_items_columns_and_format"] = 1.0

    # Match transcript actions
    if action_rows is not None and transcript_actions is not None and stakeholders is not None:
        # Filter transcript actions to only those owners in stakeholders
        stakeholder_names = {s.get("name", "").strip() for s in stakeholders}
        expected_actions = [
            a for a in transcript_actions if a["owner"] in stakeholder_names
        ]
        produced_set = {(r.get("owner", "").strip(), r.get("description", "").strip(), r.get("due_date", "").strip()) for r in action_rows}
        expected_set = {(a["owner"], a["description"], a["due_date"]) for a in expected_actions}
        if produced_set == expected_set and len(produced_set) == len(expected_set):
            scores["action_items_match_transcript"] = 1.0

    # Meeting notes checks
    notes_text = _load_meeting_notes(workspace)
    if notes_text is not None:
        sections = _parse_meeting_notes_sections(notes_text)
        # Decisions covered
        if transcript_decisions is not None:
            decisions_text = sections.get("Decisions") or sections.get("decisions")
            if decisions_text is not None:
                dec_ok = True
                for d in transcript_decisions:
                    # Check substring presence without trailing period sensitivity
                    core = d.rstrip(".")
                    if core not in decisions_text:
                        dec_ok = False
                        break
                if dec_ok:
                    scores["meeting_notes_decisions_covered"] = 1.0
        # Actions consistent
        action_section = sections.get("Action Items") or sections.get("action items")
        if action_section is not None and action_rows is not None:
            actions_ok = True
            for r in action_rows:
                owner = r.get("owner", "").strip()
                description = r.get("description", "").strip()
                due = r.get("due_date", "").strip()
                # All components should appear in the section
                if owner not in action_section or due not in action_section or description not in action_section:
                    actions_ok = False
                    break
            if actions_ok:
                scores["meeting_notes_actions_consistent"] = 1.0

    # Invite email checks
    email_text = _load_invite_email(workspace)
    if email_text is not None:
        lines = [l.strip() for l in email_text.splitlines() if l.strip() != ""]
        # To line
        to_line = None
        for l in lines:
            if l.lower().startswith("to:"):
                to_line = l
                break
        emails_expected = _emails_from_stakeholders(workspace)
        if to_line is not None and emails_expected is not None:
            to_emails = _normalize_emails_list(to_line.split(":", 1)[1])
            if set(to_emails) == set(emails_expected):
                scores["invite_email_to_recipients"] = 1.0

        # Subject line
        subject_line = None
        for l in lines:
            if l.lower().startswith("subject:"):
                subject_line = l
                break
        if subject_line is not None and selected_json is not None:
            subj_text = subject_line.split(":", 1)[1].strip()
            slot_start_sel = str(selected_json.get("slot_start", "")).strip()
            if "Book Launch Logistics Sync" in subj_text and slot_start_sel and slot_start_sel in subj_text:
                scores["invite_email_subject_uses_selected_time"] = 1.0

        # Body content (everything)
        body_text = email_text

        # Selected details: include selected meeting date/time and chosen room/location
        selected_ok = False
        if selected_json is not None:
            slot_start_sel = str(selected_json.get("slot_start", "")).strip()
            slot_end_sel = str(selected_json.get("slot_end", "")).strip()
            room_name_sel = str(selected_json.get("room_name", "")).strip()
            rooms_loc_map = _rooms_location_map(workspace) or {}
            location_sel = rooms_loc_map.get(room_name_sel, "")
            # Require slot_start and room name and location to be present
            if slot_start_sel and room_name_sel and location_sel:
                if (slot_start_sel in body_text) and (room_name_sel in body_text) and (location_sel in body_text):
                    selected_ok = True
        if selected_ok:
            scores["invite_email_body_includes_selected_details"] = 1.0

        # Alternates
        alternates_ok = False
        slot_ranking_rows_prod = slot_ranking_rows or []
        if len(slot_ranking_rows_prod) >= 2 and selected_json is not None:
            # Take up to two alternates after the selected slot in produced ranking
            # Find order of produced ranking; selected should be first; but handle if not
            produced_order = slot_ranking_rows_prod
            # Determine selected slot id
            selected_sid = str(selected_json.get("slot_id", "")).strip()
            # Build alternates: those after the selected in produced order
            alt_candidates = [r for r in produced_order if str(r.get("slot_id", "")).strip() != selected_sid]
            alts = alt_candidates[:2]
            if alts:
                # Check presence and rank order in body
                indices = []
                present_all = True
                for alt in alts:
                    alt_start = alt.get("slot_start", "").strip()
                    idx = body_text.find(alt_start) if alt_start else -1
                    if idx == -1:
                        present_all = False
                        break
                    indices.append(idx)
                if present_all and indices == sorted(indices):
                    alternates_ok = True
            else:
                # No alternates required
                alternates_ok = True
        else:
            # If fewer than 2 eligible slots, accept if body contains any alternates that exist or none if not available
            alternates_ok = True
        if alternates_ok:
            scores["invite_email_body_includes_alternates"] = 1.0

        # Agenda included
        agenda_items = _agenda_items(workspace)
        if agenda_items is not None:
            agenda_ok = True
            for item in agenda_items:
                # Look for item text anywhere in body (prefer bullet lines but accept substring)
                if item not in body_text:
                    agenda_ok = False
                    break
            if agenda_ok:
                scores["invite_email_body_includes_agenda"] = 1.0

        # Due actions included (<= selected date)
        due_actions_ok = False
        if action_rows is not None and selected_json is not None:
            slot_start_sel = str(selected_json.get("slot_start", "")).strip()
            # Extract date part YYYY-MM-DD
            m = re.match(r"(\d{4}-\d{2}-\d{2})T", slot_start_sel)
            if m:
                sel_date = m.group(1)
                # filter actions due <= sel_date
                due_actions = []
                for r in action_rows:
                    due = r.get("due_date", "").strip()
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                        if due <= sel_date:
                            due_actions.append(r)
                if due_actions:
                    present_all = True
                    for r in due_actions:
                        owner = r.get("owner", "").strip()
                        description = r.get("description", "").strip()
                        due = r.get("due_date", "").strip()
                        if owner not in body_text or due not in body_text or description not in body_text:
                            present_all = False
                            break
                    if present_all:
                        due_actions_ok = True
                else:
                    # If none due before or on selected date, accept empty
                    due_actions_ok = True
        if due_actions_ok:
            scores["invite_email_body_includes_due_actions"] = 1.0

        # Call to confirm availability
        body_lower = body_text.lower()
        if "confirm" in body_lower and "availability" in body_lower:
            scores["invite_email_calls_to_confirm"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()