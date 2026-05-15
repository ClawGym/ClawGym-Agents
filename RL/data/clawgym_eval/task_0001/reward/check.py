import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_lines(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    return text.splitlines()


def _safe_load_csv_dicts(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames or []
    except Exception:
        return None


def _parse_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, str):
            val = val.strip()
        return int(val)
    except Exception:
        return None


def _parse_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, str):
            val = val.strip()
        return float(val)
    except Exception:
        return None


def _compute_availability_stats(rows: List[Dict[str, str]], fieldnames: List[str]) -> Dict[str, Dict[str, Any]]:
    # fieldnames include 'Name' and slots
    slots = [fn for fn in fieldnames if fn != "Name"]
    stats: Dict[str, Dict[str, Any]] = {}
    for slot in slots:
        a = m = n = 0
        for r in rows:
            val = r.get(slot, "")
            v = (val or "").strip().lower()
            if v == "available":
                a += 1
            elif v == "maybe":
                m += 1
            elif v == "no":
                n += 1
            else:
                # missing or unrecognized: contributes 0 to weight, but not counted as "No"
                pass
        weighted = a * 1.0 + m * 0.5
        stats[slot] = {
            "available_count": a,
            "maybe_count": m,
            "no_count": n,
            "weighted_score": weighted,
        }
    return stats


def _select_best_slot(stats: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not stats:
        return None
    # Highest weighted_score, tie by earliest slot lexicographically
    best = sorted(stats.items(), key=lambda kv: (-kv[1]["weighted_score"], kv[0]))[0][0]
    return best


def _load_slot_stats_output(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames or []
    except Exception:
        return None


def _word_count(text: str) -> int:
    # Split on any whitespace
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _extract_open_items_from_minutes(lines: List[str]) -> List[Dict[str, str]]:
    open_items: List[Dict[str, str]] = []
    for line in lines:
        s = line.strip()
        if not s.startswith("- [OPEN]"):
            continue
        rest = s[len("- [OPEN]"):].strip()
        # Find positions of Owner: and Due:
        # Use case-sensitive as minutes use proper case
        owner_idx = rest.find("Owner:")
        due_idx = rest.find("Due:")
        # Description is from start to owner_idx if present else to due_idx else full rest
        desc_end = len(rest)
        if owner_idx != -1:
            desc_end = owner_idx
        elif due_idx != -1:
            desc_end = due_idx
        desc_text = rest[:desc_end].strip()
        # Strip trailing separators like em dash or hyphen and spaces
        desc_text = desc_text.rstrip(" -—–").strip()
        owner = ""
        if owner_idx != -1:
            after_owner = rest[owner_idx + len("Owner:"):].strip()
            # Owner value ends before due_idx (relative to rest)
            if due_idx != -1 and due_idx > owner_idx:
                owner_chunk = rest[owner_idx + len("Owner:"):due_idx].strip()
            else:
                owner_chunk = after_owner
            # Owner chunk may include separators or spaces
            owner = owner_chunk.strip(" -—–").strip()
            # owner may have trailing separators
            owner = re.sub(r"\s+", " ", owner)
        due = ""
        # Extract first date pattern YYYY-MM-DD in rest
        m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", rest)
        if m:
            due = m.group(0)
        open_items.append({"description": desc_text, "owner": owner, "due": due})
    return open_items


def _find_section_bullets(lines: List[str], section_header: str) -> List[str]:
    bullets: List[str] = []
    in_section = False
    for line in lines:
        if in_section:
            if line.strip().startswith("- "):
                bullets.append(line.strip())
                continue
            # Stop collecting when encountering a non-bullet line after we've started,
            # unless it's blank, then keep scanning for more bullets directly after header.
            if line.strip() == "":
                # allow blank lines within the section; continue scanning
                continue
            # If another header-like line encountered, stop
            if line.strip().endswith(":") and not line.strip().startswith("- "):
                break
            # Non-bullet content: ignore but continue until we hit another header
            # To be safe, we will not append it
            continue
        else:
            if line.strip() == section_header:
                in_section = True
    return bullets


def _get_first_non_bullet_line_with_text(lines: List[str]) -> Optional[str]:
    for line in lines:
        if line.strip() and not line.strip().startswith("- "):
            return line
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "slot_stats_exists_and_columns": 0.0,
        "slot_stats_counts_correct": 0.0,
        "slot_stats_weighted_scores_correct": 0.0,
        "slot_stats_sorted_correct": 0.0,
        "meeting_invite_subject_preserved": 0.0,
        "meeting_invite_includes_selected_slot": 0.0,
        "meeting_invite_includes_location": 0.0,
        "meeting_invite_mentions_purpose": 0.0,
        "meeting_invite_rsvp_deadline": 0.0,
        "meeting_invite_body_word_limit": 0.0,
        "agenda_title_and_when_where_present": 0.0,
        "agenda_agenda_section_and_required_items": 0.0,
        "agenda_carry_over_items_format_and_content": 0.0,
        "status_summary_paragraph_and_selected_slot": 0.0,
        "status_summary_slots_list_correct": 0.0,
        "status_summary_tie_break_rationale_included": 0.0,
        "status_summary_carry_over_count_included": 0.0,
    }

    # Load inputs
    availability_path = workspace / "input" / "availability.csv"
    minutes_path = workspace / "input" / "minutes_last_meeting.md"
    draft_invite_path = workspace / "input" / "draft_invite.txt"

    availability = _safe_load_csv_dicts(availability_path)
    draft_invite_lines = _safe_read_lines(draft_invite_path)
    minutes_lines = _safe_read_lines(minutes_path)

    stats: Dict[str, Dict[str, Any]] = {}
    expected_slots: List[str] = []
    selected_slot: Optional[str] = None

    if availability is not None:
        avail_rows, fieldnames = availability
        if fieldnames:
            expected_slots = [fn for fn in fieldnames if fn != "Name"]
        try:
            stats = _compute_availability_stats(avail_rows, fieldnames)
            selected_slot = _select_best_slot(stats)
        except Exception:
            stats = {}
            selected_slot = None

    # 1) Validate output/slot_stats.csv
    slot_stats_out_path = workspace / "output" / "slot_stats.csv"
    slot_stats_out = _load_slot_stats_output(slot_stats_out_path)
    if slot_stats_out is not None:
        out_rows, out_headers = slot_stats_out
        expected_headers = ["slot", "available_count", "maybe_count", "no_count", "weighted_score"]
        if out_headers == expected_headers:
            scores["slot_stats_exists_and_columns"] = 1.0

            # Only proceed to deeper checks if we have expected stats computed
            if stats and expected_slots:
                # Build a map from slot to row for output
                out_by_slot: Dict[str, Dict[str, str]] = {r["slot"]: r for r in out_rows if "slot" in r}
                # Counts correct
                counts_ok = True
                weights_ok = True
                if set(out_by_slot.keys()) != set(expected_slots) or len(out_rows) != len(expected_slots):
                    counts_ok = False
                    weights_ok = False
                else:
                    for slot in expected_slots:
                        r = out_by_slot.get(slot)
                        if r is None:
                            counts_ok = False
                            weights_ok = False
                            break
                        a = _parse_int(r.get("available_count"))
                        m = _parse_int(r.get("maybe_count"))
                        n = _parse_int(r.get("no_count"))
                        w = _parse_float(r.get("weighted_score"))
                        if a is None or m is None or n is None or w is None:
                            counts_ok = False
                            weights_ok = False
                            break
                        exp = stats[slot]
                        if a != exp["available_count"] or m != exp["maybe_count"] or n != exp["no_count"]:
                            counts_ok = False
                        if abs(w - float(exp["weighted_score"])) > 1e-9:
                            weights_ok = False
                if counts_ok:
                    scores["slot_stats_counts_correct"] = 1.0
                if weights_ok:
                    scores["slot_stats_weighted_scores_correct"] = 1.0

                # Sorting check
                # Expected sort: weighted_score desc, then slot asc
                try:
                    # Build list tuples as in file order
                    file_order = [(r["slot"], _parse_float(r.get("weighted_score"))) for r in out_rows]
                    # If any parse failure, mark sort false
                    if any(w is None or s is None for s, w in file_order):
                        pass
                    else:
                        # Create expected sorted slots order based on output rows' slots and expected stats for those slots
                        sort_key = lambda s: (-float(stats[s]["weighted_score"]), s)
                        expected_order_slots = sorted([r["slot"] for r in out_rows], key=sort_key)
                        file_order_slots = [r["slot"] for r in out_rows]
                        if file_order_slots == expected_order_slots:
                            scores["slot_stats_sorted_correct"] = 1.0
                except Exception:
                    # leave as 0.0
                    pass

    # 2) Validate output/meeting_invite.txt
    invite_out_path = workspace / "output" / "meeting_invite.txt"
    invite_lines = _safe_read_lines(invite_out_path)
    if invite_lines and draft_invite_lines:
        # subject preserved
        draft_subject = draft_invite_lines[0] if draft_invite_lines else ""
        invite_subject = invite_lines[0] if invite_lines else ""
        if invite_subject == draft_subject and invite_subject != "":
            scores["meeting_invite_subject_preserved"] = 1.0

        # Body checks
        body_lines = invite_lines[1:] if len(invite_lines) > 1 else []
        body_text = "\n".join(body_lines)
        body_text_lower = body_text.lower()

        # selected slot string appears exactly
        if selected_slot and selected_slot in body_text:
            scores["meeting_invite_includes_selected_slot"] = 1.0

        # location phrase exact
        if "Clubhouse meeting room" in body_text:
            scores["meeting_invite_includes_location"] = 1.0

        # purpose mention: match + roles + materials (case-insensitive)
        if ("match" in body_text_lower) and ("roles" in body_text_lower) and ("materials" in body_text_lower):
            scores["meeting_invite_mentions_purpose"] = 1.0

        # RSVP by 2026-04-17: check "RSVP" and the date
        if "2026-04-17" in body_text and re.search(r"\brsvp\b", body_text_lower):
            scores["meeting_invite_rsvp_deadline"] = 1.0

        # word limit: <= 120 words in body
        if _word_count(body_text) <= 120:
            scores["meeting_invite_body_word_limit"] = 1.0

    # 3) Validate output/agenda_and_actions.md
    agenda_out_path = workspace / "output" / "agenda_and_actions.md"
    agenda_lines = _safe_read_lines(agenda_out_path)
    open_items: List[Dict[str, str]] = []
    if minutes_lines:
        open_items = _extract_open_items_from_minutes(minutes_lines)

    if agenda_lines:
        # Title, When, Where
        title_ok = any(line.strip() == "Volunteer Coordination Meeting — Holsted Tigers" for line in agenda_lines)
        when_ok = False
        where_ok = any(line.strip() == "Where: Clubhouse meeting room" for line in agenda_lines)
        if selected_slot:
            for line in agenda_lines:
                if line.strip().startswith("When: "):
                    when_val = line.strip()[len("When: "):]
                    if when_val == selected_slot:
                        when_ok = True
                        break
        if title_ok and when_ok and where_ok:
            scores["agenda_title_and_when_where_present"] = 1.0

        # Agenda section and required items
        agenda_bullets = _find_section_bullets(agenda_lines, "Agenda:")
        required_items = [
            "Volunteer roles",
            "Materials checklist",
            "Stadium coordination",
            "Open items from last meeting",
        ]
        count_ok = 4 <= len([b for b in agenda_bullets if b.startswith("- ")]) <= 6
        includes_all_required = True
        ag_texts = [b[2:].strip().lower() for b in agenda_bullets if b.startswith("- ")]
        for phrase in required_items:
            if not any(phrase.lower() in t for t in ag_texts):
                includes_all_required = False
                break
        if count_ok and includes_all_required:
            scores["agenda_agenda_section_and_required_items"] = 1.0

        # Carry-over action items
        carry_bullets = _find_section_bullets(agenda_lines, "Carry-over action items:")
        # Only consider bullets that start with "- [ ]"
        carry_check_bullets = [b for b in carry_bullets if b.startswith("- [ ]")]
        all_included = True
        format_ok = True
        matched_indices: set = set()

        # For each expected open item, find a matching bullet
        for idx, item in enumerate(open_items):
            desc = item.get("description", "").strip()
            owner = item.get("owner", "").strip()
            due = item.get("due", "").strip()
            found_match = False
            for cb in carry_check_bullets:
                text = cb
                # Check normalized pattern content
                # Must contain "(Owner: <owner>; Due: <due>)"
                owner_due_pattern = f"(Owner: {owner}; Due: {due})"
                if owner and due and owner_due_pattern not in text:
                    continue
                # Description presence (case-insensitive substring)
                if desc and desc.lower() not in text.lower():
                    continue
                found_match = True
                matched_indices.add(idx)
                # format check: ensure parentheses and semicolon exist exactly for at least one bullet
                if "(Owner:" not in text or "; Due:" not in text or "(" not in text or ")" not in text:
                    format_ok = False
                break
            if not found_match:
                all_included = False
                break

        if all_included and format_ok and len(carry_check_bullets) >= len(open_items) and len(open_items) > 0:
            scores["agenda_carry_over_items_format_and_content"] = 1.0
        elif all_included and format_ok and len(open_items) == 0:
            # Edge case: if there were no [OPEN] items, accept empty list
            scores["agenda_carry_over_items_format_and_content"] = 1.0

    # 4) Validate output/status_summary.md
    summary_out_path = workspace / "output" / "status_summary.md"
    summary_lines = _safe_read_lines(summary_out_path)
    if summary_lines:
        # Paragraph with selected slot
        para_line = _get_first_non_bullet_line_with_text(summary_lines)
        if selected_slot and para_line and (selected_slot in para_line):
            scores["status_summary_paragraph_and_selected_slot"] = 1.0

        # Bulleted list of three slots with counts and weighted_score
        bullets = [l.strip() for l in summary_lines if l.strip().startswith("- ")]
        list_ok = True
        if stats and expected_slots:
            for slot in expected_slots:
                # find bullet that contains the slot string
                candidates = [b for b in bullets if slot in b]
                if len(candidates) != 1:
                    list_ok = False
                    break
                b = candidates[0]
                # Parse counts and weighted from labels
                def find_int(label: str, text: str) -> Optional[int]:
                    m = re.search(rf"{re.escape(label)}\s*:\s*(-?\d+)\b", text)
                    return int(m.group(1)) if m else None

                def find_float(label: str, text: str) -> Optional[float]:
                    m = re.search(rf"{re.escape(label)}\s*:\s*(-?\d+(?:\.\d+)?)\b", text)
                    return float(m.group(1)) if m else None

                a = find_int("available_count", b)
                m = find_int("maybe_count", b)
                n = find_int("no_count", b)
                w = find_float("weighted_score", b)
                exp = stats[slot]
                if a is None or m is None or n is None or w is None:
                    list_ok = False
                    break
                if not (a == exp["available_count"] and m == exp["maybe_count"] and n == exp["no_count"] and abs(w - float(exp["weighted_score"])) < 1e-9):
                    list_ok = False
                    break
        else:
            list_ok = False
        if list_ok:
            scores["status_summary_slots_list_correct"] = 1.0

        # Tie-break rationale included
        full_text = "\n".join(summary_lines).lower()
        if ("earlier date/time" in full_text) or ("no tie" in full_text) or ("no tiebreak" in full_text) or ("no tie-break" in full_text):
            scores["status_summary_tie_break_rationale_included"] = 1.0

        # Carry-over count included
        included_carry_count = 0
        if agenda_lines:
            # Count bullets that start with "- [ ]" in carry-over section
            carry_bullets = _find_section_bullets(agenda_lines, "Carry-over action items:")
            included_carry_count = len([b for b in carry_bullets if b.strip().startswith("- [ ]")])
        # Find any line containing keyword and the number
        found_count_ref = False
        for line in summary_lines:
            l = line.strip().lower()
            if any(kw in l for kw in ["carry", "open", "action"]):
                # search for integer tokens
                nums = re.findall(r"\b\d+\b", l)
                if str(included_carry_count) in nums:
                    found_count_ref = True
                    break
        if found_count_ref and (included_carry_count > 0 or len(open_items) == 0):
            scores["status_summary_carry_over_count_included"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()