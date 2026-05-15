import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, Any, Dict, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _load_log_lines(path: Path) -> List[str]:
    txt = _read_text(path)
    if txt is None:
        return []
    return [line.rstrip("\n") for line in txt.splitlines()]


def _extract_function_block(source: str, func_name: str) -> Optional[str]:
    lines = source.splitlines()
    def_line_index = None
    def_indent = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {func_name}("):
            def_line_index = i
            def_indent = len(line) - len(stripped)
            break
    if def_line_index is None:
        return None
    body_lines: List[str] = []
    for j in range(def_line_index + 1, len(lines)):
        line = lines[j]
        if line.strip() == "":
            body_lines.append(line)
            continue
        curr_indent = len(line) - len(line.lstrip())
        if curr_indent <= (def_indent or 0):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def _incident_changes_old_new(changes: Dict[str, Any]) -> Tuple[Optional[Any], Optional[Any]]:
    keys = {k.lower(): k for k in changes.keys()}
    old = None
    new = None
    if "old" in keys and "new" in keys:
        old = changes[keys["old"]]
        new = changes[keys["new"]]
    else:
        for ok in ["old_value", "old_sensor_poll_interval_ms"]:
            if ok in keys:
                old = changes[keys[ok]]
                break
        for nk in ["new_value", "new_sensor_poll_interval_ms"]:
            if nk in keys:
                new = changes[keys[nk]]
                break
    return old, new


def _find_function_and_summary(changes: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    func_name = None
    summary = None
    for k, v in changes.items():
        kl = k.lower()
        if func_name is None and "function" in kl and isinstance(v, str):
            func_name = v
        if summary is None and (kl == "summary" or "summary" in kl or "description" in kl) and isinstance(v, str):
            summary = v
    return func_name, summary


def _parse_expected_interval_from_config_value(val: Any) -> Optional[int]:
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if float(int(val)) == val:
            return int(val)
        return None
    if isinstance(val, str):
        m = re.match(r"^\s*(\d+)\s*ms\s*$", val, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        s = val.strip()
        if s.isdigit():
            try:
                return int(s)
            except Exception:
                return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "status_file_exists": 0.0,
        "status_ok": 0.0,
        "interval_ms_present_and_int": 0.0,
        "status_interval_consistent_with_config": 0.0,
        "incident_report_exists": 0.0,
        "incident_report_structure_fields": 0.0,
        "incident_report_root_cause_identifies_key_value": 0.0,
        "evidence_log_excerpt_matches_and_contains_valueerror": 0.0,
        "evidence_file_paths_list_exact": 0.0,
        "fix_approach_and_files_consistent": 0.0,
        "fix_changes_fields_valid": 0.0,
        "effective_fix_in_files": 0.0,
        "post_fix_check_status_consistent": 0.0,
    }

    cfg_path = workspace / "app" / "config.json"
    tracker_path = workspace / "app" / "tracker.py"
    log_path = workspace / "logs" / "run-2026-04-17.log"
    status_path = workspace / "out" / "status.json"
    incident_path = workspace / "out" / "incident_report.json"

    cfg_obj = _load_json(cfg_path) if cfg_path.exists() else None
    tracker_src = _read_text(tracker_path) if tracker_path.exists() else None
    log_lines = _load_log_lines(log_path) if log_path.exists() else []
    status_obj = _load_json(status_path) if status_path.exists() else None
    incident_obj = _load_json(incident_path) if incident_path.exists() else None

    if status_obj is not None:
        scores["status_file_exists"] = 1.0
        if isinstance(status_obj, dict):
            if status_obj.get("status") == "ok":
                scores["status_ok"] = 1.0
            if "interval_ms" in status_obj and isinstance(status_obj.get("interval_ms"), int) and status_obj.get("interval_ms") > 0:
                scores["interval_ms_present_and_int"] = 1.0

    if status_obj and isinstance(status_obj, dict) and "interval_ms" in status_obj and cfg_obj and isinstance(cfg_obj, dict):
        expected = _parse_expected_interval_from_config_value(cfg_obj.get("sensor_poll_interval_ms"))
        if expected is not None and status_obj.get("interval_ms") == expected:
            scores["status_interval_consistent_with_config"] = 1.0

    if incident_obj is not None:
        scores["incident_report_exists"] = 1.0

    if isinstance(incident_obj, dict):
        has_root = isinstance(incident_obj.get("root_cause"), str)
        ev = incident_obj.get("evidence")
        fx = incident_obj.get("fix")
        pf_obj = incident_obj.get("post_fix_check")
        structure_ok = (
            has_root and isinstance(ev, dict) and isinstance(fx, dict) and isinstance(pf_obj, dict)
            and isinstance(ev.get("log_excerpt"), str)
            and isinstance(ev.get("file_paths_inspected"), list)
            and isinstance(fx.get("approach"), str)
            and isinstance(fx.get("files_modified"), list)
            and isinstance(fx.get("changes"), dict)
            and isinstance(pf_obj.get("status_file"), str)
            and ("status" in pf_obj)
        )
        if structure_ok:
            scores["incident_report_structure_fields"] = 1.0

        rc = incident_obj.get("root_cause")
        if isinstance(rc, str):
            key_ok = "sensor_poll_interval_ms" in rc
            val_ok = "50ms" in rc
            if key_ok and val_ok:
                scores["incident_report_root_cause_identifies_key_value"] = 1.0

        log_excerpt = ev.get("log_excerpt") if isinstance(ev, dict) else None
        if isinstance(log_excerpt, str) and len(log_lines) > 0:
            if log_excerpt in log_lines and ("valueerror" in log_excerpt.lower()):
                scores["evidence_log_excerpt_matches_and_contains_valueerror"] = 1.0

        file_paths = ev.get("file_paths_inspected") if isinstance(ev, dict) else None
        if isinstance(file_paths, list):
            target_list = ["app/tracker.py", "app/config.json", "logs/run-2026-04-17.log"]
            if file_paths == target_list:
                scores["evidence_file_paths_list_exact"] = 1.0

        approach = fx.get("approach") if isinstance(fx, dict) else None
        files_mod = fx.get("files_modified") if isinstance(fx, dict) else None
        if isinstance(approach, str) and isinstance(files_mod, list):
            app_ok = approach in {"code_change", "config_change"}
            files_ok = False
            if approach == "config_change":
                files_ok = "app/config.json" in files_mod
            elif approach == "code_change":
                files_ok = "app/tracker.py" in files_mod
            if app_ok and files_ok:
                scores["fix_approach_and_files_consistent"] = 1.0

        fix_changes_ok = False

        effective_config_fix = False
        if isinstance(cfg_obj, dict) and "sensor_poll_interval_ms" in cfg_obj:
            effective_config_fix = isinstance(cfg_obj.get("sensor_poll_interval_ms"), int)

        effective_code_fix = False
        if isinstance(tracker_src, str):
            body = _extract_function_block(tracker_src, "parse_interval_ms")
            if isinstance(body, str):
                body_lower = body.lower()
                mentions_ms = "ms" in body_lower
                uses_cleaning = ("replace(" in body_lower or "strip(" in body_lower or "isdigit(" in body_lower or "re." in body_lower)
                unchanged_simple = ("return int(value)" in body_lower) and ("ms" not in body_lower) and ("replace(" not in body_lower) and ("strip(" not in body_lower)
                effective_code_fix = (mentions_ms or uses_cleaning) and not unchanged_simple

        changes = fx.get("changes") if isinstance(fx, dict) else None
        if isinstance(changes, dict) and isinstance(approach, str):
            if approach == "config_change":
                old_val, new_val = _incident_changes_old_new(changes)
                old_ok = (old_val == "50ms")
                new_ok = isinstance(new_val, int)
                cfg_matches_new = isinstance(cfg_obj, dict) and cfg_obj.get("sensor_poll_interval_ms") == new_val
                if old_ok and new_ok and cfg_matches_new:
                    fix_changes_ok = True
            elif approach == "code_change":
                func_name, summary = _find_function_and_summary(changes)
                func_ok = isinstance(func_name, str) and "parse_interval_ms" in func_name
                summary_ok = isinstance(summary, str) and len(summary.strip()) > 0
                if func_ok and summary_ok and effective_code_fix:
                    fix_changes_ok = True

        if fix_changes_ok:
            scores["fix_changes_fields_valid"] = 1.0

        if effective_config_fix or effective_code_fix:
            scores["effective_fix_in_files"] = 1.0

        pf = incident_obj.get("post_fix_check") if isinstance(incident_obj, dict) else None
        if isinstance(pf, dict):
            pf_status_file = pf.get("status_file")
            pf_status = pf.get("status")
            status_ok_obj = isinstance(status_obj, dict)
            if pf_status_file == "out/status.json" and status_ok_obj and pf_status == status_obj.get("status"):
                scores["post_fix_check_status_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()