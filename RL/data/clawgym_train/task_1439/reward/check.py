import json
import csv
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_hhmm(s: str) -> Optional[Tuple[int, int]]:
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"(\d{2}):(\d{2})", s.strip())
    if not m:
        return None
    try:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        return None
    return None


def _parse_date_yyyy_mm_dd(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _normalize_ws(s: str) -> str:
    return " ".join(s.split())


def _truthy(s: Any) -> bool:
    val = str(s).strip().lower()
    return val in ("true", "yes", "y", "1")


def _canonical_tour_tuple(t: Dict[str, Any]) -> Tuple[str, str, str, bool, int, str]:
    time = t.get("time") or ""
    theme = t.get("theme") or ""
    location = t.get("location") or ""
    survivor_present = bool(t.get("survivor_present", False))
    max_attendees = t.get("max_attendees")
    try:
        max_attendees_int = int(max_attendees)
    except Exception:
        max_attendees_int = 0
    notes = t.get("notes") or ""
    return (time, theme, location, survivor_present, max_attendees_int, notes)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "initial_error_captured": 0.0,
        "config_keys_and_formats_valid": 0.0,
        "config_paths_correct": 0.0,
        "last_run_log_success": 0.0,
        "daily_briefing_json_valid": 0.0,
        "daily_briefing_matches_exhibits_csv": 0.0,
        "summary_csv_consistent_with_json": 0.0,
        "cron_entry_matches_run_time": 0.0,
    }

    # Load config
    cfg_path = workspace / "config" / "briefing_config.json"
    cfg = _safe_load_json(cfg_path)

    # Prepare expected basics
    expected_input_csv_rel = "input/upcoming_exhibits.csv"
    expected_output_json_rel = "output/daily_briefing.json"

    ref_dt = None
    expected_target_date_str = None
    run_time_tuple = None

    if isinstance(cfg, dict):
        # Check required keys and formats
        required_keys_present = all(
            k in cfg for k in ("input_csv_path", "output_json_path", "reference_date")
        )
        ref_dt = _parse_date_yyyy_mm_dd(cfg.get("reference_date", ""))
        run_time_tuple = _parse_hhmm(cfg.get("run_time", "06:00"))
        if required_keys_present and ref_dt is not None and run_time_tuple is not None:
            scores["config_keys_and_formats_valid"] = 1.0

        # Verify paths are as specified
        if (
            cfg.get("input_csv_path") == expected_input_csv_rel
            and cfg.get("output_json_path") == expected_output_json_rel
        ):
            scores["config_paths_correct"] = 1.0

        if ref_dt is not None:
            expected_target_date_str = (ref_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    # Check initial error log
    first_err_path = workspace / "logs" / "first_run_error.txt"
    first_err_text = _safe_read_text(first_err_path)
    if first_err_text:
        if ("Traceback" in first_err_text) and ("KeyError" in first_err_text) and ("input_csv_path" in first_err_text):
            scores["initial_error_captured"] = 1.0

    # Check last run success log
    last_log_path = workspace / "logs" / "last_run.log"
    last_log_text = _safe_read_text(last_log_path)
    if last_log_text:
        has_traceback = "Traceback" in last_log_text
        # Find the "Wrote briefing to ..." line
        wrote_lines = [
            ln.strip()
            for ln in last_log_text.splitlines()
            if "Wrote briefing to " in ln
        ]
        parsed_ok = False
        if wrote_lines:
            line = wrote_lines[-1]
            m = re.search(r"Wrote briefing to (.+?) \((\d+)\s+tours\s+for\s+(\d{4}-\d{2}-\d{2})\)\.", line)
            if m:
                out_path_in_log = m.group(1)
                date_in_log = m.group(3)
                path_ok = True
                date_ok = True
                if isinstance(cfg, dict):
                    path_ok = (out_path_in_log == cfg.get("output_json_path"))
                    if expected_target_date_str is not None:
                        date_ok = (date_in_log == expected_target_date_str)
                parsed_ok = path_ok and date_ok
            else:
                parsed_ok = False
        if not has_traceback and wrote_lines and parsed_ok:
            scores["last_run_log_success"] = 1.0

    # Validate daily_briefing.json
    briefing_path = workspace / "output" / "daily_briefing.json"
    briefing = _safe_load_json(briefing_path)
    json_valid = False
    if isinstance(briefing, dict):
        date_ok = isinstance(briefing.get("date"), str)
        tours_ok = isinstance(briefing.get("tours"), list)
        types_ok = True
        if tours_ok:
            for t in briefing["tours"]:
                if not isinstance(t, dict):
                    types_ok = False
                    break
                for key in ("time", "theme", "location", "survivor_present", "max_attendees", "notes"):
                    if key not in t:
                        types_ok = False
                        break
                if not types_ok:
                    break
                if not isinstance(t.get("survivor_present"), bool):
                    types_ok = False
                    break
                try:
                    int(t.get("max_attendees"))
                except Exception:
                    types_ok = False
                    break
        if expected_target_date_str is not None:
            date_ok = date_ok and (briefing.get("date") == expected_target_date_str)
        json_valid = date_ok and tours_ok and types_ok
    if json_valid:
        scores["daily_briefing_json_valid"] = 1.0

    # Cross-check JSON against CSV content for target date
    exhibits_csv_path = workspace / expected_input_csv_rel
    exhibits_rows = _safe_load_csv_dicts(exhibits_csv_path)
    json_matches_csv = False
    if exhibits_rows is not None and isinstance(briefing, dict) and expected_target_date_str is not None:
        expected_tours: List[Dict[str, Any]] = []
        try:
            for row in exhibits_rows:
                if row.get("date") == expected_target_date_str:
                    tour = {
                        "time": row.get("time"),
                        "theme": row.get("theme"),
                        "location": row.get("location"),
                        "survivor_present": _truthy(row.get("survivor_present", "")),
                        "max_attendees": int(row.get("max_attendees") or 0),
                        "notes": row.get("notes", "") or "",
                    }
                    expected_tours.append(tour)
            expected_tours_sorted = sorted(expected_tours, key=lambda t: t["time"] or "")
            actual_tours = briefing.get("tours") if isinstance(briefing, dict) else []
            expected_can = [_canonical_tour_tuple(t) for t in expected_tours_sorted]
            actual_can = [_canonical_tour_tuple(t) for t in actual_tours]
            json_matches_csv = expected_can == actual_can
        except Exception:
            json_matches_csv = False
    if json_matches_csv:
        scores["daily_briefing_matches_exhibits_csv"] = 1.0

    # Validate summary CSV against JSON
    summary_csv_path = workspace / "output" / "briefing_summary.csv"
    summary_rows = _safe_load_csv_dicts(summary_csv_path)
    summary_ok = False
    if isinstance(briefing, dict) and summary_rows is not None:
        header_ok = False
        try:
            with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                header_ok = header == ["time", "theme", "location", "survivor_present", "max_attendees", "notes"]
        except Exception:
            header_ok = False

        tours = briefing.get("tours") if isinstance(briefing.get("tours"), list) else None
        if header_ok and isinstance(tours, list):
            json_rows = []
            for t in tours:
                can = _canonical_tour_tuple(t)
                json_rows.append(can)
            csv_rows = []
            try:
                for r in summary_rows:
                    time = r.get("time") or ""
                    theme = r.get("theme") or ""
                    location = r.get("location") or ""
                    surv = _truthy(r.get("survivor_present", ""))
                    try:
                        max_attendees = int(r.get("max_attendees"))
                    except Exception:
                        max_attendees = None
                    notes = r.get("notes") or ""
                    if max_attendees is None:
                        csv_rows = None
                        break
                    csv_rows.append((time, theme, location, surv, max_attendees, notes))
            except Exception:
                csv_rows = None

            if csv_rows is not None and len(csv_rows) == len(json_rows):
                json_rows_sorted = sorted(json_rows)
                csv_rows_sorted = sorted(csv_rows)
                summary_ok = json_rows_sorted == csv_rows_sorted

    if summary_ok:
        scores["summary_csv_consistent_with_json"] = 1.0

    # Validate cron entry matches run_time
    cron_path = workspace / "scheduler" / "daily_briefing.cron"
    cron_text = _safe_read_text(cron_path)
    cron_ok = False
    if cron_text is not None and run_time_tuple is not None:
        nonempty_lines = [ln.strip() for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(nonempty_lines) == 1:
            line = nonempty_lines[0]
            parts = line.split()
            if len(parts) >= 6:
                minute_token, hour_token, day_m, month_m, day_w = parts[:5]
                cmd = " ".join(parts[5:])
                try:
                    minute_val = int(minute_token)
                    hour_val = int(hour_token)
                except Exception:
                    minute_val = None
                    hour_val = None
                expected_hour, expected_minute = run_time_tuple
                schedule_ok = (
                    minute_val == expected_minute
                    and hour_val == expected_hour
                    and day_m == "*"
                    and month_m == "*"
                    and day_w == "*"
                )
                expected_cmd = "python3 scripts/generate_briefing.py --config config/briefing_config.json >> logs/cron.log 2>&1"
                cmd_ok = (_normalize_ws(cmd) == _normalize_ws(expected_cmd))
                cron_ok = schedule_ok and cmd_ok
    if cron_ok:
        scores["cron_entry_matches_run_time"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()