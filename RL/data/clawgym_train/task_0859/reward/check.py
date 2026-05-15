import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _read_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _json_equal_strict(a: Any, b: Any) -> bool:
    if type(a) != type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        for k in a.keys():
            if not _json_equal_strict(a[k], b[k]):
                return False
        return True
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        for i in range(len(a)):
            if not _json_equal_strict(a[i], b[i]):
                return False
        return True
    return a == b


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "tests_file_present": 0.0,
        "tests_validate_valid_data_against_expected": 0.0,
        "tests_cli_valid_writes_summary": 0.0,
        "tests_cli_invalid_checks_error_message": 0.0,
        "test_report_verbose": 0.0,
        "out_summary_matches_expected": 0.0,
        "invalid_stderr_contains_required": 0.0,
        "messages_improved_in_reef_metrics": 0.0,
        "messages_improved_in_run_script": 0.0,
    }

    # Paths
    tests_file = workspace / "tests" / "test_reef_metrics.py"
    expected_summary_path = workspace / "expected" / "valid_summary.json"
    produced_summary_path = workspace / "workspace" / "out" / "summary.json"
    test_report_path = workspace / "workspace" / "out" / "test_report.txt"
    invalid_stderr_path = workspace / "workspace" / "out" / "invalid_run.stderr.txt"
    reef_metrics_py = workspace / "src" / "reef_metrics.py"
    run_script_py = workspace / "src" / "run_reef_analysis.py"

    # 1) tests/test_reef_metrics.py existence and content coverage
    if tests_file.exists():
        scores["tests_file_present"] = 1.0
        test_text, _ = _read_text_safe(tests_file)
        if test_text is None:
            test_text = ""
        lower_text = test_text.lower()

        # Test A: validate calculations against expected summary and file paths referenced
        has_load_compute = ("load_csv" in test_text and "compute_metrics" in test_text)
        references_valid_inputs = ("data/reef_valid.csv" in test_text and "expected/valid_summary.json" in test_text)
        # Look for equality assertions for dicts (assertEqual/assertDictEqual) comparing expected and actual
        has_dict_equality_assert = ("assertEqual" in test_text or "assertDictEqual" in test_text)
        if has_load_compute and references_valid_inputs and has_dict_equality_assert:
            scores["tests_validate_valid_data_against_expected"] = 1.0

        # Test A (CLI path): running module with -m and writing workspace/out/summary.json
        mentions_module = ("src.run_reef_analysis" in test_text)
        mentions_dash_m = ("-m" in test_text)
        mentions_subprocess = ("subprocess" in test_text)
        mentions_summary_out = ("workspace/out/summary.json" in test_text or "workspace/out" in test_text)
        if mentions_module and mentions_dash_m and mentions_subprocess and mentions_summary_out:
            scores["tests_cli_valid_writes_summary"] = 1.0

        # Test B: invalid data error handling checks
        references_invalid_input = ("data/reef_invalid.csv" in test_text)
        checks_required_substrings = ("row=3" in test_text and "temp_c" in test_text)
        checks_no_bad_data = ("bad data" not in lower_text)
        # Expect stderr capture/assertions present
        mentions_stderr = ("stderr" in lower_text or "capture" in lower_text)
        if references_invalid_input and checks_required_substrings and checks_no_bad_data and mentions_stderr:
            scores["tests_cli_invalid_checks_error_message"] = 1.0

    # 2) test report: ensure verbose run output captured
    if test_report_path.exists():
        report_text, _ = _read_text_safe(test_report_path)
        if report_text is None:
            report_text = ""
        # Must look like a verbose unittest run
        ran_line = "Ran " in report_text
        # Look for test result lines with verbosity (ok/FAIL/ERROR)
        has_verbose_tests = bool(re.search(r"test_[^\n]*\.\.\. (ok|OK|FAIL|ERROR)", report_text))
        if ran_line and has_verbose_tests:
            scores["test_report_verbose"] = 1.0

    # 3) summary.json matches expected strictly
    expected_json, _ = _read_json_safe(expected_summary_path)
    produced_json, _ = _read_json_safe(produced_summary_path)
    if expected_json is not None and produced_json is not None:
        if _json_equal_strict(expected_json, produced_json):
            scores["out_summary_matches_expected"] = 1.0

    # 4) invalid stderr contains required substrings and excludes "bad data"
    if invalid_stderr_path.exists():
        stderr_text, _ = _read_text_safe(invalid_stderr_path)
        if stderr_text is None:
            stderr_text = ""
        has_input = "data/reef_invalid.csv" in stderr_text
        has_row = "row=3" in stderr_text
        has_field = "temp_c" in stderr_text
        no_bad_data_phrase = ("bad data" not in stderr_text.lower())
        if has_input and has_row and has_field and no_bad_data_phrase:
            scores["invalid_stderr_contains_required"] = 1.0

    # 5) Improved error messages in source files (ensure "bad data" removed)
    if reef_metrics_py.exists():
        metrics_text, _ = _read_text_safe(reef_metrics_py)
        if metrics_text is not None:
            if "bad data" not in metrics_text.lower():
                scores["messages_improved_in_reef_metrics"] = 1.0
    if run_script_py.exists():
        run_text, _ = _read_text_safe(run_script_py)
        if run_text is not None:
            if "bad data" not in run_text.lower():
                scores["messages_improved_in_run_script"] = 1.0

    # Return sorted keys for deterministic output
    ordered_scores = {k: scores[k] for k in sorted(scores.keys())}
    return ordered_scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()