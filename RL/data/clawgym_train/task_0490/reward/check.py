import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        text = _read_text(path)
        if text is None:
            return None, "missing"
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error:{e}"


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_simple_yaml(path: Path):
    """
    Minimal YAML parser for the known structure:
    keys: output_dir (str), per_query_limit (int), template (str), queries (list of str)
    Handles comments (#), quoted or unquoted simple scalars, and block list for queries.
    Returns (config_dict, error_str|None).
    """
    text = _read_text(path)
    if text is None:
        return None, "missing"
    cfg = {}
    lines = text.splitlines()
    in_queries = False
    queries = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped:
            continue

        def _remove_comment(s: str) -> str:
            in_single = False
            in_double = False
            out = []
            i = 0
            while i < len(s):
                ch = s[i]
                if ch == "'" and not in_double:
                    in_single = not in_single
                    out.append(ch)
                elif ch == '"' and not in_single:
                    in_double = not in_double
                    out.append(ch)
                elif ch == "#" and not in_single and not in_double:
                    break
                else:
                    out.append(ch)
                i += 1
            return "".join(out).rstrip()

        line_nc = _remove_comment(line)
        if not line_nc.strip():
            continue
        if re.match(r"^\S[^:]*:\s*(.+)?$", line_nc):
            key, val = line_nc.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "queries":
                in_queries = True
                queries = []
                if val == "[]":
                    in_queries = False
                    cfg["queries"] = []
                elif val:
                    v = val.strip()
                    if v.startswith("[") and v.endswith("]"):
                        inner = v[1:-1].strip()
                        items = []
                        buf = ""
                        in_s = False
                        in_d = False
                        for ch in inner:
                            if ch == "'" and not in_d:
                                in_s = not in_s
                                buf += ch
                            elif ch == '"' and not in_s:
                                in_d = not in_d
                                buf += ch
                            elif ch == "," and not in_s and not in_d:
                                item = _strip_quotes(buf.strip())
                                items.append(item)
                                buf = ""
                            else:
                                buf += ch
                        if buf.strip():
                            items.append(_strip_quotes(buf.strip()))
                        cfg["queries"] = [i for i in items if i != ""]
                        in_queries = False
                continue
            else:
                in_queries = False
                if key == "output_dir":
                    cfg["output_dir"] = _strip_quotes(val)
                elif key == "template":
                    cfg["template"] = _strip_quotes(val)
                elif key == "per_query_limit":
                    try:
                        cfg["per_query_limit"] = int(val)
                    except Exception:
                        try:
                            cfg["per_query_limit"] = int(_strip_quotes(val))
                        except Exception:
                            return None, "invalid_per_query_limit"
                else:
                    pass
        else:
            if in_queries:
                m = re.match(r"^\s*-\s*(.+)$", line_nc)
                if m:
                    item = _strip_quotes(m.group(1).strip())
                    queries.append(item)
                else:
                    in_queries = False
    if "queries" not in cfg and queries:
        cfg["queries"] = queries
    return cfg, None


def _parse_iso8601_utc(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    ts = s.strip()
    try:
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            return False
        return dt.tzinfo.utcoffset(dt) == timezone.utc.utcoffset(dt)
    except Exception:
        return False


def _extract_int_after_total(html: str) -> int:
    if not isinstance(html, str):
        return None
    pattern = r"Total retained entries:\s*([0-9]+)"
    m = re.search(pattern, html)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _extract_generated_at(html: str) -> str:
    if not isinstance(html, str):
        return None
    # Look for 'Generated at ' followed by ISO string up to '<' or end of string
    m = re.search(r"Generated at\s+([^<]+)", html)
    if not m:
        return None
    return m.group(1).strip()


def _domain_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        return p.netloc
    except Exception:
        return ""


def _html_order_matches_sorted(html: str, entries: list) -> bool:
    def sort_key(e):
        title = e.get("page_title")
        t = title if isinstance(title, str) else ""
        return (e.get("source_domain", "").lower(), t.lower() if t else e.get("url", "").lower())
    expected = sorted(entries, key=sort_key)
    positions = []
    for e in expected:
        url = e.get("url", "")
        if not isinstance(url, str) or not url:
            return False
        idx = html.find(url)
        if idx == -1:
            return False
        positions.append(idx)
    return all(positions[i] < positions[i + 1] for i in range(len(positions) - 1))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_queries_count": 0.0,
        "config_queries_relevance": 0.0,
        "config_per_query_limit": 0.0,
        "config_output_dir": 0.0,
        "results_json_schema": 0.0,
        "results_json_dedup_urls": 0.0,
        "results_json_query_in_config": 0.0,
        "results_json_domain_correct": 0.0,
        "results_json_matched_keywords_consistent": 0.0,
        "results_json_fetched_at_utc": 0.0,
        "index_html_exists_and_placeholders_replaced": 0.0,
        "index_html_total_matches_json": 0.0,
        "index_html_contains_entries": 0.0,
        "index_html_sorted_by_domain_then_title": 0.0,
        "template_used_in_html": 0.0,
        "index_html_generated_at_utc": 0.0,
    }

    # Load config.yaml
    cfg_path = workspace / "src" / "prototype" / "config.yaml"
    cfg, cfg_err = _parse_simple_yaml(cfg_path)
    if cfg is None:
        cfg = {}
    queries = cfg.get("queries") if isinstance(cfg.get("queries"), list) else None
    per_query_limit = cfg.get("per_query_limit")
    output_dir = cfg.get("output_dir")
    tpl_path_cfg = cfg.get("template")

    # Load input keywords
    fam_keywords_path = workspace / "input" / "family_notes.json"
    fam_data, _ = _load_json(fam_keywords_path)
    keywords = []
    if isinstance(fam_data, dict) and isinstance(fam_data.get("keywords"), list):
        keywords = [k for k in fam_data.get("keywords") if isinstance(k, str)]

    # Check config queries count and distinctness
    if isinstance(queries, list):
        unique_queries = [q for q in queries if isinstance(q, str)]
        if len(unique_queries) >= 2 and len(set(unique_queries)) >= 2:
            scores["config_queries_count"] = 1.0

    # Check config queries relevance: each query should include at least one of the family keywords,
    # and at least one query should include a primary name variant ("William Elwood Murray" or "W. E. Murray").
    if isinstance(queries, list) and keywords and len(queries) >= 2:
        kw_lower = [k.lower() for k in keywords]
        all_have_keyword = True
        has_name_variant = False
        for q in queries:
            if not isinstance(q, str):
                all_have_keyword = False
                continue
            ql = q.lower()
            matched_any = any(k in ql for k in kw_lower)
            if not matched_any:
                all_have_keyword = False
            if ("william elwood murray" in ql) or ("w. e. murray" in ql):
                has_name_variant = True
        if all_have_keyword and has_name_variant:
            scores["config_queries_relevance"] = 1.0

    # Check per_query_limit (only once queries have been configured to avoid awarding scaffold defaults)
    if isinstance(queries, list) and len(queries) >= 2:
        if isinstance(per_query_limit, int) and per_query_limit == 5:
            scores["config_per_query_limit"] = 1.0

    # Check output_dir (only once queries have been configured)
    if isinstance(queries, list) and len(queries) >= 2:
        if isinstance(output_dir, str) and output_dir == "output":
            scores["config_output_dir"] = 1.0

    # Prepare paths for outputs
    out_dir_path = workspace / (output_dir if isinstance(output_dir, str) else "output")
    results_path = out_dir_path / "search_results.json"
    index_path = out_dir_path / "index.html"

    # Validate results JSON schema
    results, _ = _load_json(results_path)
    if isinstance(results, list):
        schema_ok = True
        dedup_ok = True
        query_in_cfg_ok = isinstance(queries, list)
        domain_ok = True
        mk_ok = True
        ts_ok = True

        seen_urls = set()
        for item in results:
            if not isinstance(item, dict):
                schema_ok = False
                break
            expected_keys = {
                "query",
                "url",
                "page_title",
                "meta_description",
                "source_domain",
                "matched_keywords",
                "fetched_at",
            }
            if set(item.keys()) != expected_keys:
                schema_ok = False
                break
            if not isinstance(item.get("query"), str):
                schema_ok = False
                break
            if not isinstance(item.get("url"), str):
                schema_ok = False
                break
            if not (item.get("page_title") is None or isinstance(item.get("page_title"), str)):
                schema_ok = False
                break
            if not (item.get("meta_description") is None or isinstance(item.get("meta_description"), str)):
                schema_ok = False
                break
            if not isinstance(item.get("source_domain"), str):
                schema_ok = False
                break
            if not isinstance(item.get("matched_keywords"), list):
                schema_ok = False
                break
            if not isinstance(item.get("fetched_at"), str):
                schema_ok = False
                break

            url = item["url"]
            if url in seen_urls:
                dedup_ok = False
            else:
                seen_urls.add(url)

            if isinstance(queries, list):
                if item["query"] not in queries:
                    query_in_cfg_ok = False

            expected_domain = _domain_from_url(url)
            if expected_domain.lower() != item["source_domain"].lower():
                domain_ok = False

            mks = item["matched_keywords"]
            if len(mks) == 0:
                mk_ok = False
            else:
                # All matched keywords must come from family keywords
                for mk in mks:
                    if not isinstance(mk, str) or mk not in keywords:
                        mk_ok = False
                        break
                # And at least one should appear in title or description (case-insensitive)
                title = item.get("page_title")
                desc = item.get("meta_description")
                base_text = (title or "") + "\n" + (desc or "")
                base_lower = base_text.lower()
                if mks and not any(mk.lower() in base_lower for mk in mks):
                    mk_ok = False

            if not _parse_iso8601_utc(item["fetched_at"]):
                ts_ok = False

        if schema_ok:
            scores["results_json_schema"] = 1.0
        if dedup_ok and schema_ok:
            scores["results_json_dedup_urls"] = 1.0
        if query_in_cfg_ok and schema_ok:
            scores["results_json_query_in_config"] = 1.0
        if domain_ok and schema_ok:
            scores["results_json_domain_correct"] = 1.0
        if mk_ok and schema_ok and keywords:
            scores["results_json_matched_keywords_consistent"] = 1.0
        if ts_ok and schema_ok:
            scores["results_json_fetched_at_utc"] = 1.0

    # Validate index.html and relationship to JSON
    html_text = _read_text(index_path)
    if html_text is not None:
        placeholders_absent = ("{{TOTAL}}" not in html_text) and ("{{GENERATED_AT}}" not in html_text) and ("{{ITEMS}}" not in html_text)
        if placeholders_absent:
            scores["index_html_exists_and_placeholders_replaced"] = 1.0

        # Total count matches JSON length
        if isinstance(results, list):
            total_in_html = _extract_int_after_total(html_text)
            if total_in_html is not None and total_in_html == len(results):
                scores["index_html_total_matches_json"] = 1.0

        # Contains entries (if any)
        contains_all = True
        if isinstance(results, list) and len(results) > 0:
            for item in results:
                url = item.get("url")
                if not url or url not in html_text:
                    contains_all = False
                    break
                dom = item.get("source_domain")
                if dom and dom not in html_text:
                    contains_all = False
                    break
                mks = item.get("matched_keywords", [])
                for mk in mks:
                    if mk not in html_text:
                        contains_all = False
                        break
                if not contains_all:
                    break
                title = item.get("page_title")
                if isinstance(title, str) and title.strip():
                    if title not in html_text:
                        contains_all = False
                        break
            if contains_all:
                scores["index_html_contains_entries"] = 1.0

        # Sorted by domain then title based on URLs order in HTML
        if isinstance(results, list) and results:
            if _html_order_matches_sorted(html_text, results):
                scores["index_html_sorted_by_domain_then_title"] = 1.0

        # Template used: check that the H1 from template appears
        expected_h1 = "William Elwood Murray: Public Mentions Prototype"
        if expected_h1 in html_text:
            scores["template_used_in_html"] = 1.0

        # Generated at timestamp is ISO 8601 UTC
        gen_at = _extract_generated_at(html_text)
        if gen_at and _parse_iso8601_utc(gen_at):
            scores["index_html_generated_at_utc"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()