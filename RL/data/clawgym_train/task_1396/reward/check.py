import csv
import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    result: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, result)]
    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            return None
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if ":" not in line.strip():
            return None
        key_part, val_part = line.strip().split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent + 2, new_dict))
        else:
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                sval = val[1:-1]
            else:
                sval = val
            if sval.isdigit():
                parsed_val: Any = int(sval)
            else:
                if sval.startswith("-") and sval[1:].isdigit():
                    parsed_val = int(sval)
                else:
                    parsed_val = sval
            current[key] = parsed_val
    return result


def _safe_load_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    return _parse_simple_yaml(text)


def _safe_read_csv_dicts(path: Optional[Path]) -> Optional[List[Dict[str, str]]]:
    if path is None:
        return None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None:
                return None
            fn = set(reader.fieldnames)
            for r in rows:
                if set(r.keys()) != fn:
                    return None
            return rows
    except Exception:
        return None


def _parse_time_hhmm(t: str) -> Optional[Tuple[int, int]]:
    try:
        parts = t.strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h, m
    except Exception:
        return None


def _time_to_minutes(t: Tuple[int, int]) -> int:
    return t[0] * 60 + t[1]


def _format_hhmm(t: Tuple[int, int]) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


def _format_hhmm_compact(t: Tuple[int, int]) -> str:
    return f"{t[0]:02d}{t[1]:02d}"


def _parse_date_yyyy_mm_dd(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _iso_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _weekday_abbrev_map() -> Dict[str, int]:
    return {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _compute_expected_schedule(settings: Dict[str, Any], med_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    sim = settings.get("simulation", {})
    start_date_s = sim.get("start_date")
    days = sim.get("days")
    if not isinstance(start_date_s, str) or not isinstance(days, int):
        return None
    start = _parse_date_yyyy_mm_dd(start_date_s)
    if start is None or days <= 0:
        return None
    qh = settings.get("quiet_hours", {})
    qstart_s = qh.get("start")
    qend_s = qh.get("end")
    if not isinstance(qstart_s, str) or not isinstance(qend_s, str):
        return None
    qstart = _parse_time_hhmm(qstart_s)
    qend = _parse_time_hhmm(qend_s)
    if qstart is None or qend is None:
        return None
    qstart_min = _time_to_minutes(qstart)
    qend_min = _time_to_minutes(qend)
    abbrev_map = _weekday_abbrev_map()

    expected: List[Dict[str, str]] = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        d_str = d.isoformat()
        wk = d.weekday()
        for idx, row in enumerate(med_rows, start=1):
            med = (row.get("medication") or "").strip()
            dose = (row.get("dose") or "").strip()
            times_str = (row.get("times") or "").strip()
            days_str = (row.get("days") or "").strip()
            instructions = (row.get("instructions") or "").strip()
            if not med or not times_str or not days_str:
                continue
            day_tokens = [tok.strip() for tok in days_str.split(",") if tok.strip()]
            allowed_wks = set()
            for tok in day_tokens:
                if tok in abbrev_map:
                    allowed_wks.add(abbrev_map[tok])
            if wk not in allowed_wks:
                continue
            time_tokens = [tok.strip() for tok in times_str.split(";") if tok.strip()]
            for t_s in time_tokens:
                t_parsed = _parse_time_hhmm(t_s)
                if t_parsed is None:
                    continue
                t_min = _time_to_minutes(t_parsed)
                if qstart_min <= t_min <= qend_min:
                    expected.append({
                        "date": d_str,
                        "time_local": _format_hhmm(t_parsed),
                        "medication": med,
                        "dose": dose,
                        "instructions": instructions,
                    })
    expected.sort(key=lambda r: (r["date"], r["time_local"]))
    return expected


def _read_schedule_preview(path: Optional[Path]) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    if path is None:
        return None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(r) for r in reader]
            for r in rows:
                if set(r.keys()) != set(reader.fieldnames):
                    return None
            return list(reader.fieldnames), rows
    except Exception:
        return None


def _load_weekly_summary(path: Optional[Path]) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    return _read_schedule_preview(path)


def _compute_expected_weekly_summary(symptom_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    items: List[Tuple[date, Dict[str, Any]]] = []
    for r in symptom_rows:
        ds = (r.get("date") or "").strip()
        d = _parse_date_yyyy_mm_dd(ds)
        if d is None:
            return None
        try:
            fatigue = float((r.get("fatigue") or "").strip())
            pain = float((r.get("pain") or "").strip())
            mobility = float((r.get("mobility") or "").strip())
        except Exception:
            return None
        severity = round(0.5 * fatigue + 0.3 * pain + 0.2 * mobility, 2)
        items.append((d, {
            "date": d.isoformat(),
            "fatigue": str(int(fatigue)) if float(int(fatigue)) == fatigue else str(fatigue),
            "pain": str(int(pain)) if float(int(pain)) == pain else str(pain),
            "mobility": str(int(mobility)) if float(int(mobility)) == mobility else str(mobility),
            "severity_score": severity,
        }))

    by_week: Dict[date, List[Tuple[date, Dict[str, Any]]]] = {}
    for d, info in items:
        ws = _iso_week_start(d)
        by_week.setdefault(ws, []).append((d, info))

    expected: List[Dict[str, Any]] = []
    for ws, records in by_week.items():
        sortable = []
        for d, info in records:
            sortable.append((info["severity_score"], d, info))
        sortable.sort(key=lambda x: (-x[0], x[1]))
        top = sortable[:3]
        for rank_idx, (_, d, info) in enumerate(top, start=1):
            expected.append({
                "week_start": ws.isoformat(),
                "date": d.isoformat(),
                "fatigue": info["fatigue"],
                "pain": info["pain"],
                "mobility": info["mobility"],
                "severity_score": info["severity_score"],
                "rank_in_week": rank_idx,
            })
    expected.sort(key=lambda r: (r["week_start"], r["rank_in_week"]))
    return expected


def _is_sorted_by_date_time(rows: List[Dict[str, str]], date_key: str, time_key: str) -> bool:
    prev: Optional[Tuple[date, Tuple[int, int]]] = None
    for r in rows:
        d = _parse_date_yyyy_mm_dd(r.get(date_key, ""))
        t = _parse_time_hhmm(r.get(time_key, ""))
        if d is None or t is None:
            return False
        cur = (d, t)
        if prev is not None:
            if cur[0] < prev[0] or (cur[0] == prev[0] and _time_to_minutes(cur[1]) < _time_to_minutes(prev[1])):
                return False
        prev = cur
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "settings_timezone_correct": 0.0,
        "settings_quiet_hours_correct": 0.0,
        "settings_paths_intact": 0.0,
        "script_exists": 0.0,
        "schedule_preview_structure": 0.0,
        "schedule_preview_sorted_by_date_time": 0.0,
        "schedule_preview_content_match": 0.0,
        "schedule_preview_source_row_valid": 0.0,
        "reminders_files_present": 0.0,
        "reminders_content_correct": 0.0,
        "weekly_summary_structure": 0.0,
        "weekly_summary_correct_rows": 0.0,
    }

    settings_path = workspace / "config" / "settings.yaml"
    settings = _safe_load_yaml(settings_path)
    if settings is None or not isinstance(settings, dict):
        return scores

    tz = settings.get("timezone")
    tz_ok = tz == "US/Eastern"
    if tz_ok:
        scores["settings_timezone_correct"] = 1.0

    qh = settings.get("quiet_hours", {})
    qh_ok = isinstance(qh, dict) and qh.get("start") == "07:00" and qh.get("end") == "21:00"
    if qh_ok:
        scores["settings_quiet_hours_correct"] = 1.0

    paths_ok = True
    try:
        if settings.get("reminder_window_days") != 7:
            paths_ok = False
        sim = settings.get("simulation", {})
        if not isinstance(sim, dict):
            paths_ok = False
        else:
            if sim.get("start_date") != "2026-03-01" or sim.get("days") != 7:
                paths_ok = False
        sources = settings.get("sources", {})
        if not isinstance(sources, dict):
            paths_ok = False
        else:
            if sources.get("med_schedule_csv") != "input/med_schedule.csv":
                paths_ok = False
            if sources.get("symptom_log_csv") != "input/symptom_log.csv":
                paths_ok = False
        outputs = settings.get("outputs", {})
        if not isinstance(outputs, dict):
            paths_ok = False
        else:
            if outputs.get("reminders_dir") != "output/reminders":
                paths_ok = False
            if outputs.get("schedule_preview_csv") != "output/schedule_preview.csv":
                paths_ok = False
            if outputs.get("weekly_summary_csv") != "output/weekly_summary.csv":
                paths_ok = False
    except Exception:
        paths_ok = False

    if tz_ok and qh_ok and paths_ok:
        scores["settings_paths_intact"] = 1.0

    script_path = workspace / "tools" / "med_scheduler.py"
    if script_path.is_file():
        scores["script_exists"] = 1.0

    sources = settings.get("sources", {}) if isinstance(settings.get("sources", {}), dict) else {}
    med_csv_rel = sources.get("med_schedule_csv") if isinstance(sources, dict) else None
    med_csv_path = workspace / med_csv_rel if isinstance(med_csv_rel, str) else None
    med_rows = _safe_read_csv_dicts(med_csv_path)

    expected_schedule = None
    if med_rows is not None:
        expected_schedule = _compute_expected_schedule(settings, med_rows)

    outputs = settings.get("outputs", {}) if isinstance(settings.get("outputs", {}), dict) else {}
    sched_csv_rel = outputs.get("schedule_preview_csv") if isinstance(outputs, dict) else None
    schedule_csv_path = workspace / sched_csv_rel if isinstance(sched_csv_rel, str) else None
    schedule_header_rows = _read_schedule_preview(schedule_csv_path)

    required_sched_header = ["date", "time_local", "medication", "dose", "instructions", "source_row"]
    if schedule_header_rows is not None:
        header, rows = schedule_header_rows
        if header == required_sched_header:
            scores["schedule_preview_structure"] = 1.0

        if _is_sorted_by_date_time(rows, "date", "time_local"):
            scores["schedule_preview_sorted_by_date_time"] = 1.0

        src_ok = True
        for r in rows:
            sr = str(r.get("source_row", "")).strip()
            if not sr.isdigit():
                src_ok = False
                break
            if int(sr) < 1:
                src_ok = False
                break
        if src_ok and rows:
            scores["schedule_preview_source_row_valid"] = 1.0

        if expected_schedule is not None:
            expected_set = {(r["date"], r["time_local"], r["medication"], r["dose"], r["instructions"]) for r in expected_schedule}
            actual_set = {(r.get("date", ""), r.get("time_local", ""), r.get("medication", ""), r.get("dose", ""), r.get("instructions", "")) for r in rows}
            if expected_set == actual_set:
                scores["schedule_preview_content_match"] = 1.0

    reminders_base_rel = outputs.get("reminders_dir") if isinstance(outputs, dict) else None
    reminders_ok = False
    reminders_content_ok = False
    if isinstance(reminders_base_rel, str) and expected_schedule is not None:
        reminders_base = workspace / reminders_base_rel
        all_exist = True
        content_all_ok = True
        for occ in expected_schedule:
            d = occ["date"]
            t = _parse_time_hhmm(occ["time_local"])
            if t is None:
                all_exist = False
                content_all_ok = False
                break
            fname = f"{_format_hhmm_compact(t)}_{occ['medication']}.txt"
            fpath = reminders_base / d / fname
            if not fpath.is_file():
                all_exist = False
            else:
                txt = _read_text(fpath)
                if txt is None:
                    content_all_ok = False
                else:
                    lines = txt.splitlines()
                    expected_line = f"Take {occ['medication']} {occ['dose']} at {occ['time_local']}"
                    if not (len(lines) == 1 and lines[0] == expected_line):
                        content_all_ok = False
        if expected_schedule:
            reminders_ok = all_exist
            reminders_content_ok = content_all_ok

    if reminders_ok:
        scores["reminders_files_present"] = 1.0
    if reminders_content_ok:
        scores["reminders_content_correct"] = 1.0

    symptom_csv_rel = sources.get("symptom_log_csv") if isinstance(sources, dict) else None
    symptom_csv_path = workspace / symptom_csv_rel if isinstance(symptom_csv_rel, str) else None
    symptom_rows = _safe_read_csv_dicts(symptom_csv_path) if symptom_csv_path else None
    expected_weekly = _compute_expected_weekly_summary(symptom_rows) if symptom_rows is not None else None

    weekly_csv_rel = outputs.get("weekly_summary_csv") if isinstance(outputs, dict) else None
    weekly_csv_path = workspace / weekly_csv_rel if isinstance(weekly_csv_rel, str) else None
    weekly_header_rows = _load_weekly_summary(weekly_csv_path) if weekly_csv_path else None

    if weekly_header_rows is not None:
        w_header, w_rows = weekly_header_rows
        required_weekly_header = ["week_start", "date", "fatigue", "pain", "mobility", "severity_score", "rank_in_week"]
        if w_header == required_weekly_header:
            scores["weekly_summary_structure"] = 1.0

        if expected_weekly is not None:
            def parse_weekly_row(r: Dict[str, str]) -> Optional[Dict[str, Any]]:
                ws = _parse_date_yyyy_mm_dd(str(r.get("week_start", "")).strip())
                d = _parse_date_yyyy_mm_dd(str(r.get("date", "")).strip())
                if ws is None or d is None:
                    return None
                try:
                    sev = float(str(r.get("severity_score", "")).strip())
                except Exception:
                    return None
                try:
                    rank = int(str(r.get("rank_in_week", "")).strip())
                except Exception:
                    return None
                return {
                    "week_start": ws.isoformat(),
                    "date": d.isoformat(),
                    "fatigue": str(r.get("fatigue", "")).strip(),
                    "pain": str(r.get("pain", "")).strip(),
                    "mobility": str(r.get("mobility", "")).strip(),
                    "severity_score": round(sev, 2),
                    "rank_in_week": rank,
                }

            actual_parsed: List[Dict[str, Any]] = []
            parse_ok = True
            for r in w_rows:
                pr = parse_weekly_row(r)
                if pr is None:
                    parse_ok = False
                    break
                actual_parsed.append(pr)
            if parse_ok and expected_weekly is not None:
                # Compare in file order to enforce required sorting
                if len(actual_parsed) == len(expected_weekly):
                    match = True
                    for exp, act in zip(expected_weekly, actual_parsed):
                        if exp["week_start"] != act["week_start"]:
                            match = False
                            break
                        if exp["date"] != act["date"]:
                            match = False
                            break
                        if str(exp["fatigue"]) != str(act["fatigue"]):
                            match = False
                            break
                        if str(exp["pain"]) != str(act["pain"]):
                            match = False
                            break
                        if str(exp["mobility"]) != str(act["mobility"]):
                            match = False
                            break
                        if float(exp["severity_score"]) != float(act["severity_score"]):
                            match = False
                            break
                        if int(exp["rank_in_week"]) != int(act["rank_in_week"]):
                            match = False
                            break
                    if match:
                        scores["weekly_summary_correct_rows"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()