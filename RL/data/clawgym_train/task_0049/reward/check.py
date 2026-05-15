import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from statistics import median


def _strip_yaml_comment(line: str) -> str:
    s = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            s.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            s.append(ch)
        elif ch == '#' and not in_single and not in_double:
            break
        else:
            s.append(ch)
        i += 1
    return "".join(s).rstrip()


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    result: Dict[str, Any] = {}
    current_map_key: Optional[str] = None
    current_map_indent: Optional[int] = None
    for raw_line in lines:
        line = _strip_yaml_comment(raw_line).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        line = line.lstrip(" ")
        if line.endswith(":"):
            key = line[:-1].strip()
            if not key:
                return None
            result[key] = {}
            current_map_key = key
            current_map_indent = indent
            continue
        if ":" not in line:
            return None
        key_part, value_part = line.split(":", 1)
        key = key_part.strip()
        value_raw = value_part.strip()
        if value_raw.startswith('"') and value_raw.endswith('"'):
            value = value_raw[1:-1]
        elif value_raw.startswith("'") and value_raw.endswith("'"):
            value = value_raw[1:-1]
        else:
            value = value_raw
        coerced: Any
        try:
            coerced = int(value)
        except Exception:
            coerced = value
        if current_map_key is not None and current_map_indent is not None and indent > current_map_indent:
            if not isinstance(result.get(current_map_key), dict):
                result[current_map_key] = {}
            result[current_map_key][key] = coerced  # type: ignore[index]
        else:
            current_map_key = None
            current_map_indent = None
            result[key] = coerced
    return result


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, bool):
            return None
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            if s.is_integer():
                return int(s)
            return None
        return int(str(s).strip())
    except Exception:
        return None


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_html_file_valid": 0.0,
        "chapters_csv_exists_and_columns": 0.0,
        "chapters_numbering_strict_increasing_from_1": 0.0,
        "stats_json_structure": 0.0,
        "stats_aggregates_match_chapters": 0.0,
        "num_chapters_within_bounds": 0.0,
        "topk_csv_correctness": 0.0,
        "long_chapters_csv_correctness": 0.0,
        "validation_results_json_exists_and_parseable": 0.0,
        "scripts_present_with_shebang": 0.0,
    }

    config_path = workspace / "input" / "config.yaml"
    config = _parse_simple_yaml(config_path)
    if not config or not isinstance(config, dict):
        return scores

    outputs = config.get("outputs")
    if not isinstance(outputs, dict):
        return scores

    raw_html_path = workspace / str(outputs.get("raw_html", "workspace/raw/1342.html"))
    chapters_csv_path = workspace / str(outputs.get("chapters_csv", "workspace/chapters.csv"))
    topk_csv_path = workspace / str(outputs.get("topk_csv", "workspace/top5_chapters.csv"))
    long_chapters_csv_path = workspace / str(outputs.get("long_chapters_csv", "workspace/long_chapters.csv"))
    stats_json_path = workspace / str(outputs.get("stats_json", "workspace/stats.json"))
    validation_json_path = workspace / str(outputs.get("validation_json", "workspace/validation_results.json"))

    html_text = _safe_read_text(raw_html_path)
    if html_text is not None and len(html_text) > 0:
        markers_ok = ("Project Gutenberg" in html_text) and ("Pride and Prejudice" in html_text or "PRIDE AND PREJUDICE" in html_text)
        if markers_ok:
            scores["raw_html_file_valid"] = 1.0

    chapters_rows_raw = _safe_read_csv_dicts(chapters_csv_path)
    chapters_ok = False
    chapters_typed: List[Dict[str, Any]] = []
    if chapters_rows_raw is not None and len(chapters_rows_raw) > 0:
        fieldnames = set(chapters_rows_raw[0].keys())
        required_cols = {"chapter_number", "chapter_title", "word_count"}
        if required_cols.issubset(fieldnames):
            parse_error = False
            for row in chapters_rows_raw:
                cn = _parse_int(row.get("chapter_number"))
                wc = _parse_int(row.get("word_count"))
                title = row.get("chapter_title")
                if cn is None or wc is None or title is None:
                    parse_error = True
                    break
                chapters_typed.append(
                    {"chapter_number": cn, "chapter_title": str(title), "word_count": wc}
                )
            if not parse_error:
                chapters_ok = True
                scores["chapters_csv_exists_and_columns"] = 1.0

    if chapters_ok:
        nums = [r["chapter_number"] for r in chapters_typed]
        strictly_increasing = True
        if len(nums) == 0:
            strictly_increasing = False
        else:
            for i, n in enumerate(nums, start=1):
                if n != i:
                    strictly_increasing = False
                    break
        if strictly_increasing:
            scores["chapters_numbering_strict_increasing_from_1"] = 1.0

    stats_data = _safe_load_json(stats_json_path)
    stats_structure_ok = False
    if isinstance(stats_data, dict):
        required_stats_keys = ["num_chapters", "total_words", "mean_words", "median_words", "min_words", "max_words"]
        if all(k in stats_data for k in required_stats_keys):
            nc = stats_data.get("num_chapters")
            tw = stats_data.get("total_words")
            mw = stats_data.get("mean_words")
            medw = stats_data.get("median_words")
            minw = stats_data.get("min_words")
            maxw = stats_data.get("max_words")
            nc_i = _parse_int(nc)
            tw_i = _parse_int(tw)
            minw_i = _parse_int(minw)
            maxw_i = _parse_int(maxw)
            try:
                mw_f = float(mw)
                medw_f = float(medw)
                basic_types_ok = all(v is not None for v in [nc_i, tw_i, minw_i, maxw_i])
            except Exception:
                basic_types_ok = False
                mw_f = 0.0
                medw_f = 0.0
            if basic_types_ok:
                stats_structure_ok = True
                scores["stats_json_structure"] = 1.0
                if chapters_ok:
                    wc_list = [r["word_count"] for r in chapters_typed]
                    n = len(wc_list)
                    if n > 0:
                        total = sum(wc_list)
                        min_calc = min(wc_list)
                        max_calc = max(wc_list)
                        mean_calc = total / n
                        median_calc = float(median(wc_list))
                        if (
                            nc_i == n
                            and tw_i == total
                            and minw_i == min_calc
                            and maxw_i == max_calc
                            and _float_eq(mw_f, mean_calc)
                            and _float_eq(medw_f, median_calc)
                        ):
                            scores["stats_aggregates_match_chapters"] = 1.0

    if stats_structure_ok and isinstance(config.get("expected_min_chapters"), int) and isinstance(config.get("expected_max_chapters"), int):
        min_ch = int(config["expected_min_chapters"])
        max_ch = int(config["expected_max_chapters"])
        nc_val = _parse_int(stats_data.get("num_chapters")) if isinstance(stats_data, dict) else None
        if nc_val is not None and min_ch <= nc_val <= max_ch:
            scores["num_chapters_within_bounds"] = 1.0

    topk_rows_raw = _safe_read_csv_dicts(topk_csv_path)
    if topk_rows_raw is not None and chapters_ok and isinstance(config.get("top_k"), int):
        fieldnames = set(topk_rows_raw[0].keys()) if topk_rows_raw else set()
        required_cols_topk = {"chapter_number", "chapter_title", "word_count", "rank"}
        if required_cols_topk.issubset(fieldnames):
            k = int(config["top_k"])
            if k >= 0 and len(topk_rows_raw) == k:
                parse_error = False
                topk_typed: List[Dict[str, Any]] = []
                for row in topk_rows_raw:
                    cn = _parse_int(row.get("chapter_number"))
                    wc = _parse_int(row.get("word_count"))
                    rk = _parse_int(row.get("rank"))
                    title = row.get("chapter_title")
                    if cn is None or wc is None or rk is None or title is None:
                        parse_error = True
                        break
                    topk_typed.append({"chapter_number": cn, "chapter_title": str(title), "word_count": wc, "rank": rk})
                if not parse_error:
                    ranks = [r["rank"] for r in topk_typed]
                    expected_ranks = list(range(1, k + 1))
                    ranks_ok = ranks == expected_ranks
                    wc_seq = [r["word_count"] for r in topk_typed]
                    sorted_desc_ok = all(wc_seq[i] >= wc_seq[i + 1] for i in range(len(wc_seq) - 1))
                    cn_seq = [r["chapter_number"] for r in topk_typed]
                    unique_cn = len(set(cn_seq)) == len(cn_seq)
                    chapters_by_cn = {r["chapter_number"]: r for r in chapters_typed}
                    mapping_ok = all(
                        (cn in chapters_by_cn) and (chapters_by_cn[cn]["word_count"] == wc)
                        for cn, wc in zip(cn_seq, wc_seq)
                    )
                    if wc_seq:
                        min_included = min(wc_seq)
                        topk_cn_set = set(cn_seq)
                        no_excluded_higher = True
                        for r in chapters_typed:
                            if r["word_count"] > min_included and r["chapter_number"] not in topk_cn_set:
                                no_excluded_higher = False
                                break
                    else:
                        no_excluded_higher = True
                    if ranks_ok and sorted_desc_ok and unique_cn and mapping_ok and no_excluded_higher:
                        scores["topk_csv_correctness"] = 1.0

    long_rows_raw = _safe_read_csv_dicts(long_chapters_csv_path)
    if long_rows_raw is not None and chapters_ok and isinstance(config.get("min_words_for_inclusion"), int):
        fieldnames = set(long_rows_raw[0].keys()) if long_rows_raw else set()
        required_cols_long = {"chapter_number", "chapter_title", "word_count"}
        if required_cols_long.issubset(fieldnames):
            parse_error = False
            long_typed: List[Dict[str, Any]] = []
            for row in long_rows_raw:
                cn = _parse_int(row.get("chapter_number"))
                wc = _parse_int(row.get("word_count"))
                title = row.get("chapter_title")
                if cn is None or wc is None or title is None:
                    parse_error = True
                    break
                long_typed.append({"chapter_number": cn, "chapter_title": str(title), "word_count": wc})
            if not parse_error:
                sorted_ok = all(long_typed[i]["chapter_number"] <= long_typed[i + 1]["chapter_number"] for i in range(len(long_typed) - 1))
                cn_seq = [r["chapter_number"] for r in long_typed]
                unique_cn = len(set(cn_seq)) == len(cn_seq)
                chapters_by_cn = {r["chapter_number"]: r for r in chapters_typed}
                mapping_ok = all(
                    (r["chapter_number"] in chapters_by_cn) and (chapters_by_cn[r["chapter_number"]]["word_count"] == r["word_count"])
                    for r in long_typed
                )
                threshold = int(config["min_words_for_inclusion"])
                expected_subset = [r for r in chapters_typed if r["word_count"] >= threshold]
                expected_cns_sorted = sorted([r["chapter_number"] for r in expected_subset])
                actual_cns_sorted = sorted([r["chapter_number"] for r in long_typed])
                subset_equal = expected_cns_sorted == actual_cns_sorted
                threshold_ok = all(r["word_count"] >= threshold for r in long_typed)
                if sorted_ok and unique_cn and mapping_ok and subset_equal and threshold_ok:
                    scores["long_chapters_csv_correctness"] = 1.0

    validation_obj = _safe_load_json(validation_json_path)
    if validation_obj is not None:
        scores["validation_results_json_exists_and_parseable"] = 1.0

    run_sh_path = workspace / "scripts" / "run.sh"
    validate_sh_path = workspace / "scripts" / "validate.sh"
    scripts_ok = True
    for p in (run_sh_path, validate_sh_path):
        try:
            if not p.is_file():
                scripts_ok = False
                break
            first_line = p.open("r", encoding="utf-8", errors="ignore").readline()
            if not first_line.startswith("#!"):
                scripts_ok = False
                break
        except Exception:
            scripts_ok = False
            break
    if scripts_ok:
        scores["scripts_present_with_shebang"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()