import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Tuple[bool, Optional[Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _read_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []
            return True, rows, headers
    except Exception:
        return False, [], []


def _parse_int(value: Union[str, int, float, None]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value)
        except Exception:
            return None
    s = str(value).strip()
    if s == "":
        return None
    m = re.match(r"^-?\d+$", s)
    if m:
        try:
            return int(s)
        except Exception:
            return None
    m = re.search(r"(-?\d{1,4})", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _contains_ci(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _get_section(text: str, heading: str, next_headings: List[str]) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for nh in next_headings:
        for j in range(start_idx + 1, len(lines)):
            if lines[j].strip().startswith(nh):
                end_idx = min(end_idx, j)
                break
    return "\n".join(lines[start_idx:end_idx])


def _extract_integers(text: str) -> List[int]:
    return [int(m.group(0)) for m in re.finditer(r"(?<![\d.-])\d{1,10}(?![\d.-])", text)]


def _normalize_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "t", "yes", "y", "1", "pass", "passed"}:
            return True
        if v in {"false", "f", "no", "n", "0", "fail", "failed"}:
            return False
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "cli_tool_present": 0.0,
        "download_log_schema": 0.0,
        "raw_json_files_logged_success": 0.0,
        "normalized_csv_schema": 0.0,
        "normalized_rows_coverage": 0.0,
        "normalized_qid_raw_consistency": 0.0,
        "validation_results_schema": 0.0,
        "validation_results_country_checks_correct": 0.0,
        "validation_results_inception_checks_correct": 0.0,
        "summary_sections_and_order": 0.0,
        "summary_reproduce_command_present": 0.0,
        "summary_counts_match": 0.0,
        "per_item_results_coverage": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "weapons_brazil.csv"
    download_log_csv = workspace / "data" / "download_log.csv"
    raw_dir = workspace / "data" / "raw"
    normalized_csv = workspace / "data" / "normalized" / "weapons_wikidata.csv"
    results_json = workspace / "reports" / "validation_results.json"
    summary_md = workspace / "reports" / "validation_summary.md"
    cli_tool = workspace / "tools" / "validate_weapons"

    # Read input CSV
    input_ok, input_rows, input_headers = _read_csv_dicts(input_csv)
    expected_input_headers = [
        "name",
        "expected_country",
        "inception_min_year",
        "inception_max_year",
        "hint",
        "optional_qid",
    ]
    if not input_ok or [h.strip() for h in (input_headers or [])] != expected_input_headers:
        input_rows = []
    input_names = [r.get("name", "").strip() for r in input_rows if r.get("name")]
    input_name_set = set(input_names)

    # 1) CLI tool presence
    if cli_tool.exists():
        scores["cli_tool_present"] = 1.0

    # 2) Download log schema check
    log_ok, log_rows, log_headers = _read_csv_dicts(download_log_csv)
    expected_log_headers = ["name", "qid", "source", "status_code", "bytes", "timestamp"]
    if log_ok and [h.strip() for h in (log_headers or [])] == expected_log_headers:
        scores["download_log_schema"] = 1.0

    # 3) Raw json files for successful downloads (status_code 200 and qid non-empty)
    success_count = 0
    success_with_file_count = 0
    if log_ok and log_rows:
        for row in log_rows:
            qid = (row.get("qid") or "").strip()
            status_code = _parse_int(row.get("status_code"))
            if qid and status_code == 200:
                success_count += 1
                raw_path = raw_dir / f"{qid}.json"
                ok, data = _read_json(raw_path)
                if ok and isinstance(data, dict):
                    success_with_file_count += 1
        if success_count > 0:
            scores["raw_json_files_logged_success"] = success_with_file_count / max(1, success_count)

    # 4) Normalized CSV schema and coverage
    norm_ok, norm_rows, norm_headers = _read_csv_dicts(normalized_csv)
    expected_norm_headers = ["name", "qid", "label_pt", "country_labels", "inception_year", "status"]
    if norm_ok and [h.strip() for h in (norm_headers or [])] == expected_norm_headers:
        scores["normalized_csv_schema"] = 1.0

    # Coverage: one row per input item and names present
    if norm_ok and input_rows:
        norm_names = [r.get("name", "").strip() for r in norm_rows if r.get("name") is not None]
        if len(norm_names) == len(input_names) and set(norm_names) == set(input_names):
            scores["normalized_rows_coverage"] = 1.0

    # QID vs raw consistency
    if norm_ok:
        with_qid = [r for r in norm_rows if (r.get("qid") or "").strip()]
        if with_qid:
            ok_count = 0
            for r in with_qid:
                qid = (r.get("qid") or "").strip()
                raw_path = raw_dir / f"{qid}.json"
                ok, data = _read_json(raw_path)
                if ok and isinstance(data, dict):
                    ok_count += 1
            scores["normalized_qid_raw_consistency"] = ok_count / max(1, len(with_qid))

    # 5) Validation results schema
    results_ok, results_data = _read_json(results_json)
    results_list: List[Dict[str, Any]] = []
    if results_ok and isinstance(results_data, list):
        structural_ok = True
        for el in results_data:
            if not isinstance(el, dict):
                structural_ok = False
                break
            for k in ["name", "qid", "resolution_status", "tests"]:
                if k not in el:
                    structural_ok = False
                    break
            tests = el.get("tests")
            if not isinstance(tests, dict):
                structural_ok = False
                break
            if "country" not in tests or "inception_year" not in tests:
                structural_ok = False
                break
            ct = tests.get("country")
            it = tests.get("inception_year")
            if not isinstance(ct, dict) or not isinstance(it, dict):
                structural_ok = False
                break
            for ck in ["expected", "observed", "pass"]:
                if ck not in ct:
                    structural_ok = False
                    break
            for ik in ["expected_range", "observed", "pass"]:
                if ik not in it:
                    structural_ok = False
                    break
        if structural_ok:
            scores["validation_results_schema"] = 1.0
            results_list = results_data  # type: ignore

    # Build indices
    norm_by_name: Dict[str, Dict[str, str]] = {}
    if norm_ok:
        for r in norm_rows:
            name = (r.get("name") or "").strip()
            if name:
                norm_by_name[name] = r

    input_by_name: Dict[str, Dict[str, str]] = {}
    for r in input_rows:
        nm = (r.get("name") or "").strip()
        if nm:
            input_by_name[nm] = r

    results_by_name: Dict[str, Dict[str, Any]] = {}
    for el in results_list:
        name = str(el.get("name", "")).strip()
        if name:
            results_by_name[name] = el

    # 6) Validate country checks correctness
    country_total = 0
    country_correct = 0
    if results_list and input_rows and norm_ok:
        for nm in input_names:
            res = results_by_name.get(nm)
            norm = norm_by_name.get(nm)
            inp = input_by_name.get(nm)
            if not (res and norm and inp):
                continue
            tests = res.get("tests", {})
            ct = tests.get("country", {})
            exp_country = (inp.get("expected_country") or "").strip()
            observed_countries = (norm.get("country_labels") or "").strip()
            if str(ct.get("expected", "")).strip() != exp_country:
                continue
            if str(ct.get("observed", "")).strip() != observed_countries:
                continue
            computed_pass = False
            if exp_country and observed_countries:
                parts = [p.strip() for p in observed_countries.split(";")]
                computed_pass = any(_contains_ci(p, exp_country) or _contains_ci(exp_country, p) for p in parts if p)
            rep_pass = _normalize_bool(ct.get("pass"))
            if rep_pass is None:
                continue
            if rep_pass == computed_pass:
                country_correct += 1
            country_total += 1
        if country_total > 0:
            scores["validation_results_country_checks_correct"] = country_correct / country_total

    # 7) Validate inception checks correctness
    inception_total = 0
    inception_correct = 0
    if results_list and input_rows and norm_ok:
        for nm in input_names:
            res = results_by_name.get(nm)
            norm = norm_by_name.get(nm)
            inp = input_by_name.get(nm)
            if not (res and norm and inp):
                continue
            tests = res.get("tests", {})
            it = tests.get("inception_year", {})
            exp_min = _parse_int(inp.get("inception_min_year"))
            exp_max = _parse_int(inp.get("inception_max_year"))
            exp_range = it.get("expected_range")
            rep_range: Optional[Tuple[Optional[int], Optional[int]]] = None
            if isinstance(exp_range, list) and len(exp_range) == 2:
                rep_range = (_parse_int(exp_range[0]), _parse_int(exp_range[1]))
            elif isinstance(exp_range, dict):
                amin = _parse_int(exp_range.get("min"))
                amax = _parse_int(exp_range.get("max"))
                rep_range = (amin, amax)
            elif isinstance(exp_range, str):
                nums = [int(x) for x in re.findall(r"-?\d+", exp_range)]
                if len(nums) >= 2:
                    rep_range = (nums[0], nums[1])
            if rep_range is None or rep_range[0] != exp_min or rep_range[1] != exp_max:
                continue
            observed_inception_raw = norm.get("inception_year")
            observed_inception = _parse_int(observed_inception_raw)
            rep_obs = it.get("observed", None)
            rep_obs_int = _parse_int(rep_obs)
            if observed_inception is None:
                reason = it.get("reason") or it.get("note") or it.get("message")
                rep_pass = it.get("pass", None)
                cond_reason = isinstance(reason, str) and (re.search(r"skip|missing", reason, re.IGNORECASE) is not None)
                cond_pass = (rep_pass is None) or (_normalize_bool(rep_pass) is False)
                cond_obs = (rep_obs is None) or (str(rep_obs).strip() == "") or (rep_obs_int is None)
                if cond_reason and cond_pass and cond_obs:
                    inception_correct += 1
                inception_total += 1
            else:
                rep_pass_bool = _normalize_bool(it.get("pass"))
                in_range = (exp_min is not None and exp_max is not None
                            and observed_inception >= exp_min and observed_inception <= exp_max)
                cond_obs = (rep_obs_int == observed_inception)
                if rep_pass_bool is not None and rep_pass_bool == in_range and cond_obs:
                    inception_correct += 1
                inception_total += 1
        if inception_total > 0:
            scores["validation_results_inception_checks_correct"] = inception_correct / inception_total

    # 8) Summary sections and order
    summary_text = _read_text(summary_md) or ""
    if summary_text:
        lines = [ln.strip() for ln in summary_text.splitlines()]
        idx_overview = next((i for i, ln in enumerate(lines) if ln.startswith("Overview:")), -1)
        idx_per_item = next((i for i, ln in enumerate(lines) if ln.startswith("Per-item results:")), -1)
        idx_repro = next((i for i, ln in enumerate(lines) if ln.startswith("How to reproduce:")), -1)
        if idx_overview != -1 and idx_per_item != -1 and idx_repro != -1:
            if idx_overview < idx_per_item < idx_repro:
                scores["summary_sections_and_order"] = 1.0

        # 9) Reproduce command present
        expected_cmd = "tools/validate_weapons --input input/weapons_brazil.csv --out-data data --out-reports reports"
        if expected_cmd in summary_text:
            scores["summary_reproduce_command_present"] = 1.0

        # 10) Summary counts match
        overview_section = _get_section(summary_text, "Overview:", ["Per-item results:", "How to reproduce:"])
        counts_ok = False
        if overview_section and input_rows:
            total_items = len(input_rows)
            resolved_count = 0
            if norm_ok:
                resolved_count = sum(1 for r in norm_rows if (r.get("qid") or "").strip())
            succeeded = 0
            if log_ok:
                for row in log_rows:
                    qid = (row.get("qid") or "").strip()
                    status_code = _parse_int(row.get("status_code"))
                    if qid and status_code == 200:
                        succeeded += 1
            country_pass = country_fail = country_skip = 0
            inception_pass = inception_fail = inception_skip = 0
            if results_list:
                for el in results_list:
                    tests = el.get("tests", {})
                    ct = tests.get("country", {})
                    it = tests.get("inception_year", {})
                    cpass = _normalize_bool(ct.get("pass"))
                    if cpass is True:
                        country_pass += 1
                    elif cpass is False:
                        country_fail += 1
                    else:
                        country_skip += 1
                    ipass_raw = it.get("pass")
                    ipass = _normalize_bool(ipass_raw)
                    if ipass is True:
                        inception_pass += 1
                    elif ipass is False:
                        reason = it.get("reason") or it.get("note") or it.get("message")
                        if isinstance(reason, str) and re.search(r"skip|missing", reason, re.IGNORECASE):
                            inception_skip += 1
                        else:
                            inception_fail += 1
                    else:
                        inception_skip += 1
            nums_in_text = _extract_integers(overview_section)
            needed = [
                total_items,
                resolved_count,
                succeeded,
                country_pass,
                country_fail,
                country_skip,
                inception_pass,
                inception_fail,
                inception_skip,
            ]
            if all(needed.count(n) <= nums_in_text.count(n) and (n in nums_in_text) for n in set(needed)):
                counts_ok = True
        if counts_ok:
            scores["summary_counts_match"] = 1.0

        # 11) Per-item results coverage
        per_item_section = _get_section(summary_text, "Per-item results:", ["How to reproduce:"])
        if per_item_section and input_rows:
            coverage = 0
            for nm in input_names:
                found = False
                for ln in per_item_section.splitlines():
                    if nm in ln and re.search(r"\b(PASS|FAIL|SKIP)\b", ln):
                        found = True
                        break
                if found:
                    coverage += 1
            if coverage == len(input_names):
                scores["per_item_results_coverage"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()