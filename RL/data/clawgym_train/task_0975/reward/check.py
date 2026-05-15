import json
import csv
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_scalar(token: str) -> Any:
    token = token.strip()
    if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
        return token[1:-1]
    try:
        return int(token)
    except Exception:
        pass
    try:
        return float(token)
    except Exception:
        pass
    low = token.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    return token


def _parse_config_yaml_specific(path: Path) -> Optional[Dict[str, Any]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    cfg: Dict[str, Any] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        def is_list_item(s: str) -> bool:
            t = s.lstrip("\t")
            return (s.startswith("  - ") or t.startswith("- ")) and ":" not in s.split("#")[0]

        def is_child_kv(s: str) -> bool:
            return s.startswith("  ") and (":" in s) and not s.strip().startswith("- ")

        if stripped.startswith("id_var:"):
            val = stripped.split(":", 1)[1].strip()
            cfg["id_var"] = _parse_scalar(val)
        elif stripped.startswith("correlation_method:"):
            val = stripped.split(":", 1)[1].strip()
            cfg["correlation_method"] = _parse_scalar(val)
        elif stripped == "group_by:":
            lst: List[Any] = []
            j = i + 1
            while j < n and is_list_item(lines[j]):
                item = lines[j].split("-", 1)[1].strip()
                lst.append(_parse_scalar(item))
                j += 1
            cfg["group_by"] = lst
            i = j - 1
        elif stripped == "numeric_vars:":
            lst = []
            j = i + 1
            while j < n and is_list_item(lines[j]):
                item = lines[j].split("-", 1)[1].strip()
                lst.append(_parse_scalar(item))
                j += 1
            cfg["numeric_vars"] = lst
            i = j - 1
        elif stripped == "missing_value_codes:":
            lst = []
            j = i + 1
            while j < n and is_list_item(lines[j]):
                item = lines[j].split("-", 1)[1].strip()
                lst.append(_parse_scalar(item))
                j += 1
            cfg["missing_value_codes"] = lst
            i = j - 1
        elif stripped == "outputs:":
            out: Dict[str, Any] = {}
            j = i + 1
            while j < n and is_child_kv(lines[j]):
                child = lines[j].strip()
                if ":" in child:
                    key, val = child.split(":", 1)
                    out[key.strip()] = _parse_scalar(val.strip())
                j += 1
            cfg["outputs"] = out
            i = j - 1
        else:
            if ":" in stripped and not stripped.startswith("- "):
                key, val = stripped.split(":", 1)
                cfg[key.strip()] = _parse_scalar(val.strip())
        i += 1
    required_keys = ["id_var", "group_by", "numeric_vars", "missing_value_codes", "outputs"]
    for k in required_keys:
        if k not in cfg:
            return None
    if not isinstance(cfg["group_by"], list) or not isinstance(cfg["numeric_vars"], list):
        return None
    if not isinstance(cfg["missing_value_codes"], list):
        return None
    if not isinstance(cfg["outputs"], dict):
        return None
    return cfg


def _load_var_labels_py(path: Path) -> Optional[Dict[str, str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        ns: Dict[str, Any] = {}
        exec(compile(text, str(path), "exec"), {"__builtins__": {}}, ns)
        var_labels = ns.get("VAR_LABELS")
        if isinstance(var_labels, dict):
            return {str(k): str(v) for k, v in var_labels.items()}
        return None
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _to_missing(value: Optional[str], missing_codes: List[Any]) -> bool:
    if value is None:
        return True
    v = value
    for mc in missing_codes:
        if isinstance(mc, str):
            if v == mc:
                return True
        else:
            try:
                if v.strip() == str(mc):
                    return True
            except Exception:
                pass
    return False


def _parse_float_maybe(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    st = s.strip()
    if st == "":
        return None
    low = st.lower()
    if low in ("nan", "na", "null", "none"):
        return float("nan")
    try:
        return float(st)
    except Exception:
        return None


def _is_close(a: float, b: float, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    if isinstance(a, float) and math.isnan(a) and isinstance(b, float) and math.isnan(b):
        return True
    if isinstance(a, float) and math.isnan(a):
        return False
    if isinstance(b, float) and math.isnan(b):
        return False
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _group_key(row: Dict[str, Any], keys: List[str]) -> Tuple:
    return tuple(row.get(k) for k in keys)


def _compute_group_stats(
    rows: List[Dict[str, Any]],
    group_by: List[str],
    numeric_vars: List[str],
    missing_codes: List[Any],
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        key = _group_key(r, group_by)
        groups.setdefault(key, []).append(r)

    results: List[Dict[str, Any]] = []
    for gkey, grows in groups.items():
        for var in numeric_vars:
            vals: List[float] = []
            for r in grows:
                valstr = r.get(var, "")
                if not _to_missing(valstr, missing_codes):
                    v = _parse_float_maybe(valstr)
                    if v is not None and not (isinstance(v, float) and math.isnan(v)):
                        vals.append(float(v))
            n = len(vals)
            if n > 0:
                mean = sum(vals) / n
                if n >= 2:
                    mean_val = mean
                    ssd = sum((x - mean_val) ** 2 for x in vals)
                    std = math.sqrt(ssd / (n - 1))
                else:
                    std = float("nan")
                minv = min(vals)
                maxv = max(vals)
            else:
                mean = float("nan")
                std = float("nan")
                minv = float("nan")
                maxv = float("nan")
            row_out = {k: v for k, v in zip(group_by, gkey)}
            row_out.update(
                {
                    "variable": var,
                    "n": n,
                    "mean": mean,
                    "std": std,
                    "min": minv,
                    "max": maxv,
                }
            )
            results.append(row_out)
    results.sort(key=lambda d: tuple(d[k] for k in group_by) + (d["variable"],))
    return results


def _compute_non_missing_counts(
    rows: List[Dict[str, Any]], numeric_vars: List[str], missing_codes: List[Any]
) -> Dict[str, int]:
    counts: Dict[str, int] = {v: 0 for v in numeric_vars}
    for r in rows:
        for v in numeric_vars:
            vs = r.get(v, "")
            if not _to_missing(vs, missing_codes):
                val = _parse_float_maybe(vs)
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    counts[v] += 1
    return counts


def _compute_group_counts(rows: List[Dict[str, Any]], group_by: List[str]) -> List[Dict[str, Any]]:
    counts: Dict[Tuple, int] = {}
    for r in rows:
        key = _group_key(r, group_by)
        counts[key] = counts.get(key, 0) + 1
    out = []
    for key, n in counts.items():
        item = {k: v for k, v in zip(group_by, key)}
        item["n_rows"] = n
        out.append(item)
    out.sort(key=lambda d: tuple(d[k] for k in group_by))
    return out


def _pearson_correlation_pairwise(
    rows: List[Dict[str, Any]], var_i: str, var_j: str, missing_codes: List[Any]
) -> float:
    xs: List[float] = []
    ys: List[float] = []
    for r in rows:
        si = r.get(var_i, "")
        sj = r.get(var_j, "")
        if _to_missing(si, missing_codes) or _to_missing(sj, missing_codes):
            continue
        xi = _parse_float_maybe(si)
        yj = _parse_float_maybe(sj)
        if xi is None or yj is None:
            continue
        if isinstance(xi, float) and math.isnan(xi):
            continue
        if isinstance(yj, float) and math.isnan(yj):
            continue
        xs.append(float(xi))
        ys.append(float(yj))
    n = len(xs)
    if n < 2:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def _compute_correlation_matrix(
    rows: List[Dict[str, Any]], numeric_vars: List[str], missing_codes: List[Any]
) -> Dict[Tuple[str, str], float]:
    corr: Dict[Tuple[str, str], float] = {}
    for i, vi in enumerate(numeric_vars):
        for j, vj in enumerate(numeric_vars):
            if i == j:
                xs: List[float] = []
                for r in rows:
                    si = r.get(vi, "")
                    if _to_missing(si, missing_codes):
                        continue
                    xi = _parse_float_maybe(si)
                    if xi is None or (isinstance(xi, float) and math.isnan(xi)):
                        continue
                    xs.append(float(xi))
                if len(xs) < 2:
                    corr[(vi, vj)] = float("nan")
                else:
                    mean_x = sum(xs) / len(xs)
                    sxx = sum((x - mean_x) ** 2 for x in xs)
                    corr[(vi, vj)] = 1.0 if sxx > 0 else float("nan")
            else:
                corr[(vi, vj)] = _pearson_correlation_pairwise(rows, vi, vj, missing_codes)
    return corr


def _read_desc_by_group_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_correlation_csv(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            return {"header": rows[0], "rows": rows[1:]}
    except Exception:
        return None


def _compare_group_sort(rows: List[Dict[str, str]], group_by: List[str]) -> bool:
    keys = [tuple([r.get(k) for k in group_by] + [r.get("variable")]) for r in rows]
    return keys == sorted(keys)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "desc_by_group_exists": 0.0,
        "desc_by_group_columns_and_sort": 0.0,
        "desc_by_group_labels_correct": 0.0,
        "desc_by_group_values_accuracy": 0.0,
        "correlation_exists": 0.0,
        "correlation_shape_and_headers": 0.0,
        "correlation_values_accuracy": 0.0,
        "data_profile_exists": 0.0,
        "data_profile_structure": 0.0,
        "data_profile_values_accuracy": 0.0,
        "labels_used_exists": 0.0,
        "labels_used_values_accuracy": 0.0,
    }

    config_path = workspace / "config" / "summary_spec.yaml"
    cfg = _parse_config_yaml_specific(config_path)
    if not cfg:
        return scores

    labels_path = workspace / "config" / "variable_labels.py"
    var_labels = _load_var_labels_py(labels_path) or {}

    data_path = workspace / "input" / "plant_metrics.csv"
    data_rows = _read_csv_rows(data_path)
    if data_rows is None:
        return scores

    group_by: List[str] = [str(x) for x in cfg["group_by"]]
    numeric_vars: List[str] = [str(x) for x in cfg["numeric_vars"]]
    missing_codes: List[Any] = cfg["missing_value_codes"]
    outputs: Dict[str, Any] = cfg["outputs"]

    expected_desc = _compute_group_stats(data_rows, group_by, numeric_vars, missing_codes)
    labels_map = {v: var_labels.get(v, v) for v in numeric_vars}
    for row in expected_desc:
        row["variable_label"] = labels_map.get(row["variable"], row["variable"])
    expected_group_keyed: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for row in expected_desc:
        key = tuple(row.get(k) for k in group_by) + (row["variable"],)
        expected_group_keyed[key] = row

    expected_corr = _compute_correlation_matrix(data_rows, numeric_vars, missing_codes)
    expected_non_missing = _compute_non_missing_counts(data_rows, numeric_vars, missing_codes)
    expected_group_counts = _compute_group_counts(data_rows, group_by)

    # DESC BY GROUP CSV
    desc_out_path = outputs.get("desc_by_group_csv")
    if isinstance(desc_out_path, str):
        desc_path = workspace / desc_out_path
        if desc_path.exists():
            scores["desc_by_group_exists"] = 1.0
            desc_rows = _read_desc_by_group_csv(desc_path)
            if desc_rows is not None and len(desc_rows) > 0:
                fieldnames = list(desc_rows[0].keys())
                expected_columns = group_by + ["variable", "variable_label", "n", "mean", "std", "min", "max"]
                columns_ok = fieldnames == expected_columns
                sort_ok = _compare_group_sort(desc_rows, group_by)
                if columns_ok and sort_ok:
                    scores["desc_by_group_columns_and_sort"] = 1.0

                actual_group_keyed: Dict[Tuple[Any, ...], Dict[str, str]] = {}
                for r in desc_rows:
                    key = tuple(r.get(k) for k in group_by) + (r.get("variable"),)
                    actual_group_keyed[key] = r

                total_rows = len(expected_group_keyed)
                correct_labels = 0
                for key, exp in expected_group_keyed.items():
                    act = actual_group_keyed.get(key)
                    if act is None:
                        continue
                    exp_label = exp.get("variable_label")
                    act_label = act.get("variable_label")
                    if act_label == exp_label:
                        correct_labels += 1
                scores["desc_by_group_labels_correct"] = (correct_labels / total_rows) if total_rows > 0 else 0.0

                numeric_fields = ["n", "mean", "std", "min", "max"]
                total_checks = 0
                correct_checks = 0
                for key, exp in expected_group_keyed.items():
                    act = actual_group_keyed.get(key)
                    if act is None:
                        continue
                    for nf in numeric_fields:
                        total_checks += 1
                        if nf == "n":
                            try:
                                sval = (act.get("n") or "").strip()
                                if sval == "":
                                    act_n = None
                                else:
                                    act_n = int(float(sval))
                            except Exception:
                                act_n = None
                            exp_n = int(exp.get("n", 0))
                            if act_n == exp_n:
                                correct_checks += 1
                        else:
                            act_val = _parse_float_maybe(act.get(nf, ""))
                            exp_val = float(exp.get(nf))
                            if act_val is None:
                                act_val = float("nan")
                            if _is_close(act_val, exp_val, rel=1e-6, abs_tol=1e-6):
                                correct_checks += 1
                if total_checks > 0:
                    scores["desc_by_group_values_accuracy"] = correct_checks / total_checks

    # CORRELATION CSV
    corr_out_path = outputs.get("correlation_overall_csv")
    if isinstance(corr_out_path, str):
        corr_path = workspace / corr_out_path
        if corr_path.exists():
            scores["correlation_exists"] = 1.0
            parsed = _read_correlation_csv(corr_path)
            if parsed:
                header = parsed["header"]
                data_rows = parsed["rows"]
                shape_ok = False
                matrix_vals: List[List[Optional[float]]] = []
                # Accept two formats:
                # A) Index in first column: header[0] blank/any, header[1:] = numeric_vars; rows: first col row name, remaining values.
                # B) Pure matrix: header == numeric_vars; rows: only values, and we infer row order from first column missing, so reject; better require row count and headers numeric_vars and optional row labels absent (then we can't know row names). We'll accept if header == numeric_vars and number of rows == len(numeric_vars).
                # Try A:
                if len(header) == len(numeric_vars) + 1 and header[1:] == numeric_vars:
                    if len(data_rows) == len(numeric_vars):
                        ok = True
                        for row in data_rows:
                            if len(row) != len(numeric_vars) + 1:
                                ok = False
                                break
                        if ok:
                            shape_ok = True
                            for row in data_rows:
                                vals = [_parse_float_maybe(x) for x in row[1:]]
                                matrix_vals.append(vals)
                            row_names = [row[0] for row in data_rows]
                            if row_names != numeric_vars:
                                shape_ok = False
                                matrix_vals = []
                # Try B if A not ok
                if not shape_ok and header == numeric_vars and len(data_rows) == len(numeric_vars):
                    ok = True
                    for row in data_rows:
                        if len(row) != len(numeric_vars):
                            ok = False
                            break
                    if ok:
                        shape_ok = True
                        for row in data_rows:
                            vals = [_parse_float_maybe(x) for x in row]
                            matrix_vals.append(vals)

                if shape_ok:
                    scores["correlation_shape_and_headers"] = 1.0
                    total_cells = 0
                    correct_cells = 0
                    for i, ri in enumerate(numeric_vars):
                        for j, cj in enumerate(numeric_vars):
                            total_cells += 1
                            act_val = matrix_vals[i][j]
                            if act_val is None:
                                act_val = float("nan")
                            exp_val = expected_corr.get((ri, cj), float("nan"))
                            if _is_close(act_val, exp_val, rel=1e-5, abs_tol=1e-5):
                                correct_cells += 1
                    if total_cells > 0:
                        scores["correlation_values_accuracy"] = correct_cells / total_cells

    # DATA PROFILE JSON
    profile_out_path = outputs.get("data_profile_json")
    if isinstance(profile_out_path, str):
        profile_path = workspace / profile_out_path
        if profile_path.exists():
            scores["data_profile_exists"] = 1.0
            try:
                profile_obj = json.loads(profile_path.read_text(encoding="utf-8"))
            except Exception:
                profile_obj = None
            if isinstance(profile_obj, dict):
                required_keys = [
                    "rows_read",
                    "non_missing_counts",
                    "group_counts",
                    "numeric_vars",
                    "missing_value_codes",
                ]
                if all(k in profile_obj for k in required_keys):
                    scores["data_profile_structure"] = 1.0
                sub_total = 0
                sub_correct = 0
                sub_total += 1
                exp_rows_read = len(data_rows)
                if isinstance(profile_obj.get("rows_read"), int) and profile_obj.get("rows_read") == exp_rows_read:
                    sub_correct += 1
                sub_total += 1
                nmc = profile_obj.get("non_missing_counts")
                if isinstance(nmc, dict):
                    try:
                        nmc_int = {str(k): int(v) for k, v in nmc.items()}
                        if all(k in nmc_int for k in numeric_vars) and all(
                            nmc_int.get(k) == expected_non_missing.get(k) for k in numeric_vars
                        ):
                            sub_correct += 1
                    except Exception:
                        pass
                sub_total += 1
                gc = profile_obj.get("group_counts")
                if isinstance(gc, list):
                    try:
                        def norm_list(lst):
                            return sorted(
                                [{**{k: v for k, v in d.items() if k in group_by}, "n_rows": int(d.get("n_rows", 0))} for d in lst],
                                key=lambda x: tuple(x[k] for k in group_by),
                            )
                        if norm_list(gc) == norm_list(expected_group_counts):
                            sub_correct += 1
                    except Exception:
                        pass
                sub_total += 1
                nv = profile_obj.get("numeric_vars")
                if isinstance(nv, list) and [str(x) for x in nv] == numeric_vars:
                    sub_correct += 1
                sub_total += 1
                mvc = profile_obj.get("missing_value_codes")
                if isinstance(mvc, list):
                    def norm_codes(lst):
                        out = []
                        for x in lst:
                            if x == "":
                                out.append("")
                            else:
                                try:
                                    out.append(int(x))
                                except Exception:
                                    out.append(x)
                        return out
                    if norm_codes(mvc) == norm_codes(missing_codes):
                        sub_correct += 1
                if sub_total > 0:
                    scores["data_profile_values_accuracy"] = sub_correct / sub_total

    # LABELS USED JSON
    labels_out_path = outputs.get("labels_used_json")
    if isinstance(labels_out_path, str):
        labels_used_path = workspace / labels_out_path
        if labels_used_path.exists():
            scores["labels_used_exists"] = 1.0
            try:
                labels_used_obj = json.loads(labels_used_path.read_text(encoding="utf-8"))
            except Exception:
                labels_used_obj = None
            if isinstance(labels_used_obj, dict):
                expected_labels_used = {v: var_labels.get(v, v) for v in numeric_vars}
                # must match exactly for numeric_vars keys
                ok = True
                for k, exp_val in expected_labels_used.items():
                    if k not in labels_used_obj or str(labels_used_obj.get(k)) != exp_val:
                        ok = False
                        break
                if ok:
                    scores["labels_used_values_accuracy"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()