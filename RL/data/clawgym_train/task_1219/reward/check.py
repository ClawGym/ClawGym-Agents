import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _safe_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _parse_time_to_minutes(t: str) -> Optional[int]:
    # t is "HH:MM"; if t == "00:00", return 0
    if not isinstance(t, str):
        return None
    m = re.fullmatch(r"(\d{2}):(\d{2})", t.strip())
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return None
    return h * 60 + mi


def _minutes_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    # intervals [a_start, a_end), [b_start, b_end)
    return max(a_start, b_start) < min(a_end, b_end)


def _parse_human_date_time(date_str: str) -> Optional[str]:
    # Accept formats like "18 October 2024" or "19 Oct 2024"
    date_str = _normalize_space(date_str)
    # Remove weekday if present (e.g., "Friday, ")
    date_str = re.sub(r"^[A-Za-z]+,\s*", "", date_str)
    # Map months
    months = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", date_str)
    if not m:
        return None
    day = int(m.group(1))
    month_str = m.group(2).lower()
    year = int(m.group(3))
    month = months.get(month_str)
    if not month:
        return None
    try:
        dt = datetime(year, month, day)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_time_range(time_range: str) -> Optional[Tuple[str, str]]:
    # Accept "18:30–21:00" or "10:00-19:00"
    time_range = time_range.strip()
    sep = "–" if "–" in time_range else "-"
    parts = [p.strip() for p in time_range.split(sep)]
    if len(parts) != 2:
        return None
    s, e = parts
    if not re.fullmatch(r"\d{2}:\d{2}", s) or not re.fullmatch(r"\d{2}:\d{2}", e):
        return None
    return s, e


def _extract_expected_from_inputs(workspace: Path) -> Optional[Dict]:
    # Parse the provided input files to compute expected sessions and fields
    # Returns dict with keys: sessions (list of dict), contacts (brand->email), calendar (list of dict)
    press_dir = workspace / "input" / "press_kits"
    blog_path = workspace / "input" / "blog_audience.md"  # not strictly needed for evaluation
    cal_path = workspace / "input" / "calendar.csv"
    contacts_path = workspace / "input" / "contacts.csv"

    # Ensure minimum existence
    if not press_dir.exists() or not cal_path.exists() or not contacts_path.exists():
        return None

    # Contacts
    contacts_rows = _read_csv_dicts(contacts_path)
    if contacts_rows is None:
        return None
    contacts = {}
    for r in contacts_rows:
        brand = _normalize_space(r.get("brand", ""))
        email = _normalize_space(r.get("contact_email", ""))
        if brand and email:
            contacts[brand] = email

    # Calendar
    cal_rows = _read_csv_dicts(cal_path)
    if cal_rows is None:
        return None
    calendar = []
    for r in cal_rows:
        date = _normalize_space(r.get("date", ""))
        st = _normalize_space(r.get("start_time", ""))
        et = _normalize_space(r.get("end_time", ""))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and re.fullmatch(r"\d{2}:\d{2}", st) and re.fullmatch(r"\d{2}:\d{2}", et):
            calendar.append({"date": date, "start_time": st, "end_time": et})

    # Press kits parsing
    sessions = []

    # 1) Atelier Nebbia HTML
    nebbia_path = press_dir / "atelier_nebbia_fw24.html"
    nebbia_html = _read_text(nebbia_path)
    if nebbia_html:
        # Event title in <h1>
        m_title = re.search(r"<h1>(.*?)</h1>", nebbia_html, re.DOTALL | re.IGNORECASE)
        event_title = _normalize_space(m_title.group(1)) if m_title else ""
        m_brand = re.search(r"<strong>\s*Brand:\s*</strong>\s*([^<]+)", nebbia_html, re.IGNORECASE)
        brand = _normalize_space(m_brand.group(1)) if m_brand else ""
        m_tier = re.search(r"<strong>\s*Invite\s+tier:\s*</strong>\s*([^<]+)", nebbia_html, re.IGNORECASE)
        invite_tier = _normalize_space(m_tier.group(1)) if m_tier else ""
        m_dt = re.search(r"<strong>\s*Date\s*&\s*Time:\s*</strong>\s*([^<]+)", nebbia_html, re.IGNORECASE)
        dt_text = _normalize_space(m_dt.group(1)) if m_dt else ""
        # Example: "Friday, 18 October 2024, 18:30–21:00"
        date_part = None
        time_part = None
        if dt_text:
            parts = [p.strip() for p in dt_text.split(",")]
            # look for part with year, and part with HH:MM
            # We expect parts like ["Friday", "18 October 2024", "18:30–21:00"]
            for p in parts:
                if re.search(r"\d{4}", p) and not re.search(r"\d{2}:\d{2}", p):
                    date_part = p
                if re.search(r"\d{2}:\d{2}\s*[–-]\s*\d{2}:\d{2}", p):
                    time_part = p
        date_iso = _parse_human_date_time(date_part) if date_part else ""
        times = _parse_time_range(time_part) if time_part else None
        start_time = times[0] if times else ""
        end_time = times[1] if times else ""
        m_loc = re.search(r"<strong>\s*Location:\s*</strong>\s*([^<]+)", nebbia_html, re.IGNORECASE)
        location = _normalize_space(m_loc.group(1)) if m_loc else ""
        m_rsvp = re.search(r"<strong>\s*RSVP:\s*</strong>\s*RSVP by\s*([^<]+)", nebbia_html, re.IGNORECASE)
        rsvp_text = _normalize_space(m_rsvp.group(1)) if m_rsvp else ""
        rsvp_iso = _parse_human_date_time(rsvp_text) if rsvp_text else ""
        # Highlights
        highlights = re.findall(r"<li>(.*?)</li>", nebbia_html, re.IGNORECASE | re.DOTALL)
        highlights = [_normalize_space(h) for h in highlights if _normalize_space(h)]

        sessions.append({
            "brand": brand,
            "event_title": event_title,
            "date": date_iso,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "invite_tier": invite_tier,
            "rsvp_deadline": rsvp_iso,
            "has_multiple_claims": len(highlights) >= 2
        })

    # 2) Casa Vicenza MD
    casa_path = press_dir / "casa_vicenza_popup.md"
    casa_md = _read_text(casa_path)
    if casa_md:
        # H1
        m_title = re.search(r"^\s*#\s+(.*)$", casa_md, re.MULTILINE)
        event_title = _normalize_space(m_title.group(1)) if m_title else ""
        m_brand = re.search(r"\*\*Brand:\*\*\s*(.+)", casa_md)
        brand = _normalize_space(m_brand.group(1)) if m_brand else ""
        # When: two lines starting with "- "
        when_lines = re.findall(r"^\s*-\s*(Saturday|Sunday)\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}),\s*([0-9]{2}:[0-9]{2}\s*[–-]\s*[0-9]{2}:[0-9]{2})\s*$", casa_md, re.MULTILINE)
        # Where
        m_where = re.search(r"\*\*Where:\*\*\s*(.+)", casa_md)
        location = _normalize_space(m_where.group(1)) if m_where else ""
        # Access
        m_acc = re.search(r"\*\*Access:\*\*\s*(.+)", casa_md)
        invite_tier = _normalize_space(m_acc.group(1)) if m_acc else ""
        # RSVP: Optional (no deadline)
        m_rsvp = re.search(r"\*\*RSVP:\*\*\s*(.+)", casa_md)
        rsvp_text = _normalize_space(m_rsvp.group(1)) if m_rsvp else ""
        rsvp_iso = ""  # optional, no deadline -> empty
        # Claims bullets under **Claims:**
        claims_section = re.split(r"\*\*Claims:\*\*", casa_md)
        has_multiple_claims = False
        if len(claims_section) > 1:
            claim_lines = re.findall(r"^\s*-\s*(.+)$", claims_section[1], re.MULTILINE)
            if len([_normalize_space(c) for c in claim_lines if _normalize_space(c)]) >= 2:
                has_multiple_claims = True

        for day_name, date_human, time_range in when_lines:
            date_iso = _parse_human_date_time(date_human)
            times = _parse_time_range(time_range)
            start_time = times[0] if times else ""
            end_time = times[1] if times else ""
            sessions.append({
                "brand": brand,
                "event_title": event_title,
                "date": date_iso,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "invite_tier": invite_tier,
                "rsvp_deadline": rsvp_iso,
                "has_multiple_claims": has_multiple_claims
            })

    # 3) Spazio Montello JSON
    spazio_path = press_dir / "spazio_montello_invite.json"
    spazio_json = _read_text(spazio_path)
    if spazio_json:
        try:
            data = json.loads(spazio_json)
            brand = _normalize_space(data.get("brand", ""))
            event_title = _normalize_space(data.get("event_title", ""))
            start = _normalize_space(data.get("start", ""))
            end = _normalize_space(data.get("end", ""))
            location = _normalize_space(data.get("location", ""))
            invite_tier = _normalize_space(data.get("invite_tier", ""))
            highlights = data.get("highlights", [])
            rsvp_deadline = _normalize_space(data.get("rsvp_deadline", ""))
            # Convert start to date/time
            # Expect "2024-10-18T22:00"
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", start)
            if m:
                date_iso = m.group(1)
                start_time = m.group(2)
            else:
                date_iso = ""
                start_time = ""
            m2 = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", end)
            if m2:
                end_time = m2.group(2)
            else:
                end_time = ""
            sessions.append({
                "brand": brand,
                "event_title": event_title,
                "date": date_iso,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "invite_tier": invite_tier,
                "rsvp_deadline": rsvp_deadline,
                "has_multiple_claims": True if isinstance(highlights, list) and len(highlights) >= 2 else False
            })
        except Exception:
            pass

    return {"sessions": sessions, "contacts": contacts, "calendar": calendar}


def _compute_calendar_conflicts(rows: List[Dict[str, str]], calendar: List[Dict[str, str]]) -> Dict[Tuple[str, str, str, str], bool]:
    # returns mapping from (brand,date,start_time,end_time) -> conflict bool
    result = {}
    for r in rows:
        date = _normalize_space(r.get("date", ""))
        st = _normalize_space(r.get("start_time", ""))
        et = _normalize_space(r.get("end_time", ""))
        brand = _normalize_space(r.get("brand", ""))
        key = (brand, date, st, et)
        conflict = False
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) and re.fullmatch(r"\d{2}:\d{2}", st) and re.fullmatch(r"\d{2}:\d{2}", et):
            st_min = _parse_time_to_minutes(st)
            et_min = _parse_time_to_minutes(et)
            # Treat 00:00 as end of day (24:00) for end time if end == 00:00 and st != 00:00
            if et_min == 0 and st_min is not None and st_min != 0:
                et_min = 24 * 60
            if st_min is not None and et_min is not None and st_min < et_min:
                for c in calendar:
                    if c.get("date") == date:
                        cs = _parse_time_to_minutes(c.get("start_time", ""))
                        ce = _parse_time_to_minutes(c.get("end_time", ""))
                        if cs is not None and ce is not None and cs < ce:
                            if _minutes_overlap(st_min, et_min, cs, ce):
                                conflict = True
                                break
        result[key] = conflict
    return result


def _find_row(rows: List[Dict[str, str]], brand: str, date: str, st: str, et: str) -> Optional[Dict[str, str]]:
    for r in rows:
        if _normalize_space(r.get("brand", "")) == brand and _normalize_space(r.get("date", "")) == date and _normalize_space(r.get("start_time", "")) == st and _normalize_space(r.get("end_time", "")) == et:
            return r
    return None


def _expected_timestamp(date: str, time: str) -> str:
    return date.replace("-", "") + "-" + time.replace(":", "")


def _message_candidate_paths(messages_dir: Path, brand: str, date: str, time: str, decision: str) -> List[Path]:
    timestamp = _expected_timestamp(date, time)
    # Two variants: spaces preserved, or spaces replaced with underscores
    brand_space = brand
    brand_underscores = brand.replace(" ", "_")
    files = [
        messages_dir / f"{brand_space}_{timestamp}_{decision}.txt",
        messages_dir / f"{brand_underscores}_{timestamp}_{decision}.txt",
    ]
    # Also consider removing special characters that are unlikely in filenames
    brand_simple = re.sub(r"[^A-Za-z0-9_ ]", "", brand_space)
    files.append(messages_dir / f"{brand_simple}_{timestamp}_{decision}.txt")
    files.append(messages_dir / f"{brand_simple.replace(' ', '_')}_{timestamp}_{decision}.txt")
    # Deduplicate
    seen = set()
    unique = []
    for p in files:
        if p.as_posix() not in seen:
            seen.add(p.as_posix())
            unique.append(p)
    return unique


def _read_message(messages_dir: Path, brand: str, date: str, time: str, decision: str) -> Optional[Tuple[Path, str]]:
    for p in _message_candidate_paths(messages_dir, brand, date, time, decision):
        text = _read_text(p)
        if text is not None:
            return p, text
    return None


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ingest_log_exists": 0.0,
        "ingest_log_lists_all_files": 0.0,
        "ingest_log_marks_missing_details": 0.0,
        "events_review_exists": 0.0,
        "events_review_header_exact": 0.0,
        "events_review_rows_count_expected": 0.0,
        "events_rows_brand_date_time_match": 0.0,
        "event_titles_match_expected": 0.0,
        "locations_match_expected": 0.0,
        "rsvp_deadlines_correct": 0.0,
        "contact_email_join_correct": 0.0,
        "conflicts_detection_correct": 0.0,
        "suitability_score_in_range_all": 0.0,
        "decision_valid_values_all": 0.0,
        "rationale_present_concise_all": 0.0,
        "theme_and_key_claims_present": 0.0,
        "messages_exist_for_each_row": 0.0,
        "message_filenames_format_valid": 0.0,
        "acceptance_messages_content_requirements": 0.0,
        "decline_messages_content_requirements": 0.0,
    }

    expected = _extract_expected_from_inputs(workspace)
    press_files = [
        "atelier_nebbia_fw24.html",
        "casa_vicenza_popup.md",
        "spazio_montello_invite.json",
    ]

    # 1) Ingest log checks
    ingest_log_path = workspace / "outputs" / "ingest_log.txt"
    ingest_text = _read_text(ingest_log_path)
    if ingest_text is not None:
        scores["ingest_log_exists"] = 1.0
        # lists all files
        listed_all = True
        for fname in press_files:
            if fname not in ingest_text:
                listed_all = False
                break
        scores["ingest_log_lists_all_files"] = 1.0 if listed_all else 0.0
        # missing RSVP for Casa Vicenza should be marked as a warning
        # Look for line with "Casa Vicenza" or filename and "rsvp" and either "missing" or "no deadline" and "warn"
        lower_text = ingest_text.lower()
        casa_marker = ("casa vicenza" in lower_text) or ("casa_vicenza_popup.md" in lower_text)
        has_warning = False
        if casa_marker:
            # require rsvp and (missing or no deadline) and warning
            if ("rsvp" in lower_text) and (("missing" in lower_text) or ("no deadline" in lower_text)) and (("warning" in lower_text) or ("warn" in lower_text)):
                has_warning = True
        scores["ingest_log_marks_missing_details"] = 1.0 if has_warning else 0.0

    # 2) Events review CSV checks
    events_csv_path = workspace / "outputs" / "events_review.csv"
    rows = _read_csv_dicts(events_csv_path)
    if rows is not None:
        scores["events_review_exists"] = 1.0
        # header exact
        try:
            with events_csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip("\n\r")
        except Exception:
            header_line = ""
        expected_header = "brand,event_title,date,start_time,end_time,location,invite_tier,theme_or_highlights,rsvp_deadline,key_claims,contact_email,conflicts_with_calendar,suitability_score,decision,rationale"
        scores["events_review_header_exact"] = 1.0 if header_line == expected_header else 0.0

        # Compute expected sessions from inputs
        if expected is not None:
            expected_sessions = expected["sessions"]
            contacts_map = expected["contacts"]
            calendar = expected["calendar"]
        else:
            expected_sessions = []
            contacts_map = {}
            calendar = []

        # Count rows expected
        if expected_sessions:
            scores["events_review_rows_count_expected"] = 1.0 if len(rows) == len(expected_sessions) else 0.0

            # For matching rows by brand/date/time and verifying titles, locations, RSVP deadlines
            all_match = True
            titles_ok = True
            locs_ok = True
            rsvps_ok = True
            contacts_ok = True
            conflicts_ok = True
            suitability_ok = True
            decision_ok = True
            rationale_ok = True
            theme_key_ok = True

            # Build conflicts expected map
            # Build a temp rows clone with only necessary fields
            eval_rows = []
            for r in rows:
                eval_rows.append({
                    "brand": _normalize_space(r.get("brand", "")),
                    "date": _normalize_space(r.get("date", "")),
                    "start_time": _normalize_space(r.get("start_time", "")),
                    "end_time": _normalize_space(r.get("end_time", "")),
                })
            expected_conflicts = _compute_calendar_conflicts(eval_rows, calendar)

            # Iterate each expected session and find row
            for s in expected_sessions:
                brand = s.get("brand", "")
                date = s.get("date", "")
                st = s.get("start_time", "")
                et = s.get("end_time", "")
                row = _find_row(rows, brand, date, st, et)
                if row is None:
                    all_match = False
                    titles_ok = False
                    locs_ok = False
                    rsvps_ok = False
                    contacts_ok = False
                    conflicts_ok = False
                    suitability_ok = False
                    decision_ok = False
                    rationale_ok = False
                    theme_key_ok = False
                    continue
                # Event title match expected exact (strict)
                evt_title = _normalize_space(row.get("event_title", ""))
                if evt_title != _normalize_space(s.get("event_title", "")):
                    titles_ok = False
                # Location
                if _normalize_space(row.get("location", "")) != _normalize_space(s.get("location", "")):
                    locs_ok = False
                # RSVP deadline: exact match; Casa Vicenza expected empty, others as parsed
                if _normalize_space(row.get("rsvp_deadline", "")) != _normalize_space(s.get("rsvp_deadline", "")):
                    rsvps_ok = False
                # Contact email join correct
                expected_email = contacts_map.get(brand, "")
                if _normalize_space(row.get("contact_email", "")) != expected_email:
                    contacts_ok = False
                # Conflicts detection
                key = (brand, date, st, et)
                expected_conflict = expected_conflicts.get(key, False)
                conflict_str = _normalize_space(row.get("conflicts_with_calendar", "")).lower()
                if expected_conflict and conflict_str != "yes":
                    conflicts_ok = False
                if (not expected_conflict) and conflict_str != "no":
                    conflicts_ok = False
                # Suitability score in [0,100]
                sc = _safe_float(_normalize_space(row.get("suitability_score", "")))
                if sc is None or sc < 0 or sc > 100:
                    suitability_ok = False
                # Decision valid values
                decision = _normalize_space(row.get("decision", "")).lower()
                if decision not in {"cover", "skip"}:
                    decision_ok = False
                # Rationale present concise, single-sentence heuristic
                rationale = _normalize_space(row.get("rationale", ""))
                # Ends with punctuation and length words between 8 and 40
                wcount = _word_count(rationale)
                if not rationale or not re.search(r"[\.!\?]\s*$", rationale) or wcount < 8 or wcount > 40:
                    rationale_ok = False
                # theme_or_highlights and key_claims presence
                theme = _normalize_space(row.get("theme_or_highlights", ""))
                key_claims = _normalize_space(row.get("key_claims", ""))
                if not theme or not key_claims:
                    theme_key_ok = False
                # For items with multiple claims, ensure semicolon-separated presence
                if s.get("has_multiple_claims", False):
                    if ";" not in key_claims:
                        theme_key_ok = False

            scores["events_rows_brand_date_time_match"] = 1.0 if all_match else 0.0
            scores["event_titles_match_expected"] = 1.0 if titles_ok else 0.0
            scores["locations_match_expected"] = 1.0 if locs_ok else 0.0
            scores["rsvp_deadlines_correct"] = 1.0 if rsvps_ok else 0.0
            scores["contact_email_join_correct"] = 1.0 if contacts_ok else 0.0
            scores["conflicts_detection_correct"] = 1.0 if conflicts_ok else 0.0
            scores["suitability_score_in_range_all"] = 1.0 if suitability_ok else 0.0
            scores["decision_valid_values_all"] = 1.0 if decision_ok else 0.0
            scores["rationale_present_concise_all"] = 1.0 if rationale_ok else 0.0
            scores["theme_and_key_claims_present"] = 1.0 if theme_key_ok else 0.0

        # 3) Messages checks
        messages_dir = workspace / "outputs" / "messages"
        messages_exist_ok = True
        filenames_format_ok = True
        acceptance_ok = True
        decline_ok = True
        if expected is not None and rows:
            for r in rows:
                brand = _normalize_space(r.get("brand", ""))
                date = _normalize_space(r.get("date", ""))
                st = _normalize_space(r.get("start_time", ""))
                decision = _normalize_space(r.get("decision", "")).lower()
                # Existence
                msg = _read_message(messages_dir, brand, date, st, decision)
                if msg is None:
                    messages_exist_ok = False
                    filenames_format_ok = False
                    if decision == "cover":
                        acceptance_ok = False
                    elif decision == "skip":
                        decline_ok = False
                    continue
                path, content = msg
                # Filename format check: contains expected timestamp and correct decision
                expected_ts = _expected_timestamp(date, st)
                if expected_ts not in path.name or not path.name.endswith(f"_{decision}.txt"):
                    filenames_format_ok = False
                # Content checks
                if decision == "cover":
                    # 120–180 words, mention event title, date (YYYY-MM-DD), time HH:MM, and location substring
                    wc = _word_count(content)
                    if wc < 120 or wc > 180:
                        acceptance_ok = False
                    evt_title = _normalize_space(r.get("event_title", ""))
                    location = _normalize_space(r.get("location", ""))
                    if evt_title and evt_title not in content:
                        acceptance_ok = False
                    if date not in content or st not in content:
                        acceptance_ok = False
                    if location and (location not in content):
                        acceptance_ok = False
                elif decision == "skip":
                    wc = _word_count(content)
                    if wc < 80 or wc > 140:
                        decline_ok = False
                    # Must include clear reason and polite tone
                    low = content.lower()
                    reason_ok = any(k in low for k in ["fit", "conflict", "schedule", "audience", "overlap"])
                    polite_ok = ("thank" in low) or ("appreciate" in low)
                    if not (reason_ok and polite_ok):
                        decline_ok = False
                else:
                    # invalid decision; handled earlier
                    pass

        scores["messages_exist_for_each_row"] = 1.0 if messages_exist_ok else 0.0
        scores["message_filenames_format_valid"] = 1.0 if filenames_format_ok else 0.0
        scores["acceptance_messages_content_requirements"] = 1.0 if acceptance_ok else 0.0
        scores["decline_messages_content_requirements"] = 1.0 if decline_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()