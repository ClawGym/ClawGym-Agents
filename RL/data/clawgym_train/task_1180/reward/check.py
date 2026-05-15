import json
import csv
import re
import sys
import subprocess
from pathlib import Path


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_rows_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def list_files_with_sizes(root: Path):
    results = []
    if not root.exists():
        return results
    for p in sorted(root.rglob("*")):
        if p.is_file():
            try:
                size = p.stat().st_size
            except Exception:
                size = None
            results.append((p, size))
    return results


def vendors_from_yaml_simple(path: Path):
    # Minimal YAML parser tailored to the known structure:
    # vendors:
    #   - name: ...
    #     country: ...
    #     category: ...
    txt = read_text_safe(path)
    if not txt:
        return None
    vendors = []
    current = None
    in_list = False
    for line in txt.splitlines():
        stripped = line.rstrip()
        if stripped.strip().startswith("vendors:"):
            in_list = True
            continue
        if not in_list:
            continue
        if stripped.strip().startswith("- "):
            # start new vendor entry
            if current:
                vendors.append(current)
            current = {}
            # may contain "- name: X" on same line
            m = re.match(r"\s*-\s+name:\s*(.+)\s*$", stripped)
            if m:
                current["name"] = m.group(1).strip()
            continue
        # key: value lines under current
        if current is not None:
            m2 = re.match(r"\s*([a-zA-Z_]+):\s*(.+?)\s*$", stripped)
            if m2:
                key, val = m2.group(1).strip(), m2.group(2).strip()
                current[key] = val
    if current:
        vendors.append(current)
    return vendors


def parse_diagnostics(diagnostics_text: str):
    reminder_rows = []
    warnings = {"UNKNOWN_OWNER": [], "MISSING_DUE": [], "NO_EMAIL": []}
    summary = {"reminders": None, "warnings_total": None, "UNKNOWN_OWNER": None, "MISSING_DUE": None, "NO_EMAIL": None}
    for line in diagnostics_text.splitlines():
        l = line.strip()
        if l.startswith("REMINDER,"):
            # format: REMINDER,item_id,owner,due,topic
            parts = l.split(",", 4)
            if len(parts) >= 5:
                reminder_rows.append({
                    "item_id": parts[1].strip(),
                    "owner": parts[2].strip(),
                    "due_date": parts[3].strip(),
                    "topic": parts[4].strip(),
                })
        elif l.startswith("WARN "):
            # WARN CODE item_id owner
            m = re.match(r"^WARN\s+([A-Z_]+)\s+(\S+)\s+(.*)$", l)
            if m:
                code = m.group(1).strip()
                item_id = m.group(2).strip()
                owner = m.group(3).strip()
                if code in warnings:
                    warnings[code].append((item_id, owner))
        elif l.startswith("SUMMARY"):
            # SUMMARY reminders=1 warnings_total=4 UNKNOWN_OWNER=1 MISSING_DUE=2 NO_EMAIL=1
            # Extract numbers
            m_r = re.search(r"reminders=(\d+)", l)
            m_w = re.search(r"warnings_total=(\d+)", l)
            m_u = re.search(r"UNKNOWN_OWNER=(\d+)", l)
            m_m = re.search(r"MISSING_DUE=(\d+)", l)
            m_n = re.search(r"NO_EMAIL=(\d+)", l)
            if m_r:
                summary["reminders"] = int(m_r.group(1))
            if m_w:
                summary["warnings_total"] = int(m_w.group(1))
            if m_u:
                summary["UNKNOWN_OWNER"] = int(m_u.group(1))
            if m_m:
                summary["MISSING_DUE"] = int(m_m.group(1))
            if m_n:
                summary["NO_EMAIL"] = int(m_n.group(1))
    # Normalize order-independent sets for warnings
    for k in list(warnings.keys()):
        # Remove duplicates
        warnings[k] = list(dict.fromkeys(warnings[k]))
    return reminder_rows, warnings, summary


def parse_section(lines, section_name, all_sections):
    # Find section by keyword and return indices (start, end) of its content lines
    section_indices = None
    lower_section = section_name.lower()
    for i, line in enumerate(lines):
        if lower_section in line.lower():
            section_indices = i
            break
    if section_indices is None:
        return []
    # find next section start
    next_idx = len(lines)
    for j in range(section_indices + 1, len(lines)):
        for other in all_sections:
            if other.lower() in lines[j].lower() and other.lower() != lower_section:
                next_idx = j
                break
        if next_idx != len(lines) and next_idx == j:
            break
    # Return content lines between section heading and next section heading
    content = lines[section_indices + 1:next_idx]
    return content


def contains_path_and_size(line: str, path_str: str, size: int) -> bool:
    return (path_str in line) and (str(size) in line)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inspection_listing_complete": 0.0,
        "inspection_non_usa_section_present": 0.0,
        "command_diagnostics_present": 0.0,
        "diagnostics_expected_warnings_present": 0.0,
        "diagnostics_expected_reminders_present": 0.0,
        "diagnostics_summary_counts_correct": 0.0,
        "reminders_csv_header_and_rows_match": 0.0,
        "notes_title_has_meeting_name_and_date": 0.0,
        "notes_attendees_names_listed": 0.0,
        "notes_agenda_topics_and_owners_listed": 0.0,
        "notes_action_items_annotations_correct": 0.0,
        "notes_followup_reminders_match_csv": 0.0,
        "notes_tool_diagnostics_summary_present": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    agenda_path = input_dir / "agenda_2026-04-20.csv"
    attendees_path = input_dir / "attendees.json"
    vendors_path = input_dir / "vendors_usa.yaml"
    tool_path = input_dir / "scripts" / "reminder_tool.py"

    inspection_path = output_dir / "inspection_report.txt"
    diagnostics_path = output_dir / "command_diagnostics.txt"
    reminders_csv_path = output_dir / "reminders.csv"
    notes_path = output_dir / "meeting_notes_2026-04-20.md"

    # Compute expected warnings/reminders from inputs (deterministic baseline)
    expected_reminders = [{"item_id": "1", "owner": "Erik", "due_date": "2026-04-25",
                           "topic": "Source American-made grills for tailgate"}]
    expected_warnings = {
        "UNKNOWN_OWNER": [("4", "Olaf")],
        "MISSING_DUE": [("3", "Marta"), ("5", "Erik")],
        "NO_EMAIL": [("2", "Lars")],
    }
    expected_summary = {"reminders": 1, "warnings_total": 4, "UNKNOWN_OWNER": 1, "MISSING_DUE": 2, "NO_EMAIL": 1}

    # Check inspection_report.txt
    inspection_text = read_text_safe(inspection_path)
    if inspection_text:
        # Check file listing completeness: all input files listed with size
        files = list_files_with_sizes(input_dir)
        all_listed = True
        for p, size in files:
            # Use posix path for matching
            rel = p.relative_to(workspace).as_posix()
            if size is None:
                all_listed = False
                break
            found_line = False
            for line in inspection_text.splitlines():
                if contains_path_and_size(line, rel, size):
                    found_line = True
                    break
            if not found_line:
                all_listed = False
                break
        if files and all_listed:
            scores["inspection_listing_complete"] = 1.0

        # Check Non-USA vendor entries section
        lower_text = inspection_text.lower()
        section_idx = None
        lines = inspection_text.splitlines()
        for i, line in enumerate(lines):
            if "non-usa vendor entries" in line.lower():
                section_idx = i
                break
        if section_idx is not None:
            # Look for non-USA vendors in subsequent lines
            after_lines = lines[section_idx + 1 :]
            vendors = vendors_from_yaml_simple(vendors_path)
            non_usa_names = []
            if vendors is not None:
                for v in vendors:
                    country = (v.get("country") or "").strip()
                    name = (v.get("name") or "").strip()
                    if country != "USA":
                        non_usa_names.append(name)
            # Verify all non-USA vendor names appear after the section header
            if non_usa_names:
                present_all = True
                for n in non_usa_names:
                    if not any(n in l for l in after_lines):
                        present_all = False
                        break
                if present_all:
                    scores["inspection_non_usa_section_present"] = 1.0

    # Check command_diagnostics.txt presence and contents
    diagnostics_text = read_text_safe(diagnostics_path)
    if diagnostics_text:
        scores["command_diagnostics_present"] = 1.0
        parsed_reminders, parsed_warnings, parsed_summary = parse_diagnostics(diagnostics_text)

        # Compare reminders present in diagnostics with expected
        # normalize to set of tuples for comparison
        def to_tuple_list(rem_list):
            return sorted([(r["item_id"], r["owner"], r["due_date"], r["topic"]) for r in rem_list])

        if to_tuple_list(parsed_reminders) == to_tuple_list(expected_reminders):
            scores["diagnostics_expected_reminders_present"] = 1.0

        # Compare warnings by code (order-independent)
        warnings_match = True
        for code in expected_warnings:
            exp_set = set(expected_warnings[code])
            got_set = set(parsed_warnings.get(code, []))
            if exp_set != got_set:
                warnings_match = False
                break
        if warnings_match:
            scores["diagnostics_expected_warnings_present"] = 1.0

        # Compare summary counts
        if (parsed_summary.get("reminders") == expected_summary["reminders"] and
            parsed_summary.get("warnings_total") == expected_summary["warnings_total"] and
            parsed_summary.get("UNKNOWN_OWNER") == expected_summary["UNKNOWN_OWNER"] and
            parsed_summary.get("MISSING_DUE") == expected_summary["MISSING_DUE"] and
            parsed_summary.get("NO_EMAIL") == expected_summary["NO_EMAIL"]):
            scores["diagnostics_summary_counts_correct"] = 1.0

    # Check reminders.csv matches diagnostics REMINDER lines
    header, rows = read_csv_rows_safe(reminders_csv_path)
    if header is not None and rows is not None and diagnostics_text:
        header_ok = header == ["item_id", "owner", "due_date", "topic"]
        diag_reminders, _, _ = parse_diagnostics(diagnostics_text)
        # normalize comparison
        csv_rows_tuples = sorted([(r.get("item_id", ""), r.get("owner", ""), r.get("due_date", ""), r.get("topic", "")) for r in rows])
        diag_rows_tuples = sorted([(r.get("item_id", ""), r.get("owner", ""), r.get("due_date", ""), r.get("topic", "")) for r in diag_reminders])
        if header_ok and csv_rows_tuples == diag_rows_tuples:
            scores["reminders_csv_header_and_rows_match"] = 1.0

    # Check meeting notes content
    notes_text = read_text_safe(notes_path)
    if notes_text:
        notes_lines = notes_text.splitlines()
        # Title check
        first_nonempty = ""
        for l in notes_lines:
            if l.strip():
                first_nonempty = l.strip()
                break
        title_ok = (("Vikings fans club" in first_nonempty) and
                    ("Buy American" in first_nonempty) and
                    ("tailgate planning" in first_nonempty) and
                    ("2026-04-20" in first_nonempty))
        if title_ok:
            scores["notes_title_has_meeting_name_and_date"] = 1.0

        # Sections parsing
        section_names = ["Attendees", "Agenda", "Action Items", "Follow-up Reminders", "Tool Diagnostics"]
        attendees_section = parse_section(notes_lines, "Attendees", section_names)
        agenda_section = parse_section(notes_lines, "Agenda", section_names)
        action_items_section = parse_section(notes_lines, "Action Items", section_names)
        followup_section = parse_section(notes_lines, "Follow-up Reminders", section_names)
        tooldiag_section = parse_section(notes_lines, "Tool Diagnostics", section_names)

        # Attendees names listed
        att_json = read_json_safe(attendees_path)
        attendees_ok = False
        if isinstance(att_json, list) and attendees_section:
            names = [str(a.get("name", "")).strip() for a in att_json if "name" in a]
            attendees_ok = all(any(n in line for line in attendees_section) for n in names)
        if attendees_ok:
            scores["notes_attendees_names_listed"] = 1.0

        # Agenda topics and owners listed
        header_ag, rows_ag = read_csv_rows_safe(agenda_path)
        agenda_ok = False
        if header_ag is not None and rows_ag is not None and agenda_section:
            # For each agenda item: topic and owner should both appear in the same line
            agenda_ok = True
            for r in rows_ag:
                topic = (r.get("topic") or "").strip()
                owner = (r.get("owner") or "").strip()
                if not topic or not owner:
                    agenda_ok = False
                    break
                found = any((topic in line and owner in line) for line in agenda_section)
                if not found:
                    agenda_ok = False
                    break
        if agenda_ok:
            scores["notes_agenda_topics_and_owners_listed"] = 1.0

        # Action Items annotations
        action_ok = False
        if rows_ag is not None and action_items_section and diagnostics_text:
            # Map each agenda topic to its line in the action items section
            # We expect exactly one line per agenda item containing the topic
            # Using diagnostics to determine expected annotations
            _, parsed_warnings, _ = parse_diagnostics(diagnostics_text)
            missing_due_ids = set([iid for (iid, _) in parsed_warnings.get("MISSING_DUE", [])])
            no_email_ids = set([iid for (iid, _) in parsed_warnings.get("NO_EMAIL", [])])
            unknown_owner_ids = set([iid for (iid, _) in parsed_warnings.get("UNKNOWN_OWNER", [])])

            topic_to_line = {}
            for line in action_items_section:
                for r in rows_ag:
                    topic = (r.get("topic") or "").strip()
                    if topic and topic in line:
                        topic_to_line[topic] = line

            # Verify all agenda items exist with required annotations
            action_ok = True
            for r in rows_ag:
                item_id = (r.get("item_id") or "").strip()
                topic = (r.get("topic") or "").strip()
                line = topic_to_line.get(topic)
                if not line:
                    action_ok = False
                    break
                # Unknown owner -> "Unassigned – assign owner"
                if item_id in unknown_owner_ids:
                    if "Unassigned – assign owner" not in line:
                        action_ok = False
                        break
                # MISSING_DUE tag
                if item_id in missing_due_ids:
                    if "[Needs follow-up: set due date]" not in line:
                        action_ok = False
                        break
                # NO_EMAIL tag
                if item_id in no_email_ids:
                    if "[Needs follow-up: missing email]" not in line:
                        action_ok = False
                        break
            # No extra constraint on items without warnings
        if action_ok:
            scores["notes_action_items_annotations_correct"] = 1.0

        # Follow-up Reminders section vs reminders.csv
        followup_ok = False
        if followup_section and header is not None and rows is not None:
            # For each row in reminders.csv, ensure a line contains both owner and due_date
            followup_ok = True
            for r in rows:
                owner = (r.get("owner") or "").strip()
                due = (r.get("due_date") or "").strip()
                if not any((owner in line and due in line) for line in followup_section):
                    followup_ok = False
                    break
        if followup_ok:
            scores["notes_followup_reminders_match_csv"] = 1.0

        # Tool Diagnostics section summary
        tooldiag_ok = False
        if tooldiag_section and diagnostics_text:
            _, parsed_warnings, parsed_summary = parse_diagnostics(diagnostics_text)
            # Check counts are presented for each code on some line
            def has_code_with_count(lines, code, count):
                for l in lines:
                    if code in l:
                        nums = [int(x) for x in re.findall(r"\d+", l)]
                        if count in nums:
                            return True
                return False

            counts_ok = (has_code_with_count(tooldiag_section, "UNKNOWN_OWNER", parsed_summary.get("UNKNOWN_OWNER", -1)) and
                         has_code_with_count(tooldiag_section, "MISSING_DUE", parsed_summary.get("MISSING_DUE", -1)) and
                         has_code_with_count(tooldiag_section, "NO_EMAIL", parsed_summary.get("NO_EMAIL", -1)))
            # Check item_ids listed somewhere in the section
            ids_ok = True
            all_ids = set()
            for code, lst in parsed_warnings.items():
                for iid, _ in lst:
                    all_ids.add(iid)
            section_text_joined = "\n".join(tooldiag_section)
            for iid in all_ids:
                if iid not in section_text_joined:
                    ids_ok = False
                    break
            tooldiag_ok = counts_ok and ids_ok
        if tooldiag_ok:
            scores["notes_tool_diagnostics_summary_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()