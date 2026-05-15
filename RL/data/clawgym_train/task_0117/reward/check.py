import json
import csv
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        items = []
        for ln in lines:
            if not ln.strip():
                continue
            items.append(json.loads(ln))
        return items
    except Exception:
        return None


def _safe_load_projects_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        # Basic required fields
        required = {"project_id", "project_name", "primary_keywords", "target_agencies"}
        for row in rows:
            if not required.issubset(row.keys()):
                return None
        return rows
    except Exception:
        return None


def _contains_url(s: str) -> bool:
    s_lower = s.lower()
    return ("http://" in s_lower) or ("https://" in s_lower) or ("www." in s_lower)


def _is_domain_like(s: str) -> bool:
    # Domain-like: contains a dot, no whitespace, no URL scheme, and allowed chars
    s = s.strip()
    if not s or " " in s:
        return False
    if "http://" in s.lower() or "https://" in s.lower() or "/" in s:
        return False
    if "." not in s:
        return False
    # Allowed characters a-z0-9.- (and optional subdomains)
    return re.fullmatch(r"[A-Za-z0-9.-]+", s) is not None


def _iso_datetime_like(s: str) -> bool:
    # Allow lenient ISO date/time string detection
    # Accept YYYY-MM-DD, or full datetime with T and optional Z/offset
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return True
    # datetime forms
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|([+-]\d{2}:\d{2}))?", s):
        return True
    return False


def _extract_first_iso_date(text: str) -> Optional[str]:
    # Returns the first YYYY-MM-DD substring if present
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return m.group(1) if m else None


def _parse_event_id_date(event_id: str) -> Optional[date]:
    # event_id like "evt-2026-04-15-1" -> extract 2026-04-15
    m = re.match(r"evt-(\d{4})-(\d{2})-(\d{2})-", event_id)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def _count_sentences(text: str) -> int:
    # naive sentence count: split on ., !, ?
    parts = re.split(r"[.!?]", text)
    count = sum(1 for p in parts if p.strip())
    return count


def _collect_output_files(workspace: Path) -> List[Path]:
    out_dir = workspace / "output"
    if not out_dir.exists():
        return []
    return [p for p in out_dir.rglob("*") if p.is_file()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_file_present": 0.0,
        "search_log_schema_valid": 0.0,
        "search_log_per_project_queries": 0.0,
        "candidates_schema_and_limits": 0.0,
        "candidates_event_and_domain_valid": 0.0,
        "status_update_command_top": 0.0,
        "status_update_counts_match": 0.0,
        "status_update_narrative_3_to_5_sentences": 0.0,
        "memo_section_position_correct": 0.0,
        "memo_funding_alerts_lists_opportunities": 0.0,
        "email_draft_subject_event_and_date": 0.0,
        "email_polished_subject_bullets_and_length": 0.0,
        "no_urls_in_any_output_files": 0.0,
    }

    # Load inputs
    projects_path = workspace / "input" / "projects.csv"
    memo_draft_path = workspace / "input" / "memo_draft.md"
    event_jsonl_path = workspace / "input" / "new_event.jsonl"
    projects = _safe_load_projects_csv(projects_path)
    memo_draft = _read_text(memo_draft_path)
    event_lines = _safe_load_jsonl(event_jsonl_path)
    event_id = None
    deadline_hint_days = None
    if event_lines:
        # find first funding_check event
        for item in event_lines:
            if isinstance(item, dict) and item.get("type") == "funding_check":
                event_id = item.get("event_id")
                deadline_hint_days = item.get("deadline_hint_days")
                break

    # 1) script present
    script_path = workspace / "scripts" / "funding_watch.py"
    if script_path.exists() and script_path.is_file():
        try:
            txt = script_path.read_text(encoding="utf-8")
            if len(txt.strip()) > 0:
                scores["script_file_present"] = 1.0
        except Exception:
            pass

    # Output paths
    output_dir = workspace / "output"
    search_log_path = output_dir / "search_log.jsonl"
    candidates_path = output_dir / "funding_candidates.json"
    status_update_path = output_dir / "status_update.md"
    memo_updated_path = output_dir / "meeting_memo_updated.md"
    email_draft_path = output_dir / "email_draft.txt"
    email_polished_path = output_dir / "email_polished.txt"

    # Load outputs
    search_log = _safe_load_jsonl(search_log_path) if search_log_path.exists() else None
    candidates = _safe_load_json(candidates_path) if candidates_path.exists() else None
    status_update = _read_text(status_update_path) if status_update_path.exists() else None
    memo_updated = _read_text(memo_updated_path) if memo_updated_path.exists() else None
    email_draft = _read_text(email_draft_path) if email_draft_path.exists() else None
    email_polished = _read_text(email_polished_path) if email_polished_path.exists() else None

    # 2) search_log_schema_valid
    search_log_valid = True
    if search_log is None:
        search_log_valid = False
    else:
        if not isinstance(search_log, list) or len(search_log) == 0:
            search_log_valid = False
        else:
            for entry in search_log:
                if not isinstance(entry, dict):
                    search_log_valid = False
                    break
                required_fields = {"event_id", "project_id", "query", "engine_name", "timestamp_iso"}
                if not required_fields.issubset(entry.keys()):
                    search_log_valid = False
                    break
                # results up to top 3 with rank, title, domain
                results = entry.get("results")
                if results is None or not isinstance(results, list):
                    search_log_valid = False
                    break
                if len(results) > 3:
                    search_log_valid = False
                    break
                # check each result
                for r in results:
                    if not isinstance(r, dict):
                        search_log_valid = False
                        break
                    if not {"rank", "title", "domain"}.issubset(r.keys()):
                        search_log_valid = False
                        break
                    # domain should be domain-like; no URLs; titles may not contain URLs
                    if not _is_domain_like(str(r.get("domain", ""))):
                        search_log_valid = False
                        break
                    if _contains_url(str(r.get("title", ""))):
                        search_log_valid = False
                        break
                    # rank integer and within 1..3
                    try:
                        rank = int(r.get("rank"))
                        if rank < 1 or rank > 3:
                            search_log_valid = False
                            break
                    except Exception:
                        search_log_valid = False
                        break
                if not search_log_valid:
                    break
                # event_id must match if available
                if event_id and entry.get("event_id") != event_id:
                    search_log_valid = False
                    break
                # timestamp_iso plausibly ISO
                if not _iso_datetime_like(str(entry.get("timestamp_iso", ""))):
                    search_log_valid = False
                    break
                # no URLs in query or engine_name
                if _contains_url(str(entry.get("query", ""))) or _contains_url(str(entry.get("engine_name", ""))):
                    search_log_valid = False
                    break
    if search_log_valid:
        scores["search_log_schema_valid"] = 1.0

    # 3) search_log_per_project_queries: ensure at least one query per project with keyword/agency inclusion
    per_project_ok = False
    if projects and search_log:
        proj_map = {row["project_id"]: row for row in projects}
        coverage_ok = True
        for pid, prow in proj_map.items():
            queries = [e for e in search_log if e.get("project_id") == pid]
            if len(queries) == 0:
                coverage_ok = False
                break
            # at least one query should include a keyword or agency token
            keywords = [k.strip().lower() for k in str(prow.get("primary_keywords", "")).split("|") if k.strip()]
            agencies = [a.strip().lower() for a in str(prow.get("target_agencies", "")).split("|") if a.strip()]
            match_found = False
            for q in queries:
                qtext = str(q.get("query", "")).lower()
                if any(k in qtext for k in keywords) or any(a.lower() in qtext for a in agencies):
                    match_found = True
                    break
            if not match_found:
                coverage_ok = False
                break
        if coverage_ok:
            per_project_ok = True
    if per_project_ok:
        scores["search_log_per_project_queries"] = 1.0

    # 4) candidates_schema_and_limits
    candidates_schema_ok = False
    if isinstance(candidates, list) and len(candidates) > 0:
        fields = {"event_id", "project_id", "project_name", "keyword", "title", "issuing_agency_guess", "domain", "gathered_at_iso"}
        # per project limit <= 5
        per_project_counts: Dict[str, int] = {}
        schema_ok = True
        for c in candidates:
            if not isinstance(c, dict) or not fields.issubset(c.keys()):
                schema_ok = False
                break
            per_project_counts[c.get("project_id")] = per_project_counts.get(c.get("project_id"), 0) + 1
            # domain validity
            if not _is_domain_like(str(c.get("domain", ""))):
                schema_ok = False
                break
            # gathered_at_iso ISO-like
            if not _iso_datetime_like(str(c.get("gathered_at_iso", ""))):
                schema_ok = False
                break
            # issuing_agency_guess non-empty
            if not str(c.get("issuing_agency_guess", "")).strip():
                schema_ok = False
                break
        if schema_ok and all(count <= 5 for count in per_project_counts.values()):
            candidates_schema_ok = True
    if candidates_schema_ok:
        scores["candidates_schema_and_limits"] = 1.0

    # 5) candidates_event_and_domain_valid: event_id match, dedup, project id subset, and no URL-like fields
    candidates_consistency_ok = False
    if isinstance(candidates, list) and len(candidates) > 0:
        ok = True
        seen_pairs = set()
        proj_ids = set([row["project_id"] for row in (projects or [])])
        for c in candidates:
            if event_id and c.get("event_id") != event_id:
                ok = False
                break
            # dedup by (project_id, title, domain)
            key = (c.get("project_id"), c.get("title"), c.get("domain"))
            if key in seen_pairs:
                ok = False
                break
            seen_pairs.add(key)
            # project_id known
            if projects and c.get("project_id") not in proj_ids:
                ok = False
                break
            # no URLs in title or issuing_agency_guess
            if _contains_url(str(c.get("title", ""))) or _contains_url(str(c.get("issuing_agency_guess", ""))):
                ok = False
                break
        if ok:
            candidates_consistency_ok = True
    if candidates_consistency_ok:
        scores["candidates_event_and_domain_valid"] = 1.0

    # helper: compute candidates count by project for status checking
    candidates_by_project: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(candidates, list):
        for c in candidates:
            pid = c.get("project_id")
            candidates_by_project.setdefault(pid, []).append(c)

    # 6) status_update_command_top
    status_cmd_top_ok = False
    if isinstance(status_update, str):
        lines = [ln for ln in status_update.splitlines()]
        first_non_empty = None
        for ln in lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        if first_non_empty:
            # Must include scripts/funding_watch.py and both input files
            if ("scripts/funding_watch.py" in first_non_empty and
                "input/new_event.jsonl" in first_non_empty and
                "input/projects.csv" in first_non_empty):
                status_cmd_top_ok = True
    if status_cmd_top_ok:
        scores["status_update_command_top"] = 1.0

    # 7) status_update_counts_match
    status_counts_ok = False
    if isinstance(status_update, str) and isinstance(candidates, list):
        # Parse lines with "P-XXX: N"
        parsed_counts: Dict[str, int] = {}
        for ln in status_update.splitlines():
            m = re.search(r"\b(P-\d+)\b[^0-9]*([0-9]+)\b", ln)
            if m:
                pid = m.group(1)
                cnt = int(m.group(2))
                parsed_counts[pid] = cnt
        # Compare against computed counts for projects that appear in the file
        if parsed_counts:
            all_match = True
            for pid, cnt in parsed_counts.items():
                actual = len(candidates_by_project.get(pid, []))
                if cnt != actual:
                    all_match = False
                    break
            if all_match:
                status_counts_ok = True
    if status_counts_ok:
        scores["status_update_counts_match"] = 1.0

    # 8) status_update_narrative_3_to_5_sentences
    narrative_ok = False
    if isinstance(status_update, str):
        # Remove command line (first non-empty) and lines with counts (P-XXX: N)
        lines = status_update.splitlines()
        filtered_lines = []
        skip_first = True
        for ln in lines:
            if skip_first and ln.strip():
                skip_first = False
                continue
            if re.search(r"\bP-\d+\b[^0-9]*\b\d+\b", ln):
                continue
            filtered_lines.append(ln)
        text = " ".join([ln.strip() for ln in filtered_lines if ln.strip()])
        s_count = _count_sentences(text)
        if 3 <= s_count <= 5:
            narrative_ok = True
    if narrative_ok:
        scores["status_update_narrative_3_to_5_sentences"] = 1.0

    # 9) memo_section_position_correct
    memo_position_ok = False
    if isinstance(memo_updated, str) and isinstance(memo_draft, str):
        lines = memo_updated.splitlines()
        up_idx = None
        fund_idx = None
        attach_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == "## Upcoming Agenda Items" and up_idx is None:
                up_idx = i
            if ln.strip() == "## Funding Alerts" and fund_idx is None:
                fund_idx = i
            if ln.strip() == "## Attachments" and attach_idx is None:
                attach_idx = i
        if up_idx is not None and fund_idx is not None and attach_idx is not None:
            if up_idx < fund_idx < attach_idx:
                memo_position_ok = True
    if memo_position_ok:
        scores["memo_section_position_correct"] = 1.0

    # 10) memo_funding_alerts_lists_opportunities
    memo_content_ok = False
    if isinstance(memo_updated, str) and isinstance(candidates, list) and projects:
        # Extract the Funding Alerts section content
        section = ""
        lines = memo_updated.splitlines()
        in_section = False
        for ln in lines:
            if ln.strip() == "## Funding Alerts":
                in_section = True
                continue
            if in_section and ln.startswith("## "):
                # next section
                break
            if in_section:
                section += ln + "\n"
        if section.strip():
            # Check each project: presence of project_id or project_name,
            # and at least one listed opportunity (title + domain)
            proj_by_id = {row["project_id"]: row for row in projects}
            all_projects_ok = True
            for pid, prow in proj_by_id.items():
                pname = prow.get("project_name", "")
                # presence of project id or name
                if pid not in section and pname not in section:
                    all_projects_ok = False
                    break
                # find candidates for this project
                proj_cands = candidates_by_project.get(pid, [])
                # Accept if at least one of the candidate title and domain pairs appears in section
                found_any = False
                for c in proj_cands[:2]:  # top 1–2 opportunities; any 1 present is fine
                    title = str(c.get("title", "")).strip()
                    domain = str(c.get("domain", "")).strip()
                    if title and domain and (title in section) and (domain in section):
                        found_any = True
                        break
                if not found_any:
                    # If there are no candidates for the project at all, it's a failure
                    all_projects_ok = False
                    break
            # ensure no URLs appear in section
            if all_projects_ok and not _contains_url(section):
                memo_content_ok = True
    if memo_content_ok:
        scores["memo_funding_alerts_lists_opportunities"] = 1.0

    # 11) email_draft_subject_event_and_date
    email_draft_ok = False
    if isinstance(email_draft, str) and event_id and deadline_hint_days is not None:
        has_subject = any(ln.strip().lower().startswith("subject:") for ln in email_draft.splitlines())
        references_event = event_id in email_draft
        # find ISO date present
        iso_date_in_text = _extract_first_iso_date(email_draft or "")
        # compute acceptable dates
        acceptable_dates = set()
        # today's date + deadline
        try:
            acceptable_dates.add((date.today() + timedelta(days=int(deadline_hint_days))).isoformat())
        except Exception:
            pass
        # if event_id encodes a date, accept that + deadline, too (to allow deterministic check)
        event_date_from_id = _parse_event_id_date(event_id)
        if event_date_from_id:
            try:
                acceptable_dates.add((event_date_from_id + timedelta(days=int(deadline_hint_days))).isoformat())
            except Exception:
                pass
        has_acceptable_date = iso_date_in_text in acceptable_dates if iso_date_in_text else False
        # references feedback
        mentions_feedback = "feedback" in email_draft.lower()
        # references at least one candidate title+domain, and no URLs
        ref_any_candidate = False
        if isinstance(candidates, list) and len(candidates) > 0:
            for c in candidates[:5]:
                title = str(c.get("title", "")).strip()
                domain = str(c.get("domain", "")).strip()
                if title and domain and (title in email_draft) and (domain in email_draft):
                    ref_any_candidate = True
                    break
        no_urls = not _contains_url(email_draft)
        if has_subject and references_event and has_acceptable_date and mentions_feedback and ref_any_candidate and no_urls:
            email_draft_ok = True
    if email_draft_ok:
        scores["email_draft_subject_event_and_date"] = 1.0

    # 12) email_polished_subject_bullets_and_length
    email_polished_ok = False
    if isinstance(email_polished, str):
        lines = email_polished.splitlines()
        # subject should be first non-empty line
        first_non_empty = None
        for ln in lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        has_subject = bool(first_non_empty and first_non_empty.lower().startswith("subject:"))
        # bullets after subject: collect '-' or '*'
        bullets = []
        subject_seen = False
        for ln in lines:
            if ln.strip():
                if not subject_seen and ln.strip().lower().startswith("subject:"):
                    subject_seen = True
                    continue
                if subject_seen and ln.strip().startswith(("-", "*")):
                    bullets.append(ln.strip().lstrip("-* ").strip())
        # exactly 3 bullets
        correct_bullet_count = len(bullets) == 3
        # each bullet must match a candidate title+domain and contain domain-like, and no URLs
        bullets_match_candidates = False
        if isinstance(candidates, list) and len(candidates) >= 3 and bullets:
            bullets_match_candidates = True
            for b in bullets:
                if _contains_url(b):
                    bullets_match_candidates = False
                    break
                # domain-like presence
                dom_match = re.search(r"\b([A-Za-z0-9.-]+\.[A-Za-z0-9.-]+)\b", b)
                if not dom_match:
                    bullets_match_candidates = False
                    break
                # ensure bullet refers to a known candidate (title and domain)
                found = False
                for c in candidates:
                    title = str(c.get("title", "")).strip()
                    domain = str(c.get("domain", "")).strip()
                    if title and domain and (title in b) and (domain in b):
                        found = True
                        break
                if not found:
                    bullets_match_candidates = False
                    break
        # under 180 words
        body_text = "\n".join([ln for ln in lines if not (ln.strip().lower().startswith("subject:"))])
        word_count = len([w for w in re.findall(r"\b\w+\b", body_text)])
        under_180 = word_count <= 180
        # no URLs anywhere
        no_urls = not _contains_url(email_polished)
        if has_subject and correct_bullet_count and bullets_match_candidates and under_180 and no_urls:
            email_polished_ok = True
    if email_polished_ok:
        scores["email_polished_subject_bullets_and_length"] = 1.0

    # 13) no_urls_in_any_output_files
    no_urls_ok = False
    out_files = _collect_output_files(workspace)
    if out_files:
        ok = True
        for p in out_files:
            # search_log.jsonl can include domains only, but not raw URLs
            txt = _read_text(p)
            if txt is None:
                ok = False
                break
            if _contains_url(txt):
                ok = False
                break
        if ok:
            no_urls_ok = True
    if no_urls_ok:
        scores["no_urls_in_any_output_files"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()