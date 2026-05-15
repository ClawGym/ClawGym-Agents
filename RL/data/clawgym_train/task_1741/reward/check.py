import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def read_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def parse_ics_fields(text: str) -> dict:
    fields = {}
    for raw in text.splitlines():
        line = raw.strip()
        if ":" in line:
            key, val = line.split(":", 1)
            if key in {"SUMMARY", "ORGANIZER", "LOCATION", "DTSTART", "DTEND", "UID"}:
                fields[key] = val
    return fields


def compute_utc_z(dt_local_str: str, tz_offset_minutes: int) -> str:
    try:
        dt_local = datetime.strptime(dt_local_str, "%Y-%m-%dT%H:%M")
        dt_utc = dt_local - timedelta(minutes=int(tz_offset_minutes))
        return dt_utc.strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return ""


def extract_open_actions(prev_notes_text: str):
    actions = []
    # Only lines that end with STATUS: open
    for line in prev_notes_text.splitlines():
        if re.search(r"STATUS:\s*open\s*$", line):
            m = re.search(r"-\s*ACTION:\s*(.*?)\s*\(owner:\s*([^)]+)\)\s*STATUS:\s*open\s*$", line)
            if m:
                action_text = m.group(1).strip()
                owner = m.group(2).strip()
                actions.append({"action": action_text, "owner": owner})
            else:
                # If format unexpected but ends with STATUS: open, include raw line to allow minimal validation
                actions.append({"action": line.strip(), "owner": ""})
    return actions


def extract_done_actions(prev_notes_text: str):
    actions = []
    for line in prev_notes_text.splitlines():
        if re.search(r"STATUS:\s*done\s*$", line):
            m = re.search(r"-\s*ACTION:\s*(.*?)\s*\(owner:\s*([^)]+)\)\s*STATUS:\s*done\s*$", line)
            if m:
                actions.append({"action": m.group(1).strip(), "owner": m.group(2).strip()})
            else:
                actions.append({"action": line.strip(), "owner": ""})
    return actions


def line_contains_all(text: str, substrings):
    tl = text.lower()
    return all(s.lower() in tl for s in substrings)


def has_headcount_phrase(text: str, count: int) -> bool:
    # Look for the number near "attendees", "headcount", or "total"
    patterns = [
        rf"(?i)\b(attendees|headcount|total)\b[^0-9]{{0,40}}\b{count}\b",
        rf"\b{count}\b[^a-zA-Z]{{0,40}}(?i)\b(attendees|headcount|total)\b",
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "updated_config_exists": 0.0,
        "updated_config_event_times": 0.0,
        "updated_config_core_fields_preserved": 0.0,
        "updated_config_metadata_preserved": 0.0,
        "ics_exists": 0.0,
        "ics_core_fields_correct": 0.0,
        "ics_times_correct": 0.0,
        "agenda_exists": 0.0,
        "agenda_date_location_topics_correct": 0.0,
        "agenda_open_actions_included_correctly": 0.0,
        "briefing_exists": 0.0,
        "briefing_purpose_title_included": 0.0,
        "briefing_when_where_correct": 0.0,
        "briefing_attendees_list_and_count_correct": 0.0,
        "briefing_agenda_overview_correct": 0.0,
        "briefing_reference_paths_present": 0.0,
        "cross_file_consistency": 0.0,
    }

    # Paths
    input_config_path = workspace / "input" / "config" / "meeting_series.json"
    updated_config_path = workspace / "output" / "config" / "meeting_series.updated.json"
    ics_path = workspace / "output" / "calendar" / "eco_roundtable_2026-05-14.ics"
    agenda_template_path = workspace / "input" / "agenda_template.md"
    previous_notes_path = workspace / "input" / "previous_notes.md"
    agenda_out_path = workspace / "output" / "agendas" / "Agenda_2026-05-14_Eco_Roundtable.md"
    participants_path = workspace / "input" / "participants.json"
    briefing_out_path = workspace / "output" / "briefings" / "Staff_Briefing_2026-05-14.md"

    # Load input config (for preserved fields)
    input_cfg, _ = read_json_safe(input_config_path)

    # Load updated config
    upd_cfg, upd_err = read_json_safe(updated_config_path)
    if upd_cfg is not None and isinstance(upd_cfg, dict):
        scores["updated_config_exists"] = 1.0
        # Check event times
        event = upd_cfg.get("event", {})
        start_iso = event.get("start_iso")
        end_iso = event.get("end_iso")
        if start_iso == "2026-05-14T17:30" and end_iso == "2026-05-14T18:30":
            scores["updated_config_event_times"] = 1.0

        # Core fields preserved
        if input_cfg is not None:
            exp_title = input_cfg.get("event", {}).get("title")
            exp_location = input_cfg.get("event", {}).get("location")
            exp_uid = input_cfg.get("event", {}).get("uid")
            if (
                event.get("title") == exp_title
                and event.get("location") == exp_location
                and event.get("uid") == exp_uid
            ):
                scores["updated_config_core_fields_preserved"] = 1.0

            exp_tz = input_cfg.get("timezone_offset_minutes")
            exp_org = input_cfg.get("organizer")
            exp_series_title = input_cfg.get("series_title")
            if (
                upd_cfg.get("timezone_offset_minutes") == exp_tz
                and upd_cfg.get("organizer") == exp_org
                and upd_cfg.get("series_title") == exp_series_title
            ):
                scores["updated_config_metadata_preserved"] = 1.0
        else:
            # If input config missing, we cannot verify preserved fields -> remain 0.0
            pass
    else:
        # Updated config missing or invalid
        pass

    # ICS checks
    ics_text, ics_err = read_text_safe(ics_path)
    if ics_text is not None:
        scores["ics_exists"] = 1.0
        ics_fields = parse_ics_fields(ics_text)
        # Core fields: SUMMARY, ORGANIZER, LOCATION
        if upd_cfg is not None:
            exp_summary = upd_cfg.get("event", {}).get("title")
            exp_org = upd_cfg.get("organizer")
            exp_loc = upd_cfg.get("event", {}).get("location")
            if (
                ics_fields.get("SUMMARY") == exp_summary
                and ics_fields.get("ORGANIZER") == exp_org
                and ics_fields.get("LOCATION") == exp_loc
            ):
                scores["ics_core_fields_correct"] = 1.0

            # Times correct (UTC conversion)
            tz_offset = upd_cfg.get("timezone_offset_minutes", 0)
            start_iso = upd_cfg.get("event", {}).get("start_iso")
            end_iso = upd_cfg.get("event", {}).get("end_iso")
            dtstart_exp = compute_utc_z(start_iso, tz_offset) if start_iso else ""
            dtend_exp = compute_utc_z(end_iso, tz_offset) if end_iso else ""
            if ics_fields.get("DTSTART") == dtstart_exp and ics_fields.get("DTEND") == dtend_exp:
                scores["ics_times_correct"] = 1.0
        else:
            # Fall back to expected constants from task if updated config missing
            if (
                ics_fields.get("SUMMARY") == "Monthly Eco Partners Roundtable"
                and ics_fields.get("ORGANIZER") == "Eco-Lodge Chambéry"
                and ics_fields.get("LOCATION") == "Eco-Lodge Common Room, Chambéry"
            ):
                scores["ics_core_fields_correct"] = 1.0
            if (
                ics_fields.get("DTSTART") == "20260514T153000Z"
                and ics_fields.get("DTEND") == "20260514T163000Z"
            ):
                scores["ics_times_correct"] = 1.0

    # Agenda checks
    agenda_text, agenda_err = read_text_safe(agenda_out_path)
    if agenda_text is not None:
        scores["agenda_exists"] = 1.0
        # Date, Location, Topics
        has_date = "Date: 2026-05-14 17:30 (local)" in agenda_text
        has_loc = "Location: Eco-Lodge Common Room, Chambéry" in agenda_text
        has_topic1 = "Topic Focus 1: Reducing laundry water use" in agenda_text
        has_topic2 = "Topic Focus 2: Volunteer day planning with Réserve Naturelle des Bauges" in agenda_text
        if has_date and has_loc and has_topic1 and has_topic2:
            scores["agenda_date_location_topics_correct"] = 1.0

        # Open actions inclusion
        prev_text, _ = read_text_safe(previous_notes_path)
        if prev_text is not None:
            open_actions = extract_open_actions(prev_text)
            done_actions = extract_done_actions(prev_text)

            # Verify each open action appears as a bullet with action and owner
            found_all_open = True
            for act in open_actions:
                action = act["action"]
                owner = act["owner"]
                # Look for a line that contains both action and owner
                found = False
                for ln in agenda_text.splitlines():
                    if ln.strip().startswith("-") and (action and owner):
                        if action in ln and owner in ln:
                            found = True
                            break
                    elif ln.strip().startswith("-") and action and not owner:
                        if action in ln:
                            found = True
                            break
                if not found:
                    found_all_open = False
                    break

            # Ensure done actions not present in the open actions section
            # We'll enforce that no bullet line contains both the done action text and its owner
            no_done_included = True
            for done in done_actions:
                d_action = done["action"]
                d_owner = done["owner"]
                for ln in agenda_text.splitlines():
                    if ln.strip().startswith("-") and d_action and d_owner:
                        if d_action in ln and d_owner in ln:
                            no_done_included = False
                            break
                if not no_done_included:
                    break

            if found_all_open and no_done_included and len(open_actions) > 0:
                scores["agenda_open_actions_included_correctly"] = 1.0
            elif found_all_open and no_done_included and len(open_actions) == 0:
                # If there are no open actions per input, consider correct if none listed
                scores["agenda_open_actions_included_correctly"] = 1.0

    # Briefing checks
    briefing_text, briefing_err = read_text_safe(briefing_out_path)
    if briefing_text is not None:
        scores["briefing_exists"] = 1.0
        # Meeting title and purpose
        has_title = ("Monthly Eco Partners Roundtable" in briefing_text) or ("Eco Partners Roundtable" in briefing_text)
        has_purpose = "Coordinate responsible travel initiatives and local conservation actions." in briefing_text
        if has_title and has_purpose:
            scores["briefing_purpose_title_included"] = 1.0

        # When and Where
        has_date = ("2026-05-14" in briefing_text) and ("17:30" in briefing_text) and ("18:30" in briefing_text) and ("local" in briefing_text.lower())
        has_where = "Eco-Lodge Common Room, Chambéry" in briefing_text
        if has_date and has_where:
            scores["briefing_when_where_correct"] = 1.0

        # Attendees: list and count
        participants_data, _ = read_json_safe(participants_path)
        attendees_ok = False
        if participants_data and isinstance(participants_data, dict) and isinstance(participants_data.get("participants"), list):
            names = [p.get("name") for p in participants_data["participants"] if isinstance(p, dict) and p.get("name")]
            expected_count = len(names)
            # All names present?
            names_present = all(name in briefing_text for name in names)
            # Headcount present near label
            count_ok = has_headcount_phrase(briefing_text, expected_count)
            attendees_ok = names_present and count_ok
        if attendees_ok:
            scores["briefing_attendees_list_and_count_correct"] = 1.0

        # Agenda overview: contains two focus topics and note on open actions with count
        overview_ok = False
        topic1_ok = "Reducing laundry water use" in briefing_text
        topic2_ok = "Volunteer day planning with Réserve Naturelle des Bauges" in briefing_text
        prev_text2, _ = read_text_safe(previous_notes_path)
        open_count = 0
        if prev_text2 is not None:
            open_count = len(extract_open_actions(prev_text2))
        # Find a line mentioning open actions and the count
        open_count_ok = False
        for ln in briefing_text.splitlines():
            if re.search(r"(?i)open action", ln) and re.search(rf"\b{open_count}\b", ln):
                open_count_ok = True
                break
        if topic1_ok and topic2_ok and open_count_ok:
            overview_ok = True
        if overview_ok:
            scores["briefing_agenda_overview_correct"] = 1.0

        # Files for reference: include relative paths
        has_agenda_path = "output/agendas/Agenda_2026-05-14_Eco_Roundtable.md" in briefing_text
        has_ics_path = "output/calendar/eco_roundtable_2026-05-14.ics" in briefing_text
        if has_agenda_path and has_ics_path:
            scores["briefing_reference_paths_present"] = 1.0

    # Cross-file consistency check
    try:
        consistent = True
        # Require all main artifacts available
        if upd_cfg is None or ics_text is None or agenda_text is None or briefing_text is None:
            consistent = False
        else:
            # Location consistency
            loc_cfg = upd_cfg.get("event", {}).get("location")
            ics_fields = parse_ics_fields(ics_text)
            loc_ics = ics_fields.get("LOCATION")
            loc_in_agenda = "Location: " + loc_cfg if loc_cfg else ""
            loc_in_briefing = loc_cfg if loc_cfg else ""
            if not (loc_cfg and loc_ics == loc_cfg and (loc_in_agenda in agenda_text) and (loc_in_briefing in briefing_text)):
                consistent = False

            # Time consistency
            start_iso = upd_cfg.get("event", {}).get("start_iso")
            end_iso = upd_cfg.get("event", {}).get("end_iso")
            tz_offset = upd_cfg.get("timezone_offset_minutes", 0)
            expected_dtstart = compute_utc_z(start_iso, tz_offset) if start_iso else ""
            expected_dtend = compute_utc_z(end_iso, tz_offset) if end_iso else ""
            if expected_dtstart and expected_dtend:
                if not (("DTSTART:" + expected_dtstart) in ics_text and ("DTEND:" + expected_dtend) in ics_text):
                    consistent = False
            # Agenda date must match start local
            if start_iso:
                if f"Date: {start_iso.replace('T', ' ')} (local)" not in agenda_text:
                    consistent = False
            # Briefing must contain both local start and end times
            if start_iso and end_iso:
                if not (start_iso[0:10] in briefing_text and start_iso[11:16] in briefing_text and end_iso[11:16] in briefing_text):
                    consistent = False
        scores["cross_file_consistency"] = 1.0 if consistent else 0.0
    except Exception:
        scores["cross_file_consistency"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()