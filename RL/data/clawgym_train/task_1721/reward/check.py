import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _contains_any(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        if p in text:
            return True
    return False


def _contains_number_repr(text: str, value: float, extra_tokens: List[str] = None) -> bool:
    if extra_tokens is None:
        extra_tokens = []
    reprs = set(extra_tokens)
    # Generate multiple decimal representations
    for places in range(1, 9):
        reprs.add(f"{value:.{places}f}")
    # Also add trimmed minimal repr
    reprs.add(str(value))
    # For 2/3 and 1/2 special cases
    if abs(value - (2 / 3)) < 1e-9:
        reprs.update(["2/3", "two-thirds"])
    if abs(value - 0.5) < 1e-9:
        reprs.update(["1/2", "one-half", "one half"])
    # Check any occurrence
    return _contains_any(text, list(reprs))


def _compute_expected_from_sample(input_csv: Path, poverty_line: float) -> Optional[Dict[str, Dict[str, float]]]:
    rows = _read_csv_dicts_safe(input_csv)
    if rows is None:
        return None
    # Group by region
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    poor_counts: Dict[str, int] = {}
    for r in rows:
        try:
            region = r["region"]
            inc = float(r["income"])
        except Exception:
            return None
        sums[region] = sums.get(region, 0.0) + inc
        counts[region] = counts.get(region, 0) + 1
        if inc < poverty_line:
            poor_counts[region] = poor_counts.get(region, 0) + 1
        else:
            poor_counts.setdefault(region, 0)
    means = {reg: sums[reg] / counts[reg] for reg in counts}
    correct_rates = {reg: poor_counts.get(reg, 0) / counts[reg] for reg in counts}
    total = sum(counts.values())
    buggy_rates = {reg: poor_counts.get(reg, 0) / total for reg in counts}
    return {"means": means, "correct_rates": correct_rates, "buggy_rates": buggy_rates}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tests_file_exists_and_unittest_import": 0.0,
        "tests_method_names_exact": 0.0,
        "tests_use_parse_and_expected_values": 0.0,
        "tests_cli_validation_elements": 0.0,
        "cli_log_exists_and_mentions_output": 0.0,
        "summary_csv_header_and_regions": 0.0,
        "summary_csv_mean_values_correct": 0.0,
        "summary_csv_poverty_rates_values": 0.0,
        "test_results_captured_with_names": 0.0,
        "docs_updated_with_section_and_values": 0.0,
        "email_drafted_with_requirements": 0.0,
    }

    # Tests content checks
    tests_path = workspace / "tests" / "test_partition_metrics.py"
    tests_text = _read_text_safe(tests_path)
    if tests_text is not None:
        # unittest import
        if re.search(r"\bimport\s+unittest\b", tests_text) or re.search(r"\bfrom\s+unittest\s+import\b", tests_text):
            scores["tests_file_exists_and_unittest_import"] = 1.0
        # method names
        has_mean = re.search(r"\bdef\s+test_mean_income_by_region\s*\(", tests_text) is not None
        has_pov = re.search(r"\bdef\s+test_poverty_rate_by_region\s*\(", tests_text) is not None
        has_cli = re.search(r"\bdef\s+test_cli_generates_summary_csv\s*\(", tests_text) is not None
        if has_mean and has_pov and has_cli:
            scores["tests_method_names_exact"] = 1.0
        # parse function and expected values presence
        uses_parse = "parse_household_income_csv" in tests_text
        expected_means_present = _contains_number_repr(tests_text, 233.3333333333) and _contains_number_repr(tests_text, 175.0)
        expected_rates_present = (_contains_number_repr(tests_text, 2/3) and _contains_number_repr(tests_text, 0.5))
        if uses_parse and expected_means_present and expected_rates_present:
            scores["tests_use_parse_and_expected_values"] = 1.0
        # CLI validation elements: header and path mention plus signs of subprocess/CLI usage and regions
        header_str = "region,mean_income,poverty_rate"
        mentions_header = header_str in tests_text
        mentions_output_path = "data/processed/summary.csv" in tests_text
        mentions_script = "scripts/partition_metrics.py" in tests_text
        hints_subprocess = ("subprocess" in tests_text) or ("run(" in tests_text) or ("Popen(" in tests_text)
        mentions_regions = ("A" in tests_text and "B" in tests_text)
        if mentions_header and mentions_output_path and mentions_script and hints_subprocess and mentions_regions:
            scores["tests_cli_validation_elements"] = 1.0

    # CLI run log and summary existence
    cli_log_path = workspace / "reports" / "cli_run_log.txt"
    cli_log_text = _read_text_safe(cli_log_path)
    if cli_log_text is not None and "Wrote summary to" in cli_log_text and "data/processed/summary.csv" in cli_log_text:
        scores["cli_log_exists_and_mentions_output"] = 1.0

    # Summary CSV checks
    summary_csv_path = workspace / "data" / "processed" / "summary.csv"
    summary_rows = _read_csv_dicts_safe(summary_csv_path)
    if summary_rows is not None and len(summary_rows) > 0:
        header_ok = False
        try:
            with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
                header_ok = (first_line == "region,mean_income,poverty_rate")
        except Exception:
            header_ok = False
        regions_found = sorted({r.get("region", "") for r in summary_rows if "region" in r})
        regions_ok = (set(regions_found) == {"A", "B"})
        if header_ok and regions_ok:
            scores["summary_csv_header_and_regions"] = 1.0

        # Parse values
        observed_means: Dict[str, float] = {}
        observed_rates: Dict[str, float] = {}
        try:
            for r in summary_rows:
                reg = r["region"]
                observed_means[reg] = float(r["mean_income"])
                observed_rates[reg] = float(r["poverty_rate"])
        except Exception:
            observed_means = {}
            observed_rates = {}

        # Compute expected values from input files
        cfg = _load_json_safe(workspace / "config" / "pipeline.json")
        input_csv_path = None
        poverty_line = None
        if cfg is not None:
            try:
                poverty_line = float(cfg["poverty_line"])
                input_csv_rel = cfg["input_csv"]
                input_csv_path = workspace / input_csv_rel
            except Exception:
                input_csv_path = None
                poverty_line = None

        expected_bundle = None
        if input_csv_path is not None and poverty_line is not None:
            expected_bundle = _compute_expected_from_sample(input_csv_path, poverty_line)

        if expected_bundle is not None and observed_means:
            means_ok = True
            for reg, exp_mean in expected_bundle["means"].items():
                obs = observed_means.get(reg)
                if obs is None or not _float_equal(obs, exp_mean, tol=1e-6):
                    means_ok = False
                    break
            if means_ok:
                scores["summary_csv_mean_values_correct"] = 1.0

        if expected_bundle is not None and observed_rates:
            # Accept either correct or buggy regional rates since tests are meant to reveal discrepancies
            rates_ok_correct = True
            for reg, exp_rate in expected_bundle["correct_rates"].items():
                obs = observed_rates.get(reg)
                if obs is None or not _float_equal(obs, exp_rate, tol=1e-6):
                    rates_ok_correct = False
                    break
            rates_ok_buggy = True
            for reg, exp_rate in expected_bundle["buggy_rates"].items():
                obs = observed_rates.get(reg)
                if obs is None or not _float_equal(obs, exp_rate, tol=1e-6):
                    rates_ok_buggy = False
                    break
            if rates_ok_correct or rates_ok_buggy:
                scores["summary_csv_poverty_rates_values"] = 1.0

    # Test results log checks
    test_results_path = workspace / "reports" / "test_results.txt"
    test_results_text = _read_text_safe(test_results_path)
    if test_results_text is not None:
        has_names = all(name in test_results_text for name in [
            "test_mean_income_by_region",
            "test_poverty_rate_by_region",
            "test_cli_generates_summary_csv",
        ])
        has_status = ("FAILED" in test_results_text) or ("OK" in test_results_text)
        ran_three = ("Ran 3 tests" in test_results_text) or re.search(r"Ran\s+3\s+test", test_results_text) is not None
        if has_names and has_status and ran_three:
            scores["test_results_captured_with_names"] = 1.0

    # Docs update checks
    analysis_md_path = workspace / "docs" / "analysis_plan.md"
    analysis_md_text = _read_text_safe(analysis_md_path)
    if analysis_md_text is not None:
        has_section_title = "Validation of income summary pipeline" in analysis_md_text
        mentions_expected = re.search(r"\bexpected\b", analysis_md_text, flags=re.IGNORECASE) is not None
        mentions_observed = re.search(r"\bobserved\b", analysis_md_text, flags=re.IGNORECASE) is not None
        mentions_discrepancy = re.search(r"\b(discrepanc|difference|mismatch)\w*\b", analysis_md_text, flags=re.IGNORECASE) is not None

        # Expected values presence (poverty rates and means for A and B)
        expected_rates_ok = _contains_number_repr(analysis_md_text, 2/3) and _contains_number_repr(analysis_md_text, 0.5)
        expected_means_ok = _contains_number_repr(analysis_md_text, 233.3333333333) and _contains_number_repr(analysis_md_text, 175.0)

        # Observed values presence based on summary.csv
        observed_values_ok = False
        if summary_rows is not None:
            try:
                obs_rates_map = {}
                for r in summary_rows:
                    obs_rates_map[r["region"]] = float(r["poverty_rate"])
                observed_values_ok = (_contains_number_repr(analysis_md_text, obs_rates_map.get("A", -1.0)) and
                                      _contains_number_repr(analysis_md_text, obs_rates_map.get("B", -1.0)))
            except Exception:
                observed_values_ok = False

        if has_section_title and mentions_expected and mentions_observed and mentions_discrepancy and expected_rates_ok and expected_means_ok and observed_values_ok:
            scores["docs_updated_with_section_and_values"] = 1.0

    # Email checks
    email_path = workspace / "outbox" / "email_to_ra.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        includes_paths = all(p in email_text for p in [
            "tests/test_partition_metrics.py",
            "reports/test_results.txt",
            "data/processed/summary.csv",
        ])
        requests_review = ("review" in email_text.lower()) and ("scripts/partition_metrics.py" in email_text)
        # Expected vs observed rates present
        expected_rates_present = _contains_number_repr(email_text, 2/3) and _contains_number_repr(email_text, 0.5)
        observed_rates_present = False
        if summary_rows is not None:
            try:
                obs_rates_map = {}
                for r in summary_rows:
                    obs_rates_map[r["region"]] = float(r["poverty_rate"])
                observed_rates_present = (_contains_number_repr(email_text, obs_rates_map.get("A", -1.0)) and
                                          _contains_number_repr(email_text, obs_rates_map.get("B", -1.0)))
            except Exception:
                observed_rates_present = False
        # General subject content: state what was tested and why
        mentions_tested_why = ("test" in email_text.lower()) and ("why" in email_text.lower() or "because" in email_text.lower() or "validation" in email_text.lower())
        if includes_paths and requests_review and expected_rates_present and observed_rates_present and mentions_tested_why:
            scores["email_drafted_with_requirements"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()