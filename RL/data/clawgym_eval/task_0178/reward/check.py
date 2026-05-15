import json
import sys;
import re
import csv
from pathlib import Path
from collections import Counter


RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_csv_with_header(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames if reader.fieldnames is not None else []
            rows = []
            for row in reader:
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return header, rows
    except Exception:
        return [], []


def parse_html_key_dates(html_text: str):
    rows = []
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", html_text, flags=re.S | re.I)
    if not tbody_match:
        return rows
    tbody = tbody_match.group(1)
    tr_blocks = re.findall(r"<tr>(.*?)</tr>", tbody, flags=re.S | re.I)
    for tr in tr_blocks:
        tds = re.findall(r"<td>(.*?)</td>", tr, flags=re.S | re.I)
        tds = [re.sub(r"\s+", " ", td).strip() for td in tds]
        if len(tds) != 5:
            continue
        title, date_field, time_field, location, notes = tds
        if "to" in date_field:
            parts = [p.strip() for p in date_field.split("to")]
            if len(parts) == 2:
                date_start, date_end = parts
            else:
                date_start = date_field.strip()
                date_end = date_field.strip()
        else:
            date_start = date_field.strip()
            date_end = date_field.strip()
        title_lower = title.lower()
        if "book closing" in title_lower or "registration" in title_lower:
            item_type = "registration_deadline"
        elif "early voting" in title_lower:
            item_type = "early_voting"
        elif "election day" in title_lower or "election" in title_lower:
            item_type = "election_day"
        else:
            item_type = "meeting"
        rows.append({
            "source": "webpage",
            "item_type": item_type,
            "title": title,
            "date_start": date_start,
            "date_end": date_end,
            "time": time_field,
            "location": location,
            "notes": notes,
        })
    return rows


def parse_meeting_notes(notes_text: str):
    rows = []
    for raw_line in notes_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("—")]
        if len(parts) < 2:
            parts = [p.strip() for p in re.split(r"\s-\s", line)]
        if len(parts) >= 2:
            title = parts[0].strip()
            details = parts[1].strip()
            notes = parts[2].strip() if len(parts) >= 3 else ""
            details_parts = [p.strip() for p in details.split(",")]
            if len(details_parts) >= 3:
                date_start = details_parts[0]
                time_field = details_parts[1]
                location = ",".join(details_parts[2:]).strip()
                tl = title.lower()
                if "meeting" in tl:
                    item_type = "meeting"
                elif "tabling" in tl or "volunteer" in tl or "registration" in tl:
                    item_type = "volunteering"
                else:
                    item_type = "meeting"
                rows.append({
                    "source": "notes",
                    "item_type": item_type,
                    "title": title,
                    "date_start": date_start,
                    "date_end": date_start,
                    "time": time_field,
                    "location": location,
                    "notes": notes if notes else "",
                })
    return rows


def expected_key_dates_from_inputs(workspace: Path):
    html_path = workspace / "input" / "saved_webpage.html"
    notes_path = workspace / "input" / "meeting_notes.txt"
    html_text = read_text_file(html_path)
    notes_text = read_text_file(notes_path)
    expected = []
    if html_text:
        expected.extend(parse_html_key_dates(html_text))
    if notes_text:
        expected.extend(parse_meeting_notes(notes_text))
    return expected


def canonical_row_tuple(row: dict) -> tuple:
    keys = ["source", "item_type", "title", "date_start", "date_end", "time", "location", "notes"]
    return tuple((row.get(k, "") or "").strip() for k in keys)


def count_words(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def extract_bullet_lines(text: str):
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r"^\s*([\-*•])\s+", ln):
            bullets.append(ln.strip())
    return bullets


def validate_date_string(val: str) -> bool:
    return bool(RE_DATE.match(val.strip()))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "key_dates_file_and_header": 0.0,
        "key_dates_five_rows_included": 0.0,
        "key_dates_exact_match": 0.0,
        "key_dates_item_types_correct": 0.0,
        "key_dates_dates_normalized": 0.0,
        "welcome_note_word_count": 0.0,
        "welcome_note_bulleted_list_three_election_items": 0.0,
        "welcome_note_mentions_club_items_with_dates_locations": 0.0,
        "welcome_note_placeholders_removed": 0.0,
        "volunteer_email_subject_line": 0.0,
        "volunteer_email_word_count": 0.0,
        "volunteer_email_bulleted_list_references_required_items": 0.0,
        "volunteer_email_rsvp_request": 0.0,
    }

    expected_rows = expected_key_dates_from_inputs(workspace)
    expected_by_title = {r["title"]: r for r in expected_rows}
    required_columns = ["source", "item_type", "title", "date_start", "date_end", "time", "location", "notes"]

    key_dates_path = workspace / "output" / "key_dates.csv"
    header, student_rows = load_csv_with_header(key_dates_path)
    if key_dates_path.exists() and header == required_columns:
        scores["key_dates_file_and_header"] = 1.0

    if student_rows and len(student_rows) == 5:
        scores["key_dates_five_rows_included"] = 1.0

    if student_rows and expected_rows:
        student_set = Counter(canonical_row_tuple(r) for r in student_rows)
        expected_set = Counter(canonical_row_tuple(r) for r in expected_rows)
        if student_set == expected_set:
            scores["key_dates_exact_match"] = 1.0

    if student_rows and expected_rows:
        ok_all = True
        for title, exp_row in expected_by_title.items():
            matches = [r for r in student_rows if (r.get("title") or "").strip() == title]
            if len(matches) != 1:
                ok_all = False
                break
            stu = matches[0]
            if (stu.get("item_type") or "").strip() != exp_row["item_type"]:
                ok_all = False
                break
        if ok_all:
            scores["key_dates_item_types_correct"] = 1.0

    if student_rows and expected_rows:
        ok_dates = True
        for title, exp_row in expected_by_title.items():
            matches = [r for r in student_rows if (r.get("title") or "").strip() == title]
            if len(matches) != 1:
                ok_dates = False
                break
            stu = matches[0]
            ds = (stu.get("date_start") or "").strip()
            de = (stu.get("date_end") or "").strip()
            if not (validate_date_string(ds) and validate_date_string(de)):
                ok_dates = False
                break
            if exp_row["date_start"] == exp_row["date_end"]:
                if de != ds:
                    ok_dates = False
                    break
            else:
                if ds != exp_row["date_start"] or de != exp_row["date_end"]:
                    ok_dates = False
                    break
        if ok_dates:
            scores["key_dates_dates_normalized"] = 1.0

    welcome_path = workspace / "output" / "updated_welcome_note.md"
    welcome_text = read_text_file(welcome_path)
    if welcome_text:
        wc = count_words(welcome_text)
        if 300 <= wc <= 350:
            scores["welcome_note_word_count"] = 1.0

        placeholders = ["INSERT KEY DATES HERE", "TBD", "fix later"]
        if not any(ph.lower() in welcome_text.lower() for ph in placeholders):
            scores["welcome_note_placeholders_removed"] = 1.0

        if student_rows:
            webpage_events = [r for r in student_rows if (r.get("source") or "").strip() == "webpage"]
            bullets = extract_bullet_lines(welcome_text)
            matched_all = True
            if len(webpage_events) != 3 or not bullets:
                matched_all = False
            else:
                for ev in webpage_events:
                    title = (ev.get("title") or "").strip()
                    ds = (ev.get("date_start") or "").strip()
                    de = (ev.get("date_end") or "").strip()
                    found = False
                    for b in bullets:
                        if title in b and ds in b and ((de == ds) or (de in b)):
                            found = True
                            break
                    if not found:
                        matched_all = False
                        break
            if matched_all:
                scores["welcome_note_bulleted_list_three_election_items"] = 1.0

        if student_rows:
            notes_events = [r for r in student_rows if (r.get("source") or "").strip() == "notes"]
            mentions_ok = True
            if len(notes_events) != 2:
                mentions_ok = False
            else:
                for ev in notes_events:
                    title = (ev.get("title") or "").strip()
                    ds = (ev.get("date_start") or "").strip()
                    loc = (ev.get("location") or "").strip()
                    if not (title in welcome_text and ds in welcome_text and loc in welcome_text):
                        mentions_ok = False
                        break
            if mentions_ok:
                scores["welcome_note_mentions_club_items_with_dates_locations"] = 1.0

    email_path = workspace / "output" / "volunteer_email.txt"
    email_text = read_text_file(email_path)
    if email_text:
        lines = email_text.splitlines()
        subject_ok = False
        if lines:
            first = lines[0].strip()
            if re.match(r"^Subject:\s*\S.*", first):
                subject_ok = True
        if subject_ok:
            scores["volunteer_email_subject_line"] = 1.0

        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        body_wc = count_words(body)
        if 180 <= body_wc <= 250:
            scores["volunteer_email_word_count"] = 1.0

        if student_rows:
            bullets = extract_bullet_lines(body)
            required_ok = False
            if len(bullets) >= 3:
                by_title = {(r.get("title") or "").strip(): r for r in student_rows}
                req_titles = ["Voter Registration Tabling", "Okaloosa Dems Monthly Meeting"]
                two_ok = True
                for t in req_titles:
                    ev = by_title.get(t)
                    if not ev:
                        two_ok = False
                        break
                    ds = (ev.get("date_start") or "").strip()
                    found = any((t in b and ds in b) for b in bullets)
                    if not found:
                        two_ok = False
                        break
                webpage_events = [r for r in student_rows if (r.get("source") or "").strip() == "webpage"]
                election_ok = False
                for ev in webpage_events:
                    t = (ev.get("title") or "").strip()
                    ds = (ev.get("date_start") or "").strip()
                    de = (ev.get("date_end") or "").strip()
                    for b in bullets:
                        if t in b and ds in b and ((de == ds) or (de in b)):
                            election_ok = True
                            break
                    if election_ok:
                        break
                if two_ok and election_ok:
                    required_ok = True
            if required_ok:
                scores["volunteer_email_bulleted_list_references_required_items"] = 1.0

        rsvp_ok = False
        if body:
            if ("rsvp" in body.lower()) and ("reply" in body.lower()) and ("Fort Walton Beach Library" in body):
                rsvp_ok = True
        if rsvp_ok:
            scores["volunteer_email_rsvp_request"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()