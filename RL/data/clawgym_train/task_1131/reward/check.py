import json
import csv
import sys
import re
from statistics import median
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames or []
    except Exception:
        return None, None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, (int, float)):
            return int(x)
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _contains_word(text: str, words: List[str]) -> bool:
    if text is None:
        return False
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text, flags=re.IGNORECASE):
            return True
    return False


def _meets_filters(row: Dict[str, str]) -> bool:
    domain_ok = str(row.get("domain", "")).strip().lower() in {"manufacturing", "industrial"}
    status_ok = str(row.get("status", "")).strip().lower() in {"deployed", "pilot"}
    year = _to_int(row.get("year", ""))
    year_ok = year is not None and year >= 2020
    title = row.get("title", "") or ""
    description = row.get("description", "") or ""
    text_ok = _contains_word(title, ["safety", "maintenance"]) or _contains_word(description, ["safety", "maintenance"])
    return domain_ok and status_ok and year_ok and text_ok


def _compute_cost_per_participant(row: Dict[str, str]) -> Optional[float]:
    cost = _to_float(row.get("cost_usd", ""))
    participants = _to_float(row.get("participants", ""))
    if cost is None or participants is None or participants == 0:
        return None
    return cost / participants


def _compute_roi(row: Dict[str, str]) -> Optional[float]:
    time_saved = _to_float(row.get("metric_time_saved_percent", ""))
    error_reduction = _to_float(row.get("metric_error_reduction_percent", ""))
    cpp = _compute_cost_per_participant(row)
    if time_saved is None or error_reduction is None or cpp is None:
        return None
    roi = 0.5 * time_saved + 0.5 * error_reduction - (cpp / 500.0)
    return roi


def _round_one_decimal_str(val: float) -> str:
    return f"{round(val + 1e-12, 1):.1f}"


def _almost_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _expected_filtered(projects: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    filtered = []
    for r in projects:
        if _meets_filters(r):
            cpp = _compute_cost_per_participant(r)
            roi = _compute_roi(r)
            if cpp is None or roi is None:
                continue
            r_copy = dict(r)
            r_copy["cost_per_participant"] = cpp
            r_copy["roi_score"] = roi
            filtered.append(r_copy)
    filtered.sort(key=lambda x: x["roi_score"], reverse=True)
    return filtered


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    try:
        return float(median(values))
    except Exception:
        return None


def _safe_parse_roi_from_str(s: str) -> Optional[float]:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    return _to_float(m.group(0))


def _extract_bulleted_top3(report_text: str) -> List[str]:
    lines = [ln.strip() for ln in report_text.splitlines()]
    bullets = []
    for ln in lines:
        if ln.startswith(("- ", "* ")):
            if "(" in ln and ")" in ln and ln.find("(") < ln.rfind(")"):
                inner = ln[ln.find("(") + 1: ln.rfind(")")]
                parts = [p.strip() for p in inner.split(",")]
                if len(parts) == 5:
                    bullets.append(ln)
    return bullets


def _parse_bullet_tuple(line: str) -> Optional[Tuple[str, str, str, str, str]]:
    if "(" not in line or ")" not in line:
        return None
    inner = line[line.find("(") + 1: line.rfind(")")]
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) != 5:
        return None
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "filtered_csv_exists_and_header": 0.0,
        "filtered_csv_row_count_and_ids": 0.0,
        "filtered_csv_computed_values_correct": 0.0,
        "filtered_csv_sorted_by_roi_desc": 0.0,
        "stats_json_exists_and_schema": 0.0,
        "stats_counts_and_aggregates_correct": 0.0,
        "stats_top3_ids_correct": 0.0,
        "cross_stats_eligible_matches_filtered": 0.0,
        "report_exists_and_length": 0.0,
        "report_summary_line_matches_stats": 0.0,
        "report_top3_bullets_correct": 0.0,
        "report_engines_strengths_cited": 0.0,
        "cross_top3_consistency_across_files": 0.0,
        "report_concludes_with_next_step": 0.0,
    }

    projects_csv_path = workspace / "input" / "projects.csv"
    engines_json_path = workspace / "input" / "engines.json"
    outputs_filtered_path = workspace / "outputs" / "filtered_cases.csv"
    outputs_stats_path = workspace / "outputs" / "stats.json"
    outputs_report_path = workspace / "outputs" / "report.md"

    projects_rows, projects_header = _read_csv_dicts(projects_csv_path)
    engines_json = _load_json(engines_json_path)

    expected_filtered_rows: List[Dict[str, Any]] = []
    expected_ids_order: List[str] = []
    expected_counts_by_engine: Dict[str, int] = {}
    expected_counts_by_modality: Dict[str, int] = {}
    expected_stats: Dict[str, Any] = {}

    if projects_rows is not None and projects_header is not None:
        expected_filtered_rows = _expected_filtered(projects_rows)
        expected_ids_order = [r["id"] for r in expected_filtered_rows]

        total_projects = len(projects_rows)
        eligible_projects = len(expected_filtered_rows)
        for r in expected_filtered_rows:
            eng = r.get("engine", "")
            expected_counts_by_engine[eng] = expected_counts_by_engine.get(eng, 0) + 1
        for r in expected_filtered_rows:
            mod = r.get("modality", "")
            expected_counts_by_modality[mod] = expected_counts_by_modality.get(mod, 0) + 1

        time_vals = [_to_float(r.get("metric_time_saved_percent")) for r in expected_filtered_rows]
        time_vals = [v for v in time_vals if v is not None]
        err_vals = [_to_float(r.get("metric_error_reduction_percent")) for r in expected_filtered_rows]
        err_vals = [v for v in err_vals if v is not None]
        dep_vals = [_to_float(r.get("deployment_time_days")) for r in expected_filtered_rows]
        dep_vals = [v for v in dep_vals if v is not None]
        part_vals = [_to_int(r.get("participants")) for r in expected_filtered_rows]
        part_vals = [v for v in part_vals if v is not None]

        avg_time = float(sum(time_vals) / len(time_vals)) if time_vals else None
        avg_err = float(sum(err_vals) / len(err_vals)) if err_vals else None
        med_dep = _median(dep_vals) if dep_vals else None
        total_participants = int(sum(part_vals)) if part_vals else 0

        top_engine_candidates = []
        if expected_counts_by_engine:
            max_count = max(expected_counts_by_engine.values())
            top_engine_candidates = sorted([k for k, v in expected_counts_by_engine.items() if v == max_count])

        top3_ids = expected_ids_order[:3]

        expected_stats = {
            "total_projects": total_projects,
            "eligible_projects": eligible_projects,
            "counts_by_engine": expected_counts_by_engine,
            "counts_by_modality": expected_counts_by_modality,
            "avg_time_saved_percent": avg_time,
            "avg_error_reduction_percent": avg_err,
            "median_deployment_time_days": med_dep,
            "total_participants": total_participants,
            "top_engine_by_eligible_count_candidates": top_engine_candidates,
            "top3_ids_by_roi": top3_ids,
        }

    out_rows, out_header = _read_csv_dicts(outputs_filtered_path)
    if out_rows is not None and out_header is not None:
        original_cols = [
            "id",
            "title",
            "domain",
            "modality",
            "engine",
            "status",
            "cost_usd",
            "deployment_time_days",
            "participants",
            "metric_time_saved_percent",
            "metric_error_reduction_percent",
            "year",
            "description",
        ]
        expected_header = original_cols + ["cost_per_participant", "roi_score"]
        if out_header == expected_header:
            scores["filtered_csv_exists_and_header"] = 1.0

        out_ids = [r.get("id", "") for r in out_rows]
        if expected_ids_order and out_ids == expected_ids_order:
            scores["filtered_csv_row_count_and_ids"] = 1.0

        computed_ok = True
        if expected_filtered_rows and len(expected_filtered_rows) == len(out_rows):
            for expected_row, actual_row in zip(expected_filtered_rows, out_rows):
                exp_cpp = expected_row["cost_per_participant"]
                exp_roi = expected_row["roi_score"]
                act_cpp = _to_float(actual_row.get("cost_per_participant"))
                act_roi = _to_float(actual_row.get("roi_score"))
                if not _almost_equal(exp_cpp, act_cpp) or not _almost_equal(exp_roi, act_roi):
                    computed_ok = False
                    break
        else:
            computed_ok = False
        if computed_ok:
            scores["filtered_csv_computed_values_correct"] = 1.0

        sort_ok = True
        roi_vals = []
        for r in out_rows:
            rv = _to_float(r.get("roi_score"))
            if rv is None:
                sort_ok = False
                break
            roi_vals.append(rv)
        if sort_ok:
            for i in range(1, len(roi_vals)):
                if roi_vals[i] > roi_vals[i - 1] + 1e-9:
                    sort_ok = False
                    break
        if sort_ok:
            scores["filtered_csv_sorted_by_roi_desc"] = 1.0

    stats_json = _load_json(outputs_stats_path)
    if isinstance(stats_json, dict):
        required_keys = [
            "total_projects",
            "eligible_projects",
            "counts_by_engine",
            "counts_by_modality",
            "avg_time_saved_percent",
            "avg_error_reduction_percent",
            "median_deployment_time_days",
            "total_participants",
            "top_engine_by_eligible_count",
            "top3_ids_by_roi",
        ]
        schema_ok = all(k in stats_json for k in required_keys)
        if schema_ok:
            scores["stats_json_exists_and_schema"] = 1.0

        counts_ok = False
        if expected_stats:
            try:
                tp_ok = stats_json.get("total_projects") == expected_stats["total_projects"]
                ep_ok = stats_json.get("eligible_projects") == expected_stats["eligible_projects"]
                cbe_ok = stats_json.get("counts_by_engine") == expected_stats["counts_by_engine"]
                cbm_ok = stats_json.get("counts_by_modality") == expected_stats["counts_by_modality"]
                ats_ok = _almost_equal(_to_float(stats_json.get("avg_time_saved_percent")), expected_stats["avg_time_saved_percent"])
                aer_ok = _almost_equal(_to_float(stats_json.get("avg_error_reduction_percent")), expected_stats["avg_error_reduction_percent"])
                mdt_ok = _almost_equal(_to_float(stats_json.get("median_deployment_time_days")), expected_stats["median_deployment_time_days"])
                tp_sum_ok = stats_json.get("total_participants") == expected_stats["total_participants"]
                te_val = stats_json.get("top_engine_by_eligible_count")
                te_ok = te_val in expected_stats.get("top_engine_by_eligible_count_candidates", [])
                counts_ok = all([tp_ok, ep_ok, cbe_ok, cbm_ok, ats_ok, aer_ok, mdt_ok, tp_sum_ok, te_ok])
            except Exception:
                counts_ok = False
        if counts_ok:
            scores["stats_counts_and_aggregates_correct"] = 1.0

        top3_ok = False
        if expected_stats and isinstance(stats_json.get("top3_ids_by_roi"), list):
            top3_ok = stats_json.get("top3_ids_by_roi") == expected_stats["top3_ids_by_roi"]
        if top3_ok:
            scores["stats_top3_ids_correct"] = 1.0

        if out_rows is not None:
            try:
                scores["cross_stats_eligible_matches_filtered"] = 1.0 if stats_json.get("eligible_projects") == len(out_rows) else 0.0
            except Exception:
                scores["cross_stats_eligible_matches_filtered"] = 0.0

    report_text = _read_text(outputs_report_path)
    if report_text is not None:
        words = re.findall(r"\b\S+\b", report_text)
        if 280 <= len(words) <= 520:
            scores["report_exists_and_length"] = 1.0

        summary_ok = False
        if isinstance(stats_json, dict):
            X = stats_json.get("total_projects")
            Y = stats_json.get("eligible_projects")
            Z_val = stats_json.get("median_deployment_time_days")
            z_variants = []
            if isinstance(Z_val, (int, float)):
                if isinstance(Z_val, float) and abs(Z_val - int(Z_val)) < 1e-9:
                    z_variants.append(str(int(Z_val)))
                    z_variants.append(f"{float(Z_val)}")
                else:
                    z_str = str(Z_val)
                    z_variants.append(z_str)
                    if "." in z_str:
                        z_variants.append(z_str.rstrip("0").rstrip("."))
            candidate_lines = []
            for z in z_variants:
                candidate_lines.append(f"Summary: {X} projects considered, {Y} meet criteria, median deployment time {z} days.")
            report_lines = [ln.strip() for ln in report_text.splitlines()]
            if any(cl in report_lines for cl in candidate_lines):
                summary_ok = True
        if summary_ok:
            scores["report_summary_line_matches_stats"] = 1.0

        bullets = _extract_bulleted_top3(report_text)
        if len(bullets) >= 3 and expected_filtered_rows:
            first_three = bullets[:3]
            parsed = [_parse_bullet_tuple(b) for b in first_three]
            if all(p is not None for p in parsed):
                ok_all = True
                for idx, (pid, title, engine, modality, roi_str) in enumerate(parsed):
                    exp = expected_filtered_rows[idx]
                    id_ok = pid == exp["id"]
                    title_ok = title == exp["title"]
                    engine_ok = engine == exp["engine"]
                    modality_ok = modality == exp["modality"]
                    exp_roi = exp["roi_score"]
                    exp_roi_str = _round_one_decimal_str(exp_roi)
                    roi_num = _safe_parse_roi_from_str(roi_str)
                    roi_str_has_decimal = "." in roi_str
                    roi_ok = roi_num is not None and _almost_equal(roi_num, float(exp_roi_str), tol=0.05) and roi_str_has_decimal
                    if not (id_ok and title_ok and engine_ok and modality_ok and roi_ok):
                        ok_all = False
                        break
                scores["report_top3_bullets_correct"] = 1.0 if ok_all else 0.0

                stats_top3 = []
                if isinstance(stats_json, dict) and isinstance(stats_json.get("top3_ids_by_roi"), list):
                    stats_top3 = stats_json.get("top3_ids_by_roi")
                parsed_ids = [p[0] for p in parsed if p]
                cross_ok = parsed_ids == expected_ids_order[:3]
                if stats_top3:
                    cross_ok = cross_ok and (parsed_ids == stats_top3)
                scores["cross_top3_consistency_across_files"] = 1.0 if cross_ok else 0.0

                if isinstance(engines_json, dict):
                    engines_in_top3 = list({expected_filtered_rows[0]["engine"], expected_filtered_rows[1]["engine"], expected_filtered_rows[2]["engine"]})
                    report_lower = report_text.lower()
                    strengths_ok_all = True
                    for eng in engines_in_top3:
                        eng_info = engines_json.get(eng)
                        if not isinstance(eng_info, dict):
                            strengths_ok_all = False
                            break
                        strengths = eng_info.get("strengths", [])
                        found = False
                        for phrase in strengths:
                            if phrase and phrase.lower() in report_lower:
                                found = True
                                break
                        if not found:
                            strengths_ok_all = False
                            break
                    scores["report_engines_strengths_cited"] = 1.0 if strengths_ok_all else 0.0

        last_non_empty = ""
        for ln in (ln.strip() for ln in report_text.splitlines()[::-1]):
            if ln:
                last_non_empty = ln
                break
        if last_non_empty and re.search(r"next step", last_non_empty, flags=re.IGNORECASE):
            scores["report_concludes_with_next_step"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()