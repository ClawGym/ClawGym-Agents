import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _time_to_minutes(t: str) -> int:
    hh, mm = t.strip().split(":")
    return int(hh) * 60 + int(mm)


def _minutes_to_time(m: int) -> str:
    hh = m // 60
    mm = m % 60
    return f"{hh:02d}:{mm:02d}"


def _merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def _intersect_intervals(a: List[Tuple[int, int]], b: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    i, j = 0, 0
    result: List[Tuple[int, int]] = []
    a_sorted = sorted(a)
    b_sorted = sorted(b)
    while i < len(a_sorted) and j < len(b_sorted):
        s1, e1 = a_sorted[i]
        s2, e2 = b_sorted[j]
        s = max(s1, s2)
        e = min(e1, e2)
        if s < e:
            result.append((s, e))
        if e1 < e2:
            i += 1
        else:
            j += 1
    return _merge_intervals(result)


def _parse_availability(rows: List[Dict[str, str]], date_key: str, start_key: str, end_key: str) -> Dict[str, List[Tuple[int, int]]]:
    per_date: Dict[str, List[Tuple[int, int]]] = {}
    for r in rows:
        date = r[date_key].strip()
        s = _time_to_minutes(r[start_key].strip())
        e = _time_to_minutes(r[end_key].strip())
        per_date.setdefault(date, []).append((s, e))
    # merge intervals per date
    for d in list(per_date.keys()):
        per_date[d] = _merge_intervals(per_date[d])
    return per_date


def _parse_attendees_availability(rows: List[Dict[str, str]], attendees: List[str]) -> Dict[str, Dict[str, List[Tuple[int, int]]]]:
    # returns mapping person -> date -> intervals
    data: Dict[str, Dict[str, List[Tuple[int, int]]]] = {}
    norm_attendees = set(attendees)
    for r in rows:
        person = r.get("person", "").strip()
        if person not in norm_attendees:
            continue
        date = r["date"].strip()
        s = _time_to_minutes(r["start"].strip())
        e = _time_to_minutes(r["end"].strip())
        data.setdefault(person, {}).setdefault(date, []).append((s, e))
    # merge intervals per date for each person
    for person in list(data.keys()):
        for d in list(data[person].keys()):
            data[person][d] = _merge_intervals(data[person][d])
    return data


def _compute_candidates(workspace: Path) -> Optional[List[Dict[str, str]]]:
    # Returns list of candidates dicts: date, start, end, window_label, score(str or int)
    pref_path = workspace / "input" / "preferences.json"
    owner_path = workspace / "input" / "owner_availability.csv"
    attendees_path = workspace / "input" / "attendees_availability.csv"

    prefs = _read_json(pref_path)
    owner_rows = _read_csv(owner_path)
    att_rows = _read_csv(attendees_path)

    if prefs is None or owner_rows is None or att_rows is None:
        return None

    duration = int(prefs.get("duration_minutes", 0))
    preferred_window = prefs.get("preferred_window", {})
    pw_start = _time_to_minutes(preferred_window.get("start", "00:00"))
    pw_end = _time_to_minutes(preferred_window.get("end", "00:00"))
    morning_weight = prefs.get("morning_weight", 0)
    attendees = prefs.get("attendees", [])

    # Remove "Zen Master" from attendee list for attendees_availability; owner is separate
    non_owner_attendees = [a for a in attendees if a != "Zen Master"]

    owner = _parse_availability(owner_rows, "date", "start", "end")
    att_map = _parse_attendees_availability(att_rows, non_owner_attendees)

    # For each date where there is owner availability and each attendee has at least one interval, compute intersection windows
    dates = sorted(set(owner.keys()) | set().union(*(set(att_map.get(a, {}).keys()) for a in non_owner_attendees)))
    candidates: List[Dict[str, str]] = []
    for d in dates:
        if d not in owner:
            continue
        # Start with owner's intervals on this date
        current = owner[d]
        # Intersect with each attendee's intervals for that date; if any attendee has no intervals on that date, result becomes empty
        feasible = current
        for a in non_owner_attendees:
            att_intervals = att_map.get(a, {}).get(d, [])
            feasible = _intersect_intervals(feasible, att_intervals)
            if not feasible:
                break
        if not feasible:
            continue
        # For each maximal overlap window, take earliest feasible start (window.start) if fits duration
        for (ws, we) in feasible:
            if we - ws >= duration:
                start_min = ws
                end_min = ws + duration
                # Label preferred window (inclusive start, exclusive end on preferred window)
                label = "preferred_window" if (pw_start <= start_min < pw_end) else "off_window"
                score = morning_weight if label == "preferred_window" else 0
                candidates.append({
                    "date": d,
                    "start": _minutes_to_time(start_min),
                    "end": _minutes_to_time(end_min),
                    "window_label": label,
                    "score": str(score),
                })
    # Rank by score desc, date asc, start asc
    candidates.sort(key=lambda x: (-float(x["score"]), x["date"], x["start"]))
    return candidates


def _expected_final_selection(workspace: Path) -> Optional[Dict[str, object]]:
    prefs = _read_json(workspace / "input" / "preferences.json")
    cars = _read_json(workspace / "input" / "cars.json")
    if prefs is None or cars is None:
        return None

    candidates = _compute_candidates(workspace)
    if not candidates:
        return None
    top = candidates[0]
    # choose car by highest priority_score, tie by earliest detailing_due_date then name
    def car_key(c):
        return (-int(c.get("priority_score", 0)),
                c.get("detailing_due_date", ""),
                c.get("name", ""))

    best_car = sorted(cars, key=car_key)[0]
    return {
        "title": prefs.get("meeting_title"),
        "date": top["date"],
        "start": top["start"],
        "end": top["end"],
        "timezone": prefs.get("timezone"),
        "location": prefs.get("location"),
        "attendees": prefs.get("attendees"),
        "car": best_car.get("name"),
        "score": float(top["score"]),
    }


def _expected_filled_file(template_text: str, selection: Dict[str, object], prefs: Dict[str, object], include_duration: bool) -> str:
    attendees_str = ", ".join(prefs.get("attendees", []))
    replacements = {
        "{{TITLE}}": str(selection["title"]),
        "{{DATE}}": str(selection["date"]),
        "{{START}}": str(selection["start"]),
        "{{END}}": str(selection["end"]),
        "{{TIMEZONE}}": str(selection["timezone"]),
        "{{LOCATION}}": str(selection["location"]),
        "{{ATTENDEES}}": attendees_str,
        "{{CAR}}": str(selection["car"]),
    }
    if include_duration:
        replacements["{{DURATION}}"] = str(prefs.get("duration_minutes"))

    filled = template_text
    for k, v in replacements.items():
        filled = filled.replace(k, v)
    return filled


def _parse_csv_exact(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _find_events_blocks(yaml_text: str) -> List[str]:
    # Return list of event item blocks under 'events:'
    lines = yaml_text.splitlines()
    blocks = []
    # find 'events:' line index
    events_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*events\s*:', line):
            events_idx = i
            break
    if events_idx is None:
        return []
    # Determine base indent for events children
    base_indent = len(re.match(r'^(\s*)', lines[events_idx]).group(1)) + 2
    i = events_idx + 1
    current_block = None
    current_block_indent = None
    while i < len(lines):
        line = lines[i]
        # Stop when dedent to less than events indent and a new top-level key starts
        if len(re.match(r'^(\s*)', line).group(1)) < (base_indent - 2) and re.search(r':', line):
            break
        # Identify new item
        m = re.match(r'^(\s*)-\s*(.*)$', line)
        if m and len(m.group(1)) == base_indent:
            # Start a new block
            if current_block is not None:
                blocks.append("\n".join(current_block))
            current_block = [line]
            current_block_indent = len(m.group(1))
        else:
            if current_block is not None:
                # part of current block (including nested lines)
                current_block.append(line)
        i += 1
    if current_block is not None:
        blocks.append("\n".join(current_block))
    return blocks


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "slots_ranked_csv_valid": 0.0,
        "final_selection_json_valid": 0.0,
        "agenda_filled_correctly": 0.0,
        "invite_filled_correctly": 0.0,
        "scheduler_config_updated": 0.0,
        "retreat_calendar_updated": 0.0,
    }

    # Compute expected candidates and selection
    prefs = _read_json(workspace / "input" / "preferences.json")
    expected_candidates = _compute_candidates(workspace)
    expected_selection = _expected_final_selection(workspace)

    # Check slots_ranked.csv
    slots_path = workspace / "out" / "slots_ranked.csv"
    csv_parsed = _parse_csv_exact(slots_path)
    if expected_candidates is not None and csv_parsed is not None:
        header, rows = csv_parsed
        expected_header = ["date", "start", "end", "window_label", "score"]
        if header == expected_header:
            # Compare rows count and content
            # Normalize provided rows into dicts to compare
            provided = []
            for r in rows:
                if len(r) != 5:
                    provided = None
                    break
                provided.append({
                    "date": r[0],
                    "start": r[1],
                    "end": r[2],
                    "window_label": r[3],
                    "score": r[4],
                })
            if provided is not None:
                # Compare length
                if len(provided) == len(expected_candidates):
                    # Compare each row in order; allow score numeric equivalence
                    all_match = True
                    for p, e in zip(provided, expected_candidates):
                        try:
                            pscore = float(p["score"])
                        except Exception:
                            all_match = False
                            break
                        escore = float(e["score"])
                        if not (
                            p["date"] == e["date"] and
                            p["start"] == e["start"] and
                            p["end"] == e["end"] and
                            p["window_label"] == e["window_label"] and
                            abs(pscore - escore) < 1e-9
                        ):
                            all_match = False
                            break
                    if all_match:
                        scores["slots_ranked_csv_valid"] = 1.0

    # Check final_selection.json
    final_sel_path = workspace / "out" / "final_selection.json"
    student_final = _read_json(final_sel_path)
    if expected_selection is not None and student_final is not None:
        # Must have exactly the required keys
        required_keys = ["title", "date", "start", "end", "timezone", "location", "attendees", "car", "score"]
        if set(student_final.keys()) == set(required_keys):
            try:
                # Compare values strictly
                values_match = True
                for k in ["title", "date", "start", "end", "timezone", "location", "car"]:
                    if str(student_final.get(k)) != str(expected_selection.get(k)):
                        values_match = False
                        break
                if values_match:
                    # attendees exact order and content
                    if student_final.get("attendees") == expected_selection.get("attendees"):
                        # score numeric
                        if abs(float(student_final.get("score")) - float(expected_selection.get("score"))) < 1e-9:
                            scores["final_selection_json_valid"] = 1.0
            except Exception:
                pass

    # Check agenda.md and invite.md
    agenda_template_path = workspace / "docs" / "agenda_template.md"
    invite_template_path = workspace / "notes" / "invite_template.md"
    agenda_out_path = workspace / "out" / "agenda.md"
    invite_out_path = workspace / "out" / "invite.md"

    agenda_template = _read_text(agenda_template_path)
    invite_template = _read_text(invite_template_path)
    agenda_out = _read_text(agenda_out_path)
    invite_out = _read_text(invite_out_path)

    if expected_selection is not None and prefs is not None and agenda_template is not None and agenda_out is not None:
        expected_agenda = _expected_filled_file(agenda_template, expected_selection, prefs, include_duration=False)
        if _normalize_newlines(expected_agenda) == _normalize_newlines(agenda_out):
            scores["agenda_filled_correctly"] = 1.0

    if expected_selection is not None and prefs is not None and invite_template is not None and invite_out is not None:
        expected_invite = _expected_filled_file(invite_template, expected_selection, prefs, include_duration=True)
        if _normalize_newlines(expected_invite) == _normalize_newlines(invite_out):
            scores["invite_filled_correctly"] = 1.0

    # Check scheduler/config.yaml modifications
    config_path = workspace / "scheduler" / "config.yaml"
    config_text = _read_text(config_path)
    if expected_selection is not None and prefs is not None and config_text is not None:
        # Check default_duration_minutes updated
        duration = int(prefs.get("duration_minutes", 0))
        duration_ok = bool(re.search(r'^\s*default_duration_minutes\s*:\s*{}\s*$'.format(re.escape(str(duration))), config_text, flags=re.M))
        # Check event appended under events
        blocks = _find_events_blocks(config_text)
        event_ok = False
        if blocks:
            for b in blocks:
                # Check all required key-value pairs are present in this block
                required_pairs = [
                    ("title", str(expected_selection["title"])),
                    ("date", str(expected_selection["date"])),
                    ("start", str(expected_selection["start"])),
                    ("end", str(expected_selection["end"])),
                    ("timezone", str(expected_selection["timezone"])),
                    ("location", str(expected_selection["location"])),
                    ("car", str(expected_selection["car"])),
                ]
                pairs_ok = True
                for k, v in required_pairs:
                    # Allow key: value with optional quotes and spaces
                    pattern = r'^\s*{}\s*:\s*("?{}"?|\[.*{}\s*,?.*\]|.*)$'.format(re.escape(k), re.escape(v), re.escape(v))
                    if not re.search(pattern, b, flags=re.M):
                        pairs_ok = False
                        break
                # attendees: ensure all names present in block
                attendees_ok = True
                for name in prefs.get("attendees", []):
                    if name not in b:
                        attendees_ok = False
                        break
                if pairs_ok and attendees_ok:
                    event_ok = True
                    break
        if duration_ok and event_ok:
            scores["scheduler_config_updated"] = 1.0

    # Check notes/retreat_calendar.md updated
    calendar_path = workspace / "notes" / "retreat_calendar.md"
    cal_text = _read_text(calendar_path)
    if expected_selection is not None and cal_text is not None and prefs is not None:
        # Find '## Scheduled' section boundaries
        lines = cal_text.splitlines()
        sched_start = None
        sched_end = len(lines)
        for i, line in enumerate(lines):
            if line.strip() == "## Scheduled":
                sched_start = i
                break
        if sched_start is not None:
            for j in range(sched_start + 1, len(lines)):
                if re.match(r'^\s*##\s+', lines[j]) and j > sched_start:
                    sched_end = j
                    break
            scheduled_section = "\n".join(lines[sched_start:sched_end])
            # Build expected line
            # Use en dash U+2013 between times and also before 'Attendees' is em dash U+2014? The example uses "—" (em dash U+2014)
            en_dash = "–"
            em_dash = "—"
            expected_line = f"- {expected_selection['date']} {expected_selection['start']}{en_dash}{expected_selection['end']} (Europe/Rome) - Mindful Detailing Session @ Dojo Garage [Car: {expected_selection['car']}] {em_dash} Attendees: " + ", ".join(prefs.get("attendees", []))
            # Check presence exactly
            if expected_line in scheduled_section:
                scores["retreat_calendar_updated"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()