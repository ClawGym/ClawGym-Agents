import json
import csv
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        records = []
        for r in rows[1:]:
            # Allow missing trailing fields by padding
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            rec = {header[i]: r[i] for i in range(len(header))}
            records.append(rec)
        return header, records
    except Exception:
        return None, None


def _tokenize(text: str):
    # Return set of lowercase tokens length >=4
    if not text:
        return set()
    return set(m.group(0).lower() for m in re.finditer(r"[A-Za-z]{4,}", text))


def _extract_transcripts(workspace: Path):
    transcripts_dir = workspace / "input" / "transcripts"
    tokens_map = {}
    filenames = set()
    if transcripts_dir.exists() and transcripts_dir.is_dir():
        for p in transcripts_dir.glob("*.txt"):
            content = _read_text(p) or ""
            tokens_map[p.name] = _tokenize(content)
            filenames.add(p.name)
    return filenames, tokens_map


def _find_section(text: str, header_name: str, all_headers: list) -> str:
    # Find section text following a header line containing header_name (case-insensitive)
    if not text:
        return ""
    lines = text.splitlines()
    lower_headers = [h.lower() for h in all_headers]
    start_idx = None
    for i, line in enumerate(lines):
        if header_name.lower() in line.strip().lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        lstrip = lines[j].strip().lower()
        # If another known header encountered, end section
        for h in lower_headers:
            if h in lstrip and lines[j].strip() != "":
                end_idx = j
                break
        if end_idx != len(lines):
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section


def _count_bullets(section_text: str) -> int:
    if not section_text:
        return 0
    count = 0
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith(("-", "*", "•")) or re.match(r"^\d+\.", s):
            count += 1
    return count


def _lines(section_text: str):
    return [l for l in (section_text.splitlines() if section_text else []) if l.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # Content plan CSV checks
        "content_plan_file_parseable": 0.0,
        "content_plan_header_match": 0.0,
        "content_plan_four_rows": 0.0,
        "content_plan_week_numbers_valid": 0.0,
        "content_plan_persona_valid": 0.0,
        "content_plan_channel_valid": 0.0,
        "content_plan_key_sources_valid": 0.0,
        "content_plan_theme_grounded": 0.0,
        "content_plan_cta_matches_persona": 0.0,
        "content_plan_titles_and_links_present": 0.0,
        # Notes checks
        "notes_file_present": 0.0,
        "notes_objectives_bullets_count": 0.0,
        "notes_objectives_brand_voice_keywords": 0.0,
        "notes_extracted_themes_citations_and_quotes": 0.0,
        "notes_proposed_episodes_coverage": 0.0,
        "notes_action_items_owners_and_due_weeks": 0.0,
        "notes_open_questions_count": 0.0,
        "notes_no_external_links": 0.0,
        # Email checks
        "email_file_present": 0.0,
        "email_subject_format": 0.0,
        "email_signoff_correct": 0.0,
        "email_single_question_present": 0.0,
        "email_two_transcript_refs": 0.0,
        "email_quote_with_filename": 0.0,
        "email_persona_cta_present": 0.0,
        "email_no_external_links": 0.0,
    }

    # Load inputs
    personas_path = workspace / "input" / "resources" / "audience_personas.json"
    brand_voice_path = workspace / "input" / "resources" / "brand_voice.md"
    personas = _load_json(personas_path)
    brand_voice = _read_text(brand_voice_path) or ""
    persona_keys = set(personas.keys()) if isinstance(personas, dict) else set()
    persona_ctas = set()
    if isinstance(personas, dict):
        for v in personas.values():
            if isinstance(v, dict) and "cta" in v and isinstance(v["cta"], str):
                persona_ctas.add(v["cta"])

    transcript_filenames, transcript_tokens_map = _extract_transcripts(workspace)

    # Content Plan CSV
    plan_path = workspace / "outputs" / "plan" / "content_plan.csv"
    expected_header = [
        "week_number",
        "theme",
        "episode_title",
        "societal_link",
        "primary_persona",
        "channel",
        "key_sources",
        "CTA",
    ]
    header, records = _parse_csv(plan_path)
    if header is not None and records is not None:
        scores["content_plan_file_parseable"] = 1.0
        # Header exact match
        if header == expected_header:
            scores["content_plan_header_match"] = 1.0
        # Exactly 4 rows
        if len(records) == 4:
            scores["content_plan_four_rows"] = 1.0
        # Week numbers validation
        try:
            weeks = []
            for r in records:
                wn = r.get("week_number", "").strip()
                # allow int strings
                weeks.append(int(wn))
            if sorted(weeks) == [1, 2, 3, 4] and len(set(weeks)) == 4:
                scores["content_plan_week_numbers_valid"] = 1.0
        except Exception:
            pass
        # Persona validity
        if records and persona_keys:
            persona_ok = all(r.get("primary_persona", "").strip() in persona_keys for r in records)
            if persona_ok:
                scores["content_plan_persona_valid"] = 1.0
        # Channel validity
        allowed_channels = {"Podcast", "Blog", "Newsletter", "Social"}
        if records:
            chan_ok = all(r.get("channel", "").strip() in allowed_channels for r in records)
            if chan_ok:
                scores["content_plan_channel_valid"] = 1.0
        # Key sources valid files
        if records and transcript_filenames:
            ks_ok = True
            for r in records:
                ks = r.get("key_sources", "")
                parts = [p.strip() for p in ks.split(";") if p.strip() != ""]
                if len(parts) == 0:
                    ks_ok = False
                    break
                for p in parts:
                    if p not in transcript_filenames:
                        ks_ok = False
                        break
                if not ks_ok:
                    break
            if ks_ok:
                scores["content_plan_key_sources_valid"] = 1.0
        # Theme grounded in sources
        if records and transcript_tokens_map:
            grounded = True
            for r in records:
                theme = r.get("theme", "") or ""
                theme_tokens = _tokenize(theme)
                ks = [p.strip() for p in (r.get("key_sources", "") or "").split(";") if p.strip()]
                combined = set()
                for k in ks:
                    combined |= transcript_tokens_map.get(k, set())
                # Require at least one overlapping token length>=4
                if not (theme_tokens & combined):
                    grounded = False
                    break
            if grounded:
                scores["content_plan_theme_grounded"] = 1.0
        # CTA matches persona
        if records and isinstance(personas, dict):
            cta_ok = True
            for r in records:
                persona = r.get("primary_persona", "").strip()
                cta = r.get("CTA", "").strip()
                expected_cta = None
                pdata = personas.get(persona)
                if isinstance(pdata, dict):
                    expected_cta = pdata.get("cta")
                if not expected_cta or cta != expected_cta:
                    cta_ok = False
                    break
            if cta_ok:
                scores["content_plan_cta_matches_persona"] = 1.0
        # Titles and societal_link nonempty
        if records:
            tl_ok = all((r.get("episode_title", "") or "").strip() != "" and (r.get("societal_link", "") or "").strip() != "" for r in records)
            if tl_ok:
                scores["content_plan_titles_and_links_present"] = 1.0

    # Notes
    notes_path = workspace / "outputs" / "notes" / "kickoff_meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        scores["notes_file_present"] = 1.0
        # No external links
        if ("http://" not in notes_text) and ("https://" not in notes_text):
            scores["notes_no_external_links"] = 1.0

        section_names = [
            "Objectives",
            "Extracted Themes",
            "Proposed Episodes Overview",
            "Action Items",
            "Open Questions",
        ]
        obj_sec = _find_section(notes_text, "Objectives", section_names)
        obj_bullets = _count_bullets(obj_sec)
        if 1 <= obj_bullets <= 3:
            scores["notes_objectives_bullets_count"] = 1.0
        # Objectives brand voice alignment: presence of at least one keyword
        brand_keywords = {"inquisitive", "empathetic", "historically", "inclusive", "precise", "active", "plain", "collaboration", "tone"}
        obj_words = _tokenize(obj_sec)
        if brand_keywords & obj_words:
            scores["notes_objectives_brand_voice_keywords"] = 1.0

        # Extracted Themes: at least 6 lines with a transcript filename and a quoted snippet <=120 chars
        themes_sec = _find_section(notes_text, "Extracted Themes", section_names)
        theme_lines = _lines(themes_sec)
        valid_theme_entries = 0
        for line in theme_lines:
            if any(fn in line for fn in transcript_filenames):
                # Has a quoted snippet <=120 chars
                m = re.search(r'"([^"]{1,120})"', line)
                if m:
                    valid_theme_entries += 1
        if valid_theme_entries >= 6:
            scores["notes_extracted_themes_citations_and_quotes"] = 1.0

        # Proposed Episodes Overview coverage
        peo_sec = _find_section(notes_text, "Proposed Episodes Overview", section_names)
        # Load CSV again to fetch rows if available
        covered_all = False
        if records:
            # For each row, either theme or episode_title appears
            peo_lower = peo_sec.lower()
            coverage = []
            for r in records:
                theme = (r.get("theme", "") or "").lower()
                title = (r.get("episode_title", "") or "").lower()
                covered = (theme and theme in peo_lower) or (title and title in peo_lower)
                coverage.append(covered)
            if all(coverage):
                covered_all = True
            else:
                # Fallback: check Week 1..4 notation
                if all((f"week {i}" in peo_lower) for i in [1, 2, 3, 4]):
                    covered_all = True
        if covered_all:
            scores["notes_proposed_episodes_coverage"] = 1.0

        # Action Items: >=5, each with owner from list and due week 1-4
        ai_sec = _find_section(notes_text, "Action Items", section_names)
        ai_lines = _lines(ai_sec)
        owners = {"host", "producer", "researcher", "designer"}
        ai_valid = 0
        for line in ai_lines:
            l = line.lower()
            has_owner = any(o in l for o in owners)
            m = re.search(r"week\s*([1-4])", l)
            if has_owner and m:
                ai_valid += 1
        if ai_valid >= 5:
            scores["notes_action_items_owners_and_due_weeks"] = 1.0

        # Open Questions: >=2
        oq_sec = _find_section(notes_text, "Open Questions", section_names)
        oq_lines = _lines(oq_sec)
        if len(oq_lines) >= 2:
            scores["notes_open_questions_count"] = 1.0

    # Email
    email_path = workspace / "outputs" / "messaging" / "sponsor_outreach_email.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["email_file_present"] = 1.0
        # No external links
        if ("http://" not in email_text) and ("https://" not in email_text):
            scores["email_no_external_links"] = 1.0
        # Subject line format on first line
        first_line = email_text.splitlines()[0].strip() if email_text.splitlines() else ""
        if first_line.startswith("Subject: Partnership Idea: ") and len(first_line) > len("Subject: Partnership Idea: "):
            scores["email_subject_format"] = 1.0
        # Signoff
        if "Warmly, [Your Name]" in email_text:
            scores["email_signoff_correct"] = 1.0
        # One thoughtful question per outreach email: exactly one '?' in body (excluding subject line)
        lines = email_text.splitlines()
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        q_count = body.count("?")
        if q_count == 1:
            scores["email_single_question_present"] = 1.0
        # References at least two transcripts via bracketed filenames
        bracketed = re.findall(r"\[([^\]]+)\]", email_text)
        valid_refs = set([b for b in bracketed if b in transcript_filenames])
        if len(valid_refs) >= 2:
            scores["email_two_transcript_refs"] = 1.0
        # Contains a quoted snippet with the transcript filename in brackets
        found_quote_with_file = False
        for m in re.finditer(r'"([^"]{1,120})"\s*\[([^\]]+)\]', email_text):
            fname = m.group(2)
            if fname in transcript_filenames:
                found_quote_with_file = True
                break
        if found_quote_with_file:
            scores["email_quote_with_filename"] = 1.0
        # Contains a persona-aligned CTA
        if persona_ctas:
            if any(cta in email_text for cta in persona_ctas):
                scores["email_persona_cta_present"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()