import json
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _run_cli_and_load(workspace: Path, input_csv: Path) -> Tuple[bool, Optional[dict]]:
    src_script = workspace / "src" / "monitor.py"
    if not src_script.exists() or not input_csv.exists():
        return False, None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "summary.json"
            cmd = [sys.executable, str(src_script), str(input_csv), "--out", str(out_path)]
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return False, None
            if not out_path.exists():
                return False, None
            data = _load_json(out_path)
            return (data is not None), data
    except Exception:
        return False, None


def _compare_numeric_summary(got: dict, exp: dict) -> bool:
    required_keys = ["count", "min", "max", "mean", "median"]
    if not isinstance(got, dict) or not isinstance(exp, dict):
        return False
    if set(got.keys()) != set(required_keys) or set(exp.keys()) != set(required_keys):
        return False
    try:
        if int(got["count"]) != int(exp["count"]):
            return False
        for k in ["min", "max", "mean", "median"]:
            gv = float(got[k]) if got[k] is not None else None
            ev = float(exp[k]) if exp[k] is not None else None
            if gv is None and ev is None:
                continue
            if gv is None or ev is None:
                return False
            if round(gv, 2) != round(ev, 2):
                return False
        return True
    except Exception:
        return False


def _extract_failing_got_values(failing_txt: str) -> Tuple[Optional[int], Optional[float]]:
    got_count = None
    got_mean = None
    try:
        for line in failing_txt.splitlines():
            line = line.strip()
            if line.startswith("- count: got"):
                try:
                    part = line.split("got", 1)[1]
                    num_str = part.split(",", 1)[0].strip()
                    got_count = int(num_str)
                except Exception:
                    pass
            if line.startswith("- mean: got"):
                try:
                    part = line.split("got", 1)[1]
                    num_str = part.split(",", 1)[0].strip()
                    got_mean = float(num_str)
                except Exception:
                    pass
    except Exception:
        pass
    return got_count, got_mean


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "cli_output_matches_expected": 0.0,
        "output_summary_matches_expected": 0.0,
        "monitor_py_bug_removed_and_cli_preserved": 0.0,
        "fix_report_includes_before_after_and_stats": 0.0,
        "email_draft_includes_values_and_artifacts": 0.0,
    }

    # Paths
    src_monitor = workspace / "src" / "monitor.py"
    input_csv = workspace / "data" / "sensor_readings.csv"
    expected_json_path = workspace / "tests" / "expected_summary.json"
    failing_txt_path = workspace / "tests" / "failing_test.txt"
    out_summary_path = workspace / "output" / "summary.json"
    fix_report_path = workspace / "output" / "fix_report.md"
    email_draft_path = workspace / "output" / "email_draft.txt"

    # Load expected JSON (if present)
    expected_json = _load_json(expected_json_path)

    # Check CLI run produces expected summary
    cli_ok, cli_summary = _run_cli_and_load(workspace, input_csv)
    if cli_ok and expected_json is not None and cli_summary is not None:
        if _compare_numeric_summary(cli_summary, expected_json):
            scores["cli_output_matches_expected"] = 1.0

    # Check output/summary.json exists and matches expected numerically
    out_summary = _load_json(out_summary_path)
    if out_summary is not None and expected_json is not None:
        if _compare_numeric_summary(out_summary, expected_json):
            scores["output_summary_matches_expected"] = 1.0

    # Check monitor.py no longer contains the buggy line and CLI preserved
    monitor_text = _read_text(src_monitor) or ""
    if monitor_text:
        bug_line_present = "count = len(values) - 1" in monitor_text
        cli_signature_preserved = "argparse.ArgumentParser" in monitor_text and "--out" in monitor_text and "parser.add_argument(\"input\"" in monitor_text
        if (not bug_line_present) and cli_signature_preserved:
            scores["monitor_py_bug_removed_and_cli_preserved"] = 1.0

    # Fix report checks
    fix_report_text = _read_text(fix_report_path) or ""
    failing_text = _read_text(failing_txt_path) or ""
    got_count, got_mean = _extract_failing_got_values(failing_text)
    corrected_count = None
    corrected_mean = None
    if out_summary is not None:
        try:
            corrected_count = int(out_summary.get("count"))
        except Exception:
            corrected_count = None
        try:
            corrected_mean = float(out_summary.get("mean"))
            corrected_mean = round(corrected_mean, 2)
        except Exception:
            corrected_mean = None

    fix_report_checks = []
    if fix_report_text:
        # Include exact buggy line and a plausible corrected line
        has_buggy_quote = "count = len(values) - 1" in fix_report_text
        has_corrected_quote = ("count = len(values)" in fix_report_text) or ("n = len(values)" in fix_report_text)
        fix_report_checks.append(has_buggy_quote and has_corrected_quote)
        # Include failing 'got' values for count and mean
        if got_count is not None:
            fix_report_checks.append(str(got_count) in fix_report_text)
        else:
            fix_report_checks.append(False)
        if got_mean is not None:
            fix_report_checks.append(f"{got_mean:.2f}" in fix_report_text or str(got_mean) in fix_report_text)
        else:
            fix_report_checks.append(False)
        # Include corrected count and mean from output/summary.json
        if corrected_count is not None:
            fix_report_checks.append(str(corrected_count) in fix_report_text)
        else:
            fix_report_checks.append(False)
        if corrected_mean is not None:
            fix_report_checks.append(f"{corrected_mean:.2f}" in fix_report_text or str(corrected_mean) in fix_report_text)
        else:
            fix_report_checks.append(False)
    if fix_report_checks and all(fix_report_checks):
        scores["fix_report_includes_before_after_and_stats"] = 1.0
    else:
        scores["fix_report_includes_before_after_and_stats"] = 0.0

    # Email draft checks
    email_text = _read_text(email_draft_path) or ""
    email_checks = []
    if email_text and corrected_count is not None and corrected_mean is not None:
        # Must mention artifacts
        email_checks.append("src/monitor.py" in email_text)
        email_checks.append("output/summary.json" in email_text)
        email_checks.append("output/fix_report.md" in email_text)
        # Must include corrected count and mean
        email_checks.append(str(corrected_count) in email_text)
        email_checks.append(f"{corrected_mean:.2f}" in email_text or str(corrected_mean) in email_text)
        # Should mention fix in functional terms
        functional_terms = any(term in email_text.lower() for term in ["fix", "fixed", "bug", "off-by-one", "wrong", "issue", "corrected"])
        email_checks.append(functional_terms)
    if email_checks and all(email_checks):
        scores["email_draft_includes_values_and_artifacts"] = 1.0
    else:
        scores["email_draft_includes_values_and_artifacts"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()