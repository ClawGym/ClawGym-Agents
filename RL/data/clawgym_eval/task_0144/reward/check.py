import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import date


ALLOWED_CTAS = {"Descubrí más", "Leé más", "Contanos tu anécdota", "Compartí este dato"}


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return rows, None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[object], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _terms_in_text(note_terms: List[str], text: str) -> List[str]:
    # Return canonical terms that appear in text (case-insensitive substring)
    res = []
    t = (text or "").casefold()
    for term in note_terms or []:
        if (term or "").casefold() in t:
            res.append(term)
    # ensure unique preserving order
    seen = set()
    uniq = []
    for term in res:
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            uniq.append(term)
    return uniq


def _split_semicolon_list(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p != ""]


def _header_matches(path: Path, expected_header: List[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            first_line = f.readline()
        if not first_line:
            return False
        reader = csv.reader([first_line])
        row = next(reader)
        return row == expected_header
    except Exception:
        return False


def _build_index(rows: List[Dict[str, str]], key: str) -> Dict[str, Dict[str, str]]:
    idx = {}
    for r in rows:
        idx[r.get(key, "")] = r
    return idx


def _parse_date_iso(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _find_sections(text: str, section_names: List[str]) -> Dict[str, Tuple[int, int]]:
    # Return mapping of lower(section) -> (start_index, end_index_exclusive) of content lines
    lines = text.splitlines()
    markers = {}
    normalized_names = [name.lower() for name in section_names]
    # map each section to its first heading line index
    for i, line in enumerate(lines):
        stripped = line.lstrip().lstrip("#").strip()
        lower = stripped.lower()
        for name in normalized_names:
            if lower == name or lower == f"{name}:" or lower.startswith(f"{name} "):
                if name not in markers:
                    markers[name] = i
    # determine ranges
    ranges = {}
    sorted_positions = sorted([(i, name) for name, i in markers.items()], key=lambda x: x[0])
    for idx, (start_i, name) in enumerate(sorted_positions):
        end_i = len(lines)
        if idx + 1 < len(sorted_positions):
            end_i = sorted_positions[idx + 1][0]
        ranges[name] = (start_i + 1, end_i)
    return ranges


def _get_section_text(text: str, section_name: str) -> str:
    ranges = _find_sections(text, ["Overview", "Highlights", "Next steps"])
    key = section_name.lower()
    if key in ranges:
        start, end = ranges[key]
        return "\n".join(text.splitlines()[start:end])
    return ""


def _line_with_exact_total_posts(text: str, expected_count: int, max_line_index: int = 10) -> bool:
    lines = text.splitlines()
    target = f"Total posts: {expected_count}"
    top_limit = min(len(lines), max_line_index)
    for i in range(top_limit):
        if lines[i].strip() == target:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "editorial_exists_and_columns": 0.0,
        "editorial_row_count_exact": 0.0,
        "editorial_event_id_coverage": 0.0,
        "editorial_date_channel_match": 0.0,
        "editorial_source_note_allowed_and_topic": 0.0,
        "editorial_cta_valid": 0.0,
        "editorial_post_copy_length_and_key_terms": 0.0,
        "editorial_key_terms_used_correct": 0.0,
        "revised_exists_and_columns": 0.0,
        "revised_row_count_exact": 0.0,
        "revised_draft_coverage_and_note_match": 0.0,
        "revised_cta_valid": 0.0,
        "revised_length_and_key_terms": 0.0,
        "status_exists": 0.0,
        "status_total_posts_line_correct": 0.0,
        "status_overview_dates_and_channels": 0.0,
        "status_highlights_titles_and_terms": 0.0,
        "status_ctas_used_line_correct": 0.0,
        "status_next_steps_count": 0.0,
    }

    # Load inputs
    events_path = workspace / "input" / "events.csv"
    notes_path = workspace / "input" / "notes.json"
    drafts_path = workspace / "input" / "draft_posts.csv"

    events_rows, events_err = _safe_read_csv_dicts(events_path)
    notes_obj, notes_err = _safe_load_json(notes_path)
    drafts_rows, drafts_err = _safe_read_csv_dicts(drafts_path)

    notes_by_id = {}
    if isinstance(notes_obj, list):
        for item in notes_obj:
            if isinstance(item, dict) and "id" in item:
                notes_by_id[item["id"]] = item

    events_by_id = {}
    if isinstance(events_rows, list):
        for r in events_rows:
            if "event_id" in r:
                events_by_id[r["event_id"]] = r

    drafts_by_id = {}
    if isinstance(drafts_rows, list):
        for r in drafts_rows:
            if "draft_id" in r:
                drafts_by_id[r["draft_id"]] = r

    # Editorial calendar checks
    editorial_path = workspace / "outputs" / "editorial_calendar.csv"
    expected_editorial_header = ["event_id", "date", "channel", "topic", "post_copy", "cta", "source_note_id", "key_terms_used"]
    editorial_rows, editorial_err = _safe_read_csv_dicts(editorial_path)

    if editorial_path.exists() and _header_matches(editorial_path, expected_editorial_header):
        scores["editorial_exists_and_columns"] = 1.0

    # Row count
    if editorial_rows is not None and isinstance(events_rows, list):
        if len(editorial_rows) == len(events_rows):
            scores["editorial_row_count_exact"] = 1.0

    # Event coverage and date/channel match
    if editorial_rows is not None and isinstance(events_rows, list):
        # event id coverage and uniqueness
        ed_event_ids = [r.get("event_id", "") for r in editorial_rows]
        ed_counts = {}
        for eid in ed_event_ids:
            ed_counts[eid] = ed_counts.get(eid, 0) + 1
        all_present_once = True
        if set(ed_event_ids) != set(events_by_id.keys()):
            all_present_once = False
        for eid, cnt in ed_counts.items():
            if cnt != 1:
                all_present_once = False

        if all_present_once:
            scores["editorial_event_id_coverage"] = 1.0

        # date/channel match
        date_channel_ok = True
        for r in editorial_rows:
            eid = r.get("event_id", "")
            ev = events_by_id.get(eid)
            if not ev:
                date_channel_ok = False
                break
            if (r.get("date", "") != ev.get("date", "")) or (r.get("channel", "") != ev.get("channel", "")):
                date_channel_ok = False
                break
        if date_channel_ok:
            scores["editorial_date_channel_match"] = 1.0

    # Source note allowed and topic matches
    if editorial_rows is not None and isinstance(events_rows, list) and isinstance(notes_obj, list):
        ok = True
        for r in editorial_rows:
            eid = r.get("event_id", "")
            ev = events_by_id.get(eid)
            if not ev:
                ok = False
                break
            allowed = [x.strip() for x in (ev.get("allowed_note_ids", "") or "").split("|") if x.strip() != ""]
            note_id = r.get("source_note_id", "")
            if note_id not in allowed:
                ok = False
                break
            note = notes_by_id.get(note_id)
            if not note:
                ok = False
                break
            topic = r.get("topic", "")
            if topic != note.get("title", ""):
                ok = False
                break
        if ok:
            scores["editorial_source_note_allowed_and_topic"] = 1.0

    # CTA valid for editorial
    if editorial_rows is not None:
        cta_ok = True
        for r in editorial_rows:
            if r.get("cta", "") not in ALLOWED_CTAS:
                cta_ok = False
                break
        if cta_ok:
            scores["editorial_cta_valid"] = 1.0

    # Post copy length and includes at least one key term
    if editorial_rows is not None and isinstance(notes_obj, list):
        pc_ok = True
        for r in editorial_rows:
            note = notes_by_id.get(r.get("source_note_id", ""))
            post_copy = r.get("post_copy", "") or ""
            if len(post_copy) > 220:
                pc_ok = False
                break
            if not note:
                pc_ok = False
                break
            terms = note.get("key_terms", []) or []
            used = _terms_in_text(terms, post_copy)
            if len(used) == 0:
                pc_ok = False
                break
        if pc_ok:
            scores["editorial_post_copy_length_and_key_terms"] = 1.0

    # key_terms_used correctness
    if editorial_rows is not None and isinstance(notes_obj, list):
        ktu_ok = True
        for r in editorial_rows:
            note = notes_by_id.get(r.get("source_note_id", ""))
            if not note:
                ktu_ok = False
                break
            terms = note.get("key_terms", []) or []
            post_copy = r.get("post_copy", "") or ""
            used = _terms_in_text(terms, post_copy)
            used_set = {u.casefold() for u in used}
            provided = _split_semicolon_list(r.get("key_terms_used", "") or "")
            provided_set = {p.casefold() for p in provided}
            # The provided must match exactly the used set (case-insensitive), and no duplicates
            if provided_set != used_set:
                ktu_ok = False
                break
            if len(provided) != len(provided_set):
                ktu_ok = False
                break
        if ktu_ok:
            scores["editorial_key_terms_used_correct"] = 1.0

    # Revised posts checks
    revised_path = workspace / "outputs" / "revised_posts.csv"
    expected_revised_header = ["draft_id", "note_id", "revised_text", "cta"]
    revised_rows, revised_err = _safe_read_csv_dicts(revised_path)

    if revised_path.exists() and _header_matches(revised_path, expected_revised_header):
        scores["revised_exists_and_columns"] = 1.0

    if revised_rows is not None and isinstance(drafts_rows, list):
        if len(revised_rows) == len(drafts_rows):
            scores["revised_row_count_exact"] = 1.0

    if revised_rows is not None and isinstance(drafts_rows, list):
        # coverage and note_id match
        ok = True
        revised_ids = [r.get("draft_id", "") for r in revised_rows]
        if set(revised_ids) != set(drafts_by_id.keys()):
            ok = False
        counts = {}
        for did in revised_ids:
            counts[did] = counts.get(did, 0) + 1
        if any(cnt != 1 for cnt in counts.values()):
            ok = False
        if ok:
            for r in revised_rows:
                did = r.get("draft_id", "")
                dr = drafts_by_id.get(did)
                if not dr:
                    ok = False
                    break
                if r.get("note_id", "") != dr.get("note_id", ""):
                    ok = False
                    break
        if ok:
            scores["revised_draft_coverage_and_note_match"] = 1.0

    if revised_rows is not None:
        cta_ok = True
        for r in revised_rows:
            if r.get("cta", "") not in ALLOWED_CTAS:
                cta_ok = False
                break
        if cta_ok:
            scores["revised_cta_valid"] = 1.0

    if revised_rows is not None and isinstance(notes_obj, list):
        txt_ok = True
        for r in revised_rows:
            note = notes_by_id.get(r.get("note_id", ""))
            if not note:
                txt_ok = False
                break
            text = r.get("revised_text", "") or ""
            if len(text) > 220:
                txt_ok = False
                break
            terms = note.get("key_terms", []) or []
            used = _terms_in_text(terms, text)
            if len(used) == 0:
                txt_ok = False
                break
        if txt_ok:
            scores["revised_length_and_key_terms"] = 1.0

    # Status update checks
    status_path = workspace / "outputs" / "status_update.md"
    status_text, status_err = _safe_read_text(status_path)

    if status_text is not None:
        scores["status_exists"] = 1.0

    # Total posts line near top
    if status_text is not None and editorial_rows is not None:
        expected_posts = len(editorial_rows)
        if _line_with_exact_total_posts(status_text, expected_posts, max_line_index=10):
            scores["status_total_posts_line_correct"] = 1.0

    # Overview section: campaign dates and channel distribution
    if status_text is not None and isinstance(events_rows, list):
        overview = _get_section_text(status_text, "Overview")
        if overview:
            # dates
            dates = []
            for ev in events_rows:
                d = _parse_date_iso(ev.get("date", ""))
                if d:
                    dates.append(d)
            if dates:
                earliest = min(dates).isoformat()
                latest = max(dates).isoformat()
            else:
                earliest = ""
                latest = ""
            dates_ok = (earliest in overview) and (latest in overview)

            # channel distribution: each channel and count must appear in the same line
            channel_counts = {}
            for ev in events_rows:
                ch = ev.get("channel", "")
                if ch:
                    channel_counts[ch] = channel_counts.get(ch, 0) + 1
            lines = overview.splitlines()
            dist_ok = True
            for ch, cnt in channel_counts.items():
                found_line = False
                for line in lines:
                    if ch in line and str(cnt) in line:
                        found_line = True
                        break
                if not found_line:
                    dist_ok = False
                    break

            if dates_ok and dist_ok:
                scores["status_overview_dates_and_channels"] = 1.0

    # Highlights: list note titles used and one representative key term per title
    if status_text is not None and editorial_rows is not None and isinstance(notes_obj, list):
        highlights = _get_section_text(status_text, "Highlights")
        if highlights:
            used_note_ids = []
            for r in editorial_rows:
                nid = r.get("source_note_id", "")
                if nid and nid not in used_note_ids:
                    used_note_ids.append(nid)
            ok = True
            for nid in used_note_ids:
                note = notes_by_id.get(nid)
                if not note:
                    ok = False
                    break
                title = note.get("title", "")
                terms = note.get("key_terms", []) or []
                # Require title present and at least one key term present
                if title not in highlights:
                    ok = False
                    break
                # Check at least one term present
                has_term = any((t in highlights) for t in terms)
                if not has_term:
                    ok = False
                    break
            if ok and used_note_ids:
                scores["status_highlights_titles_and_terms"] = 1.0

    # CTAs used line
    if status_text is not None:
        # compute union of CTAs used across both CSV outputs (if available)
        union_ctas = set()
        if editorial_rows is not None:
            for r in editorial_rows:
                c = r.get("cta", "")
                if c:
                    union_ctas.add(c)
        if revised_rows is not None:
            for r in revised_rows:
                c = r.get("cta", "")
                if c:
                    union_ctas.add(c)
        # Require at least one CTA mentioned to consider it meaningful
        if union_ctas:
            found = False
            for line in status_text.splitlines():
                if line.strip().startswith("CTAs used:"):
                    # Verify all CTAs appear in this line
                    if all(cta in line for cta in union_ctas):
                        found = True
                        break
            if found:
                scores["status_ctas_used_line_correct"] = 1.0

    # Next steps: 2–3 actionable items
    if status_text is not None:
        next_steps = _get_section_text(status_text, "Next steps")
        if next_steps:
            # Consider actionable items as non-empty lines, commonly bullets or numbered
            lines = [ln.strip() for ln in next_steps.splitlines()]
            items = []
            for ln in lines:
                if not ln:
                    continue
                if ln.startswith("-") or ln.startswith("*"):
                    items.append(ln)
                elif len(ln) >= 2 and ln[0].isdigit() and (ln[1] == "." or ln[1] == ")"):
                    items.append(ln)
                else:
                    # treat any non-empty line as an actionable item as fallback
                    items.append(ln)
            if 2 <= len(items) <= 3:
                scores["status_next_steps_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()