import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_simple_yaml_keys(yaml_text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if yaml_text is None:
        return None, None
    base_url = None
    brand_name = None
    for line in yaml_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key == "base_url":
            base_url = val
        elif key == "brand_name":
            brand_name = val
    return base_url, brand_name


def extract_between(text: str, start_tag: str, end_tag: str) -> Optional[str]:
    # Case-insensitive extraction between tags
    pattern = re.compile(re.escape(start_tag) + r"(.*?)" + re.escape(end_tag), re.IGNORECASE | re.DOTALL)
    m = pattern.search(text)
    if not m:
        return None
    return m.group(1)


def get_head_inner(html: str) -> Optional[str]:
    return extract_between(html, "<head>", "</head>") or extract_between(html, "<HEAD>", "</HEAD>")


def extract_title(html: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.*?)</title\s*>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def extract_meta_description(html: str) -> Optional[str]:
    # find meta tags and check name attribute
    for m in re.finditer(r"<meta\s+[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        name = extract_attr(tag, "name")
        if name and name.lower().strip() == "description":
            content = extract_attr(tag, "content")
            if content is None:
                return ""
            return content
    return None


def extract_link_canonical(html: str) -> Optional[str]:
    for m in re.finditer(r"<link\s+[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        rel = extract_attr(tag, "rel")
        if rel and "canonical" in rel.lower().split():
            href = extract_attr(tag, "href")
            return href
    return None


def extract_attr(tag: str, attr: str) -> Optional[str]:
    # Search for attr= "..." or '...'
    pattern = re.compile(rf'{attr}\s*=\s*("([^"]*)"|\'([^\']*)\')', flags=re.IGNORECASE | re.DOTALL)
    m = pattern.search(tag)
    if not m:
        return None
    return m.group(2) if m.group(2) is not None else m.group(3)


def normalize_html_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_seo_tags_from_head(head_inner: str) -> str:
    # Remove <title>...</title>
    s = re.sub(r"<title[^>]*>.*?</title\s*>\s*", "", head_inner, flags=re.IGNORECASE | re.DOTALL)
    # Remove any meta description
    s = re.sub(r"<meta[^>]*\bname\s*=\s*['\"]description['\"][^>]*>\s*", "", s, flags=re.IGNORECASE | re.DOTALL)
    # Remove link rel=canonical
    s = re.sub(r"<link[^>]*\brel\s*=\s*['\"][^'\"]*\bcanonical\b[^'\"]*['\"][^>]*>\s*", "", s, flags=re.IGNORECASE | re.DOTALL)
    return normalize_html_space(s)


def parse_img_tags(html: str) -> List[Dict[str, Optional[str]]]:
    imgs = []
    for m in re.finditer(r"<img\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        src = extract_attr(tag, "src")
        alt = extract_attr(tag, "alt")
        imgs.append({"src": src, "alt": alt})
    return imgs


def is_generic_alt(alt: Optional[str]) -> bool:
    if alt is None:
        return True
    alt_stripped = alt.strip()
    if alt_stripped == "":
        return True
    return alt_stripped.lower() in {"image", "photo", "team"}


def expected_canonical_for_page(base_url: Optional[str], basename: str) -> Optional[str]:
    if base_url is None:
        return None
    if basename == "index.html":
        return base_url.rstrip("/") + "/"
    name = basename.rsplit(".", 1)[0]
    return base_url.rstrip("/") + "/" + name


def check_title_format(new_title: Optional[str], brand_name: Optional[str]) -> bool:
    if new_title is None or brand_name is None:
        return False
    # length 45–60 inclusive
    l = len(new_title)
    if l < 45 or l > 60:
        return False
    # ends with " | {brand_name}"
    suffix = f" | {brand_name}"
    if not new_title.endswith(suffix):
        return False
    # exactly one pipe
    if new_title.count("|") != 1:
        return False
    # no exclamation marks
    if "!" in new_title:
        return False
    return True


def check_meta_description_format(desc: Optional[str]) -> bool:
    if desc is None:
        return False
    l = len(desc)
    if l < 140 or l > 160:
        return False
    if "!" in desc:
        return False
    return True


def safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        dict_rows = []
        for r in rows[1:]:
            # pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[: len(header)]
            dict_rows.append({header[i]: r[i] for i in range(len(header))})
        return header, dict_rows
    except Exception:
        return None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        # existence of outputs
        "output_site_index_exists": 0.0,
        "output_site_about_exists": 0.0,
        "output_site_services_exists": 0.0,
        # head preservation
        "head_preserved_index": 0.0,
        "head_preserved_about": 0.0,
        "head_preserved_services": 0.0,
        # titles
        "title_format_index": 0.0,
        "title_format_about": 0.0,
        "title_format_services": 0.0,
        "title_rewritten_index": 0.0,
        "title_rewritten_about": 0.0,
        "title_created_services": 0.0,
        # descriptions
        "meta_description_present_and_length_index": 0.0,
        "meta_description_present_and_length_about": 0.0,
        "meta_description_present_and_length_services": 0.0,
        "description_rewritten_about": 0.0,
        "description_created_index": 0.0,
        "description_created_services": 0.0,
        "descriptions_unique_across_pages": 0.0,
        # canonicals
        "canonical_correct_index": 0.0,
        "canonical_correct_about": 0.0,
        "canonical_correct_services": 0.0,
        # images
        "img_count_preserved_index": 0.0,
        "img_count_preserved_about": 0.0,
        "img_count_preserved_services": 0.0,
        "img_alts_required_changes_applied_index": 0.0,
        "img_alts_required_changes_applied_about": 0.0,
        "img_alts_required_changes_applied_services": 0.0,
        "img_alts_quality_index": 0.0,
        "img_alts_quality_about": 0.0,
        "img_alts_quality_services": 0.0,
        "img_good_alts_preserved_index": 0.0,
        "img_good_alts_preserved_about": 0.0,
        "img_good_alts_preserved_services": 0.0,
        # robots
        "robots_sitemap_appended_once": 0.0,
        "robots_preserved_existing_lines": 0.0,
        # report
        "report_exists": 0.0,
        "report_header_correct": 0.0,
        "report_rows_for_all_pages": 0.0,
        "report_titles_consistent": 0.0,
        "report_descriptions_consistent": 0.0,
        "report_canonicals_consistent": 0.0,
        "report_img_alt_changes_consistent": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "config" / "site.yaml"
    base_url, brand_name = parse_simple_yaml_keys(read_text(config_path))

    # Define pages
    pages = ["index.html", "about.html", "services.html"]
    input_dir = workspace / "input" / "site"
    output_dir = workspace / "output" / "site"

    # Read input and output HTMLs
    input_html: Dict[str, Optional[str]] = {}
    output_html: Dict[str, Optional[str]] = {}
    for p in pages:
        input_html[p] = read_text(input_dir / p)
        output_html[p] = read_text(output_dir / p)

    # Existence checks
    if output_html["index.html"] is not None:
        scores["output_site_index_exists"] = 1.0
    if output_html["about.html"] is not None:
        scores["output_site_about_exists"] = 1.0
    if output_html["services.html"] is not None:
        scores["output_site_services_exists"] = 1.0

    # Head preservation, titles, descriptions, canonicals, images
    output_descriptions: Dict[str, Optional[str]] = {}
    for p in pages:
        in_html = input_html[p]
        out_html = output_html[p]
        # head preservation
        if in_html is not None and out_html is not None:
            in_head = get_head_inner(in_html)
            out_head = get_head_inner(out_html)
            if in_head is not None and out_head is not None:
                in_rest = strip_seo_tags_from_head(in_head)
                out_rest = strip_seo_tags_from_head(out_head)
                if in_rest == out_rest:
                    scores[f"head_preserved_{p.split('.')[0]}"] = 1.0

        # Title checks
        old_title = extract_title(in_html) if in_html else None
        new_title = extract_title(out_html) if out_html else None
        if check_title_format(new_title, brand_name):
            scores[f"title_format_{p.split('.')[0]}"] = 1.0
        # rewritten/created
        if old_title is None:
            if new_title is not None and len(new_title) > 0:
                if p == "services.html":
                    scores["title_created_services"] = 1.0
        else:
            if new_title is not None and new_title != old_title:
                if p == "index.html":
                    scores["title_rewritten_index"] = 1.0
                elif p == "about.html":
                    scores["title_rewritten_about"] = 1.0

        # Meta description checks
        old_desc = extract_meta_description(in_html) if in_html else None
        new_desc = extract_meta_description(out_html) if out_html else None
        output_descriptions[p] = new_desc
        if check_meta_description_format(new_desc):
            scores[f"meta_description_present_and_length_{p.split('.')[0]}"] = 1.0
        # created/rewritten specifics
        if old_desc is None:
            # should be created
            if new_desc is not None and len(new_desc) > 0 and check_meta_description_format(new_desc):
                if p == "index.html":
                    scores["description_created_index"] = 1.0
                elif p == "services.html":
                    scores["description_created_services"] = 1.0
        else:
            # should be updated; new != old
            if new_desc is not None and new_desc != old_desc and check_meta_description_format(new_desc):
                if p == "about.html":
                    scores["description_rewritten_about"] = 1.0

        # Canonical checks
        expected_canon = expected_canonical_for_page(base_url, p)
        actual_canon = extract_link_canonical(out_html) if out_html else None
        if expected_canon is not None and actual_canon == expected_canon:
            if p == "index.html":
                scores["canonical_correct_index"] = 1.0
            elif p == "about.html":
                scores["canonical_correct_about"] = 1.0
            elif p == "services.html":
                scores["canonical_correct_services"] = 1.0

        # Images checks
        in_imgs = parse_img_tags(in_html) if in_html else []
        out_imgs = parse_img_tags(out_html) if out_html else []
        # count preserved
        if in_html is not None and out_html is not None:
            if len(in_imgs) == len(out_imgs):
                scores[f"img_count_preserved_{p.split('.')[0]}"] = 1.0
        # required changes applied and quality & preservation of good alts
        all_required_applied = True
        all_quality_ok = True
        good_alts_preserved = True
        for idx in range(min(len(in_imgs), len(out_imgs))):
            in_alt = in_imgs[idx]["alt"]
            out_alt = out_imgs[idx]["alt"]
            needed_change = is_generic_alt(in_alt)
            if needed_change:
                # must become non-empty and non-generic
                if out_alt is None or is_generic_alt(out_alt):
                    all_required_applied = False
                else:
                    # quality: length <= 100 and no trailing period
                    if len(out_alt) > 100 or out_alt.strip().endswith("."):
                        all_quality_ok = False
            else:
                # should remain unchanged
                if out_alt != in_alt:
                    good_alts_preserved = False
        if all_required_applied and out_html is not None and in_html is not None:
            scores[f"img_alts_required_changes_applied_{p.split('.')[0]}"] = 1.0
        if all_quality_ok and out_html is not None and in_html is not None:
            scores[f"img_alts_quality_{p.split('.')[0]}"] = 1.0
        if good_alts_preserved and out_html is not None and in_html is not None:
            scores[f"img_good_alts_preserved_{p.split('.')[0]}"] = 1.0

    # Descriptions unique across pages
    descs = [output_descriptions.get(p) for p in pages]
    if all(d is not None for d in descs):
        unique = len(set(descs)) == len(descs)
        if unique:
            scores["descriptions_unique_across_pages"] = 1.0

    # Robots checks
    robots_in_path = workspace / "input" / "robots.txt"
    robots_out_path = workspace / "output" / "robots.txt"
    robots_in = read_text(robots_in_path)
    robots_out = read_text(robots_out_path)
    if robots_out is not None and base_url is not None:
        sitemap_line = f"Sitemap: {base_url.rstrip('/')}/sitemap.xml"
        out_lines = robots_out.splitlines()
        count_sitemap = sum(1 for ln in out_lines if ln.strip() == sitemap_line)
        # appended once
        if count_sitemap == 1:
            # If input missing sitemap, ensure it's appended at the end and others preserved
            if robots_in is not None:
                in_lines = robots_in.splitlines()
                in_has_sitemap = any(ln.strip() == sitemap_line for ln in in_lines)
                if not in_has_sitemap:
                    # expect last line equals sitemap and previous lines equal input lines
                    if len(out_lines) >= len(in_lines) + 1:
                        if out_lines[-1].strip() == sitemap_line and out_lines[: len(in_lines)] == in_lines:
                            scores["robots_sitemap_appended_once"] = 1.0
                            scores["robots_preserved_existing_lines"] = 1.0
                else:
                    # already present in input, expect no duplicates and all other lines equal
                    if count_sitemap == 1:
                        # Check that removing sitemap from both leaves same lines
                        out_wo = [ln for ln in out_lines if ln.strip() != sitemap_line]
                        in_wo = [ln for ln in in_lines if ln.strip() != sitemap_line]
                        if out_wo == in_wo:
                            scores["robots_sitemap_appended_once"] = 1.0
                            scores["robots_preserved_existing_lines"] = 1.0
            else:
                # No input robots; cannot confirm preservation, but at least has exactly one sitemap
                scores["robots_sitemap_appended_once"] = 1.0
        # else fail both robots checks

    # Report checks
    report_path = workspace / "output" / "seo-report.csv"
    header, rows = safe_read_csv(report_path)
    if header is not None and rows is not None:
        scores["report_exists"] = 1.0
        expected_header = [
            "page",
            "old_title",
            "new_title",
            "title_length",
            "old_description",
            "new_description",
            "description_length",
            "canonical",
            "img_alt_changes",
            "notes",
        ]
        if header == expected_header:
            scores["report_header_correct"] = 1.0

        # rows for all pages
        pages_in_report = [r.get("page", "") for r in rows]
        if sorted(pages_in_report) == sorted(pages) and len(rows) == 3:
            scores["report_rows_for_all_pages"] = 1.0

        # Build maps for convenience
        row_map = {r.get("page", ""): r for r in rows}

        # Consistency checks
        titles_ok = True
        descs_ok = True
        canons_ok = True
        img_changes_ok = True

        for p in pages:
            r = row_map.get(p)
            in_html = input_html.get(p)
            out_html = output_html.get(p)
            if r is None or in_html is None or out_html is None:
                titles_ok = False
                descs_ok = False
                canons_ok = False
                img_changes_ok = False
                continue

            # Title consistency
            old_title_in = extract_title(in_html) or ""
            new_title_out = extract_title(out_html) or ""
            r_old_title = r.get("old_title", "")
            r_new_title = r.get("new_title", "")
            r_title_len = r.get("title_length", "")
            try:
                r_title_len_int = int(r_title_len)
            except Exception:
                r_title_len_int = -1
            if not (r_old_title == old_title_in and r_new_title == new_title_out and r_title_len_int == len(new_title_out)):
                titles_ok = False

            # Description consistency
            old_desc_in = extract_meta_description(in_html) or ""
            new_desc_out = extract_meta_description(out_html) or ""
            r_old_desc = r.get("old_description", "")
            r_new_desc = r.get("new_description", "")
            r_desc_len = r.get("description_length", "")
            try:
                r_desc_len_int = int(r_desc_len)
            except Exception:
                r_desc_len_int = -1
            # Validate format too
            if not (r_old_desc == old_desc_in and r_new_desc == new_desc_out and r_desc_len_int == len(new_desc_out) and check_meta_description_format(new_desc_out)):
                descs_ok = False

            # Canonical consistency
            expected_canon = expected_canonical_for_page(base_url, p) or ""
            out_canon = extract_link_canonical(out_html) or ""
            r_canon = r.get("canonical", "")
            if not (out_canon == expected_canon and r_canon == expected_canon):
                canons_ok = False

            # Image alt changes count
            in_imgs = parse_img_tags(in_html)
            out_imgs = parse_img_tags(out_html)
            # compute actual number of changes (diff count), aligning by index
            change_count = 0
            limit = min(len(in_imgs), len(out_imgs))
            for idx in range(limit):
                in_alt = in_imgs[idx]["alt"]
                out_alt = out_imgs[idx]["alt"]
                if (in_alt or "") != (out_alt or ""):
                    change_count += 1
            # also consider images present in output beyond input as changes? but they shouldn't exist; we ignore extras
            r_changes = r.get("img_alt_changes", "")
            try:
                r_changes_int = int(r_changes)
            except Exception:
                r_changes_int = -1
            if r_changes_int != change_count:
                img_changes_ok = False

        if titles_ok:
            scores["report_titles_consistent"] = 1.0
        if descs_ok:
            scores["report_descriptions_consistent"] = 1.0
        if canons_ok:
            scores["report_canonicals_consistent"] = 1.0
        if img_changes_ok:
            scores["report_img_alt_changes_consistent"] = 1.0
    else:
        # report missing; leave defaults
        pass

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()