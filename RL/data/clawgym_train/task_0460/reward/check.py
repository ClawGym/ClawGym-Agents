import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _date_to_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _bool_from_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    val = s.strip().lower()
    if val in {"true", "t", "1", "yes", "y"}:
        return True
    if val in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
        return parent_resolved in child_resolved.parents or child_resolved == parent_resolved
    except Exception:
        return False


def _extract_checklist_excerpt(resource_path: Path) -> List[str]:
    text = _read_text(resource_path)
    if text is None:
        return []
    lines = text.splitlines()
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Transfer Checklist":
            header_idx = i
            break
    if header_idx is None:
        return []
    bullets = []
    for ln in lines[header_idx + 1:]:
        stripped = ln.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            break
        if stripped.startswith("- "):
            bullets.append(stripped)
            if len(bullets) >= 3:
                break
    return bullets[:3]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_json_exists": 0.0,
        "schedule_item_count_correct": 0.0,
        "schedule_items_content_correct": 0.0,
        "email_files_count_match_schedule": 0.0,
        "email_filenames_pattern_valid": 0.0,
        "email_subjects_correct": 0.0,
        "email_body_placeholders_replaced": 0.0,
        "checklist_excerpt_correct_in_emails": 0.0,
        "missing_resources_file_correct": 0.0,
        "summary_csv_exists_and_structure": 0.0,
        "summary_csv_content_correct": 0.0,
    }

    # Load inputs
    students_csv = workspace / "input" / "students.csv"
    deadlines_csv = workspace / "input" / "application_deadlines.csv"
    resources_dir = workspace / "input" / "university_resources"
    reminder_template_path = workspace / "input" / "templates" / "reminder_template.txt"
    followup_template_path = workspace / "input" / "templates" / "followup_template.txt"

    students_rows = _read_csv_dicts(students_csv)
    deadlines_rows = _read_csv_dicts(deadlines_csv)
    reminder_template = _read_text(reminder_template_path)
    followup_template = _read_text(followup_template_path)

    inputs_ok = all([
        students_rows is not None,
        deadlines_rows is not None,
        reminder_template is not None,
        followup_template is not None,
    ])

    # Build deadline lookup map
    deadline_map: Dict[tuple, datetime] = {}
    if deadlines_rows is not None:
        for r in deadlines_rows:
            uni = (r.get("university") or "").strip()
            prog = (r.get("program_interest") or "").strip()
            d = _parse_date(r.get("application_deadline") or "")
            if uni and prog and d:
                deadline_map[(uni, prog)] = d

    # Available resources by code (stem)
    available_resources = set()
    try:
        if resources_dir.exists() and resources_dir.is_dir():
            for p in resources_dir.iterdir():
                if p.is_file() and p.suffix.lower() == ".md":
                    available_resources.add(p.stem)
    except Exception:
        available_resources = set()

    # Compute expected schedule items and missing resources
    expected_items: List[Dict[str, Any]] = []
    expected_missing_resources_sorted: List[str] = []
    students_ok = students_rows is not None

    if students_ok:
        universities_in_students = set()
        for r in students_rows:
            target = (r.get("target_universities") or "").strip()
            primary = target.split(";")[0].strip() if target else ""
            if primary:
                universities_in_students.add(primary)
        missing_resources = sorted([u for u in universities_in_students if u not in available_resources])
        expected_missing_resources_sorted = missing_resources

        for r in students_rows:
            sid = (r.get("student_id") or "").strip()
            sname = (r.get("name") or "").strip()
            target = (r.get("target_universities") or "").strip()
            primary = target.split(";")[0].strip() if target else ""
            program = (r.get("program_interest") or "").strip()
            next_deadline_str = (r.get("next_deadline") or "").strip()
            preferred_channel = (r.get("preferred_channel") or "").strip()
            completed_steps = (r.get("completed_steps") or "").strip()

            deadline_dt: Optional[datetime] = None
            if next_deadline_str:
                deadline_dt = _parse_date(next_deadline_str)
            else:
                deadline_dt = deadline_map.get((primary, program))
            if not (sid and sname and primary and program and deadline_dt):
                continue

            deadline_str = _date_to_str(deadline_dt)
            resource_available = primary in available_resources
            has_submitted = "Submitted application" in completed_steps

            if has_submitted:
                send_dt = deadline_dt + timedelta(days=3)
                expected_items.append({
                    "student_id": sid,
                    "student_name": sname,
                    "primary_university": primary,
                    "program_interest": program,
                    "deadline": deadline_str,
                    "type": "follow-up",
                    "channel": preferred_channel,
                    "offset_days": None,
                    "send_date": _date_to_str(send_dt),
                    "resource_available": resource_available,
                })
            else:
                for offset in [21, 7, 2]:
                    send_dt = deadline_dt - timedelta(days=offset)
                    expected_items.append({
                        "student_id": sid,
                        "student_name": sname,
                        "primary_university": primary,
                        "program_interest": program,
                        "deadline": deadline_str,
                        "type": "reminder",
                        "channel": preferred_channel,
                        "offset_days": offset,
                        "send_date": _date_to_str(send_dt),
                        "resource_available": resource_available,
                    })

    # Output paths
    schedule_json_path = workspace / "output" / "reminders" / "schedule.json"
    summary_csv_path = workspace / "output" / "reminders" / "summary.csv"
    missing_resources_path = workspace / "output" / "reminders" / "missing_resources.txt"
    emails_dir = workspace / "output" / "emails"

    # schedule.json existence and parse
    schedule = _load_json(schedule_json_path)
    if isinstance(schedule, list):
        scores["schedule_json_exists"] = 1.0
    else:
        schedule = None

    # Build expected index keys
    expected_keys = set()
    expected_index: Dict[tuple, Dict[str, Any]] = {}
    if expected_items:
        for item in expected_items:
            key = (item["student_id"], item["type"], item["offset_days"], item["send_date"])
            expected_keys.add(key)
            expected_index[key] = item

    # Collect schedule keys
    schedule_keys = set()
    schedule_index: Dict[tuple, Dict[str, Any]] = {}
    schedule_len_ok = False
    if schedule is not None and isinstance(schedule, list):
        try:
            for obj in schedule:
                sid = obj.get("student_id")
                typ = obj.get("type")
                off = obj.get("offset_days") if "offset_days" in obj else None
                send = obj.get("send_date")
                key = (sid, typ, off, send)
                schedule_keys.add(key)
                schedule_index[key] = obj
            if expected_items:
                schedule_len_ok = (len(schedule) == len(expected_items))
                if schedule_len_ok:
                    scores["schedule_item_count_correct"] = 1.0
        except Exception:
            pass

    # Validate schedule item content strictly
    fields_ok = False
    if schedule is not None and expected_items and schedule_len_ok:
        if schedule_keys == expected_keys:
            all_match = True
            for key, exp in expected_index.items():
                obj = schedule_index.get(key, {})
                if obj.get("student_id") != exp["student_id"]:
                    all_match = False
                    break
                if obj.get("student_name") != exp["student_name"]:
                    all_match = False
                    break
                if obj.get("primary_university") != exp["primary_university"]:
                    all_match = False
                    break
                if obj.get("program_interest") != exp["program_interest"]:
                    all_match = False
                    break
                if obj.get("deadline") != exp["deadline"]:
                    all_match = False
                    break
                if obj.get("type") != exp["type"]:
                    all_match = False
                    break
                if obj.get("channel") != exp["channel"]:
                    all_match = False
                    break
                if exp["type"] == "reminder":
                    off_val = obj.get("offset_days", None)
                    if not (isinstance(off_val, int) and not isinstance(off_val, bool)):
                        all_match = False
                        break
                    if off_val != exp["offset_days"]:
                        all_match = False
                        break
                else:
                    if obj.get("offset_days", "SENTINEL") is not None:
                        all_match = False
                        break
                if obj.get("send_date") != exp["send_date"]:
                    all_match = False
                    break
                ra = obj.get("resource_available")
                if ra is not True and ra is not False:
                    all_match = False
                    break
                if ra != exp["resource_available"]:
                    all_match = False
                    break
                # email_draft_path rule: non-null string for email channel, null otherwise
                ch = obj.get("channel")
                if ch == "email":
                    edp = obj.get("email_draft_path", None)
                    if not isinstance(edp, str) or not edp:
                        all_match = False
                        break
                else:
                    if obj.get("email_draft_path", "SENTINEL") is not None:
                        all_match = False
                        break
            if all_match:
                fields_ok = True
    if fields_ok:
        scores["schedule_items_content_correct"] = 1.0

    # Email files checks
    schedule_email_items: List[Dict[str, Any]] = []
    if schedule is not None and isinstance(schedule, list):
        for obj in schedule:
            if str(obj.get("channel", "")).lower() == "email":
                schedule_email_items.append(obj)

    existing_email_files: List[Path] = []
    try:
        if emails_dir.exists() and emails_dir.is_dir():
            for p in emails_dir.iterdir():
                if p.is_file() and p.suffix.lower() == ".txt":
                    existing_email_files.append(p)
    except Exception:
        existing_email_files = []

    non_null_email_paths = [obj for obj in schedule_email_items if obj.get("email_draft_path") is not None]
    if schedule is not None and isinstance(schedule, list):
        if len(existing_email_files) == len(non_null_email_paths):
            scores["email_files_count_match_schedule"] = 1.0

    filenames_ok = True
    subjects_ok = True
    placeholders_ok = True
    checklist_ok = True

    # Precompute checklist excerpts per university
    checklist_cache: Dict[str, List[str]] = {}
    if expected_items:
        for uni in {item["primary_university"] for item in expected_items}:
            if uni in available_resources:
                path = resources_dir / f"{uni}.md"
                checklist_cache[uni] = _extract_checklist_excerpt(path)
            else:
                checklist_cache[uni] = ["- Review the transfer checklist on the university's official site."]

    if schedule is not None and isinstance(schedule, list) and inputs_ok and expected_items:
        for obj in schedule_email_items:
            email_path_str = obj.get("email_draft_path")
            if not isinstance(email_path_str, str):
                filenames_ok = False
                continue
            email_path = (workspace / email_path_str) if not Path(email_path_str).is_absolute() else Path(email_path_str)
            if not email_path.exists() or not email_path.is_file():
                filenames_ok = False
            if not _is_subpath(email_path, emails_dir):
                filenames_ok = False
            fname = email_path.name
            send_date = obj.get("send_date", "")
            sid = obj.get("student_id", "")
            uni = obj.get("primary_university", "")
            if not (isinstance(send_date, str) and isinstance(sid, str) and isinstance(uni, str)):
                filenames_ok = False
            else:
                if not fname.startswith(send_date):
                    filenames_ok = False
                if sid not in fname or uni not in fname:
                    filenames_ok = False
                if Path(fname).suffix.lower() != ".txt":
                    filenames_ok = False
            content = _read_text(email_path)
            if content is None:
                subjects_ok = False
                placeholders_ok = False
                checklist_ok = False
                continue
            lines = content.splitlines()
            subject_line = lines[0].strip() if lines else ""
            key = (obj.get("student_id"), obj.get("type"), obj.get("offset_days"), obj.get("send_date"))
            exp_item = expected_index.get(key)
            if not exp_item:
                subjects_ok = False
            else:
                if exp_item["type"] == "reminder":
                    exp_subject = f"Subject: Reminder: {exp_item['primary_university']} transfer deadline in {exp_item['offset_days']} days ({exp_item['deadline']})"
                else:
                    exp_subject = f"Subject: Follow-up: Confirm {exp_item['primary_university']} application received"
                if subject_line != exp_subject:
                    subjects_ok = False
            placeholder_tokens = ["{student_name}", "{university}", "{program_interest}", "{deadline}", "{days_before}", "{checklist_excerpt}"]
            if any(tok in content for tok in placeholder_tokens):
                placeholders_ok = False
            if exp_item:
                if exp_item["student_name"] not in content:
                    placeholders_ok = False
                if exp_item["program_interest"] not in content:
                    placeholders_ok = False
                if exp_item["deadline"] not in content:
                    placeholders_ok = False
                if exp_item["type"] == "reminder":
                    if str(exp_item["offset_days"]) not in content:
                        placeholders_ok = False
            if exp_item:
                uni_code = exp_item["primary_university"]
                expected_bullets = checklist_cache.get(uni_code, [])
                if not expected_bullets:
                    expected_bullets = ["- Review the transfer checklist on the university's official site."]
                for b in expected_bullets:
                    if b not in content:
                        checklist_ok = False

    if filenames_ok and schedule is not None:
        scores["email_filenames_pattern_valid"] = 1.0
    if subjects_ok and schedule is not None:
        scores["email_subjects_correct"] = 1.0
    if placeholders_ok and schedule is not None:
        scores["email_body_placeholders_replaced"] = 1.0
    if checklist_ok and schedule is not None:
        scores["checklist_excerpt_correct_in_emails"] = 1.0

    # missing_resources.txt correctness
    missing_ok = False
    if students_ok:
        given_missing_text = _read_text(missing_resources_path)
        if given_missing_text is not None:
            given_lines = [ln.strip() for ln in given_missing_text.splitlines() if ln.strip() != ""]
            if given_lines == expected_missing_resources_sorted:
                missing_ok = True
    if missing_ok:
        scores["missing_resources_file_correct"] = 1.0

    # summary.csv checks
    summary_rows = _read_csv_dicts(summary_csv_path)
    if summary_rows is not None:
        try:
            with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        expected_header = ["student_id", "student_name", "primary_university", "deadline", "total_scheduled", "emails_generated", "has_primary_resource"]
        if header == expected_header:
            scores["summary_csv_exists_and_structure"] = 1.0

    summary_ok = False
    if summary_rows is not None and schedule is not None and isinstance(schedule, list) and inputs_ok and expected_items:
        expected_schedule_count: Dict[str, int] = {}
        expected_deadline_per_student: Dict[str, str] = {}
        expected_name_per_student: Dict[str, str] = {}
        expected_primary_per_student: Dict[str, str] = {}
        expected_resource_per_student: Dict[str, bool] = {}
        for item in expected_items:
            sid = item["student_id"]
            expected_schedule_count[sid] = expected_schedule_count.get(sid, 0) + 1
            expected_deadline_per_student[sid] = item["deadline"]
            expected_primary_per_student[sid] = item["primary_university"]
            expected_resource_per_student[sid] = item["resource_available"]
        if students_rows:
            for r in students_rows:
                sid = (r.get("student_id") or "").strip()
                expected_name_per_student[sid] = (r.get("name") or "").strip()
        email_counts_from_dir: Dict[str, int] = {}
        for sid in expected_schedule_count.keys():
            cnt = 0
            for p in existing_email_files:
                if sid in p.name:
                    cnt += 1
            email_counts_from_dir[sid] = cnt
        student_ids_expected = set(expected_schedule_count.keys())
        student_ids_found = set()
        per_row_ok = True
        for row in summary_rows:
            sid = (row.get("student_id") or "").strip()
            student_ids_found.add(sid)
            sname = (row.get("student_name") or "").strip()
            primary = (row.get("primary_university") or "").strip()
            deadline = (row.get("deadline") or "").strip()
            total_scheduled_str = (row.get("total_scheduled") or "").strip()
            emails_generated_str = (row.get("emails_generated") or "").strip()
            has_resource_str = (row.get("has_primary_resource") or "").strip()
            if sid not in student_ids_expected:
                per_row_ok = False
                break
            if expected_name_per_student.get(sid, "") != sname:
                per_row_ok = False
                break
            if expected_primary_per_student.get(sid, "") != primary:
                per_row_ok = False
                break
            if expected_deadline_per_student.get(sid, "") != deadline:
                per_row_ok = False
                break
            try:
                total_sched_val = int(total_scheduled_str)
            except Exception:
                per_row_ok = False
                break
            if total_sched_val != expected_schedule_count.get(sid, -1):
                per_row_ok = False
                break
            try:
                emails_gen_val = int(emails_generated_str)
            except Exception:
                per_row_ok = False
                break
            if emails_gen_val != email_counts_from_dir.get(sid, -1):
                per_row_ok = False
                break
            has_res_val = _bool_from_str(has_resource_str)
            if has_res_val is None:
                per_row_ok = False
                break
            if has_res_val != expected_resource_per_student.get(sid, False):
                per_row_ok = False
                break
        if per_row_ok and student_ids_found == student_ids_expected:
            summary_ok = True

    if summary_ok:
        scores["summary_csv_content_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()