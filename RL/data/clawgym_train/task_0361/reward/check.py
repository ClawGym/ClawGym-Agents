import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_jsonl(path: Path):
    items = []
    try:
        text = _read_text(path)
        if text is None:
            return None
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                return None
            items.append(obj)
        return items
    except Exception:
        return None


def _load_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_availability_yaml(text: str):
    """
    Minimal parser tailored for the given YAML structure.
    Returns dict with keys: timezone (str), week_start_date (str),
    windows (dict day->list of (start,end)),
    rules (dict with max_posts, min_research_sessions).
    """
    if not text:
        return None
    timezone = None
    week_start_date = None
    windows = {}
    rules = {}
    lines = text.splitlines()
    i = 0
    in_windows = False
    in_rules = False
    current_day = None
    while i < len(lines):
        line = lines[i].rstrip()
        if "#" in line:
            line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            i += 1
            continue
        m_tz = re.match(r'^\s*timezone:\s*"(.*?)"\s*$', line)
        if m_tz:
            timezone = m_tz.group(1)
            i += 1
            continue
        m_wsd = re.match(r'^\s*week_start_date:\s*"(.*?)"\s*$', line)
        if m_wsd:
            week_start_date = m_wsd.group(1)
            i += 1
            continue
        if re.match(r'^\s*windows:\s*$', line):
            in_windows = True
            in_rules = False
            current_day = None
            i += 1
            continue
        if re.match(r'^\s*rules:\s*$', line):
            in_rules = True
            in_windows = False
            current_day = None
            i += 1
            continue

        if in_windows:
            md = re.match(r'^\s{2}([A-Za-z]+):\s*(\[\])?\s*$', line)
            if md:
                current_day = md.group(1)
                windows[current_day] = []
                i += 1
                while i < len(lines):
                    l2 = lines[i].rstrip()
                    if "#" in l2:
                        l2 = l2.split("#", 1)[0].rstrip()
                    if re.match(r'^\s{2}[A-Za-z]+:', l2) or re.match(r'^\s*\w+:', l2):
                        break
                    m_item = re.match(r'^\s{4}-\s*"?(\d{1,2}:\d{2})-(\d{1,2}:\d{2})"?\s*$', l2)
                    if m_item:
                        windows[current_day].append((m_item.group(1), m_item.group(2)))
                        i += 1
                        continue
                    if l2.strip() == "":
                        i += 1
                        continue
                    break
                continue
            else:
                i += 1
                continue

        if in_rules:
            m_mp = re.match(r'^\s{2}max_posts:\s*(\d+)\s*$', line)
            if m_mp:
                rules["max_posts"] = int(m_mp.group(1))
                i += 1
                continue
            m_mr = re.match(r'^\s{2}min_research_sessions:\s*(\d+)\s*$', line)
            if m_mr:
                rules["min_research_sessions"] = int(m_mr.group(1))
                i += 1
                continue
            i += 1
            continue

        i += 1

    if timezone is None or week_start_date is None or not windows or not rules:
        return None
    return {
        "timezone": timezone,
        "week_start_date": week_start_date,
        "windows": windows,
        "rules": rules,
    }


def _compute_week_dates(week_start_date_str: str):
    try:
        start = datetime.strptime(week_start_date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    mapping = {}
    for idx, name in enumerate(day_names):
        d = start + timedelta(days=idx)
        mapping[name] = d.isoformat()
    return mapping


def _time_to_minutes(t: str):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _minutes_between(start: str, end: str):
    return _time_to_minutes(end) - _time_to_minutes(start)


def _load_topics(path: Path):
    items = _load_jsonl(path)
    if items is None:
        return None
    topics = {}
    for obj in items:
        try:
            tid = obj["id"]
            title = obj["title"]
            tags = obj["tags"]
            eta = int(obj["eta_minutes"])
            needs_research = bool(obj.get("needs_research", False))
            if not isinstance(tags, list):
                return None
        except Exception:
            return None
        topics[tid] = {
            "id": tid,
            "title": title,
            "tags": tags,
            "eta_minutes": eta,
            "needs_research": needs_research,
        }
    return topics


def _load_priorities(path: Path):
    data = _load_json(path)
    if data is None:
        return None
    try:
        emphasize = data.get("emphasize_tags", [])
        deprioritize = data.get("deprioritize_tags", [])
        if not isinstance(emphasize, list) or not isinstance(deprioritize, list):
            return None
        return {"emphasize_tags": set(emphasize), "deprioritize_tags": set(deprioritize)}
    except Exception:
        return None


def _load_targets(path: Path):
    header, rows = _load_csv(path)
    if header is None or rows is None:
        return None
    required_cols = {"target_id", "name", "keywords", "type"}
    if set(header) != required_cols:
        if not required_cols.issubset(set(header)):
            return None
    result = {}
    for r in rows:
        tid = r.get("target_id")
        if not tid:
            return None
        result[tid] = {
            "target_id": tid,
            "name": r.get("name", ""),
            "keywords": r.get("keywords", ""),
            "type": r.get("type", ""),
        }
    return result


def _parse_calendar_csv(path: Path):
    header, rows = _load_csv(path)
    if header is None or rows is None:
        return None, None
    expected_header = ["date", "start_time_local", "end_time_local", "slot_type", "ref_id", "title", "tags", "eta_minutes", "notes"]
    if header != expected_header:
        return None, None
    return header, rows


def _iso_parse(ts: str):
    try:
        if ts.endswith("Z"):
            ts_mod = ts[:-1] + "+00:00"
        else:
            ts_mod = ts
        datetime.fromisoformat(ts_mod)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "calendar_exists_and_columns": 0.0,
        "calendar_windows_coverage_exact": 0.0,
        "calendar_chronological_order": 0.0,
        "calendar_slot_types_valid": 0.0,
        "calendar_posts_constraints": 0.0,
        "calendar_research_minimum_and_targets_valid": 0.0,
        "preference_emphasize_tags_respected": 0.0,
        "maintenance_slots_valid": 0.0,
        "needs_research_note_present": 0.0,
        "research_log_exists_and_schema": 0.0,
        "research_log_per_target_queries_and_domains": 0.0,
        "research_log_timestamp_format": 0.0,
        "status_update_exists": 0.0,
        "status_update_inputs_listed": 0.0,
        "status_update_counts_correct": 0.0,
        "status_update_posts_listed_with_details": 0.0,
        "status_update_research_focus_matches_log_and_no_urls": 0.0,
        "status_update_next_steps_mentions_unscheduled": 0.0,
    }

    availability_path = workspace / "input" / "availability.yaml"
    topics_path = workspace / "input" / "topics.jsonl"
    priorities_path = workspace / "input" / "priorities.json"
    targets_path = workspace / "input" / "research_targets.csv"

    availability_text = _read_text(availability_path)
    availability = _parse_availability_yaml(availability_text) if availability_text else None
    topics = _load_topics(topics_path)
    priorities = _load_priorities(priorities_path)
    targets = _load_targets(targets_path)

    calendar_path = workspace / "outputs" / "schedule" / "calendar.csv"
    research_log_path = workspace / "outputs" / "research" / "research_log.jsonl"
    status_update_path = workspace / "outputs" / "status_update.md"

    cal_header, cal_rows = _parse_calendar_csv(calendar_path)
    if cal_header is not None and cal_rows is not None:
        scores["calendar_exists_and_columns"] = 1.0

    expected_windows = []
    date_map = None
    rules = None
    if availability:
        date_map = _compute_week_dates(availability.get("week_start_date", ""))
        rules = availability.get("rules", {})
        if date_map:
            day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            for day in day_order:
                day_date = date_map.get(day)
                for w in availability["windows"].get(day, []):
                    expected_windows.append((day_date, w[0], w[1]))

    if cal_rows is not None and expected_windows:
        cal_windows = [(r["date"], r["start_time_local"], r["end_time_local"]) for r in cal_rows]
        if set(cal_windows) == set(expected_windows) and len(cal_windows) == len(expected_windows):
            scores["calendar_windows_coverage_exact"] = 1.0

        expected_order = sorted(expected_windows, key=lambda x: (x[0], x[1]))
        if cal_windows == expected_order:
            scores["calendar_chronological_order"] = 1.0

        valid_slot_types = {"post", "research", "maintenance"}
        slot_types_valid = True
        maintenance_valid = True
        needs_research_note_ok = True
        for r in cal_rows:
            if r["slot_type"] not in valid_slot_types:
                slot_types_valid = False
                break
            if r["slot_type"] == "post":
                try:
                    eta_val = int(r["eta_minutes"])
                    if eta_val <= 0:
                        slot_types_valid = False
                        break
                except Exception:
                    slot_types_valid = False
                    break
                if r["tags"].strip() in {"", "-"}:
                    slot_types_valid = False
                    break
            else:
                if r["eta_minutes"] != "-":
                    slot_types_valid = False
                    break
                if r["tags"].strip() not in {"", "-"}:
                    slot_types_valid = False
                    break

            if r["slot_type"] == "maintenance" and topics is not None:
                tid = r.get("ref_id", "")
                t = topics.get(tid)
                if not t or "maintenance" not in t.get("tags", []):
                    maintenance_valid = False

            if r["slot_type"] == "post" and topics is not None:
                tid = r.get("ref_id", "")
                t = topics.get(tid)
                if t and t.get("needs_research", False):
                    note = (r.get("notes") or "").lower()
                    if "research" not in note:
                        needs_research_note_ok = False

        if slot_types_valid:
            scores["calendar_slot_types_valid"] = 1.0
        if maintenance_valid:
            scores["maintenance_slots_valid"] = 1.0
        if needs_research_note_ok:
            scores["needs_research_note_present"] = 1.0

    if cal_rows is not None and availability and expected_windows and topics:
        posts = [r for r in cal_rows if r["slot_type"] == "post"]
        unique_ids = set(r["ref_id"] for r in posts)
        all_unique = len(unique_ids) == len(posts)
        max_posts_ok = True
        if rules and "max_posts" in rules:
            max_posts_ok = len(posts) <= rules["max_posts"]
        fit_ok = True
        for r in posts:
            window_len = _minutes_between(r["start_time_local"], r["end_time_local"])
            topic = topics.get(r["ref_id"])
            if not topic:
                fit_ok = False
                break
            if topic["eta_minutes"] > window_len:
                fit_ok = False
                break
        if all_unique and max_posts_ok and fit_ok:
            scores["calendar_posts_constraints"] = 1.0

    if cal_rows is not None and availability and targets:
        research_rows = [r for r in cal_rows if r["slot_type"] == "research"]
        targets_ok = True
        for r in research_rows:
            if r.get("ref_id") not in targets:
                targets_ok = False
                break
        min_ok = True
        if rules and "min_research_sessions" in rules:
            min_ok = len(research_rows) >= rules["min_research_sessions"]
        if targets_ok and min_ok:
            scores["calendar_research_minimum_and_targets_valid"] = 1.0

    if cal_rows is not None and availability and expected_windows and topics and priorities:
        emphasize = priorities["emphasize_tags"]
        scheduled_set = set()
        prefer_ok = True
        for r in cal_rows:
            if r["slot_type"] != "post":
                continue
            win_len = _minutes_between(r["start_time_local"], r["end_time_local"])
            scheduled_topic_id = r["ref_id"]
            scheduled_topic = topics.get(scheduled_topic_id)
            if not scheduled_topic:
                prefer_ok = False
                break
            candidates = [
                t for tid, t in topics.items()
                if tid not in scheduled_set and t["eta_minutes"] <= win_len
            ]
            emphasized_candidates = [t for t in candidates if any(tag in emphasize for tag in t["tags"])]
            scheduled_is_emphasized = any(tag in emphasize for tag in scheduled_topic["tags"])
            if emphasized_candidates:
                if not scheduled_is_emphasized:
                    prefer_ok = False
                    break
                min_eta = min(t["eta_minutes"] for t in emphasized_candidates)
                if scheduled_topic["eta_minutes"] != min_eta:
                    prefer_ok = False
                    break
            scheduled_set.add(scheduled_topic_id)
        if prefer_ok:
            scores["preference_emphasize_tags_respected"] = 1.0

    research_entries = _load_jsonl(research_log_path)
    if isinstance(research_entries, list):
        required_keys = {"target_id", "query", "domain", "page_title", "retrieval_timestamp_iso", "note"}
        schema_ok = True
        for e in research_entries:
            if not isinstance(e, dict):
                schema_ok = False
                break
            if not required_keys.issubset(e.keys()):
                schema_ok = False
                break
            dom = str(e.get("domain", "")).strip()
            if "." not in dom or dom.startswith("http"):
                schema_ok = False
                break
            note = str(e.get("note", "")).strip()
            if not note or len(note) > 300:
                schema_ok = False
                break
        if schema_ok:
            scores["research_log_exists_and_schema"] = 1.0

        if targets:
            per_target_queries = {}
            per_target_domains = {}
            for e in research_entries:
                tid = e.get("target_id")
                if tid is None:
                    continue
                per_target_queries.setdefault(tid, set()).add(str(e.get("query", "")))
                per_target_domains.setdefault(tid, set()).add(str(e.get("domain", "")))
            per_target_ok = True
            for tid in targets.keys():
                qset = per_target_queries.get(tid, set())
                dset = per_target_domains.get(tid, set())
                if len(qset) < 2 or len(dset) < 2:
                    per_target_ok = False
                    break
            if per_target_ok:
                scores["research_log_per_target_queries_and_domains"] = 1.0

        ts_ok = True
        for e in research_entries:
            ts = str(e.get("retrieval_timestamp_iso", ""))
            if not _iso_parse(ts):
                ts_ok = False
                break
        if ts_ok:
            scores["research_log_timestamp_format"] = 1.0

    status_text = _read_text(status_update_path)
    if isinstance(status_text, str):
        scores["status_update_exists"] = 1.0

        inputs_listed_ok = False
        if status_text:
            expected_files = ["availability.yaml", "topics.jsonl", "priorities.json", "research_targets.csv"]
            inputs_listed_ok = all(fn in status_text for fn in expected_files)
        if inputs_listed_ok:
            scores["status_update_inputs_listed"] = 1.0

        counts_ok = False
        if cal_rows is not None:
            posts_count = sum(1 for r in cal_rows if r["slot_type"] == "post")
            research_count = sum(1 for r in cal_rows if r["slot_type"] == "research")
            m_posts = re.search(r'\b(\d+)\s+(?:post|posts)\b', status_text, flags=re.IGNORECASE)
            m_research = re.search(r'\b(\d+)\s+(?:research|research sessions|research slots)\b', status_text, flags=re.IGNORECASE)
            if m_posts and m_research:
                try:
                    sp = int(m_posts.group(1))
                    sr = int(m_research.group(1))
                    if sp == posts_count and sr == research_count:
                        counts_ok = True
                except Exception:
                    counts_ok = False
        if counts_ok:
            scores["status_update_counts_correct"] = 1.0

        posts_details_ok = False
        if cal_rows is not None and topics is not None and status_text:
            posts = [r for r in cal_rows if r["slot_type"] == "post"]
            ok_count = 0
            lines = status_text.splitlines()
            for r in posts:
                title = r.get("title", "")
                eta = r.get("eta_minutes", "")
                date = r.get("date", "")
                time = r.get("start_time_local", "")
                found = False
                for line in lines:
                    if title and title in line and str(eta) in line and (date in line or time in line):
                        topic = topics.get(r.get("ref_id", ""))
                        if topic and any(tag in line for tag in topic.get("tags", [])):
                            found = True
                            break
                if found:
                    ok_count += 1
            if ok_count == len(posts) and len(posts) > 0:
                posts_details_ok = True
        if posts_details_ok:
            scores["status_update_posts_listed_with_details"] = 1.0

        research_focus_ok = False
        if research_entries is not None and isinstance(research_entries, list) and status_text and targets:
            if ("http://" not in status_text) and ("https://" not in status_text) and ("www." not in status_text):
                per_target_domains = {}
                per_target_titles = {}
                for e in research_entries:
                    tid = e.get("target_id")
                    if tid is None:
                        continue
                    per_target_domains.setdefault(tid, set()).add(str(e.get("domain", "")))
                    per_target_titles.setdefault(tid, set()).add(str(e.get("page_title", "")))
                all_ok = True
                for tid in targets.keys():
                    doms = list(per_target_domains.get(tid, set()))
                    tits = list(per_target_titles.get(tid, set()))
                    if len(doms) < 2 or len(tits) < 2:
                        all_ok = False
                        break
                    if tid not in status_text:
                        all_ok = False
                        break
                    dom_hits = sum(1 for d in doms if d and d in status_text)
                    tit_hits = sum(1 for t in tits if t and t in status_text)
                    if dom_hits < 2 or tit_hits < 2:
                        all_ok = False
                        break
                if all_ok:
                    research_focus_ok = True
        if research_focus_ok:
            scores["status_update_research_focus_matches_log_and_no_urls"] = 1.0

        next_steps_ok = False
        if topics is not None and cal_rows is not None and status_text:
            has_section = any(k in status_text.lower() for k in ["next steps", "deferral", "deferred", "didn’t fit", "didn't fit"])
            used_topic_ids = set(r["ref_id"] for r in cal_rows if r["slot_type"] in {"post", "maintenance"})
            unscheduled_titles = [t["title"] for tid, t in topics.items() if tid not in used_topic_ids]
            mentioned_any = any(title in status_text for title in unscheduled_titles)
            if has_section and mentioned_any:
                next_steps_ok = True
        if next_steps_ok:
            scores["status_update_next_steps_mentions_unscheduled"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()