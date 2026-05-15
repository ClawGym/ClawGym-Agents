import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime
import csv
import re


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    s2 = s
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _compute_text_stats(b: bytes) -> dict:
    size = len(b)
    try:
        txt = b.decode("utf-8", errors="replace")
    except Exception:
        txt = ""
    lines = txt.splitlines()
    line_count = len(lines)
    word_count = len(txt.split())
    sha = hashlib.sha256(b).hexdigest()
    return {
        "file_size_bytes": size,
        "line_count": line_count,
        "word_count": word_count,
        "sha256_hex": sha,
    }


def _parse_summary_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, "read_error"
    if not rows:
        return None, "empty"
    header = rows[0]
    if header != ["metric", "value"]:
        return None, "bad_header"
    metrics = {}
    for r in rows[1:]:
        if len(r) != 2:
            return None, "bad_row"
        metrics[r[0]] = r[1]
    return metrics, None


def _contains_direct_url(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return bool(re.search(r'\b(?:https?|ftp)://', s))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "last_run_exists": 0.0,
        "last_run_fields_valid": 0.0,
        "success_conditions_respected": 0.0,
        "derived_outputs_presence_correct": 0.0,
        "metrics_json_consistency": 0.0,
        "summary_csv_consistency": 0.0,
        "no_direct_url_in_log": 0.0,
    }

    trigger_path = workspace / "input" / "requests" / "rfc1149_request.json"
    last_run_path = workspace / "output" / "logs" / "last_run.json"
    raw_path = workspace / "output" / "raw" / "rfc1149.txt"
    metrics_json_path = workspace / "output" / "derived" / "metrics.json"
    summary_csv_path = workspace / "output" / "derived" / "summary.csv"

    expected_request = _safe_load_json(trigger_path)
    expected_request_id = None
    if isinstance(expected_request, dict):
        expected_request_id = expected_request.get("request_id")

    last_run = _safe_load_json(last_run_path)
    if isinstance(last_run, dict):
        scores["last_run_exists"] = 1.0

    fields_ok = False
    if isinstance(last_run, dict):
        triggered_by = last_run.get("triggered_by")
        request_id = last_run.get("request_id")
        command = last_run.get("command")
        exit_code = last_run.get("exit_code")
        stderr_excerpt = last_run.get("stderr_excerpt")
        status = last_run.get("status")
        download_time_iso = last_run.get("download_time_iso")

        command_nonempty = isinstance(command, str) and len(command.strip()) > 0
        stderr_ok = isinstance(stderr_excerpt, str) and len(stderr_excerpt) <= 200
        basic_types_ok = (
            isinstance(triggered_by, str)
            and command_nonempty
            and stderr_ok
            and isinstance(status, str)
            and isinstance(exit_code, int)
            and _is_iso8601_like(download_time_iso)
        )
        triggered_ok = triggered_by == "input/requests/rfc1149_request.json"
        if expected_request_id is not None:
            request_id_ok = request_id == expected_request_id
        else:
            request_id_ok = isinstance(request_id, str) and len(request_id.strip()) > 0
        status_ok = status in {"ok", "error"}
        fields_ok = basic_types_ok and triggered_ok and request_id_ok and status_ok

    scores["last_run_fields_valid"] = 1.0 if fields_ok else 0.0

    success_ok = False
    if isinstance(last_run, dict):
        status = last_run.get("status")
        exit_code = last_run.get("exit_code")
        raw_bytes = _safe_read_bytes(raw_path)
        raw_exists_nonempty = raw_bytes is not None and len(raw_bytes) > 0
        if status == "ok":
            success_ok = (exit_code == 0) and raw_exists_nonempty
        elif status == "error":
            success_ok = (exit_code != 0) or (not raw_exists_nonempty)
        else:
            success_ok = False
    scores["success_conditions_respected"] = 1.0 if success_ok else 0.0

    derived_presence_ok = False
    if isinstance(last_run, dict):
        status = last_run.get("status")
        metrics_exists = metrics_json_path.exists()
        summary_exists = summary_csv_path.exists()
        if status == "ok":
            derived_presence_ok = metrics_exists and summary_exists
        elif status == "error":
            derived_presence_ok = (not metrics_exists) and (not summary_exists)
        else:
            derived_presence_ok = False
    scores["derived_outputs_presence_correct"] = 1.0 if derived_presence_ok else 0.0

    metrics_ok = False
    if isinstance(last_run, dict) and last_run.get("status") == "ok":
        metrics = _safe_load_json(metrics_json_path)
        raw_bytes = _safe_read_bytes(raw_path)
        if isinstance(metrics, dict) and raw_bytes is not None:
            computed = _compute_text_stats(raw_bytes)
            source_ok = metrics.get("source") == "IETF RFC 1149 (plain text)"
            if expected_request_id is not None:
                req_id_ok = metrics.get("request_id") == expected_request_id
            else:
                req_id_ok = isinstance(metrics.get("request_id"), str) and len(str(metrics.get("request_id")).strip()) > 0
            dl_time_ok = metrics.get("download_time_iso") == last_run.get("download_time_iso")
            try:
                fsb_ok = int(metrics.get("file_size_bytes")) == computed["file_size_bytes"]
                lc_ok = int(metrics.get("line_count")) == computed["line_count"]
                wc_ok = int(metrics.get("word_count")) == computed["word_count"]
            except Exception:
                fsb_ok = lc_ok = wc_ok = False
            sha_ok = isinstance(metrics.get("sha256_hex"), str) and metrics.get("sha256_hex") == computed["sha256_hex"]
            metrics_ok = source_ok and req_id_ok and dl_time_ok and fsb_ok and lc_ok and wc_ok and sha_ok
        else:
            metrics_ok = False
    elif isinstance(last_run, dict) and last_run.get("status") == "error":
        metrics_ok = not metrics_json_path.exists()
    scores["metrics_json_consistency"] = 1.0 if metrics_ok else 0.0

    summary_ok = False
    if isinstance(last_run, dict) and last_run.get("status") == "ok":
        raw_bytes = _safe_read_bytes(raw_path)
        parsed, err = _parse_summary_csv(summary_csv_path)
        if (raw_bytes is not None) and (parsed is not None) and err is None:
            computed = _compute_text_stats(raw_bytes)
            try:
                fsb_val = int(parsed.get("file_size_bytes")) if "file_size_bytes" in parsed else None
                lc_val = int(parsed.get("line_count")) if "line_count" in parsed else None
                wc_val = int(parsed.get("word_count")) if "word_count" in parsed else None
            except Exception:
                fsb_val = lc_val = wc_val = None
            summary_ok = (
                fsb_val == computed["file_size_bytes"]
                and lc_val == computed["line_count"]
                and wc_val == computed["word_count"]
            )
        else:
            summary_ok = False
    elif isinstance(last_run, dict) and last_run.get("status") == "error":
        summary_ok = not summary_csv_path.exists()
    scores["summary_csv_consistency"] = 1.0 if summary_ok else 0.0

    no_url_ok = False
    if isinstance(last_run, dict):
        cmd = last_run.get("command")
        stderr_excerpt = last_run.get("stderr_excerpt")
        cmd_ok = isinstance(cmd, str) and len(cmd.strip()) > 0
        placeholders = {"placeholder", "n/a", "na", "none", "noop", "test", "todo"}
        not_placeholder = cmd_ok and (cmd.strip().lower() not in placeholders)
        no_direct_url_cmd = not _contains_direct_url(cmd if isinstance(cmd, str) else "")
        no_direct_url_stderr = not _contains_direct_url(stderr_excerpt if isinstance(stderr_excerpt, str) else "")
        no_url_ok = not_placeholder and no_direct_url_cmd and no_direct_url_stderr
    scores["no_direct_url_in_log"] = 1.0 if no_url_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()