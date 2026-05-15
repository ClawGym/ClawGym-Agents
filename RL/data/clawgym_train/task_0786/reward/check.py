import json
import csv
import re
import sys
import stat
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_json_load(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def strip_inline_comment(line: str) -> str:
    # Remove inline comments starting with # when not inside quotes
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
        elif ch == '#' and not in_single and not in_double:
            break
        else:
            result.append(ch)
        i += 1
    return "".join(result).rstrip("\n")


def parse_scalar(val: str):
    v = val.strip()
    if v == "":
        return ""
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def parse_simple_yaml(path: Path):
    text = read_text_file(path)
    if text is None:
        return None
    tokens = []
    for raw in text.splitlines():
        line = strip_inline_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")
        tokens.append((indent, content))

    root = {}
    stack = [(-1, root)]

    i = 0

    def next_deeper_index(idx, current_indent):
        j = idx + 1
        while j < len(tokens):
            ind, cont = tokens[j]
            if ind > current_indent:
                return j
            elif ind == current_indent:
                return None
            else:
                return None
        return None

    while i < len(tokens):
        indent, content = tokens[i]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            return None
        parent = stack[-1][1]
        if content.startswith("- "):
            item_str = content[2:].strip()
            item_val = parse_scalar(item_str)
            if isinstance(parent, list):
                parent.append(item_val)
            else:
                return None
            i += 1
            continue

        m = re.match(r"^([^:]+):(.*)$", content)
        if not m:
            return None
        key = m.group(1).strip()
        rest = m.group(2).strip()
        if rest == "":
            deeper_idx = next_deeper_index(i, indent)
            if deeper_idx is not None:
                _, deeper_content = tokens[deeper_idx]
                if deeper_content.startswith("- "):
                    new_container = []
                else:
                    new_container = {}
            else:
                new_container = {}
            if not isinstance(parent, dict):
                return None
            parent[key] = new_container
            stack.append((indent, new_container))
            i += 1
            continue
        else:
            val = parse_scalar(rest)
            if not isinstance(parent, dict):
                return None
            parent[key] = val
            i += 1
            continue

    return root


def slugify(text: str) -> str:
    if text is None:
        return ""
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


class HTMLSectionParser(HTMLParser):
    def __init__(self, heading_tags=None, paragraph_tag="p"):
        super().__init__()
        self.heading_tags = set(heading_tags or ["h2", "h3"])
        self.paragraph_tag = paragraph_tag
        self.sections = []
        self._in_heading = False
        self._in_p = False
        self._current_heading_text = []
        self._current_p_text = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self.heading_tags:
            self._in_heading = True
            self._current_heading_text = []
        elif t == self.paragraph_tag and self.sections:
            self._in_p = True
            self._current_p_text = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.heading_tags and self._in_heading:
            heading_text = "".join(self._current_heading_text).strip()
            self.sections.append({"heading": heading_text, "paragraphs": []})
            self._in_heading = False
            self._current_heading_text = []
        elif t == self.paragraph_tag and self._in_p:
            p_text = "".join(self._current_p_text).strip()
            if self.sections is not None and len(self.sections) > 0:
                self.sections[-1]["paragraphs"].append(p_text)
            self._in_p = False
            self._current_p_text = []

    def handle_data(self, data):
        if self._in_heading:
            self._current_heading_text.append(data)
        elif self._in_p:
            self._current_p_text.append(data)


class HTMLAnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = None
            for (k, v) in attrs:
                if k.lower() == "href":
                    href = v
                    break
            if href:
                self.hrefs.append(href)


def parse_html_sections(html_text: str, heading_selectors, paragraph_selector: str):
    heading_tags = [sel.strip().lower() for sel in heading_selectors if sel.strip()]
    paragraph_tag = (paragraph_selector or "p").strip().lower()
    parser = HTMLSectionParser(heading_tags=heading_tags, paragraph_tag=paragraph_tag)
    try:
        parser.feed(html_text)
    except Exception:
        pass
    return parser.sections


def parse_absolute_links(html_text: str):
    parser = HTMLAnchorParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    abs_links = []
    for href in parser.hrefs:
        if not isinstance(href, str):
            continue
        href_strip = href.strip()
        if re.match(r"^https?://", href_strip, flags=re.I):
            abs_links.append(href_strip)
    return abs_links


def compute_expected_ranking_from_json(sections):
    tuples = []
    for it in sections:
        sid = it.get("section_id")
        heading = it.get("heading")
        length = it.get("length_chars")
        if not isinstance(sid, str) or not isinstance(heading, str) or not isinstance(length, int):
            return None
        tuples.append((sid, heading, length))
    tuples_sorted = sorted(tuples, key=lambda x: (-x[2], x[0]))
    expected = []
    rank = 1
    for sid, heading, length in tuples_sorted:
        expected.append({"rank": rank, "section_id": sid, "heading": heading, "length_chars": length})
        rank += 1
    return expected


def load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_default_locale_sl": 0.0,
        "config_enabled_locales_contains_both_no_duplicates": 0.0,
        "config_license_sections_path_set": 0.0,
        "predeploy_script_exists": 0.0,
        "predeploy_script_executable_or_shebang": 0.0,
        "cc_by_raw_html_exists": 0.0,
        "cc_by_raw_html_contains_expected_markers": 0.0,
        "cc_by_sections_json_parsed_and_fields": 0.0,
        "cc_by_sections_json_slug_from_heading": 0.0,
        "cc_by_sections_json_length_chars_matches_text": 0.0,
        "cc_by_sections_ranked_csv_matches_json_sorting": 0.0,
        "gov_homepage_raw_html_exists": 0.0,
        "domain_counts_csv_matches_raw_and_whitelist": 0.0,
    }

    # Load config.yaml
    config_path = workspace / "input" / "config.yaml"
    config = parse_simple_yaml(config_path) if config_path.exists() else None

    # Check config default locale
    try:
        if (
            isinstance(config, dict)
            and isinstance(config.get("site"), dict)
            and config["site"].get("default_locale") == "sl"
        ):
            scores["config_default_locale_sl"] = 1.0
    except Exception:
        pass

    # Check enabled locales contains both and no duplicates
    try:
        enabled_locales = None
        if isinstance(config, dict) and isinstance(config.get("site"), dict):
            enabled_locales = config["site"].get("enabled_locales")
        if isinstance(enabled_locales, list):
            unique = set(enabled_locales)
            cond_contains = ("sl" in enabled_locales) and ("es-AR" in enabled_locales)
            cond_no_dups = (len(unique) == len(enabled_locales))
            if cond_contains and cond_no_dups:
                scores["config_enabled_locales_contains_both_no_duplicates"] = 1.0
    except Exception:
        pass

    # Check license sections path
    try:
        lic = None
        if isinstance(config, dict) and isinstance(config.get("content"), dict):
            lic = config["content"].get("license")
        if isinstance(lic, dict) and lic.get("license_sections_path") == "web/cc_by_sections.json":
            scores["config_license_sections_path_set"] = 1.0
    except Exception:
        pass

    # predeploy.sh existence and executability or shebang
    predeploy_path = workspace / "workspace" / "scripts" / "predeploy.sh"
    if predeploy_path.exists() and predeploy_path.is_file():
        scores["predeploy_script_exists"] = 1.0
        try:
            mode = predeploy_path.stat().st_mode
            is_exec = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        except Exception:
            is_exec = False
        shebang_ok = False
        try:
            with predeploy_path.open("rb") as f:
                first_bytes = f.read(2)
            shebang_ok = first_bytes == b"#!"
        except Exception:
            shebang_ok = False
        if is_exec or shebang_ok:
            scores["predeploy_script_executable_or_shebang"] = 1.0

    # License raw HTML
    cc_raw_path = workspace / "workspace" / "web" / "raw" / "cc-by-4.0-legalcode.html"
    if cc_raw_path.exists() and cc_raw_path.is_file():
        scores["cc_by_raw_html_exists"] = 1.0
        cc_html = read_text_file(cc_raw_path) or ""
        low = cc_html.lower()
        if ("creative commons" in low) and ("attribution 4.0" in low or "attribution 4.0 international" in low):
            scores["cc_by_raw_html_contains_expected_markers"] = 1.0

    # Load sample_html_patterns.yaml for selectors
    patterns_path = workspace / "input" / "sample_html_patterns.yaml"
    patterns = parse_simple_yaml(patterns_path) if patterns_path.exists() else None
    heading_selectors = ["h2", "h3"]
    paragraph_selector = "p"
    if isinstance(patterns, dict) and isinstance(patterns.get("cc_by_legalcode"), dict):
        cc_patterns = patterns["cc_by_legalcode"]
        hs = cc_patterns.get("heading_selectors")
        ps = cc_patterns.get("paragraph_selector")
        if isinstance(hs, list) and len(hs) > 0:
            heading_selectors = [str(x) for x in hs]
        if isinstance(ps, str) and ps.strip():
            paragraph_selector = ps

    # cc_by_sections.json checks
    cc_json_path = workspace / "workspace" / "web" / "cc_by_sections.json"
    cc_sections = None
    if cc_json_path.exists():
        cc_sections = safe_json_load(cc_json_path)
    valid_structure = False
    slug_ok = False
    length_ok = False
    if isinstance(cc_sections, list) and len(cc_sections) > 0:
        valid_structure = True
        slug_ok = True
        length_ok = True
        for item in cc_sections:
            if not isinstance(item, dict):
                valid_structure = False
                slug_ok = False
                length_ok = False
                break
            if not all(k in item for k in ("section_id", "heading", "text", "length_chars")):
                valid_structure = False
                slug_ok = False
                length_ok = False
                break
            if not isinstance(item.get("section_id"), str) or not isinstance(item.get("heading"), str) or not isinstance(item.get("text"), str) or not isinstance(item.get("length_chars"), int):
                valid_structure = False
                slug_ok = False
                length_ok = False
                break
            expected_slug = slugify(item["heading"])
            if expected_slug != item["section_id"]:
                slug_ok = False
            if len(item["text"]) != item["length_chars"]:
                length_ok = False
        if valid_structure:
            scores["cc_by_sections_json_parsed_and_fields"] = 1.0
        if slug_ok:
            scores["cc_by_sections_json_slug_from_heading"] = 1.0
        if length_ok:
            scores["cc_by_sections_json_length_chars_matches_text"] = 1.0

    # cc_by_sections_ranked.csv matches JSON ranking
    ranked_csv_path = workspace / "workspace" / "web" / "cc_by_sections_ranked.csv"
    if isinstance(cc_sections, list) and len(cc_sections) > 0 and ranked_csv_path.exists():
        rows = load_csv_rows(ranked_csv_path)
        if isinstance(rows, list) and len(rows) >= 1:
            header = rows[0]
            if header == ["rank", "section_id", "heading", "length_chars"]:
                parsed_rows = []
                ok_rows = True
                for r in rows[1:]:
                    if len(r) != 4:
                        ok_rows = False
                        break
                    try:
                        rank_val = int(r[0])
                        sid_val = r[1]
                        heading_val = r[2]
                        length_val = int(r[3])
                        parsed_rows.append({"rank": rank_val, "section_id": sid_val, "heading": heading_val, "length_chars": length_val})
                    except Exception:
                        ok_rows = False
                        break
                if ok_rows:
                    expected = compute_expected_ranking_from_json(cc_sections)
                    if expected is not None and expected == parsed_rows:
                        scores["cc_by_sections_ranked_csv_matches_json_sorting"] = 1.0

    # Gov.si homepage raw HTML
    gov_raw_path = workspace / "workspace" / "web" / "raw" / "gov-si-homepage.html"
    if gov_raw_path.exists() and gov_raw_path.is_file():
        scores["gov_homepage_raw_html_exists"] = 1.0

    # domain_counts.csv matches parsed counts from raw and whitelist
    domain_counts_csv_path = workspace / "workspace" / "web" / "domain_counts.csv"
    if gov_raw_path.exists() and domain_counts_csv_path.exists() and isinstance(config, dict):
        whitelist = None
        if isinstance(config.get("web"), dict):
            wl = config["web"].get("link_domains_whitelist")
            if isinstance(wl, list):
                whitelist = [str(x).lower() for x in wl]
        if whitelist is not None:
            html = read_text_file(gov_raw_path) or ""
            links = parse_absolute_links(html)
            hosts = []
            for href in links:
                try:
                    parsed = urlparse(href)
                    host = parsed.hostname
                    if host:
                        host_low = host.lower()
                        for suf in whitelist:
                            if host_low.endswith(suf):
                                hosts.append(host_low)
                                break
                except Exception:
                    continue
            counts = {}
            for h in hosts:
                counts[h] = counts.get(h, 0) + 1
            expected_rows = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
            rows = load_csv_rows(domain_counts_csv_path)
            if isinstance(rows, list) and len(rows) >= 1 and rows[0] == ["domain", "count"]:
                data_rows = rows[1:]
                parsed_list = []
                ok = True
                for r in data_rows:
                    if len(r) != 2:
                        ok = False
                        break
                    dom = r[0].strip().lower()
                    try:
                        cnt = int(r[1])
                    except Exception:
                        ok = False
                        break
                    parsed_list.append((dom, cnt))
                if ok:
                    if parsed_list == expected_rows:
                        scores["domain_counts_csv_matches_raw_and_whitelist"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()