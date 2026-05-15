import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys by stripping whitespace
                clean_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(clean_row)
            return rows
    except Exception:
        return None


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def parse_segment_brief(path: Path) -> Dict[str, Optional[str]]:
    brief = {"show_name": None, "station_full": None, "station_core": None, "airtime": None, "time_slot": None}
    text = safe_read_text(path)
    if not text:
        return brief
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    # Show name: first line up to "—" or full before "Promo Brief"
    if lines:
        first = lines[0]
        # Try split by em dash
        if "—" in first:
            show = first.split("—", 1)[0].strip()
        elif "-" in first:
            show = first.split("-", 1)[0].strip()
        else:
            show = first.replace("Promo Brief", "").strip()
        brief["show_name"] = show
    for ln in lines:
        if ln.lower().startswith("station:"):
            station_val = ln.split(":", 1)[1].strip()
            brief["station_full"] = station_val
            core = station_val
            # Remove anything in parentheses
            core = re.sub(r"\(.*?\)", "", core).strip()
            # Remove trailing FM descriptor to get core "CKMT 101.9"
            core = re.sub(r"\s+FM\b", "", core).strip()
            brief["station_core"] = core
        if ln.lower().startswith("airtime:"):
            airtime_val = ln.split(":", 1)[1].strip()
            brief["airtime"] = airtime_val
            # Extract a time slot like 8–9pm or 8-9pm (allow spaces)
            m = re.search(r"(\d+\s*[–-]\s*\d+\s*pm)", airtime_val, flags=re.IGNORECASE)
            if m:
                timeslot = re.sub(r"\s+", "", m.group(1)).lower()  # normalize spaces
                # standardize to two variants later
                brief["time_slot"] = m.group(1)
    return brief


def get_confirmed_and_pending(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    confirmed = [r for r in rows if r.get("status", "").strip().lower() == "confirmed"]
    pending = [r for r in rows if r.get("status", "").strip().lower() == "pending"]
    return confirmed, pending


def parse_date_iso(date_str: str) -> Optional[str]:
    # Expect YYYY-MM-DD
    ds = date_str.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ds):
        return ds
    return None


def normalize_pretty_date_to_iso(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    # Remove weekday if present
    ds = date_str.strip()
    # e.g., "Fri May 2, 2026" or "Sun May 3, 2026" or "May 5, 2026" or "Apr 30, 2026"
    # Remove leading weekday token(s)
    parts = ds.split()
    if len(parts) >= 4 and parts[0][:3].lower() in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        ds = " ".join(parts[1:])
    # Now expect "MonName DD, YYYY" like "May 5, 2026" or "Apr 30, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", ds)
    if not m:
        return None
    month_str, day_str, year_str = m.groups()
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12
    }
    mo = month_map.get(month_str.lower())
    if not mo:
        return None
    try:
        day = int(day_str)
        year = int(year_str)
        return f"{year:04d}-{mo:02d}-{day:02d}"
    except Exception:
        return None


def word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    return len(tokens)


def find_int_near_keyword(text: str, keyword_pattern: str) -> Optional[int]:
    # Find a line containing keyword pattern and parse first integer on that line
    for ln in text.splitlines():
        if re.search(keyword_pattern, ln, flags=re.IGNORECASE):
            m = re.search(r"(-?\d+)", ln)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue
    return None


def message_subject_and_body_ok(text: str) -> bool:
    lines = text.splitlines()
    if len(lines) < 3:
        return False
    if not lines[0].startswith("Subject:"):
        return False
    if lines[1].strip() != "":
        return False
    return True


def contains_all_names(text: str, names: List[str]) -> bool:
    t = text
    for name in names:
        if name not in t:
            return False
    return True


def get_time_slot_variants(airtime: Optional[str]) -> List[str]:
    if not airtime:
        return []
    m = re.search(r"(\d+\s*[–-]\s*\d+\s*pm)", airtime, flags=re.IGNORECASE)
    variants = []
    if m:
        ts = m.group(1)
        # Remove spaces to normalize
        compact_dash = re.sub(r"\s+", "", ts)
        compact_dash = compact_dash.lower()
        # Create both en-dash and hyphen variants without spaces
        compact_hyphen = compact_dash.replace("–", "-")
        compact_endash = compact_dash.replace("-", "–")
        variants = list(set([compact_dash, compact_hyphen, compact_endash]))
    return variants


def parse_action_items_from_raw(path: Path) -> List[Dict[str, Optional[str]]]:
    text = safe_read_text(path)
    items = []
    if not text:
        return items
    for ln in text.splitlines():
        if "ACTION" in ln.upper():
            # Handle bullets like: - ACTION — Owner: task ... by <date>.
            # Normalize em dash and colon separators
            # Extract owner and task and due part
            # Examples:
            # - ACTION — Avery: email ... by Apr 30, 2026.
            # - ACTION — DJ K: record ... by Fri May 2, 2026.
            # - ACTION — Producer Mia: confirm ... by May 5, 2026.
            # - ACTION — Avery: reach out ... by Sun May 3, 2026.
            # Remove leading "- "
            line = ln.strip()
            # Replace long dash variants with a common separator
            line = line.replace("—", "-")
            # Now pattern: ACTION - Owner: task ... by <date>
            m = re.search(r"ACTION\s*-\s*([^:]+):\s*(.*)", line, flags=re.IGNORECASE)
            if m:
                owner = m.group(1).strip()
                rest = m.group(2).strip()
                # Split out due date by " by "
                due_iso = None
                task = rest
                by_m = re.search(r"(.+?)\s+by\s+(.+?)(?:\.|$)", rest, flags=re.IGNORECASE)
                if by_m:
                    task = by_m.group(1).strip()
                    due_str = by_m.group(2).strip()
                    due_iso = normalize_pretty_date_to_iso(due_str)
                items.append({"owner": owner, "task": task, "due_date": due_iso})
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "messages_files_present_en": 0.0,
        "messages_files_present_fr": 0.0,
        "messages_subject_and_body_format": 0.0,
        "messages_en_confirmed_content_personalized": 0.0,
        "messages_en_pending_content_personalized": 0.0,
        "messages_fr_confirmed_includes_required_info": 0.0,
        "blurb_en_length_and_presence": 0.0,
        "blurb_fr_length_and_presence": 0.0,
        "blurbs_station_and_time_mentions": 0.0,
        "blurbs_confirmed_artists_named": 0.0,
        "status_report_confirmed_list_ordered": 0.0,
        "status_report_counts_correct": 0.0,
        "status_report_runtime_and_provinces_present": 0.0,
        "status_metrics_json_valid": 0.0,
        "meeting_notes_sections_present": 0.0,
        "action_items_csv_headers_and_coverage": 0.0,
        "validator_script_runs": 0.0,
        "validation_output_captured": 0.0,
    }

    # Load inputs
    artists_path = workspace / "input" / "artists.csv"
    brief_path = workspace / "input" / "segment_brief.md"
    meeting_raw_path = workspace / "input" / "meeting_raw.md"

    artists_rows = safe_read_csv_dicts(artists_path)
    brief_info = parse_segment_brief(brief_path)
    show_name = brief_info.get("show_name") or ""
    station_full = brief_info.get("station_full") or ""
    station_core = brief_info.get("station_core") or ""
    airtime = brief_info.get("airtime") or ""
    time_variants = get_time_slot_variants(airtime)

    # Precompute confirmed and pending, metrics
    confirmed_rows: List[Dict[str, str]] = []
    pending_rows: List[Dict[str, str]] = []
    confirmed_metrics = {"count": 0, "total_runtime": 0, "unique_provinces": 0}
    pending_count = 0
    if artists_rows is not None:
        confirmed_rows, pending_rows = get_confirmed_and_pending(artists_rows)
        confirmed_metrics["count"] = len(confirmed_rows)
        confirmed_runtime = 0
        provinces = set()
        for r in confirmed_rows:
            try:
                confirmed_runtime += int(r.get("track_duration_sec") or 0)
            except Exception:
                confirmed_runtime += 0
            prov = (r.get("province") or "").strip()
            if prov:
                provinces.add(prov)
        confirmed_metrics["total_runtime"] = confirmed_runtime
        confirmed_metrics["unique_provinces"] = len(provinces)
        pending_count = len(pending_rows)

    # Messages checks
    messages_dir = workspace / "out" / "messages"
    en_exist_total = 0
    en_exist_ok = 0
    fr_needed_total = 0
    fr_exist_ok = 0
    all_message_files: List[Path] = []
    en_confirmed_total = 0
    en_confirmed_ok = 0
    en_pending_total = 0
    en_pending_ok = 0
    fr_confirmed_total = 0
    fr_confirmed_ok = 0

    if artists_rows is not None:
        for r in artists_rows:
            name = r.get("artist_name") or ""
            slug = slugify(name)
            lang = (r.get("language_pref") or "").strip().lower()
            status = (r.get("status") or "").strip().lower()
            track_title = r.get("track_title") or ""
            on_air_date = r.get("on_air_date") or ""
            en_path = messages_dir / f"{slug}_en.txt"
            fr_path = messages_dir / f"{slug}_fr.txt"

            # EN existence
            en_exist_total += 1
            if en_path.exists():
                en_exist_ok += 1
                all_message_files.append(en_path)
                # EN content for confirmed
                if status == "confirmed":
                    en_confirmed_total += 1
                    text = safe_read_text(en_path) or ""
                    # require show and station mention, track title and date, and request for bio and pronunciation notes
                    show_ok = show_name and (show_name in text)
                    station_ok = (station_core and (station_core in text)) or (station_full and (station_full in text))
                    track_ok = track_title in text
                    date_ok = on_air_date and (on_air_date in text)
                    # look for "bio" and "pronunciation" words (case-insensitive)
                    bio_ok = re.search(r"\bbio\b", text, flags=re.IGNORECASE) is not None
                    pron_ok = re.search(r"\bpronun", text, flags=re.IGNORECASE) is not None  # match 'pronunciation' or 'pronunciations'
                    if show_ok and station_ok and track_ok and date_ok and bio_ok and pron_ok:
                        en_confirmed_ok += 1
                elif status == "pending":
                    en_pending_total += 1
                    text = safe_read_text(en_path) or ""
                    # invite to join May spotlight, reference show and station, ask for availability in May
                    may_ok = re.search(r"\bmay\b", text, flags=re.IGNORECASE) is not None
                    avail_ok = re.search(r"\bavailability\b", text, flags=re.IGNORECASE) is not None
                    ref_ok = ((show_name and (show_name in text)) or (station_core and (station_core in text)) or (station_full and (station_full in text)))
                    if may_ok and avail_ok and ref_ok:
                        en_pending_ok += 1
            # FR existence when needed
            if lang in {"fr", "bilingual"}:
                fr_needed_total += 1
                if fr_path.exists():
                    fr_exist_ok += 1
                    all_message_files.append(fr_path)
                    # FR confirmed info presence (do not enforce FR words)
                    if status == "confirmed":
                        fr_confirmed_total += 1
                        text = safe_read_text(fr_path) or ""
                        show_ok = show_name and (show_name in text)
                        station_ok = (station_core and (station_core in text)) or (station_full and (station_full in text))
                        track_ok = track_title in text
                        date_ok = on_air_date and (on_air_date in text)
                        if show_ok and station_ok and track_ok and date_ok:
                            fr_confirmed_ok += 1

    # Subject and body format check for all existing message files
    subj_total = len(all_message_files)
    subj_ok = 0
    for p in all_message_files:
        txt = safe_read_text(p) or ""
        if message_subject_and_body_ok(txt):
            subj_ok += 1

    if en_exist_total > 0:
        scores["messages_files_present_en"] = en_exist_ok / en_exist_total
    if fr_needed_total > 0:
        scores["messages_files_present_fr"] = fr_exist_ok / fr_needed_total
    if subj_total > 0:
        scores["messages_subject_and_body_format"] = subj_ok / subj_total
    if en_confirmed_total > 0:
        scores["messages_en_confirmed_content_personalized"] = en_confirmed_ok / en_confirmed_total
    if en_pending_total > 0:
        scores["messages_en_pending_content_personalized"] = en_pending_ok / en_pending_total
    if fr_confirmed_total > 0:
        scores["messages_fr_confirmed_includes_required_info"] = fr_confirmed_ok / fr_confirmed_total

    # Blurbs checks
    blurb_en_path = workspace / "out" / "segment" / "blurb_en.txt"
    blurb_fr_path = workspace / "out" / "segment" / "blurb_fr.txt"
    blurb_en_text = safe_read_text(blurb_en_path) or ""
    blurb_fr_text = safe_read_text(blurb_fr_path) or ""

    if blurb_en_text:
        wc = word_count(blurb_en_text)
        if 90 <= wc <= 120:
            scores["blurb_en_length_and_presence"] = 1.0
    if blurb_fr_text:
        wc = word_count(blurb_fr_text)
        if 90 <= wc <= 120:
            scores["blurb_fr_length_and_presence"] = 1.0

    # Station and time mentions in both blurbs
    station_ok_en = False
    station_ok_fr = False
    time_ok_en = False
    time_ok_fr = False
    if blurb_en_text:
        station_ok_en = ((station_core and (station_core in blurb_en_text)) or (station_full and (station_full in blurb_en_text)) or ("CKMT 101.9" in blurb_en_text))
        # time slot variants
        time_ok_en = False
        if time_variants:
            for v in time_variants:
                compact_content = re.sub(r"\s+", "", blurb_en_text).lower()
                if v.lower() in compact_content:
                    time_ok_en = True
                    break
        # fallback: look for "8-9pm" or "8–9pm"
        if not time_ok_en:
            compact_content = re.sub(r"\s+", "", blurb_en_text).lower()
            if ("8-9pm" in compact_content) or ("8–9pm" in compact_content):
                time_ok_en = True
    if blurb_fr_text:
        station_ok_fr = ((station_core and (station_core in blurb_fr_text)) or (station_full and (station_full in blurb_fr_text)) or ("CKMT 101.9" in blurb_fr_text))
        time_ok_fr = False
        if time_variants:
            for v in time_variants:
                compact_content = re.sub(r"\s+", "", blurb_fr_text).lower()
                if v.lower() in compact_content:
                    time_ok_fr = True
                    break
        if not time_ok_fr:
            compact_content = re.sub(r"\s+", "", blurb_fr_text).lower()
            if ("8-9pm" in compact_content) or ("8–9pm" in compact_content):
                time_ok_fr = True

    if station_ok_en and station_ok_fr and time_ok_en and time_ok_fr:
        scores["blurbs_station_and_time_mentions"] = 1.0

    # Confirmed artists named in both blurbs
    confirmed_names = [r.get("artist_name") or "" for r in confirmed_rows] if artists_rows is not None else []
    if blurb_en_text and blurb_fr_text and confirmed_names:
        if contains_all_names(blurb_en_text, confirmed_names) and contains_all_names(blurb_fr_text, confirmed_names):
            scores["blurbs_confirmed_artists_named"] = 1.0

    # Status summary/report checks
    status_report_path = workspace / "out" / "status" / "status_report.md"
    status_report_text = safe_read_text(status_report_path) or ""
    if status_report_text and confirmed_rows:
        # order by on_air_date ascending, include city and track title
        # Build expected items
        enriched = []
        for r in confirmed_rows:
            enriched.append({
                "artist_name": r.get("artist_name") or "",
                "city": r.get("city") or "",
                "track_title": r.get("track_title") or "",
                "on_air_date": r.get("on_air_date") or ""
            })
        # Sort by on_air_date
        def date_key(x):
            # blank dates sort last; but confirmed should have dates
            d = x["on_air_date"]
            return d or "9999-99-99"
        enriched_sorted = sorted(enriched, key=date_key)

        # Find first index in report where name + city + track_title are on same line
        lines = status_report_text.splitlines()
        positions = {}
        for item in enriched_sorted:
            pattern_name = item["artist_name"]
            city = item["city"]
            track = item["track_title"]
            found_index = None
            for idx, ln in enumerate(lines):
                if (pattern_name in ln) and (city in ln) and (track in ln):
                    found_index = idx
                    break
            positions[item["artist_name"]] = found_index

        # Ensure all found
        if all(v is not None for v in positions.values()):
            # Ensure non-decreasing order by date; if dates differ, index must increase
            ok_order = True
            for i in range(len(enriched_sorted) - 1):
                a = enriched_sorted[i]
                b = enriched_sorted[i + 1]
                ai = positions[a["artist_name"]]
                bi = positions[b["artist_name"]]
                da = a["on_air_date"]
                db = b["on_air_date"]
                if da < db and not (ai < bi):
                    ok_order = False
                    break
            if ok_order:
                scores["status_report_confirmed_list_ordered"] = 1.0

        # Counts
        # Look for numbers near "confirmed" and "pending"
        # We'll accept either "<n> confirmed" or "confirmed: <n>" in any case
        confirmed_num = None
        pending_num = None
        for ln in lines:
            if re.search(r"confirmed", ln, flags=re.IGNORECASE):
                nums = re.findall(r"(\d+)", ln)
                if nums:
                    try:
                        confirmed_num = int(nums[0])
                    except Exception:
                        pass
            if re.search(r"pending", ln, flags=re.IGNORECASE):
                nums = re.findall(r"(\d+)", ln)
                if nums:
                    try:
                        pending_num = int(nums[0])
                    except Exception:
                        pass
        if (confirmed_num == confirmed_metrics["count"]) and (pending_num == pending_count):
            scores["status_report_counts_correct"] = 1.0

        # Runtime seconds and unique provinces counts
        runtime_val = None
        provinces_val = None
        # runtime near "runtime" or "seconds"
        for ln in lines:
            if re.search(r"runtime|seconds", ln, flags=re.IGNORECASE):
                m = re.search(r"(\d+)", ln)
                if m:
                    runtime_val = int(m.group(1))
            if re.search(r"province", ln, flags=re.IGNORECASE):
                m = re.search(r"(\d+)", ln)
                if m:
                    provinces_val = int(m.group(1))
        if (runtime_val == confirmed_metrics["total_runtime"]) and (provinces_val == confirmed_metrics["unique_provinces"]):
            scores["status_report_runtime_and_provinces_present"] = 1.0

    # status_metrics.json checks
    metrics_path = workspace / "out" / "status" / "status_metrics.json"
    metrics = safe_load_json(metrics_path)
    if metrics is not None and artists_rows is not None:
        expected_keys = {"confirmed_count", "pending_count", "total_runtime_seconds", "unique_provinces_confirmed_count"}
        if set(metrics.keys()) == expected_keys:
            # All ints?
            try:
                vals_int = all(isinstance(metrics[k], int) for k in expected_keys)
            except Exception:
                vals_int = False
            if vals_int:
                if (metrics["confirmed_count"] == confirmed_metrics["count"] and
                    metrics["pending_count"] == pending_count and
                    metrics["total_runtime_seconds"] == confirmed_metrics["total_runtime"] and
                    metrics["unique_provinces_confirmed_count"] == confirmed_metrics["unique_provinces"]):
                    scores["status_metrics_json_valid"] = 1.0

    # Meeting notes structured sections
    meeting_notes_path = workspace / "out" / "meeting" / "meeting_notes.md"
    notes_text = safe_read_text(meeting_notes_path) or ""
    if notes_text:
        has_decisions = re.search(r"\bDecisions\b", notes_text, flags=re.IGNORECASE) is not None
        has_actions = re.search(r"\bAction Items\b", notes_text, flags=re.IGNORECASE) is not None
        has_questions = re.search(r"\bQuestions\b", notes_text, flags=re.IGNORECASE) is not None
        has_risks = re.search(r"\bRisks\b", notes_text, flags=re.IGNORECASE) is not None
        if has_decisions and has_actions and has_questions and has_risks:
            scores["meeting_notes_sections_present"] = 1.0

    # Action items CSV coverage
    action_csv_path = workspace / "out" / "meeting" / "action_items.csv"
    action_rows = None
    if action_csv_path.exists():
        try:
            with action_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
                if headers == ["owner", "task", "due_date"]:
                    action_rows = []
                    for row in reader:
                        action_rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
        except Exception:
            action_rows = None

    raw_actions = parse_action_items_from_raw(meeting_raw_path)
    if action_rows is not None and raw_actions:
        # For each raw action, ensure there's a matching row
        matches = 0
        for ra in raw_actions:
            owner = (ra["owner"] or "").strip().lower()
            task = (ra["task"] or "").strip().lower()
            due = ra["due_date"] or ""
            found = False
            for row in action_rows:
                ro = (row.get("owner") or "").strip().lower()
                rt = (row.get("task") or "").strip().lower()
                rd = (row.get("due_date") or "").strip()
                # owner must match, task must contain or equal (allow minor differences), due must match iso (or be empty if not present)
                if ro == owner and (task in rt or rt in task):
                    # Due date expected in raw may be None -> allow empty
                    if (due and rd == due) or (not due and rd == ""):
                        found = True
                        break
            if found:
                matches += 1
        if matches == len(raw_actions):
            scores["action_items_csv_headers_and_coverage"] = 1.0

    # Validator script checks
    validator_path = workspace / "scripts" / "validate.py"
    if validator_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validator_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            out = proc.stdout or ""
            # Accept if output contains PASS or FAIL (case-insensitive)
            if re.search(r"\bPASS\b", out, flags=re.IGNORECASE) or re.search(r"\bFAIL\b", out, flags=re.IGNORECASE):
                scores["validator_script_runs"] = 1.0
        except Exception:
            pass

    validation_txt_path = workspace / "out" / "validation.txt"
    validation_txt = safe_read_text(validation_txt_path) or ""
    if validation_txt:
        if re.search(r"\bPASS\b", validation_txt, flags=re.IGNORECASE) or re.search(r"\bFAIL\b", validation_txt, flags=re.IGNORECASE):
            scores["validation_output_captured"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()