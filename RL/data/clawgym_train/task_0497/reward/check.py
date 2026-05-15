import json
import re
import sys
import csv
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _safe_load_csv(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure header present
            if reader.fieldnames is None:
                return False, []
            # Validate that all rows have the same fields
            for r in rows:
                if set(r.keys()) != set(reader.fieldnames):
                    return False, []
            return True, rows
    except Exception:
        return False, []


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w+(?:'\w+)?\b", text)
    return len(words)


def _parse_offers_from_message_draft(text: str) -> List[str]:
    # Extract offers from the "Offers I can actually do:" line
    # The line format example:
    # Offers I can actually do: cook a freezer meal; fold laundry; watch baby for 1 hour; drive to appointment
    offers = []
    for line in text.splitlines():
        if "Offers I can actually do:" in line:
            parts = line.split("Offers I can actually do:", 1)[1].strip()
            # Split by semicolons
            offers = [o.strip() for o in parts.split(";") if o.strip()]
            break
    return offers


def _parse_family_update_notes(text: str) -> Dict[str, object]:
    data = {
        "baby": None,
        "highlights": [],
        "schedule": [],
        "boundaries": [],
    }
    lines = [ln.strip() for ln in text.splitlines()]
    i = 0
    n = len(lines)

    # Baby line
    while i < n and lines[i] == "":
        i += 1
    for j in range(i, n):
        if lines[j].startswith("Baby:"):
            data["baby"] = lines[j].split("Baby:", 1)[1].strip()
            i = j + 1
            break

    # Find sections
    section = None
    for j in range(i, n):
        ln = lines[j]
        if not ln:
            continue
        if ln.startswith("Highlights:"):
            section = "highlights"
            continue
        if ln.startswith("Schedule next week:"):
            section = "schedule"
            continue
        if ln.startswith("Requests/Boundaries:"):
            section = "boundaries"
            continue
        if ln.startswith("- "):
            item = ln[2:].strip()
            if section == "highlights":
                data["highlights"].append(item)
            elif section == "schedule":
                data["schedule"].append(item)
            elif section == "boundaries":
                data["boundaries"].append(item)
    return data


def _parse_meeting_transcript(text: str) -> Tuple[Optional[str], Optional[str], List[str], List[Dict[str, str]], List[str]]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    title = None
    participants = None
    decisions: List[str] = []
    todos: List[Dict[str, str]] = []
    opens: List[str] = []

    # Expect first two lines: title and participants
    non_empty = [ln for ln in lines if ln.strip() != ""]
    if len(non_empty) >= 1:
        title = non_empty[0]
    if len(non_empty) >= 2:
        participants = non_empty[1]

    # Parse L-lines
    for ln in lines:
        m = re.match(r"^L(\d+):\s*(DECISION|TODO|OPEN)\s+—\s+(.*)$", ln)
        if not m:
            continue
        lnum = m.group(1)
        kind = m.group(2)
        rest = m.group(3).strip()
        if kind == "DECISION":
            # Decision text is everything after the dash
            decisions.append(rest)
        elif kind == "OPEN":
            opens.append(rest)
        elif kind == "TODO":
            # Format: Owner: Task ... by YYYY-MM-DD.
            # Extract owner
            ow_m = re.match(r"^([^:]+):\s*(.*)$", rest)
            if not ow_m:
                continue
            owner = ow_m.group(1).strip()
            remaining = ow_m.group(2).strip()
            # Extract due date
            date_m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", remaining)
            if not date_m:
                continue
            due_date = date_m.group(1)
            # Task is text before " by {date}"
            # Find " by {date}" occurrence
            idx = remaining.find(" by " + due_date)
            if idx == -1:
                # maybe "by {date}" without space before "by"
                idx = remaining.find("by " + due_date)
            task = remaining[:idx].strip()
            # Strip trailing punctuation
            task = task.rstrip(" .")
            todos.append({
                "owner": owner,
                "task": task,
                "due_date": due_date,
                "source_line": f"L{int(lnum):02d}",
            })
    return title, participants, decisions, todos, opens


def _normalize_heading(line: str) -> str:
    s = line.strip()
    # Remove leading markdown header hashes
    s = re.sub(r"^#+\s*", "", s)
    # Remove trailing colon
    s = s.rstrip(":").strip()
    return s.lower()


def _extract_section(lines: List[str], section_name: str) -> List[str]:
    # Return lines within the named section until next section or end
    content: List[str] = []
    normalized_name = section_name.lower()
    # Build list of indices where a section starts
    indices = []
    for idx, ln in enumerate(lines):
        head = _normalize_heading(ln)
        if head in ("decisions", "action items", "open questions"):
            indices.append((head, idx))
    start_idx = None
    end_idx = None
    for k, idx in indices:
        if k == normalized_name:
            start_idx = idx + 1
            break
    if start_idx is None:
        return content
    # Find next section start
    for k, idx in indices:
        if idx > start_idx - 1:
            # Skip the first which is our section
            continue
    # Determine end index as next section start
    next_indices = [idx for (k, idx) in indices if idx > start_idx - 1]
    if next_indices:
        end_idx = min(next_indices)
    else:
        end_idx = len(lines)
    # Collect content lines
    for i in range(start_idx, end_idx):
        content.append(lines[i].rstrip("\n"))
    return content


def _bullet_texts(section_lines: List[str]) -> List[str]:
    # Extract bullet lines beginning with "- "
    bullets: List[str] = []
    for ln in section_lines:
        if ln.strip().startswith("- "):
            bullets.append(ln.strip()[2:].strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "rewritten_message_exists": 0.0,
        "rewritten_message_word_count_80_120": 0.0,
        "rewritten_message_includes_two_offers_verbatim": 0.0,
        "rewritten_message_no_banned_terms": 0.0,
        "rewritten_message_no_past_lifestyle_mentions": 0.0,
        "family_update_exists": 0.0,
        "family_update_word_count_120_180": 0.0,
        "family_update_mentions_baby_name_exactly": 0.0,
        "family_update_highlights_coverage": 0.0,
        "family_update_schedule_coverage": 0.0,
        "family_update_final_note_boundaries_verbatim": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_title_and_participants_exact": 0.0,
        "meeting_notes_decisions_section_exact_order_and_text": 0.0,
        "meeting_notes_action_items_section_correct": 0.0,
        "meeting_notes_open_questions_section_exact_texts": 0.0,
        "action_items_csv_exists": 0.0,
        "action_items_csv_header_and_rows_correct": 0.0,
        "action_items_cross_file_consistency": 0.0,
    }

    # Load inputs
    input_message_path = workspace / "input" / "message_draft.txt"
    ok_msg, msg_text = _read_text(input_message_path)
    offers_list = _parse_offers_from_message_draft(msg_text) if ok_msg else []

    input_notes_path = workspace / "input" / "family_update_notes.txt"
    ok_notes, notes_text = _read_text(input_notes_path)
    notes_data = _parse_family_update_notes(notes_text) if ok_notes else {"baby": None, "highlights": [], "schedule": [], "boundaries": []}

    input_transcript_path = workspace / "input" / "meeting_transcript.md"
    ok_transcript, transcript_text = _read_text(input_transcript_path)
    if ok_transcript:
        title_expected, participants_expected, decisions_expected, todos_expected, opens_expected = _parse_meeting_transcript(transcript_text)
    else:
        title_expected = None
        participants_expected = None
        decisions_expected = []
        todos_expected = []
        opens_expected = []

    # Check rewritten_message.md
    rewritten_path = workspace / "output" / "rewritten_message.md"
    ok_rewritten, rewritten_text = _read_text(rewritten_path)
    if ok_rewritten:
        scores["rewritten_message_exists"] = 1.0
        wc = _word_count(rewritten_text)
        if 80 <= wc <= 120:
            scores["rewritten_message_word_count_80_120"] = 1.0

        # Check offers inclusion: at least two present verbatim
        count_offers_present = 0
        for offer in offers_list:
            if offer and offer in rewritten_text:
                count_offers_present += 1
        if count_offers_present >= 2:
            scores["rewritten_message_includes_two_offers_verbatim"] = 1.0

        # Banned terms
        banned_ok = True
        banned_patterns = [
            re.compile(r"\bshould\b", re.IGNORECASE),
            re.compile(r"\btry\s+harder\b", re.IGNORECASE),
            re.compile(r"\btidy\b", re.IGNORECASE),
            re.compile(r"\btravel\b", re.IGNORECASE),
            re.compile(r"\bfancy\s+friends\b", re.IGNORECASE),
            re.compile(r"\braised\b", re.IGNORECASE),
            re.compile(r"\bfast\s+life\b", re.IGNORECASE),
        ]
        for pat in banned_patterns:
            if pat.search(rewritten_text):
                banned_ok = False
                break
        if banned_ok:
            scores["rewritten_message_no_banned_terms"] = 1.0

        # No past lifestyle mentions (deterministic proxies)
        past_ok = True
        past_forbidden = [
            re.compile(r"\blate\s+nights\b", re.IGNORECASE),
            re.compile(r"\bbefore\s+Noah\b", re.IGNORECASE),
            re.compile(r"\bmotherhood\s+is\s+different\b", re.IGNORECASE),
        ]
        for pat in past_forbidden:
            if pat.search(rewritten_text):
                past_ok = False
                break
        if past_ok:
            scores["rewritten_message_no_past_lifestyle_mentions"] = 1.0

    # Check family_update.md
    family_update_path = workspace / "output" / "family_update.md"
    ok_family, family_text = _read_text(family_update_path)
    if ok_family:
        scores["family_update_exists"] = 1.0
        wc = _word_count(family_text)
        if 120 <= wc <= 180:
            scores["family_update_word_count_120_180"] = 1.0

        # Baby name exactly
        baby_name = notes_data.get("baby")
        if isinstance(baby_name, str) and baby_name and baby_name in family_text:
            scores["family_update_mentions_baby_name_exactly"] = 1.0

        # Highlights coverage (require verbatim presence)
        highlights = notes_data.get("highlights", [])
        if highlights:
            present = sum(1 for h in highlights if h in family_text)
            scores["family_update_highlights_coverage"] = present / float(len(highlights))
        else:
            scores["family_update_highlights_coverage"] = 0.0

        # Schedule coverage (require verbatim presence)
        schedule = notes_data.get("schedule", [])
        if schedule:
            present = sum(1 for s in schedule if s in family_text)
            scores["family_update_schedule_coverage"] = present / float(len(schedule))
        else:
            scores["family_update_schedule_coverage"] = 0.0

        # Final Note line format
        boundaries = notes_data.get("boundaries", [])
        if len(boundaries) >= 2:
            expected_note_line = f"Note: {boundaries[0]} {boundaries[1]}"
            # Find last non-empty line
            lines = [ln.rstrip() for ln in family_text.splitlines()]
            non_empty_lines = [ln for ln in lines if ln.strip() != ""]
            if non_empty_lines:
                if non_empty_lines[-1] == expected_note_line:
                    scores["family_update_final_note_boundaries_verbatim"] = 1.0

    # Check meeting_notes.md
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    ok_notes_out, notes_out_text = _read_text(meeting_notes_path)
    md_action_items_set = set()
    if ok_notes_out:
        scores["meeting_notes_exists"] = 1.0
        out_lines = [ln.rstrip("\n") for ln in notes_out_text.splitlines()]
        non_empty_out = [ln for ln in out_lines if ln.strip() != ""]
        # Title and participants must match exactly
        title_ok = False
        participants_ok = False
        if title_expected and participants_expected and len(non_empty_out) >= 2:
            if non_empty_out[0] == title_expected and non_empty_out[1] == participants_expected:
                title_ok = True
                participants_ok = True
        if title_ok and participants_ok:
            scores["meeting_notes_title_and_participants_exact"] = 1.0

        # Sections
        decisions_section = _extract_section(out_lines, "Decisions")
        action_items_section = _extract_section(out_lines, "Action Items")
        open_questions_section = _extract_section(out_lines, "Open Questions")

        # Decisions check: exact order and text
        decisions_bullets = _bullet_texts(decisions_section)
        if decisions_expected and decisions_bullets == decisions_expected:
            scores["meeting_notes_decisions_section_exact_order_and_text"] = 1.0
        elif decisions_expected == []:
            # If no expected (input missing), leave 0.0
            pass

        # Action items check: one bullet per TODO with specified format, compare set equality
        expected_ai_set = set()
        for t in todos_expected:
            expected_ai_set.add(f"{t['owner']} — {t['task']} — Due {t['due_date']} — Source {t['source_line']}")
        action_bullets = _bullet_texts(action_items_section)
        parsed_ai_set = set()
        valid_format = True
        for b in action_bullets:
            m = re.match(r"^(.+)\s+—\s+(.+)\s+—\s+Due\s+(\d{4}-\d{2}-\d{2})\s+—\s+Source\s+(L\d{2})\s*$", b)
            if not m:
                valid_format = False
                break
            owner, task, due, src = m.group(1).strip(), m.group(2).strip(), m.group(3), m.group(4)
            parsed_ai_set.add(f"{owner} — {task} — Due {due} — Source {src}")
        if valid_format and expected_ai_set and parsed_ai_set == expected_ai_set and len(action_bullets) == len(todos_expected):
            scores["meeting_notes_action_items_section_correct"] = 1.0
        md_action_items_set = parsed_ai_set

        # Open questions: exact texts (set equality)
        open_bullets = _bullet_texts(open_questions_section)
        expected_open_set = set(opens_expected)
        open_set = set(open_bullets)
        if expected_open_set and open_set == expected_open_set:
            scores["meeting_notes_open_questions_section_exact_texts"] = 1.0

    # Check action_items.csv
    action_csv_path = workspace / "output" / "action_items.csv"
    ok_csv, csv_rows = _safe_load_csv(action_csv_path)
    csv_action_items_set = set()
    if ok_csv:
        scores["action_items_csv_exists"] = 1.0
        # Validate header exactly
        with action_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        expected_header = ["owner", "task", "due_date", "source_line"]
        header_ok = header == expected_header

        # Validate rows set equals expected
        expected_rows_set = set()
        for t in todos_expected:
            expected_rows_set.add((t["owner"], t["task"], t["due_date"], t["source_line"]))
        rows_set = set()
        rows_valid = True
        for r in csv_rows:
            # Ensure all required keys present
            if set(r.keys()) != set(expected_header):
                rows_valid = False
                break
            # Validate date format
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["due_date"] or ""):
                rows_valid = False
                break
            rows_set.add((r["owner"].strip(), r["task"].strip(), r["due_date"].strip(), r["source_line"].strip()))
        if header_ok and expected_rows_set and rows_valid and rows_set == expected_rows_set and len(csv_rows) == len(todos_expected):
            scores["action_items_csv_header_and_rows_correct"] = 1.0
        csv_action_items_set = set(f"{o} — {t} — Due {d} — Source {s}" for (o, t, d, s) in rows_set)

    # Cross-file consistency between meeting_notes and csv action items
    if md_action_items_set and csv_action_items_set:
        if md_action_items_set == csv_action_items_set:
            scores["action_items_cross_file_consistency"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()