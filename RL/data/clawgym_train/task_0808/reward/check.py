import json
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser

BANNED_TERMS = ["breaking", "crisis", "panic", "urgent", "shocking", "survive"]

REQUIRED_REPORT_COLUMNS = [
    "file_path",
    "original_title",
    "new_title",
    "original_description",
    "new_description",
    "title_length",
    "description_length",
    "keywords (as parsed)",
    "keyword_in_title",
    "keyword_in_description",
    "banned_terms_found",
    "canonical_href",
    "changes",
]


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def _load_json(p: Path):
    try:
        return json.loads(_read_text(p))
    except Exception:
        return None


def _normalize_ws(s: str) -> str:
    return " ".join((s or "").split())


def _contains_any_keyword(text: str, keywords: list) -> bool:
    t = (text or "").lower()
    for kw in keywords:
        kwn = kw.strip().lower()
        if kwn and kwn in t:
            return True
    return False


def _find_banned_terms(texts: list) -> list:
    found = set()
    for t in texts:
        tl = (t or "").lower()
        for b in BANNED_TERMS:
            if b in tl:
                found.add(b)
    return sorted(found)


class HTMLInfoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.titles = []
        self.current_title = []
        self.meta = []  # list of dicts
        self.links = []  # list of dicts
        self.in_body = False
        self.body_text_parts = []
        self.in_anchor = False
        self.current_anchor_text = []
        self.current_anchor_href = None
        self.anchors = []  # list of (href, text)
        self.first_h1 = None
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        attrs_dict = {k.lower(): v for k, v in attrs}
        if tag_l == "head":
            self.in_head = True
        if tag_l == "body":
            self.in_body = True
        if self.in_head and tag_l == "title":
            self.in_title = True
            self.current_title = []
        if self.in_head and tag_l == "meta":
            self.meta.append(attrs_dict)
        if self.in_head and tag_l == "link":
            self.links.append(attrs_dict)
        if self.in_body and tag_l == "a":
            self.in_anchor = True
            self.current_anchor_text = []
            self.current_anchor_href = attrs_dict.get("href")
        if self.in_body and tag_l == "h1" and self.first_h1 is None:
            self.in_h1 = True

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l == "head":
            self.in_head = False
        if tag_l == "body":
            self.in_body = False
        if tag_l == "title" and self.in_title:
            self.in_title = False
            self.titles.append("".join(self.current_title))
            self.current_title = []
        if tag_l == "a" and self.in_anchor:
            text = "".join(self.current_anchor_text)
            self.anchors.append((self.current_anchor_href, text))
            self.in_anchor = False
            self.current_anchor_text = []
            self.current_anchor_href = None
        if tag_l == "h1" and self.in_h1:
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_title:
            self.current_title.append(data)
        if self.in_body:
            if self.in_anchor:
                self.current_anchor_text.append(data)
            # Collect body text for comparison
            self.body_text_parts.append(data)
            if self.in_h1 and self.first_h1 is None:
                # Capture first h1 text
                self.first_h1 = (self.first_h1 or "") + data

    def get_title(self):
        if self.titles:
            return "".join(self.titles[0])
        return None

    def get_meta_by_name(self, name):
        out = []
        for m in self.meta:
            if m.get("name", "").lower() == name.lower():
                out.append(m)
        return out

    def get_link_rels(self, rel_value):
        out = []
        for l in self.links:
            rel = l.get("rel", "")
            if any(rv.strip().lower() == rel_value.lower() for rv in rel.split()):
                out.append(l)
        return out

    def get_body_text(self):
        return "".join(self.body_text_parts)


def _parse_html(path: Path):
    text = _read_text(path)
    if not text:
        return None
    parser = HTMLInfoParser()
    try:
        parser.feed(text)
    except Exception:
        # Even if parse error occurs, we keep what we have
        pass
    return parser


def _extract_keywords_from_meta(parser: HTMLInfoParser):
    metas = parser.get_meta_by_name("keywords") if parser else []
    if not metas:
        return []
    content = metas[0].get("content") or ""
    parts = [p.strip() for p in content.split(",")]
    return [p for p in parts if p]


def _title_from_parser(parser: HTMLInfoParser):
    if not parser:
        return None
    t = parser.get_title()
    return t if t is not None else None


def _meta_content(parser: HTMLInfoParser, name: str):
    if not parser:
        return None
    ms = parser.get_meta_by_name(name)
    if not ms:
        return None
    return ms[0].get("content")


def _canonical_href(parser: HTMLInfoParser):
    if not parser:
        return None
    links = parser.get_link_rels("canonical")
    if not links:
        return None
    return links[0].get("href")


def _robots_meta_contents(parser: HTMLInfoParser):
    if not parser:
        return []
    metas = parser.get_meta_by_name("robots")
    contents = []
    for m in metas:
        contents.append((m.get("content") or "").strip().lower())
    return contents


def _compare_body_preserved(orig_parser: HTMLInfoParser, out_parser: HTMLInfoParser) -> bool:
    if not orig_parser or not out_parser:
        return False
    # Compare normalized text content
    orig_text = _normalize_ws(orig_parser.get_body_text())
    out_text = _normalize_ws(out_parser.get_body_text())
    if orig_text != out_text:
        return False
    # Compare anchors (href and text)
    orig_anchors = [(h or "", _normalize_ws(t or "")) for h, t in orig_parser.anchors]
    out_anchors = [(h or "", _normalize_ws(t or "")) for h, t in out_parser.anchors]
    return orig_anchors == out_anchors


def _bool_from_text(s: str):
    return str(s).strip().lower() in ("true", "1", "yes")


def _slug_from_filename(name: str) -> str:
    # e.g., "study-habits.html" -> "study_habits"
    base = name.lower()
    if base.endswith(".html"):
        base = base[:-5]
    return base.replace("-", "_")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {}

    # Paths
    input_site = workspace / "input" / "site"
    output_site = workspace / "output" / "optimized" / "site"
    report_csv_path = workspace / "output" / "report" / "seo_changes.csv"

    # Load configs
    input_config_path = input_site / "config.json"
    output_config_path = output_site / "config.json"
    input_config = _load_json(input_config_path)
    output_config = _load_json(output_config_path)

    # Determine site_url for canonical and robots
    site_url = None
    if output_config and isinstance(output_config, dict) and "site_url" in output_config:
        site_url = output_config.get("site_url")
    elif input_config and isinstance(input_config, dict) and "site_url" in input_config:
        site_url = input_config.get("site_url")

    # Pages to check
    pages = ["index.html", "study-habits.html", "news-thoughts.html"]

    # Pre-parse original input HTMLs for comparison and extracting original keywords/titles/descriptions
    original_parsers = {}
    for fname in pages:
        p = input_site / fname
        original_parsers[fname] = _parse_html(p)

    # Parse output HTMLs
    output_parsers = {}
    for fname in pages:
        p = output_site / fname
        output_parsers[fname] = _parse_html(p)

    # Compute expected canonical hrefs
    expected_canonical = {}
    for fname in pages:
        if site_url:
            expected_canonical[fname] = f"{site_url}/{fname}"
        else:
            expected_canonical[fname] = None

    # Per-page checks
    for fname in pages:
        slug = _slug_from_filename(fname)
        oparser = output_parsers.get(fname)
        iparser = original_parsers.get(fname)

        # Initialize to 0.0
        keys = [
            f"{slug}_title_length_valid",
            f"{slug}_description_length_valid",
            f"{slug}_keyword_in_title",
            f"{slug}_keyword_in_description",
            f"{slug}_banned_terms_avoided",
            f"{slug}_meta_robots_single_index_follow",
            f"{slug}_canonical_correct",
            f"{slug}_body_unchanged",
            f"{slug}_title_rewritten",
            f"{slug}_description_rewritten",
        ]
        for k in keys:
            scores[k] = 0.0

        if oparser is None or iparser is None:
            # Cannot evaluate this page
            continue

        out_title = _title_from_parser(oparser) or ""
        out_desc = _meta_content(oparser, "description") or ""
        in_title = _title_from_parser(iparser) or ""
        in_desc = _meta_content(iparser, "description") or ""
        keywords = _extract_keywords_from_meta(iparser)

        # Title and description length checks
        if 50 <= len(out_title) <= 60:
            scores[f"{slug}_title_length_valid"] = 1.0
        if 120 <= len(out_desc) <= 155:
            scores[f"{slug}_description_length_valid"] = 1.0

        # Keyword inclusion checks
        if keywords:
            if _contains_any_keyword(out_title, keywords):
                scores[f"{slug}_keyword_in_title"] = 1.0
            if _contains_any_keyword(out_desc, keywords):
                scores[f"{slug}_keyword_in_description"] = 1.0
        else:
            # If no keywords in original, cannot verify; leave as 0.0
            pass

        # Banned terms avoided
        banned_found = _find_banned_terms([out_title, out_desc])
        if not banned_found:
            scores[f"{slug}_banned_terms_avoided"] = 1.0

        # Meta robots single index,follow
        robots_contents = _robots_meta_contents(oparser)
        if len(robots_contents) == 1 and robots_contents[0] == "index,follow":
            scores[f"{slug}_meta_robots_single_index_follow"] = 1.0

        # Canonical correct single and href matches expected
        can_href = _canonical_href(oparser)
        expected_href = expected_canonical.get(fname)
        # Check exactly one canonical link
        canon_links = oparser.get_link_rels("canonical")
        if len(canon_links) == 1 and can_href and expected_href and can_href == expected_href:
            scores[f"{slug}_canonical_correct"] = 1.0

        # Body unchanged (text and anchors)
        if _compare_body_preserved(iparser, oparser):
            scores[f"{slug}_body_unchanged"] = 1.0

        # Title and description rewritten (different from original)
        if _normalize_ws(out_title) != _normalize_ws(in_title):
            scores[f"{slug}_title_rewritten"] = 1.0
        if _normalize_ws(out_desc) != _normalize_ws(in_desc):
            scores[f"{slug}_description_rewritten"] = 1.0

    # Config JSON updates
    scores["config_json_updated_correct"] = 0.0
    if output_config and isinstance(output_config, dict) and input_config and isinstance(input_config, dict):
        expected_updates = {
            "site_name": "Calmer Campus Notes",
            "title_suffix": " | Calmer Campus",
            "meta_description_default": "Student wellness, study tips, and balanced notes.",
        }
        ok = True
        for k, v in expected_updates.items():
            if output_config.get(k) != v:
                ok = False
                break
        # Other keys unchanged
        if ok:
            for k, v in input_config.items():
                if k not in expected_updates:
                    if output_config.get(k) != v:
                        ok = False
                        break
        if ok:
            scores["config_json_updated_correct"] = 1.0

    # Robots.txt update
    scores["robots_txt_updated_correct"] = 0.0
    robots_path = output_site / "robots.txt"
    robots_text = _read_text(robots_path)
    if robots_text and site_url:
        expected_lines = [
            "User-agent: *",
            "Disallow: /drafts/",
            "Disallow: /private/",
            "Allow: /",
            f"Sitemap: {site_url}/sitemap.xml",
        ]
        actual_lines = [line.rstrip() for line in robots_text.splitlines()]
        # Remove empty trailing lines
        while actual_lines and actual_lines[-1] == "":
            actual_lines.pop()
        if actual_lines == expected_lines:
            scores["robots_txt_updated_correct"] = 1.0

    # Report CSV checks
    scores["report_exists"] = 0.0
    scores["report_has_three_rows"] = 0.0
    scores["report_values_consistent"] = 0.0

    if report_csv_path.exists():
        scores["report_exists"] = 1.0
        try:
            with report_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                header = reader.fieldnames or []
        except Exception:
            rows = []
            header = []

        # Check required columns present
        if all(col in header for col in REQUIRED_REPORT_COLUMNS) and len(rows) == 3:
            scores["report_has_three_rows"] = 1.0

            # Build expected mapping by file name using canonical href and file name
            # Compute expected values from parsed input and output
            consistency_ok = True

            for fname in pages:
                slug = _slug_from_filename(fname)
                iparser = original_parsers.get(fname)
                oparser = output_parsers.get(fname)

                if iparser is None or oparser is None:
                    consistency_ok = False
                    break

                orig_title = _title_from_parser(iparser) or ""
                orig_desc = _meta_content(iparser, "description") or ""
                new_title = _title_from_parser(oparser) or ""
                new_desc = _meta_content(oparser, "description") or ""
                kws = _extract_keywords_from_meta(iparser)
                kw_in_title = _contains_any_keyword(new_title, kws)
                kw_in_desc = _contains_any_keyword(new_desc, kws)
                banned = _find_banned_terms([new_title, new_desc])
                canon = _canonical_href(oparser) or ""
                expected_href = expected_canonical.get(fname) or ""

                # Find row for this page
                matched_row = None
                # Prefer canonical_href match
                for r in rows:
                    if (r.get("canonical_href") or "").strip() == expected_href:
                        matched_row = r
                        break
                if matched_row is None:
                    # Fallback: match by file name presence in file_path
                    for r in rows:
                        fp = (r.get("file_path") or "").lower()
                        if fname.lower() in fp:
                            matched_row = r
                            break
                if matched_row is None:
                    consistency_ok = False
                    break

                # Validate fields
                if (matched_row.get("original_title") or "") != orig_title:
                    consistency_ok = False
                if (matched_row.get("new_title") or "") != new_title:
                    consistency_ok = False
                if (matched_row.get("original_description") or "") != orig_desc:
                    consistency_ok = False
                if (matched_row.get("new_description") or "") != new_desc:
                    consistency_ok = False

                # Lengths
                try:
                    tlen = int(str(matched_row.get("title_length") or "0"))
                    dlen = int(str(matched_row.get("description_length") or "0"))
                except Exception:
                    consistency_ok = False
                    tlen = -1
                    dlen = -1
                if tlen != len(new_title) or dlen != len(new_desc):
                    consistency_ok = False

                # Keywords parsed
                row_kws_raw = matched_row.get("keywords (as parsed)") or ""
                row_kws = [p.strip() for p in row_kws_raw.split(",") if p.strip()]
                # Compare case-insensitive sets
                if set(k.lower() for k in row_kws) != set(k.lower() for k in kws):
                    consistency_ok = False

                # Keyword in title/description
                row_kit = _bool_from_text(matched_row.get("keyword_in_title"))
                row_kid = _bool_from_text(matched_row.get("keyword_in_description"))
                if row_kit != kw_in_title or row_kid != kw_in_desc:
                    consistency_ok = False

                # Banned terms found list
                row_banned_raw = matched_row.get("banned_terms_found") or ""
                row_banned = [p.strip().lower() for p in row_banned_raw.split(";") if p.strip()]
                if set(row_banned) != set(banned):
                    consistency_ok = False

                # Canonical href matches found in output and expected
                if (matched_row.get("canonical_href") or "") != canon or canon != expected_href:
                    consistency_ok = False

                # Changes non-empty
                if not (matched_row.get("changes") or "").strip():
                    consistency_ok = False

                if not consistency_ok:
                    break

            if consistency_ok:
                scores["report_values_consistent"] = 1.0
        else:
            # If columns missing or row count wrong, values_consistent remains 0.0
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()