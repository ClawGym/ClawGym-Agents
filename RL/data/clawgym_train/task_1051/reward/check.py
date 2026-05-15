import json
import sys
import csv
import math
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import importlib.util


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_write_json(obj: Dict[str, Any]) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _load_quality_checks(py_path: Path) -> Optional[Any]:
    try:
        if not py_path.exists():
            return None
        spec = importlib.util.spec_from_file_location("quality_checks", str(py_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_inline_list(val: str) -> Optional[List[Any]]:
    try:
        # Replace YAML-like booleans/null if any (not expected here)
        return ast.literal_eval(val)
    except Exception:
        # Try to split manually if simple CSV-like within brackets
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                return []
            parts = [p.strip() for p in inner.split(",")]
            return [ _strip_quotes(p) for p in parts ]
        return None


def _parse_scalar(val: str) -> Any:
    sval = val.strip()
    if not sval:
        return None
    # Try inline list
    if sval.startswith("[") and sval.endswith("]"):
        lst = _parse_inline_list(sval)
        if lst is not None:
            return lst
    # Try int
    try:
        if re.fullmatch(r"[+-]?\d+", sval):
            return int(sval)
    except Exception:
        pass
    # Try float
    try:
        if re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", sval):
            return float(sval)
    except Exception:
        pass
    # String (strip quotes if present)
    return _strip_quotes(sval)


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the provided config format.
    Supports:
    - top-level mappings
    - nested mapping under 'weights'
    - list under 'output_columns' (dash list)
    - inline list for 'include_labels'
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None
    in_list_section: Optional[str] = None
    indent_base = None

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Determine indentation
        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # Handle list items
        if in_list_section is not None and content.startswith("- "):
            item = content[2:].strip()
            if isinstance(result.get(in_list_section), list):
                result[in_list_section].append(_strip_quotes(item))
            i += 1
            continue
        elif in_list_section is not None and not content.startswith("- "):
            # end of list section
            in_list_section = None

        # Key: value or Key:
        if ":" in content:
            key, after = content.split(":", 1)
            key = key.strip()
            val = after.strip()

            if key == "weights":
                # Start weights mapping block
                result["weights"] = {}
                current_section = "weights"
                # parse subsequent indented mapping lines
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip() or next_line.strip().startswith("#"):
                        i += 1
                        continue
                    n_leading = len(next_line) - len(next_line.lstrip(" "))
                    n_content = next_line.strip()
                    if n_leading <= leading_spaces:
                        break
                    # Expect "feature: value"
                    if ":" in n_content:
                        k, v = n_content.split(":", 1)
                        k = k.strip()
                        v = v.strip()
                        try:
                            result["weights"][k] = float(_parse_scalar(v))
                        except Exception:
                            return None
                        i += 1
                        continue
                    else:
                        # malformed
                        return None
                continue  # don't increment here, already advanced
            elif key == "output_columns":
                # Could be inline list or block list
                if val:
                    parsed = _parse_inline_list(val)
                    if parsed is None:
                        return None
                    result["output_columns"] = [str(x) for x in parsed]
                    i += 1
                    continue
                else:
                    # Block list with dashes
                    result["output_columns"] = []
                    in_list_section = "output_columns"
                    i += 1
                    continue
            else:
                # scalar or inline list
                parsed_val = _parse_scalar(val)
                result[key] = parsed_val
                current_section = None
                i += 1
                continue
        else:
            # Malformed line
            i += 1
            continue

    # Basic validation of expected keys
    required_keys = ["weights", "include_labels", "normalization", "risk_score_min", "top_n", "output_columns"]
    for rk in required_keys:
        if rk not in result:
            return None
    # Coerce types
    try:
        result["risk_score_min"] = float(result["risk_score_min"])
        result["top_n"] = int(result["top_n"])
        # include_labels to list of strings
        if not isinstance(result["include_labels"], list):
            return None
        result["include_labels"] = [str(x) for x in result["include_labels"]]
        if not isinstance(result["weights"], dict):
            return None
        # cast weights to float
        for k in list(result["weights"].keys()):
            result["weights"][k] = float(result["weights"][k])
        if not isinstance(result["output_columns"], list):
            return None
        result["output_columns"] = [str(x) for x in result["output_columns"]]
        result["normalization"] = str(result["normalization"])
    except Exception:
        return None

    return result


def _read_csv_dict(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [row for row in reader]
        return (header, rows)
    except Exception:
        return None


def _canonical_id(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    try:
        # Try to interpret as int (handles "123.0" poorly; ensure not float string)
        if re.fullmatch(r"[+-]?\d+", s):
            return str(int(s))
        # If float-like integer string (e.g., "123.0"), coerce to int if possible
        if re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", s):
            f = float(s)
            if f.is_integer():
                return str(int(f))
    except Exception:
        pass
    return s


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_raw_wdbc(raw_path: Path, feature_map: Dict[int, str]) -> Optional[List[Dict[str, Any]]]:
    text = _safe_read_text(raw_path)
    if text is None:
        return None
    records: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(feature_map):
            # malformed line
            return None
        rec: Dict[str, Any] = {}
        for idx, val in enumerate(parts, start=1):
            name = feature_map.get(idx)
            if name is None:
                return None
            # Assign raw values as strings; we'll convert as needed
            rec[name] = val
        records.append(rec)
    return records


def _build_feature_map(mapping_json: Dict[str, Any]) -> Optional[Dict[int, str]]:
    try:
        cols = mapping_json.get("columns")
        if not isinstance(cols, list):
            return None
        fmap: Dict[int, str] = {}
        for entry in cols:
            idx = int(entry["index"])
            name = str(entry["name"])
            fmap[idx] = name
        # Ensure contiguous indices starting from 1
        if sorted(fmap.keys()) != list(range(1, len(fmap) + 1)):
            return None
        return fmap
    except Exception:
        return None


def _compute_minmax(records: List[Dict[str, Any]], numeric_features: List[str], id_col: str, label_col: str) -> Dict[str, Tuple[float, float]]:
    mins: Dict[str, float] = {}
    maxs: Dict[str, float] = {}
    for feat in numeric_features:
        mins[feat] = math.inf
        maxs[feat] = -math.inf
    for rec in records:
        for feat in numeric_features:
            v = _to_float(rec.get(feat))
            if v is None:
                continue
            if v < mins[feat]:
                mins[feat] = v
            if v > maxs[feat]:
                maxs[feat] = v
    mm: Dict[str, Tuple[float, float]] = {}
    for feat in numeric_features:
        mm[feat] = (mins[feat], maxs[feat])
    return mm


def _normalize_value(x: Optional[float], min_val: float, max_val: float) -> float:
    if x is None:
        return 0.0
    if max_val == min_val:
        return 0.0
    return (x - min_val) / (max_val - min_val)


def _compute_expected_scores(
    records: List[Dict[str, Any]],
    weights: Dict[str, float],
    tiebreak_features: List[str],
    mm: Dict[str, Tuple[float, float]],
    id_col: str,
    label_col: str
) -> Dict[str, Dict[str, Any]]:
    expected: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        rec_id = _canonical_id(rec.get(id_col))
        # Compute normalized features for weights and tiebreaks
        norm_feats: Dict[str, float] = {}
        for feat in set(list(weights.keys()) + tiebreak_features):
            v = _to_float(rec.get(feat))
            mn, mx = mm.get(feat, (0.0, 0.0))
            norm_feats[feat] = _normalize_value(v, mn, mx)
        # Weighted sum
        risk = 0.0
        for feat, w in weights.items():
            risk += w * norm_feats.get(feat, 0.0)
        expected[rec_id] = {
            "diagnosis": str(rec.get(label_col, "")).strip(),
            "risk_score": risk,
            "norm": norm_feats
        }
    return expected


def _float_eq(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _rank_filtered(
    expected: Dict[str, Dict[str, Any]],
    include_labels: List[str],
    risk_min: float,
    tiebreak_order: List[str],
    tiebreak_dir: str
) -> List[str]:
    # Filter ids
    filtered_ids = []
    for rid, info in expected.items():
        label = info.get("diagnosis", "")
        risk = info.get("risk_score", 0.0)
        if label in include_labels and risk >= risk_min:
            filtered_ids.append(rid)
    # Sort with risk desc and tiebreaks
    desc = (tiebreak_dir.lower() == "desc")

    def key_fn(rid: str):
        info = expected[rid]
        risk = info.get("risk_score", 0.0)
        key: List[Any] = []
        # Primary: risk_score desc
        key.append(-risk)
        # Tiebreaks
        for feat in tiebreak_order:
            val = info["norm"].get(feat, 0.0)
            key.append(-val if desc else val)
        # Stable final key by id to ensure deterministic order if still tied
        key.append(rid)
        return tuple(key)

    return sorted(filtered_ids, key=key_fn)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_file_present": 0.0,
        "raw_shape_validated": 0.0,
        "outputs_presence_vs_validation_gate": 0.0,
        "cleaned_records_columns_from_mapping": 0.0,
        "cleaned_records_row_count": 0.0,
        "risk_score_correctness_all_rows": 0.0,
        "top_candidates_filter_and_count": 0.0,
        "ranking_and_tie_break_correct": 0.0,
        "top_candidates_columns_match_cleaned": 0.0,
        "summary_fields_and_consistency": 0.0,
    }

    # Paths
    feature_map_path = workspace / "input" / "feature_mapping.json"
    config_yaml_path = workspace / "input" / "scoring_config.yaml"
    quality_checks_path = workspace / "input" / "quality_checks.py"
    raw_path = workspace / "data" / "raw" / "wdbc.data"
    cleaned_path = workspace / "output" / "cleaned_records.csv"
    top_path = workspace / "output" / "top_candidates.csv"
    summary_path = workspace / "output" / "summary.json"
    validation_err_path = workspace / "output" / "validation_errors.txt"

    # Load inputs
    qc = _load_quality_checks(quality_checks_path)
    fmap_json = _safe_load_json(feature_map_path)
    config = _parse_simple_yaml(config_yaml_path)

    # Baseline gates for inputs
    if qc is None or fmap_json is None or config is None:
        # If any essential input missing or malformed, most checks cannot proceed
        return scores

    # Build feature map
    feature_map = _build_feature_map(fmap_json)
    if feature_map is None:
        return scores

    # Check raw file presence
    if raw_path.exists() and raw_path.is_file():
        scores["raw_file_present"] = 1.0

    # Parse raw
    raw_records = _parse_raw_wdbc(raw_path, feature_map) if scores["raw_file_present"] > 0 else None

    # Validate raw shape using qc constants
    raw_valid = False
    if raw_records is not None:
        # Expected features
        exp_recs = getattr(qc, "EXPECTED_RECORDS", None)
        exp_feats = getattr(qc, "EXPECTED_FEATURES", None)
        valid_labels = getattr(qc, "VALID_LABELS", None)
        if isinstance(exp_recs, int) and isinstance(exp_feats, int) and isinstance(valid_labels, (set, frozenset)):
            # Check features count per row
            features_ok = True
            for rec in raw_records:
                if len(rec.keys()) != exp_feats:
                    features_ok = False
                    break
            # Check count and label set
            labels_ok = True
            for rec in raw_records:
                lab = str(rec.get("diagnosis", "")).strip()
                if lab not in valid_labels:
                    labels_ok = False
                    break
            if len(raw_records) == exp_recs and features_ok and labels_ok:
                raw_valid = True

    if raw_valid:
        scores["raw_shape_validated"] = 1.0

    # Determine gating behavior
    outputs_exist = cleaned_path.exists() and top_path.exists() and summary_path.exists()
    validation_err_exists = validation_err_path.exists()
    gate_ok = False
    if raw_valid:
        # Should produce outputs and no validation_errors
        if outputs_exist and (not validation_err_exists):
            gate_ok = True
    else:
        # Should produce validation_errors and not produce other outputs
        if validation_err_exists and (not cleaned_path.exists()) and (not top_path.exists()) and (not summary_path.exists()):
            gate_ok = True
    scores["outputs_presence_vs_validation_gate"] = 1.0 if gate_ok else 0.0

    # If we cannot proceed due to missing outputs or invalid raw when expecting outputs, leave remaining scores as 0
    if not raw_valid or not outputs_exist:
        return scores

    # Read cleaned and top CSVs
    cleaned = _read_csv_dict(cleaned_path)
    top = _read_csv_dict(top_path)
    if cleaned is None or top is None:
        return scores
    cleaned_header, cleaned_rows = cleaned
    top_header, top_rows = top

    # Verify cleaned header contains all mapping columns + risk_score
    mapping_names = [feature_map[i] for i in sorted(feature_map.keys())]
    header_has_all_mapping = all(name in cleaned_header for name in mapping_names)
    header_has_risk = "risk_score" in cleaned_header
    if header_has_all_mapping and header_has_risk:
        scores["cleaned_records_columns_from_mapping"] = 1.0

    # Verify cleaned row count equals raw record count and expected
    if len(cleaned_rows) == len(raw_records) == getattr(qc, "EXPECTED_RECORDS", -1):
        scores["cleaned_records_row_count"] = 1.0

    # Compute expected risk scores and tiebreak normalized features
    id_col = "id"
    label_col = "diagnosis"
    # Numeric features are all except id and diagnosis
    numeric_features = [n for n in mapping_names if n not in (id_col, label_col)]
    mm = _compute_minmax(raw_records, numeric_features, id_col, label_col)
    tiebreak_order = list(getattr(qc, "TIEBREAK_ORDER", []))
    tiebreak_dir = str(getattr(qc, "TIEBREAK_DIRECTION", "desc"))
    expected_map = _compute_expected_scores(
        raw_records,
        config["weights"],
        tiebreak_order,
        mm,
        id_col,
        label_col
    )

    # Risk score correctness: compare every row by id
    all_ok = True
    for row in cleaned_rows:
        rid = _canonical_id(row.get(id_col))
        if rid not in expected_map:
            all_ok = False
            break
        expected_risk = expected_map[rid]["risk_score"]
        actual_risk = _to_float(row.get("risk_score"))
        if not _float_eq(expected_risk, actual_risk, tol=1e-6):
            all_ok = False
            break
    if all_ok and len(cleaned_rows) == len(expected_map):
        scores["risk_score_correctness_all_rows"] = 1.0

    # Filter and ranking
    include_labels = [str(x) for x in config["include_labels"]]
    risk_min = float(config["risk_score_min"])
    ranked_ids = _rank_filtered(expected_map, include_labels, risk_min, tiebreak_order, tiebreak_dir)
    filtered_count = len(ranked_ids)
    top_n = int(config["top_n"])
    expected_top_count = min(filtered_count, top_n)

    # Check top_candidates filter membership and count
    top_ids = [_canonical_id(r.get(id_col)) for r in top_rows]
    count_ok = (len(top_rows) == expected_top_count)
    membership_ok = all(tid in set(ranked_ids) for tid in top_ids)
    if count_ok and membership_ok:
        scores["top_candidates_filter_and_count"] = 1.0

    # Ranking and tie-break exact order
    expected_top_ids = ranked_ids[:expected_top_count]
    if top_ids == expected_top_ids:
        scores["ranking_and_tie_break_correct"] = 1.0

    # Top candidates columns match cleaned columns exactly
    if cleaned_header == top_header and len(cleaned_header) > 0:
        scores["top_candidates_columns_match_cleaned"] = 1.0

    # Summary fields and consistency
    summary = _safe_load_json(summary_path)
    summary_ok = False
    if summary is not None and isinstance(summary, dict):
        try:
            source_ok = summary.get("source") == "UCI Machine Learning Repository"
            dataset_ok = summary.get("dataset") == "Breast Cancer Wisconsin (Diagnostic)"
            raw_file_ok = summary.get("raw_file") == "wdbc.data"
            total_rows_ok = int(summary.get("total_rows")) == len(raw_records)
            filtered_rows_ok = int(summary.get("filtered_rows")) == filtered_count
            topn_field_ok = int(summary.get("top_n")) == top_n
            normalization_ok = str(summary.get("normalization")) == str(config["normalization"])
            weights_ok = summary.get("weights_used") == config["weights"]
            top_len_ok = len(top_rows) == expected_top_count
            summary_ok = all([
                source_ok, dataset_ok, raw_file_ok, total_rows_ok, filtered_rows_ok,
                topn_field_ok, normalization_ok, weights_ok, top_len_ok
            ])
        except Exception:
            summary_ok = False
    if summary_ok:
        scores["summary_fields_and_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(_safe_write_json(result))


if __name__ == "__main__":
    main()