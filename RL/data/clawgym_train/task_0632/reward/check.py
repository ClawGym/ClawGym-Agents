import json
import os
import sys
import re

def parse_hhmm(s):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not re.fullmatch(r"\d{2}:\d{2}", s):
        return None
    hh = int(s[:2])
    mm = int(s[3:])
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh * 60 + mm
    return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if line.strip() == "":
                    continue
                lines.append(line)
        return lines
    except Exception:
        return None

def last_nonempty_print(obj):
    print(json.dumps(obj, ensure_ascii=False))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    input_path = os.path.join(input_dir, "scheduling_requests.json")
    commands_path = os.path.join(output_dir, "commands.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    notes_path = os.path.join(output_dir, "notes.md")

    allowed_days = {
        "today", "tomorrow", "day after tomorrow",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    }

    # Initialize checks (all False by default)
    checks = {
        "commands_exists": False,
        "commands_lines_count_match": False,
        "commands_has_required_keys": False,
        "commands_fields_match_input": False,
        "commands_times_format_and_order": False,
        "commands_within_window_and_duration": False,
        "non_overlap_by_day": False,
        "summary_exists_and_valid": False,
        "summary_count_matches": False,
        "summary_events_by_day_keys_match": False,
        "summary_events_by_day_counts_match": False,
        "notes_exists": False,
        "notes_min_length": False,
        "notes_has_conflict_keyword": False,
    }

    # Read input (reference only; does not contribute positive reward directly)
    input_data = load_json_file(input_path)
    if not isinstance(input_data, list):
        input_data = None

    # Prepare scoring only on outputs
    # 1) commands.jsonl validations
    commands_lines = None
    if os.path.isfile(commands_path):
        checks["commands_exists"] = True
        commands_lines = load_jsonl_lines(commands_path)

    parsed_commands = []
    if checks["commands_exists"] and commands_lines is not None and input_data is not None:
        # Count must match number of requests
        if len(commands_lines) == len(input_data):
            checks["commands_lines_count_match"] = True

        # Parse each line as JSON and check keys presence
        required_keys = [
            "calendar_name",
            "event_summary",
            "event_description",
            "relative_start_date",
            "start_time",
            "relative_end_date",
            "end_time",
        ]
        all_keys_ok = True
        all_fields_match_input = True
        times_format_ok = True
        within_window_and_duration_ok = True

        for idx, line in enumerate(commands_lines):
            try:
                obj = json.loads(line)
            except Exception:
                all_keys_ok = False
                all_fields_match_input = False
                times_format_ok = False
                within_window_and_duration_ok = False
                parsed_commands.append(None)
                continue

            # Check required keys present
            if not all(k in obj for k in required_keys):
                all_keys_ok = False

            parsed_commands.append(obj)

        # If keys are present for all, perform further validations
        if all_keys_ok:
            checks["commands_has_required_keys"] = True

            # Validate content against input, times, and windows/duration
            for idx, obj in enumerate(parsed_commands):
                if obj is None or input_data is None or idx >= len(input_data):
                    all_fields_match_input = False
                    times_format_ok = False
                    within_window_and_duration_ok = False
                    continue

                req = input_data[idx]
                # Normalize expected values
                exp_calendar = str(req.get("calendar", ""))
                exp_title = str(req.get("title", ""))
                exp_rel = str(req.get("relative_day", "")).strip().lower()

                # Field matches
                got_calendar = str(obj.get("calendar_name", ""))
                got_title = str(obj.get("event_summary", ""))
                got_rel_start = str(obj.get("relative_start_date", "")).strip().lower()
                got_rel_end = str(obj.get("relative_end_date", "")).strip().lower()

                if got_calendar != exp_calendar:
                    all_fields_match_input = False
                if got_title != exp_title:
                    all_fields_match_input = False

                # relative day checks
                if got_rel_start != exp_rel or got_rel_end != exp_rel:
                    all_fields_match_input = False
                if got_rel_start not in allowed_days or got_rel_end not in allowed_days:
                    all_fields_match_input = False

                # Time format and order
                st_str = obj.get("start_time")
                en_str = obj.get("end_time")
                st_min = parse_hhmm(st_str)
                en_min = parse_hhmm(en_str)
                if st_min is None or en_min is None or not (st_min < en_min):
                    times_format_ok = False

                # Window and duration checks
                win_start_str = str(req.get("window_start", ""))
                win_end_str = str(req.get("window_end", ""))
                dur_minutes = req.get("duration_minutes", None)
                win_start_min = parse_hhmm(win_start_str)
                win_end_min = parse_hhmm(win_end_str)
                if None in (st_min, en_min, win_start_min, win_end_min) or dur_minutes is None:
                    within_window_and_duration_ok = False
                else:
                    # Fully within window [inclusive]
                    if not (win_start_min <= st_min and en_min <= win_end_min):
                        within_window_and_duration_ok = False
                    # Duration exact
                    if (en_min - st_min) != int(dur_minutes):
                        within_window_and_duration_ok = False

        checks["commands_fields_match_input"] = all_fields_match_input and checks["commands_has_required_keys"]
        checks["commands_times_format_and_order"] = times_format_ok and checks["commands_has_required_keys"]
        checks["commands_within_window_and_duration"] = within_window_and_duration_ok and checks["commands_has_required_keys"]

        # 2) Non-overlap by day across all calendars
        non_overlap_ok = True
        if checks["commands_times_format_and_order"]:
            by_day = {}
            for obj in parsed_commands:
                if obj is None:
                    non_overlap_ok = False
                    break
                day = str(obj.get("relative_start_date", "")).strip().lower()
                st_min = parse_hhmm(obj.get("start_time"))
                en_min = parse_hhmm(obj.get("end_time"))
                if day not in by_day:
                    by_day[day] = []
                by_day[day].append((st_min, en_min))
            # Check overlaps per day
            for day, intervals in by_day.items():
                intervals_sorted = sorted(intervals, key=lambda x: (x[0], x[1]))
                prev_end = None
                for (s, e) in intervals_sorted:
                    if s is None or e is None:
                        non_overlap_ok = False
                        break
                    if prev_end is not None:
                        # Overlap if start < previous end
                        if s < prev_end:
                            non_overlap_ok = False
                            break
                    prev_end = e
                if not non_overlap_ok:
                    break
        else:
            non_overlap_ok = False
        checks["non_overlap_by_day"] = non_overlap_ok

    # 3) summary.json validations
    summary_data = None
    if os.path.isfile(summary_path):
        # Must parse and have keys "count" and "events_by_day"
        try:
            summary_data = load_json_file(summary_path)
        except Exception:
            summary_data = None
        if isinstance(summary_data, dict) and "count" in summary_data and "events_by_day" in summary_data and isinstance(summary_data.get("events_by_day"), dict):
            checks["summary_exists_and_valid"] = True

    if checks["summary_exists_and_valid"] and input_data is not None:
        # count must equal number of requests
        if isinstance(summary_data.get("count"), int) and summary_data.get("count") == len(input_data):
            checks["summary_count_matches"] = True

        # events_by_day keys match exactly set of days present in commands.jsonl
        # and counts match
        if parsed_commands and all(pc is not None for pc in parsed_commands):
            days_from_commands = {}
            for obj in parsed_commands:
                d = str(obj.get("relative_start_date", "")).strip().lower()
                days_from_commands[d] = days_from_commands.get(d, 0) + 1
            eb = summary_data.get("events_by_day", {})
            # Keys must match exactly and be allowed
            keys_ok = set(eb.keys()) == set(days_from_commands.keys())
            if keys_ok and all(k in allowed_days for k in eb.keys()):
                checks["summary_events_by_day_keys_match"] = True
            # Counts must match
            counts_ok = True
            for k, v in eb.items():
                if not isinstance(v, int):
                    counts_ok = False
                    break
                if days_from_commands.get(k, None) != v:
                    counts_ok = False
                    break
            if counts_ok and keys_ok:
                checks["summary_events_by_day_counts_match"] = True

    # 4) notes.md validations
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes_text = f.read()
        except Exception:
            notes_text = ""
        if isinstance(notes_text, str) and len(notes_text) >= 300:
            checks["notes_min_length"] = True
        # Must include at least one keyword: "conflict", "overlap", or "adjust" (case-insensitive)
        if re.search(r"\b(conflict|overlap|adjust)\b", notes_text, flags=re.IGNORECASE):
            checks["notes_has_conflict_keyword"] = True

    # Compute reward: fraction of passed checks that depend on outputs
    scored_keys = [
        "commands_exists",
        "commands_lines_count_match",
        "commands_has_required_keys",
        "commands_fields_match_input",
        "commands_times_format_and_order",
        "commands_within_window_and_duration",
        "non_overlap_by_day",
        "summary_exists_and_valid",
        "summary_count_matches",
        "summary_events_by_day_keys_match",
        "summary_events_by_day_counts_match",
        "notes_exists",
        "notes_min_length",
        "notes_has_conflict_keyword",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly model no-op baseline: if output dir missing or empty and required artifacts absent, reward 0.0
    # The above already yields 0.0 if no checks pass.

    result = {"reward": float(reward)}
    result.update(checks)
    last_nonempty_print(result)

if __name__ == "__main__":
    main()