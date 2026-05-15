import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_jsonl(path: Path):
    items = []
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None, f"malformed_json_line_{i}"
                if not isinstance(obj, dict):
                    return None, f"non_object_line_{i}"
                items.append(obj)
        return items, None
    except Exception as e:
        return None, f"error:{e}"


def _load_json(path: Path):
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"error:{e}"


def _parse_queries_yaml_simple(path: Path):
    """
    Minimal parser for the provided YAML structure.
    Expects:
    queries:
      - name: "..."
        query: "..."
        required_domain: "..."
    Returns list of dicts with keys name, query, required_domain.
    """
    if not path.exists():
        return None, "missing"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return None, f"error:{e}"
    items = []
    in_queries = False
    current = None
    for raw in lines:
        line = raw.rstrip()
        if not in_queries:
            if re.match(r'^\s*queries\s*:', line):
                in_queries = True
            continue
        m_item_inline = re.match(r'^\s*-\s*(\w+)\s*:\s*([\'"])(.*)\2\s*$', line)
        m_item_dash_only = re.match(r'^\s*-\s*$', line)
        if m_item_inline:
            if current:
                items.append(current)
            current = {}
            key = m_item_inline.group(1)
            val = m_item_inline.group(3)
            current[key] = val
            continue
        elif m_item_dash_only:
            if current:
                items.append(current)
            current = {}
            continue
        m_kv_dq = re.match(r'^\s*(\w+)\s*:\s*"(.*)"\s*$', line)
        m_kv_sq = re.match(r'^\s*(\w+)\s*:\s*\'(.*)\'\s*$', line)
        if current is not None and (m_kv_dq or m_kv_sq):
            m = m_kv_dq or m_kv_sq
            key = m.group(1)
            val = m.group(2)
            current[key] = val
            continue
        if current is not None and re.match(r'^\S', line) and not line.strip().startswith('-'):
            if current:
                items.append(current)
            current = None
            in_queries = False
    if current:
        items.append(current)
    cleaned = []
    for it in items:
        if isinstance(it, dict) and 'query' in it and 'required_domain' in it and 'name' in it:
            cleaned.append({'name': it['name'], 'query': it['query'], 'required_domain': it['required_domain']})
    if not cleaned:
        return None, "parsed_empty_or_malformed"
    return cleaned, None


def _is_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    s = ts.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _domain_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        if host.startswith('www.'):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_absolute_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _domain_matches_required(url: str, required_domain: str) -> bool:
    udom = _domain_from_url(url)
    rd = (required_domain or "").lower()
    return udom == rd or udom.endswith("." + rd)


def _list_html_files(raw_html_root: Path):
    files = []
    if not raw_html_root.exists():
        return files
    for p in raw_html_root.rglob("*.html"):
        if p.is_file():
            files.append(p)
    return files


def _count_files_by_domain(raw_html_root: Path):
    counts = {}
    files = _list_html_files(raw_html_root)
    for f in files:
        try:
            parent = f.parent
            domain = parent.name
            counts[domain] = counts.get(domain, 0) + 1
        except Exception:
            continue
    return counts


def _paths_are_relative(paths):
    for p in paths:
        if not isinstance(p, str):
            return False
        if Path(p).is_absolute():
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "readme_instructions_docker_and_local": 0.0,
        "runtime_env_provided": 0.0,
        "search_log_has_one_record_per_query": 0.0,
        "search_log_fields_valid": 0.0,
        "chosen_urls_match_required_domains": 0.0,
        "items_jsonl_present_and_well_formed": 0.0,
        "items_fields_valid_types": 0.0,
        "items_source_domain_matches_url_domain": 0.0,
        "raw_html_structure_domain_subdirs": 0.0,
        "html_files_count_matches_selected": 0.0,
        "manifest_present_and_fields": 0.0,
        "manifest_counts_consistent": 0.0,
        "cross_validation_items_logs": 0.0,
        "cross_validation_items_raw_html": 0.0,
    }

    # Load queries from input YAML
    queries_path = workspace / "input" / "input_queries.yaml"
    queries, q_err = _parse_queries_yaml_simple(queries_path)
    if queries is None:
        queries = []
    queries_by_query = {q["query"]: q for q in queries}
    required_by_query = {q["query"]: q["required_domain"] for q in queries}
    num_queries = len(queries)

    # Check README instructions for both local and Docker runs
    readme_path = workspace / "README.md"
    readme_text = _read_text(readme_path)
    if readme_text:
        lower = readme_text.lower()
        has_docker = ("docker build" in lower) and ("docker run" in lower) and ("newcastle-snapshot" in readme_text)
        has_local = ("requirements.txt" in readme_text) and (("python " in lower) or ("python3 " in lower) or ("pip install" in lower))
        if has_docker and has_local:
            scores["readme_instructions_docker_and_local"] = 1.0

    # Check runtime env files (Dockerfile OR requirements.txt + run script)
    dockerfile = workspace / "Dockerfile"
    requirements = workspace / "requirements.txt"
    possible_run_scripts = [
        workspace / "run.sh",
        workspace / "run.py",
        workspace / "main.py",
        workspace / "scripts" / "run.sh",
        workspace / "scripts" / "run.py",
    ]
    has_run_script = any(p.exists() for p in possible_run_scripts)
    if dockerfile.exists():
        scores["runtime_env_provided"] = 1.0
    elif requirements.exists() and has_run_script:
        scores["runtime_env_provided"] = 1.0

    # Load search log
    logs_path = workspace / "logs" / "search_log.jsonl"
    logs, log_err = _load_jsonl(logs_path)
    if logs is None:
        logs = []
    # Evaluate search_log_has_one_record_per_query
    if num_queries > 0 and len(logs) == num_queries:
        log_queries = [rec.get("query") for rec in logs if isinstance(rec, dict)]
        if set(log_queries) == set(queries_by_query.keys()):
            scores["search_log_has_one_record_per_query"] = 1.0

    # Validate fields in logs
    valid_count = 0
    for rec in logs:
        if not isinstance(rec, dict):
            continue
        q = rec.get("query")
        ts = rec.get("timestamp")
        engine = rec.get("search_engine")
        topn = rec.get("top_n")
        if not isinstance(topn, int):
            topn = rec.get("top_n_considered")
        chosen_urls_field = rec.get("chosen_urls")
        chosen_url_single = rec.get("chosen_url")
        if isinstance(chosen_urls_field, list):
            chosen_urls = chosen_urls_field
        elif isinstance(chosen_url_single, str):
            chosen_urls = [chosen_url_single]
        else:
            chosen_urls = None
        if (
            isinstance(q, str) and q in queries_by_query and
            isinstance(engine, str) and engine.strip() and
            isinstance(topn, int) and topn >= 5 and
            isinstance(ts, str) and _is_iso8601(ts) and
            isinstance(chosen_urls, list) and len(chosen_urls) >= 1 and
            all(isinstance(u, str) and _is_absolute_http_url(u) for u in chosen_urls)
        ):
            valid_count += 1
    if len(logs) > 0:
        scores["search_log_fields_valid"] = valid_count / len(logs)

    # chosen_urls match required domain for at least one per query
    match_count = 0
    for rec in logs:
        if not isinstance(rec, dict):
            continue
        q = rec.get("query")
        chosen_urls_field = rec.get("chosen_urls")
        chosen_url_single = rec.get("chosen_url")
        chosen_urls = []
        if isinstance(chosen_urls_field, list):
            chosen_urls = [u for u in chosen_urls_field if isinstance(u, str)]
        elif isinstance(chosen_url_single, str):
            chosen_urls = [chosen_url_single]
        required_dom = required_by_query.get(q)
        if not required_dom:
            continue
        if any(_domain_matches_required(u, required_dom) for u in chosen_urls):
            match_count += 1
    if num_queries > 0:
        scores["chosen_urls_match_required_domains"] = match_count / num_queries

    # Load items.jsonl
    items_path = workspace / "output" / "extracted" / "items.jsonl"
    items, items_err = _load_jsonl(items_path)
    if items is None:
        items = []
    # Presence and basic well-formedness
    if len(items) > 0:
        scores["items_jsonl_present_and_well_formed"] = 1.0

    # Validate items fields and types
    item_valids = 0
    source_domain_matches = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        has_fields = all(k in it for k in ["source_domain", "source_url", "page_title", "h1", "emails", "phones", "pdf_links", "retrieved_at"])
        if not has_fields:
            continue
        sd_ok = isinstance(it.get("source_domain"), str) and it.get("source_domain") != ""
        su_ok = isinstance(it.get("source_url"), str) and _is_absolute_http_url(it.get("source_url"))
        pt = it.get("page_title")
        h1 = it.get("h1")
        pt_ok = (pt is None) or isinstance(pt, str)
        h1_ok = (h1 is None) or isinstance(h1, str)
        emails = it.get("emails")
        phones = it.get("phones")
        pdfs = it.get("pdf_links")
        emails_ok = isinstance(emails, list) and all(isinstance(e, str) for e in emails)
        phones_ok = isinstance(phones, list) and all(isinstance(p, str) for p in phones)
        pdfs_ok = isinstance(pdfs, list) and all(isinstance(p, str) and _is_absolute_http_url(p) and urlparse(p).path.lower().endswith(".pdf") for p in pdfs)
        rt = it.get("retrieved_at")
        rt_ok = isinstance(rt, str) and _is_iso8601(rt)
        if sd_ok and su_ok and pt_ok and h1_ok and emails_ok and phones_ok and pdfs_ok and rt_ok:
            item_valids += 1
        src_dom = (it.get("source_domain") or "").lower()
        src_dom_clean = src_dom[4:] if src_dom.startswith("www.") else src_dom
        url_dom = _domain_from_url(it.get("source_url") or "")
        if src_dom_clean == url_dom and url_dom != "":
            source_domain_matches += 1
    if len(items) > 0:
        scores["items_fields_valid_types"] = item_valids / len(items)
        scores["items_source_domain_matches_url_domain"] = source_domain_matches / len(items)

    # Raw HTML structure and counts
    raw_html_root = workspace / "output" / "raw_html"
    html_files = _list_html_files(raw_html_root)
    if len(html_files) > 0:
        struct_ok = 0
        for f in html_files:
            parent = f.parent
            if parent == raw_html_root:
                continue
            domain_name = parent.name
            if isinstance(domain_name, str) and "." in domain_name and len(domain_name) > 1:
                struct_ok += 1
        if struct_ok == len(html_files):
            scores["raw_html_structure_domain_subdirs"] = 1.0

    # Compute selected URLs set across logs (unique)
    selected_urls = set()
    for rec in logs:
        if isinstance(rec, dict):
            chosen_urls_field = rec.get("chosen_urls")
            chosen_url_single = rec.get("chosen_url")
            urls = []
            if isinstance(chosen_urls_field, list):
                urls = [u for u in chosen_urls_field if isinstance(u, str)]
            elif isinstance(chosen_url_single, str):
                urls = [chosen_url_single]
            for u in urls:
                if _is_absolute_http_url(u):
                    selected_urls.add(u)

    unique_selected_count = len(selected_urls)
    if unique_selected_count > 0 and len(items) == unique_selected_count and len(html_files) == unique_selected_count:
        scores["html_files_count_matches_selected"] = 1.0

    # Manifest checks
    manifest_path = workspace / "output" / "manifest.json"
    manifest, man_err = _load_json(manifest_path)
    if isinstance(manifest, dict):
        keys_ok = all(k in manifest for k in ["queries_total", "pages_downloaded", "pages_per_domain", "html_files", "items_records"])
        types_ok = (
            isinstance(manifest.get("queries_total"), int) and
            isinstance(manifest.get("pages_downloaded"), int) and
            isinstance(manifest.get("items_records"), int) and
            isinstance(manifest.get("pages_per_domain"), dict) and
            isinstance(manifest.get("html_files"), list)
        )
        html_files_list = manifest.get("html_files") if isinstance(manifest.get("html_files"), list) else []
        html_files_list_ok = isinstance(html_files_list, list) and all(isinstance(x, str) for x in html_files_list)
        if keys_ok and types_ok and html_files_list_ok:
            scores["manifest_present_and_fields"] = 1.0

        consistent = True
        if manifest.get("queries_total") != num_queries:
            consistent = False
        if manifest.get("items_records") != len(items):
            consistent = False
        if manifest.get("pages_downloaded") != len(items) or manifest.get("pages_downloaded") != unique_selected_count:
            consistent = False
        if isinstance(manifest.get("html_files"), list):
            if len(manifest.get("html_files")) != len(items):
                consistent = False
        else:
            consistent = False
        if isinstance(manifest.get("html_files"), list):
            if not _paths_are_relative(manifest.get("html_files")):
                consistent = False
            for rel in manifest.get("html_files"):
                p = workspace / rel
                if not p.exists() or not p.is_file() or p.suffix.lower() != ".html":
                    consistent = False
                try:
                    rp = p.resolve()
                    rr = raw_html_root.resolve()
                    if rr not in rp.parents and rp != rr:
                        consistent = False
                except Exception:
                    consistent = False
        ppd = manifest.get("pages_per_domain")
        if isinstance(ppd, dict):
            counts_from_items = {}
            for it in items:
                if isinstance(it, dict):
                    dom = (it.get("source_domain") or "").lower()
                    if dom:
                        counts_from_items[dom] = counts_from_items.get(dom, 0) + 1
            counts_from_files = _count_files_by_domain(raw_html_root)
            sum_ppd = sum(v for v in ppd.values() if isinstance(v, int))
            if sum_ppd != len(items) or sum_ppd != len(html_files):
                consistent = False

            def _normalize_dom(d):
                d = (d or "").lower()
                return d[4:] if d.startswith("www.") else d

            manifest_doms = {_normalize_dom(k) for k in ppd.keys()}
            file_doms = {_normalize_dom(k) for k in counts_from_files.keys()}
            item_doms = {_normalize_dom(k) for k in counts_from_items.keys()}
            if manifest_doms != file_doms or manifest_doms != item_doms:
                consistent = False
            for d in manifest_doms:
                man_count = 0
                for k, v in ppd.items():
                    if _normalize_dom(k) == d and isinstance(v, int):
                        man_count += v
                file_count = 0
                for k, v in counts_from_files.items():
                    if _normalize_dom(k) == d:
                        file_count += v
                if man_count != file_count:
                    consistent = False
        else:
            consistent = False

        if consistent:
            scores["manifest_counts_consistent"] = 1.0

    # Cross-validation: items <-> logs (selected URLs)
    if len(items) > 0 and len(selected_urls) > 0:
        items_urls = [it.get("source_url") for it in items if isinstance(it, dict)]
        covered = sum(1 for u in selected_urls if u in items_urls)
        forward_ratio = covered / len(selected_urls) if len(selected_urls) > 0 else 0.0
        chosen_set = set(selected_urls)
        backward_covered = sum(1 for u in items_urls if isinstance(u, str) and u in chosen_set)
        backward_ratio = backward_covered / len(items_urls) if len(items_urls) > 0 else 0.0
        scores["cross_validation_items_logs"] = (forward_ratio + backward_ratio) / 2.0

    # Cross-validation: items -> raw_html by domain presence
    if len(items) > 0 and len(html_files) > 0:
        files_by_domain = {}
        for f in html_files:
            dom = f.parent.name.lower()
            files_by_domain.setdefault(dom, 0)
            files_by_domain[dom] += 1
        ok_count = 0
        for it in items:
            dom = (it.get("source_domain") or "").lower()
            dom_norm = dom[4:] if dom.startswith("www.") else dom
            has_files = (dom in files_by_domain) or (dom_norm in files_by_domain)
            if has_files:
                ok_count += 1
        if len(items) > 0:
            scores["cross_validation_items_raw_html"] = ok_count / len(items)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()