import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


EXPECTED_HEADER = [
    "request_id",
    "teacher",
    "grade",
    "item",
    "total_cost",
    "cost_per_student",
    "impact_score",
    "priority_score",
]


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _load_csv_rows(p: Path) -> Optional[List[dict]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        if s is None:
            return None
        s_stripped = s.strip()
        if s_stripped == "":
            return None
        return float(s_stripped)
    except Exception:
        return None


def _almost_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _compute_expected_top5(rows: List[dict]) -> List[dict]:
    filtered: List[dict] = []
    for r in rows:
        fy = r.get("fiscal_year", "")
        status = r.get("status", "")
        if fy != "2024-2025":
            continue
        if status != "approved":
            continue
        try:
            q = float(r.get("quantity", ""))
            uc = float(r.get("unit_cost", ""))
            sc = float(r.get("student_count", ""))
            impact = float(r.get("impact_score", ""))
        except Exception:
            continue
        if not (q > 0 and uc > 0 and sc > 0):
            continue
        total_cost = q * uc
        cost_per_student = total_cost / sc
        if cost_per_student == 0:
            continue
        priority_score = impact / cost_per_student
        filtered.append(
            {
                "request_id": r.get("request_id", ""),
                "teacher": r.get("teacher", ""),
                "grade": r.get("grade", ""),
                "item": r.get("item", ""),
                "total_cost": total_cost,
                "cost_per_student": cost_per_student,
                "impact_score": impact,
                "priority_score": priority_score,
            }
        )
    filtered.sort(key=lambda x: (-x["priority_score"], x["total_cost"], x["request_id"]))
    return filtered[:5]


def _run_refactored_script(workspace: Path) -> bool:
    script = workspace / "scripts" / "rank_requests_refactored.py"
    if not script.exists():
        return False
    attempts: List[List[str]] = [
        [sys.executable, str(script)],
        [sys.executable, str(script), "data/requests.csv", "output/recommendations.csv"],
        [sys.executable, str(script), "data/requests.csv"],
    ]
    for args in attempts:
        try:
            proc = subprocess.run(
                args,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True,
            )
            if proc.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _run_baseline_and_capture(workspace: Path) -> Tuple[bool, str]:
    script = workspace / "scripts" / "rank_requests.py"
    data = workspace / "data" / "requests.csv"
    if not script.exists() or not data.exists():
        return False, ""
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(data)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            text=True,
        )
        return True, proc.stdout
    except Exception:
        return False, ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "baseline_error_file_present": 0.0,
        "baseline_error_contains_traceback": 0.0,
        "baseline_error_contains_keyerror_qty": 0.0,
        "baseline_error_matches_rerun_output": 0.0,
        "refactored_script_exists": 0.0,
        "refactored_script_runs": 0.0,
        "recommendations_file_present": 0.0,
        "recommendations_header_correct": 0.0,
        "recommendations_top5_count": 0.0,
        "recommendations_ids_in_expected_order": 0.0,
        "recommendations_numeric_fields_valid": 0.0,
        "recommendations_numeric_values_correct": 0.0,
    }

    # Baseline error file validation
    baseline_error_path = workspace / "output" / "baseline_error.txt"
    baseline_err_text = _read_text(baseline_error_path)
    if baseline_err_text is not None and baseline_err_text.strip() != "":
        scores["baseline_error_file_present"] = 1.0
        if "Traceback (most recent call last)" in baseline_err_text:
            scores["baseline_error_contains_traceback"] = 1.0
        if ("KeyError: 'qty'" in baseline_err_text) or ('KeyError: "qty"' in baseline_err_text):
            scores["baseline_error_contains_keyerror_qty"] = 1.0

        # Compare to an actual rerun of the baseline (substring check for robustness)
        ran, captured = _run_baseline_and_capture(workspace)
        if ran and captured.strip():
            norm_file = _normalize_newlines(baseline_err_text)
            norm_cap = _normalize_newlines(captured)
            if norm_cap in norm_file or norm_cap.strip() in norm_file:
                scores["baseline_error_matches_rerun_output"] = 1.0

    # Refactored script presence and execution
    refactored_path = workspace / "scripts" / "rank_requests_refactored.py"
    if refactored_path.exists():
        scores["refactored_script_exists"] = 1.0
    if _run_refactored_script(workspace):
        scores["refactored_script_runs"] = 1.0

    # Load data to compute expected results
    data_path = workspace / "data" / "requests.csv"
    expected_rows: Optional[List[dict]] = None
    rows = _load_csv_rows(data_path)
    if rows is not None:
        expected_rows = _compute_expected_top5(rows)

    # Recommendations file validation
    rec_path = workspace / "output" / "recommendations.csv"
    if rec_path.exists():
        scores["recommendations_file_present"] = 1.0
        try:
            with rec_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                all_lines = list(reader)
        except Exception:
            all_lines = None

        if all_lines:
            header = all_lines[0]
            data_lines = all_lines[1:]
            if header == EXPECTED_HEADER:
                scores["recommendations_header_correct"] = 1.0

            if len(data_lines) == 5:
                scores["recommendations_top5_count"] = 1.0

            rec_dicts: Optional[List[dict]] = []
            for row in data_lines:
                if len(row) != len(EXPECTED_HEADER):
                    rec_dicts = None
                    break
                rec_dicts.append(dict(zip(EXPECTED_HEADER, row)))

            if rec_dicts is not None and expected_rows is not None:
                expected_ids = [r["request_id"] for r in expected_rows]
                got_ids = [r.get("request_id", "") for r in rec_dicts]
                if got_ids == expected_ids:
                    scores["recommendations_ids_in_expected_order"] = 1.0

                # Numeric fields parseability
                numeric_fields = ["total_cost", "cost_per_student", "impact_score", "priority_score"]
                numeric_valid = True
                for r in rec_dicts:
                    for nf in numeric_fields:
                        if _parse_float(r.get(nf, "")) is None:
                            numeric_valid = False
                            break
                    if not numeric_valid:
                        break
                if numeric_valid:
                    scores["recommendations_numeric_fields_valid"] = 1.0

                # Validate numeric values and non-numeric fields consistency
                values_ok = True
                exp_map = {r["request_id"]: r for r in expected_rows}
                for r in rec_dicts:
                    rid = r.get("request_id", "")
                    exp = exp_map.get(rid)
                    if not exp:
                        values_ok = False
                        break
                    if r.get("teacher", "") != exp.get("teacher", ""):
                        values_ok = False
                        break
                    if r.get("grade", "") != exp.get("grade", ""):
                        values_ok = False
                        break
                    if r.get("item", "") != exp.get("item", ""):
                        values_ok = False
                        break
                    got_tc = _parse_float(r.get("total_cost", ""))
                    got_cps = _parse_float(r.get("cost_per_student", ""))
                    got_imp = _parse_float(r.get("impact_score", ""))
                    got_pri = _parse_float(r.get("priority_score", ""))
                    if not (
                        _almost_equal(got_tc, exp["total_cost"], tol=1e-2)
                        and _almost_equal(got_cps, exp["cost_per_student"], tol=1e-4)
                        and _almost_equal(got_imp, exp["impact_score"], tol=1e-6)
                        and _almost_equal(got_pri, exp["priority_score"], tol=1e-4)
                    ):
                        values_ok = False
                        break
                if values_ok:
                    scores["recommendations_numeric_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()