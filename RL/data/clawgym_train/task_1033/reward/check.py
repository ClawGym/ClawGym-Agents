import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


def read_text_safe(p: Path) -> Optional[str]:
    try:
        if not p.exists() or not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def extract_between(text: str, start_tag: str, end_tag: str) -> Optional[str]:
    m = re.search(re.escape(start_tag) + r"(.*?)" + re.escape(end_tag), text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1)


def get_title(html: str) -> Optional[str]:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return unescape(m.group(1).strip())


def get_meta_description(html: str) -> Optional[str]:
    # Find <meta name="description" content="...">
    # Handle attributes in any order and single or double quotes
    metas = re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL)
    for tag in metas:
        name_m = re.search(r'name\s*=\s*("|\')description\1', tag, flags=re.IGNORECASE)
        if name_m:
            content_m = re.search(r'content\s*=\s*("|\')(.*?)\1', tag, flags=re.IGNORECASE | re.DOTALL)
            if content_m:
                return unescape(content_m.group(2).strip())
            else:
                return ""
    return None


def extract_lastmod_comment(html: str) -> Optional[str]:
    m = re.search(r"<!--\s*lastmod:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*-->", html)
    return m.group(1) if m else None


def extract_body_text(html: str) -> Optional[str]:
    body = extract_between(html, "<body>", "</body>")
    if body is None:
        return None
    # Remove scripts and styles
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<style\b.*?</style>", "", body, flags=re.IGNORECASE | re.DOTALL)
    # Remove tags to get visible text
    text = re.sub(r"<[^>]+>", " ", body)
    text = unescape(text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_yaml_base_url(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    m = re.search(r"^\s*base_url:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1)


def split_tokens(s: str) -> List[str]:
    return [t for t in re.split(r"[^A-Za-z]+", s.lower()) if t]


def strong_tokens(s: str) -> List[str]:
    return [t for t in split_tokens(s) if len(t) >= 4]


def parse_attributes(tag: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    # Remove starting < and closing >, keep inside
    inner = tag.strip()
    if inner.startswith("<"):
        inner = inner[1:]
    if inner.endswith(">"):
        inner = inner[:-1]
    # Split name and rest
    parts = inner.split(None, 1)
    if len(parts) == 1:
        return attrs
    rest = parts[1]
    # Find key=value pairs
    for m in re.finditer(r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(".*?"|\'.*?\'|[^"\'>\s]+)', rest, flags=re.DOTALL):
        k = m.group(1).lower()
        v = m.group(2)
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        attrs[k] = v
    return attrs


def find_img_contexts(html: str) -> List[Dict[str, Optional[str]]]:
    """
    Returns list of dicts: {src, alt, context_text}
    """
    results: List[Dict[str, Optional[str]]] = []
    for m in re.finditer(r"<img\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        attrs = parse_attributes(tag)
        src = attrs.get("src")
        alt = attrs.get("alt")
        # find nearest figcaption within same figure if any
        context_text = ""
        # Search forward within containing figure
        forward_slice = html[m.end(): m.end() + 800]
        figure_end = re.search(r"</figure>", forward_slice, flags=re.IGNORECASE)
        figcaption_forward = re.search(r"<figcaption>(.*?)</figcaption>", forward_slice, flags=re.IGNORECASE | re.DOTALL)
        if figcaption_forward and (not figure_end or figcaption_forward.start() < figure_end.start()):
            context_text = unescape(figcaption_forward.group(1).strip())
        else:
            # Search backward for figcaption before </figure>
            back_start = max(0, m.start() - 800)
            backward_slice = html[back_start:m.start()]
            # Find last figcaption tag
            figcaps = list(re.finditer(r"<figcaption>(.*?)</figcaption>", backward_slice, flags=re.IGNORECASE | re.DOTALL))
            if figcaps:
                context_text = unescape(figcaps[-1].group(1).strip())
        if not context_text:
            # Try nearest paragraph around
            # Search previous <p>...</p>
            back_start = max(0, m.start() - 800)
            backward_slice = html[back_start:m.start()]
            ps = list(re.finditer(r"<p\b[^>]*>(.*?)</p>", backward_slice, flags=re.IGNORECASE | re.DOTALL))
            if ps:
                context_text = unescape(ps[-1].group(1).strip())
        if not context_text:
            # Next paragraph
            forward_p = re.search(r"<p\b[^>]*>(.*?)</p>", forward_slice, flags=re.IGNORECASE | re.DOTALL)
            if forward_p:
                context_text = unescape(forward_p.group(1).strip())
        results.append({
            "src": src,
            "alt": alt,
            "context_text": context_text
        })
    return results


def normalize_whitespace(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()


def description_len_in_range(desc: Optional[str]) -> bool:
    if desc is None:
        return False
    L = len(desc.strip())
    return 150 <= L <= 160


def title_len_ok(title: Optional[str]) -> bool:
    if title is None:
        return False
    return len(title.strip()) <= 60


def placeholder_alt(val: Optional[str]) -> bool:
    if val is None:
        return True
    v = val.strip().lower()
    return v in {"", "image", "img", "photo", "picture", "placeholder"}


def get_focus_phrase(basename: str) -> Optional[str]:
    if basename == "index.html":
        return "session guitarist"
    if basename == "lessons.html":
        return "private guitar lessons"
    if basename == "setup.html":
        return "guitar setup"
    return None


def focus_phrase_present(title: Optional[str], desc: Optional[str], phrase: Optional[str]) -> bool:
    if phrase is None:
        return False
    t = (title or "").lower()
    d = (desc or "").lower()
    return (phrase in t) or (phrase in d)


def count_maestro(desc: Optional[str]) -> int:
    if not desc:
        return 0
    return len(re.findall(r"\bMaestro Rivera\b", desc))


def parse_sitemap(path: Path) -> Optional[List[Dict[str, str]]]:
    text = read_text_safe(path)
    if text is None:
        return None
    try:
        root = ET.fromstring(text)
    except Exception:
        return None
    ns = ""
    # Handle default namespace by stripping if present
    # We'll search tags ending with: urlset, url, loc, lastmod, changefreq, priority
    def tag_endswith(el, name):
        return el.tag == name or el.tag.endswith("}" + name)
    urls = []
    for url in root:
        if not tag_endswith(url, "url"):
            continue
        entry: Dict[str, str] = {}
        for child in url:
            if tag_endswith(child, "loc"):
                entry["loc"] = (child.text or "").strip()
            elif tag_endswith(child, "lastmod"):
                entry["lastmod"] = (child.text or "").strip()
            elif tag_endswith(child, "changefreq"):
                entry["changefreq"] = (child.text or "").strip()
            elif tag_endswith(child, "priority"):
                entry["priority"] = (child.text or "").strip()
        urls.append(entry)
    return urls


def load_json(path: Path) -> Optional[object]:
    text = read_text_safe(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def find_report_entries(report: object) -> Optional[List[dict]]:
    if isinstance(report, list):
        return [x for x in report if isinstance(x, dict)]
    if isinstance(report, dict):
        # Could be mapping page->entry
        entries = []
        for v in report.values():
            if isinstance(v, dict):
                entries.append(v)
        if entries:
            return entries
    return None


def compare_len_value(val_from_report: Optional[int], actual_string: Optional[str]) -> bool:
    if val_from_report is None or actual_string is None:
        return False
    # Accept if equals raw length or stripped length
    raw_len = len(actual_string)
    stripped_len = len(actual_string.strip())
    return val_from_report in (raw_len, stripped_len)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "index_title_revised": 0.0,
        "index_title_length_ok": 0.0,
        "index_meta_description_present": 0.0,
        "index_meta_description_length_ok": 0.0,
        "index_focus_phrase_included": 0.0,
        "index_maestro_mention_ok": 0.0,
        "index_body_copy_unchanged": 0.0,
        "index_images_alt_present_and_length": 0.0,
        "index_images_alt_contextual": 0.0,

        "lessons_title_revised": 0.0,
        "lessons_title_length_ok": 0.0,
        "lessons_meta_description_present": 0.0,
        "lessons_meta_description_length_ok": 0.0,
        "lessons_focus_phrase_included": 0.0,
        "lessons_maestro_mention_ok": 0.0,
        "lessons_body_copy_unchanged": 0.0,
        "lessons_images_alt_present_and_length": 0.0,
        "lessons_images_alt_contextual": 0.0,

        "setup_title_revised": 0.0,
        "setup_title_length_ok": 0.0,
        "setup_meta_description_present": 0.0,
        "setup_meta_description_length_ok": 0.0,
        "setup_focus_phrase_included": 0.0,
        "setup_maestro_mention_ok": 0.0,
        "setup_body_copy_unchanged": 0.0,
        "setup_images_alt_present_and_length": 0.0,
        "setup_images_alt_contextual": 0.0,

        "sitemap_urls_valid": 0.0,
        "sitemap_lastmod_correct": 0.0,
        "sitemap_changefreq_priority_correct": 0.0,
        "robots_allows_and_sitemap_correct": 0.0,
        "report_structure_and_fields": 0.0,
        "report_values_consistent": 0.0,
    }

    # Load config
    config_path = workspace / "site" / "site_config.yaml"
    config_text = read_text_safe(config_path)
    base_url = parse_yaml_base_url(config_text)

    # Prepare page list
    pages = ["index.html", "lessons.html", "setup.html"]

    # Read originals for lastmod and comparisons
    originals: Dict[str, Optional[str]] = {}
    originals_body_text: Dict[str, Optional[str]] = {}
    originals_title: Dict[str, Optional[str]] = {}
    originals_meta_desc: Dict[str, Optional[str]] = {}
    originals_imgs_contexts: Dict[str, List[Dict[str, Optional[str]]]] = {}
    originals_lastmod: Dict[str, Optional[str]] = {}

    for name in pages:
        p = workspace / "site" / "pages" / name
        html = read_text_safe(p)
        originals[name] = html
        originals_body_text[name] = extract_body_text(html) if html is not None else None
        originals_title[name] = get_title(html) if html is not None else None
        originals_meta_desc[name] = get_meta_description(html) if html is not None else None
        originals_imgs_contexts[name] = find_img_contexts(html) if html is not None else []
        originals_lastmod[name] = extract_lastmod_comment(html) if html is not None else None

    # Evaluate each output page
    for name in pages:
        out_p = workspace / "output" / "pages" / name
        out_html = read_text_safe(out_p)
        old_title = originals_title.get(name)
        old_desc = originals_meta_desc.get(name)
        new_title = get_title(out_html) if out_html is not None else None
        new_desc = get_meta_description(out_html) if out_html is not None else None

        # Determine key prefix
        prefix = name.split(".")[0]  # index, lessons, setup

        # Title revised
        if out_html is not None and new_title is not None and old_title is not None and new_title.strip() != old_title.strip():
            scores[f"{prefix}_title_revised"] = 1.0
        elif out_html is not None and new_title is not None and old_title is None:
            # No old title? If new is present, consider revised
            scores[f"{prefix}_title_revised"] = 1.0

        # Title length
        if out_html is not None and title_len_ok(new_title):
            scores[f"{prefix}_title_length_ok"] = 1.0

        # Meta description present
        if out_html is not None and new_desc is not None and new_desc.strip() != "":
            scores[f"{prefix}_meta_description_present"] = 1.0

        # Meta description length
        if out_html is not None and description_len_in_range(new_desc):
            scores[f"{prefix}_meta_description_length_ok"] = 1.0

        # Focus phrase inclusion in title or description
        phrase = get_focus_phrase(name)
        if out_html is not None and focus_phrase_present(new_title, new_desc, phrase):
            scores[f"{prefix}_focus_phrase_included"] = 1.0

        # Maestro mention count <= 1 in meta description
        if out_html is not None and new_desc is not None and count_maestro(new_desc) <= 1:
            scores[f"{prefix}_maestro_mention_ok"] = 1.0

        # Body copy unchanged (visible text)
        src_body = originals_body_text.get(name)
        out_body = extract_body_text(out_html) if out_html is not None else None
        if src_body is not None and out_body is not None and normalize_whitespace(src_body) == normalize_whitespace(out_body):
            scores[f"{prefix}_body_copy_unchanged"] = 1.0

        # Images alt present and length, and contextual
        src_imgs = originals_imgs_contexts.get(name, [])
        out_imgs = find_img_contexts(out_html) if out_html is not None else []
        # Map by src
        if out_html is not None and src_imgs:
            # check counts and mapping by src
            src_map = {img.get("src"): img for img in src_imgs}
            out_map = {img.get("src"): img for img in out_imgs}
            all_present = True
            all_contextual = True
            for src, src_img in src_map.items():
                out_img = out_map.get(src)
                if out_img is None:
                    all_present = False
                    all_contextual = False
                    continue
                new_alt = out_img.get("alt")
                if not new_alt or len(new_alt.strip()) == 0 or len(new_alt.strip()) > 100:
                    all_present = False
                # Context tokens
                context_text = src_img.get("context_text") or ""
                ctx_tokens = set(strong_tokens(context_text))
                alt_tokens = set(strong_tokens(new_alt or ""))
                # If no context tokens (edge case), fall back to using h1 and lead paragraph from original
                if not ctx_tokens and originals.get(name):
                    h1_m = re.search(r"<h1\b[^>]*>(.*?)</h1>", originals[name] or "", flags=re.IGNORECASE | re.DOTALL)
                    lead_m = re.search(r'<p\b[^>]*class\s*=\s*("|\')lead\1[^>]*>(.*?)</p>', originals[name] or "", flags=re.IGNORECASE | re.DOTALL)
                    h1_text = unescape((h1_m.group(1) if h1_m else "")).strip()
                    lead_text = unescape((lead_m.group(2) if lead_m else "")).strip()
                    ctx_tokens = set(strong_tokens(h1_text + " " + lead_text))
                if ctx_tokens:
                    if not (alt_tokens & ctx_tokens):
                        all_contextual = False
            if all_present:
                scores[f"{prefix}_images_alt_present_and_length"] = 1.0
            if all_contextual:
                scores[f"{prefix}_images_alt_contextual"] = 1.0
        elif out_html is not None and not src_imgs:
            # No images in source; trivially satisfied
            scores[f"{prefix}_images_alt_present_and_length"] = 1.0
            scores[f"{prefix}_images_alt_contextual"] = 1.0

    # Validate sitemap.xml
    sitemap_path = workspace / "output" / "seo" / "sitemap.xml"
    sitemap_entries = parse_sitemap(sitemap_path)
    expected_locs = {}
    for name in pages:
        if base_url:
            expected_locs[name] = f"{base_url}/{name}"
    if sitemap_entries is not None and base_url:
        locs_ok = True
        lastmod_ok = True
        cf_pr_ok = True
        # Build a map from loc to entry
        loc_map = {e.get("loc"): e for e in sitemap_entries if "loc" in e}
        # Must include exactly all three locs (order not enforced)
        for name in pages:
            expected_loc = expected_locs.get(name)
            if expected_loc not in loc_map:
                locs_ok = False
            else:
                entry = loc_map[expected_loc]
                # lastmod
                expected_lastmod = originals_lastmod.get(name)
                if not expected_lastmod or entry.get("lastmod") != expected_lastmod:
                    lastmod_ok = False
                # changefreq
                if entry.get("changefreq") != "weekly":
                    cf_pr_ok = False
                # priority
                expected_priority = "0.8" if name == "index.html" else "0.6"
                if entry.get("priority") != expected_priority:
                    cf_pr_ok = False
        # Also ensure no unexpected locs? We'll just require at least these three.
        if locs_ok:
            scores["sitemap_urls_valid"] = 1.0
        if lastmod_ok:
            scores["sitemap_lastmod_correct"] = 1.0
        if cf_pr_ok:
            scores["sitemap_changefreq_priority_correct"] = 1.0

    # Validate robots.txt
    robots_path = workspace / "output" / "seo" / "robots.txt"
    robots_text = read_text_safe(robots_path)
    if robots_text is not None and base_url:
        lines = [line.strip() for line in robots_text.splitlines() if line.strip() != ""]
        has_user_agent_all = any(re.match(r"(?i)^User-agent:\s*\*$", l) for l in lines)
        # Disallow all? Must not; Allow all crawling: either no Disallow lines or Disallow: (blank)
        disallow_lines = [l for l in lines if re.match(r"(?i)^Disallow:", l)]
        allows_all = True
        for l in disallow_lines:
            m = re.match(r"(?i)^Disallow:\s*(.*)$", l)
            if m:
                path = (m.group(1) or "").strip()
                if path != "" and path != "#":
                    allows_all = False
        has_sitemap = any(l == f"Sitemap: {base_url}/sitemap.xml" for l in lines)
        if has_user_agent_all and allows_all and has_sitemap:
            scores["robots_allows_and_sitemap_correct"] = 1.0

    # Validate report
    report_path = workspace / "output" / "reports" / "seo_changes.json"
    report_obj = load_json(report_path)
    structure_ok = False
    values_ok = False
    if report_obj is not None:
        entries = find_report_entries(report_obj)
        if entries is not None:
            # Check there is one entry per page
            entry_by_src: Dict[str, dict] = {}
            for e in entries:
                if isinstance(e, dict) and "source" in e and isinstance(e["source"], str):
                    entry_by_src[e["source"]] = e
            required_sources = [str(Path("site") / "pages" / n) for n in pages]
            # Structural checks
            struct_checks = []
            for src in required_sources:
                e = entry_by_src.get(src)
                if e is None:
                    struct_checks.append(False)
                    continue
                # Required keys
                keys_required = {
                    "source", "output",
                    "old_title", "new_title",
                    "old_meta_description", "new_meta_description",
                    "title_length", "description_length",
                    "title_len_ok", "description_len_ok",
                    "focus_phrase_included", "maestro_mentioned_once_or_less",
                    "images_updated"
                }
                has_keys = all(k in e for k in keys_required)
                # Types sanity
                types_ok = isinstance(e.get("images_updated"), list)
                struct_checks.append(has_keys and types_ok)
            structure_ok = all(struct_checks)
            # Values checks
            value_checks = []
            for name in pages:
                src = str(Path("site") / "pages" / name)
                outp = str(Path("output") / "pages" / name)
                e = entry_by_src.get(src)
                if e is None:
                    value_checks.append(False)
                    continue
                out_html = read_text_safe(workspace / outp)
                new_title = get_title(out_html) if out_html is not None else None
                new_desc = get_meta_description(out_html) if out_html is not None else None
                # Paths
                path_ok = (e.get("output") == outp)
                # Titles/descriptions match
                title_match = (new_title or "") == (e.get("new_title") or "")
                desc_match = (new_desc or "") == (e.get("new_meta_description") or "")
                # Old title and old meta description fields
                old_t = originals_title.get(name) or ""
                old_d = originals_meta_desc.get(name) or ""
                old_t_match = (e.get("old_title") or "") == old_t
                # old_meta_description should be empty if missing
                expected_old_desc_field = old_d if old_d else ""
                old_d_match = (e.get("old_meta_description") or "") == expected_old_desc_field
                # Length numbers
                title_len_field = e.get("title_length")
                desc_len_field = e.get("description_length")
                title_len_ok_match = compare_len_value(title_len_field, new_title)
                desc_len_ok_match = compare_len_value(desc_len_field, new_desc)
                # Constraint booleans
                phrase = get_focus_phrase(name)
                our_title_len_ok = title_len_ok(new_title)
                our_desc_len_ok = description_len_in_range(new_desc)
                our_focus_included = focus_phrase_present(new_title, new_desc, phrase)
                our_maestro_ok = count_maestro(new_desc) <= 1
                bools_ok = (
                    bool(e.get("title_len_ok")) == our_title_len_ok and
                    bool(e.get("description_len_ok")) == our_desc_len_ok and
                    bool(e.get("focus_phrase_included")) == our_focus_included and
                    bool(e.get("maestro_mentioned_once_or_less")) == our_maestro_ok
                )
                # Images updated array
                imgs_ok = True
                src_imgs = originals_imgs_contexts.get(name, [])
                out_imgs = find_img_contexts(out_html) if out_html is not None else []
                # Build map by src
                src_map = {img.get("src"): img for img in src_imgs}
                out_map = {img.get("src"): img for img in out_imgs}
                rep_imgs = e.get("images_updated") if isinstance(e.get("images_updated"), list) else []
                # Ensure report includes entry per source image
                if len(rep_imgs) != len(src_imgs):
                    imgs_ok = False
                else:
                    # Build report map by src
                    rep_map = {ri.get("src"): ri for ri in rep_imgs if isinstance(ri, dict) and "src" in ri}
                    for isrc, src_img in src_map.items():
                        r = rep_map.get(isrc)
                        out_img = out_map.get(isrc)
                        if r is None or out_img is None:
                            imgs_ok = False
                            continue
                        # old_alt should be null if missing or placeholder
                        orig_alt = src_img.get("alt")
                        rep_old_alt = r.get("old_alt", None)
                        if placeholder_alt(orig_alt):
                            if rep_old_alt is not None:
                                imgs_ok = False
                        else:
                            if rep_old_alt != orig_alt:
                                imgs_ok = False
                        # new_alt should match output
                        new_alt_out = out_img.get("alt")
                        if r.get("new_alt") != new_alt_out:
                            imgs_ok = False
                value_checks.append(path_ok and title_match and desc_match and old_t_match and old_d_match and title_len_ok_match and desc_len_ok_match and bools_ok and imgs_ok)
            values_ok = all(value_checks)
    if structure_ok:
        scores["report_structure_and_fields"] = 1.0
    if values_ok:
        scores["report_values_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()