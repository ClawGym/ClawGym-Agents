import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_attendees_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                row = {k: (v if v is not None else "") for k, v in r.items()}
                rows.append(row)
        return rows
    except Exception:
        return None


def _parse_notes(text: str) -> Dict[str, Any]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    meeting_date = ""
    meeting_location = ""
    decisions: List[str] = []
    events: List[Dict[str, str]] = []
    actions: List[Dict[str, str]] = []
    next_meeting_line = ""

    # Meeting date from header line with em dash or hyphen
    for ln in lines:
        m = re.search(r"Garden Club Planning Meeting\s+[—-]\s+(.+)$", ln)
        if m:
            meeting_date = m.group(1).strip()
            break

    # Meeting location from "Location:"
    for ln in lines:
        if ln.strip().lower().startswith("location:"):
            meeting_location = ln.split(":", 1)[1].strip()
            break

    # Next meeting line
    for ln in lines:
        nm = re.match(r"^Next meeting:\s*(.+)$", ln.strip())
        if nm:
            next_meeting_line = f"Next meeting: {nm.group(1).strip()}"
            break

    # Iterate for decisions, events, actions
    i = 0
    while i < len(lines):
        ln = lines[i]
        d = re.match(r"^DECISION:\s*(.+)$", ln.strip())
        if d:
            decisions.append(d.group(1).strip())
            i += 1
            continue

        e = re.match(
            r"^EVENT:\s*(?P<title>.+?)\s+on\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s*\d{4})\s+at\s+(?P<location>[^,\.]+)(?:,\s*(?P<time>[^\.]+))?\.$",
            ln.strip(),
        )
        if e:
            event = {
                "title": e.group("title").strip(),
                "date": e.group("date").strip(),
                "location": e.group("location").strip(),
                "time": (e.group("time").strip() if e.group("time") else ""),
                "notes": "",
            }
            # Check following line for Note:
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                note_m = re.match(r"^Note:\s*(.+)$", nxt)
                if note_m:
                    event["notes"] = note_m.group(1).strip()
                    i += 1  # consume note line as well
            events.append(event)
            i += 1
            continue

        a = re.match(
            r"^ACTION:\s*(?P<assignee>.+?)\s+to\s+(?P<task>.+?)\s+by\s+(?P<due>[^\.]+)\.$",
            ln.strip(),
        )
        if a:
            actions.append(
                {
                    "assignee_name": a.group("assignee").strip(),
                    "task": a.group("task").strip(),
                    "due_date": a.group("due").strip(),
                }
            )
            i += 1
            continue

        i += 1

    return {
        "meeting_date": meeting_date,
        "meeting_location": meeting_location,
        "decisions": decisions,
        "events": events,
        "actions": actions,
        "next_meeting": next_meeting_line,
    }


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    notes_path = workspace / "input" / "meeting_notes.txt"
    attendees_path = workspace / "input" / "attendees.csv"
    notes_text = _read_text_safe(notes_path)
    attendees_rows = _load_attendees_csv(attendees_path)
    if notes_text is None or attendees_rows is None:
        return None

    parsed_notes = _parse_notes(notes_text)
    meeting_date = parsed_notes["meeting_date"]
    meeting_location = parsed_notes["meeting_location"]
    decisions = parsed_notes["decisions"]
    events = parsed_notes["events"]
    actions = parsed_notes["actions"]

    # Attendees present based on attended=true
    attendees_present: List[str] = []
    email_lookup: Dict[str, str] = {}
    for row in attendees_rows:
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        attended_val = (row.get("attended") or "").strip().lower()
        attended = attended_val in {"true", "yes", "1", "y", "t"}
        if attended and name:
            attendees_present.append(name)
        if name:
            email_lookup[name.lower()] = email

    # Build action items with matched email
    action_items: List[Dict[str, Any]] = []
    for a in actions:
        assignee = a["assignee_name"]
        task = a["task"]
        due = a["due_date"]
        email = email_lookup.get(assignee.lower(), "")
        matched = bool(email)
        item = {
            "assignee_name": assignee,
            "task": task,
            "due_date": due,
            "matched_email": matched,
        }
        if matched:
            item["email"] = email
        else:
            item["email"] = ""
        action_items.append(item)

    return {
        "meeting": {"date": meeting_date, "location": meeting_location},
        "attendees_present": attendees_present,
        "decisions": decisions,
        "events": events,
        "action_items": action_items,
        "next_meeting": parsed_notes["next_meeting"],
    }


def _run_script(workspace: Path) -> bool:
    script_path = workspace / "tools" / "garden_meeting_parser.py"
    notes_path = workspace / "input" / "meeting_notes.txt"
    attendees_path = workspace / "input" / "attendees.csv"
    if not script_path.exists() or not notes_path.exists() or not attendees_path.exists():
        return False
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--notes",
                str(notes_path),
                "--attendees",
                str(attendees_path),
                "--outdir",
                "outputs",
            ],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _find_count_line(text: str, keyword: str, expected: int) -> bool:
    for line in text.splitlines():
        if keyword.lower() in line.lower():
            if re.search(rf"\b{expected}\b", line):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_runs_success": 0.0,
        "parsed_json_present": 0.0,
        "parsed_json_meeting_fields": 0.0,
        "parsed_json_attendees_present_list": 0.0,
        "parsed_json_decisions": 0.0,
        "parsed_json_events": 0.0,
        "parsed_json_action_items": 0.0,
        "summary_has_meeting_info": 0.0,
        "summary_attendees_listed": 0.0,
        "summary_decisions_listed": 0.0,
        "summary_events_and_notes_listed": 0.0,
        "summary_action_items_split": 0.0,
        "summary_counts_correct": 0.0,
        "member_update_email_subject": 0.0,
        "member_update_email_content": 0.0,
        "volunteer_emails_all_matched_present": 0.0,
        "volunteer_emails_content_correct": 0.0,
        "volunteer_emails_unmatched_absent": 0.0,
    }

    script_path = workspace / "tools" / "garden_meeting_parser.py"
    if script_path.exists():
        scores["script_exists"] = 1.0

    expected = _compute_expected(workspace)

    ran_ok = _run_script(workspace)
    if ran_ok:
        scores["script_runs_success"] = 1.0

    parsed_json_path = workspace / "outputs" / "parsed.json"
    parsed_obj = _load_json_safe(parsed_json_path)
    if parsed_obj is not None:
        scores["parsed_json_present"] = 1.0

    if expected is not None and parsed_obj is not None and isinstance(parsed_obj, dict):
        meeting = parsed_obj.get("meeting")
        if (
            isinstance(meeting, dict)
            and meeting.get("date") == expected["meeting"]["date"]
            and meeting.get("location") == expected["meeting"]["location"]
        ):
            scores["parsed_json_meeting_fields"] = 1.0

        attendees_present = parsed_obj.get("attendees_present")
        if isinstance(attendees_present, list) and attendees_present == expected["attendees_present"]:
            scores["parsed_json_attendees_present_list"] = 1.0

        decisions = parsed_obj.get("decisions")
        if isinstance(decisions, list) and decisions == expected["decisions"]:
            scores["parsed_json_decisions"] = 1.0

        events_ok = False
        events_out = parsed_obj.get("events")
        if isinstance(events_out, list) and isinstance(expected.get("events"), list):
            if len(events_out) == len(expected["events"]):
                per_event_ok = True
                for idx, ev in enumerate(expected["events"]):
                    out_ev = events_out[idx]
                    if not isinstance(out_ev, dict):
                        per_event_ok = False
                        break
                    out_title = out_ev.get("title", "")
                    out_date = out_ev.get("date", "")
                    out_location = out_ev.get("location", "")
                    out_time = out_ev.get("time", "")
                    exp_notes = ev.get("notes", "")
                    out_notes = out_ev.get("notes", "")
                    notes_match = (exp_notes == out_notes) or (exp_notes == "" and (out_notes == "" or "notes" not in out_ev))
                    if not (
                        out_title == ev.get("title", "")
                        and out_date == ev.get("date", "")
                        and out_location == ev.get("location", "")
                        and out_time == ev.get("time", "")
                        and notes_match
                    ):
                        per_event_ok = False
                        break
                events_ok = per_event_ok
        if events_ok:
            scores["parsed_json_events"] = 1.0

        actions_ok = False
        actions_out = parsed_obj.get("action_items")
        exp_actions = expected.get("action_items")
        if isinstance(actions_out, list) and isinstance(exp_actions, list) and len(actions_out) == len(exp_actions):
            per_action_ok = True
            for idx, exp_item in enumerate(exp_actions):
                out_item = actions_out[idx]
                if not isinstance(out_item, dict):
                    per_action_ok = False
                    break
                if out_item.get("assignee_name") != exp_item.get("assignee_name"):
                    per_action_ok = False
                    break
                if out_item.get("task") != exp_item.get("task"):
                    per_action_ok = False
                    break
                if out_item.get("due_date") != exp_item.get("due_date"):
                    per_action_ok = False
                    break
                if bool(out_item.get("matched_email")) != bool(exp_item.get("matched_email")):
                    per_action_ok = False
                    break
                if exp_item.get("matched_email"):
                    if out_item.get("email") != exp_item.get("email"):
                        per_action_ok = False
                        break
                else:
                    if "email" in out_item and out_item.get("email"):
                        per_action_ok = False
                        break
            actions_ok = per_action_ok
        if actions_ok:
            scores["parsed_json_action_items"] = 1.0

    summary_path = workspace / "outputs" / "meeting_summary.md"
    summary_text = _read_text_safe(summary_path)
    if expected is not None and summary_text is not None:
        if expected["meeting"]["date"] and expected["meeting"]["location"]:
            if expected["meeting"]["date"] in summary_text and expected["meeting"]["location"] in summary_text:
                scores["summary_has_meeting_info"] = 1.0

        attendees_ok = True
        for name in expected["attendees_present"]:
            if name not in summary_text:
                attendees_ok = False
                break
        if attendees_ok and expected["attendees_present"]:
            scores["summary_attendees_listed"] = 1.0

        decisions_ok = True
        for d in expected["decisions"]:
            if d not in summary_text:
                decisions_ok = False
                break
        if decisions_ok and expected["decisions"]:
            scores["summary_decisions_listed"] = 1.0

        events_in_summary_ok = True
        for ev in expected["events"]:
            if ev["title"] not in summary_text or ev["date"] not in summary_text:
                events_in_summary_ok = False
                break
        for ev in expected["events"]:
            if ev.get("notes"):
                if ev["notes"] not in summary_text:
                    events_in_summary_ok = False
                    break
        if events_in_summary_ok and expected["events"]:
            scores["summary_events_and_notes_listed"] = 1.0

        split_ok = False
        if re.search(r"matched", summary_text, re.IGNORECASE) and re.search(r"unmatched", summary_text, re.IGNORECASE):
            matched_names = [a["assignee_name"] for a in expected["action_items"] if a.get("matched_email")]
            unmatched_names = [a["assignee_name"] for a in expected["action_items"] if not a.get("matched_email")]
            names_ok = all(n in summary_text for n in matched_names) and all(n in summary_text for n in unmatched_names)
            split_ok = names_ok
        if split_ok:
            scores["summary_action_items_split"] = 1.0

        counts_ok = (
            _find_count_line(summary_text, "decisions", len(expected["decisions"]))
            and _find_count_line(summary_text, "events", len(expected["events"]))
            and _find_count_line(summary_text, "action", len(expected["action_items"]))
            and _find_count_line(summary_text, "matched", len([a for a in expected["action_items"] if a.get("matched_email")]))
            and _find_count_line(summary_text, "unmatched", len([a for a in expected["action_items"] if not a.get("matched_email")]))
        )
        if counts_ok:
            scores["summary_counts_correct"] = 1.0

    member_email_path = workspace / "outputs" / "member_update_email.txt"
    member_email_text = _read_text_safe(member_email_path)
    if expected is not None and member_email_text is not None:
        lines = member_email_text.splitlines()
        subject_ok = False
        if lines:
            first_line = lines[0]
            if first_line.startswith("Subject:") and expected["meeting"]["date"] in first_line:
                subject_ok = True
        if subject_ok:
            scores["member_update_email_subject"] = 1.0

        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        content_ok = True
        for d in expected["decisions"]:
            if d not in body:
                content_ok = False
                break
        if content_ok:
            for ev in expected["events"]:
                if ev["title"] not in body or ev["date"] not in body:
                    content_ok = False
                    break
        if content_ok and expected.get("next_meeting"):
            if expected["next_meeting"] not in body:
                content_ok = False
        if content_ok:
            scores["member_update_email_content"] = 1.0

    volunteer_dir = workspace / "outputs" / "volunteer_emails"
    all_present_ok = False
    content_ok = False
    unmatched_absent_ok = False
    if expected is not None and volunteer_dir.exists() and volunteer_dir.is_dir():
        matched_actions = {}
        unmatched_names = []
        for a in expected["action_items"]:
            if a.get("matched_email"):
                matched_actions.setdefault(a["assignee_name"], []).append(a)
            else:
                unmatched_names.append(a["assignee_name"])

        present = True
        content_good = True
        for name, items in matched_actions.items():
            file_path = volunteer_dir / f"{name}.txt"
            if not file_path.exists():
                present = False
                content_good = False
                continue
            txt = _read_text_safe(file_path) or ""
            email = items[0].get("email", "")
            if f"To: {email}" not in txt:
                content_good = False
            if "Subject:" not in txt:
                content_good = False
            for it in items:
                if it["task"] not in txt or it["due_date"] not in txt:
                    content_good = False
        all_present_ok = present and len(matched_actions) > 0
        content_ok = content_good and len(matched_actions) > 0

        unmatched_absent = True
        for name in unmatched_names:
            fp = volunteer_dir / f"{name}.txt"
            if fp.exists():
                unmatched_absent = False
                break
        unmatched_absent_ok = unmatched_absent

    if all_present_ok:
        scores["volunteer_emails_all_matched_present"] = 1.0
    if content_ok:
        scores["volunteer_emails_content_correct"] = 1.0
    if unmatched_absent_ok:
        scores["volunteer_emails_unmatched_absent"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()