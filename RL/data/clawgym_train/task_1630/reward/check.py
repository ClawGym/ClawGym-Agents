import json
import re
import sys
from pathlib import Path
from html import unescape


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _count_words(text: str) -> int:
    # Count word-like tokens (letters/digits/apostrophes/hyphens in words)
    tokens = re.findall(r"[A-Za-z0-9']+(?:-[A-Za-z0-9']+)?", text)
    return len(tokens)


def _normalize_time(t: str) -> str:
    if t is None:
        return ""
    t = t.strip()
    # Normalize en dash and em dash to hyphen
    t = t.replace("–", "-").replace("—", "-")
    # Remove extra spaces around hyphen
    t = re.sub(r"\s*-\s*", "-", t)
    return t


def _normalize_name(text: str) -> str:
    # Lowercase, remove non-letters, collapse spaces
    s = text.lower()
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_expected_metadata_from_html(html: str) -> dict:
    # Unescape basic HTML entities for consistent parsing
    doc = unescape(html)

    def _find_first(pattern: str, flags=0):
        m = re.search(pattern, doc, flags | re.S)
        return m.group(1).strip() if m else None

    # course_title
    course_title = _find_first(r"<h1>(.*?)</h1>")
    # provider
    provider = _find_first(r'<p class="provider">\s*<strong>\s*Provider:\s*</strong>\s*([^<]+)</p>')

    # table details
    details_section = _find_first(r"<section id=\"details\".*?<table>(.*?)</table>")
    semester = start_date = days_str = time_str = duration_str = location = fees = None
    if details_section:
        rows = re.findall(r"<tr>\s*<th>(.*?)</th>\s*<td>(.*?)</td>\s*</tr>", details_section, flags=re.S)
        mapping = {th.strip(): re.sub(r"\s+", " ", td.strip()) for th, td in rows}
        semester = mapping.get("Semester")
        start_date = mapping.get("Start date")
        days_str = mapping.get("Days")
        time_str = mapping.get("Time")
        duration_str = mapping.get("Duration")
        location = mapping.get("Location")
        fees = mapping.get("Fees")

    # days list
    days_list = []
    if days_str:
        tmp = days_str
        tmp = tmp.replace("&amp;", "&")
        tmp = tmp.replace(",", " & ")
        tmp = tmp.replace(" and ", " & ")
        parts = [p.strip() for p in tmp.split("&")]
        days_list = [p for p in parts if p]
    # duration weeks
    duration_weeks = None
    if duration_str:
        m = re.search(r"(\d+)\s*week", duration_str, flags=re.I)
        if m:
            try:
                duration_weeks = int(m.group(1))
            except Exception:
                duration_weeks = None

    # entry requirements
    entry_block = _find_first(r'<section id="entry".*?>(.*?)</section>')
    entry_requirements = []
    if entry_block:
        items = re.findall(r"<li>(.*?)</li>", entry_block, flags=re.S)
        entry_requirements = [re.sub(r"\s+", " ", unescape(re.sub(r"<.*?>", "", it)).strip()) for it in items]

    # supports
    support_block = _find_first(r'<section id="support".*?>(.*?)</section>')
    supports = []
    if support_block:
        ps = re.findall(r"<p>(.*?)</p>", support_block, flags=re.S)
        supports = [re.sub(r"\s+", " ", unescape(re.sub(r"<.*?>", "", p)).strip()) for p in ps if p.strip()]
        supports = [s for s in supports if s]

    # application section
    apply_block = _find_first(r'<section id="apply".*?>(.*?)</section>')
    application_contact_email = None
    contact_person = None
    if apply_block:
        m = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", apply_block)
        if m:
            application_contact_email = m.group(1)
        m2 = re.search(r"Contact:\s*<strong>([^<]+)</strong>", apply_block)
        if m2:
            contact_person = m2.group(1).strip()

    # last updated
    last_updated = _find_first(r"Last updated:\s*([^<]+)")

    # fee waiver boolean
    fee_waiver = False
    if fees and re.search(r"fee waiver", fees, flags=re.I):
        fee_waiver = True

    expected = {
        "course_title": course_title,
        "provider": provider,
        "semester": semester,
        "start_date": start_date,
        "days": days_list,
        "time": time_str,
        "duration_weeks": duration_weeks,
        "location": location,
        "fees": fees,
        "fee_waiver": fee_waiver,
        "entry_requirements": entry_requirements,
        "supports": supports,
        "application_contact_email": application_contact_email,
        "contact_person": contact_person,
        "last_updated": last_updated,
    }
    return expected


def _compare_metadata_values(student: dict, expected: dict) -> bool:
    # Strict comparison with minor normalization for time and days ordering
    # Check all keys present in expected
    for k in expected.keys():
        if k not in student:
            return False
    # course_title
    if (student.get("course_title") or "").strip() != (expected.get("course_title") or "").strip():
        return False
    if (student.get("provider") or "").strip() != (expected.get("provider") or "").strip():
        return False
    if (student.get("semester") or "").strip() != (expected.get("semester") or "").strip():
        return False
    if (student.get("start_date") or "").strip() != (expected.get("start_date") or "").strip():
        return False
    # days as set equality
    s_days = student.get("days")
    e_days = expected.get("days")
    if not isinstance(s_days, list) or not isinstance(e_days, list):
        return False
    if set([d.strip() for d in s_days]) != set([d.strip() for d in e_days]):
        return False
    # time with normalization of dash
    s_time = _normalize_time(student.get("time") or "")
    e_time = _normalize_time(expected.get("time") or "")
    if s_time != e_time:
        return False
    # duration_weeks
    if student.get("duration_weeks") != expected.get("duration_weeks"):
        return False
    # location
    if (student.get("location") or "").strip() != (expected.get("location") or "").strip():
        return False
    # fees
    if (student.get("fees") or "").strip() != (expected.get("fees") or "").strip():
        return False
    # fee_waiver
    if bool(student.get("fee_waiver")) != bool(expected.get("fee_waiver")):
        return False
    # entry_requirements
    if student.get("entry_requirements") != expected.get("entry_requirements"):
        return False
    # supports
    if student.get("supports") != expected.get("supports"):
        return False
    # application_contact_email (allow None or exact)
    if (student.get("application_contact_email") or None) != (expected.get("application_contact_email") or None):
        return False
    # contact_person
    if (student.get("contact_person") or None) != (expected.get("contact_person") or None):
        return False
    # last_updated
    if (student.get("last_updated") or "").strip() != (expected.get("last_updated") or "").strip():
        return False
    return True


def _validate_metadata_structure(student: dict) -> bool:
    # Required keys and expected types; allow None for two keys as per spec
    must_keys = [
        "course_title",
        "provider",
        "semester",
        "start_date",
        "days",
        "time",
        "duration_weeks",
        "location",
        "fees",
        "fee_waiver",
        "entry_requirements",
        "supports",
        "application_contact_email",
        "contact_person",
        "last_updated",
    ]
    for k in must_keys:
        if k not in student:
            return False
    # Type checks
    if not isinstance(student.get("course_title"), str):
        return False
    if not isinstance(student.get("provider"), str):
        return False
    if not isinstance(student.get("semester"), str):
        return False
    if not isinstance(student.get("start_date"), str):
        return False
    if not isinstance(student.get("days"), list):
        return False
    if not all(isinstance(d, str) for d in student.get("days", [])):
        return False
    if not isinstance(student.get("time"), str):
        return False
    if not isinstance(student.get("duration_weeks"), int):
        return False
    if not isinstance(student.get("location"), str):
        return False
    if not isinstance(student.get("fees"), str):
        return False
    if not isinstance(student.get("fee_waiver"), bool):
        return False
    if not isinstance(student.get("entry_requirements"), list):
        return False
    if not all(isinstance(e, str) for e in student.get("entry_requirements", [])):
        return False
    if not isinstance(student.get("supports"), list):
        return False
    if not all(isinstance(s, str) for s in student.get("supports", [])):
        return False
    # Allow application_contact_email and contact_person to be str or None
    ace = student.get("application_contact_email")
    cp = student.get("contact_person")
    if ace is not None and not isinstance(ace, str):
        return False
    if cp is not None and not isinstance(cp, str):
        return False
    if not isinstance(student.get("last_updated"), str):
        return False
    return True


def _letter_references_required_details(letter: str, metadata: dict) -> bool:
    text = letter
    # course_title
    ct = (metadata.get("course_title") or "").strip()
    if not ct or re.search(re.escape(ct), text, flags=re.I) is None:
        return False
    # start_date
    sd = (metadata.get("start_date") or "").strip()
    if not sd or re.search(re.escape(sd), text, flags=re.I) is None:
        return False
    # days: must include both day names
    days = metadata.get("days") or []
    # We expect Tuesday and Thursday specifically for this HTML
    required_days = set([d.lower() for d in days])
    for d in required_days:
        if re.search(r"\b" + re.escape(d) + r"\b", text, flags=re.I) is None:
            return False
    # time
    t = metadata.get("time") or ""
    # Accept both en dash and hyphen versions
    t_norm = _normalize_time(t)
    # Check for either
    time_ok = False
    if re.search(re.escape(t), text, flags=re.I):
        time_ok = True
    elif re.search(re.escape(t_norm), _normalize_time(text), flags=re.I):
        time_ok = True
    if not time_ok:
        return False
    # location
    loc = (metadata.get("location") or "").strip()
    if not loc or re.search(re.escape(loc), text, flags=re.I) is None:
        return False
    return True


def _salutation_uses_contact_person(letter: str, contact_person: str) -> bool:
    if not contact_person:
        return False
    # Check presence of "Dear" and contact person name
    if re.search(r"\bDear\b", letter, flags=re.I) is None:
        return False
    norm_letter = _normalize_name(letter)
    norm_cp = _normalize_name(contact_person)
    # Require both first and last names to appear if available
    parts = norm_cp.split()
    if len(parts) >= 2:
        return all(p in norm_letter for p in parts[:2])
    else:
        return parts[0] in norm_letter if parts else False


def _detect_used_fields_in_letter(letter: str, metadata: dict) -> set:
    detected = set()
    text = letter
    # Helper to check literal inclusion case-insensitive
    def has(substr: str) -> bool:
        if not substr:
            return False
        return re.search(re.escape(substr.strip()), text, flags=re.I) is not None

    if has(metadata.get("course_title")):
        detected.add("course_title")
    if has(metadata.get("provider")):
        detected.add("provider")
    if has(metadata.get("semester")):
        detected.add("semester")
    if has(metadata.get("start_date")):
        detected.add("start_date")
    # days: require both day names
    days = metadata.get("days") or []
    if isinstance(days, list) and days:
        if all(re.search(r"\b" + re.escape(d) + r"\b", text, flags=re.I) for d in days):
            detected.add("days")
    # time: accept normalized time as well
    t = metadata.get("time") or ""
    if has(t) or (_normalize_time(t) and _normalize_time(t) in _normalize_time(text)):
        detected.add("time")
    # duration_weeks: look for "10 week"
    dw = metadata.get("duration_weeks")
    if isinstance(dw, int) and re.search(rf"\b{dw}\s*week", text, flags=re.I):
        detected.add("duration_weeks")
    if has(metadata.get("location")):
        detected.add("location")
    # fees: look for exact fee amount or whole fees string
    if has(metadata.get("fees")) or re.search(r"€\s*50", text):
        detected.add("fees")
    # fee_waiver: look for phrase
    if re.search(r"\bfee waiver\b", text, flags=re.I):
        detected.add("fee_waiver")
    # application_contact_email present in letter?
    if metadata.get("application_contact_email") and has(metadata.get("application_contact_email")):
        detected.add("application_contact_email")
    # contact_person name
    if metadata.get("contact_person"):
        cp = metadata.get("contact_person")
        if re.search(re.escape(cp), text, flags=re.I):
            detected.add("contact_person")
        else:
            # Allow normalized matching (apostrophes)
            if _normalize_name(cp) in _normalize_name(text):
                detected.add("contact_person")
    if has(metadata.get("last_updated")):
        detected.add("last_updated")

    # entry_requirements and supports: include if any item appears
    er = metadata.get("entry_requirements") or []
    if isinstance(er, list) and any(has(item) for item in er):
        detected.add("entry_requirements")
    sp = metadata.get("supports") or []
    if isinstance(sp, list) and any(has(item) for item in sp):
        detected.add("supports")

    return detected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "metadata_file_exists": 0.0,
        "metadata_required_keys_present": 0.0,
        "metadata_types_valid": 0.0,
        "metadata_values_correct": 0.0,
        "letter_file_exists": 0.0,
        "letter_word_count_range": 0.0,
        "letter_references_key_details": 0.0,
        "salutation_uses_contact_person": 0.0,
        "waiver_mentioned_if_applicable": 0.0,
        "tailoring_notes_file_exists": 0.0,
        "tailoring_notes_word_count_matches": 0.0,
        "tailoring_notes_missing_fields_correct": 0.0,
        "tailoring_notes_used_fields_cover_required": 0.0,
    }

    # Check script exists
    script_path = workspace / "scripts" / "generate_application_letter.py"
    if script_path.is_file():
        scores["script_exists"] = 1.0

    # Load input HTML to compute expected
    input_html_path = workspace / "input" / "program_page.html"
    html_text = _read_text_safe(input_html_path)
    expected_meta = _extract_expected_metadata_from_html(html_text) if html_text else {}

    # Metadata JSON
    metadata_path = workspace / "output" / "program_metadata.json"
    metadata = _load_json_safe(metadata_path)
    if metadata is not None and isinstance(metadata, dict):
        scores["metadata_file_exists"] = 1.0
        # Required keys present?
        required_keys = [
            "course_title",
            "provider",
            "semester",
            "start_date",
            "days",
            "time",
            "duration_weeks",
            "location",
            "fees",
            "fee_waiver",
            "entry_requirements",
            "supports",
            "application_contact_email",
            "contact_person",
            "last_updated",
        ]
        if all(k in metadata for k in required_keys):
            scores["metadata_required_keys_present"] = 1.0
        # Types valid
        if _validate_metadata_structure(metadata):
            scores["metadata_types_valid"] = 1.0
        # Values correct (strict, based on provided HTML)
        if expected_meta and _compare_metadata_values(metadata, expected_meta):
            scores["metadata_values_correct"] = 1.0
    else:
        # metadata missing or invalid
        pass

    # Letter
    letter_path = workspace / "output" / "application_letter_en.md"
    letter_text = _read_text_safe(letter_path)
    if letter_text:
        scores["letter_file_exists"] = 1.0
        wc = _count_words(letter_text)
        if 400 <= wc <= 550:
            scores["letter_word_count_range"] = 1.0
        # Reference checks depend on metadata if present; fall back to expected if not
        meta_for_letter = metadata if isinstance(metadata, dict) else expected_meta
        if meta_for_letter and _letter_references_required_details(letter_text, meta_for_letter):
            scores["letter_references_key_details"] = 1.0
        # Salutation uses contact person if available in metadata
        contact_person = None
        if isinstance(meta_for_letter, dict):
            contact_person = meta_for_letter.get("contact_person")
        if contact_person:
            if _salutation_uses_contact_person(letter_text, contact_person):
                scores["salutation_uses_contact_person"] = 1.0
        else:
            # If no contact_person present, don't penalize; leave as 0.0
            pass
        # Waiver mention if applicable
        fee_waiver_flag = None
        if isinstance(meta_for_letter, dict):
            fee_waiver_flag = meta_for_letter.get("fee_waiver")
        if fee_waiver_flag is True:
            if re.search(r"\bfee waiver\b", letter_text, flags=re.I) and (
                re.search(r"\brefugee\b", letter_text, flags=re.I) or re.search(r"\basylum", letter_text, flags=re.I)
            ):
                scores["waiver_mentioned_if_applicable"] = 1.0
        elif fee_waiver_flag is False:
            # Not required; consider pass
            scores["waiver_mentioned_if_applicable"] = 1.0
        else:
            # Unknown; cannot assess reliably -> leave 0.0
            pass

    # Tailoring notes
    notes_path = workspace / "output" / "tailoring_notes.json"
    notes = _load_json_safe(notes_path)
    if isinstance(notes, dict):
        scores["tailoring_notes_file_exists"] = 1.0
        # Check word_count matches actual letter word count
        if letter_text:
            wc = _count_words(letter_text)
            if isinstance(notes.get("word_count"), int) and notes.get("word_count") == wc:
                scores["tailoring_notes_word_count_matches"] = 1.0
        # Check missing_fields aligns with metadata actual missing/nulls
        if isinstance(metadata, dict):
            required_keys = [
                "course_title",
                "provider",
                "semester",
                "start_date",
                "days",
                "time",
                "duration_weeks",
                "location",
                "fees",
                "fee_waiver",
                "entry_requirements",
                "supports",
                "application_contact_email",
                "contact_person",
                "last_updated",
            ]
            actual_missing = []
            for k in required_keys:
                if k not in metadata:
                    actual_missing.append(k)
                    continue
                v = metadata.get(k)
                # Consider missing if None or empty list or empty string for fields sourced from HTML
                if v is None:
                    actual_missing.append(k)
                elif isinstance(v, str) and v.strip() == "":
                    actual_missing.append(k)
                elif isinstance(v, list) and len(v) == 0:
                    actual_missing.append(k)
            nf_notes = notes.get("missing_fields")
            if isinstance(nf_notes, list):
                if set(nf_notes) == set(actual_missing):
                    scores["tailoring_notes_missing_fields_correct"] = 1.0
        # Check used_fields covers required referenced keys
        if letter_text:
            meta_for_letter = metadata if isinstance(metadata, dict) else expected_meta
            detected = _detect_used_fields_in_letter(letter_text, meta_for_letter if isinstance(meta_for_letter, dict) else {})
            # Minimal required fields from requirements
            minimal = set()
            for k in ["course_title", "start_date", "days", "time", "location"]:
                if k in detected:
                    minimal.add(k)
            # If fee waiver mentioned, include it
            if "fee_waiver" in detected:
                minimal.add("fee_waiver")
            # If contact_person used in salutation, include it
            if "contact_person" in detected:
                minimal.add("contact_person")
            uf_notes = notes.get("used_fields")
            if isinstance(uf_notes, list):
                if minimal.issubset(set(uf_notes)):
                    scores["tailoring_notes_used_fields_cover_required"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()