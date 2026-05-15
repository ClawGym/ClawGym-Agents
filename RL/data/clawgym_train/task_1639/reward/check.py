import json
import sys
import subprocess
import re
import csv
from statistics import mean as stats_mean, pstdev as stats_pstdev
from pathlib import Path
import importlib.util
from typing import Optional, Tuple, List


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_csv_values(workspace: Path) -> Optional[List[float]]:
    csv_path = workspace / "data" / "measurements.csv"
    if not csv_path.exists():
        return None
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "value" not in reader.fieldnames:
                return None
            values = []
            for row in reader:
                if row.get("value") is None:
                    return None
                try:
                    values.append(float(row["value"]))
                except Exception:
                    return None
            if not values:
                return None
            return values
    except Exception:
        return None


def _import_stats_utils(workspace: Path):
    src_path = workspace / "src" / "stats_utils.py"
    if not src_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("stats_utils", str(src_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _float_close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _run_pytest(workspace: Path) -> Tuple[Optional[int], Optional[str]]:
    try:
        proc = subprocess.run(
            ["pytest", "-q"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
            check=False,
        )
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, None


def _analyze_test_file(text: str) -> dict:
    info = {
        "has_import_statistics": False,
        "uses_statistics_mean": False,
        "uses_statistics_pstdev": False,
        "reads_csv_path": False,
        "mentions_value_header": False,
        "uses_abs_or_isclose_or_approx": False,
        "calls_stats_utils_mean": False,
        "calls_stats_utils_stdev": False,
        "imports_pytest": False,
        "negative_mean_raises": False,
        "negative_stdev_raises": False,
    }
    t = text

    if re.search(r"\bimport\s+statistics\b", t) or re.search(r"\bfrom\s+statistics\s+import\b", t):
        info["has_import_statistics"] = True

    uses_stats_mean = bool(re.search(r"statistics\s*\.\s*mean\s*\(", t)) or (
        bool(re.search(r"\bfrom\s+statistics\s+import\b.*\bmean\b", t)) and bool(re.search(r"(?<!stats_utils\.)\bmean\s*\(", t))
    )
    uses_stats_pstdev = bool(re.search(r"statistics\s*\.\s*pstdev\s*\(", t)) or (
        bool(re.search(r"\bfrom\s+statistics\s+import\b.*\bpstdev\b", t)) and bool(re.search(r"(?<!stats_utils\.)\bpstdev\s*\(", t))
    )
    info["uses_statistics_mean"] = uses_stats_mean
    info["uses_statistics_pstdev"] = uses_stats_pstdev

    if "data/measurements.csv" in t:
        info["reads_csv_path"] = True
    if re.search(r"\bvalue\b", t):
        info["mentions_value_header"] = True

    if re.search(r"\babs\s*\(", t) or re.search(r"\bmath\s*\.\s*isclose\s*\(", t) or re.search(r"\bpytest\s*\.\s*approx\b", t) or re.search(r"\bapprox\s*\(", t):
        info["uses_abs_or_isclose_or_approx"] = True

    if re.search(r"\bstats_utils\s*\.\s*mean\s*\(", t):
        info["calls_stats_utils_mean"] = True
    if re.search(r"\bstats_utils\s*\.\s*stdev\s*\(", t):
        info["calls_stats_utils_stdev"] = True

    if re.search(r"\bimport\s+pytest\b", t) or re.search(r"\bfrom\s+pytest\s+import\b", t):
        info["imports_pytest"] = True

    raises_blocks = [m.group(0) for m in re.finditer(r"with\s+pytest\s*\.\s*raises\s*\(\s*ValueError[^\)]*\)\s*:\s*(?:.+\n)+?", t)]
    mean_empty_patterns = [r"stats_utils\s*\.\s*mean\s*\(\s*\[\s*\]\s*\)", r"(?<!\w)mean\s*\(\s*\[\s*\]\s*\)"]
    stdev_empty_patterns = [r"stats_utils\s*\.\s*stdev\s*\(\s*\[\s*\]\s*\)", r"(?<!\w)stdev\s*\(\s*\[\s*\]\s*\)"]

    def _contains_pattern(patterns: List[str], text_block: str) -> bool:
        for p in patterns:
            if re.search(p, text_block):
                return True
        return False

    if raises_blocks:
        for block in raises_blocks:
            if _contains_pattern(mean_empty_patterns, block):
                info["negative_mean_raises"] = True
            if _contains_pattern(stdev_empty_patterns, block):
                info["negative_stdev_raises"] = True
    else:
        if re.search(r"pytest\s*\.\s*raises\s*\(\s*ValueError", t) and _contains_pattern(mean_empty_patterns, t):
            info["negative_mean_raises"] = True
        if re.search(r"pytest\s*\.\s*raises\s*\(\s*ValueError", t) and _contains_pattern(stdev_empty_patterns, t):
            info["negative_stdev_raises"] = True

    return info


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_file_exists": 0.0,
        "tests_use_statistics_module": 0.0,
        "tests_read_csv_value_column": 0.0,
        "tests_compare_with_tolerance": 0.0,
        "tests_call_stats_utils_functions": 0.0,
        "tests_negative_mean_raises_valueerror": 0.0,
        "tests_negative_stdev_raises_valueerror": 0.0,
        "src_stats_utils_correctness": 0.0,
        "artifacts_test_report_exists": 0.0,
        "artifacts_report_indicates_all_passed": 0.0,
        "pytest_all_tests_pass": 0.0,
    }

    test_path = workspace / "tests" / "test_stats_utils.py"
    test_text = _safe_read_text(test_path)
    if test_text is not None:
        scores["tests_file_exists"] = 1.0
        info = _analyze_test_file(test_text)
        if info["has_import_statistics"] and info["uses_statistics_mean"] and info["uses_statistics_pstdev"]:
            scores["tests_use_statistics_module"] = 1.0
        if info["reads_csv_path"] and info["mentions_value_header"]:
            scores["tests_read_csv_value_column"] = 1.0
        if info["uses_abs_or_isclose_or_approx"]:
            scores["tests_compare_with_tolerance"] = 1.0
        if info["calls_stats_utils_mean"] and info["calls_stats_utils_stdev"]:
            scores["tests_call_stats_utils_functions"] = 1.0
        if info["imports_pytest"] and info["negative_mean_raises"]:
            scores["tests_negative_mean_raises_valueerror"] = 1.0
        if info["imports_pytest"] and info["negative_stdev_raises"]:
            scores["tests_negative_stdev_raises_valueerror"] = 1.0

    values = _load_csv_values(workspace)
    module = _import_stats_utils(workspace)
    if values is not None and module is not None and hasattr(module, "mean") and hasattr(module, "stdev"):
        try:
            got_mean = module.mean(values)  # type: ignore[attr-defined]
            exp_mean = stats_mean(values)
            mean_ok = _float_close(got_mean, exp_mean, tol=1e-9)
        except Exception:
            mean_ok = False
        try:
            got_stdev = module.stdev(values)  # type: ignore[attr-defined]
            exp_stdev = stats_pstdev(values)
            stdev_ok = _float_close(got_stdev, exp_stdev, tol=1e-9)
        except Exception:
            stdev_ok = False
        try:
            raised_mean = False
            try:
                module.mean([])  # type: ignore[attr-defined]
            except ValueError:
                raised_mean = True
        except Exception:
            raised_mean = False
        try:
            raised_stdev = False
            try:
                module.stdev([])  # type: ignore[attr-defined]
            except ValueError:
                raised_stdev = True
        except Exception:
            raised_stdev = False

        if mean_ok and stdev_ok and raised_mean and raised_stdev:
            scores["src_stats_utils_correctness"] = 1.0

    report_path = workspace / "artifacts" / "test_report.txt"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        scores["artifacts_test_report_exists"] = 1.0
        lower = report_text.lower()
        passed = "passed" in lower
        failed = "failed" in lower
        error = "error" in lower or "errors" in lower
        if passed and not failed and not error:
            scores["artifacts_report_indicates_all_passed"] = 1.0

    rc, out = _run_pytest(workspace)
    if rc is not None and out is not None:
        ol = out.lower()
        if rc == 0 and ("failed" not in ol) and ("error" not in ol):
            scores["pytest_all_tests_pass"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()