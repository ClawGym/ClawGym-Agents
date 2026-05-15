import json
import os
import sys
import csv
import re
from datetime import datetime, timedelta

def read_anchor_date(input_dir):
    anchor_path = os.path.join(input_dir, "date_anchor.txt")
    fallback = "2026-02-02"
    try:
        with open(anchor_path, "r", encoding="utf-8") as f:
            line = f.read().strip()
            # Expect ISO date YYYY-MM-DD
            datetime.strptime(line, "%Y-%m-%d")
            return line
    except Exception:
        # Treat anchor as 2026-02-02 (Monday) if missing or invalid
        return fallback

def load_new_tasks(input_dir):
    path = os.path.join(input_dir, "new_tasks.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []

def week_dates_from_anchor(anchor_str):
    # anchor is Monday
    anchor = datetime.strptime(anchor_str, "%Y-%m-%d")
    # Return mapping and sets for Mon-Fri (0..4)
    mapping = {
        "Mon": anchor + timedelta(days=0),
        "Tue": anchor + timedelta(days=1),
        "Wed": anchor + timedelta(days=2),
        "Thu": anchor + timedelta(days=3),
        "Fri": anchor + timedelta(days=4),
        "Sat": anchor + timedelta(days=5),
        "Sun": anchor + timedelta(days=6),
    }
    mon_fri_list = [anchor + timedelta(days=i) for i in range(5)]
    mon_fri_strs = [d.strftime("%Y-%m-%d") for d in mon_fri_list]
    return mapping, set(mon_fri_strs)

def build_expected_schedule_rows(tasks, weekday_map, allowed_dates_set):
    # Expected rows only for Mon-Fri in the anchor week
    expected = set()
    for item in tasks:
        title = item.get("title")
        lst = item.get("list")
        weekdays = item.get("weekdays", [])
        if not isinstance(weekdays, list):
            continue
        if not isinstance(title, str) or not isinstance(lst, str):
            continue
        for wd in weekdays:
            if not isinstance(wd, str):
                continue
            wd = wd.strip()
            if wd in weekday_map:
                date_str = weekday_map[wd].strftime("%Y-%m-%d")
                if date_str in allowed_dates_set:
                    expected.add((date_str, "09:00", title, lst))
    return expected

def parse_tsv_schedule(schedule_path):
    rows = []
    try:
        with open(schedule_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                # Skip completely empty rows
                if not row or all(col.strip() == "" for col in row):
                    continue
                rows.append([col.strip() for col in row])
    except Exception:
        return None
    return rows

def maybe_strip_header(rows):
    if not rows:
        return rows, False
    header = rows[0]
    if len(header) == 4:
        h0 = header[0].strip().lower()
        h1 = header[1].strip().lower()
        h2 = header[2].strip().lower()
        h3 = header[3].strip().lower()
        if (h0, h1, h2, h3) == ("date", "time", "title", "list"):
            return rows[1:], True
    return rows, False

def jsonl_load_commands(commands_path):
    objs = []
    try:
        with open(commands_path, "r", encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if not s:
                    # Ignore blank lines
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                objs.append(obj)
    except Exception:
        return None
    return objs

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "all_outputs_present": False,
        "commands_file_exists": False,
        "commands_jsonl_valid": False,
        "commands_has_overdue_json_listing": False,
        "commands_has_followup_move_to_work": False,
        "commands_has_postpone_overdue_to_next_monday": False,
        "commands_has_complete_weekly_review": False,
        "commands_has_final_week_view_plain": False,
        "commands_has_add_due_in_week": False,
        "schedule_file_exists": False,
        "schedule_tsv_parseable": False,
        "schedule_rows_in_range_and_time": False,
        "schedule_expected_rows_present": False,
        "plan_file_exists": False,
        "plan_contains_anchor": False,
    }

    # Paths
    commands_path = os.path.join(output_dir, "commands", "weekly_reset.jsonl")
    schedule_path = os.path.join(output_dir, "schedule", "this_week_due.tsv")
    plan_path = os.path.join(output_dir, "plan", "weekly_reset.md")

    # Compute anchor and relevant dates
    anchor_str = read_anchor_date(input_dir)  # default to 2026-02-02 if missing/invalid
    weekday_map, allowed_dates_set = week_dates_from_anchor(anchor_str)
    # Specific due datetimes required by the spec
    # Tuesday after anchor at 09:00
    tue_after_anchor = (datetime.strptime(anchor_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + " 09:00"
    # Next Monday after anchor at 09:00
    next_monday_after_anchor = (datetime.strptime(anchor_str, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d") + " 09:00"
    # Allowed due datetime strings for add commands (Mon-Fri at 09:00)
    allowed_due_datetimes = {d + " 09:00" for d in allowed_dates_set}

    # Check file existence
    commands_exists = os.path.isfile(commands_path)
    schedule_exists = os.path.isfile(schedule_path)
    plan_exists = os.path.isfile(plan_path)

    checks["commands_file_exists"] = commands_exists
    checks["schedule_file_exists"] = schedule_exists
    checks["plan_file_exists"] = plan_exists
    checks["all_outputs_present"] = commands_exists and schedule_exists and plan_exists

    # Validate commands JSONL and content requirements
    cmd_objects = None
    if commands_exists:
        cmd_objects = jsonl_load_commands(commands_path)
        if cmd_objects is not None and len(cmd_objects) > 0:
            # Validate each line has required keys and types
            valid = True
            for obj in cmd_objects:
                if not isinstance(obj, dict):
                    valid = False
                    break
                if not all(k in obj for k in ("step", "command", "rationale")):
                    valid = False
                    break
                if not isinstance(obj.get("command"), str) or not isinstance(obj.get("rationale"), str):
                    valid = False
                    break
                if not isinstance(obj.get("step"), int):
                    # Require integer step as specified
                    valid = False
                    break
            checks["commands_jsonl_valid"] = valid

            # If we have parsed commands, scan for required actions
            for obj in cmd_objects:
                cmd = obj.get("command", "")
                cmd_lower = cmd.lower()

                # Overdue listing in JSON: must include "overdue" and "--json"
                if ("overdue" in cmd_lower) and ("--json" in cmd_lower):
                    checks["commands_has_overdue_json_listing"] = True

                # Edit 'Follow up:' items to Work list due Tuesday after anchor at 09:00
                # Check presence of edit action, --list Work and the explicit due datetime
                if ("edit" in cmd_lower) and ("--list Work" in cmd) and (f"--due {tue_after_anchor}" in cmd):
                    checks["commands_has_followup_move_to_work"] = True

                # Postpone remaining overdue items to next Monday after anchor at 09:00 (edit with due)
                if ("edit" in cmd_lower) and (f"--due {next_monday_after_anchor}" in cmd):
                    checks["commands_has_postpone_overdue_to_next_monday"] = True

                # Complete "Weekly Review" from previous week: look for "complete" and "Weekly Review"
                if ("complete" in cmd_lower) and ("Weekly Review" in cmd):
                    checks["commands_has_complete_weekly_review"] = True

                # Final weekly view in plain TSV: contains "week" and "--plain"
                if ("week" in cmd_lower) and ("--plain" in cmd_lower):
                    checks["commands_has_final_week_view_plain"] = True

                # Add commands with explicit anchor-week due at 09:00
                if ("add" in cmd_lower):
                    # Look for any allowed due datetime
                    for due_dt in allowed_due_datetimes:
                        if f"--due {due_dt}" in cmd:
                            checks["commands_has_add_due_in_week"] = True
                            break
                # Early exit if all command-related checks are satisfied
                if (checks["commands_has_overdue_json_listing"]
                    and checks["commands_has_followup_move_to_work"]
                    and checks["commands_has_postpone_overdue_to_next_monday"]
                    and checks["commands_has_complete_weekly_review"]
                    and checks["commands_has_final_week_view_plain"]
                    and checks["commands_has_add_due_in_week"]):
                    # do not break outer loop, but we could; keep scanning harmlessly
                    pass

    # Validate schedule TSV
    schedule_rows = None
    if schedule_exists:
        schedule_rows = parse_tsv_schedule(schedule_path)
        if schedule_rows is not None and len(schedule_rows) > 0:
            # Remove optional header if present
            data_rows, had_header = maybe_strip_header(schedule_rows)

            # Validate column count and parsing
            parseable = True
            # Collect present rows for presence check
            present_rows = set()
            in_range_and_time_ok = True

            for row in data_rows:
                if len(row) != 4:
                    parseable = False
                    break
                date_str, time_str, title, lst = row
                # Validate date format
                try:
                    datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    parseable = False
                    break
                # Validate time format (must be exactly 09:00)
                # We'll evaluate strictness in separate check; here just ensure format HH:MM
                if not re.match(r"^\d{2}:\d{2}$", time_str):
                    parseable = False
                    break

                # Range/time constraints
                if date_str not in allowed_dates_set or time_str != "09:00":
                    in_range_and_time_ok = False

                present_rows.add((date_str, time_str, title, lst))

            checks["schedule_tsv_parseable"] = parseable
            # Only evaluate further if parseable
            if parseable:
                checks["schedule_rows_in_range_and_time"] = in_range_and_time_ok

                # Build expected rows from inputs (Mon-Fri occurrences only)
                tasks = load_new_tasks(input_dir)
                expected_rows = build_expected_schedule_rows(tasks, weekday_map, allowed_dates_set)

                # Ensure all expected rows are present (as exact matches)
                checks["schedule_expected_rows_present"] = expected_rows.issubset(present_rows)

    # Validate plan markdown
    if plan_exists:
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Must contain the anchor date string "2026-02-02"
            checks["plan_contains_anchor"] = ("2026-02-02" in content)
        except Exception:
            checks["plan_contains_anchor"] = False

    # Compute reward
    # If any required output file is missing, reward must be exactly 0.0
    if not checks["all_outputs_present"]:
        reward = 0.0
    else:
        # Deterministic scoring: fraction of checks passed
        # Count all boolean checks (excluding reward)
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON line with reward first and all checks
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()