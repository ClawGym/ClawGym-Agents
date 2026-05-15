import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _contains_all_tokens(text: str, tokens: List[str]) -> bool:
    t = _normalize_text(text)
    return all(tok in t for tok in tokens)


def _date_variants(d: date) -> Set[str]:
    # Generate several common textual variants for date matching
    months_full = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    months_abbr = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]
    res = set()
    res.add(d.strftime("%Y-%m-%d"))
    # D Month YYYY (full month)
    res.add(f"{d.day} {months_full[d.month - 1]} {d.year}")
    # D Mon YYYY (abbr month)
    res.add(f"{d.day} {months_abbr[d.month - 1]} {d.year}")
    # Month D, YYYY
    res.add(f"{months_full[d.month - 1]} {d.day}, {d.year}")
    # Mon D, YYYY
    res.add(f"{months_abbr[d.month - 1]} {d.day}, {d.year}")
    # Zero-padded day in Month forms too
    res.add(f"{d.day:02d} {months_full[d.month - 1]} {d.year}")
    res.add(f"{months_full[d.month - 1]} {d.day:02d}, {d.year}")
    return res


def _time_variants_1530_1700() -> Set[str]:
    # Accept either 24h "15:30–17:00" or 12h approximations
    # Include different dash variants
    variants = set()
    variants.update(["15:30–17:00", "15:30 - 17:00", "15:30—17:00", "15:30–17:00 (Bhutan Time)"])
    # 12-hour formats
    variants.update([
        "3:30 PM", "3:30pm", "3:30 p.m.", "3:30pm to 5:00pm", "3:30 PM to 5:00 PM",
        "3:30–5:00 PM", "3:30 - 5:00 PM", "3:30—5:00 PM"
    ])
    # Accept partial mentions: either both 15:30 and 17:00 or at least start time 3:30
    return variants


def _parse_club_notes(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    data: Dict[str, Any] = {
        "event": {},
        "deliverables": [],
        "offsets": {},
        "comms": {}
    }
    # Parse Event section (- Key: value)
    in_event = False
    in_deliverables = False
    in_offsets = False
    in_comms = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.strip().lower().startswith("event"):
            in_event = True
            in_deliverables = False
            in_offsets = False
            in_comms = False
            continue
        if line.strip().lower().startswith("required deliverables"):
            in_event = False
            in_deliverables = True
            in_offsets = False
            in_comms = False
            continue
        if line.strip().lower().startswith("timeline offsets"):
            in_event = False
            in_deliverables = False
            in_offsets = True
            in_comms = False
            continue
        if line.strip().lower().startswith("communications cadence"):
            in_event = False
            in_deliverables = False
            in_offsets = False
            in_comms = True
            continue
        # Reset on other major headers
        if re.match(r"^[A-Za-z].+$", line) and not line.startswith("-"):
            if any(line.strip().lower().startswith(h) for h in [
                "goals", "constraints & tone", "current status", "core team", "notes"
            ]):
                in_event = in_deliverables = in_offsets = in_comms = False

        if in_event and line.strip().startswith("-"):
            # format "- Key: value"
            m = re.match(r"^-\s*([^:]+):\s*(.+)$", line.strip())
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                k_norm = key.lower()
                if "title" in k_norm:
                    data["event"]["title"] = val
                elif k_norm == "date":
                    data["event"]["date"] = val
                elif k_norm == "time":
                    data["event"]["time"] = val
                elif k_norm == "venue":
                    data["event"]["venue"] = val
                elif "audience" in k_norm:
                    data["event"]["audience"] = val
                elif "contact email" in k_norm or "rsvp" in k_norm:
                    # "Contact email for queries/RSVP"
                    m2 = re.search(r"([A-Za-z0-9_.+\-]+@[A-Za-z0-9\-.]+\.[A-Za-z0-9\-]+)", val)
                    if m2:
                        data["event"]["rsvp_email"] = m2.group(1)
        elif in_deliverables and line.strip().startswith("-"):
            item = line.strip()[1:].strip()
            if item:
                data["deliverables"].append(item)
        elif in_offsets and line.strip().startswith("-"):
            # Parse offsets; may include combined entries with semicolons
            item = line.strip()[1:].strip()
            # Example patterns:
            # "Hall booking written confirmation: -20 days"
            # "Photo consent slips distributed: -10 days; returned by: -3 days"
            parts = [p.strip() for p in item.split(";") if p.strip()]
            base_prefix = ""
            # If the first part has a main label, use it
            for idx, part in enumerate(parts):
                # If part contains ":" then label: -N days or "returned by: -3 days"
                if ":" in part:
                    label, rest = [s.strip() for s in part.split(":", 1)]
                    if idx == 0 and "distributed" in _normalize_text(label):
                        base_prefix = re.sub(r"\s*distributed\s*$", "", label, flags=re.IGNORECASE).strip()
                    elif idx == 0 and "written confirmation" in _normalize_text(label):
                        base_prefix = re.sub(r"\s*written confirmation\s*$", "", label, flags=re.IGNORECASE).strip()
                    elif idx == 0 and "finalized" in _normalize_text(label):
                        base_prefix = re.sub(r"\s*finalized\s*$", "", label, flags=re.IGNORECASE).strip()
                    # extract number
                    mnum = re.search(r"(-?\d+)", rest)
                    if mnum:
                        days = int(mnum.group(1))
                        key = label
                        if base_prefix and label.lower() in ("distributed", "returned by"):
                            key = f"{base_prefix} {label}"
                        data["offsets"][_normalize_text(key)] = days
                else:
                    # Unexpected format, skip
                    pass
        elif in_comms:
            # Parse cadence line
            # "Send weekly progress updates every Friday to the Principal and the Parents’ Representative. Include: progress, upcoming tasks with dates, blockers, and requests."
            lower = line.strip().lower()
            if "weekly" in lower:
                data["comms"]["frequency"] = "weekly"
            if "friday" in lower:
                data["comms"]["day"] = "Friday"
            # recipients
            recips = []
            if "principal" in lower:
                recips.append("Principal")
            if "parents’ representative" in lower or "parents' representative" in lower or "parents representative" in lower:
                recips.append("Parents_Representative")
            if recips:
                data["comms"]["recipients_roles"] = recips
            if "include:" in lower:
                # extract after "Include:"
                after = line.split("Include:", 1)[1].strip() if "Include:" in line else line.split("include:", 1)[1].strip()
                includes = [i.strip().strip(".") for i in re.split(r",|and", after) if i.strip()]
                data["comms"]["includes"] = includes
    # Post process date parsing
    if "date" in data["event"]:
        try:
            ev_date = _parse_iso_date(data["event"]["date"])
            if ev_date:
                data["event"]["date_obj"] = ev_date
        except Exception:
            pass
    return data


def _stakeholder_emails(stakeholders_path: Path) -> Tuple[Set[str], Dict[str, str]]:
    rows = _load_csv(stakeholders_path)
    emails: Set[str] = set()
    role_to_email: Dict[str, str] = {}
    if rows is None:
        return emails, role_to_email
    for r in rows:
        email = (r.get("email") or "").strip()
        role = (r.get("role") or "").strip()
        if email:
            emails.add(email)
        if role and email:
            role_to_email[role] = email
    return emails, role_to_email


def _find_role_email(role_to_email: Dict[str, str], role_key: str) -> Optional[str]:
    # Exact match first
    if role_key in role_to_email:
        return role_to_email[role_key]
    # fuzzy contains
    rk = role_key.lower().replace("’", "'")
    for k, v in role_to_email.items():
        kk = k.lower().replace("’", "'")
        if rk in kk or kk in rk:
            return v
    return None


def _is_email(s: str) -> bool:
    return re.match(r"^[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-.]+\.[A-Za-z0-9\-]+$", s or "") is not None


def _extract_body_lines(email_text: str) -> List[str]:
    lines = [ln for ln in email_text.splitlines()]
    # Remove To and Subject
    filtered: List[str] = []
    for ln in lines:
        if ln.strip().lower().startswith("to:") or ln.strip().lower().startswith("subject:"):
            continue
        filtered.append(ln)
    # Remove leading/trailing blank lines
    while filtered and not filtered[0].strip():
        filtered.pop(0)
    while filtered and not filtered[-1].strip():
        filtered.pop()
    return filtered


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    club_notes_path = workspace / "input" / "club_notes.md"
    draft_announcement_path = workspace / "input" / "draft_announcement.txt"
    stakeholders_path = workspace / "input" / "stakeholders.csv"

    plan_path = workspace / "output" / "plan.json"
    status_path = workspace / "output" / "status_update_week0.md"
    announcement_path = workspace / "output" / "announcement_rewrite.txt"
    principal_email_path = workspace / "output" / "emails" / "principal_email.txt"
    parents_email_path = workspace / "output" / "emails" / "parents_email.txt"

    scores: Dict[str, float] = {
        "plan_exists_and_parseable": 0.0,
        "plan_event_matches_inputs": 0.0,
        "tasks_structure_and_emails_valid": 0.0,
        "tasks_dependencies_valid": 0.0,
        "tasks_due_dates_from_offsets": 0.0,
        "coverage_completeness_and_validity": 0.0,
        "comms_schedule_valid": 0.0,
        "announcement_exists_and_length": 0.0,
        "announcement_includes_required_details": 0.0,
        "announcement_tone_neutral": 0.0,
        "status_update_exists_and_length": 0.0,
        "status_update_includes_required_sections": 0.0,
        "status_update_references_plan_tasks": 0.0,
        "principal_email_format_and_recipient": 0.0,
        "principal_email_requests_approval_by_deadline": 0.0,
        "parents_email_format_and_recipient": 0.0,
        "parents_email_includes_rsvp_details": 0.0,
    }

    # Parse inputs
    notes = _parse_club_notes(club_notes_path)
    draft_announcement = _read_text(draft_announcement_path)
    stakeholder_rows = _load_csv(stakeholders_path)
    stakeholder_emails, role_to_email = _stakeholder_emails(stakeholders_path)

    # Derived event info from notes
    event_title = notes["event"]["title"] if notes and "event" in notes and "title" in notes["event"] else None
    event_date_str = notes["event"]["date"] if notes and "event" in notes and "date" in notes["event"] else None
    event_date_obj = notes["event"]["date_obj"] if notes and "event" in notes and "date_obj" in notes["event"] else None
    event_time = notes["event"]["time"] if notes and "event" in notes and "time" in notes["event"] else None
    event_venue = notes["event"]["venue"] if notes and "event" in notes and "venue" in notes["event"] else None
    event_audience = notes["event"]["audience"] if notes and "event" in notes and "audience" in notes["event"] else None
    event_rsvp_email = notes["event"]["rsvp_email"] if notes and "event" in notes and "rsvp_email" in notes["event"] else None
    required_deliverables = notes["deliverables"] if notes and "deliverables" in notes else []
    offsets = notes["offsets"] if notes and "offsets" in notes else {}

    # Load plan.json
    plan = _load_json(plan_path)
    if isinstance(plan, dict):
        scores["plan_exists_and_parseable"] = 1.0

    # Check plan event matches inputs
    if isinstance(plan, dict) and notes and event_title and event_date_obj and event_time and event_venue:
        pe = plan.get("event", {})
        try:
            cond = True
            cond = cond and isinstance(pe, dict)
            cond = cond and pe.get("title") == event_title
            cond = cond and pe.get("date") == event_date_str
            cond = cond and pe.get("time") == event_time
            cond = cond and pe.get("venue") == event_venue
            scores["plan_event_matches_inputs"] = 1.0 if cond else 0.0
        except Exception:
            scores["plan_event_matches_inputs"] = 0.0

    # Validate tasks structure and emails valid
    tasks = []
    if isinstance(plan, dict):
        tasks = plan.get("tasks", [])
    task_ids: Set[str] = set()
    owner_emails_ok = True
    structure_ok = True
    depends_ok = True
    if isinstance(tasks, list) and tasks:
        for t in tasks:
            if not isinstance(t, dict):
                structure_ok = False
                break
            # Required fields
            if not all(k in t for k in ["id", "name", "owner_email", "due_date", "depends_on", "deliverable_tag"]):
                structure_ok = False
            # id
            if not isinstance(t.get("id"), str) or not t["id"].strip():
                structure_ok = False
            else:
                task_ids.add(t["id"])
            # name
            if not isinstance(t.get("name"), str) or not t["name"].strip():
                structure_ok = False
            # owner_email
            if not isinstance(t.get("owner_email"), str) or not _is_email(t["owner_email"]):
                structure_ok = False
            elif t["owner_email"] not in stakeholder_emails:
                owner_emails_ok = False
            # due_date format
            if not isinstance(t.get("due_date"), str) or _parse_iso_date(t["due_date"]) is None:
                structure_ok = False
            # depends_on
            if not isinstance(t.get("depends_on"), list):
                structure_ok = False
            else:
                for dep in t["depends_on"]:
                    if not isinstance(dep, str):
                        depends_ok = False
            # deliverable_tag
            deliv = t.get("deliverable_tag")
            if deliv is None or isinstance(deliv, str):
                # if non-empty string, must be one of required deliverables
                if isinstance(deliv, str):
                    if deliv.strip() != "" and deliv not in required_deliverables:
                        structure_ok = False
            else:
                structure_ok = False
    else:
        structure_ok = False
        owner_emails_ok = False
        depends_ok = False

    if structure_ok and owner_emails_ok:
        scores["tasks_structure_and_emails_valid"] = 1.0
    else:
        scores["tasks_structure_and_emails_valid"] = 0.0

    # Validate dependencies reference existing ids
    if structure_ok and isinstance(tasks, list):
        all_deps_exist = True
        for t in tasks:
            for dep in t.get("depends_on", []):
                if dep not in task_ids:
                    all_deps_exist = False
                    break
            if not all_deps_exist:
                break
        scores["tasks_dependencies_valid"] = 1.0 if (depends_ok and all_deps_exist) else 0.0

    # Validate coverage completeness and validity
    coverage_ok = False
    if isinstance(plan, dict) and isinstance(plan.get("coverage"), list) and required_deliverables:
        cov = plan.get("coverage")
        # Build mapping deliverable -> set of task ids
        cov_map: Dict[str, Set[str]] = {}
        valid_structure = True
        for entry in cov:
            if not isinstance(entry, dict):
                valid_structure = False
                break
            # Accept keys: deliverable and task_ids OR task_id
            deliverable = entry.get("deliverable")
            if not isinstance(deliverable, str):
                valid_structure = False
                break
            tids: Set[str] = set()
            if "task_ids" in entry:
                if isinstance(entry["task_ids"], list) and all(isinstance(x, str) for x in entry["task_ids"]):
                    tids.update(entry["task_ids"])
                else:
                    valid_structure = False
            elif "task_id" in entry:
                if isinstance(entry["task_id"], str):
                    tids.add(entry["task_id"])
                else:
                    valid_structure = False
            else:
                valid_structure = False
            if not valid_structure:
                break
            cov_map.setdefault(deliverable, set()).update(tids)
        if valid_structure:
            # All required deliverables must be covered by at least one existing task id whose deliverable_tag matches
            missing = []
            mismatch = False
            for dname in required_deliverables:
                tids = cov_map.get(dname, set())
                if not tids:
                    missing.append(dname)
                    continue
                # Validate task ids exist and their deliverable_tag matches dname
                ok_any = False
                for tid in tids:
                    tmatch = next((t for t in tasks if isinstance(t, dict) and t.get("id") == tid), None)
                    if tmatch and tmatch.get("deliverable_tag") == dname:
                        ok_any = True
                if not ok_any:
                    mismatch = True
            if not missing and not mismatch:
                coverage_ok = True
    scores["coverage_completeness_and_validity"] = 1.0 if coverage_ok else 0.0

    # Validate comms_schedule
    comms_ok = False
    if isinstance(plan, dict) and isinstance(plan.get("comms_schedule"), dict):
        cs = plan["comms_schedule"]
        freq = str(cs.get("frequency", "")).strip().lower()
        day = str(cs.get("day", "")).strip().lower()
        recips = cs.get("recipients", [])
        includes = cs.get("includes", [])
        if isinstance(recips, list):
            recips_l = [str(r).strip().lower() for r in recips if isinstance(r, str)]
        else:
            recips_l = [str(recips).strip().lower()]
        if isinstance(includes, list):
            incl_text = " ".join([str(i) for i in includes])
        else:
            incl_text = str(includes)
        incl_lower = incl_text.lower()
        # Recipient emails from stakeholders
        principal_email = _find_role_email(role_to_email, "Principal")
        parents_email = _find_role_email(role_to_email, "Parents_Representative")
        recipients_ok = False
        if principal_email and parents_email:
            recipients_ok = principal_email.lower() in recips_l and parents_email.lower() in recips_l
        includes_ok = all(x in incl_lower for x in ["progress", "upcoming", "blocker", "request"]) and ("date" in incl_lower or "dates" in incl_lower)
        if freq == "weekly" and day in ("friday", "fri") and recipients_ok and includes_ok:
            comms_ok = True
    scores["comms_schedule_valid"] = 1.0 if comms_ok else 0.0

    # Validate due dates for specific offset-tied tasks
    due_dates_ok = False
    if structure_ok and event_date_obj and isinstance(tasks, list) and offsets:
        # Build expected checks: key -> (tokens, offset days)
        expected_checks = [
            (["hall", "booking", "confirmation"], offsets.get(_normalize_text("Hall booking written confirmation"))),
            (["principal", "briefing", "approval"], offsets.get(_normalize_text("Principal briefing and approval"))),
            (["poster", "final"], offsets.get(_normalize_text("Poster finalized"))),
            (["parent", "invitation"], offsets.get(_normalize_text("Parent invitations sent"))),
            (["consent", "slip", "distribut"], offsets.get(_normalize_text("Photo consent slips distributed"))),
            (["consent", "slip", "return"], offsets.get(_normalize_text("Photo consent slips returned by"))),
            (["volunteer", "training"], offsets.get(_normalize_text("Volunteer training"))),
            (["moderator", "guide", "final"], offsets.get(_normalize_text("Moderator guide finalized"))),
            (["printing"], offsets.get(_normalize_text("Materials printing"))),
            (["rsvp", "deadline"], offsets.get(_normalize_text("RSVP deadline"))),
            (["feedback", "form", "ready"], offsets.get(_normalize_text("Feedback form ready"))),
        ]
        all_found_correct = True
        for tokens, off in expected_checks:
            if off is None:
                all_found_correct = False
                break
            # find matching task(s)
            matched = [t for t in tasks if isinstance(t, dict) and isinstance(t.get("name"), str) and _contains_all_tokens(t["name"], tokens)]
            if not matched:
                all_found_correct = False
                break
            # at least one matched task must have correct due date
            expected_date = event_date_obj + timedelta(days=off)
            expected_str = expected_date.strftime("%Y-%m-%d")
            if not any(t.get("due_date") == expected_str for t in matched):
                all_found_correct = False
                break
        due_dates_ok = all_found_correct
    scores["tasks_due_dates_from_offsets"] = 1.0 if due_dates_ok else 0.0

    # Announcement checks
    ann_text = _read_text(announcement_path)
    if isinstance(ann_text, str):
        words = re.findall(r"\b\w+\b", ann_text)
        if 90 <= len(words) <= 120:
            scores["announcement_exists_and_length"] = 1.0

    # Required details in announcement
    if isinstance(ann_text, str) and notes and event_title and event_date_obj and event_venue and event_audience and event_rsvp_email:
        details_ok = True
        text_low = ann_text.lower()
        # Title exact phrase
        details_ok = details_ok and (event_title.lower() in text_low)
        # Date: accept several variants
        date_ok = any(variant.lower() in text_low for variant in _date_variants(event_date_obj))
        details_ok = details_ok and date_ok
        # Time: accept variants
        time_variants = _time_variants_1530_1700()
        time_ok = any(v.lower() in text_low for v in time_variants) or ("15:30" in text_low) or ("3:30" in text_low)
        details_ok = details_ok and time_ok
        # Venue exact phrase
        details_ok = details_ok and (event_venue.lower() in text_low)
        # Audience: must mention students and parents
        aud_ok = ("students" in text_low and "parent" in text_low)
        details_ok = details_ok and aud_ok
        # RSVP email
        details_ok = details_ok and (event_rsvp_email.lower() in text_low)
        # RSVP deadline: compute event_date - 5 days from offsets
        rsvp_off = offsets.get(_normalize_text("RSVP deadline"), -5)
        rsvp_deadline = event_date_obj + timedelta(days=rsvp_off)
        rsvp_ok = any(variant.lower() in text_low for variant in _date_variants(rsvp_deadline))
        details_ok = details_ok and rsvp_ok
        scores["announcement_includes_required_details"] = 1.0 if details_ok else 0.0

        # Tone neutral: no partisan/advocacy phrases
        banned = [
            "political", "party", "endorse", "take a stand", "call on everyone",
            "mobilize", "reform", "awaken", "shape the system", "slogans", "campaign"
        ]
        tone_ok = not any(b in text_low for b in banned)
        scores["announcement_tone_neutral"] = 1.0 if tone_ok else 0.0

    # Status update checks
    status_text = _read_text(status_path)
    if isinstance(status_text, str):
        w = re.findall(r"\b\w+\b", status_text)
        if 150 <= len(w) <= 250:
            scores["status_update_exists_and_length"] = 1.0
        # Includes required sections
        st_low = status_text.lower()
        includes_sections = ("progress" in st_low) and (("blocker" in st_low) or ("risk" in st_low)) and (("ask" in st_low) or ("request" in st_low)) and ("next" in st_low)
        # specific asks for principal and parents’ representative
        roles_ok = ("principal" in st_low) and (("parents’ representative" in st_low) or ("parents' representative" in st_low) or ("pta" in st_low))
        scores["status_update_includes_required_sections"] = 1.0 if (includes_sections and roles_ok) else 0.0
        # references plan tasks by name
        task_names = [t.get("name") for t in tasks if isinstance(t, dict) and isinstance(t.get("name"), str)]
        ref_ok = False
        if task_names:
            for nm in task_names:
                if nm and nm.lower() in st_low:
                    ref_ok = True
                    break
        scores["status_update_references_plan_tasks"] = 1.0 if ref_ok else 0.0

    # Principal email checks
    principal_email_txt = _read_text(principal_email_path)
    principal_email = _find_role_email(role_to_email, "Principal")
    parents_email = _find_role_email(role_to_email, "Parents_Representative")
    # Compute principal approval deadline based on -12 days
    principal_deadline_date: Optional[date] = None
    if event_date_obj is not None:
        off_principal = offsets.get(_normalize_text("Principal briefing and approval"), -12)
        principal_deadline_date = event_date_obj + timedelta(days=off_principal)

    if isinstance(principal_email_txt, str) and principal_email:
        lines = principal_email_txt.splitlines()
        to_line = next((ln for ln in lines if ln.strip().lower().startswith("to:")), "")
        subject_line = next((ln for ln in lines if ln.strip().lower().startswith("subject:")), "")
        to_ok = principal_email in to_line
        subject_ok = len(subject_line.strip()) > len("subject:")
        body_lines = _extract_body_lines(principal_email_txt)
        # 4-6 non-empty lines
        non_empty_body = [ln for ln in body_lines if ln.strip()]
        lines_ok = 4 <= len(non_empty_body) <= 6
        header_ok = to_ok and subject_ok
        scores["principal_email_format_and_recipient"] = 1.0 if (header_ok and lines_ok) else 0.0

        # Must request approval by deadline and mention attached plan.json
        body_low = principal_email_txt.lower()
        date_ok = False
        if principal_deadline_date:
            variants = _date_variants(principal_deadline_date)
            date_ok = any(v.lower() in body_low for v in variants)
        attach_ok = "plan.json" in body_low
        approval_phrase = ("approval" in body_low or "approve" in body_low)
        scores["principal_email_requests_approval_by_deadline"] = 1.0 if (date_ok and attach_ok and approval_phrase) else 0.0

    # Parents email checks
    parents_email_txt = _read_text(parents_email_path)
    # Compute RSVP deadline from offsets -5
    rsvp_deadline_date: Optional[date] = None
    if event_date_obj is not None:
        off_rsvp = offsets.get(_normalize_text("RSVP deadline"), -5)
        rsvp_deadline_date = event_date_obj + timedelta(days=off_rsvp)

    if isinstance(parents_email_txt, str) and parents_email and event_rsvp_email:
        lines = parents_email_txt.splitlines()
        to_line = next((ln for ln in lines if ln.strip().lower().startswith("to:")), "")
        subject_line = next((ln for ln in lines if ln.strip().lower().startswith("subject:")), "")
        to_ok = parents_email in to_line
        subject_ok = len(subject_line.strip()) > len("subject:")
        header_ok = to_ok and subject_ok
        scores["parents_email_format_and_recipient"] = 1.0 if header_ok else 0.0

        body_low = parents_email_txt.lower()
        invite_ok = ("invite" in body_low or "welcome" in body_low or "join" in body_low) and ("forum" in body_low)
        email_ok = event_rsvp_email.lower() in body_low
        date_ok = False
        if rsvp_deadline_date:
            variants = _date_variants(rsvp_deadline_date)
            date_ok = any(v.lower() in body_low for v in variants)
        tone_ok = not any(b in body_low for b in ["political", "party", "endorse", "mobilize", "take a stand"])
        scores["parents_email_includes_rsvp_details"] = 1.0 if (invite_ok and email_ok and date_ok and tone_ok) else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()