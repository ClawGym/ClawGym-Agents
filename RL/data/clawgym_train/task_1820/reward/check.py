import json
import sys
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _list_proposal_files(workspace: Path):
    proposals_dir = workspace / "incoming" / "proposals"
    if not proposals_dir.exists():
        return []
    return sorted([p for p in proposals_dir.iterdir() if p.is_file() and p.suffix.lower() == ".md"])


def _parse_proposal_md(text: str):
    required_sections = ["Event", "Proposed Date", "Lead", "Needs", "Risks", "Decisions Pending"]
    result = {
        "Event": None,
        "Proposed Date": None,
        "Lead": None,
        "Needs": [],
        "Risks": [],
        "Decisions Pending": [],
        "sections_found": {s: False for s in required_sections},
    }

    lines = text.splitlines()
    current_section = None
    for raw in lines:
        line = raw.strip()

        # Section headers
        if re.match(r"^Event:\s*", line):
            result["sections_found"]["Event"] = True
            result["Event"] = line.split(":", 1)[1].strip()
            current_section = None
            continue
        if re.match(r"^Proposed Date:\s*", line):
            result["sections_found"]["Proposed Date"] = True
            date_str = line.split(":", 1)[1].strip()
            result["Proposed Date"] = date_str
            current_section = None
            continue
        if re.match(r"^Lead:\s*", line):
            result["sections_found"]["Lead"] = True
            result["Lead"] = line.split(":", 1)[1].strip()
            current_section = None
            continue
        if re.match(r"^Needs:\s*$", line):
            result["sections_found"]["Needs"] = True
            current_section = "Needs"
            continue
        if re.match(r"^Risks:\s*$", line):
            result["sections_found"]["Risks"] = True
            current_section = "Risks"
            continue
        if re.match(r"^Decisions Pending:\s*$", line):
            result["sections_found"]["Decisions Pending"] = True
            current_section = "Decisions Pending"
            continue

        # Bullets within current section
        if current_section in ("Needs", "Risks", "Decisions Pending") and line.startswith("- "):
            item = line[2:].strip()
            if current_section == "Needs":
                m = re.search(r"\(by\s+(\d{4}-\d{2}-\d{2})\)", item)
                due = m.group(1) if m else None
                task_text = re.sub(r"\(by\s+\d{4}-\d{2}-\d{2}\)", "", item).strip()
                task_text = re.sub(r"\s{2,}", " ", task_text).strip()
                result["Needs"].append({"task": task_text, "due_date": due})
            elif current_section == "Risks":
                result["Risks"].append(item)
            elif current_section == "Decisions Pending":
                result["Decisions Pending"].append(item)
            continue

        if line == "":
            current_section = None

    return result


def _validate_date(date_str: str, fmt: str) -> bool:
    try:
        datetime.strptime(date_str, fmt)
        return True
    except Exception:
        return False


def _extract_top_level_blocks(yaml_text: str):
    blocks = {}
    current_key = None
    current_lines = []
    for raw in yaml_text.splitlines():
        if re.match(r"^[^\s].*:\s*$", raw):
            if current_key is not None:
                blocks[current_key] = current_lines
            current_key = raw.split(":", 1)[0].strip()
            current_lines = []
        else:
            if current_key is not None:
                current_lines.append(raw)
    if current_key is not None:
        blocks[current_key] = current_lines
    return blocks


def _extract_meeting_date(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("meeting", [])
    for ln in lines:
        m = re.match(r"^\s*date:\s*\"?([^\"]+)\"?\s*$", ln)
        if m:
            return m.group(1).strip()
    return None


def _extract_meeting_location(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("meeting", [])
    for ln in lines:
        m = re.match(r"^\s*location:\s*\"?([^\"]+)\"?\s*$", ln)
        if m:
            return m.group(1).strip()
    return None


def _extract_agenda_items(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("agenda", [])
    items = []
    in_items = False
    base_indent = None
    for ln in lines:
        if re.match(r"^\s*items:\s*(\[\s*\])?\s*$", ln):
            in_items = True
            base_indent = len(re.match(r"^(\s*)", ln).group(1)) + 2
            continue
        if in_items:
            # Break when another key at same or less indentation starts
            if re.match(r"^\s*[A-Za-z_]+\s*:", ln) and len(re.match(r"^(\s*)", ln).group(1)) < base_indent:
                break
            m = re.match(r"^\s*-\s*(.*)$", ln)
            if m:
                s = m.group(1).strip()
                if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                    s = s[1:-1]
                items.append(s)
    return items


def _extract_agenda_notes_file(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("agenda", [])
    for ln in lines:
        m = re.match(r"^\s*notes_file:\s*\"?([^\"]+)\"?\s*$", ln)
        if m:
            return m.group(1).strip()
    return None


def _extract_actions_output_csv(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("actions", [])
    for ln in lines:
        m = re.match(r"^\s*output_csv:\s*\"?([^\"]+)\"?\s*$", ln)
        if m:
            return m.group(1).strip()
    return None


def _extract_audit_roster_status(yaml_text: str):
    blocks = _extract_top_level_blocks(yaml_text)
    lines = blocks.get("audit", [])
    for ln in lines:
        m = re.match(r"^\s*roster_status:\s*\"?([^\"]+)\"?\s*$", ln)
        if m:
            return m.group(1).strip()
    return None


def _find_in_order(text: str, substrings):
    pos = 0
    for s in substrings:
        idx = text.find(s, pos)
        if idx == -1:
            return False
        pos = idx + len(s)
    return True


def _extract_audit_counts(audit_text: str):
    proposals_count = None
    needs_total = None
    for ln in audit_text.splitlines():
        l = ln.lower()
        if "total" in l and "proposals" in l and ("processed" in l or "files" in l):
            nums = re.findall(r"\d+", ln)
            if nums:
                proposals_count = int(nums[0])
        if "needs" in l and "total" in l:
            nums = re.findall(r"\d+", ln)
            if nums:
                needs_total = int(nums[-1])
    return proposals_count, needs_total


def _parse_action_items_csv(path: Path):
    rows = _read_csv_dicts(path)
    return rows


def _find_regions_for_files(text: str, file_names: list):
    # Returns a dict: file_name -> (start_idx, end_idx)
    positions = []
    for name in file_names:
        idx = text.find(name)
        if idx != -1:
            positions.append((idx, name))
    positions.sort()
    regions = {}
    for i, (start, name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        regions[name] = (start, end)
    return regions


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "audit_file_present": 0.0,
        "audit_lists_all_proposals": 0.0,
        "audit_sections_status_present_per_file": 0.0,
        "audit_summary_proposals_count_correct": 0.0,
        "audit_summary_needs_count_correct": 0.0,
        "audit_lists_missing_leads": 0.0,
        "config_meeting_date_updated": 0.0,
        "config_agenda_items_sorted": 0.0,
        "config_roster_status_set": 0.0,
        "config_other_keys_preserved": 0.0,
        "meeting_notes_header_includes_date_and_location": 0.0,
        "meeting_notes_agenda_order_correct": 0.0,
        "meeting_notes_event_sections_complete": 0.0,
        "meeting_notes_roster_check_present": 0.0,
        "action_items_columns_correct": 0.0,
        "action_items_row_count_expected": 0.0,
        "action_items_rows_match_audit_total": 0.0,
        "action_items_content_correct": 0.0,
    }

    proposal_paths = _list_proposal_files(workspace)
    proposals_data = []
    for p in proposal_paths:
        txt = _read_text(p)
        if txt is None:
            continue
        proposals_data.append((p, _parse_proposal_md(txt)))

    roster_csv_path = workspace / "roster" / "volunteers.csv"
    roster_rows = _read_csv_dicts(roster_csv_path)
    roster_names = set()
    if roster_rows is not None:
        for r in roster_rows:
            name = r.get("Name")
            if name:
                roster_names.add(name.strip())

    required_sections = ["Event", "Proposed Date", "Lead", "Needs", "Risks", "Decisions Pending"]
    expected_needs_total = 0
    leads_missing = []
    per_proposal_info = []
    expected_agenda_items = []
    for p, data in proposals_data:
        expected_needs_total += len(data["Needs"])
        lead_name = data["Lead"]
        if lead_name and (lead_name not in roster_names):
            rel_src = str(p.relative_to(workspace).as_posix()) if p.is_absolute() else p.as_posix()
            leads_missing.append((lead_name, rel_src))
        ev = data["Event"]
        pd = data["Proposed Date"]
        if ev and pd and _validate_date(pd, "%Y-%m-%d"):
            expected_agenda_items.append((pd, ev))
        per_proposal_info.append({
            "path": str(p.relative_to(workspace).as_posix()) if p.is_absolute() else p.as_posix(),
            "sections_found": data["sections_found"],
            "lead": lead_name,
            "event": data["Event"],
            "proposed_date": data["Proposed Date"],
            "needs": data["Needs"],
            "risks": data["Risks"],
            "decisions": data["Decisions Pending"],
        })

    expected_agenda_items_sorted = [ev for (pd, ev) in sorted(expected_agenda_items, key=lambda x: x[0])]
    expected_proposals_count = len(proposal_paths)

    expected_meeting_date_str = "2026-05-05 19:00"
    try:
        meeting_dt = datetime.strptime(expected_meeting_date_str, "%Y-%m-%d %H:%M")
        default_due_date_str = (meeting_dt + timedelta(days=7)).strftime("%Y-%m-%d")
    except Exception:
        default_due_date_str = "2026-05-12"

    # Audit checks
    audit_path = workspace / "outputs" / "directory_audit.txt"
    audit_text = _read_text(audit_path)
    if audit_text is not None:
        scores["audit_file_present"] = 1.0
        # All proposals listed (by file name)
        all_listed = True
        file_basenames = [p.name for p in proposal_paths]
        for p in proposal_paths:
            if p.name not in audit_text:
                all_listed = False
                break
        if all_listed and len(proposal_paths) > 0:
            scores["audit_lists_all_proposals"] = 1.0

        # For each file, each required section marked found or missing within that file's region
        if file_basenames:
            regions = _find_regions_for_files(audit_text, file_basenames)
            per_file_ok = True
            for p in proposal_paths:
                name = p.name
                if name not in regions:
                    per_file_ok = False
                    break
                start, end = regions[name]
                chunk = audit_text[start:end]
                for sec in required_sections:
                    pattern = re.compile(rf"{re.escape(sec)}\b.*\b(found|missing)\b", re.IGNORECASE | re.DOTALL)
                    if not pattern.search(chunk):
                        per_file_ok = False
                        break
                if not per_file_ok:
                    break
            if per_file_ok:
                scores["audit_sections_status_present_per_file"] = 1.0

        proposals_count_found, needs_total_found = _extract_audit_counts(audit_text)
        if proposals_count_found is not None and proposals_count_found == expected_proposals_count:
            scores["audit_summary_proposals_count_correct"] = 1.0
        if needs_total_found is not None and needs_total_found == expected_needs_total:
            scores["audit_summary_needs_count_correct"] = 1.0

        if leads_missing:
            ok_missing = True
            for name, src in leads_missing:
                # Accept either relative path or just file name present along with name
                base = Path(src).name
                if (name not in audit_text) or (src not in audit_text and base not in audit_text):
                    ok_missing = False
                    break
            if ok_missing:
                scores["audit_lists_missing_leads"] = 1.0

    # Config checks
    config_path = workspace / "config" / "planning.yaml"
    config_text = _read_text(config_path)
    if config_text is not None:
        meeting_date_val = _extract_meeting_date(config_text)
        if meeting_date_val == expected_meeting_date_str:
            scores["config_meeting_date_updated"] = 1.0

        agenda_items = _extract_agenda_items(config_text)
        if agenda_items == expected_agenda_items_sorted and len(agenda_items) == len(expected_agenda_items_sorted):
            scores["config_agenda_items_sorted"] = 1.0

        roster_status = _extract_audit_roster_status(config_text)
        expected_roster_status = "requires_attention" if len(leads_missing) > 0 else "ok"
        if roster_status == expected_roster_status:
            scores["config_roster_status_set"] = 1.0

        # Only award preservation if the required updates were performed (avoid credit on scaffold defaults)
        meeting_location = _extract_meeting_location(config_text)
        notes_file = _extract_agenda_notes_file(config_text)
        output_csv_file = _extract_actions_output_csv(config_text)
        last_run_present = "last_run" in config_text
        if (
            scores["config_meeting_date_updated"] == 1.0
            and meeting_location == "Community Hall"
            and notes_file == "outputs/meeting_notes.md"
            and output_csv_file == "outputs/action_items.csv"
            and last_run_present
        ):
            scores["config_other_keys_preserved"] = 1.0

    # Meeting notes checks
    notes_path = workspace / "outputs" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None and config_text is not None:
        cfg_date = _extract_meeting_date(config_text)
        cfg_loc = _extract_meeting_location(config_text)
        if cfg_date and cfg_loc and (cfg_date in notes_text) and (cfg_loc in notes_text):
            scores["meeting_notes_header_includes_date_and_location"] = 1.0

        if expected_agenda_items_sorted and _find_in_order(notes_text, expected_agenda_items_sorted):
            scores["meeting_notes_agenda_order_correct"] = 1.0

        all_events_complete = True
        for info in per_proposal_info:
            ev = info["event"]
            lead = info["lead"]
            pd = info["proposed_date"]
            needs_tasks = [n["task"] for n in info["needs"]]
            risks_items = info["risks"]
            dec_items = info["decisions"]
            start_idx = notes_text.find(ev) if ev else -1
            if start_idx == -1:
                all_events_complete = False
                break
            # Determine section boundary by next event occurrence
            next_idx = len(notes_text)
            for other_ev in [x for x in expected_agenda_items_sorted if x != ev]:
                pos = notes_text.find(other_ev, start_idx + 1)
                if pos != -1 and pos < next_idx:
                    next_idx = pos
            section_text = notes_text[start_idx:next_idx]
            if (lead not in section_text) or (pd not in section_text):
                all_events_complete = False
                break
            if dec_items:
                if not any(di in section_text for di in dec_items):
                    all_events_complete = False
                    break
            if risks_items:
                if not any(ri in section_text for ri in risks_items):
                    all_events_complete = False
                    break
            for t in needs_tasks:
                if t not in section_text:
                    all_events_complete = False
                    break
            if not all_events_complete:
                break
        if all_events_complete:
            scores["meeting_notes_event_sections_complete"] = 1.0

        roster_check_ok = True
        if leads_missing:
            for name, _src in leads_missing:
                if name not in notes_text:
                    roster_check_ok = False
                    break
        if "outputs/directory_audit.txt" not in notes_text:
            roster_check_ok = False
        if roster_check_ok:
            scores["meeting_notes_roster_check_present"] = 1.0

    # Action items checks
    actions_csv_path = workspace / "outputs" / "action_items.csv"
    rows = _parse_action_items_csv(actions_csv_path) if actions_csv_path.exists() else None
    if rows is not None and isinstance(rows, list):
        expected_columns = ["event", "task", "owner", "due_date", "source_file"]
        try:
            with actions_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == expected_columns:
                scores["action_items_columns_correct"] = 1.0
        except Exception:
            pass

        if len(rows) == expected_needs_total:
            scores["action_items_row_count_expected"] = 1.0

        if audit_text is not None:
            _pc, needs_total_found = _extract_audit_counts(audit_text)
            if needs_total_found is not None and len(rows) == needs_total_found:
                scores["action_items_rows_match_audit_total"] = 1.0

        expected_rows = []
        for info in per_proposal_info:
            ev = info["event"]
            lead = info["lead"]
            src = info["path"]
            for need in info["needs"]:
                task = need["task"]
                due = need["due_date"] if need["due_date"] else default_due_date_str
                expected_rows.append({
                    "event": ev or "",
                    "task": task,
                    "owner": lead or "",
                    "due_date": due,
                    "source_file": src,
                })
        actual_rows = []
        if rows is not None:
            for r in rows:
                actual_rows.append({
                    "event": (r.get("event") or "").strip(),
                    "task": (r.get("task") or "").strip(),
                    "owner": (r.get("owner") or "").strip(),
                    "due_date": (r.get("due_date") or "").strip(),
                    "source_file": (r.get("source_file") or "").strip(),
                })

        def _rows_to_tuples(lst):
            return sorted([(d["event"], d["task"], d["owner"], d["due_date"], d["source_file"]) for d in lst])

        if _rows_to_tuples(actual_rows) == _rows_to_tuples(expected_rows):
            scores["action_items_content_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()