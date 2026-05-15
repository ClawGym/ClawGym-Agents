import json
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json(path: Path):
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _is_hex_sha256(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", s))


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _sha256_file(path: Path) -> str:
    data = _read_bytes(path)
    if data is None:
        return None
    return _sha256_bytes(data)


def _parse_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _count_lines(text: str) -> int:
    if text is None:
        return 0
    return len([ln for ln in text.splitlines()])


def _parse_ok_metrics_from_text(text: str):
    """
    Parse lines beginning with 'OK:' and extract numeric values for units, rejects, uptime.
    Returns list of dicts with keys 'units', 'rejects', 'uptime'.
    """
    metrics = []
    if not text:
        return metrics
    for line in text.splitlines():
        if line.strip().startswith("OK:"):
            parts = [p.strip() for p in line.split(":", 1)[-1].split(",")]
            d = {}
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k in ("units", "rejects"):
                        try:
                            d[k] = int(v)
                        except Exception:
                            try:
                                d[k] = int(float(v))
                            except Exception:
                                d[k] = None
                    elif k == "uptime":
                        try:
                            d[k] = float(v)
                        except Exception:
                            d[k] = None
            if all(k in d for k in ("units", "rejects", "uptime")) and None not in (d["units"], d["rejects"], d["uptime"]):
                metrics.append(d)
    return metrics


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_supports_run_once_flag": 0.0,
        "cron_template_valid": 0.0,
        "windows_task_template_valid": 0.0,
        "processed_osha_json_valid": 0.0,
        "raw_html_sha256_consistent": 0.0,
        "run_status_json_valid": 0.0,
        "logs_stdout_expected_lines": 0.0,
        "run_metrics_match_stdout": 0.0,
        "sha256_logs_match_json": 0.0,
        "daily_report_consistency": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "fetch_and_monitor.py"
    cron_path = workspace / "schedule" / "cron_example.txt"
    windows_task_path = workspace / "schedule" / "windows_task.xml"
    raw_html_path = workspace / "data" / "raw" / "osha_machine_guarding.html"
    processed_osha_json_path = workspace / "data" / "processed" / "osha_machine_guarding.json"
    stdout_log_path = workspace / "logs" / "simulated_stdout.log"
    stderr_log_path = workspace / "logs" / "simulated_stderr.log"
    run_status_json_path = workspace / "data" / "processed" / "run_status.json"
    daily_report_json_path = workspace / "data" / "processed" / "daily_report.json"

    # 1) Script exists
    if script_path.is_file():
        scores["script_exists"] = 1.0
        # Check support for --run-once flag by scanning script source
        script_text = _read_text(script_path) or ""
        if "--run-once" in script_text or "--run_on" in script_text or "run-once" in script_text:
            scores["script_supports_run_once_flag"] = 1.0
    else:
        scores["script_exists"] = 0.0
        scores["script_supports_run_once_flag"] = 0.0

    # 2) Cron template validation
    cron_text = _read_text(cron_path)
    if cron_text is not None:
        non_comment_lines = [ln.strip() for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(non_comment_lines) == 1:
            line = non_comment_lines[0]
            # Expect: minute hour dom month dow command...
            parts = line.split()
            if len(parts) >= 6:
                minute, hour, dom, month, dow = parts[:5]
                cmd = " ".join(parts[5:])
                minute_ok = minute == "30"
                # Allow '5' or '05'
                hour_ok = hour in ("5", "05")
                # day-of-week Monday-Saturday; accept "1-6" or "Mon-Sat" (case-insensitive)
                dow_normalized = dow.lower()
                dow_ok = (dow_normalized == "1-6") or (dow_normalized == "mon-sat")
                cmd_has_python = "/usr/bin/env python3" in cmd
                cmd_has_script = "scripts/fetch_and_monitor.py" in cmd
                if minute_ok and hour_ok and dow_ok and cmd_has_python and cmd_has_script:
                    scores["cron_template_valid"] = 1.0

    # 3) Windows Task XML template validation
    windows_xml = _read_text(windows_task_path)
    if windows_xml is not None:
        xml_lc = windows_xml.lower()
        has_task_tag = "<task" in xml_lc and "</task>" in xml_lc
        # Look for time 05:30 or 05:30:00
        has_time = "05:30" in windows_xml or "05:30:00" in windows_xml or "T05:30" in windows_xml
        has_python = "python" in xml_lc
        has_script = "scripts/fetch_and_monitor.py" in xml_lc
        # Look for indication of daily trigger
        has_daily = "daily" in xml_lc or "dailytrigger" in xml_lc or "schedulebyday" in xml_lc or "calendartrigger" in xml_lc
        if has_task_tag and has_time and has_python and has_script and has_daily:
            scores["windows_task_template_valid"] = 1.0

    # 4) Processed OSHA JSON validation
    osha = _load_json(processed_osha_json_path)
    osha_valid = False
    if osha and isinstance(osha, dict):
        st = osha.get("source_title")
        retrieved = osha.get("retrieved_at_iso")
        html_sha = osha.get("html_sha256")
        success = osha.get("success")
        error_message = osha.get("error_message")
        headings = osha.get("headings")
        links = osha.get("links")

        conds = []
        conds.append(st == "OSHA Machine Guarding")
        conds.append(_parse_iso8601(retrieved))
        conds.append(_is_hex_sha256(html_sha))
        conds.append(isinstance(success, bool))
        conds.append((error_message is None) or isinstance(error_message, str))
        if isinstance(success, bool) and success is False:
            conds.append(isinstance(error_message, str) and len(error_message.strip()) > 0)
        conds.append(isinstance(headings, list) and all(isinstance(h, str) for h in headings))
        # links: list of up to first 10 unique anchor links with non-empty text
        links_ok = isinstance(links, list) and len(links) <= 10
        if links_ok:
            for li in links:
                if not (isinstance(li, dict) and isinstance(li.get("text"), str) and isinstance(li.get("href"), str)):
                    links_ok = False
                    break
        conds.append(links_ok)
        if all(conds):
            scores["processed_osha_json_valid"] = 1.0
            osha_valid = True

    # 5) Raw HTML sha256 consistent with JSON
    if osha_valid:
        html_sha_json = osha.get("html_sha256")
        raw_sha = _sha256_file(raw_html_path)
        if raw_sha is not None and isinstance(html_sha_json, str) and raw_sha.lower() == html_sha_json.lower():
            scores["raw_html_sha256_consistent"] = 1.0

    # 6) Run status JSON validation and log checks
    run_status = _load_json(run_status_json_path)
    stdout_text = _read_text(stdout_log_path)
    stderr_text = _read_text(stderr_log_path)

    # Validate run_status.json structure and content
    run_status_valid = False
    if run_status and isinstance(run_status, dict):
        cmd = run_status.get("command")
        exit_code = run_status.get("exit_code")
        lines_stdout = run_status.get("lines_stdout")
        lines_stderr = run_status.get("lines_stderr")
        rs = run_status.get("run_status")
        metrics = run_status.get("metrics")
        error_summary = run_status.get("error_summary")
        stdout_sha = run_status.get("stdout_sha256")
        stderr_sha = run_status.get("stderr_sha256")

        conds = []
        conds.append(cmd == ["python", "input/simulate_packaging_run.py", "--test"])
        conds.append(isinstance(exit_code, int))
        conds.append(isinstance(lines_stdout, int))
        conds.append(isinstance(lines_stderr, int))
        conds.append(rs in ("ok", "failed"))
        conds.append(isinstance(metrics, dict))
        if isinstance(metrics, dict):
            mu = metrics.get("units_total")
            mr = metrics.get("rejects_total")
            muptime = metrics.get("uptime_avg")
            conds.append(all(k in metrics for k in ("units_total", "rejects_total", "uptime_avg")))
            conds.append(isinstance(mu, (int, float)) and isinstance(mr, (int, float)) and isinstance(muptime, (int, float)))
        conds.append((error_summary is None) or isinstance(error_summary, str))
        if rs == "failed":
            conds.append(isinstance(error_summary, str) and len(error_summary.strip()) > 0)
        conds.append(_is_hex_sha256(stdout_sha))
        conds.append(_is_hex_sha256(stderr_sha))

        # Compare line counts with actual logs, if available
        if stdout_text is not None:
            conds.append(lines_stdout == _count_lines(stdout_text))
        if stderr_text is not None:
            conds.append(lines_stderr == _count_lines(stderr_text))

        if all(conds):
            scores["run_status_json_valid"] = 1.0
            run_status_valid = True

    # 7) stdout expected lines
    expected_ok_lines = [
        "OK: shift=A, units=1250, rejects=18, uptime=97.8",
        "OK: shift=B, units=1310, rejects=22, uptime=98.1",
        "OK: shift=C, units=1195, rejects=20, uptime=96.9",
    ]
    if stdout_text is not None:
        actual_lines = [ln.rstrip("\r\n") for ln in stdout_text.splitlines()]
        actual_nonempty = [ln for ln in actual_lines if ln.strip() != ""]
        if actual_nonempty == expected_ok_lines:
            scores["logs_stdout_expected_lines"] = 1.0

    # 8) Metrics match parsed stdout
    if run_status_valid and stdout_text is not None:
        parsed = _parse_ok_metrics_from_text(stdout_text)
        if parsed:
            units_total = sum(item["units"] for item in parsed)
            rejects_total = sum(item["rejects"] for item in parsed)
            uptime_avg = sum(item["uptime"] for item in parsed) / len(parsed)
            m = run_status.get("metrics", {})
            if (
                int(m.get("units_total", -1)) == units_total
                and int(m.get("rejects_total", -1)) == rejects_total
                and _almost_equal(float(m.get("uptime_avg", -1.0)), uptime_avg, tol=1e-6)
            ):
                scores["run_metrics_match_stdout"] = 1.0

    # 9) SHA256 logs match JSON
    if run_status_valid:
        stdout_sha_json = run_status.get("stdout_sha256")
        stderr_sha_json = run_status.get("stderr_sha256")
        stdout_sha_actual = _sha256_file(stdout_log_path)
        stderr_sha_actual = _sha256_file(stderr_log_path)
        if (
            stdout_sha_actual is not None
            and stderr_sha_actual is not None
            and stdout_sha_json
            and stderr_sha_json
            and stdout_sha_actual.lower() == stdout_sha_json.lower()
            and stderr_sha_actual.lower() == stderr_sha_json.lower()
        ):
            scores["sha256_logs_match_json"] = 1.0

    # 10) Daily report consistency
    daily = _load_json(daily_report_json_path)
    if daily and isinstance(daily, dict) and osha_valid and run_status_valid:
        dr_conds = []
        dr_conds.append(daily.get("source_title") == osha.get("source_title"))
        dr_conds.append(daily.get("retrieved_at_iso") == osha.get("retrieved_at_iso"))
        dr_conds.append(daily.get("html_sha256") == osha.get("html_sha256"))
        # counts
        headings = osha.get("headings")
        links = osha.get("links")
        if isinstance(headings, list) and isinstance(links, list):
            dr_conds.append(daily.get("headings_count") == len(headings))
            dr_conds.append(daily.get("links_count") == len(links))
        else:
            dr_conds.append(False)
        # run status and metrics
        dr_conds.append(daily.get("run_status") == run_status.get("run_status"))
        dr_metrics = daily.get("metrics")
        rs_metrics = run_status.get("metrics")
        if isinstance(dr_metrics, dict) and isinstance(rs_metrics, dict):
            dr_conds.append(dr_metrics.get("units_total") == rs_metrics.get("units_total"))
            dr_conds.append(dr_metrics.get("rejects_total") == rs_metrics.get("rejects_total"))
            ua_dr = dr_metrics.get("uptime_avg")
            ua_rs = rs_metrics.get("uptime_avg")
            try:
                dr_conds.append(_almost_equal(float(ua_dr), float(ua_rs), tol=1e-6))
            except Exception:
                dr_conds.append(False)
        else:
            dr_conds.append(False)
        # error_summary and shas
        dr_conds.append(daily.get("error_summary") == run_status.get("error_summary"))
        dr_conds.append(daily.get("stdout_sha256") == run_status.get("stdout_sha256"))
        dr_conds.append(daily.get("stderr_sha256") == run_status.get("stderr_sha256"))
        if all(dr_conds):
            scores["daily_report_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()