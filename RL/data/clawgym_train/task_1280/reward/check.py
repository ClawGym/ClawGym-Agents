import sys
import json
import re
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def parse_markdown_headings_lines(text: str) -> List[str]:
    lines = text.splitlines()
    headings = []
    for ln in lines:
        if ln.lstrip().startswith("#"):
            # Normalize by stripping trailing spaces
            headings.append(ln.rstrip())
    return headings


def get_section_text(md_text: str, heading_name: str) -> Optional[str]:
    """
    Return the text content under a heading with text equal to heading_name
    (case-insensitive), until the next heading. Accepts any '#' level.
    """
    lines = md_text.splitlines()
    heading_indices = []
    for idx, ln in enumerate(lines):
        if ln.lstrip().startswith("#"):
            # Extract heading text
            m = re.match(r'^\s*#+\s*(.+?)\s*$', ln)
            if m:
                if m.group(1).strip().lower() == heading_name.strip().lower():
                    heading_indices.append(idx)
    if not heading_indices:
        return None
    start_idx = heading_indices[0] + 1
    # find next heading
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if lines[idx].lstrip().startswith("#"):
            end_idx = idx
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section


def headings_in_order(md_text: str, required: List[str]) -> Tuple[bool, List[str]]:
    """
    Check that required headings appear in order (case-insensitive).
    Returns (ok, found_sequence_of_required_headings).
    """
    lines = md_text.splitlines()
    found = []
    for ln in lines:
        if ln.lstrip().startswith("#"):
            m = re.match(r'^\s*#+\s*(.+?)\s*$', ln)
            if m:
                found.append(m.group(1).strip())
    # Find indices of required in order within found
    req_lower = [r.lower() for r in required]
    found_lower = [f.lower() for f in found]
    positions = []
    last_pos = -1
    for r in req_lower:
        if r in found_lower:
            pos = found_lower.index(r, last_pos + 1) if last_pos + 1 < len(found_lower) else -1
            if pos == -1:
                return False, found
            positions.append(pos)
            last_pos = pos
        else:
            return False, found
    # Ensure each required appears exactly once
    counts = {r: found_lower.count(r) for r in req_lower}
    if any(c != 1 for c in counts.values()):
        return False, found
    return True, found


def count_phrase_occurrences(text: str, phrase: str) -> int:
    # Count non-word-boundary-surrounded occurrences (phrase-level)
    # Use case-sensitive match as glossary is case-specific
    pattern = r'(?<!\w)' + re.escape(phrase) + r'(?!\w)'
    return len(re.findall(pattern, text))


def parse_transcript_actions(text: str) -> List[Dict[str, str]]:
    """
    Parse ACTION lines with format similar to:
    [8] Amina: ACTION: Carlos to update ... by 2026-05-20.
    Returns list of dicts: {'line_tag': '[8]', 'owner': 'Carlos', 'task': 'update ...', 'due': '2026-05-20'}
    """
    actions = []
    for line in text.splitlines():
        m = re.match(r'^\s*(\[\d+\]).*?ACTION:\s*([A-Za-z]+)\s+to\s+(.+?)\s+by\s+(\d{4}-\d{2}-\d{2})\b', line)
        if m:
            actions.append({
                "line_tag": m.group(1),
                "owner": m.group(2),
                "task": m.group(3).strip(),
                "due": m.group(4),
            })
    return actions


def parse_markdown_table(section_text: str) -> Optional[Tuple[List[str], List[List[str]]]]:
    """
    Parse the first markdown table found in section_text.
    Returns (headers, rows), where headers is list of header strings, rows is list of lists of cell strings.
    """
    lines = [ln for ln in section_text.splitlines()]
    # Find header line containing pipes
    start = -1
    for i, ln in enumerate(lines):
        if '|' in ln:
            # A simple heuristic: next line is a separator with - and |
            if i + 1 < len(lines) and re.search(r'\|\s*:?-{3,}:?\s*\|', lines[i + 1]):
                start = i
                break
    if start == -1:
        return None
    header_line = lines[start]
    sep_line = lines[start + 1]
    # Split by '|' and strip
    headers = [h.strip() for h in header_line.strip().strip('|').split('|')]
    # Collect data rows until a non-table line
    data_rows = []
    for ln in lines[start + 2:]:
        if '|' not in ln:
            # stop at first non-table line
            break
        row = [c.strip() for c in ln.strip().strip('|').split('|')]
        # Skip empty rows
        if len(row) == 1 and row[0] == "":
            continue
        data_rows.append(row)
    return headers, data_rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        # Design brief checks
        "design_brief_clean_exists": 0.0,
        "design_brief_headings_preserved": 0.0,
        "design_brief_synonyms_replaced": 0.0,
        "term_replacements_csv_valid": 0.0,
        "design_brief_duplicate_sentence_removed": 0.0,
        "design_brief_concise_length": 0.0,
        # Meeting notes checks
        "meeting_notes_exists": 0.0,
        "meeting_sections_order": 0.0,
        "meeting_attendees_captured": 0.0,
        "meeting_decisions_captured": 0.0,
        "meeting_action_items_table_valid": 0.0,
        # Email checks
        "email_final_exists": 0.0,
        "email_subject_format": 0.0,
        "email_blank_line_after_subject": 0.0,
        "email_body_word_limit": 0.0,
        "email_required_facts_present": 0.0,
    }

    # Paths
    input_design_brief = workspace / "input" / "design_brief.md"
    input_glossary = workspace / "input" / "glossary.csv"
    input_transcript = workspace / "input" / "project_sync_transcript.txt"
    input_email_draft = workspace / "input" / "email_draft.txt"  # not used for grading, but presence not graded

    output_design_clean = workspace / "output" / "design_brief_clean.md"
    output_term_replacements = workspace / "output" / "term_replacements.csv"
    output_meeting_notes = workspace / "output" / "meeting_notes.md"
    output_email_final = workspace / "output" / "email_final.txt"

    # Load inputs and outputs
    original_brief = read_text_safe(input_design_brief)
    glossary_rows = load_csv_safe(input_glossary)
    cleaned_brief = read_text_safe(output_design_clean)
    term_replacements_rows = load_csv_safe(output_term_replacements)
    transcript_text = read_text_safe(input_transcript)
    meeting_notes_text = read_text_safe(output_meeting_notes)
    email_final_text = read_text_safe(output_email_final)

    # Design brief exists
    if cleaned_brief is not None:
        scores["design_brief_clean_exists"] = 1.0

    # Design brief headings preserved exactly
    if original_brief is not None and cleaned_brief is not None:
        orig_headings = parse_markdown_headings_lines(original_brief)
        clean_headings = parse_markdown_headings_lines(cleaned_brief)
        # Exact match required
        if [h.rstrip() for h in orig_headings] == [h.rstrip() for h in clean_headings]:
            scores["design_brief_headings_preserved"] = 1.0

    # Design brief synonyms replaced
    if original_brief is not None and cleaned_brief is not None and glossary_rows is not None:
        all_ok = True
        for row in glossary_rows:
            synonym = row.get("synonym", "")
            if not synonym:
                continue
            count_orig = count_phrase_occurrences(original_brief, synonym)
            if count_orig > 0:
                count_clean_syn = count_phrase_occurrences(cleaned_brief, synonym)
                if count_clean_syn != 0:
                    all_ok = False
                    break
        scores["design_brief_synonyms_replaced"] = 1.0 if all_ok else 0.0

    # Term replacements CSV validity
    if original_brief is not None and cleaned_brief is not None and glossary_rows is not None and term_replacements_rows is not None:
        # Validate header columns
        # Re-load with csv module to inspect header
        try:
            with output_term_replacements.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        header_ok = header == ["synonym", "canonical", "count"]
        # Build expected replacements map: only those with replaced_count > 0
        expected: Dict[str, Tuple[str, int]] = {}
        for row in glossary_rows:
            synonym = row.get("synonym", "")
            canonical = row.get("canonical", "")
            if not synonym:
                continue
            count_orig = count_phrase_occurrences(original_brief, synonym)
            count_clean_syn = count_phrase_occurrences(cleaned_brief, synonym)
            replaced_count = max(count_orig - count_clean_syn, 0)
            if replaced_count > 0:
                expected[synonym] = (canonical, replaced_count)
        # Parse provided replacements rows
        provided: Dict[str, Tuple[str, int]] = {}
        valid_rows = True
        try:
            for row in term_replacements_rows:
                syn = row.get("synonym", "")
                can = row.get("canonical", "")
                cnt_str = row.get("count", "")
                try:
                    cnt = int(cnt_str)
                except Exception:
                    valid_rows = False
                    break
                # Only positive counts should be included
                if cnt <= 0:
                    valid_rows = False
                    break
                provided[syn] = (can, cnt)
        except Exception:
            valid_rows = False
        # Validate equality
        mapping_ok = True
        if set(provided.keys()) != set(expected.keys()):
            mapping_ok = False
        else:
            for syn, (can, cnt) in provided.items():
                exp_can, exp_cnt = expected[syn]
                if can != exp_can or cnt != exp_cnt:
                    mapping_ok = False
                    break
        if header_ok and valid_rows and mapping_ok:
            scores["term_replacements_csv_valid"] = 1.0

    # Design brief duplicate sentence removed
    if original_brief is not None and cleaned_brief is not None:
        dup_sentence = "The liner must demonstrate improved pressure distribution and stable suspension across walking tasks."
        count_orig = original_brief.count(dup_sentence)
        count_clean = cleaned_brief.count(dup_sentence)
        # Expect originally duplicated (count>=2) reduced to exactly 1
        if count_orig >= 2 and count_clean == 1:
            scores["design_brief_duplicate_sentence_removed"] = 1.0

    # Design brief concision: cleaned length <= original length
    if original_brief is not None and cleaned_brief is not None:
        if len(cleaned_brief) <= len(original_brief):
            scores["design_brief_concise_length"] = 1.0

    # Meeting notes existence
    if meeting_notes_text is not None:
        scores["meeting_notes_exists"] = 1.0

    # Meeting sections in order
    required_sections = ["Attendees", "Topics Discussed", "Decisions", "Action Items"]
    if meeting_notes_text is not None:
        ok, _found = headings_in_order(meeting_notes_text, required_sections)
        if ok:
            scores["meeting_sections_order"] = 1.0

    # Meeting attendees captured (names from transcript line 1)
    if meeting_notes_text is not None and transcript_text is not None:
        # Extract attendees from transcript
        # Expect names: Amina, Carlos, Priya, Jeff, Naomi
        attendees_expected = ["Amina", "Carlos", "Priya", "Jeff", "Naomi"]
        attendees_section = get_section_text(meeting_notes_text, "Attendees")
        if attendees_section is not None:
            all_present = True
            for name in attendees_expected:
                # Word boundary search
                if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', attendees_section) is None:
                    all_present = False
                    break
            if all_present:
                scores["meeting_attendees_captured"] = 1.0

    # Meeting decisions captured (ensure two decisions are mentioned)
    if meeting_notes_text is not None:
        decisions_section = get_section_text(meeting_notes_text, "Decisions")
        if decisions_section is not None:
            low = decisions_section.lower()
            has_decision_1 = ("use emg sensors lot b" in low)
            has_decision_2 = ("add two stair repeats" in low)
            if has_decision_1 and has_decision_2:
                scores["meeting_decisions_captured"] = 1.0

    # Meeting action items table validity
    if meeting_notes_text is not None and transcript_text is not None:
        actions = parse_transcript_actions(transcript_text)
        action_items_section = get_section_text(meeting_notes_text, "Action Items")
        if action_items_section is not None:
            parsed = parse_markdown_table(action_items_section)
            if parsed is not None:
                headers, rows = parsed
                # Normalize header labels
                expected_hdrs = ["Owner", "Task", "Due Date", "Source Lines"]
                if [h.strip() for h in headers] == expected_hdrs and len(rows) >= len(actions):
                    # Map to list of dict rows with column names
                    ok_rows = True
                    # For each expected action, verify presence in at least one row
                    for act in actions:
                        owner = act["owner"]
                        due = act["due"]
                        line_tag = act["line_tag"]
                        found_row = False
                        for r in rows:
                            # pad or trim row to headers length
                            cells = (r + [""] * len(headers))[:len(headers)]
                            row_dict = {headers[i]: cells[i] for i in range(len(headers))}
                            owner_match = row_dict["Owner"].strip() == owner
                            due_match = row_dict["Due Date"].strip() == due
                            source_contains = line_tag in row_dict["Source Lines"]
                            task_nonempty = len(row_dict["Task"].strip()) > 0
                            if owner_match and due_match and source_contains and task_nonempty:
                                found_row = True
                                break
                        if not found_row:
                            ok_rows = False
                            break
                    if ok_rows:
                        scores["meeting_action_items_table_valid"] = 1.0

    # Email final existence
    if email_final_text is not None:
        scores["email_final_exists"] = 1.0

    # Email subject format and blank line
    if email_final_text is not None:
        lines = email_final_text.splitlines()
        if len(lines) >= 1 and lines[0].startswith("Subject: "):
            scores["email_subject_format"] = 1.0
        if len(lines) >= 2 and lines[1].strip() == "":
            scores["email_blank_line_after_subject"] = 1.0

        # Body word limit
        body_lines = []
        if len(lines) >= 2:
            try:
                # body is after first blank line following subject line per requirement (immediately next line)
                # Since spec says "Include a blank line followed by the body", we consider body starting at line index 2
                body_lines = lines[2:]
            except Exception:
                body_lines = []
        body_text = "\n".join(body_lines)
        # Count words
        words = re.findall(r'\b\w+\b', body_text)
        if len(words) <= 150:
            scores["email_body_word_limit"] = 1.0

        # Required facts present
        required_facts = [
            "test protocol v2.1",
            "pilot window: 2026-06-01 to 2026-07-15",
            "15-minute feedback call",
        ]
        if all(fact in email_final_text for fact in required_facts):
            scores["email_required_facts_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()