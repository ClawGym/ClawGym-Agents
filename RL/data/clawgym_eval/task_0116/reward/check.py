import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_roster(roster_path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    rows = _read_csv_dicts(roster_path)
    if rows is None:
        return None
    roster = {}
    for r in rows:
        name = r.get("name")
        email = r.get("email")
        role = r.get("role")
        if name is None or email is None or role is None:
            return None
        roster[name] = {"email": email, "role": role}
    return roster


def _parse_agenda(agenda_lines: List[str]) -> Dict[str, Any]:
    # Extract meeting name (from first line starting with "# ")
    meeting_name = None
    date_str = None
    # Extract "Agenda" bullet lines
    agenda_bullets: List[str] = []
    in_agenda = False
    action_items: List[Dict[str, str]] = []
    action_re = re.compile(
        r'\[ACTION\]\s*(.*?)\s*\(assignee:\s*([^;]+);\s*due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\)',
        re.IGNORECASE,
    )
    for line in agenda_lines:
        if meeting_name is None and line.lstrip().startswith("# "):
            meeting_name = line.lstrip()[2:].strip()
        if date_str is None:
            m = re.match(r'\s*Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$', line)
            if m:
                date_str = m.group(1)
        if not in_agenda and line.strip() == "Agenda":
            in_agenda = True
            continue
        if in_agenda:
            # Collect all agenda bullet lines as-is (preserve indentation)
            if line.startswith("- ") or line.startswith("  - "):
                agenda_bullets.append(line.rstrip())
                # Parse ACTION items
                if "[ACTION]" in line:
                    m2 = action_re.search(line)
                    if m2:
                        task = m2.group(1).strip()
                        assignee = m2.group(2).strip()
                        due = m2.group(3).strip()
                        action_items.append(
                            {"task": task, "assignee": assignee, "due_date": due, "source": "agenda",
                             "origin_file": "input/agendas/next_meeting_agenda.md"}
                        )
            else:
                # Stop if we encounter a non-bullet after Agenda start (defensive)
                # In provided input, agenda continues to EOF; but keep permissive.
                pass
    return {
        "meeting_name": meeting_name,
        "date": date_str,
        "agenda_bullets": agenda_bullets,
        "agenda_actions": action_items,
    }


def _parse_notes_actions(notes_lines: List[str]) -> List[Dict[str, Any]]:
    # Find all lines with checkbox pattern anywhere in file
    # Pattern: - [ ] Task (Assignee: Name, due: YYYY-MM-DD)
    pattern = re.compile(
        r'- \[( |x)\]\s*(.*?)\s*\(Assignee:\s*([^,]+),\s*due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\)',
        re.IGNORECASE,
    )
    items: List[Dict[str, Any]] = []
    for line in notes_lines:
        m = pattern.search(line)
        if m:
            checked_char = m.group(1)
            task = m.group(2).strip()
            assignee = m.group(3).strip()
            due = m.group(4).strip()
            status = "done" if checked_char.lower() == "x" else "open"
            items.append(
                {
                    "task": task,
                    "assignee": assignee,
                    "due_date": due,
                    "status": status,
                    "source": "last_meeting_notes",
                    "origin_file": "input/notes/last_meeting_notes.md",
                }
            )
    # Only unchecked (open) items are considered
    return [i for i in items if i["status"] == "open"]


def _parse_prior_commitments(prior_obj: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(prior_obj, list):
        return None
    items: List[Dict[str, Any]] = []
    for rec in prior_obj:
        if not isinstance(rec, dict):
            return None
        task = rec.get("task")
        assignee = rec.get("assignee")
        due = rec.get("due")
        status = rec.get("status")
        if None in (task, assignee, due, status):
            return None
        if status == "open":
            items.append(
                {
                    "task": str(task),
                    "assignee": str(assignee),
                    "due_date": str(due),
                    "source": "prior_commitments",
                    "origin_file": "input/committees/prior_commitments.json",
                }
            )
    return items


def _digit_lines_first_three(policy_lines: List[str]) -> List[str]:
    digit_lines = [ln.rstrip() for ln in policy_lines if any(ch.isdigit() for ch in ln)]
    return digit_lines[:3]


def _build_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Paths
    agenda_path = workspace / "input" / "agendas" / "next_meeting_agenda.md"
    notes_path = workspace / "input" / "notes" / "last_meeting_notes.md"
    roster_path = workspace / "input" / "committees" / "volunteer_roster.csv"
    prior_path = workspace / "input" / "committees" / "prior_commitments.json"
    policy_path = workspace / "input" / "research" / "policy_brief.txt"

    # Read and parse all inputs
    agenda_lines = _read_text_lines(agenda_path)
    notes_lines = _read_text_lines(notes_path)
    roster = _parse_roster(roster_path)
    prior_obj = _load_json(prior_path)
    policy_lines = _read_text_lines(policy_path)

    if None in (agenda_lines, notes_lines, roster, prior_obj, policy_lines):
        return None

    agenda_info = _parse_agenda(agenda_lines)  # includes name, date, bullets, actions
    if agenda_info.get("meeting_name") is None or agenda_info.get("date") is None:
        return None
    meeting_title = f"{agenda_info['meeting_name']} ({agenda_info['date']})"

    notes_actions = _parse_notes_actions(notes_lines)
    prior_actions = _parse_prior_commitments(prior_obj)
    if prior_actions is None:
        return None

    # Annotate with roster info
    roster_matched: List[Dict[str, Any]] = []
    missing_contacts: List[Dict[str, Any]] = []

    def _attach_roster(items: List[Dict[str, Any]]):
        for item in items:
            name = item["assignee"]
            if name in roster:
                item_full = {
                    "source": item["source"],
                    "task": item["task"],
                    "assignee": name,
                    "email": roster[name]["email"],
                    "role": roster[name]["role"],
                    "due_date": item["due_date"],
                    "origin_file": item["origin_file"],
                }
                roster_matched.append(item_full)
            else:
                missing_contacts.append(
                    {
                        "assignee": name,
                        "task": item["task"],
                        "due_date": item["due_date"],
                        "source": item["source"],
                        "origin_file": item["origin_file"],
                    }
                )

    # Only open items from prior and unchecked from notes, and all [ACTION] from agenda
    _attach_roster(prior_actions)
    _attach_roster(notes_actions)
    _attach_roster(agenda_info["agenda_actions"])

    # Build grouped missing contacts JSON expected structure
    grouped_missing: Dict[str, List[Dict[str, str]]] = {}
    for it in missing_contacts:
        grouped_missing.setdefault(it["assignee"], []).append(
            {
                "task": it["task"],
                "due_date": it["due_date"],
                "source": it["source"],
                "origin_file": it["origin_file"],
            }
        )
    expected_missing_json = [{"assignee": k, "items": v} for k, v in grouped_missing.items()]
    # Ensure deterministic order for expected comparison
    expected_missing_json.sort(key=lambda x: x["assignee"])
    for entry in expected_missing_json:
        entry["items"].sort(key=lambda y: (y["source"], y["task"], y["due_date"], y["origin_file"]))

    # Context lines: first three lines with digits
    context_lines = _digit_lines_first_three(policy_lines)

    return {
        "meeting_title": meeting_title,
        "agenda_bullets": agenda_info["agenda_bullets"],
        "context_lines": context_lines,
        "roster_items": roster_matched,
        "missing_contacts": missing_contacts,
        "missing_contacts_grouped": expected_missing_json,
        "roster": roster,
    }


def _extract_minutes_sections(minutes_lines: List[str]) -> Dict[str, List[str]]:
    headers = [
        "Agenda:",
        "Context:",
        "Carryover Action Items (roster-matched):",
        "New Action Items from Agenda (roster-matched):",
        "Unassigned or Missing Contacts:",
    ]
    indices = {}
    for i, ln in enumerate(minutes_lines):
        if ln.strip() in headers:
            indices[ln.strip()] = i

    # Sort headers by their appearance in file
    ordered = [h for h in headers if h in indices]
    ordered_sorted = sorted(ordered, key=lambda h: indices[h])
    sections: Dict[str, List[str]] = {}
    for idx, header in enumerate(ordered_sorted):
        start = indices[header] + 1
        end = len(minutes_lines)
        if idx + 1 < len(ordered_sorted):
            end = indices[ordered_sorted[idx + 1]]
        content = [line.rstrip() for line in minutes_lines[start:end]]
        sections[header] = content
    return sections


def _first_nonempty_line(lines: List[str]) -> Optional[str]:
    for ln in lines:
        if ln.strip() != "":
            return ln.rstrip()
    return None


def _section_contains_line_with_substrings(section_lines: List[str], substrings: List[str]) -> bool:
    for ln in section_lines:
        if all(sub in ln for sub in substrings):
            return True
    return False


def _strip_blank_lines(lines: List[str]) -> List[str]:
    return [ln.rstrip() for ln in lines if ln.strip() != ""]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_minutes_title_line": 0.0,
        "agenda_section_lines": 0.0,
        "context_section_lines": 0.0,
        "carryover_items_in_minutes": 0.0,
        "new_action_items_in_minutes": 0.0,
        "missing_contacts_in_minutes": 0.0,
        "action_items_csv_header": 0.0,
        "action_items_csv_rows": 0.0,
        "missing_contacts_json_structure": 0.0,
        "missing_contacts_json_contents": 0.0,
    }

    expected = _build_expected(workspace)
    # Paths to outputs
    minutes_path = workspace / "output" / "meeting_minutes_draft.md"
    csv_path = workspace / "output" / "action_items.csv"
    missing_json_path = workspace / "output" / "missing_contacts.json"

    minutes_lines = _read_text_lines(minutes_path)
    # Title line check
    if expected is not None and minutes_lines is not None:
        expected_title = expected["meeting_title"]
        got_title = _first_nonempty_line(minutes_lines)
        if got_title == expected_title:
            scores["meeting_minutes_title_line"] = 1.0

    # Agenda section lines check
    if expected is not None and minutes_lines is not None:
        sections = _extract_minutes_sections(minutes_lines)
        agenda_section = sections.get("Agenda:")
        if agenda_section is not None:
            expected_agenda = expected["agenda_bullets"]
            # Remove blank lines for comparison
            if _strip_blank_lines(agenda_section) == _strip_blank_lines(expected_agenda):
                scores["agenda_section_lines"] = 1.0

    # Context section lines check
    if expected is not None and minutes_lines is not None:
        sections = _extract_minutes_sections(minutes_lines)
        context_section = sections.get("Context:")
        if context_section is not None:
            if _strip_blank_lines(context_section) == _strip_blank_lines(expected["context_lines"]):
                scores["context_section_lines"] = 1.0

    # Carryover items in minutes check (from prior_commitments open + last_meeting_notes unchecked, roster-matched)
    if expected is not None and minutes_lines is not None:
        sections = _extract_minutes_sections(minutes_lines)
        carry_section = sections.get("Carryover Action Items (roster-matched):")
        if carry_section is not None:
            # Build expected carryover roster-matched items
            roster_items: List[Dict[str, Any]] = expected["roster_items"]
            expected_carry = [
                it for it in roster_items if it["source"] in ("prior_commitments", "last_meeting_notes")
            ]
            all_present = True
            for it in expected_carry:
                substrs = [it["assignee"], it["email"], it["role"], it["task"], it["due_date"], it["source"]]
                if not _section_contains_line_with_substrings(carry_section, substrs):
                    all_present = False
                    break
            # Ensure no non-roster names present (e.g., Casey Brooks)
            section_text = "\n".join(carry_section)
            no_disallowed = True
            for miss in expected["missing_contacts"]:
                if miss["assignee"] in section_text:
                    no_disallowed = False
                    break
            if all_present and no_disallowed:
                scores["carryover_items_in_minutes"] = 1.0

    # New action items from agenda (roster-matched)
    if expected is not None and minutes_lines is not None:
        sections = _extract_minutes_sections(minutes_lines)
        new_section = sections.get("New Action Items from Agenda (roster-matched):")
        if new_section is not None:
            roster_items: List[Dict[str, Any]] = expected["roster_items"]
            expected_new = [it for it in roster_items if it["source"] == "agenda"]
            all_present = True
            for it in expected_new:
                substrs = [it["assignee"], it["email"], it["role"], it["task"], it["due_date"], it["source"]]
                if not _section_contains_line_with_substrings(new_section, substrs):
                    all_present = False
                    break
            # Ensure no disallowed names (e.g., Casey Brooks) here
            section_text = "\n".join(new_section)
            no_disallowed = True
            for miss in expected["missing_contacts"]:
                if miss["assignee"] in section_text:
                    no_disallowed = False
                    break
            if all_present and no_disallowed:
                scores["new_action_items_in_minutes"] = 1.0

    # Missing contacts in minutes
    if expected is not None and minutes_lines is not None:
        sections = _extract_minutes_sections(minutes_lines)
        miss_section = sections.get("Unassigned or Missing Contacts:")
        if miss_section is not None:
            # Expected missing grouped items flattened
            expected_missing_flat = expected["missing_contacts"]
            all_present = True
            for it in expected_missing_flat:
                substrs = [it["assignee"], it["task"], it["due_date"], it["source"]]
                if not _section_contains_line_with_substrings(miss_section, substrs):
                    all_present = False
                    break
            # Ensure no roster-matched names appear here
            section_text = "\n".join(miss_section)
            roster_names = set(expected["roster"].keys())
            no_roster_names = not any(name in section_text for name in roster_names)
            if all_present and no_roster_names:
                scores["missing_contacts_in_minutes"] = 1.0

    # action_items.csv header and rows
    if expected is not None and csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = None
        if rows:
            header = rows[0]
            expected_header = ["source", "task", "assignee", "email", "role", "due_date", "origin_file"]
            if header == expected_header:
                scores["action_items_csv_header"] = 1.0
                # Compare rows ignoring order
                actual_rows = rows[1:]
                # Build expected rows
                exp_items: List[Dict[str, Any]] = expected["roster_items"]
                exp_rows = [
                    [it["source"], it["task"], it["assignee"], it["email"], it["role"], it["due_date"], it["origin_file"]]
                    for it in exp_items
                ]
                # Sort both lists deterministically
                def _sort_key(r):
                    return tuple(r)

                actual_sorted = sorted(actual_rows, key=_sort_key)
                expected_sorted = sorted(exp_rows, key=_sort_key)
                if actual_sorted == expected_sorted:
                    scores["action_items_csv_rows"] = 1.0

    # missing_contacts.json structure and contents
    if expected is not None and missing_json_path.exists():
        actual_json = _load_json(missing_json_path)
        # Structure check
        struct_ok = True
        if not isinstance(actual_json, list):
            struct_ok = False
        else:
            for entry in actual_json:
                if not isinstance(entry, dict):
                    struct_ok = False
                    break
                # Enforce exact keys
                if set(entry.keys()) != {"assignee", "items"}:
                    struct_ok = False
                    break
                if not isinstance(entry["assignee"], str):
                    struct_ok = False
                    break
                if not isinstance(entry["items"], list):
                    struct_ok = False
                    break
                for it in entry["items"]:
                    if not isinstance(it, dict):
                        struct_ok = False
                        break
                    if set(it.keys()) != {"task", "due_date", "source", "origin_file"}:
                        struct_ok = False
                        break
                if not struct_ok:
                    break
        if struct_ok:
            scores["missing_contacts_json_structure"] = 1.0
            # Contents check (order-insensitive)
            expected_entries = expected["missing_contacts_grouped"]
            # Normalize actual for comparison
            try:
                actual_norm = []
                for entry in actual_json:
                    items = list(entry["items"])
                    items_sorted = sorted(
                        items,
                        key=lambda y: (y.get("source"), y.get("task"), y.get("due_date"), y.get("origin_file")),
                    )
                    actual_norm.append({"assignee": entry["assignee"], "items": items_sorted})
                actual_norm.sort(key=lambda x: x["assignee"])
                if actual_norm == expected_entries:
                    scores["missing_contacts_json_contents"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()