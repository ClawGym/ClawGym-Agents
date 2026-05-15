import csv
import json
import sys
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_csv_read(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists() or not path.is_file():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _safe_json_load_array(path: Path) -> Optional[List[Any]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            else:
                return None
    except Exception:
        return None


def _simple_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML loader for the provided simple config structure
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            # list item for current_key
            if current_key is None:
                # invalid structure for our simple parser
                return None
            item = line[2:].strip()
            item = item.strip('"').strip("'")
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(item)
            continue
        if ":" in line:
            # new key
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # likely a list starts next lines
                data[key] = []
                current_key = key
            else:
                current_key = key
                sval = val.strip()
                sval = sval.strip('"').strip("'")
                if sval.isdigit():
                    data[key] = int(sval)
                else:
                    # handle booleans? not needed here
                    data[key] = sval
        else:
            # unsupported
            continue
    return data


class EventHTMLParser(HTMLParser):
    def __init__(self, source_file: str):
        super().__init__()
        self.source_file = source_file
        self.in_event_div = False
        self.current_event: Dict[str, str] = {}
        self.capture_field: Optional[str] = None
        self.events: List[Dict[str, str]] = []
        self._div_stack: List[bool] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: v for k, v in attrs}
        if tag == "div":
            classes = attrs_dict.get("class", "")
            is_event = "event-card" in classes.split()
            self._div_stack.append(is_event)
            if is_event and not self.in_event_div:
                self.in_event_div = True
                self.current_event = {
                    "event_id": attrs_dict.get("data-event-id", "").strip(),
                    "title": "",
                    "category": "",
                    "date": "",
                    "venue": "",
                    "source_file": self.source_file,
                }
        elif self.in_event_div and tag == "h2":
            classes = attrs_dict.get("class", "")
            if "title" in classes.split():
                self.capture_field = "title"
        elif self.in_event_div and tag == "span":
            classes = attrs_dict.get("class", "")
            if "category" in classes.split():
                self.capture_field = "category"
            elif "venue" in classes.split():
                self.capture_field = "venue"
        elif self.in_event_div and tag == "time":
            dt = attrs_dict.get("datetime", "")
            if dt:
                self.current_event["date"] = dt.strip()

    def handle_endtag(self, tag):
        if self.in_event_div and tag in ("h2", "span"):
            self.capture_field = None
        if tag == "div":
            if self._div_stack:
                was_event = self._div_stack.pop()
            else:
                was_event = False
            if self.in_event_div and was_event:
                # finalize event
                if self.current_event.get("event_id"):
                    # Trim fields
                    for k in ["title", "category", "venue"]:
                        if k in self.current_event and isinstance(self.current_event[k], str):
                            self.current_event[k] = self.current_event[k].strip()
                    self.events.append(self.current_event)
                self.in_event_div = False
                self.current_event = {}
                self.capture_field = None

    def handle_data(self, data):
        if self.in_event_div and self.capture_field:
            prev = self.current_event.get(self.capture_field, "")
            self.current_event[self.capture_field] = (prev + data)


def _parse_events_from_html_file(path: Path) -> List[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return []
    parser = EventHTMLParser(source_file=str(path.as_posix()))
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return []
    # Ensure all necessary fields are present
    cleaned = []
    for ev in parser.events:
        if all(ev.get(k) for k in ["event_id", "title", "category", "date,"]):
            # unlikely due to typo; we handle below
            pass
        # We'll require event_id, title, category, date, venue
        if ev.get("event_id") and ev.get("title") and ev.get("category") and ev.get("date") and ev.get("venue"):
            cleaned.append(ev)
    return cleaned


def _collect_input_events(workspace: Path) -> Dict[str, Dict[str, str]]:
    events_by_id: Dict[str, Dict[str, str]] = {}
    # Seed from input/schedule.csv (existing calendar entries)
    input_sched_path = workspace / "input" / "schedule.csv"
    rows, header = _safe_csv_read(input_sched_path)
    if rows is not None and header:
        for r in rows:
            eid = r.get("event_id", "")
            if eid:
                # Keep exactly as provided
                events_by_id[eid] = {
                    "event_id": eid,
                    "title": r.get("title", ""),
                    "category": r.get("category", ""),
                    "date": r.get("date", ""),
                    "venue": r.get("venue", ""),
                    "source_file": r.get("source_file", ""),
                }
    # Parse HTML files from input/incoming and input/archive
    for rel in ["input/incoming", "input/archive"]:
        d = workspace / rel
        if d.exists() and d.is_dir():
            for p in sorted(d.glob("*.html")):
                for ev in _parse_events_from_html_file(p):
                    eid = ev["event_id"]
                    if eid not in events_by_id:
                        events_by_id[eid] = ev
    return events_by_id


def _load_config(workspace: Path) -> Optional[Dict[str, Any]]:
    cfg = _simple_yaml_load(workspace / "input" / "config.yaml")
    if not isinstance(cfg, dict):
        return None
    # Validate minimal keys
    for k in ["today", "event_window_days", "discount_code", "keywords"]:
        if k not in cfg:
            return None
    # Normalize types
    try:
        datetime.strptime(str(cfg["today"]), "%Y-%m-%d")
    except Exception:
        return None
    try:
        cfg["event_window_days"] = int(cfg["event_window_days"])
    except Exception:
        return None
    if not isinstance(cfg.get("keywords"), list):
        return None
    # Lowercase keywords for matching
    cfg["keywords"] = [str(x).strip().lower() for x in cfg["keywords"] if isinstance(x, (str, int))]
    cfg["discount_code"] = str(cfg["discount_code"])
    return cfg


def _compute_expected_alert_ids(events_by_id: Dict[str, Dict[str, str]], cfg: Dict[str, Any]) -> Tuple[set, Dict[str, Dict[str, str]]]:
    # Returns set of event_ids and map of expected alert fields per event_id
    today = datetime.strptime(cfg["today"], "%Y-%m-%d").date()
    window = int(cfg["event_window_days"])
    keywords = set(cfg["keywords"])
    expected_ids = set()
    expected_details: Dict[str, Dict[str, str]] = {}
    for eid, ev in events_by_id.items():
        # date filter
        try:
            d = datetime.strptime(ev.get("date", ""), "%Y-%m-%d").date()
        except Exception:
            continue
        diff = (d - today).days
        if diff < 0 or diff > window:
            continue
        # ballet test
        cat = ev.get("category", "")
        title = ev.get("title", "")
        is_ballet = False
        if isinstance(cat, str) and cat.lower() == "ballet":
            is_ballet = True
        else:
            t_lower = title.lower()
            for kw in keywords:
                if kw and kw in t_lower:
                    is_ballet = True
                    break
        if is_ballet:
            expected_ids.add(eid)
            expected_details[eid] = {
                "event_id": eid,
                "title": ev.get("title", ""),
                "date": ev.get("date", ""),
                "venue": ev.get("venue", ""),
                "discount_code": cfg["discount_code"],
                "source_file": ev.get("source_file", ""),
            }
    return expected_ids, expected_details


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_mentions_watch": 0.0,
        "output_schedule_exists": 0.0,
        "schedule_header_correct": 0.0,
        "schedule_expected_events_present": 0.0,
        "schedule_no_extra_events": 0.0,
        "schedule_values_correct": 0.0,
        "schedule_no_duplicate_event_ids": 0.0,
        "alerts_exists": 0.0,
        "alerts_includes_expected_ballet": 0.0,
        "alerts_excludes_non_ballet_and_out_of_window": 0.0,
        "alerts_fields_correct": 0.0,
        "logs_exists": 0.0,
        "logs_mentions_processed_files_and_counts": 0.0,
    }

    # Check scripts directory and watch mention
    scripts_dir = workspace / "scripts"
    script_files: List[Path] = []
    if scripts_dir.exists() and scripts_dir.is_dir():
        for p in scripts_dir.iterdir():
            if p.is_file() and p.stat().st_size > 0:
                script_files.append(p)
        if script_files:
            scores["script_exists"] = 1.0
            # Scan for watch keyword
            found_watch = False
            for s in script_files:
                txt = _read_text(s)
                if txt and ("watch" in txt.lower()):
                    found_watch = True
                    break
            if found_watch:
                scores["script_mentions_watch"] = 1.0

    # Expected events from inputs
    expected_events = _collect_input_events(workspace)

    # Validate output/schedule.csv
    out_schedule_path = workspace / "output" / "schedule.csv"
    out_rows, out_header = _safe_csv_read(out_schedule_path)
    if out_rows is not None and out_header:
        scores["output_schedule_exists"] = 1.0
        expected_header = ["event_id", "title", "category", "date", "venue", "source_file"]
        if out_header == expected_header:
            scores["schedule_header_correct"] = 1.0

        # Create map and check duplicates
        seen_ids = set()
        duplicates_found = False
        out_map: Dict[str, Dict[str, str]] = {}
        for r in out_rows:
            eid = r.get("event_id", "")
            if not eid:
                continue
            if eid in seen_ids:
                duplicates_found = True
            seen_ids.add(eid)
            out_map[eid] = {
                "event_id": eid,
                "title": r.get("title", ""),
                "category": r.get("category", ""),
                "date": r.get("date", ""),
                "venue": r.get("venue", ""),
                "source_file": r.get("source_file", ""),
            }
        if not duplicates_found and out_rows is not None:
            scores["schedule_no_duplicate_event_ids"] = 1.0

        # Compare sets
        expected_ids = set(expected_events.keys())
        out_ids = set(out_map.keys())

        if expected_ids.issubset(out_ids) and expected_ids:
            scores["schedule_expected_events_present"] = 1.0

        if expected_ids and out_ids == expected_ids:
            scores["schedule_no_extra_events"] = 1.0

        # Values check for each expected event
        values_ok = True
        if expected_ids:
            for eid, ev in expected_events.items():
                ov = out_map.get(eid)
                if not ov:
                    values_ok = False
                    break
                for field in ["event_id", "title", "category", "date", "venue", "source_file"]:
                    if str(ov.get(field, "")) != str(ev.get(field, "")):
                        values_ok = False
                        break
                if not values_ok:
                    break
            if values_ok:
                scores["schedule_values_correct"] = 1.0

    # Validate alerts.json using config and expected events
    alerts_path = workspace / "output" / "alerts.json"
    cfg = _load_config(workspace)
    alerts_list = _safe_json_load_array(alerts_path)
    if alerts_list is not None:
        scores["alerts_exists"] = 1.0
    if cfg is not None and isinstance(alerts_list, list):
        expected_alert_ids, expected_alert_details = _compute_expected_alert_ids(expected_events, cfg)
        # Gather present alert ids
        present_ids = set()
        for item in alerts_list:
            if isinstance(item, dict):
                eid = item.get("event_id")
                if eid:
                    present_ids.add(eid)

        # includes expected ballet
        if expected_alert_ids and expected_alert_ids.issubset(present_ids):
            scores["alerts_includes_expected_ballet"] = 1.0

        # excludes non-ballet/out-of-window (i.e., equality of sets)
        if present_ids == expected_alert_ids:
            scores["alerts_excludes_non_ballet_and_out_of_window"] = 1.0

        # fields correct for expected alerts
        fields_ok = True
        for eid in expected_alert_ids:
            # find item in alerts_list with this eid
            match = None
            for item in alerts_list:
                if isinstance(item, dict) and item.get("event_id") == eid:
                    match = item
                    break
            if not match:
                fields_ok = False
                break
            expected_fields = expected_alert_details[eid]
            for field in ["event_id", "title", "date", "venue", "discount_code", "source_file"]:
                if str(match.get(field, "")) != str(expected_fields.get(field, "")):
                    fields_ok = False
                    break
            if not fields_ok:
                break
        if expected_alert_ids and fields_ok:
            scores["alerts_fields_correct"] = 1.0

    # Validate logs
    log_path = workspace / "output" / "logs" / "run.log"
    log_text = _read_text(log_path) if log_path.exists() else None
    if log_text is not None:
        scores["logs_exists"] = 1.0
        lt = log_text.lower()
        # Check mentions of processed files and counts info (new/duplicate)
        files_ok = ("ballet_spring_gala.html" in lt) and ("arts_february.html" in lt)
        counts_ok = ("new" in lt) and ("duplicate" in lt)
        if files_ok and counts_ok:
            scores["logs_mentions_processed_files_and_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()