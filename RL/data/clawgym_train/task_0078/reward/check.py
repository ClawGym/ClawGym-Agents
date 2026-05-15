import json
import csv
import re
import sys
import calendar
from pathlib import Path
from datetime import datetime, date, timedelta


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = list(reader)
            return rows
    except Exception:
        return None


def _load_shifts_yaml(path: Path):
    # Minimal YAML parser for simple key/value indentation under shift names.
    try:
        text = _safe_read_text(path)
        if not text:
            return None
        shifts = {}
        current = None
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            if not line.startswith(" "):  # top-level key like "Day:"
                if ":" in line:
                    key = line.split(":", 1)[0].strip()
                    current = key
                    shifts[current] = {}
            else:
                if current is None:
                    continue
                m = re.match(r"\s{2,}([^:]+):\s*(.*)$", line)
                if not m:
                    continue
                k = m.group(1).strip()
                v = m.group(2).strip()
                # strip quotes if present
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                shifts[current][k] = v
        # Validate required keys for each shift
        for vals in shifts.values():
            if "default_time" not in vals or "location" not in vals:
                return None
        return shifts
    except Exception:
        return None


def _parse_date_ymd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _semicolon_split(s: str):
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def _compute_last_and_next_month(reference_date: date):
    year = reference_date.year
    month = reference_date.month
    # Last month
    if month == 1:
        last_month = 12
        last_year = year - 1
    else:
        last_month = month - 1
        last_year = year
    # Next month
    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year
    return (last_year, last_month), (next_year, next_month)


def _month_start_end(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _extract_shift_sections(text: str, shifts: list):
    lines = text.splitlines()
    indices = []
    for idx, line in enumerate(lines):
        for s in shifts:
            if re.search(rf"\b{s}\b", line):
                indices.append((idx, s))
    sections = {}
    if not indices:
        return sections
    indices.sort(key=lambda x: x[0])
    for i, (start_idx, s) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        sect = "\n".join(lines[start_idx:end_idx]).strip()
        if s not in sections:
            sections[s] = sect
    return sections


def _extract_counts_in_text(text: str):
    try:
        mt = re.search(r"Total\s+staff.*?(\d+)", text, re.IGNORECASE)
        ma = re.search(r"Count\s+attended.*?(\d+)", text, re.IGNORECASE)
        mm = re.search(r"Count\s+missed.*?(\d+)", text, re.IGNORECASE)
        if not (mt and ma and mm):
            return None
        return (int(mt.group(1)), int(ma.group(1)), int(mm.group(1)))
    except Exception:
        return None


def _extract_emails(text: str):
    return set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "plan_file_exists_and_header": 0.0,
        "plan_rows_cover_shifts": 0.0,
        "plan_dates_valid": 0.0,
        "plan_times_locations_duration_valid": 0.0,
        "plan_required_attendees_correct": 0.0,
        "status_summary_exists": 0.0,
        "status_counts_correct": 0.0,
        "status_missed_emails_listed": 0.0,
        "status_includes_scheduling_note": 0.0,
        "emails_files_exist": 0.0,
        "emails_headers_valid": 0.0,
        "emails_body_includes_details": 0.0,
        "emails_consistent_with_plan": 0.0,
        "internal_consistency_plan_vs_summary": 0.0,
        "internal_consistency_emails_to_vs_plan": 0.0,
    }

    # Load inputs
    context_path = workspace / "input" / "context.json"
    staff_path = workspace / "input" / "staff.csv"
    drill_log_path = workspace / "input" / "drill_log.csv"
    shifts_yaml_path = workspace / "input" / "shifts.yaml"

    context = _load_json(context_path)
    staff_rows = _load_csv_rows(staff_path)
    log_rows = _load_csv_rows(drill_log_path)
    shifts_yaml = _load_shifts_yaml(shifts_yaml_path)

    # If inputs are missing or malformed, cannot proceed with deeper checks
    if (
        context is None
        or staff_rows is None
        or log_rows is None
        or shifts_yaml is None
        or "reference_date" not in context
        or "drill_type" not in context
        or "duration_minutes" not in context
    ):
        return scores

    ref_date = _parse_date_ymd(str(context.get("reference_date", "")).strip())
    if ref_date is None:
        return scores
    drill_type = str(context.get("drill_type")).strip()
    try:
        duration_minutes = int(context.get("duration_minutes"))
    except Exception:
        return scores

    (last_year, last_month), (next_year, next_month) = _compute_last_and_next_month(ref_date)
    last_start, last_end = _month_start_end(last_year, last_month)
    next_start, next_end = _month_start_end(next_year, next_month)
    next_month_name = calendar.month_name[next_month]

    # Expected outputs
    next_tag = f"{next_year:04d}-{next_month:02d}"
    plan_path = workspace / "output" / f"drill_plan_{next_tag}_{drill_type}.csv"
    summary_path = workspace / "output" / f"drill_status_summary_{next_tag}_{drill_type}.md"
    emails_dir = workspace / "output" / "emails"

    # Staff by shift
    staff_by_shift = {}
    all_shifts = set()
    for r in staff_rows:
        shift = (r.get("Shift") or "").strip()
        email = (r.get("Email") or "").strip()
        if shift and email:
            all_shifts.add(shift)
            staff_by_shift.setdefault(shift, set()).add(email)
    if not all_shifts:
        return scores

    # Attended by shift in last month for given drill type
    attended_by_shift = {s: set() for s in all_shifts}
    for r in log_rows:
        dt = _parse_date_ymd((r.get("Date") or "").strip())
        if dt is None:
            continue
        if not (last_start <= dt <= last_end):
            continue
        if (r.get("DrillType") or "").strip() != drill_type:
            continue
        shift = (r.get("Shift") or "").strip()
        if shift not in all_shifts:
            continue
        participants = _semicolon_split(r.get("Participants") or "")
        for p in participants:
            if p:
                attended_by_shift[shift].add(p)

    missed_by_shift = {}
    for s in all_shifts:
        missed_by_shift[s] = staff_by_shift.get(s, set()) - attended_by_shift.get(s, set())

    # Validate plan CSV
    plan_rows = _load_csv_rows(plan_path) if plan_path.exists() else None
    expected_header = ["Shift", "DrillType", "Date", "StartTime", "DurationMinutes", "Location", "RequiredAttendees"]
    if plan_path.exists():
        try:
            with plan_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
    else:
        header = None

    if plan_path.exists() and header == expected_header:
        scores["plan_file_exists_and_header"] = 1.0

    plan_by_shift = {}
    if plan_rows is not None and header == expected_header:
        for r in plan_rows:
            shift = (r.get("Shift") or "").strip()
            if shift:
                plan_by_shift[shift] = r

        if set(plan_by_shift.keys()) == set(all_shifts) and len(plan_by_shift) == len(all_shifts) and len(plan_rows) == len(all_shifts):
            scores["plan_rows_cover_shifts"] = 1.0

        # Dates valid: weekday within next month range
        valid_dates = 0
        for s in all_shifts:
            r = plan_by_shift.get(s)
            if not r:
                continue
            d = _parse_date_ymd((r.get("Date") or "").strip())
            if d and next_start <= d <= next_end and _is_weekday(d):
                valid_dates += 1
        scores["plan_dates_valid"] = (valid_dates / len(all_shifts)) if all_shifts else 0.0

        # Times, locations, duration, drill type valid
        tld_ok = 0
        for s in all_shifts:
            r = plan_by_shift.get(s)
            if not r or s not in shifts_yaml:
                continue
            if (r.get("DrillType") or "").strip() != drill_type:
                continue
            st = (r.get("StartTime") or "").strip()
            loc = (r.get("Location") or "").strip()
            dur_str = (r.get("DurationMinutes") or "").strip()
            try:
                dur_val = int(dur_str)
            except Exception:
                continue
            if st == (shifts_yaml[s].get("default_time") or "").strip() and \
               loc == (shifts_yaml[s].get("location") or "").strip() and \
               dur_val == duration_minutes:
                tld_ok += 1
        scores["plan_times_locations_duration_valid"] = (tld_ok / len(all_shifts)) if all_shifts else 0.0

        # RequiredAttendees correctness (set equality)
        ra_ok = 0
        for s in all_shifts:
            r = plan_by_shift.get(s)
            if not r:
                continue
            ra_set = set(_semicolon_split((r.get("RequiredAttendees") or "").strip()))
            if ra_set == missed_by_shift.get(s, set()):
                ra_ok += 1
        scores["plan_required_attendees_correct"] = (ra_ok / len(all_shifts)) if all_shifts else 0.0

    # Validate status summary
    if summary_path.exists():
        scores["status_summary_exists"] = 1.0
        summary_text = _safe_read_text(summary_path)
        sections = _extract_shift_sections(summary_text, sorted(all_shifts))
        cnt_ok = 0
        emails_ok = 0
        for s in all_shifts:
            sect = sections.get(s, "")
            counts = _extract_counts_in_text(sect)
            expected_total = len(staff_by_shift.get(s, set()))
            expected_attended = len(attended_by_shift.get(s, set()))
            expected_missed = len(missed_by_shift.get(s, set()))
            if counts is not None:
                t, a, m = counts
                if t == expected_total and a == expected_attended and m == expected_missed:
                    cnt_ok += 1
            sect_emails = _extract_emails(sect)
            expected_missed_set = missed_by_shift.get(s, set())
            # Require exact equality with expected missed set
            if sect_emails == expected_missed_set:
                emails_ok += 1
        scores["status_counts_correct"] = (cnt_ok / len(all_shifts)) if all_shifts else 0.0
        scores["status_missed_emails_listed"] = (emails_ok / len(all_shifts)) if all_shifts else 0.0
        # Include a note referencing shifts.yaml and duration minutes
        note_ok = 0.0
        if re.search(r"shifts\.yaml", summary_text, re.IGNORECASE):
            dur_num = str(duration_minutes)
            if re.search(rf"\b{dur_num}\b", summary_text) and re.search(r"minute", summary_text, re.IGNORECASE):
                note_ok = 1.0
        scores["status_includes_scheduling_note"] = note_ok

    # Validate emails
    expected_email_files = [workspace / "output" / "emails" / f"{s}_{drill_type}_drill_{next_tag}.txt" for s in all_shifts]
    exist_count = sum(1 for p in expected_email_files if p.exists())
    scores["emails_files_exist"] = (exist_count / len(expected_email_files)) if expected_email_files else 0.0

    # Prepare plan details (if available)
    plan_details = {}
    if plan_by_shift:
        for s in all_shifts:
            r = plan_by_shift.get(s)
            if not r:
                continue
            plan_details[s] = {
                "date": (r.get("Date") or "").strip(),
                "time": (r.get("StartTime") or "").strip(),
                "location": (r.get("Location") or "").strip(),
                "duration": str(duration_minutes),
                "to_set": set(_semicolon_split((r.get("RequiredAttendees") or "").strip())),
            }

    headers_ok = 0
    body_ok = 0
    consistent_with_plan_ok = 0
    to_vs_plan_ok = 0
    for s in all_shifts:
        email_path = workspace / "output" / "emails" / f"{s}_{drill_type}_drill_{next_tag}.txt"
        if not email_path.exists():
            continue
        text = _safe_read_text(email_path)
        if not text:
            continue
        lines = [ln.rstrip("\n") for ln in text.splitlines()]
        non_empty = [ln for ln in lines if ln.strip() != ""]
        if len(non_empty) < 2:
            continue
        to_line = non_empty[0]
        subj_line = non_empty[1]

        # Validate To
        to_match = re.match(r"^To:\s*(.*)$", to_line)
        if to_match:
            to_list = _semicolon_split(to_match.group(1))
            to_set = set(to_list)
            expected_to_set = missed_by_shift.get(s, set())
            to_ok = to_set == expected_to_set
        else:
            to_ok = False

        # Validate Subject with month name
        expected_subject = f"Subject: {next_month_name} {next_year} {drill_type.capitalize()} Drill - Attendance Required (Shift: {s})"
        subj_ok = subj_line.strip() == expected_subject
        if to_ok and subj_ok:
            headers_ok += 1

        # Body must include scheduled details
        # If plan exists for this shift, require exact date/time/location/duration in body
        if subj_line in lines:
            body_text = "\n".join(lines[lines.index(subj_line) + 1 :])
        else:
            body_text = "\n".join(lines[2:])

        time_expected = (shifts_yaml.get(s, {}).get("default_time") or "").strip()
        loc_expected = (shifts_yaml.get(s, {}).get("location") or "").strip()
        has_time = bool(time_expected) and (time_expected in body_text)
        has_loc = bool(loc_expected) and (loc_expected in body_text)
        has_dur = re.search(rf"\b{duration_minutes}\b", body_text) is not None
        has_mandatory = re.search(r"\bmandatory\b", body_text, re.IGNORECASE) is not None

        if s in plan_details:
            pd = plan_details[s]
            has_date = pd["date"] and (pd["date"] in body_text)
            if has_date and has_time and has_loc and has_dur and has_mandatory:
                body_ok += 1
            # Consistency with plan details
            if pd["date"] in body_text and pd["time"] in body_text and pd["location"] in body_text and re.search(rf"\b{pd['duration']}\b", body_text):
                consistent_with_plan_ok += 1
            # To vs plan RequiredAttendees
            if to_match and set(_semicolon_split(to_match.group(1))) == pd["to_set"]:
                to_vs_plan_ok += 1
        else:
            # If no plan available, require a next-month date token in ISO format
            date_pattern = re.findall(rf"\b{next_year:04d}-{next_month:02d}-(0[1-9]|[12][0-9]|3[01])\b", body_text)
            has_date_any = len(date_pattern) > 0
            # Also enforce weekday if possible by checking any such date parses to weekday
            date_weekday_ok = False
            for day in re.findall(rf"\b{next_year:04d}-{next_month:02d}-(\d{{2}})\b", body_text):
                d = _parse_date_ymd(f"{next_year:04d}-{next_month:02d}-{day}")
                if d and next_start <= d <= next_end and _is_weekday(d):
                    date_weekday_ok = True
                    break
            if has_date_any and date_weekday_ok and has_time and has_loc and has_dur and has_mandatory:
                body_ok += 1

    total_shifts = len(all_shifts)
    scores["emails_headers_valid"] = (headers_ok / total_shifts) if total_shifts else 0.0
    scores["emails_body_includes_details"] = (body_ok / total_shifts) if total_shifts else 0.0
    if total_shifts > 0:
        eligible = sum(1 for s in all_shifts if (workspace / "output" / "emails" / f"{s}_{drill_type}_drill_{next_tag}.txt").exists() and s in plan_details)
        scores["emails_consistent_with_plan"] = (consistent_with_plan_ok / eligible) if eligible else 0.0
        scores["internal_consistency_emails_to_vs_plan"] = (to_vs_plan_ok / eligible) if eligible else 0.0

    # Internal consistency: plan vs summary missed emails
    if plan_by_shift and summary_path.exists():
        summary_text = _safe_read_text(summary_path)
        sections = _extract_shift_sections(summary_text, sorted(all_shifts))
        match_count = 0
        eligible = 0
        for s in all_shifts:
            plan_ra = plan_by_shift.get(s, {}).get("RequiredAttendees", "")
            plan_set = set(_semicolon_split(plan_ra))
            sect = sections.get(s, "")
            if sect:
                eligible += 1
                sect_emails = _extract_emails(sect)
                if sect_emails == plan_set:
                    match_count += 1
        scores["internal_consistency_plan_vs_summary"] = (match_count / eligible) if eligible else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()