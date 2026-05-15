import json
import csv
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET


def _safe_read_text(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_bytes(p: Path):
    try:
        return p.read_bytes()
    except Exception:
        return None


def _safe_json_load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_parse_csv(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            expected_fields = ["play_timestamp", "artist", "album", "composition", "track_duration_seconds"]
            # Strict header order check
            if reader.fieldnames != expected_fields:
                return None
            for row in reader:
                # Ensure no unexpected keys
                if sorted(list(row.keys())) != expected_fields:
                    return None
                rows.append(row)
            return rows
    except Exception:
        return None


def _parse_utc_iso_z(ts: str):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _compute_expected_report(rows, date_str: str, target_artist: str):
    matches = []
    for r in rows:
        ts = r.get("play_timestamp", "")
        dt = _parse_utc_iso_z(ts)
        if dt is None:
            return None
        row_date = dt.date().isoformat()
        if row_date != date_str:
            continue
        if r.get("artist") != target_artist:
            continue
        try:
            dur = int(r.get("track_duration_seconds"))
        except Exception:
            return None
        matches.append({
            "album": r.get("album", ""),
            "composition": r.get("composition", ""),
            "duration": dur
        })
    total_tracks = len(matches)
    total_listening_seconds = sum(m["duration"] for m in matches)
    avg = (total_listening_seconds // total_tracks) if total_tracks > 0 else 0
    distinct_albums = len(set(m["album"] for m in matches))
    comp_counts = {}
    for m in matches:
        comp = m["composition"]
        comp_counts[comp] = comp_counts.get(comp, 0) + 1
    sorted_items = sorted(comp_counts.items(), key=lambda x: (-x[1], x[0]))
    top = [{"composition": comp, "play_count": cnt} for comp, cnt in sorted_items[:3]]
    return {
        "date": date_str,
        "artist": target_artist,
        "total_tracks": total_tracks,
        "total_listening_seconds": total_listening_seconds,
        "average_track_duration_seconds": avg,
        "distinct_albums": distinct_albums,
        "top_compositions": top
    }


def _json_types_and_values_match(actual: dict, expected: dict) -> bool:
    required_keys = [
        "date",
        "artist",
        "total_tracks",
        "total_listening_seconds",
        "average_track_duration_seconds",
        "distinct_albums",
        "top_compositions",
    ]
    for k in required_keys:
        if k not in actual:
            return False
    if actual["date"] != expected["date"]:
        return False
    if actual["artist"] != expected["artist"]:
        return False
    for k in ["total_tracks", "total_listening_seconds", "average_track_duration_seconds", "distinct_albums"]:
        v = actual.get(k)
        if not isinstance(v, int):
            return False
        if v != expected[k]:
            return False
    top = actual.get("top_compositions")
    if not isinstance(top, list):
        return False
    if len(top) != len(expected["top_compositions"]):
        return False
    for a_item, e_item in zip(top, expected["top_compositions"]):
        if not isinstance(a_item, dict):
            return False
        if "composition" not in a_item or "play_count" not in a_item:
            return False
        if a_item["composition"] != e_item["composition"]:
            return False
        if not isinstance(a_item["play_count"], int):
            return False
        if a_item["play_count"] != e_item["play_count"]:
            return False
    return True


def _find_xml_elements_by_localname(root: ET.Element, localname: str):
    res = []
    for elem in root.iter():
        tag = elem.tag
        if isinstance(tag, str):
            if tag == localname or tag.endswith("}" + localname):
                res.append(elem)
    return res


def _validate_windows_task_xml(p: Path):
    try:
        tree = ET.parse(str(p))
        root = tree.getroot()
    except Exception:
        return (False, False, False, False, False)
    cmd_elems = _find_xml_elements_by_localname(root, "Command")
    args_elems = _find_xml_elements_by_localname(root, "Arguments")
    program_ok = False
    args_ok = False
    if cmd_elems:
        cmd_text = (cmd_elems[0].text or "").strip().strip('"').strip("'")
        if cmd_text == "python":
            program_ok = True
    if args_elems:
        args_text = (args_elems[0].text or "").strip().strip('"').strip("'")
        if args_text == r"scripts\analyze_listening.py":
            args_ok = True
    start_elems = _find_xml_elements_by_localname(root, "StartBoundary")
    time_ok = False
    for e in start_elems:
        t = (e.text or "")
        if "T20:00" in t:
            time_ok = True
            break
    daily_ok = False
    if _find_xml_elements_by_localname(root, "DailyTrigger"):
        daily_ok = True
    if _find_xml_elements_by_localname(root, "ScheduleByDay"):
        daily_ok = True
    for e in _find_xml_elements_by_localname(root, "DaysInterval"):
        if (e.text or "").strip() == "1":
            daily_ok = True
            break
    return (True, program_ok, args_ok, time_ok, daily_ok)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_target_artist_glenn_gould": 0.0,
        "config_schedule_time_20_00": 0.0,
        "config_paths_preserved": 0.0,
        "shell_wrapper_invokes_analyzer_and_sets_cwd": 0.0,
        "cron_entry_correct": 0.0,
        "windows_task_xml_program_and_args_correct": 0.0,
        "windows_task_xml_time_20_00_daily": 0.0,
        "analyzer_run_succeeded_and_created_report": 0.0,
        "report_file_exists": 0.0,
        "report_fields_correct": 0.0,
        "input_csv_unchanged_after_run": 0.0,
    }

    cfg_path = workspace / "config" / "config.json"
    cfg = _safe_json_load(cfg_path)
    if isinstance(cfg, dict) and cfg.get("target_artist") == "Glenn Gould":
        scores["config_target_artist_glenn_gould"] = 1.0
        if cfg.get("schedule_time") == "20:00":
            scores["config_schedule_time_20_00"] = 1.0
        if cfg.get("csv_path") == "input/listening_history.csv" and cfg.get("output_dir") == "output/daily_reports":
            scores["config_paths_preserved"] = 1.0

    shell_path = workspace / "scheduler" / "run_daily.sh"
    shell_text = _safe_read_text(shell_path)
    if shell_text is not None:
        has_python_invocation = "python3 scripts/analyze_listening.py" in shell_text and "--date" not in shell_text
        has_cd = "cd " in shell_text
        if has_python_invocation and has_cd:
            scores["shell_wrapper_invokes_analyzer_and_sets_cwd"] = 1.0

    cron_path = workspace / "scheduler" / "cron" / "analyze_listening.cron"
    cron_text = _safe_read_text(cron_path)
    if cron_text is not None:
        content = cron_text.strip()
        if content == "0 20 * * * bash scheduler/run_daily.sh":
            scores["cron_entry_correct"] = 1.0

    win_xml_path = workspace / "scheduler" / "windows" / "AnalyzeListening.xml"
    if win_xml_path.exists():
        ok_parse, program_ok, args_ok, time_ok, daily_ok = _validate_windows_task_xml(win_xml_path)
        if ok_parse and program_ok and args_ok:
            scores["windows_task_xml_program_and_args_correct"] = 1.0
        if ok_parse and time_ok and daily_ok:
            scores["windows_task_xml_time_20_00_daily"] = 1.0

    analyzer_path = workspace / "scripts" / "analyze_listening.py"
    input_csv_path = workspace / "input" / "listening_history.csv"
    pre_csv_bytes = _safe_read_bytes(input_csv_path)

    expected_report_path = workspace / "output" / "daily_reports" / "2024-05-02_GlennGould.json"

    run_ok = False
    if analyzer_path.exists():
        try:
            proc = subprocess.run(
                ["python3", str(analyzer_path), "--date", "2024-05-02"],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                text=True,
            )
            run_ok = (proc.returncode == 0) and expected_report_path.exists()
        except Exception:
            run_ok = False
    if run_ok:
        scores["analyzer_run_succeeded_and_created_report"] = 1.0

    if expected_report_path.exists():
        scores["report_file_exists"] = 1.0

    rows = _safe_parse_csv(input_csv_path)
    expected = None
    if rows is not None:
        expected = _compute_expected_report(rows, "2024-05-02", "Glenn Gould")
    if expected is not None and expected_report_path.exists():
        actual = _safe_json_load(expected_report_path)
        if isinstance(actual, dict) and _json_types_and_values_match(actual, expected):
            scores["report_fields_correct"] = 1.0

    post_csv_bytes = _safe_read_bytes(input_csv_path)
    if run_ok and pre_csv_bytes is not None and post_csv_bytes is not None:
        if pre_csv_bytes == post_csv_bytes:
            scores["input_csv_unchanged_after_run"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()