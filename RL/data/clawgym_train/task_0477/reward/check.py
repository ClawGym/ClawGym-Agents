import json
import csv
import math
import statistics
import sys
import ast
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _simple_yaml_load(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Remove inline comments
            if "#" in line:
                line = line.split("#", 1)[0].rstrip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove quotes if present
            if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                val = val[1:-1]
            # Parse booleans, ints, floats
            lower = val.lower()
            if lower in ("true", "yes", "on"):
                parsed: Any = True
            elif lower in ("false", "no", "off"):
                parsed = False
            else:
                try:
                    if "." in val or "e" in lower:
                        parsed = float(val)
                        # if integer float like "2.0", keep as float
                    else:
                        parsed = int(val)
                except Exception:
                    parsed = val
            data[key] = parsed
        return data
    except Exception:
        return None


def _parse_expected_columns(py_path: Path) -> Optional[List[str]]:
    src = _read_text(py_path)
    if src is None:
        return None
    try:
        module = ast.parse(src, filename=str(py_path))
        for node in module.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "EXPECTED_COLUMNS":
                        if isinstance(node.value, ast.List):
                            cols: List[str] = []
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Str):  # Py<3.8
                                    cols.append(elt.s)
                                elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    cols.append(elt.value)
                                else:
                                    return None
                            return cols
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "EXPECTED_COLUMNS" and isinstance(node.value, ast.List):
                    cols2: List[str] = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Str):
                            cols2.append(elt.s)
                        elif isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            cols2.append(elt.value)
                        else:
                            return None
                    return cols2
        return None
    except Exception:
        return None


def _discover_data_csvs(workspace: Path) -> List[Path]:
    data_dir = workspace / "data"
    if not data_dir.exists() or not data_dir.is_dir():
        return []
    csvs = sorted([p for p in data_dir.glob("*.csv") if p.is_file()])
    return csvs


def _almost_equal(a: float, b: float, rel_tol: float = 1e-9, abs_tol: float = 1e-9) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except Exception:
        return False


def _compute_metrics_for_csv(csv_path: Path, expected_columns: Optional[List[str]], threshold: float) -> Optional[Dict[str, Any]]:
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return None
            if header is None:
                return None
            header_list = [h.strip() for h in header]
            data_valid = True
            if expected_columns is not None:
                data_valid = (header_list == expected_columns)
            # Prepare DictReader with the read header
            f.seek(0)
            dict_reader = csv.DictReader(f)
            rows = list(dict_reader)
            if len(rows) == 0:
                # Empty data not allowed for meaningful metrics
                return None
            durations: List[float] = []
            asl_list: List[float] = []
            total_jump_scares = 0
            intense_duration = 0.0
            film_title = rows[0].get("film_title", "").strip() if "film_title" in rows[0] else ""
            for row in rows:
                # Basic field extraction with validation
                try:
                    st = float(row["start_time_s"])
                    en = float(row["end_time_s"])
                    dur = en - st
                    if dur < 0:
                        return None
                    durations.append(dur)
                    js = int(row["jump_scare"])
                    total_jump_scares += js
                    loud = float(row["avg_loudness_db"])
                    sc = int(row["shot_count"])
                    if sc <= 0:
                        return None
                    asl = dur / sc
                    asl_list.append(asl)
                    if loud >= threshold:
                        intense_duration += dur
                except Exception:
                    return None
            total_duration_s = sum(durations)
            if total_duration_s <= 0:
                return None
            scenes_analyzed = len(rows)
            jumps_per_min = float(total_jump_scares) / (total_duration_s / 60.0)
            mean_scene_duration_s = total_duration_s / scenes_analyzed
            median_shot_length_s = statistics.median(asl_list)
            intense_prop = intense_duration / total_duration_s
            return {
                "film_title": film_title,
                "total_duration_s": total_duration_s,
                "total_jump_scares": total_jump_scares,
                "jumps_per_min": jumps_per_min,
                "mean_scene_duration_s": mean_scene_duration_s,
                "median_shot_length_s": median_shot_length_s,
                "intense_loudness_proportion": intense_prop,
                "scenes_analyzed": scenes_analyzed,
                "data_valid": data_valid,
            }
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    # Load config
    cfg_path = workspace / "config" / "analysis.yaml"
    cfg = _simple_yaml_load(cfg_path)
    if cfg is None or "loudness_threshold_db" not in cfg:
        return None, None
    threshold = float(cfg["loudness_threshold_db"])
    # Load expected columns from feature_spec
    spec_path = workspace / "scripts" / "feature_spec.py"
    expected_columns = _parse_expected_columns(spec_path)
    # Discover data CSVs
    csvs = _discover_data_csvs(workspace)
    if not csvs:
        return None, None
    films_metrics: List[Dict[str, Any]] = []
    for csv_path in csvs:
        m = _compute_metrics_for_csv(csv_path, expected_columns, threshold)
        if m is None:
            return None, None
        films_metrics.append(m)
    # Build expected structures
    expected_json = {
        "films": films_metrics,
        "config_used": threshold,
    }
    return expected_json, films_metrics


def _load_pacing_summary(path: Path) -> Optional[Dict[str, Any]]:
    obj = _load_json(path)
    if obj is None or not isinstance(obj, dict):
        return None
    return obj


def _load_film_comparison_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return (reader.fieldnames, rows)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pacing_summary_json_present": 0.0,
        "pacing_summary_structure_and_films_match": 0.0,
        "pacing_summary_config_used_correct": 0.0,
        "pacing_summary_metrics_match_expected": 0.0,
        "pacing_summary_scenes_and_validation_correct": 0.0,
        "film_comparison_csv_present": 0.0,
        "film_comparison_columns_correct": 0.0,
        "film_comparison_rows_match_films": 0.0,
        "film_comparison_values_and_ranking_correct": 0.0,
        "cross_file_consistency_between_outputs": 0.0,
    }

    # Compute expected from inputs
    expected_json, expected_films_metrics = _compute_expected(workspace)
    if expected_json is None or expected_films_metrics is None:
        # If we can't compute expected, all dependent checks must remain 0.0
        return scores

    # Build expected film mapping
    expected_by_title: Dict[str, Dict[str, Any]] = {fm["film_title"]: fm for fm in expected_films_metrics}
    expected_titles = set(expected_by_title.keys())

    # Load pacing_summary.json
    pacing_path = workspace / "outputs" / "pacing_summary.json"
    pacing_obj = _load_pacing_summary(pacing_path)
    if pacing_obj is not None:
        scores["pacing_summary_json_present"] = 1.0

        # Structure check
        films = pacing_obj.get("films", None)
        config_used = pacing_obj.get("config_used", None)
        structure_ok = isinstance(films, list) and (config_used is not None)
        # Films match expected set
        titles_in_json = set()
        if structure_ok:
            for item in films:
                if isinstance(item, dict) and "film_title" in item:
                    titles_in_json.add(item["film_title"])
                else:
                    structure_ok = False
                    break
        if structure_ok and titles_in_json == expected_titles:
            scores["pacing_summary_structure_and_films_match"] = 1.0

        # Config used correctness
        try:
            if _almost_equal(float(config_used), float(expected_json["config_used"])):
                scores["pacing_summary_config_used_correct"] = 1.0
        except Exception:
            pass

        # Metrics correctness
        metrics_ok = True
        scenes_and_valid_ok = True
        required_fields = [
            "film_title",
            "total_duration_s",
            "total_jump_scares",
            "jumps_per_min",
            "mean_scene_duration_s",
            "median_shot_length_s",
            "intense_loudness_proportion",
            "scenes_analyzed",
            "data_valid",
        ]
        if isinstance(films, list):
            for item in films:
                if not isinstance(item, dict):
                    metrics_ok = False
                    scenes_and_valid_ok = False
                    break
                # Required fields presence
                for rf in required_fields:
                    if rf not in item:
                        metrics_ok = False
                        scenes_and_valid_ok = False
                        break
                if "film_title" not in item:
                    metrics_ok = False
                    scenes_and_valid_ok = False
                    break
                title = item["film_title"]
                if title not in expected_by_title:
                    metrics_ok = False
                    scenes_and_valid_ok = False
                    continue
                exp = expected_by_title[title]
                # Numeric comparisons
                try:
                    if not _almost_equal(float(item["total_duration_s"]), float(exp["total_duration_s"])):
                        metrics_ok = False
                    if int(item["total_jump_scares"]) != int(exp["total_jump_scares"]):
                        metrics_ok = False
                    if not _almost_equal(float(item["jumps_per_min"]), float(exp["jumps_per_min"]), rel_tol=1e-9, abs_tol=1e-9):
                        metrics_ok = False
                    if not _almost_equal(float(item["mean_scene_duration_s"]), float(exp["mean_scene_duration_s"])):
                        metrics_ok = False
                    if not _almost_equal(float(item["median_shot_length_s"]), float(exp["median_shot_length_s"])):
                        metrics_ok = False
                    if not _almost_equal(float(item["intense_loudness_proportion"]), float(exp["intense_loudness_proportion"]), rel_tol=1e-9, abs_tol=1e-9):
                        metrics_ok = False
                except Exception:
                    metrics_ok = False
                # scenes_analyzed and data_valid
                try:
                    if int(item["scenes_analyzed"]) != int(exp["scenes_analyzed"]):
                        scenes_and_valid_ok = False
                    # data_valid should be boolean True if columns matched spec
                    if bool(item["data_valid"]) != bool(exp["data_valid"]):
                        scenes_and_valid_ok = False
                except Exception:
                    scenes_and_valid_ok = False
        else:
            metrics_ok = False
            scenes_and_valid_ok = False

        if metrics_ok:
            scores["pacing_summary_metrics_match_expected"] = 1.0
        if scenes_and_valid_ok:
            scores["pacing_summary_scenes_and_validation_correct"] = 1.0

    # Load film_comparison.csv
    comp_path = workspace / "outputs" / "film_comparison.csv"
    comp_data = _load_film_comparison_csv(comp_path)
    if comp_data is not None:
        scores["film_comparison_csv_present"] = 1.0
        columns, rows = comp_data

        # Columns correctness (exact order and names)
        expected_columns = [
            "film_title",
            "jumps_per_min",
            "median_shot_length_s",
            "intense_loudness_proportion",
            "ranking_by_jumps_per_min",
        ]
        if columns == expected_columns:
            scores["film_comparison_columns_correct"] = 1.0

        # Rows match films (set of titles)
        titles_in_csv = set()
        try:
            for r in rows:
                titles_in_csv.add(r["film_title"])
        except Exception:
            titles_in_csv = set()
        if titles_in_csv == expected_titles and len(rows) == len(expected_titles):
            scores["film_comparison_rows_match_films"] = 1.0

        # Values and ranking correctness
        values_ok = True
        ranking_ok = True
        # Build expected ranking by jumps_per_min (dense ranking: highest -> 1)
        jpm_values = sorted({float(v["jumps_per_min"]) for v in expected_by_title.values()}, reverse=True)
        jpm_rank_map = {val: idx + 1 for idx, val in enumerate(jpm_values)}
        # Map film title to expected rank
        exp_rank_by_title = {}
        for title, vals in expected_by_title.items():
            exp_rank_by_title[title] = jpm_rank_map[float(vals["jumps_per_min"])]

        for r in rows:
            title = r.get("film_title", "")
            if title not in expected_by_title:
                values_ok = False
                ranking_ok = False
                continue
            exp_vals = expected_by_title[title]
            try:
                r_jpm = float(r["jumps_per_min"])
                r_median = float(r["median_shot_length_s"])
                r_intense = float(r["intense_loudness_proportion"])
                r_rank = int(r["ranking_by_jumps_per_min"])
                if not _almost_equal(r_jpm, float(exp_vals["jumps_per_min"])):
                    values_ok = False
                if not _almost_equal(r_median, float(exp_vals["median_shot_length_s"])):
                    values_ok = False
                if not _almost_equal(r_intense, float(exp_vals["intense_loudness_proportion"])):
                    values_ok = False
                if r_rank != exp_rank_by_title[title]:
                    ranking_ok = False
            except Exception:
                values_ok = False
                ranking_ok = False

        if values_ok and ranking_ok:
            scores["film_comparison_values_and_ranking_correct"] = 1.0

        # Cross-file consistency: ensure values in CSV match those in JSON (if JSON present)
        cross_ok = True
        if pacing_obj is None or not isinstance(pacing_obj.get("films", None), list):
            cross_ok = False
        else:
            films_by_title_json = {f["film_title"]: f for f in pacing_obj["films"] if isinstance(f, dict) and "film_title" in f}
            for r in rows:
                t = r.get("film_title", "")
                if t not in films_by_title_json:
                    cross_ok = False
                    break
                jf = films_by_title_json[t]
                try:
                    if not _almost_equal(float(r["jumps_per_min"]), float(jf["jumps_per_min"])):
                        cross_ok = False
                        break
                    if not _almost_equal(float(r["median_shot_length_s"]), float(jf["median_shot_length_s"])):
                        cross_ok = False
                        break
                    if not _almost_equal(float(r["intense_loudness_proportion"]), float(jf["intense_loudness_proportion"])):
                        cross_ok = False
                        break
                except Exception:
                    cross_ok = False
                    break
        if cross_ok:
            scores["cross_file_consistency_between_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()