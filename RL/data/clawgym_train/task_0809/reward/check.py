import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple


ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Tuple[Optional[dict], Optional[str]]:
    txt = _read_text(p)
    if txt is None:
        return None, "cannot_read"
    try:
        return json.loads(txt), None
    except Exception as e:
        return None, f"parse_error:{e}"


def _as_float(x) -> bool:
    return isinstance(x, (int, float))


def _validate_snapshot_structure(snap: dict) -> bool:
    required_keys = [
        'timestamp','os_name','kernel','hostname','cpu_model','logical_cores',
        'mem_total_mb','mem_available_mb','load_avg_1m','load_avg_5m','load_avg_15m',
        'fs_path','fs_total_gb','fs_used_gb','fs_used_percent','top_processes'
    ]
    for k in required_keys:
        if k not in snap:
            return False

    if not isinstance(snap['timestamp'], str) or not ISO_RE.match(snap['timestamp']):
        return False

    for k in ['os_name','kernel','hostname','cpu_model','fs_path']:
        if not isinstance(snap[k], str):
            return False

    if snap['fs_path'] != '.':
        return False

    if not isinstance(snap['logical_cores'], int) or snap['logical_cores'] < 1:
        return False

    if not isinstance(snap['mem_total_mb'], int) or snap['mem_total_mb'] <= 0:
        return False
    if not isinstance(snap['mem_available_mb'], int) or snap['mem_available_mb'] < 0 or snap['mem_available_mb'] > snap['mem_total_mb']:
        return False

    for k in ['load_avg_1m','load_avg_5m','load_avg_15m','fs_total_gb','fs_used_gb','fs_used_percent']:
        if not _as_float(snap[k]):
            return False
    if snap['fs_total_gb'] <= 0:
        return False
    if snap['fs_used_gb'] < 0:
        return False
    if not (0 <= snap['fs_used_percent'] <= 100):
        return False

    tp = snap['top_processes']
    if not isinstance(tp, list) or len(tp) != 3:
        return False
    for item in tp:
        if not isinstance(item, dict):
            return False
        for k in ['pid','command','rss_mb']:
            if k not in item:
                return False
        if not isinstance(item['pid'], int) or item['pid'] <= 0:
            return False
        if not isinstance(item['command'], str) or not item['command']:
            return False
        if not _as_float(item['rss_mb']) or item['rss_mb'] < 0:
            return False

    return True


def _extract_notes_section(report_txt: str) -> Optional[str]:
    marker = "## Notes on Focus"
    idx = report_txt.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    rest = report_txt[start:]
    next_idx = rest.find("\n## ")
    if next_idx == -1:
        section = rest.strip()
    else:
        section = rest[:next_idx].strip()
    return section


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    cleaned = text.replace("\n", " ").strip()
    parts = re.split(r"[.!?]+", cleaned)
    sentences = [p.strip() for p in parts if p.strip()]
    return len(sentences)


def _run_validator(workspace: Path, snap: Path, report: Path, log: Path) -> bool:
    test_script = workspace / "tests" / "validate_outputs.py"
    if not test_script.exists():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(test_script), str(snap), str(report), str(log)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except Exception:
        return False
    return proc.returncode == 0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    snap_path = workspace / "output" / "system_snapshot.json"
    report_path = workspace / "output" / "system_status_report.md"
    log_path = workspace / "logs" / "study_routine_log.md"

    scores = {
        "snapshot_json_present": 0.0,
        "snapshot_json_valid_structure": 0.0,
        "report_md_present": 0.0,
        "report_sections_present": 0.0,
        "report_values_consistent_with_json": 0.0,
        "notes_on_focus_2_to_3_sentences": 0.0,
        "log_updated_correctly": 0.0,
        "status_line_present_and_nonempty": 0.0,
        "validator_passed": 0.0,
    }

    # Snapshot presence and structure
    snap_obj, _ = _load_json(snap_path)
    if snap_obj is not None:
        scores["snapshot_json_present"] = 1.0
        if _validate_snapshot_structure(snap_obj):
            scores["snapshot_json_valid_structure"] = 1.0

    # Report presence and sections
    report_txt = _read_text(report_path)
    if report_txt is not None:
        scores["report_md_present"] = 1.0
        required_headers = [
            "System Status Report",
            "## System Overview",
            "## CPU",
            "## Memory and Load",
            "## Filesystem",
            "## Top processes by memory",
            "## Notes on Focus",
        ]
        if all(h in report_txt for h in required_headers):
            scores["report_sections_present"] = 1.0

    # Report values consistent with JSON
    if snap_obj is not None and isinstance(report_txt, str) and scores["snapshot_json_valid_structure"] == 1.0:
        date_str = snap_obj["timestamp"][:10]
        cores = str(snap_obj["logical_cores"])
        mem_total = str(snap_obj["mem_total_mb"])
        fs_used_pct_int = str(int(round(float(snap_obj["fs_used_percent"]))))
        cpu_model = snap_obj["cpu_model"]
        conds = [
            date_str in report_txt,
            cores in report_txt,
            mem_total in report_txt,
            fs_used_pct_int in report_txt,
            cpu_model in report_txt,
        ]
        if all(conds):
            scores["report_values_consistent_with_json"] = 1.0

    # Notes section sentence count
    if isinstance(report_txt, str):
        notes = _extract_notes_section(report_txt)
        if notes is not None:
            sent_count = _count_sentences(notes)
            if 2 <= sent_count <= 3:
                scores["notes_on_focus_2_to_3_sentences"] = 1.0

    # Log updated correctly and status line present
    log_txt = _read_text(log_path)
    if log_txt is not None and snap_obj is not None and scores["snapshot_json_valid_structure"] == 1.0:
        begin = "<!-- BEGIN LAST CHECK -->"
        end = "<!-- END LAST CHECK -->"
        if begin in log_txt and end in log_txt:
            seg = log_txt.split(begin, 1)[1].split(end, 1)[0]
            placeholders_ok = all(x not in seg for x in ["2023-11-15", "old_report.md", "old_snapshot.json"])
            date_str = snap_obj["timestamp"][:10]
            has_date = f"Date: {date_str}" in seg
            has_report = "Report: output/system_status_report.md" in seg
            has_snapshot = "Snapshot: output/system_snapshot.json" in seg
            if placeholders_ok and has_date and has_report and has_snapshot:
                scores["log_updated_correctly"] = 1.0
            status_line_match = re.search(r"(?mi)^\s*Status:\s+(.+)$", seg)
            if status_line_match:
                content = status_line_match.group(1).strip()
                if len(content) > 0:
                    scores["status_line_present_and_nonempty"] = 1.0

    # Validator execution result
    if snap_path.exists() and report_path.exists() and log_path.exists():
        if _run_validator(workspace, snap_path, report_path, log_path):
            scores["validator_passed"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()