import json
import sys
import subprocess
import tempfile
from pathlib import Path


def _safe_load_json(path: Path):
    try:
        if not path.exists() or not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _validate_report(report: dict, expected_files: list) -> bool:
    if not isinstance(report, dict):
        return False
    if not report.get("overall_pass", False):
        return False
    files = report.get("files")
    summary = report.get("summary", {})
    if not isinstance(files, dict):
        return False
    # Ensure all expected files are present and fully passing
    for fname in expected_files:
        if fname not in files:
            return False
        entry = files.get(fname, {})
        if not isinstance(entry, dict):
            return False
        if not entry.get("file_pass", False):
            return False
        checks = entry.get("checks", {})
        if not isinstance(checks, dict):
            return False
        # All individual checks must be True
        if not all(bool(v) for v in checks.values()):
            return False
    # Ensure counts are consistent and exactly match the expected files
    files_checked = summary.get("files_checked")
    files_failed = summary.get("files_failed")
    files_passed = summary.get("files_passed")
    if files_checked != len(expected_files):
        return False
    if files_failed != 0:
        return False
    if files_passed != len(expected_files):
        return False
    return True


def _run_checker(workspace: Path, site_dir: Path, keywords: Path, checker: Path):
    """
    Run the provided SEO checker script with fail-on-issues to validate the site.
    Returns (ran_ok: bool, exit_code: int or None, report: dict or None)
    """
    if not checker.exists() or not site_dir.exists() or not keywords.exists():
        return False, None, None
    try:
        with tempfile.NamedTemporaryFile(prefix="seo_report_", suffix=".json", delete=False) as tf:
            out_path = Path(tf.name)
        cmd = [
            sys.executable,
            str(checker),
            "--site-dir", str(site_dir),
            "--keywords", str(keywords),
            "--out", str(out_path),
            "--fail-on-issues",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        exit_code = proc.returncode
        report = _safe_load_json(out_path)
        # Clean up temp file
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return True, exit_code, report
    except Exception:
        return False, None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists_and_passes": 0.0,
        "rerun_checker_pass": 0.0,
        "index_page_pass": 0.0,
        "phenomenology_intro_page_pass": 0.0,
        "neural_correlates_page_pass": 0.0,
    }

    expected_files = ["index.html", "phenomenology-intro.html", "neural-correlates.html"]

    # Check final report exists and passes
    report_path = workspace / "outputs" / "seo_report.json"
    report = _safe_load_json(report_path)
    if report is not None and _validate_report(report, expected_files):
        scores["report_exists_and_passes"] = 1.0

    # Re-run checker to ensure it passes deterministically
    checker = workspace / "input" / "seo_check.py"
    site_dir = workspace / "site"
    keywords = workspace / "input" / "keywords.json"
    ran_ok, exit_code, rerun_report = _run_checker(workspace, site_dir, keywords, checker)
    if ran_ok and exit_code == 0 and rerun_report is not None and _validate_report(rerun_report, expected_files):
        scores["rerun_checker_pass"] = 1.0

    # Use rerun report if available and valid structure; otherwise fall back to existing report
    effective_report = rerun_report if isinstance(rerun_report, dict) else report if isinstance(report, dict) else None

    # Per-page checks: each page must be present in the report and fully pass all checks
    per_page_map = {
        "index_page_pass": "index.html",
        "phenomenology_intro_page_pass": "phenomenology-intro.html",
        "neural_correlates_page_pass": "neural-correlates.html",
    }
    if isinstance(effective_report, dict) and isinstance(effective_report.get("files"), dict):
        files = effective_report["files"]
        for score_key, fname in per_page_map.items():
            entry = files.get(fname)
            if isinstance(entry, dict) and entry.get("file_pass", False):
                checks = entry.get("checks", {})
                if isinstance(checks, dict) and all(bool(v) for v in checks.values()):
                    scores[score_key] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()