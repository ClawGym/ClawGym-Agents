import json
import os
import re
import sys

def load_queries(input_dir):
    queries_path = os.path.join(input_dir, "queries.json")
    with open(queries_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("queries.json must be a JSON array")
    queries = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict) or "query" not in item or not isinstance(item["query"], str):
            raise ValueError(f"queries[{idx}] must be an object with a 'query' string")
        queries.append(item["query"])
    return queries

def read_nonempty_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    nonempty = [ln for ln in lines if ln.strip() != ""]
    return nonempty, lines

def parse_jsonl_with_schema(raw_lines, q_set):
    iso8601_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    schema_valid = True
    items_count_valid = True
    urls_unique_per_query = True
    iso8601_valid = True
    urls_valid_http = True
    # Track queries seen and per-query URLs
    per_query_urls = {}
    counts = {}
    jsonl_queries_set = set()

    for i, line in enumerate(raw_lines):
        try:
            obj = json.loads(line)
        except Exception:
            schema_valid = False
            continue
        if not isinstance(obj, dict):
            schema_valid = False
            continue
        # Required keys
        if "query" not in obj or "fetched_at" not in obj or "results" not in obj:
            schema_valid = False
            continue
        q = obj["query"]
        fetched_at = obj["fetched_at"]
        results = obj["results"]

        if not isinstance(q, str) or not isinstance(fetched_at, str) or not isinstance(results, list):
            schema_valid = False

        # Query must be in expected set
        if q not in q_set:
            schema_valid = False  # schema/validity relative to expected inputs
        else:
            jsonl_queries_set.add(q)
            counts[q] = counts.get(q, 0) + 1

        # Timestamp format
        if not iso8601_re.match(fetched_at or ""):
            iso8601_valid = False

        # Results constraints
        if not (isinstance(results, list) and 1 <= len(results) <= 5):
            items_count_valid = False

        # Validate items and URL uniqueness
        seen_urls = set()
        per_query_urls.setdefault(q, set())
        if isinstance(results, list):
            for it in results:
                if not isinstance(it, dict):
                    schema_valid = False
                    continue
                title = it.get("title", "")
                url = it.get("url", "")
                content = it.get("content", "")
                if not (isinstance(title, str) and title.strip() != ""):
                    schema_valid = False
                if not (isinstance(url, str) and url.strip() != ""):
                    schema_valid = False
                if not (isinstance(content, str) and content.strip() != ""):
                    schema_valid = False
                if isinstance(url, str):
                    if not (url.startswith("http://") or url.startswith("https://")):
                        urls_valid_http = False
                # uniqueness per query
                if isinstance(url, str):
                    if url in seen_urls:
                        urls_unique_per_query = False
                    seen_urls.add(url)
                    per_query_urls[q].add(url)

    # Ensure each query appears exactly once
    has_all_queries_once = (jsonl_queries_set == q_set) and all(counts.get(q, 0) == 1 for q in q_set)

    return {
        "schema_valid": schema_valid,
        "items_count_valid": items_count_valid,
        "urls_unique_per_query": urls_unique_per_query,
        "iso8601_valid": iso8601_valid,
        "urls_valid_http": urls_valid_http,
        "has_all_queries_once": has_all_queries_once,
        "jsonl_queries_set": jsonl_queries_set,
        "per_query_urls": per_query_urls,
    }

def extract_urls(text):
    # Extract http/https URLs; stop at whitespace or closing parenthesis
    url_re = re.compile(r"https?://[^\s)]+")
    return url_re.findall(text)

def parse_report(report_path, queries, per_query_raw_urls):
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.splitlines()

    # Checks
    has_methodology = any(line.strip() == "## Methodology" for line in lines)

    # Find all '## ' headers
    header_indices = []
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            header_indices.append((idx, line.strip()[3:].strip()))

    # Build map of section bounds for all headers
    section_bounds = []  # list of (title, start_idx, end_idx)
    for i, (idx, title) in enumerate(header_indices):
        start = idx
        end = len(lines)
        if i + 1 < len(header_indices):
            end = header_indices[i + 1][0]
        section_bounds.append((title, start, end))

    # Determine report query headers (all '## ' except 'Methodology')
    report_query_headers = [title for (title, s, e) in section_bounds if title != "Methodology"]

    # For each expected query, find section and validate bullets and sources
    q_set = set(queries)
    section_by_q = {}
    for title, start, end in section_bounds:
        if title in q_set:
            section_by_q[title] = (start, end)

    has_all_query_sections = all(q in section_by_q for q in queries)

    bullets_ok = True
    sources_subheader_ok = True
    sources_urls_count_ok = True
    sources_urls_from_raw_ok = True

    # Function to count bullets before "### Sources"
    for q in queries:
        if q not in section_by_q:
            bullets_ok = False
            sources_subheader_ok = False
            sources_urls_count_ok = False
            sources_urls_from_raw_ok = False
            continue
        start, end = section_by_q[q]
        # locate '### Sources' within section
        src_idx = None
        for i in range(start + 1, end):
            if lines[i].strip() == "### Sources":
                src_idx = i
                break
        if src_idx is None:
            sources_subheader_ok = False
            # Without sources, bullets check is still computable; but URLs checks will fail
        # Count bullet lines "- " between header and sources (or end if missing)
        bullet_range_end = src_idx if src_idx is not None else end
        bullet_count = 0
        for i in range(start + 1, bullet_range_end):
            if lines[i].startswith("- "):
                bullet_count += 1
        if bullet_count < 3:
            bullets_ok = False

        # Extract URLs under Sources
        if src_idx is not None:
            # Lines after src_idx until next '## ' (which is end of section)
            url_lines = lines[src_idx + 1:end]
            urls = []
            for ln in url_lines:
                urls.extend(extract_urls(ln))
            urls_distinct = list(dict.fromkeys(urls))  # preserve order, unique
            if len(urls_distinct) < 2:
                sources_urls_count_ok = False
            # URLs must be subset of raw results for this query
            raw_urls = per_query_raw_urls.get(q, set())
            # All listed sources must be present in raw results; at least 2 distinct required
            if not set(urls_distinct).issubset(raw_urls) or len(set(urls_distinct)) < 2:
                sources_urls_from_raw_ok = False
        else:
            sources_urls_count_ok = False
            sources_urls_from_raw_ok = False

    # Cross-consistency: report queries match exactly Q, and JSONL queries match Q will be checked elsewhere
    report_queries_match_q = set(report_query_headers) == q_set

    return {
        "has_methodology": has_methodology,
        "has_all_query_sections": has_all_query_sections,
        "bullets_ok": bullets_ok,
        "sources_subheader_ok": sources_subheader_ok,
        "sources_urls_count_ok": sources_urls_count_ok,
        "sources_urls_from_raw_ok": sources_urls_from_raw_ok,
        "report_queries_match_q": report_queries_match_q,
        "report_query_headers_set": set(report_query_headers),
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_raw_results_file": False,
        "has_report_file": False,
        "raw_results_lines_match_queries_count": False,
        "raw_results_schema_valid": False,
        "raw_results_items_count_valid": False,
        "raw_results_urls_unique_per_query": False,
        "raw_results_iso8601_utc": False,
        "raw_results_urls_http_valid": False,
        "raw_results_has_all_queries_once": False,
        "report_has_methodology": False,
        "report_has_all_query_sections": False,
        "report_bullets_per_query_ok": False,
        "report_sources_subheader_per_query": False,
        "report_sources_urls_count_per_query": False,
        "report_sources_urls_from_raw_results": False,
        "cross_set_consistency": False,
    }

    # Load expected queries
    try:
        queries = load_queries(input_dir)
        q_set = set(queries)
        N = len(queries)
    except Exception:
        # If input parsing fails, we cannot validate; keep defaults (False)
        queries = []
        q_set = set()
        N = 0

    raw_path = os.path.join(output_dir, "raw_results.jsonl")
    report_path = os.path.join(output_dir, "report.md")

    # Existence checks
    if os.path.isfile(raw_path):
        try:
            size = os.path.getsize(raw_path)
            if size > 0:
                checks["has_raw_results_file"] = True
        except Exception:
            pass

    if os.path.isfile(report_path):
        try:
            size_r = os.path.getsize(report_path)
            if size_r > 0:
                checks["has_report_file"] = True
        except Exception:
            pass

    # Proceed only if raw_results exists to compute its related checks
    per_query_raw_urls = {}
    jsonl_queries_set = set()
    if checks["has_raw_results_file"] and N > 0:
        try:
            nonempty_lines, all_lines = read_nonempty_lines(raw_path)
            # Must have exactly N non-empty lines
            if len(nonempty_lines) == N:
                checks["raw_results_lines_match_queries_count"] = True

            parsed = parse_jsonl_with_schema(nonempty_lines, q_set)
            checks["raw_results_schema_valid"] = parsed["schema_valid"]
            checks["raw_results_items_count_valid"] = parsed["items_count_valid"]
            checks["raw_results_urls_unique_per_query"] = parsed["urls_unique_per_query"]
            checks["raw_results_iso8601_utc"] = parsed["iso8601_valid"]
            checks["raw_results_urls_http_valid"] = parsed["urls_valid_http"]
            checks["raw_results_has_all_queries_once"] = parsed["has_all_queries_once"]
            per_query_raw_urls = parsed["per_query_urls"]
            jsonl_queries_set = parsed["jsonl_queries_set"]
        except Exception:
            # Keep defaults as False on failure
            pass

    # Parse report and validate cross-references
    if checks["has_report_file"] and N > 0:
        try:
            report_info = parse_report(report_path, queries, per_query_raw_urls)
            checks["report_has_methodology"] = report_info["has_methodology"]
            checks["report_has_all_query_sections"] = report_info["has_all_query_sections"]
            checks["report_bullets_per_query_ok"] = report_info["bullets_ok"]
            checks["report_sources_subheader_per_query"] = report_info["sources_subheader_ok"]
            checks["report_sources_urls_count_per_query"] = report_info["sources_urls_count_ok"]
            checks["report_sources_urls_from_raw_results"] = report_info["sources_urls_from_raw_ok"]
            # Cross-consistency: report queries set equals Q and JSONL queries set equals Q
            checks["cross_set_consistency"] = (
                report_info["report_queries_match_q"] and (jsonl_queries_set == set(queries))
            )
        except Exception:
            # Keep defaults as False
            pass

    # Compute reward: if either output missing, reward is 0.0
    reward_checks = [
        "has_raw_results_file",
        "has_report_file",
        "raw_results_lines_match_queries_count",
        "raw_results_schema_valid",
        "raw_results_items_count_valid",
        "raw_results_urls_unique_per_query",
        "raw_results_iso8601_utc",
        "raw_results_urls_http_valid",
        "raw_results_has_all_queries_once",
        "report_has_methodology",
        "report_has_all_query_sections",
        "report_bullets_per_query_ok",
        "report_sources_subheader_per_query",
        "report_sources_urls_count_per_query",
        "report_sources_urls_from_raw_results",
        "cross_set_consistency",
    ]

    if not (checks["has_raw_results_file"] and checks["has_report_file"]):
        reward = 0.0
    else:
        passed = sum(1 for k in reward_checks if checks.get(k, False))
        total = len(reward_checks)
        reward = passed / total if total > 0 else 0.0

    # Print JSON result
    result = {"reward": reward}
    # Preserve insertion order: add checks after reward
    for k in reward_checks:
        result[k] = checks[k]
    print(json.dumps(result))

if __name__ == "__main__":
    main()