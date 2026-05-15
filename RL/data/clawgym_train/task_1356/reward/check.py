import json
import sys
import csv
from pathlib import Path
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


def load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def parse_time_hhmm(hhmm: str):
    try:
        return datetime.strptime(hhmm, "%H:%M")
    except Exception:
        return None


def format_hhmm(dt: datetime):
    return dt.strftime("%H:%M")


def normalize_dashes(s: str) -> str:
    return s.replace("–", "-").replace("—", "-")


def section_bounds_by_heading(content: str, heading: str):
    lines = content.splitlines(keepends=True)
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start == -1:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## ") and lines[j].strip() != heading:
            end = j
            break
    start_char = sum(len(l) for l in lines[:start])
    end_char = sum(len(l) for l in lines[:end])
    return (start_char, end_char)


def compute_expected_values(workspace: Path):
    schedule_path = workspace / "input" / "rehearsal_schedule.csv"
    rows = load_csv_dicts(schedule_path)
    if not rows:
        return None
    target = None
    for r in rows:
        if str(r.get("next", "")).strip().lower() == "true":
            target = r
            break
    if not target:
        return None
    rehearsal_date = target.get("date", "").strip()
    start_time = target.get("start_time", "").strip()
    duration_str = str(target.get("duration_minutes", "")).strip()
    location = target.get("location", "").strip()
    songs_str = target.get("songs", "").strip()
    try:
        duration_minutes = int(duration_str)
    except Exception:
        return None
    if not (rehearsal_date and start_time and location):
        return None
    start_dt = parse_time_hhmm(start_time)
    if not start_dt:
        return None
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    end_time = format_hhmm(end_dt)
    song_titles = [s.strip() for s in songs_str.split("|") if s.strip()]
    sorted_songs = sorted(song_titles, key=lambda x: x.lower())
    total_songs = len(sorted_songs)
    catalog_path = workspace / "input" / "songs_catalog.json"
    catalog = load_json_safe(catalog_path)
    if catalog is None or not isinstance(catalog, list):
        return None
    is_new_map = {str(item.get("title", "")).strip(): bool(item.get("is_new", False)) for item in catalog}
    new_songs_count = sum(1 for t in sorted_songs if is_new_map.get(t, False))
    workload_path = workspace / "input" / "design_workload.csv"
    tasks = load_csv_dicts(workload_path)
    if tasks is None:
        return None
    conflicts = []
    for t in tasks:
        if str(t.get("date", "")).strip() != rehearsal_date:
            continue
        task_start = parse_time_hhmm(str(t.get("start_time", "")).strip())
        task_end = parse_time_hhmm(str(t.get("end_time", "")).strip())
        if not task_start or not task_end:
            continue
        if start_dt.time() < task_end.time() and task_start.time() < end_dt.time():
            conflicts.append({
                "task": str(t.get("task", "")).strip(),
                "start_time": format_hhmm(task_start),
                "end_time": format_hhmm(task_end),
                "client": str(t.get("client", "")).strip(),
            })
    return {
        "rehearsal_date": rehearsal_date,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "sorted_songs": sorted_songs,
        "total_songs": total_songs,
        "new_songs_count": new_songs_count,
        "conflicts": conflicts,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "automation_script_present": 0.0,
        "status_report_exists_and_content": 0.0,
        "email_subject_and_content_correct": 0.0,
        "email_secular_tone": 0.0,
        "conflicts_included_in_outputs": 0.0,
        "song_list_sorted_and_counts_correct": 0.0,
        "wrapper_script_and_log_present": 0.0,
        "cron_schedule_correct": 0.0,
        "notes_section_updated_correctly": 0.0,
        "cross_file_consistency": 0.0,
    }

    expected = compute_expected_values(workspace)
    status_report_path = workspace / "output" / "status_report.md"
    draft_email_path = workspace / "output" / "draft_email.txt"
    run_weekly_path = workspace / "output" / "schedule" / "run_weekly.sh"
    weekly_cron_path = workspace / "output" / "schedule" / "weekly_cron.txt"
    logs_last_run_path = workspace / "output" / "logs" / "last_run.txt"
    notes_path = workspace / "input" / "notes.md"

    automation_dir = workspace / "automation"
    candidates = []
    if automation_dir.exists():
        for p in automation_dir.iterdir():
            if p.is_file() and p.name.startswith("weekly_brief"):
                candidates.append(p)
    if candidates:
        scores["automation_script_present"] = 1.0

    if expected is None:
        return scores

    status_ok = False
    status_content = read_text_safe(status_report_path)
    if status_content:
        norm_status = normalize_dashes(status_content)
        expected_date = expected["rehearsal_date"]
        expected_time_range_hyphen = f'{expected["start_time"]}-{expected["end_time"]}'
        expected_time_range_endash = f'{expected["start_time"]}–{expected["end_time"]}'
        expected_loc = expected["location"]
        if (expected_date in status_content and
            (expected_time_range_endash in status_content or expected_time_range_hyphen in norm_status) and
            expected_loc in status_content):
            songs_ok = True
            for t in expected["sorted_songs"]:
                if t not in status_content:
                    songs_ok = False
                    break
            if songs_ok:
                positions = [status_content.find(t) for t in expected["sorted_songs"]]
                if any(pos == -1 for pos in positions) or positions != sorted(positions):
                    songs_ok = False
            counts_ok = (str(expected["total_songs"]) in status_content and str(expected["new_songs_count"]) in status_content)
            conflicts_ok = True
            if expected["conflicts"]:
                if "None noted." in status_content:
                    conflicts_ok = False
                else:
                    c = expected["conflicts"][0]
                    if not (c["client"] in status_content and c["start_time"] in status_content and c["end_time"] in status_content):
                        conflicts_ok = False
            else:
                conflicts_ok = ("None noted." in status_content)
            status_ok = songs_ok and counts_ok and conflicts_ok
    scores["status_report_exists_and_content"] = 1.0 if status_ok else 0.0

    email_ok = False
    email_content = read_text_safe(draft_email_path)
    if email_content:
        lines = email_content.splitlines()
        if lines:
            subject_expected = f"Subject: Weekly rehearsal check-in — {expected['rehearsal_date']}"
            subject_ok = (lines[0].strip() == subject_expected)
            body = "\n".join(lines[1:])
            placeholders_resolved = "{{" not in email_content and "}}" not in email_content
            norm_body = normalize_dashes(body)
            time_hyphen = f"{expected['rehearsal_date']} {expected['start_time']}-{expected['end_time']}"
            time_endash = f"{expected['rehearsal_date']} {expected['start_time']}–{expected['end_time']}"
            when_ok = (time_endash in body or time_hyphen in norm_body)
            where_ok = (expected["location"] in body)
            song_list_str = ", ".join(expected["sorted_songs"])
            songs_line_ok = (str(expected["total_songs"]) in body and str(expected["new_songs_count"]) in body and song_list_str in body)
            sender_ok = "Avery" in body
            email_ok = subject_ok and placeholders_resolved and when_ok and where_ok and songs_line_ok and sender_ok
    scores["email_subject_and_content_correct"] = 1.0 if email_ok else 0.0

    secular_ok = False
    if email_content:
        lower = email_content.lower()
        religious_terms = [
            "bless", "blessing", "blessed", "pray", "prayer", "faith",
            "worship", "church", "god", "holy", "spirit", "amen", "sacred",
            "scripture", "psalm", "hymn", "gospel", "grace", "devotion",
        ]
        if not any(term in lower for term in religious_terms):
            secular_ok = True
    scores["email_secular_tone"] = 1.0 if secular_ok else 0.0

    conflicts_ok = False
    if expected["conflicts"]:
        def content_has_conflict(content: str) -> bool:
            if not content:
                return False
            if "None noted." in content:
                return False
            c = expected["conflicts"][0]
            return (c["client"] in content and c["start_time"] in content and c["end_time"] in content)
        if content_has_conflict(email_content or "") and content_has_conflict(status_content or ""):
            conflicts_ok = True
    else:
        if (email_content and "None noted." in email_content) and (status_content and "None noted." in status_content):
            conflicts_ok = True
    scores["conflicts_included_in_outputs"] = 1.0 if conflicts_ok else 0.0

    songs_ok = False
    if email_content:
        song_list_str = ", ".join(expected["sorted_songs"])
        counts_ok = (f"{expected['total_songs']}" in email_content and f"{expected['new_songs_count']}" in email_content)
        order_ok = song_list_str in email_content
        songs_ok = counts_ok and order_ok
    if songs_ok and status_content:
        positions = [status_content.find(t) for t in expected["sorted_songs"]]
        if any(pos == -1 for pos in positions) or positions != sorted(positions):
            songs_ok = False
    scores["song_list_sorted_and_counts_correct"] = 1.0 if songs_ok else 0.0

    wrapper_ok = False
    wrapper_text = read_text_safe(run_weekly_path)
    last_run_text = read_text_safe(logs_last_run_path)
    if wrapper_text:
        invokes = "automation/weekly_brief" in wrapper_text
        mentions_log = "output/logs/last_run.txt" in wrapper_text
        if invokes and mentions_log and last_run_text is not None and len(last_run_text.strip().splitlines()) >= 1 and last_run_text.strip() != "":
            wrapper_ok = True
    scores["wrapper_script_and_log_present"] = 1.0 if wrapper_ok else 0.0

    cron_ok = False
    cron_text = read_text_safe(weekly_cron_path)
    if cron_text is not None:
        expected_cron = "0 9 * * MON bash output/schedule/run_weekly.sh"
        cron_ok = cron_text.strip() == expected_cron
    scores["cron_schedule_correct"] = 1.0 if cron_ok else 0.0

    notes_ok = False
    notes_text = read_text_safe(notes_path)
    if notes_text:
        preserved_ok = (
            "## Ideas to help" in notes_text and
            "- Create clean lyric sheets" in notes_text and
            "- Design simple cue cards" in notes_text and
            "Keeping my planning secular and supportive." in notes_text
        )
        bounds = section_bounds_by_heading(notes_text, "## Next rehearsal")
        next_section_ok = False
        if bounds:
            sec = notes_text[bounds[0]:bounds[1]]
            norm_sec = normalize_dashes(sec)
            tr_hyphen = f"{expected['start_time']}-{expected['end_time']}"
            tr_endash = f"{expected['start_time']}–{expected['end_time']}"
            has_date = expected["rehearsal_date"] in sec
            has_time = (tr_endash in sec or tr_hyphen in norm_sec)
            has_loc = expected["location"] in sec
            has_counts = (str(expected["total_songs"]) in sec and str(expected["new_songs_count"]) in sec)
            no_old = ("2026-04-11" not in sec and "Echo, Light Path, Rise Up" not in sec)
            if expected["conflicts"]:
                c = expected["conflicts"][0]
                has_conflict_note = (c["client"] in sec or "conflict" in sec.lower() or c["start_time"] in sec or c["end_time"] in sec)
            else:
                has_conflict_note = ("None noted." in sec)
            next_section_ok = has_date and has_time and has_loc and has_counts and no_old and has_conflict_note
        notes_ok = preserved_ok and next_section_ok
    scores["notes_section_updated_correctly"] = 1.0 if notes_ok else 0.0

    consistency_ok = False
    if status_content and email_content:
        date_ok = (expected["rehearsal_date"] in status_content and expected["rehearsal_date"] in email_content)
        loc_ok = (expected["location"] in status_content and expected["location"] in email_content)
        status_norm = normalize_dashes(status_content)
        email_norm = normalize_dashes(email_content)
        time_range_str = f"{expected['start_time']}-{expected['end_time']}"
        time_ok = (time_range_str in status_norm and time_range_str in email_norm)
        counts_ok = (str(expected["total_songs"]) in status_content and str(expected["total_songs"]) in email_content and
                     str(expected["new_songs_count"]) in status_content and str(expected["new_songs_count"]) in email_content)
        consistency_ok = date_ok and loc_ok and time_ok and counts_ok
    scores["cross_file_consistency"] = 1.0 if consistency_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()