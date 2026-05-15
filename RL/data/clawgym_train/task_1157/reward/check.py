import json
import sys
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        records = []
        for r in data_rows:
            if len(r) != len(header):
                return header, None
            records.append({header[i]: r[i] for i in range(len(header))})
        return header, records
    except Exception:
        return None, None


def parse_inline_list(value: str) -> List[str]:
    items = []
    value = value.strip()
    if not value.startswith("[") or not value.endswith("]"):
        return items
    inner = value[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip() for p in inner.split(",")]
    for p in parts:
        if p.startswith(("'", '"')) and p.endswith(("'", '"')) and len(p) >= 2:
            p = p[1:-1]
        items.append(p)
    return items


def parse_yaml_calendar(text: str) -> Optional[Dict[str, Any]]:
    try:
        result: Dict[str, Any] = {}
        current_key: Optional[str] = None
        expecting_list = False
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            if re.match(r"^\s*-\s", line) and expecting_list and current_key:
                item = line.strip()
                if item.startswith("-"):
                    item = item[1:].strip()
                if item.startswith(("'", '"')) and item.endswith(("'", '"')) and len(item) >= 2:
                    item = item[1:-1]
                result.setdefault(current_key, []).append(item)
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
            if m:
                key = m.group(1)
                rest = m.group(2).strip()
                current_key = key
                if rest == "":
                    result[key] = []
                    expecting_list = True
                else:
                    expecting_list = False
                    if rest.startswith("[") and rest.endswith("]"):
                        result[key] = parse_inline_list(rest)
                    else:
                        if rest.isdigit():
                            result[key] = int(rest)
                        else:
                            if rest.startswith(("'", '"')) and rest.endswith(("'", '"')) and len(rest) >= 2:
                                rest = rest[1:-1]
                            result[key] = rest
            else:
                expecting_list = False
                current_key = None
        return result
    except Exception:
        return None


class SimpleHTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_h1 = False
        self.in_h2 = False
        self.page_title_parts: List[str] = []
        self.h1_parts: List[str] = []
        self.current_h2_parts: List[str] = []
        self.h2_list: List[str] = []
        self.meta_description: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "h1":
            self.in_h1 = True
        elif tag.lower() == "h2":
            self.in_h2 = True
            self.current_h2_parts = []
        elif tag.lower() == "meta":
            attrs_dict = {k.lower(): v for k, v in attrs}
            if attrs_dict.get("name", "").lower() == "description":
                self.meta_description = attrs_dict.get("content", self.meta_description)

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "h1":
            self.in_h1 = False
        elif tag.lower() == "h2":
            self.in_h2 = False
            h2_text = "".join(self.current_h2_parts).strip()
            if h2_text:
                self.h2_list.append(h2_text)
            self.current_h2_parts = []

    def handle_data(self, data):
        if self.in_title:
            self.page_title_parts.append(data)
        if self.in_h1:
            self.h1_parts.append(data)
        if self.in_h2:
            self.current_h2_parts.append(data)

    def get_result(self) -> Dict[str, Any]:
        return {
            "page_title": "".join(self.page_title_parts).strip(),
            "h1_text": "".join(self.h1_parts).strip(),
            "h2_headings": self.h2_list[:],
            "meta_description": self.meta_description or "",
        }


def html_extract(path: Path) -> Dict[str, Any]:
    text = read_text_safe(path) or ""
    parser = SimpleHTMLExtractor()
    try:
        parser.feed(text)
    except Exception:
        pass
    return parser.get_result()


def normalize_token(tok: str) -> str:
    cleaned = re.sub(r"[^A-Za-z]", "", tok).lower()
    return cleaned


def compute_top_keywords(h1_text: str, h2_list: List[str], stopwords: List[str], brand_keywords: List[str], top_n: int = 5) -> List[str]:
    text = " ".join([h1_text] + h2_list)
    tokens = []
    for raw in text.split():
        t = normalize_token(raw)
        if t:
            tokens.append(t)
    stops = set([s.lower() for s in stopwords])
    brands = set([b.lower() for b in brand_keywords])
    filtered = [t for t in tokens if t not in stops and t not in brands]
    freq: Dict[str, int] = {}
    for t in filtered:
        freq[t] = freq.get(t, 0) + 1
    sorted_tokens = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in sorted_tokens[:top_n]]


def split_semicolon_items(s: str) -> List[str]:
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p != ""]


def parse_pillars_md(text: str) -> List[Dict[str, Any]]:
    pillars = []
    current: Optional[Dict[str, Any]] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            if current is not None:
                pillars.append(current)
            pillar_name = line[3:].strip()
            current = {"pillar_name": pillar_name, "bullets": []}
        elif current is not None:
            striped = line.strip()
            if striped.startswith("- "):
                bullet = striped[2:].strip()
                current["bullets"].append(bullet)
            else:
                continue
    if current is not None:
        pillars.append(current)
    return pillars


def first_word_letters(s: str) -> str:
    parts = s.strip().split()
    if not parts:
        return ""
    fw = parts[0]
    fw = re.sub(r"[^A-Za-z]", "", fw)
    return fw


def base_name(path_str: str) -> str:
    return Path(path_str).name


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_channels_set": 0.0,
        "config_target_roles_set": 0.0,
        "config_weeks_unchanged": 0.0,
        "config_required_per_week_unchanged": 0.0,
        "config_stopwords_unchanged": 0.0,
        "config_brand_keywords_unchanged": 0.0,
        "competitor_themes_json_valid_structure": 0.0,
        "competitor_themes_entries_count": 0.0,
        "competitor_theme_alpha_extraction_correct": 0.0,
        "competitor_theme_beta_extraction_correct": 0.0,
        "content_calendar_csv_structure": 0.0,
        "content_calendar_row_count": 0.0,
        "content_calendar_weeks_coverage_and_per_week_counts": 0.0,
        "content_calendar_angles_per_week": 0.0,
        "content_calendar_channels_and_roles_valid": 0.0,
        "content_calendar_counterpoint_keyword_consistency": 0.0,
        "content_calendar_pillar_spotlight_consistency": 0.0,
        "content_calendar_diversity_competitors": 0.0,
        "content_calendar_diversity_pillars": 0.0,
        "content_calendar_titles_length": 0.0,
    }

    expected_weeks = ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25"]
    expected_required_per_week = 2
    expected_brand_keywords = ["ourco", "our", "company", "alpha", "beta", "corp", "inc"]
    expected_stopwords = ["and", "or", "the", "in", "with", "for", "to", "of", "a", "an", "on", "at", "by", "from", "we", "who", "as", "are", "is", "be", "our"]
    expected_channels_set = {"Blog", "LinkedIn", "Engineering Newsletter"}
    expected_target_roles_set = {"Senior Software Engineer", "Engineering Manager", "Tech Lead"}

    config_path = workspace / "input" / "config" / "calendar.yaml"
    config_text = read_text_safe(config_path)
    config_data = parse_yaml_calendar(config_text) if config_text is not None else None

    config_updated_ok = False
    if config_data is not None:
        ch = config_data.get("channels")
        tr = config_data.get("target_roles")
        if isinstance(ch, list) and set(ch) == expected_channels_set and len(ch) == len(expected_channels_set):
            scores["config_channels_set"] = 1.0
        if isinstance(tr, list) and set(tr) == expected_target_roles_set and len(tr) == len(expected_target_roles_set):
            scores["config_target_roles_set"] = 1.0
        config_updated_ok = scores["config_channels_set"] == 1.0 and scores["config_target_roles_set"] == 1.0

        # Only award unchanged checks if the update requirement is satisfied, to avoid baseline scoring on scaffold inputs.
        if config_updated_ok:
            weeks = config_data.get("weeks")
            if isinstance(weeks, list) and weeks == expected_weeks:
                scores["config_weeks_unchanged"] = 1.0

            rpw = config_data.get("required_per_week")
            if isinstance(rpw, int) and rpw == expected_required_per_week:
                scores["config_required_per_week_unchanged"] = 1.0

            sw = config_data.get("stopwords")
            if isinstance(sw, list) and sw == expected_stopwords:
                scores["config_stopwords_unchanged"] = 1.0

            bk = config_data.get("brand_keywords")
            if isinstance(bk, list) and bk == expected_brand_keywords:
                scores["config_brand_keywords_unchanged"] = 1.0

    competitor_dir = workspace / "input" / "competitor_pages"
    expected_html_files = sorted([p for p in competitor_dir.glob("*.html")])
    expected_competitors: Dict[str, Dict[str, Any]] = {}
    for p in expected_html_files:
        data = html_extract(p)
        top_kw = compute_top_keywords(data["h1_text"], data["h2_headings"], expected_stopwords, expected_brand_keywords, top_n=5)
        expected_competitors[p.name] = {
            "source_file": p.name,
            "page_title": data["page_title"],
            "meta_description": data["meta_description"],
            "h2_headings": data["h2_headings"],
            "top_keywords": top_kw,
        }

    competitor_json_path = workspace / "output" / "competitor_themes.json"
    competitor_json = load_json_safe(competitor_json_path)

    if isinstance(competitor_json, list):
        struct_ok = True
        for item in competitor_json:
            if not isinstance(item, dict):
                struct_ok = False
                break
            for key in ["source_file", "page_title", "meta_description", "h2_headings", "top_keywords"]:
                if key not in item:
                    struct_ok = False
                    break
            if not struct_ok:
                break
            if (not isinstance(item.get("source_file"), str) or
                not isinstance(item.get("page_title"), str) or
                not isinstance(item.get("meta_description"), str) or
                not isinstance(item.get("h2_headings"), list) or
                not isinstance(item.get("top_keywords"), list)):
                struct_ok = False
                break
            if any(not isinstance(x, str) for x in item.get("h2_headings", [])):
                struct_ok = False
                break
            if any(not isinstance(x, str) for x in item.get("top_keywords", [])):
                struct_ok = False
                break
        if struct_ok:
            scores["competitor_themes_json_valid_structure"] = 1.0

        provided_basenames = {base_name(it.get("source_file", "")) for it in competitor_json if isinstance(it, dict)}
        expected_basenames = {p.name for p in expected_html_files}
        if provided_basenames == expected_basenames and len(competitor_json) == len(expected_html_files):
            scores["competitor_themes_entries_count"] = 1.0

        provided_by_basename: Dict[str, Dict[str, Any]] = {}
        for it in competitor_json:
            if isinstance(it, dict):
                provided_by_basename[base_name(it.get("source_file", ""))] = it

        if "alpha_corp_careers.html" in expected_competitors and "alpha_corp_careers.html" in provided_by_basename:
            exp = expected_competitors["alpha_corp_careers.html"]
            got = provided_by_basename["alpha_corp_careers.html"]
            cond = (
                isinstance(got.get("page_title"), str) and got.get("page_title") == exp["page_title"] and
                isinstance(got.get("meta_description"), str) and got.get("meta_description") == exp["meta_description"] and
                isinstance(got.get("h2_headings"), list) and got.get("h2_headings") == exp["h2_headings"] and
                isinstance(got.get("top_keywords"), list) and got.get("top_keywords") == exp["top_keywords"]
            )
            if cond:
                scores["competitor_theme_alpha_extraction_correct"] = 1.0

        if "beta_inc_blog.html" in expected_competitors and "beta_inc_blog.html" in provided_by_basename:
            exp = expected_competitors["beta_inc_blog.html"]
            got = provided_by_basename["beta_inc_blog.html"]
            cond = (
                isinstance(got.get("page_title"), str) and got.get("page_title") == exp["page_title"] and
                isinstance(got.get("meta_description"), str) and got.get("meta_description") == exp["meta_description"] and
                isinstance(got.get("h2_headings"), list) and got.get("h2_headings") == exp["h2_headings"] and
                isinstance(got.get("top_keywords"), list) and got.get("top_keywords") == exp["top_keywords"]
            )
            if cond:
                scores["competitor_theme_beta_extraction_correct"] = 1.0

    calendar_csv_path = workspace / "output" / "content_calendar.csv"
    header, records = parse_csv_safe(calendar_csv_path)
    expected_header = ["week", "angle", "title", "target_role", "channel", "primary_keyword", "supporting_keywords", "source_type", "source_reference"]
    if header == expected_header:
        scores["content_calendar_csv_structure"] = 1.0

    if records is not None:
        if len(records) == 8:
            scores["content_calendar_row_count"] = 1.0

        cfg_weeks = config_data.get("weeks") if isinstance(config_data, dict) else None
        cfg_channels = config_data.get("channels") if isinstance(config_data, dict) else None
        cfg_roles = config_data.get("target_roles") if isinstance(config_data, dict) else None

        weeks_in_csv = [r.get("week", "") for r in records]
        if isinstance(cfg_weeks, list):
            all_weeks_ok = set(weeks_in_csv) == set(cfg_weeks) and len(weeks_in_csv) == 8
            per_week_counts_ok = True
            if all_weeks_ok:
                for w in cfg_weeks:
                    if sum(1 for r in records if r.get("week") == w) != 2:
                        per_week_counts_ok = False
                        break
            if all_weeks_ok and per_week_counts_ok:
                scores["content_calendar_weeks_coverage_and_per_week_counts"] = 1.0

        angles_ok = True
        if isinstance(cfg_weeks, list):
            for w in cfg_weeks:
                angles = [r.get("angle") for r in records if r.get("week") == w]
                if angles.count("Counterpoint") != 1 or angles.count("Pillar Spotlight") != 1:
                    angles_ok = False
                    break
        else:
            angles_ok = False
        if angles_ok:
            scores["content_calendar_angles_per_week"] = 1.0

        channels_roles_ok = True
        if isinstance(cfg_channels, list) and isinstance(cfg_roles, list):
            for r in records:
                if r.get("channel") not in cfg_channels or r.get("target_role") not in cfg_roles:
                    channels_roles_ok = False
                    break
        else:
            channels_roles_ok = False
        if channels_roles_ok:
            scores["content_calendar_channels_and_roles_valid"] = 1.0

        counterpoint_ok = True
        if isinstance(competitor_json, list):
            comp_map = {}
            for it in competitor_json:
                if isinstance(it, dict):
                    comp_map[base_name(it.get("source_file", ""))] = it
            for r in records:
                if r.get("angle") == "Counterpoint":
                    if r.get("source_type") != "competitor":
                        counterpoint_ok = False
                        break
                    src_ref = r.get("source_reference", "")
                    bn = base_name(src_ref)
                    if bn not in comp_map:
                        counterpoint_ok = False
                        break
                    comp = comp_map[bn]
                    topkw = comp.get("top_keywords", [])
                    if not isinstance(topkw, list) or len(topkw) < 3:
                        counterpoint_ok = False
                        break
                    if r.get("primary_keyword") != topkw[0]:
                        counterpoint_ok = False
                        break
                    supp = split_semicolon_items(r.get("supporting_keywords", ""))
                    if len(supp) != 2 or supp[0] != topkw[1] or supp[1] != topkw[2]:
                        counterpoint_ok = False
                        break
        else:
            counterpoint_ok = False
        if counterpoint_ok:
            scores["content_calendar_counterpoint_keyword_consistency"] = 1.0

        pillars_md_path = workspace / "input" / "internal" / "pillars.md"
        pillars_text = read_text_safe(pillars_md_path) or ""
        pillars = parse_pillars_md(pillars_text)
        pillar_map = {p["pillar_name"]: p for p in pillars if "pillar_name" in p}
        pillar_spotlight_ok = True
        for r in records:
            if r.get("angle") == "Pillar Spotlight":
                if r.get("source_type") != "pillar":
                    pillar_spotlight_ok = False
                    break
                ref = r.get("source_reference", "")
                if ref not in pillar_map:
                    pillar_spotlight_ok = False
                    break
                p = pillar_map[ref]
                bullets = p.get("bullets", [])
                if not isinstance(bullets, list) or len(bullets) < 2:
                    pillar_spotlight_ok = False
                    break
                expected_pk = first_word_letters(bullets[0])
                if r.get("primary_keyword") != expected_pk:
                    pillar_spotlight_ok = False
                    break
                supp = split_semicolon_items(r.get("supporting_keywords", ""))
                if len(supp) != 2 or supp[0] != bullets[0] or supp[1] != bullets[1]:
                    pillar_spotlight_ok = False
                    break
        if pillar_spotlight_ok:
            scores["content_calendar_pillar_spotlight_consistency"] = 1.0

        counterpoint_refs = [base_name(r.get("source_reference", "")) for r in records if r.get("angle") == "Counterpoint"]
        if len(set([ref for ref in counterpoint_refs if ref])) >= 2:
            scores["content_calendar_diversity_competitors"] = 1.0

        pillar_refs = [r.get("source_reference", "") for r in records if r.get("angle") == "Pillar Spotlight"]
        if len(set([ref for ref in pillar_refs if ref])) >= 2:
            scores["content_calendar_diversity_pillars"] = 1.0

        titles_ok = True
        for r in records:
            title = r.get("title", "")
            if not isinstance(title, str) or len(title) == 0 or len(title) > 80:
                titles_ok = False
                break
        if titles_ok:
            scores["content_calendar_titles_length"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()