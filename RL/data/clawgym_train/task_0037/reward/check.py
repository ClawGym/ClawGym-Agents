import json
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timedelta


def read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_rows_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def parse_simple_yaml(text: str):
    # Minimal YAML parser for simple key: value and key: (list) used in inputs
    try:
        result = {}
        lines = [ln.rstrip("\n\r") for ln in text.splitlines()]
        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            if ":" not in stripped:
                return None
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Expecting a list starting on subsequent lines with - items
                i += 1
                lst = []
                while i < n:
                    raw2 = lines[i]
                    stripped2 = raw2.strip()
                    if not stripped2:
                        i += 1
                        continue
                    if stripped2.startswith("- "):
                        content = stripped2[2:].strip()
                        lst.append(content)
                        i += 1
                        continue
                    if raw2.startswith(" "):
                        return None
                    break
                result[key] = lst
            else:
                result[key] = val
                i += 1
        return result
    except Exception:
        return None


class GuidanceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_section = None  # 'important' or 'required' or None
        # Important dates table parsing
        self.in_tr = False
        self.in_td_or_th = False
        self.current_cell = ""
        self.current_row = []
        self.rows = []
        # Required documents parsing
        self.current_li = None
        self.current_li_text_parts = []
        self.required_docs = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "section":
            sec_id = attrs_dict.get("id", "")
            if sec_id == "important-dates":
                self.current_section = "important"
            elif sec_id == "required-documents":
                self.current_section = "required"
        if self.current_section == "important":
            if tag == "tr":
                self.in_tr = True
                self.current_row = []
            if tag in ("td", "th"):
                self.in_td_or_th = True
                self.current_cell = ""
        if self.current_section == "required":
            if tag == "li":
                name = attrs_dict.get("data-name")
                due = attrs_dict.get("data-due")
                cat = attrs_dict.get("data-category")
                self.current_li = {"name": name, "due_date": due, "category": cat}
                self.current_li_text_parts = []

    def handle_endtag(self, tag):
        if self.current_section == "important":
            if tag in ("td", "th"):
                self.in_td_or_th = False
                cell_text = " ".join(self.current_cell.split())
                self.current_row.append(cell_text)
                self.current_cell = ""
            if tag == "tr":
                if self.in_tr:
                    if len(self.current_row) >= 2:
                        self.rows.append(self.current_row[:2])
                self.in_tr = False
        if self.current_section == "required":
            if tag == "li" and self.current_li is not None:
                desc = " ".join(" ".join(self.current_li_text_parts).split()).strip()
                doc = {
                    "name": self.current_li.get("name"),
                    "due_date": self.current_li.get("due_date"),
                    "category": self.current_li.get("category"),
                    "description": desc,
                }
                self.required_docs.append(doc)
                self.current_li = None
                self.current_li_text_parts = []
        if tag == "section":
            self.current_section = None

    def handle_data(self, data):
        if self.current_section == "important" and self.in_tr and self.in_td_or_th:
            self.current_cell += data
        if self.current_section == "required" and self.current_li is not None:
            self.current_li_text_parts.append(data)


def parse_guidance_html(text: str):
    try:
        parser = GuidanceParser()
        parser.feed(text)
        important_map = {}
        for row in parser.rows:
            if len(row) < 2:
                continue
            item, date_str = row[0].strip(), row[1].strip()
            header_like = item.lower() == "item" and date_str.lower() == "date"
            if header_like:
                continue
            important_map[item] = date_str
        expected_keys = {
            "application opens": "application_opens",
            "submission deadline": "submission_deadline",
            "decision notification": "decision_notification",
        }
        normalized = {}
        for key_human, norm_key in expected_keys.items():
            found = None
            for item, date_str in important_map.items():
                if item.strip().lower() == key_human:
                    found = date_str
                    break
            if found is None:
                normalized[norm_key] = None
            else:
                normalized[norm_key] = found
        docs = []
        for d in parser.required_docs:
            docs.append(
                {
                    "name": d.get("name"),
                    "due_date": d.get("due_date"),
                    "category": d.get("category"),
                    "description": d.get("description"),
                }
            )
        return {"important_dates": normalized, "required_documents": docs}
    except Exception:
        return None


def parse_agenda_md(text: str):
    bullets = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            bullets.append(s[2:].strip())
    return bullets


def parse_participants_csv(fields, rows):
    if not fields or not rows:
        return []
    if "name" not in fields or "role" not in fields:
        return []
    participants = []
    for r in rows:
        name = (r.get("name") or "").strip()
        role = (r.get("role") or "").strip()
        if name:
            participants.append({"name": name, "role": role})
    return participants


def find_first_by_role_contains(participants, keyword: str):
    keyword_lower = keyword.lower()
    for p in participants:
        if keyword_lower in (p.get("role") or "").lower():
            return p
    return None


def owner_for_category(category: str, participants):
    category_lower = (category or "").lower()
    if category_lower == "student":
        p = find_first_by_role_contains(participants, "student")
        if p:
            return p["name"]
    elif category_lower == "mentor":
        p = find_first_by_role_contains(participants, "mentor")
        if p:
            return p["name"]
    elif category_lower == "administrative":
        p = find_first_by_role_contains(participants, "administrator")
        if p:
            return p["name"]
    p = find_first_by_role_contains(participants, "student")
    return p["name"] if p else (participants[0]["name"] if participants else None)


def parse_meeting_notes_sections(text: str, required_sections):
    sections = {name: [] for name in required_sections}
    current = None
    for ln in text.splitlines():
        stripped = ln.strip()
        hdr = stripped.lstrip("#").strip()
        if hdr in sections:
            current = hdr
            continue
        if current is not None:
            sections[current].append(ln.rstrip("\n\r"))
    return sections


def detect_section_headers(text: str, required_sections):
    found = set()
    for ln in text.splitlines():
        stripped = ln.strip()
        hdr = stripped.lstrip("#").strip()
        if hdr in required_sections:
            found.add(hdr)
    return found


def normalize_list_line(line: str) -> str:
    s = line.strip()
    for prefix in ("- ", "* ", "• ", "+ "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if len(s) > 2 and s[0].isdigit() and (s[1] in (".", ")")):
        s = s[2:].lstrip()
    return s.strip()


def validate_date_string(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "guidance_json_exists": 0.0,
        "guidance_json_structure": 0.0,
        "guidance_json_important_dates_correct": 0.0,
        "guidance_json_required_documents_correct": 0.0,
        "action_items_csv_exists": 0.0,
        "action_items_header_matches_template": 0.0,
        "action_items_required_documents_rows_correct": 0.0,
        "action_items_planning_row_correct": 0.0,
        "action_items_row_count_exact": 0.0,
        "meeting_notes_md_exists": 0.0,
        "meeting_notes_sections_complete": 0.0,
        "meeting_notes_metadata_correct": 0.0,
        "meeting_notes_attendees_correct": 0.0,
        "meeting_notes_agenda_summary_matches": 0.0,
        "meeting_notes_requirements_summary_correct": 0.0,
        "meeting_notes_decisions_commitment_and_checkin": 0.0,
        "meeting_notes_action_items_summary_matches": 0.0,
    }

    # Input paths
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    html_path = input_dir / "scholarship_guidance.html"
    participants_path = input_dir / "participants.csv"
    agenda_path = input_dir / "agenda.md"
    template_yaml_path = input_dir / "notes_template.yaml"
    meeting_info_yaml_path = input_dir / "meeting_info.yaml"

    # Output paths
    guidance_json_path = output_dir / "guidance_extracted.json"
    action_items_csv_path = output_dir / "action_items.csv"
    meeting_notes_md_path = output_dir / "meeting_notes.md"

    # Load inputs
    html_text = read_text_safe(html_path)
    participants_fields, participants_rows = load_csv_rows_safe(participants_path)
    participants = parse_participants_csv(participants_fields, participants_rows)
    agenda_text = read_text_safe(agenda_path)
    template_yaml_text = read_text_safe(template_yaml_path)
    meeting_info_yaml_text = read_text_safe(meeting_info_yaml_path)

    template_yaml = parse_simple_yaml(template_yaml_text) if template_yaml_text else None
    meeting_info = parse_simple_yaml(meeting_info_yaml_text) if meeting_info_yaml_text else None

    agenda_bullets = parse_agenda_md(agenda_text) if agenda_text else []

    guidance_from_html = parse_guidance_html(html_text) if html_text else None

    expected_important_dates = {}
    expected_required_docs = []
    if guidance_from_html:
        expected_important_dates = guidance_from_html.get("important_dates", {})
        expected_required_docs = guidance_from_html.get("required_documents", [])

    # Existence checks
    if guidance_json_path.exists():
        scores["guidance_json_exists"] = 1.0
    if action_items_csv_path.exists():
        scores["action_items_csv_exists"] = 1.0
    if meeting_notes_md_path.exists():
        scores["meeting_notes_md_exists"] = 1.0

    # A) guidance_extracted.json checks
    guidance_json = load_json_safe(guidance_json_path)
    if guidance_json is not None and isinstance(guidance_json, dict):
        # Structure check
        ok_struct = True
        if "important_dates" not in guidance_json or "required_documents" not in guidance_json:
            ok_struct = False
        else:
            imp = guidance_json["important_dates"]
            req = guidance_json["required_documents"]
            if not isinstance(imp, dict):
                ok_struct = False
            else:
                for k in ("application_opens", "submission_deadline", "decision_notification"):
                    if k not in imp or not isinstance(imp[k], str) or not validate_date_string(imp[k]):
                        ok_struct = False
                        break
            if not isinstance(req, list):
                ok_struct = False
            else:
                for item in req:
                    if not isinstance(item, dict):
                        ok_struct = False
                        break
                    for kk in ("name", "due_date", "category", "description"):
                        if kk not in item:
                            ok_struct = False
                            break
                    if not ok_struct:
                        break
                    if not isinstance(item["name"], str) or not isinstance(item["description"], str):
                        ok_struct = False
                        break
                    if not isinstance(item["due_date"], str) or not validate_date_string(item["due_date"]):
                        ok_struct = False
                        break
                    if item["category"] not in ("student", "mentor", "administrative"):
                        ok_struct = False
                        break
        scores["guidance_json_structure"] = 1.0 if ok_struct else 0.0

        # Content correctness checks against inputs
        if expected_important_dates and all(expected_important_dates.get(k) for k in ("application_opens", "submission_deadline", "decision_notification")):
            user_imp = guidance_json.get("important_dates", {})
            imp_ok = (
                isinstance(user_imp, dict)
                and user_imp.get("application_opens") == expected_important_dates.get("application_opens")
                and user_imp.get("submission_deadline") == expected_important_dates.get("submission_deadline")
                and user_imp.get("decision_notification") == expected_important_dates.get("decision_notification")
            )
            scores["guidance_json_important_dates_correct"] = 1.0 if imp_ok else 0.0
        else:
            scores["guidance_json_important_dates_correct"] = 0.0

        if expected_required_docs:
            user_docs = guidance_json.get("required_documents", [])
            if isinstance(user_docs, list):
                def to_tuple(d):
                    return (
                        d.get("name"),
                        d.get("due_date"),
                        d.get("category"),
                        d.get("description"),
                    )
                user_set = sorted(to_tuple(d) for d in user_docs if isinstance(d, dict))
                exp_set = sorted(to_tuple(d) for d in expected_required_docs)
                scores["guidance_json_required_documents_correct"] = 1.0 if user_set == exp_set else 0.0
            else:
                scores["guidance_json_required_documents_correct"] = 0.0
        else:
            scores["guidance_json_required_documents_correct"] = 0.0
    else:
        scores["guidance_json_structure"] = 0.0
        scores["guidance_json_important_dates_correct"] = 0.0
        scores["guidance_json_required_documents_correct"] = 0.0

    # B) action_items.csv checks
    ai_fields, ai_rows = load_csv_rows_safe(action_items_csv_path)
    expected_columns = []
    if template_yaml and isinstance(template_yaml.get("action_item_columns"), list):
        expected_columns = template_yaml["action_item_columns"]
    if ai_fields is not None and expected_columns:
        scores["action_items_header_matches_template"] = 1.0 if ai_fields == expected_columns else 0.0
    else:
        scores["action_items_header_matches_template"] = 0.0

    expected_ai_rows = []
    planning_due_date = None
    submission_deadline = expected_important_dates.get("submission_deadline")
    if submission_deadline and validate_date_string(submission_deadline):
        planning_due_date = (datetime.strptime(submission_deadline, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    if expected_required_docs and participants:
        for doc in expected_required_docs:
            task = f"Prepare: {doc['name']}"
            owner = owner_for_category(doc["category"], participants)
            due_date = doc["due_date"]
            expected_ai_rows.append({
                "task": task,
                "owner": owner,
                "due_date": due_date,
                "source": "scholarship_guidance",
                "category": doc["category"],
            })
    if planning_due_date and participants:
        mentor_owner = owner_for_category("mentor", participants)
        if mentor_owner:
            expected_ai_rows.append({
                "task": "Schedule check-in meeting",
                "owner": mentor_owner,
                "due_date": planning_due_date,
                "source": "agenda",
                "category": "planning",
            })

    if ai_rows is not None and expected_required_docs and participants:
        def row_to_tuple(r):
            return (r.get("task"), r.get("owner"), r.get("due_date"), r.get("source"), r.get("category"))

        expected_req_tuples = set()
        for doc in expected_required_docs:
            task = f"Prepare: {doc['name']}"
            owner = owner_for_category(doc["category"], participants)
            due_date = doc["due_date"]
            expected_req_tuples.add((task, owner, due_date, "scholarship_guidance", doc["category"]))

        user_req_tuples = set()
        for r in ai_rows:
            if r.get("source") == "scholarship_guidance":
                user_req_tuples.add(row_to_tuple(r))

        scores["action_items_required_documents_rows_correct"] = 1.0 if user_req_tuples == expected_req_tuples else 0.0
    else:
        scores["action_items_required_documents_rows_correct"] = 0.0

    if ai_rows is not None and planning_due_date and participants:
        mentor_owner = owner_for_category("mentor", participants)
        plan_ok = False
        for r in ai_rows:
            if (
                r.get("task") == "Schedule check-in meeting"
                and r.get("owner") == mentor_owner
                and r.get("due_date") == planning_due_date
                and r.get("source") == "agenda"
                and r.get("category") == "planning"
            ):
                plan_ok = True
                break
        scores["action_items_planning_row_correct"] = 1.0 if plan_ok else 0.0
    else:
        scores["action_items_planning_row_correct"] = 0.0

    if ai_rows is not None and expected_required_docs and planning_due_date and participants:
        expected_count = len(expected_required_docs) + 1
        scores["action_items_row_count_exact"] = 1.0 if len(ai_rows) == expected_count else 0.0
    else:
        scores["action_items_row_count_exact"] = 0.0

    # C) meeting_notes.md checks
    notes_text = read_text_safe(meeting_notes_md_path)
    required_sections = []
    if template_yaml and isinstance(template_yaml.get("required_sections"), list):
        required_sections = template_yaml["required_sections"]

    if notes_text is not None and required_sections:
        sections = parse_meeting_notes_sections(notes_text, required_sections)
        found_headers = detect_section_headers(notes_text, required_sections)
        sections_complete = set(required_sections).issubset(found_headers)
        scores["meeting_notes_sections_complete"] = 1.0 if sections_complete else 0.0

        meta_ok = False
        if meeting_info and sections_complete:
            title = meeting_info.get("title")
            date = meeting_info.get("date")
            location = meeting_info.get("location")

            def section_contains(section_name: str, needle: str) -> bool:
                if not needle:
                    return False
                for ln in sections.get(section_name, []):
                    if needle in ln:
                        return True
                return False

            if section_contains("Meeting Title", str(title)) and section_contains("Date", str(date)) and section_contains("Location", str(location)):
                meta_ok = True
        scores["meeting_notes_metadata_correct"] = 1.0 if meta_ok else 0.0

        attendees_ok = False
        if participants and sections_complete:
            attendee_lines = [normalize_list_line(ln) for ln in sections.get("Attendees", [])]
            attendee_lines = [ln for ln in attendee_lines if ln.strip()]
            expected_names = [p["name"] for p in participants]
            attendees_ok = attendee_lines == expected_names
        scores["meeting_notes_attendees_correct"] = 1.0 if attendees_ok else 0.0

        agenda_ok = False
        if agenda_bullets and sections_complete:
            agenda_lines = [normalize_list_line(ln) for ln in sections.get("Agenda Summary", [])]
            agenda_lines = [ln for ln in agenda_lines if ln.strip()]
            agenda_ok = agenda_lines == agenda_bullets
        scores["meeting_notes_agenda_summary_matches"] = 1.0 if agenda_ok else 0.0

        req_summary_ok = False
        if expected_required_docs and sections_complete:
            lines = [normalize_list_line(ln) for ln in sections.get("Scholarship Requirements Summary", [])]
            lines = [ln for ln in lines if ln.strip()]
            all_present = True
            for doc in expected_required_docs:
                name = doc["name"]
                due = doc["due_date"]
                found = any((name in ln and due in ln) for ln in lines)
                if not found:
                    all_present = False
                    break
            req_summary_ok = all_present and (len(lines) >= len(expected_required_docs))
        scores["meeting_notes_requirements_summary_correct"] = 1.0 if req_summary_ok else 0.0

        decisions_ok = False
        if sections_complete and submission_deadline and planning_due_date:
            decisions_text = "\n".join(sections.get("Decisions", []))
            lower = decisions_text.lower()
            has_submit_word = ("submit" in lower) or ("submission" in lower)
            has_check_word = ("check-in" in lower) or ("check in" in lower)
            has_deadline_date = submission_deadline in decisions_text
            has_checkin_date = planning_due_date in decisions_text
            decisions_ok = has_submit_word and has_check_word and has_deadline_date and has_checkin_date
        scores["meeting_notes_decisions_commitment_and_checkin"] = 1.0 if decisions_ok else 0.0

        action_items_summary_ok = False
        if ai_rows is not None and sections_complete:
            lines = [normalize_list_line(ln) for ln in sections.get("Action Items", [])]
            lines = [ln for ln in lines if ln.strip()]
            all_found = True
            for r in ai_rows:
                task = r.get("task") or ""
                owner = r.get("owner") or ""
                due = r.get("due_date") or ""
                found = any((task in ln and owner in ln and due in ln) for ln in lines)
                if not found:
                    all_found = False
                    break
            action_items_summary_ok = all_found
        scores["meeting_notes_action_items_summary_matches"] = 1.0 if action_items_summary_ok else 0.0
    else:
        scores["meeting_notes_sections_complete"] = 0.0
        scores["meeting_notes_metadata_correct"] = 0.0
        scores["meeting_notes_attendees_correct"] = 0.0
        scores["meeting_notes_agenda_summary_matches"] = 0.0
        scores["meeting_notes_requirements_summary_correct"] = 0.0
        scores["meeting_notes_decisions_commitment_and_checkin"] = 0.0
        scores["meeting_notes_action_items_summary_matches"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()