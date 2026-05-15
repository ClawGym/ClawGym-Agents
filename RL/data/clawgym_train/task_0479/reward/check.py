import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _parse_topics_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_topics = False
    topics: List[Dict[str, Any]] = []
    current_item: Optional[Dict[str, Any]] = None
    current_list_key: Optional[str] = None
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not in_topics:
            if line.strip().startswith("topics:"):
                in_topics = True
            continue
        m_key = re.match(r'^\s*-\s+key:\s*(.+?)\s*$', line)
        if m_key:
            if current_item:
                topics.append(current_item)
            key_val = m_key.group(1).strip().strip('"\'')
            current_item = {"key": key_val}
            current_list_key = None
            continue
        m_section = re.match(r'^\s*([a-zA-Z0-9_]+):\s*$', line)
        if m_section and current_item is not None:
            sec = m_section.group(1)
            if sec in ("query_terms", "must_have_any"):
                current_list_key = sec
                current_item[sec] = []
            else:
                current_list_key = None
            continue
        m_item = re.match(r'^\s*-\s*(.+?)\s*$', line)
        if m_item and current_item is not None and current_list_key:
            val = m_item.group(1).strip().strip('"\'')
            current_item[current_list_key].append(val)
            continue
    if current_item:
        topics.append(current_item)
    if not topics:
        return None
    return {"topics": topics}


def _slugify_event(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip().lower())


def _parse_tsv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    text = _read_text(path)
    if text is None:
        return None, None
    lines = [ln for ln in text.splitlines() if ln != ""]
    if not lines:
        return None, None
    header = lines[0].split("\t")
    rows: List[Dict[str, str]] = []
    for ln in lines[1:]:
        cols = ln.split("\t")
        if len(cols) < len(header):
            cols = cols + [""] * (len(header) - len(cols))
        row = {header[i]: cols[i] if i < len(cols) else "" for i in range(len(header))}
        rows.append(row)
    return header, rows


def _to_int_safe(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _extract_last_int(s: str) -> Optional[int]:
    nums = re.findall(r'(\d+)', s)
    if not nums:
        return None
    try:
        return int(nums[-1])
    except Exception:
        return None


def _is_iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()))


def _read_nonempty_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    return lines


def _html_extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>(.*?)</title>', html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    title = m.group(1)
    title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', title)).strip()
    return title


def _html_extract_first_h1(html: str) -> str:
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    h1 = m.group(1)
    h1 = re.sub(r'<[^>]+>', '', h1)
    h1 = re.sub(r'\s+', ' ', h1).strip()
    return h1


def _html_links_count(html: str) -> int:
    return len(re.findall(r'<a\b', html, flags=re.IGNORECASE))


def _html_iso_dates(html: str) -> List[str]:
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', html)
    # unique preserving order of first appearance
    seen = set()
    unique = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _html_emails(html: str) -> List[str]:
    # simple email regex
    emails = re.findall(r'[\w\.\-]+@[\w\.\-]+\.\w+', html)
    # unique preserving order
    seen = set()
    unique = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def _hostname_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.split("@")[-1]  # remove userinfo if any
        host = host.split(":")[0]  # remove port
        return host.lower()
    except Exception:
        return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "downloads_log_header_and_count": 0.0,
        "downloads_entries_valid": 0.0,
        "downloads_queries_include_terms": 0.0,
        "errors_log_total_failed": 0.0,
        "summary_events_and_fields_match_inputs": 0.0,
        "summary_topics_fields_and_files": 0.0,
        "summary_downloads_alignment": 0.0,
        "ranking_correctness": 0.0,
        "priority_events_filtering": 0.0,
    }

    # Parse inputs
    schedule_path = workspace / "input" / "schedule.csv"
    topics_path = workspace / "input" / "topics.yaml"
    schedule_rows = _read_csv_dicts(schedule_path) or []
    topics_doc = _parse_topics_yaml(topics_path)

    # Build canonical inputs
    events_by_name: Dict[str, Dict[str, str]] = {}
    for r in schedule_rows:
        if all(k in r for k in ["event_name", "city", "country", "start_date", "end_date"]):
            events_by_name[r["event_name"]] = {
                "city": r["city"],
                "country": r["country"],
                "start_date": r["start_date"],
                "end_date": r["end_date"],
            }
    topic_keys: List[str] = []
    topic_query_terms: Dict[str, List[str]] = {}
    if topics_doc and "topics" in topics_doc and isinstance(topics_doc["topics"], list):
        for t in topics_doc["topics"]:
            if isinstance(t, dict) and "key" in t:
                k = str(t["key"])
                topic_keys.append(k)
                q = t.get("query_terms") if isinstance(t.get("query_terms"), list) else []
                topic_query_terms[k] = [str(x) for x in q]

    expected_pairs = [(ename, t) for ename in events_by_name.keys() for t in topic_keys]

    # Parse downloads log
    downloads_path = workspace / "logs" / "downloads.tsv"
    d_header, d_rows = _parse_tsv_with_header(downloads_path)
    valid_header = ["timestamp", "event_name", "topic_key", "query_used", "chosen_url", "http_status", "saved_path", "error_excerpt"]
    header_ok = d_header == valid_header

    # Count and structure check
    if header_ok and d_rows is not None and expected_pairs:
        count_ok = (len(d_rows) == len(expected_pairs))
        if count_ok:
            scores["downloads_log_header_and_count"] = 1.0

    # Validate entries and build success/failure maps
    successes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    failures: Dict[Tuple[str, str], Dict[str, Any]] = {}
    entries_valid = True
    queries_ok = True
    if header_ok and d_rows is not None and expected_pairs:
        # Build map to detect duplicates and unexpected rows
        seen_pairs = set()
        for row in d_rows:
            en = (row.get("event_name") or "").strip()
            tk = (row.get("topic_key") or "").strip()
            query_used = (row.get("query_used") or "").strip()
            chosen_url = (row.get("chosen_url") or "").strip()
            saved_path = (row.get("saved_path") or "").strip()
            status_val = row.get("http_status", "")
            status_int = _to_int_safe(status_val)
            error_excerpt = (row.get("error_excerpt") or "")
            timestamp = (row.get("timestamp") or "").strip()

            # basic validations
            if en not in events_by_name or tk not in topic_keys:
                entries_valid = False
                break
            if (en, tk) in seen_pairs:
                entries_valid = False
                break
            seen_pairs.add((en, tk))
            if not timestamp:
                entries_valid = False
                break
            if not query_used or not chosen_url or not saved_path:
                entries_valid = False
                break
            # chosen_url format
            if not re.match(r'^https?://', chosen_url):
                entries_valid = False
                break
            # query terms check (event_name + at least one topic query term)
            q_terms = topic_query_terms.get(tk, [])
            q_ok = False
            qu_lower = query_used.lower()
            if en.strip():
                if en.lower() in qu_lower:
                    for term in q_terms:
                        if term.lower() in qu_lower:
                            q_ok = True
                            break
            if not q_ok:
                queries_ok = False
            # path correctness
            expected_rel = Path("web") / _slugify_event(en) / f"{tk}.html"
            if Path(saved_path).as_posix() != expected_rel.as_posix():
                entries_valid = False
                break
            # status / error rules
            if status_int == 200:
                if error_excerpt.strip():
                    entries_valid = False
                    break
                if not (workspace / expected_rel).is_file():
                    entries_valid = False
                    break
                successes[(en, tk)] = {
                    "saved_path": saved_path,
                    "http_status": status_int,
                    "chosen_url": chosen_url,
                }
            else:
                if not error_excerpt.strip():
                    entries_valid = False
                    break
                failures[(en, tk)] = {
                    "saved_path": saved_path,
                    "http_status": status_int,
                    "chosen_url": chosen_url,
                }
        # Ensure exactly expected pairs were present and no extras
        if entries_valid and len(seen_pairs) != len(expected_pairs):
            entries_valid = False
    else:
        entries_valid = False
        queries_ok = False

    if entries_valid:
        scores["downloads_entries_valid"] = 1.0
    if queries_ok and entries_valid:
        scores["downloads_queries_include_terms"] = 1.0

    # errors.log check
    errors_log_path = workspace / "logs" / "errors.log"
    errors_lines = _read_nonempty_lines(errors_log_path) or []
    errors_ok = False
    if header_ok and d_rows is not None:
        failed_count = sum(1 for row in d_rows if _to_int_safe(row.get("http_status", "")) != 200)
        if errors_lines:
            last_line = errors_lines[-1]
            n = _extract_last_int(last_line)
            # ensure at least one line per failure + final summary line
            if n == failed_count and len(errors_lines) >= (1 if failed_count == 0 else failed_count + 1):
                errors_ok = True
    if errors_ok:
        scores["errors_log_total_failed"] = 1.0

    # summary.json checks
    summary_path = workspace / "reports" / "summary.json"
    summary = _read_json(summary_path)
    summary_events_ok = False
    summary_topics_ok = False
    downloads_alignment_ok = False

    if isinstance(summary, list) and events_by_name:
        if len(summary) == len(events_by_name):
            by_event: Dict[str, Dict[str, Any]] = {}
            names_ok = True
            for ev in summary:
                if not isinstance(ev, dict):
                    names_ok = False
                    break
                en = ev.get("event_name")
                if en not in events_by_name:
                    names_ok = False
                    break
                if ev.get("city") != events_by_name[en]["city"]:
                    names_ok = False
                    break
                if ev.get("country") != events_by_name[en]["country"]:
                    names_ok = False
                    break
                if ev.get("start_date") != events_by_name[en]["start_date"]:
                    names_ok = False
                    break
                if ev.get("end_date") != events_by_name[en]["end_date"]:
                    names_ok = False
                    break
                by_event[en] = ev
            if names_ok and len(by_event) == len(events_by_name):
                summary_events_ok = True

            # topic fields checks with recomputation from HTML and downloads alignment
            topics_ok_local = True
            if names_ok:
                for en, ev in by_event.items():
                    topics_obj = ev.get("topics")
                    if topics_obj is None:
                        topics_obj = {}
                    if not isinstance(topics_obj, dict):
                        topics_ok_local = False
                        break
                    for tk, tinfo in topics_obj.items():
                        if tk not in topic_keys:
                            topics_ok_local = False
                            break
                        if not isinstance(tinfo, dict):
                            topics_ok_local = False
                            break
                        page_title = tinfo.get("page_title")
                        source_domain = tinfo.get("source_domain")
                        first_h1_text = tinfo.get("first_h1_text", "")
                        iso_dates = tinfo.get("iso_dates")
                        emails = tinfo.get("emails")
                        links_count = tinfo.get("links_count")
                        http_status = tinfo.get("http_status")
                        saved_path = tinfo.get("saved_path")

                        hs_int = _to_int_safe(http_status)
                        if hs_int != 200:
                            topics_ok_local = False
                            break
                        if not isinstance(saved_path, str):
                            topics_ok_local = False
                            break
                        expected_rel = Path("web") / _slugify_event(en) / f"{tk}.html"
                        if Path(saved_path).as_posix() != expected_rel.as_posix():
                            topics_ok_local = False
                            break
                        full_path = (workspace / expected_rel)
                        if not full_path.is_file():
                            topics_ok_local = False
                            break
                        html_txt = _read_text(full_path)
                        if html_txt is None:
                            topics_ok_local = False
                            break
                        # recompute fields
                        comp_title = _html_extract_title(html_txt)
                        comp_h1 = _html_extract_first_h1(html_txt)
                        comp_dates = _html_iso_dates(html_txt)
                        comp_emails = _html_emails(html_txt)
                        comp_links = _html_links_count(html_txt)

                        # compare fields
                        if not isinstance(page_title, str) or page_title != comp_title:
                            topics_ok_local = False
                            break
                        # ensure source_domain matches downloads chosen_url
                        chosen_url = None
                        if (en, tk) in successes:
                            chosen_url = successes[(en, tk)].get("chosen_url")
                        elif (en, tk) in failures:
                            # shouldn't include failed topics in summary
                            topics_ok_local = False
                            break
                        else:
                            topics_ok_local = False
                            break
                        expected_domain = _hostname_from_url(chosen_url or "")
                        if not isinstance(source_domain, str) or source_domain.lower() != expected_domain:
                            topics_ok_local = False
                            break
                        if not isinstance(first_h1_text, str) or first_h1_text != comp_h1:
                            topics_ok_local = False
                            break
                        if not isinstance(iso_dates, list) or any(not isinstance(x, str) or not _is_iso_date(x) for x in iso_dates):
                            topics_ok_local = False
                            break
                        if iso_dates != comp_dates:
                            topics_ok_local = False
                            break
                        if not isinstance(emails, list) or any(not isinstance(x, str) for x in emails):
                            topics_ok_local = False
                            break
                        # compare email sets preserving order: we require exact list equality from simple extraction
                        if emails != comp_emails:
                            topics_ok_local = False
                            break
                        if _to_int_safe(links_count) is None or int(links_count) != comp_links:
                            topics_ok_local = False
                            break
                    if not topics_ok_local:
                        break
            if topics_ok_local:
                summary_topics_ok = True

            # alignment with downloads: topics present should equal successes set; no failed topics included
            if names_ok and d_rows is not None:
                align_ok = True
                for en, ev in by_event.items():
                    topics_obj = ev.get("topics") or {}
                    present_topics = set(topics_obj.keys())
                    success_topics = {tk for (e2, tk) in successes.keys() if e2 == en}
                    fail_topics = {tk for (e2, tk) in failures.keys() if e2 == en}
                    if present_topics != success_topics:
                        align_ok = False
                        break
                    if present_topics & fail_topics:
                        align_ok = False
                        break
                downloads_alignment_ok = align_ok

    if summary_events_ok:
        scores["summary_events_and_fields_match_inputs"] = 1.0
    if summary_topics_ok:
        scores["summary_topics_fields_and_files"] = 1.0
    if downloads_alignment_ok:
        scores["summary_downloads_alignment"] = 1.0

    # ranking.csv checks
    ranking_path = workspace / "reports" / "ranking.csv"
    r_header, r_data = _read_csv_with_header(ranking_path)
    ranking_ok = False
    if r_header and r_data is not None and isinstance(summary, list) and summary:
        if r_header == ["event_name", "completeness_score", "total_topics", "found_topics"]:
            if len(r_data) == len(events_by_name):
                # map summary topics by event
                summary_by_event: Dict[str, set] = {}
                for ev in summary:
                    en = ev.get("event_name")
                    tdict = ev.get("topics") or {}
                    if isinstance(tdict, dict):
                        summary_by_event[en] = set(tdict.keys())
                # check each row correctness and collect for order checking
                parsed_rows: List[Tuple[str, int]] = []
                rows_valid = True
                for row in r_data:
                    if len(row) != 4:
                        rows_valid = False
                        break
                    en, comp_s, total_t, found = row
                    if en not in events_by_name:
                        rows_valid = False
                        break
                    comp_i = _to_int_safe(comp_s)
                    total_i = _to_int_safe(total_t)
                    if comp_i is None or total_i is None:
                        rows_valid = False
                        break
                    if total_i != len(topic_keys):
                        rows_valid = False
                        break
                    expected_comp = len(summary_by_event.get(en, set()))
                    if comp_i != expected_comp:
                        rows_valid = False
                        break
                    found_set = set([x.strip() for x in found.split(",") if x.strip() != ""])
                    if found_set != summary_by_event.get(en, set()):
                        rows_valid = False
                        break
                    parsed_rows.append((en, comp_i))
                # order check: completeness desc, then event_name asc
                if rows_valid:
                    order_ok = True
                    for i in range(len(parsed_rows) - 1):
                        en1, c1 = parsed_rows[i]
                        en2, c2 = parsed_rows[i + 1]
                        if c1 < c2:
                            order_ok = False
                            break
                        if c1 == c2 and en1 > en2:
                            order_ok = False
                            break
                    if order_ok:
                        ranking_ok = True
    if ranking_ok:
        scores["ranking_correctness"] = 1.0

    # priority_events.csv checks
    priority_path = workspace / "reports" / "priority_events.csv"
    p_header, p_data = _read_csv_with_header(priority_path)
    priority_ok = False
    if p_header and p_data is not None and r_header and r_data is not None:
        if p_header == ["event_name", "completeness_score", "total_topics", "found_topics"]:
            # expected rows from ranking: rows with completeness_score >= 2, keep same order
            expected_rows = []
            for row in r_data:
                en, comp_s, total_t, found = row
                comp_i = _to_int_safe(comp_s)
                if comp_i is not None and comp_i >= 2:
                    expected_rows.append(row)
            if expected_rows == p_data:
                priority_ok = True
    if priority_ok:
        scores["priority_events_filtering"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()