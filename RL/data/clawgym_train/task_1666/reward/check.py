import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _write_debug(_: str) -> None:
    # Placeholder for potential internal debug; intentionally no output.
    return


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _parse_int_strict(s: str) -> Optional[int]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        # Disallow floats like "7.0"
        if re.fullmatch(r"[+-]?\d+", s) is None:
            return None
        return int(s)
    except Exception:
        return None


def _is_valid_record(row: Dict[str, str]) -> bool:
    # Required fields: laugh_score integer in [1,10], duration_seconds > 0
    ls = _parse_int_strict(row.get("laugh_score", ""))
    dur = _parse_int_strict(row.get("duration_seconds", ""))
    if ls is None or dur is None:
        return False
    if not (1 <= ls <= 10):
        return False
    if not (dur > 0):
        return False
    return True


def _parse_date_strict(s: str) -> Optional[datetime]:
    # Expect format YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_from_input(input_csv: Path) -> Optional[Dict[str, Any]]:
    header, rows = _read_csv_dicts(input_csv)
    if header is None or rows is None:
        return None

    total_records = len(rows)

    valid_rows = [r for r in rows if _is_valid_record(r)]
    valid_records = len(valid_rows)

    # Prepare normalized and typed records for computation
    typed_valid = []
    for r in valid_rows:
        # Copy and cast
        rr = dict(r)
        rr["_laugh_score"] = _parse_int_strict(r.get("laugh_score", ""))
        rr["_duration_seconds"] = _parse_int_strict(r.get("duration_seconds", ""))
        rr["_date"] = _parse_date_strict(r.get("date", ""))
        typed_valid.append(rr)

    # Joan Rivers counts and averages on valid records
    joan_valid = [r for r in typed_valid if r.get("comedian") == "Joan Rivers"]
    joan_records_valid = len(joan_valid)
    if joan_valid:
        joan_sum = sum(r["_laugh_score"] for r in joan_valid if r["_laugh_score"] is not None)
        joan_avg = float(joan_sum) / float(len(joan_valid))
    else:
        joan_avg = None

    # Average by comedian on valid records
    by_comedian: Dict[str, List[int]] = {}
    for r in typed_valid:
        com = r.get("comedian")
        ls = r["_laugh_score"]
        if com is None or ls is None:
            continue
        by_comedian.setdefault(com, []).append(ls)
    avg_by_comedian: Dict[str, float] = {}
    for com, lss in by_comedian.items():
        if len(lss) == 0:
            continue
        avg_by_comedian[com] = sum(lss) / float(len(lss))

    # Top comedians by avg valid: at least 2 valid records, top 3 by avg desc, ties by name asc
    eligible = [(com, avg) for com, avg in avg_by_comedian.items() if len(by_comedian.get(com, [])) >= 2]
    eligible.sort(key=lambda x: (-x[1], x[0]))
    top_comedians = [com for com, _ in eligible[:3]]

    # Top 5 Joan Rivers bits with laugh_score >= 6, sorted by:
    # laugh_score desc, then date desc, then bit_title asc
    jr_top_candidates = [
        r for r in typed_valid
        if r.get("comedian") == "Joan Rivers" and (r["_laugh_score"] is not None and r["_laugh_score"] >= 6)
    ]
    def _sort_key(r: Dict[str, Any]):
        # For date, None should be minimal; but we expect valid dates per data
        date_val = r["_date"]
        return (-r["_laugh_score"], datetime.min if date_val is None else -int(date_val.timestamp()), r.get("bit_title", ""))

    # Implement sorting carefully: convert date to comparable sortable: since we need desc, we can sort by (-score, -timestamp, title)
    # However, using negative timestamp can be risky with datetime.min; handled above.
    # We'll precompute comparable tuple manually
    def _sort_tuple(r: Dict[str, Any]):
        score = r["_laugh_score"]
        date_val = r["_date"]
        ts = date_val.timestamp() if date_val is not None else float("-inf")
        title = r.get("bit_title", "")
        return (-score, -ts, title)

    jr_top_candidates.sort(key=_sort_tuple)
    jr_top = jr_top_candidates[:5]

    expected_top_rows = []
    # Required output columns: id,date,comedian,bit_title,tag,laugh_score,duration_seconds,source
    cols = ["id", "date", "comedian", "bit_title", "tag", "laugh_score", "duration_seconds", "source"]
    for r in jr_top:
        expected_top_rows.append({c: r.get(c, "") for c in cols})

    result = {
        "total_records": total_records,
        "valid_records": valid_records,
        "joan_records_valid": joan_records_valid,
        "joan_avg_laugh_score_valid": joan_avg,
        "avg_laugh_score_by_comedian_valid": avg_by_comedian,
        "top_comedians_by_avg_valid": top_comedians,
        "expected_top_joan_rows": expected_top_rows,
        "expected_top_columns": ["id", "date", "comedian", "bit_title", "tag", "laugh_score", "duration_seconds", "source"],
    }
    return result


def _floats_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _contains_iso_timestamp(text: str) -> bool:
    # Try to find any ISO 8601-like timestamp in the text and parse via fromisoformat.
    # We'll extract candidate tokens including T separator.
    # Candidates include YYYY-MM-DD or full datetime with T.
    # We'll prefer datetime with T to be strict.
    # Search for patterns with T
    candidates = re.findall(r"\d{4}-\d{2}-\d{2}T[0-9:\.\+\-Zz]+", text)
    # Also allow space separated ISO (YYYY-MM-DD HH:MM:SS)
    candidates += re.findall(r"\d{4}-\d{2}-\d{2}\s[0-9:\.]+", text)
    for cand in candidates:
        # Normalize Z to +00:00 if present
        try:
            s = cand
            if s.endswith("Z") or s.endswith("z"):
                s = s[:-1] + "+00:00"
            # fromisoformat accepts "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS[.ffff][+HH:MM]" or with 'T'
            datetime.fromisoformat(s)
            return True
        except Exception:
            continue
    return False


def _parse_crontab_line(line: str) -> Optional[Dict[str, Any]]:
    # Return dict with fields and command string
    parts = line.strip().split()
    if len(parts) < 6:
        return None
    minute, hour, dom, month, dow = parts[:5]
    command = " ".join(parts[5:])
    return {"minute": minute, "hour": hour, "dom": dom, "month": month, "dow": dow, "command": command}


def _is_weekday_0900(minute: str, hour: str, dom: str, month: str, dow: str) -> bool:
    if minute != "0":
        return False
    if hour != "9":
        return False
    if dom != "*":
        return False
    if month != "*":
        return False
    # Accept "1-5" or "mon-fri" (case-insensitive)
    d = dow.strip()
    d_lower = d.lower()
    if d == "1-5":
        return True
    if d_lower == "mon-fri":
        return True
    return False


def _extract_nonempty_noncomment_lines(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "":
            continue
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cron_exists_and_single_entry": 0.0,
        "cron_time_weekdays_0900": 0.0,
        "cron_command_orders_processor_then_validator": 0.0,
        "run_now_matches_scheduled_chain": 0.0,
        "process_script_exists": 0.0,
        "validate_script_exists": 0.0,
        "top_joan_columns_correct": 0.0,
        "top_joan_sorted_and_filtered_correct": 0.0,
        "top_joan_max_five_rows": 0.0,
        "stats_json_keys_and_types": 0.0,
        "stats_values_correct": 0.0,
        "last_run_one_line": 0.0,
        "last_run_contains_iso_timestamp": 0.0,
        "last_run_reports_valid_count": 0.0,
        "validation_report_exists_and_shape": 0.0,
    }

    # Check for scripts existence
    process_script = workspace / "scripts" / "process_laugh_log.py"
    validate_script = workspace / "scripts" / "validate_outputs.py"
    if process_script.exists() and process_script.is_file():
        scores["process_script_exists"] = 1.0
    if validate_script.exists() and validate_script.is_file():
        scores["validate_script_exists"] = 1.0

    # Check crontab schedule
    cron_path = workspace / "schedule" / "crontab.txt"
    cron_text = _read_text(cron_path)
    scheduled_command_str = None
    if cron_text is not None:
        lines = _extract_nonempty_noncomment_lines(cron_text)
        if len(lines) == 1:
            scores["cron_exists_and_single_entry"] = 1.0
            parsed = _parse_crontab_line(lines[0])
            if parsed is not None:
                scheduled_command_str = parsed["command"].strip()
                if _is_weekday_0900(parsed["minute"], parsed["hour"], parsed["dom"], parsed["month"], parsed["dow"]):
                    scores["cron_time_weekdays_0900"] = 1.0
                # Check that command invokes processor then validator
                cmd = parsed["command"]
                proc_idx = cmd.find("scripts/process_laugh_log.py")
                val_idx = cmd.find("scripts/validate_outputs.py")
                if proc_idx != -1 and val_idx != -1 and proc_idx < val_idx:
                    scores["cron_command_orders_processor_then_validator"] = 1.0

    # Check run_now.sh matches scheduled chain
    run_now_path = workspace / "scripts" / "run_now.sh"
    run_now_text = _read_text(run_now_path)
    if run_now_text is not None and scheduled_command_str is not None:
        # Remove shebang and comments for comparison
        content_lines = [ln.strip() for ln in run_now_text.splitlines() if ln.strip() and not ln.strip().startswith("#!")]
        content_no_comments = []
        for ln in content_lines:
            if ln.startswith("#"):
                continue
            content_no_comments.append(ln)
        content_joined = " ".join(content_no_comments)
        # Check if scheduled command string appears in run_now.sh
        if scheduled_command_str in content_joined:
            scores["run_now_matches_scheduled_chain"] = 1.0

    # Compute expected artifacts from input
    input_csv = workspace / "input" / "laugh_log.csv"
    expected = _compute_expected_from_input(input_csv)

    # top_joan_rivers.csv checks
    top_csv_path = workspace / "output" / "top_joan_rivers.csv"
    top_header, top_rows = _read_csv_dicts(top_csv_path)
    if top_header is not None and top_rows is not None:
        # Columns exact match
        expected_cols = ["id", "date", "comedian", "bit_title", "tag", "laugh_score", "duration_seconds", "source"]
        if top_header == expected_cols:
            scores["top_joan_columns_correct"] = 1.0
        # At most 5 rows
        if len(top_rows) <= 5:
            scores["top_joan_max_five_rows"] = 1.0
        # Sorted/filtered correctness
        if expected is not None:
            exp_rows = expected["expected_top_joan_rows"]
            # Compare exactly len and order and values for all expected columns
            if len(exp_rows) == len(top_rows):
                match_all = True
                for i, exp in enumerate(exp_rows):
                    # Ensure only Joan Rivers rows
                    got = {k: top_rows[i].get(k, "") for k in expected_cols}
                    if got != exp:
                        match_all = False
                        break
                if match_all:
                    scores["top_joan_sorted_and_filtered_correct"] = 1.0

    # stats.json checks
    stats_path = workspace / "output" / "stats.json"
    stats = _safe_load_json(stats_path)
    if isinstance(stats, dict):
        required_keys = [
            "total_records",
            "valid_records",
            "joan_records_valid",
            "joan_avg_laugh_score_valid",
            "avg_laugh_score_by_comedian_valid",
            "top_comedians_by_avg_valid",
        ]
        keys_present = all(k in stats for k in required_keys)
        types_ok = True
        if keys_present:
            # Type checks
            if not isinstance(stats.get("total_records"), int):
                types_ok = False
            if not isinstance(stats.get("valid_records"), int):
                types_ok = False
            if not isinstance(stats.get("joan_records_valid"), int):
                types_ok = False
            # Averages must be float
            if not isinstance(stats.get("joan_avg_laugh_score_valid"), (float,)):
                types_ok = False
            if not isinstance(stats.get("avg_laugh_score_by_comedian_valid"), dict):
                types_ok = False
            else:
                for v in stats.get("avg_laugh_score_by_comedian_valid", {}).values():
                    if not isinstance(v, (float,)):
                        types_ok = False
                        break
            if not isinstance(stats.get("top_comedians_by_avg_valid"), list):
                types_ok = False
            else:
                # Ensure list of strings
                if not all(isinstance(x, str) for x in stats.get("top_comedians_by_avg_valid")):
                    types_ok = False
        if keys_present and types_ok:
            scores["stats_json_keys_and_types"] = 1.0

        # Value checks
        if expected is not None and keys_present:
            values_ok = True
            # total_records
            if stats.get("total_records") != expected["total_records"]:
                values_ok = False
            if stats.get("valid_records") != expected["valid_records"]:
                values_ok = False
            if stats.get("joan_records_valid") != expected["joan_records_valid"]:
                values_ok = False
            # joan avg
            exp_ja = expected["joan_avg_laugh_score_valid"]
            got_ja = stats.get("joan_avg_laugh_score_valid")
            if not (isinstance(got_ja, (float,)) and exp_ja is not None and _floats_close(got_ja, float(exp_ja))):
                values_ok = False
            # avg by comedian
            got_map = stats.get("avg_laugh_score_by_comedian_valid")
            if not isinstance(got_map, dict):
                values_ok = False
            else:
                # Check keys equal
                if set(got_map.keys()) != set(expected["avg_laugh_score_by_comedian_valid"].keys()):
                    values_ok = False
                else:
                    for k, v in expected["avg_laugh_score_by_comedian_valid"].items():
                        gv = got_map.get(k)
                        if not isinstance(gv, float) or not _floats_close(gv, float(v)):
                            values_ok = False
                            break
            # top comedians by avg
            got_top = stats.get("top_comedians_by_avg_valid")
            exp_top = expected["top_comedians_by_avg_valid"]
            if not isinstance(got_top, list) or got_top != exp_top:
                values_ok = False
            if values_ok:
                scores["stats_values_correct"] = 1.0

    # last_run.txt checks
    last_run_path = workspace / "output" / "last_run.txt"
    last_text = _read_text(last_run_path)
    if last_text is not None:
        # one line (ignoring trailing newline)
        lines = [ln for ln in last_text.splitlines() if ln.strip() != ""]
        if len(lines) == 1:
            scores["last_run_one_line"] = 1.0
        # contains iso timestamp
        if _contains_iso_timestamp(last_text):
            scores["last_run_contains_iso_timestamp"] = 1.0
        # contains valid_records count in summary
        if expected is not None:
            valid_count = expected["valid_records"]
            if re.search(rf"\b{valid_count}\b", last_text) is not None:
                scores["last_run_reports_valid_count"] = 1.0

    # validation_report.json shape
    validation_report_path = workspace / "output" / "validation_report.json"
    vr = _safe_load_json(validation_report_path)
    if isinstance(vr, dict):
        status = vr.get("status")
        checks = vr.get("checks")
        if isinstance(status, str) and status in ("ok", "fail") and isinstance(checks, list):
            scores["validation_report_exists_and_shape"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()