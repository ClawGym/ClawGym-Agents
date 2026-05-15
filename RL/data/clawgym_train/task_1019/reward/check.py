import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_jsonl_objects(path: Path) -> Optional[List[dict]]:
    if not path.exists():
        return None
    objs: List[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                objs.append(obj)
        return objs
    except Exception:
        return None


def _parse_csv_with_header(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return ([], [])
        # Reopen with DictReader for rows
        with path.open("r", encoding="utf-8", newline="") as f:
            dict_reader = csv.DictReader(f)
            rows = [dict(r) for r in dict_reader]
        return (header, rows)
    except Exception:
        return None


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _extract_title_from_html(html: str) -> Optional[str]:
    # Prefer first h1/h2/h3/h4/h5/h6, else <title>
    m = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", _strip_tags(m.group(1))).strip()
        if title:
            return title
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", _strip_tags(m.group(1))).strip()
        if title:
            return title
    return None


def _extract_title_from_md(text: str) -> Optional[str]:
    m = re.search(r"^\s*#\s+(.*)$", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _extract_labeled_field(text: str, label: str, labels_set: List[str]) -> Optional[str]:
    # Capture non-greedily up to next known label (Date, Time, Speaker, Location, Type) or end
    # Case-sensitive per the provided inputs (use exact label matching with word boundary)
    pattern = rf"{re.escape(label)}\s*[:：]\s*(.+?)(?=\b(?:{'|'.join(map(re.escape, labels_set))})\b\s*[:：]|$)"
    m = re.search(pattern, text)
    if m:
        return m.group(1).strip()
    return None


def _extract_time_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    # Accept hyphen or en dash between times
    m = re.search(r"\bTime\b\s*[:：]\s*([0-9]{2}:[0-9]{2})\s*[–-]\s*([0-9]{2}:[0-9]{2})", text)
    if m:
        return m.group(1), m.group(2)
    # If only start time present (not in provided inputs but robust)
    m2 = re.search(r"\bTime\b\s*[:：]\s*([0-9]{2}:[0-9]{2})", text)
    if m2:
        return m2.group(1), None
    return None, None


def _normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()


def _extract_expected_from_file(path: Path, workspace: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    ext = path.suffix.lower()
    source_format = "html" if ext == ".html" else "md" if ext == ".md" else None
    if source_format is None:
        return None

    title = None
    if source_format == "html":
        title = _extract_title_from_html(text)
        content = _strip_tags(text)
    else:
        title = _extract_title_from_md(text)
        content = text

    if title:
        title = _normalize(title)
    content_plain = _normalize(content) or ""

    labels = ["Date", "Time", "Speaker", "Location", "Type"]

    date = _extract_labeled_field(content_plain, "Date", labels)
    start_time, end_time = _extract_time_range(content_plain)
    speaker = _extract_labeled_field(content_plain, "Speaker", labels)
    location = _extract_labeled_field(content_plain, "Location", labels)
    event_type = _extract_labeled_field(content_plain, "Type", labels)

    # Normalize fields
    date = _normalize(date)
    start_time = _normalize(start_time)
    end_time = _normalize(end_time)
    speaker = _normalize(speaker)
    location = _normalize(location)
    event_type = _normalize(event_type)

    # Minimal required fields: title, date, start_time, location, event_type
    if not (title and date and start_time and location and event_type):
        return None

    rel_path = path.relative_to(workspace).as_posix()
    result: Dict[str, Any] = {
        "title": title,
        "date": date,
        "start_time": start_time,
        "location": location,
        "event_type": event_type,
        "source_file": rel_path,
        "source_format": source_format,
    }
    if end_time:
        result["end_time"] = end_time
    if speaker:
        result["speaker"] = speaker
    return result


def _compute_expected_new_events(workspace: Path) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    # Returns (expected_events, input_processed_paths, all_announcement_relative_paths)
    announcements_dir = workspace / "input" / "announcements"
    all_files: List[Path] = []
    if announcements_dir.exists():
        for p in announcements_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".html", ".md"}:
                all_files.append(p)
    all_rel = [p.relative_to(workspace).as_posix() for p in all_files]

    input_state_path = workspace / "input" / "processed_state.json"
    input_processed_paths: List[str] = []
    input_state = _load_json(input_state_path)
    if isinstance(input_state, dict) and isinstance(input_state.get("processed_paths"), list):
        # Keep only strings
        input_processed_paths = [str(x) for x in input_state.get("processed_paths") if isinstance(x, str)]
    else:
        input_processed_paths = []

    new_files: List[Path] = [p for p in all_files if p.relative_to(workspace).as_posix() not in set(input_processed_paths)]

    expected_events: List[Dict[str, Any]] = []
    for p in new_files:
        evt = _extract_expected_from_file(p, workspace)
        if evt is None:
            # If any new file cannot be parsed into required fields, return empty to indicate failure to compute expectations
            return [], input_processed_paths, all_rel
        expected_events.append(evt)

    return expected_events, input_processed_paths, all_rel


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "events_jsonl_exists_and_valid_json": 0.0,
        "events_jsonl_records_correct": 0.0,
        "calendar_csv_exists_and_header": 0.0,
        "calendar_csv_rows_correct": 0.0,
        "processed_state_exists_and_parse": 0.0,
        "processed_state_union_and_sorted_correct": 0.0,
        "cross_file_consistency_events_csv": 0.0,
    }

    expected_events, input_processed_paths, _all_rel = _compute_expected_new_events(workspace)
    expected_by_source: Dict[str, Dict[str, Any]] = {e["source_file"]: e for e in expected_events}
    expected_sources_set = set(expected_by_source.keys())

    # Load outputs
    jsonl_path = workspace / "output" / "events" / "events.jsonl"
    csv_path = workspace / "output" / "events" / "calendar.csv"
    out_state_path = workspace / "output" / "state" / "processed.json"

    jsonl_objs = _parse_jsonl_objects(jsonl_path)
    if jsonl_objs is not None:
        scores["events_jsonl_exists_and_valid_json"] = 1.0

    csv_parsed = _parse_csv_with_header(csv_path)
    header: List[str] = []
    rows: List[Dict[str, str]] = []
    if csv_parsed is not None:
        header, rows = csv_parsed
        expected_header = ["date", "start_time", "title", "location", "event_type", "source_file"]
        if header == expected_header:
            scores["calendar_csv_exists_and_header"] = 1.0

    out_state = _load_json(out_state_path)
    processed_paths_out: Optional[List[str]] = None
    if isinstance(out_state, dict) and isinstance(out_state.get("processed_paths"), list):
        try:
            processed_paths_out = [str(x) for x in out_state.get("processed_paths")]
            scores["processed_state_exists_and_parse"] = 1.0
        except Exception:
            processed_paths_out = None

    # Validate JSONL records correctness
    if jsonl_objs is not None and expected_events is not None:
        # Filter out empty lines already done in parser
        count_ok = len(jsonl_objs) == len(expected_events)
        set_ok = False
        fields_ok = False
        if count_ok:
            # Build mapping by source_file
            got_by_source: Dict[str, Dict[str, Any]] = {}
            for obj in jsonl_objs:
                sf = obj.get("source_file")
                if isinstance(sf, str):
                    got_by_source[sf] = obj
            set_ok = set(got_by_source.keys()) == expected_sources_set
            if set_ok:
                fields_ok = True
                for sf, exp in expected_by_source.items():
                    obj = got_by_source.get(sf, {})
                    # Required keys
                    required_keys = ["title", "date", "start_time", "location", "event_type", "source_file", "source_format"]
                    for k in required_keys:
                        if k not in obj:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                    # Compare values (normalized)
                    def norm(v): return _normalize(v)
                    if norm(obj.get("title")) != exp["title"]:
                        fields_ok = False
                        break
                    if norm(obj.get("date")) != exp["date"]:
                        fields_ok = False
                        break
                    if norm(obj.get("start_time")) != exp["start_time"]:
                        fields_ok = False
                        break
                    if norm(obj.get("location")) != exp["location"]:
                        fields_ok = False
                        break
                    if norm(obj.get("event_type")) != exp["event_type"]:
                        fields_ok = False
                        break
                    if norm(obj.get("source_file")) != exp["source_file"]:
                        fields_ok = False
                        break
                    if norm(obj.get("source_format")) != exp["source_format"]:
                        fields_ok = False
                        break
                    # Optional end_time
                    exp_end = exp.get("end_time")
                    if exp_end is not None:
                        if "end_time" not in obj or norm(obj.get("end_time")) != exp_end:
                            fields_ok = False
                            break
                    else:
                        if "end_time" in obj:
                            fields_ok = False
                            break
                    # Optional speaker
                    exp_speaker = exp.get("speaker")
                    if exp_speaker is not None:
                        if "speaker" not in obj or norm(obj.get("speaker")) != exp_speaker:
                            fields_ok = False
                            break
                    else:
                        if "speaker" in obj:
                            fields_ok = False
                            break
        if count_ok and set_ok and fields_ok:
            scores["events_jsonl_records_correct"] = 1.0

    # Validate CSV rows correctness
    if header and rows is not None and header == ["date", "start_time", "title", "location", "event_type", "source_file"]:
        count_ok = len(rows) == len(expected_events)
        rows_ok = False
        if count_ok:
            by_sf_row = {r.get("source_file", ""): r for r in rows}
            if set(by_sf_row.keys()) == expected_sources_set:
                rows_ok = True
                for sf, exp in expected_by_source.items():
                    row = by_sf_row.get(sf, {})
                    if (row.get("date") or "").strip() != exp["date"]:
                        rows_ok = False
                        break
                    if (row.get("start_time") or "").strip() != exp["start_time"]:
                        rows_ok = False
                        break
                    if (row.get("title") or "").strip() != exp["title"]:
                        rows_ok = False
                        break
                    if (row.get("location") or "").strip() != exp["location"]:
                        rows_ok = False
                        break
                    if (row.get("event_type") or "").strip() != exp["event_type"]:
                        rows_ok = False
                        break
                    if (row.get("source_file") or "").strip() != exp["source_file"]:
                        rows_ok = False
                        break
        if count_ok and rows_ok:
            scores["calendar_csv_rows_correct"] = 1.0

    # Validate processed state union and sorted
    if processed_paths_out is not None:
        try:
            # Expected union = input processed + newly processed
            expected_union_set = set(input_processed_paths) | expected_sources_set
            expected_sorted = sorted(expected_union_set)
            out_sorted = list(processed_paths_out)
            # Check sorted order and exact match
            if out_sorted == sorted(out_sorted) and out_sorted == expected_sorted:
                scores["processed_state_union_and_sorted_correct"] = 1.0
        except Exception:
            pass

    # Cross-file consistency between JSONL and CSV
    if jsonl_objs is not None and csv_parsed is not None and header == ["date", "start_time", "title", "location", "event_type", "source_file"]:
        try:
            jsonl_by_sf = {}
            for obj in jsonl_objs:
                sf = obj.get("source_file")
                if isinstance(sf, str):
                    jsonl_by_sf[sf] = obj
            csv_by_sf = {r.get("source_file", ""): r for r in rows}
            # Only compare intersection to avoid double penalty when counts are off
            intersect = set(jsonl_by_sf.keys()) & set(csv_by_sf.keys())
            if intersect:
                consistent = True
                for sf in intersect:
                    jo = jsonl_by_sf[sf]
                    cr = csv_by_sf[sf]
                    if (cr.get("date") or "").strip() != (_normalize(jo.get("date")) or ""):
                        consistent = False
                        break
                    if (cr.get("start_time") or "").strip() != (_normalize(jo.get("start_time")) or ""):
                        consistent = False
                        break
                    if (cr.get("title") or "").strip() != (_normalize(jo.get("title")) or ""):
                        consistent = False
                        break
                    if (cr.get("location") or "").strip() != (_normalize(jo.get("location")) or ""):
                        consistent = False
                        break
                    if (cr.get("event_type") or "").strip() != (_normalize(jo.get("event_type")) or ""):
                        consistent = False
                        break
                    if (cr.get("source_file") or "").strip() != (_normalize(jo.get("source_file")) or ""):
                        consistent = False
                        break
                if consistent:
                    scores["cross_file_consistency_events_csv"] = 1.0
            else:
                # If both are expected to be empty, count as consistent
                if len(jsonl_objs) == 0 and len(rows) == 0 and len(expected_events) == 0:
                    scores["cross_file_consistency_events_csv"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()