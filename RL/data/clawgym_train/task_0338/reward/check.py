import sys
import json
import csv
import re
from datetime import datetime, date
from pathlib import Path
from xml.etree import ElementTree as ET


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _parse_simple_yaml_key(path: Path, key: str) -> str:
    text = _read_text(path)
    if not text:
        return ""
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*:\s*(.+?)\s*$', re.M)
    m = pattern.search(text)
    if not m:
        return ""
    raw = m.group(1).strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    return raw.strip()


def _iso8601_utc_ok(ts: str) -> bool:
    if not ts or not isinstance(ts, str):
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
            datetime.fromisoformat(s2)
            return True
        else:
            datetime.fromisoformat(s)
            return True
    except Exception:
        regex = re.compile(
            r"^\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?)?$"
        )
        return bool(regex.match(s))


def _extract_html_tag_content(html: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.I | re.S)
    return (m.group(1).strip() if m else "")


def _extract_meta_description(html: str) -> str:
    for m in re.finditer(r"<meta\b[^>]*>", html, flags=re.I | re.S):
        tag = m.group(0)
        name_m = re.search(r'name\s*=\s*["\']description["\']', tag, flags=re.I)
        if name_m:
            content_m = re.search(r'content\s*=\s*["\'](.*?)["\']', tag, flags=re.I | re.S)
            if content_m:
                return content_m.group(1).strip()
    return ""


def _extract_canonical_href(html: str) -> str:
    for m in re.finditer(r"<link\b[^>]*>", html, flags=re.I | re.S):
        tag = m.group(0)
        rel_m = re.search(r'rel\s*=\s*["\']canonical["\']', tag, flags=re.I)
        if rel_m:
            href_m = re.search(r'href\s*=\s*["\'](.*?)["\']', tag, flags=re.I | re.S)
            if href_m:
                return href_m.group(1).strip()
    return ""


def _count_tag_occurrences(html: str, tag: str) -> int:
    return len(re.findall(rf"<{tag}\b[^>]*>", html, flags=re.I))


def _extract_tag_texts(html: str, tag: str):
    return [m.strip() for m in re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.I | re.S)]


def _extract_faq_section(html: str) -> str:
    m = re.search(r'<section[^>]+id=["\']faq["\'][^>]*>(.*?)</section>', html, flags=re.I | re.S)
    return (m.group(1).strip() if m else "")


def _extract_jsonld_objects(html: str):
    objs = []
    for m in re.finditer(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
            objs.append(data)
        except Exception:
            continue
    return objs


def _jsonld_faq_questions(html: str):
    objs = _extract_jsonld_objects(html)
    questions = []

    def _collect_from(obj):
        if isinstance(obj, dict):
            atype = obj.get("@type")
            if isinstance(atype, list):
                is_faq = any(str(t).lower() == "faqpage" for t in atype)
            else:
                is_faq = (isinstance(atype, str) and atype.lower() == "faqpage")
            if is_faq:
                main = obj.get("mainEntity")
                if isinstance(main, list):
                    for q in main:
                        if isinstance(q, dict):
                            qtype = q.get("@type")
                            if isinstance(qtype, list):
                                is_q = any(str(t).lower() == "question" for t in qtype)
                            else:
                                is_q = (isinstance(qtype, str) and qtype.lower() == "question")
                            if is_q:
                                name = q.get("name") or q.get("question") or ""
                                if isinstance(name, str) and name.strip():
                                    questions.append(name.strip())
        elif isinstance(obj, list):
            for x in obj:
                _collect_from(x)

    for obj in objs:
        _collect_from(obj)
    return questions


def _count_phrase(text: str, phrase: str) -> int:
    if not text or not phrase:
        return 0
    t = text.lower()
    p = phrase.lower()
    count = 0
    i = 0
    while True:
        j = t.find(p, i)
        if j == -1:
            break
        count += 1
        i = j + len(p)
    return count


def _http_url_ok(u: str) -> bool:
    return isinstance(u, str) and (u.startswith("http://") or u.startswith("https://"))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "keyword_research_columns_and_header": 0.0,
        "keyword_research_row_counts": 0.0,
        "keyword_research_row_fields_valid": 0.0,
        "primary_keywords_in_csv_and_keyword_presence_json_valid": 0.0,
        "index_canonical_present_and_correct": 0.0,
        "index_title_starts_with_keyword": 0.0,
        "index_meta_description_includes_both_and_length": 0.0,
        "index_h1_single_and_contains_keyword": 0.0,
        "index_faq_section_two_pairs_and_relevance": 0.0,
        "index_jsonld_faqpage_matches_questions": 0.0,
        "about_word_count_and_keywords": 0.0,
        "about_tone_signal": 0.0,
        "robots_txt_valid": 0.0,
        "sitemap_xml_valid": 0.0,
        "seo_report_mentions_files_and_keywords": 0.0,
        "seo_report_includes_title_and_meta_description_values": 0.0,
    }

    config_path = workspace / "site" / "config.yaml"
    site_url = _parse_simple_yaml_key(config_path, "site_url")
    if site_url.endswith("/"):
        homepage_url = site_url
    else:
        homepage_url = site_url + "/" if site_url else ""
    about_url = site_url + "/about" if site_url else ""

    csv_path = workspace / "outputs" / "keyword_research.csv"
    rows = _load_csv_rows(csv_path)
    header_ok = False
    rows_ok = False
    fields_ok = False
    if rows is not None and len(rows) >= 1:
        header = rows[0]
        expected_header = ["query", "result_rank", "page_title", "result_url", "snippet", "fetch_timestamp"]
        if header == expected_header:
            header_ok = True
        data = rows[1:]
        if len(data) >= 15:
            queries_required = [
                "how to write punchlines",
                "tips for open mic night",
                "book a stand-up comedian",
            ]
            per_query_counts = {q: 0 for q in queries_required}
            for r in data:
                if len(r) != 6:
                    per_query_counts = {q: -999 for q in queries_required}
                    break
                qv = r[0].strip()
                if qv in per_query_counts:
                    per_query_counts[qv] += 1
            if all(count >= 5 for count in per_query_counts.values()):
                rows_ok = True

            if rows_ok:
                ranks_by_query = {}
                all_rows_valid = True
                for r in data:
                    if len(r) != 6:
                        all_rows_valid = False
                        break
                    q, rank_s, title, url, snippet, ts = [c.strip() for c in r]
                    if q not in queries_required:
                        all_rows_valid = False
                        break
                    try:
                        rank = int(rank_s)
                        if rank < 1:
                            all_rows_valid = False
                            break
                    except Exception:
                        all_rows_valid = False
                        break
                    if not title:
                        all_rows_valid = False
                        break
                    if not _http_url_ok(url):
                        all_rows_valid = False
                        break
                    if len(snippet) > 160:
                        all_rows_valid = False
                        break
                    if not _iso8601_utc_ok(ts):
                        all_rows_valid = False
                        break
                    ranks_by_query.setdefault(q, []).append(rank)
                if all_rows_valid:
                    contiguous = True
                    for q, ranks in ranks_by_query.items():
                        unique_sorted = sorted(set(ranks))
                        if not unique_sorted or unique_sorted[0] != 1 or unique_sorted != list(range(1, len(unique_sorted) + 1)):
                            contiguous = False
                            break
                    if contiguous:
                        fields_ok = True

    scores["keyword_research_columns_and_header"] = 1.0 if header_ok else 0.0
    scores["keyword_research_row_counts"] = 1.0 if rows_ok else 0.0
    scores["keyword_research_row_fields_valid"] = 1.0 if fields_ok else 0.0

    kp_path = workspace / "outputs" / "keyword_presence.json"
    kp_ok = False
    keywords = []
    files_counts_valid = False
    csv_contains_keywords = False
    if kp_path.exists():
        try:
            kp = json.loads(_read_text(kp_path))
            kw = kp.get("keywords")
            files_obj = kp.get("files")
            if isinstance(kw, list) and len(kw) == 2 and all(isinstance(x, str) and x.strip() for x in kw):
                keywords = [x.strip() for x in kw]
                if isinstance(files_obj, dict):
                    required_files = ["site/index.html", "content/about.md"]
                    files_counts_valid = True
                    for rf in required_files:
                        f_counts = files_obj.get(rf)
                        if not isinstance(f_counts, dict):
                            files_counts_valid = False
                            break
                        for k in keywords:
                            if k not in f_counts or not isinstance(f_counts[k], int):
                                files_counts_valid = False
                                break
                        if not files_counts_valid:
                            break
                        file_text = _read_text(workspace / rf)
                        for k in keywords:
                            actual_count = _count_phrase(file_text, k)
                            if actual_count != f_counts.get(k, -999):
                                files_counts_valid = False
                                break
                        if not files_counts_valid:
                            break
                if rows is not None:
                    csv_text_blob = "\n".join([",".join(r) for r in rows])
                    csv_contains_keywords = all(k.lower() in csv_text_blob.lower() for k in keywords)
                kp_ok = True
        except Exception:
            kp_ok = False
    if kp_ok and files_counts_valid and csv_contains_keywords:
        scores["primary_keywords_in_csv_and_keyword_presence_json_valid"] = 1.0
    else:
        scores["primary_keywords_in_csv_and_keyword_presence_json_valid"] = 0.0

    index_path = workspace / "site" / "index.html"
    index_html = _read_text(index_path)

    if index_html and site_url:
        href = _extract_canonical_href(index_html)
        canonical_ok = False
        if href:
            acceptable = {site_url, homepage_url}
            if href in acceptable:
                canonical_ok = True
        scores["index_canonical_present_and_correct"] = 1.0 if canonical_ok else 0.0

        title_text = _extract_html_tag_content(index_html, "title")
        title_ok = False
        if title_text and keywords:
            t = title_text.strip().lower()
            for k in keywords:
                if t.startswith(k.lower()):
                    title_ok = True
                    break
        scores["index_title_starts_with_keyword"] = 1.0 if title_ok else 0.0

        meta_desc = _extract_meta_description(index_html)
        meta_ok = False
        if meta_desc and keywords:
            if len(meta_desc) <= 160:
                k1_in = keywords[0].lower() in meta_desc.lower()
                k2_in = keywords[1].lower() in meta_desc.lower()
                if k1_in and k2_in:
                    meta_ok = True
        scores["index_meta_description_includes_both_and_length"] = 1.0 if meta_ok else 0.0

        h1_count = _count_tag_occurrences(index_html, "h1")
        h1_texts = _extract_tag_texts(index_html, "h1")
        h1_ok = False
        if h1_count == 1 and h1_texts and keywords:
            h1_text = h1_texts[0]
            if any(_count_phrase(h1_text, k) > 0 for k in keywords):
                h1_ok = True
        scores["index_h1_single_and_contains_keyword"] = 1.0 if h1_ok else 0.0

        faq_section = _extract_faq_section(index_html)
        faq_relevance_ok = False
        faq_pairs_ok = False
        if faq_section:
            relevance_terms = ["joke", "jokes", "punchline", "booking", "book", "comedian", "open mic"]
            faq_lower = faq_section.lower()
            if any(term in faq_lower for term in relevance_terms):
                faq_relevance_ok = True
            q_count = faq_lower.count("?")
            structural_qs = len(re.findall(r"<(h2|h3|dt|summary)\b", faq_section, flags=re.I))
            if q_count >= 2 or structural_qs >= 2:
                faq_pairs_ok = True
        scores["index_faq_section_two_pairs_and_relevance"] = 1.0 if (faq_relevance_ok and faq_pairs_ok) else 0.0

        jsonld_questions = _jsonld_faq_questions(index_html)
        jsonld_ok = False
        if jsonld_questions:
            matched = 0
            faq_visible = faq_section.lower() if faq_section else ""
            for q in jsonld_questions:
                if q and q.strip().lower() in faq_visible:
                    matched += 1
            if matched >= 2:
                jsonld_ok = True
        scores["index_jsonld_faqpage_matches_questions"] = 1.0 if jsonld_ok else 0.0
    else:
        scores["index_canonical_present_and_correct"] = 0.0
        scores["index_title_starts_with_keyword"] = 0.0
        scores["index_meta_description_includes_both_and_length"] = 0.0
        scores["index_h1_single_and_contains_keyword"] = 0.0
        scores["index_faq_section_two_pairs_and_relevance"] = 0.0
        scores["index_jsonld_faqpage_matches_questions"] = 0.0

    about_path = workspace / "content" / "about.md"
    about_text = _read_text(about_path)
    about_wc_ok = False
    about_kw_ok = False
    about_tone_ok = False
    if about_text:
        words = re.findall(r"\b\w[\w'-]*\b", about_text)
        wc = len(words)
        if 150 <= wc <= 220:
            about_wc_ok = True
        if keywords:
            if all(_count_phrase(about_text, k) > 0 for k in keywords):
                about_kw_ok = True
        comedic_terms = [
            "punchline", "wordplay", "joke", "jokes", "laugh", "laughs", "giggle", "riff", "callback",
            "heckler", "mic", "open mic", "club", "crowd", "stage", "set", "bit", "tag"
        ]
        tone_term = any(term in about_text.lower() for term in comedic_terms)
        expressive = any(ch in about_text for ch in ["!", "—", "…"])
        # Gate tone credit on rewrite compliance to avoid false positives on scaffold content
        about_tone_ok = tone_term and expressive and about_wc_ok and about_kw_ok
    scores["about_word_count_and_keywords"] = 1.0 if (about_wc_ok and about_kw_ok) else 0.0
    scores["about_tone_signal"] = 1.0 if about_tone_ok else 0.0

    robots_path = workspace / "site" / "robots.txt"
    robots_text = _read_text(robots_path)
    robots_ok = False
    if robots_text and site_url:
        lines = [ln.strip() for ln in robots_text.splitlines() if ln.strip() != ""]
        ua_ok = any(re.match(r"(?i)^user-agent:\s*\*$", ln) for ln in lines)
        sitemap_line = f"Sitemap: {site_url}/sitemap.xml"
        sm_ok = any(ln.strip().lower() == sitemap_line.lower() for ln in lines)
        disallow_nonempty = any(re.match(r"(?i)^disallow:\s*\S", ln) for ln in lines)
        robots_ok = ua_ok and sm_ok and (not disallow_nonempty)
    scores["robots_txt_valid"] = 1.0 if robots_ok else 0.0

    sitemap_path = workspace / "site" / "sitemap.xml"
    sitemap_ok = False
    if sitemap_path.exists() and site_url:
        try:
            tree = ET.parse(str(sitemap_path))
            root = tree.getroot()

            def _iter_url():
                for elem in root.iter():
                    if elem.tag.endswith("url"):
                        yield elem

            today_str = date.today().isoformat()
            have_home = False
            have_about = False
            for url_elem in _iter_url():
                loc = None
                lastmod = None
                for child in list(url_elem):
                    tag_local = child.tag.split("}")[-1]
                    if tag_local == "loc":
                        loc = (child.text or "").strip() if child.text else ""
                    elif tag_local == "lastmod":
                        lastmod = (child.text or "").strip() if child.text else ""
                if loc in (homepage_url, site_url) and lastmod and lastmod[:10] == today_str:
                    have_home = True
                if loc == about_url and lastmod and lastmod[:10] == today_str:
                    have_about = True
            if have_home and have_about:
                sitemap_ok = True
        except Exception:
            sitemap_ok = False
    scores["sitemap_xml_valid"] = 1.0 if sitemap_ok else 0.0

    report_path = workspace / "outputs" / "seo_changes_report.md"
    report_text = _read_text(report_path)
    report_files_ok = False
    report_values_ok = False
    if report_text:
        kw_ok = all(_count_phrase(report_text, k) > 0 for k in keywords) if keywords else False
        files_listed = all(p in report_text for p in ["site/index.html", "content/about.md", "site/robots.txt", "site/sitemap.xml"])
        report_files_ok = kw_ok and files_listed
        title_text = _extract_html_tag_content(index_html, "title") if index_html else ""
        meta_desc = _extract_meta_description(index_html) if index_html else ""
        if title_text and meta_desc:
            if (title_text in report_text) and (meta_desc in report_text):
                report_values_ok = True
    scores["seo_report_mentions_files_and_keywords"] = 1.0 if report_files_ok else 0.0
    scores["seo_report_includes_title_and_meta_description_values"] = 1.0 if report_values_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()