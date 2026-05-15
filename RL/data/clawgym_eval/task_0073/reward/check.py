import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime, date
from html.parser import HTMLParser

# Helper functions

def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_safe(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return None
        return items
    except Exception:
        return None

def read_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            rows = [ {k: (v if v is not None else "") for k, v in row.items()} for row in reader ]
            return headers, rows
    except Exception:
        return None, None

def parse_date_safe(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def within_inclusive(target: str, start: str, end: str) -> bool:
    dt = parse_date_safe(target)
    ds = parse_date_safe(start)
    de = parse_date_safe(end)
    if dt is None or ds is None or de is None:
        return False
    return ds <= dt <= de

def strip_trailing_punct(s: str) -> str:
    # Remove a single trailing period, exclamation, or question mark
    return s.rstrip().rstrip(".!?").rstrip()

def extract_as_of_date(md_text: str) -> str | None:
    m = re.search(r"Report As-Of Date:\s*(\d{4}-\d{2}-\d{2})", md_text)
    if m:
        return m.group(1)
    return None

def parse_meeting_minutes(md_text: str):
    # Returns as_of_date, actions list of dicts with fields: section, owner, due_date, description (full line without trailing punctuation), raw_line
    as_of = extract_as_of_date(md_text)
    actions = []
    current_section = None
    for line in md_text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            current_section = line_stripped[3:].strip()
            continue
        if line_stripped.startswith("- "):
            bullet = line_stripped[2:].strip()
            # Extract owner (before ' to ')
            owner_match = re.match(r"^(.+?)\s+to\s+", bullet)
            owner = owner_match.group(1).strip() if owner_match else ""
            # Extract due date
            dd_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", bullet)
            due_date = dd_match.group(1) if dd_match else ""
            description = strip_trailing_punct(bullet)
            actions.append({
                "section": current_section if current_section else "",
                "owner": owner,
                "due_date": due_date,
                "description": description,
                "raw_line": bullet,
            })
    return as_of, actions

class ProgramHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.program_date = None
        self._in_program_date = False
        self._in_schedule_ul = False
        self._in_li = False
        self._current_li_time = None
        self._current_li_text_parts = []
        self.schedule_items = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "p" and attrs_dict.get("id") == "program-date":
            self._in_program_date = True
        if tag.lower() == "ul" and attrs_dict.get("id") == "schedule":
            self._in_schedule_ul = True
        if tag.lower() == "li" and self._in_schedule_ul:
            self._in_li = True
            self._current_li_time = attrs_dict.get("data-time", "").strip()
            self._current_li_text_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "p" and self._in_program_date:
            self._in_program_date = False
        if tag.lower() == "ul" and self._in_schedule_ul:
            self._in_schedule_ul = False
        if tag.lower() == "li" and self._in_li:
            text = "".join(self._current_li_text_parts).strip()
            self.schedule_items.append((self._current_li_time, text))
            self._in_li = False

    def handle_data(self, data):
        if self._in_program_date:
            m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", data)
            if m:
                self.program_date = m.group(1)
        if self._in_li:
            self._current_li_text_parts.append(data)

def parse_program_html(html_text: str):
    parser = ProgramHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:
        # fallback regex
        pass
    return parser.program_date, parser.schedule_items

def build_expected_actions_and_flags(workspace: Path):
    # Load inputs
    minutes_path = workspace / "input" / "meeting_minutes.md"
    contacts_path = workspace / "input" / "contacts.csv"
    budget_path = workspace / "input" / "budget.json"

    md_text = read_text_safe(minutes_path)
    headers, contacts_rows = read_csv_dicts_safe(contacts_path)
    budget_json = load_json_safe(budget_path)

    if not md_text or contacts_rows is None or budget_json is None:
        return None

    as_of, actions = parse_meeting_minutes(md_text)
    # Build contacts map
    contacts_map = {}
    for row in contacts_rows:
        name = (row.get("Name") or "").strip()
        team = (row.get("Team") or "").strip()
        avail_start = (row.get("AvailabilityStart") or "").strip()
        avail_end = (row.get("AvailabilityEnd") or "").strip()
        if name:
            contacts_map[name] = {
                "team": team,
                "start": avail_start,
                "end": avail_end,
            }
    # Budget items
    budget_items = []
    try:
        items = budget_json.get("items", [])
        for it in items:
            nm = str(it.get("name", "")).strip()
            if nm:
                budget_items.append(nm.lower())
    except Exception:
        budget_items = []

    expected_rows = []
    for a in actions:
        owner = a["owner"]
        due_date = a["due_date"]
        team = ""
        availability_flag = "UNKNOWN"
        if owner in contacts_map:
            info = contacts_map[owner]
            team = info["team"]
            availability_flag = "OK" if within_inclusive(due_date, info["start"], info["end"]) else "OUT_OF_WINDOW"
        # budget_related
        line_lc = a["description"].lower()
        budget_related = "no"
        if "budget:" in line_lc:
            budget_related = "yes"
        else:
            for b in budget_items:
                if b and b in line_lc:
                    budget_related = "yes"
                    break
        expected_rows.append({
            "source": "meeting_minutes.md",
            "section": a["section"],
            "task_description": a["description"],
            "owner": owner,
            "due_date": due_date,
            "team": team,
            "availability_flag": availability_flag,
            "budget_related": budget_related,
        })
    return {
        "as_of": as_of,
        "expected_rows": expected_rows,
        "budget_json": budget_json
    }

def extract_section(text: str, section_name: str, all_sections: list[str]) -> str:
    if not text:
        return ""
    text_l = text.lower()
    start_key = section_name.lower()
    start_idx = text_l.find(start_key)
    if start_idx == -1:
        return ""
    end_idx = len(text)
    for other in all_sections:
        if other.lower() == start_key:
            continue
        oi = text_l.find(other.lower(), start_idx + len(start_key))
        if oi != -1 and oi < end_idx:
            end_idx = oi
    return text[start_idx:end_idx]

def section_contains_count(section_text: str, label: str, expected_count: int) -> bool:
    if not section_text:
        return False
    pat1 = re.compile(rf"(?i)\b{re.escape(label)}\b[^0-9]{{0,15}}\b{expected_count}\b")
    pat2 = re.compile(rf"(?i)\b{expected_count}\b[^0-9]{{0,15}}\b{re.escape(label)}\b")
    return bool(pat1.search(section_text)) or bool(pat2.search(section_text))

def compute_budget_totals_and_shortfalls(budget_json: dict):
    total_requested = 0
    total_approved = 0
    shortfalls = []
    try:
        for it in budget_json.get("items", []):
            req = float(it.get("requested", 0))
            app = float(it.get("approved", 0))
            name = str(it.get("name", ""))
            total_requested += req
            total_approved += app
            if app < req:
                shortfalls.append((name, req - app))
    except Exception:
        return None
    return total_requested, total_approved, shortfalls

def load_past_tasks(workspace: Path):
    path = workspace / "input" / "past_tasks.jsonl"
    items = load_jsonl_safe(path)
    return items

def count_statuses(tasks: list[dict]) -> dict:
    counts = {"done": 0, "in_progress": 0, "blocked": 0}
    for t in tasks:
        s = (t.get("status") or "").strip()
        if s in counts:
            counts[s] += 1
    return counts

def find_overdue(tasks: list[dict], as_of: str) -> list[dict]:
    as_of_date = parse_date_safe(as_of) if as_of else None
    if as_of_date is None:
        return []
    overdue = []
    for t in tasks:
        due = parse_date_safe(t.get("due_date", ""))
        status = (t.get("status") or "").strip()
        if due is None:
            continue
        if due < as_of_date and status != "done":
            overdue.append(t)
    return overdue

def load_program(workspace: Path):
    html_text = read_text_safe(workspace / "input" / "program.html")
    if not html_text:
        return None, None
    program_date, schedule_items = parse_program_html(html_text)
    return program_date, schedule_items

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "task_breakdown_columns": 0.0,
        "task_breakdown_row_count": 0.0,
        "task_breakdown_rows_match_expected": 0.0,
        "status_update_overview_dates": 0.0,
        "status_update_budget_summary": 0.0,
        "status_update_past_tasks": 0.0,
        "status_update_upcoming_program": 0.0,
        "status_update_new_actions_summary": 0.0,
    }

    # Prepare expected
    expected_pack = build_expected_actions_and_flags(workspace)
    output_csv_path = workspace / "output" / "task_breakdown.csv"
    output_md_path = workspace / "output" / "status_update.md"

    # CSV checks
    expected_columns = [
        "source",
        "section",
        "task_description",
        "owner",
        "due_date",
        "team",
        "availability_flag",
        "budget_related",
    ]
    headers, actual_rows = read_csv_dicts_safe(output_csv_path)
    if headers is not None and actual_rows is not None:
        # Columns check: at least required columns present
        header_set = set([h.strip() for h in headers])
        if all(col in header_set for col in expected_columns):
            scores["task_breakdown_columns"] = 1.0

        # Prepare expected and compare
        if expected_pack is not None:
            expected_rows = expected_pack["expected_rows"]
            # Row count
            if len(actual_rows) == len(expected_rows):
                scores["task_breakdown_row_count"] = 1.0

            # Compare content by key (owner, due_date, section)
            expected_map = {}
            for r in expected_rows:
                key = (r["owner"], r["due_date"], r["section"])
                expected_map[key] = r
            actual_map = {}
            for r in actual_rows:
                # normalize strip
                r_norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                # Defensive: only consider required columns
                try:
                    key = (r_norm.get("owner", ""), r_norm.get("due_date", ""), r_norm.get("section", ""))
                except Exception:
                    continue
                actual_map[key] = r_norm

            all_match = True
            for key, exp in expected_map.items():
                act = actual_map.get(key)
                if act is None:
                    all_match = False
                    break
                for col in expected_columns:
                    av = (act.get(col, "") or "").strip()
                    ev = (exp.get(col, "") or "").strip()
                    if av != ev:
                        all_match = False
                        break
                if not all_match:
                    break
            if all_match and len(actual_map) == len(expected_map):
                scores["task_breakdown_rows_match_expected"] = 1.0
        else:
            # If inputs couldn't be loaded, we cannot validate content
            scores["task_breakdown_row_count"] = 0.0
            scores["task_breakdown_rows_match_expected"] = 0.0
    # MD checks
    md_text = read_text_safe(output_md_path)
    if md_text:
        sections = ["Overview", "Budget Summary", "Past Tasks Status", "Upcoming Program", "New Action Items Summary"]
        # Overview: dates
        as_of = expected_pack["as_of"] if expected_pack else None
        program_date, schedule_items = load_program(workspace)
        overview_text = extract_section(md_text, "Overview", sections)
        if overview_text and as_of and program_date:
            if (as_of in overview_text) and (program_date in overview_text):
                scores["status_update_overview_dates"] = 1.0

        # Budget Summary: totals and shortfalls
        budget_json = expected_pack["budget_json"] if expected_pack else None
        budget_text = extract_section(md_text, "Budget Summary", sections)
        if budget_json and budget_text:
            totals = compute_budget_totals_and_shortfalls(budget_json)
            if totals is not None:
                total_req, total_app, shortfalls = totals
                # Check totals presence
                totals_ok = (str(int(total_req)) in budget_text) and (str(int(total_app)) in budget_text)
                # Check shortfalls presence
                shortfalls_ok = True
                for name, short in shortfalls:
                    # allow integers only display
                    short_str = str(int(short)) if float(short).is_integer() else str(short)
                    if (name.lower() not in budget_text.lower()) or (short_str not in budget_text):
                        shortfalls_ok = False
                        break
                if totals_ok and shortfalls_ok:
                    scores["status_update_budget_summary"] = 1.0

        # Past Tasks Status: counts and overdue listing
        past_tasks = load_past_tasks(workspace)
        pts_text = extract_section(md_text, "Past Tasks Status", sections)
        if expected_pack and past_tasks is not None and pts_text:
            # Counts
            counts = count_statuses(past_tasks)
            counts_ok = (
                section_contains_count(pts_text, "done", counts.get("done", 0)) and
                section_contains_count(pts_text, "in_progress", counts.get("in_progress", 0)) and
                section_contains_count(pts_text, "blocked", counts.get("blocked", 0))
            )
            # Overdue tasks (title, owner, due_date, status)
            overdue = find_overdue(past_tasks, expected_pack["as_of"])
            overdue_ok = True
            for t in overdue:
                title = str(t.get("title", ""))
                owner = str(t.get("owner", ""))
                due_date = str(t.get("due_date", ""))
                status = str(t.get("status", ""))
                subok = (title in pts_text) and (owner in pts_text) and (due_date in pts_text) and (status in pts_text)
                if not subok:
                    overdue_ok = False
                    break
            if counts_ok and overdue_ok:
                scores["status_update_past_tasks"] = 1.0

        # Upcoming Program: first three items
        upc_text = extract_section(md_text, "Upcoming Program", sections)
        if schedule_items is not None and upc_text:
            first_three = schedule_items[:3]
            upc_ok = True
            for t, label in first_three:
                if (t not in upc_text) or (label not in upc_text):
                    upc_ok = False
                    break
            if upc_ok:
                scores["status_update_upcoming_program"] = 1.0

        # New Action Items Summary: number and out-of-window items
        nai_text = extract_section(md_text, "New Action Items Summary", sections)
        if expected_pack and nai_text:
            exp_count = len(expected_pack["expected_rows"])
            count_ok = bool(re.search(rf"\b{exp_count}\b", nai_text))
            # out-of-window items
            oow = [r for r in expected_pack["expected_rows"] if r.get("availability_flag") == "OUT_OF_WINDOW"]
            oow_ok = True
            for r in oow:
                owner = r.get("owner", "")
                due = r.get("due_date", "")
                if not (owner in nai_text and due in nai_text):
                    oow_ok = False
                    break
            if count_ok and oow_ok:
                scores["status_update_new_actions_summary"] = 1.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()