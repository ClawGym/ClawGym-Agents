import json
import os
import sys
from html.parser import HTMLParser

def safe_read(path, mode="r", encoding="utf-8"):
    try:
        with open(path, mode, encoding=encoding) as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_text(s):
    if not isinstance(s, str):
        return ""
    return " ".join(s.split()).strip().lower()

def extract_content_items(data):
    blog_titles = []
    blog_dates = []
    blog_authors = []
    blog_categories = []
    search_titles = []

    def is_blog_context(path_keys, node):
        pk = "/".join([str(k).lower() for k in path_keys])
        if any(k in pk for k in ["blog", "post", "article"]):
            return True
        t = str(node.get("type", "")).lower()
        if t in ["blog", "post", "article"]:
            return True
        if any(k in node for k in ["author", "category"]) and "snippet" not in node:
            return True
        return False

    def is_search_context(path_keys, node):
        pk = "/".join([str(k).lower() for k in path_keys])
        if any(k in pk for k in ["search", "result"]):
            return True
        t = str(node.get("type", "")).lower()
        if t in ["search", "result"]:
            return True
        if "snippet" in node and "author" not in node:
            return True
        return False

    def walk(node, path_keys):
        if isinstance(node, dict):
            # Record items with a title
            if "title" in node and isinstance(node["title"], str):
                title = node["title"].strip()
                if is_blog_context(path_keys, node) and title:
                    blog_titles.append(title)
                    if "date" in node and isinstance(node["date"], str):
                        blog_dates.append(node["date"].strip())
                    if "author" in node and isinstance(node["author"], str):
                        blog_authors.append(node["author"].strip())
                    if "category" in node and isinstance(node["category"], str):
                        blog_categories.append(node["category"].strip())
                elif is_search_context(path_keys, node) and title:
                    search_titles.append(title)
                else:
                    # Fallback: if it looks like a blog item
                    if ("author" in node or "category" in node) and title:
                        blog_titles.append(title)
                        if "date" in node and isinstance(node["date"], str):
                            blog_dates.append(node["date"].strip())
                        if "author" in node and isinstance(node["author"], str):
                            blog_authors.append(node["author"].strip())
                        if "category" in node and isinstance(node["category"], str):
                            blog_categories.append(node["category"].strip())
                    else:
                        # Fallback to search if it has snippet
                        if "snippet" in node and title:
                            search_titles.append(title)
            # Recurse
            for k, v in node.items():
                walk(v, path_keys + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path_keys + [i])

    walk(data, [])
    # Deduplicate while preserving order
    def dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen and x:
                seen.add(x)
                out.append(x)
        return out
    return {
        "blog_titles": dedup(blog_titles),
        "blog_dates": dedup(blog_dates),
        "blog_authors": dedup(blog_authors),
        "blog_categories": dedup(blog_categories),
        "search_titles": dedup(search_titles),
    }

class SectionListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # list of (tag, attrs_dict)
        self.blog_section = {"depth": None, "tag": None, "seen": False}
        self.search_section = {"depth": None, "tag": None, "seen": False}

        # UL contexts stacks for both sections
        self.blog_ul_stack = []
        self.search_ul_stack = []

        # Anchor text capture
        self.in_blog_a_depth = None
        self.blog_anchor_texts = []
        self.current_blog_anchor_text = []

        self.in_search_a_depth = None
        self.search_anchor_texts = []
        self.current_search_anchor_text = []

        # Text accumulation for blog section (for date/author presence)
        self.blog_text_content = []

    def _attrs_to_dict(self, attrs):
        return {k.lower(): (v if v is not None else "") for (k, v) in attrs}

    def _is_within_blog(self):
        d = self.blog_section["depth"]
        return d is not None and len(self.stack) >= d

    def _is_within_search(self):
        d = self.search_section["depth"]
        return d is not None and len(self.stack) >= d

    def handle_starttag(self, tag, attrs):
        ad = self._attrs_to_dict(attrs)
        # Push to stack
        self.stack.append((tag.lower(), ad))

        # Section start detection
        if ad.get("aria-label") == "Blog index list" and self.blog_section["depth"] is None:
            self.blog_section["depth"] = len(self.stack)
            self.blog_section["tag"] = tag.lower()
            self.blog_section["seen"] = True
        if ad.get("aria-label") == "Search results list" and self.search_section["depth"] is None:
            self.search_section["depth"] = len(self.stack)
            self.search_section["tag"] = tag.lower()
            self.search_section["seen"] = True

        # UL tracking
        if self._is_within_blog() and tag.lower() == "ul":
            self.blog_ul_stack.append({
                "depth": len(self.stack),
                "li_count": 0,
                "li_attrs_ok": [],
                "current_li": None,  # dict with start_depth and attr_ok
            })
        if self._is_within_search() and tag.lower() == "ul":
            self.search_ul_stack.append({
                "depth": len(self.stack),
                "li_count": 0,
                "li_attrs_ok": [],
                "current_li": None,
            })

        # LI tracking and attribute checks for blog
        if self._is_within_blog() and tag.lower() == "li" and self.blog_ul_stack:
            ulctx = self.blog_ul_stack[-1]
            # Count only direct children of UL
            if len(self.stack) - 1 == ulctx["depth"]:
                # Start a new LI context
                required = "row"
                has_attr = (ad.get("data-click-target") == required)
                ulctx["current_li"] = {
                    "start_depth": len(self.stack),
                    "attr_ok": has_attr,
                }
        # Direct child elements of LI inside blog to check data-click-target
        if self._is_within_blog() and self.blog_ul_stack:
            ulctx = self.blog_ul_stack[-1]
            if ulctx["current_li"] is not None:
                # Direct child if depth is exactly +1
                if len(self.stack) == ulctx["current_li"]["start_depth"] + 1:
                    required = "row"
                    if ad.get("data-click-target") == required:
                        ulctx["current_li"]["attr_ok"] = True

        # LI tracking and attribute checks for search
        if self._is_within_search() and tag.lower() == "li" and self.search_ul_stack:
            ulctx = self.search_ul_stack[-1]
            if len(self.stack) - 1 == ulctx["depth"]:
                required = "title"
                has_attr = (ad.get("data-click-target") == required)
                ulctx["current_li"] = {
                    "start_depth": len(self.stack),
                    "attr_ok": has_attr,
                }
        if self._is_within_search() and self.search_ul_stack:
            ulctx = self.search_ul_stack[-1]
            if ulctx["current_li"] is not None:
                if len(self.stack) == ulctx["current_li"]["start_depth"] + 1:
                    required = "title"
                    if ad.get("data-click-target") == required:
                        ulctx["current_li"]["attr_ok"] = True

        # Anchor tracking
        if self._is_within_blog() and tag.lower() == "a" and self.in_blog_a_depth is None:
            self.in_blog_a_depth = len(self.stack)
            self.current_blog_anchor_text = []
        if self._is_within_search() and tag.lower() == "a" and self.in_search_a_depth is None:
            self.in_search_a_depth = len(self.stack)
            self.current_search_anchor_text = []

    def handle_endtag(self, tag):
        tag_lower = tag.lower()

        # Close LI for blog
        if self._is_within_blog() and tag_lower == "li" and self.blog_ul_stack:
            ulctx = self.blog_ul_stack[-1]
            if ulctx["current_li"] is not None:
                # Closing when top of stack is LI
                if len(self.stack) == ulctx["current_li"]["start_depth"]:
                    ulctx["li_count"] += 1
                    ulctx["li_attrs_ok"].append(bool(ulctx["current_li"]["attr_ok"]))
                    ulctx["current_li"] = None

        # Close LI for search
        if self._is_within_search() and tag_lower == "li" and self.search_ul_stack:
            ulctx = self.search_ul_stack[-1]
            if ulctx["current_li"] is not None:
                if len(self.stack) == ulctx["current_li"]["start_depth"]:
                    ulctx["li_count"] += 1
                    ulctx["li_attrs_ok"].append(bool(ulctx["current_li"]["attr_ok"]))
                    ulctx["current_li"] = None

        # Close UL for blog
        if self._is_within_blog() and tag_lower == "ul" and self.blog_ul_stack:
            ulctx = self.blog_ul_stack[-1]
            # UL closes when its depth equals current stack length
            if len(self.stack) == ulctx["depth"]:
                # Finalize this UL context by marking it with summary booleans
                ulctx["has_3"] = ulctx["li_count"] >= 3
                ulctx["all_li_attr_ok"] = (ulctx["li_count"] >= 1 and all(ulctx["li_attrs_ok"]))
                # Keep context stored; we pop after computing; the summary can be inspected later
                self.blog_ul_stack.pop()

        # Close UL for search
        if self._is_within_search() and tag_lower == "ul" and self.search_ul_stack:
            ulctx = self.search_ul_stack[-1]
            if len(self.stack) == ulctx["depth"]:
                ulctx["has_3"] = ulctx["li_count"] >= 3
                ulctx["all_li_attr_ok"] = (ulctx["li_count"] >= 1 and all(ulctx["li_attrs_ok"]))
                self.search_ul_stack.pop()

        # Close anchors
        if self.in_blog_a_depth is not None and tag_lower == "a" and len(self.stack) == self.in_blog_a_depth:
            text = "".join(self.current_blog_anchor_text).strip()
            if text:
                self.blog_anchor_texts.append(text)
            self.in_blog_a_depth = None
            self.current_blog_anchor_text = []

        if self.in_search_a_depth is not None and tag_lower == "a" and len(self.stack) == self.in_search_a_depth:
            text = "".join(self.current_search_anchor_text).strip()
            if text:
                self.search_anchor_texts.append(text)
            self.in_search_a_depth = None
            self.current_search_anchor_text = []

        # Close sections
        if self.blog_section["depth"] is not None and tag_lower == self.blog_section["tag"] and len(self.stack) == self.blog_section["depth"]:
            # Leaving blog section
            self.blog_section["depth"] = None
            self.blog_section["tag"] = None

        if self.search_section["depth"] is not None and tag_lower == self.search_section["tag"] and len(self.stack) == self.search_section["depth"]:
            self.search_section["depth"] = None
            self.search_section["tag"] = None

        # Pop from stack at the end
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self._is_within_blog():
            self.blog_text_content.append(data)
        if self.in_blog_a_depth is not None:
            self.current_blog_anchor_text.append(data)
        if self.in_search_a_depth is not None:
            self.current_search_anchor_text.append(data)

    def summary(self):
        # Summarize UL checks: section must contain at least one UL with >=3 LI
        blog_ul_has_3 = False
        blog_ul_all_li_attr_ok = False
        # The UL contexts that are still in stack would have been popped at end; we cannot see them now.
        # So instead, we rely on flags captured at closure; to capture them, we could store summaries in arrays.
        # Adjust: store during handle_endtag by appending to logs.
        return

def parse_html_and_checks(html_text):
    parser = SectionListParser()
    parser.feed(html_text or "")
    parser.close()

    # We need to compute UL conditions; since we popped contexts, we rely on capturing them as they closed.
    # Modify parser to store summaries during closing events. For minimal changes, re-parse with augmented parser.

    class CapturingSectionListParser(SectionListParser):
        def __init__(self):
            super().__init__()
            self.blog_ul_summaries = []
            self.search_ul_summaries = []
        def handle_endtag(self, tag):
            tag_lower = tag.lower()
            # Close LI for blog
            if self._is_within_blog() and tag_lower == "li" and self.blog_ul_stack:
                ulctx = self.blog_ul_stack[-1]
                if ulctx["current_li"] is not None:
                    if len(self.stack) == ulctx["current_li"]["start_depth"]:
                        ulctx["li_count"] += 1
                        ulctx["li_attrs_ok"].append(bool(ulctx["current_li"]["attr_ok"]))
                        ulctx["current_li"] = None
            # Close LI for search
            if self._is_within_search() and tag_lower == "li" and self.search_ul_stack:
                ulctx = self.search_ul_stack[-1]
                if ulctx["current_li"] is not None:
                    if len(self.stack) == ulctx["current_li"]["start_depth"]:
                        ulctx["li_count"] += 1
                        ulctx["li_attrs_ok"].append(bool(ulctx["current_li"]["attr_ok"]))
                        ulctx["current_li"] = None
            # Close UL for blog
            if self._is_within_blog() and tag_lower == "ul" and self.blog_ul_stack:
                ulctx = self.blog_ul_stack[-1]
                if len(self.stack) == ulctx["depth"]:
                    summary = {
                        "li_count": ulctx["li_count"],
                        "has_3": ulctx["li_count"] >= 3,
                        "all_li_attr_ok": (ulctx["li_count"] >= 1 and all(ulctx["li_attrs_ok"])),
                    }
                    self.blog_ul_summaries.append(summary)
                    self.blog_ul_stack.pop()
            # Close UL for search
            if self._is_within_search() and tag_lower == "ul" and self.search_ul_stack:
                ulctx = self.search_ul_stack[-1]
                if len(self.stack) == ulctx["depth"]:
                    summary = {
                        "li_count": ulctx["li_count"],
                        "has_3": ulctx["li_count"] >= 3,
                        "all_li_attr_ok": (ulctx["li_count"] >= 1 and all(ulctx["li_attrs_ok"])),
                    }
                    self.search_ul_summaries.append(summary)
                    self.search_ul_stack.pop()
            # Anchors and section boundaries and stack pop
            super().handle_endtag(tag)

    cp = CapturingSectionListParser()
    cp.feed(html_text or "")
    cp.close()

    blog_has_ul_with_3 = any(s["has_3"] for s in cp.blog_ul_summaries)
    blog_all_li_attr_ok = any(s["has_3"] and s["all_li_attr_ok"] for s in cp.blog_ul_summaries)
    search_has_ul_with_3 = any(s["has_3"] for s in cp.search_ul_summaries)
    search_all_li_attr_ok = any(s["has_3"] and s["all_li_attr_ok"] for s in cp.search_ul_summaries)

    return {
        "blog_section_seen": cp.blog_section["seen"],
        "search_section_seen": cp.search_section["seen"],
        "blog_has_ul_with_3": blog_has_ul_with_3,
        "blog_all_li_attr_ok": blog_all_li_attr_ok,
        "search_has_ul_with_3": search_has_ul_with_3,
        "search_all_li_attr_ok": search_all_li_attr_ok,
        "blog_anchor_texts": cp.blog_anchor_texts[:],
        "search_anchor_texts": cp.search_anchor_texts[:],
        "blog_all_text": normalize_text(" ".join(cp.blog_text_content)),
    }

def titles_match_in_anchors(titles, anchors, min_matches=2):
    # Normalize
    norm_titles = [normalize_text(t) for t in titles if isinstance(t, str) and t.strip()]
    norm_anchors = [normalize_text(a) for a in anchors if isinstance(a, str) and a.strip()]
    if not norm_titles or not norm_anchors:
        return False
    matches = 0
    # Exact normalization match first
    remaining_titles = []
    for t in norm_titles:
        if any(a == t for a in norm_anchors):
            matches += 1
        else:
            remaining_titles.append(t)
    if matches >= min_matches:
        return True
    # Fallback: substring match for long titles
    for t in remaining_titles:
        if len(t) >= 15 and any(t in a for a in norm_anchors):
            matches += 1
            if matches >= min_matches:
                return True
    return matches >= min_matches

def any_substring_present(values, haystack_norm):
    for v in values:
        nv = normalize_text(v)
        if nv and nv in haystack_norm:
            return True
    return False

def validate_config(cfg):
    checks = {}
    # Base existence
    checks["config_has_use_cases"] = isinstance(cfg, dict) and "use_cases" in cfg and isinstance(cfg["use_cases"], dict)
    blog = {}
    search = {}
    if checks["config_has_use_cases"]:
        blog = cfg["use_cases"].get("blog_index", {})
        search = cfg["use_cases"].get("search_results", {})
        if not isinstance(blog, dict):
            blog = {}
        if not isinstance(search, dict):
            search = {}
    # Helper getters
    def get_infinite(use_case):
        inf = use_case.get("infinite_scroll", {})
        if not isinstance(inf, dict):
            inf = {}
        pag = inf.get("pagination", {})
        if not isinstance(pag, dict):
            pag = {}
        return inf, pag

    def get_resp(use_case):
        resp = use_case.get("responsive", {})
        if not isinstance(resp, dict):
            resp = {}
        bps = resp.get("breakpoints", {})
        if not isinstance(bps, dict):
            bps = {}
        mob = bps.get("mobile", {})
        tab = bps.get("tablet", {})
        desk = bps.get("desktop", {})
        return bps, mob, tab, desk

    def get_spacing(use_case):
        sp = use_case.get("spacing", {})
        if not isinstance(sp, dict):
            sp = {}
        return sp

    # Blog checks
    checks["config_blog_variant_rich"] = (blog.get("variant") == "rich")
    checks["config_blog_density_relaxed"] = (blog.get("density") == "relaxed")
    mfields_b = blog.get("metadata_fields", [])
    if not isinstance(mfields_b, list):
        mfields_b = []
    mfset_b = set([str(x).lower() for x in mfields_b])
    checks["config_blog_metadata_fields_includes_date_author_category"] = all(x in mfset_b for x in ["date", "author", "category"])
    fpat_b = blog.get("f_pattern", {})
    if not isinstance(fpat_b, dict):
        fpat_b = {}
    checks["config_blog_f_left_align_true"] = (fpat_b.get("left_align") is True)
    checks["config_blog_clickable_area_row"] = (blog.get("clickable_area") == "row")
    checks["config_blog_thumbnail_support_present"] = isinstance(blog.get("thumbnail_support"), bool)
    checks["config_blog_truncate_long_titles_present"] = isinstance(blog.get("truncate_long_titles"), bool)
    checks["config_blog_divider_style_valid"] = blog.get("divider_style") in ["none", "divider", "zebra"]
    spacing_b = get_spacing(blog)
    checks["config_blog_spacing_item_gap_px_number"] = isinstance(spacing_b.get("item_gap_px"), (int, float))
    ttmp_b = blog.get("touch_target_min_px")
    checks["config_blog_touch_target_min_px_>=44"] = isinstance(ttmp_b, (int, float)) and ttmp_b >= 44
    bps_b, mob_b, tab_b, desk_b = get_resp(blog)
    checks["config_blog_responsive_breakpoints_has_all"] = all(isinstance(x, dict) for x in [mob_b, tab_b, desk_b]) and "mobile" in bps_b and "tablet" in bps_b and "desktop" in bps_b
    checks["config_blog_responsive_breakpoints_mobile_columns_1"] = isinstance(mob_b.get("columns"), (int, float)) and int(mob_b.get("columns")) == 1
    inf_b, pag_b = get_infinite(blog)
    checks["config_blog_infinite_scroll_flags"] = (inf_b.get("enabled") is True) and (inf_b.get("seo_pagination_fallback") is True)
    checks["config_blog_pagination_fields_valid"] = (isinstance(pag_b.get("page_param"), str) and isinstance(pag_b.get("page_size"), (int, float)) and isinstance(pag_b.get("page_url_template"), str) and "{page}" in pag_b.get("page_url_template", ""))

    # Search checks
    checks["config_search_variant_rich"] = (search.get("variant") == "rich")
    checks["config_search_density_compact"] = (search.get("density") == "compact")
    mfields_s = search.get("metadata_fields", [])
    if not isinstance(mfields_s, list):
        mfields_s = []
    mfset_s = set([str(x).lower() for x in mfields_s])
    checks["config_search_metadata_fields_includes_type_date"] = all(x in mfset_s for x in ["type", "date"])
    fpat_s = search.get("f_pattern", {})
    if not isinstance(fpat_s, dict):
        fpat_s = {}
    checks["config_search_f_left_align_true"] = (fpat_s.get("left_align") is True)
    checks["config_search_clickable_area_title"] = (search.get("clickable_area") == "title")
    checks["config_search_truncate_long_titles_present"] = isinstance(search.get("truncate_long_titles"), bool)
    checks["config_search_divider_style_valid"] = search.get("divider_style") in ["none", "divider", "zebra"]
    spacing_s = get_spacing(search)
    checks["config_search_spacing_item_gap_px_number"] = isinstance(spacing_s.get("item_gap_px"), (int, float))
    ttmp_s = search.get("touch_target_min_px")
    checks["config_search_touch_target_min_px_>=44"] = isinstance(ttmp_s, (int, float)) and ttmp_s >= 44
    bps_s, mob_s, tab_s, desk_s = get_resp(search)
    checks["config_search_responsive_breakpoints_has_all"] = all(isinstance(x, dict) for x in [mob_s, tab_s, desk_s]) and "mobile" in bps_s and "tablet" in bps_s and "desktop" in bps_s
    checks["config_search_responsive_breakpoints_mobile_columns_1"] = isinstance(mob_s.get("columns"), (int, float)) and int(mob_s.get("columns")) == 1
    inf_s, pag_s = get_infinite(search)
    checks["config_search_infinite_scroll_flags"] = (inf_s.get("enabled") is True) and (inf_s.get("seo_pagination_fallback") is True)
    checks["config_search_pagination_fields_valid"] = (isinstance(pag_s.get("page_param"), str) and isinstance(pag_s.get("page_size"), (int, float)) and isinstance(pag_s.get("page_url_template"), str) and "{page}" in pag_s.get("page_url_template", ""))
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {}

    # File existence checks
    list_config_path = os.path.join(output_dir, "list-config.json")
    list_spec_path = os.path.join(output_dir, "list-spec.md")
    prototype_path = os.path.join(output_dir, "prototype.html")

    checks["exists_list_config"] = os.path.isfile(list_config_path)
    checks["exists_list_spec"] = os.path.isfile(list_spec_path)
    checks["exists_prototype"] = os.path.isfile(prototype_path)

    # Non-empty checks
    checks["list_spec_non_empty"] = False
    checks["prototype_non_empty"] = False
    if checks["exists_list_spec"]:
        content = safe_read(list_spec_path)
        checks["list_spec_non_empty"] = bool(content and content.strip())
    if checks["exists_prototype"]:
        content = safe_read(prototype_path)
        checks["prototype_non_empty"] = bool(content and content.strip())

    # Config JSON validation and detailed checks
    checks["list_config_valid_json"] = False
    config_detail_checks = {}
    cfg = None
    if checks["exists_list_config"]:
        cfg = load_json(list_config_path)
        checks["list_config_valid_json"] = isinstance(cfg, dict)
        if isinstance(cfg, dict):
            config_detail_checks = validate_config(cfg)
        else:
            # Initialize expected keys to False
            config_detail_checks = validate_config({})

    checks.update(config_detail_checks)

    # Spec content keywords
    checks["spec_contains_keywords"] = False
    checks["spec_contains_44_and_seo_or_crawler"] = False
    if checks["list_spec_non_empty"]:
        spec_text = safe_read(list_spec_path) or ""
        low = spec_text.lower()
        required_keywords = ["f-pattern", "responsive", "infinite scroll", "accessibility", "spacing"]
        if all(k in low for k in required_keywords):
            checks["spec_contains_keywords"] = True
        if "44" in spec_text and ("seo" in low or "crawler" in low):
            checks["spec_contains_44_and_seo_or_crawler"] = True

    # Prototype structure checks and content checks referencing input/content.json
    proto_checks = {
        "proto_has_both_sections": False,
        "proto_blog_ul_has_3_li": False,
        "proto_search_ul_has_3_li": False,
        "proto_blog_titles_from_input_in_anchors": False,
        "proto_blog_li_have_data_click_target_row": False,
        "proto_search_titles_from_input_in_anchors": False,
        "proto_search_li_have_data_click_target_title": False,
        "proto_blog_has_date_author_from_input_text": False,
    }

    html_text = safe_read(prototype_path) if checks["prototype_non_empty"] else None
    content_json_path = os.path.join(input_dir, "content.json")
    content_json = load_json(content_json_path) if os.path.isfile(content_json_path) else None
    items = {"blog_titles": [], "blog_dates": [], "blog_authors": [], "blog_categories": [], "search_titles": []}
    if isinstance(content_json, (dict, list)):
        items = extract_content_items(content_json)

    if html_text:
        parsed = parse_html_and_checks(html_text)
        proto_checks["proto_has_both_sections"] = parsed["blog_section_seen"] and parsed["search_section_seen"]
        proto_checks["proto_blog_ul_has_3_li"] = parsed["blog_has_ul_with_3"]
        proto_checks["proto_search_ul_has_3_li"] = parsed["search_has_ul_with_3"]
        proto_checks["proto_blog_li_have_data_click_target_row"] = parsed["blog_all_li_attr_ok"]
        proto_checks["proto_search_li_have_data_click_target_title"] = parsed["search_all_li_attr_ok"]

        # Title presence in anchors
        if items["blog_titles"]:
            proto_checks["proto_blog_titles_from_input_in_anchors"] = titles_match_in_anchors(items["blog_titles"], parsed["blog_anchor_texts"], min_matches=2)
        if items["search_titles"]:
            proto_checks["proto_search_titles_from_input_in_anchors"] = titles_match_in_anchors(items["search_titles"], parsed["search_anchor_texts"], min_matches=2)

        # Blog date and author present in text
        has_date = False
        has_author = False
        blog_text_all = parsed["blog_all_text"]
        if items["blog_dates"]:
            has_date = any_substring_present(items["blog_dates"], blog_text_all)
        if items["blog_authors"]:
            has_author = any_substring_present(items["blog_authors"], blog_text_all)
        proto_checks["proto_blog_has_date_author_from_input_text"] = has_date and has_author

    checks.update(proto_checks)

    # Compute reward as fraction of passed checks.
    # Only count checks that are artifact-dependent (all of them are).
    # If no outputs at all, reward should be exactly 0.0
    total_checks = 0
    passed_checks = 0
    for key, val in checks.items():
        if isinstance(val, bool):
            total_checks += 1
            if val:
                passed_checks += 1

    reward = 0.0
    if os.path.isdir(output_dir):
        if total_checks > 0:
            reward = passed_checks / total_checks
    else:
        reward = 0.0

    # Ensure zero if output is missing or empty of required artifacts
    # If none of the three main files exist, reward must be 0.0
    if not (checks.get("exists_list_config") or checks.get("exists_list_spec") or checks.get("exists_prototype")):
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()