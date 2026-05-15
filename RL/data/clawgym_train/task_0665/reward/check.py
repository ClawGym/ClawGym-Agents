import json
import os
import re
import sys
from datetime import datetime, date

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, None

def is_iso_date(s):
    return isinstance(s, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None

def parse_date(s):
    # Expect YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def weekday_abbrev(d):
    # Python weekday(): Monday=0..Sunday=6
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return names[d.weekday()]

def is_weekend_py(d):
    # Saturday (5) or Sunday (6)
    return d.weekday() >= 5

def find_weekday_header(lines):
    # Return (index, alignment) where alignment is "Mon" or "Sun", or (None, None)
    sun_first_re = re.compile(r"\bSun\b.*\bMon\b.*\bTue\b.*\bWed\b.*\bThu\b.*\bFri\b.*\bSat\b")
    mon_first_re = re.compile(r"\bMon\b.*\bTue\b.*\bWed\b.*\bThu\b.*\bFri\b.*\bSat\b.*\bSun\b")
    for idx, line in enumerate(lines):
        if sun_first_re.search(line):
            return idx, "Sun"
        if mon_first_re.search(line):
            return idx, "Mon"
    return None, None

def count_week_rows(lines, header_idx):
    # Count lines after header that look like week rows (>=7 tokens by whitespace or '|')
    count = 0
    for line in lines[header_idx+1:]:
        raw = line.strip()
        if not raw:
            continue
        if '|' in raw:
            tokens = [t.strip() for t in raw.split('|') if t.strip() != ""]
        else:
            tokens = raw.split()
        if len(tokens) >= 7:
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "calendar_json_exists": False,
        "calendar_json_valid_json": False,
        "calendar_json_length_42": False,
        "calendar_json_required_fields": False,
        "calendar_json_day_of_week_correct": False,
        "calendar_json_weekend_correct": False,
        "calendar_json_holiday_fields_consistent": False,
        "calendar_json_alignment_valid": False,

        "stats_json_exists": False,
        "stats_json_valid_json": False,
        "stats_json_valid_fields": False,
        "stats_year_month_match": False,
        "stats_consistency_with_calendar": False,

        "calendar_md_exists": False,
        "calendar_md_non_empty": False,
        "calendar_md_month_year_present": False,
        "calendar_md_header_alignment_consistent": False,
        "calendar_md_six_week_rows": False,
    }

    # Paths
    cal_json_path = os.path.join(output_dir, "calendar.json")
    stats_json_path = os.path.join(output_dir, "stats.json")
    cal_md_path = os.path.join(output_dir, "calendar.md")

    calendar_items = None
    stats = None
    cal_md_text = None
    grid_alignment = None  # "Mon" or "Sun"

    # Load calendar.json
    if os.path.isfile(cal_json_path):
        checks["calendar_json_exists"] = True
        ok, data = load_json(cal_json_path)
        if ok and isinstance(data, list):
            checks["calendar_json_valid_json"] = True
            calendar_items = data
            if len(calendar_items) == 42:
                checks["calendar_json_length_42"] = True

            # Validate required fields and types
            required_keys = {
                "date": str,
                "is_current_month": bool,
                "is_weekend": bool,
                "day_of_week_name": str,
                "week_of_year": int,
                "day_of_year": int,
                "is_holiday": bool,
                "holiday_name": str,
            }
            fields_ok = True
            dayname_set = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"}
            for item in calendar_items:
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                for k, t in required_keys.items():
                    if k not in item:
                        fields_ok = False
                        break
                    v = item[k]
                    if t is int:
                        if not (isinstance(v, int) and not isinstance(v, bool)):
                            fields_ok = False
                            break
                    elif t is bool:
                        if not isinstance(v, bool):
                            fields_ok = False
                            break
                    elif t is str:
                        if not isinstance(v, str):
                            fields_ok = False
                            break
                if not fields_ok:
                    break
                # Additional validation for specific fields
                if not is_iso_date(item["date"]):
                    fields_ok = False
                    break
                if item["day_of_week_name"] not in dayname_set:
                    fields_ok = False
                    break
            if fields_ok:
                checks["calendar_json_required_fields"] = True

            # Weekend and day_of_week correctness, holiday name rule, alignment
            if checks["calendar_json_required_fields"]:
                # compute correctness
                weekend_ok = True
                dow_ok = True
                holiday_ok = True
                for item in calendar_items:
                    d = parse_date(item["date"])
                    if d is None:
                        weekend_ok = False
                        dow_ok = False
                        holiday_ok = False
                        break
                    if item["is_weekend"] != is_weekend_py(d):
                        weekend_ok = False
                    if item["day_of_week_name"] != weekday_abbrev(d):
                        dow_ok = False
                    if item["is_holiday"]:
                        if not item["holiday_name"] or item["holiday_name"].strip() == "":
                            holiday_ok = False
                checks["calendar_json_weekend_correct"] = weekend_ok
                checks["calendar_json_day_of_week_correct"] = dow_ok
                checks["calendar_json_holiday_fields_consistent"] = holiday_ok

                # Alignment: first 7 entries names sequence must be Mon-first or Sun-first
                if len(calendar_items) >= 7:
                    first7 = [item["day_of_week_name"] for item in calendar_items[:7]]
                    mon_seq = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    sun_seq = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                    if first7 == mon_seq:
                        checks["calendar_json_alignment_valid"] = True
                        grid_alignment = "Mon"
                    elif first7 == sun_seq:
                        checks["calendar_json_alignment_valid"] = True
                        grid_alignment = "Sun"

    # Load stats.json
    if os.path.isfile(stats_json_path):
        checks["stats_json_exists"] = True
        ok, data = load_json(stats_json_path)
        if ok and isinstance(data, dict):
            checks["stats_json_valid_json"] = True
            stats = data
            # Validate fields and basic relationships
            needed_ints = ["year", "month", "days_in_month", "weekdays_count", "weekends_count", "holidays_in_month"]
            ints_ok = True
            for k in needed_ints:
                if k not in stats or not (isinstance(stats[k], int) and not isinstance(stats[k], bool)):
                    ints_ok = False
                    break
            strings_ok = True
            for k in ["first_day", "last_day"]:
                if k not in stats or not is_iso_date(stats[k]):
                    strings_ok = False
                    break
            if ints_ok and strings_ok:
                # month range, non-negative counts, and basic sum consistency
                basic_ok = True
                if not (1 <= stats["month"] <= 12):
                    basic_ok = False
                for k in ["days_in_month", "weekdays_count", "weekends_count", "holidays_in_month"]:
                    if stats[k] < 0:
                        basic_ok = False
                if stats["weekdays_count"] + stats["weekends_count"] != stats["days_in_month"]:
                    basic_ok = False
                if basic_ok:
                    checks["stats_json_valid_fields"] = True

                # Year/month match first/last day strings
                fd = parse_date(stats["first_day"])
                ld = parse_date(stats["last_day"])
                if fd and ld and fd <= ld:
                    if fd.year == stats["year"] and fd.month == stats["month"] and ld.year == stats["year"] and ld.month == stats["month"]:
                        checks["stats_year_month_match"] = True

    # Cross consistency between calendar.json and stats.json
    if (
        calendar_items is not None
        and stats is not None
        and checks["calendar_json_required_fields"]
        and checks["stats_json_valid_fields"]
    ):
        in_month_items = [it for it in calendar_items if it.get("is_current_month") is True]
        # Count based checks
        try:
            days_in_month_match = (len(in_month_items) == stats["days_in_month"])
            weekends_in_month = 0
            holidays_in_month = 0
            dates_in_month = []
            for it in in_month_items:
                d = parse_date(it["date"])
                if d is None:
                    days_in_month_match = False
                    break
                dates_in_month.append(d)
                if it["is_weekend"]:
                    weekends_in_month += 1
                if it["is_holiday"]:
                    holidays_in_month += 1
            if dates_in_month:
                first_day_calc = min(dates_in_month).strftime("%Y-%m-%d")
                last_day_calc = max(dates_in_month).strftime("%Y-%m-%d")
            else:
                first_day_calc = None
                last_day_calc = None

            weekends_match = (weekends_in_month == stats["weekends_count"])
            weekdays_match = ((stats["days_in_month"] - stats["weekends_count"]) == stats["weekdays_count"])
            holidays_match = (holidays_in_month == stats["holidays_in_month"])
            first_last_match = (first_day_calc == stats["first_day"] and last_day_calc == stats["last_day"])

            if days_in_month_match and weekends_match and weekdays_match and holidays_match and first_last_match:
                checks["stats_consistency_with_calendar"] = True
        except Exception:
            pass

    # Load calendar.md
    if os.path.isfile(cal_md_path):
        checks["calendar_md_exists"] = True
        ok, text = load_text(cal_md_path)
        if ok and isinstance(text, str):
            cal_md_text = text
            if cal_md_text.strip() != "":
                checks["calendar_md_non_empty"] = True

    # Calendar.md content checks
    if cal_md_text and stats is not None and isinstance(stats.get("month"), int) and isinstance(stats.get("year"), int):
        # Month name and year presence
        month_names = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        month_name = month_names[stats["month"]]
        if re.search(re.escape(month_name), cal_md_text, flags=re.IGNORECASE) and str(stats["year"]) in cal_md_text:
            checks["calendar_md_month_year_present"] = True

        # Header line alignment consistency with grid alignment
        lines = cal_md_text.splitlines()
        header_idx, header_alignment = find_weekday_header(lines)
        header_ok = False
        if header_idx is not None and header_alignment in ("Mon", "Sun"):
            # If grid alignment known, require consistency
            if grid_alignment in ("Mon", "Sun"):
                header_ok = (header_alignment == grid_alignment)
            else:
                # If grid alignment unknown, at least header found
                header_ok = True
        if header_ok:
            checks["calendar_md_header_alignment_consistent"] = True

        # Count week rows (should be at least 6)
        if header_idx is not None:
            week_rows = count_week_rows(lines, header_idx)
            if week_rows >= 6:
                checks["calendar_md_six_week_rows"] = True

    # Compute reward
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if passed > 0 else 0.0

    # Print final JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()