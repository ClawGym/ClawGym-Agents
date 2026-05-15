import json
import csv
import re
import sys
from pathlib import Path
from typing import Tuple, List, Dict, Optional


def _read_text_safe(path: Path) -> Tuple[bool, str]:
    try:
        if not path.exists() or not path.is_file():
            return False, ""
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _load_json_safe(path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _load_csv_dicts_safe(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        if not path.exists() or not path.is_file():
            return False, []
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                clean = {}
                for k, v in r.items():
                    ck = (k or "").strip()
                    cv = (v or "").strip()
                    clean[ck] = cv
                rows.append(clean)
        return True, rows
    except Exception:
        return False, []


def _list_files(path: Path) -> Tuple[bool, List[str]]:
    try:
        if not path.exists() or not path.is_dir():
            return False, []
        files = [p.name for p in path.iterdir() if p.is_file()]
        return True, files
    except Exception:
        return False, []


def _first_line(text: str) -> str:
    lines = text.splitlines()
    return lines[0] if lines else ""


def _find_first_event(events: List[Dict[str, str]], kind: str) -> Optional[Dict[str, str]]:
    for e in events:
        if e.get("kind", "").strip().lower() == kind.lower():
            return e
    return None


def _extract_section(lines: List[str], start_keyword: str, end_keyword: Optional[str] = None) -> List[str]:
    start_idx = None
    end_idx = None
    lower_lines = [ln.lower() for ln in lines]
    for i, ln in enumerate(lower_lines):
        if start_keyword.lower() in ln and start_idx is None:
            start_idx = i
            break
    if start_idx is None:
        return []
    if end_keyword:
        for j in range(start_idx + 1, len(lines)):
            if end_keyword.lower() in lower_lines[j]:
                end_idx = j
                break
    if end_idx is None:
        end_idx = len(lines)
    return lines[start_idx:end_idx]


def _count_sentences_in_paragraph(paragraph: str) -> int:
    parts = re.split(r'[.!?]+', paragraph)
    count = 0
    for seg in parts:
        if seg and re.search(r'[A-Za-z]{2,}', seg):
            count += 1
    return count


def _has_external_links(text: str) -> bool:
    low = text.lower()
    return ("http://" in low) or ("https://" in low) or ("www." in low)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    out_dir = workspace / "out"
    email_path = out_dir / "email_draft.md"
    status_path = out_dir / "status_update.md"

    context_path = workspace / "input" / "context.json"
    events_path = workspace / "input" / "events.csv"
    artworks_path = workspace / "input" / "artworks.json"
    art_dir = workspace / "assets" / "images" / "new_works"

    scores = {
        "email_subject_first_line": 0.0,
        "email_subject_includes_month_label": 0.0,
        "email_greeting_friends_and_supporters": 0.0,
        "email_mentions_painting_and_purpose": 0.0,
        "email_at_a_glance_label_present": 0.0,
        "email_at_least_three_bullets": 0.0,
        "email_new_works_count_correct": 0.0,
        "email_includes_all_new_work_titles": 0.0,
        "email_mentions_exhibition_title_and_date": 0.0,
        "email_mentions_workshop_title_and_date": 0.0,
        "email_invites_rsvp_or_reply_without_links": 0.0,
        "status_has_required_sections": 0.0,
        "status_highlights_new_works_bullet_exact": 0.0,
        "status_highlights_mentions_exhibition_title": 0.0,
        "status_upcoming_mentions_workshop_title": 0.0,
        "status_reflective_note_2_to_3_sentences": 0.0,
        "no_external_links_in_outputs": 0.0,
    }

    # Load inputs
    ok_ctx, ctx = _load_json_safe(context_path)
    month_label = ""
    if ok_ctx and isinstance(ctx, dict):
        month_label = str(ctx.get("month_label", "")).strip()

    ok_events, events_rows = _load_csv_dicts_safe(events_path)
    exhibition = _find_first_event(events_rows, "exhibition") if ok_events else None
    workshop = _find_first_event(events_rows, "workshop") if ok_events else None
    ex_title = exhibition.get("title", "").strip() if exhibition else ""
    ex_date = exhibition.get("date", "").strip() if exhibition else ""
    wk_title = workshop.get("title", "").strip() if workshop else ""
    wk_date = workshop.get("date", "").strip() if workshop else ""

    ok_art_json, artworks = _load_json_safe(artworks_path)
    artwork_map: Dict[str, str] = {}
    if ok_art_json and isinstance(artworks, dict):
        for w in artworks.get("new_works", []):
            fn = str(w.get("filename", "")).strip()
            title = str(w.get("title", "")).strip()
            if fn and title:
                artwork_map[fn] = title

    ok_files, present_files = _list_files(art_dir)
    present_files_set = set(present_files) if ok_files else set()
    n_new_works = len(present_files_set)

    # Email checks
    ok_email, email_text = _read_text_safe(email_path)
    if ok_email:
        # Subject on first line
        first_ln = _first_line(email_text)
        subj_match = re.match(r'^\s*Subject\s*:\s*(.+)\s*$', first_ln, flags=re.IGNORECASE)
        if subj_match:
            scores["email_subject_first_line"] = 1.0
            subj_content = subj_match.group(1)
            if month_label and month_label in subj_content:
                scores["email_subject_includes_month_label"] = 1.0

        # Greeting "friends and supporters"
        if re.search(r'\bfriends and supporters\b', email_text, flags=re.IGNORECASE):
            scores["email_greeting_friends_and_supporters"] = 1.0

        # Painting and purpose words
        low_email = email_text.lower()
        if "painting" in low_email and "purpose" in low_email:
            scores["email_mentions_painting_and_purpose"] = 1.0

        # At-a-glance label
        if re.search(r'at-?\s*a-?\s*glance', email_text, flags=re.IGNORECASE):
            scores["email_at_a_glance_label_present"] = 1.0

        # Bullets count (lines starting with "- ")
        bullets = [ln for ln in email_text.splitlines() if ln.strip().startswith("- ")]
        if len(bullets) >= 3:
            scores["email_at_least_three_bullets"] = 1.0

        # New works count present
        if n_new_works > 0 and str(n_new_works) in email_text:
            scores["email_new_works_count_correct"] = 1.0

        # Include all new work titles (map present filenames to titles from artworks.json)
        if present_files_set and artwork_map:
            titles_expected = []
            missing_map = False
            for fn in present_files_set:
                if fn in artwork_map:
                    titles_expected.append(artwork_map[fn])
                else:
                    missing_map = True
                    break
            if not missing_map and titles_expected and all(title in email_text for title in titles_expected):
                scores["email_includes_all_new_work_titles"] = 1.0

        # Exhibition title and date present
        if ex_title and ex_date and (ex_title in email_text) and (ex_date in email_text):
            scores["email_mentions_exhibition_title_and_date"] = 1.0

        # Workshop title and date present
        if wk_title and wk_date and (wk_title in email_text) and (wk_date in email_text):
            scores["email_mentions_workshop_title_and_date"] = 1.0

        # RSVP or reply invite without links
        invite_present = bool(re.search(r'\b(rsvp|reply)\b', email_text, flags=re.IGNORECASE))
        no_links = not _has_external_links(email_text)
        if invite_present and no_links:
            scores["email_invites_rsvp_or_reply_without_links"] = 1.0

    # Status update checks
    ok_status, status_text = _read_text_safe(status_path)
    if ok_status:
        low_status = status_text.lower()
        has_highlights = "highlights" in low_status
        has_upcoming = "upcoming commitments" in low_status
        if has_highlights and has_upcoming:
            scores["status_has_required_sections"] = 1.0

        status_lines = status_text.splitlines()
        highlights_sec = _extract_section(status_lines, "highlights", "upcoming commitments")
        upcoming_sec = _extract_section(status_lines, "upcoming commitments", None)

        # New works bullet exact in Highlights: line should be exactly "New works: N" (allow optional bullet marker)
        if highlights_sec:
            pat = re.compile(r'^\s*(?:[-*•]\s*)?new\s*works\s*:\s*' + re.escape(str(n_new_works)) + r'\s*$', flags=re.IGNORECASE)
            if any(pat.search(ln) for ln in highlights_sec):
                scores["status_highlights_new_works_bullet_exact"] = 1.0

        # Exhibition title mentioned in Highlights
        if highlights_sec and ex_title:
            if any(ex_title in ln for ln in highlights_sec):
                scores["status_highlights_mentions_exhibition_title"] = 1.0

        # Workshop title in Upcoming commitments
        if upcoming_sec and wk_title:
            if any(wk_title in ln for ln in upcoming_sec):
                scores["status_upcoming_mentions_workshop_title"] = 1.0

        # Reflective note 2–3 sentences: find any non-heading paragraph with 2 or 3 sentences
        paragraphs = [p for p in re.split(r'\n\s*\n', status_text) if p.strip()]
        reflective_ok = False
        for p in paragraphs:
            if re.search(r'\bhighlights\b', p, flags=re.IGNORECASE) or re.search(r'\bupcoming commitments\b', p, flags=re.IGNORECASE):
                continue
            n_sent = _count_sentences_in_paragraph(p)
            if 2 <= n_sent <= 3:
                reflective_ok = True
                break
        if reflective_ok:
            scores["status_reflective_note_2_to_3_sentences"] = 1.0

    # No external links in outputs combined
    all_text = ""
    if ok_email:
        all_text += email_text + "\n"
    if ok_status:
        all_text += status_text
    if all_text and not _has_external_links(all_text):
        scores["no_external_links_in_outputs"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()