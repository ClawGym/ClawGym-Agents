import sys
import json
import csv
import re
from math import ceil, isclose
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # Fallback handled below


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
        return dt
    except Exception:
        return None


def _slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-{2,}', '-', s)
    s = s.strip('-')
    return s


def _get_tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    # Fallback: assume ET for the specific window which is -04:00 in Oct 2024
    return timezone(timedelta(hours=-4))


def _parse_availability_yaml(text: str) -> Optional[dict]:
    # Minimal parser for the provided simple YAML structure
    tz = None
    window_start = None
    window_end = None
    availability: Dict[str, List[Tuple[str, str]]] = {}
    mode = None
    current_day = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if mode is None:
            m = re.match(r'^\s*timezone:\s*(.+)\s*$', line)
            if m:
                tz = m.group(1).strip()
                continue
            m = re.match(r'^\s*window_start:\s*(.+)\s*$', line)
            if m:
                window_start = m.group(1).strip()
                continue
            m = re.match(r'^\s*window_end:\s*(.+)\s*$', line)
            if m:
                window_end = m.group(1).strip()
                continue
            if re.match(r'^\s*availability:\s*$', line):
                mode = 'availability'
                continue
        elif mode == 'availability':
            mday = re.match(r'^\s{2}([A-Za-z]+):\s*$', line)
            if mday:
                current_day = mday.group(1)
                availability[current_day] = []
                continue
            mslot = re.match(r'^\s{4}-\s*"?(\d{2}:\d{2})-(\d{2}:\d{2})"?\s*$', line)
            if mslot and current_day:
                start_t, end_t = mslot.group(1), mslot.group(2)
                availability[current_day].append((start_t, end_t))
                continue
            # ignore other lines
    if tz is None or window_start is None or window_end is None or not availability:
        return None
    return {
        "timezone": tz,
        "window_start": window_start,
        "window_end": window_end,
        "availability": availability,
    }


def _weekday_name(d: date) -> str:
    # Monday, Tuesday...
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][d.weekday()]


def _build_availability_windows(tz, window_start: date, window_end: date, weekly: Dict[str, List[Tuple[str, str]]]) -> Dict[date, List[Tuple[datetime, datetime]]]:
    windows: Dict[date, List[Tuple[datetime, datetime]]] = {}
    current = window_start
    one_day = timedelta(days=1)
    while current <= window_end:
        name = _weekday_name(current)
        slots = weekly.get(name, [])
        day_windows: List[Tuple[datetime, datetime]] = []
        for st_str, en_str in slots:
            st_parts = [int(x) for x in st_str.split(":")]
            en_parts = [int(x) for x in en_str.split(":")]
            st_dt = datetime.combine(current, time(st_parts[0], st_parts[1]), tzinfo=tz)
            en_dt = datetime.combine(current, time(en_parts[0], en_parts[1]), tzinfo=tz)
            day_windows.append((st_dt, en_dt))
        windows[current] = day_windows
        current = current + one_day
    return windows


def _parse_newsletter(html: str) -> List[Tuple[str, str]]:
    # returns list of (title, iso_str)
    items = []
    # Regex for rows with class="drop" and capture title and data-iso
    pattern = re.compile(
        r'<tr\s+class="drop"[^>]*>.*?<td\s+class="title"\s*>(.*?)</td>.*?<td\s+class="datetime"[^>]*data-iso="([^"]+)"[^>]*>.*?</td>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
        iso = m.group(2).strip()
        items.append((title, iso))
    return items


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    # half-open intervals [start, end)
    latest_start = a_start if a_start >= b_start else b_start
    earliest_end = a_end if a_end <= b_end else b_end
    return earliest_end > latest_start


def _within_window(dt: datetime, window_start_dt: datetime, window_end_dt: datetime) -> bool:
    return (dt >= window_start_dt) and (dt <= window_end_dt)


def _event_within_availability(start: datetime, end: datetime, availability_by_date: Dict[date, List[Tuple[datetime, datetime]]], tz) -> bool:
    # Must be fully within a single availability window on the same local date
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    if local_start.date() != local_end.date():
        return False
    slots = availability_by_date.get(local_start.date(), [])
    for s, e in slots:
        if local_start >= s and local_end <= e:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "merged_schedule_exists_and_schema": 0.0,
        "sources_and_ref_ids_valid": 0.0,
        "times_timezone_aware_and_within_window": 0.0,
        "non_deadline_within_availability": 0.0,
        "no_overlaps_across_events": 0.0,
        "assignment_blocks_one_hour_and_count": 0.0,
        "assignment_last_block_before_due": 0.0,
        "deadlines_present_and_exact": 0.0,
        "releases_watch_blocks_one_hour_and_within_48h": 0.0,
        "release_starts_align_when_available": 0.0,
        "summary_json_consistency": 0.0,
        "validation_report_present_and_consistent": 0.0,
    }

    # Load inputs
    assignments_path = workspace / "input" / "assignments.csv"
    newsletter_path = workspace / "input" / "fan_newsletter.html"
    availability_path = workspace / "input" / "availability.yaml"

    assignments_csv = _safe_read_csv(assignments_path)
    newsletter_html = _safe_read_text(newsletter_path)
    availability_text = _safe_read_text(availability_path)

    # Baseline parse of inputs; if any missing/malformed, many checks will fail gracefully
    assignments: List[dict] = []
    assignments_by_id: Dict[str, dict] = {}
    tzname = "America/New_York"
    tz = _get_tz(tzname)
    window_start_date = None
    window_end_date = None
    availability_by_date: Dict[date, List[Tuple[datetime, datetime]]] = {}

    if availability_text is not None:
        av = _parse_availability_yaml(availability_text)
        if av:
            tzname = av["timezone"]
            tz = _get_tz(tzname)
            try:
                window_start_date = datetime.fromisoformat(av["window_start"]).date()
                window_end_date = datetime.fromisoformat(av["window_end"]).date()
            except Exception:
                window_start_date = None
                window_end_date = None
            if window_start_date and window_end_date:
                availability_by_date = _build_availability_windows(tz, window_start_date, window_end_date, av["availability"])

    if assignments_csv is not None:
        headers, rows = assignments_csv
        # Expect columns assignment_id,course,assignment,due_at,estimate_hours
        for r in rows:
            try:
                aid = r["assignment_id"].strip()
                course = r["course"].strip()
                aname = r["assignment"].strip()
                due = _parse_iso_dt(r["due_at"].strip())
                est = float(r["estimate_hours"].strip())
                if not aid or due is None:
                    continue
                obj = {"assignment_id": aid, "course": course, "assignment": aname, "due_at": due, "estimate_hours": est}
                assignments.append(obj)
                assignments_by_id[aid] = obj
            except Exception:
                continue

    releases: List[dict] = []
    if newsletter_html is not None:
        items = _parse_newsletter(newsletter_html)
        for title, iso in items:
            dt = _parse_iso_dt(iso)
            if dt is None:
                continue
            releases.append({"title": title, "release_at": dt, "slug": _slugify(title)})

    # Define window start and end datetimes (inclusive)
    window_start_dt = None
    window_end_dt = None
    if window_start_date and window_end_date:
        window_start_dt = datetime.combine(window_start_date, time(0, 0), tzinfo=tz)
        # inclusive end: 23:59:59.999999
        window_end_dt = datetime.combine(window_end_date, time(23, 59, 59, 999999), tzinfo=tz)

    # Load outputs
    merged_path = workspace / "output" / "merged_schedule.csv"
    summary_path = workspace / "output" / "summary.json"
    validation_path = workspace / "output" / "validation_report.json"

    merged_csv = _safe_read_csv(merged_path)

    # Prepare structures for evaluation
    merged_ok = False
    events: List[dict] = []
    schema_ok = False
    sources_ok = False
    tz_and_window_ok = False
    availability_ok = False
    overlaps_ok = False
    assignment_blocks_ok = False
    assignment_last_block_ok = False
    deadlines_ok = False
    releases_blocks_ok = False
    release_align_ok = False
    summary_ok = False
    validation_ok = False

    # Parse merged schedule
    if merged_csv is not None:
        headers, rows = merged_csv
        expected_headers = ["start_iso", "end_iso", "title", "source", "ref_id", "notes"]
        schema_ok = headers == expected_headers
        # Build event list if schema ok
        if schema_ok:
            parse_fail = False
            for r in rows:
                s = r.get("start_iso", "")
                e = r.get("end_iso", "")
                title = (r.get("title") or "").strip()
                source = (r.get("source") or "").strip()
                ref_id = (r.get("ref_id") or "").strip()
                notes = (r.get("notes") or "")
                sd = _parse_iso_dt(s.strip())
                ed = _parse_iso_dt(e.strip())
                if sd is None or ed is None:
                    parse_fail = True
                    break
                events.append({
                    "start": sd,
                    "end": ed,
                    "title": title,
                    "source": source,
                    "ref_id": ref_id,
                    "notes": notes,
                })
            merged_ok = not parse_fail

    # Evaluate events if we parsed them
    if merged_ok and events and window_start_dt and window_end_dt and availability_by_date:
        # Check sources and ref_ids validity
        valid_sources = {"assignment_work", "release_watch", "deadline"}
        sources_ok = True
        for ev in events:
            if ev["source"] not in valid_sources:
                sources_ok = False
                break
            if ev["source"] == "assignment_work":
                # ref_id must be assignment id
                if ev["ref_id"] not in assignments_by_id:
                    sources_ok = False
                    break
            elif ev["source"] == "release_watch":
                # ref_id should be slug of some release title
                slug = ev["ref_id"]
                if slug not in {r["slug"] for r in releases}:
                    sources_ok = False
                    break
            elif ev["source"] == "deadline":
                # ref_id must be assignment id
                if ev["ref_id"] not in assignments_by_id:
                    sources_ok = False
                    break

        # Times timezone-aware and within window
        tz_and_window_ok = True
        for ev in events:
            sd = ev["start"]
            ed = ev["end"]
            # timezone-aware
            if sd.tzinfo is None or ed.tzinfo is None:
                tz_and_window_ok = False
                break
            # start <= end
            if ed < sd:
                tz_and_window_ok = False
                break
            # All events should be within the date window (inclusive)
            if not _within_window(sd, window_start_dt, window_end_dt) or not _within_window(ed, window_start_dt, window_end_dt):
                tz_and_window_ok = False
                break

        # Non-deadline events within availability
        availability_ok = True
        for ev in events:
            if ev["source"] == "deadline":
                continue
            if not _event_within_availability(ev["start"], ev["end"], availability_by_date, tz):
                availability_ok = False
                break

        # No overlaps across all scheduled items (treat as half-open)
        overlaps_ok = True
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                a = events[i]
                b = events[j]
                if _overlap(a["start"], a["end"], b["start"], b["end"]):
                    overlaps_ok = False
                    break
            if not overlaps_ok:
                break

        # Assignment blocks: one-hour and count >= ceil(estimate)
        assignment_blocks_ok = True
        assignment_last_block_ok = True
        deadlines_ok = True

        # Build index mappings
        assign_work_by_id: Dict[str, List[dict]] = {}
        deadline_by_id: Dict[str, List[dict]] = {}
        for ev in events:
            if ev["source"] == "assignment_work":
                assign_work_by_id.setdefault(ev["ref_id"], []).append(ev)
            elif ev["source"] == "deadline":
                deadline_by_id.setdefault(ev["ref_id"], []).append(ev)

        for a in assignments:
            aid = a["assignment_id"]
            due = a["due_at"]
            est = a["estimate_hours"]
            blocks = assign_work_by_id.get(aid, [])
            # Check count
            needed_blocks = ceil(est)
            if len(blocks) < needed_blocks:
                assignment_blocks_ok = False
            # Check each block duration is exactly 60 minutes
            for b in blocks:
                dur = (b["end"] - b["start"]).total_seconds()
                if not isclose(dur, 3600.0, rel_tol=0, abs_tol=0.5):
                    assignment_blocks_ok = False
                    break
            # Check last block end <= due_at - 120 minutes
            if blocks:
                last_end = max(b["end"] for b in blocks)
                if last_end > (due - timedelta(minutes=120)):
                    assignment_last_block_ok = False
            else:
                assignment_last_block_ok = False
            # Check deadline event present exact at due_at with zero duration
            dls = deadline_by_id.get(aid, [])
            # Must have at least one; require exactly one with start==end==due
            found_exact = False
            for dlev in dls:
                if dlev["start"] == due and dlev["end"] == due:
                    found_exact = True
                    break
            if not found_exact:
                deadlines_ok = False

        # Releases: exactly one 60-min watch block within 48h of release time, aligned if available
        releases_blocks_ok = True
        release_align_ok = True

        # Map release slug to release info for in-window releases
        in_window_releases = []
        if window_start_dt and window_end_dt:
            for r in releases:
                if _within_window(r["release_at"], window_start_dt, window_end_dt):
                    in_window_releases.append(r)

        watch_by_slug: Dict[str, List[dict]] = {}
        for ev in events:
            if ev["source"] == "release_watch":
                watch_by_slug.setdefault(ev["ref_id"], []).append(ev)

        for r in in_window_releases:
            slug = r["slug"]
            rel_t = r["release_at"]
            watches = watch_by_slug.get(slug, [])
            # Exactly one
            if len(watches) != 1:
                releases_blocks_ok = False
                continue
            w = watches[0]
            # Duration 60
            if not isclose((w["end"] - w["start"]).total_seconds(), 3600.0, rel_tol=0, abs_tol=0.5):
                releases_blocks_ok = False
            # Within 48 hours after release
            if w["start"] < rel_t or w["end"] > (rel_t + timedelta(hours=48)):
                releases_blocks_ok = False
            # Align if release time itself is within availability for a full hour
            align_needed = False
            local_rel = rel_t.astimezone(tz)
            rel_day_slots = availability_by_date.get(local_rel.date(), [])
            for s, e in rel_day_slots:
                if local_rel >= s and (local_rel + timedelta(hours=1)) <= e:
                    align_needed = True
                    break
            if align_needed:
                if w["start"] != rel_t:
                    release_align_ok = False

    # Set initial scores from above checks
    if merged_ok and schema_ok:
        scores["merged_schedule_exists_and_schema"] = 1.0
    if sources_ok and merged_ok and schema_ok:
        scores["sources_and_ref_ids_valid"] = 1.0
    if tz_and_window_ok and merged_ok and schema_ok and window_start_dt and window_end_dt:
        scores["times_timezone_aware_and_within_window"] = 1.0
    if availability_ok and merged_ok and schema_ok:
        scores["non_deadline_within_availability"] = 1.0
    if overlaps_ok and merged_ok and schema_ok:
        scores["no_overlaps_across_events"] = 1.0
    if assignment_blocks_ok and merged_ok and schema_ok and assignments:
        scores["assignment_blocks_one_hour_and_count"] = 1.0
    if assignment_last_block_ok and merged_ok and schema_ok and assignments:
        scores["assignment_last_block_before_due"] = 1.0
    if deadlines_ok and merged_ok and schema_ok and assignments:
        scores["deadlines_present_and_exact"] = 1.0
    if releases_blocks_ok and merged_ok and schema_ok and releases:
        scores["releases_watch_blocks_one_hour_and_within_48h"] = 1.0
    if release_align_ok and merged_ok and schema_ok and releases:
        scores["release_starts_align_when_available"] = 1.0

    # Summary JSON consistency
    summary_json = _safe_read_json(summary_path)
    if summary_json is not None and merged_ok and schema_ok:
        try:
            # Expected keys
            has_keys = all(k in summary_json for k in ["total_events", "total_hours", "hours_by_source", "events_by_day", "unmet_constraints"])
            if has_keys:
                # Recompute metrics from events
                total_events = len(events)
                total_hours = sum(max(0.0, (ev["end"] - ev["start"]).total_seconds() / 3600.0) for ev in events)
                hours_by_source = {"assignment_work": 0.0, "release_watch": 0.0, "deadline": 0.0}
                for ev in events:
                    dur = max(0.0, (ev["end"] - ev["start"]).total_seconds() / 3600.0)
                    if ev["source"] in hours_by_source:
                        hours_by_source[ev["source"]] += dur
                # events_by_day by local date from start
                events_by_day: Dict[str, int] = {}
                for ev in events:
                    dstr = ev["start"].astimezone(tz).date().isoformat()
                    events_by_day[dstr] = events_by_day.get(dstr, 0) + 1

                # Check unmet_constraints: if our critical checks all pass, expect empty; else expect non-empty
                our_constraints_pass = (scores["non_deadline_within_availability"] == 1.0 and
                                        scores["assignment_blocks_one_hour_and_count"] == 1.0 and
                                        scores["assignment_last_block_before_due"] == 1.0 and
                                        scores["releases_watch_blocks_one_hour_and_within_48h"] == 1.0 and
                                        scores["no_overlaps_across_events"] == 1.0)
                unmet_list = summary_json.get("unmet_constraints", [])
                unmet_ok = isinstance(unmet_list, list)
                if our_constraints_pass:
                    unmet_ok = unmet_ok and (len(unmet_list) == 0)
                else:
                    unmet_ok = unmet_ok and (len(unmet_list) >= 1)

                # Compare numbers with tolerance for floats
                numbers_ok = (
                    summary_json.get("total_events") == total_events and
                    isclose(float(summary_json.get("total_hours", -1.0)), total_hours, rel_tol=1e-6, abs_tol=1e-6)
                )
                hbs = summary_json.get("hours_by_source", {})
                hours_ok = all(
                    isclose(float(hbs.get(k, -1.0)), hours_by_source[k], rel_tol=1e-6, abs_tol=1e-6)
                    for k in ["assignment_work", "release_watch", "deadline"]
                )
                ebd = summary_json.get("events_by_day", {})
                ebd_ok = isinstance(ebd, dict) and all(ebd.get(k, 0) == v for k, v in events_by_day.items()) and all(
                    k in events_by_day for k in ebd.keys()
                )
                if numbers_ok and hours_ok and ebd_ok and unmet_ok:
                    summary_ok = True
        except Exception:
            summary_ok = False

    if summary_ok:
        scores["summary_json_consistency"] = 1.0

    # Validation report presence and consistency
    validation_json = _safe_read_json(validation_path)
    if validation_json is not None and merged_ok and schema_ok:
        try:
            # Accept either 'passed' bool or 'status' with 'pass'/'fail'; and 'issues' list
            issues = validation_json.get("issues")
            passed = None
            if isinstance(validation_json.get("passed"), bool):
                passed = validation_json.get("passed")
            elif isinstance(validation_json.get("status"), str):
                st = validation_json.get("status").lower().strip()
                if st in ("pass", "passed", "ok", "success"):
                    passed = True
                elif st in ("fail", "failed", "error"):
                    passed = False
            has_min_fields = isinstance(issues, list) and (passed is not None)
            if has_min_fields:
                # Our recomputed constraints pass/fail
                our_constraints_pass = (scores["non_deadline_within_availability"] == 1.0 and
                                        scores["assignment_blocks_one_hour_and_count"] == 1.0 and
                                        scores["assignment_last_block_before_due"] == 1.0 and
                                        scores["releases_watch_blocks_one_hour_and_within_48h"] == 1.0 and
                                        scores["no_overlaps_across_events"] == 1.0)
                if our_constraints_pass:
                    if passed is True and len(issues) == 0:
                        validation_ok = True
                else:
                    if passed is False or len(issues) > 0:
                        validation_ok = True
        except Exception:
            validation_ok = False

    if validation_ok:
        scores["validation_report_present_and_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()