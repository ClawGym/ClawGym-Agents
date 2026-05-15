import json
import csv
import re
import sys
from pathlib import Path
from html import unescape


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_keywords_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        mapping = {}
        for r in rows:
            city = (r.get("city") or "").strip()
            pk = (r.get("primary_keyword") or "").strip()
            if city:
                mapping[city.lower()] = pk
        return mapping
    except Exception:
        return None


def load_domain_txt(path: Path) -> str:
    txt = read_text_safe(path)
    if txt is None:
        return None
    return txt.strip()


def parse_yaml_config(path: Path):
    text = read_text_safe(path)
    if text is None:
        return None, None
    site_name = None
    base_url = None
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if line_stripped.startswith("site_name:"):
            val = line_stripped.split(":", 1)[1].strip()
            site_name = _strip_quotes(val)
        elif line_stripped.startswith("base_url:"):
            val = line_stripped.split(":", 1)[1].strip()
            base_url = _strip_quotes(val)
    return site_name, base_url


def _strip_quotes(s: str) -> str:
    if s is None:
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def between_tags(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text or "", flags=re.I | re.S)
    return m.group(1) if m else None


def extract_head(text: str) -> str:
    return between_tags(text, "head")


def extract_body(text: str) -> str:
    return between_tags(text, "body")


def strip_tags(html: str) -> str:
    if html is None:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", html)
    no_tags = unescape(no_tags)
    return " ".join(no_tags.split()).strip()


def find_all_tags(head_html: str, tag: str):
    return re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", head_html or "", flags=re.I | re.S)


def parse_tag_attributes(tag_html: str) -> dict:
    attrs = {}
    m = re.match(r"<\w+\b([^>]*)>", tag_html.strip(), flags=re.I | re.S)
    attr_text = ""
    if m:
        attr_text = m.group(1)
    for k, v in re.findall(r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*"(.*?)"', attr_text, flags=re.S):
        attrs[k.lower()] = v
    for k, v in re.findall(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*'(.*?)'", attr_text, flags=re.S):
        attrs[k.lower()] = v
    for k in re.findall(r"\s([A-Za-z_:][-A-Za-z0-9_:.]*)\s", " " + attr_text + " "):
        attrs.setdefault(k.lower(), "")
    return attrs


def extract_meta_description(head_html: str):
    meta_tags = re.findall(r"<meta\b[^>]*>", head_html or "", flags=re.I | re.S)
    descs = []
    for mt in meta_tags:
        attrs = parse_tag_attributes(mt)
        name = attrs.get("name", "")
        if name and name.lower() == "description":
            descs.append(attrs.get("content", ""))
    return descs


def extract_canonical_href(head_html: str):
    link_tags = re.findall(r"<link\b[^>]*>", head_html or "", flags=re.I | re.S)
    hrefs = []
    for lt in link_tags:
        attrs = parse_tag_attributes(lt)
        rel = attrs.get("rel", "")
        if rel and rel.lower() == "canonical":
            hrefs.append(attrs.get("href", ""))
    return hrefs


def extract_h1_text(html: str) -> str:
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html or "", flags=re.I | re.S)
    return strip_tags(h1.group(1)) if h1 else ""


def extract_section_inner_html(html: str) -> str:
    m = re.search(r"<section\b[^>]*>(.*?)</section>", html or "", flags=re.I | re.S)
    return m.group(1) if m else None


def extract_hero_text(html: str) -> str:
    ps = re.findall(r"<p\b([^>]*)>(.*?)</p>", html or "", flags=re.I | re.S)
    for attr_text, inner in ps:
        class_m_dq = re.search(r'class\s*=\s*"(.*?)"', attr_text, flags=re.I | re.S)
        class_m_sq = re.search(r"class\s*=\s*'(.*?)'", attr_text, flags=re.I | re.S)
        classes = ""
        if class_m_dq:
            classes = class_m_dq.group(1)
        elif class_m_sq:
            classes = class_m_sq.group(1)
        class_list = [c.strip().lower() for c in classes.split()] if classes else []
        if "hero" in class_list:
            return strip_tags(inner)
    return ""


def count_word(text: str) -> int:
    return 0 if not text else len(text.split())


def detect_city_from_h1_or_slug(h1_text: str, slug: str, available_cities: list) -> str:
    h1_lower = h1_text.lower()
    for c in available_cities:
        if c.lower() in h1_lower:
            return c
    city_guess = slug.replace("-", " ").strip()
    for c in available_cities:
        if c.lower() == city_guess.lower():
            return c
    return " ".join(w.capitalize() for w in city_guess.split())


def make_expected_canonical(base_url: str, slug: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/cities/{slug}/"


def title_length_valid(title: str) -> bool:
    if title is None:
        return False
    L = len(title.strip())
    return 45 <= L <= 60


def description_length_valid(desc: str) -> bool:
    if desc is None:
        return False
    L = len(desc.strip())
    return 140 <= L <= 160


def contains_primary_keyword_exactly_once(text: str, keyword: str) -> bool:
    if text is None or keyword is None or keyword == "":
        return False
    return text.count(keyword) == 1


def title_includes_keyword_and_brand(title: str, keyword: str) -> bool:
    if title is None or keyword is None or keyword == "":
        return False
    if keyword not in title:
        return False
    if not title.rstrip().endswith(" | GeoInsights"):
        return False
    return True


def is_action_oriented(desc: str) -> bool:
    if not desc:
        return False
    verbs = {
        "get", "discover", "drive", "unlock", "book", "contact", "explore", "request",
        "schedule", "learn", "boost", "elevate", "optimize", "partner", "grow", "improve",
        "advance", "transform", "supercharge", "power", "start", "see"
    }
    s = desc.strip()
    if not s:
        return False
    first_word = s.split()[0].lower().strip(",.")
    if first_word in verbs:
        return True
    if re.search(r"\b(contact us|get started|request|schedule|book a demo|talk to|call us)\b", s, flags=re.I):
        return True
    return False


def normalize_ws(s: str) -> str:
    if s is None:
        return ""
    return " ".join(s.split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_base_url_set": 0.0,
        "config_site_name_preserved": 0.0,
        "new_york_title_valid": 0.0,
        "san_francisco_title_valid": 0.0,
        "new_york_meta_description_valid": 0.0,
        "san_francisco_meta_description_valid": 0.0,
        "new_york_meta_description_action_oriented": 0.0,
        "san_francisco_meta_description_action_oriented": 0.0,
        "new_york_canonical_link_valid": 0.0,
        "san_francisco_canonical_link_valid": 0.0,
        "new_york_hero_rewritten": 0.0,
        "san_francisco_hero_rewritten": 0.0,
        "new_york_other_content_preserved": 0.0,
        "san_francisco_other_content_preserved": 0.0,
        "seo_report_structure": 0.0,
        "seo_report_values_match": 0.0,
        "commit_message_concise_and_descriptive": 0.0,
    }

    config_path = workspace / "config" / "site.yaml"
    keywords_path = workspace / "data" / "keywords.csv"
    domain_path = workspace / "input" / "domain.txt"
    ny_path = workspace / "content" / "cities" / "new-york.html"
    sf_path = workspace / "content" / "cities" / "san-francisco.html"
    report_path = workspace / "output" / "seo_report.csv"
    commit_path = workspace / "output" / "commit_message.txt"

    site_name, base_url = parse_yaml_config(config_path)
    domain = load_domain_txt(domain_path)

    # Base URL must be set to domain to award any config points
    if base_url is not None and domain is not None:
        if base_url == domain and base_url != "":
            scores["config_base_url_set"] = 1.0

    # Site name preserved only counts when base_url is correctly set
    if scores["config_base_url_set"] == 1.0 and site_name is not None:
        if site_name == "GeoInsights: Location Intelligence":
            scores["config_site_name_preserved"] = 1.0

    keywords_map = load_keywords_csv(keywords_path)
    available_cities = []
    if keywords_map:
        available_cities = list(keywords_map.keys())

    original_h1 = {
        "new-york": "New York Location Analytics Services",
        "san-francisco": "San Francisco Location Analytics Services",
    }
    original_section_inner = {
        "new-york": normalize_ws("""
    <h2>What we do</h2>
    <p>We specialize in multi-source mobility and POI analysis to guide expansion and media planning.</p>
    """),
        "san-francisco": normalize_ws("""
    <h2>What we do</h2>
    <p>We bring together mobile data and trade area delineation to inform decisions.</p>
    """),
    }
    original_hero = {
        "new-york": "We help brands and retailers make sense of where customers live, work, and move across the five boroughs by stitching together foot traffic signals, demographics, and store performance so teams can prioritize neighborhoods, align assortment, and choose sites, but this page still uses placeholder copy.",
        "san-francisco": "Our team analyzes mobility patterns, commercial corridors, and competitive presence around the city and broader Bay Area to support smarter store placement and field operations; this intro needs tightening for clarity and is longer than it should be.",
    }

    pages = [
        ("new-york", ny_path),
        ("san-francisco", sf_path),
    ]

    per_page_info = {}

    for slug, path in pages:
        html = read_text_safe(path)
        if not html:
            per_page_info[slug] = None
            continue

        head_html = extract_head(html)
        body_html = extract_body(html)

        titles = find_all_tags(head_html or "", "title")
        title_texts = [strip_tags(t) for t in titles]
        meta_descs = extract_meta_description(head_html or "")
        canonical_hrefs = extract_canonical_href(head_html or "")

        h1_text = extract_h1_text(html)
        hero_text = extract_hero_text(html)
        section_inner = extract_section_inner_html(html)

        if keywords_map:
            csv_city_names = []
            try:
                with keywords_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        city_name_row = (r.get("city") or "").strip()
                        if city_name_row:
                            csv_city_names.append(city_name_row)
            except Exception:
                csv_city_names = []
            city_name = detect_city_from_h1_or_slug(h1_text, slug, csv_city_names if csv_city_names else [])
            pk_lookup_key = city_name.lower()
            primary_keyword = keywords_map.get(pk_lookup_key)
        else:
            city_name = ""
            primary_keyword = None

        expected_canonical = make_expected_canonical(base_url or "", slug)

        title_valid = False
        if len(title_texts) == 1 and head_html:
            t = title_texts[0]
            title_valid = title_length_valid(t) and title_includes_keyword_and_brand(t, primary_keyword)

        meta_valid = False
        meta_action = False
        if len(meta_descs) == 1 and head_html:
            desc = meta_descs[0]
            city_ok = bool(city_name) and (city_name.lower() in desc.lower())
            meta_valid = description_length_valid(desc) and city_ok and contains_primary_keyword_exactly_once(desc, primary_keyword or "")
            meta_action = is_action_oriented(desc)

        canonical_valid = False
        if len(canonical_hrefs) == 1 and head_html:
            canonical_valid = (canonical_hrefs[0] == expected_canonical and expected_canonical != "//cities/{}/".format(slug))

        hero_ok = False
        if hero_text:
            original = original_hero.get(slug, "")
            hero_ok = (normalize_ws(hero_text) != normalize_ws(original)) and (count_word(hero_text) <= 30)
            hero_ok = hero_ok and (city_name and city_name.lower() in hero_text.lower())

        # Other content preserved should only be rewarded if the required SEO modifications are present and valid
        other_ok = False
        if h1_text and section_inner is not None:
            h1_ok = (h1_text == original_h1.get(slug, ""))
            section_ok = (normalize_ws(section_inner) == original_section_inner.get(slug, ""))
            modifications_present_and_valid = title_valid and meta_valid and canonical_valid and hero_ok
            other_ok = h1_ok and section_ok and modifications_present_and_valid

        if slug == "new-york":
            scores["new_york_title_valid"] = 1.0 if title_valid else 0.0
            scores["new_york_meta_description_valid"] = 1.0 if meta_valid else 0.0
            scores["new_york_meta_description_action_oriented"] = 1.0 if meta_action else 0.0
            scores["new_york_canonical_link_valid"] = 1.0 if canonical_valid else 0.0
            scores["new_york_hero_rewritten"] = 1.0 if hero_ok else 0.0
            scores["new_york_other_content_preserved"] = 1.0 if other_ok else 0.0
        elif slug == "san-francisco":
            scores["san_francisco_title_valid"] = 1.0 if title_valid else 0.0
            scores["san_francisco_meta_description_valid"] = 1.0 if meta_valid else 0.0
            scores["san_francisco_meta_description_action_oriented"] = 1.0 if meta_action else 0.0
            scores["san_francisco_canonical_link_valid"] = 1.0 if canonical_valid else 0.0
            scores["san_francisco_hero_rewritten"] = 1.0 if hero_ok else 0.0
            scores["san_francisco_other_content_preserved"] = 1.0 if other_ok else 0.0

        per_page_info[slug] = {
            "page_file": f"content/cities/{slug}.html",
            "city": city_name,
            "primary_keyword": primary_keyword or "",
            "title": title_texts[0] if title_texts else "",
            "title_length": str(len(title_texts[0].strip())) if title_texts else "0",
            "meta_description": meta_descs[0] if meta_descs else "",
            "description_length": str(len((meta_descs[0] or "").strip())) if meta_descs else "0",
            "canonical_url": canonical_hrefs[0] if canonical_hrefs else "",
            "hero_word_count": str(count_word(hero_text)),
            "expected_canonical": expected_canonical,
        }

    report_ok_structure = False
    report_ok_values = False
    header_expected = [
        "page_file",
        "city",
        "primary_keyword",
        "title",
        "title_length",
        "meta_description",
        "description_length",
        "canonical_url",
        "hero_word_count",
    ]
    try:
        with report_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            if header == header_expected:
                report_ok_structure = True
            data_rows = rows[1:]
            report_map = {}
            for r in data_rows:
                if len(r) != len(header_expected):
                    continue
                row_dict = dict(zip(header, r))
                report_map[row_dict["page_file"]] = row_dict
            expected_pages = {f"content/cities/{slug}.html" for slug, _ in pages}
            if expected_pages.issubset(set(report_map.keys())):
                values_match = True
                for slug, info in per_page_info.items():
                    if info is None:
                        values_match = False
                        break
                    row = report_map.get(info["page_file"])
                    if not row:
                        values_match = False
                        break
                    if (row.get("city") or "") != (info.get("city") or ""):
                        values_match = False
                        break
                    if (row.get("primary_keyword") or "") != (info.get("primary_keyword") or ""):
                        values_match = False
                        break
                    if (row.get("title") or "") != (info.get("title") or ""):
                        values_match = False
                        break
                    if (row.get("title_length") or "") != (info.get("title_length") or ""):
                        values_match = False
                        break
                    if (row.get("meta_description") or "") != (info.get("meta_description") or ""):
                        values_match = False
                        break
                    if (row.get("description_length") or "") != (info.get("description_length") or ""):
                        values_match = False
                        break
                    if (row.get("canonical_url") or "") != (info.get("canonical_url") or ""):
                        values_match = False
                        break
                    if (row.get("hero_word_count") or "") != (info.get("hero_word_count") or ""):
                        values_match = False
                        break
                    if (row.get("canonical_url") or "") != info.get("expected_canonical", ""):
                        values_match = False
                        break
                report_ok_values = values_match
    except Exception:
        report_ok_structure = False
        report_ok_values = False

    scores["seo_report_structure"] = 1.0 if report_ok_structure else 0.0
    scores["seo_report_values_match"] = 1.0 if (report_ok_structure and report_ok_values) else 0.0

    commit_text = read_text_safe(commit_path)
    commit_ok = False
    if commit_text is not None:
        msg = " ".join(commit_text.strip().split())
        if 0 < len(msg) <= 120:
            has_seo = re.search(r"\bseo\b", msg, flags=re.I) is not None
            has_config = re.search(r"\b(config|configuration|base_url|domain|site|yaml)\b", msg, flags=re.I) is not None
            commit_ok = has_seo and has_config
    scores["commit_message_concise_and_descriptive"] = 1.0 if commit_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()