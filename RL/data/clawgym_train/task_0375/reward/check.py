import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Ensure header exists and rows are dicts
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        try:
            return float(val)
        except Exception:
            return None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        # Remove commas used as thousands separators if any
        s = s.replace(",", "")
        # Remove percentage sign if present
        s = s.replace("%", "")
        try:
            return float(s)
        except Exception:
            return None
    return None


def _float_equal(a: float, b: float, eps: float = 1e-6) -> bool:
    return abs(a - b) <= eps


def _compute_expected_metrics_and_top(rows: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Returns (metrics_dict, top_projects_list)
    metrics_dict keys:
      - total_reduction_mtco2e
      - mean_project_reduction_mtco2e
      - percent_reduction_overall
      - top_countries_by_reduction: list of {'country': str, 'total_reduction_mtco2e': float} length 3
    top_projects_list: list of dicts for top 5 with columns:
      project_id, country, initiative, emission_reduction_mtco2e, percent_reduction, funding_musd
    """
    active = []
    for r in rows:
        status = (r.get("status") or "").strip().lower()
        if status == "active":
            # Parse required numeric fields
            b = _parse_float(r.get("baseline_emissions_mtco2e"))
            c = _parse_float(r.get("current_emissions_mtco2e"))
            f = _parse_float(r.get("funding_musd"))
            if b is None or c is None or f is None:
                return None, None
            if b == 0:
                # Avoid division by zero; invalid input for required calc
                return None, None
            reduction = b - c
            percent = (reduction / b) * 100.0
            entry = {
                "project_id": r.get("project_id", "").strip(),
                "country": r.get("country", "").strip(),
                "initiative": r.get("initiative", "").strip(),
                "baseline": b,
                "current": c,
                "emission_reduction_mtco2e": reduction,
                "percent_reduction": percent,
                "funding_musd": f,
            }
            active.append(entry)

    if not active:
        # No active projects -> calculations undefined for mean/percent overall
        return None, None

    total_reduction = sum(p["emission_reduction_mtco2e"] for p in active)
    mean_reduction = total_reduction / len(active)
    total_baseline = sum(p["baseline"] for p in active)
    if total_baseline == 0:
        return None, None
    percent_overall = (total_reduction / total_baseline) * 100.0

    # Countries aggregation
    country_totals: Dict[str, float] = {}
    for p in active:
        country_totals[p["country"]] = country_totals.get(p["country"], 0.0) + p["emission_reduction_mtco2e"]
    # Sort: total desc, then country asc
    top_countries_sorted = sorted(
        country_totals.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    top_countries = [{"country": c, "total_reduction_mtco2e": t} for c, t in top_countries_sorted[:3]]

    # Top 5 projects by emission_reduction desc, tie by project_id asc
    top_projects_sorted = sorted(
        active,
        key=lambda p: (-p["emission_reduction_mtco2e"], p["project_id"]),
    )
    top5 = top_projects_sorted[:5]
    # Construct required columns for top5
    top5_rows = []
    for p in top5:
        top5_rows.append({
            "project_id": p["project_id"],
            "country": p["country"],
            "initiative": p["initiative"],
            "emission_reduction_mtco2e": p["emission_reduction_mtco2e"],
            "percent_reduction": p["percent_reduction"],
            "funding_musd": p["funding_musd"],
        })

    metrics = {
        "total_reduction_mtco2e": total_reduction,
        "mean_project_reduction_mtco2e": mean_reduction,
        "percent_reduction_overall": percent_overall,
        "top_countries_by_reduction": top_countries,
    }
    return metrics, top5_rows


def _normalize_text_for_compare(s: str) -> str:
    # Lowercase, strip punctuation-like chars, normalize whitespace
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _check_requirements_pinned(req_path: Path) -> float:
    text = _safe_read_text(req_path)
    if text is None:
        return 0.0
    lines = [ln.strip() for ln in text.splitlines()]
    # Consider only non-empty, non-comment lines that are not option flags starting with '-'
    specs = [ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("-")]
    if not specs:
        # If there are no package lines, fail
        return 0.0
    ok = True
    for ln in specs:
        # Accept only exact pins with '=='
        if "==" not in ln:
            ok = False
            break
        # Avoid environment markers and extras check loosely
        parts = ln.split("==")
        if len(parts) != 2:
            ok = False
            break
        pkg, ver = parts[0].strip(), parts[1].strip()
        if not pkg or not ver:
            ok = False
            break
        # Basic sanity: version should not contain comparison operators
        if any(op in ver for op in [">", "<", "~", "*", " "]):
            ok = False
            break
    return 1.0 if ok else 0.0


def _check_run_report_script(script_path: Path) -> Dict[str, float]:
    scores = {
        "run_report_venv_setup": 0.0,
        "run_report_installs_deps": 0.0,
        "run_report_references_build_outputs": 0.0,
    }
    text = _safe_read_text(script_path)
    if text is None:
        return scores

    lower = text.lower()

    # Check venv setup: presence of venv creation or activation
    venv_create = ("python -m venv" in lower) or ("python3 -m venv" in lower) or ("virtualenv " in lower)
    venv_activate = (".venv/bin/activate" in lower) or ("source .venv/bin/activate" in lower) or ("source ./.venv/bin/activate" in lower)
    if venv_create or venv_activate:
        scores["run_report_venv_setup"] = 1.0

    # Check pip install dependencies from requirements.txt
    installs = False
    for line in lower.splitlines():
        if "pip " in line and "install" in line and "-r" in line and "requirements.txt" in line:
            installs = True
            break
    scores["run_report_installs_deps"] = 1.0 if installs else 0.0

    # Check that the script references build directory or creates it
    if "build/" in lower or "mkdir -p build" in lower or "mkdir build" in lower:
        scores["run_report_references_build_outputs"] = 1.0

    return scores


def _check_metrics_json(workspace: Path, expected_metrics: Dict[str, Any]) -> float:
    metrics_path = workspace / "build" / "metrics.json"
    data = _safe_load_json(metrics_path)
    if not isinstance(data, dict):
        return 0.0

    # Required keys
    req_keys = ["total_reduction_mtco2e", "mean_project_reduction_mtco2e", "percent_reduction_overall", "top_countries_by_reduction"]
    for k in req_keys:
        if k not in data:
            return 0.0

    # Compare numeric values
    a = _parse_float(data["total_reduction_mtco2e"])
    b = _parse_float(data["mean_project_reduction_mtco2e"])
    c = _parse_float(data["percent_reduction_overall"])
    if a is None or b is None or c is None:
        return 0.0
    if not (_float_equal(a, expected_metrics["total_reduction_mtco2e"]) and
            _float_equal(b, expected_metrics["mean_project_reduction_mtco2e"]) and
            _float_equal(c, expected_metrics["percent_reduction_overall"])):
        return 0.0

    # Check top countries list
    tlist = data["top_countries_by_reduction"]
    if not isinstance(tlist, list):
        return 0.0
    if len(tlist) < 3:
        return 0.0
    # Only first 3 are required to match exactly in order
    for i in range(3):
        item = tlist[i]
        if not isinstance(item, dict):
            return 0.0
        if "country" not in item or "total_reduction_mtco2e" not in item:
            return 0.0
        exp_item = expected_metrics["top_countries_by_reduction"][i]
        if str(item["country"]).strip() != exp_item["country"]:
            return 0.0
        val = _parse_float(item["total_reduction_mtco2e"])
        if val is None or not _float_equal(val, exp_item["total_reduction_mtco2e"]):
            return 0.0

    return 1.0


def _check_top_projects_csv(workspace: Path, expected_top: List[Dict[str, Any]]) -> float:
    csv_path = workspace / "build" / "top_projects.csv"
    rows = _safe_read_csv_dicts(csv_path)
    if rows is None:
        return 0.0
    # Expect exactly 5 rows
    if len(rows) != 5:
        return 0.0

    # Check header exact order
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
    except Exception:
        return 0.0
    expected_header = "project_id,country,initiative,emission_reduction_mtco2e,percent_reduction,funding_musd"
    if header_line.replace(" ", "") != expected_header:
        return 0.0

    # Compare each row to expected order and values
    for i, row in enumerate(rows):
        exp = expected_top[i]
        # Required columns exist
        for col in ["project_id", "country", "initiative", "emission_reduction_mtco2e", "percent_reduction", "funding_musd"]:
            if col not in row:
                return 0.0
        if (row["project_id"] or "").strip() != exp["project_id"]:
            return 0.0
        if (row["country"] or "").strip() != exp["country"]:
            return 0.0
        if (row["initiative"] or "").strip() != exp["initiative"]:
            return 0.0
        # Numeric comparisons with tolerance
        er = _parse_float(row["emission_reduction_mtco2e"])
        pr = _parse_float(row["percent_reduction"])
        fm = _parse_float(row["funding_musd"])
        if er is None or pr is None or fm is None:
            return 0.0
        if not _float_equal(er, float(exp["emission_reduction_mtco2e"])):
            return 0.0
        if not _float_equal(pr, float(exp["percent_reduction"])):
            return 0.0
        if not _float_equal(fm, float(exp["funding_musd"])):
            return 0.0

    return 1.0


def _check_index_html(workspace: Path, expected_metrics: Dict[str, Any], expected_top: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Returns:
      {
        "index_html_has_summary_and_countries": 0.0-1.0,
        "index_html_has_ranked_projects_table": 0.0-1.0
      }
    """
    scores = {
        "index_html_has_summary_and_countries": 0.0,
        "index_html_has_ranked_projects_table": 0.0,
    }
    path = workspace / "build" / "index.html"
    text = _safe_read_text(path)
    if text is None:
        return scores

    lower = text.lower()

    # Summary keyword
    has_summary = "summary" in lower

    # Top countries presence
    countries = [c["country"] for c in expected_metrics["top_countries_by_reduction"]]
    countries_present = all((c.lower() in lower) for c in countries)

    if has_summary and countries_present:
        scores["index_html_has_summary_and_countries"] = 1.0

    # Table: headers and ordered projects
    headers_present = all(h in lower for h in [
        "project_id", "country", "initiative", "emission_reduction_mtco2e", "percent_reduction", "funding_musd"
    ])
    # Check project IDs appear in order
    positions = []
    for p in expected_top:
        pid = p["project_id"].lower()
        idx = lower.find(pid)
        positions.append(idx)
    ordered = all(i >= 0 for i in positions) and all(positions[i] < positions[i+1] for i in range(len(positions)-1))

    if headers_present and ordered:
        scores["index_html_has_ranked_projects_table"] = 1.0

    return scores


def _extract_bullets_from_md(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line)
        elif line.startswith("-"):
            # In case missing space after dash
            bullets.append("- " + line[1:].lstrip())
    return bullets


def _check_remarks_rewritten(workspace: Path, input_path: Path) -> float:
    # Load original
    original_text = _safe_read_text(input_path)
    if original_text is None:
        return 0.0
    original_bullets = _extract_bullets_from_md(original_text)
    if not original_bullets:
        return 0.0

    # Load rewritten
    rewritten_path = workspace / "build" / "remarks_rewritten.md"
    rewritten_text = _safe_read_text(rewritten_path)
    if rewritten_text is None:
        return 0.0
    rewritten_bullets = _extract_bullets_from_md(rewritten_text)

    # Check same count
    if len(rewritten_bullets) != len(original_bullets):
        return 0.0

    # Each bullet starts with dash and <= 25 words, and is not identical to original
    for ob, rb in zip(original_bullets, rewritten_bullets):
        if not rb.startswith("- "):
            return 0.0
        content = rb[2:].strip()
        words = [w for w in content.split() if w]
        if len(words) > 25:
            return 0.0
        # Not identical (normalized)
        if _normalize_text_for_compare(ob) == _normalize_text_for_compare(rb):
            return 0.0

    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "requirements_txt_pins_versions": 0.0,
        "run_report_venv_setup": 0.0,
        "run_report_installs_deps": 0.0,
        "run_report_references_build_outputs": 0.0,
        "metrics_json_correct": 0.0,
        "top_projects_csv_correct": 0.0,
        "index_html_has_summary_and_countries": 0.0,
        "index_html_has_ranked_projects_table": 0.0,
        "remarks_rewritten_structure_and_brevity": 0.0,
    }

    # Check requirements.txt
    req_path = workspace / "requirements.txt"
    scores["requirements_txt_pins_versions"] = _check_requirements_pinned(req_path)

    # Check run_report.sh
    run_script = workspace / "run_report.sh"
    script_scores = _check_run_report_script(run_script)
    scores.update(script_scores)

    # Load input data for expected computations
    projects_path = workspace / "input" / "projects.csv"
    rows = _safe_read_csv_dicts(projects_path)
    if rows is not None:
        expected_metrics, expected_top = _compute_expected_metrics_and_top(rows)
    else:
        expected_metrics, expected_top = None, None

    # metrics.json correctness
    if expected_metrics is not None:
        scores["metrics_json_correct"] = _check_metrics_json(workspace, expected_metrics)
    else:
        scores["metrics_json_correct"] = 0.0

    # top_projects.csv correctness
    if expected_top is not None:
        scores["top_projects_csv_correct"] = _check_top_projects_csv(workspace, expected_top)
    else:
        scores["top_projects_csv_correct"] = 0.0

    # index.html checks
    if expected_metrics is not None and expected_top is not None:
        index_scores = _check_index_html(workspace, expected_metrics, expected_top)
        scores.update(index_scores)
    else:
        # Already initialized to 0.0
        pass

    # remarks rewritten check
    remarks_input = workspace / "input" / "remarks.md"
    scores["remarks_rewritten_structure_and_brevity"] = _check_remarks_rewritten(workspace, remarks_input)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()