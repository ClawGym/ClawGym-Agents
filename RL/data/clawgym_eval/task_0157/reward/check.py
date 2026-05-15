import json
import csv
import sys
import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _minimal_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for simple key: value and nested mappings by indentation.
    Supports:
      - Scalars: integers, floats, booleans (true/false), and strings
      - Nested dicts indicated by lines ending with ':' and increased indentation
    Does not support lists or complex YAML features.
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]

    def parse_scalar(val: str) -> Any:
        v = val.strip()
        low = v.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        try:
            if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                return int(v)
        except Exception:
            pass
        try:
            return float(v)
        except Exception:
            pass
        if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
            return v[1:-1]
        return v

    for raw in lines:
        if not raw.strip():
            continue
        if raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if line.endswith(":"):
            key = line[:-1].strip()
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent + 1, new_dict))
        else:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = parse_scalar(val)
            current[key] = val
    return root


def _safe_import_constants(py_path: Path) -> Dict[str, Any]:
    result = {}
    if not py_path.exists():
        return result
    try:
        spec = importlib.util.spec_from_file_location("analysis_notes", str(py_path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore
            for name in ["UNITS", "ROUNDING_DECIMALS", "DISCLAIMER", "THREAD_TONE"]:
                if hasattr(module, name):
                    result[name] = getattr(module, name)
    except Exception:
        return {}
    return result


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_float(value: Union[str, float, int]) -> Optional[float]:
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        v = value.strip().replace(",", "")
        try:
            return float(v)
        except Exception:
            return None
    return None


def _median(values: List[float]) -> float:
    if not values:
        return float("nan")
    arr = sorted(values)
    n = len(arr)
    mid = n // 2
    if n % 2 == 1:
        return arr[mid]
    else:
        return (arr[mid - 1] + arr[mid]) / 2.0


def _round_value(val: float, decimals: int) -> float:
    return round(val, decimals)


def _format_number(val: float, decimals: int) -> str:
    fmt = f"{{:.{decimals}f}}"
    try:
        return fmt.format(val)
    except Exception:
        return str(round(val, decimals))


def _compute_group_stats(rows: List[Dict[str, str]], pre_col: str, post_col: str, group_col: str, action_level: float) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float], int]:
    groups: Dict[str, List[Tuple[float, float]]] = {}
    total_pairs: List[Tuple[float, float]] = []
    for r in rows:
        if pre_col not in r or post_col not in r or group_col not in r:
            continue
        pre = _parse_float(r[pre_col])
        post = _parse_float(r[post_col])
        grp = r[group_col]
        if pre is None or post is None:
            continue
        total_pairs.append((pre, post))
        groups.setdefault(grp, []).append((pre, post))

    def metrics_for_pairs(pairs: List[Tuple[float, float]]) -> Dict[str, float]:
        pre_list = [p for p, _ in pairs]
        post_list = [q for _, q in pairs]
        n = len(pairs)
        mean_pre = sum(pre_list) / n if n > 0 else float("nan")
        mean_post = sum(post_list) / n if n > 0 else float("nan")
        median_pre = _median(pre_list) if n > 0 else float("nan")
        median_post = _median(post_list) if n > 0 else float("nan")
        mean_reduction = mean_pre - mean_post if n > 0 else float("nan")
        percent_reduction_mean = (100.0 * mean_reduction / mean_pre) if n > 0 and mean_pre != 0 else (0.0 if n > 0 else float("nan"))
        pre_above_n = sum(1 for v in pre_list if v > action_level)
        post_above_n = sum(1 for v in post_list if v > action_level)
        pre_above_pct = (100.0 * pre_above_n / n) if n > 0 else float("nan")
        post_above_pct = (100.0 * post_above_n / n) if n > 0 else float("nan")
        return {
            "n_samples": float(n),
            "mean_pre": mean_pre,
            "median_pre": median_pre,
            "mean_post": mean_post,
            "median_post": median_post,
            "mean_reduction": mean_reduction,
            "percent_reduction_mean": percent_reduction_mean,
            "pre_above_action_n": float(pre_above_n),
            "pre_above_action_pct": pre_above_pct,
            "post_above_action_n": float(post_above_n),
            "post_above_action_pct": post_above_pct,
        }

    group_stats: Dict[str, Dict[str, float]] = {g: metrics_for_pairs(pairs) for g, pairs in groups.items()}
    overall_stats = metrics_for_pairs(total_pairs)
    total_n = len(total_pairs)
    return group_stats, overall_stats, total_n


def _apply_rounding_to_stats(stats: Dict[str, float], decimals: int) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in stats.items():
        if k.endswith("_n") or k == "n_samples":
            out[k] = float(int(round(v)))
        else:
            out[k] = _round_value(v, decimals)
    return out


def _split_posts(text: str) -> List[str]:
    t = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    parts = re.split(r"\n\s*\n", t)
    parts = [p.strip() for p in parts if p.strip() != ""]
    return parts


def _numeric_token_present(text: str, value: float, decimals: int, require_percent: bool = False, allow_percent: bool = True) -> bool:
    token = _format_number(value, decimals)
    t = text
    if not require_percent:
        if token in t:
            return True
        if allow_percent:
            if f"{token}%" in t or f"{token} %" in t:
                return True
            if f"{token} percent" in t.lower():
                return True
    else:
        if f"{token}%" in t or f"{token} %" in t:
            return True
        if f"{token} percent" in t.lower():
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_csv_structure": 0.0,
        "summary_csv_group_values": 0.0,
        "overall_json_structure": 0.0,
        "overall_json_values": 0.0,
        "csv_headers_without_units": 0.0,
        "thread_structure": 0.0,
        "thread_post1_overall": 0.0,
        "thread_posts_by_group_content": 0.0,
        "thread_post5_disclaimer": 0.0,
        "thread_units_usage": 0.0,
    }

    input_csv_path = workspace / "input" / "lead_samples.csv"
    config_yaml_path = workspace / "config" / "remediation_config.yaml"
    notes_py_path = workspace / "scripts" / "analysis_notes.py"
    out_summary_csv = workspace / "output" / "summary" / "lead_remedy_summary.csv"
    out_overall_json = workspace / "output" / "summary" / "overall.json"
    out_thread_txt = workspace / "output" / "thread" / "thread.txt"

    config = _minimal_yaml_load(config_yaml_path)
    constants = _safe_import_constants(notes_py_path)

    if not (config and isinstance(config, dict)):
        return scores
    columns = config.get("columns") if isinstance(config.get("columns"), dict) else None
    if not columns:
        return scores
    pre_col = columns.get("pre")
    post_col = columns.get("post")
    group_col = columns.get("group_by")
    try:
        action_level = float(config.get("action_level_ppb"))
    except Exception:
        return scores
    if not (isinstance(pre_col, str) and isinstance(post_col, str) and isinstance(group_col, str)):
        return scores

    if "UNITS" not in constants or "ROUNDING_DECIMALS" not in constants or "DISCLAIMER" not in constants:
        return scores

    units = constants["UNITS"]
    try:
        decimals = int(constants["ROUNDING_DECIMALS"])
    except Exception:
        return scores
    disclaimer_text = str(constants["DISCLAIMER"])

    in_rows = _load_csv_dicts(input_csv_path)
    if in_rows is None:
        return scores

    group_stats_raw, overall_stats_raw, total_n = _compute_group_stats(in_rows, pre_col, post_col, group_col, action_level)
    if total_n == 0 or not group_stats_raw:
        return scores

    group_stats_rounded: Dict[str, Dict[str, float]] = {}
    for g, metrics in group_stats_raw.items():
        group_stats_rounded[g] = _apply_rounding_to_stats(metrics, decimals)
    overall_stats_rounded = _apply_rounding_to_stats(overall_stats_raw, decimals)

    expected_headers = [
        group_col,
        "n_samples",
        "mean_pre",
        "median_pre",
        "mean_post",
        "median_post",
        "mean_reduction",
        "percent_reduction_mean",
        "pre_above_action_n",
        "pre_above_action_pct",
        "post_above_action_n",
        "post_above_action_pct",
    ]
    if out_summary_csv.exists():
        try:
            with out_summary_csv.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = list(reader.fieldnames) if reader.fieldnames else []
                rows = [dict(row) for row in reader]
        except Exception:
            headers = []
            rows = []
        header_ok = headers == expected_headers
        headers_without_units_ok = header_ok and all(units not in h for h in headers)
        row_groups: Dict[str, Dict[str, str]] = {}
        for row in rows:
            gname = row.get(group_col, "")
            if gname:
                row_groups[gname] = row

        all_groups_present = set(row_groups.keys()) == set(group_stats_rounded.keys())
        values_match = False
        if all_groups_present and header_ok:
            values_match = True
            tol = 10 ** (-(decimals + 2))
            for gname, expected in group_stats_rounded.items():
                r = row_groups.get(gname, {})
                if r.get(group_col) != gname:
                    values_match = False
                    break
                n_val = r.get("n_samples")
                n_parsed = _parse_float(n_val) if n_val is not None else None
                if n_parsed is None or int(round(n_parsed)) != int(round(expected["n_samples"])):
                    values_match = False
                    break
                for key in [
                    "mean_pre",
                    "median_pre",
                    "mean_post",
                    "median_post",
                    "mean_reduction",
                    "percent_reduction_mean",
                    "pre_above_action_n",
                    "pre_above_action_pct",
                    "post_above_action_n",
                    "post_above_action_pct",
                ]:
                    sval = r.get(key)
                    fval = _parse_float(sval) if sval is not None else None
                    if fval is None:
                        values_match = False
                        break
                    ev = expected[key]
                    if key.endswith("_n"):
                        if int(round(fval)) != int(round(ev)):
                            values_match = False
                            break
                    else:
                        if not (abs(fval - ev) <= tol):
                            values_match = False
                            break
                if not values_match:
                    break
        scores["summary_csv_structure"] = 1.0 if header_ok and all_groups_present else 0.0
        scores["csv_headers_without_units"] = 1.0 if headers_without_units_ok else 0.0
        scores["summary_csv_group_values"] = 1.0 if values_match else 0.0

    if out_overall_json.exists():
        try:
            with out_overall_json.open("r", encoding="utf-8") as f:
                overall_json = json.load(f)
        except Exception:
            overall_json = None
        if isinstance(overall_json, dict):
            required_keys = [
                "action_level_ppb",
                "units",
                "n_samples",
                "overall_mean_pre",
                "overall_mean_post",
                "overall_mean_reduction",
                "overall_mean_reduction_pct",
                "overall_pre_above_action_n",
                "overall_pre_above_action_pct",
                "overall_post_above_action_n",
                "overall_post_above_action_pct",
            ]
            structure_ok = all(k in overall_json for k in required_keys)
            scores["overall_json_structure"] = 1.0 if structure_ok else 0.0
            if structure_ok:
                try:
                    tol = 10 ** (-(decimals + 2))
                    values_ok = True
                    if _parse_float(overall_json.get("action_level_ppb")) != float(action_level):
                        values_ok = False
                    if str(overall_json.get("units")) != str(units):
                        values_ok = False
                    if int(overall_json.get("n_samples")) != int(total_n):
                        values_ok = False
                    mapping = {
                        "overall_mean_pre": overall_stats_rounded["mean_pre"],
                        "overall_mean_post": overall_stats_rounded["mean_post"],
                        "overall_mean_reduction": overall_stats_rounded["mean_reduction"],
                        "overall_mean_reduction_pct": overall_stats_rounded["percent_reduction_mean"],
                        "overall_pre_above_action_n": overall_stats_rounded["pre_above_action_n"],
                        "overall_pre_above_action_pct": overall_stats_rounded["pre_above_action_pct"],
                        "overall_post_above_action_n": overall_stats_rounded["post_above_action_n"],
                        "overall_post_above_action_pct": overall_stats_rounded["post_above_action_pct"],
                    }
                    for k, ev in mapping.items():
                        v = overall_json.get(k)
                        if v is None:
                            values_ok = False
                            break
                        if k.endswith("_n"):
                            fv = _parse_float(v)
                            if fv is None or int(round(fv)) != int(round(ev)):
                                values_ok = False
                                break
                        else:
                            fv = _parse_float(v)
                            if fv is None or not (abs(fv - ev) <= tol):
                                values_ok = False
                                break
                    scores["overall_json_values"] = 1.0 if values_ok else 0.0
                except Exception:
                    scores["overall_json_values"] = 0.0
            else:
                scores["overall_json_values"] = 0.0

    if out_thread_txt.exists():
        text = _read_text(out_thread_txt)
        posts = _split_posts(text) if text is not None else []
        structure_ok = len(posts) == 5
        scores["thread_structure"] = 1.0 if structure_ok else 0.0
        if structure_ok:
            post1 = posts[0]
            post1_ok = True
            if str(units) not in post1:
                post1_ok = False
            action_level_str_plain = str(int(action_level)) if action_level == int(action_level) else _format_number(action_level, decimals)
            if action_level_str_plain not in post1 and _format_number(action_level, decimals) not in post1:
                post1_ok = False
            overall_mean_reduction_val = overall_stats_rounded["mean_reduction"]
            if not _numeric_token_present(post1, overall_mean_reduction_val, decimals, require_percent=False, allow_percent=False):
                post1_ok = False
            pre_pct = overall_stats_rounded["pre_above_action_pct"]
            post_pct = overall_stats_rounded["post_above_action_pct"]
            drop_pct = _round_value(pre_pct - post_pct, decimals)
            has_drop = _numeric_token_present(post1, drop_pct, decimals, require_percent=False, allow_percent=True)
            has_both = _numeric_token_present(post1, pre_pct, decimals, require_percent=False, allow_percent=True) and _numeric_token_present(post1, post_pct, decimals, require_percent=False, allow_percent=True)
            if not (has_drop or has_both):
                post1_ok = False
            scores["thread_post1_overall"] = 1.0 if post1_ok else 0.0

            remedies_sorted = sorted(group_stats_rounded.keys(), key=lambda x: str(x))
            posts2_4_ok = True
            for idx, remedy in enumerate(remedies_sorted):
                post = posts[1 + idx]
                if remedy not in post:
                    posts2_4_ok = False
                    break
                stats = group_stats_rounded[remedy]
                for key in ["mean_pre", "mean_post", "mean_reduction"]:
                    if not _numeric_token_present(post, stats[key], decimals, require_percent=False, allow_percent=False):
                        posts2_4_ok = False
                        break
                if not posts2_4_ok:
                    break
                grp_pre_pct = stats["pre_above_action_pct"]
                grp_post_pct = stats["post_above_action_pct"]
                grp_drop = _round_value(grp_pre_pct - grp_post_pct, decimals)
                has_drop = _numeric_token_present(post, grp_drop, decimals, require_percent=False, allow_percent=True)
                has_both = _numeric_token_present(post, grp_pre_pct, decimals, require_percent=False, allow_percent=True) and _numeric_token_present(post, grp_post_pct, decimals, require_percent=False, allow_percent=True)
                if not (has_drop or has_both):
                    posts2_4_ok = False
                    break
            remedies_in_posts = []
            for i in range(1, 4):
                found = None
                for remedy in remedies_sorted:
                    if remedy in posts[i]:
                        found = remedy
                        break
                remedies_in_posts.append(found)
            order_ok = remedies_in_posts == remedies_sorted
            posts2_4_ok = posts2_4_ok and order_ok
            scores["thread_posts_by_group_content"] = 1.0 if posts2_4_ok else 0.0

            post5 = posts[4]
            disclaimer_ok = disclaimer_text in post5
            scores["thread_post5_disclaimer"] = 1.0 if disclaimer_ok else 0.0

            any_units_in_thread = any(str(units) in p for p in posts)
            scores["thread_units_usage"] = 1.0 if any_units_in_thread else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()