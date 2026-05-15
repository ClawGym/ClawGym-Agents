import json
import csv
import sys
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


def read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def parse_config_yaml_simple(path: Path) -> Optional[Dict[str, Any]]:
    text = read_text_safe(path)
    if text is None:
        return None
    include_series: List[str] = []
    top_n: Optional[int] = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("include_series:"):
            # Collect following indented list items "- value"
            i += 1
            while i < len(lines):
                l2 = lines[i]
                if re.match(r"^\s*-\s+", l2):
                    val = re.sub(r"^\s*-\s+", "", l2).strip()
                    # Remove possible quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    include_series.append(val)
                    i += 1
                elif l2.strip() == "":
                    i += 1
                else:
                    break
            continue
        elif stripped.startswith("top_n:"):
            try:
                top_n = int(stripped.split(":", 1)[1].strip())
            except Exception:
                return None
        i += 1
    if top_n is None:
        return None
    return {"include_series": include_series, "top_n": top_n}


class EventHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_event_info = False
        self.in_results = False
        self.in_td = False
        self.in_th = False
        self.in_strong = False
        self.current_label: Optional[str] = None
        self.expect_value_for_label: Optional[str] = None
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self.event_info: Dict[str, str] = {}
        self._tag_stack: List[str] = []
        self._current_table_id: Optional[str] = None
        self._current_section_id: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        attrs_dict = {k: v for k, v in attrs}
        if tag == "section" and attrs_dict.get("id") == "event-info":
            self.in_event_info = True
            self._current_section_id = "event-info"
        if tag == "table":
            self._current_table_id = attrs_dict.get("id")
            if self._current_table_id == "results":
                self.in_results = True
        if tag == "td":
            self.in_td = True
        if tag == "th":
            self.in_th = True
        if tag == "strong" and self.in_event_info:
            self.in_strong = True

    def handle_endtag(self, tag):
        # Pop stack
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        else:
            # try to remove first occurrence from end
            try:
                idx = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
                self._tag_stack.pop(idx)
            except ValueError:
                pass
        if tag == "section" and self._current_section_id == "event-info":
            self.in_event_info = False
            self._current_section_id = None
        if tag == "table" and self._current_table_id == "results":
            self.in_results = False
            self._current_table_id = None
        if tag == "td":
            self.in_td = False
        if tag == "th":
            self.in_th = False
        if tag == "strong":
            self.in_strong = False
        if tag == "tr" and self.in_results:
            if self.current_row:
                # Only accept rows with 4 columns
                if len(self.current_row) == 4:
                    self.rows.append([c.strip() for c in self.current_row])
            self.current_row = []

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self.in_event_info:
            if self.in_strong:
                # label like "Event ID:" -> strip colon
                label = text.strip().rstrip(":").strip().lower()
                self.current_label = label
                self.expect_value_for_label = label
            else:
                # after strong, this is the value
                if self.expect_value_for_label:
                    key_map = {
                        "event id": "event_id",
                        "series": "series",
                        "date": "date",
                        "venue": "venue",
                    }
                    k = key_map.get(self.expect_value_for_label)
                    if k:
                        # Append to any existing value to accumulate if spaced
                        prev = self.event_info.get(k, "")
                        combined = (prev + " " + text).strip() if prev else text
                        self.event_info[k] = combined
                    self.expect_value_for_label = None
        if self.in_results and self.in_td:
            # Capture cell data
            self.current_row.append(text)


def parse_event_html(path: Path) -> Optional[Dict[str, Any]]:
    text = read_text_safe(path)
    if text is None:
        return None
    parser = EventHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    # Basic validation
    info = parser.event_info
    if not all(k in info for k in ("event_id", "series", "date", "venue")):
        return None
    # Normalize rows
    rows = []
    for r in parser.rows:
        if len(r) != 4:
            continue
        rows.append({
            "rank": r[0].strip(),
            "athlete": r[1].strip(),
            "country": r[2].strip(),
            "points": r[3].strip(),
        })
    return {
        "event_id": info["event_id"].strip(),
        "series": info["series"].strip(),
        "date": info["date"].strip(),
        "venue": info["venue"].strip(),
        "results": rows,
        "source_file": path.name,
    }


def normalize_row_for_compare(row: Dict[str, str]) -> Tuple[str, str, str, str, int, str, str, float]:
    # Normalize to comparable tuple
    def to_int_safe(s: str) -> int:
        try:
            return int(float(s.strip()))
        except Exception:
            return int(s.strip()) if s.strip().isdigit() else -1

    def to_float_round1(s: str) -> float:
        try:
            return round(float(s.strip()), 1)
        except Exception:
            # attempt replace comma decimal
            try:
                return round(float(s.strip().replace(",", ".")), 1)
            except Exception:
                return float("nan")

    return (
        row.get("event_id", "").strip(),
        row.get("date", "").strip(),
        row.get("venue", "").strip(),
        row.get("series", "").strip(),
        to_int_safe(row.get("rank", "")),
        row.get("athlete", "").strip(),
        row.get("country", "").strip(),
        to_float_round1(row.get("points", "")),
    )


def normalize_appearance_for_compare(app: Dict[str, Any]) -> Tuple[str, str, str, str, int, float]:
    def to_int_safe(v: Any) -> int:
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        try:
            return int(float(str(v)))
        except Exception:
            return -1

    def to_float_round1(v: Any) -> float:
        if isinstance(v, (int, float)):
            try:
                return round(float(v), 1)
            except Exception:
                return float("nan")
        try:
            return round(float(str(v).replace(",", ".")), 1)
        except Exception:
            return float("nan")

    return (
        str(app.get("event_id", "")).strip(),
        str(app.get("date", "")).strip(),
        str(app.get("venue", "")).strip(),
        str(app.get("series", "")).strip(),
        to_int_safe(app.get("rank", "")),
        to_float_round1(app.get("points", "")),
    )


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "combined_results_header": 0.0,
        "combined_results_rows_correct": 0.0,
        "combined_results_filtering": 0.0,
        "events_scanned_coverage_and_status": 0.0,
        "events_scanned_reason_includes_series": 0.0,
        "club_highlights_structure": 0.0,
        "club_highlights_content": 0.0,
        "highlights_consistent_with_combined": 0.0,
    }

    # Paths
    config_path = workspace / "input" / "config.yaml"
    events_dir = workspace / "input" / "events"
    members_path = workspace / "input" / "members.csv"

    combined_path = workspace / "output" / "combined_results.csv"
    highlights_path = workspace / "output" / "club_highlights.json"
    scanned_path = workspace / "output" / "events_scanned.txt"

    # Parse inputs
    config = parse_config_yaml_simple(config_path)
    members = read_csv_dicts(members_path)
    # Discover and parse events
    event_files = sorted([p for p in events_dir.glob("*.html")]) if events_dir.exists() else []
    parsed_events: List[Dict[str, Any]] = []
    for p in event_files:
        ev = parse_event_html(p)
        if ev is not None:
            parsed_events.append(ev)

    inputs_ok = config is not None and members is not None and len(event_files) > 0 and len(parsed_events) == len(event_files)

    # Compute expected datasets if inputs are ok
    expected_include_series: List[str] = []
    expected_top_n: int = 0
    expected_included_events: List[Dict[str, Any]] = []
    expected_combined_rows: List[Dict[str, str]] = []
    expected_scan_status: Dict[str, Dict[str, Any]] = {}

    if inputs_ok:
        expected_include_series = config.get("include_series", [])
        expected_top_n = int(config.get("top_n", 0))
        # event inclusion decision
        for ev in parsed_events:
            included = ev["series"] in expected_include_series
            reason = f"series={ev['series']}"
            expected_scan_status[ev["source_file"]] = {"included": included, "series": ev["series"], "reason": reason}
            if included:
                expected_included_events.append(ev)
        # Build expected combined
        for ev in expected_included_events:
            # Keep top_n
            take = []
            for row in ev["results"]:
                try:
                    rnk = int(float(str(row["rank"]).strip()))
                except Exception:
                    continue
                if rnk <= expected_top_n:
                    take.append(row)
            # Sort by rank if not guaranteed
            try:
                take.sort(key=lambda x: int(float(str(x["rank"]).strip())))
            except Exception:
                pass
            for row in take:
                expected_combined_rows.append({
                    "event_id": ev["event_id"],
                    "date": ev["date"],
                    "venue": ev["venue"],
                    "series": ev["series"],
                    "rank": str(int(float(row["rank"]))),
                    "athlete": row["athlete"],
                    "country": row["country"],
                    "points": row["points"],
                })

    # Read student's outputs
    # combined_results.csv header check
    combined_rows = read_csv_dicts(combined_path)
    expected_header = ["event_id", "date", "venue", "series", "rank", "athlete", "country", "points"]
    if combined_rows is not None and combined_rows != []:
        # Verify header
        try:
            with combined_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == expected_header:
            scores["combined_results_header"] = 1.0
        else:
            scores["combined_results_header"] = 0.0
    else:
        scores["combined_results_header"] = 0.0

    # combined_results_rows_correct
    if inputs_ok and combined_rows is not None:
        # Normalize both to sets of tuples
        student_set = set()
        for row in combined_rows:
            student_set.add(normalize_row_for_compare(row))
        expected_set = set()
        for row in expected_combined_rows:
            expected_set.add(normalize_row_for_compare(row))
        # Exact set equality
        if student_set == expected_set and len(student_set) == len(expected_set):
            scores["combined_results_rows_correct"] = 1.0
        else:
            scores["combined_results_rows_correct"] = 0.0
    else:
        scores["combined_results_rows_correct"] = 0.0

    # combined_results_filtering
    if inputs_ok and combined_rows is not None:
        # Check only included series appear and per event ranks <= top_n
        ok = True
        per_event_max_rank: Dict[Tuple[str, str], int] = {}
        seen_series = set()
        # Build map of included event_ids
        included_event_ids = set(ev["event_id"] for ev in expected_included_events)
        excluded_event_ids = set(ev["event_id"] for ev in parsed_events if ev["event_id"] not in included_event_ids)
        # Counts
        per_event_counts: Dict[str, int] = {}
        expected_counts: Dict[str, int] = {}
        for ev in expected_included_events:
            # count of rows with rank <= top_n
            cnt = 0
            for row in ev["results"]:
                try:
                    if int(float(str(row["rank"]).strip())) <= expected_top_n:
                        cnt += 1
                except Exception:
                    pass
            expected_counts[ev["event_id"]] = cnt
        for row in combined_rows:
            event_id = row.get("event_id", "").strip()
            series = row.get("series", "").strip()
            seen_series.add(series)
            # No excluded events
            if event_id in excluded_event_ids:
                ok = False
                break
            # For included events, ranks <= top_n
            try:
                rnk = int(float(str(row.get("rank", "")).strip()))
            except Exception:
                ok = False
                break
            if event_id and (event_id in included_event_ids):
                if rnk > expected_top_n:
                    ok = False
                    break
                per_event_counts[event_id] = per_event_counts.get(event_id, 0) + 1
        # All included events should appear with expected counts
        if ok:
            for ev_id, cnt in expected_counts.items():
                if per_event_counts.get(ev_id, 0) != cnt:
                    ok = False
                    break
        # Only allowed series present
        if ok:
            for s in seen_series:
                if s not in expected_include_series:
                    ok = False
                    break
        scores["combined_results_filtering"] = 1.0 if ok else 0.0
    else:
        scores["combined_results_filtering"] = 0.0

    # events_scanned checks
    scanned_text = read_text_safe(scanned_path)
    if inputs_ok and scanned_text is not None:
        lines = [ln.strip() for ln in scanned_text.splitlines() if ln.strip() != ""]
        # Map file -> found line(s)
        found_status: Dict[str, Dict[str, Any]] = {}
        series_mentions_ok = True
        for ev_file, info in expected_scan_status.items():
            # find lines containing file name
            matching = [ln for ln in lines if ev_file in ln]
            if not matching:
                found_status[ev_file] = {"present": False, "status_ok": False, "series_ok": False}
                series_mentions_ok = False
                continue
            # Determine status: INCLUDED or EXCLUDED
            status_ok = False
            series_ok = False
            for ln in matching:
                status_expected = "INCLUDED" if info["included"] else "EXCLUDED"
                if status_expected in ln:
                    status_ok = True
                # Check series mention (contain the series string somewhere)
                if info["series"] in ln:
                    series_ok = True
            found_status[ev_file] = {"present": True, "status_ok": status_ok, "series_ok": series_ok}
            if not series_ok:
                series_mentions_ok = False
        all_present = all(v["present"] and v["status_ok"] for v in found_status.values()) and (len(found_status) == len(expected_scan_status))
        scores["events_scanned_coverage_and_status"] = 1.0 if all_present else 0.0
        scores["events_scanned_reason_includes_series"] = 1.0 if series_mentions_ok and len(found_status) == len(expected_scan_status) else 0.0
    else:
        scores["events_scanned_coverage_and_status"] = 0.0
        scores["events_scanned_reason_includes_series"] = 0.0

    # club_highlights_structure
    highlights = load_json_safe(highlights_path)
    if members is not None and isinstance(highlights, list):
        # Check length and per-object structure
        struct_ok = True
        if len(highlights) != len(members):
            struct_ok = False
        else:
            for obj in highlights:
                if not isinstance(obj, dict):
                    struct_ok = False
                    break
                req_keys = {"member_name", "athlete", "country", "appearances"}
                if not req_keys.issubset(set(obj.keys())):
                    struct_ok = False
                    break
                if not isinstance(obj.get("appearances"), list):
                    struct_ok = False
                    break
                for ap in obj.get("appearances"):
                    if not isinstance(ap, dict):
                        struct_ok = False
                        break
                    app_keys = {"event_id", "date", "venue", "series", "rank", "points"}
                    if not app_keys.issubset(set(ap.keys())):
                        struct_ok = False
                        break
                if not struct_ok:
                    break
        scores["club_highlights_structure"] = 1.0 if struct_ok else 0.0
    else:
        scores["club_highlights_structure"] = 0.0

    # club_highlights_content
    if inputs_ok and isinstance(highlights, list):
        # Build expected appearances from expected_combined_rows
        # Index by athlete and country
        expected_by_athlete_country: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in expected_combined_rows:
            key = (row["athlete"].strip(), row["country"].strip())
            expected_by_athlete_country.setdefault(key, []).append({
                "event_id": row["event_id"],
                "date": row["date"],
                "venue": row["venue"],
                "series": row["series"],
                "rank": int(float(row["rank"])),
                "points": round(float(str(row["points"]).replace(",", ".")), 1),
            })
        # Compare
        content_ok = True
        # We'll compare by mapping member_name or by order? The spec says array of objects one per row in members.csv.
        # We'll check that for each member entry there exists exactly one object with same member_name, athlete, country.
        # To keep deterministic, we'll build a dict from (member_name, athlete, country) to appearances from highlights.
        seen = {}
        for obj in highlights:
            key = (str(obj.get("member_name", "")).strip(), str(obj.get("athlete", "")).strip(), str(obj.get("country", "")).strip())
            if key in seen:
                # duplicate entries not allowed
                content_ok = False
                break
            seen[key] = obj
        if content_ok:
            # verify all members present
            for m in members:
                mkey = (m.get("member_name", "").strip(), m.get("athlete", "").strip(), m.get("country", "").strip())
                if mkey not in seen:
                    content_ok = False
                    break
                # Compare appearances
                actual_apps = seen[mkey].get("appearances", [])
                if not isinstance(actual_apps, list):
                    content_ok = False
                    break
                # Normalize to comparable tuples
                actual_set = set(normalize_appearance_for_compare(ap) for ap in actual_apps)
                expected_list = expected_by_athlete_country.get((mkey[1], mkey[2]), [])
                expected_set = set((e["event_id"], e["date"], e["venue"], e["series"], e["rank"], e["points"]) for e in expected_list)
                if actual_set != expected_set:
                    content_ok = False
                    break
        scores["club_highlights_content"] = 1.0 if content_ok else 0.0
    else:
        scores["club_highlights_content"] = 0.0

    # highlights_consistent_with_combined
    if isinstance(highlights, list) and combined_rows is not None and len(combined_rows) > 0:
        # Make set from combined
        combined_set = set()
        for row in combined_rows:
            combo = normalize_row_for_compare(row)
            combined_set.add((
                combo[0],  # event_id
                combo[1],  # date
                combo[2],  # venue
                combo[3],  # series
                combo[4],  # rank
                combo[7],  # points
            ))
        consistent = True
        for obj in highlights:
            apps = obj.get("appearances", [])
            if not isinstance(apps, list):
                consistent = False
                break
            for ap in apps:
                ap_norm = normalize_appearance_for_compare(ap)
                if ap_norm not in combined_set:
                    consistent = False
                    break
            if not consistent:
                break
        scores["highlights_consistent_with_combined"] = 1.0 if consistent else 0.0
    else:
        scores["highlights_consistent_with_combined"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()