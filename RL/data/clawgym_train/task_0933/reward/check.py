import json
import sys
import re
import os
from pathlib import Path
from datetime import date
import xml.etree.ElementTree as ET
import shlex
from urllib.parse import urlparse


ALLOWED_STATUSES = {"ok", "http_error", "network_error", "parse_error", "skipped_political"}
ALLOWED_ERROR_TYPES = {"dns_error", "timeout", "http_status_not_ok", "parse_failure"}


def _read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_iso_timestamp(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T", s))


def _within_workspace(p: Path, workspace: Path) -> bool:
    try:
        p.resolve().relative_to(workspace.resolve())
        return True
    except Exception:
        return False


def _find_runner_from_tokens(tokens, workspace: Path):
    preferred_exts = {".py", ".sh", ".bat", ".cmd", ".exe"}
    candidates = []
    for tok in tokens:
        if tok in {">", ">>", "2>&1", "2>", "1>", "&"}:
            continue
        cleaned = tok.strip()
        if not cleaned:
            continue
        p = Path(cleaned)
        if not p.is_absolute():
            p = (workspace / cleaned).resolve()
        try:
            p = p.resolve()
        except Exception:
            continue
        if p.exists() and p.is_file() and _within_workspace(p, workspace):
            candidates.append(p)
    for c in candidates:
        if c.suffix.lower() in preferred_exts:
            return c
    if candidates:
        return candidates[-1]
    return None


def _parse_cron_line(cron_text: str):
    lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return False, False, None
    line = lines[0].strip()
    parts = line.split()
    if len(parts) < 6:
        return False, False, None
    minute, hour = parts[0], parts[1]
    has_time = (minute == "30" and hour in {"7", "07"})
    command_str = " ".join(parts[5:])
    has_redirect = ("output/logs/cron.log" in command_str) and ("2>&1" in command_str) and (">>" in command_str)
    return has_time, has_redirect, command_str


def _extract_tokens_from_command(command_str: str):
    try:
        return shlex.split(command_str)
    except Exception:
        return command_str.split()


def _parse_windows_task_for_runner_and_time(xml_path: Path, workspace: Path):
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception:
        return None, False

    ns = {}
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0].strip("{")
        ns["ns"] = ns_uri

    cmd_texts = []
    arg_texts = []
    paths = [
        ".//ns:Actions/ns:Exec/ns:Command",
        ".//Actions/Exec/Command",
    ]
    for pth in paths:
        for node in root.findall(pth, ns):
            if node is not None and node.text:
                cmd_texts.append(node.text.strip())

    arg_paths = [
        ".//ns:Actions/ns:Exec/ns:Arguments",
        ".//Actions/Exec/Arguments",
    ]
    for pth in arg_paths:
        for node in root.findall(pth, ns):
            if node is not None and node.text:
                arg_texts.append(node.text.strip())

    tokens = []
    for t in cmd_texts:
        tokens.extend(_extract_tokens_from_command(t))
    for a in arg_texts:
        tokens.extend(_extract_tokens_from_command(a))

    runner_path = _find_runner_from_tokens(tokens, workspace)

    time_strs = []
    sb_paths = [
        ".//ns:Triggers//ns:StartBoundary",
        ".//Triggers//StartBoundary",
    ]
    for pth in sb_paths:
        for node in root.findall(pth, ns):
            if node is not None and node.text:
                time_strs.append(node.text)

    has_0730 = False
    for ts in time_strs:
        if re.search(r"T0?7:30", ts):
            has_0730 = True
            break

    return runner_path, has_0730


def _parse_tsv_last_line(tsv_path: Path):
    try:
        text = tsv_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    cols = last.split("\t")
    if len(cols) != 8:
        return None
    rec = {
        "timestamp_iso": cols[0],
        "status": cols[1],
        "http_status": cols[2],
        "exit_code": cols[3],
        "error_type": cols[4],
        "message": cols[5],
        "html_path": cols[6],
        "json_path": cols[7],
    }
    return rec


def _validate_json_summary(data: dict, expected_date_str: str) -> bool:
    if not isinstance(data, dict):
        return False
    required_keys = {
        "date",
        "source_name",
        "source_page",
        "page_title",
        "status",
        "http_status",
        "image_urls",
        "caption_snippet",
        "error_type",
        "error_message",
    }
    if set(data.keys()) != required_keys:
        return False
    if data.get("date") != expected_date_str:
        return False
    if data.get("source_name") != "NASA APOD":
        return False
    if data.get("source_page") is not None and not isinstance(data.get("source_page"), str):
        return False
    if data.get("page_title") is not None and not isinstance(data.get("page_title"), str):
        return False
    status = data.get("status")
    if status not in ALLOWED_STATUSES:
        return False
    hs = data.get("http_status")
    if hs is not None and not isinstance(hs, int):
        return False
    if not isinstance(data.get("image_urls"), list):
        return False
    if any((not isinstance(u, str)) for u in data.get("image_urls")):
        return False
    cs = data.get("caption_snippet")
    if cs is not None and not isinstance(cs, str):
        return False
    et = data.get("error_type")
    em = data.get("error_message")
    if status in {"ok", "skipped_political"}:
        if et is not None:
            return False
        if em is not None:
            return False
    else:
        if et not in ALLOWED_ERROR_TYPES:
            return False
        if not isinstance(em, str) or not em.strip():
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    today_str = date.today().isoformat()
    html_path = workspace / f"output/raw/apod-{today_str}.html"
    json_path = workspace / f"output/summaries/apod-{today_str}.json"
    run_log_path = workspace / "output/logs/run.log"
    cron_path = workspace / "output/schedule/cron_entry.txt"
    windows_xml_path = workspace / "output/schedule/windows_task.xml"
    last_run_path = workspace / "output/last_run.json"

    scores = {
        "cron_entry_exists_single_line": 0.0,
        "cron_entry_time_and_redirect": 0.0,
        "windows_task_xml_exists": 0.0,
        "windows_task_time_0730": 0.0,
        "runner_path_consistent_in_schedules": 0.0,
        "today_html_file_present": 0.0,
        "today_json_summary_valid": 0.0,
        "source_page_nasa_domain": 0.0,
        "image_urls_are_absolute": 0.0,
        "caption_snippet_max_length": 0.0,
        "skipped_political_has_empty_images": 0.0,
        "run_log_exists_and_columns": 0.0,
        "run_log_last_line_matches_files": 0.0,
        "exit_code_policy_enforced": 0.0,
        "last_run_json_consistency": 0.0,
    }

    if cron_path.exists() and cron_path.is_file():
        cron_text = _read_text_safe(cron_path)
        if cron_text is not None:
            content_lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if len(content_lines) == 1:
                scores["cron_entry_exists_single_line"] = 1.0
            has_time, has_redirect, command_str = _parse_cron_line(cron_text)
            if has_time and has_redirect and command_str:
                scores["cron_entry_time_and_redirect"] = 1.0

    if windows_xml_path.exists() and windows_xml_path.is_file():
        scores["windows_task_xml_exists"] = 1.0
        runner_from_windows, windows_has_time = _parse_windows_task_for_runner_and_time(windows_xml_path, workspace)
        if windows_has_time:
            scores["windows_task_time_0730"] = 1.0
    else:
        runner_from_windows = None

    runner_from_cron = None
    if cron_path.exists():
        cron_text = _read_text_safe(cron_path)
        if cron_text:
            _, _, command_str = _parse_cron_line(cron_text)
            if command_str:
                tokens = _extract_tokens_from_command(command_str)
                runner_from_cron = _find_runner_from_tokens(tokens, workspace)

    if runner_from_cron is not None and runner_from_windows is not None:
        try:
            r1 = runner_from_cron.resolve()
            r2 = runner_from_windows.resolve()
            if _within_workspace(r1, workspace) and _within_workspace(r2, workspace) and r1 == r2 and r1.exists():
                scores["runner_path_consistent_in_schedules"] = 1.0
        except Exception:
            pass

    if html_path.exists() and html_path.is_file():
        try:
            if html_path.stat().st_size > 0:
                scores["today_html_file_present"] = 1.0
        except Exception:
            pass

    summary = None
    if json_path.exists() and json_path.is_file():
        summary = _load_json_safe(json_path)
        if summary is not None and _validate_json_summary(summary, today_str):
            scores["today_json_summary_valid"] = 1.0

            sp = summary.get("source_page")
            if isinstance(sp, str):
                try:
                    parsed = urlparse(sp)
                    if parsed.scheme in {"http", "https"} and "nasa.gov" in (parsed.netloc or "").lower():
                        scores["source_page_nasa_domain"] = 1.0
                except Exception:
                    pass

            imgs = summary.get("image_urls", [])
            if isinstance(imgs, list) and all(isinstance(u, str) for u in imgs):
                all_abs = True
                for u in imgs:
                    pu = urlparse(u)
                    if pu.scheme not in {"http", "https"} or not pu.netloc:
                        all_abs = False
                        break
                if all_abs:
                    scores["image_urls_are_absolute"] = 1.0

            cs = summary.get("caption_snippet")
            if cs is None or (isinstance(cs, str) and len(cs) <= 200):
                scores["caption_snippet_max_length"] = 1.0

            if summary.get("status") == "skipped_political":
                if isinstance(imgs, list) and len(imgs) == 0:
                    scores["skipped_political_has_empty_images"] = 1.0
            else:
                scores["skipped_political_has_empty_images"] = 1.0

    log_rec = None
    if run_log_path.exists() and run_log_path.is_file():
        log_rec = _parse_tsv_last_line(run_log_path)
        if log_rec is not None:
            ts_ok = _is_iso_timestamp(log_rec["timestamp_iso"])
            status_ok = log_rec["status"] in ALLOWED_STATUSES
            http_col = log_rec["http_status"]
            http_ok = True
            if http_col.strip().lower() == "null" or http_col.strip() == "":
                http_ok = True
            else:
                try:
                    int(http_col.strip())
                    http_ok = True
                except Exception:
                    http_ok = False
            try:
                int(log_rec["exit_code"])
                exit_ok = True
            except Exception:
                exit_ok = False
            html_p = workspace / log_rec["html_path"]
            json_p = workspace / log_rec["json_path"]
            paths_ok = html_p.exists() and json_p.exists()
            if ts_ok and status_ok and http_ok and exit_ok and paths_ok:
                scores["run_log_exists_and_columns"] = 1.0

            expected_html_rel = f"output/raw/apod-{today_str}.html"
            expected_json_rel = f"output/summaries/apod-{today_str}.json"
            if log_rec["html_path"] == expected_html_rel and log_rec["json_path"] == expected_json_rel:
                if summary is None or log_rec["status"] == summary.get("status"):
                    scores["run_log_last_line_matches_files"] = 1.0

            try:
                exit_code_val = int(log_rec["exit_code"])
                if log_rec["status"] in {"ok", "skipped_political"}:
                    if exit_code_val == 0:
                        scores["exit_code_policy_enforced"] = 1.0
                else:
                    if exit_code_val != 0:
                        scores["exit_code_policy_enforced"] = 1.0
            except Exception:
                pass

    if last_run_path.exists() and last_run_path.is_file():
        lr = _load_json_safe(last_run_path)
        if isinstance(lr, dict):
            fields_ok = all(k in lr for k in ["timestamp_iso", "status", "html_path", "json_path", "log_path"])
            ts_ok = isinstance(lr.get("timestamp_iso"), str) and _is_iso_timestamp(lr.get("timestamp_iso"))
            st_ok = lr.get("status") in ALLOWED_STATUSES
            html_ok = isinstance(lr.get("html_path"), str) and (workspace / lr.get("html_path")).exists()
            json_ok = isinstance(lr.get("json_path"), str) and (workspace / lr.get("json_path")).exists()
            log_ok = lr.get("log_path") == "output/logs/run.log" and (workspace / "output/logs/run.log").exists()
            paths_match_today = (
                lr.get("html_path") == f"output/raw/apod-{today_str}.html" and
                lr.get("json_path") == f"output/summaries/apod-{today_str}.json"
            )
            status_matches_summary = True
            if summary is not None:
                status_matches_summary = (lr.get("status") == summary.get("status"))
            if fields_ok and ts_ok and st_ok and html_ok and json_ok and log_ok and paths_match_today and status_matches_summary:
                scores["last_run_json_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()