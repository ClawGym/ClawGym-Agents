import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _is_float_token(tok: str) -> bool:
    try:
        float(tok)
        return True
    except Exception:
        return False


def _parse_single_column_csv(path: Path) -> Optional[List[float]]:
    """
    Parse a single numeric column CSV with optional header and blank lines.
    Ignore blank lines. If the first non-blank entry is non-numeric, treat it as header.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    lines = [ln.strip() for ln in text.splitlines()]
    idx = 0
    while idx < len(lines) and lines[idx] == "":
        idx += 1
    if idx < len(lines):
        first = lines[idx]
        if not _is_float_token(first.split(",")[0].strip()):
            idx += 1
    values: List[float] = []
    for ln in lines[idx:]:
        if not ln:
            continue
        token = ln.split(",")[0].strip()
        if not token:
            continue
        if not _is_float_token(token):
            return None
        values.append(float(token))
    return values


def _compute_stats(values: List[float]) -> Dict[str, float]:
    n = len(values)
    if n == 0:
        mean = 0.0
        var = 0.0
        mn = float("nan")
        mx = float("nan")
    else:
        s = sum(values)
        mean = s / n
        mn = min(values)
        mx = max(values)
        var = sum((x - mean) ** 2 for x in values) / n
    return {"count": float(n), "mean": float(mean), "variance": float(var), "min": float(mn), "max": float(mx)}


def _close(a: float, b: float, tol: float = 1e-9) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


def _extract_fortran_module_content(content: str, module_name: str) -> Optional[str]:
    pattern = re.compile(
        rf"(?is)\bmodule\s+{re.escape(module_name)}\b(.*?)(?:\bend\s+module\b(?:\s+{re.escape(module_name)})?)"
    )
    m = pattern.search(content)
    if m:
        return m.group(1)
    return None


def _find_fortran_files(workspace: Path) -> List[Path]:
    try:
        return sorted(list(workspace.rglob("*.f90")))
    except Exception:
        return []


def _check_fortran_stats_mod(fortran_files: List[Path]) -> Tuple[float, float, float]:
    expected_funcs = ["count", "mean", "variance", "min", "max"]
    module_present = 0.0
    pure_funcs_found = {name: False for name in expected_funcs}
    dp_found = 0.0

    contents = []
    for p in fortran_files:
        txt = _read_text(p)
        if txt:
            contents.append(txt)

    full_text = "\n".join(contents)
    mod_content = _extract_fortran_module_content(full_text, "stats_mod")
    if mod_content is not None:
        module_present = 1.0
        for fname in expected_funcs:
            pat = re.compile(rf"(?is)\bpure\s+function\s+{re.escape(fname)}\b")
            if pat.search(mod_content):
                pure_funcs_found[fname] = True
        dp_patterns = [
            r"(?i)\bdouble\s+precision\b",
            r"(?i)\breal\s*\(\s*kind\s*=\s*8\s*\)",
            r"(?i)\breal\s*\(\s*8\s*\)",
            r"(?i)\bkind\s*=\s*dp\b",
            r"(?i)\bselected_real_kind",
        ]
        for pat in dp_patterns:
            if re.search(pat, mod_content):
                dp_found = 1.0
                break

    pure_ratio = sum(1 for v in pure_funcs_found.values() if v) / len(expected_funcs) if module_present > 0 else 0.0
    return module_present, pure_ratio, dp_found


def _check_fortran_program(fortran_files: List[Path]) -> Tuple[float, float]:
    contents = []
    for p in fortran_files:
        txt = _read_text(p)
        if txt:
            contents.append((p, txt))
    program_present = 0.0
    uses_args = 0.0
    prog_re = re.compile(r"(?is)\bprogram\s+stats_cli\b")
    for _, txt in contents:
        if prog_re.search(txt):
            program_present = 1.0
            if re.search(r"(?i)\bget_command_argument\b", txt) or re.search(r"(?i)\bcommand_argument_count\b", txt):
                uses_args = 1.0
            break
    return program_present, uses_args


def _check_build_script(script_path: Path) -> Tuple[float, float]:
    if not script_path.exists():
        return 0.0, 0.0
    txt = _read_text(script_path) or ""
    has_gfortran_ref = "gfortran" in txt
    has_check = bool(
        re.search(r"command\s+-v\s+gfortran", txt)
        or re.search(r"\bwhich\s+gfortran\b", txt)
        or re.search(r"\btype\s+gfortran\b", txt)
    )
    has_exit_nonzero = bool(re.search(r"\bexit\s+[1-9]\d*\b", txt))
    checks_gfortran = 1.0 if (has_gfortran_ref and has_check and has_exit_nonzero) else 0.0

    refs_data = "data/measurements.csv" in txt
    refs_json = "out/stats.json" in txt
    refs_txt = "out/stats.txt" in txt
    references_paths = 1.0 if (refs_data and refs_json and refs_txt) else 0.0
    return checks_gfortran, references_paths


def _extract_metric_from_line(line: str) -> List[float]:
    num_re = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
    vals = []
    for m in num_re.finditer(line):
        try:
            vals.append(float(m.group(0)))
        except Exception:
            pass
    return vals


def _parse_stats_txt(path: Path) -> Optional[Dict[str, float]]:
    txt = _read_text(path)
    if txt is None:
        return None
    metrics = {"count": None, "mean": None, "variance": None, "min": None, "max": None}
    lines = txt.splitlines()
    for ln in lines:
        low = ln.lower()
        for key in metrics:
            if key in low and metrics[key] is None:
                nums = _extract_metric_from_line(ln)
                if nums:
                    metrics[key] = float(nums[0])
    if any(v is None for v in metrics.values()):
        return None
    return {k: float(v) for k, v in metrics.items()}  # type: ignore


def _find_result_dicts_in_verification_json(data: Any) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, float]]]:
    def is_stats_dict(d: Any) -> bool:
        if not isinstance(d, dict):
            return False
        req = ["count", "mean", "variance", "min", "max"]
        for k in req:
            if k not in d:
                return False
            if not isinstance(d[k], (int, float)):
                return False
        return True

    found_fortran: Optional[Dict[str, float]] = None
    found_python: Optional[Dict[str, float]] = None

    if isinstance(data, dict):
        for k, v in data.items():
            lk = str(k).lower()
            if "fortran" in lk and isinstance(v, dict) and is_stats_dict(v):
                found_fortran = {kk: float(v[kk]) for kk in ["count", "mean", "variance", "min", "max"]}
            if "python" in lk and isinstance(v, dict) and is_stats_dict(v):
                found_python = {kk: float(v[kk]) for kk in ["count", "mean", "variance", "min", "max"]}
        if (found_fortran is None or found_python is None):
            for v in data.values():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        lk2 = str(k2).lower()
                        if "fortran" in lk2 and isinstance(v2, dict) and is_stats_dict(v2):
                            found_fortran = {kk: float(v2[kk]) for kk in ["count", "mean", "variance", "min", "max"]}
                        if "python" in lk2 and isinstance(v2, dict) and is_stats_dict(v2):
                            found_python = {kk: float(v2[kk]) for kk in ["count", "mean", "variance", "min", "max"]}
    return found_fortran, found_python


def _find_pass_flag_in_verification_json(data: Any) -> Optional[bool]:
    def find_bool_in_dict(d: Dict[Any, Any]) -> Optional[bool]:
        for k, v in d.items():
            lk = str(k).lower()
            if isinstance(v, bool) and any(word in lk for word in ["pass", "passed", "ok", "success"]):
                return bool(v)
        return None

    if isinstance(data, dict):
        flag = find_bool_in_dict(data)
        if flag is not None:
            return flag
        for v in data.values():
            if isinstance(v, dict):
                flag = find_bool_in_dict(v)
                if flag is not None:
                    return flag
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "fortran_stats_mod_present": 0.0,
        "fortran_pure_functions_ratio": 0.0,
        "fortran_double_precision_mentioned": 0.0,
        "fortran_stats_cli_program_present": 0.0,
        "fortran_cli_uses_arguments": 0.0,
        "build_script_checks_gfortran_and_exits_nonzero": 0.0,
        "build_script_references_paths_and_outputs": 0.0,
        "verify_script_references_inputs_and_outputs": 0.0,
        "stats_json_exists": 0.0,
        "stats_json_has_required_keys": 0.0,
        "stats_json_values_correct": 0.0,
        "stats_txt_exists": 0.0,
        "stats_txt_contains_all_metrics": 0.0,
        "verification_json_exists": 0.0,
        "verification_json_includes_results_and_flag": 0.0,
        "verification_json_pass_and_within_tolerance": 0.0,
        "docs_architecture_exists": 0.0,
        "docs_architecture_covers_topics": 0.0,
        "docs_legacy_review_three_issues": 0.0,
        "status_progress_exists": 0.0,
        "status_progress_covers_run_verify_limitations_next": 0.0,
    }

    # Fortran checks
    fortran_files = _find_fortran_files(workspace)
    mod_present, pure_ratio, dp_found = _check_fortran_stats_mod(fortran_files)
    scores["fortran_stats_mod_present"] = mod_present
    scores["fortran_pure_functions_ratio"] = pure_ratio
    scores["fortran_double_precision_mentioned"] = dp_found

    prog_present, uses_args = _check_fortran_program(fortran_files)
    scores["fortran_stats_cli_program_present"] = prog_present
    scores["fortran_cli_uses_arguments"] = uses_args

    # Build script checks
    build_script = workspace / "scripts" / "build_and_run.sh"
    checks_gfortran, refs_paths = _check_build_script(build_script)
    scores["build_script_checks_gfortran_and_exits_nonzero"] = checks_gfortran
    scores["build_script_references_paths_and_outputs"] = refs_paths

    # Verify script basic textual checks
    verify_script_path = workspace / "scripts" / "verify.py"
    if verify_script_path.exists():
        txt = _read_text(verify_script_path) or ""
        has_in = "data/measurements.csv" in txt
        has_out = "out/verification.json" in txt
        has_stats_json = "out/stats.json" in txt
        scores["verify_script_references_inputs_and_outputs"] = 1.0 if (has_in and has_out and has_stats_json) else 0.0
    else:
        scores["verify_script_references_inputs_and_outputs"] = 0.0

    # Compute expected stats from data
    data_csv = workspace / "data" / "measurements.csv"
    expected: Optional[Dict[str, float]] = None
    values = _parse_single_column_csv(data_csv) if data_csv.exists() else None
    if values is not None:
        expected = _compute_stats(values)

    # stats.json checks
    stats_json_path = workspace / "out" / "stats.json"
    if stats_json_path.exists():
        scores["stats_json_exists"] = 1.0
        data_json = _load_json(stats_json_path)
        if isinstance(data_json, dict):
            required_keys = ["count", "mean", "variance", "min", "max"]
            has_keys = all(k in data_json for k in required_keys)
            types_ok = all(isinstance(data_json.get(k), (int, float)) for k in required_keys)
            scores["stats_json_has_required_keys"] = 1.0 if (has_keys and types_ok) else 0.0
            if expected is not None and has_keys and types_ok:
                matched = sum(1 for k in required_keys if _close(float(data_json[k]), expected[k], 1e-9))
                scores["stats_json_values_correct"] = matched / len(required_keys)
            else:
                scores["stats_json_values_correct"] = 0.0
        else:
            scores["stats_json_has_required_keys"] = 0.0
            scores["stats_json_values_correct"] = 0.0
    else:
        scores["stats_json_exists"] = 0.0
        scores["stats_json_has_required_keys"] = 0.0
        scores["stats_json_values_correct"] = 0.0

    # stats.txt checks
    stats_txt_path = workspace / "out" / "stats.txt"
    if stats_txt_path.exists():
        scores["stats_txt_exists"] = 1.0
        parsed_txt = _parse_stats_txt(stats_txt_path)
        if parsed_txt is not None and expected is not None:
            matched = sum(1 for k in ["count", "mean", "variance", "min", "max"] if _close(parsed_txt[k], expected[k], 1e-9))
            scores["stats_txt_contains_all_metrics"] = matched / 5.0
        else:
            scores["stats_txt_contains_all_metrics"] = 0.0
    else:
        scores["stats_txt_exists"] = 0.0
        scores["stats_txt_contains_all_metrics"] = 0.0

    # verification.json checks
    verification_json_path = workspace / "out" / "verification.json"
    if verification_json_path.exists():
        scores["verification_json_exists"] = 1.0
        vj = _load_json(verification_json_path)
        if vj is not None:
            f_dict, p_dict = _find_result_dicts_in_verification_json(vj)
            pass_flag = _find_pass_flag_in_verification_json(vj)
            includes_ok = (f_dict is not None and p_dict is not None and pass_flag is not None)
            scores["verification_json_includes_results_and_flag"] = 1.0 if includes_ok else 0.0
            if includes_ok and isinstance(pass_flag, bool):
                diffs_within = all(_close(f_dict[k], p_dict[k], 1e-9) for k in ["count", "mean", "variance", "min", "max"])  # type: ignore
                scores["verification_json_pass_and_within_tolerance"] = 1.0 if (pass_flag and diffs_within) else 0.0
            else:
                scores["verification_json_pass_and_within_tolerance"] = 0.0
        else:
            scores["verification_json_includes_results_and_flag"] = 0.0
            scores["verification_json_pass_and_within_tolerance"] = 0.0
    else:
        scores["verification_json_exists"] = 0.0
        scores["verification_json_includes_results_and_flag"] = 0.0
        scores["verification_json_pass_and_within_tolerance"] = 0.0

    # docs/architecture.md checks
    arch_path = workspace / "docs" / "architecture.md"
    if arch_path.exists():
        scores["docs_architecture_exists"] = 1.0
        arch_text = _read_text(arch_path) or ""
        topics = {
            "stats_mod": bool(re.search(r"(?i)\bstats_mod\b", arch_text)),
            "stats_cli": bool(re.search(r"(?i)\bstats_cli\b", arch_text)),
            "csv_io": bool(re.search(r"(?i)\bcsv\b", arch_text) and (re.search(r"(?i)\binput\b", arch_text) or re.search(r"(?i)\bI/O\b", arch_text))),
            "outputs": bool("out/stats.json" in arch_text and "out/stats.txt" in arch_text),
            "double_precision": bool(re.search(r"(?i)\bdouble\s+precision\b", arch_text) or re.search(r"(?i)\breal\s*\(\s*8\s*\)", arch_text)),
            "population_variance": bool(re.search(r"(?i)\bpopulation\s+variance\b", arch_text) or re.search(r"(?i)\bdivide\s+by\s+N\b", arch_text)),
            "build_run_instructions": bool(re.search(r"(?i)\bbuild\b", arch_text) and re.search(r"(?i)\brun\b", arch_text) and ("scripts/build_and_run.sh" in arch_text)),
        }
        scores["docs_architecture_covers_topics"] = sum(1.0 for v in topics.values() if v) / float(len(topics))
        legacy_section = arch_text
        m = re.search(r"(?is)^\s*#+\s*Legacy\s+review\b(.*?)(^\s*#|\Z)", arch_text, re.MULTILINE)
        if m:
            legacy_section = m.group(1)
        issue_keywords = ["integer", "division", "csv", "header", "argument", "stdin", "no.*error", "no.*file", "precision"]
        issues_found = set()
        for kw in issue_keywords:
            if re.search(rf"(?is)\b{kw}\b", legacy_section):
                issues_found.add(kw)
        scores["docs_legacy_review_three_issues"] = 1.0 if len(issues_found) >= 3 else min(len(issues_found) / 3.0, 1.0)
    else:
        scores["docs_architecture_exists"] = 0.0
        scores["docs_architecture_covers_topics"] = 0.0
        scores["docs_legacy_review_three_issues"] = 0.0

    # status/progress.md checks
    status_path = workspace / "status" / "progress.md"
    if status_path.exists():
        scores["status_progress_exists"] = 1.0
        st = _read_text(status_path) or ""
        reqs = {
            "implemented": bool(re.search(r"(?i)\bimplemented\b|\bcompleted\b|\bdone\b", st)),
            "run_verify": bool(re.search(r"(?i)\brun\b", st) and re.search(r"(?i)\bverify\b", st)),
            "limitations": bool(re.search(r"(?i)\blimitation\b|\bknown issues\b", st)),
            "next_steps": bool(re.search(r"(?i)\bnext\s+steps\b|\bfuture\b|\bfollow[- ]?up\b", st)),
        }
        scores["status_progress_covers_run_verify_limitations_next"] = sum(1.0 for v in reqs.values() if v) / float(len(reqs))
    else:
        scores["status_progress_exists"] = 0.0
        scores["status_progress_covers_run_verify_limitations_next"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()