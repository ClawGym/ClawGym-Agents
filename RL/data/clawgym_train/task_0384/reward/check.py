import json
import csv
import re
import sys
from pathlib import Path
from datetime import date
from typing import Dict, List, Tuple, Optional


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[dict]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv(p: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _extract_sections(md_text: str) -> Dict[str, Dict[str, object]]:
    """
    Return dict:
      key: normalized header (lower-case stripped)
      value: {"title": original title, "content": full content string, "lines": list of lines}
    Allows any level of '#' for headers; treats any header as section delimiter.
    """
    sections: Dict[str, Dict[str, object]] = {}
    current_title = None
    current_lines: List[str] = []
    for line in md_text.splitlines():
        if re.match(r'^\s*#{1,6}\s+', line):
            # Save previous
            if current_title is not None:
                norm = current_title.strip().lower()
                sections[norm] = {
                    "title": current_title.strip(),
                    "content": "\n".join(current_lines).strip(),
                    "lines": current_lines[:],
                }
            # Start new
            current_title = re.sub(r'^\s*#{1,6}\s+', '', line).strip()
            current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line.rstrip())
    # Save last
    if current_title is not None:
        norm = current_title.strip().lower()
        sections[norm] = {
            "title": current_title.strip(),
            "content": "\n".join(current_lines).strip(),
            "lines": current_lines[:],
        }
    return sections


def _find_section_by_keywords(sections: Dict[str, Dict[str, object]], keywords: List[str]) -> Optional[Dict[str, object]]:
    for norm_title, payload in sections.items():
        if all(k.lower() in norm_title for k in keywords):
            return payload
    return None


def _extract_bullets(text: str) -> List[str]:
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r'^\s*[-*]\s+', ln):
            bullets.append(re.sub(r'^\s*[-*]\s+', '', ln).strip())
    return bullets


def _today_str() -> str:
    return date.today().isoformat()


def _parse_todos(prior_text: str) -> List[str]:
    todos = []
    for ln in prior_text.splitlines():
        s = ln.strip()
        if s.startswith("[TODO]"):
            # exclude if contains other status markers
            if ("[DONE]" in s) or ("[BLOCKED]" in s) or ("[IN REVIEW]" in s):
                continue
            todos.append(s)
    return todos


def _collect_valid_citation_tokens(search_log: dict) -> Tuple[set, List[dict]]:
    valid = set()
    queries = search_log.get("queries")
    if not isinstance(queries, list):
        return valid, []
    for q in queries:
        qid = q.get("id")
        results = q.get("results", [])
        for r in results:
            rid = r.get("id")
            if isinstance(qid, str) and isinstance(rid, str):
                token = f"[{qid}-{rid}]"
                valid.add(token)
    return valid, queries


def _extract_tokens(text: str) -> List[str]:
    return re.findall(r'\[Q\d+-R\d+\]', text)


def _members_map(members_rows: List[Dict[str, str]]) -> Dict[str, str]:
    # Map name -> role
    mapping = {}
    for r in members_rows:
        name = (r.get("name") or "").strip()
        role = (r.get("role") or "").strip()
        if name:
            mapping[name] = role
    return mapping


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_structure": 0.0,
        "search_queries_requirements": 0.0,
        "meeting_notes_title_and_date": 0.0,
        "meeting_notes_sections_presence": 0.0,
        "agenda_overview_covers_topics": 0.0,
        "highlights_bullets_and_citations": 0.0,
        "content_ideas_minimum": 0.0,
        "outreach_plan_minimum": 0.0,
        "carried_over_items_in_notes": 0.0,
        "notes_citations_valid": 0.0,
        "action_items_csv_structure": 0.0,
        "action_items_rows_valid": 0.0,
        "carried_over_items_in_csv": 0.0,
        "crosslink_notes_and_csv_action_items": 0.0,
        "sources_section_explains_citations": 0.0,
        "owners_match_members": 0.0,
    }

    # Paths
    search_log_path = workspace / "data" / "search_log.json"
    notes_path = workspace / "notes" / "meeting_notes.md"
    actions_csv_path = workspace / "notes" / "action_items.csv"
    agenda_path = workspace / "input" / "agenda.md"
    prior_notes_path = workspace / "input" / "prior_notes.md"
    members_path = workspace / "input" / "members.csv"

    # Load inputs
    search_log = _load_json(search_log_path)
    agenda_text = _read_text(agenda_path) or ""
    prior_text = _read_text(prior_notes_path) or ""
    members_headers, members_rows = _parse_csv(members_path)
    members_mapping = _members_map(members_rows or [])

    # Validate search log structure
    valid_tokens = set()
    if isinstance(search_log, dict) and isinstance(search_log.get("queries"), list) and len(search_log["queries"]) >= 2:
        structure_ok = True
        for q in search_log["queries"]:
            if not isinstance(q, dict):
                structure_ok = False
                break
            if not isinstance(q.get("id"), str):
                structure_ok = False
                break
            if not isinstance(q.get("query"), str):
                structure_ok = False
                break
            if not isinstance(q.get("timestamp"), str):
                structure_ok = False
                break
            res = q.get("results")
            if not isinstance(res, list):
                structure_ok = False
                break
            if not (3 <= len(res) <= 5):
                structure_ok = False
                break
            for r in res:
                if not isinstance(r, dict):
                    structure_ok = False
                    break
                if not isinstance(r.get("id"), str):
                    structure_ok = False
                    break
                if not isinstance(r.get("title"), str):
                    structure_ok = False
                    break
                if not isinstance(r.get("url"), str):
                    structure_ok = False
                    break
            if structure_ok is False:
                break
        if structure_ok:
            scores["search_log_structure"] = 1.0
        valid_tokens, queries = _collect_valid_citation_tokens(search_log)
    else:
        scores["search_log_structure"] = 0.0

    # Validate search queries content
    queries_ok = False
    if isinstance(search_log, dict) and isinstance(search_log.get("queries"), list) and len(search_log["queries"]) >= 2:
        req_phrase = "francesc bonet"
        any_keywords = ["awards", "recognition", "biography", "interview", "festival", "press"]
        q_ok_count = 0
        for q in search_log["queries"]:
            qstr = (q.get("query") or "").lower()
            if req_phrase in qstr and any(k in qstr for k in any_keywords):
                q_ok_count += 1
        if q_ok_count >= 2:
            queries_ok = True
    scores["search_queries_requirements"] = 1.0 if queries_ok else 0.0

    # Meeting notes checks
    notes_text = _read_text(notes_path) or ""
    if notes_text:
        # Title and today's date
        lines = [ln for ln in notes_text.splitlines()]
        first_nonempty_idx = None
        for i, ln in enumerate(lines):
            if ln.strip():
                first_nonempty_idx = i
                break
        title_ok = False
        date_ok = False
        if first_nonempty_idx is not None:
            title_ok = lines[first_nonempty_idx].lstrip().startswith("#")
            # Date in first 10 lines
            today = _today_str()
            date_ok = any(today in (lines[i] if i < len(lines) else "") for i in range(first_nonempty_idx, min(len(lines), first_nonempty_idx + 10)))
        if title_ok and date_ok:
            scores["meeting_notes_title_and_date"] = 1.0

        # Sections presence
        sections = _extract_sections(notes_text)
        sect_agenda = _find_section_by_keywords(sections, ["agenda", "overview"])
        sect_highlights = _find_section_by_keywords(sections, ["highlights"])
        sect_content = _find_section_by_keywords(sections, ["content", "ideas"])
        sect_outreach = _find_section_by_keywords(sections, ["outreach", "plan"])
        sect_carried = _find_section_by_keywords(sections, ["carried", "previous"])
        sect_actions = _find_section_by_keywords(sections, ["action", "items"])
        sect_sources = _find_section_by_keywords(sections, ["sources"])
        if all(s is not None for s in [sect_agenda, sect_highlights, sect_content, sect_outreach, sect_carried, sect_actions, sect_sources]):
            scores["meeting_notes_sections_presence"] = 1.0

        # Agenda overview covers topics from agenda.md
        agenda_topics = []
        if agenda_text:
            for ln in agenda_text.splitlines():
                if re.match(r'^\s*\d+\.\s+', ln):
                    agenda_topics.append(re.sub(r'^\s*\d+\.\s+', '', ln).strip())
        agenda_keywords = ["highlights", "content ideas", "outreach", "carried-over", "action items"]
        agenda_ok = False
        if sect_agenda:
            agenda_content_lower = (sect_agenda.get("content") or "").lower()
            agenda_ok = all(any(k in agenda_content_lower for k in [kw]) for kw in agenda_keywords)
        scores["agenda_overview_covers_topics"] = 1.0 if agenda_ok else 0.0

        # Highlights bullets and citations
        highlights_ok = False
        if sect_highlights:
            bullets = _extract_bullets(sect_highlights.get("content") or "")
            count_ok = 5 <= len(bullets) <= 8
            citations_ok = True
            for b in bullets:
                tokens = _extract_tokens(b)
                if len(tokens) < 1:
                    citations_ok = False
                    break
                # Must be in valid set if search log exists
                if valid_tokens:
                    if not all(t in valid_tokens for t in tokens):
                        citations_ok = False
                        break
            highlights_ok = count_ok and citations_ok
        scores["highlights_bullets_and_citations"] = 1.0 if highlights_ok else 0.0

        # Content ideas minimum
        content_ok = False
        if sect_content:
            bullets = _extract_bullets(sect_content.get("content") or "")
            content_ok = len(bullets) >= 3
        scores["content_ideas_minimum"] = 1.0 if content_ok else 0.0

        # Outreach plan minimum
        outreach_ok = False
        if sect_outreach:
            bullets = _extract_bullets(sect_outreach.get("content") or "")
            if len(bullets) >= 2:
                # Ensure each bullet has some rationale (length heuristic)
                rationale_ok = all(len(b) >= 10 for b in bullets)
                outreach_ok = rationale_ok
        scores["outreach_plan_minimum"] = 1.0 if outreach_ok else 0.0

        # Carried-over items listed verbatim
        expected_todos = _parse_todos(prior_text)
        carried_ok = False
        if sect_carried:
            content = sect_carried.get("content") or ""
            carried_ok = all(todo in content for todo in expected_todos) and len(expected_todos) > 0
        scores["carried_over_items_in_notes"] = 1.0 if carried_ok else 0.0

        # Notes citations are valid and only from search_log.json
        all_tokens = _extract_tokens(notes_text)
        notes_citations_ok = False
        if all_tokens:
            if valid_tokens:
                notes_citations_ok = all(t in valid_tokens for t in all_tokens)
            else:
                notes_citations_ok = False
        else:
            # Allow no citations only if highlights check failed? But requirement demands citations.
            notes_citations_ok = False
        scores["notes_citations_valid"] = 1.0 if notes_citations_ok else 0.0

        # Sources section explains citation format and mentions search log path
        sources_ok = False
        if sect_sources:
            sc = (sect_sources.get("content") or "")
            if ("[Q" in sc and "-R" in sc) and ("workspace/data/search_log.json" in sc):
                sources_ok = True
        scores["sources_section_explains_citations"] = 1.0 if sources_ok else 0.0

    # Action items CSV checks
    headers, rows = _parse_csv(actions_csv_path)
    required_headers = ["item", "source_section", "owner_name", "owner_role", "status", "citation_refs"]
    if headers == required_headers and isinstance(rows, list):
        scores["action_items_csv_structure"] = 1.0
    else:
        scores["action_items_csv_structure"] = 0.0
        rows = rows or []

    # Owners match members (CSV)
    owners_ok = False
    if rows and members_rows:
        owners_ok = True
        for r in rows:
            oname = (r.get("owner_name") or "").strip()
            orole = (r.get("owner_role") or "").strip()
            if not oname or not orole:
                owners_ok = False
                break
            # Check exact mapping exists in members.csv
            expected_role = members_mapping.get(oname)
            if expected_role != orole:
                owners_ok = False
                break
    scores["owners_match_members"] = 1.0 if owners_ok else 0.0

    # Action items rows valid: source_section values, status rules, citations validity for new items
    rows_valid = False
    if rows:
        allowed_sections = {"Carried-Over", "New-Content", "Outreach"}
        rows_valid = True
        for r in rows:
            item = (r.get("item") or "").strip()
            source_section = (r.get("source_section") or "").strip()
            status = (r.get("status") or "").strip()
            citrefs = (r.get("citation_refs") or "").strip()
            if not item or source_section not in allowed_sections:
                rows_valid = False
                break
            if source_section == "Carried-Over":
                if status != "Carry-Over":
                    rows_valid = False
                    break
                # Carried-over items may have empty citations; if present, validate tokens
                if citrefs:
                    tokens = [t.strip() for t in citrefs.split(";") if t.strip()]
                    if valid_tokens:
                        if not all(t in valid_tokens for t in tokens):
                            rows_valid = False
                            break
            else:
                # New items must be status New
                if status != "New":
                    rows_valid = False
                    break
                # Require at least one valid citation token
                tokens = [t.strip() for t in citrefs.split(";") if t.strip()]
                if len(tokens) == 0:
                    rows_valid = False
                    break
                if valid_tokens:
                    if not all(t in valid_tokens for t in tokens):
                        rows_valid = False
                        break
                else:
                    rows_valid = False
                    break
    scores["action_items_rows_valid"] = 1.0 if rows_valid else 0.0

    # Carried-over items must appear in CSV with exact wording and flags
    carried_csv_ok = False
    expected_todos = _parse_todos(prior_text)
    if rows and expected_todos:
        carried_csv_ok = True
        for todo in expected_todos:
            found = False
            for r in rows:
                if (r.get("item") or "").strip() == todo and (r.get("source_section") or "").strip() == "Carried-Over" and (r.get("status") or "").strip() == "Carry-Over":
                    # owner checked in owners_ok
                    found = True
                    break
            if not found:
                carried_csv_ok = False
                break
    scores["carried_over_items_in_csv"] = 1.0 if carried_csv_ok else 0.0

    # Crosslink: every action item in notes appears in CSV and vice versa; and owners shown in notes
    crosslink_ok = False
    if notes_text and rows:
        sections = _extract_sections(notes_text)
        sect_actions = _find_section_by_keywords(sections, ["action", "items"])
        if sect_actions:
            action_bullets = _extract_bullets(sect_actions.get("content") or "")
            # 1) Every CSV item appears in one bullet
            csv_to_notes_ok = True
            for r in rows:
                item_txt = (r.get("item") or "").strip()
                owner_name = (r.get("owner_name") or "").strip()
                owner_role = (r.get("owner_role") or "").strip()
                # bullet must contain item text and owner name + role
                matched_bullet = None
                for b in action_bullets:
                    if item_txt and item_txt in b:
                        matched_bullet = b
                        break
                if matched_bullet is None:
                    csv_to_notes_ok = False
                    break
                if owner_name not in matched_bullet or owner_role not in matched_bullet:
                    csv_to_notes_ok = False
                    break
            # 2) Each bullet should correspond to some CSV item
            notes_to_csv_ok = True
            for b in action_bullets:
                # find at least one csv row whose item is in the bullet
                if not any((r.get("item") or "").strip() and (r.get("item") or "").strip() in b for r in rows):
                    notes_to_csv_ok = False
                    break
            crosslink_ok = csv_to_notes_ok and notes_to_csv_ok and len(action_bullets) > 0
    scores["crosslink_notes_and_csv_action_items"] = 1.0 if crosslink_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()