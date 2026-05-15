import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(read_text_safe(path) or "")
    except Exception:
        return None


def load_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def extract_h1_and_date(md_text: str) -> Tuple[Optional[str], Optional[str]]:
    lines = md_text.splitlines()
    non_empty_idx = None
    for i, ln in enumerate(lines):
        if ln.strip():
            non_empty_idx = i
            break
    h1 = None
    date_line = None
    if non_empty_idx is not None and lines[non_empty_idx].startswith("# "):
        h1 = lines[non_empty_idx].rstrip("\n")
    # Search near top for a date line: "Date: YYYY-MM-DD"
    for i in range(0, min((non_empty_idx or 0) + 10, len(lines))):
        m = re.match(r"^Date:\s*\d{4}-\d{2}-\d{2}$", lines[i].strip())
        if m:
            date_line = lines[i].strip()
            break
    if date_line is None:
        # Fallback: search whole document if not found near top
        for ln in lines:
            m = re.match(r"^Date:\s*\d{4}-\d{2}-\d{2}$", ln.strip())
            if m:
                date_line = ln.strip()
                break
    return h1, date_line


def parse_sections(md_text: str) -> List[Tuple[str, int]]:
    lines = md_text.splitlines()
    sections = []
    section_re = re.compile(r"^##\s+(.*)\s*$")
    for idx, ln in enumerate(lines):
        m = section_re.match(ln)
        if m:
            sections.append((m.group(1).strip(), idx))
    return sections


def section_body_lines(md_text: str, title: str) -> List[str]:
    lines = md_text.splitlines()
    sections = parse_sections(md_text)
    starts = [i for (name, i) in sections if name == title]
    if not starts:
        return []
    start = starts[0] + 1
    next_idxs = [i for (_, i) in sections if i > start - 1]
    end = min(next_idxs) if next_idxs else len(lines)
    return lines[start:end]


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_newsletter_present": 0.0,
        "output_status_summary_present": 0.0,
        "h1_title_preserved": 0.0,
        "date_line_preserved": 0.0,
        "section_order_correct": 0.0,
        "editors_note_mentions_van_halen": 0.0,
        "gig_calendar_matches_csv": 0.0,
        "album_spotlight_includes_title_and_artist": 0.0,
        "resources_at_least_one_bullet": 0.0,
        "resources_no_placeholder_strings": 0.0,
        "no_todo_or_fixme_markers": 0.0,
        "status_summary_word_count": 0.0,
        "status_summary_mentions_album_and_van_halen": 0.0,
        "status_summary_includes_gig_count_numeral": 0.0,
        "validator_all_checks_passed": 0.0,
    }

    # Paths
    draft_path = workspace / "draft" / "newsletter_draft.md"
    newsletter_path = workspace / "output" / "classic_rock_newsletter.md"
    summary_path = workspace / "output" / "status_summary.txt"
    events_csv_path = workspace / "input" / "events.csv"
    spotlight_json_path = workspace / "input" / "spotlight.json"
    schema_json_path = workspace / "config" / "newsletter_schema.json"
    validator_path = workspace / "tools" / "validate_newsletter.py"

    # Presence of outputs
    newsletter_text = read_text_safe(newsletter_path)
    summary_text = read_text_safe(summary_path)
    if newsletter_text is not None:
        scores["output_newsletter_present"] = 1.0
    if summary_text is not None:
        scores["output_status_summary_present"] = 1.0

    # Load inputs
    draft_text = read_text_safe(draft_path)
    events = load_csv_dicts_safe(events_csv_path)
    spotlight = load_json_safe(spotlight_json_path)
    schema = load_json_safe(schema_json_path)

    # H1 title and date preservation (compare to draft)
    if draft_text is not None and newsletter_text is not None:
        expected_h1, expected_date = extract_h1_and_date(draft_text)
        actual_h1, actual_date = extract_h1_and_date(newsletter_text)
        if expected_h1 is not None and actual_h1 == expected_h1:
            scores["h1_title_preserved"] = 1.0
        if expected_date is not None and actual_date == expected_date:
            scores["date_line_preserved"] = 1.0

    # Section order and level (via parsing H2)
    if newsletter_text is not None:
        found_sections = [name for name, _ in parse_sections(newsletter_text)]
        required_sections = None
        if schema and isinstance(schema.get("required_sections"), list):
            required_sections = schema.get("required_sections")
        else:
            required_sections = ["Editor's Note", "Gig Calendar", "Album Spotlight", "Resources"]
        if found_sections == required_sections:
            scores["section_order_correct"] = 1.0

        # TODO/FIXME markers (case-insensitive)
        if not re.search(r"\bTODO\b", newsletter_text, flags=re.IGNORECASE) and not re.search(r"\bFIXME\b", newsletter_text, flags=re.IGNORECASE):
            scores["no_todo_or_fixme_markers"] = 1.0

        # Editor's Note mentions Van Halen
        ed_body = "\n".join(section_body_lines(newsletter_text, "Editor's Note")).lower()
        if "van halen" in ed_body:
            scores["editors_note_mentions_van_halen"] = 1.0

        # Gig Calendar matches CSV as exact bullet set
        if events is not None:
            expected_gigs = set()
            for ev in events:
                date = (ev.get("date") or "").strip()
                artist = (ev.get("artist") or "").strip()
                venue = (ev.get("venue") or "").strip()
                expected_gigs.add(f"- {date} - {artist} @ {venue}")
            gig_lines = [ln.strip() for ln in section_body_lines(newsletter_text, "Gig Calendar") if ln.strip().startswith("- ")]
            if set(gig_lines) == expected_gigs:
                scores["gig_calendar_matches_csv"] = 1.0

        # Album Spotlight includes album title and artist from spotlight.json
        if spotlight is not None:
            album_title = str(spotlight.get("album_title", "")).strip().lower()
            album_artist = str(spotlight.get("artist", "")).strip().lower()
            alb_body = "\n".join(section_body_lines(newsletter_text, "Album Spotlight")).lower()
            if album_title and album_artist and (album_title in alb_body) and (album_artist in alb_body):
                scores["album_spotlight_includes_title_and_artist"] = 1.0

        # Resources checks
        res_lines = section_body_lines(newsletter_text, "Resources")
        res_bullets = [ln for ln in res_lines if ln.strip().startswith("- ")]
        if len(res_bullets) >= 1:
            scores["resources_at_least_one_bullet"] = 1.0
        res_text_lower = "\n".join(res_lines).lower()
        if "placeholder" not in res_text_lower:
            scores["resources_no_placeholder_strings"] = 1.0

    # Status summary checks
    if summary_text is not None:
        wc = word_count(summary_text)
        if 120 <= wc <= 180:
            scores["status_summary_word_count"] = 1.0
        album_title_lower = ""
        if spotlight is not None:
            album_title_lower = str(spotlight.get("album_title", "")).strip().lower()
        mentions_album = album_title_lower and (album_title_lower in summary_text.lower())
        mentions_vh = "van halen" in summary_text.lower()
        if mentions_album and mentions_vh:
            scores["status_summary_mentions_album_and_van_halen"] = 1.0
        if events is not None:
            gigs_count = len(events)
            if re.search(rf"\b{gigs_count}\b", summary_text):
                scores["status_summary_includes_gig_count_numeral"] = 1.0

    # Run validator to ensure "ALL CHECKS PASSED"
    if newsletter_path.exists() and summary_path.exists() and events_csv_path.exists() and spotlight_json_path.exists() and schema_json_path.exists() and validator_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validator_path), str(newsletter_path), str(events_csv_path), str(spotlight_json_path), str(schema_json_path), str(summary_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0 and "ALL CHECKS PASSED" in (proc.stdout or ""):
                scores["validator_all_checks_passed"] = 1.0
        except Exception:
            scores["validator_all_checks_passed"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()