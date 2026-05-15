import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, time, timedelta, timezone


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _load_json(path: Path):
    txt, err = _read_text(path)
    if err:
        return None, err
    try:
        return json.loads(txt), None
    except Exception as e:
        return None, f"json parse error: {e}"


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows, None
    except Exception as e:
        return None, None, str(e)


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


def _parse_bool_str(s: str):
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    v = s.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def _parse_time_hhmm(s: str):
    try:
        parts = s.strip().split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return time(hour=hh, minute=mm)
        return None
    except Exception:
        return None


def _parse_utc_z(ts: str):
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s.endswith("Z"):
        return None
    try:
        # datetime.fromisoformat doesn't accept Z, replace with +00:00
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _parse_iso_aware(ts: str):
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        # Must include explicit numeric offset
        # Reject naive datetimes (without offset)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        return dt
    except Exception:
        return None


def _offset_str_to_seconds(s: str):
    """
    Parse an offset like +02:00, -06:00, +0200, UTC+02:00, GMT-06:00, or Z to seconds.
    """
    if not isinstance(s, str):
        return None
    v = s.strip().upper()
    if v == "Z" or v == "UTC" or v == "GMT":
        return 0
    # Remove leading UTC/GMT and surrounding text
    v = re.sub(r'^(UTC|GMT)\s*', '', v)
    m = re.search(r'([+-])\s*(\d{1,2})(?::?(\d{2}))?$', v)
    if not m:
        return None
    sign = -1 if m.group(1) == '-' else 1
    hh = int(m.group(2))
    mm = int(m.group(3)) if m.group(3) else 0
    if hh > 18 or mm >= 60:
        return None
    return sign * (hh * 3600 + mm * 60)


def _parse_offset_value_to_seconds(val):
    """
    Accept common representations:
    - string "+02:00", "-06:00", "UTC+02:00", "Z"
    - int/float (seconds)
    - dict with keys 'utc_offset', 'offset', 'raw_offset' containing either string or number
    """
    if isinstance(val, (int, float)):
        try:
            sec = int(round(val))
            # Basic sanity: absolute offset should be less than 18 hours
            if abs(sec) <= 18 * 3600:
                return sec
            return None
        except Exception:
            return None
    if isinstance(val, str):
        return _offset_str_to_seconds(val)
    if isinstance(val, dict):
        for k in ("utc_offset", "offset", "raw_offset"):
            if k in val:
                return _parse_offset_value_to_seconds(val[k])
        # Some formats might include 'total_seconds' or nested fields
        if "total_seconds" in val and isinstance(val["total_seconds"], (int, float)):
            return _parse_offset_value_to_seconds(val["total_seconds"])
    return None


def _ensure_date_keys_for_offsets(obj):
    if not isinstance(obj, dict):
        return False
    # expect keys as 'YYYY-MM-DD'
    for k in obj.keys():
        if not isinstance(k, str):
            return False
        try:
            datetime.strptime(k, "%Y-%m-%d").date()
        except Exception:
            return False
    return True


def _dates_list_yyyy_mm_dd(start: date, end: date):
    return [d.isoformat() for d in _daterange(start, end)]


def _normalize_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _dt_add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def _load_holidays(path: Path, expected_cc: str):
    data, err = _load_json(path)
    if err or not isinstance(data, list):
        return None, False
    ok = True
    dates = set()
    for item in data:
        if not isinstance(item, dict):
            ok = False
            break
        d = item.get("date")
        cc = item.get("countryCode")
        # Nager.Date returns 'date' as '2025-01-01' or '2025-01-01T00:00:00' depending on API.
        # We'll parse the first 10 chars as date string if possible.
        if not isinstance(d, str) or len(d) < 10:
            ok = False
            break
        try:
            ds = d[:10]
            _ = datetime.strptime(ds, "%Y-%m-%d").date()
        except Exception:
            ok = False
            break
        if not isinstance(cc, str) or cc.upper() != expected_cc.upper():
            # Some API variants might not include 'countryCode' for country-specific endpoint,
            # but to be strict with the task, we require it.
            ok = False
            break
        dates.add(ds)
    if not ok:
        return None, False
    return dates, True


def _load_offsets_map(path: Path, required_dates):
    obj, err = _load_json(path)
    if err or not _ensure_date_keys_for_offsets(obj):
        return None, False
    out = {}
    ok = True
    for d in required_dates:
        if d not in obj:
            ok = False
            break
        sec = _parse_offset_value_to_seconds(obj[d])
        if sec is None:
            ok = False
            break
        out[d] = sec
    if not ok:
        return None, False
    return out, True


def _attendee_windows(attendees_rows):
    """
    Returns a list of dicts with tz, start_time, end_time.
    """
    windows = []
    for r in attendees_rows:
        tz = r.get("tz_iana")
        ws = r.get("working_start")
        we = r.get("working_end")
        t_ws = _parse_time_hhmm(ws) if isinstance(ws, str) else None
        t_we = _parse_time_hhmm(we) if isinstance(we, str) else None
        if not tz or t_ws is None or t_we is None:
            return None
        # ensure start < end (same day)
        if datetime.combine(date(2000, 1, 1), t_we) <= datetime.combine(date(2000, 1, 1), t_ws):
            return None
        windows.append({"tz": tz, "start": t_ws, "end": t_we})
    return windows


def _compute_overlap_utc_for_date(d: date, windows, zone_to_offsets):
    """
    Convert all attendees' local working windows to UTC for date d, then compute intersection.
    Returns (utc_start: datetime, utc_end: datetime) in UTC tzinfo, or (None, None) if no overlap.
    """
    intervals = []
    for w in windows:
        tz = w["tz"]
        # get offset seconds for this date and zone
        zmap = zone_to_offsets.get(tz)
        if not zmap:
            return None, None
        off_sec = zmap.get(d.isoformat())
        if off_sec is None:
            return None, None
        # local start/end
        local_start = datetime.combine(d, w["start"]).replace(tzinfo=None)
        local_end = datetime.combine(d, w["end"]).replace(tzinfo=None)
        # Convert to UTC by subtracting offset
        utc_start = (local_start - timedelta(seconds=off_sec)).replace(tzinfo=timezone.utc)
        utc_end = (local_end - timedelta(seconds=off_sec)).replace(tzinfo=timezone.utc)
        intervals.append((utc_start, utc_end))
    if not intervals:
        return None, None
    start_max = max(iv[0] for iv in intervals)
    end_min = min(iv[1] for iv in intervals)
    if end_min <= start_max:
        return None, None
    return start_max, end_min


def _generate_candidate_slots(start_date: date, end_date: date, windows, zone_to_offsets, fr_holidays, mx_holidays):
    candidates = []
    for d in _daterange(start_date, end_date):
        if not _is_weekday(d):
            continue
        ds = d.isoformat()
        if ds in fr_holidays or ds in mx_holidays:
            continue
        ov_start, ov_end = _compute_overlap_utc_for_date(d, windows, zone_to_offsets)
        if ov_start is None or ov_end is None:
            continue
        # Normalize to minute precision
        s = _normalize_to_minute(ov_start)
        e = _normalize_to_minute(ov_end)
        cur = s
        while cur + timedelta(minutes=60) <= e:
            candidates.append({
                "date": ds,
                "utc_start": cur,
                "utc_end": cur + timedelta(minutes=60),
            })
            cur = cur + timedelta(minutes=60)
    candidates.sort(key=lambda x: x["utc_start"])
    return candidates


def _parse_local_and_compare(utc_dt: datetime, local_ts: str, expected_offset_sec: int):
    """
    Validate that the given local_ts corresponds to utc_dt with the expected offset.
    Returns True if matches exactly to minute, else False.
    """
    dt_local = _parse_iso_aware(local_ts)
    if dt_local is None:
        return False
    # check numeric offset matches expected
    offset_td = dt_local.utcoffset()
    if offset_td is None:
        return False
    actual_sec = int(offset_td.total_seconds())
    if actual_sec != expected_offset_sec:
        return False
    # convert local to UTC and compare
    conv_utc = dt_local.astimezone(timezone.utc)
    return _normalize_to_minute(conv_utc) == _normalize_to_minute(utc_dt)


def _parse_date_str(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _time_in_range(t: time, start: time, end: time) -> bool:
    # assumes same day window and start < end
    return (t > start or t == start) and (t < end or t == end)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "holidays_files_present_and_valid": 0.0,
        "time_offsets_files_present_and_valid": 0.0,
        "proposals_csv_structure_and_count": 0.0,
        "proposals_timestamps_and_order_valid": 0.0,
        "proposals_utc_vs_local_consistency": 0.0,
        "proposals_within_working_hours": 0.0,
        "proposals_avoid_weekends_and_holidays": 0.0,
        "summary_json_structure_and_sources": 0.0,
        "summary_selected_slots_match_csv": 0.0,
        "summary_tz_offsets_match_web": 0.0,
        "determinism_three_earliest_slots_across_week": 0.0,
    }

    # Constants
    start_date = date(2025, 5, 12)
    end_date = date(2025, 5, 16)
    expected_dates = _dates_list_yyyy_mm_dd(start_date, end_date)

    # Load input attendees
    attendees_path = workspace / "input" / "attendees.csv"
    attendees_header, attendees_rows, attendees_err = _load_csv_dicts(attendees_path)
    windows = None
    if not attendees_err and attendees_header:
        windows = _attendee_windows(attendees_rows)

    # Load holidays
    hol_fr_path = workspace / "web" / "holidays_FR_2025.json"
    hol_mx_path = workspace / "web" / "holidays_MX_2025.json"
    fr_holidays, fr_ok = _load_holidays(hol_fr_path, "FR")
    mx_holidays, mx_ok = _load_holidays(hol_mx_path, "MX")
    if fr_ok and mx_ok and isinstance(fr_holidays, set) and isinstance(mx_holidays, set):
        scores["holidays_files_present_and_valid"] = 1.0

    # Load time offsets
    tz_paris_path = workspace / "web" / "time_offsets_Europe_Paris_2025-05-12_2025-05-16.json"
    tz_mex_path = workspace / "web" / "time_offsets_America_Mexico_City_2025-05-12_2025-05-16.json"
    paris_offsets, paris_ok = _load_offsets_map(tz_paris_path, expected_dates)
    mex_offsets, mex_ok = _load_offsets_map(tz_mex_path, expected_dates)
    if paris_ok and mex_ok:
        scores["time_offsets_files_present_and_valid"] = 1.0

    # Build zone_to_offsets for computation
    zone_to_offsets = {}
    if paris_ok:
        zone_to_offsets["Europe/Paris"] = paris_offsets
    if mex_ok:
        zone_to_offsets["America/Mexico_City"] = mex_offsets

    # Load proposals.csv
    proposals_path = workspace / "outputs" / "proposals.csv"
    prop_header, prop_rows, prop_err = _load_csv_dicts(proposals_path)
    header_ok = False
    if not prop_err and isinstance(prop_header, list):
        expected_header = [
            "slot_id",
            "date",
            "utc_start",
            "utc_end",
            "america_mexico_city_start",
            "america_mexico_city_end",
            "europe_paris_start",
            "europe_paris_end",
            "is_holiday_FR",
            "is_holiday_MX",
            "all_within_working_hours",
        ]
        header_ok = (prop_header == expected_header)
        if header_ok and isinstance(prop_rows, list) and len(prop_rows) == 3:
            scores["proposals_csv_structure_and_count"] = 1.0

    # Validate proposals timestamps and order
    proposals_valid = False
    parsed_proposals = []
    if header_ok and prop_rows:
        all_ok = True
        # check slot_id uniqueness
        slot_ids = set()
        utc_starts = []
        for r in prop_rows:
            sid = r.get("slot_id")
            if not sid or sid in slot_ids:
                all_ok = False
            slot_ids.add(sid)
            d_str = r.get("date")
            dt_date = _parse_date_str(d_str)
            if dt_date is None or not (start_date <= dt_date <= end_date) or not _is_weekday(dt_date):
                all_ok = False
            us = r.get("utc_start")
            ue = r.get("utc_end")
            if not isinstance(us, str) or not isinstance(ue, str):
                all_ok = False
            dt_us = _parse_utc_z(us)
            dt_ue = _parse_utc_z(ue)
            if dt_us is None or dt_ue is None:
                all_ok = False
            else:
                # Duration 60 minutes
                if _normalize_to_minute(dt_ue) - _normalize_to_minute(dt_us) != timedelta(minutes=60):
                    all_ok = False
                # date matches utc_start date
                if dt_us.date() != dt_date:
                    all_ok = False
                utc_starts.append(_normalize_to_minute(dt_us))
            parsed_proposals.append({
                "slot_id": sid,
                "date": dt_date,
                "utc_start": dt_us,
                "utc_end": dt_ue,
                "row": r,
            })
        # check ascending order by utc_start as listed in CSV
        if all_ok:
            utc_starts_ordered = sorted(utc_starts)
            if utc_starts != utc_starts_ordered:
                all_ok = False
        if all_ok:
            scores["proposals_timestamps_and_order_valid"] = 1.0
            proposals_valid = True

    # Validate UTC vs local consistency using offsets from web files
    utc_local_ok = False
    if proposals_valid and paris_ok and mex_ok:
        all_ok = True
        for p in parsed_proposals:
            ds = p["date"].isoformat()
            off_paris = paris_offsets.get(ds)
            off_mex = mex_offsets.get(ds)
            row = p["row"]
            # Local fields must have explicit numeric offsets
            eps = row.get("europe_paris_start")
            epe = row.get("europe_paris_end")
            mps = row.get("america_mexico_city_start")
            mpe = row.get("america_mexico_city_end")
            if not all(isinstance(x, str) for x in [eps, epe, mps, mpe]):
                all_ok = False
                break
            # Validate local conversions
            if not _parse_local_and_compare(p["utc_start"], eps, off_paris):
                all_ok = False
                break
            if not _parse_local_and_compare(p["utc_end"], epe, off_paris):
                all_ok = False
                break
            if not _parse_local_and_compare(p["utc_start"], mps, off_mex):
                all_ok = False
                break
            if not _parse_local_and_compare(p["utc_end"], mpe, off_mex):
                all_ok = False
                break
        if all_ok:
            scores["proposals_utc_vs_local_consistency"] = 1.0
            utc_local_ok = True

    # Validate within working hours
    within_ok = False
    if proposals_valid and windows is not None and paris_ok and mex_ok:
        all_ok = True
        for p in parsed_proposals:
            ds = p["date"].isoformat()
            row = p["row"]
            # Parse local timestamps for each timezone to extract local times
            # For each attendee, verify local start >= working_start and local end <= working_end
            # We'll compute local times via offsets map rather than relying on provided local strings.
            # For Mexico City attendees
            off_mex = mex_offsets.get(ds)
            off_paris = paris_offsets.get(ds)
            if off_mex is None or off_paris is None:
                all_ok = False
                break
            # Compute local times for both zones
            start_mex_local = (p["utc_start"] + timedelta(seconds=off_mex)).timetz()
            end_mex_local = (p["utc_end"] + timedelta(seconds=off_mex)).timetz()
            start_paris_local = (p["utc_start"] + timedelta(seconds=off_paris)).timetz()
            end_paris_local = (p["utc_end"] + timedelta(seconds=off_paris)).timetz()
            # Now check each attendee according to tz
            for w in windows:
                if w["tz"] == "America/Mexico_City":
                    s_ok = _time_in_range(time(start_mex_local.hour, start_mex_local.minute), w["start"], w["end"])
                    e_ok = _time_in_range(time(end_mex_local.hour, end_mex_local.minute), w["start"], w["end"])
                elif w["tz"] == "Europe/Paris":
                    s_ok = _time_in_range(time(start_paris_local.hour, start_paris_local.minute), w["start"], w["end"])
                    e_ok = _time_in_range(time(end_paris_local.hour, end_paris_local.minute), w["start"], w["end"])
                else:
                    # Unknown tz in attendees
                    all_ok = False
                    break
                if not (s_ok and e_ok):
                    all_ok = False
                    break
            if not all_ok:
                break
            # Check the all_within_working_hours column is true
            aw = _parse_bool_str(row.get("all_within_working_hours"))
            if aw is not True:
                all_ok = False
                break
        if all_ok:
            scores["proposals_within_working_hours"] = 1.0
            within_ok = True

    # Validate avoid weekends and holidays and flags
    avoid_ok = False
    if proposals_valid and fr_ok and mx_ok:
        all_ok = True
        for p in parsed_proposals:
            ds = p["date"].isoformat()
            if not _is_weekday(p["date"]):
                all_ok = False
                break
            fr_flag = _parse_bool_str(p["row"].get("is_holiday_FR"))
            mx_flag = _parse_bool_str(p["row"].get("is_holiday_MX"))
            # Proposals must not be on holiday dates
            if ds in fr_holidays or ds in mx_holidays:
                all_ok = False
                break
            # And flags should be false
            if fr_flag is not False or mx_flag is not False:
                all_ok = False
                break
        if all_ok:
            scores["proposals_avoid_weekends_and_holidays"] = 1.0
            avoid_ok = True

    # Load summary.json
    summary_path = workspace / "outputs" / "summary.json"
    summary, sum_err = _load_json(summary_path)
    summary_ok = False
    if not sum_err and isinstance(summary, dict):
        keys_present = all(k in summary for k in ["considered_dates", "excluded_dates", "tz_offsets_used", "sources", "selected_slots"])
        if keys_present:
            considered = summary.get("considered_dates")
            sources = summary.get("sources")
            # sources must list the exact four paths (order-insensitive)
            expected_sources = {
                str(hol_fr_path.relative_to(workspace)) if hol_fr_path.is_absolute() else "web/holidays_FR_2025.json",
                str(hol_mx_path.relative_to(workspace)) if hol_mx_path.is_absolute() else "web/holidays_MX_2025.json",
                str(tz_paris_path.relative_to(workspace)) if tz_paris_path.is_absolute() else "web/time_offsets_Europe_Paris_2025-05-12_2025-05-16.json",
                str(tz_mex_path.relative_to(workspace)) if tz_mex_path.is_absolute() else "web/time_offsets_America_Mexico_City_2025-05-12_2025-05-16.json",
            }
            sources_set = set(sources) if isinstance(sources, list) else set()
            # considered_dates must equal the exact five weekdays from start to end
            if isinstance(considered, list) and considered == expected_dates and sources_set == expected_sources:
                scores["summary_json_structure_and_sources"] = 1.0
                summary_ok = True

    # Validate summary selected_slots match CSV proposals
    selected_match_ok = False
    if summary_ok and proposals_valid:
        sel = summary.get("selected_slots")
        if isinstance(sel, list) and len(sel) == 3:
            # Build comparable tuples
            def _row_to_key(r):
                return (
                    r.get("slot_id"),
                    r.get("date"),
                    r.get("utc_start"),
                    r.get("utc_end"),
                    r.get("america_mexico_city_start"),
                    r.get("america_mexico_city_end"),
                    r.get("europe_paris_start"),
                    r.get("europe_paris_end"),
                )
            csv_keys = set(_row_to_key(r["row"]) for r in parsed_proposals)
            sum_keys = set(_row_to_key(r) for r in sel if isinstance(r, dict))
            if csv_keys == sum_keys:
                scores["summary_selected_slots_match_csv"] = 1.0
                selected_match_ok = True

    # Validate summary tz_offsets_used matches web
    tz_used_ok = False
    if summary_ok and paris_ok and mex_ok:
        used = summary.get("tz_offsets_used")
        all_ok = isinstance(used, dict)
        if all_ok:
            for ds in expected_dates:
                ent = used.get(ds)
                if not isinstance(ent, dict):
                    all_ok = False
                    break
                p_val = _parse_offset_value_to_seconds(ent.get("Europe/Paris"))
                m_val = _parse_offset_value_to_seconds(ent.get("America/Mexico_City"))
                if p_val is None or m_val is None:
                    all_ok = False
                    break
                if paris_offsets.get(ds) != p_val or mex_offsets.get(ds) != m_val:
                    all_ok = False
                    break
        if all_ok:
            scores["summary_tz_offsets_match_web"] = 1.0
            tz_used_ok = True

    # Determinism: three earliest feasible slots across the week by UTC, using provided web offsets and attendees
    determinism_ok = False
    if proposals_valid and windows is not None and paris_ok and mex_ok and fr_ok and mx_ok:
        # Build zone_to_offsets for attendees
        z2o = {
            "Europe/Paris": paris_offsets,
            "America/Mexico_City": mex_offsets,
        }
        candidates = _generate_candidate_slots(start_date, end_date, windows, z2o, fr_holidays, mx_holidays)
        expected_three = candidates[:3]
        # Build comparable keys to minute precision
        expected_keys = [(c["date"], _normalize_to_minute(c["utc_start"]), _normalize_to_minute(c["utc_end"])) for c in expected_three]
        proposed_keys = [(p["date"].isoformat(), _normalize_to_minute(p["utc_start"]), _normalize_to_minute(p["utc_end"])) for p in parsed_proposals]
        if len(expected_keys) == 3 and expected_keys == proposed_keys:
            scores["determinism_three_earliest_slots_across_week"] = 1.0
            determinism_ok = True

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()