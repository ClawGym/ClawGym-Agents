import json
import re
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_stdout_rows(text: str) -> Optional[int]:
    m = re.search(r"OK:\s*wrote\s+output/summary_by_mode_year\.csv\s+with\s+(\d+)\s+rows", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _is_relative_path(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    if s.startswith("/") or re.match(r"^[a-zA-Z]:\\", s):
        return False
    if "://" in s:
        return False
    if s.startswith("../"):
        return False
    return True


def _expected_summary_rows(input_csv: Path) -> Optional[List[List[str]]]:
    rows = _read_csv_rows(input_csv)
    if rows is None:
        return None
    counts: Dict[tuple, int] = {}
    for r in rows:
        mode = (r.get("transport_type") or "").strip()
        year_raw = (r.get("year_opened") or "").strip()
        if not mode or not year_raw:
            continue
        try:
            year = int(year_raw)
        except Exception:
            return None
        key = (mode, year)
        counts[key] = counts.get(key, 0) + 1
    sorted_rows = sorted([(m, y, c) for (m, y), c in counts.items()], key=lambda t: (t[0], t[1]))
    return [["mode", "start_year", "count"]] + [[m, str(y), str(c)] for (m, y, c) in sorted_rows]


def _load_csv_exact(path: Path) -> Optional[List[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return [row for row in reader]
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "first_run_captured_stderr": 0.0,
        "config_corrected_fields": 0.0,
        "second_run_captured_stdout": 0.0,
        "summary_csv_content": 0.0,
        "stdout_rows_match_csv": 0.0,
        "diagnostics_structure": 0.0,
        "research_tasks_structure": 0.0,
    }

    input_csv = workspace / "input" / "routes.csv"
    config_json = workspace / "config" / "config.json"
    first_stderr = workspace / "output" / "first_run_stderr.txt"
    second_stdout = workspace / "output" / "second_run_stdout.txt"
    summary_csv = workspace / "output" / "summary_by_mode_year.csv"
    diagnostics_json = workspace / "output" / "diagnostics.json"
    research_tasks_json = workspace / "output" / "research_tasks.json"

    # 1) First run stderr check
    stderr_text = _read_text_safe(first_stderr)
    if stderr_text is not None:
        has_missing_header_msg = "ERROR: Missing columns in CSV per field mapping" in stderr_text
        mentions_mode_expected = "expected column 'mode' present in CSV header" in stderr_text
        mentions_start_year_expected = "expected column 'start_year' present in CSV header" in stderr_text
        no_stdout_phrases = ("Reading data from" not in stderr_text) and ("OK: wrote" not in stderr_text)
        if has_missing_header_msg and mentions_mode_expected and mentions_start_year_expected and no_stdout_phrases:
            scores["first_run_captured_stderr"] = 1.0

    # 2) Config corrected fields
    cfg = _load_json_safe(config_json)
    if isinstance(cfg, dict):
        data_path_ok = cfg.get("data_path") == "input/routes.csv"
        output_dir_ok = cfg.get("output_dir") == "output"
        fields = cfg.get("fields", {})
        mode_ok = isinstance(fields, dict) and fields.get("mode") == "transport_type"
        start_year_ok = isinstance(fields, dict) and fields.get("start_year") == "year_opened"
        if data_path_ok and output_dir_ok and mode_ok and start_year_ok:
            scores["config_corrected_fields"] = 1.0

    # 3) Second run stdout check
    stdout_text = _read_text_safe(second_stdout)
    parsed_rows_from_stdout: Optional[int] = None
    if stdout_text is not None:
        has_reading = "Reading data from input/routes.csv" in stdout_text
        has_validating = "Validating field mapping and data types..." in stdout_text
        parsed_rows_from_stdout = _parse_stdout_rows(stdout_text)
        wrote_ok = parsed_rows_from_stdout is not None
        no_error_keyword = "ERROR:" not in stdout_text
        if has_reading and has_validating and wrote_ok and no_error_keyword:
            scores["second_run_captured_stdout"] = 1.0

    # 4) Summary CSV content check
    expected = _expected_summary_rows(input_csv)
    actual = _load_csv_exact(summary_csv)
    if expected is not None and actual is not None:
        if actual == expected:
            scores["summary_csv_content"] = 1.0

    # 5) stdout rows match CSV rows (non-header)
    if parsed_rows_from_stdout is not None and actual is not None and len(actual) >= 1:
        data_rows = actual[1:]
        try:
            expected_n = len(data_rows)
            if parsed_rows_from_stdout == expected_n == 10:
                scores["stdout_rows_match_csv"] = 1.0
        except Exception:
            pass

    # 6) Diagnostics structure
    diag = _load_json_safe(diagnostics_json)
    if isinstance(diag, dict):
        initial_errors = diag.get("initial_errors")
        config_changes = diag.get("config_changes")
        success_summary = diag.get("success_summary")
        ok = True

        if not (isinstance(initial_errors, list) and all(isinstance(x, str) for x in initial_errors) and len(initial_errors) >= 1):
            ok = False
        else:
            if stderr_text is None:
                ok = False
            else:
                for msg in initial_errors:
                    if msg.strip() and msg not in stderr_text:
                        ok = False
                        break
                if ok:
                    has_mode_mention = any("mode" in m for m in initial_errors)
                    has_start_year_mention = any("start_year" in m for m in initial_errors)
                    if not (has_mode_mention and has_start_year_mention):
                        ok = False

        if not (isinstance(config_changes, list) and all(isinstance(x, dict) for x in config_changes)):
            ok = False
        else:
            found_mode_change = False
            found_start_year_change = False
            for ch in config_changes:
                field = ch.get("field")
                fr = ch.get("from")
                to = ch.get("to")
                if field == "mode" and fr == "mode" and to == "transport_type":
                    found_mode_change = True
                if field == "start_year" and fr == "start_year" and to == "year_opened":
                    found_start_year_change = True
            if not (found_mode_change and found_start_year_change):
                ok = False

        if not (isinstance(success_summary, str) and "output/summary_by_mode_year.csv" in success_summary):
            ok = False
        else:
            if parsed_rows_from_stdout is None:
                ok = False
            else:
                if str(parsed_rows_from_stdout) not in success_summary:
                    ok = False

        if ok:
            scores["diagnostics_structure"] = 1.0

    # 7) Research tasks structure
    tasks = _load_json_safe(research_tasks_json)
    rt_ok = True
    if not (isinstance(tasks, list) and 5 <= len(tasks) <= 8):
        rt_ok = False
    if rt_ok:
        ids = []
        for t in tasks:
            if not isinstance(t, dict):
                rt_ok = False
                break
            req_fields = ["id", "description", "inputs", "command", "outputs", "dependencies", "status"]
            if any(f not in t for f in req_fields):
                rt_ok = False
                break
            if not isinstance(t["id"], str) or not t["id"].strip():
                rt_ok = False
                break
            if not isinstance(t["description"], str) or not t["description"].strip():
                rt_ok = False
                break
            if not (isinstance(t["inputs"], list) and all(isinstance(x, str) and _is_relative_path(x) for x in t["inputs"])):
                rt_ok = False
                break
            if not (isinstance(t["command"], str) and t["command"].strip()):
                rt_ok = False
                break
            if not (isinstance(t["outputs"], list) and all(isinstance(x, str) and _is_relative_path(x) for x in t["outputs"])):
                rt_ok = False
                break
            if not (isinstance(t["dependencies"], list) and all(isinstance(x, str) for x in t["dependencies"])):
                rt_ok = False
                break
            if t["status"] != "pending":
                rt_ok = False
                break
            ids.append(t["id"])

        if rt_ok and tasks:
            first_task = tasks[0]
            first_id = first_task["id"]
            cmd = first_task.get("command", "")
            if "scripts/process_routes.py" not in cmd or "--config" not in cmd:
                rt_ok = False
            if "output/summary_by_mode_year.csv" not in first_task.get("outputs", []):
                rt_ok = False
            if any(dep for dep in first_task.get("dependencies", [])):
                rt_ok = False
            for t in tasks[1:]:
                if "output/summary_by_mode_year.csv" not in t.get("inputs", []):
                    rt_ok = False
                    break
                if first_id not in t.get("dependencies", []):
                    rt_ok = False
                    break

    if rt_ok:
        scores["research_tasks_structure"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()