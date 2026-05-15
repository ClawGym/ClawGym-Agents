import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser


class TopProblemsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_target_table = False
        self.current_table_id = None
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self.current_table_id = attrs_dict.get("id")
            self.in_target_table = (self.current_table_id == "top-problems")
        elif self.in_target_table and tag == "thead":
            self.in_thead = True
        elif self.in_target_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_target_table and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_target_table and tag == "td":
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_target_table = False
            self.current_table_id = None
        elif self.in_target_table and tag == "thead":
            self.in_thead = False
        elif self.in_target_table and tag == "tbody":
            self.in_tbody = False
        elif self.in_target_table and tag == "td":
            if self.in_td:
                cell_text = "".join(self.current_cell).strip()
                self.current_row.append(cell_text)
            self.in_td = False
        elif self.in_target_table and tag == "tr":
            if self.in_tr:
                if self.in_tbody and self.current_row:
                    self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []

    def handle_data(self, data):
        if self.in_target_table and self.in_td:
            self.current_cell.append(data)


def safe_read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_read_lines(p: Path) -> list:
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def safe_parse_csv_rows(p: Path) -> list:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return list(reader)
    except Exception:
        return []


def safe_parse_csv_dicts(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames, list(reader)
    except Exception:
        return None, []


def safe_parse_jsonl(p: Path):
    objects = []
    try:
        for line in safe_read_lines(p):
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            objects.append(obj)
        return objects
    except Exception:
        return None


def parse_top_problems_from_html(html_text: str) -> list:
    parser = TopProblemsTableParser()
    try:
        parser.feed(html_text)
    except Exception:
        return None
    return parser.rows


def compute_input_file_inventory(input_root: Path):
    expected = {}
    if not input_root.exists():
        return expected

    for path in sorted(input_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(input_root).as_posix()
        suffix = path.suffix.lower()
        fmt = None
        count = None
        try:
            if suffix == ".csv":
                fmt = "CSV"
                rows = safe_parse_csv_rows(path)
                if rows:
                    count = max(len(rows) - 1, 0)
                else:
                    count = 0
            elif suffix == ".jsonl":
                fmt = "JSONL"
                lines = safe_read_lines(path)
                count = len(lines)
            elif suffix == ".html":
                fmt = "HTML"
                html_text = safe_read_text(path)
                rows = parse_top_problems_from_html(html_text)
                if rows is None:
                    count = 0
                else:
                    count = len(rows)
            elif suffix == ".txt":
                fmt = "TXT"
                lines = safe_read_lines(path)
                count = sum(1 for ln in lines if ln.strip() != "")
            else:
                fmt = None
                count = None
        except Exception:
            fmt = fmt or None
            count = None

        if fmt is not None and count is not None:
            expected[rel] = (fmt, count)
    return expected


def parse_dir_report_line(line: str):
    line = line.strip()
    if not line:
        return None
    if "," in line:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
            path = parts[0]
            fmt = parts[1]
            try:
                count = int(parts[2])
                return path, fmt, count
            except ValueError:
                pass
    tokens = line.split()
    if len(tokens) >= 3:
        try:
            count = int(tokens[-1])
            fmt = tokens[-2]
            path = " ".join(tokens[:-2])
            return path, fmt, count
        except ValueError:
            return None
    return None


def load_issues_combined_expected(input_root: Path):
    expected_rows = []
    notes_path = input_root / "sessions" / "notes.jsonl"
    notes = safe_parse_jsonl(notes_path)
    if notes is not None:
        for rec in notes:
            try:
                session_id = rec.get("session_id", "")
                for issue in rec.get("issues", []):
                    issue_id = issue.get("id", "")
                    sev = str(issue.get("severity", "")).strip().lower()
                    desc = str(issue.get("description", "")).strip()
                    expected_rows.append(("notes", session_id, issue_id, sev, desc))
            except Exception:
                return None
    else:
        return None

    html_path = input_root / "surveys" / "feedback.html"
    html_text = safe_read_text(html_path)
    if not html_text:
        return None
    rows = parse_top_problems_from_html(html_text)
    if rows is None:
        return None
    for row in rows:
        if len(row) >= 2:
            session = row[0].strip()
            desc = row[1].strip()
            if len(row) >= 3 and row[2].strip():
                sev = row[2].strip().lower()
            else:
                sev = "medium"
            expected_rows.append(("survey", session, "survey_top_problem", sev, desc))
        else:
            return None
    return expected_rows


def load_missing_sessions_expected(input_root: Path):
    roster_path = input_root / "sessions" / "roster.csv"
    fieldnames, roster_rows = safe_parse_csv_dicts(roster_path)
    if fieldnames is None or not roster_rows:
        return None
    session_ids_ref = set()
    for r in roster_rows:
        sid = r.get("session_id")
        if sid:
            session_ids_ref.add(sid)

    notes_path = input_root / "sessions" / "notes.jsonl"
    notes = safe_parse_jsonl(notes_path)
    if notes is None:
        return None
    notes_sessions = set()
    for rec in notes:
        sid = rec.get("session_id")
        if sid:
            notes_sessions.add(sid)

    html_path = input_root / "surveys" / "feedback.html"
    html_text = safe_read_text(html_path)
    if not html_text:
        return None
    rows = parse_top_problems_from_html(html_text)
    if rows is None:
        return None
    survey_sessions = set()
    for row in rows:
        if row and row[0]:
            survey_sessions.add(row[0].strip())

    expected = []
    for sid in sorted(session_ids_ref):
        in_notes = sid in notes_sessions
        in_survey = sid in survey_sessions
        if in_notes and in_survey:
            continue
        if (not in_notes) and (not in_survey):
            missing_in = "both"
        elif not in_notes:
            missing_in = "notes"
        else:
            missing_in = "survey"
        expected.append((sid, missing_in))
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_root = workspace / "input"
    out_root = workspace / "out"

    scores = {
        "dir_report_present_and_parsed": 0.0,
        "dir_report_covers_all_input_files": 0.0,
        "dir_report_formats_and_counts_correct": 0.0,
        "issues_combined_exists_and_header": 0.0,
        "issues_combined_rows_match_expected": 0.0,
        "missing_sessions_exists_and_header": 0.0,
        "missing_sessions_rows_match_expected": 0.0,
        "email_rewrite_exists": 0.0,
        "email_rewrite_subject_first_line": 0.0,
        "email_rewrite_word_limit": 0.0,
        "email_rewrite_three_numbered_steps": 0.0,
        "email_rewrite_step_install_v130": 0.0,
        "email_rewrite_step_keyboard_sr_navigation": 0.0,
        "email_rewrite_step_feedback_survey_or_reply": 0.0,
        "email_rewrite_contains_deadline_and_version": 0.0,
    }

    expected_inventory = compute_input_file_inventory(input_root)
    dir_report_path = out_root / "dir_report.txt"
    if dir_report_path.exists():
        lines = safe_read_lines(dir_report_path)
        parsed = []
        ok_parse = True
        for ln in lines:
            if not ln.strip():
                continue
            res = parse_dir_report_line(ln)
            if res is None:
                ok_parse = False
                break
            parsed.append(res)
        if ok_parse:
            scores["dir_report_present_and_parsed"] = 1.0
            reported = {}
            for (path_str, fmt, cnt) in parsed:
                reported[path_str] = (fmt, cnt)

            expected_paths = set(expected_inventory.keys())
            reported_paths = set(reported.keys())

            if expected_paths and reported_paths == expected_paths:
                scores["dir_report_covers_all_input_files"] = 1.0

            all_ok = True
            for p in expected_paths:
                if p not in reported:
                    all_ok = False
                    break
                fmt_rep, cnt_rep = reported[p]
                fmt_exp, cnt_exp = expected_inventory[p]
                if str(fmt_rep).strip().lower() != fmt_exp.lower():
                    all_ok = False
                    break
                if cnt_rep != cnt_exp:
                    all_ok = False
                    break
            if expected_paths and all_ok:
                scores["dir_report_formats_and_counts_correct"] = 1.0

    issues_path = out_root / "issues_combined.csv"
    expected_issues = load_issues_combined_expected(input_root)
    if issues_path.exists():
        header, rows = safe_parse_csv_dicts(issues_path)
        if header is not None and header == ["source", "session_id", "issue_id", "severity", "description"]:
            scores["issues_combined_exists_and_header"] = 1.0
        if header is not None and expected_issues is not None:
            from collections import Counter
            expected_counter = Counter(expected_issues)
            actual_tuples = []
            ok_rows = True
            for r in rows:
                try:
                    tup = (
                        (r.get("source") or "").strip(),
                        (r.get("session_id") or "").strip(),
                        (r.get("issue_id") or "").strip(),
                        (r.get("severity") or "").strip().lower(),
                        (r.get("description") or "").strip(),
                    )
                    actual_tuples.append(tup)
                except Exception:
                    ok_rows = False
                    break
            if ok_rows:
                actual_counter = Counter(actual_tuples)
                if actual_counter == expected_counter:
                    scores["issues_combined_rows_match_expected"] = 1.0

    missing_path = out_root / "missing_sessions.csv"
    expected_missing = load_missing_sessions_expected(input_root)
    if missing_path.exists():
        header, rows = safe_parse_csv_dicts(missing_path)
        if header is not None and header == ["session_id", "missing_in"]:
            scores["missing_sessions_exists_and_header"] = 1.0
        if header is not None and expected_missing is not None:
            from collections import Counter
            expected_counter = Counter(expected_missing)
            actual_tuples = []
            ok_rows = True
            for r in rows:
                try:
                    sid = (r.get("session_id") or "").strip()
                    miss = (r.get("missing_in") or "").strip()
                    if miss not in {"notes", "survey", "both"}:
                        ok_rows = False
                        break
                    actual_tuples.append((sid, miss))
                except Exception:
                    ok_rows = False
                    break
            if ok_rows:
                actual_counter = Counter(actual_tuples)
                if actual_counter == expected_counter:
                    scores["missing_sessions_rows_match_expected"] = 1.0

    email_path = out_root / "email_rewrite.txt"
    if email_path.exists():
        scores["email_rewrite_exists"] = 1.0
        email_text = safe_read_text(email_path)
        lines = email_text.splitlines()

        if lines:
            if lines[0].startswith("Subject:"):
                scores["email_rewrite_subject_first_line"] = 1.0

        words = re.findall(r"\b[\w'-]+\b", email_text)
        if len(words) <= 150:
            scores["email_rewrite_word_limit"] = 1.0

        step_lines = []
        for ln in lines:
            m = re.match(r"^\s*([1-3])\.\s+(.*)$", ln)
            if m:
                num = int(m.group(1))
                content = m.group(2).strip()
                step_lines.append((num, content))
        if len(step_lines) == 3 and [n for n, _ in step_lines] == [1, 2, 3]:
            scores["email_rewrite_three_numbered_steps"] = 1.0

            norm_steps = []
            for _, content in step_lines:
                c = content.lower()
                c_norm = c.replace("-", " ")
                norm_steps.append(c_norm)

            install_ok = any(("v1.3.0" in s and "install" in s) for s in norm_steps)
            if install_ok:
                scores["email_rewrite_step_install_v130"] = 1.0

            def step_has_keyboard_sr_nav(s: str) -> bool:
                has_keyboard = "keyboard" in s
                has_sr = "screen reader" in s
                has_nav_or_flows = ("navigation" in s) or ("navigate" in s) or ("flow" in s) or ("flows" in s)
                return has_keyboard and has_sr and has_nav_or_flows

            ksr_ok = any(step_has_keyboard_sr_nav(s) for s in norm_steps)
            if ksr_ok:
                scores["email_rewrite_step_keyboard_sr_navigation"] = 1.0

            feedback_ok = any(("feedback" in s and "[survey link]" in s and "reply" in s) for s in norm_steps)
            if feedback_ok:
                scores["email_rewrite_step_feedback_survey_or_reply"] = 1.0

        if ("April 30, 2026" in email_text) and ("v1.3.0" in email_text):
            scores["email_rewrite_contains_deadline_and_version"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()