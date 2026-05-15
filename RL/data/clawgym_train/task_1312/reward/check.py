import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_yaml(path: Path) -> Optional[dict]:
    try:
        import yaml  # standard environment usually provides PyYAML in tasks; handle absence gracefully
    except Exception:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _safe_load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _discover_trial_csvs(workspace: Path, data_dir: str) -> List[Path]:
    base = workspace / data_dir
    if not base.exists() or not base.is_dir():
        return []
    return sorted([p for p in base.rglob("*_trials.csv") if p.is_file()])


def _csv_row_count(path: Path) -> Optional[int]:
    rows = _safe_load_csv_rows(path)
    if rows is None:
        return None
    return len(rows)


def _normalize_relpath(workspace: Path, data_dir: str, raw_path_str: str) -> Optional[str]:
    s = raw_path_str.strip().replace("\\", "/")
    if not s:
        return None
    # Try to make it relative to workspace, focusing on data_dir substring
    idx = s.find(data_dir)
    if idx != -1:
        s = s[idx:]
    # Ensure it is a relative path under data_dir
    if not s.startswith(data_dir + "/") and s != data_dir:
        # Might already be relative with "./"
        if s.startswith("./"):
            s = s[2:]
    return s


def _parse_files_loaded_log(workspace: Path, data_dir: str, log_path: Path) -> Optional[Dict[str, int]]:
    text = _safe_read_text(log_path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    result: Dict[str, int] = {}
    for ln in lines:
        # Try to parse "path<TAB>count" or "path, count" or "path count"
        m = re.match(r"^(?P<path>.+?)[,\t ]+(?P<count>\d+)$", ln)
        if m:
            raw_path = m.group("path").strip()
            count_s = m.group("count").strip()
        else:
            # Try last integer at end
            m2 = re.search(r"(\d+)\s*$", ln)
            if not m2:
                return None
            count_s = m2.group(1)
            raw_path = ln[: m2.start()].strip()
        try:
            count = int(count_s)
        except Exception:
            return None
        norm = _normalize_relpath(workspace, data_dir, raw_path)
        if norm is None:
            return None
        result[norm] = count
    return result


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z]+", (text or "").lower())


def _to_int(val: str) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None


def _mean(xs: List[float]) -> float:
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


def _sd(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _load_all_trials(workspace: Path, trial_paths: List[Path]) -> Optional[List[Dict[str, object]]]:
    all_rows: List[Dict[str, object]] = []
    for p in trial_paths:
        rows = _safe_load_csv_rows(p)
        if rows is None:
            return None
        for row in rows:
            rec: Dict[str, object] = dict(row)
            rec["participant_id"] = row.get("participant_id", "")
            rec["condition"] = row.get("condition", "")
            rec["rt_ms"] = _to_int(row.get("rt_ms"))
            rec["accuracy"] = _to_int(row.get("accuracy"))
            rec["vividness_rating"] = _to_int(row.get("vividness_rating"))
            rec["report_text"] = row.get("report_text", "")
            all_rows.append(rec)
    return all_rows


def _compute_condition_summary(rows: List[Dict[str, object]], include_conditions: List[str]) -> List[Dict[str, object]]:
    # Aggregate per participant_id, condition for included conditions
    by_group: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    for r in rows:
        cond = str(r.get("condition", ""))
        pid = str(r.get("participant_id", ""))
        if cond in include_conditions:
            by_group.setdefault((pid, cond), []).append(r)
    out: List[Dict[str, object]] = []
    for (pid, cond), rs in sorted(by_group.items()):
        n_trials = len(rs)
        rt_vals = [int(v) for v in [r.get("rt_ms") for r in rs] if isinstance(v, int)]
        acc_vals = [int(v) for v in [r.get("accuracy") for r in rs] if isinstance(v, int)]
        vivid_vals = [int(v) for v in [r.get("vividness_rating") for r in rs] if isinstance(v, int)]
        out.append({
            "participant_id": pid,
            "condition": cond,
            "n_trials": n_trials,
            "mean_rt_ms": _mean(rt_vals),
            "sd_rt_ms": _sd(rt_vals),
            "mean_accuracy": _mean(acc_vals),
            "mean_vividness": _mean(vivid_vals),
        })
    return out


def _compute_valid_trial_flags(rows: List[Dict[str, object]], min_vivid: int, min_words: int, include_conditions: List[str]) -> Dict[int, bool]:
    flags: Dict[int, bool] = {}
    for idx, r in enumerate(rows):
        cond = str(r.get("condition", ""))
        if cond not in include_conditions:
            flags[idx] = False
            continue
        vivid = r.get("vividness_rating")
        text = str(r.get("report_text") or "")
        words = _tokenize_words(text)
        is_valid = isinstance(vivid, int) and vivid >= min_vivid and len(words) >= min_words
        flags[idx] = is_valid
    return flags


def _detect_themes_in_text(text: str, themes: Dict[str, List[str]]) -> List[str]:
    found: List[str] = []
    t = (text or "").lower()
    for theme, keywords in themes.items():
        for kw in keywords:
            kw_l = str(kw).lower()
            if kw_l and kw_l in t:
                found.append(theme)
                break
    return found


def _compute_theme_matrix(rows: List[Dict[str, object]], include_conditions: List[str], themes_cfg: Dict[str, List[str]], min_vivid: int, min_words: int) -> List[Dict[str, object]]:
    # Build valid trials per participant-condition
    groups: Dict[Tuple[str, str], List[Tuple[int, Dict[str, object]]]] = {}
    valid_flags = _compute_valid_trial_flags(rows, min_vivid, min_words, include_conditions)
    for idx, r in enumerate(rows):
        pid = str(r.get("participant_id", ""))
        cond = str(r.get("condition", ""))
        if cond in include_conditions:
            groups.setdefault((pid, cond), []).append((idx, r))
    out: List[Dict[str, object]] = []
    for (pid, cond), lst in sorted(groups.items()):
        valid_indices = [i for i, r in lst if valid_flags.get(i, False)]
        n_valid = len(valid_indices)
        # Count theme matches across valid trials
        theme_counts: Dict[str, int] = {theme: 0 for theme in themes_cfg.keys()}
        for i, r in lst:
            if not valid_flags.get(i, False):
                continue
            text = str(r.get("report_text") or "")
            found = _detect_themes_in_text(text, themes_cfg)
            for theme in found:
                theme_counts[theme] += 1
        for theme in sorted(theme_counts.keys()):
            n_t = theme_counts[theme]
            proportion = (n_t / n_valid) if n_valid > 0 else 0.0
            out.append({
                "participant_id": pid,
                "condition": cond,
                "theme": theme,
                "n_theme_trials": n_t,
                "proportion_of_valid_trials": proportion,
            })
    return out


def _read_condition_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _safe_load_csv_rows(path)


def _read_theme_matrix_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _safe_load_csv_rows(path)


def _float_close(a: float, b: float, tol: float = 1e-9) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_include_conditions_updated": 0.0,
        "config_min_vividness_threshold_updated": 0.0,
        "config_min_report_words_threshold_updated": 0.0,
        "files_loaded_log_exists": 0.0,
        "files_loaded_log_lists_all_trial_csvs": 0.0,
        "files_loaded_log_row_counts_correct": 0.0,
        "condition_summary_exists": 0.0,
        "condition_summary_columns_correct": 0.0,
        "condition_summary_values_correct": 0.0,
        "theme_matrix_exists": 0.0,
        "theme_matrix_columns_correct": 0.0,
        "theme_matrix_values_correct": 0.0,
        "outputs_filter_respects_include_conditions": 0.0,
    }

    # Load config
    cfg_path = workspace / "config" / "analysis_config.yaml"
    cfg = _safe_load_yaml(cfg_path)

    include_conditions: List[str] = []
    min_vivid: Optional[int] = None
    min_words: Optional[int] = None
    data_dir: str = "data"
    output_dir: str = "output"
    coding_scheme_path: Optional[Path] = None

    if isinstance(cfg, dict):
        include_conditions = list(cfg.get("include_conditions") or [])
        min_vivid = cfg.get("min_vividness_for_theme")
        min_words = cfg.get("min_report_words")
        data_dir = str(cfg.get("data_dir") or "data")
        output_dir = str(cfg.get("output_dir") or "output")
        csp = cfg.get("coding_scheme_path")
        if isinstance(csp, str):
            coding_scheme_path = workspace / csp

        # Config checks
        if set(include_conditions) >= {"focused", "mind_wandering"}:
            scores["config_include_conditions_updated"] = 1.0
        if isinstance(min_vivid, int) and min_vivid == 3:
            scores["config_min_vividness_threshold_updated"] = 1.0
        if isinstance(min_words, int) and min_words == 3:
            scores["config_min_report_words_threshold_updated"] = 1.0

    # Discover trial files and counts
    trial_paths = _discover_trial_csvs(workspace, data_dir)
    expected_counts: Dict[str, int] = {}
    all_rows = None
    if trial_paths:
        ok_counts = True
        for p in trial_paths:
            cnt = _csv_row_count(p)
            if cnt is None:
                ok_counts = False
                break
            rel = p.relative_to(workspace).as_posix()
            expected_counts[rel] = cnt
        if ok_counts:
            all_rows = _load_all_trials(workspace, trial_paths)

    # Read files_loaded log
    files_loaded_path = workspace / output_dir / "logs" / "files_loaded.txt"
    if files_loaded_path.exists():
        scores["files_loaded_log_exists"] = 1.0
    log_map = None
    if files_loaded_path.exists() and isinstance(cfg, dict):
        log_map = _parse_files_loaded_log(workspace, data_dir, files_loaded_path)

    # Check log lists all trial CSVs
    if log_map is not None:
        logged_files = set(log_map.keys())
        expected_files = set(expected_counts.keys())
        if logged_files == expected_files:
            scores["files_loaded_log_lists_all_trial_csvs"] = 1.0
        # Check counts match
        counts_match = True
        for rel, cnt in expected_counts.items():
            if rel not in log_map or log_map[rel] != cnt:
                counts_match = False
                break
        if counts_match and expected_counts:
            scores["files_loaded_log_row_counts_correct"] = 1.0
        elif counts_match and not expected_counts:
            # If no trial files, treat as correct only if log also empty
            if not log_map:
                scores["files_loaded_log_row_counts_correct"] = 1.0

    # Paths for expected outputs
    summary_path = workspace / output_dir / "metrics" / "condition_summary.csv"
    theme_path = workspace / output_dir / "themes" / "theme_matrix.csv"

    # Condition summary existence and columns
    summary_rows = None
    if summary_path.exists():
        scores["condition_summary_exists"] = 1.0
        summary_rows = _read_condition_summary_csv(summary_path)
    if summary_rows is not None and summary_rows:
        header = list(summary_rows[0].keys())
        required_header = [
            "participant_id",
            "condition",
            "n_trials",
            "n_valid_trials_for_theme",
            "mean_rt_ms",
            "sd_rt_ms",
            "mean_accuracy",
            "mean_vividness",
        ]
        if header == required_header:
            scores["condition_summary_columns_correct"] = 1.0

    # Theme matrix existence and columns
    theme_rows = None
    if theme_path.exists():
        scores["theme_matrix_exists"] = 1.0
        theme_rows = _read_theme_matrix_csv(theme_path)
    if theme_rows is not None and theme_rows:
        header_t = list(theme_rows[0].keys())
        required_header_t = [
            "participant_id",
            "condition",
            "theme",
            "n_theme_trials",
            "proportion_of_valid_trials",
        ]
        if header_t == required_header_t:
            scores["theme_matrix_columns_correct"] = 1.0

    # Validate outputs filter respects include_conditions
    if summary_rows is not None and theme_rows is not None and isinstance(cfg, dict):
        ok_filter = True
        inc_set = set(include_conditions)
        for r in summary_rows:
            if r.get("condition") not in inc_set:
                ok_filter = False
                break
        if ok_filter:
            for r in theme_rows:
                if r.get("condition") not in inc_set:
                    ok_filter = False
                    break
        if ok_filter:
            scores["outputs_filter_respects_include_conditions"] = 1.0

    # Values correctness: recompute expected based on config and input data
    if all_rows is not None and isinstance(cfg, dict) and summary_rows is not None:
        # Compute summary expected
        # We need n_valid_trials_for_theme using thresholds
        include_conditions_cfg = include_conditions
        min_vivid_cfg = min_vivid if isinstance(min_vivid, int) else None
        min_words_cfg = min_words if isinstance(min_words, int) else None

        # If thresholds missing, cannot compute; fail values checks
        if min_vivid_cfg is not None and min_words_cfg is not None:
            # Compute per group metrics
            summary_expected_map: Dict[Tuple[str, str], Dict[str, object]] = {}
            # Aggregate per group
            groups: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
            for r in all_rows:
                cond = str(r.get("condition", ""))
                pid = str(r.get("participant_id", ""))
                if cond in include_conditions_cfg:
                    groups.setdefault((pid, cond), []).append(r)
            for (pid, cond), rs in groups.items():
                # n_valid_trials_for_theme
                n_valid = 0
                for r in rs:
                    vivid = r.get("vividness_rating")
                    text = str(r.get("report_text") or "")
                    words = _tokenize_words(text)
                    if isinstance(vivid, int) and vivid >= min_vivid_cfg and len(words) >= min_words_cfg:
                        n_valid += 1
                rt_vals = [int(v) for v in [r.get("rt_ms") for r in rs] if isinstance(v, int)]
                acc_vals = [int(v) for v in [r.get("accuracy") for r in rs] if isinstance(v, int)]
                vivid_vals = [int(v) for v in [r.get("vividness_rating") for r in rs] if isinstance(v, int)]
                summary_expected_map[(pid, cond)] = {
                    "participant_id": pid,
                    "condition": cond,
                    "n_trials": len(rs),
                    "n_valid_trials_for_theme": n_valid,
                    "mean_rt_ms": _mean(rt_vals),
                    "sd_rt_ms": _sd(rt_vals),
                    "mean_accuracy": _mean(acc_vals),
                    "mean_vividness": _mean(vivid_vals),
                }

            # Read actual summary rows into map
            summary_actual_map: Dict[Tuple[str, str], Dict[str, object]] = {}
            for r in summary_rows:
                try:
                    pid = r.get("participant_id")
                    cond = r.get("condition")
                    n_trials = int(r.get("n_trials")) if r.get("n_trials") is not None else None
                    n_valid_trials_for_theme = int(r.get("n_valid_trials_for_theme")) if r.get("n_valid_trials_for_theme") is not None else None
                    mean_rt_ms = float(r.get("mean_rt_ms")) if r.get("mean_rt_ms") not in (None, "", "nan") else float("nan")
                    sd_rt_ms = float(r.get("sd_rt_ms")) if r.get("sd_rt_ms") not in (None, "", "nan") else float("nan")
                    mean_accuracy = float(r.get("mean_accuracy")) if r.get("mean_accuracy") not in (None, "", "nan") else float("nan")
                    mean_vividness = float(r.get("mean_vividness")) if r.get("mean_vividness") not in (None, "", "nan") else float("nan")
                except Exception:
                    summary_actual_map = {}
                    break
                summary_actual_map[(pid, cond)] = {
                    "n_trials": n_trials,
                    "n_valid_trials_for_theme": n_valid_trials_for_theme,
                    "mean_rt_ms": mean_rt_ms,
                    "sd_rt_ms": sd_rt_ms,
                    "mean_accuracy": mean_accuracy,
                    "mean_vividness": mean_vividness,
                }

            # Compare sets and values
            if summary_actual_map and summary_expected_map and set(summary_actual_map.keys()) == set(summary_expected_map.keys()):
                ok_vals = True
                for key, exp in summary_expected_map.items():
                    act = summary_actual_map.get(key)
                    if act is None:
                        ok_vals = False
                        break
                    if act.get("n_trials") != exp.get("n_trials"):
                        ok_vals = False
                        break
                    if act.get("n_valid_trials_for_theme") != exp.get("n_valid_trials_for_theme"):
                        ok_vals = False
                        break
                    if not _float_close(float(act.get("mean_rt_ms")), float(exp.get("mean_rt_ms"))):
                        ok_vals = False
                        break
                    if not _float_close(float(act.get("sd_rt_ms")), float(exp.get("sd_rt_ms"))):
                        ok_vals = False
                        break
                    if not _float_close(float(act.get("mean_accuracy")), float(exp.get("mean_accuracy"))):
                        ok_vals = False
                        break
                    if not _float_close(float(act.get("mean_vividness")), float(exp.get("mean_vividness"))):
                        ok_vals = False
                        break
                if ok_vals:
                    scores["condition_summary_values_correct"] = 1.0

    # Theme matrix values correctness
    if all_rows is not None and isinstance(cfg, dict) and theme_rows is not None and coding_scheme_path is not None:
        coding_scheme = _safe_load_yaml(coding_scheme_path)
        if isinstance(coding_scheme, dict) and isinstance(coding_scheme.get("themes"), dict):
            themes_cfg = coding_scheme["themes"]
            include_conditions_cfg = include_conditions
            min_vivid_cfg = min_vivid if isinstance(min_vivid, int) else None
            min_words_cfg = min_words if isinstance(min_words, int) else None
            if min_vivid_cfg is not None and min_words_cfg is not None:
                theme_expected = _compute_theme_matrix(all_rows, include_conditions_cfg, themes_cfg, min_vivid_cfg, min_words_cfg)
                # Build expected map: (pid, cond, theme) -> (n, prop)
                exp_map: Dict[Tuple[str, str, str], Tuple[int, float]] = {}
                for r in theme_expected:
                    exp_map[(str(r["participant_id"]), str(r["condition"]), str(r["theme"]))] = (int(r["n_theme_trials"]), float(r["proportion_of_valid_trials"]))
                # Build actual map
                act_map: Dict[Tuple[str, str, str], Tuple[int, float]] = {}
                parse_ok = True
                for r in theme_rows:
                    try:
                        pid = r.get("participant_id")
                        cond = r.get("condition")
                        theme = r.get("theme")
                        n_theme_trials = int(r.get("n_theme_trials")) if r.get("n_theme_trials") is not None else None
                        prop = float(r.get("proportion_of_valid_trials")) if r.get("proportion_of_valid_trials") not in (None, "", "nan") else float("nan")
                    except Exception:
                        parse_ok = False
                        break
                    act_map[(pid, cond, theme)] = (n_theme_trials, prop)
                if parse_ok and act_map and exp_map and set(act_map.keys()) == set(exp_map.keys()):
                    ok_vals = True
                    for key, (n_exp, p_exp) in exp_map.items():
                        n_act, p_act = act_map.get(key, (None, None))
                        if n_act != n_exp:
                            ok_vals = False
                            break
                        if not _float_close(float(p_act), float(p_exp)):
                            ok_vals = False
                            break
                    if ok_vals:
                        scores["theme_matrix_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()