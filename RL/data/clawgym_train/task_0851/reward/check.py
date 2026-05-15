import sys
import json
import csv
import math
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple


def _read_csv_rows(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return True, rows
    except Exception:
        return False, []


def _discover_run_csv_files(workspace: Path) -> List[Path]:
    runs_dir = workspace / "input" / "test_runs"
    if not runs_dir.exists():
        return []
    return sorted([p for p in runs_dir.glob("run_*.csv") if p.is_file()])


def _safe_float(x: Any) -> float:
    try:
        if x is None:
            return float("nan")
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def _safe_int(x: Any) -> int:
    try:
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(round(x))
        s = str(x).strip()
        if s == "":
            return 0
        return int(float(s))
    except Exception:
        return 0


def _nearly_equal(a: float, b: float, rel_tol: float = 1e-4, abs_tol: float = 1e-6) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _ols_slope_r2(x_vals: List[float], y_vals: List[float]) -> Tuple[float, float, float]:
    # Returns slope, intercept, r2
    n = len(x_vals)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n
    sxx = sum((x - mean_x) ** 2 for x in x_vals)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals))
    if sxx == 0.0:
        slope = 0.0
        intercept = mean_y
        sst = sum((y - mean_y) ** 2 for y in y_vals)
        r2 = 1.0 if sst == 0.0 else 0.0
        return slope, intercept, r2
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    y_hat = [slope * x + intercept for x in x_vals]
    sse = sum((y - yh) ** 2 for y, yh in zip(y_vals, y_hat))
    sst = sum((y - mean_y) ** 2 for y in y_vals)
    if sst == 0.0:
        r2 = 1.0 if sse == 0.0 else 0.0
    else:
        r2 = 1.0 - (sse / sst)
    return slope, intercept, r2


def _compute_expected_trends_and_flags(workspace: Path) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    input_files = _discover_run_csv_files(workspace)
    all_rows: List[Dict[str, Any]] = []
    for f in input_files:
        ok, rows = _read_csv_rows(f)
        if not ok:
            continue
        for r in rows:
            try:
                all_rows.append({
                    "date": r.get("date", ""),
                    "cycle_k": _safe_float(r.get("cycle_k")),
                    "joint_id": r.get("joint_id", ""),
                    "peak_torque_nm": _safe_float(r.get("peak_torque_nm")),
                    "backlash_deg": _safe_float(r.get("backlash_deg")),
                    "temperature_c": _safe_float(r.get("temperature_c")),
                })
            except Exception:
                continue

    by_joint: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        jid = r.get("joint_id", "")
        if jid not in by_joint:
            by_joint[jid] = []
        by_joint[jid].append(r)

    trends: Dict[str, Dict[str, Any]] = {}
    for jid, rows in by_joint.items():
        clean_rows = [r for r in rows if not math.isnan(r["cycle_k"]) and not math.isnan(r["peak_torque_nm"]) and not math.isnan(r["backlash_deg"])]
        if len(clean_rows) < 3:
            continue
        clean_rows.sort(key=lambda x: x["cycle_k"])
        x_vals = [r["cycle_k"] for r in clean_rows]
        torque_vals = [r["peak_torque_nm"] for r in clean_rows]
        backlash_vals = [r["backlash_deg"] for r in clean_rows]

        t_slope, t_intercept, t_r2 = _ols_slope_r2(x_vals, torque_vals)
        b_slope, b_intercept, b_r2 = _ols_slope_r2(x_vals, backlash_vals)

        cycle_k_min = x_vals[0]
        cycle_k_max = x_vals[-1]
        torque_start = torque_vals[0]
        torque_end = torque_vals[-1]
        torque_delta = torque_end - torque_start

        backlash_start = backlash_vals[0]
        backlash_end = backlash_vals[-1]
        backlash_delta = backlash_end - backlash_start

        trends[jid] = {
            "joint_id": jid,
            "n_points": len(clean_rows),
            "cycle_k_min": cycle_k_min,
            "cycle_k_max": cycle_k_max,
            "torque_slope_nm_per_1k": t_slope,
            "torque_r2": t_r2,
            "torque_start_nm": torque_start,
            "torque_end_nm": torque_end,
            "torque_delta_nm": torque_delta,
            "backlash_slope_deg_per_1k": b_slope,
            "backlash_r2": b_r2,
            "backlash_start_deg": backlash_start,
            "backlash_end_deg": backlash_end,
            "backlash_delta_deg": backlash_delta,
        }

    flags: List[Dict[str, Any]] = []
    for jid, m in trends.items():
        if (m["torque_slope_nm_per_1k"] >= 0.0009) and (m["torque_r2"] >= 0.9):
            flags.append({
                "joint_id": jid,
                "metric": "peak_torque_nm",
                "direction": "increasing",
                "slope_per_1k": m["torque_slope_nm_per_1k"],
                "r2": m["torque_r2"],
                "start_value": m["torque_start_nm"],
                "end_value": m["torque_end_nm"],
                "n_points": m["n_points"],
                "run_span": f"{_safe_int(m['cycle_k_min'])}-{_safe_int(m['cycle_k_max'])}k",
            })
        b_slope = m["backlash_slope_deg_per_1k"]
        if (abs(b_slope) >= 0.00012) and (m["backlash_r2"] >= 0.8):
            direction = "increasing" if b_slope > 0 else "decreasing"
            flags.append({
                "joint_id": jid,
                "metric": "backlash_deg",
                "direction": direction,
                "slope_per_1k": m["backlash_slope_deg_per_1k"],
                "r2": m["backlash_r2"],
                "start_value": m["backlash_start_deg"],
                "end_value": m["backlash_end_deg"],
                "n_points": m["n_points"],
                "run_span": f"{_safe_int(m['cycle_k_min'])}-{_safe_int(m['cycle_k_max'])}k",
            })
    return trends, flags


def _load_student_trends(path: Path) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    ok, rows = _read_csv_rows(path)
    if not ok:
        return False, [], []
    header = []
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        if rows:
            header = list(rows[0].keys())
        else:
            header = []
    return True, header, rows


def _parse_trends_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    parsed: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        jid = r.get("joint_id", "")
        if not jid:
            continue
        parsed[jid] = {
            "joint_id": jid,
            "n_points": _safe_int(r.get("n_points")),
            "cycle_k_min": _safe_float(r.get("cycle_k_min")),
            "cycle_k_max": _safe_float(r.get("cycle_k_max")),
            "torque_slope_nm_per_1k": _safe_float(r.get("torque_slope_nm_per_1k")),
            "torque_r2": _safe_float(r.get("torque_r2")),
            "torque_start_nm": _safe_float(r.get("torque_start_nm")),
            "torque_end_nm": _safe_float(r.get("torque_end_nm")),
            "torque_delta_nm": _safe_float(r.get("torque_delta_nm")),
            "backlash_slope_deg_per_1k": _safe_float(r.get("backlash_slope_deg_per_1k")),
            "backlash_r2": _safe_float(r.get("backlash_r2")),
            "backlash_start_deg": _safe_float(r.get("backlash_start_deg")),
            "backlash_end_deg": _safe_float(r.get("backlash_end_deg")),
            "backlash_delta_deg": _safe_float(r.get("backlash_delta_deg")),
        }
    return parsed


def _load_json_array(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None


def _normalize_flag_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "joint_id": item.get("joint_id", ""),
        "metric": item.get("metric", ""),
        "direction": item.get("direction", ""),
        "slope_per_1k": _safe_float(item.get("slope_per_1k")),
        "r2": _safe_float(item.get("r2")),
        "start_value": _safe_float(item.get("start_value")),
        "end_value": _safe_float(item.get("end_value")),
        "n_points": _safe_int(item.get("n_points")),
        "run_span": str(item.get("run_span", "")),
    }


def _extract_numbers_from_text(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?(?:\d+\.\d+|\d+\.|\.\d+|\d+)(?:[eE][-+]?\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "per_joint_trends_exists": 0.0,
        "per_joint_trends_columns_exact": 0.0,
        "per_joint_trends_row_count": 0.0,
        "per_joint_trends_values_correct": 0.0,
        "flags_json_exists": 0.0,
        "flags_json_structure_and_values": 0.0,
        "flags_match_trends_consistency": 0.0,
        "email_exists": 0.0,
        "email_subject_and_recipients": 0.0,
        "email_references_output_files": 0.0,
        "email_flags_summary": 0.0,
    }

    expected_trends, expected_flags = _compute_expected_trends_and_flags(workspace)

    trends_path = workspace / "output" / "metrics" / "per_joint_trends.csv"
    required_header = [
        "joint_id",
        "n_points",
        "cycle_k_min",
        "cycle_k_max",
        "torque_slope_nm_per_1k",
        "torque_r2",
        "torque_start_nm",
        "torque_end_nm",
        "torque_delta_nm",
        "backlash_slope_deg_per_1k",
        "backlash_r2",
        "backlash_start_deg",
        "backlash_end_deg",
        "backlash_delta_deg",
    ]
    if trends_path.exists() and trends_path.is_file():
        scores["per_joint_trends_exists"] = 1.0
        ok, header, rows = _load_student_trends(trends_path)
        if ok and header == required_header:
            scores["per_joint_trends_columns_exact"] = 1.0
        student_trends = _parse_trends_rows(rows) if ok else {}
        expected_joint_ids = set(expected_trends.keys())
        if ok and len(student_trends) == len(expected_joint_ids):
            scores["per_joint_trends_row_count"] = 1.0
        values_ok = True
        if ok:
            for jid, exp in expected_trends.items():
                stu = student_trends.get(jid)
                if not stu:
                    values_ok = False
                    break
                if stu.get("n_points") != exp.get("n_points"):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("cycle_k_min", 0.0), exp.get("cycle_k_min", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("cycle_k_max", 0.0), exp.get("cycle_k_max", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("torque_slope_nm_per_1k", 0.0), exp.get("torque_slope_nm_per_1k", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("torque_r2", 0.0), exp.get("torque_r2", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("torque_start_nm", 0.0), exp.get("torque_start_nm", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("torque_end_nm", 0.0), exp.get("torque_end_nm", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("torque_delta_nm", 0.0), exp.get("torque_delta_nm", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("backlash_slope_deg_per_1k", 0.0), exp.get("backlash_slope_deg_per_1k", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("backlash_r2", 0.0), exp.get("backlash_r2", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("backlash_start_deg", 0.0), exp.get("backlash_start_deg", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("backlash_end_deg", 0.0), exp.get("backlash_end_deg", 0.0)):
                    values_ok = False
                    break
                if not _nearly_equal(stu.get("backlash_delta_deg", 0.0), exp.get("backlash_delta_deg", 0.0)):
                    values_ok = False
                    break
        else:
            values_ok = False
        if values_ok:
            scores["per_joint_trends_values_correct"] = 1.0

    flags_path = workspace / "output" / "metrics" / "flags.json"
    if flags_path.exists() and flags_path.is_file():
        scores["flags_json_exists"] = 1.0
        ok, data = _load_json_array(flags_path)
        structure_ok = False
        values_ok = False
        no_extra = False
        if ok and isinstance(data, list):
            structure_ok = True
            student_flags = [_normalize_flag_item(item) for item in data]
            expected_norm = [_normalize_flag_item(item) for item in expected_flags]
            matched = [False] * len(expected_norm)
            for sf in student_flags:
                found_index = -1
                for idx, ef in enumerate(expected_norm):
                    if matched[idx]:
                        continue
                    if sf["joint_id"] == ef["joint_id"] and sf["metric"] == ef["metric"] and sf["direction"] == ef["direction"]:
                        slope_ok = _nearly_equal(sf["slope_per_1k"], ef["slope_per_1k"])
                        r2_ok = _nearly_equal(sf["r2"], ef["r2"])
                        start_ok = _nearly_equal(sf["start_value"], ef["start_value"])
                        end_ok = _nearly_equal(sf["end_value"], ef["end_value"])
                        npts_ok = (sf["n_points"] == ef["n_points"])
                        run_span_ok = (sf["run_span"] == ef["run_span"])
                        if slope_ok and r2_ok and start_ok and end_ok and npts_ok and run_span_ok:
                            found_index = idx
                            break
                if found_index >= 0:
                    matched[found_index] = True
            values_ok = all(matched)
            no_extra = (len(student_flags) == len(expected_norm))
        if structure_ok and values_ok:
            scores["flags_json_structure_and_values"] = 1.0
        if structure_ok and no_extra:
            scores["flags_match_trends_consistency"] = 1.0

    email_path = workspace / "output" / "drafts" / "trend_email.txt"
    if email_path.exists() and email_path.is_file():
        scores["email_exists"] = 1.0
        try:
            content = email_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        content_lower = content.lower()

        subj_present = ("Robotic joint cycling trend check" in content)
        recipients_present = ("quality@example.com" in content_lower and "tribology@example.com" in content_lower)
        if subj_present and recipients_present:
            scores["email_subject_and_recipients"] = 1.0

        has_trends_ref = "output/metrics/per_joint_trends.csv" in content
        has_flags_ref = "output/metrics/flags.json" in content
        if has_trends_ref and has_flags_ref:
            scores["email_references_output_files"] = 1.0

        bullet_lines = []
        for line in content.splitlines():
            ls = line.lstrip()
            if ls.startswith("-") or ls.startswith("*") or ls.startswith("•"):
                bullet_lines.append(ls)

        email_ok = True
        if len(expected_flags) == 0:
            if not (("no trends" in content_lower) or ("no trend" in content_lower)):
                email_ok = False
        else:
            for ef in expected_flags:
                jid = ef["joint_id"]
                metric = ef["metric"]
                direction = ef["direction"]
                slope = ef["slope_per_1k"]
                r2 = ef["r2"]
                end_val = ef["end_value"]
                matched_line = False
                for bl in bullet_lines:
                    bl_lower = bl.lower()
                    if (jid.lower() in bl_lower) and (metric.lower() in bl_lower) and (direction.lower() in bl_lower) and ("r^2" in bl_lower):
                        nums = _extract_numbers_from_text(bl)
                        def has_close(target: float) -> bool:
                            for n in nums:
                                if _nearly_equal(n, target, rel_tol=0.1, abs_tol=1e-3):
                                    return True
                            return False
                        if has_close(slope) and has_close(r2) and has_close(end_val):
                            matched_line = True
                            break
                if not matched_line:
                    email_ok = False
                    break
        if email_ok:
            scores["email_flags_summary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()