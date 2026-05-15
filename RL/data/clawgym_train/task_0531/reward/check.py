import json
import os
import sys
from urllib.parse import urlparse
from datetime import datetime

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Support Zulu time by replacing 'Z' with +00:00 for fromisoformat
        if s.endswith('Z'):
            datetime.fromisoformat(s[:-1] + '+00:00')
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        # Try a fallback parse for common formats without timezone
        try:
            datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            return True
        except Exception:
            return False

def read_file_lines(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().splitlines()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    raw_results_path = os.path.join(output_dir, "raw_results.jsonl")
    domains_csv_path = os.path.join(output_dir, "domains.csv")
    queries_json_path = os.path.join(output_dir, "queries.json")
    summary_md_path = os.path.join(output_dir, "summary.md")

    # Initialize all checks to False
    # raw_results checks
    checks["raw_results_file_exists"] = False
    checks["raw_results_nonempty"] = False
    checks["raw_results_at_least_20_lines"] = False
    checks["raw_results_valid_schema"] = False
    checks["raw_results_valid_categories"] = False
    checks["raw_results_urls_http"] = False
    checks["raw_results_engines_nonempty_array"] = False
    checks["raw_results_no_duplicate_url_within_keyword_category"] = False

    # domains.csv checks
    checks["domains_csv_exists"] = False
    checks["domains_csv_header_ok"] = False
    checks["domains_csv_min_rows_10"] = False
    checks["domains_csv_counts_positive_ints"] = False

    # queries.json checks
    checks["queries_json_exists"] = False
    checks["queries_json_structure_valid"] = False
    checks["queries_language_en_us"] = False
    checks["queries_has_pagination_for_any_keyword"] = False

    # cross-validation checks
    checks["cross_validate_keyword_has_both_categories"] = False

    # summary.md checks
    checks["summary_md_exists"] = False
    checks["summary_has_required_headings"] = False
    checks["summary_methodology_mentions_categories_and_language"] = False

    # Validate raw_results.jsonl
    raw_lines = None
    if os.path.isfile(raw_results_path):
        checks["raw_results_file_exists"] = True
        raw_lines = read_file_lines(raw_results_path)
        if raw_lines is not None and len([ln for ln in raw_lines if ln.strip()]) > 0:
            checks["raw_results_nonempty"] = True
        if raw_lines is not None:
            nonempty_lines = [ln for ln in raw_lines if ln.strip()]
            if len(nonempty_lines) >= 20:
                checks["raw_results_at_least_20_lines"] = True

        # Validate schema
        if raw_lines is not None:
            valid_schema = True
            valid_categories = True
            urls_http = True
            engines_nonempty = True

            group_urls = {}  # (keyword, category) -> set(url)
            no_dupes = True

            for ln in raw_lines:
                if not ln.strip():
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    valid_schema = False
                    continue

                # Required keys and types
                required_keys = ["keyword", "category", "pageno", "title", "url", "content", "engines", "score"]
                if not all(k in obj for k in required_keys):
                    valid_schema = False
                    continue

                if not isinstance(obj["keyword"], str):
                    valid_schema = False
                if not isinstance(obj["title"], str):
                    valid_schema = False
                if not isinstance(obj["url"], str):
                    valid_schema = False
                if not isinstance(obj["content"], str):
                    valid_schema = False
                if not is_number(obj["score"]):
                    valid_schema = False
                # pageno should be a number; accept int/float but prefer int
                if not is_number(obj["pageno"]):
                    valid_schema = False
                # engines: non-empty array of strings
                if not isinstance(obj["engines"], list) or len(obj["engines"]) == 0:
                    engines_nonempty = False
                else:
                    if not all(isinstance(e, str) for e in obj["engines"]):
                        engines_nonempty = False

                # category check
                cat = obj.get("category")
                if cat not in ("news", "it"):
                    valid_categories = False

                # url should start with http
                url = obj.get("url", "")
                if not (isinstance(url, str) and url.lower().startswith("http")):
                    urls_http = False

                # Dedup per (keyword, category)
                kw = obj.get("keyword")
                grp = (kw, cat)
                if isinstance(kw, str) and isinstance(cat, str) and isinstance(url, str):
                    if grp not in group_urls:
                        group_urls[grp] = set()
                    if url in group_urls[grp]:
                        no_dupes = False
                    else:
                        group_urls[grp].add(url)

            checks["raw_results_valid_schema"] = valid_schema
            checks["raw_results_valid_categories"] = valid_categories
            checks["raw_results_urls_http"] = urls_http
            checks["raw_results_engines_nonempty_array"] = engines_nonempty
            checks["raw_results_no_duplicate_url_within_keyword_category"] = no_dupes

    # Validate domains.csv
    if os.path.isfile(domains_csv_path):
        checks["domains_csv_exists"] = True
        lines = read_file_lines(domains_csv_path) or []
        if lines:
            header = lines[0].strip()
            if header == "keyword,domain,count":
                checks["domains_csv_header_ok"] = True
            data_rows = [ln for ln in lines[1:] if ln.strip()]
            if len(data_rows) >= 10:
                checks["domains_csv_min_rows_10"] = True
            # Validate counts as positive integers
            counts_valid = True
            for ln in data_rows:
                parts = ln.strip().split(",")
                if len(parts) != 3:
                    counts_valid = False
                    break
                count_str = parts[2].strip()
                if not count_str.isdigit():
                    counts_valid = False
                    break
                if int(count_str) <= 0:
                    counts_valid = False
                    break
            checks["domains_csv_counts_positive_ints"] = counts_valid

    # Validate queries.json
    queries_data = None
    if os.path.isfile(queries_json_path):
        checks["queries_json_exists"] = True
        queries_data = parse_json_file(queries_json_path)
        if isinstance(queries_data, dict):
            structure_valid = True
            # Top-level keys
            language = queries_data.get("language")
            endpoint_used = queries_data.get("endpoint_used")
            kw_items = queries_data.get("keywords")

            if language != "en-US":
                # value may still be a string but not 'en-US', structure_valid can still be True
                pass
            else:
                checks["queries_language_en_us"] = True

            if not isinstance(endpoint_used, str) or not endpoint_used.strip():
                structure_valid = False

            if not isinstance(kw_items, list) or len(kw_items) == 0:
                structure_valid = False

            # Validate each keyword item and queries
            pagination_found = False
            if isinstance(kw_items, list):
                for item in kw_items:
                    if not isinstance(item, dict):
                        structure_valid = False
                        break
                    if not isinstance(item.get("keyword"), str):
                        structure_valid = False
                        break
                    qlist = item.get("queries")
                    if not isinstance(qlist, list):
                        structure_valid = False
                        break
                    # Track pagination per category for this keyword
                    per_cat_pages = {}
                    for q in qlist:
                        if not isinstance(q, dict):
                            structure_valid = False
                            break
                        qstr = q.get("q")
                        cat = q.get("categories")
                        pageno = q.get("pageno")
                        ts = q.get("timestamp")
                        if not isinstance(qstr, str) or not isinstance(cat, str):
                            structure_valid = False
                            break
                        if cat not in ("news", "it"):
                            structure_valid = False
                            break
                        if not is_number(pageno):
                            structure_valid = False
                            break
                        if not isinstance(ts, str) or not is_iso8601(ts):
                            structure_valid = False
                            break
                        # Track pages for pagination check (need both 1 and 2 for a category)
                        try:
                            p_int = int(pageno)
                        except Exception:
                            p_int = None
                        if p_int is not None:
                            per_cat_pages.setdefault(cat, set()).add(p_int)
                    # After processing queries for this keyword
                    for cat, pageset in per_cat_pages.items():
                        if 1 in pageset and 2 in pageset:
                            pagination_found = True
                    if not structure_valid:
                        break

            checks["queries_json_structure_valid"] = structure_valid
            checks["queries_has_pagination_for_any_keyword"] = pagination_found

    # Cross-validation: For at least one keyword in raw_results, queries.json includes entries for both categories
    if raw_lines is not None and queries_data is not None and isinstance(queries_data, dict):
        try:
            # Collect keywords from raw_results
            raw_keywords = set()
            for ln in raw_lines:
                if not ln.strip():
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                kw = obj.get("keyword")
                cat = obj.get("category")
                if isinstance(kw, str) and isinstance(cat, str) and cat in ("news", "it"):
                    raw_keywords.add(kw)
            # Build category presence per keyword from queries.json
            q_keywords = queries_data.get("keywords", [])
            has_both = False
            if isinstance(q_keywords, list):
                for item in q_keywords:
                    if not isinstance(item, dict):
                        continue
                    kw = item.get("keyword")
                    if kw in raw_keywords:
                        cats_present = set()
                        qlist = item.get("queries") or []
                        for q in qlist:
                            if isinstance(q, dict):
                                cat = q.get("categories")
                                if cat in ("news", "it"):
                                    cats_present.add(cat)
                        if "news" in cats_present and "it" in cats_present:
                            has_both = True
                            break
            checks["cross_validate_keyword_has_both_categories"] = has_both
        except Exception:
            checks["cross_validate_keyword_has_both_categories"] = False

    # Validate summary.md
    if os.path.isfile(summary_md_path):
        checks["summary_md_exists"] = True
        try:
            with open(summary_md_path, 'r', encoding='utf-8') as f:
                summary_text = f.read()
        except Exception:
            summary_text = ""

        if summary_text:
            # Check headings exactly present on their own lines
            lines = [ln.rstrip("\r") for ln in summary_text.splitlines()]
            headings = {"Methodology": False, "Top Findings": False, "Gaps & Next Steps": False}
            for ln in lines:
                if ln.strip() in headings:
                    headings[ln.strip()] = True
            if all(headings.values()):
                checks["summary_has_required_headings"] = True

            # Extract Methodology section content (between Methodology and next heading)
            method_content = ""
            try:
                # Find indices of headings
                idx_method = None
                idx_next = None
                for i, ln in enumerate(lines):
                    if ln.strip() == "Methodology":
                        idx_method = i
                        break
                if idx_method is not None:
                    # Search for the next heading after idx_method
                    for j in range(idx_method + 1, len(lines)):
                        if lines[j].strip() in headings and lines[j].strip() != "Methodology":
                            idx_next = j
                            break
                    if idx_next is None:
                        method_content = "\n".join(lines[idx_method+1:])
                    else:
                        method_content = "\n".join(lines[idx_method+1:idx_next])
            except Exception:
                method_content = ""

            mc_lower = method_content.lower()
            # Must mention categories "news" and "it" and language "en-US"
            mentions = ("news" in mc_lower) and ("it" in mc_lower) and ("en-us" in mc_lower)
            checks["summary_methodology_mentions_categories_and_language"] = mentions

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()