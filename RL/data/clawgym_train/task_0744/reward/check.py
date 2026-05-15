import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_keywords(path: Path) -> List[str]:
    keywords: List[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                kw = (row.get("keyword") or "").strip()
                if kw:
                    keywords.append(kw)
    except Exception:
        return []
    return keywords


def _safe_load_menu(path: Path) -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                image = (row.get("image") or "").strip()
                item = (row.get("item") or "").strip()
                desc = (row.get("description") or "").strip()
                if image and item:
                    mapping[Path(image).name] = {"item": item, "description": desc}
    except Exception:
        return {}
    return mapping


def _safe_load_business_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for line in text.splitlines():
        raw = line.rstrip("\n")
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0 and ":" in raw:
            key, val = raw.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                current_section = key
                if key in ("address",):
                    data[key] = {}
                elif key in ("serviceAreas", "openingHours"):
                    data[key] = []
                else:
                    data[key] = {}
            else:
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                data[key] = val
                current_section = None
        elif indent > 0 and current_section:
            sub = raw.strip()
            if current_section in ("serviceAreas", "openingHours"):
                if sub.startswith("-"):
                    item = sub[1:].strip()
                    if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    data[current_section].append(item)
            elif current_section == "address":
                if ":" in sub:
                    k, v = sub.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    data[current_section][k] = v
    if "address" not in data:
        data["address"] = {}
    if "serviceAreas" not in data:
        data["serviceAreas"] = []
    if "openingHours" not in data:
        data["openingHours"] = []
    return data


def _extract_title(html: str) -> Optional[str]:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _extract_meta_description(html: str) -> Optional[str]:
    metas = re.findall(r"<meta\s+[^>]*>", html, flags=re.IGNORECASE | re.DOTALL)
    for tag in metas:
        name_m = re.search(r'name\s*=\s*["\']description["\']', tag, flags=re.IGNORECASE)
        if name_m:
            content_m = re.search(r'content\s*=\s*["\'](.*?)["\']', tag, flags=re.IGNORECASE | re.DOTALL)
            if content_m:
                return re.sub(r"\s+", " ", content_m.group(1)).strip()
    return None


def _extract_img_tags(html: str) -> List[Dict[str, Optional[str]]]:
    imgs: List[Dict[str, Optional[str]]] = []
    for m in re.finditer(r"<img\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        src_m = re.search(r'src\s*=\s*["\'](.*?)["\']', tag, flags=re.IGNORECASE | re.DOTALL)
        alt_m = re.search(r'alt\s*=\s*["\'](.*?)["\']', tag, flags=re.IGNORECASE | re.DOTALL)
        src = src_m.group(1).strip() if src_m else None
        alt = alt_m.group(1) if alt_m else None
        imgs.append({"src": src, "alt": alt})
    return imgs


def _basename(p: Optional[str]) -> Optional[str]:
    if p is None:
        return None
    return Path(p).name


def _extract_nav_anchors(html: str) -> List[Tuple[str, str]]:
    anchors: List[Tuple[str, str]] = []
    navs = re.findall(r"<nav\b[^>]*>(.*?)</nav>", html, flags=re.IGNORECASE | re.DOTALL)
    for nav_html in navs:
        for a in re.finditer(r"<a\b[^>]*>(.*?)</a>", nav_html, flags=re.IGNORECASE | re.DOTALL):
            a_tag = a.group(0)
            text = re.sub(r"<.*?>", "", a.group(1)).strip()
            href_m = re.search(r'href\s*=\s*["\'](.*?)["\']', a_tag, flags=re.IGNORECASE)
            href = href_m.group(1).strip() if href_m else ""
            anchors.append((text, href))
    return anchors


def _extract_jsonld_blocks(html: str) -> List[str]:
    blocks = []
    for m in re.finditer(r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        blocks.append(m.group(1).strip())
    return blocks


def _ci_contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def _keywords_in_text(keywords: List[str], text: Optional[str]) -> List[str]:
    if not text:
        return []
    found = []
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            found.append(kw)
    return list(dict.fromkeys(found))


def _validate_jsonld_cafe(data: Any, business: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("@type") != "CafeOrCoffeeShop":
        return False
    required_fields = ["@context", "@type", "name", "description", "telephone", "url", "priceRange", "servesCuisine", "openingHours", "areaServed", "address"]
    for f in required_fields:
        if f not in data:
            return False
    if data.get("name") != business.get("name"):
        return False
    if data.get("description") != business.get("description"):
        return False
    if data.get("telephone") != business.get("telephone"):
        return False
    if data.get("url") != business.get("url"):
        return False
    if data.get("priceRange") != business.get("priceRange"):
        return False
    if data.get("servesCuisine") != business.get("servesCuisine"):
        return False
    if data.get("openingHours") != business.get("openingHours"):
        return False
    service_areas = business.get("serviceAreas") or []
    area_served = data.get("areaServed")
    if isinstance(area_served, list):
        area_values = []
        for item in area_served:
            if isinstance(item, dict) and "name" in item:
                area_values.append(str(item.get("name")))
            else:
                area_values.append(str(item))
    elif isinstance(area_served, dict) and "name" in area_served:
        area_values = [str(area_served.get("name"))]
    elif isinstance(area_served, str):
        area_values = [area_served]
    else:
        return False
    for sa in service_areas:
        if not any(sa.lower() == av.lower() for av in area_values):
            return False
    addr = data.get("address")
    if not isinstance(addr, dict):
        return False
    addr_required = ["streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"]
    for k in addr_required:
        if addr.get(k) != (business.get("address") or {}).get(k):
            return False
    # Require PostalAddress type for address
    if addr.get("@type") not in (None, "PostalAddress"):
        return False
    if "@type" in addr and addr.get("@type") != "PostalAddress":
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "index_title_valid": 0.0,
        "menu_title_valid": 0.0,
        "schedule_title_valid": 0.0,
        "titles_unique_across_pages": 0.0,
        "index_description_valid": 0.0,
        "menu_description_valid": 0.0,
        "schedule_description_valid": 0.0,
        "descriptions_unique_across_pages": 0.0,
        "index_title_includes_business_name": 0.0,
        "menu_title_includes_business_name": 0.0,
        "schedule_title_includes_business_name": 0.0,
        "index_title_contains_keyword": 0.0,
        "menu_title_contains_keyword": 0.0,
        "schedule_title_contains_keyword": 0.0,
        "index_description_contains_keyword_and_service_area": 0.0,
        "menu_description_contains_keyword_and_service_area": 0.0,
        "schedule_description_contains_keyword_and_service_area": 0.0,
        "json_ld_present_and_valid_on_index": 0.0,
        "json_ld_absent_on_menu_and_schedule": 0.0,
        "nav_present_with_required_links_all_pages": 0.0,
        "index_images_alt_updated": 0.0,
        "menu_images_alt_updated": 0.0,
        "schedule_images_alt_updated": 0.0,
        "seo_report_exists": 0.0,
        "seo_report_includes_old_new_titles_and_descriptions": 0.0,
        "seo_report_mentions_nav_added": 0.0,
        "seo_report_lists_json_ld_fields": 0.0,
        "seo_summary_json_valid": 0.0,
    }

    business_yaml_path = workspace / "content" / "business.yaml"
    keywords_csv_path = workspace / "content" / "keywords.csv"
    menu_csv_path = workspace / "content" / "menu.csv"

    business = _safe_load_business_yaml(business_yaml_path)
    keywords = _safe_load_keywords(keywords_csv_path)
    menu_map = _safe_load_menu(menu_csv_path)

    pages = ["index.html", "menu.html", "schedule.html"]
    page_paths = [workspace / "site" / p for p in pages]
    page_htmls: Dict[str, Optional[str]] = {p: _read_text(path) for p, path in zip(pages, page_paths)}

    titles: Dict[str, Optional[str]] = {}
    descriptions: Dict[str, Optional[str]] = {}
    used_keywords_title: Dict[str, List[str]] = {}
    used_keywords_desc: Dict[str, List[str]] = {}
    nav_ok_pages: Dict[str, bool] = {}
    imgs_pass: Dict[str, List[str]] = {}
    jsonld_blocks_count: Dict[str, int] = {}
    jsonld_valid_index: bool = False

    for p in pages:
        html = page_htmls[p]
        if html is None:
            titles[p] = None
            descriptions[p] = None
            used_keywords_title[p] = []
            used_keywords_desc[p] = []
            nav_ok_pages[p] = False
            imgs_pass[p] = []
            jsonld_blocks_count[p] = 0
            continue
        title = _extract_title(html)
        desc = _extract_meta_description(html)
        titles[p] = title
        descriptions[p] = desc
        used_keywords_title[p] = _keywords_in_text(keywords, title or "")
        used_keywords_desc[p] = _keywords_in_text(keywords, desc or "")

        anchors = _extract_nav_anchors(html)
        required = [("Home", "index.html"), ("Menu", "menu.html"), ("Schedule", "schedule.html")]
        has_all = all(any(t == req_t and h == req_h for (t, h) in anchors) for (req_t, req_h) in required)
        nav_ok_pages[p] = has_all

        images = _extract_img_tags(html)
        passed_basenames: List[str] = []
        for img in images:
            src = img.get("src")
            base = _basename(src) or ""
            if base in menu_map:
                alt = img.get("alt")
                if alt is None:
                    continue
                alt_text = (alt or "").strip()
                item = menu_map[base]["item"]
                if alt_text.startswith(item) and len(alt_text) <= 80 and len(alt_text) > len(item):
                    passed_basenames.append(base)
        imgs_pass[p] = passed_basenames

        blocks = _extract_jsonld_blocks(html)
        jsonld_blocks_count[p] = len(blocks)
        if p == "index.html" and len(blocks) == 1 and business:
            try:
                data = json.loads(blocks[0])
                jsonld_valid_index = _validate_jsonld_cafe(data, business)
            except Exception:
                jsonld_valid_index = False

    # Titles validity per page (must include business name, include at least one keyword, and be <= 60 chars)
    for p in pages:
        t = titles.get(p)
        if t is not None and business:
            valid_len = len(t) <= 60
            has_business = _ci_contains(t, business.get("name", ""))
            has_keyword = len(used_keywords_title.get(p, [])) > 0
            scores[f"{p.split('.')[0]}_title_valid"] = 1.0 if (valid_len and has_business and has_keyword) else 0.0
            scores[f"{p.split('.')[0]}_title_includes_business_name"] = 1.0 if has_business else 0.0
            scores[f"{p.split('.')[0]}_title_contains_keyword"] = 1.0 if has_keyword else 0.0
        else:
            scores[f"{p.split('.')[0]}_title_valid"] = 0.0
            scores[f"{p.split('.')[0]}_title_includes_business_name"] = 0.0
            scores[f"{p.split('.')[0]}_title_contains_keyword"] = 0.0

    # Titles uniqueness only if all titles are valid per above
    title_values = [titles.get(p) for p in pages if titles.get(p) is not None]
    all_titles_valid = all(scores[f"{p.split('.')[0]}_title_valid"] == 1.0 for p in pages)
    if len(title_values) == 3 and len(set([tv.strip().lower() for tv in title_values])) == 3 and all_titles_valid:
        scores["titles_unique_across_pages"] = 1.0

    # Descriptions per page
    for p in pages:
        d = descriptions.get(p)
        if d is not None and business:
            valid_len = len(d) <= 160
            has_keyword = len(used_keywords_desc.get(p, [])) > 0
            service_areas = business.get("serviceAreas") or []
            mentions_area = any(_ci_contains(d, area) for area in service_areas)
            scores[f"{p.split('.')[0]}_description_valid"] = 1.0 if (valid_len and has_keyword and mentions_area) else 0.0
            scores[f"{p.split('.')[0]}_description_contains_keyword_and_service_area"] = 1.0 if (has_keyword and mentions_area) else 0.0
        else:
            scores[f"{p.split('.')[0]}_description_valid"] = 0.0
            scores[f"{p.split('.')[0]}_description_contains_keyword_and_service_area"] = 0.0

    # Descriptions uniqueness only if all descriptions are valid
    desc_values = [descriptions.get(p) for p in pages if descriptions.get(p) is not None]
    all_desc_valid = all(scores[f"{p.split('.')[0]}_description_valid"] == 1.0 for p in pages)
    if len(desc_values) == 3 and len(set([dv.strip().lower() for dv in desc_values])) == 3 and all_desc_valid:
        scores["descriptions_unique_across_pages"] = 1.0

    # JSON-LD checks
    if jsonld_blocks_count.get("index.html", 0) == 1 and jsonld_valid_index:
        scores["json_ld_present_and_valid_on_index"] = 1.0
    # Absent on others only counts if index has valid JSON-LD
    if scores["json_ld_present_and_valid_on_index"] == 1.0 and jsonld_blocks_count.get("menu.html", 0) == 0 and jsonld_blocks_count.get("schedule.html", 0) == 0:
        scores["json_ld_absent_on_menu_and_schedule"] = 1.0

    # NAV on all pages
    if all(nav_ok_pages.get(p, False) for p in pages):
        scores["nav_present_with_required_links_all_pages"] = 1.0

    # Images alt updated per page: require at least one matching image and all such images updated
    for p in pages:
        html = page_htmls.get(p)
        key = f"{p.split('.')[0]}_images_alt_updated"
        if html is None:
            scores[key] = 0.0
            continue
        imgs = _extract_img_tags(html)
        expected_bases = [(_basename(img.get("src")) or "") for img in imgs if (_basename(img.get("src")) or "") in menu_map]
        expected_set = set(expected_bases)
        passed_set = set(imgs_pass.get(p, []))
        if len(expected_set) == 0:
            scores[key] = 0.0
        else:
            scores[key] = 1.0 if expected_set.issubset(passed_set) else 0.0

    # Report checks
    report_path = workspace / "output" / "seo_changes_report.md"
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["seo_report_exists"] = 1.0
        old_titles = {
            "index.html": "Home",
            "menu.html": "Menu",
            "schedule.html": "Schedule",
        }
        old_descs = {
            "index.html": "Coffee on the go.",
            "menu.html": "Our drinks.",
        }
        ok_old_new = True
        for p in pages:
            new_t = titles.get(p) or ""
            old_t = old_titles.get(p, "")
            if old_t and (old_t not in report_text):
                ok_old_new = False
            if new_t and (new_t not in report_text):
                ok_old_new = False
        for p in ["index.html", "menu.html"]:
            new_d = descriptions.get(p) or ""
            old_d = old_descs.get(p, "")
            if old_d and (old_d not in report_text):
                ok_old_new = False
            if new_d and (new_d not in report_text):
                ok_old_new = False
        scores["seo_report_includes_old_new_titles_and_descriptions"] = 1.0 if ok_old_new else 0.0

        if re.search(r"\bnav\b", report_text, flags=re.IGNORECASE) and re.search(r"\badded\b", report_text, flags=re.IGNORECASE):
            scores["seo_report_mentions_nav_added"] = 1.0

        jsonld_fields = [
            "@context",
            "@type",
            "name",
            "description",
            "telephone",
            "url",
            "priceRange",
            "servesCuisine",
            "openingHours",
            "areaServed",
            "address",
            "streetAddress",
            "addressLocality",
            "addressRegion",
            "postalCode",
            "addressCountry",
        ]
        listed_all = all(field in report_text for field in jsonld_fields)
        scores["seo_report_lists_json_ld_fields"] = 1.0 if listed_all else 0.0
    else:
        scores["seo_report_exists"] = 0.0
        scores["seo_report_includes_old_new_titles_and_descriptions"] = 0.0
        scores["seo_report_mentions_nav_added"] = 0.0
        scores["seo_report_lists_json_ld_fields"] = 0.0

    # Summary JSON checks
    summary_path = workspace / "output" / "seo_summary.json"
    summary_ok = False
    try:
        summary_text = _read_text(summary_path)
        if summary_text is not None:
            parsed = json.loads(summary_text)
            if isinstance(parsed, list) and len(parsed) == 3:
                per_page_ok = True
                for p in pages:
                    expected_page_path = f"site/{p}"
                    entry = None
                    for obj in parsed:
                        if isinstance(obj, dict) and obj.get("page") == expected_page_path:
                            entry = obj
                            break
                    if entry is None:
                        per_page_ok = False
                        break
                    t = titles.get(p) or ""
                    d = descriptions.get(p) or ""
                    k_used = list(dict.fromkeys((used_keywords_title.get(p, []) + used_keywords_desc.get(p, []))))
                    imgs_updated = imgs_pass.get(p, [])
                    jsonld_present = (p == "index.html" and jsonld_blocks_count.get(p, 0) >= 1)

                    if entry.get("title") != t:
                        per_page_ok = False
                    if entry.get("title_length") != len(t):
                        per_page_ok = False
                    if entry.get("description_length") != len(d):
                        per_page_ok = False
                    if sorted(entry.get("keywords_used") or []) != sorted(k_used):
                        per_page_ok = False
                    if sorted([Path(x).name for x in (entry.get("images_with_updated_alt") or [])]) != sorted(imgs_updated):
                        per_page_ok = False
                    if bool(entry.get("json_ld_present")) != bool(jsonld_present):
                        per_page_ok = False
                summary_ok = per_page_ok
    except Exception:
        summary_ok = False
    scores["seo_summary_json_valid"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()