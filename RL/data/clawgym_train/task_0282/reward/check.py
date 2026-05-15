import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_inspirations_yaml(path: Path) -> Tuple[Optional[Dict[str, str]], Optional[List[str]]]:
    """
    Minimal strict parser for the known simple YAML structure in input/inspirations.yaml.

    Expected format:

    schedule:
      Monday: "Maya Angelou"
      ...

    authors:
      - name: "Maya Angelou"
      ...

    Returns (schedule_dict, authors_list) or (None, None) on failure.
    """
    text = read_text_safe(path)
    if text is None:
        return None, None

    lines = text.splitlines()
    schedule: Dict[str, str] = {}
    authors: List[str] = []
    i = 0
    n = len(lines)
    try:
        while i < n:
            line = lines[i].rstrip("\n")
            if re.match(r'^\s*schedule\s*:\s*$', line):
                i += 1
                while i < n:
                    l = lines[i]
                    if re.match(r'^\S', l) and not re.match(r'^\s', l):
                        break  # next top-level key
                    m = re.match(r'^\s{2}([A-Za-z]+)\s*:\s*"(.*)"\s*$', l)
                    if m:
                        weekday = m.group(1).strip()
                        name = m.group(2).strip()
                        schedule[weekday] = name
                    i += 1
                continue
            if re.match(r'^\s*authors\s*:\s*$', line):
                i += 1
                while i < n:
                    l = lines[i]
                    if re.match(r'^\S', l) and not re.match(r'^\s', l):
                        break  # next top-level key
                    m = re.match(r'^\s{2}-\s+name:\s*"(.*)"\s*$', l)
                    if m:
                        name = m.group(1).strip()
                        authors.append(name)
                    i += 1
                continue
            i += 1
    except Exception:
        return None, None

    if not schedule or not authors:
        return None, None
    return schedule, authors


def split_markdown_sections_by_headings(text: str) -> List[Tuple[str, int, int]]:
    """
    Splits markdown text into sections by headings (# to ######).
    Returns a list of tuples (heading_text, start_index, end_index) where start_index/end_index
    are line indices defining the section content range [start, end).
    """
    lines = text.splitlines()
    # collect headings positions
    positions: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        m = re.match(r'^\s{0,3}#{1,6}\s*(.+?)\s*$', line)
        if m:
            title = m.group(1).strip()
            positions.append((idx, title))

    sections: List[Tuple[str, int, int]] = []
    for i, (start_idx, title) in enumerate(positions):
        end_idx = positions[i + 1][0] if i + 1 < len(positions) else len(lines)
        sections.append((title, start_idx + 1, end_idx))  # content lines after heading
    return sections


def extract_author_sections(search_log_text: str, authors: List[str]) -> Dict[str, str]:
    """
    Map each author's name to the content of their section in the search_log.md.
    We look for a heading exactly matching the author's name.
    """
    sections = split_markdown_sections_by_headings(search_log_text or "")
    lines = (search_log_text or "").splitlines()
    result: Dict[str, str] = {}
    for author in authors:
        for title, start, end in sections:
            if title == author:
                content = "\n".join(lines[start:end]).strip()
                result[author] = content
                break
    return result


def detect_queries_in_section(section_text: str) -> List[str]:
    """
    Detect query lines in a section: take bullet or numbered list lines
    that do not include 'http' and are not obviously 'source' or 'rationale' lines.
    """
    queries: List[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if re.match(r'^(-|\*|\d+\.)\s+', stripped):
            # filter out source/rationale lines
            lower = stripped.lower()
            if 'http' in lower:
                continue
            if 'source' in lower or 'rationale' in lower or 'chosen' in lower:
                continue
            content = re.sub(r'^(-|\*|\d+\.)\s+', '', stripped).strip()
            if content:
                queries.append(content)
    return queries


def has_markdown_link_with_url(section_text: str) -> bool:
    # Look for [Title](http...) pattern
    if re.search(r'\[[^\]]+\]\((https?://[^\)]+)\)', section_text):
        return True
    # Or a bare URL with a nearby 'Title' label on the same line
    for line in section_text.splitlines():
        if 'http' in line and ('title' in line.lower() or '[' in line or 'source' in line.lower()):
            return True
    return False


def has_rationale_sentence(section_text: str) -> bool:
    # Look for a line indicating rationale or a sentence explaining the choice.
    for line in section_text.splitlines():
        lower = line.lower()
        if 'rationale' in lower or 'because' in lower or 'selected' in lower or 'chosen' in lower or 'official' in lower or 'reputable' in lower:
            if 'http' not in lower and len(line.strip()) > 10:
                return True
        if '.' in line and 'http' not in line and len(line.strip()) > 20:
            return True
    return False


def validate_url(url: str) -> bool:
    return isinstance(url, str) and re.match(r'^https?://[^\s]+$', url) is not None


def parse_date_str(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def compute_weekday_name(date_str: str) -> Optional[str]:
    dt = parse_date_str(date_str)
    if not dt:
        return None
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][dt.weekday()]


def read_agenda_headings(path: Path) -> Optional[List[str]]:
    text = read_text_safe(path)
    if text is None:
        return None
    # Exact non-empty lines as headings sequence (as provided)
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    # Keep all lines (including the first heading line with '# ') and subsequent section titles
    headings = [ln for ln in lines if ln.strip() != ""]
    return headings


def find_section_ranges_by_headings(doc_text: str, headings: List[str]) -> Dict[str, Tuple[int, int]]:
    """
    Given document text and ordered headings (exact lines), return a mapping heading->(start_line_idx, end_line_idx)
    for content ranges in doc_text.
    """
    lines = doc_text.splitlines()
    positions: List[Tuple[str, int]] = []
    for idx, line in enumerate(lines):
        for h in headings:
            if line.strip() == h.strip():
                positions.append((h, idx))
                break
    # Ensure order
    ordered_positions: List[Tuple[str, int]] = []
    seen = set()
    last_idx = -1
    for h in headings:
        pos = None
        for (hh, i) in positions:
            if hh == h and hh not in seen and i > last_idx:
                pos = i
                break
        if pos is not None:
            ordered_positions.append((h, pos))
            seen.add(h)
            last_idx = pos
    ranges: Dict[str, Tuple[int, int]] = {}
    for i, (h, start) in enumerate(ordered_positions):
        end = ordered_positions[i + 1][1] if i + 1 < len(ordered_positions) else len(lines)
        ranges[h] = (start + 1, end)
    return ranges


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_sections_per_author": 0.0,
        "search_log_queries_per_author": 0.0,
        "search_log_source_link_per_author": 0.0,
        "search_log_rationale_per_author": 0.0,
        "quotes_json_structure_valid": 0.0,
        "quotes_total_count": 0.0,
        "quotes_author_name_matching": 0.0,
        "quotes_per_author_coverage": 0.0,
        "script_file_present": 0.0,
        "run_log_single_command_correct": 0.0,
        "reminder_output_exists_and_valid": 0.0,
        "meeting_notes_headings_order": 0.0,
        "meeting_notes_sources_summary": 0.0,
        "meeting_notes_open_questions": 0.0,
        "meeting_notes_action_items_count": 0.0,
    }

    # Load inputs
    inspirations_path = workspace / "input" / "inspirations.yaml"
    reminder_config_path = workspace / "input" / "reminder_config.json"
    meeting_agenda_path = workspace / "input" / "meeting_agenda.md"

    schedule, authors = parse_inspirations_yaml(inspirations_path)
    reminder_config = load_json_safe(reminder_config_path)
    agenda_headings = read_agenda_headings(meeting_agenda_path)

    # SEARCH LOG CHECKS
    search_log_path = workspace / "output" / "search_log.md"
    search_log_text = read_text_safe(search_log_path)
    if search_log_text is not None and authors:
        author_sections = extract_author_sections(search_log_text, authors)
        if authors:
            sec_ok = sum(1 for a in authors if a in author_sections)
            scores["search_log_sections_per_author"] = sec_ok / max(1, len(authors))

            queries_ok_count = 0
            source_link_ok_count = 0
            rationale_ok_count = 0
            for a in authors:
                sect = author_sections.get(a, "")
                queries = detect_queries_in_section(sect)
                if len(queries) >= 2:
                    queries_ok_count += 1
                if has_markdown_link_with_url(sect):
                    source_link_ok_count += 1
                if has_rationale_sentence(sect):
                    rationale_ok_count += 1
            scores["search_log_queries_per_author"] = queries_ok_count / max(1, len(authors))
            scores["search_log_source_link_per_author"] = source_link_ok_count / max(1, len(authors))
            scores["search_log_rationale_per_author"] = rationale_ok_count / max(1, len(authors))

    # QUOTES JSON CHECKS
    quotes_path = workspace / "output" / "quotes.json"
    quotes_data = load_json_safe(quotes_path)
    quotes_valid = True
    quotes_list: List[dict] = []
    allowed_source_types = {
        "official site", "foundation", "publisher", "library/archive",
        "museum", "university", "press", "other reputable"
    }
    if isinstance(quotes_data, list):
        quotes_list = quotes_data
        for item in quotes_list:
            # required fields
            if not isinstance(item, dict):
                quotes_valid = False
                break
            required_fields = ["author", "quote_text", "source_name", "source_url", "source_type", "retrieval_date"]
            for f in required_fields:
                if f not in item or not isinstance(item[f], str) or not item[f].strip():
                    quotes_valid = False
                    break
            if not quotes_valid:
                break
            # source_type
            if item["source_type"] not in allowed_source_types:
                quotes_valid = False
                break
            # date format
            if parse_date_str(item["retrieval_date"]) is None:
                quotes_valid = False
                break
            # url
            if not validate_url(item["source_url"]):
                quotes_valid = False
                break
            # citation if present must be string
            if "citation" in item and not isinstance(item["citation"], str):
                quotes_valid = False
                break
    else:
        quotes_valid = False

    if quotes_valid:
        scores["quotes_json_structure_valid"] = 1.0

    # author name matching and coverage and total count
    if quotes_valid and authors:
        all_names_match = all(q.get("author") in set(authors) for q in quotes_list)
        scores["quotes_author_name_matching"] = 1.0 if all_names_match else 0.0

        coverage = 0
        for a in authors:
            if any(q.get("author") == a for q in quotes_list):
                coverage += 1
        scores["quotes_per_author_coverage"] = coverage / max(1, len(authors))

        scores["quotes_total_count"] = 1.0 if len(quotes_list) >= 5 else 0.0

    # SCRIPT FILE PRESENT
    script_py = workspace / "scripts" / "quote_reminder.py"
    script_sh = workspace / "scripts" / "quote_reminder.sh"
    script_exists = script_py.exists() or script_sh.exists()
    scores["script_file_present"] = 1.0 if script_exists else 0.0

    # RUN LOG CHECK
    run_log_path = workspace / "output" / "run_log.txt"
    run_log_text = read_text_safe(run_log_path)
    if run_log_text is not None:
        non_empty_lines = [ln.strip() for ln in run_log_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            cmd = non_empty_lines[0]
            has_date = "--date 2024-01-02" in cmd
            uses_py = "quote_reminder.py" in cmd and script_py.exists()
            uses_sh = "quote_reminder.sh" in cmd and script_sh.exists()
            uses_python_prefix = cmd.startswith("python ") or cmd.startswith("python3 ") or cmd.startswith("PYTHON ") or cmd.startswith("PY ") or cmd.startswith("py ")
            uses_shell_prefix = cmd.startswith("bash ") or cmd.startswith("sh ")
            valid_invocation = False
            if uses_py:
                # Accept: direct execution (shebang) or python/python3
                valid_invocation = True
            if uses_sh:
                valid_invocation = True
            if has_date and valid_invocation:
                scores["run_log_single_command_correct"] = 1.0

    # REMINDER OUTPUT CHECK
    reminder_out_path = workspace / "output" / "reminder_2024-01-02.json"
    reminder_out = load_json_safe(reminder_out_path)
    if isinstance(reminder_out, dict) and quotes_valid and schedule and reminder_config and authors:
        expected_weekday = compute_weekday_name("2024-01-02")
        expected_author = schedule.get(expected_weekday or "", None)
        # first quote for expected author
        first_quote = None
        for q in quotes_list:
            if q.get("author") == expected_author:
                first_quote = q
                break
        try:
            # required fields in reminder
            fields_ok = all(k in reminder_out for k in ["date", "weekday", "author", "quote_text", "source_url", "scheduled_time", "message"])
            if fields_ok and expected_author and first_quote:
                conds = []
                conds.append(reminder_out.get("date") == "2024-01-02")
                conds.append(reminder_out.get("weekday") == expected_weekday)
                conds.append(reminder_out.get("author") == expected_author)
                conds.append(reminder_out.get("quote_text") == first_quote.get("quote_text"))
                conds.append(reminder_out.get("source_url") == first_quote.get("source_url"))
                # scheduled_time from config
                config_time = reminder_config.get("time")
                conds.append(reminder_out.get("scheduled_time") == config_time)
                # message format
                template = reminder_config.get("message_template", "")
                expected_message = template.replace("{author}", expected_author) + " " + first_quote.get("quote_text", "")
                conds.append(reminder_out.get("message") == expected_message)
                if all(conds):
                    scores["reminder_output_exists_and_valid"] = 1.0
        except Exception:
            pass

    # MEETING NOTES CHECKS
    meeting_notes_path = workspace / "output" / "next_steps_meeting_notes.md"
    meeting_notes_text = read_text_safe(meeting_notes_path)
    if meeting_notes_text is not None and agenda_headings:
        # Check headings and order: ensure all agenda headings appear in order
        m_lines = meeting_notes_text.splitlines()
        indices = []
        search_pos = 0
        ok_order = True
        for h in agenda_headings:
            found = -1
            for idx in range(search_pos, len(m_lines)):
                if m_lines[idx].strip() == h.strip():
                    found = idx
                    break
            if found == -1:
                ok_order = False
                break
            indices.append(found)
            search_pos = found + 1
        if ok_order:
            scores["meeting_notes_headings_order"] = 1.0

        # Analyze sections
        ranges = find_section_ranges_by_headings(meeting_notes_text, agenda_headings)
        # Sources summary: look for keywords in "Purpose" section content (or anywhere if not found)
        purpose_heading = None
        for h in agenda_headings:
            if h.strip().lower() == "purpose":
                purpose_heading = h
                break
        purpose_text = ""
        if purpose_heading and purpose_heading in ranges:
            start, end = ranges[purpose_heading]
            purpose_text = "\n".join(m_lines[start:end]).strip()
        else:
            purpose_text = meeting_notes_text

        keywords = ["reputable", "official", "foundation", "archive", "university", "press", "publisher", "museum", "library", "source"]
        if any(kw in purpose_text.lower() for kw in keywords):
            scores["meeting_notes_sources_summary"] = 1.0

        # Open questions: at least one question mark in that section
        openq_heading = None
        for h in agenda_headings:
            if h.strip().lower() == "open questions":
                openq_heading = h
                break
        if openq_heading and openq_heading in ranges:
            start, end = ranges[openq_heading]
            openq_text = "\n".join(m_lines[start:end]).strip()
            if "?" in openq_text:
                scores["meeting_notes_open_questions"] = 1.0

        # Action items: at least 3 lines with ISO date and owner indicator
        action_heading = None
        for h in agenda_headings:
            if h.strip().lower() == "action items":
                action_heading = h
                break
        if action_heading and action_heading in ranges:
            start, end = ranges[action_heading]
            action_lines = [ln for ln in m_lines[start:end] if ln.strip()]
            count = 0
            for ln in action_lines:
                has_date = re.search(r'\b\d{4}-\d{2}-\d{2}\b', ln) is not None
                has_owner = ('@' in ln) or (re.search(r'\bowner\s*:?', ln, flags=re.IGNORECASE) is not None)
                if has_date and has_owner:
                    count += 1
            if count >= 3:
                scores["meeting_notes_action_items_count"] = 1.0
            else:
                # Partial credit proportional to 3
                scores["meeting_notes_action_items_count"] = min(1.0, count / 3.0)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()