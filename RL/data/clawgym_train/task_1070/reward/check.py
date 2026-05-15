import json
import csv
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_load_jsonl(p: Path) -> Optional[List[dict]]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    out = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        out.append(obj)
    return out


def parse_iso_ts(ts: str) -> Optional[datetime]:
    try:
        # Expect format like "2026-04-18T19:40"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def iso_week_bounds(d: date) -> Tuple[date, date]:
    # ISO week starts Monday (weekday 0) to Sunday (6)
    # datetime.weekday(): Monday=0 ... Sunday=6
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start, end


def parse_availability_csv(p: Path) -> Optional[Dict[str, List[Tuple[datetime, datetime]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if not {"person", "start", "end"}.issubset(set(rdr.fieldnames or [])):
                return None
            av: Dict[str, List[Tuple[datetime, datetime]]] = {}
            for row in rdr:
                person = row.get("person", "").strip()
                s = row.get("start", "").strip()
                e = row.get("end", "").strip()
                try:
                    sdt = datetime.strptime(s, "%Y-%m-%d %H:%M")
                    edt = datetime.strptime(e, "%Y-%m-%d %H:%M")
                except Exception:
                    return None
                if edt <= sdt:
                    # invalid range
                    continue
                av.setdefault(person, []).append((sdt, edt))
            return av
    except Exception:
        return None


def find_script_with_readme_example(scripts_dir: Path) -> Optional[Path]:
    # Prefer scripts/watch_incidents.py if present
    preferred = scripts_dir / "watch_incidents.py"
    if preferred.is_file():
        return preferred
    # Otherwise, pick any .py under scripts/
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.glob("*.py")):
            if p.is_file():
                return p
    return None


def contains_field_with_number(text: str, field: str, number_str: str) -> bool:
    # Look for the field name followed by up to 20 non-digits and then the number
    pattern = re.compile(rf"{re.escape(field)}[^\d]{{0,20}}{re.escape(number_str)}", re.IGNORECASE)
    return bool(pattern.search(text))


def line_contains_both(text: str, a: str, b: str) -> bool:
    for line in text.splitlines():
        if a in line and b in line:
            return True
    return False


def extract_word_counts_from_text(text: str) -> Dict[str, int]:
    # Extract simple "word: number" or "word (number)" patterns, lowercase words only
    counts: Dict[str, int] = {}
    # Patterns like:
    # - word: 3
    # - "word": 3
    # - word (3)
    # - - word: 3
    # Capture hyphenated words like 'follow-up' and 'de-escalation'
    for m in re.finditer(r'["\']?([a-z][a-z\-]+)["\']?\s*[:(]\s*(\d+)\)?', text):
        w = m.group(1)
        n = int(m.group(2))
        if w != w.lower():
            continue
        counts[w] = counts.get(w, 0) + n
    return counts


def compute_expected_from_inputs(workspace: Path):
    inputs_ok = True
    incidents_path = workspace / "input" / "incidents.jsonl"
    peers_path = workspace / "input" / "peers.json"
    avail_path = workspace / "input" / "availability.csv"

    incidents = safe_load_jsonl(incidents_path)
    peers = safe_load_json(peers_path)
    avail = parse_availability_csv(avail_path)

    if incidents is None or peers is None or avail is None:
        inputs_ok = False
        return inputs_ok, None

    # Determine latest incident timestamp and ISO week bounds
    parsed_incidents = []
    for rec in incidents:
        ts = rec.get("timestamp")
        itype = rec.get("incident_type")
        stress = rec.get("stress_rating")
        notes = rec.get("notes", "")
        dt = parse_iso_ts(ts) if isinstance(ts, str) else None
        if dt is None or not isinstance(itype, str) or not isinstance(stress, (int, float)):
            inputs_ok = False
            return inputs_ok, None
        parsed_incidents.append(
            {
                "dt": dt,
                "date": dt.date(),
                "incident_type": itype,
                "stress_rating": float(stress),
                "notes": notes if isinstance(notes, str) else "",
            }
        )
    if not parsed_incidents:
        inputs_ok = False
        return inputs_ok, None

    latest_dt = max(pi["dt"] for pi in parsed_incidents)
    latest_date = latest_dt.date()
    week_start, week_end = iso_week_bounds(latest_date)

    included = [pi for pi in parsed_incidents if week_start <= pi["date"] <= week_end]

    if not included:
        # If none, still inputs_ok but we cannot compute totals meaningfully
        inputs_ok = False
        return inputs_ok, None

    total_new_incidents = len(included)
    avg_stress = round(sum(pi["stress_rating"] for pi in included) / total_new_incidents, 1)

    # Counts by incident_type
    type_counts: Dict[str, int] = {}
    for pi in included:
        type_counts[pi["incident_type"]] = type_counts.get(pi["incident_type"], 0) + 1

    # Expected summary and email file paths
    buddy_name = None
    if isinstance(peers, dict):
        buddy_name = peers.get("primary_buddy")
    if not isinstance(buddy_name, str) or not buddy_name:
        inputs_ok = False
        return inputs_ok, None

    summary_filename = f"weekly_summary_{week_start.isoformat()}_to_{week_end.isoformat()}.md"
    summary_path = workspace / "output" / summary_filename
    email_filename = f"email_to_{buddy_name}_{latest_date.isoformat()}.txt"
    email_path = workspace / "output" / email_filename
    state_path = workspace / "output" / "state.json"

    # Compute expected earliest overlap within 7 days from latest_date
    # Window: latest_date to latest_date + 7 days inclusive
    window_start = datetime.combine(latest_date, datetime.min.time())
    window_end = window_start + timedelta(days=7, seconds=-1)
    self_slots = avail.get("self", [])
    buddy_slots = avail.get(buddy_name, [])
    overlaps: List[Tuple[datetime, datetime]] = []
    for s_start, s_end in self_slots:
        for b_start, b_end in buddy_slots:
            # Check if on same date, intersection positive
            inter_start = max(s_start, b_start)
            inter_end = min(s_end, b_end)
            if inter_end > inter_start and (window_start <= inter_start <= window_end):
                overlaps.append((inter_start, inter_end))
    overlaps.sort(key=lambda t: t[0])
    expected_overlap_str = None
    if overlaps:
        # Propose 30-minute slot starting at overlap start, or as long as available if shorter?
        # Spec asks to propose a 30-minute shared wind-down time based on overlapping availability.
        # We'll format the intersection start and min(start+30min, end).
        inter_start, inter_end = overlaps[0]
        proposed_end = min(inter_start + timedelta(minutes=30), inter_end)
        if proposed_end > inter_start:
            expected_overlap_str = f"{inter_start.strftime('%Y-%m-%d %H:%M')}-{proposed_end.strftime('%H:%M')}"

    expected = {
        "incidents_path": str(incidents_path),
        "peers_path": str(peers_path),
        "availability_path": str(avail_path),
        "latest_date": latest_date.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_new_incidents": total_new_incidents,
        "avg_stress": f"{avg_stress:.1f}",
        "type_counts": type_counts,
        "buddy_name": buddy_name,
        "summary_path": str(summary_path),
        "email_path": str(email_path),
        "state_path": str(state_path),
        "expected_overlap_str": expected_overlap_str,
        "included_incidents": included,
        "incidents_count_total_lines": len(incidents),
    }
    return inputs_ok, expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_exists": 0.0,
        "summary_period_correct": 0.0,
        "summary_totals_correct": 0.0,
        "summary_incident_counts_present": 0.0,
        "summary_keywords_quality": 0.0,
        "summary_incident_table_entries": 0.0,
        "email_file_exists": 0.0,
        "email_greeting_and_buddy": 0.0,
        "email_includes_recap_numbers": 0.0,
        "email_overlap_time_correct": 0.0,
        "email_includes_preferred_activity": 0.0,
        "state_file_exists": 0.0,
        "state_fields_correct": 0.0,
        "state_last_generated_files_correct": 0.0,
        "script_contains_readme_example": 0.0,
    }

    inputs_ok, expected = compute_expected_from_inputs(workspace)

    # Check for summary and email files presence
    summary_path = None
    email_path = None
    state_path = workspace / "output" / "state.json"

    if expected is not None:
        summary_path = Path(expected["summary_path"])
        email_path = Path(expected["email_path"])
        if summary_path.is_file():
            scores["summary_file_exists"] = 1.0
        if email_path.is_file():
            scores["email_file_exists"] = 1.0
    else:
        # If expected cannot be computed, we still try to detect presence via patterns
        # but we won't be able to validate contents strictly.
        # Attempt to locate any weekly_summary_* file
        weekly_files = sorted((workspace / "output").glob("weekly_summary_*_to_*.md")) if (workspace / "output").is_dir() else []
        if weekly_files:
            summary_path = weekly_files[-1]
            scores["summary_file_exists"] = 1.0
        email_files = sorted((workspace / "output").glob("email_to_*_*.txt")) if (workspace / "output").is_dir() else []
        if email_files:
            email_path = email_files[-1]
            scores["email_file_exists"] = 1.0

    # Validate summary content
    if summary_path and summary_path.is_file() and expected is not None:
        text = safe_read_text(summary_path) or ""
        # Period exact
        expected_period = f"Period: {expected['week_start']} to {expected['week_end']}"
        if expected_period in text:
            scores["summary_period_correct"] = 1.0

        # Totals: total_new_incidents and avg_stress_rating with correct values
        totals_ok = True
        if not contains_field_with_number(text, "total_new_incidents", str(expected["total_new_incidents"])):
            totals_ok = False
        if not contains_field_with_number(text, "avg_stress_rating", expected["avg_stress"]):
            totals_ok = False
        scores["summary_totals_correct"] = 1.0 if totals_ok else 0.0

        # Counts by incident_type: ensure each included type appears with count
        counts_ok = True
        for itype, cnt in expected["type_counts"].items():
            # Search a line where itype appears with a digit count nearby on the same line
            found = False
            for line in text.splitlines():
                if itype in line:
                    # look for the number in the same line
                    m = re.search(r'(\d+)', line)
                    if m and int(m.group(1)) == cnt:
                        found = True
                        break
            if not found:
                counts_ok = False
                break
        scores["summary_incident_counts_present"] = 1.0 if counts_ok else 0.0

        # Keywords: at least 5 entries and 'coordinated' with freq >= 2
        wc = extract_word_counts_from_text(text)
        keywords_ok = False
        if len(wc) >= 5:
            coord_freq = wc.get("coordinated", 0)
            if coord_freq >= 2:
                keywords_ok = True
        scores["summary_keywords_quality"] = 1.0 if keywords_ok else 0.0

        # Incident table: verify that each included incident appears with date and incident_type on same line
        pairs = []
        for pi in expected["included_incidents"]:
            dstr = pi["date"].isoformat()
            itype = pi["incident_type"]
            pairs.append((dstr, itype))
        found_count = 0
        for dstr, itype in pairs:
            if line_contains_both(text, dstr, itype):
                found_count += 1
        # Proportion correct
        if pairs:
            scores["summary_incident_table_entries"] = found_count / len(pairs)
        else:
            scores["summary_incident_table_entries"] = 0.0

    # Validate email content
    if email_path and email_path.is_file() and expected is not None:
        etext = safe_read_text(email_path) or ""
        # Greeting with buddy's first name at start
        non_empty_lines = [ln for ln in etext.splitlines() if ln.strip()]
        greeting_ok = False
        for ln in non_empty_lines[:3]:
            if re.match(rf'^\s*(hi|hello|dear|hey)\b.*\b{re.escape(expected["buddy_name"])}\b', ln, re.IGNORECASE):
                greeting_ok = True
                break
        scores["email_greeting_and_buddy"] = 1.0 if greeting_ok else 0.0

        # Recap numbers: include total_new_incidents and avg_stress from summary
        recap_ok = False
        if str(expected["total_new_incidents"]) in etext and str(expected["avg_stress"]) in etext:
            recap_ok = True
        scores["email_includes_recap_numbers"] = 1.0 if recap_ok else 0.0

        # Overlap time: verify earliest overlap string present if expected
        overlap_ok = False
        if expected.get("expected_overlap_str"):
            if expected["expected_overlap_str"] in etext:
                overlap_ok = True
        # If no overlap expected, then check for "async check-in via chat" phrase
        else:
            if re.search(r'async check-in via chat', etext, re.IGNORECASE):
                overlap_ok = True
        scores["email_overlap_time_correct"] = 1.0 if overlap_ok else 0.0

        # Includes preferred activity (first activity of buddy)
        peers = safe_load_json(workspace / "input" / "peers.json")
        activity_ok = False
        if isinstance(peers, dict):
            buddies = peers.get("buddies", {})
            buddy_info = buddies.get(expected["buddy_name"], {})
            if isinstance(buddy_info, dict):
                acts = buddy_info.get("preferred_activities", [])
                if isinstance(acts, list) and acts:
                    first_act = str(acts[0])
                    if first_act and re.search(re.escape(first_act), etext, re.IGNORECASE):
                        activity_ok = True
        scores["email_includes_preferred_activity"] = 1.0 if activity_ok else 0.0

    # Validate state.json
    if state_path.is_file():
        scores["state_file_exists"] = 1.0
        state = safe_load_json(state_path)
        fields_ok = False
        last_gen_ok = False
        if isinstance(state, dict):
            last_processed_line = state.get("last_processed_line")
            last_generated_files = state.get("last_generated_files")
            if expected is not None and isinstance(last_processed_line, int):
                if last_processed_line == expected["incidents_count_total_lines"]:
                    fields_ok = True
            # last_generated_files should include summary and email paths
            if isinstance(last_generated_files, list):
                expected_paths = set([expected["summary_path"], expected["email_path"]]) if expected is not None else set()
                have = set()
                for v in last_generated_files:
                    if isinstance(v, str):
                        have.add(str((workspace / v).resolve()) if not v.startswith(str(workspace)) else v)
                # Normalize comparisons by direct string equality to expected relative paths if available
                if expected is not None:
                    if expected["summary_path"] in last_generated_files and expected["email_path"] in last_generated_files:
                        last_gen_ok = True
        scores["state_fields_correct"] = 1.0 if fields_ok else 0.0
        scores["state_last_generated_files_correct"] = 1.0 if last_gen_ok else 0.0

    # Check script README example at top of script file
    script_path = find_script_with_readme_example(workspace / "scripts")
    if script_path and script_path.is_file():
        head = safe_read_text(script_path) or ""
        # Look in first ~15 lines
        first_lines = "\n".join(head.splitlines()[:15])
        if re.search(r'#.*python\s+.+watch_incidents\.py', first_lines, re.IGNORECASE) or re.search(r'#\s*Example:.*python\s+', first_lines, re.IGNORECASE) or re.search(r'#.*python\s+', first_lines, re.IGNORECASE):
            scores["script_contains_readme_example"] = 1.0

    # If inputs were not OK, we still returned partial scores for existence. Ensure no crashes occurred.
    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()