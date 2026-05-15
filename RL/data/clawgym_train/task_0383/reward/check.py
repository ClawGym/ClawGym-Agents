import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
            return rows, headers, None
    except Exception as e:
        return None, None, str(e)


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    val = s.strip()
    # Accept ISO 8601 with optional 'Z'
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def _extract_host(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # handle cases where scheme is missing but something is present in path
        if not host and parsed.path:
            # attempt parse with 'http://' prefix
            parsed2 = urlparse("http://" + url)
            host = parsed2.netloc.lower()
        # strip port if present
        if ":" in host:
            host = host.split(":", 1)[0]
        host = host.strip()
        if not host:
            return None
        return host
    except Exception:
        return None


def _normalize_domain_for_compare(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _domain_matches(given: str, from_url: str) -> bool:
    g = _normalize_domain_for_compare(given)
    u = _normalize_domain_for_compare(from_url)
    if not g or not u:
        return False
    if g == u:
        return True
    # Allow one to be a subdomain of the other
    return g.endswith("." + u) or u.endswith("." + g)


def _classify_domain_category(host: str) -> str:
    h = (host or "").lower()
    if h.endswith(".gov") or h == "gov":
        return "gov"
    if h.endswith(".edu") or h == "edu":
        return "edu"
    if h.endswith(".int") or h == "int":
        return "int"
    if h.endswith(".org") or h == "org":
        return "org"
    return "other"


def _parse_search_log_counts(log_text: str, queries: List[str]) -> Dict[str, Optional[int]]:
    # For each query, attempt to find a line containing the query and an integer count on same or adjacent lines
    lines = log_text.splitlines()
    results: Dict[str, Optional[int]] = {}
    for q in queries:
        found_count: Optional[int] = None
        for idx, line in enumerate(lines):
            if q in line:
                # find integers in this line
                nums = re.findall(r"\b(\d+)\b", line)
                if nums:
                    found_count = int(nums[-1])
                    break
                # check next and previous lines for a numeric capture
                if idx + 1 < len(lines):
                    nums2 = re.findall(r"\b(\d+)\b", lines[idx + 1])
                    if nums2:
                        found_count = int(nums2[-1])
                        break
                if idx - 1 >= 0:
                    nums3 = re.findall(r"\b(\d+)\b", lines[idx - 1])
                    if nums3:
                        found_count = int(nums3[-1])
                        break
        results[q] = found_count
    return results


def _find_any_engine_name(log_text: str) -> bool:
    engines = ["DuckDuckGo", "Bing", "Google", "Brave", "Yahoo", "Ecosia"]
    for e in engines:
        if e.lower() in log_text.lower():
            return True
    return False


def _contains_direct_links(log_text: str) -> bool:
    return ("http://" in log_text.lower()) or ("https://" in log_text.lower())


def _parse_status_summary_counts(summary_text: str) -> Dict[str, Optional[int]]:
    counts: Dict[str, Optional[int]] = {"2xx": None, "3xx": None, "4xx": None, "5xx": None}
    for cls in ["2xx", "3xx", "4xx", "5xx"]:
        # find '2xx' followed by any non-digit then digits
        m = re.search(rf"{cls}\D+(\d+)", summary_text, flags=re.IGNORECASE)
        if m:
            counts[cls] = int(m.group(1))
    return counts


def _get_section(text: str, heading: str) -> Optional[str]:
    # heading like '## Citations'
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = i + 1
            break
    if start is None:
        return None
    # find next heading
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _count_hashtags_in_text(text: str, allowed: List[str]) -> int:
    present = set()
    for tag in allowed:
        if tag in text:
            present.add(tag)
    return len(present)


def _sentence_count(text: str) -> int:
    # Count number of non-empty sentence-like segments split by . ! ?
    parts = re.split(r"[.!?]+", text)
    non_empty = [p.strip() for p in parts if p.strip()]
    return len(non_empty)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "search_results_file_exists": 0.0,
        "search_results_columns_valid": 0.0,
        "search_results_rows_valid": 0.0,
        "queries_subset_valid": 0.0,
        "queries_coverage": 0.0,
        "per_query_max_5": 0.0,
        "search_log_exists": 0.0,
        "search_log_queries_and_counts": 0.0,
        "search_log_engine_and_no_links": 0.0,
        "link_status_json_exists": 0.0,
        "link_status_json_valid": 0.0,
        "link_status_coverage": 0.0,
        "link_status_summary_consistency": 0.0,
        "curated_sources_exists": 0.0,
        "curated_sources_count_and_fields": 0.0,
        "curated_sources_in_results_and_ok": 0.0,
        "curated_domain_and_category_correct": 0.0,
        "awareness_thread_exists": 0.0,
        "awareness_headings_exact_once": 0.0,
        "awareness_citations_match_curated": 0.0,
        "awareness_hashtags_from_input": 0.0,
    }

    # Load inputs
    input_queries_path = workspace / "input" / "queries.json"
    input_hashtags_path = workspace / "input" / "hashtags.csv"
    queries_data, qerr = _load_json(input_queries_path)
    hashtags_rows, hashtags_headers, herr = _load_csv(input_hashtags_path)
    input_queries: List[str] = queries_data if isinstance(queries_data, list) else []
    input_hashtags: List[str] = []
    if hashtags_rows and hashtags_headers and "hashtag" in hashtags_headers:
        input_hashtags = [row.get("hashtag", "") for row in hashtags_rows if row.get("hashtag", "")]
    # Expected outputs
    search_results_path = workspace / "output" / "search_results.csv"
    search_log_path = workspace / "output" / "search_log.txt"
    link_status_json_path = workspace / "output" / "link_status.json"
    link_status_summary_path = workspace / "output" / "link_status_summary.txt"
    curated_sources_path = workspace / "output" / "curated_sources.json"
    awareness_thread_path = workspace / "output" / "awareness_thread.md"

    # 1) search_results.csv checks
    sr_rows: List[Dict[str, str]] = []
    sr_headers: List[str] = []
    if search_results_path.exists():
        scores["search_results_file_exists"] = 1.0
        rows, headers, err = _load_csv(search_results_path)
        if rows is not None and headers is not None and err is None:
            sr_rows = rows
            sr_headers = headers
            required_cols = [
                "query",
                "result_rank",
                "title",
                "url",
                "domain",
                "domain_category",
                "retrieved_at",
            ]
            if all(col in sr_headers for col in required_cols):
                scores["search_results_columns_valid"] = 1.0

            # Validate rows content
            all_valid = True
            for r in sr_rows:
                q = r.get("query", "")
                if not isinstance(q, str) or not q:
                    all_valid = False
                    break
                # rank
                try:
                    rk = int(str(r.get("result_rank", "")).strip())
                except Exception:
                    all_valid = False
                    break
                if rk < 1:
                    all_valid = False
                    break
                title = r.get("title", "")
                if not isinstance(title, str) or not title.strip():
                    all_valid = False
                    break
                url = r.get("url", "")
                if not isinstance(url, str) or not url.strip():
                    all_valid = False
                    break
                host = _extract_host(url)
                if not host:
                    all_valid = False
                    break
                domain = r.get("domain", "")
                if not _domain_matches(domain, host):
                    all_valid = False
                    break
                cat = r.get("domain_category", "")
                expected_cat = _classify_domain_category(host)
                if cat != expected_cat:
                    all_valid = False
                    break
                retrieved_at = r.get("retrieved_at", "")
                if not _is_iso8601(retrieved_at):
                    all_valid = False
                    break
            if all_valid and required_cols and sr_rows:
                scores["search_results_rows_valid"] = 1.0

            # queries subset
            subset_ok = True
            for r in sr_rows:
                if r.get("query") not in input_queries:
                    subset_ok = False
                    break
            if subset_ok and input_queries:
                scores["queries_subset_valid"] = 1.0

            # coverage: each input query appears at least once
            if input_queries:
                q_counts = {q: 0 for q in input_queries}
                for r in sr_rows:
                    if r.get("query") in q_counts:
                        q_counts[r.get("query")] += 1
                if all(q_counts[q] > 0 for q in input_queries):
                    scores["queries_coverage"] = 1.0

                # per query max 5
                if all(q_counts[q] <= 5 for q in input_queries):
                    scores["per_query_max_5"] = 1.0
        else:
            # Cannot parse CSV -> keep scores as 0 for structured checks
            pass

    # 2) search_log.txt checks
    log_text = _read_text(search_log_path) if search_log_path.exists() else None
    if log_text is not None:
        scores["search_log_exists"] = 1.0
        # queries and counts consistency
        counts_match = True
        if sr_rows and input_queries:
            expected_counts = {q: 0 for q in input_queries}
            for r in sr_rows:
                q = r.get("query", "")
                if q in expected_counts:
                    expected_counts[q] += 1
            found_counts = _parse_search_log_counts(log_text, input_queries)
            # also ensure presence of at least one ISO timestamp in the log
            has_any_iso = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", log_text))
            for q in input_queries:
                if found_counts.get(q) != expected_counts.get(q):
                    counts_match = False
                    break
            if counts_match and has_any_iso:
                scores["search_log_queries_and_counts"] = 1.0
        # engine listed and no direct links
        engine_ok = _find_any_engine_name(log_text)
        no_links = not _contains_direct_links(log_text)
        if engine_ok and no_links:
            scores["search_log_engine_and_no_links"] = 1.0

    # 3) link_status.json and summary
    link_status_list: List[Dict[str, Any]] = []
    summary_text = _read_text(link_status_summary_path) if link_status_summary_path.exists() else None
    if link_status_json_path.exists():
        scores["link_status_json_exists"] = 1.0
        data, err = _load_json(link_status_json_path)
        if isinstance(data, list) and err is None:
            link_status_list = data
            # validate structure and values
            valid_struct = True
            for item in link_status_list:
                if not isinstance(item, dict):
                    valid_struct = False
                    break
                url = item.get("url")
                status = item.get("status")
                status_code = item.get("status_code")
                error_message = item.get("error_message") if "error_message" in item else None
                checked_at = item.get("checked_at")
                if not isinstance(url, str) or not url.strip():
                    valid_struct = False
                    break
                if status not in ("ok", "error"):
                    valid_struct = False
                    break
                if status_code is not None and not isinstance(status_code, int):
                    valid_struct = False
                    break
                if error_message is not None and not isinstance(error_message, str):
                    valid_struct = False
                    break
                if not isinstance(checked_at, str) or not _is_iso8601(checked_at):
                    valid_struct = False
                    break
                # status consistency
                if status == "ok":
                    if not isinstance(status_code, int) or not (200 <= status_code <= 299):
                        valid_struct = False
                        break
                else:
                    # error: code is None or not 2xx
                    if status_code is not None and 200 <= status_code <= 299:
                        valid_struct = False
                        break
            if valid_struct:
                scores["link_status_json_valid"] = 1.0

            # coverage: all URLs in search_results.csv should be present
            if sr_rows:
                sr_urls = sorted(set([r.get("url", "") for r in sr_rows if r.get("url", "")]))
                ls_urls = sorted(set([it.get("url", "") for it in link_status_list if isinstance(it, dict) and it.get("url", "")]))
                coverage_ok = all(u in ls_urls for u in sr_urls)
                if coverage_ok:
                    scores["link_status_coverage"] = 1.0

            # summary consistency
            if summary_text is not None and link_status_list:
                # compute counts by status class
                cls_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
                error_items: List[Dict[str, Any]] = []
                for it in link_status_list:
                    code = it.get("status_code")
                    status = it.get("status")
                    if isinstance(code, int):
                        if 200 <= code <= 299:
                            cls_counts["2xx"] += 1
                        elif 300 <= code <= 399:
                            cls_counts["3xx"] += 1
                        elif 400 <= code <= 499:
                            cls_counts["4xx"] += 1
                        elif 500 <= code <= 599:
                            cls_counts["5xx"] += 1
                    if status == "error":
                        error_items.append(it)
                parsed_counts = _parse_status_summary_counts(summary_text)
                counts_match = all(parsed_counts.get(k) == cls_counts.get(k) for k in ["2xx", "3xx", "4xx", "5xx"])
                # check that errors are listed with messages
                errors_listed = True
                for it in error_items:
                    u = it.get("url", "")
                    emsg = it.get("error_message")
                    if u not in summary_text:
                        errors_listed = False
                        break
                    if emsg and (emsg not in summary_text):
                        errors_listed = False
                        break
                if counts_match and errors_listed:
                    scores["link_status_summary_consistency"] = 1.0

    # 4) curated_sources.json
    curated_list: List[Dict[str, Any]] = []
    if curated_sources_path.exists():
        scores["curated_sources_exists"] = 1.0
        cdata, cerr = _load_json(curated_sources_path)
        if isinstance(cdata, list) and cerr is None:
            curated_list = cdata
            # count and fields
            fields_ok = True
            count_ok = 3 <= len(curated_list) <= 5
            for it in curated_list:
                if not isinstance(it, dict):
                    fields_ok = False
                    break
                for key in ["title", "url", "domain", "domain_category", "derived_from_query", "why_relevant"]:
                    if key not in it:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                # type/basic validation
                if not isinstance(it.get("title"), str) or not it.get("title").strip():
                    fields_ok = False
                    break
                if not isinstance(it.get("url"), str) or not it.get("url").strip():
                    fields_ok = False
                    break
                if not isinstance(it.get("domain"), str) or not it.get("domain").strip():
                    fields_ok = False
                    break
                if not isinstance(it.get("domain_category"), str) or it.get("domain_category") not in {"gov", "edu", "int", "org"}:
                    fields_ok = False
                    break
                if it.get("derived_from_query") not in input_queries:
                    fields_ok = False
                    break
                why = it.get("why_relevant")
                if not isinstance(why, str) or not why.strip():
                    fields_ok = False
                    break
                sc = _sentence_count(why)
                if sc < 1 or sc > 2:
                    fields_ok = False
                    break
            if fields_ok and count_ok:
                scores["curated_sources_count_and_fields"] = 1.0

            # in results and ok status
            in_results_ok = True
            if sr_rows and link_status_list and curated_list:
                sr_by_url = {r.get("url"): r for r in sr_rows if r.get("url")}
                ls_by_url = {}
                for it in link_status_list:
                    if isinstance(it, dict) and isinstance(it.get("url"), str):
                        ls_by_url[it["url"]] = it
                for it in curated_list:
                    url = it.get("url")
                    if url not in sr_by_url:
                        in_results_ok = False
                        break
                    st = ls_by_url.get(url)
                    if not st or st.get("status") != "ok" or not isinstance(st.get("status_code"), int) or not (200 <= st.get("status_code") <= 299):
                        in_results_ok = False
                        break
                if in_results_ok:
                    scores["curated_sources_in_results_and_ok"] = 1.0
            elif curated_list:
                in_results_ok = False

            # domain and category correctness and consistency
            domain_cat_ok = True
            if curated_list:
                for it in curated_list:
                    url = it.get("url", "")
                    host = _extract_host(url)
                    if not host:
                        domain_cat_ok = False
                        break
                    if not _domain_matches(it.get("domain", ""), host):
                        domain_cat_ok = False
                        break
                    expected_cat = _classify_domain_category(host)
                    if it.get("domain_category") != expected_cat:
                        domain_cat_ok = False
                        break
                    # also check consistency with search_results row if available
                    if sr_rows:
                        sr_match = [r for r in sr_rows if r.get("url") == url]
                        if sr_match:
                            if not _domain_matches(sr_match[0].get("domain", ""), it.get("domain", "")):
                                domain_cat_ok = False
                                break
                            if sr_match[0].get("domain_category") != it.get("domain_category"):
                                domain_cat_ok = False
                                break
                if domain_cat_ok:
                    scores["curated_domain_and_category_correct"] = 1.0

    # 5) awareness_thread.md
    thread_text = _read_text(awareness_thread_path) if awareness_thread_path.exists() else None
    if thread_text is not None:
        scores["awareness_thread_exists"] = 1.0
        # headings exactly once each as H2
        required_headings = ["Hook", "Key facts", "Treatments in development", "Call to action", "Citations"]
        heading_counts = {h: 0 for h in required_headings}
        for line in thread_text.splitlines():
            m = re.match(r"^\s*##\s+(.*)\s*$", line)
            if m:
                title = m.group(1).strip()
                if title in heading_counts:
                    heading_counts[title] += 1
        if all(heading_counts[h] == 1 for h in required_headings):
            scores["awareness_headings_exact_once"] = 1.0

        # citations match curated
        if curated_list:
            citations_section = _get_section(thread_text, "Citations")
            if citations_section is not None:
                all_present = True
                for it in curated_list:
                    title = it.get("title", "")
                    url = it.get("url", "")
                    if title not in citations_section or url not in citations_section:
                        all_present = False
                        break
                if all_present:
                    scores["awareness_citations_match_curated"] = 1.0

        # hashtags from input (at least 3)
        if input_hashtags:
            ht_count = _count_hashtags_in_text(thread_text, input_hashtags)
            if ht_count >= 3:
                scores["awareness_hashtags_from_input"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()