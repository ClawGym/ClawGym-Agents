import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_themes(path: Path) -> Tuple[List[Dict[str, str]], List[str], Dict[str, Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if not rows:
        return [], [], {}
    theme_ids = []
    theme_map: Dict[str, Dict[str, str]] = {}
    for row in rows:
        tid = row.get("theme_id", "").strip()
        if tid:
            theme_ids.append(tid)
            theme_map[tid] = {
                "theme_title": row.get("theme_title", "").strip(),
                "brief_note": row.get("brief_note", "").strip(),
            }
    return rows, theme_ids, theme_map


def _is_valid_year(year_val: Any) -> bool:
    if year_val is None:
        return False
    s = str(year_val).strip()
    if s == "":
        return True  # blank allowed
    if not re.fullmatch(r"\d{4}", s):
        return False
    year_num = int(s)
    return 1800 <= year_num <= 2100


def _is_valid_resource_type(s: Any) -> bool:
    allowed = {"report", "law/act", "archive page", "museum page", "article", "other"}
    return isinstance(s, str) and s in allowed


def _extract_citations_from_line(line: str) -> List[str]:
    # Extract all IDs in the form [SRC:ID] including multiple like [SRC:ID1, SRC:ID2]
    ids: List[str] = []
    # find all bracket contents
    for bracket_content in re.findall(r"\[([^\]]+)\]", line):
        for mid in re.findall(r"SRC:([A-Za-z0-9]+)", bracket_content):
            ids.append(mid.strip())
    return ids


def _parse_outline_citations_by_theme(text: str, theme_ids: List[str]) -> Dict[str, List[str]]:
    citations: Dict[str, List[str]] = {tid: [] for tid in theme_ids}
    lines = text.splitlines()
    for tid in theme_ids:
        pat = re.compile(r"^\s*-\s*" + re.escape(tid) + r"\b", flags=re.IGNORECASE)
        for line in lines:
            if pat.search(line):
                ids = _extract_citations_from_line(line)
                citations[tid] = ids
                break
    return citations


def _find_theme_line(text: str, theme_id: str) -> Optional[str]:
    for line in text.splitlines():
        if re.match(r"^\s*-\s*" + re.escape(theme_id) + r"\b", line):
            return line
    return None


def _is_moldovan_official_domain(domain: str) -> bool:
    if not isinstance(domain, str):
        return False
    d = domain.strip().lower()
    if d.endswith(".gov.md"):
        return True
    # Common official Moldovan institutional domains (non-exhaustive)
    official_candidates = {
        "parlament.md",
        "gov.md",  # main portal
        "presedinte.md",
        "mec.gov.md",
        "justice.gov.md",
        "ms.gov.md",
        "mf.gov.md",
        "mfa.gov.md",
        "mei.gov.md",
        "mma.gov.md",
    }
    if d in official_candidates:
        return True
    return False


def _is_international_org_domain(domain: str) -> bool:
    if not isinstance(domain, str):
        return False
    d = domain.strip().lower()
    if d.endswith(".int"):
        return True
    international_indicators = (
        "un.org",
        "unesco.org",
        "coe.int",
        "osce.org",
        "worldbank.org",
        "europa.eu",
        "europarl.europa.eu",
        "ec.europa.eu",
        "euneighbours.eu",
        "councilofeurope.int",
        "oecd.org",
        "who.int",
    )
    return any(ind in d for ind in international_indicators)


def _parse_sources_json(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], List[str]]:
    data = _load_json(path)
    errors: List[str] = []
    if not isinstance(data, list):
        return None, ["sources.json not a list"]
    return data, errors


def _parse_theme_source_map(path: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(path)


def _parse_meeting_sections(text: str) -> Dict[str, List[str]]:
    # Split into sections by lines that exactly start with "Agenda:", "Research Updates:", "Decisions Needed:", "Action Items:"
    lines = text.splitlines()
    sections = {"Agenda": [], "Research Updates": [], "Decisions Needed": [], "Action Items": []}
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Agenda:"):
            current = "Agenda"
            continue
        if stripped.startswith("Research Updates:"):
            current = "Research Updates"
            continue
        if stripped.startswith("Decisions Needed:"):
            current = "Decisions Needed"
            continue
        if stripped.startswith("Action Items:"):
            current = "Action Items"
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _count_agenda_bullets(section_lines: List[str]) -> int:
    count = 0
    for line in section_lines:
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            count += 1
    return count


def _extract_research_updates_counts(section_lines: List[str], theme_ids: List[str]) -> Dict[str, Optional[int]]:
    text = "\n".join(section_lines)
    counts: Dict[str, Optional[int]] = {}
    for tid in theme_ids:
        # Find number following the theme mention
        # e.g., "T1: 2 sources" or "T1 — 3"
        m = re.search(rf"{re.escape(tid)}[^0-9]*([0-9]+)", text)
        if m:
            counts[tid] = int(m.group(1))
        else:
            counts[tid] = None
    return counts


def _extract_action_items(section_lines: List[str]) -> List[str]:
    # Return non-empty lines that look like items (either list or table rows)
    items = []
    for line in section_lines:
        if line.strip() == "":
            continue
        # Collect all lines; parsing will happen later
        items.append(line)
    return items


def _find_assignment_line_for_theme(items: List[str], theme_id: str) -> List[str]:
    matches = []
    for line in items:
        if re.search(rf"\b{re.escape(theme_id)}\b", line):
            matches.append(line)
    return matches


def _extract_emails(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)


def _extract_source_ids(text: str) -> List[str]:
    return re.findall(r"\bSRC[0-9]+\b", text)


def _tokenize(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def _compute_best_match_volunteers(theme_info: Dict[str, str], roster: List[Dict[str, str]]) -> Tuple[int, List[str]]:
    # Returns (max_score, list_of_best_names)
    title = theme_info.get("theme_title", "")
    note = theme_info.get("brief_note", "")
    theme_tokens = set(_tokenize(title) + _tokenize(note))
    best_score = -1
    best_names: List[str] = []
    for row in roster:
        focus_tokens = set(_tokenize(row.get("focus_area", "")))
        score = len(theme_tokens & focus_tokens)
        if score > best_score:
            best_score = score
            best_names = [row.get("name", "")]
        elif score == best_score:
            best_names.append(row.get("name", ""))
    # If all zero and empty names, return zero score and all names considered best to avoid false negatives
    if best_score < 0:
        best_score = 0
        best_names = [row.get("name", "") for row in roster]
    return best_score, best_names


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "sources_json_exists_and_valid_structure": 0.0,
        "sources_resource_count_range": 0.0,
        "sources_ids_unique_and_pattern": 0.0,
        "sources_allowed_resource_types": 0.0,
        "sources_theme_ids_valid": 0.0,
        "sources_contains_official_moldovan_domain": 0.0,
        "sources_contains_international_org": 0.0,
        "theme_source_map_exists_and_valid": 0.0,
        "map_covers_all_themes_exactly_once": 0.0,
        "map_only_existing_source_ids": 0.0,
        "outline_updated_exists": 0.0,
        "outline_structure_preserved": 0.0,
        "outline_all_themes_cited": 0.0,
        "outline_todos_removed": 0.0,
        "map_outline_consistency": 0.0,
        "meeting_notes_exists_structure": 0.0,
        "meeting_agenda_count": 0.0,
        "meeting_research_updates_counts_correct": 0.0,
        "meeting_decisions_needed_includes_single_source_themes": 0.0,
        "meeting_action_items_assignments_complete": 0.0,
        "meeting_action_items_one_per_theme": 0.0,
        "meeting_action_items_volunteer_valid": 0.0,
        "meeting_action_items_due_tbd_present": 0.0,
        "meeting_action_items_sources_valid": 0.0,
        "meeting_assignments_best_match": 0.0,
    }

    # Load inputs
    themes_csv = workspace / "input" / "themes.csv"
    team_csv = workspace / "input" / "team_roster.csv"
    orig_outline_path = workspace / "input" / "exhibit_outline.md"  # not strictly needed for grading but may help
    themes_rows, theme_ids, theme_info_map = _parse_themes(themes_csv)
    roster_rows = _read_csv_dicts(team_csv) or []

    # Load outputs
    outputs_dir = workspace / "outputs"
    sources_path = outputs_dir / "sources.json"
    map_path = outputs_dir / "theme_source_map.csv"
    outline_updated_path = outputs_dir / "exhibit_outline_updated.md"
    meeting_notes_path = outputs_dir / "meeting_notes.md"

    # Parse sources.json
    sources_data, src_errors = _parse_sources_json(sources_path)
    if isinstance(sources_data, list):
        scores["sources_json_exists_and_valid_structure"] = 1.0

        # Validate entries and resource constraints
        ids = []
        valid_types = True
        valid_years_and_fields = True
        valid_theme_refs = True
        official_present = False
        intl_present = False

        allowed_resource_types = {"report", "law/act", "archive page", "museum page", "article", "other"}

        # Count
        if 7 <= len(sources_data) <= 10:
            scores["sources_resource_count_range"] = 1.0

        for item in sources_data:
            # id
            sid = item.get("id")
            if isinstance(sid, str) and re.fullmatch(r"SRC\d+", sid):
                ids.append(sid)
            else:
                ids.append(None)  # to break uniqueness later

            # resource_type
            if not _is_valid_resource_type(item.get("resource_type")):
                valid_types = False

            # year
            if not _is_valid_year(item.get("year", "")):
                valid_years_and_fields = False

            # access_date: require non-empty string
            ad = item.get("access_date")
            if not isinstance(ad, str) or ad.strip() == "":
                valid_years_and_fields = False

            # required string fields
            for fld in ["title", "organization", "host_domain", "query_used", "summary"]:
                val = item.get(fld)
                if not isinstance(val, str) or (fld != "year" and val.strip() == ""):
                    valid_years_and_fields = False

            # summary 1-2 sentences heuristic
            summary = item.get("summary", "")
            # Count sentences by ., !, ?
            parts = [p for p in re.split(r"[.!?]+", summary) if p.strip()]
            if not (1 <= len(parts) <= 2):
                valid_years_and_fields = False

            # theme_ids
            tids = item.get("theme_ids")
            if not isinstance(tids, list) or not tids:
                valid_theme_refs = False
            else:
                # all must be valid themes present in input
                for t in tids:
                    if t not in theme_ids:
                        valid_theme_refs = False

            # domains category checks
            host_domain = str(item.get("host_domain", "")).strip().lower()
            if _is_moldovan_official_domain(host_domain):
                official_present = True
            if _is_international_org_domain(host_domain):
                intl_present = True

        # Unique and pattern
        if ids and all(isinstance(x, str) for x in ids) and len(set(ids)) == len(ids):
            scores["sources_ids_unique_and_pattern"] = 1.0

        if valid_types:
            scores["sources_allowed_resource_types"] = 1.0

        if valid_theme_refs:
            scores["sources_theme_ids_valid"] = 1.0

        if official_present:
            scores["sources_contains_official_moldovan_domain"] = 1.0

        if intl_present:
            scores["sources_contains_international_org"] = 1.0

        # If summary, year, access_date and strings valid
        if valid_years_and_fields and scores["sources_json_exists_and_valid_structure"] == 1.0:
            # No explicit separate key; keep core checks above
            pass
    else:
        # No sources.json or malformed
        pass

    # Parse theme_source_map.csv
    theme_map_rows = _parse_theme_source_map(map_path)
    map_valid = False
    mapping: Dict[str, List[str]] = {}
    sources_ids_set = set()
    if isinstance(sources_data, list):
        sources_ids_set = {it.get("id") for it in sources_data if isinstance(it.get("id"), str)}
    if theme_map_rows is not None:
        # Basic existence valid
        scores["theme_source_map_exists_and_valid"] = 1.0
        # Build mapping
        for row in theme_map_rows:
            tid = (row.get("theme_id") or "").strip()
            sids = (row.get("source_ids") or "").strip()
            if tid:
                sid_list = [s.strip() for s in sids.split(",") if s.strip()]
                mapping[tid] = sid_list
        # Covers all themes exactly once
        if set(mapping.keys()) == set(theme_ids) and all(len([r for r in theme_map_rows if (r.get("theme_id") or "").strip() == tid]) == 1 for tid in theme_ids):
            scores["map_covers_all_themes_exactly_once"] = 1.0
        # Only existing source IDs and at least one per theme
        only_existing = True
        for tid, sid_list in mapping.items():
            if not sid_list:
                only_existing = False
                break
            for sid in sid_list:
                if sid not in sources_ids_set:
                    only_existing = False
                    break
        if only_existing:
            scores["map_only_existing_source_ids"] = 1.0

    # Outline updated checks
    outline_text = _read_text(outline_updated_path)
    if isinstance(outline_text, str):
        scores["outline_updated_exists"] = 1.0
        # Structure preserved: check main title and section headings exist
        structure_ok = True
        required_headings = [
            "# Community Exhibit: Moldovan Identity After the Soviet Period",
            "Introduction",
            "Section 1: Scripts and Language",
            "Section 2: Institutions and Regions",
            "Section 3: Society and Culture",
            "Notes",
        ]
        for h in required_headings:
            if h not in outline_text:
                structure_ok = False
                break
        if structure_ok:
            scores["outline_structure_preserved"] = 1.0

        # TODOs removed
        if "TODO" not in outline_text:
            scores["outline_todos_removed"] = 1.0

        # Each theme cited with [SRC:...] and "[needs source]" removed per theme line
        all_cited = True
        mapping_consistent = True
        outline_citations = _parse_outline_citations_by_theme(outline_text, theme_ids)
        # Check that all cited IDs exist in sources.json
        all_outline_ids_exist = True
        for tid in theme_ids:
            line = _find_theme_line(outline_text, tid)
            if not line:
                all_cited = False
                mapping_consistent = False
                all_outline_ids_exist = False
                continue
            if "[needs source]" in line:
                all_cited = False
            cits = outline_citations.get(tid, [])
            if not cits:
                all_cited = False
            # check ids exist
            for cid in cits:
                if cid not in sources_ids_set:
                    all_outline_ids_exist = False
            # Check mapping consistency: mapped IDs must appear in outline citations for the same theme
            if mapping:
                mapped_ids = set(mapping.get(tid, []))
                if not mapped_ids.issubset(set(cits)):
                    mapping_consistent = False
        if all_cited and all_outline_ids_exist:
            scores["outline_all_themes_cited"] = 1.0
        if mapping and mapping_consistent and all_outline_ids_exist:
            scores["map_outline_consistency"] = 1.0

    # Meeting notes checks
    meeting_text = _read_text(meeting_notes_path)
    if isinstance(meeting_text, str):
        sections = _parse_meeting_sections(meeting_text)
        # Ensure all sections present by keys (even if empty)
        if all(k in sections for k in ["Agenda", "Research Updates", "Decisions Needed", "Action Items"]):
            scores["meeting_notes_exists_structure"] = 1.0

        # Agenda bullets 3-5
        agenda_count = _count_agenda_bullets(sections.get("Agenda", []))
        if 3 <= agenda_count <= 5:
            scores["meeting_agenda_count"] = 1.0

        # Research updates counts per theme
        ru_counts = _extract_research_updates_counts(sections.get("Research Updates", []), theme_ids)
        counts_ok = True
        if mapping:
            for tid in theme_ids:
                declared = ru_counts.get(tid)
                actual = len(mapping.get(tid, []))
                if declared is None or declared != actual:
                    counts_ok = False
                    break
            if counts_ok:
                scores["meeting_research_updates_counts_correct"] = 1.0

        # Decisions Needed includes themes with only one source
        decisions_text = "\n".join(sections.get("Decisions Needed", []))
        if mapping:
            single_source_themes = [tid for tid, sids in mapping.items() if len(sids) == 1]
            # If none, we accept either empty or explicit "None"
            if not single_source_themes:
                # If there are zero single-source themes, pass if section exists
                scores["meeting_decisions_needed_includes_single_source_themes"] = 1.0
            else:
                if all(tid in decisions_text for tid in single_source_themes):
                    scores["meeting_decisions_needed_includes_single_source_themes"] = 1.0

        # Action items parsing
        items = _extract_action_items(sections.get("Action Items", []))
        # For each theme: exactly one assignment line
        one_per_theme_ok = True
        complete_ok = True
        volunteer_ok = True
        due_ok = True
        sources_valid_ok = True
        # Build roster name/email map
        roster_names = [r.get("name", "") for r in roster_rows]
        roster_email_by_name = {r.get("name", ""): r.get("email", "") for r in roster_rows}
        assigned_volunteers: Dict[str, str] = {}  # theme_id -> volunteer name
        for tid in theme_ids:
            lines_for_theme = _find_assignment_line_for_theme(items, tid)
            if len(lines_for_theme) != 1:
                one_per_theme_ok = False
                continue
            line = lines_for_theme[0]
            # Due TBD
            if "due:TBD" not in line:
                due_ok = False
            # Volunteer presence
            found_name = None
            for nm in roster_names:
                if nm and nm in line:
                    found_name = nm
                    break
            # Email presence
            emails = _extract_emails(line)
            if not found_name or not emails:
                volunteer_ok = False
            else:
                # Verify email matches roster name
                expected_email = roster_email_by_name.get(found_name, "")
                if expected_email and expected_email not in emails:
                    volunteer_ok = False
            if found_name:
                assigned_volunteers[tid] = found_name
            # Sources validity: extract SRC ids
            cited = _extract_source_ids(line)
            # Must have at least one and all must exist and be mapped to that theme_id
            if not cited:
                sources_valid_ok = False
            else:
                for cid in cited:
                    if cid not in sources_ids_set:
                        sources_valid_ok = False
                        break
                    # Check cited is mapped to that theme (subset allowed)
                    if mapping and cid not in set(mapping.get(tid, [])):
                        sources_valid_ok = False
                        break
            # Complete: all required parts present (name, email, theme_id, sources, due)
            if not found_name or not emails or not cited or "due:TBD" not in line or tid not in line:
                complete_ok = False

        if complete_ok:
            scores["meeting_action_items_assignments_complete"] = 1.0
        if one_per_theme_ok:
            scores["meeting_action_items_one_per_theme"] = 1.0
        if volunteer_ok:
            scores["meeting_action_items_volunteer_valid"] = 1.0
        if due_ok:
            scores["meeting_action_items_due_tbd_present"] = 1.0
        if sources_valid_ok:
            scores["meeting_action_items_sources_valid"] = 1.0

        # Best match check
        if assigned_volunteers and theme_info_map and roster_rows:
            per_theme_scores: List[float] = []
            for tid in theme_ids:
                assigned = assigned_volunteers.get(tid)
                if not assigned:
                    per_theme_scores.append(0.0)
                    continue
                max_score, best_names = _compute_best_match_volunteers(theme_info_map.get(tid, {}), roster_rows)
                # If max_score is zero across all volunteers (no overlap), accept assignment as pass
                # Else, require assigned in best_names
                if max_score == 0:
                    per_theme_scores.append(1.0)
                else:
                    per_theme_scores.append(1.0 if assigned in best_names else 0.0)
            if per_theme_scores:
                scores["meeting_assignments_best_match"] = sum(per_theme_scores) / len(per_theme_scores)

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()