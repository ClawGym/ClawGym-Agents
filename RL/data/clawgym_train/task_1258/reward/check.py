import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json_safe(path: Path, data: dict) -> bool:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _parse_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None


class _NewsletterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_session = False
        self.current = None
        self.sessions = []
        self._current_tag = None
        self._current_attrs = {}

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: v for k, v in attrs}
        self._current_tag = tag
        self._current_attrs = attrs_dict
        if tag == "article" and "class" in attrs_dict and "session" in attrs_dict.get("class", ""):
            self.in_session = True
            self.current = {
                "date": None,
                "start_time": None,
                "theme": None,
                "venue": None,
                "capacity": None,
            }
        if self.in_session and tag == "time":
            # Capture machine-readable date
            dt = attrs_dict.get("datetime")
            if self.current is not None:
                self.current["date"] = dt

    def handle_endtag(self, tag):
        if tag == "article" and self.in_session:
            # finalize
            if self.current and all(v is not None for v in self.current.values()):
                self.sessions.append(self.current)
            self.in_session = False
            self.current = None
        self._current_tag = None
        self._current_attrs = {}

    def handle_data(self, data):
        if not self.in_session or self.current is None:
            return
        text = data.strip()
        if not text:
            return
        if self._current_tag == "span" and self._current_attrs.get("class") == "start":
            self.current["start_time"] = text
        elif self._current_tag == "h3" and self._current_attrs.get("class") == "theme":
            self.current["theme"] = text
        elif self._current_tag == "span" and self._current_attrs.get("class") == "venue":
            self.current["venue"] = text
        elif self._current_tag == "span" and self._current_attrs.get("class") == "capacity":
            # Expect "Capacity: 12"
            m = re.search(r"(\d+)", text)
            if m:
                self.current["capacity"] = int(m.group(1))


def _parse_newsletter_sessions(path: Path) -> Optional[List[Dict[str, str]]]:
    html = _read_text_safe(path)
    if html is None:
        return None
    parser = _NewsletterParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    sessions = parser.sessions
    # Validate
    result = []
    for s in sessions:
        if not all(k in s and s[k] is not None for k in ("date", "start_time", "theme", "venue", "capacity")):
            return None
        result.append(
            {
                "date": s["date"],
                "start_time": s["start_time"],
                "theme": s["theme"],
                "venue": s["venue"],
                "capacity": str(int(s["capacity"])),
            }
        )
    return result


def _compare_schedule_with_html(schedule_path: Path, html_path: Path) -> Tuple[bool, bool]:
    """
    Returns (header_ok, rows_match) where:
    - header_ok: schedule header exactly ['date','start_time','theme','venue','capacity']
    - rows_match: rows match the sessions parsed from HTML (order-insensitive)
    """
    parsed = _parse_csv_dicts(schedule_path)
    if parsed is None:
        return (False, False)
    header, rows = parsed
    expected_header = ['date', 'start_time', 'theme', 'venue', 'capacity']
    header_ok = (header == expected_header)
    expected_rows = _parse_newsletter_sessions(html_path)
    if expected_rows is None:
        return (header_ok, False)
    # Normalize
    def norm_row(r):
        return {
            'date': r.get('date', '').strip(),
            'start_time': r.get('start_time', '').strip(),
            'theme': r.get('theme', '').strip(),
            'venue': r.get('venue', '').strip(),
            'capacity': r.get('capacity', '').strip(),
        }
    norm_rows = [norm_row(r) for r in rows]
    # Verify capacity integers
    for r in norm_rows:
        try:
            int(r['capacity'])
        except Exception:
            return (header_ok, False)
    norm_expected = [norm_row(r) for r in expected_rows]
    # Compare as sets (order-insensitive)
    set_rows = {tuple((k, v) for k, v in sorted(r.items())) for r in norm_rows}
    set_expected = {tuple((k, v) for k, v in sorted(r.items())) for r in norm_expected}
    rows_match = (set_rows == set_expected)
    return (header_ok, rows_match)


def _run_validator_capture(workspace: Path) -> Optional[str]:
    """
    Run input/validate_attendance.py with output/schedule.csv and input/attendance.csv
    Capture both stdout and stderr merged in order and return the combined text.
    """
    script = workspace / "input" / "validate_attendance.py"
    attendance = workspace / "input" / "attendance.csv"
    schedule = workspace / "output" / "schedule.csv"
    if not script.exists() or not attendance.exists() or not schedule.exists():
        return None
    try:
        # Merge stderr into stdout to preserve order
        proc = subprocess.run(
            [sys.executable, str(script), "--attendance", str(attendance), "--schedule", str(schedule)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(workspace),
            text=True,
            encoding="utf-8",
        )
        return proc.stdout
    except Exception:
        return None


def _read_validation_log(path: Path) -> Optional[str]:
    return _read_text_safe(path)


def _parse_attendance_counts(path: Path) -> Optional[Tuple[Dict[str, int], int]]:
    """
    Returns (counts_by_date, unique_attendee_count)
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            counts: Dict[str, int] = {}
            unique = set()
            for row in reader:
                d = (row.get("date") or "").strip()
                n = (row.get("name") or "").strip()
                if not d or not n:
                    return None
                counts[d] = counts.get(d, 0) + 1
                unique.add(n)
            return counts, len(unique)
    except Exception:
        return None


def _parse_schedule_csv(path: Path) -> Optional[Dict[str, int]]:
    parsed = _parse_csv_dicts(path)
    if parsed is None:
        return None
    header, rows = parsed
    if header != ['date', 'start_time', 'theme', 'venue', 'capacity']:
        return None
    sched = {}
    for r in rows:
        d = (r.get("date") or "").strip()
        c = (r.get("capacity") or "").strip()
        try:
            cap = int(c)
        except Exception:
            return None
        if not d:
            return None
        sched[d] = cap
    return sched


def _compute_metrics(attendance_path: Path, schedule_path: Path) -> Optional[dict]:
    att = _parse_attendance_counts(attendance_path)
    sched = _parse_schedule_csv(schedule_path)
    if att is None or sched is None:
        return None
    counts_by_date, unique_count = att
    sessions_scheduled = len(sched)
    sessions_with_attendance = len(counts_by_date)
    total = sum(counts_by_date.values())
    avg = (total / sessions_with_attendance) if sessions_with_attendance else 0.0
    over_capacity_dates = sorted([d for d, cnt in counts_by_date.items() if d in sched and cnt > sched[d]])
    missing_from_schedule_dates = sorted([d for d in counts_by_date if d not in sched])
    return {
        "sessions_scheduled": sessions_scheduled,
        "sessions_with_attendance": sessions_with_attendance,
        "unique_attendees": unique_count,
        "average_attendance": avg,
        "over_capacity_dates": over_capacity_dates,
        "missing_from_schedule_dates": missing_from_schedule_dates,
    }


def _find_sections_indices(lines: List[str], titles: List[str]) -> Optional[List[Tuple[int, int, str]]]:
    """
    Find sections by titles in order. Accept lines that are exactly the title with optional colon,
    optionally prefixed by Markdown heading markers (#, ##, etc.).
    Returns list of tuples (start_idx, end_idx, title).
    """
    indices = []
    start_positions = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        for t in titles:
            # Construct patterns to match headings like "## Title:", "Title:" or "Title"
            if re.fullmatch(r"(#+\s*)?"+re.escape(t)+r":?", stripped, flags=0):
                # Avoid overwriting if already found
                if t not in start_positions:
                    start_positions[t] = i
    # Verify order
    positions = []
    last = -1
    for t in titles:
        if t not in start_positions:
            return None
        idx = start_positions[t]
        if idx <= last:
            return None
        positions.append(idx)
        last = idx
    # Compute end indices
    sections = []
    for j, t in enumerate(titles):
        start = positions[j]
        end = positions[j+1] if j+1 < len(positions) else len(lines)
        sections.append((start, end, t))
    return sections


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        m = re.match(r"\s*-\s+(.*)", ln.strip())
        if m:
            bullets.append(m.group(1).strip())
    return bullets


def _parse_minutes_md(path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    sections = {
        "Discussion": [],
        "Decisions": [],
        "Tasks": [],
    }
    titles = ["Discussion", "Decisions", "Tasks"]
    idxs = _find_sections_indices(lines, titles)
    if idxs is None:
        return None
    for (start, end, title) in idxs:
        content_lines = lines[start+1:end]
        sections[title] = content_lines
    return sections


def _parse_unchecked_tasks(task_lines: List[str]) -> List[Dict[str, str]]:
    tasks = []
    for ln in task_lines:
        if "[ ]" in ln:
            # Extract description, owner, due date
            # Example: - [ ] Coordinate larger room ... (Owner: Emma; Due: 2024-09-20)
            desc_part = ln
            # Remove leading bullet and checkbox
            m = re.match(r"\s*-\s*\[\s\]\s*(.*)", ln.strip())
            desc = m.group(1).strip() if m else ln.strip()
            # Extract owner and due
            owner_m = re.search(r"Owner:\s*([^;()]+)", ln)
            due_m = re.search(r"Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", ln)
            owner = owner_m.group(1).strip() if owner_m else ""
            due = due_m.group(1).strip() if due_m else ""
            tasks.append({"description": desc, "owner": owner, "due": due})
    return tasks


def _contains_number(text: str, value: float, tol: float = 1e-2) -> bool:
    # Find all numbers (integers or floats) in text
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    for n in nums:
        try:
            if abs(float(n) - value) <= tol:
                return True
            # For integer match, also check exact int equality if value is integer
            if float(int(float(n))) == value and abs(float(n) - int(float(n))) < tol:
                return True
        except Exception:
            continue
    return False


def _parse_validation_summary_from_log(log_text: str) -> Dict[str, Dict[str, str]]:
    """
    Parse validation.log to extract per-date counts and capacities from DATE lines,
    and list of WARNING/ERROR lines. Return dict with:
    {
        "date_info": { date: {"count": "N", "capacity": "C"} },
        "warnings": [{"date": d, "text": line}],
        "errors": [{"date": d, "text": line}],
    }
    """
    date_info: Dict[str, Dict[str, str]] = {}
    warnings = []
    errors = []
    for line in log_text.splitlines():
        line_stripped = line.strip()
        m_date = re.match(r"DATE\s+(\d{4}-\d{2}-\d{2})\s+COUNT\s+(\d+)\s+CAPACITY\s+(.+)", line_stripped)
        if m_date:
            d = m_date.group(1)
            cnt = m_date.group(2)
            cap = m_date.group(3)
            date_info[d] = {"count": cnt, "capacity": cap}
        m_warn = re.match(r"WARNING\s+(\d{4}-\d{2}-\d{2})\s+", line_stripped)
        if m_warn:
            warnings.append({"date": m_warn.group(1), "text": line_stripped})
        m_err = re.match(r"ERROR\s+(\d{4}-\d{2}-\d{2})\s+", line_stripped)
        if m_err:
            errors.append({"date": m_err.group(1), "text": line_stripped})
    return {"date_info": date_info, "warnings": warnings, "errors": errors}


def _parse_meeting_notes_sections(path: Path, expected_titles: List[str]) -> Optional[Dict[str, List[str]]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    idxs = _find_sections_indices(lines, expected_titles)
    if idxs is None:
        return None
    sections_content: Dict[str, List[str]] = {}
    for (start, end, title) in idxs:
        sections_content[title] = lines[start+1:end]
    return sections_content


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_csv_header_correct": 0.0,
        "schedule_csv_rows_match_html": 0.0,
        "validation_log_matches_command_output": 0.0,
        "meeting_notes_sections_and_order": 0.0,
        "meeting_notes_discussion_bullets_exact": 0.0,
        "meeting_notes_decisions_bullets_exact": 0.0,
        "meeting_notes_action_items_unchecked_with_details": 0.0,
        "meeting_notes_summary_numbers_correct": 0.0,
        "meeting_notes_capacity_summary_from_log": 0.0,
        "metrics_json_schema": 0.0,
        "metrics_json_values_correct": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"

    # 1) Schedule CSV checks
    schedule_csv = output_dir / "schedule.csv"
    newsletter_html = input_dir / "newsletter.html"
    if schedule_csv.exists() and newsletter_html.exists():
        header_ok, rows_match = _compare_schedule_with_html(schedule_csv, newsletter_html)
        scores["schedule_csv_header_correct"] = 1.0 if header_ok else 0.0
        scores["schedule_csv_rows_match_html"] = 1.0 if rows_match else 0.0
    else:
        scores["schedule_csv_header_correct"] = 0.0
        scores["schedule_csv_rows_match_html"] = 0.0

    # 2) Validation log content verification (re-run deterministically)
    validation_log_path = output_dir / "validation.log"
    expected_log = _run_validator_capture(workspace)
    actual_log = _read_validation_log(validation_log_path) if validation_log_path.exists() else None
    if expected_log is not None and actual_log is not None:
        # Compare exact including newlines
        scores["validation_log_matches_command_output"] = 1.0 if expected_log == actual_log else 0.0
    else:
        scores["validation_log_matches_command_output"] = 0.0

    # 3) Meeting notes checks
    meeting_notes_path = output_dir / "meeting_notes.md"
    expected_titles = ["Summary", "Key Discussion Points", "Decisions", "Action Items", "Capacity Check Summary"]
    sections_ok = False
    sections_content = None
    if meeting_notes_path.exists():
        sections_content = _parse_meeting_notes_sections(meeting_notes_path, expected_titles)
        if sections_content is not None:
            sections_ok = True
    scores["meeting_notes_sections_and_order"] = 1.0 if sections_ok else 0.0

    # Compare Discussion bullets
    minutes = _parse_minutes_md(input_dir / "knitting_minutes.md") if (input_dir / "knitting_minutes.md").exists() else None
    if sections_ok and minutes is not None:
        discussion_expected = _extract_bullets(minutes["Discussion"])
        decisions_expected = _extract_bullets(minutes["Decisions"])
        # Extract bullets from meeting notes
        discussion_bullets = _extract_bullets(sections_content.get("Key Discussion Points", []))
        decisions_bullets = _extract_bullets(sections_content.get("Decisions", []))
        # Exact match as sets and counts
        if set(discussion_bullets) == set(discussion_expected) and len(discussion_bullets) == len(discussion_expected):
            scores["meeting_notes_discussion_bullets_exact"] = 1.0
        else:
            scores["meeting_notes_discussion_bullets_exact"] = 0.0
        if set(decisions_bullets) == set(decisions_expected) and len(decisions_bullets) == len(decisions_expected):
            scores["meeting_notes_decisions_bullets_exact"] = 1.0
        else:
            scores["meeting_notes_decisions_bullets_exact"] = 0.0
        # Action items: only unchecked tasks, include description, owner, due
        unchecked_tasks_input = _parse_unchecked_tasks(minutes["Tasks"])
        action_items_lines = sections_content.get("Action Items", [])
        action_bullets = _extract_bullets(action_items_lines)
        # For each expected unchecked task, require presence of description substring, owner, and due date
        action_ok = True
        if len(action_bullets) != len(unchecked_tasks_input):
            action_ok = False
        else:
            for t in unchecked_tasks_input:
                # Find matching bullet that includes description, owner, and due
                desc_present = False
                for b in action_bullets:
                    has_desc = t["description"].split(" (Owner")[0].strip() in b
                    has_owner = t["owner"] in b if t["owner"] else True
                    has_due = t["due"] in b if t["due"] else True
                    if has_desc and has_owner and has_due:
                        desc_present = True
                        break
                if not desc_present:
                    action_ok = False
                    break
        scores["meeting_notes_action_items_unchecked_with_details"] = 1.0 if action_ok else 0.0
        # Summary numbers
        att_counts = _parse_attendance_counts(input_dir / "attendance.csv") if (input_dir / "attendance.csv").exists() else None
        summary_lines = sections_content.get("Summary", [])
        summary_text = " ".join([ln.strip() for ln in summary_lines])
        summary_ok = False
        if att_counts is not None:
            counts_by_date, unique_attendees = att_counts
            sessions_with_attendance = len(counts_by_date)
            average_attendance = (sum(counts_by_date.values()) / sessions_with_attendance) if sessions_with_attendance else 0.0
            # Check digits present
            has_sessions = _contains_number(summary_text, float(sessions_with_attendance))
            has_unique = _contains_number(summary_text, float(unique_attendees))
            # Allow 2 decimal average or integer if whole number
            has_avg = _contains_number(summary_text, float(f"{average_attendance:.2f}")) or _contains_number(summary_text, float(average_attendance))
            summary_ok = has_sessions and has_unique and has_avg
        scores["meeting_notes_summary_numbers_correct"] = 1.0 if summary_ok else 0.0
        # Capacity Check Summary bullets from validation.log
        cap_summary_lines = sections_content.get("Capacity Check Summary", [])
        cap_bullets = _extract_bullets(cap_summary_lines)
        cap_ok = False
        if actual_log is not None:
            parsed_log = _parse_validation_summary_from_log(actual_log)
            date_info = parsed_log["date_info"]
            warn_lines = parsed_log["warnings"]
            err_lines = parsed_log["errors"]
            expected_bullets = []
            for w in warn_lines:
                d = w["date"]
                info = date_info.get(d, {})
                cnt = info.get("count", "N/A")
                cap = info.get("capacity", "N/A")
                expected_bullets.append(f"[WARNING] DATE: {d} — attendees {cnt}; capacity {cap}")
            for e in err_lines:
                d = e["date"]
                info = date_info.get(d, {})
                cnt = info.get("count", "N/A")
                cap = info.get("capacity", "N/A")
                expected_bullets.append(f"[ERROR] DATE: {d} — attendees {cnt}; capacity {cap}")
            # Normalize bullets by removing leading '-' and spaces
            def norm(b: str) -> str:
                return b.lstrip("-").strip()
            cap_ok = set(map(norm, cap_bullets)) == set(expected_bullets) and len(cap_bullets) == len(expected_bullets)
        scores["meeting_notes_capacity_summary_from_log"] = 1.0 if cap_ok else 0.0
    else:
        # meeting notes missing or malformed
        scores["meeting_notes_discussion_bullets_exact"] = 0.0
        scores["meeting_notes_decisions_bullets_exact"] = 0.0
        scores["meeting_notes_action_items_unchecked_with_details"] = 0.0
        scores["meeting_notes_summary_numbers_correct"] = 0.0
        scores["meeting_notes_capacity_summary_from_log"] = 0.0

    # 4) Metrics JSON checks
    metrics_path = output_dir / "metrics.json"
    metrics = _load_json_safe(metrics_path) if metrics_path.exists() else None
    schema_ok = False
    values_ok = False
    if metrics is not None and isinstance(metrics, dict):
        required_fields = {
            "sessions_scheduled": int,
            "sessions_with_attendance": int,
            "unique_attendees": int,
            "average_attendance": (int, float),
            "over_capacity_dates": list,
            "missing_from_schedule_dates": list,
        }
        schema_ok = True
        for k, typ in required_fields.items():
            if k not in metrics:
                schema_ok = False
                break
            if not isinstance(metrics[k], typ):
                schema_ok = False
                break
        if schema_ok:
            # Validate lists content types
            if not all(isinstance(x, str) for x in metrics.get("over_capacity_dates", [])):
                schema_ok = False
            if not all(isinstance(x, str) for x in metrics.get("missing_from_schedule_dates", [])):
                schema_ok = False
    scores["metrics_json_schema"] = 1.0 if schema_ok else 0.0
    if schema_ok:
        computed = _compute_metrics(input_dir / "attendance.csv", output_dir / "schedule.csv")
        if computed is not None:
            # Compare values (average_attendance tolerance)
            try:
                vals_match = True
                if metrics["sessions_scheduled"] != computed["sessions_scheduled"]:
                    vals_match = False
                if metrics["sessions_with_attendance"] != computed["sessions_with_attendance"]:
                    vals_match = False
                if metrics["unique_attendees"] != computed["unique_attendees"]:
                    vals_match = False
                if abs(float(metrics["average_attendance"]) - float(computed["average_attendance"])) > 1e-6:
                    vals_match = False
                if sorted(metrics["over_capacity_dates"]) != computed["over_capacity_dates"]:
                    vals_match = False
                if sorted(metrics["missing_from_schedule_dates"]) != computed["missing_from_schedule_dates"]:
                    vals_match = False
                values_ok = vals_match
            except Exception:
                values_ok = False
    scores["metrics_json_values_correct"] = 1.0 if values_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()