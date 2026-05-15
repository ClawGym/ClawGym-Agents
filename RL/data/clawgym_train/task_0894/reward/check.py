import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_json(path: Path) -> Optional[Any]:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        return None


def safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def parse_simple_yaml_mapping(path: Path) -> Optional[Dict[str, Any]]:
    text = safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        result[key] = val
    return result


def extract_title(html: str) -> Optional[str]:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def parse_attributes(tag_str: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for m in re.finditer(
        r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+))',
        tag_str,
        flags=re.IGNORECASE,
    ):
        key = m.group(1).lower()
        val = m.group(3) or m.group(4) or m.group(5) or ""
        attrs[key] = val
    return attrs


def parse_meta_and_links(html: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    metas_by_name: Dict[str, str] = {}
    metas_by_property: Dict[str, str] = {}
    links_by_rel: Dict[str, str] = {}
    for m in re.finditer(r"<meta\b[^>]*>", html, flags=re.IGNORECASE):
        attrs = parse_attributes(m.group(0))
        content = attrs.get("content", "")
        if "name" in attrs:
            metas_by_name[attrs["name"].lower()] = content
        if "property" in attrs:
            metas_by_property[attrs["property"].lower()] = content
    for m in re.finditer(r"<link\b[^>]*>", html, flags=re.IGNORECASE):
        attrs = parse_attributes(m.group(0))
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "")
        if rel:
            for token in rel.split():
                links_by_rel[token] = href
    return metas_by_name, metas_by_property, links_by_rel


def extract_ld_json_objects(html: str) -> List[Dict[str, Any]]:
    objs: List[Dict[str, Any]] = []
    for m in re.finditer(
        r'<script\b[^>]*type\s*=\s*("application/ld\+json"|\'application/ld\+json\')[^>]*>(.*?)</script\s*>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        content = m.group(2).strip()
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        objs.append(item)
            elif isinstance(data, dict):
                objs.append(data)
        except Exception:
            continue
    return objs


def html_text_content(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_first_paragraph_in_article(html: str) -> Optional[str]:
    m_article = re.search(r"<article\b[^>]*>(.*?)</article\s*>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m_article:
        return None
    article_html = m_article.group(1)
    m_p = re.search(r"<p\b[^>]*>(.*?)</p\s*>", article_html, flags=re.IGNORECASE | re.DOTALL)
    if not m_p:
        return None
    return html_text_content(m_p.group(1))


def extract_h2_texts(html: str) -> List[str]:
    texts: List[str] = []
    for m in re.finditer(r"<h2\b[^>]*>(.*?)</h2\s*>", html, flags=re.IGNORECASE | re.DOTALL):
        texts.append(html_text_content(m.group(1)))
    return texts


def find_img_alt_in_article(html: str) -> Optional[str]:
    m_article = re.search(r"<article\b[^>]*>(.*?)</article\s*>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m_article:
        return None
    article_html = m_article.group(1)
    m_img = re.search(r"<img\b[^>]*>", article_html, flags=re.IGNORECASE)
    if not m_img:
        return None
    attrs = parse_attributes(m_img.group(0))
    return attrs.get("alt")


def has_breadcrumb_link_to_index(html: str) -> bool:
    return re.search(r'<a\b[^>]*href\s*=\s*["\']index\.html["\']', html, flags=re.IGNORECASE) is not None


def is_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def today_iso() -> str:
    return date.today().isoformat()


def find_ld_object_by_type(ld_objs: List[Dict[str, Any]], type_name: str) -> Optional[Dict[str, Any]]:
    for obj in ld_objs:
        t = obj.get("@type")
        if isinstance(t, str) and t.lower() == type_name.lower():
            return obj
        if isinstance(t, list) and any(isinstance(x, str) and x.lower() == type_name.lower() for x in t):
            return obj
    return None


def get_string_or_nested_name(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "name" in value and isinstance(value["name"], str):
            return value["name"]
    return None


def extract_breadcrumb_items(blist_obj: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    elems = blist_obj.get("itemListElement")
    if isinstance(elems, list):
        items: List[Dict[str, Any]] = []
        for el in elems:
            if isinstance(el, dict) and el.get("@type") == "ListItem":
                items.append(el)
        return items
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "queries_csv_exists_and_structure": 0.0,
        "queries_csv_min_rows_and_required_queries": 0.0,
        "queries_csv_serp_and_date_valid": 0.0,
        "sources_json_valid_and_official_domain_present": 0.0,
        "keywords_json_structure_counts": 0.0,
        "keywords_sources_cross_validated_and_domain_diversity": 0.0,
        "config_twitter_handle_set": 0.0,
        "config_other_fields_unchanged": 0.0,
        "article_title_and_meta_description_requirements": 0.0,
        "article_canonical_and_social_tags": 0.0,
        "article_newsarticle_jsonld_valid": 0.0,
        "article_faqpage_jsonld_matches_queries": 0.0,
        "article_body_keywords_headings_and_image_alt": 0.0,
        "article_breadcrumb_link": 0.0,
        "index_meta_and_canonical": 0.0,
        "index_breadcrumblist_jsonld": 0.0,
        "robots_txt_valid": 0.0,
        "sitemap_xml_valid": 0.0,
        "report_summary_present_and_references": 0.0,
    }

    # Paths
    queries_csv_path = workspace / "research" / "queries.csv"
    sources_json_path = workspace / "research" / "sources.json"
    keywords_json_path = workspace / "research" / "keywords.json"
    config_yaml_path = workspace / "config" / "site.yaml"
    index_html_path = workspace / "site" / "index.html"
    article_html_path = workspace / "site" / "article.html"
    robots_txt_path = workspace / "site" / "robots.txt"
    sitemap_xml_path = workspace / "site" / "sitemap.xml"
    report_md_path = workspace / "report" / "seo_changes.md"

    # Load config
    config = parse_simple_yaml_mapping(config_yaml_path) or {}
    base_url = config.get("base_url", "")
    author = config.get("author", "")
    twitter_handle = config.get("twitter_handle", "")
    site_name = config.get("site_name", "")

    # Check config twitter handle updated
    if twitter_handle == "@BrumTennisCommentary":
        scores["config_twitter_handle_set"] = 1.0

    # Check config other fields unchanged (only relevant if twitter was updated)
    if scores["config_twitter_handle_set"] == 1.0:
        if (
            site_name == "Birmingham Tennis Commentary"
            and base_url == "https://example.com"
            and author == "Local Sports Commentator"
        ):
            scores["config_other_fields_unchanged"] = 1.0

    # Load research files
    queries_rows, queries_fields = safe_read_csv(queries_csv_path)
    sources_json = safe_read_json(sources_json_path)
    keywords_json = safe_read_json(keywords_json_path)

    # queries.csv structure
    required_query_columns = ["query", "search_engine", "date_iso", "observed_serp_features"]
    if queries_rows is not None and queries_fields is not None:
        if queries_fields == required_query_columns:
            scores["queries_csv_exists_and_structure"] = 1.0

    # queries.csv min rows and required queries present
    required_queries = {"Birmingham Classic tennis", "Edgbaston grass court tournament"}
    if isinstance(queries_rows, list):
        if len(queries_rows) >= 5:
            present_queries = {row.get("query", "") for row in queries_rows}
            if required_queries.issubset(present_queries):
                scores["queries_csv_min_rows_and_required_queries"] = 1.0

    # queries.csv serp features and date validation
    allowed_features = {
        "people_also_ask",
        "top_stories",
        "knowledge_panel",
        "videos",
        "images",
        "faqs",
        "sitelinks",
        "map_pack",
        "none",
    }
    serp_valid = True
    if isinstance(queries_rows, list) and queries_fields == required_query_columns:
        for row in queries_rows:
            q = row.get("query", "")
            se = row.get("search_engine", "")
            d = row.get("date_iso", "")
            feats = row.get("observed_serp_features", "")
            if not q or not se:
                serp_valid = False
                break
            if not is_iso_date(d):
                serp_valid = False
                break
            tokens = [t.strip() for t in feats.split(";") if t.strip()] if feats else []
            if not tokens:
                serp_valid = False
                break
            for t in tokens:
                if t not in allowed_features:
                    serp_valid = False
                    break
            if not serp_valid:
                break
            if "none" in tokens and len(tokens) > 1:
                serp_valid = False
                break
        if serp_valid:
            scores["queries_csv_serp_and_date_valid"] = 1.0

    # sources.json validation and official domain
    if isinstance(sources_json, list) and len(sources_json) >= 3:
        domains = []
        sources_valid = True
        has_official = False
        official_domains = {"wtatennis.com", "lta.org.uk", "itftennis.com"}
        for item in sources_json:
            if not isinstance(item, dict):
                sources_valid = False
                break
            domain = item.get("domain")
            title = item.get("doc_title")
            reason = item.get("reason")
            if not isinstance(domain, str) or not isinstance(title, str) or not isinstance(reason, str):
                sources_valid = False
                break
            # domain should not contain protocol or slashes
            if "://" in domain or "/" in domain:
                sources_valid = False
                break
            # No direct URLs in title or reason
            tl = title.lower()
            rl = reason.lower()
            if "http://" in tl or "https://" in tl or "http://" in rl or "https://" in rl:
                sources_valid = False
                break
            domains.append(domain)
            if domain in official_domains:
                has_official = True
        if sources_valid and has_official:
            scores["sources_json_valid_and_official_domain_present"] = 1.0

    # keywords.json structure and counts
    primary_phrases: List[str] = []
    long_tail_phrases: List[str] = []
    keywords_structure_ok = False
    if isinstance(keywords_json, dict):
        pk = keywords_json.get("primary_keywords")
        lt = keywords_json.get("long_tail_phrases")
        if isinstance(pk, list) and isinstance(lt, list):
            entries_ok = True
            for entry in pk:
                if not isinstance(entry, dict) or "phrase" not in entry or "source_domains" not in entry:
                    entries_ok = False
                    break
                if not isinstance(entry["phrase"], str):
                    entries_ok = False
                    break
                if not isinstance(entry["source_domains"], list) or not entry["source_domains"]:
                    entries_ok = False
                    break
                primary_phrases.append(entry["phrase"])
            for entry in lt:
                if not isinstance(entry, dict) or "phrase" not in entry or "source_domains" not in entry:
                    entries_ok = False
                    break
                if not isinstance(entry["phrase"], str):
                    entries_ok = False
                    break
                if not isinstance(entry["source_domains"], list) or not entry["source_domains"]:
                    entries_ok = False
                    break
                long_tail_phrases.append(entry["phrase"])
            if entries_ok and len(pk) >= 10 and len(lt) >= 5:
                keywords_structure_ok = True
                scores["keywords_json_structure_counts"] = 1.0

    # keywords sources cross-validation and domain diversity
    if keywords_structure_ok and isinstance(sources_json, list):
        allowed_domains = {item.get("domain") for item in sources_json if isinstance(item, dict) and isinstance(item.get("domain"), str)}
        all_entries: List[Dict[str, Any]] = []
        if isinstance(keywords_json.get("primary_keywords"), list):
            all_entries.extend(keywords_json["primary_keywords"])
        if isinstance(keywords_json.get("long_tail_phrases"), list):
            all_entries.extend(keywords_json["long_tail_phrases"])
        domain_subset_ok = True
        used_domains: set = set()
        for entry in all_entries:
            sdoms = entry.get("source_domains", [])
            if not isinstance(sdoms, list) or not sdoms:
                domain_subset_ok = False
                break
            for d in sdoms:
                if d not in allowed_domains:
                    domain_subset_ok = False
                    break
                used_domains.add(d)
            if not domain_subset_ok:
                break
        if domain_subset_ok and len({d for d in used_domains if d}) >= 3:
            scores["keywords_sources_cross_validated_and_domain_diversity"] = 1.0

    # Load HTML files
    article_html = safe_read_text(article_html_path) or ""
    index_html = safe_read_text(index_html_path) or ""

    # Article: title and meta description requirements
    if article_html:
        art_title = extract_title(article_html)
        metas_by_name, metas_by_prop, links_by_rel = parse_meta_and_links(article_html)
        desc = metas_by_name.get("description", "")
        title_ok = isinstance(art_title, str) and len(art_title) <= 60 and len(art_title) > 0
        desc_ok = False
        includes_primary = False
        if isinstance(desc, str) and 120 <= len(desc) <= 160:
            if primary_phrases:
                for phrase in primary_phrases:
                    if phrase and phrase.lower() in desc.lower():
                        includes_primary = True
                        break
            desc_ok = includes_primary
        if title_ok and desc_ok:
            scores["article_title_and_meta_description_requirements"] = 1.0

        # Article: canonical and social tags
        canonical_expected = f"{base_url}/article.html" if base_url else ""
        canonical_ok = links_by_rel.get("canonical", "") == canonical_expected and bool(canonical_expected)
        og_ok = (
            metas_by_prop.get("og:type", "") == "article"
            and metas_by_prop.get("og:url", "") == canonical_expected
            and art_title is not None
            and metas_by_prop.get("og:title", "") == art_title
            and metas_by_prop.get("og:description", "") == desc
        )
        twitter_ok = (
            metas_by_name.get("twitter:card", "") == "summary_large_image"
            and metas_by_name.get("twitter:site", "") == twitter_handle
            and metas_by_name.get("twitter:title", "") == art_title
            and metas_by_name.get("twitter:description", "") == desc
            and bool(twitter_handle)
        )
        if canonical_ok and og_ok and twitter_ok:
            scores["article_canonical_and_social_tags"] = 1.0

        # Article: NewsArticle JSON-LD validation
        ld_objs = extract_ld_json_objects(article_html)
        news_obj = find_ld_object_by_type(ld_objs, "NewsArticle")
        news_ok = False
        if isinstance(news_obj, dict):
            has_context = "@context" in news_obj
            headline = news_obj.get("headline")
            author_field = news_obj.get("author")
            dp = news_obj.get("datePublished")
            about = news_obj.get("about")
            main_entity = news_obj.get("mainEntityOfPage")
            headline_ok = isinstance(headline, str) and art_title is not None and headline == art_title
            author_name = get_string_or_nested_name(author_field)
            author_ok = isinstance(author_name, str) and author_name == author
            dp_ok = isinstance(dp, str) and dp.startswith(today_iso())
            about_ok = False
            if isinstance(about, list) and len(about) >= 3:
                if primary_phrases:
                    about_ok = all(isinstance(x, str) and (x in primary_phrases) for x in about[:3])
                else:
                    about_ok = False
            meop_ok = isinstance(main_entity, str) and main_entity == canonical_expected
            if has_context and headline_ok and author_ok and dp_ok and about_ok and meop_ok:
                news_ok = True
        if news_ok:
            scores["article_newsarticle_jsonld_valid"] = 1.0

        # Article: FAQPage validation
        faq_obj = find_ld_object_by_type(ld_objs, "FAQPage")
        faq_ok = False
        if isinstance(faq_obj, dict) and isinstance(queries_rows, list):
            main_entity = faq_obj.get("mainEntity")
            if isinstance(main_entity, list):
                questions = []
                for item in main_entity:
                    if isinstance(item, dict) and item.get("@type") == "Question":
                        qname = item.get("name")
                        ans = item.get("acceptedAnswer")
                        if isinstance(qname, str) and isinstance(ans, dict) and ans.get("@type") == "Answer" and isinstance(ans.get("text"), str):
                            questions.append(qname)
                if len(questions) >= 3:
                    query_set = {row.get("query", "") for row in queries_rows}
                    if all(q in query_set for q in questions):
                        faq_ok = True
        if faq_ok:
            scores["article_faqpage_jsonld_matches_queries"] = 1.0

        # Article: body keywords, headings, and image alt
        first_para = extract_first_paragraph_in_article(article_html) or ""
        para_ok = False
        if primary_phrases and first_para:
            matched = set()
            for phrase in primary_phrases:
                if phrase and phrase.lower() in first_para.lower():
                    matched.add(phrase)
                if len(matched) >= 2:
                    break
            para_ok = len(matched) >= 2
        h2_texts = extract_h2_texts(article_html)
        h2_ok = False
        if long_tail_phrases and h2_texts:
            matched_lt: List[str] = []
            for phrase in long_tail_phrases:
                for h2 in h2_texts:
                    if phrase and phrase.lower() in h2.lower():
                        matched_lt.append(phrase)
                        break
                if len(set(matched_lt)) >= 2:
                    break
            h2_ok = len(set(matched_lt)) >= 2
        img_alt = find_img_alt_in_article(article_html)
        img_ok = isinstance(img_alt, str) and ("birmingham classic" in img_alt.lower()) and len(img_alt.strip()) > 0
        if para_ok and h2_ok and img_ok:
            scores["article_body_keywords_headings_and_image_alt"] = 1.0

        # Article: breadcrumb link
        if has_breadcrumb_link_to_index(article_html):
            scores["article_breadcrumb_link"] = 1.0

    # Index: meta description and canonical
    if index_html:
        metas_by_name_i, metas_by_prop_i, links_by_rel_i = parse_meta_and_links(index_html)
        desc_i = metas_by_name_i.get("description", "")
        desc_i_ok = isinstance(desc_i, str) and 120 <= len(desc_i) <= 160
        canonical_i_expected = f"{base_url}/index.html" if base_url else ""
        canonical_i_ok = links_by_rel_i.get("canonical", "") == canonical_i_expected and bool(canonical_i_expected)
        if desc_i_ok and canonical_i_ok:
            scores["index_meta_and_canonical"] = 1.0

        # Index: BreadcrumbList JSON-LD
        ld_objs_i = extract_ld_json_objects(index_html)
        blist_obj = find_ld_object_by_type(ld_objs_i, "BreadcrumbList")
        blist_ok = False
        if isinstance(blist_obj, dict):
            items = extract_breadcrumb_items(blist_obj)
            if isinstance(items, list) and len(items) == 2:
                try:
                    pos1 = int(items[0].get("position"))
                    pos2 = int(items[1].get("position"))
                except Exception:
                    pos1 = pos2 = -1

                def get_item_url(el: Dict[str, Any]) -> Optional[str]:
                    item = el.get("item")
                    if isinstance(item, str):
                        return item
                    if isinstance(item, dict):
                        if "@id" in item and isinstance(item["@id"], str):
                            return item["@id"]
                        if "url" in item and isinstance(item["url"], str):
                            return item["url"]
                    return None

                url1 = get_item_url(items[0])
                url2 = get_item_url(items[1])
                if (
                    pos1 == 1
                    and pos2 == 2
                    and url1 == canonical_i_expected
                    and url2 == f"{base_url}/article.html"
                ):
                    blist_ok = True
        if blist_ok:
            scores["index_breadcrumblist_jsonld"] = 1.0

    # Robots.txt
    robots_text = safe_read_text(robots_txt_path) or ""
    if robots_text:
        ua_ok = re.search(r"^\s*User-agent:\s*\*\s*$", robots_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        allow_ok = re.search(r"^\s*Allow:\s*/\s*$", robots_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        sitemap_line = f"Sitemap: {base_url}/sitemap.xml" if base_url else ""
        sitemap_ok = (
            sitemap_line != ""
            and re.search(r"^\s*Sitemap:\s*(\S+)\s*$", robots_text, flags=re.IGNORECASE | re.MULTILINE) is not None
            and sitemap_line in robots_text
        )
        if ua_ok and allow_ok and sitemap_ok:
            scores["robots_txt_valid"] = 1.0

    # Sitemap.xml
    sitemap_valid = False
    if sitemap_xml_path.exists():
        try:
            tree = ET.parse(str(sitemap_xml_path))
            root = tree.getroot()

            def strip_ns(tag: str) -> str:
                return tag.split("}", 1)[-1] if "}" in tag else tag

            urls = []
            for el in root.iter():
                if strip_ns(el.tag) == "url":
                    urls.append(el)
            if len(urls) == 2:
                locs = set()
                lastmods_ok = True
                today = today_iso()
                for u in urls:
                    loc = None
                    lastmod = None
                    for child in list(u):
                        tag = strip_ns(child.tag)
                        if tag == "loc":
                            loc = (child.text or "").strip()
                        elif tag == "lastmod":
                            lastmod = (child.text or "").strip()
                    if loc is None or lastmod is None or lastmod != today:
                        lastmods_ok = False
                        break
                    locs.add(loc)
                expected_locs = {f"{base_url}/index.html", f"{base_url}/article.html"} if base_url else set()
                if lastmods_ok and locs == expected_locs and len(expected_locs) == 2:
                    sitemap_valid = True
        except Exception:
            sitemap_valid = False
    if sitemap_valid:
        scores["sitemap_xml_valid"] = 1.0

    # Report
    report_text = safe_read_text(report_md_path) or ""
    report_ok = False
    if report_text:
        has_index_canonical = f"{base_url}/index.html" in report_text if base_url else False
        has_article_canonical = f"{base_url}/article.html" in report_text if base_url else False
        mentions_schemas = ("NewsArticle" in report_text) and ("FAQPage" in report_text)
        mentions_keywords = False
        mentions_long_tail = False
        if primary_phrases:
            for phrase in primary_phrases:
                if phrase and phrase in report_text:
                    mentions_keywords = True
                    break
        if long_tail_phrases:
            for phrase in long_tail_phrases:
                if phrase and phrase in report_text:
                    mentions_long_tail = True
                    break
        if has_index_canonical and has_article_canonical and mentions_schemas and mentions_keywords and mentions_long_tail:
            report_ok = True
    if report_ok:
        scores["report_summary_present_and_references"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()