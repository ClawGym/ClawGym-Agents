import json
import csv
import re
import sys
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path


def _read_text_safe(p: Path):
    try:
        return True, p.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _read_json_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _read_csv_dicts_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            return True, list(csv.DictReader(f))
    except Exception:
        return False, None


def _parse_iso_dt(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            if s.endswith("Z"):
                return datetime.fromisoformat(s[:-1])
        except Exception:
            return None
    return None


def _parse_config_yaml_minimal(p: Path):
    ok, txt = _read_text_safe(p)
    if not ok:
        return False, None
    cfg = {}
    schedule = {}
    current_section = None
    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2)
        if indent == 0:
            current_section = None
            if val == "":
                current_section = key
                if key == "schedule":
                    schedule = {}
            else:
                v = val.strip().strip('"').strip("'")
                if v.isdigit():
                    cfg[key] = int(v)
                else:
                    cfg[key] = v
        else:
            if current_section == "schedule":
                v = val.strip().strip('"').strip("'")
                schedule[key] = v
    if schedule:
        cfg["schedule"] = schedule
    return True, cfg


def _parse_action_items(md_text: str):
    items = []
    pattern = re.compile(
        r"^\s*-\s*\[ACTION\]\s*(.+?)\s*\(Owner:\s*([^,]+),\s*Due:\s*(\d{4}-\d{2}-\d{2})\)\s*$",
        re.MULTILINE,
    )
    for m in pattern.finditer(md_text):
        desc = m.group(1).strip()
        owner = m.group(2).strip()
        due = m.group(3).strip()
        items.append({"description": desc, "owner": owner, "due_date": due})
    return items


def _filter_dates_in_window(dt: date, start: date, end: date) -> bool:
    return start <= dt <= end


def _compute_expected_weekly_events(events_rows, as_of: date, window_days: int):
    start = as_of
    end = as_of + timedelta(days=window_days - 1)
    filtered = []
    for r in events_rows:
        sd = _parse_iso_dt(r.get("start_date", ""))
        if sd is None:
            continue
        if _filter_dates_in_window(sd.date(), start, end):
            try:
                pr = int(str(r.get("priority", "")).strip())
            except Exception:
                continue
            filtered.append((pr, sd, r))
    filtered.sort(key=lambda x: (x[0], x[1]))
    expected = []
    rank = 1
    for pr, sd, r in filtered:
        expected.append({
            "rank": str(rank),
            "event_id": r.get("event_id", ""),
            "title": r.get("title", ""),
            "start_date": r.get("start_date", ""),
            "location": r.get("location", ""),
            "priority": str(r.get("priority", "")),
            "type": r.get("type", ""),
        })
        rank += 1
    return expected


def _get_bullet_lines(txt: str):
    bullets = []
    for line in txt.splitlines():
        if re.match(r"^\s*([-*•])\s+", line):
            bullets.append(line.strip())
    return bullets


def _allowed_dow_tokens_from_config(schedule_day: str):
    if not schedule_day:
        return set()
    s = schedule_day.strip().lower()
    names = {
        "sunday": ("sun", "0", "7"),
        "monday": ("mon", "1"),
        "tuesday": ("tue", "2"),
        "wednesday": ("wed", "3"),
        "thursday": ("thu", "4"),
        "friday": ("fri", "5"),
        "saturday": ("sat", "6"),
    }
    # Numeric provided
    if s.isdigit():
        idx = int(s)
        if idx == 7:
            full = "sunday"
            return {"sunday", "sun", "0", "7"}
        for full, reps in names.items():
            if str(idx) in reps:
                return {full, reps[0], str(idx)}
        return {s}
    # Abbrev or full name
    for full, reps in names.items():
        if s == full or s == reps[0]:
            return {full, reps[0], *reps[1:]}
    # Try prefix match on full names
    for full, reps in names.items():
        if full.startswith(s):
            return {full, reps[0], *reps[1:]}
    return {s}


def _parse_schedule_time_tokens(schedule_time: str):
    # Returns (hour:int, minute:int) if parseable, else (None, None)
    if not schedule_time:
        return None, None
    t = schedule_time.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return None, None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None, None
    return hh, mm


def _cron_token_matches(field: str, value: int) -> bool:
    # Allow "7" vs "07" formats
    token = str(value)
    return field == token or field == token.zfill(2)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_script_exists": 0.0,
        "outputs_present_for_2026_05_01": 0.0,
        "weekly_events_header_and_columns": 0.0,
        "weekly_events_window_and_order": 0.0,
        "weekly_status_counts_and_top_event": 0.0,
        "weekly_status_action_items_section": 0.0,
        "email_headers_correct": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_top_n_events_listed": 0.0,
        "email_action_items_listed": 0.0,
        "meeting_prep_content": 0.0,
        "cron_schedule_valid": 0.0,
        "validation_script_runs_successfully": 0.0,
    }

    # Load inputs
    events_path = workspace / "input" / "events.csv"
    transcripts_path = workspace / "input" / "transcripts.md"
    contacts_path = workspace / "input" / "contacts.json"
    config_path = workspace / "input" / "config.yaml"

    ok_events, events_rows = _read_csv_dicts_safe(events_path)
    ok_transcripts, transcripts_txt = _read_text_safe(transcripts_path)
    ok_contacts, contacts_json = _read_json_safe(contacts_path)
    ok_config, config = _parse_config_yaml_minimal(config_path)

    # Determine as-of date and window
    as_of = date(2026, 5, 1)
    window_days = 7
    top_n = 3
    schedule_day = None
    schedule_time = None
    if ok_config and isinstance(config, dict):
        if isinstance(config.get("window_days", None), int):
            window_days = int(config.get("window_days", window_days))
        if isinstance(config.get("top_n_events", None), int):
            top_n = int(config.get("top_n_events", top_n))
        if isinstance(config.get("schedule", None), dict):
            schedule_day = config["schedule"].get("day_of_week", None)
            schedule_time = config["schedule"].get("time", None)

    out_dir = workspace / "out" / as_of.strftime("%Y-%m-%d")
    weekly_events_out = out_dir / "weekly_events.csv"
    weekly_status_out = out_dir / "weekly_status.md"
    email_draft_out = out_dir / "email_draft.txt"
    meeting_prep_out = out_dir / "meeting_prep.md"

    # Check run script existence
    run_script = workspace / "scripts" / "run_weekly_digest.sh"
    if run_script.exists() and run_script.is_file():
        try:
            is_exec = bool(run_script.stat().st_mode & 0o111)
        except Exception:
            is_exec = False
        scores["run_script_exists"] = 1.0 if is_exec else 0.0

    # Outputs presence
    present = all([weekly_events_out.exists(), weekly_status_out.exists(), email_draft_out.exists(), meeting_prep_out.exists()])
    non_empty = True
    for p in [weekly_events_out, weekly_status_out, email_draft_out, meeting_prep_out]:
        try:
            if not p.exists() or p.stat().st_size <= 0:
                non_empty = False
        except Exception:
            non_empty = False
    if present and non_empty:
        scores["outputs_present_for_2026_05_01"] = 1.0

    # Weekly events checks
    expected_columns = ["rank", "event_id", "title", "start_date", "location", "priority", "type"]
    ok_events_out, events_out_rows = _read_csv_dicts_safe(weekly_events_out)
    if ok_events and ok_events_out and isinstance(events_rows, list) and isinstance(events_out_rows, list):
        # header check
        try:
            with weekly_events_out.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if header == expected_columns:
            scores["weekly_events_header_and_columns"] = 1.0

        # compute expected rows
        expected = _compute_expected_weekly_events(events_rows, as_of, window_days)
        try:
            out_ids = [r.get("event_id", "") for r in events_out_rows]
            exp_ids = [r["event_id"] for r in expected]
            order_ok = out_ids == exp_ids
            out_ranks = [str(r.get("rank", "")).strip() for r in events_out_rows]
            rank_ok = out_ranks == [str(i) for i in range(1, len(expected) + 1)]
            start = as_of
            end = as_of + timedelta(days=window_days - 1)
            window_ok = True
            for r in events_out_rows:
                sd = _parse_iso_dt(r.get("start_date", ""))
                if sd is None or not _filter_dates_in_window(sd.date(), start, end):
                    window_ok = False
                    break
            if order_ok and rank_ok and window_ok and len(events_out_rows) == len(expected):
                scores["weekly_events_window_and_order"] = 1.0
        except Exception:
            pass

    # Weekly status.md checks
    ok_status, status_txt = _read_text_safe(weekly_status_out)
    if ok_status and ok_events:
        total_events = len(events_rows) if isinstance(events_rows, list) else 0
        expected_filtered = _compute_expected_weekly_events(events_rows, as_of, window_days)
        window_count = len(expected_filtered)
        top_title = expected_filtered[0]["title"] if expected_filtered else ""

        counts_ok = False
        try:
            if re.search(rf"total[^0-9]*\b{total_events}\b", status_txt, flags=re.IGNORECASE):
                if re.search(rf"(window|next\s*{window_days}\s*days)[^\n]*\b{window_count}\b", status_txt, flags=re.IGNORECASE):
                    counts_ok = True
        except Exception:
            counts_ok = False

        top_ok = bool(top_title) and (top_title in status_txt)

        if counts_ok and top_ok:
            scores["weekly_status_counts_and_top_event"] = 1.0

        # Action items section and items listed
        items = _parse_action_items(transcripts_txt) if ok_transcripts else []
        start = as_of
        end = as_of + timedelta(days=window_days - 1)
        due_items = []
        for it in items:
            try:
                due_dt = datetime.fromisoformat(it["due_date"]).date()
            except Exception:
                continue
            if _filter_dates_in_window(due_dt, start, end):
                due_items.append(it)
        section_ok = "Action Items Due Next 7 Days" in status_txt
        all_items_present = True if due_items else False
        for it in due_items:
            desc = it["description"]
            owner = it["owner"]
            due = it["due_date"]
            if (desc not in status_txt) or (due not in status_txt) or (owner not in status_txt):
                all_items_present = False
                break
        if section_ok and all_items_present:
            scores["weekly_status_action_items_section"] = 1.0

    # Email draft checks
    ok_email, email_txt = _read_text_safe(email_draft_out)
    if ok_email and ok_contacts:
        try:
            from_email = contacts_json.get("from", {}).get("email", "")
            to_emails = [e.get("email", "") for e in contacts_json.get("to", []) if "email" in e]
            cc_emails = [e.get("email", "") for e in contacts_json.get("cc", []) if "email" in e]
        except Exception:
            from_email, to_emails, cc_emails = "", [], []

        # headers
        lines = email_txt.splitlines()
        to_ok = False
        cc_ok = False
        from_ok = False
        for ln in lines:
            if ln.strip().lower().startswith("to:"):
                if all(em in ln for em in to_emails):
                    to_ok = True
            if ln.strip().lower().startswith("cc:"):
                if all(em in ln for em in cc_emails):
                    cc_ok = True
            if ln.strip().lower().startswith("from:"):
                if from_email and (from_email in ln):
                    from_ok = True
        if to_ok and cc_ok and from_ok:
            scores["email_headers_correct"] = 1.0

        # subject and greeting reference to ambassador
        subject_ok = any(re.search(rf"Subject:\s*Weekly briefing for week of {as_of.strftime('%Y-%m-%d')}\b", ln, re.IGNORECASE) for ln in lines)
        greet_ok = bool(re.search(r"ambassador", email_txt, re.IGNORECASE) and re.search(r"smith", email_txt, re.IGNORECASE))
        if subject_ok and greet_ok:
            scores["email_subject_and_greeting"] = 1.0

        # top N events
        if ok_events:
            expected_filtered = _compute_expected_weekly_events(events_rows, as_of, window_days)
            top_titles = [r["title"] for r in expected_filtered[:top_n]]
            bullets = _get_bullet_lines(email_txt)
            titles_ok = True if top_titles else False
            for t in top_titles:
                if not any(t in b for b in bullets):
                    titles_ok = False
                    break
            if titles_ok:
                scores["email_top_n_events_listed"] = 1.0

        # action items bullets
        items = _parse_action_items(transcripts_txt) if ok_transcripts else []
        start = as_of
        end = as_of + timedelta(days=window_days - 1)
        due_items = []
        for it in items:
            try:
                due_dt = datetime.fromisoformat(it["due_date"]).date()
            except Exception:
                continue
            if _filter_dates_in_window(due_dt, start, end):
                due_items.append(it)
        bullets = _get_bullet_lines(email_txt)
        ai_ok = True if due_items else False
        for it in due_items:
            desc = it["description"]
            due = it["due_date"]
            if not any((desc in b and due in b) for b in bullets):
                ai_ok = False
                break
        if ai_ok:
            scores["email_action_items_listed"] = 1.0

    # Meeting prep checks
    ok_prep, prep_txt = _read_text_safe(meeting_prep_out)
    if ok_prep and ok_events:
        # find next meeting-type event among filtered events by time ascending
        start = as_of
        end = as_of + timedelta(days=window_days - 1)
        candidates = []
        for r in events_rows:
            sd = _parse_iso_dt(r.get("start_date", ""))
            if sd is None:
                continue
            if _filter_dates_in_window(sd.date(), start, end) and (str(r.get("type", "")).lower() == "meeting"):
                candidates.append((sd, r))
        meeting_event = None
        if candidates:
            candidates.sort(key=lambda x: x[0])
            meeting_event = candidates[0][1]
        has_meeting_info = True
        if meeting_event:
            title = meeting_event.get("title", "")
            date_str = ""
            try:
                date_str = datetime.fromisoformat(meeting_event.get("start_date", "")).date().strftime("%Y-%m-%d")
            except Exception:
                pass
            if not (title and (title in prep_txt) and (date_str and (date_str in prep_txt))):
                has_meeting_info = False
        # action items due in window
        items = _parse_action_items(transcripts_txt) if ok_transcripts else []
        due_items = []
        for it in items:
            try:
                due_dt = datetime.fromisoformat(it["due_date"]).date()
            except Exception:
                continue
            if _filter_dates_in_window(due_dt, start, end):
                due_items.append(it)
        ai_ok = True if due_items else False
        for it in due_items:
            desc = it["description"]
            due = it["due_date"]
            if (desc not in prep_txt) or (due not in prep_txt):
                ai_ok = False
                break
        if has_meeting_info and ai_ok:
            scores["meeting_prep_content"] = 1.0

    # Cron schedule validation
    cron_path = workspace / "out" / "schedule" / "weekly_digest.cron"
    ok_cron, cron_txt = _read_text_safe(cron_path)
    if ok_cron:
        lines = [ln.strip() for ln in cron_txt.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(lines) == 1:
            cron_line = lines[0]
            parts = cron_line.split()
            if len(parts) >= 6:
                minute, hour, dom, mon, dow = parts[:5]
                command = " ".join(parts[5:])
                # Expected time tokens based on config
                hh_cfg, mm_cfg = _parse_schedule_time_tokens(schedule_time if schedule_time else "")
                if hh_cfg is None or mm_cfg is None:
                    minute_ok = bool(re.match(r"^\d{1,2}$", minute))
                    hour_ok = bool(re.match(r"^\d{1,2}$", hour))
                else:
                    minute_ok = _cron_token_matches(minute, mm_cfg)
                    hour_ok = _cron_token_matches(hour, hh_cfg)
                # Day of week check based on config
                dow_ok = False
                if schedule_day:
                    allowed = _allowed_dow_tokens_from_config(schedule_day)
                    if dow.strip().lower() in {a.lower() for a in allowed}:
                        dow_ok = True
                else:
                    dow_ok = bool(re.match(r"^(sun|mon|tue|wed|thu|fri|sat|[0-7])$", dow.strip().lower()))
                cmd_ok = ("scripts/run_weekly_digest.sh" in command) and ("$(date +%F)" in command) and ("/out/$(date +%F)/" in command or " out/$(date +%F)/" in command)
                if minute_ok and hour_ok and dow_ok and cmd_ok:
                    scores["cron_schedule_valid"] = 1.0

    # Validation script run
    validate_script = workspace / "scripts" / "validate.sh"
    if validate_script.exists() and validate_script.is_file():
        try:
            is_exec = bool(validate_script.stat().st_mode & 0o111)
        except Exception:
            is_exec = False
        if is_exec:
            try:
                res = subprocess.run(
                    ["bash", str(validate_script), "--as-of", as_of.strftime("%Y-%m-%d")],
                    cwd=str(workspace),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                report_path = out_dir / "validation_report.txt"
                report_exists = report_path.exists() and report_path.stat().st_size > 0
                if res.returncode == 0 and report_exists:
                    scores["validation_script_runs_successfully"] = 1.0
            except Exception:
                pass

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()