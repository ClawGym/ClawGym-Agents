import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"error:{e}"


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error:{e}"


def _import_sum_nonnegatives(app_path: Path):
    # Import sum_nonnegatives from a specific file path without altering sys.path
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("app_app_module", app_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        func = getattr(module, "sum_nonnegatives", None)
        return func
    except Exception:
        return None


def _compute_test_metrics(workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    tests_path = workspace / "tests" / "test_cases.json"
    app_py = workspace / "app" / "app.py"
    cases, err = _load_json(tests_path)
    if err or not isinstance(cases, list):
        return None, err or "bad_cases"
    func = _import_sum_nonnegatives(app_py)
    if func is None or not callable(func):
        return None, "import_error"

    try:
        total = len(cases)
        passed = 0
        results = []
        for c in cases:
            if not isinstance(c, dict):
                return None, "bad_case_item"
            inp = c.get("input", [])
            expected = c.get("expected")
            actual = func(inp)
            ok = (actual == expected)
            passed += 1 if ok else 0
            results.append({"input": inp, "expected": expected, "actual": actual, "ok": ok})
        failed = total - passed
        return {"total": total, "passed": passed, "failed": failed, "cases": results}, None
    except Exception as e:
        return None, f"exec_error:{e}"


def _find_step(steps: Any, name: str) -> int:
    if not isinstance(steps, list):
        return -1
    for i, s in enumerate(steps):
        if isinstance(s, dict) and s.get("name") == name:
            return i
    return -1


def _parse_summary_md(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        # Extract duration: line "Total duration (s): <value>"
        dur_match = re.search(r"^Total duration \(s\):\s*([0-9]+(?:\.[0-9]+)?)\s*$", text, re.MULTILINE)
        tests_match = re.search(
            r"^Tests\s*-\s*total:\s*([0-9]+),\s*passed:\s*([0-9]+),\s*failed:\s*([0-9]+)\s*$",
            text,
            re.MULTILINE,
        )
        if not dur_match or not tests_match:
            return None, "missing_fields"
        duration = float(dur_match.group(1))
        total = int(tests_match.group(1))
        passed = int(tests_match.group(2))
        failed = int(tests_match.group(3))
        return {
            "total_duration_seconds": duration,
            "tests": {"total": total, "passed": passed, "failed": failed},
        }, None
    except Exception as e:
        return None, f"parse_error:{e}"


def _contains_phrase_ci_change(text: str) -> bool:
    # Must state that a unit-test step was added to .ci/pipeline.json
    # Accept flexible phrasing: look for .ci/pipeline.json and unit test mention and "step"
    t = text.lower()
    has_path = ".ci/pipeline.json" in t
    has_unit = ("unit-test" in t) or ("unit tests" in t) or ("unit test" in t)
    has_step = "step" in t
    return has_path and has_unit and has_step


def _contains_phrase_function_fix(text: str) -> bool:
    # Must state that sum_nonnegatives in app/app.py was fixed to ignore negatives
    t = text.lower()
    return ("sum_nonnegatives" in t) and ("app/app.py" in t) and ("ignore" in t) and ("negative" in t)


def _email_includes_metrics(text: str, logs: Dict[str, Any]) -> bool:
    # The email must include metrics exactly as they appear in ci_logs.json:
    # tests total, tests passed, tests failed, and total_duration_seconds.
    # We will search for patterns combining labels and their values within the same line.
    try:
        tests = logs.get("tests", {})
        total = tests.get("total")
        passed = tests.get("passed")
        failed = tests.get("failed")
        duration = logs.get("total_duration_seconds")
        if not isinstance(total, int) or not isinstance(passed, int) or not isinstance(failed, int):
            return False
        if not (isinstance(duration, int) or isinstance(duration, float)):
            return False

        # Prepare value strings
        total_str = str(total)
        passed_str = str(passed)
        failed_str = str(failed)
        # For duration, accept both default str and json.dumps formatting
        duration_strs = {str(duration), json.dumps(duration)}

        # Build regex patterns to ensure labels and numbers appear in order on the same line
        # Case-insensitive, allow any non-newline chars between tokens
        def has_pattern(label1: str, label2: str, value: str) -> bool:
            pat = re.compile(rf"{label1}[^\n\r]*{label2}[^\n\r]*{re.escape(value)}", re.IGNORECASE)
            if pat.search(text):
                return True
            # Try reversed order of labels (e.g., "total tests: X")
            pat2 = re.compile(rf"{label2}[^\n\r]*{label1}[^\n\r]*{re.escape(value)}", re.IGNORECASE)
            return bool(pat2.search(text))

        tests_total_ok = has_pattern("tests", "total", total_str)
        tests_passed_ok = has_pattern("tests", "passed", passed_str)
        tests_failed_ok = has_pattern("tests", "failed", failed_str)

        # Duration: require literal key name and exact numeric value presence on same line
        duration_ok = False
        for ds in duration_strs:
            if re.search(rf"total_duration_seconds[^\n\r]*{re.escape(ds)}", text, re.IGNORECASE):
                duration_ok = True
                break

        return tests_total_ok and tests_passed_ok and tests_failed_ok and duration_ok
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "function_passes_all_cases": 0.0,
        "pipeline_unit_tests_step_present": 0.0,
        "pipeline_unit_tests_order_correct": 0.0,
        "pipeline_unit_tests_command_exact": 0.0,
        "test_results_artifact_valid_and_matches": 0.0,
        "ci_logs_valid_and_matches": 0.0,
        "ci_steps_include_unit_tests": 0.0,
        "ci_summary_consistent_with_logs": 0.0,
        "email_file_exists": 0.0,
        "email_describes_changes": 0.0,
        "email_includes_required_metrics": 0.0,
        "email_references_required_artifacts": 0.0,
    }

    # Compute expected metrics from tests and current function
    expected_metrics, expected_err = _compute_test_metrics(workspace)
    if expected_metrics and expected_err is None:
        if expected_metrics.get("failed") == 0:
            scores["function_passes_all_cases"] = 1.0

    # Check pipeline config
    pipeline_path = workspace / ".ci" / "pipeline.json"
    pipeline, pipe_err = _load_json(pipeline_path)
    steps = []
    if pipe_err is None and isinstance(pipeline, dict):
        steps = pipeline.get("steps", [])
        idx_unit = _find_step(steps, "unit-tests")
        if idx_unit != -1:
            scores["pipeline_unit_tests_step_present"] = 1.0
            # Command exactness
            step_obj = steps[idx_unit] if isinstance(steps, list) and idx_unit < len(steps) else {}
            cmd = step_obj.get("run") if isinstance(step_obj, dict) else None
            if cmd == "python tests/run_tests.py --out output/test_results.json":
                scores["pipeline_unit_tests_command_exact"] = 1.0
            # Order after build (immediately after)
            idx_build = _find_step(steps, "build")
            if idx_build != -1 and (idx_build + 1) == idx_unit:
                scores["pipeline_unit_tests_order_correct"] = 1.0

    # Validate test_results.json
    test_results_path = workspace / "output" / "test_results.json"
    tr_json, tr_err = _load_json(test_results_path)
    if tr_err is None and isinstance(tr_json, dict):
        tr_total = tr_json.get("total")
        tr_passed = tr_json.get("passed")
        tr_failed = tr_json.get("failed")
        # Ensure types
        if all(isinstance(x, int) for x in [tr_total, tr_passed, tr_failed]):
            if expected_metrics is not None:
                if (
                    tr_total == expected_metrics.get("total")
                    and tr_passed == expected_metrics.get("passed")
                    and tr_failed == expected_metrics.get("failed")
                ):
                    scores["test_results_artifact_valid_and_matches"] = 1.0

    # Validate ci_logs.json and steps presence
    ci_logs_path = workspace / "output" / "ci_logs.json"
    ci_logs, logs_err = _load_json(ci_logs_path)
    if logs_err is None and isinstance(ci_logs, dict):
        tests_obj = ci_logs.get("tests", {})
        l_total = tests_obj.get("total")
        l_passed = tests_obj.get("passed")
        l_failed = tests_obj.get("failed")
        l_duration = ci_logs.get("total_duration_seconds")
        # Validate types
        types_ok = (
            isinstance(l_total, int)
            and isinstance(l_passed, int)
            and isinstance(l_failed, int)
            and (isinstance(l_duration, float) or isinstance(l_duration, int))
        )
        # Match expected
        matches_expected = False
        if types_ok and expected_metrics is not None:
            matches_expected = (
                l_total == expected_metrics.get("total")
                and l_passed == expected_metrics.get("passed")
                and l_failed == expected_metrics.get("failed")
            )
        if types_ok and matches_expected:
            scores["ci_logs_valid_and_matches"] = 1.0

        # steps include unit-tests
        steps_log = ci_logs.get("steps", [])
        if isinstance(steps_log, list):
            names = [s.get("name") for s in steps_log if isinstance(s, dict)]
            if "unit-tests" in names:
                scores["ci_steps_include_unit_tests"] = 1.0

    # Validate ci_summary.md content consistent with ci_logs.json
    summary_path = workspace / "output" / "ci_summary.md"
    summary_text, sm_err = _read_text(summary_path)
    if sm_err is None and isinstance(summary_text, str):
        parsed_summary, ps_err = _parse_summary_md(summary_text)
        if ps_err is None and isinstance(parsed_summary, dict) and isinstance(ci_logs, dict):
            tests_ok = (
                parsed_summary.get("tests", {}).get("total") == ci_logs.get("tests", {}).get("total")
                and parsed_summary.get("tests", {}).get("passed") == ci_logs.get("tests", {}).get("passed")
                and parsed_summary.get("tests", {}).get("failed") == ci_logs.get("tests", {}).get("failed")
            )
            dur_ok = parsed_summary.get("total_duration_seconds") == ci_logs.get("total_duration_seconds")
            if tests_ok and dur_ok:
                scores["ci_summary_consistent_with_logs"] = 1.0

    # Email checks
    email_path = workspace / "output" / "ci_announcement_email.txt"
    email_text, em_err = _read_text(email_path)
    if em_err is None and isinstance(email_text, str) and email_text.strip():
        scores["email_file_exists"] = 1.0

        # Describes changes
        if email_text:
            if _contains_phrase_ci_change(email_text) and _contains_phrase_function_fix(email_text):
                scores["email_describes_changes"] = 1.0

        # Includes metrics from logs
        if isinstance(ci_logs, dict):
            if _email_includes_metrics(email_text or "", ci_logs):
                scores["email_includes_required_metrics"] = 1.0

        # References artifacts
        if "output/test_results.json" in (email_text or "") and "output/ci_summary.md" in (email_text or ""):
            scores["email_references_required_artifacts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()