import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _parse_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if s == "":
            return None
        v = int(float(s))
        if str(v) != s and not s.isdigit():
            # be strict; allow "3" or "3.0" converting to 3
            pass
        return v
    except Exception:
        return None


def _count_sentences(text: str) -> int:
    # Count sentences by ., !, ? delimiters; collapse ellipses
    if not text:
        return 0
    cleaned = re.sub(r"\.{2,}", ".", text)
    # Split on punctuation followed by space or end
    parts = re.split(r"[.!?](?:\s|$)", cleaned)
    # Filter out empty fragments
    nonempty = [p.strip() for p in parts if p.strip()]
    return len(nonempty)


def _is_domain(value: str) -> bool:
    if not value:
        return False
    s = value.strip()
    # reject if URL with protocol
    if re.search(r"://", s):
        return False
    # basic domain pattern
    return re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", s) is not None


def _bool_from_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    t = str(s).strip().lower()
    if t in ("true", "t", "yes", "y", "1"):
        return True
    if t in ("false", "f", "no", "n", "0"):
        return False
    return None


def _weighted_score(a: float, c: float, r: float, acc: float) -> float:
    return 0.4 * a + 0.3 * c + 0.2 * r + 0.1 * acc


def _find_section_indices(lines: List[str], patterns: List[re.Pattern]) -> Dict[int, int]:
    # Return mapping from pattern index to line index where it occurs
    indices = {}
    for i, pat in enumerate(patterns):
        for idx, line in enumerate(lines):
            if pat.search(line):
                indices[i] = idx
                break
    return indices


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_brief = workspace / "input" / "committee_brief.md"

    scores: Dict[str, float] = {
        "resources_raw_exists": 0.0,
        "resources_raw_columns_valid": 0.0,
        "resources_raw_minimum_rows": 0.0,
        "resources_raw_scores_valid": 0.0,
        "resources_raw_description_sentence_count": 0.0,
        "resources_raw_domain_format": 0.0,
        "resources_ranked_exists": 0.0,
        "resources_ranked_columns_valid": 0.0,
        "resources_ranked_weighted_score_correct": 0.0,
        "resources_ranked_sorted_desc": 0.0,
        "resources_ranked_access_type_free_only": 0.0,
        "resources_ranked_titles_unique": 0.0,
        "resources_ranked_top5_flags_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_includes_meeting_details": 0.0,
        "meeting_notes_includes_agenda": 0.0,
        "meeting_notes_shortlist_matches_top5": 0.0,
        "meeting_notes_justifications_present": 0.0,
        "meeting_notes_action_items_present": 0.0,
        "handout_exists": 0.0,
        "handout_title_exact": 0.0,
        "handout_sections_order_and_counts": 0.0,
        "handout_further_reading_top3_match": 0.0,
    }

    # Paths
    outputs_dir = workspace / "outputs"
    resources_raw_path = outputs_dir / "resources_raw.csv"
    resources_ranked_path = outputs_dir / "resources_ranked.csv"
    meeting_notes_path = outputs_dir / "meeting_notes.md"
    handout_path = outputs_dir / "handout_draft.md"

    # Load raw resources
    raw_rows = _read_csv_dicts(resources_raw_path) if resources_raw_path.exists() else None
    if raw_rows is not None:
        scores["resources_raw_exists"] = 1.0
        # Column validation
        required_raw_cols = [
            "title",
            "organization",
            "domain",
            "year",
            "brief_description",
            "access_type",
            "audience_tag",
            "notes_on_bias_or_marketing",
            "authority_score",
            "clarity_score",
            "relevance_score",
            "accessibility_score",
        ]
        if all(set(required_raw_cols).issubset(set(r.keys())) for r in ([raw_rows[0]] if raw_rows else [{}])):
            scores["resources_raw_columns_valid"] = 1.0
        else:
            scores["resources_raw_columns_valid"] = 0.0

        # Minimum rows (at least 8)
        if isinstance(raw_rows, list) and len(raw_rows) >= 8:
            scores["resources_raw_minimum_rows"] = 1.0

        # Scores valid 1-5 integers
        scores_valid = True
        if raw_rows:
            for r in raw_rows:
                for col in ["authority_score", "clarity_score", "relevance_score", "accessibility_score"]:
                    v = _parse_int(r.get(col))
                    if v is None or v < 1 or v > 5:
                        scores_valid = False
                        break
                if not scores_valid:
                    break
        else:
            scores_valid = False
        scores["resources_raw_scores_valid"] = 1.0 if scores_valid else 0.0

        # Description sentence count 1-2
        desc_ok = True
        if raw_rows:
            for r in raw_rows:
                desc = (r.get("brief_description") or "").strip()
                count = _count_sentences(desc)
                if count < 1 or count > 2:
                    desc_ok = False
                    break
        else:
            desc_ok = False
        scores["resources_raw_description_sentence_count"] = 1.0 if desc_ok else 0.0

        # Domain format valid for all rows
        domain_ok = True
        if raw_rows:
            for r in raw_rows:
                d = (r.get("domain") or "").strip()
                if not _is_domain(d):
                    domain_ok = False
                    break
        else:
            domain_ok = False
        scores["resources_raw_domain_format"] = 1.0 if domain_ok else 0.0
    else:
        # Ensure keys remain 0.0
        pass

    # Load ranked resources
    ranked_rows = _read_csv_dicts(resources_ranked_path) if resources_ranked_path.exists() else None
    if ranked_rows is not None:
        scores["resources_ranked_exists"] = 1.0
        required_ranked_cols = [
            "title",
            "organization",
            "domain",
            "year",
            "brief_description",
            "access_type",
            "audience_tag",
            "notes_on_bias_or_marketing",
            "authority_score",
            "clarity_score",
            "relevance_score",
            "accessibility_score",
            "weighted_score",
            "top5",
        ]
        if all(set(required_ranked_cols).issubset(set(r.keys())) for r in ([ranked_rows[0]] if ranked_rows else [{}])):
            scores["resources_ranked_columns_valid"] = 1.0
        else:
            scores["resources_ranked_columns_valid"] = 0.0

        # Weighted score correctness (to one decimal place)
        ws_ok = True
        if ranked_rows:
            for r in ranked_rows:
                a = _parse_float(r.get("authority_score"))
                c = _parse_float(r.get("clarity_score"))
                rel = _parse_float(r.get("relevance_score"))
                acc = _parse_float(r.get("accessibility_score"))
                ws_str = (r.get("weighted_score") or "").strip()
                if None in (a, c, rel, acc) or ws_str == "":
                    ws_ok = False
                    break
                ws = _weighted_score(a, c, rel, acc)
                expected = f"{ws:.1f}"
                if ws_str != expected:
                    ws_ok = False
                    break
        else:
            ws_ok = False
        scores["resources_ranked_weighted_score_correct"] = 1.0 if ws_ok else 0.0

        # Sorted by weighted_score descending
        sorted_ok = True
        if ranked_rows:
            ws_list = []
            for r in ranked_rows:
                ws_str = (r.get("weighted_score") or "").strip()
                v = _parse_float(ws_str)
                if v is None:
                    sorted_ok = False
                    break
                ws_list.append(v)
            if sorted_ok:
                for i in range(1, len(ws_list)):
                    if ws_list[i] > ws_list[i - 1] + 1e-9:
                        sorted_ok = False
                        break
        else:
            sorted_ok = False
        scores["resources_ranked_sorted_desc"] = 1.0 if sorted_ok else 0.0

        # Access type free only
        free_only = True
        if ranked_rows:
            for r in ranked_rows:
                at = (r.get("access_type") or "").strip().lower()
                if at != "free":
                    free_only = False
                    break
        else:
            free_only = False
        scores["resources_ranked_access_type_free_only"] = 1.0 if free_only else 0.0

        # Titles unique
        titles_unique = True
        if ranked_rows:
            seen = set()
            for r in ranked_rows:
                t = (r.get("title") or "").strip().lower()
                if t in seen:
                    titles_unique = False
                    break
                seen.add(t)
        else:
            titles_unique = False
        scores["resources_ranked_titles_unique"] = 1.0 if titles_unique else 0.0

        # Top5 flags correct: first 5 TRUE, rest FALSE (or all TRUE if <5 rows)
        top5_ok = True
        if ranked_rows:
            n = len(ranked_rows)
            for idx, r in enumerate(ranked_rows):
                flag = _bool_from_str((r.get("top5") or "").strip())
                if n >= 5:
                    should = idx < 5
                else:
                    should = True  # if fewer than 5, all entries should be top5
                if flag is None or flag != should:
                    top5_ok = False
                    break
        else:
            top5_ok = False
        scores["resources_ranked_top5_flags_correct"] = 1.0 if top5_ok else 0.0
    else:
        # keep zeros
        pass

    # Meeting notes checks
    notes_text = _read_text(meeting_notes_path) if meeting_notes_path.exists() else None
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        notes_lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]

        # Meeting details: date/time and attendees
        # Check presence of date and time patterns and names
        date_ok = bool(re.search(r"2026[^\d]?05[^\d]?01", notes_text))
        time_ok = "10:00" in notes_text and "10:30" in notes_text
        attendees_ok = all(name in notes_text for name in ["Erin", "Malik", "You"])
        scores["meeting_notes_includes_meeting_details"] = 1.0 if (date_ok and time_ok and attendees_ok) else 0.0

        # Agenda items
        agenda_ok = all(
            phrase.lower() in notes_text.lower()
            for phrase in ["Review ranked shortlist", "Decide top three", "Assign follow-ups"]
        )
        scores["meeting_notes_includes_agenda"] = 1.0 if agenda_ok else 0.0

        # Shortlist matches top 5
        shortlist_ok = False
        justifications_ok = False
        if ranked_rows:
            # Build list of top 5 titles
            top5_titles = [r.get("title", "").strip() for r in ranked_rows[: min(5, len(ranked_rows))]]
            if all(t and (t in notes_text) for t in top5_titles):
                shortlist_ok = True

                # For each title, find nearby justification mentioning scoring criteria
                criteria_words = ["authority", "clarity", "relevance", "accessibility"]
                per_item_ok = True
                for t in top5_titles:
                    # Find a line containing the title
                    line_idx = None
                    for i, ln in enumerate(notes_lines):
                        if t in ln:
                            line_idx = i
                            break
                    if line_idx is None:
                        per_item_ok = False
                        break
                    window_text = "\n".join(notes_lines[line_idx : min(len(notes_lines), line_idx + 3)])
                    # Check presence of criteria words
                    has_criteria = any(w in window_text.lower() for w in criteria_words)
                    # Count sentences in window (1-2)
                    sent_count = _count_sentences(window_text)
                    if not has_criteria or sent_count < 1 or sent_count > 2:
                        per_item_ok = False
                        break
                justifications_ok = per_item_ok
        scores["meeting_notes_shortlist_matches_top5"] = 1.0 if shortlist_ok else 0.0
        scores["meeting_notes_justifications_present"] = 1.0 if justifications_ok else 0.0

        # Action items with owner and due date
        action_ok = False
        # Look for lines containing both an owner name and a due date
        action_count = 0
        for ln in notes_lines:
            if re.search(r"\bdue\b", ln, flags=re.IGNORECASE) and re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", ln):
                if any(n in ln for n in ["Erin", "Malik", "You"]):
                    action_count += 1
        if action_count >= 3:
            action_ok = True
        scores["meeting_notes_action_items_present"] = 1.0 if action_ok else 0.0
    else:
        # keep zeros
        pass

    # Handout checks
    handout_text = _read_text(handout_path) if handout_path.exists() else None
    if handout_text is not None:
        scores["handout_exists"] = 1.0
        lines = [ln.rstrip("\n") for ln in handout_text.splitlines()]
        # Title exact
        # Find first non-empty line
        first_non_empty = ""
        for ln in lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        expected_title = "Quick Guide: How to Watch a Race When You’re Not a Fan."
        scores["handout_title_exact"] = 1.0 if first_non_empty == expected_title else 0.0

        # Sections order and bullet counts
        # Define patterns for section headings
        patterns = [
            re.compile(r"^\s*#*\s*Why\s+people\s+enjoy\s+watching", flags=re.IGNORECASE),
            re.compile(r"^\s*#*\s*What\s+to\s+focus\s+on\s+during\s+any\s+race", flags=re.IGNORECASE),
            re.compile(r"^\s*#*\s*Safety\s+and\s+etiquette", flags=re.IGNORECASE),
            re.compile(r"^\s*#*\s*Further\s+reading", flags=re.IGNORECASE),
        ]
        idx_map = _find_section_indices(lines, patterns)
        order_ok = all(i in idx_map for i in range(4))
        if order_ok:
            order_ok = idx_map[0] < idx_map[1] < idx_map[2] < idx_map[3]
        # Count bullets between sections
        bullets = []
        if order_ok:
            # Helper to count bullets in a section range
            def section_bullets(start_idx: int, end_idx: int) -> List[str]:
                blts = []
                for ln in lines[start_idx + 1 : end_idx]:
                    if re.match(r"^\s*[-*]\s+", ln):
                        blts.append(ln.strip())
                return blts

            b1 = section_bullets(idx_map[0], idx_map[1])
            b2 = section_bullets(idx_map[1], idx_map[2])
            b3 = section_bullets(idx_map[2], idx_map[3])
            # Validate counts and content emphasis
            b1_ok = 3 <= len(b1) <= 4
            b2_ok = 3 <= len(b2) <= 5
            b3_ok = len(b3) >= 3 and any(
                re.search(r"(safety|respect|etiquette)", x, flags=re.IGNORECASE) for x in b3
            )
            if b1_ok and b2_ok and b3_ok and order_ok:
                scores["handout_sections_order_and_counts"] = 1.0
            else:
                scores["handout_sections_order_and_counts"] = 0.0
        else:
            scores["handout_sections_order_and_counts"] = 0.0

        # Further reading top 3
        fr_ok = False
        if ranked_rows and order_ok:
            # Get top 3 from ranked rows
            top3 = ranked_rows[: min(3, len(ranked_rows))]
            # Extract bullets in further reading
            fr_bullets = []
            for ln in lines[idx_map[3] + 1 :]:
                if re.match(r"^\s*[-*]\s+", ln):
                    fr_bullets.append(ln.strip())
                elif ln.strip() == "":
                    continue
                else:
                    # stop at non-bullet content
                    continue
            # Exactly 3 bullets
            if len(fr_bullets) == min(3, len(top3)) == 3:
                # No URLs
                no_urls = all(("http" not in b.lower() and "www." not in b.lower() and "://" not in b) for b in fr_bullets)
                # Each bullet contains title and organization
                all_match = True
                for res in top3:
                    title = (res.get("title") or "").strip()
                    org = (res.get("organization") or "").strip()
                    found = False
                    for b in fr_bullets:
                        if title and org and (title.lower() in b.lower()) and (org.lower() in b.lower()):
                            found = True
                            break
                    if not found:
                        all_match = False
                        break
                fr_ok = no_urls and all_match
        scores["handout_further_reading_top3_match"] = 1.0 if fr_ok else 0.0
    else:
        # keep zeros
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()