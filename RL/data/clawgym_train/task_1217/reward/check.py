import json
import csv
import hashlib
import sys
import os
from pathlib import Path, PurePosixPath
from datetime import datetime
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes_safe(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _parse_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _is_executable_or_bash_script(path: Path) -> bool:
    try:
        if os.access(path, os.X_OK):
            return True
        txt = _read_text_safe(path)
        if not txt:
            return False
        first_line = txt.splitlines()[0].strip() if txt else ""
        return first_line.startswith("#!") and ("bash" in first_line or "sh" in first_line)
    except Exception:
        return False


def _norm_path_str(p: str) -> str:
    s = p.replace("\\", "/")
    s = str(PurePosixPath(s))
    if s.startswith("./"):
        s = s[2:]
    return s.lower()


def _parse_junit_xml(junit_path: Path) -> Optional[Dict[str, Any]]:
    try:
        tree = ET.parse(str(junit_path))
        root = tree.getroot()
    except Exception:
        return None

    testcases = list(root.findall(".//testcase"))
    total = len(testcases)
    failures = 0
    errors = 0
    skipped = 0
    duration = 0.0
    any_case_time = False

    for tc in testcases:
        if tc.find("failure") is not None:
            failures += 1
        elif tc.find("error") is not None:
            errors += 1
        elif tc.find("skipped") is not None:
            skipped += 1
        t = tc.get("time")
        if t is not None:
            try:
                duration += float(t)
                any_case_time = True
            except Exception:
                pass

    if not any_case_time:
        suites = root.findall(".//testsuite")
        for ts in suites:
            t = ts.get("time")
            if t is not None:
                try:
                    duration += float(t)
                except Exception:
                    pass

    return {
        "total_tests": int(total),
        "failures": int(failures),
        "errors": int(errors),
        "skipped": int(skipped),
        "duration_seconds": float(duration),
    }


def _parse_cobertura_xml(coverage_path: Path) -> Optional[Tuple[int, int, Dict[str, Dict[str, Any]]]]:
    try:
        tree = ET.parse(str(coverage_path))
        root = tree.getroot()
    except Exception:
        return None

    per_file: Dict[str, Dict[str, Any]] = {}
    classes = root.findall(".//class")
    for cls in classes:
        filename = cls.get("filename")
        if not filename:
            continue
        norm = _norm_path_str(filename)
        lines_elem = cls.find("lines")
        if lines_elem is None:
            lines = cls.findall("line")
        else:
            lines = lines_elem.findall("line")
        valid = 0
        covered = 0
        for ln in lines:
            try:
                hits = ln.get("hits")
                if hits is None:
                    continue
                valid += 1
                if int(float(hits)) > 0:
                    covered += 1
            except Exception:
                return None
        if norm in per_file:
            per_file[norm]["lines_covered"] += covered
            per_file[norm]["lines_valid"] += valid
        else:
            per_file[norm] = {"lines_covered": covered, "lines_valid": valid}

    overall_valid = 0
    overall_covered = 0
    for d in per_file.values():
        valid = d["lines_valid"]
        covered = d["lines_covered"]
        overall_valid += valid
        overall_covered += covered
        d["coverage_percent"] = (covered / valid) * 100.0 if valid > 0 else 0.0

    if overall_valid == 0:
        try:
            ov = root.get("lines-valid")
            oc = root.get("lines-covered")
            if ov is not None and oc is not None:
                overall_valid = int(ov)
                overall_covered = int(oc)
        except Exception:
            pass

    return overall_covered, overall_valid, per_file


def _float_close(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _int_equal(a: int, b: int) -> bool:
    return int(a) == int(b)


def _looks_like_iso8601(dt: Any) -> bool:
    if not isinstance(dt, str) or not dt:
        return False
    s = dt.strip()
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    artifacts = workspace / "artifacts"
    junit_xml = artifacts / "junit.xml"
    coverage_xml = artifacts / "coverage.xml"
    ci_log = artifacts / "ci.log"
    test_summary_json = artifacts / "test_summary.json"
    per_file_csv = artifacts / "per_file_coverage.csv"
    licenses_dir = artifacts / "licenses"
    mit_license_txt = licenses_dir / "mit_license.txt"
    source_metadata_json = licenses_dir / "source_metadata.json"
    entry_script = workspace / "scripts" / "run_ci.sh"

    scores: Dict[str, float] = {
        "entrypoint_script_present": 0.0,
        "junit_xml_parseable": 0.0,
        "coverage_xml_parseable": 0.0,
        "ci_log_present_nonempty": 0.0,
        "test_summary_consistent_with_junit": 0.0,
        "per_file_coverage_consistent_with_xml": 0.0,
        "overall_coverage_matches_xml": 0.0,
        "hash_util_coverage_row_present": 0.0,
        "license_metadata_valid": 0.0,
        "license_validation_passes": 0.0,
        "tests_all_passed": 0.0,
    }

    # Entry point script check
    if entry_script.exists() and entry_script.is_file() and _is_executable_or_bash_script(entry_script):
        scores["entrypoint_script_present"] = 1.0

    # Parse junit.xml
    junit_info: Optional[Dict[str, Any]] = None
    if junit_xml.exists() and junit_xml.is_file():
        junit_info = _parse_junit_xml(junit_xml)
        if junit_info is not None:
            scores["junit_xml_parseable"] = 1.0

    # Parse coverage.xml
    cov_info: Optional[Tuple[int, int, Dict[str, Dict[str, Any]]]] = None
    if coverage_xml.exists() and coverage_xml.is_file():
        cov_info = _parse_cobertura_xml(coverage_xml)
        if cov_info is not None:
            scores["coverage_xml_parseable"] = 1.0

    # CI log present and non-empty
    if ci_log.exists() and ci_log.is_file():
        content = _read_text_safe(ci_log)
        if content is not None and len(content.strip()) > 0:
            scores["ci_log_present_nonempty"] = 1.0

    # Test summary consistency with JUnit
    if scores["junit_xml_parseable"] == 1.0 and test_summary_json.exists() and test_summary_json.is_file():
        tsj = _load_json_safe(test_summary_json)
        if isinstance(tsj, dict):
            required_keys = [
                "total_tests",
                "passed",
                "failed",
                "errors",
                "skipped",
                "duration_seconds",
                "coverage_percent_overall",
            ]
            has_keys = all(k in tsj for k in required_keys)
            types_ok = (
                isinstance(tsj.get("total_tests"), int)
                and isinstance(tsj.get("passed"), int)
                and isinstance(tsj.get("failed"), int)
                and isinstance(tsj.get("errors"), int)
                and isinstance(tsj.get("skipped"), int)
                and isinstance(tsj.get("duration_seconds"), (int, float))
                and isinstance(tsj.get("coverage_percent_overall"), (int, float))
            )
            exp_total = junit_info["total_tests"] if junit_info else 0
            exp_fail = junit_info["failures"] if junit_info else 0
            exp_err = junit_info["errors"] if junit_info else 0
            exp_skip = junit_info["skipped"] if junit_info else 0
            exp_pass = exp_total - exp_fail - exp_err - exp_skip
            if exp_pass < 0:
                exp_pass = 0
            exp_duration = junit_info["duration_seconds"] if junit_info else 0.0

            if has_keys and types_ok:
                if (
                    _int_equal(tsj["total_tests"], exp_total)
                    and _int_equal(tsj["failed"], exp_fail)
                    and _int_equal(tsj["errors"], exp_err)
                    and _int_equal(tsj["skipped"], exp_skip)
                    and _int_equal(tsj["passed"], exp_pass)
                    and _float_close(float(tsj["duration_seconds"]), float(exp_duration), tol=1e-2)
                ):
                    scores["test_summary_consistent_with_junit"] = 1.0

    # Tests all passed (from JUnit)
    if scores["junit_xml_parseable"] == 1.0 and junit_info is not None:
        if junit_info["failures"] == 0 and junit_info["errors"] == 0:
            scores["tests_all_passed"] = 1.0

    # Per-file coverage CSV consistency and presence of hash_util row
    if scores["coverage_xml_parseable"] == 1.0 and per_file_csv.exists() and per_file_csv.is_file():
        csv_rows = _parse_csv_safe(per_file_csv)
        header_ok = False
        hash_util_present = False
        consistent = False
        if isinstance(csv_rows, list):
            try:
                with per_file_csv.open("r", encoding="utf-8", newline="") as f:
                    first_line = f.readline().strip()
                header_ok = (first_line == "file,lines_covered,lines_valid,coverage_percent")
            except Exception:
                header_ok = False

            overall_covered, overall_valid, per_file_map = cov_info if cov_info is not None else (0, 0, {})
            by_norm = dict(per_file_map)
            by_basename: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
            for k, v in per_file_map.items():
                base = Path(k).name
                by_basename.setdefault(base, [])
                by_basename[base].append((k, v))

            all_rows_valid = True
            for row in csv_rows:
                if not {"file", "lines_covered", "lines_valid", "coverage_percent"}.issubset(row.keys()):
                    all_rows_valid = False
                    break
                file_val = row["file"]
                try:
                    lines_cov = int(row["lines_covered"])
                    lines_val = int(row["lines_valid"])
                    cov_pct = float(row["coverage_percent"])
                except Exception:
                    all_rows_valid = False
                    break

                norm_row = _norm_path_str(file_val)
                if norm_row.endswith("/src/hash_util.py"):
                    hash_util_present = True

                match = by_norm.get(norm_row)
                if match is None:
                    base = Path(norm_row).name
                    candidates = by_basename.get(base)
                    if candidates and len(candidates) == 1:
                        match = candidates[0][1]
                    else:
                        all_rows_valid = False
                        break

                if match["lines_valid"] != lines_val or match["lines_covered"] != lines_cov:
                    all_rows_valid = False
                    break
                if not _float_close(match["coverage_percent"], cov_pct, tol=0.05):
                    all_rows_valid = False
                    break

            if header_ok and all_rows_valid:
                consistent = True

        if consistent:
            scores["per_file_coverage_consistent_with_xml"] = 1.0
        if hash_util_present:
            scores["hash_util_coverage_row_present"] = 1.0

    # Overall coverage matches XML
    if scores["coverage_xml_parseable"] == 1.0 and test_summary_json.exists() and test_summary_json.is_file():
        tsj2 = _load_json_safe(test_summary_json)
        if isinstance(tsj2, dict) and "coverage_percent_overall" in tsj2 and cov_info is not None:
            cov_number = tsj2.get("coverage_percent_overall")
            if isinstance(cov_number, (int, float)):
                overall_covered, overall_valid, per_file_map = cov_info
                if overall_valid == 0 and per_file_map:
                    overall_valid = sum(v["lines_valid"] for v in per_file_map.values())
                    overall_covered = sum(v["lines_covered"] for v in per_file_map.values())
                expected_pct = (overall_covered / overall_valid) * 100.0 if overall_valid > 0 else 0.0
                if _float_close(expected_pct, float(cov_number), tol=0.05):
                    scores["overall_coverage_matches_xml"] = 1.0

    # License metadata and validation
    meta_valid = False
    validation_passes = False
    if mit_license_txt.exists() and mit_license_txt.is_file() and source_metadata_json.exists() and source_metadata_json.is_file():
        meta = _load_json_safe(source_metadata_json)
        text_bytes = _read_bytes_safe(mit_license_txt)
        text_str: Optional[str] = None
        if text_bytes is not None:
            try:
                text_str = text_bytes.decode("utf-8", errors="replace")
            except Exception:
                text_str = None
        if isinstance(meta, dict) and isinstance(text_str, str):
            required_meta_keys = [
                "search_query",
                "engine_used",
                "chosen_result_title",
                "chosen_result_domain",
                "retrieved_at",
                "sha256",
            ]
            has_keys = all(k in meta for k in required_meta_keys)
            engine_ok = isinstance(meta.get("engine_used"), str) and len(meta.get("engine_used").strip()) > 0
            query_ok = isinstance(meta.get("search_query"), str) and len(meta.get("search_query").strip()) > 0
            domain = meta.get("chosen_result_domain")
            domain_ok = isinstance(domain, str) and ("opensource.org" in domain)
            title = meta.get("chosen_result_title")
            title_ok = isinstance(title, str) and ("mit" in title.lower() and "license" in title.lower())
            time_ok = _looks_like_iso8601(meta.get("retrieved_at"))
            sha_meta = meta.get("sha256")
            sha_ok_format = isinstance(sha_meta, str) and len(sha_meta) == 64 and all(c in "0123456789abcdef" for c in sha_meta.lower())

            if has_keys and engine_ok and query_ok and domain_ok and title_ok and time_ok and sha_ok_format:
                meta_valid = True

            phrases_present = ("permission is hereby granted" in text_str.lower()) and ("without warranty" in text_str.lower())
            sha_actual = hashlib.sha256(text_bytes or b"").hexdigest()
            sha_matches = isinstance(sha_meta, str) and sha_actual == sha_meta
            if phrases_present and sha_matches:
                validation_passes = True

    scores["license_metadata_valid"] = 1.0 if meta_valid else 0.0
    scores["license_validation_passes"] = 1.0 if validation_passes else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()