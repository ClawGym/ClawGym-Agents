import csv
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_simple_config_yaml(path: Path):
    """
    Minimal parser for the specific expected YAML structure:
    - Top-level keys: schedule, output_dir, retention_days, filter_communities
    - filter_communities is a simple list of strings with "- " items.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # Remove comments
        if "#" in line:
            line = line.split("#", 1)[0]
        if not line.strip():
            i += 1
            continue
        if ":" in line and not line.lstrip().startswith("- "):
            # top-level key
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if key == "filter_communities":
                # collect list items
                items = []
                i += 1
                while i < n:
                    nxt = lines[i]
                    if "#" in nxt:
                        nxt = nxt.split("#", 1)[0]
                    if not nxt.strip():
                        i += 1
                        continue
                    stripped = nxt.lstrip()
                    if stripped.startswith("- "):
                        item_val = stripped[2:].strip()
                        item_val = _strip_quotes(item_val)
                        items.append(item_val)
                        i += 1
                        continue
                    if ":" in nxt and not nxt.lstrip().startswith("- "):
                        break
                    break
                result[key] = items
                continue
            else:
                val = _strip_quotes(val)
                result[key] = val
                i += 1
                continue
        else:
            i += 1
            continue
    if "retention_days" in result:
        rd = result["retention_days"]
        try:
            result["retention_days"] = int(rd)
        except Exception:
            pass
    return result


def _parse_intish(v):
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        iv = int(round(v))
        if abs(v - iv) < 1e-9:
            return iv
        return None
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except Exception:
            try:
                f = float(s)
                iv = int(round(f))
                if abs(f - iv) < 1e-9:
                    return iv
                return None
            except Exception:
                return None
    return None


def _parse_floatish(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except Exception:
            return None
    return None


def _safe_parse_datetime(dt_str: str):
    try:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _compute_expected_summary(patrol_csv_path: Path, filter_communities):
    """
    Returns:
      expected_sorted: list of dicts with keys:
        date, community, patrol_count, total_patrol_minutes, average_patrol_minutes, incidents_reported, door_checks
      expected_map: dict keyed by (date, community) -> values dict
    """
    expected = {}
    try:
        with patrol_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not {"timestamp", "community", "guard_id", "patrol_minutes", "incidents_reported", "door_checks"}.issubset(reader.fieldnames or []):
                return [], {}
            allowed = set(filter_communities or [])
            for row in reader:
                community = row.get("community", "")
                if allowed and community not in allowed:
                    continue
                ts = row.get("timestamp", "")
                if "T" in ts:
                    date = ts.split("T", 1)[0]
                else:
                    try:
                        date = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
                    except Exception:
                        continue
                pm = _parse_floatish(row.get("patrol_minutes", "0"))
                ir = _parse_intish(row.get("incidents_reported", "0"))
                dc = _parse_intish(row.get("door_checks", "0"))
                if pm is None or ir is None or dc is None:
                    return [], {}
                key = (date, community)
                agg = expected.get(key)
                if agg is None:
                    agg = {
                        "date": date,
                        "community": community,
                        "patrol_count": 0,
                        "total_patrol_minutes": 0.0,
                        "incidents_reported": 0,
                        "door_checks": 0,
                    }
                agg["patrol_count"] += 1
                agg["total_patrol_minutes"] += pm
                agg["incidents_reported"] += ir
                agg["door_checks"] += dc
                expected[key] = agg
    except Exception:
        return [], {}
    expected_list = []
    for _, agg in expected.items():
        cnt = agg["patrol_count"]
        total = agg["total_patrol_minutes"]
        avg = (total / cnt) if cnt > 0 else 0.0
        record = {
            "date": agg["date"],
            "community": agg["community"],
            "patrol_count": int(cnt),
            "total_patrol_minutes": float(total),
            "average_patrol_minutes": float(avg),
            "incidents_reported": int(agg["incidents_reported"]),
            "door_checks": int(agg["door_checks"]),
        }
        expected_list.append(record)
    expected_sorted = sorted(expected_list, key=lambda r: (r["date"], r["community"]))
    expected_map = {(r["date"], r["community"]): r for r in expected_sorted}
    return expected_sorted, expected_map


def _parse_summary_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = []
            for row in reader:
                rec = {
                    "date": row.get("date", ""),
                    "community": row.get("community", ""),
                    "patrol_count": _parse_intish(row.get("patrol_count")),
                    "total_patrol_minutes": _parse_floatish(row.get("total_patrol_minutes")),
                    "average_patrol_minutes": _parse_floatish(row.get("average_patrol_minutes")),
                    "incidents_reported": _parse_intish(row.get("incidents_reported")),
                    "door_checks": _parse_intish(row.get("door_checks")),
                }
                rows.append(rec)
            return header, rows
    except Exception:
        return None, None


def _parse_summary_json(path: Path):
    data = _load_json(path)
    if not isinstance(data, list):
        return None
    out = []
    try:
        for item in data:
            if not isinstance(item, dict):
                return None
            rec = {
                "date": item.get("date", ""),
                "community": item.get("community", ""),
                "patrol_count": _parse_intish(item.get("patrol_count")),
                "total_patrol_minutes": _parse_floatish(item.get("total_patrol_minutes")),
                "average_patrol_minutes": _parse_floatish(item.get("average_patrol_minutes")),
                "incidents_reported": _parse_intish(item.get("incidents_reported")),
                "door_checks": _parse_intish(item.get("door_checks")),
            }
            out.append(rec)
        return out
    except Exception:
        return None


def _is_sorted_by_date_community(rows):
    if rows is None:
        return False
    prev = None
    for r in rows:
        key = (r.get("date", ""), r.get("community", ""))
        if prev is not None and key < prev:
            return False
        prev = key
    return True


def _float_close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compare_summary_rows(rows, expected_map):
    if rows is None:
        return False
    if len(rows) != len(expected_map):
        return False
    actual_map = {}
    for r in rows:
        k = (r.get("date", ""), r.get("community", ""))
        actual_map[k] = r
    if set(actual_map.keys()) != set(expected_map.keys()):
        return False
    for k, exp in expected_map.items():
        act = actual_map.get(k)
        if act is None:
            return False
        if _parse_intish(act.get("patrol_count")) != exp["patrol_count"]:
            return False
        if not _float_close(_parse_floatish(act.get("total_patrol_minutes")), exp["total_patrol_minutes"]):
            return False
        if not _float_close(_parse_floatish(act.get("average_patrol_minutes")), exp["average_patrol_minutes"]):
            return False
        if _parse_intish(act.get("incidents_reported")) != exp["incidents_reported"]:
            return False
        if _parse_intish(act.get("door_checks")) != exp["door_checks"]:
            return False
    return True


def _compute_next_runs_23_at(reference_time_str: str):
    ref_dt = _safe_parse_datetime(reference_time_str)
    if ref_dt is None:
        return None
    first_candidate = ref_dt.replace(hour=23, minute=0, second=0, microsecond=0)
    runs = []
    # Include same-day 23:00 if reference is before or exactly at 23:00
    if ref_dt.time() <= first_candidate.time():
        next_dt = first_candidate
    else:
        next_dt = first_candidate + timedelta(days=1)
    for _ in range(3):
        runs.append(next_dt.strftime("%Y-%m-%dT%H:%M:%S"))
        next_dt = next_dt + timedelta(days=1)
    return runs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_schedule_set": 0.0,
        "config_retention_days_set": 0.0,
        "config_filter_communities_expected": 0.0,
        "script_file_exists": 0.0,
        "summary_csv_exists": 0.0,
        "summary_csv_header_correct": 0.0,
        "summary_csv_row_count_correct": 0.0,
        "summary_csv_sorted": 0.0,
        "summary_csv_values_correct": 0.0,
        "summary_json_exists": 0.0,
        "summary_json_values_correct": 0.0,
        "schedule_preview_exists": 0.0,
        "schedule_preview_schedule_correct": 0.0,
        "schedule_preview_reference_time_correct": 0.0,
        "schedule_preview_next_runs_correct": 0.0,
    }

    # Check script existence
    script_path = workspace / "tools" / "guard_report.py"
    if script_path.exists() and script_path.is_file():
        scores["script_file_exists"] = 1.0

    # Parse configuration if present
    config_path = workspace / "input" / "config.yml"
    config = _parse_simple_config_yaml(config_path)

    # Configuration checks
    if isinstance(config, dict):
        if config.get("schedule") == "daily 23:00":
            scores["config_schedule_set"] = 1.0
        rd = config.get("retention_days", None)
        if rd == 14 or (isinstance(rd, str) and rd.strip().isdigit() and int(rd.strip()) == 14):
            scores["config_retention_days_set"] = 1.0
        # Only award filter_communities_expected if schedule is correctly set (avoid baseline credit in scaffold)
        fc = config.get("filter_communities")
        if scores["config_schedule_set"] == 1.0:
            if isinstance(fc, list):
                expected_set = {"Oak Grove", "River Bend"}
                fc_set = set(str(x) for x in fc)
                if fc_set == expected_set and len(fc) == 2:
                    scores["config_filter_communities_expected"] = 1.0

    # Determine output_dir from config
    output_dir_path = None
    if isinstance(config, dict):
        output_dir_val = config.get("output_dir")
        if isinstance(output_dir_val, str) and output_dir_val:
            output_dir_path = workspace / output_dir_val

    # Compute expected daily summary from logs and config filter (only if inputs exist)
    patrol_csv_path = workspace / "input" / "patrol_logs.csv"
    filter_communities = config.get("filter_communities", []) if isinstance(config, dict) else []
    expected_list, expected_map = _compute_expected_summary(patrol_csv_path, filter_communities)

    # Check CSV summary
    if output_dir_path is not None:
        csv_path = output_dir_path / "daily_guard_summary.csv"
        if csv_path.exists() and csv_path.is_file():
            scores["summary_csv_exists"] = 1.0
            header, rows = _parse_summary_csv(csv_path)
            expected_header = [
                "date",
                "community",
                "patrol_count",
                "total_patrol_minutes",
                "average_patrol_minutes",
                "incidents_reported",
                "door_checks",
            ]
            if header == expected_header:
                scores["summary_csv_header_correct"] = 1.0
            if rows is not None and len(rows) == len(expected_list):
                scores["summary_csv_row_count_correct"] = 1.0
            if rows is not None and _is_sorted_by_date_community(rows):
                scores["summary_csv_sorted"] = 1.0
            if rows is not None and expected_map:
                if _compare_summary_rows(rows, expected_map):
                    scores["summary_csv_values_correct"] = 1.0

        # Check JSON summary
        json_summary_path = output_dir_path / "daily_guard_summary.json"
        if json_summary_path.exists() and json_summary_path.is_file():
            scores["summary_json_exists"] = 1.0
            json_rows = _parse_summary_json(json_summary_path)
            if json_rows is not None and expected_map:
                if _compare_summary_rows(json_rows, expected_map):
                    scores["summary_json_values_correct"] = 1.0

        # Check schedule preview
        schedule_preview_path = output_dir_path / "schedule_preview.json"
        if schedule_preview_path.exists() and schedule_preview_path.is_file():
            scores["schedule_preview_exists"] = 1.0
            sched_prev = _load_json(schedule_preview_path)
            if isinstance(sched_prev, dict):
                if sched_prev.get("schedule") == "daily 23:00":
                    scores["schedule_preview_schedule_correct"] = 1.0
                ref_input = _load_json(workspace / "input" / "reference_time.json")
                if isinstance(ref_input, dict) and "as_of" in ref_input:
                    expected_ref = ref_input["as_of"]
                    if sched_prev.get("reference_time") == expected_ref:
                        scores["schedule_preview_reference_time_correct"] = 1.0
                    expected_runs = _compute_next_runs_23_at(expected_ref)
                    nr = sched_prev.get("next_runs")
                    if isinstance(nr, list) and expected_runs is not None and nr == expected_runs:
                        scores["schedule_preview_next_runs_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()