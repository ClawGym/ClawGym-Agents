import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Optional, Tuple, Any, List, Dict
import importlib.util
import types


def _read_text_safe(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, None


def _load_json_safe(path: Path) -> Tuple[bool, Optional[Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _run_python_script(cwd: Path, script_relpath: str) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [sys.executable, script_relpath],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)


def _import_module_from_path(module_name: str, module_path: Path) -> Tuple[bool, Optional[types.ModuleType], Optional[str]]:
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            return False, None, "spec not found"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return True, module, None
    except Exception as e:
        return False, None, str(e)


def _validate_remediation_list(rem_list: Any) -> Tuple[bool, Dict[str, Dict[str, Any]]]:
    if not isinstance(rem_list, list):
        return False, {}
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in rem_list:
        if not isinstance(item, dict):
            return False, {}
        for k in ("setting", "current", "required"):
            if k not in item:
                return False, {}
        setting = item.get("setting")
        if not isinstance(setting, str):
            return False, {}
        mapping[setting] = item
    return True, mapping


def _expected_remediation_from_inputs(baseline_req: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    expected: Dict[str, Dict[str, Any]] = {}
    if "screen_lock_minutes_max" in baseline_req:
        max_val = baseline_req["screen_lock_minutes_max"]
        cur = state.get("screen_lock_minutes")
        if isinstance(cur, (int, float)) and cur > max_val:
            expected["screen_lock_minutes"] = {"setting": "screen_lock_minutes", "current": cur, "required": max_val}
    if baseline_req.get("require_full_disk_encryption") is True:
        cur_enc = state.get("full_disk_encryption")
        if cur_enc is not True:
            expected["full_disk_encryption"] = {"setting": "full_disk_encryption", "current": cur_enc, "required": True}
    if baseline_req.get("guest_account_disabled") is True:
        cur_guest = state.get("guest_account")
        if cur_guest != "disabled":
            expected["guest_account"] = {"setting": "guest_account", "current": cur_guest, "required": "disabled"}
    return expected


def _count_action_items(lines: List[str]) -> int:
    count = 0
    date_re = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    for line in lines:
        if line.strip().startswith("- [ ] "):
            if "Owner:" in line and "Due:" in line and date_re.search(line):
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "importable_compute_remediation": 0.0,
        "compute_remediation_expected_output": 0.0,
        "tests_runtime_passed": 0.0,
        "test_report_contains_all_tests_passed": 0.0,
        "remediation_plan_json_correct": 0.0,
        "device_policy_updated_statements_present": 0.0,
        "device_policy_no_weaker_language": 0.0,
        "compliance_checks_section_and_references": 0.0,
        "meeting_notes_status_and_actions": 0.0,
    }

    baseline_ok, baseline_json = _load_json_safe(workspace / "input" / "policy_baseline.json")
    state_ok, state_json = _load_json_safe(workspace / "input" / "sample_device_state.json")
    baseline_requirements: Dict[str, Any] = {}
    if baseline_ok and isinstance(baseline_json, dict):
        reqs = baseline_json.get("requirements", {})
        if isinstance(reqs, dict):
            baseline_requirements = reqs
    device_state: Dict[str, Any] = state_json if state_ok and isinstance(state_json, dict) else {}

    policy_path = workspace / "tools" / "policy_enforcer.py"
    imported, module, err = _import_module_from_path("tools.policy_enforcer", policy_path)
    if imported and module is not None and hasattr(module, "compute_remediation") and callable(getattr(module, "compute_remediation")):
        scores["importable_compute_remediation"] = 1.0
        try:
            if baseline_requirements and device_state:
                result = module.compute_remediation(device_state, baseline_requirements)  # type: ignore[attr-defined]
                valid, mapping = _validate_remediation_list(result)
                expected_map = _expected_remediation_from_inputs(baseline_requirements, device_state)
                if valid and mapping.keys() == expected_map.keys():
                    all_match = True
                    for k, v in expected_map.items():
                        mv = mapping.get(k)
                        if mv is None:
                            all_match = False
                            break
                        if mv.get("current") != v.get("current") or mv.get("required") != v.get("required"):
                            all_match = False
                            break
                    if all_match:
                        scores["compute_remediation_expected_output"] = 1.0
        except Exception:
            pass
    else:
        scores["importable_compute_remediation"] = 0.0
        scores["compute_remediation_expected_output"] = 0.0

    if (workspace / "tests" / "test_policy.py").exists():
        rc, out, err = _run_python_script(workspace, str(Path("tests") / "test_policy.py"))
        if rc == 0 and "All tests passed" in out:
            scores["tests_runtime_passed"] = 1.0

    report_path = workspace / "output" / "test_report.txt"
    ok, text = _read_text_safe(report_path)
    if ok and text is not None and "All tests passed" in text:
        scores["test_report_contains_all_tests_passed"] = 1.0

    remediation_path = workspace / "output" / "remediation_plan.json"
    rem_ok, rem_json = _load_json_safe(remediation_path)
    if rem_ok:
        valid, mapping = _validate_remediation_list(rem_json)
        expected_map = _expected_remediation_from_inputs(baseline_requirements, device_state)
        if valid and mapping.keys() == expected_map.keys():
            all_match = True
            for k, v in expected_map.items():
                mv = mapping.get(k)
                if mv is None:
                    all_match = False
                    break
                if mv.get("current") != v.get("current") or mv.get("required") != v.get("required"):
                    all_match = False
                    break
            if all_match:
                scores["remediation_plan_json_correct"] = 1.0

    policy_doc_path = workspace / "docs" / "DevicePolicy.md"
    doc_ok, doc_text = _read_text_safe(policy_doc_path)
    if doc_ok and doc_text is not None:
        required_statements = [
            "Screen must auto-lock at 10 minutes or less.",
            "Full-disk encryption is required (not optional).",
            "Guest account must be disabled.",
        ]
        if all(stmt in doc_text for stmt in required_statements):
            scores["device_policy_updated_statements_present"] = 1.0

        weaker_phrases = [
            "Screen should auto-lock after 15 minutes of inactivity.",
            "Full-disk encryption is recommended (optional) to protect student data.",
            "Guest account is discouraged but allowed if supervised.",
        ]
        if not any(phrase in doc_text for phrase in weaker_phrases):
            scores["device_policy_no_weaker_language"] = 1.0

        lines = doc_text.splitlines()
        has_heading = any(re.match(r"^\s*#{1,6}\s*Compliance Checks\b", ln, flags=re.IGNORECASE) for ln in lines)
        has_tests_ref = "tests/test_policy.py" in doc_text
        has_output_ref = "output/remediation_plan.json" in doc_text
        if has_heading and has_tests_ref and has_output_ref:
            scores["compliance_checks_section_and_references"] = 1.0

    meeting_path = workspace / "output" / "Meeting_Notes_Foundation_Devices.md"
    meet_ok, meet_text = _read_text_safe(meeting_path)
    if meet_ok and meet_text is not None:
        has_status = "Automation status: All tests passed" in meet_text
        action_count = _count_action_items(meet_text.splitlines())
        if has_status and action_count >= 5:
            scores["meeting_notes_status_and_actions"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()