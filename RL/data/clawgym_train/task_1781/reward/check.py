import json
import sys
import hashlib
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text_lines(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read().splitlines(), None
    except Exception as e:
        return None, str(e)


def _compute_sha256(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest(), None
    except Exception as e:
        return None, str(e)


def _count_csv_rows(path: Path) -> Tuple[Optional[int], Optional[str], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header_fields = list(reader.fieldnames or [])
            rows = sum(1 for _ in reader)
        return rows, None, header_fields
    except Exception as e:
        return None, str(e), None


def _list_all_files_relative(root: Path) -> List[str]:
    files: List[str] = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            # Normalize to forward slashes for comparison robustness
            files.append(rel.as_posix())
    return files


def _is_sorted_alpha(lst: List[str]) -> bool:
    return lst == sorted(lst)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "test_results_file_schema": 0.0,
        "test_results_all_tests_passed": 0.0,
        "validation_report_file_schema": 0.0,
        "validation_report_content_correct": 0.0,
        "tree_file_complete_listing": 0.0,
    }

    # Paths
    output_dir = workspace / "output"
    tests_results_path = output_dir / "test_results.json"
    validation_report_path = output_dir / "validation_report.json"
    tree_path = output_dir / "tree.txt"
    config_path = workspace / "config" / "validation.json"
    metadata_path = workspace / "input" / "metadata.json"
    data_path = workspace / "input" / "observations.csv"

    # Load files needed for validation report content checks
    cfg_data, cfg_err = _safe_load_json(config_path) if config_path.exists() else (None, "missing")
    meta_data, meta_err = _safe_load_json(metadata_path) if metadata_path.exists() else (None, "missing")
    csv_rows, csv_err, csv_header = _count_csv_rows(data_path) if data_path.exists() else (None, "missing", None)
    data_sha256, sha_err = _compute_sha256(data_path) if data_path.exists() else (None, "missing")

    # 1) Test results schema check
    test_results, tr_err = _safe_load_json(tests_results_path) if tests_results_path.exists() else (None, "missing")
    if isinstance(test_results, dict):
        total_ok = isinstance(test_results.get("total"), int)
        passed_ok = isinstance(test_results.get("passed"), int)
        failed_ok = isinstance(test_results.get("failed"), int)
        tests_list = test_results.get("tests")
        tests_ok = isinstance(tests_list, list)
        per_test_ok = True
        if tests_ok:
            for t in tests_list:
                if not isinstance(t, dict):
                    per_test_ok = False
                    break
                if not isinstance(t.get("name"), str):
                    per_test_ok = False
                    break
                if not isinstance(t.get("passed"), bool):
                    per_test_ok = False
                    break
                if not isinstance(t.get("message"), str):
                    per_test_ok = False
                    break
        math_ok = False
        if tests_ok and total_ok and passed_ok and failed_ok:
            calc_passed = sum(1 for t in tests_list if isinstance(t, dict) and t.get("passed") is True)
            math_ok = (test_results.get("total") == len(tests_list)
                       and test_results.get("passed") == calc_passed
                       and test_results.get("failed") == (len(tests_list) - calc_passed))
        if total_ok and passed_ok and failed_ok and tests_ok and per_test_ok and math_ok:
            scores["test_results_file_schema"] = 1.0
        else:
            scores["test_results_file_schema"] = 0.0
    else:
        scores["test_results_file_schema"] = 0.0

    # 2) Test results content check: expected four named tests and all passed
    expected_test_names = {
        "load_config_has_required_keys",
        "validate_no_missing_fields_or_columns",
        "sha256_consistency_independent",
        "config_version_propagated_to_report",
    }
    if isinstance(test_results, dict) and isinstance(test_results.get("tests"), list):
        names_found = {t.get("name") for t in test_results["tests"] if isinstance(t, dict) and isinstance(t.get("name"), str)}
        all_pass_true = all(isinstance(t, dict) and t.get("name") in expected_test_names and t.get("passed") is True for t in test_results["tests"])
        counts_ok = (test_results.get("total") == 4 and test_results.get("passed") == 4 and test_results.get("failed") == 0)
        names_ok = (names_found == expected_test_names)
        if all_pass_true and counts_ok and names_ok:
            scores["test_results_all_tests_passed"] = 1.0
        else:
            scores["test_results_all_tests_passed"] = 0.0
    else:
        scores["test_results_all_tests_passed"] = 0.0

    # 3) Validation report schema check
    report, rep_err = _safe_load_json(validation_report_path) if validation_report_path.exists() else (None, "missing")
    required_keys = [
        "config_version",
        "metadata_path",
        "data_path",
        "required_fields_present",
        "missing_fields",
        "required_columns_present",
        "missing_columns",
        "dataset_sha256",
        "row_count",
    ]
    schema_ok = False
    if isinstance(report, dict):
        # Check presence and types
        presence_ok = all(k in report for k in required_keys)
        types_ok = (
            isinstance(report.get("config_version"), str)
            and isinstance(report.get("metadata_path"), str)
            and isinstance(report.get("data_path"), str)
            and isinstance(report.get("required_fields_present"), bool)
            and isinstance(report.get("missing_fields"), list)
            and all(isinstance(x, str) for x in report.get("missing_fields", []))
            and isinstance(report.get("required_columns_present"), bool)
            and isinstance(report.get("missing_columns"), list)
            and all(isinstance(x, str) for x in report.get("missing_columns", []))
            and isinstance(report.get("dataset_sha256"), str)
            and isinstance(report.get("row_count"), int)
        )
        # Check sha256 hex length (64 hex chars)
        sha_hex_ok = False
        ds = report.get("dataset_sha256")
        if isinstance(ds, str):
            try:
                int(ds, 16)
                sha_hex_ok = len(ds) == 64
            except Exception:
                sha_hex_ok = False
        # Check sorted arrays
        sorted_ok = _is_sorted_alpha(report.get("missing_fields", [])) and _is_sorted_alpha(report.get("missing_columns", []))
        schema_ok = presence_ok and types_ok and sha_hex_ok and sorted_ok
    if schema_ok:
        scores["validation_report_file_schema"] = 1.0
    else:
        scores["validation_report_file_schema"] = 0.0

    # 4) Validation report content correctness
    content_ok = False
    if isinstance(report, dict) and cfg_data is not None and meta_data is not None and csv_rows is not None and data_sha256 is not None:
        try:
            # Exact paths as specified in task
            paths_ok = (report.get("metadata_path") == "input/metadata.json" and report.get("data_path") == "input/observations.csv")
            # Config version propagation
            cfg_ver_ok = (str(report.get("config_version")) == str(cfg_data.get("config_version", "")))
            # Required metadata fields present and missing_fields empty
            req_meta_fields = list(cfg_data.get("required_metadata_fields", []))
            missing_fields = sorted([k for k in req_meta_fields if k not in meta_data])
            fields_ok = (report.get("required_fields_present") is True and report.get("missing_fields") == missing_fields == [])
            # Required columns present and missing_columns empty
            req_cols = list(cfg_data.get("required_columns", []))
            header_fields = csv_header or []
            missing_cols = sorted([c for c in req_cols if c not in header_fields])
            cols_ok = (report.get("required_columns_present") is True and report.get("missing_columns") == missing_cols == [])
            # Row count matches
            rows_ok = (report.get("row_count") == csv_rows)
            # Dataset sha256 matches actual file
            sha_ok = (report.get("dataset_sha256") == data_sha256)
            content_ok = paths_ok and cfg_ver_ok and fields_ok and cols_ok and rows_ok and sha_ok
        except Exception:
            content_ok = False
    scores["validation_report_content_correct"] = 1.0 if content_ok else 0.0

    # 5) Tree file completeness
    tree_lines, tree_err = _safe_read_text_lines(tree_path) if tree_path.exists() else (None, "missing")
    if tree_lines is not None:
        # Normalize to forward slashes and strip whitespace
        listed = [ln.strip().replace("\\", "/") for ln in tree_lines if ln.strip() != ""]
        listed_set = set(listed)
        # Recompute current file listing
        actual_files = set(_list_all_files_relative(workspace))
        # Compare sets
        tree_ok = (listed_set == actual_files)
        scores["tree_file_complete_listing"] = 1.0 if tree_ok else 0.0
    else:
        scores["tree_file_complete_listing"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()