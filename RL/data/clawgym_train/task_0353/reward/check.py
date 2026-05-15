import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_ndjson_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    result: List[Dict[str, Any]] = []
    for ln in lines:
        if not ln.strip():
            # skip empty lines in NDJSON
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        result.append(obj)
    return result


def is_iso8601(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    s = value.strip()
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?"
        r"(?:Z|[+\-]\d{2}:\d{2})?$"
    )
    if not pattern.match(s):
        return False
    try:
        if s.endswith("Z"):
            ds = s[:-1] + "+00:00"
        else:
            ds = s
        datetime.fromisoformat(ds)
        return True
    except Exception:
        return False


def parse_channels_yaml_handle(yaml_text: Optional[str]) -> Optional[str]:
    if yaml_text is None:
        return None
    lines = yaml_text.splitlines()
    handles: List[str] = []
    in_channels = False
    for line in lines:
        if re.match(r"^\s*channels\s*:\s*$", line):
            in_channels = True
            continue
        m = re.search(r"handle\s*:\s*['\"]?(@[A-Za-z0-9_\-]+)['\"]?", line)
        if m:
            handles.append(m.group(1))
            if in_channels or len(handles) == 1:
                pass
    if handles:
        return handles[0]
    return None


def extract_kv_from_md(content: str, key: str) -> Optional[str]:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
    for line in content.splitlines():
        m = pattern.match(line)
        if m:
            return m.group(1).strip()
    return None


def parse_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s.strip())
    except Exception:
        return None


def count_stderr_levels(stderr_text: Optional[str]) -> Tuple[int, int]:
    if stderr_text is None:
        return (0, 0)
    errors = 0
    warnings = 0
    for line in stderr_text.splitlines():
        if line.startswith("ERROR"):
            errors += 1
        if line.startswith("WARNING"):
            warnings += 1
    return errors, warnings


def extract_error_warning_counts_from_md(content: str) -> Tuple[Optional[int], Optional[int], bool, bool]:
    has_section = "error_analysis" in content.lower()
    err_match = re.search(r"errors?\s*[:=]\s*(\d+)", content, re.IGNORECASE)
    warn_match = re.search(r"warnings?\s*[:=]\s*(\d+)", content, re.IGNORECASE)
    errors_val = int(err_match.group(1)) if err_match else None
    warnings_val = int(warn_match.group(1)) if warn_match else None
    summary_present = False
    sm = re.search(r"summary\s*[:=]\s*(.+)", content, re.IGNORECASE)
    if sm and sm.group(1).strip():
        summary_present = True
    if not summary_present:
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "error_analysis" in line.lower():
                for j in range(i + 1, min(i + 6, len(lines))):
                    t = lines[j].strip()
                    if t and len(t) >= 8 and (" " in t or "." in t):
                        summary_present = True
                        break
                break
    return errors_val, warnings_val, has_section, summary_present


def collect_processed_ids(proc_json: Dict[str, Any]) -> Optional[List[str]]:
    if not isinstance(proc_json, dict):
        return None
    items = proc_json.get("items")
    if not isinstance(items, list):
        return None
    ids: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            return None
        vid = it.get("id")
        if not isinstance(vid, str):
            return None
        ids.append(vid)
    return ids


def check_canonical_urls(proc_json: Dict[str, Any]) -> Optional[bool]:
    if not isinstance(proc_json, dict):
        return None
    items = proc_json.get("items")
    if not isinstance(items, list):
        return None
    ok = True
    for it in items:
        if not isinstance(it, dict):
            return None
        vid = it.get("id")
        url = it.get("url")
        if not isinstance(vid, str) or not isinstance(url, str):
            return None
        expected = f"https://www.youtube.com/watch?v={vid}"
        if url != expected:
            ok = False
            break
    return ok


def processed_json_structure_valid(proc_json: Dict[str, Any]) -> bool:
    if not isinstance(proc_json, dict):
        return False
    if not isinstance(proc_json.get("channel_handle"), str):
        return False
    fetched_at = proc_json.get("fetched_at")
    if not isinstance(fetched_at, str) or not is_iso8601(fetched_at):
        return False
    items = proc_json.get("items")
    if not isinstance(items, list):
        return False
    for it in items:
        if not isinstance(it, dict):
            return False
        if not isinstance(it.get("id"), str):
            return False
        if not isinstance(it.get("title"), str):
            return False
        url = it.get("url")
        if not isinstance(url, str):
            return False
        up = it.get("upload_date")
        if up is not None and not isinstance(up, str):
            return False
    return True


def has_stderr_head_in_report(report_text: str, stderr_text: Optional[str]) -> bool:
    if stderr_text is None:
        return False
    if "stderr_head" not in report_text.lower():
        return False
    stderr_lines = stderr_text.splitlines()
    head_lines = stderr_lines[:10]
    for hl in head_lines:
        if hl and hl not in report_text:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "logs_stdout_present": 0.0,
        "logs_stderr_present": 0.0,
        "run_summary_core_fields": 0.0,
        "run_summary_error_analysis": 0.0,
        "previous_index_counts_consistent": 0.0,
        "raw_jsonl_valid": 0.0,
        "processed_json_valid": 0.0,
        "ids_alignment_raw_processed": 0.0,
        "canonical_watch_urls": 0.0,
        "success_failure_behavior": 0.0,
    }

    stdout_path = workspace / "logs" / "yt_fetch.stdout"
    stderr_path = workspace / "logs" / "yt_fetch.stderr"
    raw_path = workspace / "out" / "raw" / "videos.jsonl"
    proc_path = workspace / "out" / "processed" / "videos.json"
    report_path = workspace / "reports" / "run_summary.md"
    channels_yaml_path = workspace / "input" / "channels.yaml"
    prev_index_path = workspace / "input" / "previous_index.json"

    stdout_text = read_text_safe(stdout_path)
    stderr_text = read_text_safe(stderr_path)
    if stdout_text is not None:
        scores["logs_stdout_present"] = 1.0
    if stderr_text is not None:
        scores["logs_stderr_present"] = 1.0

    channels_yaml_text = read_text_safe(channels_yaml_path)
    cfg_channel_handle = parse_channels_yaml_handle(channels_yaml_text)
    prev_index = load_json_safe(prev_index_path)
    known_ids_set: Optional[set] = None
    if isinstance(prev_index, dict):
        known = prev_index.get("known_video_ids")
        if isinstance(known, list) and all(isinstance(x, str) for x in known):
            known_ids_set = set(known)

    report_text = read_text_safe(report_path)
    success_status: Optional[bool] = None
    fetched_count_report: Optional[int] = None
    prev_count_report: Optional[int] = None
    overlap_count_report: Optional[int] = None
    potential_new_count_report: Optional[int] = None
    channel_handle_report: Optional[str] = None

    if report_text is not None:
        run_started_at = extract_kv_from_md(report_text, "run_started_at")
        exit_status_val = extract_kv_from_md(report_text, "exit_status")
        channel_handle_val = extract_kv_from_md(report_text, "channel_handle")
        tool_name_val = extract_kv_from_md(report_text, "tool_name")
        tool_version_val = extract_kv_from_md(report_text, "tool_version")

        has_core = True
        if not (isinstance(run_started_at, str) and is_iso8601(run_started_at)):
            has_core = False
        if not (isinstance(channel_handle_val, str) and channel_handle_val.strip()):
            has_core = False
        if not (isinstance(tool_name_val, str) and tool_name_val.strip()):
            has_core = False
        if not (isinstance(tool_version_val, str) and tool_version_val.strip()):
            has_core = False
        if not isinstance(exit_status_val, str):
            has_core = False

        if has_core:
            scores["run_summary_core_fields"] = 1.0

        if isinstance(exit_status_val, str):
            v = exit_status_val.strip().lower()
            if v == "0":
                success_status = True
            else:
                success_status = False

        fetched_count_report = parse_int(extract_kv_from_md(report_text, "fetched_count"))
        prev_count_report = parse_int(extract_kv_from_md(report_text, "previously_known_count"))
        overlap_count_report = parse_int(extract_kv_from_md(report_text, "overlap_count"))
        potential_new_count_report = parse_int(extract_kv_from_md(report_text, "potential_new_count"))
        channel_handle_report = channel_handle_val

        err_c, warn_c, has_err_section, summary_present = extract_error_warning_counts_from_md(report_text)
        actual_err, actual_warn = count_stderr_levels(stderr_text)
        ea_ok = False
        if has_err_section and err_c is not None and warn_c is not None and summary_present:
            if err_c == actual_err and warn_c == actual_warn:
                ea_ok = True
        if ea_ok:
            scores["run_summary_error_analysis"] = 1.0

    raw_exists = raw_path.exists()
    raw_ndjson = parse_ndjson_safe(raw_path) if raw_exists else None
    raw_text = read_text_safe(raw_path) if raw_exists else None
    raw_nonempty = False
    if raw_text is not None and raw_text.strip():
        raw_nonempty = True

    proc_exists = proc_path.exists()
    proc_json = load_json_safe(proc_path) if proc_exists else None

    raw_valid_score = 0.0
    if success_status is True:
        if raw_exists and raw_ndjson is not None:
            fetched_lines = len(raw_ndjson)
            if fetched_count_report is not None and fetched_lines == fetched_count_report:
                raw_valid_score = 1.0
    elif success_status is False:
        if raw_exists and (raw_text is not None) and (raw_text.strip() == ""):
            raw_valid_score = 1.0
    else:
        if raw_exists and raw_ndjson is not None:
            raw_valid_score = 1.0
    scores["raw_jsonl_valid"] = raw_valid_score

    proc_valid_score = 0.0
    if success_status is True:
        if proc_exists and isinstance(proc_json, dict) and processed_json_structure_valid(proc_json):
            proc_valid_score = 1.0
    elif success_status is False:
        if not proc_exists:
            proc_valid_score = 1.0
    else:
        if proc_exists and isinstance(proc_json, dict) and processed_json_structure_valid(proc_json):
            proc_valid_score = 1.0
    scores["processed_json_valid"] = proc_valid_score

    ids_align_score = 0.0
    if success_status is True and proc_exists and isinstance(proc_json, dict) and raw_text is not None:
        proc_ids = collect_processed_ids(proc_json)
        if isinstance(proc_ids, list):
            all_in_raw = all((pid in raw_text) for pid in proc_ids)
            ids_length_equal = True
            if fetched_count_report is not None:
                ids_length_equal = len(proc_ids) == fetched_count_report
            else:
                if raw_ndjson is not None:
                    ids_length_equal = len(proc_ids) == len(raw_ndjson)
            if all_in_raw and ids_length_equal:
                ids_align_score = 1.0
    elif success_status is False:
        ids_align_score = 1.0
    scores["ids_alignment_raw_processed"] = ids_align_score

    canonical_score = 0.0
    if success_status is True and proc_exists and isinstance(proc_json, dict):
        canon_ok = check_canonical_urls(proc_json)
        if canon_ok is True:
            canonical_score = 1.0
    elif success_status is False:
        canonical_score = 1.0
    scores["canonical_watch_urls"] = canonical_score

    prev_counts_score = 0.0
    if report_text is not None and known_ids_set is not None:
        ok = True
        if prev_count_report is None or prev_count_report != len(known_ids_set):
            ok = False
        fetched_ids: List[str] = []
        if success_status is True and isinstance(proc_json, dict):
            ids = collect_processed_ids(proc_json)
            if isinstance(ids, list):
                fetched_ids = ids
        overlap = len(set(fetched_ids) & known_ids_set)
        potential_new = len(fetched_ids) - overlap
        if fetched_count_report is not None and fetched_count_report != len(fetched_ids):
            ok = False
        if overlap_count_report is None or overlap_count_report != overlap:
            ok = False
        if potential_new_count_report is None or potential_new_count_report != potential_new:
            ok = False
        sample_new_line = extract_kv_from_md(report_text, "sample_new_ids")
        if potential_new > 0:
            if sample_new_line is None:
                ok = False
            else:
                sample_ids = re.findall(r"[A-Za-z0-9_\-]{11}", sample_new_line)
                diff_set = list(set(fetched_ids) - known_ids_set)
                if not sample_ids or len(sample_ids) > 3:
                    ok = False
                elif not set(sample_ids).issubset(set(diff_set)):
                    ok = False
        else:
            if sample_new_line is not None and sample_new_line.strip():
                ok = False
        if ok:
            prev_counts_score = 1.0
    scores["previous_index_counts_consistent"] = prev_counts_score

    sf_score = 0.0
    if success_status is True:
        if proc_exists and raw_exists and raw_nonempty:
            sf_score = 1.0
    elif success_status is False:
        cond_proc_absent = not proc_exists
        cond_raw_empty = raw_exists and (read_text_safe(raw_path) is not None) and not read_text_safe(raw_path).strip()
        cond_stderr_head = report_text is not None and has_stderr_head_in_report(report_text, stderr_text)
        if cond_proc_absent and cond_raw_empty and cond_stderr_head:
            sf_score = 1.0
    else:
        sf_score = 0.0
    scores["success_failure_behavior"] = sf_score

    if cfg_channel_handle and proc_exists and isinstance(proc_json, dict):
        ph = proc_json.get("channel_handle")
        if isinstance(ph, str) and channel_handle_report and (ph != cfg_channel_handle or channel_handle_report != cfg_channel_handle):
            scores["run_summary_core_fields"] = 0.0
            scores["processed_json_valid"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()