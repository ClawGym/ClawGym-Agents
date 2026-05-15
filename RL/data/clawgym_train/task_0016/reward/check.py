import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
        return rows
    except Exception:
        return None


def _time_to_minutes(t: str) -> Optional[int]:
    m = re.fullmatch(r"(\d{2}):(\d{2})", t)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def _detect_conflicts(schedule_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    conflicts = []
    by_date: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
    for idx, r in enumerate(schedule_rows):
        by_date.setdefault(r.get("date", ""), []).append((idx, r))

    for date, items in by_date.items():
        n = len(items)
        for i in range(n):
            for j in range(i + 1, n):
                _, a = items[i]
                _, b = items[j]
                sa = _time_to_minutes(a.get("start_time", ""))
                ea = _time_to_minutes(a.get("end_time", ""))
                sb = _time_to_minutes(b.get("start_time", ""))
                eb = _time_to_minutes(b.get("end_time", ""))
                if None in (sa, ea, sb, eb):
                    continue
                overlap = (sa < eb) and (ea > sb)
                if overlap:
                    conflicts.append({
                        "date": date,
                        "type": "overlap",
                        "event_a": {
                            "event_type": a.get("event_type", ""),
                            "project": a.get("project", ""),
                            "start_time": a.get("start_time", ""),
                            "end_time": a.get("end_time", ""),
                            "location_city": a.get("location_city", "")
                        },
                        "event_b": {
                            "event_type": b.get("event_type", ""),
                            "project": b.get("project", ""),
                            "start_time": b.get("start_time", ""),
                            "end_time": b.get("end_time", ""),
                            "location_city": b.get("location_city", "")
                        }
                    })
                else:
                    city_a = a.get("location_city", "")
                    city_b = b.get("location_city", "")
                    if city_a != city_b:
                        if sa <= sb:
                            earlier_end = ea
                            later_start = sb
                        else:
                            earlier_end = eb
                            later_start = sa
                        gap = later_start - earlier_end
                        if gap < 180:
                            conflicts.append({
                                "date": date,
                                "type": "tight_turnaround_diff_city",
                                "event_a": {
                                    "event_type": a.get("event_type", ""),
                                    "project": a.get("project", ""),
                                    "start_time": a.get("start_time", ""),
                                    "end_time": a.get("end_time", ""),
                                    "location_city": a.get("location_city", "")
                                },
                                "event_b": {
                                    "event_type": b.get("event_type", ""),
                                    "project": b.get("project", ""),
                                    "start_time": b.get("start_time", ""),
                                    "end_time": b.get("end_time", ""),
                                    "location_city": b.get("location_city", "")
                                }
                            })
    return conflicts


def _canonicalize_conflict(entry: Dict[str, Any]) -> Optional[Tuple[str, str, frozenset]]:
    try:
        dt = entry["date"]
        typ = entry["type"]
        ea = entry["event_a"]
        eb = entry["event_b"]
        rep_a = (ea["event_type"], ea["project"], ea["start_time"], ea["end_time"], ea["location_city"])
        rep_b = (eb["event_type"], eb["project"], eb["start_time"], eb["end_time"], eb["location_city"])
        return (dt, typ, frozenset([rep_a, rep_b]))
    except Exception:
        return None


def _required_event_fields_ok(event: Dict[str, Any]) -> bool:
    required = ["date", "start_time", "end_time", "event_type", "project", "location_city", "location_venue", "notes", "has_conflict"]
    for k in required:
        if k not in event:
            return False
    if not isinstance(event["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event["date"]):
        return False
    if not isinstance(event["start_time"], str) or not re.fullmatch(r"\d{2}:\d{2}", event["start_time"]):
        return False
    if not isinstance(event["end_time"], str) or not re.fullmatch(r"\d{2}:\d{2}", event["end_time"]):
        return False
    if not isinstance(event["has_conflict"], bool):
        return False
    return True


def _build_schedule_key(row: Dict[str, str]) -> Tuple[str, str, str, str, str, str, str, str]:
    return (
        row.get("date", ""),
        row.get("start_time", ""),
        row.get("end_time", ""),
        row.get("event_type", ""),
        row.get("project", ""),
        row.get("location_city", ""),
        row.get("location_venue", ""),
        row.get("notes", ""),
    )


def _group_pending_requests(media_requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in media_requests if str(r.get("status", "")).lower() == "pending"]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "upcoming_events_exists": 0.0,
        "upcoming_events_length": 0.0,
        "upcoming_events_fields": 0.0,
        "upcoming_events_conflict_flags_correct": 0.0,
        "conflicts_file_exists": 0.0,
        "conflicts_entries_correct": 0.0,
        "weekly_report_exists": 0.0,
        "weekly_report_has_headings": 0.0,
        "weekly_report_includes_date_range": 0.0,
        "weekly_report_pending_requests_listed": 0.0,
        "weekly_report_data_checks_no_unknown": 0.0,
        "publicist_email_exists": 0.0,
        "publicist_email_to_and_greeting": 0.0,
        "publicist_email_pending_actions": 0.0,
        "publicist_email_closing": 0.0,
        "agent_email_exists": 0.0,
        "agent_email_to_and_greeting": 0.0,
        "agent_email_conflicts_and_travel": 0.0,
        "agent_email_closing": 0.0,
    }

    input_dir = workspace / "input"
    schedule_path = input_dir / "schedule.csv"
    projects_path = input_dir / "projects.json"
    media_requests_path = input_dir / "media_requests.jsonl"
    contacts_path = input_dir / "contacts.json"

    schedule_rows = _safe_load_csv_dicts(schedule_path)
    projects_json = _safe_load_json(projects_path)
    media_requests = _safe_load_jsonl(media_requests_path)
    contacts = _safe_load_json(contacts_path)

    project_titles = set()
    if isinstance(projects_json, dict) and isinstance(projects_json.get("projects", None), list):
        for p in projects_json["projects"]:
            title = p.get("title")
            if isinstance(title, str):
                project_titles.add(title)

    expected_conflicts: Optional[List[Dict[str, Any]]] = None
    expected_has_conflict_map: Optional[Dict[Tuple[str, str, str, str, str, str, str, str], bool]] = None
    date_min = None
    date_max = None
    unknown_projects: Optional[List[Dict[str, str]]] = None

    if schedule_rows is not None:
        dates = [r.get("date", "") for r in schedule_rows if r.get("date", "")]
        if dates:
            try:
                date_min = min(dates)
                date_max = max(dates)
            except Exception:
                date_min = None
                date_max = None

        unknowns = []
        for r in schedule_rows:
            proj = r.get("project", "")
            if proj != "General" and proj not in project_titles:
                unknowns.append(r)
        unknown_projects = unknowns

        expected_conflicts = _detect_conflicts(schedule_rows)

        expected_has_conflict_map = {}
        for r in schedule_rows:
            k = _build_schedule_key(r)
            expected_has_conflict_map[k] = False
        if expected_conflicts is not None:
            for c in expected_conflicts:
                for role in ("event_a", "event_b"):
                    ev = c.get(role, {})
                    for r in schedule_rows:
                        if (r.get("date", "") == c.get("date", "")
                                and r.get("event_type", "") == ev.get("event_type", "")
                                and r.get("project", "") == ev.get("project", "")
                                and r.get("start_time", "") == ev.get("start_time", "")
                                and r.get("end_time", "") == ev.get("end_time", "")
                                and r.get("location_city", "") == ev.get("location_city", "")):
                            k = _build_schedule_key(r)
                            expected_has_conflict_map[k] = True
                            break

    out_events_path = workspace / "output" / "data" / "upcoming_events.json"
    out_conflicts_path = workspace / "output" / "data" / "conflicts.json"
    out_report_path = workspace / "output" / "reports" / "weekly_status.md"
    out_pub_email_path = workspace / "output" / "emails" / "publicist_email.txt"
    out_agent_email_path = workspace / "output" / "emails" / "agent_email.txt"

    out_events = _safe_load_json(out_events_path)
    if out_events is not None and isinstance(out_events, list):
        scores["upcoming_events_exists"] = 1.0
        if schedule_rows is not None and len(out_events) == len(schedule_rows):
            scores["upcoming_events_length"] = 1.0
        fields_ok = True
        for ev in out_events:
            if not isinstance(ev, dict) or not _required_event_fields_ok(ev):
                fields_ok = False
                break
        if fields_ok:
            scores["upcoming_events_fields"] = 1.0
        if expected_has_conflict_map is not None:
            match_counts: Dict[Tuple[str, str, str, str, str, str, str, str], int] = {}
            match_flags: Dict[Tuple[str, str, str, str, str, str, str, str], bool] = {}
            for ev in out_events:
                if not isinstance(ev, dict):
                    continue
                k = (
                    str(ev.get("date", "")),
                    str(ev.get("start_time", "")),
                    str(ev.get("end_time", "")),
                    str(ev.get("event_type", "")),
                    str(ev.get("project", "")),
                    str(ev.get("location_city", "")),
                    str(ev.get("location_venue", "")),
                    str(ev.get("notes", "")),
                )
                match_counts[k] = match_counts.get(k, 0) + 1
                match_flags[k] = bool(ev.get("has_conflict", False))
            flags_ok = True
            for k, expected_flag in expected_has_conflict_map.items():
                if match_counts.get(k, 0) != 1:
                    flags_ok = False
                    break
                actual_flag = match_flags.get(k, None)
                if actual_flag is None or bool(actual_flag) != bool(expected_flag):
                    flags_ok = False
                    break
            if flags_ok:
                scores["upcoming_events_conflict_flags_correct"] = 1.0

    out_conflicts = _safe_load_json(out_conflicts_path)
    if out_conflicts is not None and isinstance(out_conflicts, list):
        scores["conflicts_file_exists"] = 1.0
        if expected_conflicts is not None:
            expected_set = set()
            for c in expected_conflicts:
                can = _canonicalize_conflict(c)
                if can is not None:
                    expected_set.add(can)
            actual_set = set()
            structure_ok = True
            for entry in out_conflicts:
                if not isinstance(entry, dict):
                    structure_ok = False
                    break
                if "date" not in entry or "type" not in entry or "event_a" not in entry or "event_b" not in entry:
                    structure_ok = False
                    break
                if entry.get("type") not in ("overlap", "tight_turnaround_diff_city"):
                    structure_ok = False
                    break
                can = _canonicalize_conflict(entry)
                if can is None:
                    structure_ok = False
                    break
                actual_set.add(can)
            if structure_ok and actual_set == expected_set:
                scores["conflicts_entries_correct"] = 1.0

    report_text = _safe_read_text(out_report_path)
    if isinstance(report_text, str):
        scores["weekly_report_exists"] = 1.0
        text_lower = report_text.lower()
        headings_required = ["overview", "agenda by date", "conflicts", "pending media requests", "data checks"]
        if all(h in text_lower for h in headings_required):
            scores["weekly_report_has_headings"] = 1.0
        if date_min and date_max:
            if (date_min in report_text) and (date_max in report_text):
                scores["weekly_report_includes_date_range"] = 1.0
        pending_listed_ok = False
        if media_requests is not None:
            pending = _group_pending_requests(media_requests)
            if all(str(item.get("outlet", "")) in report_text for item in pending):
                pending_listed_ok = True
        if pending_listed_ok:
            scores["weekly_report_pending_requests_listed"] = 1.0
        if unknown_projects is not None and len(unknown_projects) == 0:
            if "no unknown projects" in text_lower:
                scores["weekly_report_data_checks_no_unknown"] = 1.0

    pub_text = _safe_read_text(out_pub_email_path)
    if isinstance(pub_text, str):
        scores["publicist_email_exists"] = 1.0
        lines = [ln.strip() for ln in pub_text.splitlines() if ln.strip() != ""]
        first_nonempty = lines[0] if lines else ""
        to_greeting_ok = False
        contacts = _safe_load_json(contacts_path)
        if contacts and isinstance(contacts.get("publicist", None), dict):
            pub_name = contacts["publicist"].get("name", "")
            pub_email = contacts["publicist"].get("email", "")
            if first_nonempty.lower().startswith("to:") and (pub_email in first_nonempty):
                greet_found = any((pub_name in ln) or (pub_name.split()[0] in ln) for ln in lines[0:3])
                if greet_found:
                    to_greeting_ok = True
        if to_greeting_ok:
            scores["publicist_email_to_and_greeting"] = 1.0
        actions_ok = False
        if media_requests is not None:
            pending = _group_pending_requests(media_requests)
            overlaps_map: Dict[str, bool] = {}
            if schedule_rows is not None:
                for req in pending:
                    outlet = req.get("outlet", "")
                    rdate = req.get("requested_date", "")
                    rs = req.get("requested_start", "")
                    re = req.get("requested_end", "")
                    rs_min = _time_to_minutes(rs) if isinstance(rs, str) else None
                    re_min = _time_to_minutes(re) if isinstance(re, str) else None
                    ov = False
                    if rs_min is not None and re_min is not None:
                        for r in schedule_rows:
                            if r.get("date", "") != rdate:
                                continue
                            es = _time_to_minutes(r.get("start_time", ""))
                            ee = _time_to_minutes(r.get("end_time", ""))
                            if None in (es, ee):
                                continue
                            if rs_min < ee and re_min > es:
                                ov = True
                                break
                    overlaps_map[outlet] = ov
            found_all = True
            for req in pending:
                outlet = req.get("outlet", "")
                ov = overlaps_map.get(outlet, None)
                related_lines = [ln for ln in lines if outlet in ln]
                if not related_lines:
                    found_all = False
                    break
                if ov is True:
                    if not any("propose alternate window" in ln.lower() or "propose alternate" in ln.lower() for ln in related_lines):
                        found_all = False
                        break
                elif ov is False:
                    if not any("confirm" in ln.lower() for ln in related_lines):
                        found_all = False
                        break
                else:
                    found_all = False
                    break
            if found_all:
                actions_ok = True
        if actions_ok:
            scores["publicist_email_pending_actions"] = 1.0
        if "– [your name]" in pub_text.lower() or "- [your name]" in pub_text.lower():
            scores["publicist_email_closing"] = 1.0

    agent_text = _safe_read_text(out_agent_email_path)
    if isinstance(agent_text, str):
        scores["agent_email_exists"] = 1.0
        lines = [ln.strip() for ln in agent_text.splitlines() if ln.strip() != ""]
        first_nonempty = lines[0] if lines else ""
        to_greeting_ok = False
        contacts = _safe_load_json(contacts_path)
        if contacts and isinstance(contacts.get("agent", None), dict):
            agent_name = contacts["agent"].get("name", "")
            agent_email = contacts["agent"].get("email", "")
            if first_nonempty.lower().startswith("to:") and (agent_email in first_nonempty):
                greet_found = any((agent_name in ln) or (agent_name.split()[0] in ln) for ln in lines[0:3])
                if greet_found:
                    to_greeting_ok = True
        if to_greeting_ok:
            scores["agent_email_to_and_greeting"] = 1.0
        conflicts_travel_ok = False
        expected_conflict_dates = set()
        if schedule_rows is not None:
            expected_conflicts_calc = _detect_conflicts(schedule_rows)
            for c in expected_conflicts_calc:
                expected_conflict_dates.add(c.get("date", ""))
        has_conflict_mentions = True
        if expected_conflict_dates:
            for d in expected_conflict_dates:
                if d and d not in agent_text:
                    has_conflict_mentions = False
                    break
        else:
            has_conflict_mentions = False
        travel_mention = ("flight" in agent_text.lower()) or ("travel" in agent_text.lower())
        if has_conflict_mentions and travel_mention:
            conflicts_travel_ok = True
        if conflicts_travel_ok:
            scores["agent_email_conflicts_and_travel"] = 1.0
        if "– [your name]" in agent_text.lower() or "- [your name]" in agent_text.lower():
            scores["agent_email_closing"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()