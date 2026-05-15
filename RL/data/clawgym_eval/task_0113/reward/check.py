import json
import sys
import re
import csv
from pathlib import Path
from datetime import datetime, date, time
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_time(t: str) -> Optional[time]:
    try:
        return datetime.strptime(t.strip(), "%H:%M").time()
    except Exception:
        return None


def _parse_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _minutes_between(start: str, end: str) -> Optional[int]:
    ts = _parse_time(start)
    te = _parse_time(end)
    if ts is None or te is None:
        return None
    dt_s = datetime.combine(date(2000, 1, 1), ts)
    dt_e = datetime.combine(date(2000, 1, 1), te)
    if dt_e < dt_s:
        return None
    delta = dt_e - dt_s
    return int(delta.total_seconds() // 60)


def _parse_cast_list_html(path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text(path)
    if text is None:
        return None
    table_match = re.search(r'<table[^>]*id=["\']cast["\'][^>]*>(.*?)</table>', text, re.S | re.I)
    if not table_match:
        return None
    tbody = table_match.group(1)
    rows = re.findall(r'<tr>(.*?)</tr>', tbody, re.S | re.I)
    roles = []
    principals = []
    for row_html in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.S | re.I)
        if len(cells) < 3:
            continue
        cleaned = []
        for c in cells[:3]:
            c_clean = re.sub(r'<[^>]+>', '', c)
            c_clean = c_clean.replace("&amp;", "&").replace("&nbsp;", " ").strip()
            cleaned.append(c_clean)
        role, performer, principal_flag = cleaned
        if role.lower() == "role" and performer.lower() == "performer":
            continue
        roles.append(role)
        if principal_flag.strip().lower() == "yes":
            principals.append(role)
    return {"roles": roles, "principals": principals}


def _compute_expected_attendees(group: str, cast_info: Dict[str, List[str]]) -> Optional[int]:
    if cast_info is None:
        return None
    roles = cast_info.get("roles", [])
    principals = cast_info.get("principals", [])
    if group == "Full Cast":
        return len(roles)
    if group == "Principals":
        return len(principals)
    if group == "Tech":
        return 0
    if "+" in group:
        parts = [p.strip() for p in group.split("+")]
        count = 0
        for p in parts:
            if p in roles:
                count += 1
        return count
    return None


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[Dict[str, List[str]]], Optional[List[Dict[str, str]]]]:
    reh_path = workspace / "input" / "rehearsals.csv"
    cast_path = workspace / "input" / "cast_list.html"
    tasks_path = workspace / "input" / "tasks_thread.txt"
    rehearsals = _safe_load_csv(reh_path) if reh_path.exists() else None
    cast_info = _parse_cast_list_html(cast_path) if cast_path.exists() else None
    tasks_text = _read_text(tasks_path) if tasks_path.exists() else None
    tasks = _parse_tasks(tasks_text) if tasks_text is not None else None
    return rehearsals, cast_info, tasks


def _parse_tasks(text: str) -> Optional[List[Dict[str, str]]]:
    tasks = []
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "ID:" in line and "Production:" in line:
                parts = [p.strip() for p in line.split("|")]
                data = {}
                for p in parts:
                    m = re.match(r'^(?:- \[ \]\s*)?([A-Za-z]+):\s*(.*)$', p.strip())
                    if m:
                        key = m.group(1).strip()
                        val = m.group(2).strip()
                        data[key.lower()] = val
                tid = data.get("id")
                prod = data.get("production")
                ttask = data.get("task")
                owner = data.get("owner")
                due = data.get("due")
                notes = data.get("notes") if "notes" in data else None
                if tid and prod and ttask and owner and due:
                    tasks.append({
                        "id": tid,
                        "production": prod,
                        "task": ttask,
                        "owner": owner,
                        "due": due,
                        "notes": notes or ""
                    })
        return tasks
    except Exception:
        return None


def _expected_schedule(rehearsals: List[Dict[str, str]], cast_info: Dict[str, List[str]]) -> Optional[List[Dict[str, str]]]:
    if rehearsals is None or cast_info is None:
        return None
    out = []
    start_date = _parse_date("2024-09-16")
    end_date = _parse_date("2024-09-22")
    if start_date is None or end_date is None:
        return None
    for row in rehearsals:
        prod = row.get("production", "")
        d = row.get("date", "")
        s = row.get("start_time", "")
        e = row.get("end_time", "")
        loc = row.get("location", "")
        group = row.get("group", "")
        notes = row.get("notes", "")
        d_parsed = _parse_date(d)
        if prod != "Twelfth Night":
            continue
        if d_parsed is None or d_parsed < start_date or d_parsed > end_date:
            continue
        dur = _minutes_between(s, e)
        if dur is None:
            return None
        exp_att = _compute_expected_attendees(group, cast_info)
        if exp_att is None:
            return None
        out.append({
            "date": d,
            "start_time": s,
            "end_time": e,
            "duration_minutes": str(dur),
            "location": loc,
            "group": group,
            "expected_attendees": str(exp_att),
            "notes": notes
        })
    def sort_key(r):
        dd = _parse_date(r["date"])
        tt = _parse_time(r["start_time"])
        return (dd or date.min, tt or time.min)
    out.sort(key=sort_key)
    return out


def _load_produced_schedule_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _safe_load_csv(path)
    if rows is None:
        return None
    return rows


def _check_columns_exact(rows: List[Dict[str, str]], expected_cols: List[str]) -> bool:
    if not rows:
        return False
    cols = list(rows[0].keys())
    return cols == expected_cols


def _unique_locations(rows: List[Dict[str, str]]) -> List[str]:
    seen = []
    for r in rows:
        loc = r.get("location", "")
        if loc not in seen:
            seen.append(loc)
    return seen


def _round_two_decimals(value: float) -> float:
    return round(value + 1e-12, 2)


def _parse_markdown_table(md: str) -> Tuple[List[str], List[Dict[str, str]]]:
    lines = [l.rstrip() for l in md.splitlines()]
    headers = []
    data_rows = []
    header_idx = -1
    for i, line in enumerate(lines):
        if "|" in line:
            cells = [c.strip() for c in line.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            low = [c.lower() for c in cells]
            if low == ["id", "owner", "task", "due"]:
                headers = cells
                header_idx = i
                break
    if headers and header_idx >= 0:
        for j in range(header_idx + 1, len(lines)):
            line = lines[j]
            if not line.strip():
                break
            if set(line.strip()) <= set("-|: "):
                continue
            if "|" not in line:
                break
            cells = [c.strip() for c in line.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            if len(cells) != len(headers):
                break
            row = {headers[k]: cells[k] for k in range(len(headers))}
            data_rows.append(row)
    return headers, data_rows


def _extract_ids_from_text_after_heading(text: str, heading: str) -> List[str]:
    lines = text.splitlines()
    capture = False
    ids = []
    for line in lines:
        if not capture and heading.lower() in line.strip().lower():
            capture = True
            continue
        if capture:
            if not line.strip():
                break
            ids += re.findall(r'\bTN-\d+\b', line)
    return ids


def _parse_email_schedule_lines(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    sched = []
    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*[–-]\s*(\d{2}:\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*)$')
    for line in lines:
        m = pattern.match(line.strip())
        if m:
            sched.append({
                "date": m.group(1),
                "start_time": m.group(2),
                "end_time": m.group(3),
                "location": m.group(4),
                "group": m.group(5),
                "notes": m.group(6),
            })
    return sched


def _parse_email_action_item_lines(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    items = []
    pattern = re.compile(r'^(TN-\d+)\s+[—-]\s+(.*?)\s*\(\s*(.*?),\s*Due:\s*(\d{4}-\d{2}-\d{2})\s*\)\s*$')
    for line in lines:
        m = pattern.match(line.strip())
        if m:
            items.append({
                "id": m.group(1),
                "task": m.group(2),
                "owner": m.group(3),
                "due": m.group(4),
            })
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_csv_exists_and_columns": 0.0,
        "schedule_csv_row_count_and_filtering": 0.0,
        "schedule_csv_duration_minutes_correct": 0.0,
        "schedule_csv_expected_attendees_correct": 0.0,
        "schedule_csv_sort_order": 0.0,
        "meeting_notes_title_and_date_range": 0.0,
        "meeting_notes_rehearsal_overview_metrics": 0.0,
        "meeting_notes_locations_listed": 0.0,
        "meeting_notes_action_items_table_structure_and_content": 0.0,
        "meeting_notes_next_steps_ids_correct": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_summary_matches_schedule": 0.0,
        "email_schedule_section_correct": 0.0,
        "email_action_items_section_correct": 0.0,
        "email_closing_signature": 0.0,
    }

    rehearsals, cast_info, tasks = _load_inputs(workspace)
    expected_schedule = None
    if rehearsals is not None and cast_info is not None:
        expected_schedule = _expected_schedule(rehearsals, cast_info)

    expected_tasks_tn = []
    if tasks is not None:
        expected_tasks_tn = [t for t in tasks if t.get("production") == "Twelfth Night"]
        try:
            expected_tasks_tn.sort(key=lambda t: t.get("due", ""))
        except Exception:
            pass

    produced_csv_path = workspace / "output" / "twelfth_night_rehearsals_2024-09-16_to_2024-09-22.csv"
    produced_rows = None
    if produced_csv_path.exists():
        produced_rows = _load_produced_schedule_csv(produced_csv_path)

    expected_cols = ["date", "start_time", "end_time", "duration_minutes", "location", "group", "expected_attendees", "notes"]
    if produced_rows is not None and _check_columns_exact(produced_rows, expected_cols):
        scores["schedule_csv_exists_and_columns"] = 1.0

    if expected_schedule is not None and produced_rows is not None:
        if len(produced_rows) == len(expected_schedule) and len(expected_schedule) > 0:
            def key_from_row(r):
                return (r.get("date", ""), r.get("start_time", ""), r.get("end_time", ""), r.get("location", ""), r.get("group", ""), r.get("notes", ""))
            exp_keys = [key_from_row(r) for r in expected_schedule]
            prod_keys = [key_from_row(r) for r in produced_rows]
            if set(prod_keys) == set(exp_keys):
                scores["schedule_csv_row_count_and_filtering"] = 1.0

    if expected_schedule is not None and produced_rows is not None and len(produced_rows) == len(expected_schedule) and len(expected_schedule) > 0:
        dur_ok = True
        exp_map = {(r["date"], r["start_time"], r["end_time"], r["location"], r["group"], r["notes"]): r for r in expected_schedule}
        for r in produced_rows:
            key = (r.get("date", ""), r.get("start_time", ""), r.get("end_time", ""), r.get("location", ""), r.get("group", ""), r.get("notes", ""))
            exp = exp_map.get(key)
            if not exp:
                dur_ok = False
                break
            if str(r.get("duration_minutes", "")).strip() != str(exp.get("duration_minutes", "")).strip():
                dur_ok = False
                break
        if dur_ok:
            scores["schedule_csv_duration_minutes_correct"] = 1.0

    if expected_schedule is not None and produced_rows is not None and len(produced_rows) == len(expected_schedule) and len(expected_schedule) > 0:
        att_ok = True
        exp_map = {(r["date"], r["start_time"], r["end_time"], r["location"], r["group"], r["notes"]): r for r in expected_schedule}
        for r in produced_rows:
            key = (r.get("date", ""), r.get("start_time", ""), r.get("end_time", ""), r.get("location", ""), r.get("group", ""), r.get("notes", ""))
            exp = exp_map.get(key)
            if not exp:
                att_ok = False
                break
            if str(r.get("expected_attendees", "")).strip() != str(exp.get("expected_attendees", "")).strip():
                att_ok = False
                break
        if att_ok:
            scores["schedule_csv_expected_attendees_correct"] = 1.0

    if produced_rows is not None and len(produced_rows) > 0:
        sorted_ok = True
        prev = None
        for r in produced_rows:
            d = _parse_date(r.get("date", ""))
            t = _parse_time(r.get("start_time", ""))
            if d is None or t is None:
                sorted_ok = False
                break
            cur = (d, t)
            if prev is not None and cur < prev:
                sorted_ok = False
                break
            prev = cur
        if sorted_ok:
            scores["schedule_csv_sort_order"] = 1.0

    notes_path = workspace / "output" / "meeting_notes_2024-09-16_to_2024-09-22.md"
    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text:
        lines = notes_text.splitlines()
        expected_title = "Meeting: Twelfth Night Weekly Check-In"
        expected_range = "2024-09-16 to 2024-09-22"
        if len(lines) >= 2 and lines[0].strip() == expected_title and lines[1].strip() == expected_range:
            scores["meeting_notes_title_and_date_range"] = 1.0

        if produced_rows is not None and len(produced_rows) > 0:
            try:
                total_rehearsals = len(produced_rows)
                total_minutes = sum(int(r.get("duration_minutes", "0")) for r in produced_rows)
                total_hours = _round_two_decimals(total_minutes / 60.0)
            except Exception:
                total_rehearsals = None
                total_hours = None
            overview_ok = False
            if total_rehearsals is not None and total_hours is not None:
                hour_strs = {f"{total_hours:.2f}", f"{total_hours}".rstrip('0').rstrip('.') if '.' in f"{total_hours}" else f"{total_hours}"}
                for line in lines:
                    if str(total_rehearsals) in line and any(h in line for h in hour_strs):
                        overview_ok = True
                        break
            if overview_ok:
                scores["meeting_notes_rehearsal_overview_metrics"] = 1.0

            locs = _unique_locations(produced_rows)
            locs_ok = True
            for loc in locs:
                if notes_text.find(loc) == -1:
                    locs_ok = False
                    break
            if locs and locs_ok:
                scores["meeting_notes_locations_listed"] = 1.0

        headers, table_rows = _parse_markdown_table(notes_text)
        table_ok = False
        if [h.strip().lower() for h in headers] == ["id", "owner", "task", "due"] and expected_tasks_tn:
            exp_ids = [t["id"] for t in expected_tasks_tn]
            try:
                table_ids = [r["ID"].strip() for r in table_rows]
                if set(table_ids) == set(exp_ids) and len(table_ids) == len(exp_ids):
                    table_map = {r["ID"].strip(): r for r in table_rows}
                    content_match = True
                    for t in expected_tasks_tn:
                        rid = t["id"]
                        tr = table_map.get(rid)
                        if not tr:
                            content_match = False
                            break
                        if tr["Owner"].strip() != t["owner"]:
                            content_match = False
                            break
                        if tr["Task"].strip() != t["task"]:
                            content_match = False
                            break
                        if tr["Due"].strip() != t["due"]:
                            content_match = False
                            break
                    due_dates = []
                    for rid in table_ids:
                        due_dates.append(table_map[rid]["Due"].strip())
                    if content_match:
                        order_ok = all(due_dates[i] <= due_dates[i+1] for i in range(len(due_dates)-1))
                        if order_ok:
                            if "DC-201" not in " ".join(table_ids):
                                table_ok = True
            except Exception:
                table_ok = False
        if table_ok:
            scores["meeting_notes_action_items_table_structure_and_content"] = 1.0

        next_steps_ids = _extract_ids_from_text_after_heading(notes_text, "Next Steps")
        expected_next_ids = []
        if expected_tasks_tn:
            for t in expected_tasks_tn:
                try:
                    d = _parse_date(t["due"])
                except Exception:
                    d = None
                if d is not None and d <= _parse_date("2024-09-17"):
                    expected_next_ids.append(t["id"])
        if next_steps_ids and set(next_steps_ids) == set(expected_next_ids):
            scores["meeting_notes_next_steps_ids_correct"] = 1.0

    email_path = workspace / "output" / "draft_email_twelfth_night_2024-09-16_to_2024-09-22.txt"
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text:
        expected_subject = "Subject: Twelfth Night — Week of 2024-09-16: Rehearsals & Action Items"
        subj_ok = any(line.strip() == expected_subject for line in email_text.splitlines())
        greet_ok = False
        for line in email_text.splitlines():
            l = line.strip()
            if re.match(r'^(hi|hello|dear)\b', l, flags=re.I):
                if re.search(r'\bcast\b', l, flags=re.I) and re.search(r'\bteam\b', l, flags=re.I):
                    greet_ok = True
                    break
        if subj_ok and greet_ok:
            scores["email_subject_and_greeting"] = 1.0

        if produced_rows is not None and len(produced_rows) > 0:
            try:
                total_rehearsals = len(produced_rows)
                total_minutes = sum(int(r.get("duration_minutes", "0")) for r in produced_rows)
                total_hours = _round_two_decimals(total_minutes / 60.0)
            except Exception:
                total_rehearsals = None
                total_hours = None
            summary_ok = False
            if total_rehearsals is not None and total_hours is not None:
                hour_strs = {f"{total_hours:.2f}", f"{total_hours}".rstrip('0').rstrip('.') if '.' in f"{total_hours}" else f"{total_hours}"}
                for line in email_text.splitlines():
                    if str(total_rehearsals) in line and any(h in line for h in hour_strs):
                        summary_ok = True
                        break
            if summary_ok:
                scores["email_summary_matches_schedule"] = 1.0

        email_sched = _parse_email_schedule_lines(email_text)
        sched_ok = False
        if expected_schedule is not None and email_sched:
            if len(email_sched) == len(expected_schedule):
                ok = True
                for i in range(len(expected_schedule)):
                    exp = expected_schedule[i]
                    got = email_sched[i]
                    if got["date"] != exp["date"]:
                        ok = False
                        break
                    if got["start_time"] != exp["start_time"]:
                        ok = False
                        break
                    if got["end_time"] != exp["end_time"]:
                        ok = False
                        break
                    if got["location"] != exp["location"]:
                        ok = False
                        break
                    if got["group"] != exp["group"]:
                        ok = False
                        break
                    if got["notes"] != exp["notes"]:
                        ok = False
                        break
                if ok:
                    sched_ok = True
        if sched_ok:
            scores["email_schedule_section_correct"] = 1.0

        email_items = _parse_email_action_item_lines(email_text)
        email_ai_ok = False
        if expected_tasks_tn and email_items:
            exp_ids = [t["id"] for t in expected_tasks_tn]
            got_ids = [it["id"] for it in email_items]
            if set(got_ids) == set(exp_ids) and len(got_ids) == len(exp_ids):
                exp_map = {t["id"]: t for t in expected_tasks_tn}
                content_ok = True
                for it in email_items:
                    e = exp_map.get(it["id"])
                    if not e:
                        content_ok = False
                        break
                    if it["task"] != e["task"]:
                        content_ok = False
                        break
                    if it["owner"] != e["owner"]:
                        content_ok = False
                        break
                    if it["due"] != e["due"]:
                        content_ok = False
                        break
                due_dates = [it["due"] for it in email_items]
                order_ok = all(due_dates[i] <= due_dates[i+1] for i in range(len(due_dates)-1))
                if content_ok and order_ok:
                    email_ai_ok = True
        if email_ai_ok:
            scores["email_action_items_section_correct"] = 1.0

        if "Thanks, Jordan Taylor, Stage Manager" in email_text:
            scores["email_closing_signature"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()