import json
import re
import sys;
import csv
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    content = _read_text(path)
    if content is None:
        return None
    return content.splitlines()


def _load_simple_yaml(path: Path) -> Optional[Dict]:
    """
    Minimal YAML loader for the provided config format. Supports:
    - top-level key: "key: value"
    - top-level list:
        key:
          - item1
          - item2
    Values may be quoted; quotes are stripped.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, object] = {}
    current_list_key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        if current_list_key is not None:
            if line.strip().startswith("-"):
                item = line.split("-", 1)[1].strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                assert isinstance(data[current_list_key], list)
                data[current_list_key].append(item)
                continue
            else:
                current_list_key = None
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                data[key] = []
                current_list_key = key
            else:
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                data[key] = val
    return data


def _safe_csv_read_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return rows
    except Exception:
        return None


def _compute_invalid_event_ids_by_date_format(rows: List[Dict[str, str]]) -> List[str]:
    bad_ids: List[str] = []
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for r in rows:
        date_str = (r.get("date") or "").strip()
        eid = (r.get("event_id") or "").strip()
        if not date_re.match(date_str):
            if eid:
                bad_ids.append(eid)
    return bad_ids


def _filter_events_for_date_and_categories(rows: List[Dict[str, str]], date_str: str, categories: List[str], invalid_ids: List[str]) -> List[Dict[str, str]]:
    cats_lower = {c.lower() for c in categories}
    filtered: List[Dict[str, str]] = []
    for r in rows:
        eid = (r.get("event_id") or "").strip()
        if eid in invalid_ids:
            continue
        if (r.get("date") or "").strip() != date_str:
            continue
        category = (r.get("category") or "").strip()
        if category.lower() not in cats_lower:
            continue
        filtered.append(r)
    filtered.sort(key=lambda x: (x.get("start_time") or ""))
    return filtered


def _expected_bulletin_lines(rows: List[Dict[str, str]]) -> List[str]:
    lines: List[str] = []
    for r in rows:
        start_time = (r.get("start_time") or "").strip()
        title = (r.get("title") or "").strip()
        category = (r.get("category") or "").strip()
        location = (r.get("location") or "").strip()
        lines.append(f"{start_time} - {title} ({category}) @ {location}")
    return lines


def _parse_cron_line(line: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    m = re.match(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$", line)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)


def _extract_skipped_ids_from_log_first_line(lines: List[str]) -> Optional[List[str]]:
    first_idx = None
    for idx, ln in enumerate(lines):
        if ln.strip() != "":
            first_idx = idx
            break
    if first_idx is None:
        return None
    header = lines[first_idx].strip()
    m = re.match(r"^Skipped event_ids:\s*\[(.*)\]\s*$", header)
    if not m:
        return None
    inside = m.group(1).strip()
    if inside == "":
        return []
    parts = [p.strip() for p in inside.split(",")]
    parts = [p for p in parts if p != ""]
    return parts


def _find_first_warning_index(lines: List[str]) -> Optional[int]:
    for i, ln in enumerate(lines):
        if "WARNING:" in ln:
            return i
    return None


def _contains_expected_warning(lines: List[str]) -> bool:
    pattern = r"^WARNING: invalid date format at row\s+6\s+\(event_id=105\): '2024/07/15'\s*$"
    for ln in lines:
        if re.match(pattern, ln):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "cron_entry_present_and_correct": 0.0,
        "bulletin_for_2024_07_15_present": 0.0,
        "bulletin_content_correct": 0.0,
        "summary_for_2024_07_15_present": 0.0,
        "summary_csv_content_correct": 0.0,
        "run_log_for_2024_07_15_present": 0.0,
        "run_log_skipped_event_ids_correct": 0.0,
        "run_log_contains_validator_warnings": 0.0,
        "run_log_explanation_present_between_header_and_warnings": 0.0,
        "bulletin_path_matches_config_output_dir": 0.0,
    }

    config_path = workspace / "config" / "config.yaml"
    config = _load_simple_yaml(config_path) if config_path.exists() else None
    run_time = None
    output_dir_cfg = None
    categories_cfg: List[str] = []
    if isinstance(config, dict):
        run_time = config.get("run_time")
        output_dir_cfg = config.get("output_dir")
        cats = config.get("categories_for_bulletin")
        if isinstance(cats, list):
            categories_cfg = [str(c) for c in cats]

    script_path = workspace / "scripts" / "generate_bulletin.py"
    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0

    cron_path = workspace / "out" / "cron_entry.txt"
    cron_text = _read_text(cron_path)
    if cron_text is not None and run_time is not None:
        cron_lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(cron_lines) == 1:
            parsed = _parse_cron_line(cron_lines[0])
            if parsed is not None:
                minute, hour, dom, month, dow, command = parsed
                rt_match = re.match(r"^(\d{2}):(\d{2})$", str(run_time))
                if rt_match:
                    cfg_hour = rt_match.group(1)
                    cfg_min = rt_match.group(2)
                    try:
                        hour_ok = int(hour) == int(cfg_hour)
                        min_ok = int(minute) == int(cfg_min)
                    except Exception:
                        hour_ok = False
                        min_ok = False
                    daily_ok = (dom == "*" and month == "*" and dow == "*")
                    abs_script = str(script_path.resolve())
                    script_in_cmd = abs_script in command
                    no_date_arg = ("--date" not in command)
                    redirects_ok = ("2>&1" in command) and ("out/logs/cron.log" in command)
                    if hour_ok and min_ok and daily_ok and script_in_cmd and no_date_arg and redirects_ok:
                        scores["cron_entry_present_and_correct"] = 1.0

    events_csv_path = workspace / "input" / "events.csv"
    rows = _safe_csv_read_dicts(events_csv_path) or []
    invalid_ids = _compute_invalid_event_ids_by_date_format(rows)
    expected_skipped_ids = sorted(invalid_ids)
    expected_categories = categories_cfg
    expected_included_rows = _filter_events_for_date_and_categories(rows, "2024-07-15", expected_categories, invalid_ids)

    if output_dir_cfg:
        bulletin_path = workspace / output_dir_cfg / "bulletin-2024-07-15.txt"
    else:
        bulletin_path = workspace / "out" / "bulletins" / "bulletin-2024-07-15.txt"
    bulletin_lines = _read_lines(bulletin_path)
    if bulletin_lines is not None:
        scores["bulletin_for_2024_07_15_present"] = 1.0

    if output_dir_cfg:
        expected_bulletin_dir = (workspace / output_dir_cfg).resolve()
        if bulletin_path.resolve().parent == expected_bulletin_dir and bulletin_path.exists():
            scores["bulletin_path_matches_config_output_dir"] = 1.0

    if bulletin_lines is not None:
        non_empty_bulletin = [ln.strip() for ln in bulletin_lines if ln.strip() != ""]
        expected_lines = _expected_bulletin_lines(expected_included_rows)
        if non_empty_bulletin == expected_lines:
            scores["bulletin_content_correct"] = 1.0

    summary_path = workspace / "out" / "summaries" / "summary-2024-07-15.csv"
    summary_rows = None
    summary_header = None
    try:
        if summary_path.exists():
            with summary_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                all_rows = list(reader)
                if all_rows:
                    summary_header = all_rows[0]
                    summary_rows = all_rows[1:]
            scores["summary_for_2024_07_15_present"] = 1.0
    except Exception:
        summary_rows = None
        summary_header = None

    if summary_rows is not None and summary_header is not None:
        header_ok = summary_header == ["event_id", "title", "category", "start_time"]
        expected_summary = []
        for r in expected_included_rows:
            expected_summary.append([
                (r.get("event_id") or "").strip(),
                (r.get("title") or "").strip(),
                (r.get("category") or "").strip(),
                (r.get("start_time") or "").strip()
            ])
        content_ok = header_ok and (summary_rows == expected_summary)
        if content_ok:
            scores["summary_csv_content_correct"] = 1.0

    run_log_path = workspace / "out" / "logs" / "run-2024-07-15.log"
    run_log_lines = _read_lines(run_log_path)
    if run_log_lines is not None:
        scores["run_log_for_2024_07_15_present"] = 1.0
        skipped = _extract_skipped_ids_from_log_first_line(run_log_lines)
        if skipped is not None and sorted(skipped) == expected_skipped_ids:
            scores["run_log_skipped_event_ids_correct"] = 1.0
        if _contains_expected_warning(run_log_lines):
            scores["run_log_contains_validator_warnings"] = 1.0
        first_nonempty_idx = None
        for i, ln in enumerate(run_log_lines):
            if ln.strip():
                first_nonempty_idx = i
                break
        warn_idx = _find_first_warning_index(run_log_lines)
        explanation_ok = False
        if first_nonempty_idx is not None and warn_idx is not None and warn_idx > first_nonempty_idx:
            for i in range(first_nonempty_idx + 1, warn_idx):
                ln = run_log_lines[i].strip()
                if ln and "WARNING:" not in ln:
                    explanation_ok = True
                    break
        if explanation_ok:
            scores["run_log_explanation_present_between_header_and_warnings"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()