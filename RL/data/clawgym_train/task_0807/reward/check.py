import json
import os
import re
import sys
from datetime import datetime, date
from collections import OrderedDict

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_valid_date(s):
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def is_valid_time(s):
    if not isinstance(s, str):
        return False
    m = re.fullmatch(r"(\d{2}):(\d{2})", s)
    if not m:
        return False
    hh = int(m.group(1))
    mm = int(m.group(2))
    return 0 <= hh <= 23 and 0 <= mm <= 59

def weekday_name_for(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        return dt.strftime("%A")
    except Exception:
        return None

def compare_day_of_week(date_str, day_name):
    expected = weekday_name_for(date_str)
    if expected is None or not isinstance(day_name, str):
        return False
    return expected.lower() == day_name.strip().lower()

def looks_like_iana_tz(tz):
    return isinstance(tz, str) and "/" in tz and len(tz.strip()) > 0

def is_url(s):
    return isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    events_path = os.path.join(output_dir, "events.json")
    ics_path = os.path.join(output_dir, "calendar_export.txt")
    summary_path = os.path.join(output_dir, "summary.md")
    emails_path = os.path.join(input_dir, "emails.txt")

    checks = OrderedDict()
    # Initialize all checks to False
    checks["has_all_required_outputs"] = False
    checks["events_json_exists"] = False
    checks["events_json_is_array_and_len_ge_6"] = False
    checks["events_items_have_required_keys_and_types"] = False
    checks["events_date_format_valid_all"] = False
    checks["events_time_format_valid_all"] = False
    checks["events_day_of_week_matches_all"] = False
    checks["events_timezones_iana_like_all"] = False
    checks["has_ET_and_PT_items_distinct"] = False
    checks["has_type_event"] = False
    checks["has_type_deadline"] = False
    checks["has_recurring_or_travel_item"] = False
    checks["has_multi_day_item"] = False
    checks["deadline_has_action_and_url"] = False
    checks["soft_team_lunch_medium_default_time"] = False
    checks["source_quotes_match_emails_at_least_3"] = False
    checks["calendar_export_exists"] = False
    checks["calendar_export_bounds_and_events_ge_5"] = False
    checks["calendar_export_has_rrule"] = False
    checks["summary_exists"] = False
    checks["summary_has_numbered_list_and_day_names"] = False
    checks["summary_has_action_url"] = False
    checks["summary_includes_source_quote_for_medium_low"] = False

    # Quick presence check
    if os.path.isfile(events_path) and os.path.isfile(ics_path) and os.path.isfile(summary_path):
        checks["has_all_required_outputs"] = True

    events_data = None
    if os.path.isfile(events_path):
        checks["events_json_exists"] = True
        events_data = load_json_file(events_path)

    # Validate events.json structure and items
    items = []
    if isinstance(events_data, list):
        items = events_data
        if len(items) >= 6:
            checks["events_json_is_array_and_len_ge_6"] = True

    # Required schema fields
    required_keys = {
        "title",
        "type",
        "date",
        "day_of_week",
        "time_start",
        "time_end",
        "timezone",
        "is_all_day",
        "is_multi_day",
        "end_date",
        "recurrence",
        "location",
        "url",
        "attendees",
        "confidence",
        "source_quote",
        "notes",
        "deadline_action",
        "deadline_url",
        "reminder_minutes",
    }

    # Per-item validations
    schema_ok = True
    date_ok_all = True
    time_ok_all = True
    day_ok_all = True
    tz_ok_all = True

    found_type_event = False
    found_type_deadline = False
    found_recurring_or_travel = False
    found_multi_day = False
    found_deadline_with_action_url = False
    found_soft_team_lunch = False

    # Timezones presence checks
    et_candidates = {"America/New_York", "US/Eastern", "America/Detroit", "America/Toronto"}
    pt_candidates = {"America/Los_Angeles", "US/Pacific", "America/Vancouver"}
    has_et = False
    has_pt = False

    # For summary checks later
    medium_low_source_quotes = []

    # For source quote vs emails
    emails_content = read_text_file(emails_path) or ""

    if isinstance(items, list) and len(items) > 0:
        for it in items:
            # Check required keys presence
            if not isinstance(it, dict):
                schema_ok = False
                break
            if not required_keys.issubset(it.keys()):
                schema_ok = False
                break
            # Type checks for some fields
            # attendees must be list
            if not isinstance(it.get("attendees"), list):
                schema_ok = False
                break
            # is_all_day & is_multi_day booleans
            if not isinstance(it.get("is_all_day"), bool) or not isinstance(it.get("is_multi_day"), bool):
                schema_ok = False
                break
            # confidence must be one of
            if it.get("confidence") not in {"high", "medium", "low"}:
                schema_ok = False
                break
            # source_quote: non-empty str
            if not isinstance(it.get("source_quote"), str) or len(it.get("source_quote").strip()) == 0:
                schema_ok = False
                break
            # notes: str (can be empty)
            if not isinstance(it.get("notes"), str):
                schema_ok = False
                break
            # deadline_action: None or str
            da = it.get("deadline_action")
            if da is not None and not isinstance(da, str):
                schema_ok = False
                break
            # deadline_url: None or str
            du = it.get("deadline_url")
            if du is not None and not isinstance(du, str):
                schema_ok = False
                break
            # end_date: None or valid date
            ed = it.get("end_date")
            if ed is not None:
                if not is_valid_date(ed):
                    schema_ok = False
                    break
            # recurrence: None or str
            rec = it.get("recurrence")
            if rec is not None and not isinstance(rec, str):
                schema_ok = False
                break
            # location/url: None or str
            if it.get("location") is not None and not isinstance(it.get("location"), str):
                schema_ok = False
                break
            if it.get("url") is not None and not isinstance(it.get("url"), str):
                schema_ok = False
                break
            # reminder_minutes: int-like
            if not isinstance(it.get("reminder_minutes"), int):
                schema_ok = False
                break

            # Date format
            d = it.get("date")
            if not is_valid_date(d):
                date_ok_all = False
            # time formats
            if not is_valid_time(it.get("time_start")) or not is_valid_time(it.get("time_end")):
                time_ok_all = False
            # day-of-week match
            if not compare_day_of_week(d, it.get("day_of_week")):
                day_ok_all = False
            # timezone format
            tz = it.get("timezone")
            if not looks_like_iana_tz(tz):
                tz_ok_all = False

            # ET/PT detection
            if isinstance(tz, str):
                if tz in et_candidates:
                    has_et = True
                if tz in pt_candidates:
                    has_pt = True

            # type presence
            ttype = it.get("type")
            if ttype == "event":
                found_type_event = True
            if ttype == "deadline":
                found_type_deadline = True

            # recurring or travel
            if it.get("recurrence") is not None:
                found_recurring_or_travel = True
            if ttype == "travel":
                found_recurring_or_travel = True

            # multi-day
            if it.get("is_multi_day") is True and it.get("end_date") is not None and is_valid_date(d) and is_valid_date(it.get("end_date")):
                try:
                    start_dt = datetime.strptime(d, "%Y-%m-%d").date()
                    end_dt = datetime.strptime(it.get("end_date"), "%Y-%m-%d").date()
                    if end_dt >= start_dt:
                        found_multi_day = True
                except Exception:
                    pass

            # deadline action/url completeness
            if ttype == "deadline":
                da = it.get("deadline_action")
                du = it.get("deadline_url")
                if isinstance(da, str) and len(da.strip()) > 0 and isinstance(du, str) and len(du.strip()) > 0:
                    found_deadline_with_action_url = True

            # soft Team Lunch check
            title = it.get("title", "")
            source_quote = it.get("source_quote", "")
            if isinstance(title, str) and isinstance(source_quote, str):
                lower_title = title.lower()
                lower_sq = source_quote.lower()
                if ("team lunch" in lower_title) or ("team lunch" in lower_sq):
                    if it.get("confidence") == "medium" and it.get("time_start") == "09:00" and it.get("time_end") == "10:00":
                        found_soft_team_lunch = True

            # collect medium/low quotes
            if it.get("confidence") in {"medium", "low"}:
                q = it.get("source_quote")
                if isinstance(q, str) and q:
                    medium_low_source_quotes.append(q)

        # After loop, assign aggregated per-item validations
        if schema_ok:
            checks["events_items_have_required_keys_and_types"] = True
        if date_ok_all and len(items) > 0:
            checks["events_date_format_valid_all"] = True
        if time_ok_all and len(items) > 0:
            checks["events_time_format_valid_all"] = True
        if day_ok_all and len(items) > 0:
            checks["events_day_of_week_matches_all"] = True
        if tz_ok_all and len(items) > 0:
            checks["events_timezones_iana_like_all"] = True

        if has_et and has_pt:
            checks["has_ET_and_PT_items_distinct"] = True
        if found_type_event:
            checks["has_type_event"] = True
        if found_type_deadline:
            checks["has_type_deadline"] = True
        if found_recurring_or_travel:
            checks["has_recurring_or_travel_item"] = True
        if found_multi_day:
            checks["has_multi_day_item"] = True
        if found_deadline_with_action_url:
            checks["deadline_has_action_and_url"] = True
        if found_soft_team_lunch:
            checks["soft_team_lunch_medium_default_time"] = True

        # source_quote vs emails content: at least 3 items where quote is substring
        if emails_content:
            count_match = 0
            for it in items:
                sq = it.get("source_quote", "")
                if isinstance(sq, str) and sq and sq in emails_content:
                    count_match += 1
            if count_match >= 3:
                checks["source_quotes_match_emails_at_least_3"] = True

    # ICS checks
    ics_text = None
    if os.path.isfile(ics_path):
        checks["calendar_export_exists"] = True
        ics_text = read_text_file(ics_path)
        if isinstance(ics_text, str):
            # First non-empty line BEGIN:VCALENDAR and contains END:VCALENDAR
            lines = [ln.strip() for ln in ics_text.splitlines() if ln.strip() != ""]
            bounds_ok = False
            if lines:
                if lines[0] == "BEGIN:VCALENDAR" and "END:VCALENDAR" in lines:
                    bounds_ok = True
            # count VEVENT
            vevent_count = len(re.findall(r"\bBEGIN:VEVENT\b", ics_text))
            if bounds_ok and vevent_count >= 5:
                checks["calendar_export_bounds_and_events_ge_5"] = True
            # RRULE presence
            if re.search(r"\bRRULE:", ics_text) is not None:
                checks["calendar_export_has_rrule"] = True

    # Summary checks
    summary_text = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_text = read_text_file(summary_path) or ""
        if summary_text:
            lines = summary_text.splitlines()
            numbered = any(re.match(r"^\s*\d+\.\s+", ln) for ln in lines)
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            has_day_name = any(dn in summary_text for dn in day_names)
            if numbered and has_day_name:
                checks["summary_has_numbered_list_and_day_names"] = True
            # Action URL presence in summary
            if "http://" in summary_text or "https://" in summary_text:
                checks["summary_has_action_url"] = True
            # Include source quote for a medium/low confidence item
            included_any_quote = False
            for q in medium_low_source_quotes:
                if q and q in summary_text:
                    included_any_quote = True
                    break
            if included_any_quote:
                checks["summary_includes_source_quote_for_medium_low"] = True

    # Compute reward: fraction of checks passed, but gate to 0.0 if required outputs missing
    total_checks = len(checks) - 1  # exclude has_all_required_outputs from denominator?
    # We will include all checks in denominator to weight equally; but gating applies.
    passed = sum(1 for v in checks.values() if v)
    # Gate: if any required output file missing, reward must be 0.0
    if not checks["has_all_required_outputs"]:
        reward = 0.0
    else:
        # Exclude has_all_required_outputs from the ratio to avoid double counting presence
        denom_keys = [k for k in checks.keys() if k != "has_all_required_outputs"]
        denom = len(denom_keys)
        passed_without_gate = sum(1 for k, v in checks.items() if k != "has_all_required_outputs" and v)
        reward = passed_without_gate / denom if denom > 0 else 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    out = OrderedDict()
    out["reward"] = round(reward, 6)
    for k, v in checks.items():
        out[k] = v

    print(json.dumps(out))

if __name__ == "__main__":
    main()