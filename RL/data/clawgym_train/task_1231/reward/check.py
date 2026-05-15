import json
import sys
import re
from pathlib import Path
from html import unescape
from typing import Dict, List, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def load_simple_yaml(path: Path) -> Optional[Dict[str, str]]:
    text = read_text_safe(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            if len(val) >= 2:
                val = val[1:-1]
        data[key] = val
    return data


def load_keywords_csv(path: Path) -> Optional[List[str]]:
    text = read_text_safe(path)
    if text is None:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        idx = header.index("keyword")
    except ValueError:
        idx = 0
    keywords: List[str] = []
    for row in lines[1:]:
        parts = [p.strip() for p in row.split(",")]
        if idx < len(parts):
            kw = parts[idx].strip()
            if kw:
                keywords.append(kw)
    return keywords


def find_html_files(input_site_dir: Path) -> List[Path]:
    if not input_site_dir.exists():
        return []
    return sorted([p for p in input_site_dir.glob("*.html") if p.is_file()])


def strip_scripts_styles(html: str) -> str:
    no_script = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    no_style = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", no_script)
    return no_style


def html_text_content(html: str) -> str:
    cleaned = strip_scripts_styles(html)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def word_count_from_html(html: str) -> int:
    text = html_text_content(html)
    if not text:
        return 0
    tokens = [t for t in text.split() if re.search(r"[A-Za-z0-9]", t)]
    return len(tokens)


def find_all_titles(html: str) -> List[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?is)<title[^>]*>(.*?)</title>", html)]


def find_meta_content_by_name(html: str, name: str) -> List[str]:
    results = []
    for m in re.finditer(r'(?is)<meta\s+[^>]*name\s*=\s*["\']\s*' + re.escape(name) + r'\s*["\'][^>]*>', html):
        tag = m.group(0)
        cm = re.search(r'(?is)content\s*=\s*["\'](.*?)["\']', tag)
        if cm:
            results.append(cm.group(1).strip())
        else:
            results.append("")
    return results


def find_meta_content_by_property(html: str, prop: str) -> List[str]:
    results = []
    for m in re.finditer(r'(?is)<meta\s+[^>]*property\s*=\s*["\']\s*' + re.escape(prop) + r'\s*["\'][^>]*>', html):
        tag = m.group(0)
        cm = re.search(r'(?is)content\s*=\s*["\'](.*?)["\']', tag)
        if cm:
            results.append(cm.group(1).strip())
        else:
            results.append("")
    return results


def find_link_href_by_rel(html: str, rel: str) -> List[str]:
    results = []
    for m in re.finditer(r'(?is)<link\s+[^>]*rel\s*=\s*["\']\s*' + re.escape(rel) + r'\s*["\'][^>]*>', html):
        tag = m.group(0)
        hm = re.search(r'(?is)href\s*=\s*["\'](.*?)["\']', tag)
        if hm:
            results.append(hm.group(1).strip())
        else:
            results.append("")
    return results


def count_h1(html: str) -> int:
    return len(re.findall(r"(?is)<h1\b[^>]*>.*?</h1\s*>", html))


def parse_img_tags(html: str) -> List[str]:
    return [m.group(0) for m in re.finditer(r'(?is)<img\b[^>]*>', html)]


def has_nonempty_alt(img_tag: str) -> bool:
    m = re.search(r'(?is)\balt\s*=\s*["\'](.*?)["\']', img_tag)
    if not m:
        return False
    val = m.group(1)
    return val.strip() != ""


def count_imgs_missing_alt(html: str) -> int:
    imgs = parse_img_tags(html)
    missing = 0
    for img in imgs:
        if not has_nonempty_alt(img):
            missing += 1
    return missing


def count_keyword_occurrences(text: str, keyword: str) -> int:
    if not keyword:
        return 0
    text_lower = text.lower()
    key_lower = keyword.lower()
    count = 0
    i = 0
    while True:
        idx = text_lower.find(key_lower, i)
        if idx == -1:
            break
        count += 1
        i = idx + len(key_lower)
    return count


def extract_jsonld_objects(html: str) -> List[dict]:
    objs: List[dict] = []
    for m in re.finditer(r'(?is)<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', html):
        content = m.group(1).strip()
        try:
            loaded = json.loads(content)
            if isinstance(loaded, list):
                for item in loaded:
                    if isinstance(item, dict):
                        objs.append(item)
            elif isinstance(loaded, dict):
                objs.append(loaded)
        except Exception:
            continue
    return objs


def validate_jsonld_thesis(obj: dict, meta: Dict[str, str]) -> bool:
    atype = obj.get("@type")
    has_thesis = False
    if isinstance(atype, str):
        has_thesis = atype.lower() == "thesis"
    elif isinstance(atype, list):
        has_thesis = any(isinstance(t, str) and t.lower() == "thesis" for t in atype)
    if not has_thesis:
        return False
    name = obj.get("name")
    if not isinstance(name, str) or name.strip() != meta.get("title", "").strip():
        return False
    author = obj.get("author")
    author_ok = False
    if isinstance(author, str):
        if author.strip() == meta.get("author", "").strip():
            author_ok = True
    elif isinstance(author, dict):
        aname = author.get("name")
        aid = author.get("identifier") or author.get("id") or author.get("@id")
        if isinstance(aname, str) and aname.strip() == meta.get("author", "").strip():
            orcid = meta.get("orcid", "").strip()
            if orcid:
                if isinstance(aid, str) and orcid in aid:
                    author_ok = True
                elif isinstance(aid, list) and any(isinstance(v, str) and orcid in v for v in aid):
                    author_ok = True
                else:
                    author_ok = False
            else:
                author_ok = True
    if not author_ok:
        return False
    if meta.get("language"):
        if obj.get("inLanguage") != meta.get("language"):
            return False
    if meta.get("year"):
        if obj.get("datePublished") != meta.get("year"):
            return False
    doi = meta.get("doi", "").strip()
    if doi:
        ident = obj.get("identifier")
        if ident != doi:
            return False
    uni = meta.get("university", "").strip()
    pub = obj.get("publisher")
    pub_ok = False
    if isinstance(pub, str):
        pub_ok = pub.strip() == uni
    elif isinstance(pub, dict):
        pname = pub.get("name")
        if isinstance(pname, str) and pname.strip() == uni:
            pub_ok = True
    if not pub_ok:
        return False
    return True


def build_expected_canonical(base_url: str, filename: str) -> str:
    return base_url.rstrip("/") + "/" + filename


def extract_section(content: str, heading: str) -> Optional[str]:
    lines = content.splitlines()
    indices = [i for i, l in enumerate(lines) if heading.lower() in l.lower()]
    if not indices:
        return None
    start = indices[0]
    end = len(lines)
    section_titles = [
        "Files processed",
        "Per-page metrics",
        "Keyword coverage",
        "Coverage summary",
        "Changes made",
    ]
    for i in range(start + 1, len(lines)):
        for t in section_titles:
            if t.lower() in lines[i].lower():
                end = i
                return "\n".join(lines[start:end])
    return "\n".join(lines[start:end])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_site_files_present": 0.0,
        "title_unique_and_single": 0.0,
        "meta_description_presence_and_keyword": 0.0,
        "h1_single_presence": 0.0,
        "canonical_tag_correct": 0.0,
        "meta_robots_index_follow": 0.0,
        "opengraph_tags_presence": 0.0,
        "dissertation_jsonld_thesis": 0.0,
        "images_alt_text_added": 0.0,
        "sitemap_xml_correct": 0.0,
        "robots_txt_correct": 0.0,
        "seo_report_md_sections": 0.0,
        "seo_summary_json_consistency": 0.0,
    }

    input_site = workspace / "input" / "site"
    output_site = workspace / "output" / "site"
    input_files = find_html_files(input_site)
    input_filenames = [p.name for p in input_files]

    metadata_path = workspace / "input" / "metadata.yaml"
    keywords_path = workspace / "input" / "keywords.csv"
    meta = load_simple_yaml(metadata_path) or {}
    keywords = load_keywords_csv(keywords_path) or []

    output_files = []
    if output_site.exists():
        output_files = sorted([p for p in output_site.glob("*.html") if p.is_file()])
    output_filenames = [p.name for p in output_files]

    if input_filenames and output_filenames and set(output_filenames) >= set(input_filenames):
        scores["output_site_files_present"] = 1.0
    else:
        scores["output_site_files_present"] = 0.0

    input_html_map: Dict[str, str] = {p.name: (read_text_safe(p) or "") for p in input_files}
    output_html_map: Dict[str, str] = {p.name: (read_text_safe(p) or "") for p in output_files}

    titles = {}
    titles_ok = True
    for fname in input_filenames:
        html = output_html_map.get(fname, "")
        if not html:
            titles_ok = False
            continue
        ts = find_all_titles(html)
        if len(ts) != 1 or not ts[0].strip():
            titles_ok = False
        else:
            titles[fname] = ts[0].strip()
    if titles_ok and len(set(titles.values())) == len(input_filenames) and len(titles) == len(input_filenames):
        scores["title_unique_and_single"] = 1.0

    desc_ok_all = True
    for fname in input_filenames:
        out_html = output_html_map.get(fname, "")
        in_html = input_html_map.get(fname, "")
        if not out_html or not in_html:
            desc_ok_all = False
            continue
        descs = find_meta_content_by_name(out_html, "description")
        if len(descs) < 1 or not descs[0].strip():
            desc_ok_all = False
            continue
        desc_text = descs[0].strip().lower()
        page_text_in = html_text_content(in_html).lower()
        present_kws = [kw for kw in keywords if kw.lower() in page_text_in]
        if not present_kws:
            desc_ok_all = False
            continue
        if not any(kw.lower() in desc_text for kw in present_kws):
            desc_ok_all = False
    if desc_ok_all and input_filenames:
        scores["meta_description_presence_and_keyword"] = 1.0

    h1_ok = True
    for fname in input_filenames:
        html = output_html_map.get(fname, "")
        if not html:
            h1_ok = False
            continue
        if count_h1(html) != 1:
            h1_ok = False
    if h1_ok and input_filenames:
        scores["h1_single_presence"] = 1.0

    canonical_ok = True
    base_url = meta.get("base_url", "")
    if not base_url:
        canonical_ok = False
    for fname in input_filenames:
        html = output_html_map.get(fname, "")
        if not html or not base_url:
            canonical_ok = False
            continue
        hrefs = find_link_href_by_rel(html, "canonical")
        expected = build_expected_canonical(base_url, fname)
        if len(hrefs) != 1 or hrefs[0] != expected:
            canonical_ok = False
    if canonical_ok and input_filenames:
        scores["canonical_tag_correct"] = 1.0

    robots_meta_ok = True
    for fname in input_filenames:
        html = output_html_map.get(fname, "")
        if not html:
            robots_meta_ok = False
            continue
        metas = find_meta_content_by_name(html, "robots")
        if not metas:
            robots_meta_ok = False
            continue
        has_index_follow = any(re.search(r"\bindex\b", c, re.I) and re.search(r"\bfollow\b", c, re.I) for c in metas)
        if not has_index_follow:
            robots_meta_ok = False
    if robots_meta_ok and input_filenames:
        scores["meta_robots_index_follow"] = 1.0

    og_ok = True
    for fname in input_filenames:
        html = output_html_map.get(fname, "")
        if not html:
            og_ok = False
            continue
        ogt = find_meta_content_by_property(html, "og:title")
        ogd = find_meta_content_by_property(html, "og:description")
        ogtype = find_meta_content_by_property(html, "og:type")
        if not ogt or not ogd or not ogtype:
            og_ok = False
    if og_ok and input_filenames:
        scores["opengraph_tags_presence"] = 1.0

    jsonld_ok = False
    if "dissertation.html" in input_filenames:
        out_html = output_html_map.get("dissertation.html", "")
        if out_html and meta:
            objs = extract_jsonld_objects(out_html)
            for obj in objs:
                if validate_jsonld_thesis(obj, meta):
                    jsonld_ok = True
                    break
    scores["dissertation_jsonld_thesis"] = 1.0 if jsonld_ok else 0.0

    imgs_ok = True
    for fname in input_filenames:
        in_html = input_html_map.get(fname, "")
        out_html = output_html_map.get(fname, "")
        if not out_html or not in_html:
            imgs_ok = False
            continue
        before = count_imgs_missing_alt(in_html)
        after = count_imgs_missing_alt(out_html)
        if before > 0:
            if after != 0:
                imgs_ok = False
        else:
            if after != 0:
                imgs_ok = False
    if imgs_ok and input_filenames:
        scores["images_alt_text_added"] = 1.0

    sitemap_ok = False
    sitemap_path = workspace / "output" / "sitemap.xml"
    sitemap_text = read_text_safe(sitemap_path)
    if sitemap_text and base_url:
        locs = re.findall(r"(?is)<loc>\s*(.*?)\s*</loc>", sitemap_text)
        expected_locs = [build_expected_canonical(base_url, fn) for fn in input_filenames]
        sitemap_ok = set(locs) == set(expected_locs) and len(locs) == len(expected_locs)
    scores["sitemap_xml_correct"] = 1.0 if sitemap_ok else 0.0

    robots_ok = False
    robots_path = workspace / "output" / "robots.txt"
    robots_text = read_text_safe(robots_path)
    if robots_text and base_url:
        lines = [l.strip() for l in robots_text.strip().splitlines() if l.strip() != ""]
        expected_lines = [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {base_url.rstrip('/')}/sitemap.xml",
        ]
        robots_ok = lines == expected_lines
    scores["robots_txt_correct"] = 1.0 if robots_ok else 0.0

    report_ok = False
    report_path = workspace / "output" / "seo_report.md"
    report_text = read_text_safe(report_path)
    if report_text:
        needed_sections = [
            "Files processed",
            "Per-page metrics",
            "Keyword coverage",
            "Coverage summary",
            "Changes made",
        ]
        has_sections = all(s.lower() in report_text.lower() for s in needed_sections)
        has_files = all(fn in report_text for fn in input_filenames)
        report_ok = has_sections and has_files
    scores["seo_report_md_sections"] = 1.0 if report_ok else 0.0

    summary_ok = False
    summary_path = workspace / "output" / "seo_summary.json"
    summary_text = read_text_safe(summary_path)
    if summary_text:
        try:
            summary = json.loads(summary_text)
        except Exception:
            summary = None
        if isinstance(summary, dict):
            req_keys = [
                "total_pages",
                "pages_fixed",
                "total_word_count",
                "keywords_total",
                "keywords_covered",
                "coverage_ratio",
                "keyword_counts_by_page",
                "per_page_metrics",
            ]
            if all(k in summary for k in req_keys) and isinstance(summary.get("keyword_counts_by_page"), dict) and isinstance(summary.get("per_page_metrics"), list):
                total_pages = summary.get("total_pages")
                n_pages = len(input_filenames)
                changed_count = 0
                for fn in input_filenames:
                    in_html = input_html_map.get(fn, "")
                    out_html = output_html_map.get(fn, "")
                    if out_html and in_html and out_html != in_html:
                        changed_count += 1
                recomputed_word_sum = sum(word_count_from_html(output_html_map.get(fn, "")) for fn in input_filenames)
                k_total = len(keywords)
                kcounts_by_page_expected: Dict[str, Dict[str, int]] = {}
                for fn in input_filenames:
                    out_html = output_html_map.get(fn, "")
                    text = html_text_content(out_html) if out_html else ""
                    page_counts: Dict[str, int] = {}
                    for kw in keywords:
                        page_counts[kw] = count_keyword_occurrences(text, kw)
                    kcounts_by_page_expected[fn] = page_counts
                site_counts: Dict[str, int] = {}
                for kw in keywords:
                    total_count = sum(kcounts_by_page_expected.get(fn, {}).get(kw, 0) for fn in input_filenames)
                    site_counts[kw] = total_count
                k_covered = sum(1 for kw, c in site_counts.items() if c > 0)
                cov_ratio = (k_covered / k_total) if k_total > 0 else 0.0
                per_page_metrics_expected: Dict[str, Dict[str, int]] = {}
                for fn in input_filenames:
                    in_html = input_html_map.get(fn, "")
                    out_html = output_html_map.get(fn, "")
                    if not out_html:
                        continue
                    metrics = {
                        "word_count": word_count_from_html(out_html),
                        "title_length": len(find_all_titles(out_html)[0]) if find_all_titles(out_html) else 0,
                        "description_length": len(find_meta_content_by_name(out_html, "description")[0]) if find_meta_content_by_name(out_html, "description") else 0,
                        "h1_count": count_h1(out_html),
                        "images_without_alt_before": count_imgs_missing_alt(in_html) if in_html else 0,
                        "images_without_alt_after": count_imgs_missing_alt(out_html),
                    }
                    per_page_metrics_expected[fn] = metrics
                try:
                    conds = []
                    conds.append(isinstance(total_pages, int) and total_pages == n_pages)
                    conds.append(isinstance(summary.get("pages_fixed"), int) and summary.get("pages_fixed") == changed_count)
                    conds.append(isinstance(summary.get("total_word_count"), int) and summary.get("total_word_count") == recomputed_word_sum)
                    conds.append(isinstance(summary.get("keywords_total"), int) and summary.get("keywords_total") == k_total)
                    conds.append(isinstance(summary.get("keywords_covered"), int) and summary.get("keywords_covered") == k_covered)
                    cov_val = summary.get("coverage_ratio")
                    conds.append(isinstance(cov_val, (int, float)) and abs(cov_val - cov_ratio) <= 1e-6)
                    kc = summary.get("keyword_counts_by_page")
                    conds.append(set(kc.keys()) == set(input_filenames))
                    kc_match = True
                    for fn in input_filenames:
                        map_expected = kcounts_by_page_expected.get(fn, {})
                        actual_map = kc.get(fn, {})
                        if set(actual_map.keys()) != set(map_expected.keys()):
                            kc_match = False
                            break
                        for kw in keywords:
                            if int(actual_map.get(kw, -1)) != int(map_expected.get(kw, -1)):
                                kc_match = False
                                break
                        if not kc_match:
                            break
                    conds.append(kc_match)
                    pms: List[dict] = summary.get("per_page_metrics")
                    pm_match = True
                    if len(pms) != n_pages:
                        pm_match = False
                    else:
                        for obj in pms:
                            if not isinstance(obj, dict):
                                pm_match = False
                                break
                            for key in ["word_count", "title_length", "description_length", "h1_count", "images_without_alt_before", "images_without_alt_after"]:
                                if key not in obj:
                                    pm_match = False
                                    break
                            if not pm_match:
                                break
                        if pm_match:
                            filename_key = None
                            for k in ["filename", "file", "page", "name"]:
                                if isinstance(pms[0], dict) and k in pms[0]:
                                    filename_key = k
                                    break
                            if filename_key:
                                unmatched_expected = per_page_metrics_expected.copy()
                                for obj in pms:
                                    fn = obj.get(filename_key)
                                    if fn in unmatched_expected:
                                        exp = unmatched_expected[fn]
                                        for key in exp:
                                            if int(obj.get(key)) != int(exp.get(key)):
                                                pm_match = False
                                                break
                                        if not pm_match:
                                            break
                                        del unmatched_expected[fn]
                                if unmatched_expected:
                                    pm_match = False
                            else:
                                expected_list = list(per_page_metrics_expected.items())
                                used_indices = set()
                                for obj in pms:
                                    found = False
                                    for i, (fn, exp) in enumerate(expected_list):
                                        if i in used_indices:
                                            continue
                                        if all(int(obj.get(k)) == int(exp.get(k)) for k in exp.keys()):
                                            used_indices.add(i)
                                            found = True
                                            break
                                    if not found:
                                        pm_match = False
                                        break
                    conds.append(pm_match)
                    summary_ok = all(conds)
                except Exception:
                    summary_ok = False
    scores["seo_summary_json_consistency"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()