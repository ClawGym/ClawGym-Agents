import io
import json
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json_file(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _timestamp_is_iso_z(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts) is not None


def _run_tests_and_get_counts(workspace: Path, tests_dir: str = "tests") -> Optional[Dict[str, int]]:
    tests_path = workspace / tests_dir
    if not tests_path.exists():
        return {"tests_run": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        loader = unittest.TestLoader()
        suite = loader.discover(start_dir=str(tests_path), pattern="test*.py")
        stream = io.StringIO()
        runner = unittest.TextTestRunner(stream=stream, verbosity=1)
        result = runner.run(suite)
        skipped_count = 0
        if hasattr(result, "skipped"):
            skipped_count = len(result.skipped)  # type: ignore[attr-defined]
        return {
            "tests_run": int(result.testsRun),
            "failures": int(len(result.failures)),
            "errors": int(len(result.errors)),
            "skipped": int(skipped_count),
        }
    except Exception:
        return None


def _parse_unittest_text_summary(text: str) -> Tuple[Optional[int], Optional[str]]:
    tests_run = None
    status = None
    m = re.search(r"Ran\s+(\d+)\s+tests?", text)
    if m:
        try:
            tests_run = int(m.group(1))
        except Exception:
            tests_run = None
    if re.search(r"^\s*OK\s*$", text, re.MULTILINE):
        status = "OK"
    elif re.search(r"^\s*FAILED\b", text, re.MULTILINE):
        status = "FAILED"
    return tests_run, status


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _count_bullet_lines(text: str) -> Tuple[int, list]:
    bullet_lines = []
    for line in text.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            bullet_lines.append(line.strip())
    return len(bullet_lines), bullet_lines


def _detect_config_reading(ci_runner_text: str) -> bool:
    # Require evidence of actual file I/O with the specific config path, not just comments
    patterns = [
        r"open\(\s*[\"']\.ci/config\.yaml[\"']",
        r"Path\(\s*[\"']\.ci/config\.yaml[\"']\)\s*\.\s*read_text\(",
        r"Path\(\s*[\"']\.ci[\"']\s*\)\s*/\s*[\"']config\.yaml[\"'].*?\.read_text\(",
    ]
    for pat in patterns:
        if re.search(pat, ci_runner_text, flags=re.DOTALL):
            return True
    return False


def _detect_exit_logic(ci_runner_text: str) -> bool:
    # Require a sys.exit call and explicit zero-checks for failures and errors
    has_sys_exit = "sys.exit(" in ci_runner_text
    has_failures_check = re.search(r"failures?\s*==\s*0", ci_runner_text) is not None
    has_errors_check = re.search(r"errors?\s*==\s*0", ci_runner_text) is not None
    return has_sys_exit and has_failures_check and has_errors_check


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ci_runner_contains_config_reading": 0.0,
        "ci_runner_uses_unittest": 0.0,
        "ci_runner_prints_summary_phrase": 0.0,
        "ci_runner_exit_logic_present": 0.0,
        "test_results_text_present": 0.0,
        "test_summary_json_schema_valid": 0.0,
        "results_counts_consistent_with_tests": 0.0,
        "text_results_contains_counts_and_status": 0.0,
        "workflow_contains_checkout": 0.0,
        "workflow_contains_setup_python": 0.0,
        "workflow_contains_run_step": 0.0,
        "workflow_contains_upload_artifact": 0.0,
        "ci_status_overview_mentions_changes": 0.0,
        "ci_status_results_section_matches_json": 0.0,
        "ci_status_artifacts_section_paths": 0.0,
        "slack_rewrite_word_count_under_120": 0.0,
        "slack_rewrite_first_line_one_sentence": 0.0,
        "slack_rewrite_two_bullets": 0.0,
        "slack_rewrite_bullet_1_reports_path": 0.0,
        "slack_rewrite_bullet_2_review_workflow": 0.0,
        "email_has_subject_line": 0.0,
        "email_mentions_reproducibility": 0.0,
        "email_includes_metrics": 0.0,
        "email_mentions_artifacts_and_workflow": 0.0,
        "email_addresses_working_group": 0.0,
    }

    ci_runner_path = workspace / "ci_runner.py"
    workflow_path = workspace / ".github" / "workflows" / "ci.yml"
    text_results_path = workspace / "out" / "reports" / "test_results.txt"
    json_summary_path = workspace / "out" / "reports" / "test_summary.json"
    ci_status_path = workspace / "out" / "CI_STATUS.md"
    slack_rewrite_path = workspace / "out" / "slack_message_rewrite.txt"
    email_announcement_path = workspace / "out" / "email_announcement.txt"

    ci_runner_text = _read_text_file(ci_runner_path)
    if ci_runner_text is not None:
        if _detect_config_reading(ci_runner_text):
            scores["ci_runner_contains_config_reading"] = 1.0
        if ("import unittest" in ci_runner_text or "from unittest" in ci_runner_text) and (
            "TestLoader" in ci_runner_text or "discover(" in ci_runner_text or "TextTestRunner" in ci_runner_text
        ):
            scores["ci_runner_uses_unittest"] = 1.0
        if re.search(r"print\([^)]*CI runner completed:", ci_runner_text):
            scores["ci_runner_prints_summary_phrase"] = 1.0
        if _detect_exit_logic(ci_runner_text):
            scores["ci_runner_exit_logic_present"] = 1.0

    text_results_content = _read_text_file(text_results_path)
    if text_results_content and text_results_content.strip():
        scores["test_results_text_present"] = 1.0

    summary = _read_json_file(json_summary_path)
    schema_ok = False
    if isinstance(summary, dict):
        expected_keys = {"tests_run", "failures", "errors", "skipped", "timestamp"}
        if set(summary.keys()) == expected_keys:
            types_ok = (
                isinstance(summary.get("tests_run"), int)
                and isinstance(summary.get("failures"), int)
                and isinstance(summary.get("errors"), int)
                and isinstance(summary.get("skipped"), int)
                and isinstance(summary.get("timestamp"), str)
            )
            ts_ok = _timestamp_is_iso_z(summary.get("timestamp"))  # type: ignore[arg-type]
            if types_ok and ts_ok:
                schema_ok = True
    scores["test_summary_json_schema_valid"] = 1.0 if schema_ok else 0.0

    expected_counts = _run_tests_and_get_counts(workspace, tests_dir="tests")
    if isinstance(summary, dict) and isinstance(expected_counts, dict):
        try:
            match = (
                int(summary.get("tests_run")) == int(expected_counts.get("tests_run"))  # type: ignore[arg-type]
                and int(summary.get("failures")) == int(expected_counts.get("failures"))  # type: ignore[arg-type]
                and int(summary.get("errors")) == int(expected_counts.get("errors"))  # type: ignore[arg-type]
                and int(summary.get("skipped")) == int(expected_counts.get("skipped"))  # type: ignore[arg-type]
            )
            if match:
                scores["results_counts_consistent_with_tests"] = 1.0
        except Exception:
            pass

    if text_results_content and isinstance(summary, dict):
        tr, status = _parse_unittest_text_summary(text_results_content)
        try:
            expected_tr = int(summary.get("tests_run"))  # type: ignore[arg-type]
            expected_fail = int(summary.get("failures"))  # type: ignore[arg-type]
            expected_err = int(summary.get("errors"))  # type: ignore[arg-type]
            ok_expected = (expected_fail == 0 and expected_err == 0)
            status_expected = "OK" if ok_expected else "FAILED"
            if tr == expected_tr and status == status_expected:
                scores["text_results_contains_counts_and_status"] = 1.0
        except Exception:
            pass

    workflow_text = _read_text_file(workflow_path)
    if workflow_text:
        if "actions/checkout" in workflow_text:
            scores["workflow_contains_checkout"] = 1.0
        if "actions/setup-python" in workflow_text or "setup-python" in workflow_text:
            scores["workflow_contains_setup_python"] = 1.0
        if re.search(r"run:\s*python\s+ci_runner\.py", workflow_text):
            scores["workflow_contains_run_step"] = 1.0
        upload_ok = ("upload-artifact" in workflow_text and "out/reports" in workflow_text and "ci-reports" in workflow_text)
        if upload_ok:
            scores["workflow_contains_upload_artifact"] = 1.0

    ci_status_text = _read_text_file(ci_status_path)
    if ci_status_text:
        overview_ok = False
        # Expect mentions of implemented ci_runner.py, standardized outputs, and updated workflow upload
        has_runner = "ci_runner.py" in ci_status_text
        has_workflow = ".github/workflows/ci.yml" in ci_status_text
        has_standardized_outputs = re.search(r"standardi[sz]ed\s+outputs?", ci_status_text, flags=re.IGNORECASE) is not None
        has_upload_artifacts = re.search(r"upload(?:ing)?\s+artifact", ci_status_text, flags=re.IGNORECASE) is not None or "artifacts" in ci_status_text.lower()
        if has_runner and has_workflow and has_standardized_outputs and has_upload_artifacts:
            overview_ok = True
        scores["ci_status_overview_mentions_changes"] = 1.0 if overview_ok else 0.0

        results_ok = False
        if isinstance(summary, dict):
            m_tr = re.search(r"Tests\s*run:\s*(\d+)", ci_status_text, flags=re.IGNORECASE)
            m_fail = re.search(r"Failures:\s*(\d+)", ci_status_text, flags=re.IGNORECASE)
            m_err = re.search(r"Errors:\s*(\d+)", ci_status_text, flags=re.IGNORECASE)
            m_skip = re.search(r"Skipped:\s*(\d+)", ci_status_text, flags=re.IGNORECASE)
            try:
                if all([m_tr, m_fail, m_err, m_skip]):
                    results_ok = (
                        int(m_tr.group(1)) == int(summary.get("tests_run"))  # type: ignore[arg-type]
                        and int(m_fail.group(1)) == int(summary.get("failures"))  # type: ignore[arg-type]
                        and int(m_err.group(1)) == int(summary.get("errors"))  # type: ignore[arg-type]
                        and int(m_skip.group(1)) == int(summary.get("skipped"))  # type: ignore[arg-type]
                    )
            except Exception:
                results_ok = False
        scores["ci_status_results_section_matches_json"] = 1.0 if results_ok else 0.0

        artifacts_ok = (
            "out/reports/test_results.txt" in ci_status_text and "out/reports/test_summary.json" in ci_status_text
        )
        scores["ci_status_artifacts_section_paths"] = 1.0 if artifacts_ok else 0.0

    slack_text = _read_text_file(slack_rewrite_path)
    if slack_text:
        if _word_count(slack_text) <= 120:
            scores["slack_rewrite_word_count_under_120"] = 1.0
        first_line = _first_nonempty_line(slack_text) or ""
        if first_line and not re.match(r"^\s*[-*]\s+", first_line):
            # Count terminal punctuation in the first sentence line
            enders = re.findall(r"[.!?]", first_line)
            if len(enders) == 1:
                scores["slack_rewrite_first_line_one_sentence"] = 1.0
        n_bullets, bullet_lines = _count_bullet_lines(slack_text)
        if n_bullets == 2:
            scores["slack_rewrite_two_bullets"] = 1.0
            b1 = bullet_lines[0].lower()
            if "out/reports" in b1:
                scores["slack_rewrite_bullet_1_reports_path"] = 1.0
            b2 = bullet_lines[1].lower()
            if ".github/workflows/ci.yml" in b2 and (("review" in b2) or ("look" in b2)):
                scores["slack_rewrite_bullet_2_review_workflow"] = 1.0

    email_text = _read_text_file(email_announcement_path)
    if email_text:
        first_line = email_text.splitlines()[0] if email_text.splitlines() else ""
        if first_line.strip().lower().startswith("subject:"):
            scores["email_has_subject_line"] = 1.0
        if re.search(r"reproduc", email_text, flags=re.IGNORECASE):
            scores["email_mentions_reproducibility"] = 1.0
        metrics_ok = False
        if isinstance(summary, dict):
            try:
                contains_all = (
                    str(int(summary.get("tests_run"))) in email_text  # type: ignore[arg-type]
                    and str(int(summary.get("failures"))) in email_text  # type: ignore[arg-type]
                    and str(int(summary.get("errors"))) in email_text  # type: ignore[arg-type]
                    and str(int(summary.get("skipped"))) in email_text  # type: ignore[arg-type]
                )
                metrics_ok = contains_all
            except Exception:
                metrics_ok = False
        scores["email_includes_metrics"] = 1.0 if metrics_ok else 0.0
        if ("out/reports" in email_text) and (".github/workflows/ci.yml" in email_text):
            scores["email_mentions_artifacts_and_workflow"] = 1.0
        if re.search(r"Policy Outreach Working Group", email_text, flags=re.IGNORECASE):
            scores["email_addresses_working_group"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()