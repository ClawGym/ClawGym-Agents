import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple
import zipfile


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_pipeline_test_stage_unchanged(pipeline: Dict[str, Any]) -> bool:
    try:
        stages = pipeline.get("stages", [])
        expected_stage = {
            "name": "test",
            "steps": [
                {"name": "Run tests", "run": "python tools/run_tests.py"}
            ]
        }
        if not isinstance(stages, list) or not stages:
            return False
        return stages[0] == expected_stage
    except Exception:
        return False


def _pipeline_has_env_app_env_prod(pipeline: Dict[str, Any]) -> bool:
    try:
        env = pipeline.get("env")
        if not isinstance(env, dict):
            return False
        val = env.get("APP_ENV")
        return isinstance(val, str) and val == "prod"
    except Exception:
        return False


def _pipeline_has_build_after_test_with_cmd(pipeline: Dict[str, Any], cmd: str) -> bool:
    try:
        stages = pipeline.get("stages", [])
        if not isinstance(stages, list) or not stages:
            return False
        # find index of the exact "test" stage as originally defined
        expected_test = {
            "name": "test",
            "steps": [
                {"name": "Run tests", "run": "python tools/run_tests.py"}
            ]
        }
        test_idx = None
        for idx, st in enumerate(stages):
            if st == expected_test:
                test_idx = idx
                break
        if test_idx is None:
            return False
        # ensure there exists a stage AFTER the test stage that contains a step with the exact run command
        for st in stages[test_idx + 1:]:
            steps = st.get("steps", [])
            if not isinstance(steps, list):
                continue
            for step in steps:
                if isinstance(step, dict) and step.get("run") == cmd:
                    return True
        return False
    except Exception:
        return False


def _validate_ci_log(log_text: str, required_cmd: str) -> Tuple[bool, bool, bool]:
    """
    Returns tuple:
    - success_line_present
    - package_step_present (the exact command appears in the log)
    - order_ok (test stage starts before the package command appears)
    """
    if not isinstance(log_text, str):
        return (False, False, False)
    success_present = "Pipeline status: SUCCESS" in log_text
    package_cmd_line = f"cmd='{required_cmd}'"
    package_cmd_present = package_cmd_line in log_text
    # Ensure ordering: "STAGE test: START" occurs before package cmd line
    test_start_idx = log_text.find("STAGE test: START")
    pkg_idx = log_text.find(package_cmd_line)
    order_ok = (test_start_idx != -1 and pkg_idx != -1 and test_start_idx < pkg_idx)
    return (success_present, package_cmd_present, order_ok)


def _load_test_results(path: Path) -> Optional[Dict[str, Any]]:
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return None
    try:
        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            return None
        tests_run = summary.get("tests_run")
        tests_passed = summary.get("tests_passed")
        tests_failed = summary.get("tests_failed")
        if not (isinstance(tests_run, int) and isinstance(tests_passed, int) and isinstance(tests_failed, int)):
            return None
        results = data.get("results")
        if not isinstance(results, list):
            return None
        if len(results) != tests_run:
            return None
        for r in results:
            if not isinstance(r, dict):
                return None
            if "passed" not in r or not isinstance(r["passed"], bool):
                return None
        return data
    except Exception:
        return None


def _all_tests_passed(test_results: Dict[str, Any]) -> bool:
    try:
        summary = test_results.get("summary", {})
        if not isinstance(summary, dict):
            return False
        return summary.get("tests_failed") == 0
    except Exception:
        return False


def _env_prod_in_test_results(test_results: Dict[str, Any]) -> bool:
    try:
        env = test_results.get("env", {})
        if not isinstance(env, dict):
            return False
        if env.get("APP_ENV") != "prod":
            return False
        for r in test_results.get("results", []):
            if isinstance(r, dict) and r.get("name") == "env_is_prod" and r.get("passed") is True:
                return True
        return False
    except Exception:
        return False


def _zip_contains_file(zip_path: Path, expected_rel: str) -> bool:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return expected_rel in zf.namelist()
    except Exception:
        return False


def _zip_file_matches_source(zip_path: Path, src_file: Path, arcname: str) -> bool:
    try:
        if not src_file.exists():
            return False
        with zipfile.ZipFile(zip_path, "r") as zf:
            if arcname not in zf.namelist():
                return False
            zbytes = zf.read(arcname)
        sbytes = src_file.read_bytes()
        return zbytes == sbytes
    except Exception:
        return False


def _parse_email_lines(email_text: str) -> List[str]:
    if not isinstance(email_text, str):
        return []
    return email_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _email_subject_and_status(email_text: str) -> Tuple[bool, bool]:
    lines = _parse_email_lines(email_text)
    if not lines:
        return (False, False)
    subject_ok = lines[0].startswith("Subject: CI Update —")
    # Status line must be in the body (anywhere after the subject line)
    status_ok = any(line.strip() == "Pipeline status: SUCCESS" for line in lines[1:])
    return (subject_ok, status_ok)


def _email_mentions_env_artifact_and_counts(email_text: str, test_results: Dict[str, Any]) -> bool:
    if not isinstance(email_text, str) or not isinstance(test_results, dict):
        return False
    lines = _parse_email_lines(email_text)
    body = "\n".join(lines[1:]) if lines else ""
    if "APP_ENV=prod" not in body:
        return False
    if "output/build/package.zip" not in body:
        return False
    summary = test_results.get("summary", {})
    try:
        tr = int(summary.get("tests_run"))
        tp = int(summary.get("tests_passed"))
        tf = int(summary.get("tests_failed"))
    except Exception:
        return False
    expected_line = f"tests_run: {tr}, tests_passed: {tp}, tests_failed: {tf}"
    for line in lines:
        if line.strip() == expected_line:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    pipeline_path = workspace / "ci" / "pipeline.json"
    log_path = workspace / "output" / "ci.log"
    test_results_path = workspace / "output" / "test_results.json"
    build_zip_path = workspace / "output" / "build" / "package.zip"
    email_path = workspace / "output" / "rollout_email.txt"

    required_build_cmd = "python tools/package.py --src app --out output/build/package.zip"

    scores = {
        "pipeline_env_app_env_prod": 0.0,
        "pipeline_build_stage_after_test_with_correct_command": 0.0,
        "pipeline_test_stage_preserved": 0.0,
        "ci_log_success_and_contains_package_step": 0.0,
        "test_results_valid_and_all_passed": 0.0,
        "build_zip_valid_and_contains_app": 0.0,
        "email_subject_and_status_line_present": 0.0,
        "email_mentions_env_artifact_and_correct_counts": 0.0,
    }

    pipeline = _safe_load_json(pipeline_path)
    env_ok = False
    build_ok = False
    test_preserved = False
    if isinstance(pipeline, dict):
        env_ok = _pipeline_has_env_app_env_prod(pipeline)
        if env_ok:
            scores["pipeline_env_app_env_prod"] = 1.0
        build_ok = _pipeline_has_build_after_test_with_cmd(pipeline, required_build_cmd)
        if build_ok:
            scores["pipeline_build_stage_after_test_with_correct_command"] = 1.0
        # Only award preservation if other modifications exist to avoid baseline credit
        if env_ok and build_ok and _is_pipeline_test_stage_unchanged(pipeline):
            test_preserved = True
            scores["pipeline_test_stage_preserved"] = 1.0

    log_text = _safe_read_text(log_path)
    if isinstance(log_text, str):
        success_present, package_cmd_present, order_ok = _validate_ci_log(log_text, required_build_cmd)
        if success_present and package_cmd_present and order_ok:
            scores["ci_log_success_and_contains_package_step"] = 1.0

    test_results = _load_test_results(test_results_path)
    if isinstance(test_results, dict):
        if _all_tests_passed(test_results) and _env_prod_in_test_results(test_results):
            scores["test_results_valid_and_all_passed"] = 1.0

    if build_zip_path.exists():
        contains_calc = _zip_contains_file(build_zip_path, "calc.py")
        matches_calc = _zip_file_matches_source(build_zip_path, workspace / "app" / "calc.py", "calc.py")
        if contains_calc and matches_calc:
            scores["build_zip_valid_and_contains_app"] = 1.0

    email_text = _safe_read_text(email_path)
    if isinstance(email_text, str):
        subj_ok, status_ok = _email_subject_and_status(email_text)
        if subj_ok and status_ok:
            scores["email_subject_and_status_line_present"] = 1.0
        if isinstance(test_results, dict) and _email_mentions_env_artifact_and_counts(email_text, test_results):
            scores["email_mentions_env_artifact_and_correct_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()