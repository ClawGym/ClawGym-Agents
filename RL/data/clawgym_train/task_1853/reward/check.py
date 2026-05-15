import json
import csv
import re
import sys
from datetime import datetime
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_jsonl(path: Path):
    items = []
    if not path.exists():
        return items, False
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items, True
    except Exception:
        return [], False


def _read_csv_rows(path: Path):
    if not path.exists():
        return [], None, False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return [], None, False
            rows = list(reader)
        return rows, header, True
    except Exception:
        return [], None, False


def _parse_iso_to_epoch(dt_str: str):
    try:
        dt = datetime.fromisoformat(dt_str)
        # If naive, treat as local naive timestamp; still convert to epoch relative to 1970-01-01
        return dt.timestamp()
    except Exception:
        return float("-inf")


def _extract_details_and_actions(emails: list) -> dict:
    # Sort emails by date ascending using epoch, unparseable first
    parsed = []
    for e in emails:
        epoch = _parse_iso_to_epoch(e.get("date", ""))
        parsed.append((epoch, e))
    parsed.sort(key=lambda x: x[0])

    details = {
        "date": None,
        "time": None,
        "venue": None,
        "rsvp_deadline": None,
        "rsvp_email": None,
    }

    # Action items by owner
    items_by_owner = {}

    # Patterns for decisions
    re_date = re.compile(r'^\s*-\s*Date:\s*(.+)\s*$', re.IGNORECASE)
    re_time = re.compile(r'^\s*-\s*Time:\s*(.+)\s*$', re.IGNORECASE)
    re_venue = re.compile(r'^\s*-\s*Venue:\s*(.+)\s*$', re.IGNORECASE)
    re_rsvp_deadline = re.compile(r'^\s*-\s*RSVP\s+deadline:\s*(.+)\s*$', re.IGNORECASE)
    re_rsvp_email_line = re.compile(r'^\s*-\s*RSVP\s+email:\s*(.+)\s*$', re.IGNORECASE)
    re_rsvp_email_any = re.compile(
        r'RSVP\s+email[^:]*?\s*(?:should be|is|:)?\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})',
        re.IGNORECASE
    )

    # Action item line: "1) Owner — task (due X)"
    re_action_item = re.compile(
        r'^\s*\d+\)\s*([^—–-]+?)\s*[—–-]\s*(.*?)\s*\(due\s*([^)]+)\)\s*$',
        re.IGNORECASE
    )

    for _, e in parsed:
        body = e.get("body", "")
        lines = body.splitlines()

        # Extract decision details; later emails override earlier ones by simple reassignment
        for line in lines:
            m = re_date.match(line)
            if m:
                details["date"] = m.group(1).strip()
                continue
            m = re_time.match(line)
            if m:
                details["time"] = m.group(1).strip()
                continue
            m = re_venue.match(line)
            if m:
                details["venue"] = m.group(1).strip()
                continue
            m = re_rsvp_deadline.match(line)
            if m:
                details["rsvp_deadline"] = m.group(1).strip()
                continue
            m = re_rsvp_email_line.match(line)
            if m:
                val = m.group(1).strip()
                m2 = re_rsvp_email_any.search(line)
                if m2:
                    val = m2.group(1).strip()
                details["rsvp_email"] = val
                continue
            m = re_rsvp_email_any.search(line)
            if m:
                details["rsvp_email"] = m.group(1).strip()

        # Extract action items from enumerated lines
        for line in lines:
            mi = re_action_item.match(line)
            if mi:
                owner = mi.group(1).strip()
                task = mi.group(2).strip()
                due = mi.group(3).strip()
                if owner not in items_by_owner:
                    items_by_owner[owner] = {"owner": owner, "task": task, "due": due, "update": None}

        # Attach updates from later emails to existing items where applicable
        for line in lines:
            if re.match(r'^\s*-\s+', line):
                low = line.lower()
                if "field permit" in low:
                    for item in items_by_owner.values():
                        if "confirm field permit" in item.get("task", "").lower():
                            item["update"] = line.strip()

    action_items = [items_by_owner[k] for k in sorted(items_by_owner.keys())]
    return {"details": details, "action_items": action_items}


def _list_attachments(attachments_dir: Path):
    files = []
    if attachments_dir.exists():
        for p in attachments_dir.rglob("*"):
            if p.is_file():
                files.append(p)
    return files


def _compute_expected_manifest_entries(attachments_dir: Path, workspace: Path):
    files = _list_attachments(attachments_dir)
    entries = []
    for f in files:
        try:
            size = f.stat().st_size
        except Exception:
            size = None
        if size is None:
            continue
        rel = f.relative_to(workspace).as_posix()
        entries.append((rel, str(size)))
    entries.sort()
    return entries


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "invite_email_exists": 0.0,
        "invite_subject_line_correct": 0.0,
        "invite_placeholders_filled": 0.0,
        "invite_details_correct": 0.0,
        "invite_attachments_listed": 0.0,
        "invite_reunion_reference": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_decisions_complete": 0.0,
        "meeting_notes_action_items_complete": 0.0,
        "meeting_notes_updates_reflected": 0.0,
        "attachments_manifest_complete": 0.0,
        "recipient_list_complete": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"
    mailbox_path = input_dir / "mailbox.jsonl"
    roster_path = input_dir / "roster.csv"
    attachments_dir = input_dir / "attachments"

    invite_out = output_dir / "invite_email.md"
    notes_out = output_dir / "meeting_notes_and_action_items.md"
    manifest_out = output_dir / "attachments_manifest.csv"
    recipients_out = output_dir / "recipient_list.csv"

    # Load mailbox and extract details/actions
    mailbox_items, mailbox_ok = _load_jsonl(mailbox_path)
    extraction = _extract_details_and_actions(mailbox_items) if mailbox_ok else {"details": {}, "action_items": []}
    details = extraction.get("details", {}) if isinstance(extraction, dict) else {}
    action_items = extraction.get("action_items", []) if isinstance(extraction, dict) else []

    exp_date = details.get("date")
    exp_time = details.get("time")
    exp_venue = details.get("venue")
    exp_rsvp_deadline = details.get("rsvp_deadline")
    exp_rsvp_email = details.get("rsvp_email")

    # Grade invite_email.md
    if invite_out.exists():
        scores["invite_email_exists"] = 1.0
        content = _read_text(invite_out)
        lines = content.splitlines()

        # Subject line should start with "Subject:" and include the required phrase
        if lines:
            subj = lines[0].strip()
            if subj.lower().startswith("subject:") and ("Cal Bears Rugby 1986 Team — 40th Reunion Invite" in subj):
                scores["invite_subject_line_correct"] = 1.0

        # Placeholders filled: none of the placeholders should remain
        placeholders = ["[DATE]", "[TIME]", "[VENUE]", "[RSVP_DEADLINE]", "[RSVP_EMAIL]"]
        if not any(ph in content for ph in placeholders):
            scores["invite_placeholders_filled"] = 1.0

        # Details correctness: verify content matches latest mailbox decisions
        detail_checks = 0
        total_details = 5
        if mailbox_ok and isinstance(exp_date, str) and exp_date and (exp_date in content):
            detail_checks += 1
        if mailbox_ok and isinstance(exp_time, str) and exp_time and (exp_time in content):
            detail_checks += 1
        venue_ok = False
        if mailbox_ok and isinstance(exp_venue, str) and exp_venue:
            # Require both parts of the venues mentioned explicitly
            if "Witter Rugby Field" in content and "Faculty Club" in content:
                venue_ok = True
        if venue_ok:
            detail_checks += 1
        if mailbox_ok and isinstance(exp_rsvp_deadline, str) and exp_rsvp_deadline and (exp_rsvp_deadline in content):
            detail_checks += 1
        rsvp_ok = False
        if mailbox_ok and isinstance(exp_rsvp_email, str) and exp_rsvp_email and (exp_rsvp_email in content):
            # Ensure outdated alias isn't used if a newer one exists
            if "calrugby1986@list.example" not in content or exp_rsvp_email == "calrugby1986@list.example":
                rsvp_ok = True
        if rsvp_ok:
            detail_checks += 1
        if mailbox_ok and all([exp_date, exp_time, exp_venue, exp_rsvp_deadline, exp_rsvp_email]):
            scores["invite_details_correct"] = detail_checks / total_details
        else:
            scores["invite_details_correct"] = 0.0

        # Attachments section: each file name (file names only) present on its own line
        expected_files = [p.name for p in _list_attachments(attachments_dir)]
        line_set = set(l.strip() for l in lines)
        if expected_files:
            present = all(name in line_set for name in expected_files)
            scores["invite_attachments_listed"] = 1.0 if present else 0.0
        else:
            scores["invite_attachments_listed"] = 1.0

        # Reunion reference: mention "reunion" and "1986"
        if ("1986" in content) and (re.search(r'\breunion\b', content, re.IGNORECASE) is not None):
            scores["invite_reunion_reference"] = 1.0

    # Grade meeting_notes_and_action_items.md
    if notes_out.exists():
        scores["meeting_notes_exists"] = 1.0
        notes = _read_text(notes_out)

        # Decisions completeness
        dec_checks = 0
        dec_total = 5
        if mailbox_ok and isinstance(exp_date, str) and exp_date and (exp_date in notes):
            dec_checks += 1
        if mailbox_ok and isinstance(exp_time, str) and exp_time and (exp_time in notes):
            dec_checks += 1
        if "Witter Rugby Field" in notes and "Faculty Club" in notes:
            dec_checks += 1
        if mailbox_ok and isinstance(exp_rsvp_deadline, str) and exp_rsvp_deadline and (exp_rsvp_deadline in notes):
            dec_checks += 1
        if mailbox_ok and isinstance(exp_rsvp_email, str) and exp_rsvp_email and (exp_rsvp_email in notes):
            dec_checks += 1
        scores["meeting_notes_decisions_complete"] = (dec_checks / dec_total) if mailbox_ok else 0.0

        # Action items completeness
        if mailbox_ok and action_items:
            item_ok_count = 0
            for item in action_items:
                owner = (item.get("owner") or "").strip()
                task = (item.get("task") or "").strip()
                due = (item.get("due") or "").strip()
                cond_owner = owner in notes if owner else False
                cond_task = (re.search(re.escape(task), notes, re.IGNORECASE) is not None) if task else False
                cond_due = due in notes if due else False
                if cond_owner and cond_task and cond_due:
                    item_ok_count += 1
            scores["meeting_notes_action_items_complete"] = (item_ok_count / len(action_items)) if action_items else 0.0
        else:
            scores["meeting_notes_action_items_complete"] = 0.0

        # Updates reflected (e.g., field permit request submitted)
        update_present = bool(re.search(r'Field permit request submitted', notes, re.IGNORECASE))
        scores["meeting_notes_updates_reflected"] = 1.0 if update_present else 0.0

    # Grade attachments_manifest.csv
    expected_manifest = _compute_expected_manifest_entries(attachments_dir, workspace)
    if manifest_out.exists():
        try:
            with manifest_out.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                data_rows = rows[1:]
                header_ok = header == ["file_path", "size_bytes"]
                output_set = set(tuple(r) for r in data_rows if len(r) == 2)
                expected_set = set(expected_manifest)
                manifest_ok = header_ok and (output_set == expected_set)
                scores["attachments_manifest_complete"] = 1.0 if manifest_ok else 0.0
            else:
                scores["attachments_manifest_complete"] = 0.0
        except Exception:
            scores["attachments_manifest_complete"] = 0.0
    else:
        scores["attachments_manifest_complete"] = 0.0

    # Grade recipient_list.csv
    roster_rows, roster_header, roster_ok = _read_csv_rows(roster_path)
    if recipients_out.exists() and roster_ok:
        out_rows, out_header, out_ok = _read_csv_rows(recipients_out)
        if out_ok and out_header == ["name", "email", "status"]:
            expected = {}
            for r in roster_rows:
                name = (r.get("name") or "").strip()
                email = (r.get("email") or "").strip()
                status = "ok" if email != "" else "missing"
                expected[name] = (email, status)
            correct_count = 0
            seen_names = set()
            for r in out_rows:
                name = (r.get("name") or "").strip()
                email = (r.get("email") or "").strip()
                status = (r.get("status") or "").strip()
                if name in expected:
                    exp_email, exp_status = expected[name]
                    if email == exp_email and status == exp_status:
                        correct_count += 1
                    seen_names.add(name)
            count_ok = len(out_rows) == len(roster_rows)
            values_ok = (correct_count == len(roster_rows)) and (seen_names == set(expected.keys()))
            scores["recipient_list_complete"] = 1.0 if (count_ok and values_ok) else 0.0
        else:
            scores["recipient_list_complete"] = 0.0
    else:
        scores["recipient_list_complete"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()