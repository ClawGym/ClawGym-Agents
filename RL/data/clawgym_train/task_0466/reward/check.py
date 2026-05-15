import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import ast


def _read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if "T" not in s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _parse_yaml_config(path: Path):
    """
    Very small YAML parser for the provided simple config structure.
    Supports:
      key:
        - 'value'
      key: 'value'
      key: number
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    cfg = {}
    current_key = None
    is_list_context = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" in line:
            # New key
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            current_key = key
            if val == "":
                # Expect list or nested block
                cfg[current_key] = []
                is_list_context = True
            else:
                # Scalar
                is_list_context = False
                # Strip quotes if present
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                elif val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                # Try int
                if re.fullmatch(r"-?\d+", val):
                    try:
                        cfg[current_key] = int(val)
                    except Exception:
                        cfg[current_key] = val
                else:
                    cfg[current_key] = val
        else:
            # Possibly list item
            if is_list_context and current_key is not None:
                m = re.match(r"\s*-\s+(.*)$", line)
                if m:
                    item = m.group(1).strip()
                    if item.startswith("'") and item.endswith("'"):
                        item = item[1:-1]
                    elif item.startswith('"') and item.endswith('"'):
                        item = item[1:-1]
                    cfg[current_key].append(item)
    return cfg


def _load_watchlist_names(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            names = []
            for row in rdr:
                if "name" in row and row["name"]:
                    names.append(row["name"].strip())
            return names
    except Exception:
        return None


def _load_history_urls(path: Path):
    urls = set()
    text = _read_text_safe(path)
    if text is None:
        return None
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            url = obj.get("url")
            if isinstance(url, str):
                urls.add(url.strip().lower())
        except Exception:
            return None
    return urls


def _load_canonical_domains(path: Path):
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "canonical_domains":
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            # Normalize keys and values to lowercase strings
                            canon = {}
                            for k, v in value.items():
                                if isinstance(k, str) and isinstance(v, str):
                                    canon[k.lower()] = v.lower()
                            return canon
        return None
    except Exception:
        return None


def _parse_jsonl(path: Path):
    text = _read_text_safe(path)
    if text is None:
        return None
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            items.append(obj)
        except Exception:
            return None
    return items


def _extract_host(url: str):
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host is None:
            return None
        return host.lower()
    except Exception:
        return None


def _parse_trend_summary_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            header = rdr.fieldnames
            if header is None:
                return None, None
            rows = []
            for row in rdr:
                rows.append(row)
            return header, rows
    except Exception:
        return None, None


def _compute_expected_queries(cfg: dict, names: list):
    # cfg has keys: queries (list of templates), general_keywords (list)
    queries = set()
    watchlist_queries = set()
    general_queries = set()
    for name in names:
        for tmpl in cfg.get("queries", []):
            q = tmpl.replace("{NAME}", name)
            watchlist_queries.add(q)
            queries.add(q)
    for q in cfg.get("general_keywords", []):
        general_queries.add(q)
        queries.add(q)
    return queries, watchlist_queries, general_queries


def _find_line_with_keywords_and_number(text: str, keywords: list):
    for line in text.splitlines():
        lower = line.lower()
        if all(k in lower for k in keywords):
            m = re.search(r"\d+", line)
            if m:
                return True
    return False


def _line_contains_term_and_count(text: str, term: str, count: int):
    pattern = re.compile(rf"(^|[^0-9]){re.escape(str(count))}([^0-9]|$)")
    for line in text.splitlines():
        if term in line and pattern.search(line):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "queries_log_present_and_format": 0.0,
        "queries_log_contains_all_expected_queries": 0.0,
        "new_results_schema_and_fields": 0.0,
        "domain_and_canonicalization_correct": 0.0,
        "disallowed_domains_filtered": 0.0,
        "history_dedup_applied": 0.0,
        "new_results_query_watchlist_consistency": 0.0,
        "trend_summary_header_correct": 0.0,
        "trend_summary_term_coverage": 0.0,
        "trend_summary_metrics_correct": 0.0,
        "brief_md_before_filtering_includes_number": 0.0,
        "brief_md_reports_new_links_count": 0.0,
        "brief_md_top3_watchlist_includes_counts": 0.0,
        "brief_md_top3_domain_groups_includes_counts": 0.0,
    }

    # Load config
    cfg_path = workspace / "input" / "config.yaml"
    cfg = _parse_yaml_config(cfg_path)
    if not isinstance(cfg, dict):
        # Without config, many checks cannot proceed
        return scores

    output_dir = cfg.get("output_dir", "output")
    out_dir_path = workspace / output_dir

    # Load expected inputs
    names = _load_watchlist_names(workspace / "data" / "watchlist.csv")
    history_urls = _load_history_urls(workspace / "data" / "history.jsonl")
    canonical_domains = _load_canonical_domains(workspace / "scripts" / "analyzer.py")

    if not isinstance(names, list):
        names = []
    if not isinstance(history_urls, set):
        history_urls = None  # Signal missing
    if not isinstance(canonical_domains, dict):
        canonical_domains = None  # Signal missing

    expected_all_queries, expected_watchlist_queries, expected_general_queries = _compute_expected_queries(cfg, names)

    # Check queries.log
    queries_log_path = out_dir_path / "queries.log"
    queries_log_text = _read_text_safe(queries_log_path)
    if queries_log_text is not None:
        lines = [ln for ln in queries_log_text.splitlines() if ln.strip()]
        if len(lines) > 0:
            all_valid = True
            logged_queries = []
            for ln in lines:
                if "\t" not in ln:
                    all_valid = False
                    break
                ts, q = ln.split("\t", 1)
                if not _is_iso8601(ts.strip()):
                    all_valid = False
                    break
                if not q.strip():
                    all_valid = False
                    break
                logged_queries.append(q.strip())
            if all_valid:
                scores["queries_log_present_and_format"] = 1.0
            # Check all expected queries appear at least once
            if expected_all_queries:
                all_present = all(q in logged_queries for q in expected_all_queries)
                if all_present:
                    scores["queries_log_contains_all_expected_queries"] = 1.0
        else:
            # Empty file
            scores["queries_log_present_and_format"] = 0.0
            scores["queries_log_contains_all_expected_queries"] = 0.0

    # Load new_results.jsonl
    new_results_path = out_dir_path / "new_results.jsonl"
    results = _parse_jsonl(new_results_path)  # None on error
    schema_ok = False
    canonical_ok = False
    disallowed_ok = False
    dedup_ok = False
    query_watchlist_ok = False

    if results is not None:
        # Schema validation
        required_keys = {"query", "watchlist_term", "title", "url", "domain", "domain_group", "fetched_at"}
        schema_ok = True
        canonical_ok = True if canonical_domains is not None else False
        disallowed_ok = True
        dedup_ok = True if history_urls is not None else False
        query_watchlist_ok = True
        for obj in results:
            if not isinstance(obj, dict):
                schema_ok = False
                break
            if set(obj.keys()).issuperset(required_keys) is False:
                schema_ok = False
                break
            # Types and ISO
            if not isinstance(obj.get("query"), str):
                schema_ok = False
                break
            if obj.get("watchlist_term") is not None and not isinstance(obj.get("watchlist_term"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("title"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("url"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("domain"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("domain_group"), str):
                schema_ok = False
                break
            if not isinstance(obj.get("fetched_at"), str) or not _is_iso8601(obj.get("fetched_at")):
                schema_ok = False
                break

            # Query must be one of expected queries
            if expected_all_queries and obj["query"] not in expected_all_queries:
                query_watchlist_ok = False

            # Domain must equal URL hostname (case-insensitive)
            host = _extract_host(obj["url"])
            if host is None or host.lower() != obj["domain"].strip().lower():
                canonical_ok = False  # Using canonical_ok to capture domain mismatch as well
            # Canonicalization check
            if canonical_domains is not None and host is not None:
                expected_group = canonical_domains.get(host.lower(), host.lower())
                if obj["domain_group"].strip().lower() != expected_group:
                    canonical_ok = False

            # Disallowed filter
            disallowed = set([d.lower() for d in cfg.get("disallowed_domains", [])])
            if isinstance(obj.get("domain_group"), str) and obj["domain_group"].strip().lower() in disallowed:
                disallowed_ok = False

            # Dedup filter
            if history_urls is not None and isinstance(obj.get("url"), str):
                if obj["url"].strip().lower() in history_urls:
                    dedup_ok = False

            # watchlist_term consistency
            if obj["query"] in expected_general_queries:
                if obj.get("watchlist_term") is not None:
                    query_watchlist_ok = False
            else:
                # Must be a watchlist query; find which name is in the template instance
                wt = obj.get("watchlist_term")
                if wt is None or wt not in names or wt not in obj["query"]:
                    query_watchlist_ok = False

        # Schema result
        scores["new_results_schema_and_fields"] = 1.0 if schema_ok else 0.0
        # Domain and canonicalization
        if canonical_domains is not None and schema_ok:
            scores["domain_and_canonicalization_correct"] = 1.0 if canonical_ok else 0.0
        else:
            scores["domain_and_canonicalization_correct"] = 0.0
        # Disallowed filter
        scores["disallowed_domains_filtered"] = 1.0 if disallowed_ok and schema_ok else 0.0
        # Dedup filter
        scores["history_dedup_applied"] = 1.0 if dedup_ok and schema_ok else 0.0
        # Query/watchlist_term consistency
        scores["new_results_query_watchlist_consistency"] = 1.0 if query_watchlist_ok and schema_ok else 0.0

    # trend_summary.csv checks
    trend_summary_path = out_dir_path / "trend_summary.csv"
    header, rows = _parse_trend_summary_csv(trend_summary_path)
    header_ok = False
    coverage_ok = False
    metrics_ok = False
    if header is not None and rows is not None:
        expected_header = ["term_type", "term", "new_links", "unique_domains", "top_domain_group", "top_domain_new_links"]
        if header == expected_header:
            header_ok = True

        # Coverage: one row for each name (term_type=watchlist) and each general keyword (term_type=keyword)
        names_set = set(names)
        keywords_set = set(cfg.get("general_keywords", []))
        found_watchlist_terms = set()
        found_keyword_terms = set()
        # Prepare a lookup of rows
        row_lookup = {}
        for r in rows:
            # basic field checks
            if "term_type" not in r or "term" not in r:
                continue
            ttype = r["term_type"].strip()
            term = r["term"].strip()
            row_lookup[(ttype, term)] = r
            if ttype == "watchlist" and term in names_set:
                found_watchlist_terms.add(term)
            if ttype == "keyword" and term in keywords_set:
                found_keyword_terms.add(term)

        if found_watchlist_terms == names_set and found_keyword_terms == keywords_set:
            coverage_ok = True

        # Metrics correctness: recompute from new_results.jsonl
        metrics_ok = False
        if results is not None and header_ok and coverage_ok:
            # Build aggregations
            # For each name: items where watchlist_term == name
            # For each keyword: items where watchlist_term is None and query == keyword
            # Compute counts by domain_group
            # Validate: new_links, unique_domains, top_domain_group, top_domain_new_links
            def compute_for_items(items):
                total = len(items)
                groups = {}
                for it in items:
                    dg = it.get("domain_group")
                    groups[dg] = groups.get(dg, 0) + 1
                unique = len(groups)
                top_group = None
                top_count = 0
                for g, c in groups.items():
                    if c > top_count:
                        top_group = g
                        top_count = c
                return total, unique, top_group, top_count

            all_ok = True
            # Check each name
            for name in names:
                items = [it for it in results if it.get("watchlist_term") == name]
                total, unique, top_group, top_count = compute_for_items(items)
                r = row_lookup.get(("watchlist", name))
                try:
                    nl = int(r["new_links"])
                    ud = int(r["unique_domains"])
                    tdn = int(r["top_domain_new_links"])
                    tdg = r["top_domain_group"]
                except Exception:
                    all_ok = False
                    break
                if nl != total or ud != unique:
                    all_ok = False
                    break
                if total == 0:
                    if tdn != 0:
                        all_ok = False
                        break
                else:
                    groups = {}
                    for it in items:
                        dg = it.get("domain_group")
                        groups[dg] = groups.get(dg, 0) + 1
                    maxc = max(groups.values()) if groups else 0
                    candidate_groups = {g for g, c in groups.items() if c == maxc}
                    if tdn != maxc or tdg not in candidate_groups:
                        all_ok = False
                        break

            # Check each keyword
            for kw in cfg.get("general_keywords", []):
                items = [it for it in results if it.get("watchlist_term") is None and it.get("query") == kw]
                total, unique, top_group, top_count = compute_for_items(items)
                r = row_lookup.get(("keyword", kw))
                try:
                    nl = int(r["new_links"])
                    ud = int(r["unique_domains"])
                    tdn = int(r["top_domain_new_links"])
                    tdg = r["top_domain_group"]
                except Exception:
                    all_ok = False
                    break
                if nl != total or ud != unique:
                    all_ok = False
                    break
                if total == 0:
                    if tdn != 0:
                        all_ok = False
                        break
                else:
                    groups = {}
                    for it in items:
                        dg = it.get("domain_group")
                        groups[dg] = groups.get(dg, 0) + 1
                    maxc = max(groups.values()) if groups else 0
                    candidate_groups = {g for g, c in groups.items() if c == maxc}
                    if tdn != maxc or tdg not in candidate_groups:
                        all_ok = False
                        break
            metrics_ok = all_ok

    scores["trend_summary_header_correct"] = 1.0 if header_ok else 0.0
    scores["trend_summary_term_coverage"] = 1.0 if coverage_ok else 0.0
    scores["trend_summary_metrics_correct"] = 1.0 if metrics_ok else 0.0

    # brief.md checks
    brief_path = out_dir_path / "brief.md"
    brief_text = _read_text_safe(brief_path)
    if brief_text is not None:
        # before filtering number present
        if _find_line_with_keywords_and_number(brief_text, ["before", "filter"]):
            scores["brief_md_before_filtering_includes_number"] = 1.0

        # new links after filtering count matches number of results
        if results is not None:
            total_new_links = len(results)
            # look for a line with "new" and "link" and the number
            found_new_links_line = False
            for line in brief_text.splitlines():
                lower = line.lower()
                if "new" in lower and "link" in lower:
                    if re.search(rf"(^|[^0-9]){re.escape(str(total_new_links))}([^0-9]|$)", line):
                        found_new_links_line = True
                        break
                if "after" in lower and "filter" in lower:
                    if re.search(rf"(^|[^0-9]){re.escape(str(total_new_links))}([^0-9]|$)", line):
                        found_new_links_line = True
                        break
            if found_new_links_line:
                scores["brief_md_reports_new_links_count"] = 1.0

        # top 3 watchlist terms by new link count with counts
        if results is not None and names:
            counts = {name: 0 for name in names}
            for it in results:
                wt = it.get("watchlist_term")
                if wt in counts:
                    counts[wt] += 1
            # sort by count desc, then name asc
            sorted_terms = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            top3 = sorted_terms[:3]
            ok = True
            for term, cnt in top3:
                if cnt < 0:
                    continue
                if not _line_contains_term_and_count(brief_text, term, cnt):
                    ok = False
                    break
            if ok:
                scores["brief_md_top3_watchlist_includes_counts"] = 1.0

        # top 3 domain_groups by new link count across all terms
        if results is not None:
            dg_counts = {}
            for it in results:
                dg = it.get("domain_group")
                if isinstance(dg, str):
                    dg_counts[dg] = dg_counts.get(dg, 0) + 1
            sorted_dg = sorted(dg_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            top3dg = sorted_dg[:3]
            okdg = True
            for dg, cnt in top3dg:
                if not _line_contains_term_and_count(brief_text, dg, cnt):
                    okdg = False
                    break
            if okdg and top3dg:
                scores["brief_md_top3_domain_groups_includes_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()