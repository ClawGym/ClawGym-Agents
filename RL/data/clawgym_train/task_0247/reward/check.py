import json
import sys
import csv
import re
from pathlib import Path
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _parse_inline_list(value: str) -> Optional[List[Any]]:
    v = value.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    inner = v[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip() for p in inner.split(",")]
    out = []
    for p in parts:
        if p == "" or p.lower() == "null":
            out.append(None)
            continue
        if p.startswith(("'", '"')) and p.endswith(("'", '"')) and len(p) >= 2:
            out.append(p[1:-1])
            continue
        iv = _parse_int(p)
        if iv is not None:
            out.append(iv)
            continue
        out.append(p)
    return out


def _parse_yaml_simple(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.lstrip()
        if stripped == "" or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if ":" not in stripped:
            return None
        key_part, value_part = stripped.split(":", 1)
        key = key_part.strip()
        value_raw = value_part.strip()
        value_clean = value_raw
        if " # " in value_clean:
            value_clean = value_clean.split(" # ", 1)[0].rstrip()
        if value_clean.startswith("#"):
            value_clean = ""
        if value_clean == "":
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent + 2, new_map))
            continue
        val: Any
        low = value_clean.lower()
        if low == "null" or value_clean == "~":
            val = None
        elif value_clean.startswith(("'", '"')) and value_clean.endswith(("'", '"')) and len(value_clean) >= 2:
            val = value_clean[1:-1]
        elif value_clean.startswith("[") and value_clean.endswith("]"):
            parsed_list = _parse_inline_list(value_clean)
            if parsed_list is None:
                return None
            val = parsed_list
        else:
            iv = _parse_int(value_clean)
            if iv is not None:
                val = iv
            else:
                val = value_clean
        current[key] = val
    return root


def _safe_csv_dict_reader(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return rows
    except Exception:
        return None


def _scan_manifests(workspace: Path) -> List[Tuple[str, str, Path]]:
    manifests_dir = workspace / "input" / "manifests"
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.csv$")
    results: List[Tuple[str, str, Path]] = []
    if not manifests_dir.exists() or not manifests_dir.is_dir():
        return results
    for p in manifests_dir.iterdir():
        if p.is_file() and pattern.match(p.name):
            date_str = p.name[:10]
            results.append((date_str, p.name, p))
    results.sort(key=lambda t: (t[0], t[1]))
    return results


def _compute_manifest_totals(rows: List[Dict[str, str]]) -> Optional[Tuple[int, int, int]]:
    total_clips = 0
    total_duration = 0
    total_size = 0
    required_cols = {"clip_id", "scene", "take", "camera", "duration_sec", "size_bytes"}
    if rows is None:
        return None
    if len(rows) == 0:
        return (0, 0, 0)
    if not required_cols.issubset(set(rows[0].keys())):
        return None
    for r in rows:
        d_str = (r.get("duration_sec") or "").strip()
        s_str = (r.get("size_bytes") or "").strip()
        d = _parse_int(d_str)
        s = _parse_int(s_str)
        if d is None or s is None:
            return None
        total_clips += 1
        total_duration += d
        total_size += s
    return (total_clips, total_duration, total_size)


def _expected_from_workspace(workspace: Path) -> Optional[Dict[str, Any]]:
    manifests = _scan_manifests(workspace)
    if not manifests:
        return {"manifests": [], "overall": {"total_clips": 0, "total_duration_sec": 0, "total_size_bytes": 0}, "latest_date": None, "rows": []}
    manifests_info: List[Dict[str, Any]] = []
    overall_clips = 0
    overall_dur = 0
    overall_size = 0
    all_rows: List[Dict[str, str]] = []
    for date_str, file_name, p in manifests:
        rows = _safe_csv_dict_reader(p)
        if rows is None:
            return None
        totals = _compute_manifest_totals(rows)
        if totals is None:
            return None
        tc, td, ts = totals
        overall_clips += tc
        overall_dur += td
        overall_size += ts
        manifests_info.append({
            "file_name": file_name,
            "date": date_str,
            "total_clips": tc,
            "total_duration_sec": td,
            "total_size_bytes": ts,
        })
        for r in rows:
            all_rows.append({
                "manifest_date": date_str,
                "file_name": file_name,
                "clip_id": (r.get("clip_id") or "").strip(),
                "scene": (r.get("scene") or "").strip(),
                "take": (r.get("take") or "").strip(),
                "camera": (r.get("camera") or "").strip(),
                "duration_sec": (r.get("duration_sec") or "").strip(),
                "size_bytes": (r.get("size_bytes") or "").strip(),
            })
    latest_date = max(d for d, _, _ in manifests)
    return {
        "manifests": manifests_info,
        "overall": {"total_clips": overall_clips, "total_duration_sec": overall_dur, "total_size_bytes": overall_size},
        "latest_date": latest_date,
        "rows": all_rows,
    }


def _last_sunday(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    offset = last_day.weekday()  # Monday=0..Sunday=6
    delta = (offset - 6) % 7
    return last_day - timedelta(days=delta)


def _europe_madrid_offset(dt_d: date) -> Tuple[int, int]:
    year = dt_d.year
    start_dst = _last_sunday(year, 3)
    end_dst = _last_sunday(year, 10)
    if dt_d >= start_dst and dt_d < end_dst:
        return (2, 0)  # CEST
    else:
        return (1, 0)  # CET


def _format_iso_with_offset(dt_d: date, hour: int, minute: int, tz_name: str) -> str:
    if tz_name == "Europe/Madrid":
        oh, om = _europe_madrid_offset(dt_d)
    else:
        oh, om = (0, 0)
    sign = "+" if (oh > 0 or (oh == 0 and om >= 0)) else "-"
    abs_h = abs(oh)
    abs_m = abs(om)
    return f"{dt_d.isoformat()}T{hour:02d}:{minute:02d}:00{sign}{abs_h:02d}:{abs_m:02d}"


def _compute_next_runs(from_date_str: str, schedule: Dict[str, Any], timezone: str) -> Optional[List[str]]:
    try:
        y, m, d = map(int, from_date_str.split("-"))
        cur = date(y, m, d)
    except Exception:
        return None
    hour = schedule.get("hour")
    minute = schedule.get("minute")
    weekdays = schedule.get("weekdays")
    if not isinstance(hour, int) or not isinstance(minute, int) or not isinstance(weekdays, list):
        return None
    allowed = set()
    for w in weekdays:
        if isinstance(w, int) and 1 <= w <= 7:
            allowed.add(w)
    if not allowed:
        return None
    out: List[str] = []
    while len(out) < 5:
        py_wd = cur.weekday()
        if (py_wd + 1) in allowed:
            out.append(_format_iso_with_offset(cur, hour, minute, timezone))
        cur = cur + timedelta(days=1)
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_source_dir_set": 0.0,
        "config_timezone_set": 0.0,
        "config_schedule_values_set": 0.0,
        "config_output_paths_preserved": 0.0,
        "digest_json_exists_and_structure": 0.0,
        "digest_json_source_and_schedule_match_config": 0.0,
        "digest_json_manifest_entries_correct": 0.0,
        "digest_json_overall_totals_correct": 0.0,
        "manifest_index_exists_and_header": 0.0,
        "manifest_index_rows_match_expected": 0.0,
        "next_runs_json_exists_and_structure": 0.0,
        "next_runs_values_correct": 0.0,
    }

    config_path = workspace / "config" / "scheduler.yaml"
    cfg_text = _read_text(config_path)
    cfg = _parse_yaml_simple(cfg_text) if cfg_text is not None else None

    expected_source_dir = "input/manifests"
    expected_timezone = "Europe/Madrid"
    expected_schedule_hour = 21
    expected_schedule_minute = 30
    expected_schedule_weekdays = [1, 2, 3, 4, 5]
    expected_output = {
        "digest_json": "output/digest.json",
        "next_runs_json": "output/next_runs.json",
        "manifest_index_csv": "output/manifest_index.csv",
    }

    source_ok = False
    tz_ok = False
    sched_ok = False
    outputs_ok = False

    if cfg is not None and isinstance(cfg, dict):
        if cfg.get("source_dir") == expected_source_dir:
            source_ok = True
            scores["config_source_dir_set"] = 1.0
        if cfg.get("timezone") == expected_timezone:
            tz_ok = True
            scores["config_timezone_set"] = 1.0
        sch = cfg.get("schedule")
        if isinstance(sch, dict):
            hour_ok = sch.get("hour") == expected_schedule_hour
            minute_ok = sch.get("minute") == expected_schedule_minute
            weekdays_ok = sch.get("weekdays") == expected_schedule_weekdays
            if hour_ok and minute_ok and weekdays_ok:
                sched_ok = True
                scores["config_schedule_values_set"] = 1.0
        out_m = cfg.get("output")
        if isinstance(out_m, dict):
            preserved = True
            for k, v in expected_output.items():
                if out_m.get(k) != v:
                    preserved = False
                    break
            if preserved:
                outputs_ok = True
        # Only award 'output_paths_preserved' if config was actually updated correctly
        if outputs_ok and source_ok and tz_ok and sched_ok:
            scores["config_output_paths_preserved"] = 1.0

    expected = _expected_from_workspace(workspace)

    digest_path = workspace / "output" / "digest.json"
    digest = _load_json(digest_path)
    if isinstance(digest, dict):
        has_keys = all(k in digest for k in ["source_dir", "timezone", "schedule", "manifests", "overall"])
        schedule_struct_ok = isinstance(digest.get("schedule"), dict) and all(
            kk in digest["schedule"] for kk in ["hour", "minute", "weekdays"]
        )
        manifests_ok = isinstance(digest.get("manifests"), list)
        overall_ok = isinstance(digest.get("overall"), dict) and all(
            kk in digest["overall"] for kk in ["total_clips", "total_duration_sec", "total_size_bytes"]
        )
        if has_keys and schedule_struct_ok and manifests_ok and overall_ok:
            scores["digest_json_exists_and_structure"] = 1.0

        if cfg is not None and isinstance(cfg, dict):
            sch_cfg = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else None
            if (
                digest.get("source_dir") == cfg.get("source_dir")
                and digest.get("timezone") == cfg.get("timezone")
                and isinstance(digest.get("schedule"), dict)
                and sch_cfg is not None
                and digest["schedule"].get("hour") == sch_cfg.get("hour")
                and digest["schedule"].get("minute") == sch_cfg.get("minute")
                and digest["schedule"].get("weekdays") == sch_cfg.get("weekdays")
            ):
                scores["digest_json_source_and_schedule_match_config"] = 1.0

        if expected is not None and isinstance(expected, dict):
            exp_manifests: List[Dict[str, Any]] = expected.get("manifests", [])
            exp_map = {m["file_name"]: m for m in exp_manifests}
            try:
                act_list = digest.get("manifests", [])
                if isinstance(act_list, list):
                    act_map = {}
                    valid_items = True
                    for item in act_list:
                        if not isinstance(item, dict):
                            valid_items = False
                            break
                        fn = item.get("file_name")
                        dt = item.get("date")
                        tc = item.get("total_clips")
                        td = item.get("total_duration_sec")
                        ts = item.get("total_size_bytes")
                        if not (isinstance(fn, str) and isinstance(dt, str) and isinstance(tc, int) and isinstance(td, int) and isinstance(ts, int)):
                            valid_items = False
                            break
                        act_map[fn] = {"file_name": fn, "date": dt, "total_clips": tc, "total_duration_sec": td, "total_size_bytes": ts}
                    if valid_items and set(act_map.keys()) == set(exp_map.keys()):
                        all_match = True
                        for fn, exp in exp_map.items():
                            act = act_map.get(fn)
                            if act is None or act["date"] != exp["date"]:
                                all_match = False
                                break
                            if (
                                act["total_clips"] != exp["total_clips"]
                                or act["total_duration_sec"] != exp["total_duration_sec"]
                                or act["total_size_bytes"] != exp["total_size_bytes"]
                            ):
                                all_match = False
                                break
                        if all_match:
                            scores["digest_json_manifest_entries_correct"] = 1.0
            except Exception:
                pass

            overall = digest.get("overall")
            if isinstance(overall, dict):
                if (
                    overall.get("total_clips") == expected.get("overall", {}).get("total_clips")
                    and overall.get("total_duration_sec") == expected.get("overall", {}).get("total_duration_sec")
                    and overall.get("total_size_bytes") == expected.get("overall", {}).get("total_size_bytes")
                ):
                    scores["digest_json_overall_totals_correct"] = 1.0

    manifest_index_path = workspace / "output" / "manifest_index.csv"
    header_expected = ["manifest_date", "file_name", "clip_id", "scene", "take", "camera", "duration_sec", "size_bytes"]
    try:
        with manifest_index_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header == header_expected:
                scores["manifest_index_exists_and_header"] = 1.0
            if expected is not None and isinstance(expected, dict) and header == header_expected:
                actual_rows = []
                for row in reader:
                    if len(row) != len(header_expected):
                        actual_rows = None
                        break
                    actual_rows.append(tuple(cell.strip() for cell in row))
                if actual_rows is not None:
                    exp_rows = []
                    for r in expected.get("rows", []):
                        exp_rows.append((
                            r["manifest_date"],
                            r["file_name"],
                            r["clip_id"],
                            r["scene"],
                            r["take"],
                            r["camera"],
                            r["duration_sec"],
                            r["size_bytes"],
                        ))
                    if len(actual_rows) == len(exp_rows) and set(actual_rows) == set(exp_rows):
                        scores["manifest_index_rows_match_expected"] = 1.0
    except Exception:
        pass

    next_runs_path = workspace / "output" / "next_runs.json"
    next_runs = _load_json(next_runs_path)
    if isinstance(next_runs, dict):
        has_fields = all(k in next_runs for k in ["timezone", "schedule", "from_date", "next_runs"])
        sched_ok_struct = isinstance(next_runs.get("schedule"), dict) and all(k in next_runs["schedule"] for k in ["hour", "minute", "weekdays"])
        runs_ok = isinstance(next_runs.get("next_runs"), list)
        if has_fields and sched_ok_struct and runs_ok:
            scores["next_runs_json_exists_and_structure"] = 1.0
        if cfg is not None and isinstance(cfg, dict) and expected is not None and isinstance(expected, dict):
            sch_cfg = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else None
            tz_cfg = cfg.get("timezone")
            latest_date = expected.get("latest_date")
            if sch_cfg is not None and isinstance(sch_cfg, dict) and isinstance(tz_cfg, str) and latest_date is not None:
                from_date_ok = next_runs.get("from_date") == latest_date
                sched_match = (
                    next_runs.get("timezone") == tz_cfg
                    and isinstance(next_runs.get("schedule"), dict)
                    and next_runs["schedule"].get("hour") == sch_cfg.get("hour")
                    and next_runs["schedule"].get("minute") == sch_cfg.get("minute")
                    and next_runs["schedule"].get("weekdays") == sch_cfg.get("weekdays")
                )
                expected_list = _compute_next_runs(latest_date, sch_cfg, tz_cfg)
                actual_list = next_runs.get("next_runs") if isinstance(next_runs.get("next_runs"), list) else None
                list_ok = isinstance(actual_list, list) and expected_list is not None and actual_list == expected_list
                if from_date_ok and sched_match and list_ok:
                    scores["next_runs_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()