import json
import re
import sys
import subprocess
import csv
from pathlib import Path
from typing import List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _line_starts_with(text: str, prefix: str) -> bool:
    for ln in text.splitlines():
        if ln.strip().lower().startswith(prefix.lower()):
            return True
    return False


def _find_line_regex(text: str, pattern: str) -> Optional[re.Match]:
    for ln in text.splitlines():
        m = re.search(pattern, ln)
        if m:
            return m
    return None


def _count_bullets(text: str) -> int:
    return len(re.findall(r"^\s*-\s+", text, flags=re.MULTILINE))


def _extract_due_dates_from_action_items(text: str) -> Tuple[int, List[str]]:
    # Matches checkbox items with due date: - [ ] ... (due YYYY-MM-DD)
    pattern = re.compile(r"^\s*-\s*\[\s*\]\s+.*\(due\s+(\d{4}-\d{2}-\d{2})\)", flags=re.MULTILINE)
    dates = pattern.findall(text or "")
    return len(dates), dates


def _load_segments(csv_path: Path) -> List[str]:
    segments: List[str] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "segment" not in reader.fieldnames:
                return []
            for row in reader:
                seg = (row.get("segment") or "").strip()
                if seg:
                    segments.append(seg)
    except Exception:
        return []
    return segments


def _messages_next_steps_bullet_count(text: str) -> int:
    # Count bullet lines after the "NEXT STEPS:" section until a blank line or end
    lines = text.splitlines()
    count = 0
    in_section = False
    for ln in lines:
        if not in_section:
            if ln.strip().upper().startswith("NEXT STEPS:"):
                in_section = True
            continue
        # in NEXT STEPS
        if ln.strip() == "":
            # Stop on first blank line after section
            break
        if ln.strip().startswith("- "):
            count += 1
    return count


def _contains_any(text: str, words: List[str]) -> bool:
    tl = text.lower()
    return any(w.lower() in tl for w in words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_sections": 0.0,
        "meeting_notes_date_exact": 0.0,
        "meeting_notes_action_items_due_dates": 0.0,
        "status_update_sections_and_bullets": 0.0,
        "status_update_mentions_lena": 0.0,
        "status_update_topics_coverage": 0.0,
        "messages_exist_and_format": 0.0,
        "messages_next_steps_bullet_range": 0.0,
        "messages_segment_tailoring": 0.0,
        "validator_script_passed": 0.0,
    }

    # Paths
    meeting_notes_path = workspace / "output" / "meeting_notes_en.md"
    status_update_path = workspace / "output" / "status_update_en.md"
    messages_dir = workspace / "output" / "messages"
    segments_csv = workspace / "input" / "supporter_segments.csv"
    validator_script = workspace / "tools" / "validate.py"

    # Check meeting notes sections
    meeting_text = _read_text_safe(meeting_notes_path)
    if meeting_text is not None:
        # Sections: Meeting Date (with date), Attendees, Agenda, Decisions, Action Items
        sections_present = True
        # Meeting Date must be a line starting with "Meeting Date:"
        md_match = _find_line_regex(meeting_text, r"^\s*Meeting Date:\s*\d{4}-\d{2}-\d{2}")
        if md_match is None:
            sections_present = False
        for sec in ["Attendees", "Agenda", "Decisions", "Action Items"]:
            # Allow optional colon, check start of a line
            if not re.search(rf"(?m)^\s*{re.escape(sec)}\s*:?", meeting_text):
                sections_present = False
                break
        scores["meeting_notes_sections"] = 1.0 if sections_present else 0.0

        # Meeting Date exact value check
        md_exact = _find_line_regex(meeting_text, r"^\s*Meeting Date:\s*(\d{4}-\d{2}-\d{2})")
        if md_exact:
            date_val = md_exact.group(1)
            scores["meeting_notes_date_exact"] = 1.0 if date_val == "2026-04-10" else 0.0

        # Action items with due dates only from allowed set and at least 3 tasks
        allowed_due_dates = {"2026-04-17", "2026-04-18", "2026-04-28", "2026-04-13"}
        count_items, due_dates = _extract_due_dates_from_action_items(meeting_text)
        invalid_due = any(d not in allowed_due_dates for d in due_dates)
        if count_items >= 3 and not invalid_due:
            scores["meeting_notes_action_items_due_dates"] = 1.0
    else:
        # File missing or unreadable -> keep zeros
        pass

    # Check status update
    status_text = _read_text_safe(status_update_path)
    if status_text is not None:
        # Summary and Highlights sections and at least 3 bullet highlights
        summary_ok = re.search(r"(?m)^\s*Summary\s*:?", status_text) is not None
        highlights_ok = re.search(r"(?m)^\s*Highlights\s*:?", status_text) is not None
        bullets_count = _count_bullets(status_text)
        if summary_ok and highlights_ok and bullets_count >= 3:
            scores["status_update_sections_and_bullets"] = 1.0

        # Must mention Lena by name
        scores["status_update_mentions_lena"] = 1.0 if "Lena" in status_text else 0.0

        # Topics coverage: require at least 3 of 4 signals to be present
        t = status_text.lower()
        topic_signals = 0
        # Q2 donation goal
        if ("q2" in t) and (_contains_any(status_text, ["goal", "donation", "donations", "donor", "fundraising"])):
            topic_signals += 1
        # upcoming video
        if "video" in t:
            topic_signals += 1
        # volunteer workshop
        if "workshop" in t:
            topic_signals += 1
        # legal compliance review
        if ("legal" in t) or ("compliance" in t):
            topic_signals += 1
        if topic_signals >= 3:
            scores["status_update_topics_coverage"] = 1.0

    # Messages checks
    segments = _load_segments(segments_csv)
    if segments:
        exists_ok_count = 0
        next_steps_range_ok_count = 0
        tailoring_ok_count = 0
        for seg in segments:
            msg_path = messages_dir / f"message_{seg}_en.txt"
            text = _read_text_safe(msg_path)
            if text is None:
                continue
            lines = text.splitlines()
            first_line_ok = bool(lines) and lines[0].startswith("Subject:")
            has_update = "UPDATE:" in text
            has_next_steps = "NEXT STEPS:" in text
            has_lena = "Lena" in text
            bullets_any = _count_bullets(text) >= 2
            if first_line_ok and has_update and has_next_steps and has_lena and bullets_any:
                exists_ok_count += 1

            # Next steps bullet count between 2 and 3 inclusive
            ns_bullets = _messages_next_steps_bullet_count(text)
            if 2 <= ns_bullets <= 3:
                next_steps_range_ok_count += 1

            # Tailoring: simple relevance check per segment
            tl = text.lower()
            tailored = True
            if seg.lower() == "volunteers":
                tailored = ("volunteer" in tl)
            elif seg.lower() == "donors":
                tailored = any(word in tl for word in ["donor", "donors", "donation", "donations", "give", "support"])
            else:
                # For other segments, require mention of segment term
                tailored = (seg.lower() in tl)
            if tailored:
                tailoring_ok_count += 1

        total = len(segments)
        if total > 0:
            scores["messages_exist_and_format"] = exists_ok_count / total
            scores["messages_next_steps_bullet_range"] = next_steps_range_ok_count / total
            scores["messages_segment_tailoring"] = tailoring_ok_count / total

    # Validator script check
    if validator_script.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validator_script)],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0 and "All checks passed." in out:
                scores["validator_script_passed"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()