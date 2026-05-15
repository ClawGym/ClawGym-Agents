import json
import sys
import csv
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_tag_attributes(tag_str: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    # Remove starting "<... " and trailing ">"
    inner = tag_str.strip()
    if inner.startswith("<"):
        inner = inner[1:]
    if inner.endswith(">"):
        inner = inner[:-1]
    # Now parse attributes in the remainder after the tag name
    # Split on whitespace first token is tag name
    parts = inner.split(None, 1)
    attr_part = parts[1] if len(parts) > 1 else ""
    # Regex to find key="value" or key='value'
    for m in re.finditer(r'([^\s=]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', attr_part, flags=re.S):
        key = m.group(1).strip().lower()
        val = m.group(3) if m.group(3) is not None else m.group(4)
        attrs[key] = val
    # Also capture boolean attributes (no equals) as present with empty string
    for m in re.finditer(r'([^\s=]+)(?=(\s|$))', attr_part):
        key = m.group(1).strip().lower()
        if key and key not in attrs:
            # Avoid capturing tag name again
            # Ensure it's not something like '/' from self-closing
            if key not in ("/",):
                attrs[key] = ""
    return attrs


def _extract_head_body(html: str) -> Tuple[Optional[str], Optional[str]]:
    if html is None:
        return None, None
    head_match = re.search(r'<head\b[^>]*>(.*?)</head\s*>', html, flags=re.I | re.S)
    body_match = re.search(r'<body\b[^>]*>(.*?)</body\s*>', html, flags=re.I | re.S)
    head_html = head_match.group(1) if head_match else None
    body_html = body_match.group(1) if body_match else None
    return head_html, body_html


def _parse_title(head_html: Optional[str]) -> Optional[str]:
    if not head_html:
        return None
    m = re.search(r'<title\b[^>]*>(.*?)</title\s*>', head_html, flags=re.I | re.S)
    if not m:
        return None
    # Strip inner whitespace
    title = m.group(1).strip()
    # Collapse internal whitespace to single spaces
    title = re.sub(r'\s+', ' ', title)
    return title


def _parse_meta_description(head_html: Optional[str]) -> Optional[str]:
    if not head_html:
        return None
    metas = re.findall(r'<meta\b[^>]*>', head_html, flags=re.I | re.S)
    for tag in metas:
        attrs = _parse_tag_attributes(tag)
        name = attrs.get("name", "")
        if name is not None and name.lower() == "description":
            content = attrs.get("content")
            if content is None:
                return ""
            return content
    return None


def _parse_canonical(head_html: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not head_html:
        return False, None
    links = re.findall(r'<link\b[^>]*>', head_html, flags=re.I | re.S)
    for tag in links:
        attrs = _parse_tag_attributes(tag)
        rel = attrs.get("rel", "")
        if rel is not None and rel.lower() == "canonical":
            href = attrs.get("href")
            return True, href
    return False, None


def _parse_images(body_html: Optional[str]) -> List[Dict[str, Optional[str]]]:
    imgs: List[Dict[str, Optional[str]]] = []
    if not body_html:
        return imgs
    tags = re.findall(r'<img\b[^>]*>', body_html, flags=re.I | re.S)
    for tag in tags:
        attrs = _parse_tag_attributes(tag)
        alt = attrs.get("alt")
        # Treat None or empty string as missing/empty
        imgs.append({"alt": alt})
    return imgs


def _img_missing_alt_count(imgs: List[Dict[str, Optional[str]]]) -> int:
    count = 0
    for img in imgs:
        alt = img.get("alt")
        if alt is None or alt.strip() == "":
            count += 1
    return count


def _h1_present(body_html: Optional[str]) -> bool:
    if not body_html:
        return False
    return re.search(r'<h1\b[^>]*>', body_html, flags=re.I) is not None


def _count_internal_links(body_html: Optional[str]) -> int:
    if not body_html:
        return 0
    tags = re.findall(r'<a\b[^>]*>', body_html, flags=re.I | re.S)
    count = 0
    for tag in tags:
        attrs = _parse_tag_attributes(tag)
        href = attrs.get("href") or ""
        if href.lower().endswith(".html"):
            count += 1
    return count


def _normalize_body_for_compare(body_html: Optional[str]) -> Optional[str]:
    if body_html is None:
        return None
    # Remove all alt attributes (case-insensitive), including whitespace around them
    without_alt = re.sub(r'\s+alt\s*=\s*(".*?"|\'.*?\')', '', body_html, flags=re.I | re.S)
    # Collapse whitespace
    normalized = re.sub(r'\s+', ' ', without_alt).strip()
    return normalized


def _includes_brand_in_title(title: Optional[str]) -> bool:
    if not title:
        return False
    t = title.lower()
    return ("greenswell cooperative" in t) or ("greenswell" in t)


def _includes_any_keyword(text: Optional[str], keywords: List[str]) -> bool:
    if not text:
        return False
    t = text.lower()
    for kw in keywords:
        if kw.lower() in t:
            return True
    return False


def _find_keyword_used(text: Optional[str], keywords: List[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for kw in keywords:
        if kw.lower() in t:
            return kw
    return None


def _parse_robots(robots_text: Optional[str]) -> Dict[str, object]:
    disallows: List[str] = []
    disallow_count = 0
    sitemap_present = False
    if robots_text:
        for line in robots_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            lower = line.lower()
            if lower.startswith("disallow:"):
                # Extract value after colon
                val = line.split(":", 1)[1].strip()
                disallows.append(val)
                disallow_count += 1
            elif lower.startswith("sitemap:"):
                sitemap_present = True
    return {
        "disallow_count": disallow_count,
        "disallows": disallows,
        "sitemap_present": sitemap_present,
    }


def _compute_page_metrics(html_text: Optional[str]) -> Dict[str, object]:
    head, body = _extract_head_body(html_text or "")
    title = _parse_title(head)
    meta_desc = _parse_meta_description(head)
    has_canonical, canonical_href = _parse_canonical(head)
    imgs = _parse_images(body)
    img_count = len(imgs)
    img_missing_alt = _img_missing_alt_count(imgs)
    h1 = _h1_present(body)
    internal_links = _count_internal_links(body)
    body_norm = _normalize_body_for_compare(body)
    return {
        "title": title,
        "meta_description": meta_desc if meta_desc is not None else None,
        "has_canonical": has_canonical,
        "canonical_href": canonical_href,
        "img_count": img_count,
        "img_missing_alt": img_missing_alt,
        "imgs": imgs,
        "h1_present": h1,
        "internal_link_count": internal_links,
        "body_norm": body_norm,
        "body_raw": body or "",
    }


def _strict_len_in_range(s: Optional[str], min_len: int, max_len: int) -> bool:
    if s is None:
        return False
    n = len(s)
    return min_len <= n <= max_len


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_in_expected_paths": 0.0,
        "index_title_ok": 0.0,
        "products_title_ok": 0.0,
        "blog_title_ok": 0.0,
        "index_meta_ok": 0.0,
        "products_meta_ok": 0.0,
        "blog_meta_ok": 0.0,
        "index_imgs_alt_ok": 0.0,
        "products_imgs_alt_ok": 0.0,
        "blog_imgs_alt_ok": 0.0,
        "index_body_preserved": 0.0,
        "products_body_preserved": 0.0,
        "blog_body_preserved": 0.0,
        "canonical_handling_correct": 0.0,
        "audit_csv_correct": 0.0,
        "summary_json_correct": 0.0,
    }

    # Paths
    input_pages_dir = workspace / "input" / "pages"
    output_pages_dir = workspace / "output" / "optimized" / "pages"
    audit_csv_path = workspace / "output" / "audit" / "seo_audit.csv"
    summary_json_path = workspace / "output" / "audit" / "summary.json"
    robots_path = workspace / "input" / "robots.txt"
    config_path = workspace / "input" / "site-config.json"

    expected_pages = ["index.html", "products.html", "blog.html"]

    # Load config
    config = _load_json(config_path)
    if config is None:
        # Default ranges as fallback (task-specified), but missing config still impacts checks reliant on keywords
        preferred_keywords = []
        title_range = (50, 60)
        meta_range = (140, 160)
    else:
        preferred_keywords = config.get("preferred_keywords", []) or []
        tr = config.get("title_length_range", [50, 60])
        mr = config.get("meta_description_length_range", [140, 160])
        try:
            title_range = (int(tr[0]), int(tr[1]))
        except Exception:
            title_range = (50, 60)
        try:
            meta_range = (int(mr[0]), int(mr[1]))
        except Exception:
            meta_range = (140, 160)

    # Read inputs and outputs
    inputs: Dict[str, Dict[str, object]] = {}
    outputs: Dict[str, Dict[str, object]] = {}

    for page in expected_pages:
        before_text = _read_text(input_pages_dir / page)
        after_text = _read_text(output_pages_dir / page)
        inputs[page] = _compute_page_metrics(before_text) if before_text is not None else {}
        outputs[page] = _compute_page_metrics(after_text) if after_text is not None else {}

    # outputs_in_expected_paths
    if all((output_pages_dir / p).exists() for p in expected_pages):
        scores["outputs_in_expected_paths"] = 1.0

    # Per-page checks
    for page in expected_pages:
        after = outputs.get(page) or {}
        before = inputs.get(page) or {}

        # Title check
        title_ok = False
        title_after = after.get("title")
        if title_after is not None and _strict_len_in_range(title_after, title_range[0], title_range[1]) and _includes_brand_in_title(title_after):
            title_ok = True
        scores_key = f"{page.split('.')[0]}_title_ok"
        if scores_key in scores and title_ok:
            scores[scores_key] = 1.0

        # Meta description check
        meta_ok = False
        meta_after = after.get("meta_description")
        if (
            isinstance(meta_after, str)
            and _strict_len_in_range(meta_after, meta_range[0], meta_range[1])
            and _includes_any_keyword(meta_after, preferred_keywords)
        ):
            meta_ok = True
        scores_key = f"{page.split('.')[0]}_meta_ok"
        if scores_key in scores and meta_ok:
            scores[scores_key] = 1.0

        # Images alt check
        imgs_ok = False
        imgs_before = before.get("imgs") if before else None
        imgs_after = after.get("imgs") if after else None
        if isinstance(imgs_before, list) and isinstance(imgs_after, list) and len(imgs_before) == len(imgs_after):
            per_ok = True
            for i in range(len(imgs_before)):
                alt_b = imgs_before[i].get("alt")
                alt_a = imgs_after[i].get("alt")
                if alt_b is None or (isinstance(alt_b, str) and alt_b.strip() == ""):
                    # After must be non-empty and under 80 chars
                    if not (isinstance(alt_a, str) and alt_a.strip() != "" and len(alt_a) <= 80):
                        per_ok = False
                        break
                else:
                    # After must equal before
                    if alt_a != alt_b:
                        per_ok = False
                        break
            # Also ensure no missing alt remain after
            if per_ok:
                missing_after = _img_missing_alt_count(imgs_after)
                if missing_after != 0:
                    per_ok = False
            imgs_ok = per_ok
        scores_key = f"{page.split('.')[0]}_imgs_alt_ok"
        if scores_key in scores and imgs_ok:
            scores[scores_key] = 1.0

        # Body preserved (ignoring alt attributes)
        body_ok = False
        body_before_norm = before.get("body_norm") if before else None
        body_after_norm = after.get("body_norm") if after else None
        if body_before_norm is not None and body_after_norm is not None and body_before_norm == body_after_norm:
            body_ok = True
        scores_key = f"{page.split('.')[0]}_body_preserved"
        if scores_key in scores and body_ok:
            scores[scores_key] = 1.0

    # Canonical handling: preserve existing and do not add where absent
    canonical_ok = True
    # products.html had canonical; must be present after and same href
    before_prod = inputs.get("products.html") or {}
    after_prod = outputs.get("products.html") or {}
    if not before_prod or not after_prod:
        canonical_ok = False
    else:
        if not (before_prod.get("has_canonical") is True and after_prod.get("has_canonical") is True):
            canonical_ok = False
        else:
            if before_prod.get("canonical_href") != after_prod.get("canonical_href"):
                canonical_ok = False
    # index.html and blog.html had no canonical; must not have after
    for page in ["index.html", "blog.html"]:
        before_p = inputs.get(page) or {}
        after_p = outputs.get(page) or {}
        if not before_p or not after_p:
            canonical_ok = False
        else:
            if before_p.get("has_canonical") is True:
                # If it had canonical originally (not expected), still must preserve? But according to inputs it's absent.
                # We'll enforce that after must match before.
                if after_p.get("has_canonical") is not True:
                    canonical_ok = False
            else:
                if after_p.get("has_canonical") is True:
                    canonical_ok = False
    if canonical_ok:
        scores["canonical_handling_correct"] = 1.0

    # Audit CSV correctness
    def _validate_csv(csv_path: Path) -> bool:
        required_header = [
            "page",
            "title_before",
            "title_after",
            "title_length_after",
            "meta_description_before",
            "meta_description_after",
            "meta_description_length_after",
            "h1_present",
            "canonical_present",
            "img_count_before",
            "img_missing_alt_before",
            "img_missing_alt_after",
            "internal_link_count_before",
            "keyword_used_in_description",
        ]
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            return False
        if not rows:
            return False
        header = rows[0]
        if header != required_header:
            return False
        data_rows = rows[1:]
        if len(data_rows) != len(expected_pages):
            return False
        # Build map from page to row dict
        idx_map = {name: i for i, name in enumerate(required_header)}
        seen_pages = set()
        for row in data_rows:
            if len(row) != len(required_header):
                return False
            page_name = row[idx_map["page"]]
            if page_name not in expected_pages:
                return False
            if page_name in seen_pages:
                return False
            seen_pages.add(page_name)
            before = inputs.get(page_name) or {}
            after = outputs.get(page_name) or {}
            if not before or not after:
                return False
            # title_before
            tb = before.get("title") or ""
            if row[idx_map["title_before"]] != tb:
                return False
            # title_after
            ta = after.get("title") or ""
            if row[idx_map["title_after"]] != ta:
                return False
            # title_length_after
            try:
                tla = int(row[idx_map["title_length_after"]])
            except Exception:
                return False
            if tla != len(ta):
                return False
            # meta_description_before (empty if missing)
            mdb_before = before.get("meta_description")
            mdb_str = "" if (mdb_before is None) else (mdb_before)
            if row[idx_map["meta_description_before"]] != mdb_str:
                return False
            # meta_description_after
            mda = after.get("meta_description") or ""
            if row[idx_map["meta_description_after"]] != mda:
                return False
            # meta_description_length_after
            try:
                mdla = int(row[idx_map["meta_description_length_after"]])
            except Exception:
                return False
            if mdla != len(mda):
                return False
            # h1_present (true/false) - compute from input
            h1b = before.get("h1_present") is True
            h1_csv = row[idx_map["h1_present"]].strip().lower()
            if h1_csv not in ("true", "false"):
                return False
            if (h1_csv == "true") != h1b:
                return False
            # canonical_present (true/false) - compute from after
            can_after = after.get("has_canonical") is True
            can_csv = row[idx_map["canonical_present"]].strip().lower()
            if can_csv not in ("true", "false"):
                return False
            if (can_csv == "true") != can_after:
                return False
            # img_count_before
            try:
                icb = int(row[idx_map["img_count_before"]])
            except Exception:
                return False
            if icb != int(before.get("img_count") or 0):
                return False
            # img_missing_alt_before
            try:
                imab = int(row[idx_map["img_missing_alt_before"]])
            except Exception:
                return False
            if imab != int(before.get("img_missing_alt") or 0):
                return False
            # img_missing_alt_after
            try:
                imaa = int(row[idx_map["img_missing_alt_after"]])
            except Exception:
                return False
            if imaa != int(after.get("img_missing_alt") or 0):
                return False
            # internal_link_count_before
            try:
                ilcb = int(row[idx_map["internal_link_count_before"]])
            except Exception:
                return False
            if ilcb != int(before.get("internal_link_count") or 0):
                return False
            # keyword_used_in_description: one value from preferred_keywords that is present in rewritten meta description
            kw_csv = row[idx_map["keyword_used_in_description"]]
            if kw_csv not in preferred_keywords:
                return False
            if kw_csv.lower() not in (mda or "").lower():
                return False
        # ensure all expected pages covered
        if set(expected_pages) != seen_pages:
            return False
        return True

    if audit_csv_path.exists() and _validate_csv(audit_csv_path):
        scores["audit_csv_correct"] = 1.0

    # Summary JSON correctness
    def _validate_summary_json(path: Path) -> bool:
        summary = _load_json(path)
        if summary is None:
            return False
        # Compute expected
        total_pages = len(expected_pages)
        pages_missing_meta_before = 0
        total_images_before = 0
        total_images_missing_alt_before = 0
        total_images_missing_alt_after = 0
        title_lengths_after: List[int] = []
        meta_lengths_after: List[int] = []

        for page in expected_pages:
            before = inputs.get(page) or {}
            after = outputs.get(page) or {}
            md_before = before.get("meta_description")
            if md_before is None:
                pages_missing_meta_before += 1
            total_images_before += int(before.get("img_count") or 0)
            total_images_missing_alt_before += int(before.get("img_missing_alt") or 0)
            total_images_missing_alt_after += int(after.get("img_missing_alt") or 0)
            ta = after.get("title")
            if isinstance(ta, str):
                title_lengths_after.append(len(ta))
            mda = after.get("meta_description")
            if isinstance(mda, str):
                meta_lengths_after.append(len(mda))

        avg_title_len_after = sum(title_lengths_after) / total_pages if total_pages > 0 else 0.0
        avg_meta_len_after = sum(meta_lengths_after) / total_pages if total_pages > 0 else 0.0

        # Robots
        robots_text = _read_text(robots_path)
        robots_metrics = _parse_robots(robots_text)

        # Validate fields
        try:
            if int(summary.get("total_pages")) != total_pages:
                return False
            if int(summary.get("pages_missing_meta_description_before")) != pages_missing_meta_before:
                return False
            # Allow minor float rounding; compare within tiny epsilon
            def _approx_equal(a, b, eps=1e-6):
                try:
                    return abs(float(a) - float(b)) <= eps
                except Exception:
                    return False
            if not _approx_equal(summary.get("avg_title_length_after"), avg_title_len_after):
                return False
            if not _approx_equal(summary.get("avg_meta_description_length_after"), avg_meta_len_after):
                return False
            if int(summary.get("total_images_before")) != total_images_before:
                return False
            if int(summary.get("total_images_missing_alt_before")) != total_images_missing_alt_before:
                return False
            if int(summary.get("total_images_missing_alt_after")) != total_images_missing_alt_after:
                return False
            robots_obj = summary.get("robots")
            if not isinstance(robots_obj, dict):
                return False
            if int(robots_obj.get("disallow_count")) != robots_metrics["disallow_count"]:
                return False
            # Disallows must match exactly including order
            if robots_obj.get("disallows") != robots_metrics["disallows"]:
                return False
            sp = robots_obj.get("sitemap_present")
            if not isinstance(sp, bool):
                return False
            if sp != robots_metrics["sitemap_present"]:
                return False
        except Exception:
            return False
        return True

    if summary_json_path.exists() and _validate_summary_json(summary_json_path):
        scores["summary_json_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()