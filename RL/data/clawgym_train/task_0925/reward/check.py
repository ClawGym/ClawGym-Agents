import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class NewsletterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_mfs_div = False
        self.mfs_div_depth = 0
        self.location = None

        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = ""
        self.current_row = []
        self.sessions = []

        self.in_dnd_p = False
        self.dnd_text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and attrs_dict.get("id") == "military-family-sessions":
            self.in_mfs_div = True
            self.mfs_div_depth = 1
            self.location = attrs_dict.get("data-location") or ""
        elif self.in_mfs_div and tag == "div":
            self.mfs_div_depth += 1

        if self.in_mfs_div:
            if tag == "table" and ("class" in attrs_dict and "sessions" in attrs_dict.get("class", "").split()):
                self.in_table = True
            elif tag == "tbody" and self.in_table:
                self.in_tbody = True
            elif tag == "tr" and self.in_tbody:
                self.in_tr = True
                self.current_row = []
            elif tag == "td" and self.in_tr:
                self.in_td = True
                self.current_cell = ""
            elif tag == "p":
                cls = attrs_dict.get("class", "")
                classes = cls.split() if isinstance(cls, str) else []
                if "dnd-note" in classes or cls == "dnd-note":
                    self.in_dnd_p = True
                    self.dnd_text = ""

    def handle_endtag(self, tag):
        if self.in_mfs_div:
            if tag == "td" and self.in_td:
                self.in_td = False
                self.current_row.append(self.current_cell.strip())
                self.current_cell = ""
            elif tag == "tr" and self.in_tr:
                self.in_tr = False
                if len(self.current_row) == 3:
                    date, start, end = self.current_row
                    self.sessions.append({
                        "date": date.strip(),
                        "start": self._normalize_time(start.strip()),
                        "end": self._normalize_time(end.strip()),
                        "location": self.location or ""
                    })
                self.current_row = []
            elif tag == "tbody" and self.in_tbody:
                self.in_tbody = False
            elif tag == "table" and self.in_table:
                self.in_table = False
            elif tag == "p" and self.in_dnd_p:
                self.in_dnd_p = False

        if tag == "div" and self.in_mfs_div:
            self.mfs_div_depth -= 1
            if self.mfs_div_depth <= 0:
                self.in_mfs_div = False
                self.mfs_div_depth = 0

    def handle_data(self, data):
        if self.in_mfs_div and self.in_td:
            self.current_cell += data
        if self.in_mfs_div and self.in_dnd_p:
            self.dnd_text += data

    @staticmethod
    def _normalize_time(t: str) -> str:
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", t)
        if not m:
            return t.strip()
        h = int(m.group(1))
        mm = m.group(2)
        return f"{h:02d}:{mm}"

    def extract_dnd_window(self):
        m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", self.dnd_text)
        if not m:
            return None, None
        start = self._normalize_time(m.group(1))
        end = self._normalize_time(m.group(2))
        return start, end


def parse_newsletter(newsletter_html: str):
    parser = NewsletterParser()
    parser.feed(newsletter_html)
    dnd_start, dnd_end = parser.extract_dnd_window()
    return {
        "sessions": parser.sessions,
        "location": parser.location or "",
        "dnd_start": dnd_start,
        "dnd_end": dnd_end,
    }


def parse_config_dnd_and_timezone(config_text: str):
    timezone = None
    dnd_start = None
    dnd_end = None

    lines = config_text.splitlines()
    in_dnd = False
    dnd_indent = None

    for line in lines:
        tz_m = re.match(r'^\s*timezone:\s*"?([^"\n]+)"?\s*$', line)
        if tz_m:
            timezone = tz_m.group(1).strip()

        dnd_m = re.match(r'^(\s*)dnd:\s*(?:#.*)?$', line)
        if dnd_m:
            in_dnd = True
            dnd_indent = len(dnd_m.group(1))
            continue

        if in_dnd:
            indent_len = len(line) - len(line.lstrip(' '))
            if line.strip() and indent_len <= dnd_indent:
                in_dnd = False

            if in_dnd:
                start_m = re.match(r'^\s*start:\s*"?([^"\n]*)"?\s*$', line)
                end_m = re.match(r'^\s*end:\s*"?([^"\n]*)"?\s*$', line)
                if start_m:
                    dnd_start = start_m.group(1).strip()
                if end_m:
                    dnd_end = end_m.group(1).strip()

    return dnd_start, dnd_end, timezone


def load_students(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def filter_students_for_checkin(rows):
    if rows is None:
        return None
    allowed_status = {"deployed", "deploying", "recently_returned"}
    allowed_grades = {3, 4, 5}
    filtered = []
    for r in rows:
        try:
            grade_str = (r.get("grade") or "").strip()
            grade = int(grade_str)
        except Exception:
            return None
        status = (r.get("parent_deployment_status") or "").strip()
        if grade in allowed_grades and status in allowed_status:
            filtered.append({
                "student_id": (r.get("student_id") or "").strip(),
                "full_name": (r.get("full_name") or "").strip(),
                "preferred_name": (r.get("preferred_name") or "").strip(),
                "grade": str(grade),
                "service_branch": (r.get("service_branch") or "").strip(),
                "parent_deployment_status": status,
            })
    return filtered


def load_checkin_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None, None
            header = rows[0]
            data_rows = rows[1:]
            return header, data_rows
    except Exception:
        return None, None


def compare_sessions(expected_sessions, actual_sessions):
    if not isinstance(actual_sessions, list):
        return False
    if len(expected_sessions) != len(actual_sessions):
        return False
    for e, a in zip(expected_sessions, actual_sessions):
        if not isinstance(a, dict):
            return False
        if set(a.keys()) != {"date", "start", "end", "location"}:
            return False
        if e != a:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "sessions_json_matches_newsletter": 0.0,
        "config_dnd_matches_newsletter": 0.0,
        "checkin_files_exist_for_all_sessions": 0.0,
        "checkin_headers_correct": 0.0,
        "checkin_filtering_correct": 0.0,
        "scheduler_log_has_mute_lines": 0.0,
        "scheduler_log_has_checkin_lines": 0.0,
    }

    newsletter_path = workspace / "input" / "newsletter.html"
    students_csv_path = workspace / "input" / "students.csv"
    config_path = workspace / "config" / "app.yaml"
    sessions_json_path = workspace / "out" / "sessions.json"
    logs_path = workspace / "logs" / "scheduler_dry_run.log"

    newsletter_html = _read_text_safe(newsletter_path)
    parsed_news = None
    if newsletter_html:
        parsed_news = parse_newsletter(newsletter_html)

    sessions_json = _load_json_safe(sessions_json_path)

    if parsed_news and parsed_news["sessions"] is not None and sessions_json is not None:
        if compare_sessions(parsed_news["sessions"], sessions_json):
            scores["sessions_json_matches_newsletter"] = 1.0

    config_text = _read_text_safe(config_path)
    dnd_start_cfg = dnd_end_cfg = tz_cfg = None
    if config_text:
        dnd_start_cfg, dnd_end_cfg, tz_cfg = parse_config_dnd_and_timezone(config_text)

    if parsed_news and parsed_news["dnd_start"] and parsed_news["dnd_end"]:
        if dnd_start_cfg == parsed_news["dnd_start"] and dnd_end_cfg == parsed_news["dnd_end"]:
            scores["config_dnd_matches_newsletter"] = 1.0

    expected_sessions = parsed_news["sessions"] if parsed_news else None
    expected_dates = [s["date"] for s in expected_sessions] if expected_sessions else []

    students_rows, _ = load_students(students_csv_path)
    expected_filtered = filter_students_for_checkin(students_rows)

    expected_header = ["student_id", "full_name", "preferred_name", "grade", "service_branch", "parent_deployment_status"]
    expected_row_set = set()
    if expected_filtered is not None:
        for r in expected_filtered:
            expected_row_set.add(tuple(r.get(k, "") for k in expected_header))

    if expected_dates:
        exist_count = 0
        header_correct_count = 0
        filtering_correct_count = 0
        for date in expected_dates:
            checkin_path = workspace / "out" / f"checkin_{date}.csv"
            header, data_rows = load_checkin_csv(checkin_path)
            if header is not None:
                exist_count += 1
                if header == expected_header:
                    header_correct_count += 1
                    present_set = set()
                    for row in data_rows:
                        if len(row) != len(expected_header):
                            present_set = None
                            break
                        present_set.add(tuple(cell.strip() for cell in row))
                    if present_set is not None and expected_row_set is not None and present_set == expected_row_set:
                        filtering_correct_count += 1
        total = len(expected_dates)
        if total > 0:
            scores["checkin_files_exist_for_all_sessions"] = exist_count / total
            scores["checkin_headers_correct"] = header_correct_count / total
            scores["checkin_filtering_correct"] = filtering_correct_count / total

    logs_text = _read_text_safe(logs_path)
    if expected_dates and logs_text:
        lines = [ln.strip() for ln in logs_text.splitlines() if ln.strip()]
        mute_ok = 0
        checkin_ok = 0
        total = len(expected_dates)
        expected_N = len(expected_filtered) if expected_filtered is not None else None

        for date in expected_dates:
            checkin_file = workspace / "out" / f"checkin_{date}.csv"
            header, data_rows = load_checkin_csv(checkin_file)
            N = None
            if header == expected_header and data_rows is not None:
                N = len(data_rows)
            elif expected_N is not None:
                N = expected_N

            mute_line = None
            if dnd_start_cfg and dnd_end_cfg and tz_cfg:
                mute_line = f"Mute notifications from {dnd_start_cfg} to {dnd_end_cfg} on {date} (timezone {tz_cfg})"
            checkin_line = None
            if N is not None:
                checkin_line = f"Would generate check-in sheet: out/checkin_{date}.csv: {N} students"

            if mute_line and mute_line in lines:
                mute_ok += 1
            if checkin_line and checkin_line in lines:
                checkin_ok += 1

        if total > 0:
            scores["scheduler_log_has_mute_lines"] = mute_ok / total
            scores["scheduler_log_has_checkin_lines"] = checkin_ok / total

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()