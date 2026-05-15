import csv
import json
import re
import sys
from datetime import datetime, timedelta, date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _safe_parse_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_parse_datetime(dt: str) -> Optional[datetime]:
    try:
        return datetime.strptime(dt, "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _extract_placeholders(text: str) -> Set[str]:
    return set(re.findall(r"{{\s*([a-zA-Z_]+)\s*}}", text or ""))


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w[\w'-]*\b", text or "")
    return len(words)


def _has_bullet_lines(text: str) -> bool:
    if not text:
        return False
    for line in text.splitlines():
        l = line.strip()
        if re.match(r"^(\*|-|\d+\.)\s+", l):
            return True
    return False


def _single_paragraph(text: str) -> bool:
    if text is None:
        return False
    # Count non-empty paragraphs separated by blank lines
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip() != ""]
    return len(paragraphs) == 1


def _parse_allowed_placeholders(mailer_py: Path) -> Optional[Set[str]]:
    content = _read_text(mailer_py)
    if content is None:
        return None
    # Try to extract ALLOWED_PLACEHOLDERS set literal
    m = re.search(r"ALLOWED_PLACEHOLDERS\s*=\s*\{([^}]*)\}", content, re.DOTALL)
    if not m:
        return None
    inner = m.group(1)
    # Extract quoted identifiers inside
    items = re.findall(r'["\']([a-zA-Z_]+)["\']', inner)
    return set(items)


class _ScholarshipTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.capture = False
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self.in_td = False
        self.table_depth = 0
        self.current_table_id: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            attrs_dict = dict(attrs)
            self.current_table_id = attrs_dict.get("id")
            if self.current_table_id == "sch-table":
                self.in_table = True
                self.table_depth = 1
            elif self.in_table:
                self.table_depth += 1
        elif self.in_table and tag.lower() == "tbody":
            self.capture = True
        elif self.in_table and self.capture and tag.lower() == "tr":
            self.current_row = []
        elif self.in_table and self.capture and tag.lower() == "td":
            self.in_td = True

    def handle_endtag(self, tag):
        if tag.lower() == "table" and self.in_table:
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_table = False
        elif self.in_table and tag.lower() == "tbody":
            self.capture = False
        elif self.in_table and self.capture and tag.lower() == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif self.in_table and self.capture and tag.lower() == "td":
            self.in_td = False

    def handle_data(self, data):
        if self.in_table and self.capture and self.in_td:
            text = data.strip()
            if text != "":
                self.current_row.append(text)


def _parse_scholarships_html(path: Path) -> Optional[List[Dict[str, str]]]:
    content = _read_text(path)
    if content is None:
        return None
    parser = _ScholarshipTableParser()
    try:
        parser.feed(content)
    except Exception:
        return None
    result: List[Dict[str, str]] = []
    for row in parser.rows:
        # Expect at least 3 cells: ID, Name, Deadline
        if len(row) < 3:
            return None
        sid = row[0].strip()
        name = row[1].strip()
        deadline = row[2].strip()
        if _safe_parse_date(deadline) is None:
            return None
        result.append({"id": sid, "name": name, "deadline": deadline})
    return result


def _parse_students_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = [
                "student_name",
                "student_email",
                "parent_email",
                "recommender_name",
                "recommender_email",
                "college",
                "app_deadline",
                "rec_deadline",
                "scholarship_ids",
            ]
            if reader.fieldnames is None:
                return None
            if [h.strip() for h in reader.fieldnames] != required:
                # If header order wrong or missing, still attempt but signal failure by returning None
                return None
            for r in reader:
                rows.append({k: (r.get(k, "") or "").strip() for k in required})
        return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    # Very simple parser for this specific config structure.
    txt = _read_text(path)
    if txt is None:
        return None

    def parse_value(val: str) -> Any:
        v = val.strip()
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip() for x in v[1:-1].split(",") if x.strip() != ""]
            parsed = []
            for it in items:
                try:
                    parsed.append(int(it))
                except Exception:
                    parsed.append(it.strip('"').strip("'"))
            return parsed
        try:
            return int(v)
        except Exception:
            return v

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any], Optional[str]]] = [(0, root, None)]
    for raw_line in txt.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # New nested dict
                new_map: Dict[str, Any] = {}
                stack[-1][1][key] = new_map
                stack.append((indent + 2, new_map, key))
            else:
                stack[-1][1][key] = parse_value(val)
        else:
            # Unsupported form; fail
            return None
    return root


def _adjust_for_weekend(d: date, is_pre: bool, weekday_only: bool) -> date:
    if not weekday_only:
        return d
    wd = d.weekday()  # Monday=0 ... Sunday=6
    if is_pre:
        if wd == 5:  # Saturday
            return d - timedelta(days=1)
        if wd == 6:  # Sunday
            return d - timedelta(days=2)
        return d
    else:
        if wd == 5:  # Saturday
            return d + timedelta(days=2)
        if wd == 6:  # Sunday
            return d + timedelta(days=1)
        return d


def _format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _format_send_datetime(d: date, time_str: str) -> str:
    # time_str expected "HH:MM"
    return f"{d.strftime('%Y-%m-%d')} {time_str}"


def _build_scholarship_map(sch_list: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {s["id"]: {"name": s["name"], "deadline": s["deadline"]} for s in sch_list}


def _compute_expected_reminders(students: List[Dict[str, str]], scholarships: Dict[str, Dict[str, str]], config: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    try:
        tz = str(config["timezone"])
        send_time = str(config["send_time"])
        weekday_only = bool(config.get("weekday_only", False))
        pre_days: List[int] = list(config["pre_deadline_days"])
        followup_after_days: int = int(config["followup_after_days"])
    except Exception:
        return None

    expected_rows: List[Dict[str, str]] = []

    def add_row(recipient_name: str, recipient_email: str, audience: str, message_type: str,
                related_name: str, deadline_date: str, stage: str, send_date: date, template_path: str):
        expected_rows.append({
            "recipient_name": recipient_name,
            "recipient_email": recipient_email,
            "audience": audience,
            "message_type": message_type,
            "stage": stage,
            "related_name": related_name,
            "deadline_date": deadline_date,
            "send_datetime": _format_send_datetime(send_date, send_time),
            "timezone": tz,
            "template_path": template_path,
        })

    for st in students:
        student_name = st["student_name"]
        student_email = st["student_email"]
        recommender_name = st["recommender_name"]
        recommender_email = st["recommender_email"]
        college = st["college"]

        # Application reminders (student)
        app_deadline = _safe_parse_date(st["app_deadline"])
        if app_deadline:
            for d in pre_days:
                stage = f"pre-{d}"
                pre_date = app_deadline - timedelta(days=d)
                send_date = _adjust_for_weekend(pre_date, is_pre=True, weekday_only=weekday_only)
                add_row(student_name, student_email, "student", "application", college, _format_date(app_deadline), stage, send_date, "out/templates/student_application.md")
            # follow-up
            post_stage = f"post+{followup_after_days}"
            post_date = app_deadline + timedelta(days=followup_after_days)
            send_date = _adjust_for_weekend(post_date, is_pre=False, weekday_only=weekday_only)
            add_row(student_name, student_email, "student", "application", college, _format_date(app_deadline), post_stage, send_date, "out/templates/student_application.md")

        # Recommendation reminders (recommender)
        rec_deadline = _safe_parse_date(st["rec_deadline"])
        if rec_deadline:
            for d in pre_days:
                stage = f"pre-{d}"
                pre_date = rec_deadline - timedelta(days=d)
                send_date = _adjust_for_weekend(pre_date, is_pre=True, weekday_only=weekday_only)
                add_row(recommender_name, recommender_email, "recommender", "recommendation", college, _format_date(rec_deadline), stage, send_date, "out/templates/recommender.md")
            # follow-up
            post_stage = f"post+{followup_after_days}"
            post_date = rec_deadline + timedelta(days=followup_after_days)
            send_date = _adjust_for_weekend(post_date, is_pre=False, weekday_only=weekday_only)
            add_row(recommender_name, recommender_email, "recommender", "recommendation", college, _format_date(rec_deadline), post_stage, send_date, "out/templates/recommender.md")

        # Scholarship reminders (student)
        sch_ids = [x.strip() for x in (st.get("scholarship_ids", "") or "").split(";") if x.strip()]
        for sid in sch_ids:
            if sid in scholarships:
                sdata = scholarships[sid]
                sname = sdata["name"]
                sdeadline = _safe_parse_date(sdata["deadline"])
                if sdeadline:
                    for d in pre_days:
                        stage = f"pre-{d}"
                        pre_date = sdeadline - timedelta(days=d)
                        send_date = _adjust_for_weekend(pre_date, is_pre=True, weekday_only=weekday_only)
                        add_row(student_name, student_email, "student", "scholarship", sname, _format_date(sdeadline), stage, send_date, "out/templates/student_scholarship.md")
                    post_stage = f"post+{followup_after_days}"
                    post_date = sdeadline + timedelta(days=followup_after_days)
                    send_date = _adjust_for_weekend(post_date, is_pre=False, weekday_only=weekday_only)
                    add_row(student_name, student_email, "student", "scholarship", sname, _format_date(sdeadline), post_stage, send_date, "out/templates/student_scholarship.md")

    return expected_rows


def _read_reminders_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows: List[Dict[str, str]] = []
            for r in reader:
                # Normalize whitespace
                row_norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                rows.append(row_norm)
            return [h.strip() for h in headers], rows
    except Exception:
        return None


def _subjects_valid(rows: List[Dict[str, str]], config: Dict[str, Any]) -> bool:
    try:
        auds = config["audiences"]
    except Exception:
        return False
    ok = True
    for r in rows:
        audience = r.get("audience", "")
        subject = r.get("subject", "")
        message_type = r.get("message_type", "")
        related_name = r.get("related_name", "")
        deadline_date = r.get("deadline_date", "")
        stage = r.get("stage", "")
        if audience not in ("student", "recommender"):
            ok = False
            continue
        prefix = auds.get(audience, {}).get("subject_prefix")
        if not isinstance(prefix, str):
            ok = False
            continue
        if not subject.startswith(prefix):
            ok = False
            continue
        if len(subject) >= 70:
            ok = False
        # Must include related_name and deadline_date and stage marker (e.g., (pre-14))
        if related_name not in subject or deadline_date not in subject:
            ok = False
        if f"({stage})" not in subject:
            ok = False
        # message_type is used for mapping; not enforced in subject but we already check above constraints
    return ok


def _check_templates(template_paths: Dict[str, Path], allowed_placeholders: Optional[Set[str]]) -> Dict[str, float]:
    results: Dict[str, float] = {}
    for key, path in template_paths.items():
        text = _read_text(path)
        exists = text is not None
        if not exists:
            results[f"{key}_valid"] = 0.0
            results[f"{key}_required_placeholders"] = 0.0
            continue
        wc = _word_count(text or "")
        length_ok = 60 <= wc <= 120
        paragraph_ok = _single_paragraph(text or "")
        bullets_ok = not _has_bullet_lines(text or "")
        placeholders = _extract_placeholders(text or "")
        if key == "student_application":
            required = {"student_name", "college", "deadline_date"}
        elif key == "student_scholarship":
            required = {"student_name", "scholarship_name", "deadline_date"}
        elif key == "recommender":
            required = {"recommender_name", "student_name", "deadline_date"}
        else:
            required = set()
        required_ok = required.issubset(placeholders)
        allowed_ok = True
        if allowed_placeholders is not None:
            # No placeholders outside allowed set
            if not placeholders.issubset(allowed_placeholders):
                allowed_ok = False
        valid_all = 1.0 if (length_ok and paragraph_ok and bullets_ok and allowed_ok) else 0.0
        results[f"{key}_valid"] = valid_all
        results[f"{key}_required_placeholders"] = 1.0 if required_ok else 0.0
    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "scholarships_json_exists": 0.0,
        "scholarships_json_structure": 0.0,
        "scholarships_json_matches_source": 0.0,
        "template_student_application_valid": 0.0,
        "template_student_application_required_placeholders": 0.0,
        "template_student_scholarship_valid": 0.0,
        "template_student_scholarship_required_placeholders": 0.0,
        "template_recommender_valid": 0.0,
        "template_recommender_required_placeholders": 0.0,
        "reminders_csv_exists": 0.0,
        "reminders_csv_columns": 0.0,
        "reminders_row_count": 0.0,
        "reminders_rows_match_expected": 0.0,
        "reminders_subjects_valid": 0.0,
        "reminders_template_paths_correct": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    out_dir = workspace / "out"
    scholarships_html_path = input_dir / "scholarships.html"
    scholarships_json_path = out_dir / "scholarships.json"
    students_csv_path = input_dir / "students.csv"
    config_yaml_path = input_dir / "reminder_config.yaml"
    mailer_py_path = input_dir / "mailer.py"

    template_student_application_path = out_dir / "templates" / "student_application.md"
    template_student_scholarship_path = out_dir / "templates" / "student_scholarship.md"
    template_recommender_path = out_dir / "templates" / "recommender.md"

    # Parse allowed placeholders from mailer.py
    allowed_placeholders = _parse_allowed_placeholders(mailer_py_path)

    # Check templates
    tpl_results = _check_templates(
        {
            "student_application": template_student_application_path,
            "student_scholarship": template_student_scholarship_path,
            "recommender": template_recommender_path,
        },
        allowed_placeholders,
    )
    scores.update(tpl_results)

    # Scholarships JSON checks
    sch_expected = _parse_scholarships_html(scholarships_html_path)
    sch_actual = _load_json(scholarships_json_path)
    if sch_actual is not None:
        scores["scholarships_json_exists"] = 1.0
        # Structure: list of objects with id, name, deadline (YYYY-MM-DD)
        structure_ok = False
        try:
            if isinstance(sch_actual, list) and all(isinstance(x, dict) for x in sch_actual) and len(sch_actual) > 0:
                structure_ok = True
                for obj in sch_actual:
                    keys = set(obj.keys())
                    if not {"id", "name", "deadline"}.issubset(keys):
                        structure_ok = False
                        break
                    if not isinstance(obj["id"], str) or not isinstance(obj["name"], str) or not isinstance(obj["deadline"], str):
                        structure_ok = False
                        break
                    if _safe_parse_date(obj["deadline"]) is None:
                        structure_ok = False
                        break
            elif isinstance(sch_actual, list) and len(sch_actual) == 0:
                # Empty list is structurally valid but content mismatch will fail later
                structure_ok = True
        except Exception:
            structure_ok = False
        scores["scholarships_json_structure"] = 1.0 if structure_ok else 0.0

        # Match to source of truth (ignore order)
        if sch_expected is not None and isinstance(sch_actual, list):
            expected_set = {(x["id"], x["name"], x["deadline"]) for x in sch_expected}
            actual_set = {(x.get("id"), x.get("name"), x.get("deadline")) for x in sch_actual if isinstance(x, dict)}
            scores["scholarships_json_matches_source"] = 1.0 if expected_set == actual_set else 0.0

    # Reminders CSV checks
    reminders_csv_path = out_dir / "reminders.csv"
    csv_data = _read_reminders_csv(reminders_csv_path)
    if csv_data is not None:
        scores["reminders_csv_exists"] = 1.0
        headers, rows = csv_data
        expected_headers = [
            "recipient_name",
            "recipient_email",
            "audience",
            "message_type",
            "stage",
            "related_name",
            "deadline_date",
            "send_datetime",
            "timezone",
            "template_path",
            "subject",
        ]
        scores["reminders_csv_columns"] = 1.0 if headers == expected_headers else 0.0

        # Parse inputs for expected schedule
        students = _parse_students_csv(students_csv_path)
        config = _parse_simple_yaml(config_yaml_path)
        sch_from_html = _parse_scholarships_html(scholarships_html_path)
        expected_rows: Optional[List[Dict[str, str]]] = None
        if students is not None and config is not None and sch_from_html is not None:
            sch_map = _build_scholarship_map(sch_from_html)
            expected_rows = _compute_expected_reminders(students, sch_map, config)

        if expected_rows is not None:
            # Row count must match
            scores["reminders_row_count"] = 1.0 if len(rows) == len(expected_rows) else 0.0

            # Build key for matching rows excluding subject
            def row_key(d: Dict[str, str]) -> Tuple[str, str, str, str, str, str, str, str]:
                return (
                    d.get("recipient_email", ""),
                    d.get("audience", ""),
                    d.get("message_type", ""),
                    d.get("related_name", ""),
                    d.get("deadline_date", ""),
                    d.get("stage", ""),
                    d.get("send_datetime", ""),
                    d.get("template_path", ""),
                )

            expected_map = {row_key(er): er for er in expected_rows}
            actual_map = {row_key(r): r for r in rows}

            rows_match = expected_map.keys() == actual_map.keys()
            # Additionally validate types/formats for all rows
            formats_ok = True
            template_paths_ok = True
            if rows_match:
                # Validate each actual row against expected values and formats
                for k, expected in expected_map.items():
                    actual = actual_map.get(k, {})
                    # Validate date/time formats
                    if _safe_parse_date(actual.get("deadline_date", "")) is None:
                        formats_ok = False
                        break
                    if _safe_parse_datetime(actual.get("send_datetime", "")) is None:
                        formats_ok = False
                        break
                    # Validate stage
                    if actual.get("stage") not in {f"pre-{d}" for d in config["pre_deadline_days"]} | {f"post+{int(config['followup_after_days'])}"}:
                        formats_ok = False
                        break
                    # Validate timezone equals config
                    if actual.get("timezone") != str(config["timezone"]):
                        formats_ok = False
                        break
                    # Validate audience and message_type values
                    if actual.get("audience") not in {"student", "recommender"}:
                        formats_ok = False
                        break
                    if actual.get("message_type") not in {"application", "scholarship", "recommendation"}:
                        formats_ok = False
                        break
                    # Validate template path selection is our rewritten templates
                    mt = actual.get("message_type")
                    aud = actual.get("audience")
                    tpath = actual.get("template_path", "")
                    if mt == "application" and aud == "student":
                        if tpath != "out/templates/student_application.md":
                            template_paths_ok = False
                    elif mt == "scholarship" and aud == "student":
                        if tpath != "out/templates/student_scholarship.md":
                            template_paths_ok = False
                    elif mt == "recommendation" and aud == "recommender":
                        if tpath != "out/templates/recommender.md":
                            template_paths_ok = False
                    else:
                        # unexpected pairing
                        template_paths_ok = False
                # Done loop
            else:
                formats_ok = False
                template_paths_ok = False

            scores["reminders_rows_match_expected"] = 1.0 if rows_match and formats_ok else 0.0
            scores["reminders_template_paths_correct"] = 1.0 if rows_match and template_paths_ok else 0.0

            # Subjects validation
            subjects_ok = False
            if rows_match and config is not None:
                subjects_ok = _subjects_valid(rows, config)
            scores["reminders_subjects_valid"] = 1.0 if subjects_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()