import sys
import json
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def find_section_indices(lines: List[str], headers: List[str]) -> Dict[str, int]:
    indices = {}
    lower_lines = [line.strip().lower() for line in lines]
    for header in headers:
        idx = -1
        for i, ll in enumerate(lower_lines):
            if ll == header.lower() or ll.startswith(header.lower() + ":"):
                idx = i
                break
        indices[header] = idx
    return indices


def parse_agenda_titles(content: str) -> List[str]:
    titles = []
    for line in content.splitlines():
        m = re.match(r"^\s*\d+\.\s*(.+)\s*$", line)
        if m:
            titles.append(m.group(1).strip())
    return titles


def parse_notes(content: str) -> Dict:
    data = {
        "date": None,
        "time": None,
        "attendees": [],
        "apologies": [],
        "decisions": [],
        "actions": [],
        "unresolved": [],
        "next_meeting": {"date": None, "time": None},
    }
    lines = content.splitlines()
    # Date
    for line in lines:
        m = re.match(r"^\s*Date:\s*(.+)$", line)
        if m:
            data["date"] = m.group(1).strip()
            break
    # Time
    for line in lines:
        m = re.match(r"^\s*Time:\s*(.+)$", line)
        if m:
            data["time"] = m.group(1).strip()
            break
    # Attendees
    for line in lines:
        m = re.match(r"^\s*Attendees\s*\(present\):\s*(.+)$", line)
        if m:
            attendees_raw = m.group(1).strip()
            parts = [p.strip() for p in attendees_raw.split(",")]
            clean = []
            for p in parts:
                p = re.sub(r"\s*\((chair|remote)\)\s*$", "", p, flags=re.IGNORECASE)
                clean.append(p.strip())
            data["attendees"] = [c for c in clean if c]
            break
    # Apologies
    for line in lines:
        m = re.match(r"^\s*Apologies:\s*(.+)$", line)
        if m:
            apologies_raw = m.group(1).strip()
            parts = [p.strip() for p in apologies_raw.split(",")]
            clean = []
            for p in parts:
                p = re.sub(r"\s*\(.*?\)\s*$", "", p)
                clean.append(p.strip())
            data["apologies"] = [c for c in clean if c]
            break
    # Decisions
    for line in lines:
        m = re.match(r"^\s*DECISION:\s*(.+)$", line)
        if m:
            data["decisions"].append(m.group(1).strip())
    # Actions
    for line in lines:
        m = re.match(r"^\s*ACTION:\s*(.+)$", line)
        if m:
            act_text = m.group(1).strip()
            m2 = re.match(r"^(?P<assignee>.+?)\s+to\s+(?P<task>.+?)\s+by\s+(?P<due>\d{4}-\d{2}-\d{2})(?:\.|$)", act_text)
            if m2:
                data["actions"].append({
                    "assignee": m2.group("assignee").strip(),
                    "task": m2.group("task").strip(),
                    "due": m2.group("due").strip(),
                    "raw": act_text
                })
            else:
                data["actions"].append({
                    "assignee": "",
                    "task": "",
                    "due": "",
                    "raw": act_text
                })
    # Unresolved (lines containing "??")
    for line in lines:
        if "??" in line:
            idx = line.find("??")
            unresolved_text = line[idx+2:].strip() if idx >= 0 else line.strip()
            data["unresolved"].append(unresolved_text if unresolved_text else line.strip())
    # Next meeting from decisions
    nm_date = None
    nm_time = None
    for dec in data["decisions"]:
        m = re.search(r"Next meeting on\s+(\d{4}-\d{2}-\d{2})", dec, flags=re.IGNORECASE)
        if m:
            nm_date = m.group(1)
        m2 = re.search(r"at\s+([0-2]?\d:[0-5]\d)", dec, flags=re.IGNORECASE)
        if m2:
            nm_time = m2.group(1)
    if nm_date:
        data["next_meeting"]["date"] = nm_date
    if nm_time:
        data["next_meeting"]["time"] = nm_time
    return data


def actions_to_triples(actions: List[Dict]) -> List[Tuple[str, str, str]]:
    triples = []
    for a in actions:
        triples.append((normalize_whitespace(a.get("assignee", "")),
                        normalize_whitespace(a.get("task", "")),
                        a.get("due", "").strip()))
    return triples


def parse_summary_sections(content: str) -> Dict[str, Tuple[int, int]]:
    lines = content.splitlines()
    headers = ["Key decisions", "Action items", "Next meeting"]
    idxs = find_section_indices(lines, headers)
    sections = {}
    if idxs["Key decisions"] != -1 and idxs["Action items"] != -1:
        sections["Key decisions"] = (idxs["Key decisions"], idxs["Action items"])
    if idxs["Action items"] != -1 and idxs["Next meeting"] != -1:
        sections["Action items"] = (idxs["Action items"], idxs["Next meeting"])
    if idxs["Next meeting"] != -1:
        sections["Next meeting"] = (idxs["Next meeting"], len(lines))
    return sections


def extract_section_lines(content: str, start: int, end: int) -> List[str]:
    lines = content.splitlines()
    return [line for line in lines[start+1:end]]


def parse_summary_actions(content: str) -> List[Tuple[str, str, str]]:
    sections = parse_summary_sections(content)
    triples: List[Tuple[str, str, str]] = []
    if "Action items" not in sections:
        return triples
    start, end = sections["Action items"]
    lines = extract_section_lines(content, start, end)
    for line in lines:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("—")]
        if len(parts) == 3:
            assignee, task, due = parts
            m = re.search(r"(\d{4}-\d{2}-\d{2})$", due)
            if m:
                date = m.group(1)
                triples.append((normalize_whitespace(assignee), normalize_whitespace(task), date))
    return triples


def contains_all_substrings(text: str, substrs: List[str], case_insensitive: bool = True) -> bool:
    t = text.lower() if case_insensitive else text
    for s in substrs:
        if case_insensitive:
            if s.lower() not in t:
                return False
        else:
            if s not in t:
                return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "minutes_exists_and_metadata": 0.0,
        "minutes_attendees_and_apologies_exact": 0.0,
        "minutes_agenda_sections": 0.0,
        "minutes_decisions_captured": 0.0,
        "minutes_actions_captured": 0.0,
        "minutes_unresolved_section": 0.0,
        "summary_sections_order": 0.0,
        "summary_decisions_covered": 0.0,
        "summary_actions_exact_match": 0.0,
        "summary_next_meeting": 0.0,
        "email_structure_and_references": 0.0,
        "email_overview_focus_areas": 0.0,
        "email_actions_match_summary": 0.0,
        "email_next_meeting_and_corrections": 0.0,
    }

    # Load inputs
    agenda_path = workspace / "input" / "agenda.md"
    notes_path = workspace / "input" / "notes_raw.txt"
    draft_minutes_path = workspace / "input" / "draft_minutes.md"

    agenda_content = read_text_file(agenda_path)
    notes_content = read_text_file(notes_path)
    _ = read_text_file(draft_minutes_path)

    if not agenda_content or not notes_content:
        return scores

    agenda_titles = parse_agenda_titles(agenda_content)
    notes_data = parse_notes(notes_content)
    expected_date = notes_data.get("date")
    expected_time = notes_data.get("time")
    expected_attendees = notes_data.get("attendees", [])
    expected_apologies = notes_data.get("apologies", [])
    expected_decisions = notes_data.get("decisions", [])
    expected_actions = actions_to_triples(notes_data.get("actions", []))
    unresolved_items = notes_data.get("unresolved", [])
    nm = notes_data.get("next_meeting", {})
    next_meeting_date = nm.get("date")
    next_meeting_time = nm.get("time")

    # Load outputs
    minutes_path = workspace / "output" / "meeting_minutes_2024-10-18.md"
    summary_path = workspace / "output" / "executive_summary_2024-10-18.txt"
    email_path = workspace / "output" / "email_to_collective_2024-10-18.txt"

    minutes_content = read_text_file(minutes_path)
    summary_content = read_text_file(summary_path)
    email_content = read_text_file(email_path)

    # minutes_exists_and_metadata
    if minutes_content:
        cond_date = expected_date is not None and (f"Date: {expected_date}" in minutes_content or f"Date {expected_date}" in minutes_content)
        time_ok = False
        if expected_time:
            times = re.findall(r"(\d{1,2}:\d{2})", expected_time)
            if len(times) >= 2:
                start, end = times[0], times[-1]
                if start in minutes_content and end in minutes_content:
                    time_ok = True
            else:
                time_ok = expected_time in minutes_content
        if cond_date and time_ok:
            scores["minutes_exists_and_metadata"] = 1.0

    # minutes_attendees_and_apologies_exact
    if minutes_content:
        attendees_ok = True
        for name in expected_attendees:
            if name not in minutes_content:
                attendees_ok = False
                break
        apologies_ok = (len(expected_apologies) == 0)
        if expected_apologies:
            apologies_ok = False
            lines = minutes_content.splitlines()
            ap_idx = -1
            for i, line in enumerate(lines):
                if line.strip().lower().startswith("apologies"):
                    ap_idx = i
                    break
            if ap_idx != -1:
                segment = "\n".join(lines[ap_idx: ap_idx + 10])
                apologies_ok = all(name in segment for name in expected_apologies)
        if attendees_ok and apologies_ok:
            scores["minutes_attendees_and_apologies_exact"] = 1.0

    # minutes_agenda_sections
    if minutes_content and agenda_titles:
        all_titles_present = all(title in minutes_content for title in agenda_titles)
        scores["minutes_agenda_sections"] = 1.0 if all_titles_present else 0.0

    # minutes_decisions_captured
    if minutes_content and expected_decisions:
        decisions_ok = True
        for dec in expected_decisions:
            if normalize_whitespace(dec).lower() not in normalize_whitespace(minutes_content).lower():
                decisions_ok = False
                break
        scores["minutes_decisions_captured"] = 1.0 if decisions_ok else 0.0

    # minutes_actions_captured
    if minutes_content and expected_actions:
        actions_ok = True
        norm_minutes = normalize_whitespace(minutes_content).lower()
        for assignee, task, due in expected_actions:
            if (assignee.lower() not in norm_minutes) or (due.lower() not in norm_minutes) or (normalize_whitespace(task).lower() not in norm_minutes):
                actions_ok = False
                break
        scores["minutes_actions_captured"] = 1.0 if actions_ok else 0.0

    # minutes_unresolved_section
    if minutes_content and unresolved_items:
        has_heading = ("open questions" in minutes_content.lower()) or ("unresolved" in minutes_content.lower())
        unresolved_ok = has_heading
        if unresolved_ok:
            unresolved_text_lc = minutes_content.lower()
            guild_ok = ("guild" in unresolved_text_lc and "1690" in unresolved_text_lc and "1695" in unresolved_text_lc)
            mary_ok = ("mary" in unresolved_text_lc and "marie" in unresolved_text_lc and "folio 47" in unresolved_text_lc)
            unresolved_ok = guild_ok and mary_ok
        scores["minutes_unresolved_section"] = 1.0 if unresolved_ok else 0.0

    # summary_sections_order
    if summary_content:
        lines = summary_content.splitlines()
        idxs = find_section_indices(lines, ["Key decisions", "Action items", "Next meeting"])
        if all(idxs[h] != -1 for h in ["Key decisions", "Action items", "Next meeting"]):
            in_order = idxs["Key decisions"] < idxs["Action items"] < idxs["Next meeting"]
            scores["summary_sections_order"] = 1.0 if in_order else 0.0

    # summary_decisions_covered
    if summary_content and expected_decisions:
        sections = parse_summary_sections(summary_content)
        if "Key decisions" in sections:
            start, end = sections["Key decisions"]
            dec_section_text = "\n".join(extract_section_lines(summary_content, start, end))
            all_decisions_present = True
            for dec in expected_decisions:
                if normalize_whitespace(dec).lower() not in normalize_whitespace(dec_section_text).lower():
                    all_decisions_present = False
                    break
            scores["summary_decisions_covered"] = 1.0 if all_decisions_present else 0.0

    # summary_actions_exact_match
    if summary_content and expected_actions:
        summary_triples = parse_summary_actions(summary_content)
        formatting_ok = len(summary_triples) == len(expected_actions)
        set_expected = set((a.lower(), b.lower(), c) for (a, b, c) in expected_actions)
        set_summary = set((a.lower(), b.lower(), c) for (a, b, c) in summary_triples)
        match_ok = set_expected == set_summary and formatting_ok
        scores["summary_actions_exact_match"] = 1.0 if match_ok else 0.0

    # summary_next_meeting
    if summary_content and next_meeting_date and next_meeting_time:
        sections = parse_summary_sections(summary_content)
        next_ok = False
        if "Next meeting" in sections:
            start, end = sections["Next meeting"]
            nm_text = "\n".join(extract_section_lines(summary_content, start, end))
            next_ok = (next_meeting_date in nm_text) and (next_meeting_time in nm_text)
        scores["summary_next_meeting"] = 1.0 if next_ok else 0.0

    # email_structure_and_references
    if email_content:
        lines = email_content.splitlines()
        subject_ok = any(line.strip().lower().startswith("subject:") for line in lines)
        refs_ok = ("output/meeting_minutes_2024-10-18.md" in email_content and
                   "output/executive_summary_2024-10-18.txt" in email_content)
        scores["email_structure_and_references"] = 1.0 if (subject_ok and refs_ok) else 0.0

    # email_overview_focus_areas
    if email_content:
        lc = email_content.lower()
        focus_hits = 0
        if "norwich" in lc and "account" in lc:
            focus_hits += 1
        if "widow" in lc and "petition" in lc:
            focus_hits += 1
        if "bodleian" in lc or "midwife" in lc:
            focus_hits += 1
        if "cavendish" in lc or "sociable letters" in lc:
            focus_hits += 1
        scores["email_overview_focus_areas"] = 1.0 if focus_hits >= 3 else 0.0

    # email_actions_match_summary
    if email_content and summary_content:
        summary_triples = parse_summary_actions(summary_content)
        email_action_triples = []
        for line in email_content.splitlines():
            if "—" in line:
                parts = [p.strip() for p in line.split("—")]
                if len(parts) == 3:
                    assignee, task, due = parts
                    m = re.search(r"(\d{4}-\d{2}-\d{2})$", due)
                    if m:
                        email_action_triples.append((normalize_whitespace(assignee), normalize_whitespace(task), m.group(1)))
        set_email = set((a.lower(), b.lower(), c) for (a, b, c) in email_action_triples)
        set_summary = set((a.lower(), b.lower(), c) for (a, b, c) in summary_triples)
        scores["email_actions_match_summary"] = 1.0 if (set_email == set_summary and len(set_email) == len(set_summary) and len(set_summary) > 0) else 0.0

    # email_next_meeting_and_corrections
    if email_content and next_meeting_date and next_meeting_time:
        lc = email_content.lower()
        nm_ok = (next_meeting_date in email_content and next_meeting_time in email_content)
        corrections_ok = ("correction" in lc) or ("let me know" in lc and "correct" in lc)
        scores["email_next_meeting_and_corrections"] = 1.0 if (nm_ok and corrections_ok) else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()