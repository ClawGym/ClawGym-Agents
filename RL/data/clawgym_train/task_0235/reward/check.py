import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"json_error: {e}"


def _safe_load_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows, None
    except Exception as e:
        return None, f"csv_error: {e}"


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, f"text_error: {e}"


def _title_case_day(day: str) -> Optional[str]:
    if day is None:
        return None
    cleaned = day.strip().lower().capitalize()
    if cleaned in WEEKDAYS:
        return cleaned
    if day.strip().capitalize() in WEEKDAYS:
        return day.strip().capitalize()
    return None


def _normalize_time_str(t: str) -> Optional[str]:
    if t is None:
        return None
    t = t.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return None
    h = int(m.group(1))
    m_str = m.group(2)
    try:
        m_int = int(m_str)
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m_int <= 59):
        return None
    return f"{h:02d}:{m_int:02d}"


def _normalize_format(fmt: str) -> Optional[str]:
    if fmt is None:
        return None
    s = fmt.strip().lower()
    s_clean = re.sub(r"[\s\-_]", "", s)
    if "online" in s_clean:
        return "online"
    if "inperson" in s_clean or ("person" in s_clean and s_clean.startswith("in")):
        return "in-person"
    if s in ("inperson", "in-person", "in person"):
        return "in-person"
    if s == "online":
        return "online"
    return None


def _compute_expected_schedule(input_csv_path: Path, config: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    rows, err = _safe_load_csv_rows(input_csv_path)
    if err or rows is None:
        return None, err or "failed_to_read_csv"
    include_notes = bool(config.get("include_notes", False))
    tz = config.get("default_timezone")
    if not isinstance(tz, str) or not tz:
        return None, "missing_default_timezone"

    expected_items: List[Dict[str, Any]] = []
    for r in rows:
        status = (r.get("status", "") or "").strip().lower()
        if status != "active":
            continue
        day_tc = _title_case_day(r.get("day", ""))
        t_norm = _normalize_time_str(r.get("start_time", ""))
        fmt_norm = _normalize_format(r.get("meeting_format", ""))
        dur_str = r.get("duration_min", "")
        try:
            dur_int = int(dur_str)
        except Exception:
            return None, f"invalid_duration_min_for_id_{r.get('id','')}"
        if day_tc is None:
            return None, f"invalid_day_for_id_{r.get('id','')}"
        if t_norm is None:
            return None, f"invalid_start_time_for_id_{r.get('id','')}"
        if fmt_norm is None:
            return None, f"invalid_meeting_format_for_id_{r.get('id','')}"
        item: Dict[str, Any] = {
            "id": str(r.get("id", "")),
            "name": r.get("name", "") or "",
            "day": day_tc,
            "start_time": t_norm,
            "duration_min": dur_int,
            "format": fmt_norm,
            "location": r.get("location", "") or "",
            "timezone": tz,
        }
        if include_notes:
            item["notes"] = r.get("notes", "") or ""
        expected_items.append(item)
    return expected_items, None


def _load_actual_schedule(output_dir: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    schedule_path = output_dir / "schedule.json"
    data, err = _safe_load_json(schedule_path)
    if err or data is None:
        return None, err or "missing_schedule_json"
    if not isinstance(data, list):
        return None, "schedule_json_not_array"
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return None, f"schedule_item_{i}_not_object"
    return data, None


def _build_counts(items: List[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
    counts: Dict[Tuple[str, str], int] = {}
    for it in items:
        day = it.get("day", "")
        fmt = it.get("format", "")
        key = (day, fmt)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _safe_load_summary(output_dir: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    summary_path = output_dir / "summary.csv"
    try:
        with summary_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as e:
        return None, f"summary_csv_read_error: {e}"
    if not rows:
        return None, "summary_empty"
    header = rows[0]
    if header != ["day", "format", "count"]:
        return None, "summary_header_incorrect"
    data_rows: List[Dict[str, str]] = []
    for i, row in enumerate(rows[1:], start=1):
        if len(row) != 3:
            return None, f"summary_row_{i}_malformed"
        data_rows.append({"day": row[0], "format": row[1], "count": row[2]})
    return data_rows, None


def _compare_schedule(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> float:
    exp_by_id = {str(it["id"]): it for it in expected}
    act_by_id = {str(it.get("id", "")): it for it in actual}
    ids_union = set(exp_by_id.keys()) | set(act_by_id.keys())
    if not ids_union:
        return 0.0
    matches = 0
    for _id in ids_union:
        e = exp_by_id.get(_id)
        a = act_by_id.get(_id)
        if e is not None and a is not None and e == a:
            matches += 1
    return matches / float(len(ids_union))


def _validate_schedule_structure(actual: List[Dict[str, Any]], config: Dict[str, Any]) -> float:
    include_notes = bool(config.get("include_notes", False))
    tz = config.get("default_timezone")
    required_keys = {"id", "name", "day", "start_time", "duration_min", "format", "location", "timezone"}
    if include_notes:
        required_keys.add("notes")
    valid = 0
    for it in actual:
        keys = set(it.keys())
        if keys != required_keys:
            continue
        if not isinstance(it.get("id"), str):
            continue
        if not isinstance(it.get("name"), str):
            continue
        if it.get("day") not in WEEKDAYS:
            continue
        st = it.get("start_time")
        if not isinstance(st, str) or not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", st):
            continue
        if not isinstance(it.get("duration_min"), int):
            continue
        if it.get("format") not in {"online", "in-person"}:
            continue
        if not isinstance(it.get("location"), str):
            continue
        if include_notes and not isinstance(it.get("notes"), str):
            continue
        if tz is None or it.get("timezone") != tz:
            continue
        valid += 1
    return (valid / float(len(actual))) if actual else 0.0


def _counts_from_summary_rows(rows: List[Dict[str, str]]) -> Optional[Dict[Tuple[str, str], int]]:
    counts: Dict[Tuple[str, str], int] = {}
    for r in rows:
        day = r.get("day", "")
        fmt = r.get("format", "")
        cnt_str = r.get("count", "")
        if day not in WEEKDAYS or fmt not in {"online", "in-person"}:
            return None
        try:
            cnt = int(cnt_str)
        except Exception:
            return None
        counts[(day, fmt)] = cnt
    return counts


def _word_count(s: str) -> int:
    return len(re.findall(r"\S+", s))


def _email_mentions_output_dir_and_files(text: str, output_dir: str) -> float:
    has_schedule = "schedule.json" in text
    has_summary = "summary.csv" in text
    dir_name = output_dir.strip()
    mentions_dir = (dir_name in text) or ("output directory" in text.lower())
    files_count = int(has_schedule) + int(has_summary)
    if files_count == 2 and mentions_dir:
        return 1.0
    if files_count == 2:
        return 0.66
    if files_count == 1:
        return 0.33
    return 0.0


def _email_supportive_tone(text: str) -> float:
    lower = text.lower()
    keywords = ["thank", "appreciate", "support", "glad", "service", "grateful", "help"]
    return 1.0 if any(k in lower for k in keywords) else 0.0


def _email_total_mentions(text: str, total: int) -> float:
    lower = text.lower()
    m1 = re.search(r"\btotal\b[^\d]{0,10}(\d+)", lower)
    m2 = re.search(r"(\d+)[^\d]{0,10}\btotal\b", lower)
    found = False
    for m in (m1, m2):
        if m:
            try:
                val = int(m.group(1))
                if val == total:
                    found = True
                    break
            except Exception:
                pass
    return 1.0 if found else 0.0


def _email_breakdown_mentions(text: str, counts: Dict[Tuple[str, str], int]) -> float:
    if not counts:
        return 0.0
    found = 0
    lines = text.splitlines()
    for (day, fmt), cnt in counts.items():
        pattern1 = re.compile(rf"\b{re.escape(day)}\b[^\d\n]{{0,50}}\b{re.escape(fmt)}\b[^\d\n]{{0,50}}\b{cnt}\b", re.IGNORECASE)
        pattern2 = re.compile(rf"\b{re.escape(fmt)}\b[^\d\n]{{0,50}}\b{re.escape(day)}\b[^\d\n]{{0,50}}\b{cnt}\b", re.IGNORECASE)
        matched = False
        for ln in lines:
            if pattern1.search(ln) or pattern2.search(ln):
                matched = True
                break
        if matched:
            found += 1
    return found / float(len(counts)) if counts else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_dir_respected": 0.0,
        "schedule_json_exists_and_parseable": 0.0,
        "schedule_json_structure": 0.0,
        "schedule_json_expected_content": 0.0,
        "summary_csv_header_and_counts": 0.0,
        "summary_vs_schedule_consistency": 0.0,
        "email_exists_and_basic_requirements": 0.0,
        "email_totals_and_breakdown": 0.0,
        "email_confirms_output_dir_and_files": 0.0,
        "supportive_tone": 0.0,
    }

    config_path = workspace / "config" / "config.json"
    config, config_err = _safe_load_json(config_path)
    if config is None:
        return scores

    output_dir_name = config.get("output_dir", "")
    output_dir = workspace / str(output_dir_name)
    input_csv_path = workspace / "input" / "meetings.csv"

    expected_schedule, expected_err = _compute_expected_schedule(input_csv_path, config)
    if expected_schedule is None:
        expected_schedule = []

    schedule_path = output_dir / "schedule.json"
    summary_path = output_dir / "summary.csv"
    email_path = output_dir / "fix_email.txt"
    if schedule_path.is_file() and summary_path.is_file() and email_path.is_file():
        scores["outputs_dir_respected"] = 1.0

    actual_schedule, schedule_err = _load_actual_schedule(output_dir)
    if actual_schedule is not None:
        scores["schedule_json_exists_and_parseable"] = 1.0
        scores["schedule_json_structure"] = _validate_schedule_structure(actual_schedule, config)
        if expected_schedule:
            scores["schedule_json_expected_content"] = _compare_schedule(expected_schedule, actual_schedule)
        else:
            scores["schedule_json_expected_content"] = 0.0
    else:
        scores["schedule_json_exists_and_parseable"] = 0.0
        scores["schedule_json_structure"] = 0.0
        scores["schedule_json_expected_content"] = 0.0

    summary_rows, summary_err = _safe_load_summary(output_dir)
    if summary_rows is not None and expected_schedule:
        expected_counts = _build_counts(expected_schedule)
        parsed_counts = _counts_from_summary_rows(summary_rows)
        if parsed_counts is not None:
            correct_pairs = 0
            all_pairs = set(expected_counts.keys()) | set(parsed_counts.keys())
            for key in all_pairs:
                if expected_counts.get(key, 0) == parsed_counts.get(key, -1):
                    correct_pairs += 1
            scores["summary_csv_header_and_counts"] = correct_pairs / float(len(all_pairs)) if all_pairs else 0.0
        else:
            scores["summary_csv_header_and_counts"] = 0.0
    else:
        scores["summary_csv_header_and_counts"] = 0.0

    if actual_schedule is not None and summary_rows is not None:
        actual_counts = _build_counts(actual_schedule)
        parsed_counts2 = _counts_from_summary_rows(summary_rows)
        if parsed_counts2 is not None:
            all_pairs2 = set(actual_counts.keys()) | set(parsed_counts2.keys())
            correct2 = 0
            for key in all_pairs2:
                if actual_counts.get(key, 0) == parsed_counts2.get(key, -1):
                    correct2 += 1
            scores["summary_vs_schedule_consistency"] = correct2 / float(len(all_pairs2)) if all_pairs2 else 0.0
        else:
            scores["summary_vs_schedule_consistency"] = 0.0
    else:
        scores["summary_vs_schedule_consistency"] = 0.0

    email_text, email_err = _safe_read_text(email_path)
    if email_text is not None:
        wc_ok = 1.0 if _word_count(email_text) <= 200 else 0.0
        addressed = 1.0 if re.search(r"group service team", email_text, flags=re.IGNORECASE) else 0.0
        scores["email_exists_and_basic_requirements"] = (wc_ok + addressed) / 2.0

        if expected_schedule:
            total_active = len(expected_schedule)
            total_score = _email_total_mentions(email_text, total_active)
            expected_counts2 = _build_counts(expected_schedule)
            breakdown_score = _email_breakdown_mentions(email_text, expected_counts2)
            scores["email_totals_and_breakdown"] = (total_score + breakdown_score) / 2.0
        else:
            scores["email_totals_and_breakdown"] = 0.0

        scores["email_confirms_output_dir_and_files"] = _email_mentions_output_dir_and_files(email_text, str(output_dir_name))
        scores["supportive_tone"] = _email_supportive_tone(email_text)
    else:
        scores["email_exists_and_basic_requirements"] = 0.0
        scores["email_totals_and_breakdown"] = 0.0
        scores["email_confirms_output_dir_and_files"] = 0.0
        scores["supportive_tone"] = 0.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()