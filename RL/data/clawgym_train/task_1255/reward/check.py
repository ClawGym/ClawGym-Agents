import csv
import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional


DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"


def _safe_read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows, None
    except Exception as e:
        return None, str(e)


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)


def _parse_date(s: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except Exception:
        return None


def _valid_time_str(s: str) -> bool:
    try:
        datetime.strptime(s, TIME_FMT)
        return True
    except Exception:
        return False


def _normalize_heading(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r'^[#>\s]+', '', stripped)  # remove markdown heading markers or whitespace
    return stripped.strip().lower()


def _find_section_bounds(text: str, section_name: str, next_sections: List[str]) -> Tuple[int, int]:
    lines = text.splitlines()
    start_idx = -1
    end_idx = len(lines)
    section_name_norm = section_name.lower()
    next_norms = [s.lower() for s in next_sections]
    for idx, line in enumerate(lines):
        h = _normalize_heading(line)
        if h == section_name_norm and start_idx == -1:
            start_idx = idx + 1  # content starts after heading line
        elif start_idx != -1 and h in next_norms:
            end_idx = idx
            break
    return start_idx, end_idx


def _extract_section(text: str, section_name: str, all_sections_in_order: List[str]) -> Optional[str]:
    # Determine next sections after the given section_name
    if section_name not in all_sections_in_order:
        return None
    idx = all_sections_in_order.index(section_name)
    next_sections = all_sections_in_order[idx + 1:]
    start, end = _find_section_bounds(text, section_name, next_sections)
    if start == -1:
        return None
    lines = text.splitlines()
    return "\n".join(lines[start:end]).strip()


def _integers_in_text(s: str) -> List[int]:
    return [int(x) for x in re.findall(r'\d+', s)]


def _channel_aliases(channel: str) -> List[str]:
    aliases = {channel}
    aliases.add(channel.replace("_", " "))
    aliases.add(channel.replace("_", "-"))
    # Common title-case variants
    aliases.add(channel.replace("_", " ").title())
    aliases.add(channel.replace("_", "-").title())
    return list(aliases)


def _find_channel_count_in_text(text: str, channel: str, expected_count: int) -> bool:
    aliases = _channel_aliases(channel)
    for line in text.splitlines():
        low = line.lower()
        if any(alias.lower() in low for alias in aliases):
            nums = _integers_in_text(line)
            if expected_count in nums:
                return True
    return False


def _per_day_channel_counts(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], int]:
    counts: Dict[Tuple[str, str], int] = {}
    for r in rows:
        key = (r.get("scheduled_date", ""), r.get("channel", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    input_ideas_path = workspace / "input" / "content_ideas.csv"
    config_path = workspace / "config" / "campaign.json"
    builder_path = workspace / "tools" / "calendar_builder.py"
    calendar_path = workspace / "out" / "calendar.csv"
    meeting_path = workspace / "out" / "meeting_notes.md"
    email_path = workspace / "out" / "email_merch.txt"
    dm_path = workspace / "out" / "dm_mods.txt"

    scores = {
        "config_dates_set_from_ideas": 0.0,
        "config_channels_include_required": 0.0,
        "config_hashtags_include_required": 0.0,
        "config_time_slots_and_timezone_valid": 0.0,
        "calendar_exists_and_valid_csv": 0.0,
        "calendar_includes_instagram_reels": 0.0,
        "calendar_includes_thread_format": 0.0,
        "calendar_dates_within_campaign_and_idea_ranges": 0.0,
        "calendar_scheduling_deterministic_times_first_slot": 0.0,
        "calendar_counts_within_max_per_day_per_channel": 0.0,
        "calendar_includes_all_schedulable_ideas": 0.0,
        "meeting_notes_sections_present": 0.0,
        "decisions_include_campaign_dates_timezone": 0.0,
        "decisions_channel_counts_match_calendar": 0.0,
        "action_items_one_per_scheduled_with_owner_channel_date": 0.0,
        "email_merch_subject_and_references_correct": 0.0,
        "dm_mods_references_and_cta_correct": 0.0,
    }

    # Load inputs
    ideas, ideas_err = _safe_read_csv_dicts(input_ideas_path)
    cfg, cfg_err = _safe_read_json(config_path)
    calendar_rows, cal_err = _safe_read_csv_dicts(calendar_path)

    # Precompute ideas mapping and date range
    earliest_date = None
    latest_date = None
    ideas_by_id: Dict[str, Dict[str, str]] = {}
    if ideas is not None:
        try:
            for row in ideas:
                idea_id = row.get("idea_id", "").strip()
                ideas_by_id[idea_id] = row
                ds = _parse_date(row.get("date_range_start", "").strip())
                de = _parse_date(row.get("date_range_end", "").strip())
                if ds is None or de is None:
                    earliest_date = None
                    latest_date = None
                    break
                if earliest_date is None or ds < earliest_date:
                    earliest_date = ds
                if latest_date is None or de > latest_date:
                    latest_date = de
        except Exception:
            earliest_date = None
            latest_date = None

    # Config checks
    if cfg is not None and ideas is not None and earliest_date is not None and latest_date is not None:
        start_date_str = cfg.get("start_date", "").strip()
        end_date_str = cfg.get("end_date", "").strip()
        cfg_campaign_name = cfg.get("campaign_name", "")
        # campaign_name must remain the same, but we only need dates set from ideas explicitly
        if start_date_str == earliest_date.strftime(DATE_FMT) and end_date_str == latest_date.strftime(DATE_FMT):
            scores["config_dates_set_from_ideas"] = 1.0

        channels = cfg.get("channels", [])
        required_channels = {"twitter", "instagram", "instagram_reels"}
        if isinstance(channels, list) and required_channels.issubset(set(channels)):
            scores["config_channels_include_required"] = 1.0

        hashtags = cfg.get("hashtags", [])
        if isinstance(hashtags, list) and "#Halsey" in hashtags and "#HalseyAppreciationWeek" in hashtags:
            scores["config_hashtags_include_required"] = 1.0

        time_slots = cfg.get("time_slots", {})
        tz_ok = (cfg.get("timezone", "") == "UTC")
        ts_ok = False
        if isinstance(time_slots, dict):
            tw = time_slots.get("twitter", [])
            ig = time_slots.get("instagram", [])
            reels = time_slots.get("instagram_reels", [])
            # ensure counts and valid time strings
            def all_valid(times: List[str]) -> bool:
                if not isinstance(times, list) or not times:
                    return False
                return all(_valid_time_str(t) for t in times)
            if isinstance(tw, list) and len(tw) >= 2 and all_valid(tw) and all_valid(ig) and all_valid(reels):
                ts_ok = True
        if tz_ok and ts_ok:
            scores["config_time_slots_and_timezone_valid"] = 1.0
    else:
        # If config missing or ideas missing, all config checks remain 0.0
        cfg_campaign_name = cfg.get("campaign_name", "") if isinstance(cfg, dict) else ""

    # Calendar existence and validity
    calendar_valid = False
    if calendar_rows is not None:
        # basic header validation
        required_cols = {"idea_id", "channel", "format", "scheduled_date", "scheduled_time", "theme", "priority"}
        present_cols = set(calendar_rows[0].keys()) if calendar_rows else set()
        if required_cols.issubset(present_cols):
            # validate row field types/formats
            try:
                for r in calendar_rows:
                    if not r.get("idea_id") or not r.get("channel") or not r.get("format"):
                        raise ValueError("Missing required fields")
                    if _parse_date(r.get("scheduled_date", "")) is None:
                        raise ValueError("Invalid date")
                    if not _valid_time_str(r.get("scheduled_time", "")):
                        raise ValueError("Invalid time")
                calendar_valid = True
            except Exception:
                calendar_valid = False
    if calendar_valid:
        scores["calendar_exists_and_valid_csv"] = 1.0

    # Calendar content checks require config and ideas and calendar
    if calendar_valid and isinstance(cfg, dict) and ideas is not None:
        # Check that instagram_reels and thread items are present
        has_reels = any(r.get("idea_id") == "3" and r.get("channel") == "instagram_reels" for r in calendar_rows)
        if has_reels:
            scores["calendar_includes_instagram_reels"] = 1.0
        has_thread = any(r.get("idea_id") == "2" and r.get("format") == "thread" for r in calendar_rows)
        if has_thread:
            scores["calendar_includes_thread_format"] = 1.0

        # Calendar dates within campaign and idea ranges
        start_date = _parse_date(cfg.get("start_date", ""))
        end_date = _parse_date(cfg.get("end_date", ""))
        within_all = True
        for r in calendar_rows:
            d = _parse_date(r.get("scheduled_date", ""))
            if d is None or start_date is None or end_date is None:
                within_all = False
                break
            if not (start_date <= d <= end_date):
                within_all = False
                break
            idea = ideas_by_id.get(r.get("idea_id", ""))
            if idea is None:
                within_all = False
                break
            idea_start = _parse_date(idea.get("date_range_start", ""))
            idea_end = _parse_date(idea.get("date_range_end", ""))
            if idea_start is None or idea_end is None:
                within_all = False
                break
            if not (idea_start <= d <= idea_end):
                within_all = False
                break
        if within_all:
            scores["calendar_dates_within_campaign_and_idea_ranges"] = 1.0

        # Deterministic scheduling: time equals first configured time slot for channel, and date equals idea start when possible
        det_ok = True
        time_slots = cfg.get("time_slots", {})
        for r in calendar_rows:
            ch = r.get("channel")
            stime = r.get("scheduled_time")
            if ch not in time_slots or not isinstance(time_slots[ch], list) or not time_slots[ch]:
                det_ok = False
                break
            if stime != time_slots[ch][0]:
                det_ok = False
                break
            # Check date equals idea date_range_start (no shifting expected for given dataset)
            idea = ideas_by_id.get(r.get("idea_id", ""))
            if idea is None:
                det_ok = False
                break
            idea_start = _parse_date(idea.get("date_range_start", ""))
            r_date = _parse_date(r.get("scheduled_date", ""))
            if idea_start is None or r_date is None:
                det_ok = False
                break
            # Only enforce equality if within campaign window and max-per-day not exceeded; for this dataset it's always equal
            if r_date != idea_start:
                det_ok = False
                break
        if det_ok:
            scores["calendar_scheduling_deterministic_times_first_slot"] = 1.0

        # Max per day per channel
        max_per_day = int(cfg.get("rules", {}).get("max_posts_per_day_per_channel", 2))
        per_day_counts = _per_day_channel_counts(calendar_rows)
        if all(count <= max_per_day for count in per_day_counts.values()):
            scores["calendar_counts_within_max_per_day_per_channel"] = 1.0

        # Includes all schedulable ideas (overlap with campaign, channel in config, time slot configured)
        cfg_channels = set(cfg.get("channels", [])) if isinstance(cfg.get("channels", []), list) else set()
        cfg_time_slots = cfg.get("time_slots", {}) if isinstance(cfg.get("time_slots", {}), dict) else {}
        expected_ids = []
        if start_date is not None and end_date is not None:
            for idea in ideas:
                ch = idea.get("channel", "")
                ds = _parse_date(idea.get("date_range_start", ""))
                de = _parse_date(idea.get("date_range_end", ""))
                if ds is None or de is None:
                    continue
                # overlap
                if de < start_date or ds > end_date:
                    continue
                if ch not in cfg_channels:
                    continue
                if ch not in cfg_time_slots or not cfg_time_slots.get(ch):
                    continue
                expected_ids.append(idea.get("idea_id", ""))
        cal_ids = [r.get("idea_id", "") for r in calendar_rows]
        if sorted(expected_ids) == sorted(cal_ids):
            scores["calendar_includes_all_schedulable_ideas"] = 1.0

    # Meeting notes checks
    meeting_text, meeting_err = _safe_read_text(meeting_path)
    # Compute counts from calendar for later checks
    calendar_counts: Dict[str, int] = {}
    if calendar_valid:
        for r in calendar_rows:
            ch = r.get("channel", "")
            calendar_counts[ch] = calendar_counts.get(ch, 0) + 1

    if meeting_text is not None:
        # Sections present in order: Agenda, Decisions, Action Items
        sections_order = ["Agenda", "Decisions", "Action Items"]
        # find occurrences
        lines = meeting_text.splitlines()
        found_indices = []
        for s in sections_order:
            idx = -1
            for i, line in enumerate(lines):
                if _normalize_heading(line) == s.lower():
                    idx = i
                    break
            found_indices.append(idx)
        if all(idx >= 0 for idx in found_indices) and found_indices == sorted(found_indices):
            scores["meeting_notes_sections_present"] = 1.0

        # Decisions: campaign_name, dates, timezone, per-channel counts
        decisions = _extract_section(meeting_text, "Decisions", sections_order) or ""
        cfg_ok = isinstance(cfg, dict)
        decisions_ok = False
        decisions_counts_ok = False
        if cfg_ok:
            cfg_campaign_name = cfg.get("campaign_name", "")
            start_date_str = cfg.get("start_date", "")
            end_date_str = cfg.get("end_date", "")
            tz = cfg.get("timezone", "")
            if cfg_campaign_name and start_date_str and end_date_str and tz:
                if (cfg_campaign_name in decisions and start_date_str in decisions and end_date_str in decisions and tz in decisions):
                    decisions_ok = True
            # Check channel counts
            if calendar_valid and calendar_counts:
                counts_match = True
                for ch, count in calendar_counts.items():
                    if not _find_channel_count_in_text(decisions, ch, count):
                        counts_match = False
                        break
                if counts_match:
                    decisions_counts_ok = True
        if decisions_ok:
            scores["decisions_include_campaign_dates_timezone"] = 1.0
        if decisions_counts_ok:
            scores["decisions_channel_counts_match_calendar"] = 1.0

        # Action Items: one line per scheduled idea with owner, channel, scheduled_date
        action_items = _extract_section(meeting_text, "Action Items", sections_order) or ""
        action_lines = [ln for ln in action_items.splitlines() if ln.strip()]
        matched = 0
        if calendar_valid:
            used_indices = set()
            for r in calendar_rows:
                owner = "Me" if r.get("priority", "").lower() == "high" else "Alex"
                ch = r.get("channel", "")
                date = r.get("scheduled_date", "")
                # find a line with all tokens
                found = False
                for idx, ln in enumerate(action_lines):
                    if idx in used_indices:
                        continue
                    low = ln.lower()
                    if owner.lower() in low and ch.lower() in low and date in ln:
                        # ensure there is at least some description beyond tokens
                        temp = ln
                        temp = re.sub(re.escape(owner), "", temp, flags=re.IGNORECASE)
                        temp = re.sub(re.escape(ch), "", temp, flags=re.IGNORECASE)
                        temp = temp.replace(date, "")
                        if re.search(r"[A-Za-z]", temp):
                            used_indices.add(idx)
                            matched += 1
                            found = True
                            break
                if not found:
                    # can't find corresponding line
                    pass
            if matched == len(calendar_rows) and len(action_lines) >= len(calendar_rows):
                scores["action_items_one_per_scheduled_with_owner_channel_date"] = 1.0

    # Email merch checks
    email_text, email_err = _safe_read_text(email_path)
    if email_text is not None and isinstance(cfg, dict) and calendar_valid:
        lines = [ln for ln in email_text.splitlines()]
        # find first non-empty line
        first_non_empty = None
        for ln in lines:
            if ln.strip():
                first_non_empty = ln
                break
        subject_ok = bool(first_non_empty and first_non_empty.startswith("Subject:"))
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        body_lower = body.lower()
        cfg_campaign_name = cfg.get("campaign_name", "")
        start_date_str = cfg.get("start_date", "")
        end_date_str = cfg.get("end_date", "")
        references_ok = (cfg_campaign_name in body and start_date_str in body and end_date_str in body)
        counts_ok = True
        for ch, count in calendar_counts.items():
            if not _find_channel_count_in_text(body, ch, count):
                counts_ok = False
                break
        # CTA: confirm or share assets
        cta_ok = (("confirm" in body_lower or "share" in body_lower) and "assets" in body_lower)
        if subject_ok and references_ok and counts_ok and cta_ok:
            scores["email_merch_subject_and_references_correct"] = 1.0

    # DM mods checks
    dm_text, dm_err = _safe_read_text(dm_path)
    if dm_text is not None and isinstance(cfg, dict) and calendar_valid:
        body = dm_text
        body_lower = body.lower()
        cfg_campaign_name = cfg.get("campaign_name", "")
        start_date_str = cfg.get("start_date", "")
        end_date_str = cfg.get("end_date", "")
        references_ok = (cfg_campaign_name in body and start_date_str in body and end_date_str in body)
        counts_ok = True
        for ch, count in calendar_counts.items():
            if not _find_channel_count_in_text(body, ch, count):
                counts_ok = False
                break
        # CTA: approve cross-posting
        cross_post_present = any(x in body_lower for x in ["cross-post", "cross post", "crossposting", "crossposting", "crosspost"])
        cta_ok = ("approve" in body_lower and cross_post_present)
        if references_ok and counts_ok and cta_ok:
            scores["dm_mods_references_and_cta_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()