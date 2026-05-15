import json
import os
import re
import sys
from urllib.parse import urlparse
from datetime import datetime

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # Allow formats like 2026-01-26T12:34:56, with optional .sss and Z or timezone offset
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?"
        r"(?:Z|[+\-]\d{2}:\d{2})?$"
    )
    if pattern.match(s):
        return True
    # Fallback: try fromisoformat (accepts offsets but not Z)
    try:
        # Replace Z with +00:00 for fromisoformat
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False

def slugify(s: str) -> str:
    s = (s or "").lower()
    s = s.replace(" ", "-")
    # Remove all characters not in [a-z0-9-]
    s = re.sub(r"[^a-z0-9-]", "", s)
    # Collapse multiple dashes (optional, safer)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

def get_hostname(url: str) -> str:
    try:
        p = urlparse(url)
        # hostname gives lowercase without port if possible
        host = p.hostname
        if host:
            return host.lower()
        # fallback to netloc (may include port)
        return p.netloc.lower()
    except Exception:
        return ""

def extract_urls(text: str) -> list:
    if not isinstance(text, str):
        return []
    # Simple URL regex; stop at whitespace, ')', ']', or '>'
    pattern = re.compile(r"https?://[^\s\)\]\>]+", re.IGNORECASE)
    return pattern.findall(text)

def normalize_exclusions(lines):
    ex = []
    for line in lines:
        t = line.strip()
        if not t:
            continue
        if t.startswith("#"):
            continue
        ex.append(t.lower())
    return ex

def contains_excluded(hostname: str, exclusions: list) -> bool:
    hn = (hostname or "").lower()
    for sub in exclusions:
        if sub and sub in hn:
            return True
    return False

def unique(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Load inputs
    search_plan_path = os.path.join(input_dir, "search_plan.json")
    exclusions_path = os.path.join(input_dir, "exclusions.txt")
    brief_path = os.path.join(input_dir, "brief.md")

    plan = read_json_file(search_plan_path)
    exclusions_text = read_text_file(exclusions_path)
    brief_text = read_text_file(brief_path)

    # Prepare derived inputs
    if plan and isinstance(plan, dict):
        items = plan.get("items", [])
        # Defaults may be at top-level or under "defaults"
        defaults_obj = plan.get("defaults", {}) if isinstance(plan.get("defaults"), dict) else {}
        default_language = plan.get("language") or defaults_obj.get("language") or "auto"
        default_time_range = plan.get("time_range") or defaults_obj.get("time_range") or ""
    else:
        items = []
        default_language = "auto"
        default_time_range = ""

    exclusions_list = normalize_exclusions((exclusions_text or "").splitlines())

    # If no items or missing inputs, baseline 0 reward (checks remain False)
    # Proceed to validate outputs only if plan exists with items
    # Build expectations for raw files
    expected_raw = []
    for idx, it in enumerate(items):
        q = it.get("query", "")
        cat = it.get("category", "")
        lim = it.get("limit", None)
        lang_eff = it.get("language", default_language)
        tr_eff = it.get("time_range", default_time_range)
        slug = slugify(q)
        expected_filename = os.path.join(output_dir, "raw", f"{slug}__{cat}.json")
        expected_rel = os.path.join("output", "raw", f"{slug}__{cat}.json")
        expected_raw.append({
            "index": idx,
            "query": q,
            "category": cat,
            "limit": lim,
            "language": lang_eff,
            "time_range": tr_eff,
            "slug": slug,
            "path_abs": expected_filename,
            "path_rel": expected_rel
        })

    # Validate raw files
    raw_union_urls = []
    all_raw_ok = True
    for er in expected_raw:
        i = er["index"] + 1
        file_ok_key = f"raw_{i}_file_ok"
        fields_ok_key = f"raw_{i}_fields_ok"
        limit_ok_key = f"raw_{i}_limit_ok"
        results_shape_ok_key = f"raw_{i}_results_shape_ok"
        checks[file_ok_key] = False
        checks[fields_ok_key] = False
        checks[limit_ok_key] = False
        checks[results_shape_ok_key] = False

        data = read_json_file(er["path_abs"])
        if data is None or not isinstance(data, dict):
            all_raw_ok = False
            continue

        checks[file_ok_key] = True

        # Required top-level keys
        required_keys = ["query", "category", "language", "time_range", "results"]
        if not all(k in data for k in required_keys):
            all_raw_ok = False
            continue

        # Validate fields types
        if not isinstance(data.get("query"), str):
            all_raw_ok = False
            continue
        if not isinstance(data.get("category"), str):
            all_raw_ok = False
            continue
        if not isinstance(data.get("language"), str):
            all_raw_ok = False
            continue
        if not isinstance(data.get("time_range"), str):
            all_raw_ok = False
            continue
        if not isinstance(data.get("results"), list):
            all_raw_ok = False
            continue

        # Validate values match effective plan
        if data.get("query") != er["query"] or data.get("category") != er["category"] or data.get("language") != er["language"] or data.get("time_range") != er["time_range"]:
            all_raw_ok = False
            # Do not continue; still check other aspects
        else:
            checks[fields_ok_key] = True

        # Validate results shape and count <= limit
        results = data.get("results", [])
        # limit may be None; if None, just ensure it's a list
        limit_val = er["limit"]
        if isinstance(limit_val, int):
            if len(results) <= limit_val:
                checks[limit_ok_key] = True
            else:
                all_raw_ok = False
        else:
            # If limit absent or invalid, we still require array exists; do not award limit_ok
            pass

        # Validate each result item has title and url strings
        result_items_ok = True
        for r in results:
            if not isinstance(r, dict):
                result_items_ok = False
                break
            if "title" not in r or "url" not in r:
                result_items_ok = False
                break
            if not isinstance(r["title"], str) or not isinstance(r["url"], str):
                result_items_ok = False
                break
            raw_union_urls.append(r["url"])
        if result_items_ok:
            checks[results_shape_ok_key] = True
        else:
            all_raw_ok = False

    # Validate index.json
    index_path = os.path.join(output_dir, "index.json")
    index = read_json_file(index_path)
    checks["index_exists"] = isinstance(index, dict)
    checks["index_topic_string"] = False
    checks["index_items_count_ok"] = False
    checks["index_generated_at_iso8601"] = False
    checks["index_items_match_plan_ok"] = False
    checks["index_result_counts_ok"] = False

    if isinstance(index, dict):
        # topic
        if isinstance(index.get("topic"), str):
            checks["index_topic_string"] = True
        # generated_at
        if is_iso8601_like(index.get("generated_at", "")):
            checks["index_generated_at_iso8601"] = True
        # items
        idx_items = index.get("items", None)
        if isinstance(idx_items, list) and len(idx_items) == len(expected_raw):
            checks["index_items_count_ok"] = True

            # Build a mapping from expected tuple to index item
            # expected tuple key: (query, category, language, time_range)
            index_match_ok = True
            index_result_counts_ok = True

            # For faster lookup, copy raw data map by rel path
            raw_data_cache = {}
            for er in expected_raw:
                d = read_json_file(er["path_abs"])
                if isinstance(d, dict):
                    raw_data_cache[er["path_rel"]] = d

            # For each expected, find matching index item
            # We allow any order in index
            for er in expected_raw:
                # Find index item with matching fields
                found = None
                for it in idx_items:
                    if not isinstance(it, dict):
                        continue
                    if (it.get("query") == er["query"] and
                        it.get("category") == er["category"] and
                        it.get("language") == er["language"] and
                        it.get("time_range") == er["time_range"]):
                        found = it
                        break
                if not found:
                    index_match_ok = False
                    continue
                # Verify file path exists
                file_rel = found.get("file")
                if not isinstance(file_rel, str):
                    index_match_ok = False
                    continue
                file_abs = os.path.join(workspace_root, file_rel)
                if not os.path.isfile(file_abs):
                    index_match_ok = False
                    continue
                # Verify result_count equals actual results length in raw file
                raw_json = raw_data_cache.get(file_rel) or read_json_file(file_abs)
                if not isinstance(raw_json, dict):
                    index_result_counts_ok = False
                    continue
                results_len = len(raw_json.get("results", [])) if isinstance(raw_json.get("results"), list) else 0
                if found.get("result_count") != results_len:
                    index_result_counts_ok = False

            if index_match_ok:
                checks["index_items_match_plan_ok"] = True
            if index_result_counts_ok:
                checks["index_result_counts_ok"] = True

    # Validate deduped_urls.json
    dedup_path = os.path.join(output_dir, "deduped_urls.json")
    dedup = read_json_file(dedup_path)
    checks["dedup_exists"] = isinstance(dedup, list)
    checks["dedup_all_strings"] = False
    checks["dedup_unique"] = False
    checks["dedup_filtered_domains_ok"] = False
    checks["dedup_from_raw_ok"] = False

    allowed_raw_urls_set = set()
    # Compute allowed URLs from raw (filter exclusions)
    for url in raw_union_urls:
        hn = get_hostname(url)
        if not contains_excluded(hn, exclusions_list):
            allowed_raw_urls_set.add(url)

    if isinstance(dedup, list):
        all_strings = all(isinstance(u, str) for u in dedup)
        if all_strings:
            checks["dedup_all_strings"] = True
        # Unique check
        if len(dedup) == len(set(dedup)):
            checks["dedup_unique"] = True
        # Exclusions applied: no URL has excluded hostname substring
        filtered_ok = True
        for u in dedup:
            hn = get_hostname(u)
            if contains_excluded(hn, exclusions_list):
                filtered_ok = False
                break
        if filtered_ok:
            checks["dedup_filtered_domains_ok"] = True
        # Every dedup URL must come from allowed_raw_urls_set
        from_raw_ok = True
        for u in dedup:
            if u not in allowed_raw_urls_set:
                from_raw_ok = False
                break
        if from_raw_ok and len(dedup) > 0:
            checks["dedup_from_raw_ok"] = True
        elif from_raw_ok and len(dedup) == 0:
            # Empty is acceptable for this check to be True (every URL in empty set is from raw)
            checks["dedup_from_raw_ok"] = True

    # Validate report.md
    report_path = os.path.join(output_dir, "report.md")
    report_text = read_text_file(report_path)
    checks["report_exists"] = isinstance(report_text, str)

    checks["report_headings_ok"] = False
    checks["report_params_ok"] = False
    checks["report_total_count_match"] = False
    checks["report_sources_ok"] = False

    if isinstance(report_text, str):
        # Headings exactly once each
        headings = [
            "# Executive Summary",
            "## Methodology",
            "## Findings",
            "## Sources",
            "## Appendix: Deduplicated URLs",
        ]
        headings_ok = True
        for h in headings:
            if report_text.count(h) != 1:
                headings_ok = False
                break
        if headings_ok:
            checks["report_headings_ok"] = True

        # Params presence
        params_ok = ("Time range: " + str(default_time_range)) in report_text and ("Language: " + str(default_language)) in report_text
        if params_ok:
            checks["report_params_ok"] = True

        # Total unique URLs count matches dedup length
        m = re.search(r"Total unique URLs:\s*(\d+)", report_text)
        if m and isinstance(dedup, list):
            try:
                n = int(m.group(1))
                if n == len(dedup):
                    checks["report_total_count_match"] = True
            except Exception:
                pass

        # Sources section: verify at least 3 HTTP(S) URLs appear and none are excluded and all are from allowed_raw_urls_set
        # Extract the Sources section content
        src_section = ""
        src_start = report_text.find("## Sources")
        if src_start != -1:
            # End at next heading "## " or end of string
            next_heading_match = re.search(r"\n## ", report_text[src_start + len("## Sources"):])
            if next_heading_match:
                end_idx = src_start + len("## Sources") + next_heading_match.start()
                src_section = report_text[src_start:end_idx]
            else:
                src_section = report_text[src_start:]

        urls_in_sources = extract_urls(src_section)
        # Filter those that are allowed (not excluded) and present in raw (allowed_raw_urls_set)
        allowed_urls_in_sources = []
        for u in urls_in_sources:
            hn = get_hostname(u)
            if not contains_excluded(hn, exclusions_list) and u in allowed_raw_urls_set:
                allowed_urls_in_sources.append(u)
        # Unique count
        allowed_urls_in_sources = list(set(allowed_urls_in_sources))
        if len(allowed_urls_in_sources) >= 3:
            checks["report_sources_ok"] = True

    # Compute reward as average of passed checks
    # Ensure no-op baseline: if no output artifacts, all checks remain False and reward is 0.0
    total_checks = 0
    passed_checks = 0
    for k, v in checks.items():
        if isinstance(v, bool):
            total_checks += 1
            if v:
                passed_checks += 1

    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Clamp between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print final JSON as last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()