import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _read_json(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if row is None:
                    return None
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_participants_yaml(text: str) -> Optional[List[str]]:
    # Extract names from lines like "- name: Sam"
    try:
        names = []
        for line in text.splitlines():
            m = re.match(r'^\s*-\s*name:\s*(.+?)\s*$', line)
            if m:
                names.append(m.group(1).strip())
        if not names:
            # Try alternative simple mapping style if present: participants: [Sam, Mira]
            # But given provided input, above should work. If none found, return empty list (valid parse).
            pass
        return names
    except Exception:
        return None


def _parse_transcript(text: str) -> Optional[Dict[str, List]]:
    try:
        decisions = []
        trivia = []
        actions = []  # list of dicts: assignee, description, due_date
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("DECISION:"):
                val = line[len("DECISION:"):].strip()
                decisions.append(val)
            elif line.startswith("TRIVIA:"):
                val = line[len("TRIVIA:"):].strip()
                trivia.append(val)
            elif line.startswith("ACTION:"):
                # ACTION: <Assignee> -> <Task> by <YYYY-MM-DD>.
                m = re.match(r'^ACTION:\s*(?P<assignee>[^-:]+?)\s*->\s*(?P<task>.*?)\s*by\s*(?P<date>\d{4}-\d{2}-\d{2})\.\s*$', line)
                if not m:
                    # Try a slightly more lenient regex without the terminal dot
                    m2 = re.match(r'^ACTION:\s*(?P<assignee>[^-:]+?)\s*->\s*(?P<task>.*?)\s*by\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\.?\s*$', line)
                    m = m2
                if m:
                    assignee = m.group("assignee").strip()
                    task = m.group("task").strip()
                    due = m.group("date").strip()
                    actions.append({
                        "assignee": assignee,
                        "description": task,
                        "due_date": due
                    })
                else:
                    # Malformed action line - treat as parse failure
                    return None
        return {"decisions": decisions, "trivia": trivia, "actions": actions}
    except Exception:
        return None


def _extract_sections(lines: List[str], headings: List[str]) -> Optional[Dict[str, List[str]]]:
    # Returns dict mapping heading to list of lines in that section (excluding heading line)
    try:
        indices = {}
        order = []
        for i, raw in enumerate(lines):
            s = raw.strip()
            if s in headings:
                indices[s] = i
                order.append((s, i))
        # Ensure all headings present
        if any(h not in indices for h in headings):
            return None
        # Ensure correct order
        ordered = [h for h, _ in sorted(order, key=lambda x: x[1])]
        if ordered != headings:
            return None
        sections = {}
        for idx, head in enumerate(headings):
            start = indices[head] + 1
            end = len(lines)
            if idx + 1 < len(headings):
                next_head = headings[idx + 1]
                end = indices[next_head]
            sections[head] = [l.rstrip("\n") for l in lines[start:end]]
        return sections
    except Exception:
        return None


def _normalize_agenda_line(s: str) -> str:
    # Remove leading bullet and extra spaces
    s = s.strip()
    s = re.sub(r'^\s*[-*]\s+', '', s)
    return s.strip()


def _compare_list_exact(a: List[str], b: List[str]) -> bool:
    return a == b


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "notes_sections_order_and_presence": 0.0,
        "agenda_overview_lines_match": 0.0,
        "decisions_section_matches": 0.0,
        "trivia_section_matches": 0.0,
        "action_items_section_matches": 0.0,
        "action_items_json_structure_and_values": 0.0,
        "agenda_summary_csv_matches": 0.0,
    }

    # Load run_config.json
    config_path = workspace / "input" / "run_config.json"
    config = _read_json(config_path)
    if not isinstance(config, dict):
        return scores

    target_date = config.get("target_date")
    output_base = config.get("output_base")
    inputs_cfg = config.get("inputs") if isinstance(config.get("inputs"), dict) else None
    if not target_date or not output_base or not inputs_cfg:
        return scores

    agenda_csv_path = workspace / inputs_cfg.get("agenda_csv", "")
    transcript_path = workspace / inputs_cfg.get("transcript_txt", "")
    participants_yaml_path = workspace / inputs_cfg.get("participants_yaml", "")
    if not agenda_csv_path.exists() or not transcript_path.exists() or not participants_yaml_path.exists():
        # Missing inputs - cannot compute expected outputs
        return scores

    # Parse inputs
    agenda_rows = _read_csv_dicts(agenda_csv_path)
    if agenda_rows is None:
        return scores
    transcript_text = _read_text(transcript_path)
    if transcript_text is None:
        return scores
    participants_text = _read_text(participants_yaml_path)
    if participants_text is None:
        return scores

    participants = _parse_participants_yaml(participants_text)
    if participants is None:
        return scores
    participants_set = set(participants)

    tr = _parse_transcript(transcript_text)
    if tr is None:
        return scores

    # Filter agenda by target_date
    filtered_agenda = [row for row in agenda_rows if (row.get("meeting_date") == target_date)]
    # Build expected Agenda Overview lines
    expected_agenda_lines = []
    for row in filtered_agenda:
        agenda_id = row.get("agenda_id", "").strip()
        topic = row.get("topic", "").strip()
        presenter = row.get("presenter", "").strip()
        atype = row.get("type", "").strip()
        expected_outcome = row.get("expected_outcome", "").strip()
        # Use em dash U+2014 between topic and presenter
        line = f"[{agenda_id}] {topic} — {presenter} ({atype}): {expected_outcome}"
        expected_agenda_lines.append(line)

    # Expected decisions and trivia text
    expected_decisions = tr.get("decisions", [])
    expected_trivia = tr.get("trivia", [])

    # Expected actions with owner validation
    expected_actions = []
    for idx, a in enumerate(tr.get("actions", []), start=1):
        assignee = a["assignee"]
        description = a["description"]
        due_date = a["due_date"]
        if assignee in participants_set:
            owner = assignee
            assignee_suggested = None
        else:
            owner = "Unassigned"
            assignee_suggested = assignee
        expected_actions.append({
            "id": f"A{idx}",
            "description": description,
            "owner": owner,
            "due_date": due_date,
            "source": "transcript",
            "status": "open",
            "assignee_suggested": assignee_suggested
        })

    # Expected action items notes lines
    expected_action_notes_lines = []
    for item in expected_actions:
        owner = item["owner"]
        desc = item["description"]
        due = item["due_date"]
        expected_action_notes_lines.append(f"[{owner}] {desc} (due: {due})")

    # Prepare output paths
    out_dir = workspace / output_base / target_date
    notes_path = out_dir / "notes.md"
    ai_json_path = out_dir / "action_items.json"
    agenda_summary_path = out_dir / "agenda_summary.csv"

    # Check notes.md
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        lines = notes_text.splitlines()
        headings = ["Agenda Overview:", "Decisions:", "Trivia Nuggets:", "Action Items:"]
        sections = _extract_sections(lines, headings)
        if sections is not None:
            scores["notes_sections_order_and_presence"] = 1.0

            # Agenda Overview content
            agenda_sec_lines = sections["Agenda Overview:"]
            agenda_norm = [_normalize_agenda_line(l) for l in agenda_sec_lines if _normalize_agenda_line(l)]
            if len(agenda_norm) == len(expected_agenda_lines) and set(agenda_norm) == set(expected_agenda_lines):
                scores["agenda_overview_lines_match"] = 1.0

            # Decisions: bullet list, order preserved
            decisions_sec_lines = [l.strip() for l in sections["Decisions:"] if l.strip()]
            decisions_bullets = []
            ok_bullets = True
            for l in decisions_sec_lines:
                if not l.startswith("- "):
                    ok_bullets = False
                    break
                decisions_bullets.append(l[2:].strip())
            if ok_bullets and _compare_list_exact(decisions_bullets, expected_decisions):
                scores["decisions_section_matches"] = 1.0

            # Trivia: bullet list, order preserved
            trivia_sec_lines = [l.strip() for l in sections["Trivia Nuggets:"] if l.strip()]
            trivia_bullets = []
            ok_bullets2 = True
            for l in trivia_sec_lines:
                if not l.startswith("- "):
                    ok_bullets2 = False
                    break
                trivia_bullets.append(l[2:].strip())
            if ok_bullets2 and _compare_list_exact(trivia_bullets, expected_trivia):
                scores["trivia_section_matches"] = 1.0

            # Action Items: bullet list of "[owner] description (due: YYYY-MM-DD)"
            action_sec_lines = [l.strip() for l in sections["Action Items:"] if l.strip()]
            action_bullets = []
            ok_bullets3 = True
            for l in action_sec_lines:
                if not l.startswith("- "):
                    ok_bullets3 = False
                    break
                action_bullets.append(l[2:].strip())
            if ok_bullets3 and _compare_list_exact(action_bullets, expected_action_notes_lines):
                scores["action_items_section_matches"] = 1.0

    # Check action_items.json
    ai_text = _read_text(ai_json_path)
    if ai_text is not None:
        try:
            data = json.loads(ai_text)
            if isinstance(data, list) and len(data) == len(expected_actions):
                all_ok = True
                for i, (got, exp) in enumerate(zip(data, expected_actions), start=1):
                    if not isinstance(got, dict):
                        all_ok = False
                        break
                    # Required fields
                    required_fields = ["id", "description", "owner", "due_date", "source", "status"]
                    if any(k not in got for k in required_fields):
                        all_ok = False
                        break
                    # Values
                    if got["id"] != exp["id"]:
                        all_ok = False
                        break
                    if got["description"] != exp["description"]:
                        all_ok = False
                        break
                    if got["owner"] != exp["owner"]:
                        all_ok = False
                        break
                    if got["due_date"] != exp["due_date"]:
                        all_ok = False
                        break
                    if got["source"] != "transcript":
                        all_ok = False
                        break
                    if got["status"] != "open":
                        all_ok = False
                        break
                    if exp["owner"] == "Unassigned":
                        if "assignee_suggested" not in got:
                            all_ok = False
                            break
                        if got["assignee_suggested"] != exp["assignee_suggested"]:
                            all_ok = False
                            break
                    else:
                        if "assignee_suggested" in got:
                            all_ok = False
                            break
                if all_ok:
                    scores["action_items_json_structure_and_values"] = 1.0
        except Exception:
            pass

    # Check agenda_summary.csv
    if agenda_summary_path.exists():
        try:
            with agenda_summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["agenda_id", "topic", "presenter", "type", "meeting_date"]
                if header == expected_header:
                    # Build expected rows in same order as filtered_agenda
                    expected_rows = []
                    for row in filtered_agenda:
                        expected_rows.append([
                            row.get("agenda_id", "").strip(),
                            row.get("topic", "").strip(),
                            row.get("presenter", "").strip(),
                            row.get("type", "").strip(),
                            row.get("meeting_date", "").strip(),
                        ])
                    actual_rows = rows[1:]
                    if actual_rows == expected_rows:
                        scores["agenda_summary_csv_matches"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()