import json
import sys
import subprocess
import re
import csv
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _run_validator(workspace: Path, validator_path: Path, actions_path: Path) -> Optional[Tuple[str, int]]:
    try:
        if not validator_path.exists() or not actions_path.exists():
            return None
        proc = subprocess.run(
            [sys.executable, str(validator_path), str(actions_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = proc.stdout
        return stdout, proc.returncode
    except Exception:
        return None


def _parse_validator_log(log_text: str) -> Optional[Dict[str, Any]]:
    if log_text is None:
        return None
    lines_all = log_text.splitlines()
    idx = len(lines_all) - 1
    while idx >= 0 and lines_all[idx].strip() == "":
        idx -= 1
    if idx < 0:
        return None
    last_line = lines_all[idx]
    if not last_line.startswith("EXIT_CODE="):
        return None
    try:
        exit_code = int(last_line.split("=", 1)[1].strip())
    except Exception:
        return None
    stdout_lines = lines_all[:idx]
    parsed = _parse_validator_lines(stdout_lines)
    if parsed is None:
        parsed = {"errors": [], "warnings": []}
    return {
        "stdout_lines": stdout_lines,
        "exit_code": exit_code,
        "errors": parsed["errors"],
        "warnings": parsed["warnings"],
    }


def _parse_validator_lines(lines: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    errors = []
    warnings = []
    err_re = re.compile(r"^ERROR:\s+row\s+(\d+)\s+\(action_id=(.*?)\):\s*(.*)$")
    warn_re = re.compile(r"^WARNING:\s+row\s+(\d+)\s+\(action_id=(.*?)\):\s*(.*)$")
    for line in lines:
        if line.startswith("ERROR:"):
            m = err_re.match(line)
            if not m:
                return None
            row = int(m.group(1))
            aid = m.group(2)
            msg = line
            errors.append({"action_id": aid, "row": row, "message": msg})
        elif line.startswith("WARNING:"):
            m = warn_re.match(line)
            if not m:
                return None
            row = int(m.group(1))
            aid = m.group(2)
            msg = line
            kind = "priority" if "priority" in msg.lower() else ("status" if "status" in msg.lower() else "other")
            warnings.append({"action_id": aid, "row": row, "message": msg, "kind": kind})
    return {"errors": errors, "warnings": warnings}


def _build_chapters_map(chapter_rows: List[Dict[str, str]]) -> Dict[str, str]:
    mapping = {}
    for row in chapter_rows:
        cid = (row.get("chapter_id") or "").strip()
        cname = (row.get("chapter_name") or "").strip()
        if cid:
            mapping[cid] = cname
    return mapping


def _compute_orphans(actions_rows: List[Dict[str, str]], chapters_map: Dict[str, str]) -> List[Dict[str, str]]:
    orphans = []
    for row in actions_rows:
        aid = (row.get("action_id") or "").strip()
        cid = (row.get("chapter_id") or "").strip()
        if cid == "" or cid not in chapters_map:
            if aid:
                orphans.append({"action_id": aid, "chapter_id": cid})
    return orphans


def _build_expected_plan(actions_rows: List[Dict[str, str]], chapters_map: Dict[str, str],
                         vdata: Dict[str, Any]) -> List[Dict[str, str]]:
    error_ids = set([e["action_id"] for e in vdata.get("errors", [])])
    warn_kinds: Dict[str, set] = {}
    for w in vdata.get("warnings", []):
        aid = w["action_id"]
        kind = w.get("kind", "")
        if aid not in warn_kinds:
            warn_kinds[aid] = set()
        warn_kinds[aid].add(kind)
    expected = []
    for row in actions_rows:
        aid = (row.get("action_id") or "").strip()
        cid = (row.get("chapter_id") or "").strip()
        title = (row.get("action_title") or "").strip()
        pr = (row.get("priority") or "").strip()
        st = (row.get("status") or "").strip()
        if cid == "" or cid not in chapters_map:
            continue
        if aid in error_ids:
            continue
        kinds = warn_kinds.get(aid, set())
        if "priority" in kinds:
            pr = "medium"
        if "status" in kinds:
            st = "planned"
        expected.append({
            "action_id": aid,
            "chapter_id": cid,
            "chapter_name": chapters_map.get(cid, ""),
            "action_title": title,
            "priority": pr,
            "status": st,
        })
    expected.sort(key=lambda r: (r["chapter_name"], r["action_id"]))
    return expected


def _read_sync_plan(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                rows.append({
                    "action_id": row.get("action_id", ""),
                    "chapter_id": row.get("chapter_id", ""),
                    "chapter_name": row.get("chapter_name", ""),
                    "action_title": row.get("action_title", ""),
                    "priority": row.get("priority", ""),
                    "status": row.get("status", ""),
                })
            return reader.fieldnames, rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    actions_path = workspace / "input" / "actions.csv"
    chapters_path = workspace / "input" / "chapters.csv"
    validator_path = workspace / "tools" / "validate_actions.py"
    log_path = workspace / "output" / "validator_raw.log"
    plan_path = workspace / "output" / "sync_plan.csv"
    issues_path = workspace / "output" / "issues.json"

    scores = {
        "validator_log_capture_and_exit_code": 0.0,
        "validator_stdout_match": 0.0,
        "validator_exit_code_match": 0.0,
        "sync_plan_structure_and_sorting": 0.0,
        "sync_plan_content": 0.0,
        "issues_json_schema": 0.0,
        "issues_validator_exit_code": 0.0,
        "issues_errors_match_log": 0.0,
        "issues_warnings_included_match": 0.0,
        "issues_orphans_correct": 0.0,
    }

    log_text = _safe_read_text(log_path)
    parsed_log = None
    if log_text is not None:
        parsed_log = _parse_validator_log(log_text)
        if parsed_log is not None and isinstance(parsed_log.get("exit_code"), int):
            scores["validator_log_capture_and_exit_code"] = 1.0

    expected_run = _run_validator(workspace, validator_path, actions_path)
    if expected_run is not None and parsed_log is not None:
        expected_stdout, expected_code = expected_run
        if parsed_log.get("stdout_lines") == expected_stdout.splitlines():
            scores["validator_stdout_match"] = 1.0
        if parsed_log.get("exit_code") == expected_code:
            scores["validator_exit_code_match"] = 1.0

    plan_read = _read_sync_plan(plan_path)
    actions_rows = _safe_read_csv_dicts(actions_path)
    chapters_rows = _safe_read_csv_dicts(chapters_path)
    chapters_map = _build_chapters_map(chapters_rows or [])

    if plan_read is not None:
        header, plan_rows = plan_read
        expected_header = ["action_id", "chapter_id", "chapter_name", "action_title", "priority", "status"]
        header_ok = header == expected_header
        sort_ok = True
        for i in range(1, len(plan_rows)):
            prev = plan_rows[i - 1]
            curr = plan_rows[i]
            if (prev["chapter_name"], prev["action_id"]) > (curr["chapter_name"], curr["action_id"]):
                sort_ok = False
                break
        if header_ok and sort_ok:
            scores["sync_plan_structure_and_sorting"] = 1.0

    validator_data_for_plan = None
    if parsed_log is not None:
        validator_data_for_plan = {"errors": parsed_log.get("errors", []), "warnings": parsed_log.get("warnings", [])}
    else:
        if expected_run is not None:
            stdout_lines = expected_run[0].splitlines()
            parsed_from_run = _parse_validator_lines(stdout_lines)
            if parsed_from_run is not None:
                validator_data_for_plan = {"errors": parsed_from_run.get("errors", []), "warnings": parsed_from_run.get("warnings", [])}

    if plan_read is not None and actions_rows is not None and chapters_rows is not None and validator_data_for_plan is not None:
        expected_plan_rows = _build_expected_plan(actions_rows, chapters_map, validator_data_for_plan)
        _, actual_plan_rows = plan_read
        if expected_plan_rows == actual_plan_rows:
            scores["sync_plan_content"] = 1.0

    issues = _safe_load_json(issues_path)
    if issues is not None and isinstance(issues, dict):
        schema_ok = True
        required_keys = ["validator_exit_code", "errors", "warnings_included", "orphans"]
        for k in required_keys:
            if k not in issues:
                schema_ok = False
                break
        if schema_ok:
            if not isinstance(issues.get("validator_exit_code"), int):
                schema_ok = False
            if not isinstance(issues.get("errors"), list):
                schema_ok = False
            else:
                for e in issues.get("errors"):
                    if not isinstance(e, dict):
                        schema_ok = False
                        break
                    if not all(key in e for key in ["action_id", "row", "message"]):
                        schema_ok = False
                        break
                    if not isinstance(e.get("action_id"), str) or not isinstance(e.get("row"), int) or not isinstance(e.get("message"), str):
                        schema_ok = False
                        break
            if not isinstance(issues.get("warnings_included"), list):
                schema_ok = False
            else:
                for w in issues.get("warnings_included"):
                    if not isinstance(w, dict):
                        schema_ok = False
                        break
                    if not all(key in w for key in ["action_id", "row", "message"]):
                        schema_ok = False
                        break
                    if not isinstance(w.get("action_id"), str) or not isinstance(w.get("row"), int) or not isinstance(w.get("message"), str):
                        schema_ok = False
                        break
            if not isinstance(issues.get("orphans"), list):
                schema_ok = False
            else:
                for o in issues.get("orphans"):
                    if not isinstance(o, dict):
                        schema_ok = False
                        break
                    if not all(key in o for key in ["action_id", "chapter_id"]):
                        schema_ok = False
                        break
                    if not isinstance(o.get("action_id"), str) or not isinstance(o.get("chapter_id"), str):
                        schema_ok = False
                        break
        if schema_ok:
            scores["issues_json_schema"] = 1.0

        if parsed_log is not None:
            if issues.get("validator_exit_code") == parsed_log.get("exit_code"):
                scores["issues_validator_exit_code"] = 1.0

        if parsed_log is not None and isinstance(issues.get("errors"), list):
            expected_errors_set = set((e["action_id"], e["row"], e["message"]) for e in parsed_log.get("errors", []))
            actual_errors_set = set((e.get("action_id"), e.get("row"), e.get("message")) for e in issues.get("errors", []))
            if expected_errors_set == actual_errors_set:
                scores["issues_errors_match_log"] = 1.0

        plan_read_for_issues = _read_sync_plan(plan_path)
        if parsed_log is not None and plan_read_for_issues is not None and isinstance(issues.get("warnings_included"), list):
            _, plan_rows2 = plan_read_for_issues
            plan_included_ids = set(r["action_id"] for r in plan_rows2)
            expected_warnings_set = set(
                (w["action_id"], w["row"], w["message"])
                for w in parsed_log.get("warnings", [])
                if w["action_id"] in plan_included_ids
            )
            actual_warnings_set = set(
                (w.get("action_id"), w.get("row"), w.get("message"))
                for w in issues.get("warnings_included", [])
            )
            if expected_warnings_set == actual_warnings_set:
                scores["issues_warnings_included_match"] = 1.0

        if actions_rows is not None and chapters_rows is not None and isinstance(issues.get("orphans"), list):
            chapters_map2 = _build_chapters_map(chapters_rows)
            expected_orphans = _compute_orphans(actions_rows, chapters_map2)
            expected_orphans_set = set((o["action_id"], o["chapter_id"]) for o in expected_orphans)
            actual_orphans_set = set((o.get("action_id"), o.get("chapter_id")) for o in issues.get("orphans", []))
            if expected_orphans_set == actual_orphans_set:
                scores["issues_orphans_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()