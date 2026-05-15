import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return ""


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _load_json(path: Path):
    try:
        return json.loads(_read_text_safe(path))
    except Exception:
        return None


def _strip_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        return text.lstrip("\ufeff")
    return text


def _load_simple_yaml_config(path: Path):
    # Minimal YAML parsing for the provided simple config structure
    # Supports:
    # key: "value"
    # key: value
    # key:
    #   - "item"
    #   - item
    content = _read_text_safe(path)
    if not content:
        return None
    lines = [ln.rstrip("\n") for ln in content.splitlines()]
    data = {}
    current_key = None
    in_list = False
    for raw in lines:
        line = _strip_bom(raw).strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[\w_]+:\s*(.+)$", line):
            m = re.match(r"^([\w_]+):\s*(.+)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            current_key = key
            in_list = False
            # Strip quotes if present
            val = val.strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
            if key in ("min_rows",):
                try:
                    data[key] = int(val)
                except Exception:
                    data[key] = None
            else:
                data[key] = val
        elif re.match(r"^[\w_]+:\s*$", line):
            m = re.match(r"^([\w_]+):\s*$", line)
            if not m:
                continue
            current_key = m.group(1)
            data[current_key] = []
            in_list = True
        elif in_list and line.startswith("-"):
            item = line[1:].strip()
            if item.startswith('"') and item.endswith('"') and len(item) >= 2:
                item = item[1:-1]
            # ensure list initialized
            if current_key is not None and isinstance(data.get(current_key), list):
                data[current_key].append(item)
        else:
            # ignore other constructs
            pass
    return data


def _domain_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        # strip credentials if present
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        # strip port
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        return netloc.lower()
    except Exception:
        return ""


def _is_relative_under(p: Path, root: Path) -> bool:
    try:
        resolved = (root / p.name) if p.is_absolute() else p
        # Ensure p is a relative path within root
        full = (root.parent / resolved).resolve()
        return str(full).startswith(str(root.resolve()))
    except Exception:
        return False


def _regex_date_yyyy_mm_dd(val: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", val.strip()))


def _parse_queries(path: Path):
    text = _read_text_safe(path)
    if not text:
        return []
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln:
            out.append(ln)
    return out


def _contains_case_insensitive(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _find_files_for_slug(pages_dir: Path, slug: str):
    matches = []
    if not pages_dir.exists():
        return matches
    try:
        for p in pages_dir.iterdir():
            if not p.is_file():
                continue
            name = p.name
            stem = p.stem
            if name.startswith(slug) or stem == slug:
                matches.append(p)
    except Exception:
        return matches
    return matches


def _traverse_find_query_entries(obj):
    # Return dict mapping query string -> entry dict with keys of interest
    found = {}
    def visit(node):
        nonlocal found
        if isinstance(node, dict):
            # Possible mapping of query -> details
            # If dict keys look like queries (strings with spaces, quotes)
            # and values are dicts with timestamp etc., collect them
            for k, v in node.items():
                if isinstance(k, str) and isinstance(v, dict) and ("timestamp" in v or "selected_urls" in v or "candidates_examined" in v):
                    if "query" not in v:
                        # Add synthetic query field
                        vv = dict(v)
                        vv["query"] = k
                        found[k] = vv
                    else:
                        found[k] = v
            # also visit nested dicts/lists
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict) and "query" in item:
                    q = item.get("query")
                    found[q] = item
                visit(item)
    visit(obj)
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scripts_collect_exists_and_args": 0.0,
        "tests_validate_exists_and_args": 0.0,
        "validate_script_writes_reports": 0.0,
        "achievements_csv_header_exact": 0.0,
        "achievements_min_rows_meet": 0.0,
        "achievements_person_name_exact": 0.0,
        "achievements_source_url_unique": 0.0,
        "achievements_local_path_exists_and_contains_name": 0.0,
        "achievements_title_and_snippet_non_empty": 0.0,
        "achievements_published_date_format": 0.0,
        "achievements_achievement_type_values": 0.0,
        "achievements_domain_allowed_presence": 0.0,
        "achievements_org_domain_matches_source_url": 0.0,
        "raw_pages_manifest_exists_and_header": 0.0,
        "manifest_rows_have_files_and_size_match": 0.0,
        "search_log_includes_queries_and_timestamps": 0.0,
        "achievements_local_path_under_data_raw_pages": 0.0,
    }

    # Paths
    collect_py = workspace / "scripts" / "collect.py"
    validate_py = workspace / "tests" / "validate.py"
    data_dir = workspace / "data"
    reports_dir = workspace / "reports"
    pages_dir = data_dir / "raw" / "pages"
    manifest_csv = data_dir / "raw" / "pages_manifest.csv"
    achievements_csv = data_dir / "achievements.csv"
    log_json = data_dir / "search" / "log.json"
    queries_txt = workspace / "input" / "queries.txt"
    config_yaml = workspace / "input" / "config.yaml"

    # Check scripts existence and basic CLI args presence
    if collect_py.exists() and collect_py.is_file():
        text = _read_text_safe(collect_py)
        required_args = ["--queries", "--config", "--out", "--max-pages"]
        if all(arg in text for arg in required_args):
            scores["scripts_collect_exists_and_args"] = 1.0

    if validate_py.exists() and validate_py.is_file():
        text = _read_text_safe(validate_py)
        required_args = ["--config", "--data", "--report-dir"]
        if all(arg in text for arg in required_args):
            scores["tests_validate_exists_and_args"] = 1.0
        # check that it writes the specified reports
        if "validation_report.json" in text and "validation_report.md" in text:
            scores["validate_script_writes_reports"] = 1.0

    # Load config and queries
    config = _load_simple_yaml_config(config_yaml) if config_yaml.exists() else None
    queries_list = _parse_queries(queries_txt) if queries_txt.exists() else []

    # Load achievements.csv
    ach_headers, ach_rows = _load_csv_rows(achievements_csv)
    expected_headers = [
        "source_url",
        "organization_domain",
        "title",
        "person_name",
        "snippet",
        "achievement_type",
        "published_date",
        "local_path",
    ]
    if ach_headers is not None and ach_rows is not None:
        if ach_headers == expected_headers:
            scores["achievements_csv_header_exact"] = 1.0

        # min_rows
        if isinstance(config, dict) and isinstance(config.get("min_rows"), int):
            if len(ach_rows) >= config["min_rows"]:
                scores["achievements_min_rows_meet"] = 1.0

        # person_name exact
        name_ok = True
        expected_name = config.get("person_name") if isinstance(config, dict) else None
        if expected_name is None:
            name_ok = False
        else:
            for r in ach_rows:
                if (r.get("person_name") or "").strip() != expected_name:
                    name_ok = False
                    break
        scores["achievements_person_name_exact"] = 1.0 if name_ok else 0.0

        # source_url unique
        seen = set()
        uniq = True
        for r in ach_rows:
            su = (r.get("source_url") or "").strip()
            if su in seen:
                uniq = False
                break
            seen.add(su)
        scores["achievements_source_url_unique"] = 1.0 if uniq and len(ach_rows) > 0 else 0.0

        # title and snippet non-empty
        ts_ok = True
        for r in ach_rows:
            if not (r.get("title") or "").strip():
                ts_ok = False
                break
            if not (r.get("snippet") or "").strip():
                ts_ok = False
                break
        scores["achievements_title_and_snippet_non_empty"] = 1.0 if ts_ok and len(ach_rows) > 0 else 0.0

        # published_date format if present
        pd_ok = True
        for r in ach_rows:
            pd = (r.get("published_date") or "").strip()
            if pd and not _regex_date_yyyy_mm_dd(pd):
                pd_ok = False
                break
        scores["achievements_published_date_format"] = 1.0 if pd_ok and len(ach_rows) > 0 else 0.0

        # achievement_type allowed values
        valid_types = {"award", "competition", "press", "profile", "other"}
        type_ok = True
        for r in ach_rows:
            t = (r.get("achievement_type") or "").strip().lower()
            if t not in valid_types:
                type_ok = False
                break
        scores["achievements_achievement_type_values"] = 1.0 if type_ok and len(ach_rows) > 0 else 0.0

        # domain allowed presence (at least one)
        allowed_ok = 0.0
        if isinstance(config, dict):
            allowed_tlds = [s.lower() for s in (config.get("allowed_tlds") or [])]
            allowed_keywords = [s.lower() for s in (config.get("allowed_domain_keywords") or [])]
            for r in ach_rows:
                dom = (r.get("organization_domain") or "").lower()
                if not dom:
                    continue
                if any(dom.endswith(tld) for tld in allowed_tlds) or any(kw in dom for kw in allowed_keywords):
                    allowed_ok = 1.0
                    break
        scores["achievements_domain_allowed_presence"] = allowed_ok

        # org_domain matches source_url
        dom_ok = True
        for r in ach_rows:
            su = (r.get("source_url") or "").strip()
            od = (r.get("organization_domain") or "").strip().lower()
            if not su or not od:
                dom_ok = False
                break
            su_dom = _domain_from_url(su)
            if su_dom != od:
                dom_ok = False
                break
        scores["achievements_org_domain_matches_source_url"] = 1.0 if dom_ok and len(ach_rows) > 0 else 0.0

        # local_path exists and contains "Matt Vela"
        lp_ok = True
        contains_ok = True
        local_under_ok = True
        for r in ach_rows:
            lp = (r.get("local_path") or "").strip()
            if not lp:
                lp_ok = False
                break
            lp_path = workspace / lp
            if not lp_path.exists() or not lp_path.is_file():
                lp_ok = False
                break
            # check under data/raw/pages
            try:
                # Must be a relative path starting with data/raw/pages
                parts = Path(lp).parts
                if len(parts) < 3 or parts[0] != "data" or parts[1] != "raw" or parts[2] != "pages":
                    local_under_ok = False
                    break
                # also ensure the canonical path resolves within pages_dir
                if not str(lp_path.resolve()).startswith(str(pages_dir.resolve())):
                    local_under_ok = False
                    break
            except Exception:
                local_under_ok = False
                break
            html = _read_text_safe(lp_path)
            if not _contains_case_insensitive(html, "Matt Vela"):
                contains_ok = False
                break
        scores["achievements_local_path_exists_and_contains_name"] = 1.0 if lp_ok and contains_ok and len(ach_rows) > 0 else 0.0
        scores["achievements_local_path_under_data_raw_pages"] = 1.0 if local_under_ok and len(ach_rows) > 0 else 0.0

    # Manifest checks
    man_headers, man_rows = _load_csv_rows(manifest_csv)
    if man_headers is not None and man_rows is not None:
        required_cols = {"slug", "source_url", "http_status", "content_length"}
        if required_cols.issubset(set(man_headers)):
            scores["raw_pages_manifest_exists_and_header"] = 1.0

        # For each manifest row, find corresponding file(s) and check size and http_status range
        all_ok = True
        any_rows = False
        for r in man_rows:
            any_rows = True
            slug = (r.get("slug") or "").strip()
            status_str = (r.get("http_status") or "").strip()
            clen_str = (r.get("content_length") or "").strip()
            # status valid
            try:
                st = int(status_str)
                if st < 100 or st > 599:
                    all_ok = False
                    break
            except Exception:
                all_ok = False
                break
            # find files
            files = _find_files_for_slug(pages_dir, slug) if slug else []
            if not files:
                # If we cannot map slug to a file, we still require at least size >0 numeric
                try:
                    clen = int(clen_str)
                    if clen <= 0:
                        all_ok = False
                        break
                except Exception:
                    all_ok = False
                    break
            else:
                # pick largest matching file and compare size
                try:
                    actual_size = max(f.stat().st_size for f in files)
                except Exception:
                    actual_size = None
                try:
                    clen = int(clen_str)
                except Exception:
                    clen = None
                if actual_size is None or clen is None or actual_size != clen:
                    # Be strict: require exact match
                    all_ok = False
                    break
        if any_rows and all_ok:
            scores["manifest_rows_have_files_and_size_match"] = 1.0

    # Search log checks
    log = _load_json(log_json)
    if log is not None and isinstance(log, (dict, list)):
        # list of queries included
        queries_in_log = []
        if isinstance(log, dict) and isinstance(log.get("queries"), list):
            queries_in_log = [str(x) for x in log.get("queries")]
        has_queries_list = False
        if queries_list:
            if queries_in_log:
                # require all queries from file to be included
                if set(queries_list).issubset(set(queries_in_log)):
                    has_queries_list = True

        # per-query timestamps
        per_query_map = _traverse_find_query_entries(log)
        per_query_ok = False
        if queries_list and per_query_map:
            per_query_ok = True
            for q in queries_list:
                entry = per_query_map.get(q)
                if not isinstance(entry, dict):
                    per_query_ok = False
                    break
                # timestamp present
                if "timestamp" not in entry:
                    per_query_ok = False
                    break
                # candidates_examined present
                if "candidates_examined" not in entry:
                    per_query_ok = False
                    break
                # selected_urls present and list
                if "selected_urls" not in entry or not isinstance(entry.get("selected_urls"), list):
                    per_query_ok = False
                    break

        if has_queries_list and per_query_ok:
            scores["search_log_includes_queries_and_timestamps"] = 1.0

    # Compute overall as mean of the checks
    values = [v for k, v in scores.items()]
    overall = sum(values) / len(values) if values else 0.0
    scores["overall"] = overall

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()