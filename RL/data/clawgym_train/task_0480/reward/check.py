import json
import csv
import math
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_simple_yaml_config(text: str) -> Dict[str, Any]:
    # Minimal parser for simple YAML: top-level keys and one-level nested maps
    cfg: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" in line:
            # detect indentation
            leading_spaces = len(line) - len(line.lstrip(" "))
            key, val = line.strip().split(":", 1)
            key = key.strip()
            val = val.strip()
            if leading_spaces == 0:
                # top-level key
                current_section = None
                if val == "":
                    # start of nested dict
                    cfg[key] = {}
                    current_section = key
                else:
                    # scalar
                    if key == "version":
                        try:
                            cfg[key] = int(val)
                        except Exception:
                            cfg[key] = val
                    elif key == "score_threshold":
                        try:
                            cfg[key] = float(val)
                        except Exception:
                            cfg[key] = val
                    else:
                        cfg[key] = val
            else:
                # nested under current_section
                if current_section:
                    if current_section not in cfg or not isinstance(cfg[current_section], dict):
                        cfg[current_section] = {}
                    sub = cfg[current_section]
                    # attempt to parse float if possible
                    try:
                        sub[key] = float(val)
                    except Exception:
                        sub[key] = val
                # else ignore malformed nesting
    return cfg


def _to_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def _to_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _format_4(x: float) -> str:
    return f"{x:.4f}"


def _compute_min_max(rows: List[Dict[str, str]], features: List[str]) -> Dict[str, Tuple[float, float]]:
    mm: Dict[str, Tuple[float, float]] = {}
    for feat in features:
        vals = []
        for r in rows:
            vals.append(_to_float(r.get(feat, "nan")))
        finite = [v for v in vals if math.isfinite(v)]
        if not finite:
            mm[feat] = (0.0, 0.0)
        else:
            mm[feat] = (min(finite), max(finite))
    return mm


def _normalize_value(value: float, mn: float, mx: float) -> float:
    if not math.isfinite(value) or not math.isfinite(mn) or not math.isfinite(mx):
        return float("nan")
    if mx == mn:
        return 0.0
    return (value - mn) / (mx - mn)


def _compute_expected_scores(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    # v2 required spec
    weights = {
        "interests_overlap": 0.5,
        "messages_exchanged": 0.3,
        "location_distance_km": 0.2,
    }
    negative_features = {"location_distance_km"}
    threshold = 0.6

    features = list(weights.keys())
    mm = _compute_min_max(rows, features)

    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("pair_id", "")).strip()
        score_sum = 0.0
        valid = True
        for feat in features:
            v = _to_float(r.get(feat, "nan"))
            mn, mx = mm[feat]
            norm = _normalize_value(v, mn, mx)
            if not math.isfinite(norm):
                valid = False
                break
            if feat in negative_features:
                norm = 1.0 - norm
            score_sum += weights[feat] * norm
        if not valid:
            # Mark invalid with NaN so comparisons will fail
            comp_score = float("nan")
        else:
            comp_score = score_sum
        pred = 1 if (math.isfinite(comp_score) and comp_score >= threshold) else 0
        result[pid] = {
            "pair_id": pid,
            "person_a_id": r.get("person_a_id"),
            "person_b_id": r.get("person_b_id"),
            "compatibility_score": comp_score,
            "compatibility_score_rounded": _format_4(comp_score) if math.isfinite(comp_score) else "",
            "predicted_match": pred,
            "matched_label": _to_int(r.get("matched_label")),
            "age_gap_years": _to_float(r.get("age_gap_years")),
        }
    return result


def _compute_metrics(expected: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    # metrics from expected unrounded scores
    scores = [v["compatibility_score"] for v in expected.values() if math.isfinite(v["compatibility_score"])]
    predicted = [v["predicted_match"] for v in expected.values()]
    labels = [v["matched_label"] for v in expected.values()]
    count_pairs = len(expected)
    mean_score = sum(scores) / len(scores) if scores else 0.0
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    if n == 0:
        median_score = 0.0
    elif n % 2 == 1:
        median_score = sorted_scores[n // 2]
    else:
        median_score = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2.0
    if n > 0:
        var = sum((s - mean_score) ** 2 for s in scores) / n
        std_score = math.sqrt(var)
    else:
        std_score = 0.0
    acc_rate = (sum(1 for p in predicted if p == 1) / count_pairs) if count_pairs > 0 else 0.0
    # Precision and recall
    tp = sum(1 for p, y in zip(predicted, labels) if p == 1 and y == 1)
    fp = sum(1 for p, y in zip(predicted, labels) if p == 1 and y == 0)
    fn = sum(1 for p, y in zip(predicted, labels) if p == 0 and y == 1)
    precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    # Age gap buckets acceptance_rate
    buckets = {"0-3": [], "4-7": [], "8+": []}
    for v in expected.values():
        age_gap = v["age_gap_years"]
        pred = v["predicted_match"]
        if not math.isfinite(age_gap):
            continue
        if 0 <= age_gap <= 3:
            buckets["0-3"].append(pred)
        elif 4 <= age_gap <= 7:
            buckets["4-7"].append(pred)
        elif age_gap >= 8:
            buckets["8+"].append(pred)
    bucket_rates: Dict[str, float] = {}
    for k, preds in buckets.items():
        if len(preds) == 0:
            bucket_rates[k] = 0.0
        else:
            bucket_rates[k] = sum(1 for p in preds if p == 1) / len(preds)

    return {
        "count_pairs": count_pairs,
        "mean_score": mean_score,
        "median_score": median_score,
        "std_score": std_score,
        "acceptance_rate": acc_rate,
        "precision": precision,
        "recall": recall,
        "age_gap_buckets": bucket_rates,
    }


def _compare_floats(a: float, b: float, tol: float = 1e-6) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _require_columns_exact(header: List[str], expected: List[str]) -> bool:
    return header == expected


def _find_age_bucket_map_in_json(obj: Any) -> Optional[Dict[str, float]]:
    # recursively search for dict with keys "0-3","4-7","8+"
    if isinstance(obj, dict):
        keys = set(obj.keys())
        if {"0-3", "4-7", "8+"}.issubset(keys):
            # ensure numeric values
            try:
                return {k: float(obj[k]) for k in ["0-3", "4-7", "8+"]}
            except Exception:
                return None
        for v in obj.values():
            found = _find_age_bucket_map_in_json(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_age_bucket_map_in_json(it)
            if found is not None:
                return found
    return None


def _number_present_in_text(value: float, text: str) -> bool:
    # Generate several string representations and search
    candidates: List[str] = []
    if abs(value - round(value)) < 1e-12:
        candidates.append(str(int(round(value))))
    # Add fixed decimal formats
    for d in [4, 3, 2, 1]:
        candidates.append(f"{value:.{d}f}")
    # Also add raw rounded to 6 decimals trimmed
    raw = f"{value:.6f}".rstrip("0").rstrip(".")
    if raw:
        candidates.append(raw)
    # Remove duplicates
    seen = set()
    uniq_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq_candidates.append(c)
    lower_text = text
    for c in uniq_candidates:
        if c in lower_text:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_version_and_threshold": 0.0,
        "config_weights": 0.0,
        "config_feature_directions_negative_location": 0.0,
        "scores_csv_columns_and_rowcount": 0.0,
        "scores_csv_values_correct": 0.0,
        "metrics_json_overall_correct": 0.0,
        "metrics_json_age_buckets_correct": 0.0,
        "report_summarizes_changes": 0.0,
        "report_overall_metrics_match_json": 0.0,
        "report_bucket_rates_match_json": 0.0,
        "code_file_updated_for_v2": 0.0,
    }

    # Paths
    cfg_path = workspace / "config" / "matching.yaml"
    input_csv_path = workspace / "input" / "pair_features.csv"
    scores_csv_path = workspace / "output" / "scores.csv"
    metrics_json_path = workspace / "output" / "metrics.json"
    report_md_path = workspace / "docs" / "update_report.md"
    score_py_path = workspace / "src" / "score.py"

    # Load input CSV
    input_rows = _safe_read_csv_dicts(input_csv_path)

    # Parse config
    cfg_text = _safe_read_text(cfg_path)
    cfg = {}
    if cfg_text is not None:
        cfg = _parse_simple_yaml_config(cfg_text)

    # Check config version and normalization and threshold
    try:
        version_ok = (cfg.get("version") == 2)
        normalization_ok = (str(cfg.get("normalization", "")).strip().lower() == "minmax")
        threshold_ok = (abs(float(cfg.get("score_threshold", float("nan"))) - 0.6) < 1e-9)
        if version_ok and normalization_ok and threshold_ok:
            scores["config_version_and_threshold"] = 1.0
    except Exception:
        pass

    # Check config weights
    try:
        weights = cfg.get("weights", {}) if isinstance(cfg.get("weights", {}), dict) else {}
        expected_weights = {
            "interests_overlap": 0.5,
            "messages_exchanged": 0.3,
            "location_distance_km": 0.2,
        }
        if set(weights.keys()) == set(expected_weights.keys()):
            all_match = True
            for k, v in expected_weights.items():
                if not _compare_floats(float(weights.get(k)), float(v), tol=1e-9):
                    all_match = False
                    break
            if all_match:
                scores["config_weights"] = 1.0
    except Exception:
        pass

    # Check config feature_directions
    try:
        fd = cfg.get("feature_directions", {}) if isinstance(cfg.get("feature_directions", {}), dict) else {}
        val = str(fd.get("location_distance_km", "")).strip().lower()
        if val == "negative":
            scores["config_feature_directions_negative_location"] = 1.0
    except Exception:
        pass

    # Compute expected scores from v2 spec (independent of config file content)
    expected_scores: Dict[str, Dict[str, Any]] = {}
    if input_rows is not None:
        expected_scores = _compute_expected_scores(input_rows)

    # Validate scores.csv
    scores_csv_ok = False
    values_ok = False
    out_rows = _safe_read_csv_dicts(scores_csv_path)
    expected_cols = ["pair_id", "person_a_id", "person_b_id", "compatibility_score", "predicted_match", "matched_label"]
    if out_rows is not None:
        # Check columns and rowcount and pair coverage
        try:
            with scores_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            columns_ok = _require_columns_exact(header, expected_cols)
        except Exception:
            columns_ok = False
        rowcount_ok = (input_rows is not None and len(out_rows) == len(input_rows))
        # Check pair id sets
        try:
            input_ids = set(str(r.get("pair_id", "")).strip() for r in (input_rows or []))
            out_ids = set(str(r.get("pair_id", "")).strip() for r in out_rows)
            idset_ok = (input_ids == out_ids)
        except Exception:
            idset_ok = False
        if columns_ok and rowcount_ok and idset_ok:
            scores_csv_ok = True
            scores["scores_csv_columns_and_rowcount"] = 1.0

        # Check values correctness against expected
        try:
            # Index expected and input by pair_id for verification
            expected_by_id = expected_scores
            input_by_id = {str(r.get("pair_id", "")).strip(): r for r in (input_rows or [])}
            all_match = True
            for r in out_rows:
                pid = str(r.get("pair_id", "")).strip()
                if pid not in expected_by_id or pid not in input_by_id:
                    all_match = False
                    break
                exp = expected_by_id[pid]
                # Check identity fields match input
                if str(r.get("person_a_id", "")).strip() != str(exp["person_a_id"]).strip():
                    all_match = False
                    break
                if str(r.get("person_b_id", "")).strip() != str(exp["person_b_id"]).strip():
                    all_match = False
                    break
                # Check score rounded 4 decimals
                out_score_str = str(r.get("compatibility_score", "")).strip()
                if out_score_str != exp["compatibility_score_rounded"]:
                    all_match = False
                    break
                # Check predicted_match
                try:
                    out_pred = int(str(r.get("predicted_match", "")).strip())
                except Exception:
                    all_match = False
                    break
                if out_pred != exp["predicted_match"]:
                    all_match = False
                    break
                # Check matched_label equals input
                try:
                    out_label = int(str(r.get("matched_label", "")).strip())
                except Exception:
                    all_match = False
                    break
                if out_label != exp["matched_label"]:
                    all_match = False
                    break
            if all_match:
                values_ok = True
                scores["scores_csv_values_correct"] = 1.0
        except Exception:
            pass

    # Validate metrics.json
    metrics_data = _safe_load_json(metrics_json_path)
    if metrics_data is not None and expected_scores:
        expected_metrics = _compute_metrics(expected_scores)
        try:
            overall_ok = True
            for key in ["count_pairs", "mean_score", "median_score", "std_score", "acceptance_rate", "precision", "recall"]:
                if key not in metrics_data:
                    overall_ok = False
                    break
                exp_val = expected_metrics[key]
                try:
                    got_val = float(metrics_data[key]) if key != "count_pairs" else int(metrics_data[key])
                    if key == "count_pairs":
                        if int(got_val) != int(exp_val):
                            overall_ok = False
                            break
                    else:
                        if not _compare_floats(float(got_val), float(exp_val), tol=1e-6):
                            overall_ok = False
                            break
                except Exception:
                    overall_ok = False
                    break
            if overall_ok:
                scores["metrics_json_overall_correct"] = 1.0
        except Exception:
            pass

        # Age bucket acceptance rates
        try:
            bucket_map = _find_age_bucket_map_in_json(metrics_data)
            expected_buckets = expected_metrics["age_gap_buckets"]
            buckets_ok = True
            if bucket_map is None:
                buckets_ok = False
            else:
                for k in ["0-3", "4-7", "8+"]:
                    if k not in bucket_map:
                        buckets_ok = False
                        break
                    if not _compare_floats(float(bucket_map[k]), float(expected_buckets[k]), tol=1e-6):
                        buckets_ok = False
                        break
            if buckets_ok:
                scores["metrics_json_age_buckets_correct"] = 1.0
        except Exception:
            pass

    # Validate report markdown
    report_text = _safe_read_text(report_md_path)
    if report_text is not None:
        text_lower = report_text.lower()
        # Summarizes v2 architecture changes: weights, negative feature handling, and threshold
        try:
            v2_ok = ("v2" in text_lower) or ("version 2" in text_lower)
            weights_ok = ("weights" in text_lower and "interests_overlap" in report_text and "messages_exchanged" in report_text and "location_distance_km" in report_text and ("0.5" in report_text) and ("0.3" in report_text) and ("0.2" in report_text))
            threshold_ok = ("threshold" in text_lower and "0.6" in report_text)
            # negative feature handling for location_distance_km
            neg_ok = False
            # check occurrence on same line or context
            for line in report_text.splitlines():
                if "location_distance_km" in line and ("negative" in line.lower()):
                    neg_ok = True
                    break
            if not neg_ok:
                # broader search around mentions
                idx = report_text.find("location_distance_km")
                if idx != -1:
                    window = report_text[max(0, idx - 100): idx + 100]
                    if "negative" in window.lower():
                        neg_ok = True
            if v2_ok and weights_ok and threshold_ok and neg_ok:
                scores["report_summarizes_changes"] = 1.0
        except Exception:
            pass

        # Report numbers must match metrics.json for overall metrics and buckets
        # Overall metrics
        try:
            if metrics_data is not None:
                overall_match = True
                for key in ["count_pairs", "mean_score", "median_score", "std_score", "acceptance_rate", "precision", "recall"]:
                    if key not in metrics_data:
                        overall_match = False
                        break
                    val = metrics_data[key]
                    if isinstance(val, int):
                        num_ok = _number_present_in_text(float(val), report_text)
                    else:
                        num_ok = _number_present_in_text(float(val), report_text)
                    if not num_ok:
                        overall_match = False
                        break
                if overall_match:
                    scores["report_overall_metrics_match_json"] = 1.0
        except Exception:
            pass

        # Bucketed acceptance rates
        try:
            if metrics_data is not None:
                bucket_map = _find_age_bucket_map_in_json(metrics_data)
                if bucket_map is not None:
                    labels_present = all(lbl in report_text for lbl in ["0-3", "4-7", "8+"])
                    nums_ok = all(_number_present_in_text(float(bucket_map[k]), report_text) for k in ["0-3", "4-7", "8+"])
                    if labels_present and nums_ok:
                        scores["report_bucket_rates_match_json"] = 1.0
        except Exception:
            pass

    # Code file updated for v2 (heuristic static checks)
    code_text = _safe_read_text(score_py_path)
    if code_text is not None:
        has_feature_dir = ("feature_direction" in code_text) or ("feature_directions" in code_text)
        has_negative = "negative" in code_text.lower()
        has_inversion = "(1 - " in code_text.replace(" ", "") or "1-" in code_text.replace(" ", "")
        reads_cfg = "config/matching.yaml" in code_text or "matching.yaml" in code_text
        writes_scores = "scores.csv" in code_text
        writes_metrics = "metrics.json" in code_text
        if has_feature_dir and has_negative and has_inversion and reads_cfg and writes_scores and writes_metrics:
            scores["code_file_updated_for_v2"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()