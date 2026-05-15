import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime


def _safe_read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_read_csv_dicts(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _safe_read_jsonl_objects(p: Path):
    objs = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    objs.append(obj)
                except Exception:
                    return None
        return objs
    except Exception:
        return None


def _parse_simple_yaml(p: Path) -> dict:
    text = _safe_read_text(p)
    data = {}
    current_key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', line)
        if m and not line.startswith("  -"):
            key = m.group(1)
            rest = m.group(2).strip()
            current_key = key
            if rest == "" or rest is None:
                data[key] = []
            else:
                val = rest
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                data[key] = val
            continue
        if current_key and re.match(r'^\s*-\s+', line):
            if current_key not in data or not isinstance(data[current_key], list):
                data[current_key] = []
            val = re.sub(r'^\s*-\s+', "", line).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[current_key].append(val)
            continue
    return data


def _is_iso_date(s: str) -> bool:
    if not s:
        return True
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_iso_timestamp(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _normalize_url(u: str) -> str:
    try:
        parts = urlsplit(u.strip())
        scheme = parts.scheme.lower() if parts.scheme else "http"
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parts.path.rstrip("/")
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return u.strip().rstrip("/").lower()


def _hostname(u: str) -> str:
    try:
        parts = urlsplit(u.strip())
        host = parts.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_gov_or_us_domain(host: str) -> bool:
    host = host.lower()
    return host.endswith(".gov") or host.endswith(".us") or ".gov." in host


def _line_is_heading(line: str, expected: str) -> bool:
    txt = line.strip()
    txt = re.sub(r"^#{1,6}\s*", "", txt)
    txt = txt.rstrip(":").strip().lower()
    return txt == expected.strip().lower()


def _find_section(text: str, heading: str, all_headings: list) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if _line_is_heading(line, heading):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    expected_set = {h.strip().lower() for h in all_headings}
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        for h in expected_set:
            if _line_is_heading(lines[j], h) and not _line_is_heading(lines[j], heading):
                end_idx = j
                break
        if end_idx != len(lines):
            break
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section


def _extract_bullets(text: str) -> list:
    bullets = []
    for line in text.splitlines():
        if re.match(r'^\s*([-*•])\s+', line):
            bullets.append(line.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sources_csv_headers": 0.0,
        "sources_min_count_and_gov_court_quota": 0.0,
        "sources_fields_validity": 0.0,
        "search_log_jsonl_validity": 0.0,
        "search_log_min_queries_and_scope_coverage": 0.0,
        "sources_url_in_log": 0.0,
        "sources_query_in_log": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_references_to_sources": 0.0,
        "action_items_count_valid": 0.0,
        "email_polished_word_count_and_attachments": 0.0,
        "email_polished_neutrality_and_meeting_and_public_records": 0.0,
    }

    outputs_dir = workspace / "outputs"
    sources_csv = outputs_dir / "sources.csv"
    search_log = outputs_dir / "search_log.jsonl"
    meeting_notes = outputs_dir / "meeting_notes.md"
    email_polished = outputs_dir / "email_polished.txt"
    scope_yaml = workspace / "input" / "scope.yaml"

    headers, rows = _safe_read_csv_dicts(sources_csv)
    expected_headers = [
        "source_id",
        "category",
        "domain_type",
        "organization",
        "title",
        "publish_date",
        "url",
        "query_used",
        "summary",
    ]

    if headers is not None and headers == expected_headers:
        scores["sources_csv_headers"] = 1.0

    log_objs = _safe_read_jsonl_objects(search_log)

    if rows is not None:
        min_ok = len(rows) >= 8
        gov_court_count = 0
        for r in rows:
            url = r.get("url", "")
            domain_type = (r.get("domain_type") or "").strip().lower()
            host = _hostname(url)
            if domain_type in {"gov/us", "court"} or _is_gov_or_us_domain(host):
                gov_court_count += 1
        quota_ok = gov_court_count >= 5
        if min_ok and quota_ok:
            scores["sources_min_count_and_gov_court_quota"] = 1.0

    allowed_categories = {
        "official report",
        "policy",
        "procurement record",
        "court docket",
        "ethics/financial disclosure",
        "news",
    }
    allowed_domain_types = {"gov/us", "court", "news", "other"}
    accusatory_terms = {
        "bribe", "bribery", "bribing", "corrupt", "corruption", "kickback", "kickbacks",
        "collude", "collusion", "illegal", "guilty", "criminal", "crime", "payoff",
        "payoffs", "cover-up", "coverup", "conspiracy", "scandal"
    }
    fields_ok = True
    if rows is None or headers is None or headers != expected_headers:
        fields_ok = False
    else:
        for r in rows:
            cat = (r.get("category") or "").strip().lower()
            dom = (r.get("domain_type") or "").strip().lower()
            url = (r.get("url") or "").strip()
            query_used = (r.get("query_used") or "").strip()
            pub = (r.get("publish_date") or "").strip()
            summary = (r.get("summary") or "").strip()
            if cat not in allowed_categories:
                fields_ok = False
                break
            if dom not in allowed_domain_types:
                fields_ok = False
                break
            if not url or not re.match(r'^https?://', url):
                fields_ok = False
                break
            if not query_used:
                fields_ok = False
                break
            if pub and not _is_iso_date(pub):
                fields_ok = False
                break
            wc = _count_words(summary)
            if wc < 30 or wc > 60:
                fields_ok = False
                break
            low = summary.lower()
            if any(term in low for term in accusatory_terms):
                fields_ok = False
                break
    if fields_ok:
        scores["sources_fields_validity"] = 1.0

    log_valid = True
    if log_objs is None or not isinstance(log_objs, list) or len(log_objs) == 0:
        log_valid = False
    else:
        for obj in log_objs:
            for k in ["timestamp", "engine", "query", "filters", "reviewed_results", "selected_urls"]:
                if k not in obj:
                    log_valid = False
                    break
            if not log_valid:
                break
            if not _is_iso_timestamp(obj.get("timestamp")):
                log_valid = False
                break
            if not isinstance(obj.get("engine"), str) or obj.get("engine").strip() == "":
                log_valid = False
                break
            if not isinstance(obj.get("query"), str) or obj.get("query").strip() == "":
                log_valid = False
                break
            if not isinstance(obj.get("reviewed_results"), int) or obj.get("reviewed_results") < 0:
                log_valid = False
                break
            sel = obj.get("selected_urls")
            if not isinstance(sel, list) or any(not isinstance(u, str) for u in sel):
                log_valid = False
                break
    if log_valid:
        scores["search_log_jsonl_validity"] = 1.0

    scope = _parse_simple_yaml(scope_yaml)
    queries_ok = False
    coverage_ok = False
    timeframe_ok = False
    entity_ok = False
    jurisdiction_ok = False
    if log_valid:
        queries = [obj.get("query", "") for obj in log_objs if isinstance(obj, dict)]
        distinct_queries = {q.strip().lower() for q in queries if isinstance(q, str) and q.strip()}
        queries_ok = len(distinct_queries) >= 5

        entities = [e.lower() for e in scope.get("entities", [])] if isinstance(scope.get("entities"), list) else []
        jurisdictions = [j.lower() for j in scope.get("jurisdictions", [])] if isinstance(scope.get("jurisdictions"), list) else []

        for q in distinct_queries:
            if any(e in q for e in entities):
                entity_ok = True
                break
        for q in distinct_queries:
            if any(j in q for j in jurisdictions):
                jurisdiction_ok = True
                break
        for q in distinct_queries:
            if "past 5 years" in q or "last 5 years" in q or "5 years" in q:
                timeframe_ok = True
                break
        coverage_ok = entity_ok and jurisdiction_ok and timeframe_ok

    if queries_ok and coverage_ok:
        scores["search_log_min_queries_and_scope_coverage"] = 1.0

    url_in_log_ok = False
    if rows is not None and log_valid:
        sel_set = set()
        for obj in log_objs:
            for u in obj.get("selected_urls", []):
                if isinstance(u, str):
                    sel_set.add(_normalize_url(u))
        all_match = True
        for r in rows:
            su = (r.get("url") or "").strip()
            if not su:
                all_match = False
                break
            su_norm = _normalize_url(su)
            if su_norm not in sel_set:
                found = False
                for candidate in sel_set:
                    if su_norm.rstrip("/") == candidate.rstrip("/"):
                        found = True
                        break
                if not found:
                    all_match = False
                    break
        if all_match:
            url_in_log_ok = True
    if url_in_log_ok:
        scores["sources_url_in_log"] = 1.0

    query_in_log_ok = False
    if rows is not None and log_valid:
        log_queries = {obj.get("query", "").strip() for obj in log_objs if isinstance(obj.get("query", ""), str)}
        all_found = True
        for r in rows:
            q = (r.get("query_used") or "").strip()
            if q == "" or q not in log_queries:
                all_found = False
                break
        if all_found:
            query_in_log_ok = True
    if query_in_log_ok:
        scores["sources_query_in_log"] = 1.0

    notes_text = _safe_read_text(meeting_notes)
    headings = [
        "Purpose",
        "Key findings summary",
        "Risks & limitations",
        "Open questions",
        "Action items",
    ]
    sections_present = False
    if notes_text:
        present_flags = []
        for h in headings:
            present_flags.append(any(_line_is_heading(line, h) for line in notes_text.splitlines()))
        sections_present = all(present_flags)
    if sections_present:
        scores["meeting_notes_sections_present"] = 1.0

    refs_score = 0.0
    if notes_text and rows is not None and isinstance(rows, list):
        ids = [str(r.get("source_id", "")).strip() for r in rows if str(r.get("source_id", "")).strip()]
        key_findings_section = _find_section(notes_text, "Key findings summary", headings)
        if key_findings_section:
            found_ids = set()
            for sid in ids:
                if not sid:
                    continue
                if re.search(r'\b' + re.escape(sid) + r'\b', key_findings_section):
                    found_ids.add(sid)
            if len(found_ids) >= 5:
                refs_score = 1.0
            else:
                if len(found_ids) > 0:
                    refs_score = min(len(found_ids) / 5.0, 1.0)
    scores["meeting_notes_references_to_sources"] = refs_score

    action_items_ok = False
    if notes_text:
        action_section = _find_section(notes_text, "Action items", headings)
        if action_section:
            bullets = _extract_bullets(action_section)
            if 3 <= len(bullets) <= 6:
                action_items_ok = True
    if action_items_ok:
        scores["action_items_count_valid"] = 1.0

    email_text = _safe_read_text(email_polished)
    wc_ok = False
    attach_ok = False
    if email_text:
        wc = _count_words(email_text)
        wc_ok = 150 <= wc <= 180
        bullets = _extract_bullets(email_text)
        has_sources = any("sources.csv" in b.lower() for b in bullets)
        has_notes = any("meeting_notes.md" in b.lower() for b in bullets)
        attach_ok = has_sources and has_notes
    if wc_ok and attach_ok:
        scores["email_polished_word_count_and_attachments"] = 1.0

    email_content_ok = False
    if email_text:
        low = email_text.lower()
        banned_email_terms = {
            "bribe", "bribery", "bribing", "corrupt", "corruption", "kickback", "kickbacks",
            "collude", "collusion", "illegal", "guilty", "criminal", "crime", "payoff",
            "payoffs", "cover-up", "coverup", "conspiracy", "scandal", "press", "aggressive", "names", "asap", "urgent"
        }
        neutral_ok = not any(term in low for term in banned_email_terms)
        meeting_ok = ("meeting" in low) or ("meet" in low)
        public_records_ok = "public record" in low or "public records" in low
        prelim_ok = "preliminary" in low
        objective_scope_ok = ("objective" in low) or ("scope" in low)
        email_content_ok = neutral_ok and meeting_ok and public_records_ok and prelim_ok and objective_scope_ok
    if email_content_ok:
        scores["email_polished_neutrality_and_meeting_and_public_records"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()