import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_csv_safe(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def parse_yaml_front_matter(md_text: str) -> Optional[dict]:
    lines = md_text.splitlines()
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None
    data = {}
    current_list_key = None
    in_abstract_block = False
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            break
        if in_abstract_block:
            continue
        stripped = line.strip()
        if not stripped:
            current_list_key = None
            continue
        if re.match(r'^abstract:\s*\|', stripped):
            in_abstract_block = True
            current_list_key = None
            continue
        m_key = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$', stripped)
        if m_key:
            key = m_key.group(1)
            value = m_key.group(2)
            if key in ("authors", "keywords"):
                data[key] = []
                current_list_key = key
                continue
            elif key == "title":
                v = value.strip()
                if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                    v = v[1:-1]
                elif v.startswith("'") and v.endswith("'") and len(v) >= 2:
                    v = v[1:-1]
                data["title"] = v
                current_list_key = None
                continue
            elif key == "page_count":
                try:
                    data["page_count"] = int(value.strip())
                except Exception:
                    return None
                current_list_key = None
                continue
            else:
                current_list_key = None
                continue
        if current_list_key and re.match(r'^-\s+', stripped):
            item = re.sub(r'^-\s+', '', stripped).strip()
            data[current_list_key].append(item)
            continue
        if current_list_key and re.match(r'^\s*-\s+', line):
            item = re.sub(r'^\s*-\s+', '', line).strip()
            data[current_list_key].append(item)
            continue
        continue
    required = ("title", "page_count", "keywords")
    for k in required:
        if k not in data:
            return None
    if not isinstance(data.get("keywords"), list):
        return None
    if "authors" in data and not isinstance(data["authors"], list):
        return None
    return data


class VenuesHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self.current_cell_text_parts: List[str] = []
        self.current_table_id: Optional[str] = None
        self._tag_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        if tag == "table":
            attrs_dict = dict(attrs)
            self.current_table_id = attrs_dict.get("id")
            if self.current_table_id == "venues":
                self.in_table = True
        if tag == "tbody" and self.in_table:
            self.in_tbody = True
        if tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        if tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell_text_parts = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell_text_parts.append(data)

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag == "td" and self.in_td:
            text = "".join(self.current_cell_text_parts).strip()
            self.current_row.append(text)
            self.in_td = False
            self.current_cell_text_parts = []
        if tag == "tr" and self.in_tr:
            if len(self.current_row) == 4:
                self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []
        if tag == "tbody":
            self.in_tbody = False
        if tag == "table":
            self.in_table = False
            self.current_table_id = None


def parse_venues_from_html(html_text: str) -> Optional[List[Dict]]:
    try:
        parser = VenuesHTMLParser()
        parser.feed(html_text)
        venues = []
        for row in parser.rows:
            name, scope_keywords, max_pages, vformat = row
            try:
                mp = int(str(max_pages).strip())
            except Exception:
                return None
            kw_list = [k.strip() for k in scope_keywords.split(",")]
            venues.append({
                "name": name.strip(),
                "scope_keywords": kw_list,
                "max_pages": mp,
                "format": vformat.strip(),
            })
        return venues
    except Exception:
        return None


def tokenize_keywords(keywords: List[str]) -> List[str]:
    tokens = []
    for k in keywords:
        if k is None:
            continue
        t = k.strip().lower()
        if t:
            tokens.append(t)
    return tokens


def compute_expected_eligibility(drafts_dir: Path, html_path: Path) -> Optional[Dict[str, Dict]]:
    draft_files = list(drafts_dir.rglob("*.md")) if drafts_dir.exists() else []
    draft_infos = []
    for df in draft_files:
        text = read_text_safe(df)
        if text is None:
            return None
        fm = parse_yaml_front_matter(text)
        if fm is None:
            return None
        draft_infos.append({
            "path": str(df.as_posix()),
            "title": fm.get("title"),
            "keywords": tokenize_keywords(fm.get("keywords", [])),
            "page_count": fm.get("page_count"),
        })
    html_text = read_text_safe(html_path)
    if html_text is None:
        return None
    venues = parse_venues_from_html(html_text)
    if venues is None:
        return None
    result = {}
    for d in draft_infos:
        eligible = []
        for v in venues:
            venue_kw = tokenize_keywords(v.get("scope_keywords", []))
            overlap = sorted(list(set(d["keywords"]).intersection(set(venue_kw))))
            if len(overlap) >= 2 and isinstance(d["page_count"], int) and d["page_count"] <= v["max_pages"]:
                eligible.append({
                    "name": v["name"],
                    "overlap_keywords": overlap,
                    "max_pages": v["max_pages"],
                })
        result[d["path"]] = {
            "title": d["title"],
            "eligible": eligible,
        }
    return result


def find_line_with_timestamp_and_substring(lines: List[str], substring: str) -> bool:
    pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*' + re.escape(substring))
    for line in lines:
        if pattern.search(line):
            return True
    return False


def extract_parse_html_count(lines: List[str]) -> Optional[int]:
    regex = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*PARSE_HTML:\s*(\d+)\s+journals', re.IGNORECASE)
    for line in lines:
        m = regex.search(line)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def contains_listing_command(lines: List[str]) -> bool:
    for line in lines:
        lower = line.lower()
        if ("ls" in lower or "dir" in lower or "tree" in lower) and "drafts" in lower:
            return True
    return False


def contains_listing_tree(lines: List[str]) -> bool:
    for line in lines:
        if "contrastive_learning.md" in line and "INSPECT:" not in line:
            return True
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("drafts:"):
            for j in range(i + 1, min(i + 10, len(lines))):
                if "contrastive_learning.md" in lines[j]:
                    return True
    return False


def parse_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    res = read_csv_safe(path)
    if res is None:
        return None
    header, data_rows = res
    rows = []
    for r in data_rows:
        if len(r) != len(header):
            return None
        rows.append({header[i]: r[i] for i in range(len(header))})
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "cli_support_scan_flag": 0.0,
        "cli_support_watch_flag": 0.0,
        "csv_exists": 0.0,
        "csv_header_correct": 0.0,
        "csv_eligible_pair_count_correct": 0.0,
        "csv_rows_overlap_and_fields_correct": 0.0,
        "json_exists": 0.0,
        "json_structure_and_fields_correct": 0.0,
        "json_eligibility_content_correct": 0.0,
        "watch_log_exists": 0.0,
        "watch_log_inspect_line_with_timestamp": 0.0,
        "watch_log_parse_html_count_correct": 0.0,
        "watch_log_listing_command_included": 0.0,
        "watch_log_listing_tree_included": 0.0,
    }

    script_path = workspace / "scripts" / "suggest_venues.py"
    drafts_dir = workspace / "drafts"
    html_path = workspace / "data" / "journals.html"
    csv_path = workspace / "output" / "suggestions.csv"
    json_path = workspace / "output" / "suggestions.json"
    log_path = workspace / "output" / "watch.log"

    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0
        content = read_text_safe(script_path) or ""
        if "--scan" in content:
            scores["cli_support_scan_flag"] = 1.0
        if "--watch" in content:
            scores["cli_support_watch_flag"] = 1.0

    expected = compute_expected_eligibility(drafts_dir, html_path)

    if csv_path.exists() and csv_path.is_file():
        scores["csv_exists"] = 1.0
        csv_content = read_csv_safe(csv_path)
        if csv_content is not None:
            header, data_rows = csv_content
            expected_header = ["draft_file", "draft_title", "journal_name", "max_pages", "overlap_keywords", "eligible"]
            if header == expected_header:
                scores["csv_header_correct"] = 1.0
            if expected is not None:
                expected_pairs = []
                for dfile, dinfo in expected.items():
                    for v in dinfo["eligible"]:
                        expected_pairs.append({
                            "draft_file": dfile,
                            "draft_title": dinfo["title"],
                            "journal_name": v["name"],
                            "max_pages": str(v["max_pages"]),
                            "overlap_keywords_set": set(v["overlap_keywords"]),
                            "eligible": "true",
                        })
                if len(data_rows) == len(expected_pairs):
                    scores["csv_eligible_pair_count_correct"] = 1.0
                parsed_rows = parse_csv_rows(csv_path)
                if parsed_rows is not None and (expected_pairs or len(data_rows) == 0):
                    exp_by_key = {}
                    for e in expected_pairs:
                        key = (e["draft_file"], e["journal_name"])
                        exp_by_key[key] = e
                    all_ok = True
                    for row in parsed_rows:
                        df = row.get("draft_file", "")
                        dt = row.get("draft_title", "")
                        jn = row.get("journal_name", "")
                        mp = row.get("max_pages", "")
                        ok = row.get("overlap_keywords", "")
                        elig = row.get("eligible", "")
                        key = (df, jn)
                        if key not in exp_by_key:
                            all_ok = False
                            break
                        exp = exp_by_key[key]
                        if dt != exp["draft_title"]:
                            all_ok = False
                            break
                        if mp.strip() != exp["max_pages"]:
                            all_ok = False
                            break
                        if elig.strip().lower() != "true":
                            all_ok = False
                            break
                        toks = [t.strip() for t in ok.split(";") if t.strip() != ""]
                        if any(t != t.lower() for t in toks):
                            all_ok = False
                            break
                        if set(toks) != exp["overlap_keywords_set"]:
                            all_ok = False
                            break
                    if all_ok:
                        scores["csv_rows_overlap_and_fields_correct"] = 1.0

    if json_path.exists() and json_path.is_file():
        scores["json_exists"] = 1.0
        data = read_json_safe(json_path)
        if data is not None and isinstance(data, dict):
            if expected is not None:
                struct_ok = True
                content_ok = True
                for dfile, dinfo in expected.items():
                    if dfile not in data:
                        struct_ok = False
                        content_ok = False
                        break
                    entry = data[dfile]
                    if not isinstance(entry, dict):
                        struct_ok = False
                        content_ok = False
                        break
                    if entry.get("title") != dinfo["title"]:
                        struct_ok = False
                        content_ok = False
                        break
                    journals = entry.get("journals")
                    if not isinstance(journals, list):
                        struct_ok = False
                        content_ok = False
                        break
                    exp_by_name = {v["name"]: v for v in dinfo["eligible"]}
                    names_in_json = [j.get("name") for j in journals if isinstance(j, dict)]
                    if set(names_in_json) != set(exp_by_name.keys()):
                        content_ok = False
                    for j in journals:
                        if not isinstance(j, dict):
                            content_ok = False
                            break
                        name = j.get("name")
                        ov = j.get("overlap_keywords")
                        mp = j.get("max_pages")
                        if name not in exp_by_name:
                            content_ok = False
                            break
                        exp = exp_by_name[name]
                        if mp != exp["max_pages"]:
                            content_ok = False
                            break
                        if not isinstance(ov, list):
                            content_ok = False
                            break
                        if any((not isinstance(x, str)) or x != x.lower() for x in ov):
                            content_ok = False
                            break
                        if set(ov) != set(exp["overlap_keywords"]):
                            content_ok = False
                            break
                if struct_ok:
                    scores["json_structure_and_fields_correct"] = 1.0
                if content_ok:
                    scores["json_eligibility_content_correct"] = 1.0

    if log_path.exists() and log_path.is_file():
        scores["watch_log_exists"] = 1.0
        log_text = read_text_safe(log_path) or ""
        lines = log_text.splitlines()
        if find_line_with_timestamp_and_substring(lines, "INSPECT: drafts/contrastive_learning.md"):
            scores["watch_log_inspect_line_with_timestamp"] = 1.0
        cnt = extract_parse_html_count(lines)
        expected_journal_count = None
        html_text = read_text_safe(html_path)
        if html_text is not None:
            venues = parse_venues_from_html(html_text)
            if venues is not None:
                expected_journal_count = len(venues)
        if cnt is not None and expected_journal_count is not None and cnt == expected_journal_count:
            scores["watch_log_parse_html_count_correct"] = 1.0
        if contains_listing_command(lines):
            scores["watch_log_listing_command_included"] = 1.0
        if contains_listing_tree(lines):
            scores["watch_log_listing_tree_included"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()