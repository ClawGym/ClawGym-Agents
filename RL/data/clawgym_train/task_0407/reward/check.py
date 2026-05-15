import sys
import json
import csv
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = []
            for row in reader:
                # Ensure all keys exist
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return headers, rows
    except Exception:
        return None, None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        items.append(obj)
                    else:
                        return None
                except Exception:
                    return None
        return items
    except Exception:
        return None


def _parse_iso8601_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    val = value.strip()
    # Handle 'Z' timezone by converting to +00:00
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def _domains_match(source_domain: str, url: str) -> bool:
    if not source_domain or not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    src = source_domain.lower()
    # Strip common leading 'www.' for comparison
    if host.startswith("www."):
        host_cmp = host[4:]
    else:
        host_cmp = host
    if src.startswith("www."):
        src_cmp = src[4:]
    else:
        src_cmp = src
    # Match if equal or suffix/prefix matches (handle subdomains)
    return host_cmp == src_cmp or host_cmp.endswith("." + src_cmp) or src_cmp.endswith("." + host_cmp)


def _extract_brief_title_date(brief_text: str) -> Tuple[Optional[str], Optional[str]]:
    title = None
    date_val = None
    for line in brief_text.splitlines():
        if line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("Date:"):
            date_val = line.split(":", 1)[1].strip()
    return title, date_val


def _parse_recipients(path: Path) -> Optional[List[Dict[str, str]]]:
    headers, rows = _load_csv(path)
    if headers is None or rows is None:
        return None
    required = {"name", "email", "language_preference", "affiliation", "role"}
    if not set(headers).issuperset(required):
        return None
    return rows


def _first_nonempty_line_after(lines: List[str], start_index: int) -> Optional[Tuple[int, str]]:
    for i in range(start_index + 1, len(lines)):
        if lines[i].strip():
            return i, lines[i]
    return None


def _check_subject_and_greeting(email_text: str, recipient_name: str) -> bool:
    lines = email_text.splitlines()
    # Find first non-empty line
    first_idx = None
    for i, ln in enumerate(lines):
        if ln.strip():
            first_idx = i
            break
    if first_idx is None:
        return False
    if not lines[first_idx].startswith("Subject:"):
        return False
    next_line = _first_nonempty_line_after(lines, first_idx)
    if not next_line:
        return False
    _, greet_line = next_line
    # Greeting should include recipient name exactly
    return recipient_name in greet_line


def _email_includes_title_and_date(email_text: str, title: str, date_str: str) -> bool:
    if not title or not date_str:
        return False
    return (title in email_text) and (date_str in email_text)


def _get_recommended_items(email_text: str, sources_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    recommended: List[Dict[str, str]] = []
    text = email_text
    for row in sources_rows:
        title = row.get("title", "") or ""
        issuing = row.get("issuing_body", "") or ""
        if title and issuing and (title in text) and (issuing in text):
            recommended.append(row)
    # Deduplicate by (title, issuing_body)
    seen = set()
    uniq = []
    for r in recommended:
        key = (r.get("title", ""), r.get("issuing_body", ""))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _notes_lines_count_ok(notes: str) -> bool:
    if notes is None:
        return False
    # Count logical lines
    lines = notes.splitlines()
    # Allow 1 to 2 lines inclusive, non-empty
    return len(lines) in (1, 2) and any(part.strip() for part in lines)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "sources_csv_present_and_header": 0.0,
        "sources_minimum_five_items": 0.0,
        "sources_years_within_1968_1978_when_provided": 0.0,
        "sources_languages_nonempty": 0.0,
        "sources_source_domain_matches_url": 0.0,
        "sources_access_date_format_valid": 0.0,
        "sources_at_least_two_institutions": 0.0,
        "sources_notes_one_to_two_lines": 0.0,
        "search_log_present_and_schema": 0.0,
        "search_log_queries_unique": 0.0,
        "email_li_subject_and_greeting": 0.0,
        "email_li_includes_brief_title_and_date": 0.0,
        "email_li_recommends_2_to_3_items_from_csv": 0.0,
        "email_li_language_preference_respected": 0.0,
        "email_li_polite_close": 0.0,
        "email_sato_subject_and_greeting": 0.0,
        "email_sato_includes_brief_title_and_date": 0.0,
        "email_sato_recommends_2_to_3_items_from_csv": 0.0,
        "email_sato_language_preference_respected": 0.0,
        "email_sato_polite_close": 0.0,
    }

    # Load sources.csv
    sources_path = workspace / "out" / "sources.csv"
    sources_headers, sources_rows = _load_csv(sources_path)

    required_headers = [
        "title",
        "issuing_body",
        "year",
        "language",
        "document_type",
        "source_domain",
        "url",
        "access_date",
        "notes",
    ]
    sources_present = False
    if sources_headers is not None and sources_rows is not None:
        # Check exact header order
        if sources_headers == required_headers:
            scores["sources_csv_present_and_header"] = 1.0
            sources_present = True
        else:
            # If file exists but headers don't match exactly, mark as present but fail header check.
            sources_present = True

    # Sources minimum five items
    if sources_rows is not None and len(sources_rows) >= 5:
        scores["sources_minimum_five_items"] = 1.0

    # Sources years within 1968-1978 when provided
    if sources_rows is not None:
        all_ok = True
        for row in sources_rows:
            y = (row.get("year") or "").strip()
            if y == "":
                # allowed to be empty
                continue
            try:
                yi = int(y)
            except Exception:
                all_ok = False
                break
            if not (1968 <= yi <= 1978):
                all_ok = False
                break
        if all_ok:
            scores["sources_years_within_1968_1978_when_provided"] = 1.0

    # Languages nonempty
    if sources_rows is not None and sources_headers is not None and ("language" in sources_headers):
        if all((row.get("language") or "").strip() != "" for row in sources_rows):
            scores["sources_languages_nonempty"] = 1.0

    # Source domain matches URL
    if sources_rows is not None and sources_headers is not None and ("source_domain" in sources_headers) and ("url" in sources_headers):
        all_match = True
        for row in sources_rows:
            sd = (row.get("source_domain") or "").strip()
            url = (row.get("url") or "").strip()
            if not _domains_match(sd, url):
                all_match = False
                break
        if all_match and len(sources_rows) > 0:
            scores["sources_source_domain_matches_url"] = 1.0

    # Access date format YYYY-MM-DD
    if sources_rows is not None and sources_headers is not None and ("access_date" in sources_headers):
        fmt_ok = True
        for row in sources_rows:
            ad = (row.get("access_date") or "").strip()
            try:
                datetime.strptime(ad, "%Y-%m-%d")
            except Exception:
                fmt_ok = False
                break
        if fmt_ok and len(sources_rows) > 0:
            scores["sources_access_date_format_valid"] = 1.0

    # At least two institutions (by issuing_body and source_domain)
    if sources_rows is not None and sources_headers is not None and ("issuing_body" in sources_headers) and ("source_domain" in sources_headers):
        uniq_issuing = set()
        uniq_domains = set()
        for row in sources_rows:
            uniq_issuing.add((row.get("issuing_body") or "").strip())
            uniq_domains.add((row.get("source_domain") or "").strip())
        if len([x for x in uniq_issuing if x]) >= 2 and len([x for x in uniq_domains if x]) >= 2:
            scores["sources_at_least_two_institutions"] = 1.0

    # Notes one to two lines and non-empty
    if sources_rows is not None and sources_headers is not None and ("notes" in sources_headers):
        notes_ok = True
        for row in sources_rows:
            notes = row.get("notes")
            if not _notes_lines_count_ok(notes if notes is not None else ""):
                notes_ok = False
                break
        if notes_ok and len(sources_rows) > 0:
            scores["sources_notes_one_to_two_lines"] = 1.0

    # Search log checks
    search_log_path = workspace / "out" / "search_log.jsonl"
    search_items = _load_jsonl(search_log_path)
    if search_items is not None and len(search_items) >= 1:
        schema_ok = True
        for obj in search_items:
            if not all(k in obj for k in ("query", "engine", "rationale", "timestamp")):
                schema_ok = False
                break
            if not isinstance(obj["query"], str) or not isinstance(obj["engine"], str) or not isinstance(obj["rationale"], str):
                schema_ok = False
                break
            if not _parse_iso8601_timestamp(obj["timestamp"]):
                schema_ok = False
                break
        if schema_ok:
            scores["search_log_present_and_schema"] = 1.0

        # Queries unique
        queries = [str(obj.get("query", "")).strip() for obj in search_items]
        if len(queries) == len(set(queries)) and all(q != "" for q in queries):
            scores["search_log_queries_unique"] = 1.0

    # Emails
    recipients_path = workspace.parent / "input" / "recipients.csv"
    brief_path = workspace.parent / "input" / "brief.md"
    recipients = _parse_recipients(recipients_path)
    brief_text = _safe_read_text(brief_path)
    brief_title, brief_date = (None, None)
    if brief_text is not None:
        brief_title, brief_date = _extract_brief_title_date(brief_text)

    # Build map from names to expected files and language preference
    recipients_info: Dict[str, Dict[str, Any]] = {}
    if recipients is not None:
        for r in recipients:
            name = r.get("name", "")
            if name == "Li Wei":
                recipients_info["Li Wei"] = {
                    "filename": workspace / "out" / "emails" / "email_to_li_wei.txt",
                    "language_preference": r.get("language_preference", "").strip(),
                }
            elif name == "Sato Hiroshi":
                recipients_info["Sato Hiroshi"] = {
                    "filename": workspace / "out" / "emails" / "email_to_sato_hiroshi.txt",
                    "language_preference": r.get("language_preference", "").strip(),
                }

    # Helper to grade each email
    def grade_email(name: str, subject_key: str, title_date_key: str, recs_key: str, lang_pref_key: str, polite_key: str) -> None:
        info = recipients_info.get(name)
        if info is None:
            return
        email_path: Path = info["filename"]
        email_text = _safe_read_text(email_path)
        if email_text is None:
            return

        # Subject and greeting
        if _check_subject_and_greeting(email_text, name):
            scores[subject_key] = 1.0

        # Includes seminar title and date
        if brief_title and brief_date and _email_includes_title_and_date(email_text, brief_title, brief_date):
            scores[title_date_key] = 1.0

        # Recommendations: 2 to 3 items with exact title and issuing_body
        if sources_rows is not None:
            recs = _get_recommended_items(email_text, sources_rows)
            if 2 <= len(recs) <= 3:
                scores[recs_key] = 1.0

            # Language preference respected
            pref = (info.get("language_preference") or "").strip().lower()
            if pref:
                available_pref_items = [row for row in sources_rows if (row.get("language") or "").strip().lower() == pref]
                if len(available_pref_items) == 0:
                    # Nothing available in preferred language -> consider satisfied by default
                    scores[lang_pref_key] = 1.0
                else:
                    recs_have_pref = any((r.get("language") or "").strip().lower() == pref for r in recs)
                    if recs_have_pref:
                        scores[lang_pref_key] = 1.0

        # Polite close with request for feedback or suggestions
        text_lower = email_text.lower()
        if ("feedback" in text_lower) or ("suggestion" in text_lower):
            scores[polite_key] = 1.0

    grade_email(
        name="Li Wei",
        subject_key="email_li_subject_and_greeting",
        title_date_key="email_li_includes_brief_title_and_date",
        recs_key="email_li_recommends_2_to_3_items_from_csv",
        lang_pref_key="email_li_language_preference_respected",
        polite_key="email_li_polite_close",
    )
    grade_email(
        name="Sato Hiroshi",
        subject_key="email_sato_subject_and_greeting",
        title_date_key="email_sato_includes_brief_title_and_date",
        recs_key="email_sato_recommends_2_to_3_items_from_csv",
        lang_pref_key="email_sato_language_preference_respected",
        polite_key="email_sato_polite_close",
    )

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()