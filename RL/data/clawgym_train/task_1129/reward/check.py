import sys
import json
import csv
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except Exception:
        return None


def _ensure_str(s: Optional[str]) -> str:
    return "" if s is None else s


def _cls_contains(attrs: Dict[str, str], target: str) -> bool:
    cls = attrs.get("class", "") or ""
    parts = cls.split()
    return target in parts


def _attrs_to_dict(attrs_list: List[Tuple[str, Optional[str]]]) -> Dict[str, str]:
    return {k: (v if v is not None else "") for k, v in attrs_list}


def _strip(s: Optional[str]) -> str:
    if s is None:
        return ""
    return s.strip()


def _mentions_name(*fields: Optional[str]) -> bool:
    hay = " ".join([_ensure_str(f) for f in fields]).lower()
    return ("ma hanbao" in hay) or ("hanbao ma" in hay)


class SiteHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: List[Dict[str, str]] = []

        # Article
        self.in_article = False
        self.art_title = ""
        self.art_date = ""
        self.art_location = ""
        self.art_desc = ""
        self.art_link = ""
        self.art_cap_title = False
        self.art_cap_location = False
        self.art_cap_desc = False

        # UL events
        self.in_ul_events = False
        self.in_li_event = False
        self.li_date = ""
        self.li_title = ""
        self.li_desc = ""
        self.li_location = ""
        self.li_cap_date = False
        self.li_cap_title = False
        self.li_cap_desc = False
        self.li_cap_location = False

        # Table program
        self.in_table_program = False
        self.in_thead = False
        self.in_row = False
        self.current_cells: List[str] = []
        self.td_index = -1
        self.in_td = False
        self.cell_text = ""
        self.link_href_in_cell = ""

    def handle_starttag(self, tag: str, attrs_list: List[Tuple[str, Optional[str]]]) -> None:
        attrs = _attrs_to_dict(attrs_list)
        if tag == "article" and _cls_contains(attrs, "news-item"):
            self.in_article = True
            self.art_title = ""
            self.art_date = ""
            self.art_location = ""
            self.art_desc = ""
            self.art_link = ""
            self.art_cap_title = False
            self.art_cap_location = False
            self.art_cap_desc = False
        elif self.in_article:
            if tag == "h2":
                self.art_cap_title = True
            elif tag == "time":
                dt = attrs.get("datetime", "") or ""
                if dt:
                    self.art_date = dt.strip()
            elif tag == "span" and _cls_contains(attrs, "location"):
                self.art_cap_location = True
            elif tag == "p" and _cls_contains(attrs, "summary"):
                self.art_cap_desc = True
            elif tag == "a":
                if not self.art_link:
                    href = attrs.get("href", "") or ""
                    if href:
                        self.art_link = href.strip()

        if tag == "ul" and _cls_contains(attrs, "events"):
            self.in_ul_events = True
        elif tag == "li" and self.in_ul_events and _cls_contains(attrs, "event"):
            self.in_li_event = True
            self.li_date = ""
            self.li_title = ""
            self.li_desc = ""
            self.li_location = ""
            self.li_cap_date = False
            self.li_cap_title = False
            self.li_cap_desc = False
            self.li_cap_location = False
        elif self.in_li_event:
            if tag == "span" and _cls_contains(attrs, "date"):
                self.li_cap_date = True
            elif tag == "span" and _cls_contains(attrs, "title"):
                self.li_cap_title = True
            elif tag == "div" and _cls_contains(attrs, "desc"):
                self.li_cap_desc = True
            elif tag == "span" and _cls_contains(attrs, "location"):
                self.li_cap_location = True

        if tag == "table" and attrs.get("id", "") == "program":
            self.in_table_program = True
            self.in_thead = False
        elif self.in_table_program:
            if tag == "thead":
                self.in_thead = True
            elif tag == "tbody":
                # nothing specific needed; rows will be handled
                pass
            elif tag == "tr" and not self.in_thead:
                self.in_row = True
                self.current_cells = []
                self.td_index = -1
            elif tag == "td" and self.in_row:
                self.in_td = True
                self.td_index += 1
                self.cell_text = ""
                self.link_href_in_cell = ""
            elif tag == "a" and self.in_row and self.in_td:
                href = attrs.get("href", "") or ""
                if href:
                    self.link_href_in_cell = href.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self.in_article:
            # finalize article item
            item = {
                "type": "article",
                "date": _strip(self.art_date),
                "title": _strip(self.art_title),
                "desc": _strip(self.art_desc),
                "location": _strip(self.art_location),
                "link": _strip(self.art_link),
                "speaker": "",
            }
            self.items.append(item)
            # reset
            self.in_article = False
            self.art_cap_title = False
            self.art_cap_location = False
            self.art_cap_desc = False
        elif self.in_article:
            if tag == "h2":
                self.art_cap_title = False
            elif tag == "span":
                self.art_cap_location = False
            elif tag == "p":
                self.art_cap_desc = False

        if tag == "ul" and self.in_ul_events:
            self.in_ul_events = False
        elif tag == "li" and self.in_li_event:
            # finalize list item
            item = {
                "type": "list",
                "date": _strip(self.li_date),
                "title": _strip(self.li_title),
                "desc": _strip(self.li_desc),
                "location": _strip(self.li_location),
                "link": "",
                "speaker": "",
            }
            self.items.append(item)
            self.in_li_event = False
            self.li_cap_date = False
            self.li_cap_title = False
            self.li_cap_desc = False
            self.li_cap_location = False
        elif self.in_li_event:
            if tag == "span":
                # end of possible span subfields
                self.li_cap_date = False
                self.li_cap_title = False
                self.li_cap_location = False
            elif tag == "div":
                self.li_cap_desc = False

        if tag == "table" and self.in_table_program:
            self.in_table_program = False
            self.in_thead = False
        elif tag == "thead" and self.in_table_program:
            self.in_thead = False
        elif tag == "td" and self.in_table_program and self.in_row and self.in_td:
            text = _strip(self.cell_text)
            if self.td_index == 4:
                # Link column: prefer href if present
                value = self.link_href_in_cell if self.link_href_in_cell else text
            else:
                value = text
            self.current_cells.append(value)
            self.in_td = False
        elif tag == "tr" and self.in_table_program and self.in_row:
            if len(self.current_cells) >= 5:
                item = {
                    "type": "table",
                    "date": _strip(self.current_cells[0]),
                    "title": _strip(self.current_cells[1]),
                    "speaker": _strip(self.current_cells[2]),
                    "location": _strip(self.current_cells[3]),
                    "link": _strip(self.current_cells[4]),
                    "desc": "",
                }
                self.items.append(item)
            self.in_row = False
            self.current_cells = []
            self.td_index = -1
            self.in_td = False
            self.cell_text = ""
            self.link_href_in_cell = ""

    def handle_data(self, data: str) -> None:
        if self.in_article:
            if self.art_cap_title:
                self.art_title += data
            elif self.art_cap_location:
                self.art_location += data
            elif self.art_cap_desc:
                self.art_desc += data
        if self.in_li_event:
            if self.li_cap_date:
                self.li_date += data
            elif self.li_cap_title:
                self.li_title += data
            elif self.li_cap_desc:
                self.li_desc += data
            elif self.li_cap_location:
                self.li_location += data
        if self.in_table_program and self.in_row and self.in_td:
            self.cell_text += data


def _parse_html_items(html_text: str) -> List[Dict[str, str]]:
    parser = SiteHTMLParser()
    parser.feed(html_text)
    parser.close()
    return parser.items


def _find_html_files(workspace: Path) -> List[Path]:
    base = workspace / "input" / "sites"
    if not base.exists():
        return []
    files = [p for p in base.rglob("*.html") if p.is_file()]
    return files


def _build_expected(workspace: Path) -> Tuple[List[Dict[str, str]], Dict[str, Tuple[int, int]]]:
    # Returns (expected_records, scan_log_map)
    files = _find_html_files(workspace)
    # Sort files by lexicographic path
    files_sorted = sorted(files, key=lambda p: p.as_posix())
    expected_records: List[Dict[str, str]] = []
    scan_log: Dict[str, Tuple[int, int]] = {}
    seen_keys = set()

    for fpath in files_sorted:
        rel = fpath.relative_to(workspace).as_posix()
        text = _read_text(fpath)
        if text is None:
            # If file cannot be read, treat as no parsed items
            scan_log[rel] = (0, 0)
            continue
        items = _parse_html_items(text)
        total = len(items)
        matched = 0
        # iterate in document order
        for it in items:
            title = _strip(it.get("title", ""))
            desc = _strip(it.get("desc", ""))
            speaker = _strip(it.get("speaker", ""))
            if _mentions_name(title, desc, speaker):
                matched += 1
                # Build record fields
                date = _strip(it.get("date", ""))
                location = _strip(it.get("location", ""))
                link = _strip(it.get("link", ""))
                # Dedup by (date + lowercased, trimmed title)
                key = (date, title.lower().strip())
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                expected_records.append({
                    "date": date,
                    "title": title,
                    "people": "Ma Hanbao",
                    "location": location,
                    "link": link,
                    "source_file": rel,
                })
        scan_log[rel] = (total, matched)

    # Sort by date ascending (YYYY-MM-DD lex order works)
    expected_records_sorted = sorted(expected_records, key=lambda r: r.get("date", ""))
    return expected_records_sorted, scan_log


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
            rows_raw: List[List[str]] = list(reader)
        # Convert to dict rows keyed by header
        dict_rows: List[Dict[str, str]] = []
        for row in rows_raw:
            # Pad or trim row to header length
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            elif len(row) > len(header):
                row = row[:len(header)]
            d = {header[i]: row[i] for i in range(len(header))}
            dict_rows.append(d)
        return header, dict_rows
    except Exception:
        return None, None


def _load_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "csv_exists": 0.0,
        "csv_header_correct": 0.0,
        "csv_rows_correct_count": 0.0,
        "csv_sorted_by_date": 0.0,
        "csv_rows_content_exact": 0.0,
        "json_exists": 0.0,
        "json_top3_correct": 0.0,
        "scan_log_exists": 0.0,
        "scan_log_lines_count": 0.0,
        "scan_log_lines_correct": 0.0,
    }

    expected_records, expected_scan_log = _build_expected(workspace)
    expected_header = ["date", "title", "people", "location", "link", "source_file"]

    # Build expected CSV rows for exact comparison
    expected_csv_rows = []
    for rec in expected_records:
        expected_csv_rows.append([rec["date"], rec["title"], rec["people"], rec["location"], rec["link"], rec["source_file"]])

    # CSV checks
    csv_path = workspace / "output" / "hanbao_events.csv"
    if csv_path.exists() and csv_path.is_file():
        scores["csv_exists"] = 1.0
        header, rows = _read_csv(csv_path)
        if header is not None and rows is not None:
            # Header check
            if header == expected_header:
                scores["csv_header_correct"] = 1.0
            # Count check
            if rows is not None:
                if len(rows) == len(expected_csv_rows):
                    scores["csv_rows_correct_count"] = 1.0
                # Sort check: verify ascending by date
                try:
                    dates = [r.get("date", "") for r in rows]
                    if dates == sorted(dates):
                        scores["csv_sorted_by_date"] = 1.0
                except Exception:
                    pass
                # Content exact check
                # Only perform strict equality if header correct
                if header == expected_header:
                    actual_rows_seq = [[r.get(col, "") for col in expected_header] for r in rows]
                    if actual_rows_seq == expected_csv_rows:
                        scores["csv_rows_content_exact"] = 1.0
        # else malformed CSV -> keep zeros
    # else csv missing -> keep zeros

    # JSON checks
    json_path = workspace / "output" / "top_by_recency.json"
    expected_top_n = min(3, len(expected_records))
    # Build expected top3 from expected_records by date descending, stable among ties by order in expected_records
    # Determine indices for stability
    expected_with_index = list(enumerate(expected_records))
    expected_top_sorted = sorted(expected_with_index, key=lambda t: (t[1]["date"], t[0]), reverse=True)
    expected_top = [{"date": rec["date"], "title": rec["title"], "source_file": rec["source_file"]} for _, rec in expected_top_sorted[:expected_top_n]]

    if json_path.exists() and json_path.is_file():
        scores["json_exists"] = 1.0
        data = _load_json(json_path)
        if isinstance(data, list):
            # Simplify actual data to required keys if present
            actual_simplified = []
            ok = True
            for item in data[:expected_top_n]:
                if not isinstance(item, dict):
                    ok = False
                    break
                simplified = {
                    "date": item.get("date", ""),
                    "title": item.get("title", ""),
                    "source_file": item.get("source_file", ""),
                }
                actual_simplified.append(simplified)
            if ok and len(actual_simplified) == expected_top_n and actual_simplified == expected_top:
                scores["json_top3_correct"] = 1.0

    # Scan log checks
    log_path = workspace / "output" / "scan_log.txt"
    if log_path.exists() and log_path.is_file():
        scores["scan_log_exists"] = 1.0
        try:
            lines = [ln.strip() for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip() != ""]
            # Expected lines map to string lines
            expected_lines_map = {}
            for rel, (total, matched) in expected_scan_log.items():
                expected_lines_map[rel] = f"{rel}: total={total}, matched={matched}"
            if len(lines) == len(expected_lines_map):
                scores["scan_log_lines_count"] = 1.0
            # Build actual mapping from lines
            actual_map = {}
            for ln in lines:
                # Expect format "<relative_path>: total=<N>, matched=<N>"
                if ": total=" in ln and ", matched=" in ln:
                    try:
                        left, rest = ln.split(": total=", 1)
                        tot_str, mpart = rest.split(", matched=", 1)
                        tot = int(tot_str)
                        m = int(mpart)
                        actual_map[left] = f"{left}: total={tot}, matched={m}"
                    except Exception:
                        # Malformed, keep as is to fail exact match
                        actual_map[ln] = ln
                else:
                    actual_map[ln] = ln
            # Compare sets of lines for exact equality (ignoring order)
            expected_set = set(expected_lines_map.values())
            actual_set = set(actual_map.values())
            if expected_set == actual_set:
                scores["scan_log_lines_correct"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()