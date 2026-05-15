import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _find_participation_files(workspace: Path) -> List[Path]:
    data_dir = workspace / "input" / "data"
    if not data_dir.exists():
        return []
    return sorted([p for p in data_dir.glob("participation_*.csv") if p.is_file()])


def _parse_participation_rows(files: List[Path]) -> Tuple[Optional[List[dict]], Optional[str]]:
    required_cols = {"respondent_id", "year", "country", "region", "ethnicity", "voted"}
    rows: List[dict] = []
    try:
        for file in files:
            with file.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return None, f"Missing header in {file}"
                if set(reader.fieldnames) != required_cols:
                    return None, f"Unexpected columns in {file}: {reader.fieldnames}"
                for row in reader:
                    # Validate fields
                    if any(k not in row for k in required_cols):
                        return None, f"Row missing required columns in {file}"
                    try:
                        # Normalize types
                        row["year"] = int(row["year"])
                        row["ethnicity"] = row["ethnicity"]
                        v = row["voted"]
                        if isinstance(v, str):
                            v = v.strip()
                        row["voted"] = int(v)
                        if row["voted"] not in (0, 1):
                            return None, f"Invalid voted value {row['voted']} in {file}"
                    except Exception as e:
                        return None, f"Invalid data types in {file}: {e}"
                    rows.append(row)
        return rows, None
    except Exception as e:
        return None, str(e)


def _compute_summary(rows: List[dict]) -> Dict[str, Dict[str, object]]:
    # Summary schema per ethnicity:
    # n_respondents: int
    # turnout_rate: str formatted to 3 decimals
    # years_covered: str "YYYY;YYYY;..."
    by_eth: Dict[str, Dict[str, object]] = {}
    for r in rows:
        eth = r["ethnicity"]
        ent = by_eth.setdefault(eth, {"count": 0, "sum_voted": 0, "years": set()})
        ent["count"] += 1
        ent["sum_voted"] += r["voted"]
        ent["years"].add(r["year"])
    summary: Dict[str, Dict[str, object]] = {}
    for eth, ent in by_eth.items():
        count = ent["count"]
        sv = ent["sum_voted"]
        years_sorted = sorted(ent["years"])
        years_str = ";".join(str(y) for y in years_sorted)
        rate = 0.0 if count == 0 else sv / count
        rate_str = f"{rate:.3f}"
        summary[eth] = {
            "n_respondents": count,
            "turnout_rate": rate_str,
            "years_covered": years_str,
        }
    return summary


def _parse_output_summary_csv(path: Path) -> Tuple[Optional[Dict[str, Dict[str, object]]], Optional[str]]:
    expected_header = ["ethnicity", "n_respondents", "turnout_rate", "years_covered"]
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, "Missing header"
            if reader.fieldnames != expected_header:
                return None, f"Header mismatch: {reader.fieldnames}"
            out: Dict[str, Dict[str, object]] = {}
            for row in reader:
                eth = row.get("ethnicity")
                if not eth:
                    return None, "Missing ethnicity value"
                try:
                    n = int(row.get("n_respondents", ""))
                except Exception:
                    return None, f"Invalid n_respondents for {eth}"
                tr = row.get("turnout_rate", None)
                yc = row.get("years_covered", None)
                if tr is None or yc is None:
                    return None, f"Missing fields for {eth}"
                out[eth] = {
                    "n_respondents": n,
                    "turnout_rate": tr,
                    "years_covered": yc,
                }
            return out, None
    except Exception as e:
        return None, str(e)


def _compare_summaries(expected: Dict[str, Dict[str, object]], actual: Dict[str, Dict[str, object]]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    exp_eths = set(expected.keys())
    act_eths = set(actual.keys())
    if exp_eths != act_eths:
        missing = sorted(exp_eths - act_eths)
        extra = sorted(act_eths - exp_eths)
        if missing:
            errors.append(f"Missing ethnicities in output: {', '.join(missing)}")
        if extra:
            errors.append(f"Unexpected ethnicities in output: {', '.join(extra)}")
        # Continue to check intersection for more detailed errors
    for eth in sorted(exp_eths & act_eths):
        e = expected[eth]
        a = actual[eth]
        if e["n_respondents"] != a["n_respondents"]:
            errors.append(f"{eth}: n_respondents expected {e['n_respondents']} got {a['n_respondents']}")
        # turnout_rate must be formatted to 3 decimals string
        if e["turnout_rate"] != a["turnout_rate"]:
            errors.append(f"{eth}: turnout_rate expected {e['turnout_rate']} got {a['turnout_rate']}")
        if e["years_covered"] != a["years_covered"]:
            errors.append(f"{eth}: years_covered expected {e['years_covered']} got {a['years_covered']}")
    return len(errors) == 0, errors


def _read_crontab_entries(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    lines = _read_text_lines(path)
    if lines is None:
        return None, "Cannot read crontab"
    entries = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        entries.append(s)
    return entries, None


def _parse_cron_line(line: str) -> Optional[Tuple[List[str], str]]:
    parts = line.split()
    if len(parts) < 6:
        return None
    schedule = parts[:5]
    command = " ".join(parts[5:])
    return schedule, command


def _is_relative_command(command: str) -> bool:
    # Ensure any path token with '/' does not start with '/'
    tokens = command.split()
    for tok in tokens:
        if "/" in tok:
            # strip quotes if any
            t = tok.strip("\"'")
            if t.startswith("/"):
                return False
    return True


def _check_daily_job(schedule: List[str], command: str) -> bool:
    # Daily at 06:15 local time: dom='*', month='*', dow='*'
    minute, hour, dom, month, dow = schedule
    if minute != "15":
        return False
    if hour not in ("06", "6"):
        return False
    if dom != "*" or month != "*" or dow != "*":
        return False
    # Command must reference scripts/aggregate_turnout.py or .sh and output/ethnicity_turnout.csv
    if ("scripts/aggregate_turnout.py" not in command) and ("scripts/aggregate_turnout.sh" not in command):
        return False
    if "output/ethnicity_turnout.csv" not in command:
        return False
    if not _is_relative_command(command):
        return False
    return True


def _check_weekly_job(schedule: List[str], command: str) -> bool:
    # Weekly on Sundays at 08:00 local time: dom='*', month='*', dow in {0,7,Sun}
    minute, hour, dom, month, dow = schedule
    if minute not in ("00", "0"):
        return False
    if hour not in ("08", "8"):
        return False
    if dom != "*" or month != "*":
        return False
    dow_norm = dow.lower()
    if dow not in ("0", "7") and dow_norm not in ("sun", "0", "7"):
        return False
    # Command must reference scripts/validate_pipeline.py and output/validation_report.json
    if "scripts/validate_pipeline.py" not in command:
        return False
    if "output/validation_report.json" not in command:
        return False
    if not _is_relative_command(command):
        return False
    return True


def _evaluate_schedule(workspace: Path) -> Tuple[bool, bool, bool]:
    # Returns: (crontab_exists_and_two_entries, daily_ok, weekly_ok)
    crontab = workspace / "scheduler" / "crontab"
    entries, _ = _read_crontab_entries(crontab)
    if entries is None:
        return False, False, False
    if len(entries) != 2:
        # Still attempt to evaluate lines if present
        daily_ok = False
        weekly_ok = False
        for line in entries:
            parsed = _parse_cron_line(line)
            if not parsed:
                continue
            schedule, command = parsed
            if ("aggregate_turnout" in command) and _check_daily_job(schedule, command):
                daily_ok = True
            if ("validate_pipeline" in command) and _check_weekly_job(schedule, command):
                weekly_ok = True
        return False, daily_ok, weekly_ok
    # Identify which line is daily vs weekly by command content
    schedules = []
    for line in entries:
        parsed = _parse_cron_line(line)
        if not parsed:
            schedules.append((None, None))
        else:
            schedules.append(parsed)
    daily_ok = False
    weekly_ok = False
    for schedule, command in schedules:
        if schedule is None or command is None:
            continue
        if "aggregate_turnout" in command:
            if _check_daily_job(schedule, command):
                daily_ok = True
        elif "validate_pipeline" in command:
            if _check_weekly_job(schedule, command):
                weekly_ok = True
        else:
            # Unknown command; cannot mark ok
            pass
    return True, daily_ok, weekly_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregation_script_present": 0.0,
        "aggregation_output_header": 0.0,
        "aggregation_output_correctness": 0.0,
        "scheduler_crontab_entries": 0.0,
        "scheduler_daily_job_correct": 0.0,
        "scheduler_weekly_job_correct": 0.0,
        "validation_script_present": 0.0,
        "validation_report_structure": 0.0,
        "validation_report_consistency": 0.0,
    }

    # Check aggregation script presence
    agg_py = workspace / "scripts" / "aggregate_turnout.py"
    agg_sh = workspace / "scripts" / "aggregate_turnout.sh"
    if agg_py.exists() or agg_sh.exists():
        scores["aggregation_script_present"] = 1.0

    # Compute expected summary from input/data
    files = _find_participation_files(workspace)
    rows, parse_err = _parse_participation_rows(files) if files else ([], None)
    expected_summary: Dict[str, Dict[str, object]] = {}
    if parse_err is None:
        expected_summary = _compute_summary(rows)

    # Check output summary CSV
    output_csv = workspace / "output" / "ethnicity_turnout.csv"
    if output_csv.exists():
        parsed_output, out_err = _parse_output_summary_csv(output_csv)
        if out_err is None and parsed_output is not None:
            scores["aggregation_output_header"] = 1.0
            if parse_err is None:
                ok, diffs = _compare_summaries(expected_summary, parsed_output)
                if ok:
                    scores["aggregation_output_correctness"] = 1.0
                else:
                    scores["aggregation_output_correctness"] = 0.0
            else:
                # Cannot compute expected summary due to parse error
                scores["aggregation_output_correctness"] = 0.0
        else:
            # Malformed header/content
            scores["aggregation_output_header"] = 0.0
            scores["aggregation_output_correctness"] = 0.0
    else:
        # Missing output file
        scores["aggregation_output_header"] = 0.0
        scores["aggregation_output_correctness"] = 0.0

    # Scheduler checks
    crontab_exists_two, daily_ok, weekly_ok = _evaluate_schedule(workspace)
    # Check crontab file existence and exactly two entries
    crontab_file = workspace / "scheduler" / "crontab"
    entries, _ = _read_crontab_entries(crontab_file)
    if entries is not None and len(entries) == 2:
        scores["scheduler_crontab_entries"] = 1.0
    else:
        scores["scheduler_crontab_entries"] = 0.0
    scores["scheduler_daily_job_correct"] = 1.0 if daily_ok else 0.0
    scores["scheduler_weekly_job_correct"] = 1.0 if weekly_ok else 0.0

    # Validation script presence
    val_py = workspace / "scripts" / "validate_pipeline.py"
    if val_py.exists():
        scores["validation_script_present"] = 1.0

    # Validation report checks
    report_path = workspace / "output" / "validation_report.json"
    report, jerr = _load_json(report_path)
    if jerr is None and isinstance(report, dict):
        # Structure check
        keys_ok = all(k in report for k in ("schedule_ok", "data_ok", "errors", "ethnicity_count"))
        types_ok = (
            isinstance(report.get("schedule_ok"), bool) and
            isinstance(report.get("data_ok"), bool) and
            isinstance(report.get("errors"), list) and
            isinstance(report.get("ethnicity_count"), int)
        )
        errors_types_ok = all(isinstance(e, str) for e in report.get("errors", []))
        if keys_ok and types_ok and errors_types_ok:
            scores["validation_report_structure"] = 1.0
        else:
            scores["validation_report_structure"] = 0.0

        # Consistency check with recomputed schedule/data
        # Compute schedule_ok: must have crontab exists+two entries and both daily+weekly correct
        recomputed_schedule_ok = (entries is not None and len(entries) == 2 and daily_ok and weekly_ok)
        recomputed_data_ok = scores["aggregation_output_correctness"] == 1.0
        recomputed_ethnicity_count = len(expected_summary) if parse_err is None else 0

        consistent = True
        if report.get("schedule_ok") != recomputed_schedule_ok:
            consistent = False
        if report.get("data_ok") != recomputed_data_ok:
            consistent = False
        if report.get("ethnicity_count") != recomputed_ethnicity_count:
            consistent = False
        # If any failures per recomputation, errors array should be non-empty
        if (not recomputed_schedule_ok or not recomputed_data_ok) and len(report.get("errors", [])) == 0:
            consistent = False
        scores["validation_report_consistency"] = 1.0 if consistent else 0.0
    else:
        scores["validation_report_structure"] = 0.0
        scores["validation_report_consistency"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()