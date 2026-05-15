import json
import csv
import sys
import subprocess
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            # Ensure required columns exist
            required = {"farm_id", "region", "method", "season", "yield_kg_per_ha", "water_used_mm"}
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                return None, "missing_required_columns"
            # Type conversion for numeric fields
            for r in rows:
                try:
                    r["yield_kg_per_ha"] = float(r["yield_kg_per_ha"])
                    r["water_used_mm"] = float(r["water_used_mm"])
                except Exception:
                    return None, "non_numeric_values"
            return rows, None
    except FileNotFoundError:
        return None, "file_not_found"
    except Exception:
        return None, "parse_error"


def _compute_expected_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Compute WUE for each row and overall average, and regional summaries
    all_wue = []
    by_region_method: Dict[Tuple[str, str], List[float]] = {}
    regions_set = set()
    for r in rows:
        try:
            wue = r["yield_kg_per_ha"] / r["water_used_mm"]
        except Exception:
            # If division invalid (e.g., zero), skip this row
            continue
        all_wue.append(wue)
        key = (r["region"], r["method"])
        by_region_method.setdefault(key, []).append(wue)
        regions_set.add(r["region"])
    overall = sum(all_wue) / len(all_wue) if all_wue else float("nan")

    # organize by region
    improvement_by_region = []
    regions_sorted = sorted(list(regions_set))
    for region in regions_sorted:
        base_list = by_region_method.get((region, "conventional"), [])
        improved_list = by_region_method.get((region, "mulch_drip"), [])
        base = sum(base_list) / len(base_list) if base_list else None
        improved = sum(improved_list) / len(improved_list) if improved_list else None
        if base is not None and improved is not None and base != 0:
            pct = ((improved - base) / base) * 100.0
        else:
            pct = None
        improvement_by_region.append({
            "region": region,
            "baseline": base,
            "improved": improved,
            "percent_improvement": pct
        })
    return {
        "overall_avg_wue": overall,
        "improvement_by_region": improvement_by_region,
        "regions": regions_sorted
    }


def _is_close(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    # Handle NaNs
    if a is None or b is None:
        return False
    try:
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except Exception:
        return False


def _run_student_script(workspace: Path) -> Tuple[bool, Optional[str]]:
    script = workspace / "scripts" / "analyze_trials.py"
    if not script.exists():
        return False, "missing_script"
    try:
        # Run "python scripts/analyze_trials.py" with cwd=workspace
        res = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        if res.returncode != 0:
            return False, "nonzero_returncode"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception:
        return False, "exec_error"


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "file_not_found"
    except json.JSONDecodeError:
        return None, "json_decode_error"
    except Exception:
        return None, "json_read_error"


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None, "missing_header"
            rows = [dict(row) for row in reader]
            return header, rows, None
    except FileNotFoundError:
        return None, None, "file_not_found"
    except Exception:
        return None, None, "csv_read_error"


def _extract_input_path_and_column_usage(script_path: Path) -> Tuple[bool, bool]:
    # Returns (reads_correct_input_path, uses_correct_columns_for_wue)
    try:
        text = script_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False, False

    reads_correct_input_path = False
    uses_correct_columns = False

    # Check for literal input/farm_trials.csv anywhere
    if "input/farm_trials.csv" in text:
        reads_correct_input_path = True
    else:
        # Try to detect pd.read_csv("...") literals
        m = re.findall(r'read_csv\(\s*[ru]?["\']([^"\']+)["\']', text)
        if any(p.strip() == "input/farm_trials.csv" for p in m):
            reads_correct_input_path = True
        # Try to detect INPUT_PATH assignment
        m2 = re.findall(r'INPUT_PATH\s*=\s*[ru]?["\']([^"\']+)["\']', text)
        if any(p.strip() == "input/farm_trials.csv" for p in m2):
            reads_correct_input_path = True

    # Check usage of correct columns in WUE computation
    # Look for yield_kg_per_ha and water_used_mm being referenced
    if ("yield_kg_per_ha" in text) and ("water_used_mm" in text):
        uses_correct_columns = True

    return reads_correct_input_path, uses_correct_columns


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_runs_successfully": 0.0,
        "summary_json_exists_and_valid": 0.0,
        "overall_avg_wue_correct": 0.0,
        "improvement_by_region_count_and_regions_correct": 0.0,
        "baseline_and_improved_values_correct": 0.0,
        "percent_improvement_values_correct": 0.0,
        "recommendations_csv_exists_and_valid_header": 0.0,
        "recommendations_rows_count_correct": 0.0,
        "recommendations_values_correct": 0.0,
        "script_reads_correct_input_path": 0.0,
        "script_uses_correct_columns_for_wue": 0.0,
    }

    # Attempt to run student script
    ran, _ = _run_student_script(workspace)
    if ran:
        scores["script_runs_successfully"] = 1.0

    # Compute expected metrics from input/farm_trials.csv
    input_csv = workspace / "input" / "farm_trials.csv"
    rows, err = _safe_read_csv_dicts(input_csv)
    expected = None
    if rows is not None:
        expected = _compute_expected_metrics(rows)

    # Load and validate summary.json
    summary_path = workspace / "output" / "summary.json"
    summary_json, summary_err = _load_json(summary_path)
    if summary_json is not None and isinstance(summary_json, dict):
        # Validate basic structure
        has_overall = "overall_avg_wue" in summary_json
        has_regions = "improvement_by_region" in summary_json and isinstance(summary_json["improvement_by_region"], list)
        if has_overall and has_regions:
            scores["summary_json_exists_and_valid"] = 1.0

    # Check overall average
    if expected is not None and summary_json is not None and isinstance(summary_json, dict):
        overall = summary_json.get("overall_avg_wue", None)
        if isinstance(overall, (int, float)) and _is_close(overall, expected["overall_avg_wue"]):
            scores["overall_avg_wue_correct"] = 1.0

    # Check improvement_by_region details
    if expected is not None and summary_json is not None and isinstance(summary_json, dict):
        regions_expected = expected["regions"]
        improvements = summary_json.get("improvement_by_region", None)
        if isinstance(improvements, list):
            # Build dict by region
            actual_map = {}
            valid_entries = True
            for entry in improvements:
                if not isinstance(entry, dict):
                    valid_entries = False
                    break
                region = entry.get("region", None)
                baseline = entry.get("baseline", None)
                improved = entry.get("improved", None)
                pct = entry.get("percent_improvement", None)
                # ensure types for numbers
                if region is None or not isinstance(region, str):
                    valid_entries = False
                    break
                if not (isinstance(baseline, (int, float, type(None))) and isinstance(improved, (int, float, type(None))) and isinstance(pct, (int, float, type(None)))):
                    valid_entries = False
                    break
                actual_map[region] = {"baseline": baseline, "improved": improved, "percent_improvement": pct}
            if valid_entries:
                # Count and region set
                if set(actual_map.keys()) == set(regions_expected) and len(actual_map) == len(regions_expected):
                    scores["improvement_by_region_count_and_regions_correct"] = 1.0

                # Compare baseline/improved and percent
                baseline_ok = True
                pct_ok = True
                for exp in expected["improvement_by_region"]:
                    reg = exp["region"]
                    act = actual_map.get(reg)
                    if act is None:
                        baseline_ok = False
                        pct_ok = False
                        break
                    exp_base = exp["baseline"]
                    exp_impr = exp["improved"]
                    exp_pct = exp["percent_improvement"]
                    # Baseline and improved must be close
                    if not (isinstance(act["baseline"], (int, float)) and isinstance(act["improved"], (int, float))):
                        baseline_ok = False
                    else:
                        if not _is_close(act["baseline"], exp_base):
                            baseline_ok = False
                        if not _is_close(act["improved"], exp_impr):
                            baseline_ok = False
                    # Percent improvement must be close; in this dataset exp_pct not None
                    if exp_pct is None:
                        # If not computable, require None in output
                        if act["percent_improvement"] is not None:
                            pct_ok = False
                    else:
                        if not isinstance(act["percent_improvement"], (int, float)) or not _is_close(act["percent_improvement"], exp_pct):
                            pct_ok = False
                if baseline_ok:
                    scores["baseline_and_improved_values_correct"] = 1.0
                if pct_ok:
                    scores["percent_improvement_values_correct"] = 1.0

    # Validate recommendations.csv
    recs_path = workspace / "output" / "recommendations.csv"
    header, rec_rows, rec_err = _read_csv_with_header(recs_path)
    if header is not None and rec_rows is not None:
        # Must match exact header
        if header == ["region", "recommended_method", "expected_wue_gain_pct"]:
            scores["recommendations_csv_exists_and_valid_header"] = 1.0

        if expected is not None:
            # Count rows
            if len(rec_rows) == len(expected["regions"]):
                scores["recommendations_rows_count_correct"] = 1.0

            # Build expected map for percent improvements
            exp_pct_map = {}
            for item in expected["improvement_by_region"]:
                pct = item["percent_improvement"]
                exp_pct_map[item["region"]] = pct

            # Validate each row's recommendation and value
            values_ok = True
            for row in rec_rows:
                reg = row.get("region", "")
                rec_method = row.get("recommended_method", "")
                pct_str = row.get("expected_wue_gain_pct", "")
                if reg not in exp_pct_map:
                    values_ok = False
                    break
                exp_pct = exp_pct_map[reg]
                try:
                    pct_val = float(pct_str)
                except Exception:
                    # If non-numeric, treat 0.0 only if exp_pct is None (not in this dataset)
                    values_ok = False
                    break
                if exp_pct is None:
                    # Should be 0 per spec
                    if not _is_close(pct_val, 0.0):
                        values_ok = False
                        break
                    # recommended method should be "conventional" if no improvement computable
                    if rec_method != "conventional":
                        values_ok = False
                        break
                else:
                    # method "mulch_drip" if pct > 0 else "conventional"
                    expected_method = "mulch_drip" if exp_pct > 0 else "conventional"
                    if rec_method != expected_method:
                        values_ok = False
                        break
                    if not _is_close(pct_val, exp_pct):
                        values_ok = False
                        break
            if values_ok:
                scores["recommendations_values_correct"] = 1.0

    # Static analysis of script for input path and column usage
    script_path = workspace / "scripts" / "analyze_trials.py"
    reads_path, uses_cols = _extract_input_path_and_column_usage(script_path)
    if reads_path:
        scores["script_reads_correct_input_path"] = 1.0
    if uses_cols:
        scores["script_uses_correct_columns_for_wue"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()