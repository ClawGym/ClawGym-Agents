import json
import os
import sys
from datetime import datetime, timedelta, date
from math import ceil
from decimal import Decimal, ROUND_HALF_UP

def round_half_up(n):
    return int(Decimal(n).quantize(0, rounding=ROUND_HALF_UP))

def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def daterange_inclusive(start_d, end_d):
    days = (end_d - start_d).days
    for i in range(days + 1):
        yield start_d + timedelta(days=i)

def build_progress_bar(date_set, window_start, window_end):
    # Left-to-right is newest-to-oldest with end at leftmost
    chars = []
    d = window_end
    while d >= window_start:
        chars.append('█' if d in date_set else '░')
        d -= timedelta(days=1)
    return ''.join(chars)

def longest_streak(dates_set):
    if not dates_set:
        return 0
    days = sorted(dates_set)
    longest = 1
    cur = 1
    for i in range(1, len(days)):
        if days[i] == days[i-1] + timedelta(days=1):
            cur += 1
        else:
            if cur > longest:
                longest = cur
            cur = 1
    if cur > longest:
        longest = cur
    return longest

def current_streak(dates_set, today):
    # If logged on today, start today; else if logged on yesterday, start yesterday; else 0
    if today in dates_set:
        start = today
    elif (today - timedelta(days=1)) in dates_set:
        start = today - timedelta(days=1)
    else:
        return 0
    streak = 0
    d = start
    while d in dates_set:
        streak += 1
        d = d - timedelta(days=1)
    return streak

def is_int_like(x):
    return isinstance(x, int) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_stats_file": False,
        "has_report_file": False,
        "stats_valid_json_array": False,
        "stats_sorted_and_keys_ok": False,
        "stats_values_correct": False,
        "report_header_ok": False,
        "report_sections_match": False,
        "report_summary_ok": False,
        "names_consistent_between_files": False
    }

    # Constants per task
    WINDOW_START_STR = "2026-03-18"
    WINDOW_END_STR = "2026-03-31"
    WINDOW_START = parse_date(WINDOW_START_STR)
    WINDOW_END = parse_date(WINDOW_END_STR)
    WINDOW_DAYS = 14  # inclusive days count per problem statement

    # Load input reference
    habits_path = os.path.join(input_dir, "habits.json")
    logs_path = os.path.join(input_dir, "logs.json")
    try:
        with open(habits_path, "r", encoding="utf-8") as f:
            habits = json.load(f)
    except Exception:
        habits = None
    try:
        with open(logs_path, "r", encoding="utf-8") as f:
            logs = json.load(f)
    except Exception:
        logs = None

    # Prepare expected data structures only if inputs loaded
    expected_stats = []
    active_habits_sorted = []

    if isinstance(habits, list) and isinstance(logs, list):
        # Index logs by habitId for speed
        logs_by_habit = {}
        for l in logs:
            try:
                hid = l.get("habitId") or l.get("habit_id") or l.get("habitID")
                if not isinstance(hid, str):
                    continue
                cnt = l.get("count", 0)
                try:
                    cnt_val = int(cnt)
                except Exception:
                    cnt_val = 0
                d = parse_date(str(l.get("date", "")))
                if d is None:
                    continue
                if cnt_val <= 0:
                    continue  # only positive counts considered logged
                logs_by_habit.setdefault(hid, []).append((d, cnt_val))
            except Exception:
                continue

        # Filter active habits
        active_habits = []
        for h in habits:
            if not isinstance(h, dict):
                continue
            active = h.get("active")
            # Treat truthy boolean True as active
            if active is True:
                active_habits.append(h)

        # Sort by name ascending
        def name_key(h):
            n = h.get("name", "")
            if isinstance(n, str):
                return n.lower()
            return ""

        active_habits_sorted = sorted(active_habits, key=name_key)

        # Build expected stats for each active habit
        for h in active_habits_sorted:
            habit_id = h.get("id") or h.get("habitId") or ""
            name = h.get("name", "")
            frequency = h.get("frequency", "daily")
            target_raw = h.get("target", 1)
            try:
                target = int(target_raw)
            except Exception:
                target = 1
            if target < 0:
                target = 0
            # Collect logs for this habit
            habit_logs = logs_by_habit.get(habit_id, [])
            # Window filter
            total = 0
            active_dates_in_window = set()
            dates_to_counts = {}
            for d, c in habit_logs:
                # count all logs, we also need all dates for streaks later
                if WINDOW_START <= d <= WINDOW_END:
                    total += c
                    active_dates_in_window.add(d)
                    dates_to_counts[d] = dates_to_counts.get(d, 0) + c
            # activeDays
            active_days = len(active_dates_in_window)
            # completionRateStats expected by frequency
            if frequency == "weekly":
                expected_comp = ceil(WINDOW_DAYS / 7) * target
            elif frequency == "monthly":
                expected_comp = ceil(WINDOW_DAYS / 30) * target
            else:
                # default daily
                expected_comp = WINDOW_DAYS * target
            if expected_comp <= 0:
                comp_rate_stats = 0
            else:
                comp_rate_stats = round_half_up(min(100, (total / expected_comp) * 100))

            # completionRateReport always days*target
            denom_report = WINDOW_DAYS * target
            if denom_report <= 0:
                comp_rate_report = 0
            else:
                comp_rate_report = round_half_up((total / denom_report) * 100)

            # onTrack
            on_track = comp_rate_report >= 80

            # Progress bar
            # Build set of dates with any logs in window (count>0)
            dates_with_logs_in_window = set(active_dates_in_window)
            progress_bar = build_progress_bar(dates_with_logs_in_window, WINDOW_START, WINDOW_END)

            # Streaks across all logs
            # Build set of dates (unique) where there was any log count>0 for that habit across all time
            all_dates_set = set(d for d, c in habit_logs)
            streak_current = current_streak(all_dates_set, WINDOW_END)
            streak_longest = longest_streak(all_dates_set)

            expected_stats.append({
                "habitId": habit_id,
                "name": name,
                "frequency": frequency,
                "target": int(target),
                "windowStart": WINDOW_START_STR,
                "windowEnd": WINDOW_END_STR,
                "windowDays": WINDOW_DAYS,
                "totalCompletions": int(total),
                "activeDays": int(active_days),
                "completionRateStats": int(comp_rate_stats),
                "streakCurrentDays": int(streak_current),
                "streakLongestDays": int(streak_longest),
                "progressBar": progress_bar,
                "completionRateReport": int(comp_rate_report),
                "onTrack": bool(on_track),
            })

    # Paths to agent outputs
    stats_path = os.path.join(output_dir, "stats.json")
    report_path = os.path.join(output_dir, "report.txt")

    # Check existence
    if os.path.isfile(stats_path):
        checks["has_stats_file"] = True
    if os.path.isfile(report_path):
        checks["has_report_file"] = True

    # Early exit if missing main files: reward must be 0 if outputs missing
    agent_stats = None
    if checks["has_stats_file"]:
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                agent_stats = json.load(f)
            if isinstance(agent_stats, list):
                checks["stats_valid_json_array"] = True
        except Exception:
            agent_stats = None

    # Validate stats.json against expected
    required_keys = [
        "habitId", "name", "frequency", "target",
        "windowStart", "windowEnd", "windowDays",
        "totalCompletions", "activeDays", "completionRateStats",
        "streakCurrentDays", "streakLongestDays",
        "progressBar", "completionRateReport", "onTrack"
    ]

    # Helper to compare arrays by name order
    def names_list(lst):
        return [x.get("name", "") if isinstance(x, dict) else "" for x in lst]

    if checks["stats_valid_json_array"] and expected_stats is not None:
        # Check that number of items equals number of active habits
        size_ok = len(agent_stats) == len(expected_stats)
        # Check sorted by name ascending as in expected order
        expected_order_names = names_list(expected_stats)
        agent_order_names = names_list(agent_stats)
        sorted_ok = agent_order_names == expected_order_names
        # Check keys exact and values types
        keys_ok = True
        values_ok = True
        for idx, (agent_item, exp_item) in enumerate(zip(agent_stats, expected_stats)):
            if not isinstance(agent_item, dict):
                keys_ok = False
                values_ok = False
                break
            # exact keys
            agent_keys = set(agent_item.keys())
            if agent_keys != set(required_keys):
                keys_ok = False
            # values check
            # String fields
            if not isinstance(agent_item.get("habitId"), str):
                values_ok = False
            if not isinstance(agent_item.get("name"), str):
                values_ok = False
            if agent_item.get("frequency") not in ("daily", "weekly", "monthly"):
                values_ok = False
            # Int fields
            int_fields = [
                "target", "windowDays", "totalCompletions", "activeDays",
                "completionRateStats", "streakCurrentDays", "streakLongestDays",
                "completionRateReport"
            ]
            for k in int_fields:
                if not is_int_like(agent_item.get(k)):
                    values_ok = False
            # windowStart/End exact
            if agent_item.get("windowStart") != WINDOW_START_STR:
                values_ok = False
            if agent_item.get("windowEnd") != WINDOW_END_STR:
                values_ok = False
            # progressBar length and chars
            pb = agent_item.get("progressBar")
            if not isinstance(pb, str) or len(pb) != WINDOW_DAYS or any(ch not in ("█", "░") for ch in pb):
                values_ok = False
            # onTrack boolean
            if not isinstance(agent_item.get("onTrack"), bool):
                values_ok = False
            # Compare with expected values exactly
            for k in required_keys:
                if k in ("habitId", "name", "frequency", "target",
                         "windowStart", "windowEnd", "windowDays",
                         "totalCompletions", "activeDays", "completionRateStats",
                         "streakCurrentDays", "streakLongestDays",
                         "progressBar", "completionRateReport", "onTrack"):
                    if agent_item.get(k) != exp_item.get(k):
                        values_ok = False
        checks["stats_sorted_and_keys_ok"] = bool(size_ok and sorted_ok and keys_ok)
        checks["stats_values_correct"] = bool(size_ok and values_ok)

    # Validate report.txt formatting and contents
    report_lines = []
    if checks["has_report_file"]:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            # Normalize line endings and keep empty lines
            report_lines = report_text.splitlines()
        except Exception:
            report_lines = []

    # Header check
    if report_lines:
        header_ok = (report_lines[0].strip() == "Habit Tracker Report (2026-03-18 to 2026-03-31)")
        checks["report_header_ok"] = bool(header_ok)

    # Sections check
    sections_ok = False
    names_consistent = False
    summary_ok = False
    if expected_stats is not None and report_lines:
        # Parse sections:
        # For each active habit in expected order:
        # name line, progress bar line, "Completions: X | Streak: Y days | Rate: Z%" line, blank line
        # Then final summary line
        idx_line = 1  # start after header
        parsed_names = []
        parsed_progress = []
        parsed_metrics = []
        # skip any leading blank lines after header
        while idx_line < len(report_lines) and report_lines[idx_line].strip() == "":
            idx_line += 1

        ok = True
        for exp in expected_stats:
            if idx_line >= len(report_lines):
                ok = False
                break
            name_line = report_lines[idx_line].rstrip("\n")
            if name_line != exp["name"]:
                ok = False
                break
            parsed_names.append(name_line)
            idx_line += 1
            if idx_line >= len(report_lines):
                ok = False
                break
            pb_line = report_lines[idx_line]
            if pb_line != exp["progressBar"]:
                ok = False
                break
            parsed_progress.append(pb_line)
            idx_line += 1
            if idx_line >= len(report_lines):
                ok = False
                break
            metrics_line = report_lines[idx_line]
            expected_metrics_line = f"Completions: {exp['totalCompletions']} | Streak: {exp['streakCurrentDays']} days | Rate: {exp['completionRateReport']}%"
            if metrics_line != expected_metrics_line:
                ok = False
                break
            parsed_metrics.append(metrics_line)
            idx_line += 1
            # Expect blank line
            if idx_line >= len(report_lines):
                ok = False
                break
            if report_lines[idx_line].strip() != "":
                ok = False
                break
            idx_line += 1

        # After parsing all habits, skip extra blank lines
        while idx_line < len(report_lines) and report_lines[idx_line].strip() == "":
            idx_line += 1

        # Now expect summary line exactly
        if ok:
            total_active = len(expected_stats)
            on_track_count = sum(1 for x in expected_stats if x["onTrack"])
            expected_summary = f"Summary: {on_track_count}/{total_active} habits on track (≥80% completion)"
            if idx_line < len(report_lines) and report_lines[idx_line].strip() == expected_summary:
                summary_ok = True
            else:
                summary_ok = False
            sections_ok = ok
            # Names consistent with stats.json order
            if checks["stats_valid_json_array"] and isinstance(agent_stats, list):
                names_consistent = (parsed_names == names_list(agent_stats))
            else:
                names_consistent = (parsed_names == [e["name"] for e in expected_stats])

    checks["report_sections_match"] = bool(sections_ok)
    checks["report_summary_ok"] = bool(summary_ok)
    checks["names_consistent_between_files"] = bool(names_consistent)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["has_stats_file"] or checks["has_report_file"] else 0.0

    # No-op baseline: if output is empty or missing required artifacts, reward must be exactly 0.0
    # If either file missing or invalid core checks fail, reward may still be >0 due to partial; this is allowed as long as not fully missing.
    # However, if both files missing -> reward must be 0.0 (already ensured).
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()