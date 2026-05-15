import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ALLOWED_ISSUE_TYPES = {"threshold_breach", "data_issue", "runtime_error", "none"}
REQUIRED_FIELDS = ["check_name", "script_path", "exit_code", "status", "issue_type", "stdout", "stderr"]


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _discover_scripts(health_checks_dir: Path) -> List[Path]:
    if not health_checks_dir.exists() or not health_checks_dir.is_dir():
        return []
    return sorted([p for p in health_checks_dir.iterdir() if p.is_file() and p.suffix == ".py"])


def _run_script(script_path: Path, cwd: Path, timeout: float = 10.0) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"TimeoutExpired: {e}"
    except Exception as e:
        return 1, "", f"RunnerError: {e}"


def _derive_status(exit_code: int, stdout: str) -> str:
    if exit_code == 0 and stdout.startswith("OK:"):
        return "passed"
    return "failed"


def _contains_any(hay: str, needles: List[str], case_insensitive: bool = True) -> bool:
    if case_insensitive:
        hay_low = hay.lower()
        for n in needles:
            if n.lower() in hay_low:
                return True
        return False
    else:
        return any(n in hay for n in needles)


def _has_traceback(stderr: str) -> bool:
    for line in stderr.splitlines():
        if line.strip().startswith("Traceback (most recent call last):"):
            return True
    return False


def _derive_issue_type(stdout: str, stderr: str, status: str) -> str:
    text_all = f"{stdout}\n{stderr}"
    if _contains_any(text_all, ["REORDER NEEDED", "below herd average threshold", "THRESHOLD"]):
        return "threshold_breach"
    if _contains_any(text_all, ["DATA ERROR", "missing input file"]):
        return "data_issue"
    if _has_traceback(stderr):
        return "runtime_error"
    if status == "passed":
        return "none"
    return "runtime_error"


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        datetime.fromisoformat(v)
        return True
    except Exception:
        return False


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.rstrip("\n")
    return ""


def _get_error_alert_line(stdout: str, stderr: str) -> str:
    for src in (stderr, stdout):
        for line in src.splitlines():
            ls = line.strip()
            if not ls:
                continue
            if _contains_any(ls, ["DATA ERROR", "missing input file"]) or _has_traceback(ls):
                return line
    for src in (stdout, stderr):
        for line in src.splitlines():
            ls = line.strip()
            if not ls:
                continue
            if _contains_any(ls, ["REORDER NEEDED", "below herd average threshold", "THRESHOLD"]):
                return line
    cand = _first_nonempty_line(stderr)
    if cand:
        return cand
    cand = _first_nonempty_line(stdout)
    return cand


def _extract_section(text: str, header: str, other_headers: List[str]) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(header.lower()):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        for oh in other_headers:
            if lines[j].strip().lower().startswith(oh.lower()):
                end_idx = j
                break
        if end_idx != len(lines):
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _parse_table_rows(section_text: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    lines = [ln for ln in section_text.splitlines() if ln.strip()]
    header_idx = None
    for i, ln in enumerate(lines):
        if "check" in ln.lower() and "status" in ln.lower() and "next action" in ln.lower():
            header_idx = i
            break
    if header_idx is None:
        return rows
    i = header_idx + 1
    if i < len(lines) and re.fullmatch(r"\s*\|?\s*-+\s*\|\s*-+\s*\|\s*-+\s*\|?\s*", lines[i]):
        i += 1
    for ln in lines[i:]:
        if "|" not in ln:
            continue
        parts = [p.strip() for p in ln.split("|")]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) != 3:
            continue
        check, status, action = parts
        rows.append((check, status.lower(), action))
    return rows


def _extract_numbers_in_overview(overview_text: str) -> Tuple[Optional[int], Optional[int]]:
    text = overview_text
    passed = None
    failed = None
    m = re.search(r"(\d+)\s+passed", text, flags=re.IGNORECASE)
    if m:
        try:
            passed = int(m.group(1))
        except Exception:
            passed = None
    if passed is None:
        m = re.search(r"passed\s*[:\-]\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            try:
                passed = int(m.group(1))
            except Exception:
                passed = None
    m = re.search(r"(\d+)\s+failed", text, flags=re.IGNORECASE)
    if m:
        try:
            failed = int(m.group(1))
        except Exception:
            failed = None
    if failed is None:
        m = re.search(r"failed\s*[:\-]\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            try:
                failed = int(m.group(1))
            except Exception:
                failed = None
    return passed, failed


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_exists": 0.0,
        "summary_json_valid": 0.0,
        "checks_count_matches_discovery": 0.0,
        "json_fields_complete": 0.0,
        "check_names_match_files": 0.0,
        "script_paths_resolve": 0.0,
        "status_classification_rule_applied": 0.0,
        "issue_type_rule_applied": 0.0,
        "exit_codes_match_recomputed": 0.0,
        "logs_exist_all_checks": 0.0,
        "logs_content_match_json": 0.0,
        "failed_checks_have_logs": 0.0,
        "generated_at_is_iso8601": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_overview_counts_correct": 0.0,
        "meeting_notes_table_covers_all_checks": 0.0,
        "meeting_notes_action_items_for_failed_checks": 0.0,
    }

    health_checks_dir = workspace / "project" / "health_checks"
    discovered_scripts = _discover_scripts(health_checks_dir)
    discovered_map = {p.stem: p for p in discovered_scripts}

    out_dir = workspace / "out" / "ci"
    summary_path = out_dir / "summary.json"
    logs_dir = out_dir / "logs"
    notes_path = out_dir / "meeting_notes.md"

    summary = _load_json_safe(summary_path)
    if summary is None:
        return scores
    scores["summary_exists"] = 1.0
    if isinstance(summary, dict):
        scores["summary_json_valid"] = 1.0

    checks = summary.get("checks")
    generated_at = summary.get("generated_at")

    if isinstance(generated_at, str) and _is_iso8601(generated_at):
        scores["generated_at_is_iso8601"] = 1.0

    if not isinstance(checks, list):
        return scores

    if len(checks) == len(discovered_scripts):
        scores["checks_count_matches_discovery"] = 1.0

    fields_ok = True
    names_ok = True
    names_set = set()
    paths_resolve_ok = True
    status_rule_ok = True
    issue_rule_ok = True
    logs_exist_ok = True
    logs_content_ok = True
    failed_logs_ok = True
    script_exit_match_ok = True

    recomputed_results: Dict[str, Tuple[int, str, str, str, str]] = {}
    for name, path in discovered_map.items():
        rc, out, err = _run_script(path, cwd=workspace)
        status = _derive_status(rc, out)
        issue = _derive_issue_type(out, err, status)
        recomputed_results[name] = (rc, out, err, status, issue)

    for entry in checks:
        if not isinstance(entry, dict):
            fields_ok = False
            continue
        for f in REQUIRED_FIELDS:
            if f not in entry:
                fields_ok = False
        if not isinstance(entry.get("check_name"), str):
            fields_ok = False
        if not isinstance(entry.get("script_path"), str):
            fields_ok = False
        if not isinstance(entry.get("exit_code"), int):
            fields_ok = False
        if not isinstance(entry.get("status"), str) or entry.get("status") not in {"passed", "failed"}:
            fields_ok = False
        if not isinstance(entry.get("issue_type"), str) or entry.get("issue_type") not in ALLOWED_ISSUE_TYPES:
            fields_ok = False
        if not isinstance(entry.get("stdout"), str):
            fields_ok = False
        if not isinstance(entry.get("stderr"), str):
            fields_ok = False
        if not fields_ok:
            continue

        check_name = entry["check_name"]
        names_set.add(check_name)
        if check_name not in discovered_map:
            names_ok = False

        spath_str = entry["script_path"]
        try:
            spath = Path(spath_str)
            if not spath.is_absolute():
                spath = (workspace / spath).resolve()
            expected = discovered_map.get(check_name)
            if expected is None or spath.resolve() != expected.resolve():
                paths_resolve_ok = False
        except Exception:
            paths_resolve_ok = False

        expected_status = _derive_status(entry["exit_code"], entry["stdout"])
        if entry["status"] != expected_status:
            status_rule_ok = False

        derived_issue = _derive_issue_type(entry["stdout"], entry["stderr"], entry["status"])
        if entry["issue_type"] != derived_issue:
            issue_rule_ok = False

        stdout_log = logs_dir / f"{check_name}_stdout.txt"
        stderr_log = logs_dir / f"{check_name}_stderr.txt"
        so = _read_text_safe(stdout_log)
        se = _read_text_safe(stderr_log)
        if so is None or se is None:
            logs_exist_ok = False
        else:
            if so != entry["stdout"] or se != entry["stderr"]:
                logs_content_ok = False

        if entry["status"] == "failed":
            if so is None or se is None:
                failed_logs_ok = False

        if check_name in recomputed_results:
            rrc, _, _, _, _ = recomputed_results[check_name]
            if entry["exit_code"] != rrc:
                script_exit_match_ok = False
        else:
            script_exit_match_ok = False

    if names_ok and len(names_set) == len(discovered_map):
        scores["check_names_match_files"] = 1.0

    if fields_ok:
        scores["json_fields_complete"] = 1.0
    if paths_resolve_ok:
        scores["script_paths_resolve"] = 1.0
    if status_rule_ok:
        scores["status_classification_rule_applied"] = 1.0
    if issue_rule_ok:
        scores["issue_type_rule_applied"] = 1.0
    if logs_exist_ok:
        scores["logs_exist_all_checks"] = 1.0
    if logs_content_ok:
        scores["logs_content_match_json"] = 1.0
    if failed_logs_ok:
        scores["failed_checks_have_logs"] = 1.0
    if script_exit_match_ok:
        scores["exit_codes_match_recomputed"] = 1.0

    notes_text = _read_text_safe(notes_path)
    if notes_text is None:
        return scores
    scores["meeting_notes_exists"] = 1.0

    other_headers = ["Overview:", "Check Results:", "Action Items:"]
    overview_text = _extract_section(notes_text, "Overview:", other_headers)
    table_text = _extract_section(notes_text, "Check Results:", other_headers)
    actions_text = _extract_section(notes_text, "Action Items:", other_headers)

    passed_count = sum(1 for e in checks if isinstance(e, dict) and e.get("status") == "passed")
    failed_count = sum(1 for e in checks if isinstance(e, dict) and e.get("status") == "failed")
    p_num, f_num = _extract_numbers_in_overview(overview_text)
    if p_num == passed_count and f_num == failed_count:
        scores["meeting_notes_overview_counts_correct"] = 1.0

    rows = _parse_table_rows(table_text)
    rows_by_check: Dict[str, Tuple[str, str, str]] = {}
    for chk, st, act in rows:
        rows_by_check[chk] = (chk, st, act)
    table_ok = True
    for entry in checks:
        if not isinstance(entry, dict):
            table_ok = False
            continue
        name = entry["check_name"]
        status = entry["status"]
        if name not in rows_by_check:
            table_ok = False
            break
        _, st, act = rows_by_check[name]
        if st != status or not act:
            table_ok = False
            break
    header_present = "check" in table_text.lower() and "status" in table_text.lower() and "next action" in table_text.lower()
    if table_ok and header_present:
        scores["meeting_notes_table_covers_all_checks"] = 1.0

    bullets = []
    for ln in actions_text.splitlines():
        if ln.strip().startswith(("-", "*")):
            bullets.append(ln.strip())
    action_ok = True
    for entry in checks:
        if not isinstance(entry, dict) or entry.get("status") != "failed":
            continue
        stdout = entry.get("stdout", "")
        stderr = entry.get("stderr", "")
        context_line = _get_error_alert_line(stdout, stderr)
        found = False
        for b in bullets:
            if ("owner: Vet Tech" in b) and ("due: next weekly herd review" in b) and (context_line in b):
                found = True
                break
        if not found:
            action_ok = False
            break
    if action_ok:
        scores["meeting_notes_action_items_for_failed_checks"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()