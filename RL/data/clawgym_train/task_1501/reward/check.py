import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from datetime import date, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_minimal_yaml_settings(path: Path) -> dict:
    """
    Minimal YAML parser for the expected settings.yaml structure:
      - input_dir: str
      - output_dir: str
      - today: YYYY-MM-DD (string)
      - days_ahead: int
      - questions_to_ask: list of strings
    Ignores comments and extra keys.
    """
    settings = {}
    if not path.exists():
        return settings
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return settings
    current_list_key = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            # Start of a block (likely list)
            key = stripped[:-1].strip()
            current_list_key = key
            settings[key] = []
            continue
        if stripped.startswith("-"):
            if current_list_key:
                item = stripped[1:].strip()
                # Remove optional surrounding quotes
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                settings[current_list_key].append(item)
            continue
        # key: value
        current_list_key = None
        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # Try to parse int
            if re.fullmatch(r"-?\d+", val):
                try:
                    val_parsed = int(val)
                except Exception:
                    val_parsed = val
            else:
                val_parsed = val
            settings[key] = val_parsed
    return settings


def _parse_md_sections(content: str):
    """
    Parse Markdown content into ordered H2 sections.
    Returns:
      - titles: list of section titles in order (H2 '## ')
      - sections: dict title -> list of lines (content lines between this H2 and next H2)
    """
    lines = content.splitlines()
    titles = []
    indices = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            title = line[3:].strip()
            titles.append(title)
            indices.append(i)
    sections = {}
    for idx, title in enumerate(titles):
        start = indices[idx] + 1
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        sections[title] = lines[start:end]
    return titles, sections


def _extract_bullet_items(lines):
    """
    Extract items from Markdown bullet lines starting with '- ' (allow leading spaces).
    Returns a list of item strings with the leading marker removed and stripped.
    """
    items = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("- "):
            items.append(s[2:].strip())
    return items


def _parse_faqs_input(path: Path):
    """
    Parse Q/A pairs from input/faqs.md which follow:
      Q: question
      A: answer
    Returns list of (question, answer) in order.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    faqs = []
    current_q = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Q:"):
            current_q = line[2:].strip()
        elif line.startswith("A:") and current_q:
            faqs.append((current_q, line[2:].strip()))
            current_q = None
    return faqs


def _safe_date_from_iso(s: str):
    try:
        parts = s.strip().split("T")[0]
        return date.fromisoformat(parts)
    except Exception:
        return None


def _compute_expected_events(calendar_csv: Path, today_str: str, days_ahead: int):
    """
    Compute expected top 3 events within [today, today+days_ahead], inclusive,
    sorted ascending by date. Returns list of dicts with event, date (YYYY-MM-DD), notes.
    """
    today_dt = _safe_date_from_iso(today_str) if isinstance(today_str, str) else None
    if today_dt is None:
        return None
    horizon = today_dt + timedelta(days=days_ahead)
    events = []
    try:
        with calendar_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Expect columns: event, date, notes
            for row in reader:
                d = _safe_date_from_iso(row.get("date", ""))
                if d is None:
                    continue
                if today_dt <= d <= horizon:
                    events.append({
                        "event": row.get("event", "").strip(),
                        "date": d.isoformat(),
                        "notes": row.get("notes", "").strip()
                    })
    except Exception:
        return None
    events.sort(key=lambda x: x["date"])
    return events[:3]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_run_success": 0.0,
        "notes_file_created": 0.0,
        "sections_titles_and_order": 0.0,
        "overview_has_name_and_location": 0.0,
        "programs_match": 0.0,
        "facilities_match": 0.0,
        "admissions_contact_present": 0.0,
        "upcoming_dates_top3_match": 0.0,
        "faqs_pairs_present": 0.0,
        "action_items_exact_match": 0.0,
    }

    # Attempt to run the script as specified
    script_path = workspace / "tools" / "generate_notes.py"
    if script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            if proc.returncode == 0:
                scores["script_run_success"] = 1.0
        except Exception:
            pass

    # Load inputs to compute expected results
    cfg_path = workspace / "config" / "settings.yaml"
    settings = _parse_minimal_yaml_settings(cfg_path)

    input_dir_name = settings.get("input_dir", "input")
    output_dir_name = settings.get("output_dir", "output")
    today_val = settings.get("today", "")
    days_ahead_val = settings.get("days_ahead", 0)
    if not isinstance(today_val, str):
        # Accept non-str by converting to string if it's date-like; otherwise set empty to fail downstream checks
        try:
            today_val = str(today_val)
        except Exception:
            today_val = ""
    try:
        days_ahead_int = int(days_ahead_val)
    except Exception:
        days_ahead_int = 0

    input_dir = workspace / input_dir_name
    output_dir = workspace / output_dir_name

    profile = _load_json(input_dir / "college_profile.json")
    faqs_expected = _parse_faqs_input(input_dir / "faqs.md")
    expected_events = _compute_expected_events(input_dir / "calendar.csv", today_val, days_ahead_int)

    # Locate output file
    out_file = output_dir / "meeting_notes.md"
    notes_text = _read_text(out_file)
    if notes_text:
        scores["notes_file_created"] = 1.0

    # Determine section titles and content
    titles, sections = _parse_md_sections(notes_text) if notes_text else ([], {})
    expected_titles = [
        "College Overview",
        "Programs",
        "Facilities",
        "Admissions Contact",
        "Upcoming Dates",
        "FAQs",
        "Action Items",
    ]
    if titles == expected_titles:
        scores["sections_titles_and_order"] = 1.0

    # College Overview: must include name and location fields
    # Require both the college name and the location tokens (village, district, state) present in this section.
    overview_ok = False
    if profile and "College Overview" in sections:
        overview_lines = sections.get("College Overview", [])
        overview_text = "\n".join(overview_lines)
        name = (profile.get("name") or "").strip()
        loc = profile.get("location") or {}
        village = (loc.get("village") or "").strip()
        district = (loc.get("district") or "").strip()
        state = (loc.get("state") or "").strip()
        # Check all required substrings present within the section
        if all(s for s in [name, village, district, state]):
            if (name in overview_text) and (village in overview_text) and (district in overview_text) and (state in overview_text):
                overview_ok = True
    scores["overview_has_name_and_location"] = 1.0 if overview_ok else 0.0

    # Programs list: exactly the programs, no extras (order not mandated)
    programs_ok = False
    if profile and "Programs" in sections:
        expected_programs = list(profile.get("programs") or [])
        got_programs = _extract_bullet_items(sections.get("Programs", []))
        # exact multiset match irrespective of order
        if len(got_programs) == len(expected_programs) and sorted(got_programs) == sorted(expected_programs):
            programs_ok = True
    scores["programs_match"] = 1.0 if programs_ok else 0.0

    # Facilities list: exactly the facilities, no extras (order not mandated)
    facilities_ok = False
    if profile and "Facilities" in sections:
        expected_facilities = list(profile.get("facilities") or [])
        got_facilities = _extract_bullet_items(sections.get("Facilities", []))
        if len(got_facilities) == len(expected_facilities) and sorted(got_facilities) == sorted(expected_facilities):
            facilities_ok = True
    scores["facilities_match"] = 1.0 if facilities_ok else 0.0

    # Admissions Contact: must include email and phone
    admissions_ok = False
    if profile and "Admissions Contact" in sections:
        adm = profile.get("admissions") or {}
        email = (adm.get("email") or "").strip()
        phone = (adm.get("phone") or "").strip()
        adm_text = "\n".join(sections.get("Admissions Contact", []))
        if email and phone and (email in adm_text) and (phone in adm_text):
            admissions_ok = True
    scores["admissions_contact_present"] = 1.0 if admissions_ok else 0.0

    # Upcoming Dates: top 3 events within window, ascending by date; each with event, date, notes
    upcoming_ok = False
    if expected_events is not None and "Upcoming Dates" in sections:
        sec_lines = sections.get("Upcoming Dates", [])
        # Identify candidate lines containing ISO date patterns
        date_line_indices = []
        for i, ln in enumerate(sec_lines):
            if re.search(r"\b\d{4}-\d{2}-\d{2}\b", ln):
                date_line_indices.append(i)
        # Must be exactly len(expected_events) lines with dates
        if len(date_line_indices) == len(expected_events):
            # For each expected event in order, ensure there is a corresponding line with all substrings, and in order
            match_indices = []
            success = True
            start_search = 0
            for ev in expected_events:
                found_idx = -1
                for j in range(start_search, len(sec_lines)):
                    ln = sec_lines[j]
                    if (ev["date"] in ln) and (ev["event"] in ln) and (ev["notes"] in ln):
                        found_idx = j
                        break
                if found_idx == -1:
                    success = False
                    break
                match_indices.append(found_idx)
                start_search = found_idx + 1
            if success:
                # Ensure indices are strictly increasing (preserving ascending order)
                if match_indices == sorted(match_indices):
                    upcoming_ok = True
    scores["upcoming_dates_top3_match"] = 1.0 if upcoming_ok else 0.0

    # FAQs: all Q/A pairs present in order as adjacent lines (Q then A)
    faqs_ok = False
    if faqs_expected is not None and "FAQs" in sections:
        sec_lines = sections.get("FAQs", [])
        # Normalize lines for searching
        # For each expected pair, find adjacent lines with substrings
        success = True
        start_idx = 0
        for q, a in faqs_expected:
            found = False
            for i in range(start_idx, len(sec_lines) - 1):
                if (q in sec_lines[i]) and (a in sec_lines[i + 1]):
                    found = True
                    start_idx = i + 2
                    break
            if not found:
                success = False
                break
        if success:
            faqs_ok = True
    scores["faqs_pairs_present"] = 1.0 if faqs_ok else 0.0

    # Action Items: exactly questions_to_ask list in order
    action_ok = False
    if "Action Items" in sections and isinstance(settings.get("questions_to_ask"), list):
        expected_questions = settings.get("questions_to_ask", [])
        items = _extract_bullet_items(sections.get("Action Items", []))
        if items == expected_questions:
            action_ok = True
    scores["action_items_exact_match"] = 1.0 if action_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()