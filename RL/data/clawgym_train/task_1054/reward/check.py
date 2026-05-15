import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_list(obj: Any) -> Optional[List[Any]]:
    if isinstance(obj, list):
        return obj
    return None


def _normalize_time_str(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:[AP]M)?\s*(?:ET)?\s*$", s, re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    return f"{hour:02d}:{minute:02d}"


def _extract_expected_from_inputs(workspace: Path) -> Dict[str, Any]:
    expected: Dict[str, Any] = {}

    # Agenda details
    agenda_md = workspace / "input" / "agenda.md"
    agenda_text = _read_text(agenda_md) or ""
    # Title
    title_match = re.search(r"^#\s+(.*)$", agenda_text, re.MULTILINE)
    expected["meeting_title"] = title_match.group(1).strip() if title_match else None
    # Date
    date_match = re.search(r"^Date:\s*(.*)$", agenda_text, re.MULTILINE)
    expected_date = None
    if date_match:
        date_str = date_match.group(1).strip()
        dm = re.search(r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})", date_str)
        if dm:
            months = {
                "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
            }
            mon = months.get(dm.group("month").lower())
            day = int(dm.group("day"))
            yr = int(dm.group("year"))
            if mon and day and yr:
                expected_date = f"{yr:04d}-{mon:02d}-{day:02d}"
    expected["meeting_date"] = expected_date
    # Time
    time_match = re.search(r"^Time:\s*([^\n]+)$", agenda_text, re.MULTILINE)
    start_time = None
    end_time = None
    if time_match:
        tline = time_match.group(1)
        parts = re.split(r"\s*[–-]\s*", tline)
        if len(parts) >= 2:
            st = parts[0].strip()
            et = parts[1].strip()
            st = re.sub(r"\s*ET\s*$", "", st, flags=re.IGNORECASE)
            et = re.sub(r"\s*ET\s*$", "", et, flags=re.IGNORECASE)

            def to_24h(ts: str) -> Optional[str]:
                m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AP]M)?\s*$", ts, re.IGNORECASE)
                if not m:
                    return None
                h = int(m.group(1))
                mi = int(m.group(2))
                ampm = m.group(3).upper() if m.group(3) else None
                if ampm == "PM" and h != 12:
                    h += 12
                if ampm == "AM" and h == 12:
                    h = 0
                return f"{h:02d}:{mi:02d}"

            start_time = to_24h(st) or _normalize_time_str(st)
            end_time = to_24h(et) or _normalize_time_str(et)
    expected["start_time"] = start_time
    expected["end_time"] = end_time

    # Agenda items expected
    expected_agenda = []
    for line in agenda_text.splitlines():
        m = re.match(r"^\s*\d+\.\s*(.+?)\s*\((\d+)\s*m\)\s*$", line, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            duration = int(m.group(2))
            expected_agenda.append({"title": title, "duration_minutes": duration})
    expected["agenda_items"] = expected_agenda

    # Attendees canonical names
    attendees_csv = workspace / "input" / "attendees.csv"
    attendees_text = _read_text(attendees_csv) or ""
    canonical_names: Dict[str, str] = {}
    for i, line in enumerate(attendees_text.splitlines()):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if i == 0:
            continue
        if len(parts) >= 1:
            name = parts[0]
            first = name.split()[0]
            canonical_names[first.lower()] = name
            canonical_names[name.lower()] = name
    expected["attendees_canonical"] = canonical_names

    # Expected attendees present (from notes/transcript)
    rn1 = _read_text(workspace / "input" / "raw_notes_1.md") or ""
    tr1 = _read_text(workspace / "input" / "transcript_excerpt.txt") or ""

    present_first_names: List[str] = []
    m1 = re.search(r"Attendees present:\s*([^\n]+)", rn1, re.IGNORECASE)
    if m1:
        names = re.split(r"\s*,\s*", m1.group(1).strip())
        present_first_names.extend([n.strip() for n in names if n.strip()])
    m2 = re.search(r"Rolling attendance:\s*([^\.\n]+)", tr1, re.IGNORECASE)
    if m2:
        names = re.split(r"\s*,\s*", m2.group(1).strip())
        for n in names:
            present_first_names.append(n.strip())
    present_first_names = list(dict.fromkeys(present_first_names))
    expected_attendees_full = []
    for fn in present_first_names:
        key = fn.lower()
        if key in canonical_names:
            expected_attendees_full.append(canonical_names[key])
    expected["expected_attendees_list"] = sorted(set(expected_attendees_full))

    # Expected guests
    guests = set()
    m3 = re.search(r"Guests:\s*([^\n]+)", rn1, re.IGNORECASE)
    if m3:
        gs = [g.strip() for g in re.split(r"\s*,\s*", m3.group(1).strip()) if g.strip()]
        for g in gs:
            if g:
                guests.add(g)
    if re.search(r"\bLily\b", tr1):
        guests.add("Lily")
    expected["expected_guests"] = guests

    # Projects mapping
    projects = _read_json(workspace / "input" / "projects.json") or {}
    projects_list = projects.get("projects", []) if isinstance(projects, dict) else []
    proj_by_id = {p.get("id"): p for p in projects_list if isinstance(p, dict)}
    proj_by_title = {p.get("title"): p for p in projects_list if isinstance(p, dict)}
    expected["projects_by_id"] = proj_by_id
    expected["projects_by_title"] = proj_by_title

    # Expected decisions: keywords for validation
    expected["decision_vendor_keywords"] = ["vendor b", "400"]
    expected["decision_reunion_keywords"] = ["asheville", "pavilion"]

    # Expected action items details
    expected["actions_expected"] = [
        {
            "owner": "Marcus Young",
            "due": "2026-03-20",
            "project_id": "P-001",
            "keywords": ["quote", "vendor b"],
        },
        {
            "owner": "Noah Perez",
            "due": "2026-03-25",
            "project_id": None,
            "keywords": ["budget", "400"],
        },
        {
            "owner": "Tessa Young",
            "due": "2026-03-18",
            "project_id": "P-002",
            "keywords": ["save-the-date", "email"],
        },
        {
            "owner": "Tessa Young",
            "due": "2026-03-21",
            "project_id": "P-002",
            "keywords": ["deposit", "pavilion"],
        },
        {
            "owner": "Daniel Cho",
            "due": "2026-03-22",
            "project_id": "P-003",
            "keywords": ["cemetery", "permits", "office"],
        },
    ]

    # Expected next meeting
    expected["next_meeting_date"] = "2026-04-07"
    expected["next_meeting_time"] = "18:00"

    # List of all input files expected to be parsed
    expected["input_files"] = [
        "input/agenda.md",
        "input/attendees.csv",
        "input/projects.json",
        "input/raw_notes_1.md",
        "input/chat_log.txt",
        "input/transcript_excerpt.txt",
    ]

    return expected


def _load_meeting_summary(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if isinstance(data, dict):
        return data
    return None


def _find_decision(decisions: List[Dict[str, Any]], keywords: List[str]) -> Optional[Dict[str, Any]]:
    for d in decisions:
        if not isinstance(d, dict):
            continue
        summary = str(d.get("summary", "")).lower()
        if all(k in summary for k in keywords):
            return d
    return None


def _find_action(actions: List[Dict[str, Any]], owner: str, due: str, project_id: Optional[str], keywords: List[str]) -> Optional[Dict[str, Any]]:
    for a in actions:
        if not isinstance(a, dict):
            continue
        own = a.get("owner")
        due_date = a.get("due_date")
        pid = a.get("project_id")
        task = str(a.get("task", "")).lower()
        if own == owner and due_date == due and pid == project_id:
            if all(k in task for k in keywords):
                return a
    return None


def _parse_minutes_sections(text: str) -> Dict[str, bool]:
    sections = {
        "title": False,
        "date_time": False,
        "attendees": False,
        "agenda": False,
        "decisions": False,
        "action_items": False,
        "next_meeting": False,
        "generated_line": False,
    }
    lower = text.lower()
    sections["title"] = "title" in lower
    sections["date_time"] = "date/time" in lower or ("date" in lower and "time" in lower)
    sections["attendees"] = "attendees" in lower
    sections["agenda"] = "agenda" in lower
    sections["decisions"] = "decisions" in lower
    sections["action_items"] = "action items" in lower or "action-items" in lower
    sections["next_meeting"] = "next meeting" in lower
    sections["generated_line"] = "generated by" in lower
    return sections


def _run_report_checks(text: str, expected_inputs: List[str]) -> Dict[str, float]:
    scores = {
        "run_report_command_scripts_path_valid": 0.0,
        "run_report_contains_inputs_and_counts": 0.0,
    }
    lower = text.lower()
    cmd_ok = False
    for line in text.splitlines():
        l = line.strip()
        if "python" in l and "scripts/" in l and l.endswith(".py"):
            cmd_ok = True
            break
    scores["run_report_command_scripts_path_valid"] = 1.0 if cmd_ok else 0.0

    inputs_ok = all(inp in text for inp in expected_inputs)
    decisions_count_present = bool(re.search(r"\bdecisions?\b.*\b\d+\b", lower))
    action_items_count_present = bool(re.search(r"\baction\s*items?\b.*\b\d+\b", lower))
    matched_unmatched_present = bool(re.search(r"\bmatched\b.*\b\d+\b", lower)) and bool(re.search(r"\bunmatched\b.*\b\d+\b", lower))
    warnings_present = "warning" in lower
    if inputs_ok and decisions_count_present and action_items_count_present and matched_unmatched_present and warnings_present:
        scores["run_report_contains_inputs_and_counts"] = 1.0
    else:
        scores["run_report_contains_inputs_and_counts"] = 0.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_present_meeting_summary": 0.0,
        "outputs_present_minutes_md": 0.0,
        "outputs_present_run_report": 0.0,
        "run_report_command_scripts_path_valid": 0.0,
        "meeting_title_correct": 0.0,
        "meeting_date_correct": 0.0,
        "meeting_times_correct": 0.0,
        "attendees_matched_correct": 0.0,
        "guests_identified_correct": 0.0,
        "agenda_parsed_correct": 0.0,
        "decisions_vendor_budget_extracted": 0.0,
        "decisions_reunion_extracted": 0.0,
        "action_item_marcus_quote": 0.0,
        "action_item_noah_budget": 0.0,
        "action_item_tessa_save_the_date": 0.0,
        "action_item_tessa_deposit": 0.0,
        "action_item_daniel_permits": 0.0,
        "next_meeting_correct": 0.0,
        "validation_counts_present_and_reasonable": 0.0,
        "minutes_sections_present": 0.0,
        "run_report_contains_inputs_and_counts": 0.0,
    }

    expected = _extract_expected_from_inputs(workspace)

    summary_path = workspace / "output" / "meeting_summary.json"
    minutes_path = workspace / "output" / "minutes.md"
    report_path = workspace / "output" / "run_report.txt"

    summary = _load_meeting_summary(summary_path) if summary_path.exists() else None
    minutes_text = _read_text(minutes_path) if minutes_path.exists() else None
    report_text = _read_text(report_path) if report_path.exists() else None

    if summary is not None:
        scores["outputs_present_meeting_summary"] = 1.0
    if minutes_text is not None:
        scores["outputs_present_minutes_md"] = 1.0
    if report_text is not None:
        scores["outputs_present_run_report"] = 1.0

    if report_text is not None:
        rr_scores = _run_report_checks(report_text, expected.get("input_files", []))
        scores.update(rr_scores)

    if summary is not None:
        if isinstance(summary.get("meeting_title"), str) and summary.get("meeting_title") == expected.get("meeting_title"):
            scores["meeting_title_correct"] = 1.0

        if isinstance(summary.get("meeting_date"), str) and summary.get("meeting_date") == expected.get("meeting_date"):
            scores["meeting_date_correct"] = 1.0

        st = summary.get("start_time")
        et = summary.get("end_time")
        stn = _normalize_time_str(st) if isinstance(st, str) else None
        etn = _normalize_time_str(et) if isinstance(et, str) else None
        if stn == expected.get("start_time") and etn == expected.get("end_time"):
            scores["meeting_times_correct"] = 1.0

        attendees = summary.get("attendees")
        guests = summary.get("guests")
        if isinstance(attendees, list):
            attendees_set = set([str(x) for x in attendees])
            expected_attendees_set = set(expected.get("expected_attendees_list", []))
            if attendees_set == expected_attendees_set and len(attendees) == len(expected_attendees_set):
                scores["attendees_matched_correct"] = 1.0
        if isinstance(guests, list):
            guests_lower = set([str(g).lower() for g in guests])
            ok_guest = ("aunt lily" in guests_lower) or ("lily" in guests_lower)
            if ok_guest and len(guests_lower) >= 1:
                scores["guests_identified_correct"] = 1.0

        agenda_list = summary.get("agenda")
        agenda_ok = False
        if isinstance(agenda_list, list):
            exp = expected.get("agenda_items", [])
            if len(agenda_list) == len(exp):
                all_match = True
                for got_item, exp_item in zip(agenda_list, exp):
                    if not isinstance(got_item, dict):
                        all_match = False
                        break
                    gt = str(got_item.get("title", "")).strip()
                    gd = got_item.get("duration_minutes")
                    if gt != exp_item.get("title") or gd != exp_item.get("duration_minutes"):
                        all_match = False
                        break
                if all_match:
                    agenda_ok = True
        scores["agenda_parsed_correct"] = 1.0 if agenda_ok else 0.0

        decisions = summary.get("decisions")
        if isinstance(decisions, list):
            vend = _find_decision(decisions, expected.get("decision_vendor_keywords", []))
            if isinstance(vend, dict):
                sources = vend.get("sources")
                if isinstance(sources, list) and all(isinstance(s, str) for s in sources):
                    ok_sources = 0
                    for s in sources:
                        if s in ["input/raw_notes_1.md", "input/chat_log.txt", "input/transcript_excerpt.txt"]:
                            ok_sources += 1
                    if ok_sources >= 2:
                        scores["decisions_vendor_budget_extracted"] = 1.0
            reun = _find_decision(decisions, expected.get("decision_reunion_keywords", []))
            if isinstance(reun, dict):
                sources = reun.get("sources")
                if isinstance(sources, list) and all(isinstance(s, str) for s in sources):
                    ok_sources = 0
                    for s in sources:
                        if s in ["input/raw_notes_1.md", "input/chat_log.txt"]:
                            ok_sources += 1
                    if ok_sources >= 2 or ("input/raw_notes_1.md" in sources and "input/chat_log.txt" in sources):
                        scores["decisions_reunion_extracted"] = 1.0

        actions = summary.get("action_items")
        if isinstance(actions, list):
            for action_expect in expected.get("actions_expected", []):
                found = _find_action(
                    actions,
                    owner=action_expect["owner"],
                    due=action_expect["due"],
                    project_id=action_expect["project_id"],
                    keywords=action_expect["keywords"],
                )
                key_map = {
                    "Marcus Young": "action_item_marcus_quote",
                    "Noah Perez": "action_item_noah_budget",
                    "Tessa Young|2026-03-18": "action_item_tessa_save_the_date",
                    "Tessa Young|2026-03-21": "action_item_tessa_deposit",
                    "Daniel Cho": "action_item_daniel_permits",
                }
                if action_expect["owner"] == "Tessa Young":
                    k = key_map.get(f"Tessa Young|{action_expect['due']}")
                else:
                    k = key_map.get(action_expect["owner"])
                if k:
                    if isinstance(found, dict) and isinstance(found.get("source"), str) and found.get("source").startswith("input/"):
                        scores[k] = 1.0
                    else:
                        scores[k] = 0.0

        next_meeting = summary.get("next_meeting")
        nm_ok = False
        if isinstance(next_meeting, dict):
            nd = next_meeting.get("date")
            nt = next_meeting.get("time")
            nd_ok = isinstance(nd, str) and nd == expected.get("next_meeting_date")
            nt_ok = isinstance(nt, str) and _normalize_time_str(nt) == expected.get("next_meeting_time")
            if nd_ok and nt_ok:
                nm_ok = True
        scores["next_meeting_correct"] = 1.0 if nm_ok else 0.0

        validation = summary.get("validation")
        val_ok = False
        if isinstance(validation, dict):
            td = validation.get("total_decisions")
            tai = validation.get("total_action_items")
            ma = validation.get("matched_attendees")
            ua = validation.get("unmatched_attendees_count")
            td_ok = isinstance(td, int) and td >= 2
            tai_ok = isinstance(tai, int) and tai >= 5
            if isinstance(ma, int):
                ma_ok = (ma == 6)
            elif isinstance(ma, list):
                ma_ok = (len(ma) == 6)
            else:
                ma_ok = False
            ua_ok = isinstance(ua, int) and ua >= 1
            if td_ok and tai_ok and ma_ok and ua_ok:
                val_ok = True
        scores["validation_counts_present_and_reasonable"] = 1.0 if val_ok else 0.0

    if minutes_text is not None:
        secs = _parse_minutes_sections(minutes_text)
        required = ["title", "date_time", "attendees", "agenda", "decisions", "action_items", "next_meeting", "generated_line"]
        if all(secs.get(k, False) for k in required):
            scores["minutes_sections_present"] = 1.0
        else:
            scores["minutes_sections_present"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()