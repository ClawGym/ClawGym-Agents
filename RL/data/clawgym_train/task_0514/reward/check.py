import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[dict]:
    """
    Minimal YAML parser for a small subset:
    - key: value (scalar string or int/float)
    - key:
        - item
        - item
    Ignores comments (# ...) and blank lines.
    Returns dict or None on failure.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: dict = {}
    current_list_key: Optional[str] = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Remove inline trailing comments beginning with ' #' (simple heuristic)
            if " #" in line:
                parts = line.split(" #", 1)
                line = parts[0].rstrip()
                if not line:
                    continue

            if current_list_key:
                if line.startswith("- "):
                    item = line[2:].strip()
                    item = _strip_quotes(item)
                    data[current_list_key].append(_coerce_scalar(item))
                    continue
                else:
                    current_list_key = None  # end of list

            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if val == "":
                    # start of list or empty value
                    current_list_key = key
                    data[key] = []
                else:
                    val = _strip_quotes(val)
                    data[key] = _coerce_scalar(val)
            else:
                continue
        return data
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _coerce_scalar(s: str):
    try:
        return int(s)
    except Exception:
        pass
    try:
        return float(s)
    except Exception:
        pass
    return s


def _parse_pilot_html(html_path: Path) -> Optional[Dict[str, str]]:
    """
    Parse <ul id="pilot-schools"> and extract <li data-school-id="...">Name</li>
    """
    text = _read_text(html_path)
    if text is None:
        return None
    try:
        ul_match = re.search(
            r'<ul[^>]*id=["\']pilot-schools["\'][^>]*>(.*?)</ul>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not ul_match:
            return {}
        ul_content = ul_match.group(1)
        items = re.findall(
            r'<li[^>]*data-school-id=["\']([^"\']+)["\'][^>]*>(.*?)</li>',
            ul_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        result: Dict[str, str] = {}
        for sid, name in items:
            clean_name = re.sub(r"\s+", " ", name).strip()
            result[sid.strip()] = clean_name
        return result
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _discover_data_csvs(data_dir: Path) -> List[Path]:
    try:
        return sorted([p for p in data_dir.rglob("*.csv") if p.is_file()])
    except Exception:
        return []


def _compute_expected_summary(workspace: Path, cfg: dict, pilot_ids: set) -> Optional[List[dict]]:
    data_dir = workspace / "data"
    csv_paths = _discover_data_csvs(data_dir)
    if not csv_paths:
        return None
    score_field = cfg.get("score_field", "avg_score")
    try:
        min_students = int(cfg.get("min_valid_students", 0))
    except Exception:
        return None
    exp_methods = set(cfg.get("experimental_methods", []) or [])
    groups: Dict[Tuple[int, str, str], dict] = {}
    for p in csv_paths:
        fns, rows = _read_csv_dicts(p)
        if rows is None:
            return None
        for r in rows:
            try:
                year = int(r["year"])
                sid = r["school_id"]
                students = int(r["students_tested"])
                score_str = r[score_field]
                score = float(score_str)
                method = r.get("method", "")
            except Exception:
                continue
            if students < min_students:
                continue
            group = "pilot" if sid in pilot_ids else "non_pilot"
            method_category = "experimental" if method in exp_methods else "traditional"
            key = (year, group, method_category)
            if key not in groups:
                groups[key] = {
                    "schools_count": 0,
                    "students_total": 0,
                    "score_sum_for_mean": 0.0,
                    "weighted_score_sum": 0.0,
                }
            agg = groups[key]
            agg["schools_count"] += 1
            agg["students_total"] += students
            agg["score_sum_for_mean"] += score
            agg["weighted_score_sum"] += score * students
    out_rows: List[dict] = []
    for (year, group, method_cat), agg in sorted(groups.items()):
        schools_count = agg["schools_count"]
        students_total = agg["students_total"]
        average_score_mean = (agg["score_sum_for_mean"] / schools_count) if schools_count else 0.0
        average_score_weighted = (agg["weighted_score_sum"] / students_total) if students_total else 0.0
        out_rows.append(
            {
                "year": int(year),
                "group": group,
                "method_category": method_cat,
                "schools_count": int(schools_count),
                "students_total": int(students_total),
                "average_score_mean": float(average_score_mean),
                "average_score_weighted": float(average_score_weighted),
            }
        )
    return out_rows


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pilot_csv_exists": 0.0,
        "pilot_csv_headers_correct": 0.0,
        "pilot_csv_content_matches_html": 0.0,
        "summary_csv_exists": 0.0,
        "summary_csv_headers_correct": 0.0,
        "summary_csv_values_correct": 0.0,
        "effective_config_exists": 0.0,
        "effective_config_min_valid_students_30": 0.0,
        "effective_config_experimental_methods_complete": 0.0,
        "effective_config_score_field_is_avg_score": 0.0,
        "effective_config_pilot_html_path_correct": 0.0,
        "analysis_config_min_valid_students_30": 0.0,
        "analysis_config_experimental_methods_complete": 0.0,
        "analysis_config_score_field_is_avg_score": 0.0,
        "analysis_config_pilot_html_path_correct": 0.0,
        "script_parse_pilot_schools_implemented": 0.0,
        "script_discover_csvs_recursive": 0.0,
    }

    # Paths
    pilot_html_path = workspace / "meta" / "pilots.html"
    pilot_csv_path = workspace / "output" / "pilot_schools_extracted.csv"
    summary_csv_path = workspace / "output" / "summary_by_group.csv"
    effective_cfg_path = workspace / "output" / "config_effective.yaml"
    analysis_cfg_path = workspace / "config" / "analysis.yaml"
    script_path = workspace / "scripts" / "process_scores.py"

    # Pilot extraction CSV checks
    pilot_fieldnames, pilot_rows = _read_csv_dicts(pilot_csv_path)
    if pilot_rows is not None:
        scores["pilot_csv_exists"] = 1.0
        expected_headers = ["school_id", "school_name"]
        if pilot_fieldnames == expected_headers:
            scores["pilot_csv_headers_correct"] = 1.0
        # Compare content to HTML-derived pilot list
        html_pilots = _parse_pilot_html(pilot_html_path) or {}
        actual_set = {(r.get("school_id", "").strip(), r.get("school_name", "").strip()) for r in pilot_rows}
        expected_set = {(sid, name) for sid, name in html_pilots.items()}
        if actual_set == expected_set and len(actual_set) == len(html_pilots):
            scores["pilot_csv_content_matches_html"] = 1.0

    # Effective config checks
    effective_cfg = _parse_simple_yaml(effective_cfg_path)
    if effective_cfg is not None:
        scores["effective_config_exists"] = 1.0
        try:
            if int(effective_cfg.get("min_valid_students", -1)) == 30:
                scores["effective_config_min_valid_students_30"] = 1.0
        except Exception:
            pass
        exp_methods = effective_cfg.get("experimental_methods", []) or []
        exp_set = set(exp_methods) if isinstance(exp_methods, list) else set()
        required_methods = {
            "Project-Based Learning",
            "Flipped Classroom",
            "Block Scheduling",
        }
        if required_methods.issubset(exp_set):
            scores["effective_config_experimental_methods_complete"] = 1.0
        if str(effective_cfg.get("score_field", "")) == "avg_score":
            scores["effective_config_score_field_is_avg_score"] = 1.0
        if str(effective_cfg.get("pilot_html_path", "")) == "meta/pilots.html":
            scores["effective_config_pilot_html_path_correct"] = 1.0

    # Analysis config checks (source file edits)
    analysis_cfg = _parse_simple_yaml(analysis_cfg_path)
    if analysis_cfg is not None:
        try:
            if int(analysis_cfg.get("min_valid_students", -1)) == 30:
                scores["analysis_config_min_valid_students_30"] = 1.0
        except Exception:
            pass
        exp_methods_src = analysis_cfg.get("experimental_methods", []) or []
        exp_set_src = set(exp_methods_src) if isinstance(exp_methods_src, list) else set()
        if {"Project-Based Learning", "Flipped Classroom", "Block Scheduling"}.issubset(exp_set_src):
            scores["analysis_config_experimental_methods_complete"] = 1.0
        # To avoid awarding baseline credit for pre-existing defaults,
        # only award the following if key updates have been made (min_valid_students and experimental methods complete).
        if (
            scores["analysis_config_min_valid_students_30"] == 1.0
            and scores["analysis_config_experimental_methods_complete"] == 1.0
        ):
            if str(analysis_cfg.get("score_field", "")) == "avg_score":
                scores["analysis_config_score_field_is_avg_score"] = 1.0
            if str(analysis_cfg.get("pilot_html_path", "")) == "meta/pilots.html":
                scores["analysis_config_pilot_html_path_correct"] = 1.0

    # Summary CSV checks
    summary_fieldnames, summary_rows = _read_csv_dicts(summary_csv_path)
    if summary_rows is not None:
        scores["summary_csv_exists"] = 1.0
        expected_summary_headers = [
            "year",
            "group",
            "method_category",
            "schools_count",
            "students_total",
            "average_score_mean",
            "average_score_weighted",
        ]
        if summary_fieldnames == expected_summary_headers:
            scores["summary_csv_headers_correct"] = 1.0

        # Values correctness: require effective config to compute expected
        if effective_cfg is not None:
            html_pilots = _parse_pilot_html(pilot_html_path) or {}
            pilot_ids = set(html_pilots.keys())
            expected_rows = _compute_expected_summary(workspace, effective_cfg, pilot_ids)
            if expected_rows is not None:
                actual_map: Dict[Tuple[int, str, str], dict] = {}
                valid_parse = True
                for r in summary_rows:
                    y = _parse_int(str(r.get("year", "")).strip())
                    g = str(r.get("group", "")).strip()
                    m = str(r.get("method_category", "")).strip()
                    sc = _parse_int(str(r.get("schools_count", "")).strip())
                    st = _parse_int(str(r.get("students_total", "")).strip())
                    mean = _parse_float(str(r.get("average_score_mean", "")).strip())
                    wmean = _parse_float(str(r.get("average_score_weighted", "")).strip())
                    if None in (y, sc, st, mean, wmean) or not g or not m:
                        valid_parse = False
                        break
                    actual_map[(y, g, m)] = {
                        "schools_count": sc,
                        "students_total": st,
                        "average_score_mean": mean,
                        "average_score_weighted": wmean,
                    }
                if valid_parse:
                    expected_keys = {(r["year"], r["group"], r["method_category"]) for r in expected_rows}
                    actual_keys = set(actual_map.keys())
                    if expected_keys == actual_keys and len(actual_keys) == len(expected_rows):
                        all_match = True
                        for er in expected_rows:
                            k = (er["year"], er["group"], er["method_category"])
                            av = actual_map.get(k)
                            if av is None:
                                all_match = False
                                break
                            if av["schools_count"] != er["schools_count"]:
                                all_match = False
                                break
                            if av["students_total"] != er["students_total"]:
                                all_match = False
                                break
                            if not _float_eq(av["average_score_mean"], er["average_score_mean"]):
                                all_match = False
                                break
                            if not _float_eq(av["average_score_weighted"], er["average_score_weighted"]):
                                all_match = False
                                break
                        if all_match:
                            scores["summary_csv_values_correct"] = 1.0

    # Script static checks
    script_text = _read_text(script_path) or ""
    if script_text:
        # Check that NotImplementedError for parse_pilot_schools is not present (indicates implemented)
        if "parse_pilot_schools" in script_text and "NotImplementedError" not in script_text:
            scores["script_parse_pilot_schools_implemented"] = 1.0
        # Check recursive discovery usage: rglob(, os.walk(, or glob with ** pattern
        recursive_detected = False
        if "rglob(" in script_text:
            recursive_detected = True
        elif "os.walk(" in script_text:
            recursive_detected = True
        else:
            # Look for glob with **/*.csv pattern
            glob_patterns = re.findall(r'glob\(([^)]*)\)', script_text)
            for pat in glob_patterns:
                if "**" in pat and ".csv" in pat:
                    recursive_detected = True
                    break
        if recursive_detected:
            scores["script_discover_csvs_recursive"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()