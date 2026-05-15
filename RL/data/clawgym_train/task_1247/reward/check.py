import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_banned_terms(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    terms = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        terms.append(s)
    return terms


def _split_captions(raw: str) -> List[str]:
    token = "\n---\n"
    if token in raw:
        parts = [c.strip() for c in raw.split(token)]
        return parts
    return [raw.strip()] if raw.strip() else []


def _count_sentences(text: str) -> int:
    # Simple sentence segmentation based on ., !, ?
    # Count segments with at least one alphanumeric character
    segments = re.split(r'[.!?]+(?:\s+|$)', text.strip())
    return sum(1 for s in segments if s.strip() and re.search(r'\w', s))


def _find_emojis(text: str) -> List[str]:
    # Collect common emoji ranges
    # Emoticons, pictographs, transport/map symbols, supplemental symbols, etc.
    emoji_pattern = (
        r'['
        r'\U0001F300-\U0001F5FF'  # Misc Symbols and Pictographs
        r'\U0001F600-\U0001F64F'  # Emoticons
        r'\U0001F680-\U0001F6FF'  # Transport and Map
        r'\U0001F700-\U0001F77F'  # Alchemical
        r'\U0001F780-\U0001F7FF'  # Geometric Extended
        r'\U0001F800-\U0001F8FF'  # Supplemental Arrows-C
        r'\U0001F900-\U0001F9FF'  # Supplemental Symbols and Pictographs
        r'\U0001FA00-\U0001FAFF'  # Chess, Symbols Extended-A
        r'\U00002702-\U000027B0'  # Dingbats
        r'\U000024C2-\U0001F251'  # Enclosed characters
        r'\U00002600-\U000026FF'  # Misc symbols
        r']'
    )
    try:
        return re.findall(emoji_pattern, text)
    except re.error:
        # Narrow pattern for Python builds lacking wide Unicode
        narrow_pattern = r'[\u2600-\u26FF\u2700-\u27BF]'
        return re.findall(narrow_pattern, text)


def _banned_terms_found(text: str, terms: List[str]) -> List[str]:
    found = []
    for term in terms:
        if not term:
            continue
        pattern = r'\b' + re.escape(term) + r'\b'
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(term)
    # unique, sorted
    return sorted(list(set(found)))


def _has_first_person(text: str) -> bool:
    # Check for common first-person markers
    patterns = [
        r'\bI\b',
        r"\bI'm\b",
        r"\bI’m\b",  # curly apostrophe
        r'\bme\b',
        r'\bmy\b',
        r'\bmine\b',
    ]
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def _caption_matches_topic(caption: str, topic_index: int) -> bool:
    c = caption.lower()
    if topic_index == 0:
        # honey mask
        return ("honey" in c) and ("mask" in c)
    if topic_index == 1:
        # green tea toner
        return ("green tea" in c) and ("toner" in c)
    if topic_index == 2:
        # oatmeal cleanse
        has_oat = ("oatmeal" in c) or ("oats" in c)
        has_cleanse = ("cleanse" in c) or ("cleanser" in c) or ("cleansing" in c)
        return has_oat and has_cleanse
    return False


def _extract_section(text: str, header: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Extract section content between a header line and the next header.
    Returns (content_string, start_index, end_index). If not found, returns (None, None, None).
    Header matching allows markdown hashes and leading spaces.
    """
    lines = text.splitlines()
    pattern = re.compile(r'^\s*(?:#+\s*)?' + re.escape(header) + r'\s*$', flags=re.IGNORECASE)
    indices = [i for i, line in enumerate(lines) if pattern.match(line)]
    if not indices:
        return None, None, None
    start_line = indices[0] + 1
    # Find next header among the known three to delimit section
    headers = ["Summary:", "Edits by Caption:", "Action Items:"]
    header_patterns = [re.compile(r'^\s*(?:#+\s*)?' + re.escape(h) + r'\s*$', flags=re.IGNORECASE) for h in headers]
    end_line = len(lines)
    for i in range(start_line, len(lines)):
        if any(hp.match(lines[i]) for hp in header_patterns):
            end_line = i
            break
    content = "\n".join(lines[start_line:end_line]).strip()
    return content, start_line, end_line


def _section_bullets(section_text: str) -> List[str]:
    bullets = []
    for line in section_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped)
    return bullets


def _has_due_date(text: str) -> bool:
    # Recognize various due date formats
    patterns = [
        r'\b20\d{2}-\d{2}-\d{2}\b',  # YYYY-MM-DD
        r'\b\d{1,2}/\d{1,2}(?:/20\d{2})?\b',  # M/D or M/D/YYYY
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b',  # Month Day
        r'\b(?:Mon|Tue|Tues|Wed|Thu|Thur|Fri|Sat|Sun)(?:day)?\b',  # weekday name
        r'\bEOD\b',  # EOD marker
        r'\bCOB\b',  # COB marker
    ]
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "captions_file_exists": 0.0,
        "captions_separator_and_count": 0.0,
        "captions_lengths_within_range": 0.0,
        "captions_disclaimer_once_at_end": 0.0,
        "captions_emojis_allowed_and_count": 0.0,
        "captions_no_banned_terms": 0.0,
        "captions_topics_ordered": 0.0,
        "captions_first_person_voice": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_pass_zero_violations": 0.0,
        "validation_report_matches_content": 0.0,
        "meeting_notes_file_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_summary_2_to_4_sentences": 0.0,
        "meeting_notes_edits_by_caption_covered": 0.0,
        "meeting_notes_action_items_min3_owner_due": 0.0,
    }

    captions_path = workspace / "outputs" / "captions_final.md"
    banned_terms_path = workspace / "input" / "banned_terms.txt"
    config_path = workspace / "input" / "validation_config.json"
    report_path = workspace / "outputs" / "validation_report.json"
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"

    captions_raw = _safe_read_text(captions_path)
    config = _safe_load_json(config_path)
    banned_terms = _safe_load_banned_terms(banned_terms_path)

    if captions_raw is not None:
        scores["captions_file_exists"] = 1.0
        # Parse captions using the same split token as validator
        captions_list = _split_captions(captions_raw)
        # Check separator presence and count
        sep_ok = ("\n---\n" in captions_raw) and (len(captions_list) == 3)
        scores["captions_separator_and_count"] = 1.0 if sep_ok else 0.0

        # Load config for length/emojis/disclaimer
        if isinstance(config, dict):
            min_chars = int(config.get("min_chars", 0))
            max_chars = int(config.get("max_chars", 10**9))
            required_disclaimer = str(config.get("required_disclaimer", "")).strip()
            allowed_emojis = list(config.get("allowed_emojis", []))
            # Lengths
            lengths_ok = len(captions_list) == 3 and all(min_chars <= len(c) <= max_chars for c in captions_list)
            scores["captions_lengths_within_range"] = 1.0 if lengths_ok else 0.0

            # Disclaimer once and at end
            disc_ok = (
                len(captions_list) == 3 and
                all(c.count(required_disclaimer) == 1 and c.rstrip().endswith(required_disclaimer) for c in captions_list)
            )
            scores["captions_disclaimer_once_at_end"] = 1.0 if disc_ok else 0.0

            # Emojis allowed and count 1-2, and no disallowed emojis present
            emojis_ok = False
            if len(captions_list) == 3:
                per_cap_ok = []
                for c in captions_list:
                    allowed_count = sum(c.count(e) for e in allowed_emojis)
                    # find all emojis and ensure they are all from allowed set
                    all_emoji_chars = _find_emojis(c)
                    disallowed = [e for e in all_emoji_chars if e not in allowed_emojis]
                    per_cap_ok.append((1 <= allowed_count <= 2) and (len(disallowed) == 0))
                emojis_ok = all(per_cap_ok)
            scores["captions_emojis_allowed_and_count"] = 1.0 if emojis_ok else 0.0
        else:
            # Cannot validate without config
            scores["captions_lengths_within_range"] = 0.0
            scores["captions_disclaimer_once_at_end"] = 0.0
            scores["captions_emojis_allowed_and_count"] = 0.0

        # Banned terms absent
        if banned_terms is not None:
            if len(captions_list) == 3:
                banned_ok = all(len(_banned_terms_found(c, banned_terms)) == 0 for c in captions_list)
                scores["captions_no_banned_terms"] = 1.0 if banned_ok else 0.0
            else:
                scores["captions_no_banned_terms"] = 0.0
        else:
            scores["captions_no_banned_terms"] = 0.0

        # Topics ordered and focused
        topics_ok = len(captions_list) == 3 and all(_caption_matches_topic(captions_list[i], i) for i in range(3))
        scores["captions_topics_ordered"] = 1.0 if topics_ok else 0.0

        # First-person voice present in each caption
        fp_ok = len(captions_list) == 3 and all(_has_first_person(c) for c in captions_list)
        scores["captions_first_person_voice"] = 1.0 if fp_ok else 0.0
    else:
        # File missing; related checks remain 0.0
        pass

    # Validation report checks
    report = _safe_load_json(report_path)
    if report is not None:
        scores["validation_report_exists"] = 1.0
        overall_ok = (
            report.get("overall_status") == "pass" and
            report.get("violations_count") == 0 and
            report.get("total_captions") == 3 and
            isinstance(report.get("captions"), list) and
            all(c.get("status") == "pass" for c in report.get("captions", []))
        )
        scores["validation_report_pass_zero_violations"] = 1.0 if overall_ok else 0.0

        # Cross-check with current captions content if available
        validation_match_ok = False
        if captions_raw is not None and isinstance(config, dict) and banned_terms is not None:
            required_disclaimer = str(config.get("required_disclaimer", "")).strip()
            allowed_emojis = list(config.get("allowed_emojis", []))
            captions_list = _split_captions(captions_raw)
            # Build our own expected entries
            expected = []
            for idx, cap in enumerate(captions_list, start=1):
                char_count = len(cap)
                emoji_count = sum(cap.count(e) for e in allowed_emojis)
                disclaimer_count = cap.count(required_disclaimer) if required_disclaimer else 0
                banned_found = _banned_terms_found(cap, banned_terms)
                expected.append({
                    "index": idx,
                    "char_count": char_count,
                    "emoji_count": emoji_count,
                    "has_required_disclaimer": disclaimer_count == 1,
                    "disclaimer_count": disclaimer_count,
                    "banned_terms_found": banned_found,
                })
            # Compare lengths and fields with report
            rep_caps = report.get("captions", [])
            if len(expected) == len(rep_caps) == 3:
                all_match = True
                for e, r in zip(expected, rep_caps):
                    if not (
                        e["index"] == r.get("index") and
                        e["char_count"] == r.get("char_count") and
                        e["emoji_count"] == r.get("emoji_count") and
                        e["has_required_disclaimer"] == r.get("has_required_disclaimer") and
                        e["disclaimer_count"] == r.get("disclaimer_count") and
                        e["banned_terms_found"] == r.get("banned_terms_found")
                    ):
                        all_match = False
                        break
                validation_match_ok = all_match
        scores["validation_report_matches_content"] = 1.0 if validation_match_ok else 0.0
    else:
        # Missing or malformed report
        scores["validation_report_exists"] = 0.0
        scores["validation_report_pass_zero_violations"] = 0.0
        scores["validation_report_matches_content"] = 0.0

    # Meeting notes checks
    meeting_text = _safe_read_text(meeting_notes_path)
    if meeting_text is not None:
        scores["meeting_notes_file_exists"] = 1.0
        # Sections present
        summary_sec, _, _ = _extract_section(meeting_text, "Summary:")
        edits_sec, _, _ = _extract_section(meeting_text, "Edits by Caption:")
        actions_sec, _, _ = _extract_section(meeting_text, "Action Items:")

        sections_present = all(sec is not None for sec in (summary_sec, edits_sec, actions_sec))
        scores["meeting_notes_sections_present"] = 1.0 if sections_present else 0.0

        # Summary: 2–4 sentences
        if summary_sec is not None:
            sent_count = _count_sentences(summary_sec)
            scores["meeting_notes_summary_2_to_4_sentences"] = 1.0 if (2 <= sent_count <= 4) else 0.0
        else:
            scores["meeting_notes_summary_2_to_4_sentences"] = 0.0

        # Edits by Caption: bullet points per caption referencing each topic
        if edits_sec is not None:
            bullets = _section_bullets(edits_sec)
            # Require at least one bullet mentioning each topic
            def mentions_topic(lines: List[str], idx: int) -> bool:
                joined = "\n".join(lines).lower()
                if idx == 0:
                    return "honey" in joined
                if idx == 1:
                    return "green tea" in joined
                if idx == 2:
                    return ("oatmeal" in joined) or ("oats" in joined)
                return False

            edits_ok = len(bullets) >= 3 and all(mentions_topic(bullets, i) for i in range(3))
            scores["meeting_notes_edits_by_caption_covered"] = 1.0 if edits_ok else 0.0
        else:
            scores["meeting_notes_edits_by_caption_covered"] = 0.0

        # Action Items: at least 3, each with owner and due date
        if actions_sec is not None:
            action_bullets = _section_bullets(actions_sec)
            owners = re.compile(r'\b(Social|Legal|Creative)\b', flags=re.IGNORECASE)
            valid_items = 0
            for b in action_bullets:
                has_owner = owners.search(b) is not None
                has_due = _has_due_date(b)
                if has_owner and has_due:
                    valid_items += 1
            scores["meeting_notes_action_items_min3_owner_due"] = 1.0 if valid_items >= 3 else 0.0
        else:
            scores["meeting_notes_action_items_min3_owner_due"] = 0.0
    else:
        # Missing meeting notes
        pass

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()