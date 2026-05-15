import sys
import json
import csv
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_systemd_service_execstart(text: str) -> Optional[str]:
    execstart = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("ExecStart="):
            execstart = line.split("=", 1)[1].strip()
            break
    return execstart


def _parse_systemd_timer_oncalendar(text: str) -> Optional[str]:
    oncal = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("OnCalendar="):
            oncal = line.split("=", 1)[1].strip()
            break
    return oncal


def _parse_crontab_entries(text: str) -> List[Tuple[str, str, str, int]]:
    # Returns list of (schedule, command, original_line, index)
    entries = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        raw = line
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 6:
            # Not a valid cron line
            continue
        schedule = " ".join(parts[0:5])
        command = " ".join(parts[5:])
        entries.append((schedule, command, raw, idx))
    return entries


def _command_before_redirection(cmd: str) -> str:
    # Remove common shell redirections from a command string
    redir_patterns = [">>", " 2>>", " 2>", " 1>>", " 1>", " >", "|"]
    cut_index = None
    for pat in redir_patterns:
        i = cmd.find(pat)
        if i != -1:
            if cut_index is None or i < cut_index:
                cut_index = i
    if cut_index is not None:
        return cmd[:cut_index].rstrip()
    return cmd.strip()


def _parse_yaml_output_dir(text: str) -> Optional[str]:
    # Minimal YAML: find output_dir: value on a single line
    for line in text.splitlines():
        if line.strip().startswith("output_dir"):
            m = re.match(r'^\s*output_dir\s*:\s*(.+?)\s*(#.*)?$', line)
            if m:
                val = m.group(1).strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                return val
    return None


def _parse_log_runs(text: str) -> Dict[str, Dict[str, str]]:
    # Returns mapping run_id -> fields dict with keys:
    # date, start_time, scheduler, status, duration_seconds (as string)
    runs: Dict[str, Dict[str, str]] = {}
    start_re = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(.+?)\] run id=([^\s]+) start$')
    comp_re = re.compile(
        r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(.+?)\] run id=([^\s]+) completed in ([0-9]+(?:\.[0-9]+)?)s status=([A-Za-z0-9_\-]+)\b'
    )
    for line in text.splitlines():
        line = line.rstrip("\n")
        m = start_re.match(line)
        if m:
            date, time, scheduler, run_id = m.groups()
            runs.setdefault(run_id, {})
            runs[run_id].update({
                "date": date,
                "start_time": time,
                "scheduler": scheduler,
            })
            continue
        m2 = comp_re.match(line)
        if m2:
            _, _, _, run_id, dur, status = m2.groups()
            runs.setdefault(run_id, {})
            runs[run_id].update({
                "status": status,
                "duration_seconds": dur,
            })
            continue
    complete_runs = {}
    for rid, data in runs.items():
        if all(k in data for k in ["date", "start_time", "scheduler", "status", "duration_seconds"]):
            complete_runs[rid] = data
    return complete_runs


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Input paths
    service_path = workspace / "input" / "systemd" / "press-release-fetch.service"
    timer_path = workspace / "input" / "systemd" / "press-release-fetch.timer"
    crontab_in_path = workspace / "input" / "cron" / "crontab.txt"
    yaml_path = workspace / "input" / "config" / "fetcher.yaml"
    log_path = workspace / "input" / "logs" / "press_fetch.log"

    # Output paths
    audit_path = workspace / "out" / "schedule_audit.md"
    runs_csv_path = workspace / "out" / "run_history.csv"
    crontab_out_path = workspace / "out" / "cron" / "crontab_disabled.txt"

    # Load inputs
    service_text = _read_text(service_path) or ""
    timer_text = _read_text(timer_path) or ""
    crontab_text = _read_text(crontab_in_path) or ""
    yaml_text = _read_text(yaml_path) or ""
    log_text = _read_text(log_path) or ""

    expected_execstart = _parse_systemd_service_execstart(service_text) if service_text else None
    expected_oncalendar = _parse_systemd_timer_oncalendar(timer_text) if timer_text else None
    cron_entries = _parse_crontab_entries(crontab_text) if crontab_text else []
    yaml_output_dir = _parse_yaml_output_dir(yaml_text) if yaml_text else None
    parsed_runs = _parse_log_runs(log_text) if log_text else {}

    # Determine expected cron command that duplicates ExecStart
    expected_cron_dup_index = None
    expected_cron_schedule = None
    expected_cron_cmd_before_redir = None
    if expected_execstart and cron_entries:
        for sched, cmd, raw, idx in cron_entries:
            before = _command_before_redirection(cmd)
            if before == expected_execstart:
                expected_cron_dup_index = idx
                expected_cron_schedule = sched
                expected_cron_cmd_before_redir = before
                break

    # Prepare expected run rows for CSV verification
    expected_csv_headers = ["run_id", "date", "start_time", "scheduler", "status", "duration_seconds"]
    expected_rows = []
    for rid, data in parsed_runs.items():
        expected_rows.append({
            "run_id": rid,
            "date": data["date"],
            "start_time": data["start_time"],
            "scheduler": data["scheduler"],
            "status": data["status"],
            "duration_seconds": data["duration_seconds"],
        })

    # Load outputs
    audit_text = _read_text(audit_path) or ""
    csv_loaded = _read_csv_dicts(runs_csv_path)
    if csv_loaded is not None:
        actual_headers, actual_rows = csv_loaded
    else:
        actual_headers, actual_rows = None, None
    crontab_out_text = _read_text(crontab_out_path) or ""
    crontab_out_lines = crontab_out_text.splitlines()
    crontab_in_lines = crontab_text.splitlines()

    # Scoring
    scores = {
        "audit_timer_oncalendar_reported": 0.0,
        "audit_service_execstart_reported": 0.0,
        "audit_cron_schedule_and_command_reported": 0.0,
        "audit_output_dir_reported": 0.0,
        "audit_confirms_same_target": 0.0,
        "audit_recommends_systemd_over_cron": 0.0,
        "run_history_header_correct": 0.0,
        "run_history_rows_count": 0.0,
        "run_history_rows_correct": 0.0,
        "cron_disabled_file_exists": 0.0,
        "cron_duplicate_line_commented": 0.0,
        "cron_other_lines_intact": 0.0,
    }

    # Audit checks
    if audit_text and expected_oncalendar is not None:
        timer_ok = ("press-release-fetch.timer" in audit_text) and (f"OnCalendar={expected_oncalendar}" in audit_text)
        if timer_ok:
            scores["audit_timer_oncalendar_reported"] = 1.0

    if audit_text and expected_execstart is not None:
        service_ok = ("press-release-fetch.service" in audit_text) and (f"ExecStart={expected_execstart}" in audit_text)
        if service_ok:
            scores["audit_service_execstart_reported"] = 1.0

    if audit_text and expected_cron_schedule is not None and expected_cron_cmd_before_redir is not None:
        cron_ok = ("crontab.txt" in audit_text) and (expected_cron_schedule in audit_text) and (expected_cron_cmd_before_redir in audit_text)
        if cron_ok:
            scores["audit_cron_schedule_and_command_reported"] = 1.0

    if audit_text and yaml_output_dir is not None:
        if ("output_dir" in audit_text) and (yaml_output_dir in audit_text):
            scores["audit_output_dir_reported"] = 1.0

    if audit_text:
        confirms = False
        if re.search(r'\bduplicat', audit_text, flags=re.IGNORECASE):
            confirms = True
        if not confirms:
            for line in audit_text.splitlines():
                if re.search(r'systemd', line, re.IGNORECASE) and re.search(r'cron', line, re.IGNORECASE):
                    if re.search(r'\bsame\b', line, re.IGNORECASE) and re.search(r'(script|config|command)', line, re.IGNORECASE):
                        confirms = True
                        break
        if confirms:
            scores["audit_confirms_same_target"] = 1.0

        recommend = False
        for line in audit_text.splitlines():
            if re.search(r'recommend', line, re.IGNORECASE) and re.search(r'systemd', line, re.IGNORECASE):
                if re.search(r'(keep|use|retain)', line, re.IGNORECASE) and re.search(r'cron', line, re.IGNORECASE):
                    if re.search(r'(disable|turn off|remove|comment out)', line, re.IGNORECASE):
                        recommend = True
                        break
        if recommend:
            scores["audit_recommends_systemd_over_cron"] = 1.0

    # run_history.csv checks
    if actual_headers is not None:
        if actual_headers == expected_csv_headers:
            scores["run_history_header_correct"] = 1.0

        if actual_rows is not None:
            if len(actual_rows) == len(expected_rows):
                scores["run_history_rows_count"] = 1.0

            expected_by_id = {row["run_id"]: row for row in expected_rows}
            actual_by_id = {row.get("run_id", ""): row for row in actual_rows if "run_id" in row}
            rows_ok = True
            if set(expected_by_id.keys()) != set(actual_by_id.keys()):
                rows_ok = False
            else:
                for rid, exp in expected_by_id.items():
                    act = actual_by_id.get(rid)
                    if act is None:
                        rows_ok = False
                        break
                    for k in ["date", "start_time", "scheduler", "status"]:
                        if act.get(k) != exp.get(k):
                            rows_ok = False
                            break
                    if not rows_ok:
                        break
                    try:
                        act_d = float(act.get("duration_seconds", "nan"))
                        exp_d = float(exp.get("duration_seconds", "nan"))
                        if abs(act_d - exp_d) > 1e-6:
                            rows_ok = False
                            break
                    except Exception:
                        rows_ok = False
                        break
            if rows_ok:
                scores["run_history_rows_correct"] = 1.0

    # crontab_disabled.txt checks
    if crontab_out_path.exists():
        scores["cron_disabled_file_exists"] = 1.0

        if expected_cron_dup_index is not None and crontab_in_lines:
            if expected_cron_dup_index < len(crontab_out_lines):
                out_line = crontab_out_lines[expected_cron_dup_index].rstrip("\n")
                if out_line.lstrip().startswith("#"):
                    if re.search(r'disabl', out_line, re.IGNORECASE) and re.search(r'systemd', out_line, re.IGNORECASE):
                        orig = crontab_in_lines[expected_cron_dup_index].strip()
                        if orig in out_line:
                            scores["cron_duplicate_line_commented"] = 1.0

            others_ok = True
            if len(crontab_in_lines) != len(crontab_out_lines):
                others_ok = False
            else:
                for i, (in_line, out_line) in enumerate(zip(crontab_in_lines, crontab_out_lines)):
                    if i == expected_cron_dup_index:
                        continue
                    if in_line.rstrip("\n") != out_line.rstrip("\n"):
                        others_ok = False
                        break
            if others_ok:
                scores["cron_other_lines_intact"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()