import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from html import unescape
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        if not path.exists() or not path.is_file():
            return None
        items = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
        with path.open("r", encoding="utf-8", newline="") as f2:
            dict_reader = csv.DictReader(f2)
            rows = [row for row in dict_reader]
        return header, rows
    except Exception:
        return None, None


def _extract_domain(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        return p.netloc.lower()
    except Exception:
        return None


def _is_allowed_domain(url: str, allowed_domains: List[str]) -> bool:
    dom = _extract_domain(url)
    if dom is None:
        return False
    return dom in [d.lower() for d in allowed_domains]


def _strip_html_visible_text(html: str) -> str:
    if html is None:
        return ""
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<head.*?>.*?</head>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _count_h2_h3(html: str) -> int:
    if html is None:
        return 0
    h = html.lower()
    c2 = len(re.findall(r"<\s*h2(\s|>)", h))
    c3 = len(re.findall(r"<\s*h3(\s|>)", h))
    return c2 + c3


def _count_keyword_hits(text: str, term: str) -> int:
    if not term:
        return 0
    pattern = r"\b" + re.escape(term) + r"\b"
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    return len(matches)


def _extract_title(html: str) -> Optional[str]:
    if html is None:
        return None
    m = re.search(r"(?is)<title>(.*?)</title>", html)
    if not m:
        return None
    title = m.group(1)
    title = re.sub(r"\s+", " ", title).strip()
    return unescape(title)


def _safe_int(val) -> Optional[int]:
    try:
        if val is None or val == "":
            return None
        return int(str(val).strip())
    except Exception:
        return None


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if p.strip())


def _contains_number(text: str, number: int) -> bool:
    if not text:
        return False
    pattern = r"\b" + re.escape(str(number)) + r"\b"
    return re.search(pattern, text) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "index_csv_columns_valid": 0.0,
        "index_rows_field_types_and_domains": 0.0,
        "html_files_present_and_referenced": 0.0,
        "per_topic_min_pages_collected": 0.0,
        "keyword_hits_valid_and_match_html": 0.0,
        "section_count_matches_html": 0.0,
        "ranking_correct_per_topic": 0.0,
        "search_log_present_and_format_valid": 0.0,
        "search_queries_cover_topic_domain_pairs": 0.0,
        "selected_urls_cover_index_urls": 0.0,
        "selected_urls_in_allowed_domains": 0.0,
        "report_exists_and_includes_sections": 0.0,
        "report_mentions_domains_and_site_pattern": 0.0,
        "report_includes_top_page_urls": 0.0,
        "report_reflects_total_counts": 0.0,
        "first_paragraph_concise": 0.0,
        "word_count_plausible": 0.0,
    }

    # Load config (used to validate outputs; does not directly award points)
    config_path = workspace / "input" / "topics.json"
    config = _load_json(config_path)
    topics: List[str] = []
    domains: List[str] = []
    min_pages: Optional[int] = None
    if isinstance(config, dict):
        topics = config.get("topics") if isinstance(config.get("topics"), list) else []
        domains = config.get("domains") if isinstance(config.get("domains"), list) else []
        min_pages = config.get("min_pages_per_topic") if isinstance(config.get("min_pages_per_topic"), int) else None

    # Paths
    pages_dir = workspace / "outputs" / "pages"
    index_csv = workspace / "outputs" / "data" / "index.csv"
    search_log = workspace / "outputs" / "logs" / "search_log.jsonl"
    report_md = workspace / "outputs" / "report.md"

    # Load index.csv
    header, rows = _read_csv_with_header(index_csv)
    expected_columns = [
        "topic",
        "source_domain",
        "url",
        "page_title",
        "html_filename",
        "word_count",
        "section_count",
        "keyword_hits",
        "rank_within_topic",
        "first_paragraph",
    ]
    if header is not None and rows is not None and header == expected_columns:
        scores["index_csv_columns_valid"] = 1.0

    # Validate index rows
    if rows:
        total_rows = len(rows)
        valid_rows = 0
        files_present = 0
        keyword_match_count = 0
        section_match_count = 0
        first_para_concise_hits = 0
        word_count_plausible_hits = 0

        # Preload HTML cache
        html_cache: Dict[str, Optional[str]] = {}

        for r in rows:
            topic = (r.get("topic") or "").strip()
            source_domain = (r.get("source_domain") or "").strip().lower()
            url = (r.get("url") or "").strip()
            page_title = (r.get("page_title") or "").strip()
            html_filename = (r.get("html_filename") or "").strip()
            wc = _safe_int(r.get("word_count"))
            sc = _safe_int(r.get("section_count"))
            kh = _safe_int(r.get("keyword_hits"))
            rank = _safe_int(r.get("rank_within_topic"))
            first_paragraph = (r.get("first_paragraph") or "").strip()

            field_types_ok = True
            # Basic type/empty checks
            if not topic or not url or not page_title or not html_filename:
                field_types_ok = False
            if wc is None or wc < 0:
                field_types_ok = False
            if sc is None or sc < 0:
                field_types_ok = False
            if kh is None or kh < 0:
                field_types_ok = False
            if rank is None or rank < 1:
                field_types_ok = False
            if not first_paragraph:
                field_types_ok = False
            # Topic must be in config topics (if available)
            if topics and topic not in topics:
                field_types_ok = False
            # Domain of URL must match source_domain exactly
            url_domain = _extract_domain(url) or ""
            if url_domain != source_domain:
                field_types_ok = False
            # Domain must be in allowed domains
            if domains and source_domain not in [d.lower() for d in domains]:
                field_types_ok = False

            # html_filename should not contain path separators and should exist
            html_path = pages_dir / html_filename
            if "/" in html_filename or "\\" in html_filename:
                # invalid path pattern
                pass
            if html_path.exists() and html_path.is_file():
                files_present += 1
            # Evaluate HTML-related checks only if file exists
            html_content = None
            if html_path.exists() and html_path.is_file():
                if html_filename not in html_cache:
                    html_cache[html_filename] = _read_text(html_path)
                html_content = html_cache[html_filename]
                visible_text = _strip_html_visible_text(html_content or "")
                # keyword hits: recompute from visible text
                recomputed_kh = _count_keyword_hits(visible_text, topic)
                if kh is not None and kh == recomputed_kh and kh >= 1:
                    keyword_match_count += 1
                # section count: count h2 + h3
                recomputed_sc = _count_h2_h3(html_content or "")
                if sc is not None and sc == recomputed_sc:
                    section_match_count += 1
                # first paragraph conciseness: <= 3 sentences and reasonable length
                sent_count = _sentence_count(first_paragraph)
                if 1 <= sent_count <= 3 and len(first_paragraph) <= 600:
                    first_para_concise_hits += 1
                # word_count plausible: >= words in first_paragraph and within reasonable bounds
                first_words = len(re.findall(r"\w+", first_paragraph))
                if wc is not None and wc >= first_words and wc <= 500000:
                    word_count_plausible_hits += 1

            # Enforce keyword_hits >= 1 for included rows
            if kh is None or kh < 1:
                field_types_ok = False

            if field_types_ok:
                valid_rows += 1

        if total_rows > 0:
            scores["index_rows_field_types_and_domains"] = valid_rows / total_rows
            scores["html_files_present_and_referenced"] = files_present / total_rows
            scores["keyword_hits_valid_and_match_html"] = keyword_match_count / total_rows
            scores["section_count_matches_html"] = section_match_count / total_rows
            scores["first_paragraph_concise"] = first_para_concise_hits / total_rows
            scores["word_count_plausible"] = word_count_plausible_hits / total_rows

    # Per-topic minimum pages
    if rows and topics and isinstance(min_pages, int):
        per_topic_ok = 0
        for t in topics:
            cnt = sum(1 for r in rows if (r.get("topic") or "").strip() == t)
            if cnt >= min_pages:
                per_topic_ok += 1
        if len(topics) > 0:
            scores["per_topic_min_pages_collected"] = per_topic_ok / len(topics)

    # Ranking correctness per topic
    def _in_title(title: str, term: str) -> bool:
        if not title or not term:
            return False
        return re.search(r"\b" + re.escape(term) + r"\b", title, flags=re.IGNORECASE) is not None

    if rows and topics:
        topic_to_rows: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            t = (r.get("topic") or "").strip()
            if t:
                topic_to_rows.setdefault(t, []).append(r)
        topic_ranking_ok = 0
        topic_count = 0
        for t, lst in topic_to_rows.items():
            topic_count += 1
            filtered = [r for r in lst if _safe_int(r.get("keyword_hits")) is not None and _safe_int(r.get("keyword_hits")) >= 1]

            def sort_key(r):
                title = (r.get("page_title") or "").strip()
                hits = _safe_int(r.get("keyword_hits")) or 0
                sec = _safe_int(r.get("section_count")) or 0
                words = _safe_int(r.get("word_count")) or 0
                return (
                    0 if _in_title(title, t) else 1,
                    -hits,
                    -sec,
                    -words,
                )

            expected = sorted(filtered, key=sort_key)
            order_ok = True
            for idx, r in enumerate(expected, start=1):
                r_rank = _safe_int(r.get("rank_within_topic"))
                if r_rank != idx:
                    order_ok = False
                    break
            if order_ok:
                topic_ranking_ok += 1
        if topic_count > 0:
            scores["ranking_correct_per_topic"] = topic_ranking_ok / topic_count

    # Search log checks
    logs = _load_jsonl(search_log)
    if logs is not None:
        total = len(logs)
        good = 0
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            timestamp = entry.get("timestamp")
            topic = entry.get("topic")
            domain = entry.get("domain")
            query_string = entry.get("query_string")
            num_results_considered = entry.get("num_results_considered")
            selected_urls = entry.get("selected_urls")
            if not timestamp or not topic or not domain or not query_string:
                continue
            if not isinstance(num_results_considered, int) or num_results_considered < 0:
                continue
            if not isinstance(selected_urls, list):
                continue
            sel_urls = [u for u in selected_urls if isinstance(u, str) and u.strip()]
            if len(sel_urls) != len(selected_urls):
                continue
            if num_results_considered < len(selected_urls):
                continue
            good += 1
        if total > 0:
            scores["search_log_present_and_format_valid"] = good / total
        else:
            scores["search_log_present_and_format_valid"] = 0.0

    # Search queries cover all (topic, domain) with "site:{domain} {topic}"
    if logs is not None and topics and domains:
        pairs = [(t, d) for t in topics for d in domains]
        ok = 0
        for (t, d) in pairs:
            found = False
            for entry in logs:
                q = (entry.get("query_string") or "")
                et = (entry.get("topic") or "")
                ed = (entry.get("domain") or "")
                if et == t and ed == d:
                    if f"site:{d}" in q and re.search(r"\b" + re.escape(t) + r"\b", q, flags=re.IGNORECASE):
                        found = True
                        break
            if found:
                ok += 1
        if pairs:
            scores["search_queries_cover_topic_domain_pairs"] = ok / len(pairs)

    # Selected URLs cover index.csv URLs and are within allowed domains
    if rows and logs is not None:
        all_selected = set()
        selected_allowed_count = 0
        total_selected = 0
        for entry in logs:
            sel = entry.get("selected_urls") or []
            for u in sel:
                if not isinstance(u, str):
                    continue
                u = u.strip()
                if not u:
                    continue
                total_selected += 1
                all_selected.add(u)
                if domains and _is_allowed_domain(u, domains):
                    selected_allowed_count += 1
        needed = set()
        for r in rows:
            u = (r.get("url") or "").strip()
            if u:
                needed.add(u)
        cover_hits = sum(1 for u in needed if u in all_selected)
        scores["selected_urls_cover_index_urls"] = (cover_hits / len(needed)) if needed else 0.0
        if total_selected > 0:
            scores["selected_urls_in_allowed_domains"] = selected_allowed_count / total_selected
        else:
            scores["selected_urls_in_allowed_domains"] = 0.0

    # Report checks
    report_text = _read_text(report_md) or ""
    if report_text:
        required_sections = [
            "Overview",
            "Sources and discovery",
            "Architecture summary",
            "Per-topic highlights",
            "Next steps",
        ]
        sec_hits = sum(1 for s in required_sections if re.search(re.escape(s), report_text, flags=re.IGNORECASE))
        scores["report_exists_and_includes_sections"] = 1.0 if sec_hits == len(required_sections) else (sec_hits / len(required_sections))

        # Mentions domains and query pattern
        if domains:
            domain_mentions = sum(1 for d in domains if re.search(re.escape(d), report_text, flags=re.IGNORECASE))
            has_site = "site:" in report_text
            if domain_mentions == len(domains) and has_site:
                scores["report_mentions_domains_and_site_pattern"] = 1.0
            else:
                denom = len(domains) + 1
                num = domain_mentions + (1 if has_site else 0)
                scores["report_mentions_domains_and_site_pattern"] = num / denom
        else:
            scores["report_mentions_domains_and_site_pattern"] = 0.0

        # Includes top-ranked page URLs per topic
        if rows and topics:
            top_urls = []
            for t in topics:
                topic_rows = [r for r in rows if (r.get("topic") or "").strip() == t]
                if not topic_rows:
                    continue
                top_row = None
                for r in topic_rows:
                    rr = _safe_int(r.get("rank_within_topic"))
                    if rr == 1:
                        top_row = r
                        break
                if top_row is None:
                    def sort_key(r):
                        title = (r.get("page_title") or "").strip()
                        hits = _safe_int(r.get("keyword_hits")) or 0
                        sec = _safe_int(r.get("section_count")) or 0
                        words = _safe_int(r.get("word_count")) or 0
                        return (0 if _in_title(title, t) else 1, -hits, -sec, -words)
                    top_row = sorted(topic_rows, key=sort_key)[0]
                top_urls.append((t, (top_row.get("url") or "").strip()))
            if top_urls:
                present = sum(1 for _, u in top_urls if u and u in report_text)
                scores["report_includes_top_page_urls"] = present / len(top_urls)

        # Report reflects total counts: total pages and total queries
        total_pages = len(rows) if rows else 0
        total_queries = len(logs) if logs is not None else 0
        counts_present = 0
        denom = 0
        if total_pages > 0:
            denom += 1
            counts_present += 1 if _contains_number(report_text, total_pages) else 0
        if total_queries > 0:
            denom += 1
            counts_present += 1 if _contains_number(report_text, total_queries) else 0
        if denom > 0:
            scores["report_reflects_total_counts"] = counts_present / denom
        else:
            scores["report_reflects_total_counts"] = 0.0

    # Final clamp
    for k in list(scores.keys()):
        v = scores.get(k, 0.0)
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()