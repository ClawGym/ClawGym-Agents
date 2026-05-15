import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_heading(text: str) -> str:
    t = text.strip().lower()
    # remove markdown anchor or extra spaces
    t = re.sub(r"\s+", " ", t)
    return t


def _parse_markdown_sections(content: str) -> Dict[str, List[str]]:
    """
    Parse markdown into sections by headings (# ...). Returns a dict where keys
    are normalized headings (lowercase) and values are lists of lines under that heading.
    """
    lines = content.splitlines()
    sections: Dict[str, List[str]] = {}
    current_heading = None
    for line in lines:
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$", line)
        if m:
            current_heading = _normalize_heading(m.group(1))
            sections[current_heading] = []
        else:
            if current_heading is not None:
                sections[current_heading].append(line.rstrip("\n"))
    return sections


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for line in lines:
        m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*\S)\s*$", line)
        if m:
            bullets.append(m.group(1).strip())
    return bullets


def _compute_expected_top_entries(journal_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Filter rows by tags containing any of the terms: ana, rivera, adoption, photo, locket (case-insensitive).
    Sort by relevance_score desc, then by date desc, then by id asc.
    Return the top 5 rows with parsed values where appropriate.
    """
    terms = ["ana", "rivera", "adoption", "photo", "locket"]
    filtered = []
    for r in journal_rows:
        tags = (r.get("tags") or "")
        if any(term in tags.lower() for term in terms):
            # parse needed fields
            rs = _parse_float(r.get("relevance_score"))
            date = r.get("date") or ""
            rid = r.get("id") or ""
            filtered.append({
                "id": rid,
                "date": date,
                "source": r.get("source") or "",
                "author": r.get("author") or "",
                "tags": r.get("tags") or "",
                "relevance_score": rs,
                "summary": r.get("summary") or ""
            })
    # sort
    def sort_key(x):
        # For missing relevance_score, treat as very low
        rs = x["relevance_score"]
        if rs is None:
            rs = -1e9
        # "newest first" -> sort by date descending; YYYY-MM-DD allows lexicographic sort
        date = x["date"] or ""
        # Ties by id ascending
        rid = x["id"] or ""
        # Python sorts ascending; to sort by rs desc and date desc, use negative or reverse tuple
        return (-rs, "" if not date else -int(date.replace("-", "")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else 0, rid)
    # Since the date is string, converting to int YYYYMMDD for descending fine; if malformed, fallback 0
    filtered.sort(key=sort_key)
    return filtered[:5]


def _get_expected_from_input(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    journal_path = workspace / "input" / "journal_entries.csv"
    rows = _safe_read_csv(journal_path)
    if not rows:
        return None
    expected = _compute_expected_top_entries(rows)
    return expected


def _load_top_entries_output(workspace: Path) -> Optional[List[Dict[str, str]]]:
    top_path = workspace / "output" / "top_entries.csv"
    rows = _safe_read_csv(top_path)
    return rows


def _check_schema_order(rows: List[Dict[str, str]], expected_columns: List[str]) -> bool:
    if rows is None:
        return False
    if len(rows) == 0:
        # Still check header via DictReader fieldnames if possible by reading again raw
        return False
    # Verify columns order from first row keys
    # DictReader in Python preserves fieldnames order
    # We cannot get fieldnames here since we already have dicts only; fallback by reading the file header directly
    return True  # Placeholder; will be handled via header read function


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            header = next(rdr, None)
            if header is None:
                return None
            return header
    except Exception:
        return None


def _find_section(sections: Dict[str, List[str]], name_contains: str) -> Optional[List[str]]:
    name_contains = name_contains.lower()
    for k, v in sections.items():
        if name_contains in k:
            return v
    return None


def _get_expected_attendees(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    contacts_path = workspace / "input" / "family_contacts.json"
    contacts = _safe_load_json(contacts_path)
    if contacts is None or not isinstance(contacts, list):
        return None
    filtered = [c for c in contacts if isinstance(c, dict) and c.get("priority") is not None and c.get("priority") <= 2]
    # Sort by priority ascending then name A–Z
    filtered.sort(key=lambda x: (x.get("priority"), x.get("name") or ""))
    return filtered


def _extract_first_indices(text: str, names: List[str]) -> Dict[str, int]:
    indices = {}
    for name in names:
        m = re.search(re.escape(name), text)
        if m:
            indices[name] = m.start()
        else:
            indices[name] = -1
    return indices


def _ids_in_text(text: str) -> List[str]:
    return re.findall(r"\bJ\d{3}\b", text)


def _contains_summary(text: str, summary: str) -> bool:
    # Check if the summary appears verbatim (case-insensitive) as a contiguous substring
    t = re.sub(r"\s+", " ", text).strip().lower()
    s = re.sub(r"\s+", " ", summary).strip().lower()
    return s in t if s else False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "top_entries_exists": 0.0,
        "top_entries_schema_correct": 0.0,
        "top_entries_order_correct": 0.0,
        "top_entries_values_correct": 0.0,
        "top_entries_why_selected_quality": 0.0,
        "meeting_notes_sections_present": 0.0,
        "attendees_list_correct": 0.0,
        "key_evidence_ids_complete": 0.0,
        "key_evidence_paraphrase_nonverbatim": 0.0,
        "agenda_item_count_valid": 0.0,
        "agenda_grounded_in_evidence": 0.0,
        "action_items_count_valid": 0.0,
        "action_items_structure_valid": 0.0,
        "action_items_owners_valid": 0.0,
        "notes_ids_within_top_entries": 0.0,
        "letter_word_count_valid": 0.0,
        "letter_cites_2_to_3_ids_from_top": 0.0,
        "letter_no_verbatim_summaries": 0.0,
        "letter_has_gentle_invitation_with_bring": 0.0,
        "letter_minimize_hedging_and_accusation": 0.0,
    }

    # Expected top entries from input
    expected_top = _get_expected_from_input(workspace)
    expected_ids: List[str] = []
    expected_by_id: Dict[str, Dict[str, Any]] = {}
    if expected_top is not None:
        expected_ids = [r["id"] for r in expected_top]
        expected_by_id = {r["id"]: r for r in expected_top}

    # Check top_entries.csv
    top_path = workspace / "output" / "top_entries.csv"
    if top_path.exists():
        scores["top_entries_exists"] = 1.0
        rows = _safe_read_csv(top_path) or []
        header = _read_csv_header(top_path)
        expected_cols = ["id", "date", "source", "author", "tags", "relevance_score", "summary", "why_selected"]
        if header == expected_cols:
            scores["top_entries_schema_correct"] = 1.0
        else:
            scores["top_entries_schema_correct"] = 0.0

        # Order and value checks only if we can compute expected and header is correct
        if expected_top is not None and header == expected_cols and rows is not None:
            # Verify number of rows equals 5
            ids_out = [r.get("id", "") for r in rows]
            if ids_out == expected_ids:
                scores["top_entries_order_correct"] = 1.0
            else:
                scores["top_entries_order_correct"] = 0.0

            # Values check for fields matching input (except why_selected)
            values_ok = True
            if len(rows) != len(expected_ids):
                values_ok = False
            else:
                for i, r in enumerate(rows[:len(expected_ids)]):
                    eid = expected_ids[i]
                    exp = expected_by_id.get(eid, {})
                    # Compare fields
                    def eq(a: Optional[str], b: Optional[str]) -> bool:
                        return (a or "").strip() == (b or "").strip()

                    if not eq(r.get("date"), exp.get("date")):
                        values_ok = False
                        break
                    if not eq(r.get("source"), exp.get("source")):
                        values_ok = False
                        break
                    if not eq(r.get("author"), exp.get("author")):
                        values_ok = False
                        break
                    if not eq(r.get("tags"), exp.get("tags")):
                        values_ok = False
                        break
                    # relevance_score float compare
                    rs_out = _parse_float(r.get("relevance_score"))
                    rs_exp = exp.get("relevance_score")
                    if rs_out is None or rs_exp is None or abs(rs_out - rs_exp) > 1e-6:
                        values_ok = False
                        break
                    if not eq(r.get("summary"), exp.get("summary")):
                        values_ok = False
                        break
            scores["top_entries_values_correct"] = 1.0 if values_ok else 0.0

            # why_selected quality: one sentence, non-empty, mentions relevant keyword
            why_scores = []
            kw = ["ana", "rivera", "adoption", "photo", "locket", "family", "connection", "mother", "hospital"]
            for r in rows[:len(expected_ids)]:
                why = (r.get("why_selected") or "").strip()
                if not why:
                    why_scores.append(0.0)
                    continue
                # sentence boundary count
                # Count occurrences of sentence-ending punctuation
                enders = len(re.findall(r"[.!?]", why))
                one_sentence_like = enders <= 2  # allow at most 2 punctuation marks to be tolerant
                mentions_kw = any(k in why.lower() for k in kw)
                ok = one_sentence_like and mentions_kw
                why_scores.append(1.0 if ok else 0.0)
            if why_scores:
                scores["top_entries_why_selected_quality"] = sum(why_scores) / len(why_scores)
            else:
                scores["top_entries_why_selected_quality"] = 0.0
        else:
            # can't assess order/values without expected inputs or schema
            scores["top_entries_order_correct"] = 0.0
            scores["top_entries_values_correct"] = 0.0
            scores["top_entries_why_selected_quality"] = 0.0
    else:
        # File missing: leave zeros
        pass

    # Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path) or ""
    if notes_text:
        sections = _parse_markdown_sections(notes_text)
        attendees_sec = _find_section(sections, "attendees")
        agenda_sec = _find_section(sections, "agenda")
        key_evidence_sec = _find_section(sections, "key evidence")
        action_items_sec = _find_section(sections, "action items")
        if attendees_sec is not None and agenda_sec is not None and key_evidence_sec is not None and action_items_sec is not None:
            scores["meeting_notes_sections_present"] = 1.0

        # Attendees list correct
        expected_attendees = _get_expected_attendees(workspace)
        if expected_attendees is not None and attendees_sec is not None:
            expected_names = [a.get("name") for a in expected_attendees if a.get("name")]
            attendees_text = "\n".join(attendees_sec)
            # Verify each expected name appears
            all_present = all(name in attendees_text for name in expected_names)
            # Verify excluded (Carlos Rivera) not present
            excluded_ok = "Carlos Rivera" not in attendees_text
            # Verify order: by first appearance indices
            indices = _extract_first_indices(attendees_text, expected_names)
            order_ok = True
            if all(val >= 0 for val in indices.values()):
                idx_list = [indices[name] for name in expected_names]
                order_ok = idx_list == sorted(idx_list)
            else:
                order_ok = False
            if all_present and excluded_ok and order_ok:
                scores["attendees_list_correct"] = 1.0
            else:
                scores["attendees_list_correct"] = 0.0

        # Key Evidence
        if key_evidence_sec is not None:
            bullets_ke = _extract_bullets(key_evidence_sec)
            # IDs complete: must include all five expected ids from top_entries.csv output if available
            # Load produced top_entries.csv ids (preferred), else expected_ids
            produced_top_rows = _load_top_entries_output(workspace)
            produced_ids = []
            summaries_by_id = {}
            if produced_top_rows:
                produced_ids = [r.get("id", "") for r in produced_top_rows]
                # For paraphrase checks, map id to summary from produced file if available, else expected
                for r in produced_top_rows:
                    if r.get("id"):
                        summaries_by_id[r["id"]] = r.get("summary", "")
            if not produced_ids and expected_ids:
                produced_ids = expected_ids[:]
                summaries_by_id = {eid: expected_by_id[eid]["summary"] for eid in expected_ids}
            ids_present = True
            if produced_ids:
                for eid in produced_ids[:5]:
                    found = any(re.search(rf"\b{re.escape(eid)}\b", b) for b in bullets_ke)
                    if not found:
                        ids_present = False
                        break
            else:
                ids_present = False
            scores["key_evidence_ids_complete"] = 1.0 if ids_present else 0.0

            # Paraphrase non-verbatim: line should not copy summary verbatim
            paraphrase_scores = []
            if produced_ids:
                for eid in produced_ids[:5]:
                    # find bullet for eid
                    match_line = None
                    for b in bullets_ke:
                        if re.search(rf"\b{re.escape(eid)}\b", b):
                            match_line = b
                            break
                    if not match_line:
                        paraphrase_scores.append(0.0)
                        continue
                    summary = summaries_by_id.get(eid, "")
                    non_verbatim = not _contains_summary(match_line, summary)
                    # Also enforce it's one line (by bullet nature) and has some content besides id
                    has_content = len(match_line.strip()) > len(eid) + 3
                    paraphrase_scores.append(1.0 if (non_verbatim and has_content) else 0.0)
            if paraphrase_scores:
                scores["key_evidence_paraphrase_nonverbatim"] = sum(paraphrase_scores) / len(paraphrase_scores)
            else:
                scores["key_evidence_paraphrase_nonverbatim"] = 0.0

        # Agenda checks
        if agenda_sec is not None:
            bullets_agenda = _extract_bullets(agenda_sec)
            if 3 <= len(bullets_agenda) <= 5:
                scores["agenda_item_count_valid"] = 1.0
            # Grounding: at least 2 items mention an id or a relevant keyword
            relevant_kw = ["records", "photo", "locket", "archive", "hospital", "adoption", "caption", "letters", "evidence"]
            grounded = 0
            for b in bullets_agenda:
                if re.search(r"\bJ\d{3}\b", b):
                    grounded += 1
                elif any(k in b.lower() for k in relevant_kw):
                    grounded += 1
            if len(bullets_agenda) > 0 and grounded >= 2:
                scores["agenda_grounded_in_evidence"] = 1.0

        # Action Items checks
        if action_items_sec is not None:
            bullets_ai = _extract_bullets(action_items_sec)
            if 4 <= len(bullets_ai) <= 6:
                scores["action_items_count_valid"] = 1.0
            # Structure valid: each contains at least one id reference in parentheses and some task-like text
            # Owners valid: each includes an attendee name
            attendees_list = _get_expected_attendees(workspace)
            attendee_names = [a["name"] for a in attendees_list] if attendees_list else []
            structure_count = 0
            owners_count = 0
            for b in bullets_ai:
                has_id_in_paren = bool(re.search(r"\(J\d{3}(?:[,\s]*J\d{3})*\)", b))
                task_like = len(b.strip()) >= 20
                if has_id_in_paren and task_like:
                    structure_count += 1
                has_owner = any(name in b for name in attendee_names)
                if has_owner:
                    owners_count += 1
            if bullets_ai:
                scores["action_items_structure_valid"] = structure_count / len(bullets_ai)
                scores["action_items_owners_valid"] = owners_count / len(bullets_ai)

        # Notes ids within top entries
        if expected_ids:
            all_ids_in_notes = set(_ids_in_text(notes_text))
            if all_ids_in_notes and all(i in expected_ids for i in all_ids_in_notes):
                scores["notes_ids_within_top_entries"] = 1.0
            elif not all_ids_in_notes:
                # If no ids referenced at all, fail
                scores["notes_ids_within_top_entries"] = 0.0
            else:
                scores["notes_ids_within_top_entries"] = 0.0

    # Letter checks
    letter_path = workspace / "output" / "rewritten_letter_to_Ana.md"
    letter_text = _safe_read_text(letter_path) or ""
    if letter_text:
        words = re.findall(r"\b\w+\b", letter_text)
        wc = len(words)
        if 250 <= wc <= 400:
            scores["letter_word_count_valid"] = 1.0

        # IDs cited
        cited_ids = list(dict.fromkeys(re.findall(r"\(J(\d{3})\)", letter_text)))  # capture numbers within parentheses
        cited_ids_full = [f"J{n}" for n in cited_ids]
        unique_count = len(set(cited_ids_full))
        if expected_ids and 2 <= unique_count <= 3 and all(cid in expected_ids for cid in cited_ids_full):
            scores["letter_cites_2_to_3_ids_from_top"] = 1.0

        # No verbatim summaries
        no_verbatim = True
        if expected_by_id:
            for eid, rec in expected_by_id.items():
                if _contains_summary(letter_text, rec.get("summary", "")):
                    no_verbatim = False
                    break
        scores["letter_no_verbatim_summaries"] = 1.0 if no_verbatim else 0.0

        # Closing invitation to meet with bringing notes/artifacts
        tail = letter_text[-400:].lower()
        invite = ("meet" in tail or "meeting" in tail) and ("bring" in tail) and any(
            k in tail for k in ["notes", "artifacts", "agenda", "photo", "locket"]
        )
        scores["letter_has_gentle_invitation_with_bring"] = 1.0 if invite else 0.0

        # Minimize hedging and accusations
        hedging_terms = [
            "maybe", "probably", "possibly", "might", "unsure", "not sure", "i guess", "i think", "i'm not sure",
            "could be", "perhaps"
        ]
        accusatory_terms = ["blame", "fault", "accuse", "accus", "guilt", "lied", "deceiv", "culprit"]
        lt = letter_text.lower()
        hedge_count = 0
        for h in hedging_terms:
            hedge_count += lt.count(h)
        any_accusatory = any(a in lt for a in accusatory_terms)
        # Require minimal hedging and no accusatory terms
        if hedge_count <= 2 and not any_accusatory:
            scores["letter_minimize_hedging_and_accusation"] = 1.0
        else:
            scores["letter_minimize_hedging_and_accusation"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()