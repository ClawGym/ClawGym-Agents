import csv
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Dict, List, Tuple, Optional, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _parse_yaml_domains(path: Path) -> Optional[List[str]]:
    """
    Very simple YAML parser for the expected structure:
    domains:
      - domain1
      - domain2
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    domains: List[str] = []
    in_domains = False
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_domains:
            if stripped.startswith("domains:"):
                in_domains = True
            continue
        if stripped.startswith("- "):
            domains.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("- "):
            break
    if not domains:
        return None
    return domains


def _read_keywords_csv(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if "keyword" not in rdr.fieldnames:
                return None
            kws = []
            for row in rdr:
                kw = (row.get("keyword") or "").strip()
                if kw != "":
                    kws.append(kw)
            if not kws:
                return None
            return kws
    except Exception:
        return None


def _ns_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_sitemap_xml(path: Path) -> Optional[Dict]:
    """
    Returns:
    - {"type": "urlset", "urls": [(loc, lastmod or "") ...]} or
    - {"type": "sitemapindex", "sitemaps": [loc, ...]}
    """
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        root_tag = _ns_tag(root.tag).lower()
        if root_tag == "urlset":
            urls: List[Tuple[str, str]] = []
            for url_el in root.findall(".//*"):
                if _ns_tag(url_el.tag).lower() == "url":
                    loc_text = ""
                    lastmod_text = ""
                    for child in list(url_el):
                        tag = _ns_tag(child.tag).lower()
                        if tag == "loc":
                            loc_text = (child.text or "").strip()
                        elif tag == "lastmod":
                            lastmod_text = (child.text or "").strip()
                    if loc_text:
                        urls.append((loc_text, lastmod_text))
            return {"type": "urlset", "urls": urls}
        elif root_tag == "sitemapindex":
            locs: List[str] = []
            for sm_el in root.findall(".//*"):
                if _ns_tag(sm_el.tag).lower() == "sitemap":
                    loc_text = ""
                    for child in list(sm_el):
                        if _ns_tag(child.tag).lower() == "loc":
                            loc_text = (child.text or "").strip()
                    if loc_text:
                        locs.append(loc_text)
            return {"type": "sitemapindex", "sitemaps": locs}
        else:
            return {"type": "unknown"}
    except Exception:
        return None


def _list_sitemap_xmls(sitemaps_dir: Path) -> List[Path]:
    if not sitemaps_dir.exists():
        return []
    return [p for p in sitemaps_dir.rglob("*.xml") if p.is_file()]


def _compute_domain_urls_from_sitemaps(sitemaps_dir: Path) -> Dict[str, Set[str]]:
    """
    Returns dict: url -> set of lastmod strings found (non-empty only).
    """
    url_lastmods: Dict[str, Set[str]] = {}
    for xml_path in _list_sitemap_xmls(sitemaps_dir):
        parsed = _parse_sitemap_xml(xml_path)
        if not parsed:
            continue
        if parsed.get("type") == "urlset":
            for loc, lastmod in parsed.get("urls", []):
                if loc:
                    s = url_lastmods.setdefault(loc, set())
                    if lastmod:
                        s.add(lastmod)
    return url_lastmods


def _load_inventory_csv(path: Path) -> Optional[Dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if rdr.fieldnames != ["url", "lastmod"]:
                return None
            inventory: Dict[str, str] = {}
            for row in rdr:
                url = (row.get("url") or "").strip()
                lastmod = (row.get("lastmod") or "").strip()
                if url == "":
                    return None
                if url in inventory:
                    return None
                inventory[url] = lastmod
            return inventory
    except Exception:
        return None


def _extract_robots_sitemap_count(robots_path: Path) -> Optional[int]:
    text = _read_text(robots_path)
    if text is None:
        return None
    count = 0
    for ln in text.splitlines():
        ln_stripped = ln.strip()
        if ln_stripped.lower().startswith("sitemap:"):
            count += 1
    return count


def _keyword_match_ordered(url: str, keywords: List[str]) -> List[str]:
    """
    Case-insensitive substring match. Returns keywords ordered by first occurrence position in URL.
    If two keywords have the same position, tie-break by their order in the keywords list.
    """
    url_l = url.lower()
    indexed: List[Tuple[int, int, str]] = []
    for i, kw in enumerate(keywords):
        kw_l = kw.lower()
        pos = url_l.find(kw_l)
        if pos >= 0:
            indexed.append((pos, i, kw))
    indexed.sort(key=lambda t: (t[0], t[1]))
    return [kw for _, _, kw in indexed]


def _load_matches_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if rdr.fieldnames != ["domain", "url", "lastmod", "matched_keywords"]:
                return None
            rows: List[Dict[str, str]] = []
            for row in rdr:
                d = {
                    "domain": (row.get("domain") or "").strip(),
                    "url": (row.get("url") or "").strip(),
                    "lastmod": (row.get("lastmod") or "").strip(),
                    "matched_keywords": (row.get("matched_keywords") or "").strip(),
                }
                if not d["domain"] or not d["url"]:
                    return None
                rows.append(d)
            return rows
    except Exception:
        return None


def _load_csv_as_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = []
            for row in rdr:
                rows.append({k: (v or "").strip() for k, v in row.items()})
            return rows
    except Exception:
        return None


def _round_rate(numer: int, denom: int) -> str:
    if denom <= 0:
        return "0.0000"
    rate = numer / denom
    return f"{rate:.4f}"


def _parse_errors_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        out.append(obj)
                except Exception:
                    continue
    except Exception:
        return []
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "robots_txt_saved": 0.0,
        "sitemaps_saved": 0.0,
        "robots_sitemap_entries_covered": 0.0,
        "sitemap_index_followed": 0.0,
        "url_inventory_headers_valid": 0.0,
        "url_inventory_completeness": 0.0,
        "matches_coverage_jaccard": 0.0,
        "matches_keywords_correctness": 0.0,
        "matches_lastmod_consistency": 0.0,
        "domain_metrics_header_valid": 0.0,
        "domain_metrics_values_correct": 0.0,
        "keyword_metrics_header_valid": 0.0,
        "keyword_metrics_values_correct": 0.0,
        "error_logging_consistency": 0.0,
    }

    domains_path = workspace / "input" / "domains.yaml"
    keywords_path = workspace / "input" / "keywords.csv"

    domains = _parse_yaml_domains(domains_path)
    keywords = _read_keywords_csv(keywords_path)

    if not domains or not isinstance(domains, list):
        return scores
    if not keywords or not isinstance(keywords, list):
        keywords = []

    robots_hits = 0
    for d in domains:
        robots_path = workspace / "output" / "raw" / d / "robots.txt"
        if robots_path.exists() and robots_path.is_file():
            robots_hits += 1
    scores["robots_txt_saved"] = robots_hits / len(domains) if domains else 0.0

    sitemaps_hits = 0
    covered_count = 0
    applicable_robots_domains = 0
    index_followed_ok = 0
    index_applicable = 0

    domain_xml_files: Dict[str, List[Path]] = {}
    for d in domains:
        sitemaps_dir = workspace / "output" / "raw" / d / "sitemaps"
        xmls = _list_sitemap_xmls(sitemaps_dir)
        domain_xml_files[d] = xmls
        if len(xmls) > 0:
            sitemaps_hits += 1

        robots_path = workspace / "output" / "raw" / d / "robots.txt"
        scount = _extract_robots_sitemap_count(robots_path) if robots_path.exists() else None
        if scount is not None:
            if scount > 0:
                applicable_robots_domains += 1
                if len(xmls) >= scount:
                    covered_count += 1

        referenced = 0
        local_index_count = 0
        for xp in xmls:
            parsed = _parse_sitemap_xml(xp)
            if parsed and parsed.get("type") == "sitemapindex":
                local_index_count += 1
                referenced += len(parsed.get("sitemaps", []))
        if local_index_count > 0:
            index_applicable += 1
            if referenced > 0 and len(xmls) >= referenced:
                index_followed_ok += 1

    scores["sitemaps_saved"] = sitemaps_hits / len(domains) if domains else 0.0
    scores["robots_sitemap_entries_covered"] = (covered_count / applicable_robots_domains) if applicable_robots_domains > 0 else 0.0
    scores["sitemap_index_followed"] = (index_followed_ok / index_applicable) if index_applicable > 0 else 0.0

    headers_ok = 0
    headers_total = 0
    completeness_ok = 0
    completeness_total = 0

    domain_urls_from_sitemaps: Dict[str, Dict[str, Set[str]]] = {}
    domain_inventory: Dict[str, Dict[str, str]] = {}

    for d in domains:
        sitemaps_dir = workspace / "output" / "raw" / d / "sitemaps"
        url_map = _compute_domain_urls_from_sitemaps(sitemaps_dir)
        domain_urls_from_sitemaps[d] = url_map

        inv_path = workspace / "output" / "urls" / f"{d}.csv"
        if inv_path.exists():
            headers_total += 1
            inv = _load_inventory_csv(inv_path)
            if inv is not None:
                headers_ok += 1
                domain_inventory[d] = inv
        if len(domain_xml_files.get(d, [])) > 0:
            completeness_total += 1
            inv = domain_inventory.get(d)
            if inv is None:
                continue
            inv_urls_set = set(inv.keys())
            expected_urls_set = set(url_map.keys())
            urls_equal = inv_urls_set == expected_urls_set
            lastmod_ok = True
            for url in expected_urls_set:
                s_lastmods = url_map.get(url, set())
                csv_lastmod = inv.get(url, "")
                if s_lastmods:
                    if csv_lastmod == "":
                        lastmod_ok = False
                        break
                else:
                    if csv_lastmod != "":
                        lastmod_ok = False
                        break
            if urls_equal and lastmod_ok:
                completeness_ok += 1

    scores["url_inventory_headers_valid"] = (headers_ok / headers_total) if headers_total > 0 else 0.0
    scores["url_inventory_completeness"] = (completeness_ok / completeness_total) if completeness_total > 0 else 0.0

    expected_matches: Dict[Tuple[str, str], Dict[str, str]] = {}
    domains_with_inventories = [d for d in domains if d in domain_inventory]
    for d in domains_with_inventories:
        inv = domain_inventory.get(d, {})
        for url, lastmod in inv.items():
            matched = _keyword_match_ordered(url, keywords) if keywords else []
            if matched:
                expected_matches[(d, url)] = {
                    "domain": d,
                    "url": url,
                    "lastmod": lastmod,
                    "matched_keywords": ";".join(matched),
                }

    matches_path = workspace / "output" / "matches" / "ai_pages.csv"
    actual_matches_rows = _load_matches_csv(matches_path) if matches_path.exists() else None

    expected_set = set(expected_matches.keys())
    actual_set: Set[Tuple[str, str]] = set()
    if actual_matches_rows:
        actual_set = set((r["domain"], r["url"]) for r in actual_matches_rows)

    if len(expected_set) == 0 and len(actual_set) == 0:
        scores["matches_coverage_jaccard"] = 0.0
    else:
        inter = len(expected_set & actual_set)
        union = len(expected_set | actual_set)
        scores["matches_coverage_jaccard"] = (inter / union) if union > 0 else 0.0

    if actual_matches_rows is None or len(actual_matches_rows) == 0:
        # If nothing produced, give 0 unless both expectations and results are non-empty
        if len(expected_set) == 0:
            scores["matches_keywords_correctness"] = 0.0
            scores["matches_lastmod_consistency"] = 0.0
        else:
            scores["matches_keywords_correctness"] = 0.0
            scores["matches_lastmod_consistency"] = 0.0
    else:
        correct_kw = 0
        correct_lm = 0
        total_rows = len(actual_matches_rows)
        for r in actual_matches_rows:
            k = (r["domain"], r["url"])
            exp = expected_matches.get(k)
            if exp:
                if r.get("matched_keywords", "") == exp.get("matched_keywords", ""):
                    correct_kw += 1
                if r.get("lastmod", "") == exp.get("lastmod", ""):
                    correct_lm += 1
        scores["matches_keywords_correctness"] = (correct_kw / total_rows) if total_rows > 0 else 0.0
        scores["matches_lastmod_consistency"] = (correct_lm / total_rows) if total_rows > 0 else 0.0

    domain_metrics_path = workspace / "output" / "summary" / "domain_metrics.csv"
    dm_rows = _load_csv_as_rows(domain_metrics_path) if domain_metrics_path.exists() else None

    dm_header_ok = 0.0
    try:
        with domain_metrics_path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            header = next(rdr, None)
            if header == ["domain", "total_urls", "matched_urls", "match_rate"]:
                dm_header_ok = 1.0
    except Exception:
        dm_header_ok = 0.0
    scores["domain_metrics_header_valid"] = dm_header_ok

    if dm_rows is None:
        scores["domain_metrics_values_correct"] = 0.0
    else:
        dm_by_domain: Dict[str, Dict[str, str]] = {}
        for r in dm_rows:
            d = r.get("domain", "")
            if d:
                dm_by_domain[d] = r

        correct_dm = 0
        total_dm = len(domains)
        for d in domains:
            inv = domain_inventory.get(d, {})
            total_urls = len(inv)
            matched_urls = len([1 for (dd, _url) in expected_matches.keys() if dd == d])
            expected_rate = _round_rate(matched_urls, total_urls)
            r = dm_by_domain.get(d)
            if r:
                try:
                    if (
                        r.get("domain") == d
                        and int(r.get("total_urls", "-1")) == total_urls
                        and int(r.get("matched_urls", "-1")) == matched_urls
                        and r.get("match_rate", "") == expected_rate
                    ):
                        correct_dm += 1
                except Exception:
                    pass
        scores["domain_metrics_values_correct"] = (correct_dm / total_dm) if total_dm > 0 else 0.0

    keyword_metrics_path = workspace / "output" / "summary" / "keyword_metrics.csv"
    km_rows = _load_csv_as_rows(keyword_metrics_path) if keyword_metrics_path.exists() else None

    km_header_ok = 0.0
    try:
        with keyword_metrics_path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.reader(f)
            header = next(rdr, None)
            if header == ["keyword", "total_matches", "domains_with_hits"]:
                km_header_ok = 1.0
    except Exception:
        km_header_ok = 0.0
    scores["keyword_metrics_header_valid"] = km_header_ok

    if km_rows is None or not keywords:
        scores["keyword_metrics_values_correct"] = 0.0
    else:
        expected_kw_totals: Dict[str, int] = {kw: 0 for kw in keywords}
        expected_kw_domains: Dict[str, Set[str]] = {kw: set() for kw in keywords}
        for (d, _url), meta in expected_matches.items():
            mk = meta.get("matched_keywords", "")
            found_kws = [k for k in mk.split(";") if k != ""]
            for kw in found_kws:
                if kw in expected_kw_totals:
                    expected_kw_totals[kw] += 1
                    expected_kw_domains[kw].add(d)
        km_by_kw: Dict[str, Dict[str, str]] = {}
        for r in km_rows:
            kw = r.get("keyword", "")
            if kw:
                km_by_kw[kw] = r
        correct_km = 0
        total_km = len(keywords)
        for kw in keywords:
            r = km_by_kw.get(kw)
            exp_total = expected_kw_totals.get(kw, 0)
            exp_domains = len(expected_kw_domains.get(kw, set()))
            if r:
                try:
                    if (
                        r.get("keyword") == kw
                        and int(r.get("total_matches", "-1")) == exp_total
                        and int(r.get("domains_with_hits", "-1")) == exp_domains
                    ):
                        correct_km += 1
                except Exception:
                    pass
        scores["keyword_metrics_values_correct"] = (correct_km / total_km) if total_km > 0 else 0.0

    errors_path = workspace / "output" / "logs" / "errors.jsonl"
    errors = _parse_errors_jsonl(errors_path)
    error_index: Dict[Tuple[str, str], List[Dict]] = {}
    for e in errors:
        d = e.get("domain")
        step = e.get("step")
        if d and step:
            error_index.setdefault((d, step), []).append(e)

    expected_error_instances = []
    for d in domains:
        robots_path = workspace / "output" / "raw" / d / "robots.txt"
        if not (robots_path.exists() and robots_path.is_file()):
            expected_error_instances.append((d, "robots"))
        xmls = domain_xml_files.get(d, [])
        if len(xmls) == 0:
            expected_error_instances.append((d, "sitemap"))

    if not expected_error_instances:
        scores["error_logging_consistency"] = 0.0
    else:
        ok = 0
        for inst in expected_error_instances:
            if inst in error_index and len(error_index[inst]) > 0:
                ok += 1
        scores["error_logging_consistency"] = ok / len(expected_error_instances)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()