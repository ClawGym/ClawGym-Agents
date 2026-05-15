import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_messages(messages_dir: Path) -> List[Dict[str, str]]:
    results = []
    if not messages_dir.exists() or not messages_dir.is_dir():
        return results
    for p in sorted(messages_dir.glob("*.txt")):
        text = _safe_read_text(p)
        if not text:
            continue
        from_val = None
        rsvp_val = None
        song_val = None
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key_l = key.strip().lower()
            val = val.strip()
            if key_l == "from":
                from_val = val
            elif key_l == "rsvp":
                rsvp_val = val.strip().lower()
            elif key_l == "favorite song":
                song_val = val
        if from_val is None or rsvp_val is None or song_val is None:
            # Skip malformed messages
            continue
        if rsvp_val not in {"yes", "no", "maybe"}:
            # Skip unexpected RSVP categories
            continue
        results.append({"from": from_val, "rsvp": rsvp_val, "song": song_val})
    return results


def _compute_expected_from_messages(messages: List[Dict[str, str]]) -> Tuple[Dict[str, int], List[str], List[Tuple[str, int]]]:
    totals = {"yes": 0, "no": 0, "maybe": 0}
    for m in messages:
        r = m["rsvp"]
        totals[r] = totals.get(r, 0) + 1
    yes_names = sorted([m["from"] for m in messages if m["rsvp"] == "yes"])
    song_counts = Counter([m["song"] for m in messages])
    # Sort by count desc, then title asc
    ranked = sorted(song_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return totals, yes_names, ranked


def _parse_next_steps(next_steps_text: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    planned_date = None
    location = None
    action_items: List[str] = []
    lines = next_steps_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("planned date:"):
            planned_date = line.split(":", 1)[1].strip()
        elif line.strip().lower().startswith("location:"):
            location = line.split(":", 1)[1].strip()
        elif line.strip().lower().startswith("action items"):
            # The following lines until next header are items (starting with '-')
            for j in range(i + 1, len(lines)):
                l2 = lines[j]
                if l2.strip().startswith("#"):
                    break
                if l2.strip().startswith("-"):
                    item = l2.strip()
                    # remove leading "- " if present
                    if item.startswith("- "):
                        item = item[2:].strip()
                    elif item.startswith("-"):
                        item = item[1:].strip()
                    if item:
                        action_items.append(item)
    return planned_date, location, action_items


def _extract_sections(md_text: str, titles: List[str]) -> Dict[str, List[str]]:
    # Sections recognized by lines that equal the title (ignoring optional leading '#', spaces)
    sections: Dict[str, List[str]] = {t: [] for t in titles}
    current: Optional[str] = None
    for line in md_text.splitlines():
        stripped = line.strip()
        # Normalize header lines like "## Overview"
        m = re.match(r'^\s*#*\s*(.+?)\s*$', line)
        header_name = stripped.lstrip("#").strip()
        if header_name in titles:
            current = header_name
            continue
        if current:
            # Stop on encountering another header not in our list but marked by '#'
            if stripped.startswith("#") and header_name not in titles:
                current = None
            else:
                sections[current].append(line)
    return sections


def _parse_totals_from_text(text: str) -> Optional[Tuple[int, int, int]]:
    # Look for yes: X, maybe: Y, no: Z in any order; we will capture each
    yes = maybe = no = None
    # Search across entire text
    # Case-insensitive keys, but digits capture
    patterns = {
        "yes": re.compile(r'\byes\s*:\s*(\d+)\b', re.IGNORECASE),
        "maybe": re.compile(r'\bmaybe\s*:\s*(\d+)\b', re.IGNORECASE),
        "no": re.compile(r'\bno\s*:\s*(\d+)\b', re.IGNORECASE),
    }
    m_yes = patterns["yes"].search(text)
    m_maybe = patterns["maybe"].search(text)
    m_no = patterns["no"].search(text)
    if m_yes:
        yes = int(m_yes.group(1))
    if m_maybe:
        maybe = int(m_maybe.group(1))
    if m_no:
        no = int(m_no.group(1))
    if yes is None or maybe is None or no is None:
        return None
    return (yes, maybe, no)


def _parse_names_from_section(lines: List[str]) -> List[str]:
    # Accept bullet lines or plain lines; also accept comma-separated
    gathered: List[str] = []
    # Join lines with commas to split; but also gather from separate lines
    blob = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Strip bullets
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("* "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("-"):
            stripped = stripped[1:].strip()
        elif stripped.startswith("*"):
            stripped = stripped[1:].strip()
        blob.append(stripped)
    # Combine and split by comma
    combined = ", ".join(blob)
    parts = [p.strip() for p in combined.split(",") if p.strip()]
    for p in parts:
        gathered.append(p)
    return gathered


def _parse_songs_from_section(lines: List[str]) -> Optional[List[Tuple[str, int]]]:
    items: List[Tuple[str, int]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Remove bullet marker if present
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("* "):
            stripped = stripped[2:].strip()
        # Attempt to parse "Title: N" or "Title - N" or "Title : N"
        m = re.match(r'^(.*?)\s*[:\-]\s*(\d+)\s*$', stripped)
        if not m:
            # Fallback: last number in line
            m2 = re.search(r'(.+?)\s+(\d+)\s*$', stripped)
            if not m2:
                return None
            title = m2.group(1).strip()
            try:
                count = int(m2.group(2))
            except Exception:
                return None
        else:
            title = m.group(1).strip()
            try:
                count = int(m.group(2))
            except Exception:
                return None
        if not title:
            return None
        items.append((title, count))
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_exists": 0.0,
        "summary_overview_section_valid": 0.0,
        "summary_totals_section_correct": 0.0,
        "summary_yes_names_section_correct": 0.0,
        "summary_favorite_songs_section_correct": 0.0,
        "email_subject_and_accent_correct": 0.0,
        "email_summary_totals_present_and_correct": 0.0,
        "email_includes_phrase_humble_fan": 0.0,
        "email_includes_meeting_details_from_next_steps": 0.0,
        "email_includes_yes_names_comma_list": 0.0,
        "email_totals_match_summary": 0.0,
        "email_names_match_summary": 0.0,
    }

    # Load inputs
    draft_path = workspace / "input" / "draft_email.txt"
    next_steps_path = workspace / "input" / "next_steps.md"
    messages_dir = workspace / "input" / "messages"

    next_steps_text = _safe_read_text(next_steps_path) or ""
    planned_date, location, action_items = _parse_next_steps(next_steps_text)

    messages = _parse_messages(messages_dir)
    totals, yes_names, ranked_songs = _compute_expected_from_messages(messages)

    # Output files
    summary_path = workspace / "output" / "status_summary.md"
    email_path = workspace / "output" / "fanclub_update_email.txt"

    summary_text = _safe_read_text(summary_path)
    email_text = _safe_read_text(email_path)

    # summary_file_exists
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0

    # Summary sections validation
    if summary_text:
        section_titles = ["Overview", "Totals", "Yes – Names", "Favorite Songs (ranked)"]
        sections = _extract_sections(summary_text, section_titles)

        # Overview: one sentence; mentions Sarah Àlainn and the three RSVP totals
        overview_lines = [ln for ln in sections.get("Overview", []) if ln.strip()]
        if len(overview_lines) == 1:
            overview_line = overview_lines[0]
            has_name = "Sarah Àlainn" in overview_line
            # Check contains the numeric totals (as digits) for yes, maybe, no
            has_yes = str(totals["yes"]) in overview_line
            has_maybe = str(totals["maybe"]) in overview_line
            has_no = str(totals["no"]) in overview_line
            if has_name and has_yes and has_maybe and has_no:
                scores["summary_overview_section_valid"] = 1.0

        # Totals section listing yes, maybe, no with correct numbers
        totals_section_text = "\n".join(sections.get("Totals", []))
        parsed_totals = _parse_totals_from_text(totals_section_text)
        if parsed_totals is not None:
            yes_v, maybe_v, no_v = parsed_totals
            if yes_v == totals["yes"] and maybe_v == totals["maybe"] and no_v == totals["no"]:
                scores["summary_totals_section_correct"] = 1.0

        # Yes – Names section: alphabetical, exact match to expected yes_names
        names_list = _parse_names_from_section(sections.get("Yes – Names", []))
        if names_list:
            is_alpha = names_list == sorted(names_list)
            if is_alpha and names_list == yes_names:
                scores["summary_yes_names_section_correct"] = 1.0
        else:
            # If there are no yes RSVPs, ensure section allows empty list correctly
            if len(yes_names) == 0:
                scores["summary_yes_names_section_correct"] = 1.0

        # Favorite Songs (ranked) section: correct counts and order
        songs_list = _parse_songs_from_section(sections.get("Favorite Songs (ranked)", []))
        if songs_list is not None:
            expected_map = dict(ranked_songs)
            got_map = dict(songs_list)
            # Check same keys and counts
            if got_map == expected_map:
                # Verify order matches expected ranking order
                if [t for t, c in songs_list] == [t for t, c in ranked_songs]:
                    scores["summary_favorite_songs_section_correct"] = 1.0

    # Email checks
    if email_text:
        lines = email_text.splitlines()
        subject_line = lines[0].strip() if lines else ""
        required_subject_prefix = "Subject: Update: Sarah Àlainn Appreciation Meetup"
        has_required_subject = subject_line.startswith(required_subject_prefix)
        contains_accent = "Sarah Àlainn" in email_text
        contains_unaccented = "Sarah Alainn" in email_text
        if has_required_subject and contains_accent and not contains_unaccented:
            scores["email_subject_and_accent_correct"] = 1.0

        # Email includes replaced summary totals in form "yes: X, maybe: Y, no: Z" matching computed
        expected_summary_str = f"yes: {totals['yes']}, maybe: {totals['maybe']}, no: {totals['no']}"
        if expected_summary_str in email_text:
            scores["email_summary_totals_present_and_correct"] = 1.0

        # Email includes phrase "As a humble fan in Japan,"
        if "As a humble fan in Japan," in email_text:
            scores["email_includes_phrase_humble_fan"] = 1.0

        # Email includes meeting details and action items from next_steps.md
        details_ok = True
        # Require planned date value and location value to appear exactly as in next_steps
        if planned_date:
            if planned_date not in email_text:
                details_ok = False
        else:
            details_ok = False
        if location:
            if location not in email_text:
                details_ok = False
        else:
            details_ok = False
        # All action items
        if not action_items:
            details_ok = False
        else:
            for item in action_items:
                if item not in email_text:
                    details_ok = False
                    break
        if details_ok:
            scores["email_includes_meeting_details_from_next_steps"] = 1.0

        # Email includes names of confirmed attendees as comma-separated list
        yes_names_str = ", ".join(yes_names)
        if (len(yes_names) == 0 and (", " not in email_text)) or (len(yes_names) > 0 and yes_names_str in email_text):
            # For zero attendees, we don't require a comma-list substring
            if len(yes_names) == 0 or yes_names_str in email_text:
                scores["email_includes_yes_names_comma_list"] = 1.0

        # Consistency checks with summary.md if available
        if summary_text:
            # totals match summary
            section_titles = ["Overview", "Totals", "Yes – Names", "Favorite Songs (ranked)"]
            sections = _extract_sections(summary_text, section_titles)
            totals_section_text = "\n".join(sections.get("Totals", []))
            parsed_totals = _parse_totals_from_text(totals_section_text)
            if parsed_totals is not None:
                yes_v, maybe_v, no_v = parsed_totals
                summary_str = f"yes: {yes_v}, maybe: {maybe_v}, no: {no_v}"
                if summary_str in email_text:
                    scores["email_totals_match_summary"] = 1.0
            # names match summary (as a comma-separated list, same order)
            summary_names = _parse_names_from_section(sections.get("Yes – Names", []))
            summary_names_str = ", ".join(summary_names)
            if summary_names_str:
                if summary_names_str in email_text:
                    scores["email_names_match_summary"] = 1.0
            else:
                # If summary has no names, consider it matches if email does not contain any of the expected yes names
                if len(yes_names) == 0:
                    scores["email_names_match_summary"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()