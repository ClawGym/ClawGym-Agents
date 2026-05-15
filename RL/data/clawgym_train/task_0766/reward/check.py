import json
import csv
import sys
import re
from datetime import date, timedelta
from pathlib import Path


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_text(path: Path) -> str:
    try:
        return _normalize_newlines(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_json(path: Path):
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        headers = rows[0]
        dict_rows = []
        for r in rows[1:]:
            if len(r) == 0:
                continue
            if len(r) < len(headers):
                r = r + [""] * (len(headers) - len(r))
            elif len(r) > len(headers):
                r = r[: len(headers)]
            dict_rows.append(dict(zip(headers, r)))
        return headers, dict_rows
    except Exception:
        return None, None


def _parse_date_yyyy_mm_dd(s: str):
    try:
        parts = s.split("-")
        if len(parts) != 3:
            return None
        y, m, d = map(int, parts)
        return date(y, m, d)
    except Exception:
        return None


def _render_template(text: str, mapping: dict) -> str:
    rendered = text
    for key, value in mapping.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _extract_subject_and_body_from_template(template_text: str):
    if template_text is None:
        return None, None
    lines = template_text.split("\n")
    subject_line_idx = None
    for idx, ln in enumerate(lines):
        if ln.startswith("Subject:"):
            subject_line_idx = idx
            break
    if subject_line_idx is None:
        return "", template_text
    subject_line = lines[subject_line_idx]
    subject = subject_line[len("Subject:"):].lstrip()
    body_lines = lines[subject_line_idx + 1 :]
    body = "\n".join(body_lines)
    return subject, body


def _compute_expected_visits(workspace: Path):
    visits_csv_path = workspace / "input" / "school_visits.csv"
    template_path = workspace / "input" / "email_template.md"
    headers, rows = _parse_csv(visits_csv_path)
    template_text = _read_text(template_path)
    if headers is None or rows is None or template_text is None:
        return None

    subject_template, body_template = _extract_subject_and_body_from_template(template_text)
    if subject_template is None or body_template is None:
        return None

    confirmed = []
    for r in rows:
        status = r.get("status", "")
        if status == "confirmed":
            confirmed.append(r)

    expected = []
    for r in confirmed:
        school = r.get("school", "")
        contact_name = r.get("contact_name", "")
        contact_email = r.get("contact_email", "")
        visit_date_str = r.get("visit_date", "")
        start_time = r.get("start_time", "")
        tz = r.get("timezone", "")
        grade_band = r.get("grade_band", "")
        theme = r.get("theme_focus", "")

        vd = _parse_date_yyyy_mm_dd(visit_date_str)
        if vd is None:
            return None
        reminder_date = vd - timedelta(days=3)
        reminder_date_str = reminder_date.isoformat()

        mapping = {
            "SCHOOL": school,
            "CONTACT_NAME": contact_name,
            "DATE": visit_date_str,
            "TIME": start_time,
            "TIMEZONE": tz,
            "THEME": theme,
            "GRADE_BAND": grade_band,
        }
        subj = _render_template(subject_template, mapping)
        body = _render_template(body_template, mapping)

        expected.append({
            "id": r.get("id", ""),
            "school": school,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "visit_date": visit_date_str,
            "start_time": start_time,
            "timezone": tz,
            "grade_band": grade_band,
            "theme_focus": theme,
            "reminder_send_date": reminder_date_str,
            "subject": subj,
            "body": body,
        })

    expected.sort(key=lambda x: (x["reminder_send_date"], x["id"]))
    return expected


def _load_manuscripts(workspace: Path):
    manuscripts_path = workspace / "input" / "manuscripts.json"
    data = _load_json(manuscripts_path)
    if data is None or not isinstance(data, list):
        return None
    filtered = []
    for m in data:
        try:
            status = m.get("status")
            ned = m.get("next_edit_deadline")
            if status != "completed" and ned is not None:
                if _parse_date_yyyy_mm_dd(ned) is None:
                    return None
                filtered.append({
                    "title": m.get("title", ""),
                    "theme": m.get("theme", ""),
                    "status": status,
                    "next_edit_deadline": ned,
                    "notes": m.get("notes", ""),
                })
        except Exception:
            return None
    filtered.sort(key=lambda x: (x["next_edit_deadline"], x["title"]))
    return filtered


def _extract_section(text: str, heading: str):
    pattern = rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^\#\#\s|\Z)"
    m = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return None, None, None
    heading_prefix = m.group(1)
    content = m.group(2)
    return content, m.start(1), m.end(2)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "visit_csv_exists_and_columns": 0.0,
        "visit_csv_rowcount_and_filter": 0.0,
        "visit_csv_sorted_by_reminder_date": 0.0,
        "visit_csv_field_values_match": 0.0,
        "visit_csv_reminder_date_correct": 0.0,
        "visit_csv_template_subject_and_body_match": 0.0,
        "docs_upcoming_visits_bullets": 0.0,
        "docs_manuscript_edits_bullets": 0.0,
        "docs_visits_csv_consistency": 0.0,
        "docs_other_sections_unchanged": 0.0,
        "docs_sections_rewritten_no_placeholders": 0.0,
    }

    expected_visits = _compute_expected_visits(workspace)
    expected_manuscripts = _load_manuscripts(workspace)

    out_csv_path = workspace / "out" / "visit_reminders.csv"
    out_headers, out_rows = _parse_csv(out_csv_path)

    required_columns = [
        "id",
        "school",
        "contact_name",
        "contact_email",
        "visit_date",
        "start_time",
        "timezone",
        "grade_band",
        "theme_focus",
        "reminder_send_date",
        "subject",
        "body",
    ]
    if out_headers is not None:
        if out_headers == required_columns:
            scores["visit_csv_exists_and_columns"] = 1.0

    if expected_visits is not None and out_rows is not None:
        expected_ids = [v["id"] for v in expected_visits]
        out_ids = [r.get("id", "") for r in out_rows]
        if len(out_rows) == len(expected_visits) and sorted(out_ids) == sorted(expected_ids):
            scores["visit_csv_rowcount_and_filter"] = 1.0

        try:
            out_reminders = [r.get("reminder_send_date", "") for r in out_rows]
            parsed = [_parse_date_yyyy_mm_dd(x) for x in out_reminders]
            if None not in parsed:
                is_sorted = all(parsed[i] <= parsed[i + 1] for i in range(len(parsed) - 1))
                if is_sorted:
                    scores["visit_csv_sorted_by_reminder_date"] = 1.0
        except Exception:
            pass

        field_values_ok = True
        reminder_dates_ok = True
        template_ok = True
        expected_by_id = {v["id"]: v for v in expected_visits}
        for r in out_rows:
            vid = r.get("id", "")
            exp = expected_by_id.get(vid)
            if not exp:
                field_values_ok = False
                reminder_dates_ok = False
                template_ok = False
                continue
            for key in ["school", "contact_name", "contact_email", "visit_date", "start_time", "timezone", "grade_band", "theme_focus"]:
                if r.get(key, "") != exp.get(key, ""):
                    field_values_ok = False
                    break
            if r.get("reminder_send_date", "") != exp.get("reminder_send_date", ""):
                reminder_dates_ok = False
            subj = r.get("subject", "")
            body = r.get("body", "")
            if subj != exp.get("subject", "") or body != exp.get("body", ""):
                template_ok = False
            if "{{" in subj or "{{" in body:
                template_ok = False

        if field_values_ok and out_headers == required_columns:
            scores["visit_csv_field_values_match"] = 1.0
        if reminder_dates_ok:
            scores["visit_csv_reminder_date_correct"] = 1.0
        if template_ok:
            scores["visit_csv_template_subject_and_body_match"] = 1.0

    docs_path = workspace / "docs" / "REMINDERS.md"
    docs_text = _read_text(docs_path)

    if docs_text is not None:
        upcoming_content, up_start, up_end = _extract_section(docs_text, "Upcoming School Visits")
        manus_content, m_start, m_end = _extract_section(docs_text, "Manuscript Edits")

        sections_rewritten = False
        if upcoming_content is not None and manus_content is not None:
            if "Placeholder:" not in upcoming_content and "Placeholder:" not in manus_content:
                sections_rewritten = True
        if sections_rewritten:
            scores["docs_sections_rewritten_no_placeholders"] = 1.0

        visits_bullets_ok = False
        if upcoming_content is not None and expected_visits is not None:
            lines = [ln.strip() for ln in upcoming_content.split("\n")]
            bullets = [ln for ln in lines if ln.startswith("- ")]
            count_ok = len(bullets) == len(expected_visits)
            field_presence_ok = True
            dates = []
            for b in bullets:
                m = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", b)
                if not m:
                    field_presence_ok = False
                    break
                dates.append(m.group(1))
                matched = False
                for v in expected_visits:
                    required_vals = [
                        v["contact_name"],
                        v["contact_email"],
                        v["school"],
                        v["visit_date"],
                        v["start_time"],
                        v["timezone"],
                        v["theme_focus"],
                        v["grade_band"],
                    ]
                    if all(val in b for val in required_vals) and v["reminder_send_date"] == m.group(1):
                        matched = True
                        break
                if not matched:
                    field_presence_ok = False
                    break
            sorted_ok = False
            if field_presence_ok and dates:
                parsed_dates = [_parse_date_yyyy_mm_dd(d) for d in dates]
                if None not in parsed_dates:
                    sorted_ok = all(parsed_dates[i] <= parsed_dates[i + 1] for i in range(len(parsed_dates) - 1))
            if count_ok and field_presence_ok and sorted_ok:
                visits_bullets_ok = True
        if visits_bullets_ok:
            scores["docs_upcoming_visits_bullets"] = 1.0

        manus_bullets_ok = False
        if manus_content is not None and expected_manuscripts is not None:
            lines = [ln.strip() for ln in manus_content.split("\n")]
            bullets = [ln for ln in lines if ln.startswith("- ")]
            count_ok = len(bullets) == len(expected_manuscripts)
            field_presence_ok = True
            dates = []
            for b in bullets:
                m = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", b)
                if not m:
                    field_presence_ok = False
                    break
                dates.append(m.group(1))
                matched = False
                for man in expected_manuscripts:
                    req_vals = [
                        man["title"],
                        man["theme"],
                        man["status"],
                    ]
                    notes = man["notes"] or ""
                    notes_ok = (notes == "") or (notes[:8] in b) or (notes in b)
                    if all(val in b for val in req_vals) and (man["next_edit_deadline"] == m.group(1)) and notes_ok:
                        matched = True
                        break
                if not matched:
                    field_presence_ok = False
                    break
            sorted_ok = False
            if field_presence_ok and dates:
                parsed_dates = [_parse_date_yyyy_mm_dd(d) for d in dates]
                if None not in parsed_dates:
                    sorted_ok = all(parsed_dates[i] <= parsed_dates[i + 1] for i in range(len(parsed_dates) - 1))
            if count_ok and field_presence_ok and sorted_ok:
                manus_bullets_ok = True
        if manus_bullets_ok:
            scores["docs_manuscript_edits_bullets"] = 1.0

        csv_consistency_ok = False
        if upcoming_content is not None and out_rows is not None:
            lines = [ln.strip() for ln in upcoming_content.split("\n")]
            bullets = [ln for ln in lines if ln.startswith("- ")]
            csv_set = set(
                (
                    r.get("contact_name", ""),
                    r.get("contact_email", ""),
                    r.get("school", ""),
                    r.get("visit_date", ""),
                    r.get("start_time", ""),
                    r.get("timezone", ""),
                    r.get("theme_focus", ""),
                    r.get("grade_band", ""),
                    r.get("reminder_send_date", ""),
                )
                for r in out_rows
            )
            bullets_set = set()
            for b in bullets:
                m = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", b)
                if not m:
                    bullets_set = None
                    break
                b_date = m.group(1)
                if expected_visits is None:
                    bullets_set = None
                    break
                matched_tuple = None
                for v in expected_visits:
                    required_vals = [
                        v["contact_name"],
                        v["contact_email"],
                        v["school"],
                        v["visit_date"],
                        v["start_time"],
                        v["timezone"],
                        v["theme_focus"],
                        v["grade_band"],
                    ]
                    if all(val in b for val in required_vals) and b_date == v["reminder_send_date"]:
                        matched_tuple = (
                            v["contact_name"],
                            v["contact_email"],
                            v["school"],
                            v["visit_date"],
                            v["start_time"],
                            v["timezone"],
                            v["theme_focus"],
                            v["grade_band"],
                            v["reminder_send_date"],
                        )
                        break
                if matched_tuple is None:
                    bullets_set = None
                    break
                bullets_set.add(matched_tuple)
            if bullets_set is not None and csv_set == bullets_set:
                csv_consistency_ok = True
        if csv_consistency_ok:
            scores["docs_visits_csv_consistency"] = 1.0

        other_unchanged_ok = False
        try:
            expected_prefix = _normalize_newlines(
                "# Weekly Reminders\n\nThese reminders help me stay ahead on school visit follow-ups and manuscript edits.\n\n"
            )
            idx_upcoming = docs_text.find("## Upcoming School Visits")
            if idx_upcoming != -1:
                actual_prefix = docs_text[:idx_upcoming]
                if _normalize_newlines(actual_prefix) == expected_prefix:
                    notes_content, n_start, n_end = _extract_section(docs_text, "Notes to Self")
                    expected_notes = _normalize_newlines(
                        "- Bring extra paper gears and a small wind turbine model.\n- Test the projector adapter.\n"
                    )
                    if notes_content is not None:
                        actual_notes = notes_content
                        if not actual_notes.endswith("\n"):
                            actual_notes = actual_notes + "\n"
                        if _normalize_newlines(actual_notes) == expected_notes:
                            other_unchanged_ok = True
        except Exception:
            other_unchanged_ok = False
        if other_unchanged_ok and sections_rewritten:
            scores["docs_other_sections_unchanged"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()