import json
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _is_iso_date(s: str) -> bool:
    try:
        if not isinstance(s, str):
            return False
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return False
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _normalize_text(s: str) -> str:
    # Normalize whitespace and dashes for robust comparisons
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s.strip())
    return s


def _extract_section_lines(text: str, start_label: str, next_labels: List[str]) -> List[str]:
    # Returns the lines between a start label line and the next label line from next_labels or EOF
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_label.strip():
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip() in [lbl.strip() for lbl in next_labels]:
            end_idx = j
            break
    return lines[start_idx:end_idx]


def _find_bullet_lines(lines: List[str]) -> List[str]:
    bullets = []
    for line in lines:
        if re.match(r"^\s*[-*]\s+", line):
            bullets.append(line.strip())
    return bullets


def _contains_all_keywords(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return all(k.lower() in t for k in keywords)


def _tokenize_hint(hint: str) -> List[str]:
    # Extract meaningful tokens (length >=3) excluding common stopwords
    stop = {"the", "and", "for", "or", "of", "to", "in", "on", "any", "with", "from", "acts", "body"}
    tokens = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", hint) if len(t) >= 3]
    tokens = [t for t in tokens if t not in stop]
    # Deduplicate keeping order
    seen = set()
    uniq = []
    for t in tokens:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Initialize scores
    scores = {
        "findings_file_structure": 0.0,
        "findings_ids_coverage": 0.0,
        "findings_status_and_dates_valid": 0.0,
        "findings_confirmed_have_source": 0.0,
        "search_log_structure": 0.0,
        "search_log_ids_coverage": 0.0,
        "search_log_queries_minimum": 0.0,
        "search_log_sources_fields_valid": 0.0,
        "search_log_confirmed_have_source": 0.0,
        "cross_confirmed_domain_matches_search": 0.0,
        "agenda_exists_and_placeholders_filled": 0.0,
        "agenda_attendees_list_correct": 0.0,
        "agenda_objectives_summary_present": 0.0,
        "agenda_confirmed_bullets_match": 0.0,
        "agenda_pending_bullets_match": 0.0,
        "agenda_actions_preview_for_pending": 0.0,
        "meeting_notes_exists_and_sections": 0.0,
        "meeting_notes_decisions_tbd": 0.0,
        "meeting_notes_findings_mirror_ids": 0.0,
        "meeting_notes_action_items_for_pending": 0.0,
        "meeting_notes_action_items_owner_and_due": 0.0,
    }

    # Load inputs
    backlog_path = workspace / "input" / "research_backlog.csv"
    attendees_path = workspace / "input" / "attendees.csv"
    findings_path = workspace / "output" / "findings" / "findings.csv"
    search_log_path = workspace / "output" / "search_logs" / "search_log.json"
    agenda_path = workspace / "output" / "agendas" / "agenda_2026-04-22.md"
    notes_path = workspace / "output" / "meeting" / "meeting_notes_2026-04-22.md"

    backlog_rows = _read_csv_dicts(backlog_path) or []
    attendees_rows = _read_csv_dicts(attendees_path) or []
    backlog_by_id: Dict[str, Dict[str, str]] = {}
    for row in backlog_rows:
        if "backlog_id" in row and row["backlog_id"]:
            backlog_by_id[row["backlog_id"]] = row

    attendee_names = []
    for row in attendees_rows:
        name = row.get("name", "").strip()
        if name:
            attendee_names.append(name)
    attendee_names_set = set(attendee_names)
    attendee_names_set.add("A. Bot")  # Coordinator fallback explicitly allowed

    # Load findings
    findings_rows = _read_csv_dicts(findings_path)
    # Check findings file structure
    expected_findings_headers = [
        "backlog_id",
        "country",
        "symbol_type",
        "query_used",
        "source_domain",
        "document_title",
        "accessed_date",
        "status",
        "notes",
    ]
    findings_file_ok = False
    if findings_rows is not None:
        # DictReader stores the header in fieldnames; re-open to access exact header order
        try:
            with findings_path.open(newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader, [])
            if headers == expected_findings_headers:
                findings_file_ok = True
        except Exception:
            findings_file_ok = False
    if findings_file_ok:
        scores["findings_file_structure"] = 1.0

    # Validate findings coverage, statuses, dates, confirmed have source
    findings_by_id: Dict[str, List[Dict[str, str]]] = {}
    findings_status_dates_ok = True
    findings_confirmed_source_ok = True
    if findings_rows is not None:
        for row in findings_rows:
            bid = row.get("backlog_id", "")
            if bid:
                findings_by_id.setdefault(bid, []).append(row)

        # Coverage: every backlog id appears at least once
        if backlog_by_id and all(bid in findings_by_id for bid in backlog_by_id.keys()):
            scores["findings_ids_coverage"] = 1.0

        # Validate fields
        for bid, rows in findings_by_id.items():
            for r in rows:
                status = r.get("status", "")
                date = r.get("accessed_date", "")
                notes = r.get("notes", "")
                query_used = r.get("query_used", "")
                # Status must be exactly "confirmed" or "pending"
                if status not in {"confirmed", "pending"}:
                    findings_status_dates_ok = False
                # ISO date
                if not _is_iso_date(date):
                    findings_status_dates_ok = False
                # Notes non-empty
                if not isinstance(notes, str) or not notes.strip():
                    findings_status_dates_ok = False
                # query_used non-empty
                if not isinstance(query_used, str) or not query_used.strip():
                    findings_status_dates_ok = False
                # confirmed must have source_domain and document_title non-empty
                if status == "confirmed":
                    sd = r.get("source_domain", "")
                    dt = r.get("document_title", "")
                    if not isinstance(sd, str) or not sd.strip() or not isinstance(dt, str) or not dt.strip():
                        findings_confirmed_source_ok = False
        if findings_status_dates_ok:
            scores["findings_status_and_dates_valid"] = 1.0
        if findings_confirmed_source_ok and findings_rows is not None:
            scores["findings_confirmed_have_source"] = 1.0

    # Load search logs
    search_obj = _load_json(search_log_path)
    search_entries_by_id: Dict[str, Dict[str, Any]] = {}
    search_structure_ok = False
    if isinstance(search_obj, list):
        for item in search_obj:
            if isinstance(item, dict):
                bid = item.get("backlog_id")
                if isinstance(bid, str):
                    search_entries_by_id[bid] = item
        # Basic structure validation on at least one item
        search_structure_ok = True if search_entries_by_id else False
    elif isinstance(search_obj, dict):
        # Could be dict keyed by backlog_id
        ok = True
        tmp = {}
        for k, v in search_obj.items():
            if not isinstance(v, dict):
                ok = False
                break
            tmp[k] = v
        if ok and tmp:
            # Ensure each has backlog_id field (if missing, inject k)
            for k, v in tmp.items():
                if "backlog_id" not in v:
                    v["backlog_id"] = k
            search_entries_by_id = tmp
            search_structure_ok = True
    if search_structure_ok:
        scores["search_log_structure"] = 1.0

    # Search log coverage and fields
    if search_entries_by_id:
        if backlog_by_id and all(bid in search_entries_by_id for bid in backlog_by_id.keys()):
            scores["search_log_ids_coverage"] = 1.0

        queries_ok = True
        sources_fields_ok = True
        confirmed_have_source_ok = True

        for bid, entry in search_entries_by_id.items():
            # Queries check
            queries = entry.get("queries")
            if not isinstance(queries, list) or len(queries) < 1 or any(not isinstance(q, str) or not q.strip() for q in queries):
                queries_ok = False
            # Sources check
            sources = entry.get("sources")
            if not isinstance(sources, list):
                sources_fields_ok = False
            else:
                for s in sources:
                    if not isinstance(s, dict):
                        sources_fields_ok = False
                        break
                    dom = s.get("domain")
                    title = s.get("title")
                    ad = s.get("accessed_date")
                    if not (isinstance(dom, str) and dom.strip() and isinstance(title, str) and title.strip() and isinstance(ad, str) and _is_iso_date(ad)):
                        sources_fields_ok = False
                        break
            # status_summary present
            ss = entry.get("status_summary")
            if not isinstance(ss, str) or not ss.strip():
                sources_fields_ok = False

            # If this backlog_id is confirmed in findings, sources should be non-empty
            if bid in findings_by_id:
                # If any row for this bid is confirmed, enforce at least one source
                is_confirmed = any(r.get("status") == "confirmed" for r in findings_by_id[bid])
                if is_confirmed:
                    if not isinstance(entry.get("sources"), list) or len(entry.get("sources")) < 1:
                        confirmed_have_source_ok = False

        if queries_ok:
            scores["search_log_queries_minimum"] = 1.0
        if sources_fields_ok:
            scores["search_log_sources_fields_valid"] = 1.0
        if confirmed_have_source_ok:
            scores["search_log_confirmed_have_source"] = 1.0

    # Cross-check: for confirmed items, findings source_domain should match a domain in search log sources
    cross_domain_ok = True
    if findings_by_id and search_entries_by_id:
        for bid, rows in findings_by_id.items():
            # Identify confirmed rows
            for r in rows:
                if r.get("status") == "confirmed":
                    f_dom = (r.get("source_domain") or "").strip()
                    if not f_dom:
                        cross_domain_ok = False
                        continue
                    entry = search_entries_by_id.get(bid)
                    if not entry:
                        cross_domain_ok = False
                        continue
                    domains = []
                    ss = entry.get("sources")
                    if isinstance(ss, list):
                        for s in ss:
                            if isinstance(s, dict) and isinstance(s.get("domain"), str):
                                domains.append(s.get("domain").strip())
                    if f_dom not in domains:
                        cross_domain_ok = False
        if cross_domain_ok:
            scores["cross_confirmed_domain_matches_search"] = 1.0

    # Agenda checks
    agenda_text = None
    if agenda_path.exists():
        try:
            agenda_text = agenda_path.read_text(encoding='utf-8')
        except Exception:
            agenda_text = None
    if agenda_text:
        # Check placeholders removed and meeting date in title
        placeholders_present = "{{" in agenda_text or "}}" in agenda_text
        date_in_title = f"Weekly Symbols Research Sync — 2026-04-22" in agenda_text
        if not placeholders_present and date_in_title:
            scores["agenda_exists_and_placeholders_filled"] = 1.0

        # Attendees list correct (exact names from attendees.csv, comma-separated)
        attendees_section_lines = _extract_section_lines(
            agenda_text, "Attendees:", ["Objectives:", "Confirmed items (for review):", "Pending/Blocked items:", "Action items preview:"]
        )
        attendees_line_text = " ".join([line.strip() for line in attendees_section_lines if line.strip()])
        # Split by comma
        listed_names = [n.strip() for n in attendees_line_text.split(",") if n.strip()]
        if set(listed_names) == set(name for name in attendee_names if name):
            scores["agenda_attendees_list_correct"] = 1.0

        # Objectives summary presence with required keywords
        objectives_lines = _extract_section_lines(
            agenda_text, "Objectives:", ["Confirmed items (for review):", "Pending/Blocked items:", "Action items preview:"]
        )
        objectives_text = " ".join([line.strip() for line in objectives_lines if line.strip()])
        if objectives_text and _contains_all_keywords(objectives_text, ["review", "confirmed", "triage", "pending", "assign", "follow-ups"]):
            scores["agenda_objectives_summary_present"] = 1.0

        # Confirmed and pending bullets match findings
        confirmed_rows = []
        pending_rows = []
        for bid, rows in findings_by_id.items():
            # Take the first row per id for listing (assuming one per backlog id)
            # If multiple, prioritize a confirmed row for confirmed list; else pending
            confirmed = [r for r in rows if r.get("status") == "confirmed"]
            pending = [r for r in rows if r.get("status") == "pending"]
            if confirmed:
                confirmed_rows.append((bid, confirmed[0]))
            elif pending:
                pending_rows.append((bid, pending[0]))
        # Extract bullet lines across the agenda
        confirmed_section_lines = _extract_section_lines(
            agenda_text, "Confirmed items (for review):", ["Pending/Blocked items:", "Action items preview:"]
        )
        pending_section_lines = _extract_section_lines(
            agenda_text, "Pending/Blocked items:", ["Action items preview:"]
        )
        confirmed_bullets = _find_bullet_lines(confirmed_section_lines)
        pending_bullets = _find_bullet_lines(pending_section_lines)

        def bullet_contains_confirmed(bullet: str, bid: str, country: str, topic: str, source_domain: str) -> bool:
            b = _normalize_text(bullet)
            # Require all components in order
            pattern = f"[{bid}]"
            if pattern not in b:
                return False
            # Ensure country, topic, and source_domain appear after the id
            idx = b.find(pattern)
            tail = b[idx + len(pattern):]
            # Normalize tokens
            tail_norm = _normalize_text(tail)
            return (country in tail_norm) and (topic in tail_norm) and (source_domain in tail_norm)

        def bullet_contains_pending(bullet: str, bid: str, country: str, topic: str, notes: str) -> bool:
            b = _normalize_text(bullet)
            pattern = f"[{bid}]"
            if pattern not in b:
                return False
            idx = b.find(pattern)
            tail = _normalize_text(b[idx + len(pattern):])
            return (country in tail) and (topic in tail) and (notes[:40].strip() in tail or any(tok in tail for tok in _tokenize_hint(notes)))

        confirmed_ok = True
        for (bid, r) in confirmed_rows:
            backlog = backlog_by_id.get(bid, {})
            country = r.get("country", "")
            topic = backlog.get("topic", "")
            source_domain = r.get("source_domain", "")
            # Check at least one bullet matches
            if not any(bullet_contains_confirmed(b, bid, country, topic, source_domain) for b in confirmed_bullets):
                confirmed_ok = False
        if confirmed_ok and confirmed_rows:
            scores["agenda_confirmed_bullets_match"] = 1.0

        pending_ok = True
        for (bid, r) in pending_rows:
            backlog = backlog_by_id.get(bid, {})
            country = r.get("country", "")
            topic = backlog.get("topic", "")
            notes_val = r.get("notes", "")
            if not any(bullet_contains_pending(b, bid, country, topic, notes_val) for b in pending_bullets):
                pending_ok = False
        if pending_ok or (not pending_rows and pending_bullets == []):
            # If no pending rows, it's acceptable that no bullets exist
            scores["agenda_pending_bullets_match"] = 1.0

        # Action items preview: for each pending, line must reference backlog_id and suggest likely official source based on source_hint
        actions_preview_lines = _extract_section_lines(
            agenda_text, "Action items preview:", []
        )
        actions_preview_bullets = _find_bullet_lines(actions_preview_lines) or [l.strip() for l in actions_preview_lines if l.strip()]
        actions_preview_ok = True
        for (bid, r) in pending_rows:
            backlog = backlog_by_id.get(bid, {})
            hint = backlog.get("source_hint", "")
            tokens = _tokenize_hint(hint)
            # Find a line with bid and at least one token
            found = False
            for line in actions_preview_bullets:
                ln = line.lower()
                if f"[{bid.lower()}]" in ln or bid.lower() in ln:
                    if any(tok in ln for tok in tokens) and any(k in ln for k in ["try", "check", "consult", "contact", "search", "review", "verify", "visit", "look"]):
                        found = True
                        break
            if not found:
                actions_preview_ok = False
                break
        if actions_preview_ok or (not pending_rows and not actions_preview_bullets):
            scores["agenda_actions_preview_for_pending"] = 1.0

    # Meeting notes checks
    notes_text = None
    if notes_path.exists():
        try:
            notes_text = notes_path.read_text(encoding='utf-8')
        except Exception:
            notes_text = None
    if notes_text:
        # Sections existence
        has_decisions = "Decisions:" in notes_text
        has_findings_summary = "Findings summary:" in notes_text
        has_action_items = "Action items:" in notes_text
        if has_decisions and has_findings_summary and has_action_items:
            scores["meeting_notes_exists_and_sections"] = 1.0

        # Decisions TBD placeholders
        decisions_lines = _extract_section_lines(notes_text, "Decisions:", ["Findings summary:", "Action items:"])
        decisions_text = " ".join([l.strip() for l in decisions_lines if l.strip()])
        if "TBD" in decisions_text or "tbd" in decisions_text.lower():
            scores["meeting_notes_decisions_tbd"] = 1.0

        # Findings summary mirrors confirmed and pending items
        findings_summary_lines = _extract_section_lines(notes_text, "Findings summary:", ["Action items:"])
        findings_bullets = _find_bullet_lines(findings_summary_lines)
        mirror_ok = True
        for bid in backlog_by_id.keys():
            # Each backlog_id should appear in findings summary bullets (either in confirmed or pending list inside this section)
            if not any(f"[{bid}]" in bl for bl in findings_bullets):
                mirror_ok = False
                break
        if mirror_ok and findings_bullets:
            scores["meeting_notes_findings_mirror_ids"] = 1.0

        # Action items: for each pending backlog id, create actionable task line with fields: backlog_id, task summary, owner, due=2026-04-29, rationale
        action_lines = _extract_section_lines(notes_text, "Action items:", [])
        action_lines = [l.strip() for l in action_lines if l.strip()]
        # Consider bullet or plain lines
        action_items_lines = _find_bullet_lines(action_lines) or action_lines

        # Map action items by backlog id
        def find_action_line_for_bid(bid: str) -> Optional[str]:
            for line in action_items_lines:
                if f"[{bid}]" in line or bid in line:
                    return line
            return None

        have_actions_for_all_pending = True
        owner_and_due_ok = True
        for (bid, r) in [(bid, rr) for bid, rr in findings_by_id.items() if any(x.get("status") == "pending" for x in rr)]:
            # Use bid once
            line = find_action_line_for_bid(bid)
            if not line:
                have_actions_for_all_pending = False
                break
            # Check due date
            if "2026-04-29" not in line:
                owner_and_due_ok = False
            # Check owner
            has_owner = False
            for name in attendee_names_set:
                if name in line:
                    has_owner = True
                    break
            if not has_owner:
                owner_and_due_ok = False
            # Check rationale presence indicator
            if "rationale" not in line.lower():
                # allow lines that at least include a "because"/"so that" style justification
                if not re.search(r"\b(because|so that|to ensure|due to)\b", line, flags=re.IGNORECASE):
                    owner_and_due_ok = False

        # If no pending items, it's acceptable that there are no action items for pending
        if have_actions_for_all_pending or not pending_rows:
            scores["meeting_notes_action_items_for_pending"] = 1.0
        if owner_and_due_ok or not pending_rows:
            scores["meeting_notes_action_items_owner_and_due"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()