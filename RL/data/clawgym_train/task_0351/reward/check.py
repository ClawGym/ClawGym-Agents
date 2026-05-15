import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class FirstTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.table_captured = False
        self.in_tr = False
        self.in_th = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.headers: List[str] = []
        self.rows: List[List[str]] = []
        self.seen_header = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table" and not self.table_captured:
            self.in_table = True
        if self.in_table:
            if tag.lower() == "tr":
                self.in_tr = True
                self.current_row = []
            elif tag.lower() == "th":
                self.in_th = True
                self.current_cell = []
            elif tag.lower() == "td":
                self.in_td = True
                self.current_cell = []

    def handle_endtag(self, tag):
        if self.in_table:
            if tag.lower() == "th":
                self.in_th = False
                text = "".join(self.current_cell).strip()
                self.current_row.append(text)
                self.current_cell = []
            elif tag.lower() == "td":
                self.in_td = False
                text = "".join(self.current_cell).strip()
                self.current_row.append(text)
                self.current_cell = []
            elif tag.lower() == "tr":
                if self.in_tr:
                    if self.current_row:
                        if not self.seen_header and any(x is not None for x in self.current_row):
                            if self.headers == [] and any(cell for cell in self.current_row):
                                if len(self.rows) == 0 and not self.seen_header:
                                    self.headers = self.current_row
                                    self.seen_header = True
                                else:
                                    self.rows.append(self.current_row)
                            else:
                                self.rows.append(self.current_row)
                        else:
                            self.rows.append(self.current_row)
                    self.current_row = []
                self.in_tr = False
            elif tag.lower() == "table":
                self.in_table = False
                self.table_captured = True

    def handle_data(self, data):
        if (self.in_th or self.in_td) and self.in_table:
            self.current_cell.append(data)


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def parse_first_table_from_html(html_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    parser = FirstTableParser()
    parser.feed(html_text)
    headers = parser.headers
    rows_list = parser.rows
    if not headers and rows_list:
        headers = rows_list[0]
        rows_list = rows_list[1:]
    dict_rows: List[Dict[str, str]] = []
    for row in rows_list:
        padded = row + [""] * (len(headers) - len(row))
        rec = {headers[i]: padded[i] if i < len(padded) else "" for i in range(len(headers))}
        dict_rows.append(rec)
    return headers, dict_rows


def discover_schedule_files(workspace: Path) -> List[Path]:
    sched_dir = workspace / "input" / "schedules"
    if not sched_dir.exists():
        return []
    matches = sorted(sched_dir.glob("braves_away_*.html"))
    return matches


def load_ballparks_reference(workspace: Path) -> Dict[str, Dict[str, str]]:
    ref_path = workspace / "input" / "reference" / "ballparks.csv"
    ref_rows = safe_load_csv_dicts(ref_path) or []
    mapping: Dict[str, Dict[str, str]] = {}
    for r in ref_rows:
        stadium_name = (r.get("stadium_name") or "").strip()
        if stadium_name:
            key = stadium_name.lower()
            mapping[key] = {
                "stadium_name": stadium_name,
                "city": (r.get("city") or "").strip(),
                "state": (r.get("state") or "").strip(),
                "time_zone": (r.get("time_zone") or "").strip(),
            }
    return mapping


def normalize_date(date_str: str, fallback_year: Optional[int] = None) -> Optional[str]:
    ds = (date_str or "").strip()
    fmts = ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(ds, fmt).date()
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    if fallback_year:
        m = re.match(r"^\s*(\d{1,2})[/-](\d{1,2})\s*$", ds)
        if m:
            try:
                dt = datetime(fallback_year, int(m.group(1)), int(m.group(2))).date()
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return None


def build_expected_from_inputs(workspace: Path) -> Tuple[List[Dict[str, str]], Dict[str, int], List[str], Dict[str, int], List[str]]:
    schedule_files = discover_schedule_files(workspace)
    ballparks = load_ballparks_reference(workspace)
    file_row_counts: Dict[str, int] = {}
    all_rows: List[Dict[str, str]] = []
    unmatched: List[str] = []
    seasons_set = set()
    coverage_by_month: Dict[str, int] = {}
    for sch in schedule_files:
        text = safe_read_text(sch)
        if text is None:
            file_row_counts[str(sch.relative_to(workspace))] = 0
            continue
        headers, rows = parse_first_table_from_html(text)
        cols_needed = {"Date", "Opponent", "Venue", "City"}
        if not set(headers) >= cols_needed:
            usable_rows = []
        else:
            usable_rows = rows
        count_this = 0
        for r in usable_rows:
            date_raw = r.get("Date", "")
            m = re.search(r"(\d{4})", sch.name)
            fallback_year = int(m.group(1)) if m else None
            date_norm = normalize_date(date_raw, fallback_year)
            if not date_norm:
                continue
            season = int(date_norm[:4])
            seasons_set.add(season)
            opponent = (r.get("Opponent") or "").strip()
            venue = (r.get("Venue") or "").strip()
            schedule_city = (r.get("City") or "").strip()
            ref = ballparks.get(venue.lower())
            if not ref:
                unmatched.append(venue)
                continue
            expected_row = {
                "season": str(season),
                "date": date_norm,
                "opponent": opponent,
                "stadium_name": venue,
                "city": ref["city"],
                "state": ref["state"],
                "time_zone": ref["time_zone"],
            }
            all_rows.append(expected_row)
            count_this += 1
            ym = date_norm[:7]
            coverage_by_month[ym] = coverage_by_month.get(ym, 0) + 1
        file_row_counts[str(sch.relative_to(workspace))] = count_this
    all_rows.sort(key=lambda x: x["date"])
    seasons_list = sorted([str(s) for s in seasons_set])
    return all_rows, file_row_counts, seasons_list, coverage_by_month, unmatched


def read_actual_itinerary_csv(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    path = workspace / "output" / "itinerary_candidates.csv"
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        header = rows[0]
        out_rows: List[Dict[str, str]] = []
        for r in rows[1:]:
            r = r + [""] * (len(header) - len(r))
            out_rows.append({header[i]: r[i] if i < len(r) else "" for i in range(len(header))})
        return header, out_rows
    except Exception:
        return None, None


def parse_status_sections(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {
        "Inputs scanned": [],
        "Processing summary": [],
        "Coverage by month": [],
        "Unmatched stadiums": [],
        "City cross-checks": [],
    }
    current = None
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.endswith(":"):
            title = stripped[:-1].strip()
            if title.lower().startswith("inputs scanned"):
                current = "Inputs scanned"
                continue
            elif title.lower().startswith("processing summary"):
                current = "Processing summary"
                continue
            elif title.lower().startswith("coverage by month"):
                current = "Coverage by month"
                continue
            elif title.lower().startswith("unmatched stadiums"):
                current = "Unmatched stadiums"
                continue
            elif title.lower().startswith("city cross-checks"):
                current = "City cross-checks"
                continue
        if lower in {"inputs scanned", "processing summary", "coverage by month", "unmatched stadiums", "city cross-checks"}:
            mapping = {
                "inputs scanned": "Inputs scanned",
                "processing summary": "Processing summary",
                "coverage by month": "Coverage by month",
                "unmatched stadiums": "Unmatched stadiums",
                "city cross-checks": "City cross-checks",
            }
            current = mapping[lower]
            continue
        if current:
            sections[current].append(stripped)
    return sections


def parse_inputs_scanned(lines: List[str]) -> Dict[str, int]:
    files_to_counts: Dict[str, int] = {}
    for line in lines:
        if not line:
            continue
        m_path = re.search(r"(input/schedules/[^:\)\]]+)", line)
        m_count = re.search(r"(\d+)\s*rows?\b", line, re.IGNORECASE)
        if m_path and m_count:
            path_str = m_path.group(1).strip()
            cnt = int(m_count.group(1))
            files_to_counts[path_str] = cnt
    return files_to_counts


def parse_processing_summary(lines: List[str]) -> Tuple[Optional[int], Optional[int], List[str]]:
    total = None
    unique_stadiums = None
    seasons: List[str] = []
    for line in lines:
        l = line.lower()
        if "total" in l and "game" in l and "process" in l:
            m = re.search(r"(\d+)", line)
            if m:
                total = int(m.group(1))
        if "unique" in l and "stadium" in l and "match" in l:
            m = re.search(r"(\d+)", line)
            if m:
                unique_stadiums = int(m.group(1))
        if "season" in l and "cover" in l:
            years = re.findall(r"\b(20\d{2})\b", line)
            if years:
                seasons = sorted(set(years))
    return total, unique_stadiums, seasons


def parse_coverage_by_month(lines: List[str]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for line in lines:
        m = re.search(r"(\d{4}-\d{2})\D+(\d+)", line)
        if m:
            d[m.group(1)] = int(m.group(2))
    return d


def parse_unmatched(lines: List[str]) -> Optional[List[str]]:
    content = " ".join(lines).strip()
    if not content:
        return []
    if re.search(r"\bnone\b", content, re.IGNORECASE):
        return None
    items: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*\d\.\)\s]+", "", stripped)
        if stripped:
            items.append(stripped)
    return items


def parse_city_cross_checks(lines: List[str]) -> Optional[List[str]]:
    content = " ".join(lines).strip()
    if re.search(r"\bnone\b", content, re.IGNORECASE):
        return None
    items: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*\d\.\)\s]+", "", stripped)
        if stripped:
            items.append(stripped)
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "itinerary_csv_header": 0.0,
        "itinerary_csv_row_count_and_sort": 0.0,
        "itinerary_csv_content_match": 0.0,
        "status_update_sections_present": 0.0,
        "status_inputs_scanned_correct": 0.0,
        "status_processing_summary_correct": 0.0,
        "status_coverage_by_month_correct": 0.0,
        "status_unmatched_stadiums_section_correct": 0.0,
        "status_city_cross_checks_correct": 0.0,
    }

    expected_rows, file_row_counts, seasons_list, expected_coverage_by_month, unmatched_expected = build_expected_from_inputs(workspace)

    expected_header = ["season", "date", "opponent", "stadium_name", "city", "state", "time_zone"]
    actual_header, actual_rows = read_actual_itinerary_csv(workspace)

    if actual_header is not None and actual_rows is not None:
        if actual_header == expected_header:
            scores["itinerary_csv_header"] = 1.0
        if len(actual_rows) == len(expected_rows):
            try:
                dates = [r.get("date", "") for r in actual_rows]
                parsed_dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
                if parsed_dates == sorted(parsed_dates):
                    scores["itinerary_csv_row_count_and_sort"] = 1.0
            except Exception:
                pass
        try:
            def key_fn(r):
                return (r.get("date", ""), r.get("opponent", ""), r.get("stadium_name", ""))
            actual_sorted = sorted(
                [{k: v for k, v in r.items() if k in expected_header} for r in actual_rows],
                key=key_fn,
            )
            expected_sorted = sorted(expected_rows, key=key_fn)
            if len(actual_sorted) == len(expected_sorted):
                all_match = True
                for a, e in zip(actual_sorted, expected_sorted):
                    for h in expected_header:
                        if (a.get(h) or "") != (e.get(h) or ""):
                            all_match = False
                            break
                    if not all_match:
                        break
                if all_match:
                    scores["itinerary_csv_content_match"] = 1.0
        except Exception:
            pass

    status_path = workspace / "output" / "summary" / "status_update.md"
    status_text = safe_read_text(status_path)
    if status_text is not None:
        sections = parse_status_sections(status_text)
        required_sections = ["Inputs scanned", "Processing summary", "Coverage by month", "Unmatched stadiums", "City cross-checks"]
        if all(sections.get(s) is not None for s in required_sections):
            scores["status_update_sections_present"] = 1.0

        inputs_map = parse_inputs_scanned(sections.get("Inputs scanned", []))
        discovered_files = discover_schedule_files(workspace)
        expected_inputs_map: Dict[str, int] = {}
        for p in discovered_files:
            rel = str(p.relative_to(workspace))
            expected_inputs_map[rel] = file_row_counts.get(rel, 0)
        if inputs_map and expected_inputs_map and inputs_map == expected_inputs_map:
            scores["status_inputs_scanned_correct"] = 1.0

        total_games, unique_stadiums, seasons_reported = parse_processing_summary(sections.get("Processing summary", []))
        expected_total_games = len(expected_rows)
        expected_unique_stadiums = len(set([r["stadium_name"].lower() for r in expected_rows]))
        if (
            total_games == expected_total_games
            and unique_stadiums == expected_unique_stadiums
            and sorted(seasons_reported) == sorted(seasons_list)
        ):
            scores["status_processing_summary_correct"] = 1.0

        coverage_reported = parse_coverage_by_month(sections.get("Coverage by month", []))
        if coverage_reported == expected_coverage_by_month:
            scores["status_coverage_by_month_correct"] = 1.0

        unmatched_reported = parse_unmatched(sections.get("Unmatched stadiums", []))
        if not unmatched_expected:
            if unmatched_reported is None or unmatched_reported == []:
                scores["status_unmatched_stadiums_section_correct"] = 1.0
        else:
            if unmatched_reported is not None and sorted([u.strip() for u in unmatched_reported]) == sorted([u.strip() for u in unmatched_expected]):
                scores["status_unmatched_stadiums_section_correct"] = 1.0

        city_cross = parse_city_cross_checks(sections.get("City cross-checks", []))
        if city_cross is None:
            scores["status_city_cross_checks_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()