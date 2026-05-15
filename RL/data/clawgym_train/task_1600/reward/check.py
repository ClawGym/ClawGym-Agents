import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, time, timedelta


def _read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path):
    txt = _read_text_safe(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def _parse_yaml_minimal(path: Path):
    """
    Minimal YAML parser for simple key: value pairs used in preferences.yaml.
    Supports quoted or unquoted scalar strings and integers.
    """
    txt = _read_text_safe(path)
    if txt is None:
        return None
    data = {}
    for line in txt.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            return None
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip()
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if re.fullmatch(r"-?\d+", val):
            try:
                data[key] = int(val)
                continue
            except Exception:
                pass
        data[key] = val
    return data


def _parse_csv_safe(path: Path):
    txt = _read_text_safe(path)
    if txt is None:
        return None
    try:
        rows = []
        reader = csv.DictReader(txt.splitlines())
        if reader.fieldnames is None:
            return None
        for row in reader:
            rows.append(row)
        return {"headers": reader.fieldnames, "rows": rows}
    except Exception:
        return None


def _parse_time_hhmm(s: str):
    try:
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return time(hour=hh, minute=mm)
    except Exception:
        return None


def _format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _format_time(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _compute_week_dates(start_date_str: str):
    try:
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    mapping = {}
    for idx, day_abbr in enumerate(days):
        mapping[day_abbr] = start_dt + timedelta(days=idx)
    return mapping


def _compute_schedule(workouts_json, meals_csv, prefs_yaml):
    """
    Returns list of events with:
    {
      "type": "workout"|"meal",
      "title": str,
      "event_date": date,
      "event_time": time,
      "reminder_dt": datetime,
      "source": "workouts"|"meals",
      "notes": str
    }
    Sorted by reminder_dt ascending.
    """
    if not isinstance(prefs_yaml, dict):
        return None
    lead_min = prefs_yaml.get("lead_time_minutes")
    start_date = prefs_yaml.get("start_date")
    if not isinstance(lead_min, int) or not isinstance(start_date, str):
        return None
    week_map = _compute_week_dates(start_date)
    if week_map is None:
        return None

    # Validate meals headers strictly as a set match to expected columns
    if not isinstance(meals_csv, dict):
        return None
    expected_meal_headers = {"day", "time", "dish", "calories", "notes"}
    headers = set(meals_csv.get("headers") or [])
    if headers != expected_meal_headers:
        return None

    schedule = []

    # Workouts
    if not isinstance(workouts_json, dict):
        return None
    plan = workouts_json.get("plan")
    if not isinstance(plan, list):
        return None
    for w in plan:
        try:
            day_abbr = w["day"]
            event_t = _parse_time_hhmm(w["start_time"])
            title = str(w["title"])
            intensity = str(w["intensity"])
        except Exception:
            return None
        if day_abbr not in week_map or event_t is None:
            return None
        event_date = week_map[day_abbr]
        event_dt = datetime.combine(event_date, event_t)
        reminder_dt = event_dt - timedelta(minutes=lead_min)
        schedule.append({
            "type": "workout",
            "title": title,
            "event_date": event_date,
            "event_time": event_t,
            "reminder_dt": reminder_dt,
            "source": "workouts",
            "notes": intensity
        })

    # Meals
    for row in meals_csv["rows"]:
        try:
            day_abbr = row["day"].strip()
            event_t = _parse_time_hhmm(row["time"])
            dish = row["dish"].strip()
            notes = row["notes"].strip()
        except Exception:
            return None
        if day_abbr not in week_map or event_t is None or not dish:
            return None
        event_date = week_map[day_abbr]
        event_dt = datetime.combine(event_date, event_t)
        reminder_dt = event_dt - timedelta(minutes=lead_min)
        schedule.append({
            "type": "meal",
            "title": dish,
            "event_date": event_date,
            "event_time": event_t,
            "reminder_dt": reminder_dt,
            "source": "meals",
            "notes": notes
        })

    # De-duplicate by (type,title,event_date,event_time) keep earliest reminder
    dedup = {}
    for ev in schedule:
        key = (ev["type"], ev["title"], ev["event_date"].isoformat(), _format_time(ev["event_time"]))
        if key not in dedup or ev["reminder_dt"] < dedup[key]["reminder_dt"]:
            dedup[key] = ev
    schedule = list(dedup.values())
    schedule.sort(key=lambda e: e["reminder_dt"])
    return schedule


def _expected_tsv_rows(schedule):
    rows = []
    for ev in schedule:
        reminder_date = ev["reminder_dt"].date()
        rows.append({
            "date": _format_date(reminder_date),
            "type": ev["type"],
            "title": ev["title"],
            "event_time_local": _format_time(ev["event_time"]),
            "reminder_time_local": _format_time(ev["reminder_dt"].time()),
            "source": ev["source"],
            "notes": ev["notes"]
        })
    return rows


def _load_tsv_strict(path: Path):
    txt = _read_text_safe(path)
    if txt is None:
        return None
    lines = txt.splitlines()
    if not lines:
        return None
    reader = csv.reader(lines, delimiter="\t")
    try:
        rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    data_rows = rows[1:]
    dict_rows = []
    for r in data_rows:
        if len(r) != len(header):
            return None
        dict_rows.append({header[i]: r[i] for i in range(len(header))})
    return {"header": header, "rows": dict_rows}


def _contains_message_with_details(s: str, ev_type: str, title: str, event_dt: datetime):
    # Must include 'REMINDER', type, title, and "YYYY-MM-DD HH:MM"
    pattern_dt = event_dt.strftime("%Y-%m-%d %H:%M")
    ci = s.lower()
    if "reminder" not in ci:
        return False
    if ev_type.lower() not in ci:
        return False
    if title.lower() not in ci:
        return False
    if pattern_dt not in s:
        return False
    return True


def _check_tag_comment_at_line_end(line: str, tag: str) -> bool:
    if "#" not in line:
        return False
    idx = line.rfind("#")
    comment = line[idx + 1:].strip()
    return comment == tag


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "reminders_tsv_exists_and_header": 0.0,
        "reminders_tsv_content_match": 0.0,
        "crontab_preview_lines_and_tags": 0.0,
        "crontab_preview_messages_and_log_path": 0.0,
        "schedule_tasks_bat_count_and_tags": 0.0,
        "schedule_tasks_bat_time_date": 0.0,
        "schedule_tasks_bat_message_and_log_path": 0.0,
        "accountability_message_next3_workouts": 0.0,
        "accountability_message_next3_meals": 0.0,
        "accountability_message_total_and_tags": 0.0,
        "accountability_message_word_limit": 0.0,
        "run_log_counts_and_inputs_outputs": 0.0,
        "run_log_contains_command_hint": 0.0,
    }

    # Load inputs
    workouts_path = workspace / "input" / "workouts.json"
    meals_path = workspace / "input" / "meals.csv"
    prefs_path = workspace / "input" / "preferences.yaml"

    workouts_json = _load_json_safe(workouts_path)
    meals_csv = _parse_csv_safe(meals_path)
    prefs_yaml = _parse_yaml_minimal(prefs_path)

    schedule = None
    expected_rows = []
    expected_header = [
        "date",
        "type",
        "title",
        "event_time_local",
        "reminder_time_local",
        "source",
        "notes",
    ]
    tag = ""
    total_reminders = 0
    workouts_count = 0
    meals_count = 0

    if workouts_json is not None and meals_csv is not None and prefs_yaml is not None:
        schedule = _compute_schedule(workouts_json, meals_csv, prefs_yaml)
        if schedule is not None:
            expected_rows = _expected_tsv_rows(schedule)
            tag = str(prefs_yaml.get("tag", "")).strip()
            total_reminders = len(schedule)
            workouts_count = sum(1 for e in schedule if e["type"] == "workout")
            meals_count = sum(1 for e in schedule if e["type"] == "meal")

    # reminders.tsv checks
    tsv_path = workspace / "output" / "reminders.tsv"
    tsv_data = _load_tsv_strict(tsv_path)
    if tsv_data is not None and schedule is not None:
        if tsv_data.get("header") == expected_header:
            scores["reminders_tsv_exists_and_header"] = 1.0
            actual_rows = tsv_data.get("rows", [])
            if len(actual_rows) == len(expected_rows):
                all_match = True
                for i, exp in enumerate(expected_rows):
                    act = actual_rows[i]
                    if any(act.get(k) != v for k, v in exp.items()):
                        all_match = False
                        break
                if all_match:
                    scores["reminders_tsv_content_match"] = 1.0

    # crontab_preview.txt checks
    cron_path = workspace / "output" / "crontab_preview.txt"
    cron_txt = _read_text_safe(cron_path)
    if cron_txt is not None and schedule is not None and tag:
        lines = [ln for ln in cron_txt.splitlines() if ln.strip()]
        if len(lines) == total_reminders and total_reminders > 0:
            tag_ok = all(_check_tag_comment_at_line_end(ln, tag) for ln in lines)
            if tag_ok:
                scores["crontab_preview_lines_and_tags"] = 1.0
            msgs_ok = True
            log_ok = True
            for ev, ln in zip(schedule, lines):
                if not _contains_message_with_details(
                    ln, ev["type"], ev["title"],
                    datetime.combine(ev["event_date"], ev["event_time"])
                ):
                    msgs_ok = False
                    break
                if "output/notifications.log" not in ln:
                    log_ok = False
                    break
            if msgs_ok and log_ok:
                scores["crontab_preview_messages_and_log_path"] = 1.0

    # schedule_tasks.bat checks
    bat_path = workspace / "output" / "schedule_tasks.bat"
    bat_txt = _read_text_safe(bat_path)
    if bat_txt is not None and schedule is not None and tag:
        bat_lines = [ln.rstrip("\r\n") for ln in bat_txt.splitlines()]
        sch_lines_idx = [i for i, ln in enumerate(bat_lines) if "schtasks" in ln.lower()]
        if len(sch_lines_idx) == total_reminders and total_reminders > 0:
            tags_ok = True
            time_date_ok = True
            msg_log_ok = True
            for idx, ev in zip(sch_lines_idx, schedule):
                prev_idx = idx - 1
                while prev_idx >= 0 and not bat_lines[prev_idx].strip():
                    prev_idx -= 1
                prev_line = bat_lines[prev_idx].strip() if prev_idx >= 0 else ""
                prev_is_comment = prev_line.lower().startswith("rem") or prev_line.startswith("::")
                if not (prev_is_comment and (tag in prev_line)):
                    tags_ok = False
                    break
                line = bat_lines[idx]
                low = line.lower()
                if "/sc once" not in low or "/st" not in low or "/sd" not in low:
                    time_date_ok = False
                    break
                st_match = re.search(r"/ST\s+(\d{2}:\d{2})", line, re.IGNORECASE)
                sd_match = re.search(r"/SD\s+(\d{2}/\d{2}/\d{4})", line, re.IGNORECASE)
                if not st_match or not sd_match:
                    time_date_ok = False
                    break
                st_val = st_match.group(1)
                sd_val = sd_match.group(1)
                rem_time = ev["reminder_dt"].time()
                expected_st = _format_time(rem_time)
                rem_date = ev["reminder_dt"].date()
                expected_sd = f"{rem_date.month:02d}/{rem_date.day:02d}/{rem_date.year:04d}"
                if st_val != expected_st or sd_val != expected_sd:
                    time_date_ok = False
                    break
                if "output\\notifications.log" not in line:
                    msg_log_ok = False
                    break
                if not _contains_message_with_details(
                    line, ev["type"], ev["title"],
                    datetime.combine(ev["event_date"], ev["event_time"])
                ):
                    msg_log_ok = False
                    break
            if tags_ok:
                scores["schedule_tasks_bat_count_and_tags"] = 1.0
            if time_date_ok:
                scores["schedule_tasks_bat_time_date"] = 1.0
            if msg_log_ok:
                scores["schedule_tasks_bat_message_and_log_path"] = 1.0

    # accountability_message.txt checks
    acc_path = workspace / "output" / "accountability_message.txt"
    acc_txt = _read_text_safe(acc_path)
    if acc_txt is not None and schedule is not None and total_reminders > 0:
        words = re.findall(r"\S+", acc_txt)
        # We'll set word limit only if other content checks (below) will be attempted
        workouts_sorted = [e for e in schedule if e["type"] == "workout"]
        meals_sorted = [e for e in schedule if e["type"] == "meal"]
        workouts_sorted.sort(key=lambda e: e["reminder_dt"])
        meals_sorted.sort(key=lambda e: e["reminder_dt"])

        wk_ok = True
        for ev in workouts_sorted[:3]:
            title = ev["title"]
            event_dt_str = datetime.combine(ev["event_date"], ev["event_time"]).strftime("%Y-%m-%d %H:%M")
            if title not in acc_txt or event_dt_str not in acc_txt:
                wk_ok = False
                break
        if wk_ok and len(workouts_sorted) >= 3:
            scores["accountability_message_next3_workouts"] = 1.0

        ml_ok = True
        for ev in meals_sorted[:3]:
            dish = ev["title"]
            event_dt_str = datetime.combine(ev["event_date"], ev["event_time"]).strftime("%Y-%m-%d %H:%M")
            if dish not in acc_txt or event_dt_str not in acc_txt:
                ml_ok = False
                break
        if ml_ok and len(meals_sorted) >= 3:
            scores["accountability_message_next3_meals"] = 1.0

        total_str_ok = (str(total_reminders) in acc_txt and re.search(r"reminder", acc_txt, re.IGNORECASE) is not None)
        channels_ok = (re.search(r"cron", acc_txt, re.IGNORECASE) is not None and
                       re.search(r"task scheduler", acc_txt, re.IGNORECASE) is not None and
                       (tag in acc_txt if tag else False))
        if total_str_ok and channels_ok:
            scores["accountability_message_total_and_tags"] = 1.0

        if len(words) <= 150 and (scores["accountability_message_next3_workouts"] > 0.0 or
                                  scores["accountability_message_next3_meals"] > 0.0 or
                                  scores["accountability_message_total_and_tags"] > 0.0):
            scores["accountability_message_word_limit"] = 1.0

    # run.log checks
    runlog_path = workspace / "output" / "run.log"
    runlog_txt = _read_text_safe(runlog_path)
    if runlog_txt is not None and schedule is not None:
        counts_ok = (re.search(r"workout", runlog_txt, re.IGNORECASE) is not None and
                     re.search(r"\b" + str(workouts_count) + r"\b", runlog_txt) is not None and
                     re.search(r"meal", runlog_txt, re.IGNORECASE) is not None and
                     re.search(r"\b" + str(meals_count) + r"\b", runlog_txt) is not None and
                     re.search(r"total", runlog_txt, re.IGNORECASE) is not None and
                     re.search(r"\b" + str(total_reminders) + r"\b", runlog_txt) is not None)
        io_ok = all(s in runlog_txt for s in [
            "input/workouts.json",
            "input/meals.csv",
            "input/preferences.yaml",
            "output/reminders.tsv",
            "output/crontab_preview.txt",
            "output/schedule_tasks.bat",
            "output/accountability_message.txt",
        ])
        if counts_ok and io_ok:
            scores["run_log_counts_and_inputs_outputs"] = 1.0

        cmd_ok = (re.search(r"(command|executed|run|python|bash|sh|\.py)", runlog_txt, re.IGNORECASE) is not None)
        if cmd_ok:
            scores["run_log_contains_command_hint"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()