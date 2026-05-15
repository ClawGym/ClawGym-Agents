import sys
import json
import csv
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_minimal_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # strip inline comments
            if "#" in line:
                # only keep content before first # if not inside quotes
                # For simplicity here, we assume no quotes in these lines contain '#'
                line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                return None  # malformed yaml (no key-value separator)
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # remove surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # type coercion
            low = val.lower()
            if low == "true":
                coerced: Any = True
            elif low == "false":
                coerced = False
            else:
                # try int, then float
                try:
                    if re.fullmatch(r"[+-]?\d+", val):
                        coerced = int(val)
                    else:
                        coerced = float(val)
                except Exception:
                    coerced = val
            data[key] = coerced
        return data
    except Exception:
        return None


def _parse_feature_selector_info(text: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if text is None:
        return None, None, None
    algo = None
    version = None
    complexity_line = None
    try:
        m = re.search(r'ALGORITHM_NAME\s*=\s*([\'"])(.*?)\1', text)
        if m:
            algo = m.group(2).strip()
        mv = re.search(r'__version__\s*=\s*([\'"])(.*?)\1', text)
        if mv:
            version = mv.group(2).strip()
        # Find complexity line exactly as in docstring
        for line in text.splitlines():
            if "Worst-case time complexity:" in line:
                # clean leading/trailing spaces
                c = line.strip()
                # Reconstruct exact text after colon with trimmed right side
                m2 = re.search(r'Worst-case time complexity:\s*(.*)', c)
                if m2:
                    rhs = m2.group(1).strip()
                    complexity_line = f"Worst-case time complexity: {rhs}"
                    break
    except Exception:
        pass
    return algo, version, complexity_line


def _load_ablation_csv(path: Path) -> Optional[Dict[str, List[float]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            groups: Dict[str, List[float]] = {}
            for row in reader:
                variant = row.get("config_variant")
                val_str = row.get("val_f1")
                if variant is None or val_str is None:
                    return None
                try:
                    val = float(val_str)
                except Exception:
                    return None
                groups.setdefault(variant, []).append(val)
            return groups
    except Exception:
        return None


def _avg(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt2(x: float) -> str:
    return f"{x:.2f}"


def _find_section_lines(content: str, heading: str) -> List[str]:
    lines = content.splitlines()
    section_lines: List[str] = []
    in_section = False
    for line in lines:
        if line.strip() == heading:
            in_section = True
            continue
        if in_section and line.startswith("## ") and line.strip() != heading:
            break
        if in_section:
            section_lines.append(line)
    return section_lines


def _find_headings(content: str) -> List[str]:
    lines = content.splitlines()
    return [line.strip() for line in lines if line.strip().startswith("#")]


def _parse_hyperparams_section(lines: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        # optional bullet
        if line.startswith("- "):
            line = line[2:].strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        parsed[k.strip()] = v.strip()
    return parsed


def _normalize_value_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        # For floats, preserve simple representation
        if isinstance(v, float) and not v.is_integer():
            return str(v).rstrip("0").rstrip(".") if "." in str(v) else str(v)
        else:
            return str(int(v)) if float(v).is_integer() else str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _parse_key_value_line(line: str) -> Optional[Tuple[str, str]]:
    if ":" not in line:
        return None
    k, v = line.split(":", 1)
    return k.strip(), v.strip()


def _extract_status_defaults(content: str) -> Dict[str, str]:
    lines = content.splitlines()
    defaults_started = False
    defaults: Dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not defaults_started:
            if line == "Defaults:":
                defaults_started = True
            continue
        # Stop at Results or Blockers or empty line
        if not line or line.startswith("Results:") or line.startswith("Blockers:"):
            break
        kv = _parse_key_value_line(line)
        if kv:
            k, v = kv
            defaults[k] = v
    return defaults


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists": 0.0,
        "headings_preserved_and_changelog_added": 0.0,
        "report_algorithm_name_correct": 0.0,
        "report_complexity_exact_from_code": 0.0,
        "report_hyperparameters_synced": 0.0,
        "report_results_updated": 0.0,
        "report_todos_and_bracketed_tags_removed": 0.0,
        "report_changelog_bullets_exact": 0.0,
        "status_exists": 0.0,
        "status_title_correct": 0.0,
        "status_algorithm_and_version_correct": 0.0,
        "status_defaults_listed": 0.0,
        "status_results_line_correct": 0.0,
        "status_blockers_correct": 0.0,
    }

    # Load expected info from code/config/csv
    code_path = workspace / "src" / "feature_selector.py"
    code_text = _read_text(code_path)
    algo_name, version, complexity_line = _parse_feature_selector_info(code_text)

    config_path = workspace / "config" / "defaults.yaml"
    defaults = _load_minimal_yaml(config_path)

    csv_path = workspace / "data" / "ablation_runs.csv"
    groups = _load_ablation_csv(csv_path)

    expected_baseline_avg: Optional[float] = None
    expected_tuned_avg: Optional[float] = None
    expected_delta: Optional[float] = None
    if groups is not None:
        base_vals = groups.get("baseline", [])
        tuned_vals = groups.get("tuned", [])
        base_avg = _avg(base_vals) if base_vals is not None else None
        tuned_avg = _avg(tuned_vals) if tuned_vals is not None else None
        if base_avg is not None and tuned_avg is not None:
            expected_baseline_avg = base_avg
            expected_tuned_avg = tuned_avg
            expected_delta = tuned_avg - base_avg

    # Prepare expected defaults mapping for five keys
    required_keys = ["selection_method", "max_features", "stopping_threshold", "random_state", "normalize"]
    expected_defaults: Optional[Dict[str, Any]] = None
    if defaults is not None:
        # Build mapping with only required keys
        expected_defaults = {}
        try:
            for k in required_keys:
                if k not in defaults:
                    expected_defaults = None
                    break
                expected_defaults[k] = defaults[k]
        except Exception:
            expected_defaults = None

    # Check report
    report_path = workspace / "output" / "progress_report_updated.md"
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0

        # Headings preserved and changelog added
        expected_headings = [
            "# Feature Selection Algorithm Progress Report (Draft)",
            "## Overview",
            "## Algorithm",
            "## Hyperparameters (defaults)",
            "## Results summary (validation set)",
            "## Notes",
            "## Next steps",
        ]
        headings = _find_headings(report_text)
        has_all = all(h in headings for h in expected_headings)
        has_changelog = any(h.strip() == "## Changelog" for h in headings)
        # ensure Changelog is the last heading
        last_is_changelog = False
        if has_changelog and headings:
            # find positions
            last_is_changelog = headings[-1].strip() == "## Changelog"
        if has_all and has_changelog and last_is_changelog:
            scores["headings_preserved_and_changelog_added"] = 1.0

        # Algorithm name in Algorithm section
        algo_section = _find_section_lines(report_text, "## Algorithm")
        algo_line_ok = False
        if algo_name is not None:
            for line in algo_section:
                if line.strip() == f"Current implementation: {algo_name}":
                    algo_line_ok = True
                    break
        if algo_line_ok:
            scores["report_algorithm_name_correct"] = 1.0

        # Complexity exact line present from code, and old O(n^2) not present
        complexity_ok = False
        if complexity_line is not None and algo_section:
            in_section_text = "\n".join(algo_section)
            if complexity_line in in_section_text and "O(n^2)" not in in_section_text:
                complexity_ok = True
        if complexity_ok:
            scores["report_complexity_exact_from_code"] = 1.0

        # Hyperparameters synced
        hyper_section = _find_section_lines(report_text, "## Hyperparameters (defaults)")
        hyper_kv = _parse_hyperparams_section(hyper_section)
        hyper_ok = False
        if expected_defaults is not None:
            # check each required key-value match
            match_all = True
            for k in required_keys:
                if k not in hyper_kv:
                    match_all = False
                    break
                actual_val_str = hyper_kv.get(k, "")
                # normalize actual value
                actual_val_clean = actual_val_str.strip().strip('"').strip("'")
                # expected normalized string
                expected_val = expected_defaults[k]
                expected_norm = _normalize_value_str(expected_val)
                # Compare with flexible typing
                equal = False
                # try boolean
                if expected_norm in ("true", "false"):
                    equal = actual_val_clean.lower() == expected_norm
                else:
                    # try numeric
                    try:
                        if isinstance(expected_val, int):
                            equal = int(actual_val_clean) == expected_val
                        elif isinstance(expected_val, float):
                            equal = abs(float(actual_val_clean) - expected_val) < 1e-9
                        else:
                            equal = actual_val_clean == expected_norm
                    except Exception:
                        equal = actual_val_clean == expected_norm
                if not equal:
                    match_all = False
                    break
            if match_all:
                hyper_ok = True
        if hyper_ok:
            scores["report_hyperparameters_synced"] = 1.0

        # Results updated in report
        results_section = _find_section_lines(report_text, "## Results summary (validation set)")
        res_ok = False
        if expected_baseline_avg is not None and expected_tuned_avg is not None and expected_delta is not None:
            try:
                base_str = _fmt2(expected_baseline_avg)
                tuned_str = _fmt2(expected_tuned_avg)
                delta_str = _fmt2(expected_delta)
                lines_clean = [ln.strip() for ln in results_section if ln.strip()]
                has_base = any(ln == f"- baseline avg F1: {base_str}" or ln == f"baseline avg F1: {base_str}" for ln in lines_clean)
                has_tuned = any(ln == f"- tuned avg F1: {tuned_str}" or ln == f"tuned avg F1: {tuned_str}" for ln in lines_clean)
                has_delta = any(ln == f"- delta (tuned - baseline): {delta_str}" or ln == f"delta (tuned - baseline): {delta_str}" for ln in lines_clean)
                if has_base and has_tuned and has_delta:
                    res_ok = True
            except Exception:
                res_ok = False
        if res_ok:
            scores["report_results_updated"] = 1.0

        # TODOs and bracketed tags removed
        # ensure absence of exact bracketed tags present in draft and absence of "TODO" (case-insensitive)
        content_upper = report_text.upper()
        todo_absent = "TODO" not in content_upper
        specific_tags = [
            "[to be filled]",
            "[TODO: verify algorithm name from code]",
            "[TO VERIFY]",
            "[TODO]",
        ]
        tags_absent = all(tag not in report_text for tag in specific_tags)
        if todo_absent and tags_absent:
            scores["report_todos_and_bracketed_tags_removed"] = 1.0

        # Changelog bullets exact
        changelog_lines = _find_section_lines(report_text, "## Changelog")
        # collect bullet items under changelog until next heading
        bullets = []
        for ln in changelog_lines:
            s = ln.strip()
            if s.startswith("- "):
                bullets.append(s[2:].strip())
        expected_bullets = [
            "algorithm name corrected",
            "worst-case complexity updated from code",
            "hyperparameter defaults synced from config",
            "results averages and delta recomputed from CSV",
        ]
        bullets_ok = False
        if len(bullets) == 4:
            # exact match ignoring order? The task lists exactly these items; order not specified.
            bullets_ok = sorted(bullets) == sorted(expected_bullets)
        if bullets_ok:
            scores["report_changelog_bullets_exact"] = 1.0

    # Check status summary
    status_path = workspace / "output" / "status_summary.md"
    status_text = _read_text(status_path)
    if status_text is not None:
        scores["status_exists"] = 1.0
        lines = [ln.strip() for ln in status_text.splitlines()]

        # Title correct: first non-empty line
        first_non_empty = next((ln for ln in lines if ln), "")
        if first_non_empty == "Weekly Status: Feature Selector":
            scores["status_title_correct"] = 1.0

        # Algorithm and Version lines
        alg_ok = False
        ver_ok = False
        if algo_name is not None:
            alg_ok = any(ln == f"Algorithm: {algo_name}" for ln in lines)
        if version is not None:
            ver_ok = any(ln == f"Version: {version}" for ln in lines)
        if alg_ok and ver_ok:
            scores["status_algorithm_and_version_correct"] = 1.0

        # Defaults section listed
        defaults_ok = False
        if expected_defaults is not None:
            status_defaults = _extract_status_defaults(status_text)
            # Check presence and exact string value match (with normalization for booleans and numbers)
            present_all = True
            for k in required_keys:
                if k not in status_defaults:
                    present_all = False
                    break
                actual_val = status_defaults[k].strip().strip('"').strip("'")
                exp_val = expected_defaults[k]
                exp_norm = _normalize_value_str(exp_val)
                equal = False
                if exp_norm in ("true", "false"):
                    equal = actual_val.lower() == exp_norm
                else:
                    try:
                        if isinstance(exp_val, int):
                            equal = int(actual_val) == exp_val
                        elif isinstance(exp_val, float):
                            equal = abs(float(actual_val) - exp_val) < 1e-9
                        else:
                            equal = actual_val == exp_norm
                    except Exception:
                        equal = actual_val == exp_norm
                if not equal:
                    present_all = False
                    break
            if present_all:
                defaults_ok = True
        if defaults_ok:
            scores["status_defaults_listed"] = 1.0

        # Results line correct
        res_line_ok = False
        blk_ok = False
        if expected_baseline_avg is not None and expected_tuned_avg is not None and expected_delta is not None:
            base_str = _fmt2(expected_baseline_avg)
            tuned_str = _fmt2(expected_tuned_avg)
            delta_str = _fmt2(expected_delta)
            expected_results_line = f"Results: baseline avg F1: {base_str}; tuned avg F1: {tuned_str}; delta: {delta_str}"
            res_line_ok = any(ln == expected_results_line for ln in lines)
            if res_line_ok:
                scores["status_results_line_correct"] = 1.0
            # Blockers line
            expected_blocker = "none" if expected_tuned_avg >= expected_baseline_avg else "performance regression"
            blk_ok = any(ln == f"Blockers: {expected_blocker}" for ln in lines)
            if blk_ok:
                scores["status_blockers_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()