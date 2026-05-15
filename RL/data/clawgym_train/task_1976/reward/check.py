import json
import csv
import sys
from pathlib import Path
from datetime import datetime
from statistics import median
from typing import List, Dict, Any, Optional, Tuple


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return float(s)
        except Exception:
            return None
    try:
        s_str = str(s).strip()
        if s_str == "" or s_str.lower() == "nan":
            return None
        return float(s_str)
    except Exception:
        return None


def _parse_int_like(s: Any) -> Optional[int]:
    val = _parse_float(s)
    if val is None:
        return None
    try:
        return int(round(val))
    except Exception:
        return None


def _almost_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    profiles_path = workspace / "input" / "horse_profiles.csv"
    rides_path = workspace / "input" / "ride_log.csv"

    profiles_rows = _read_csv_rows(profiles_path)
    rides_rows = _read_csv_rows(rides_path)
    if profiles_rows is None or rides_rows is None:
        return None

    # Build horse profiles map
    profiles = {}
    for row in profiles_rows:
        horse_id = row.get("horse_id", "").strip()
        name = row.get("name", "").strip()
        af = _parse_date(row.get("active_from", ""))
        at_raw = row.get("active_to", "")
        at = _parse_date(at_raw) if at_raw and at_raw.strip() != "" else None
        if not horse_id or af is None:
            continue
        profiles[horse_id] = {
            "name": name,
            "active_from": af,
            "active_to": at,
        }

    rides_total = 0
    included: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    anomalies_unrealistic: List[Dict[str, Any]] = []
    anomalies_hr: List[Dict[str, Any]] = []

    for row in rides_rows:
        rides_total += 1
        ride_id = row.get("ride_id", "").strip()
        date = _parse_date(row.get("date", ""))
        horse_id = row.get("horse_id", "").strip()
        dist = _parse_float(row.get("distance_km"))
        dur = _parse_float(row.get("duration_min"))
        gait = (row.get("gait_dominant") or "").strip()
        hr = _parse_float(row.get("heart_rate_avg"))

        # Determine inclusion/exclusion
        reason = None
        # invalid distance/duration
        if dist is None or dur is None or dist <= 0 or dur <= 0:
            reason = "invalid_duration_or_distance"
        else:
            prof = profiles.get(horse_id)
            if prof is None or date is None:
                reason = "outside_active_period"
            else:
                af = prof["active_from"]
                at = prof["active_to"]
                if date < af or (at is not None and date > at):
                    reason = "outside_active_period"

        if reason is not None:
            excluded.append({"ride_id": ride_id, "reason": reason})
            continue

        # Included ride
        speed = dist / (dur / 60.0)
        included.append({
            "ride_id": ride_id,
            "date": date,
            "month": date.strftime("%Y-%m"),
            "horse_id": horse_id,
            "distance_km": dist,
            "duration_min": dur,
            "gait_dominant": gait,
            "heart_rate_avg": hr,
            "speed_kmh": speed,
        })

        # Anomalies among included rides
        if speed > 40.0:
            anomalies_unrealistic.append({"ride_id": ride_id, "speed_kmh": speed})
        if hr is not None and (hr < 60.0 or hr > 220.0):
            anomalies_hr.append({"ride_id": ride_id, "heart_rate": hr})

    # Aggregate monthly per horse
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in included:
        key = (r["horse_id"], r["month"])
        groups.setdefault(key, []).append(r)

    summary_rows: List[Dict[str, Any]] = []
    for (horse_id, month), rides in groups.items():
        sessions = len(rides)
        total_dist = sum(r["distance_km"] for r in rides)
        total_dur = sum(r["duration_min"] for r in rides)
        avg_speed = sum(r["speed_kmh"] for r in rides) / sessions if sessions > 0 else None
        median_dist = median([r["distance_km"] for r in rides]) if sessions > 0 else None
        # dominant gait: most frequent; tie -> alphabetically first
        gait_counts: Dict[str, int] = {}
        for r in rides:
            g = r.get("gait_dominant", "")
            gait_counts[g] = gait_counts.get(g, 0) + 1
        max_count = max(gait_counts.values()) if gait_counts else 0
        candidates = sorted([g for g, c in gait_counts.items() if c == max_count])
        dominant_gait = candidates[0] if candidates else ""
        # avg heart rate ignoring blanks
        hr_vals = [r["heart_rate_avg"] for r in rides if r["heart_rate_avg"] is not None]
        avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None
        horse_name = profiles.get(horse_id, {}).get("name", "")

        summary_rows.append({
            "horse_id": horse_id,
            "horse_name": horse_name,
            "month": month,
            "sessions": sessions,
            "total_distance_km": total_dist,
            "total_duration_min": total_dur,
            "avg_speed_kmh": avg_speed,
            "median_distance_km": median_dist,
            "dominant_gait": dominant_gait,
            "avg_heart_rate": avg_hr,
        })

    expected = {
        "summary_rows": summary_rows,
        "quality_report": {
            "counts": {
                "rides_total": rides_total,
                "rides_included": len(included),
                "rides_excluded": len(excluded),
            },
            "excluded_rides": excluded,
            "anomalies": {
                "unrealistic_speed": anomalies_unrealistic,
                "heart_rate_out_of_range": anomalies_hr,
            }
        }
    }
    return expected


def _load_summary_output(workspace: Path) -> Optional[Dict[str, Any]]:
    summary_path = workspace / "output" / "horse_monthly_summary.csv"
    rows = _read_csv_rows(summary_path)
    if rows is None:
        return None
    header_ok = False
    try:
        with summary_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            expected_header = [
                "horse_id",
                "horse_name",
                "month",
                "sessions",
                "total_distance_km",
                "total_duration_min",
                "avg_speed_kmh",
                "median_distance_km",
                "dominant_gait",
                "avg_heart_rate",
            ]
            header_ok = header == expected_header
    except Exception:
        header_ok = False
    return {
        "rows": rows,
        "header_ok": header_ok,
    }


def _compare_summary_content(expected_rows: List[Dict[str, Any]], actual_rows: List[Dict[str, str]]) -> bool:
    # Build expected map
    exp_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in expected_rows:
        key = (r["horse_id"], r["month"])
        exp_map[key] = r

    # Build actual map
    act_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in actual_rows:
        horse_id = (r.get("horse_id") or "").strip()
        month = (r.get("month") or "").strip()
        if not horse_id or not month:
            return False
        act_map[(horse_id, month)] = r

    # Keys must match exactly
    if set(exp_map.keys()) != set(act_map.keys()):
        return False

    # Compare each row
    for key in exp_map:
        exp = exp_map[key]
        act = act_map[key]

        # horse_name
        if (act.get("horse_name") or "").strip() != (exp.get("horse_name") or "").strip():
            return False

        # sessions
        act_sessions = _parse_int_like(act.get("sessions"))
        if act_sessions is None or act_sessions != int(exp["sessions"]):
            return False

        # total_distance_km
        act_total_dist = _parse_float(act.get("total_distance_km"))
        if not _almost_equal(act_total_dist, float(exp["total_distance_km"])):
            return False

        # total_duration_min
        act_total_dur = _parse_float(act.get("total_duration_min"))
        if not _almost_equal(act_total_dur, float(exp["total_duration_min"])):
            return False

        # avg_speed_kmh
        act_avg_speed = _parse_float(act.get("avg_speed_kmh"))
        if not _almost_equal(act_avg_speed, float(exp["avg_speed_kmh"])):
            return False

        # median_distance_km
        act_median_dist = _parse_float(act.get("median_distance_km"))
        if not _almost_equal(act_median_dist, float(exp["median_distance_km"])):
            return False

        # dominant_gait
        if (act.get("dominant_gait") or "").strip() != (exp.get("dominant_gait") or "").strip():
            return False

        # avg_heart_rate
        exp_hr = exp.get("avg_heart_rate")
        act_hr_raw = act.get("avg_heart_rate")
        act_hr = _parse_float(act_hr_raw)
        if exp_hr is None:
            # Accept blank or missing
            if act_hr_raw is None or str(act_hr_raw).strip() == "":
                pass
            else:
                return False
        else:
            if not _almost_equal(act_hr, float(exp_hr)):
                return False

    return True


def _load_quality_output(workspace: Path) -> Optional[Dict[str, Any]]:
    quality_path = workspace / "output" / "quality_report.json"
    obj = _load_json(quality_path)
    return obj


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "output_summary_exists": 0.0,
        "summary_columns_ok": 0.0,
        "summary_content_correct": 0.0,
        "output_quality_exists": 0.0,
        "quality_structure_ok": 0.0,
        "quality_counts_correct": 0.0,
        "quality_exclusions_correct": 0.0,
        "quality_anomalies_correct": 0.0,
    }

    # Check script existence (specific deliverable path)
    script_path = workspace / "scripts" / "analyze_rides.py"
    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0

    # Compute expected results from inputs
    expected = _compute_expected(workspace)

    # Load and check summary CSV
    summary_info = _load_summary_output(workspace)
    if summary_info is not None:
        scores["output_summary_exists"] = 1.0
        if summary_info.get("header_ok"):
            scores["summary_columns_ok"] = 1.0
        # Content check only if we could compute expected and header is present
        if expected is not None and isinstance(summary_info.get("rows"), list):
            try:
                if _compare_summary_content(expected["summary_rows"], summary_info["rows"]):
                    scores["summary_content_correct"] = 1.0
            except Exception:
                scores["summary_content_correct"] = 0.0

    # Load and check quality report
    quality_obj = _load_quality_output(workspace)
    if quality_obj is not None:
        scores["output_quality_exists"] = 1.0
        # Structure check
        try:
            has_counts = isinstance(quality_obj.get("counts"), dict)
            has_excluded = isinstance(quality_obj.get("excluded_rides"), list)
            anomalies = quality_obj.get("anomalies")
            has_anomalies = isinstance(anomalies, dict) and isinstance(anomalies.get("unrealistic_speed"), list) and isinstance(anomalies.get("heart_rate_out_of_range"), list)
            if has_counts and has_excluded and has_anomalies:
                counts = quality_obj.get("counts", {})
                if all(k in counts for k in ("rides_total", "rides_included", "rides_excluded")):
                    scores["quality_structure_ok"] = 1.0
        except Exception:
            scores["quality_structure_ok"] = 0.0

        # Content checks only if expected computed
        if expected is not None:
            # Counts
            try:
                exp_counts = expected["quality_report"]["counts"]
                act_counts = quality_obj.get("counts", {})
                if (
                    isinstance(act_counts.get("rides_total"), int)
                    and isinstance(act_counts.get("rides_included"), int)
                    and isinstance(act_counts.get("rides_excluded"), int)
                    and act_counts.get("rides_total") == exp_counts.get("rides_total")
                    and act_counts.get("rides_included") == exp_counts.get("rides_included")
                    and act_counts.get("rides_excluded") == exp_counts.get("rides_excluded")
                ):
                    scores["quality_counts_correct"] = 1.0
            except Exception:
                scores["quality_counts_correct"] = 0.0

            # Excluded rides
            try:
                exp_excluded = expected["quality_report"]["excluded_rides"]
                act_excluded = quality_obj.get("excluded_rides", [])
                exp_set = {(e.get("ride_id"), e.get("reason")) for e in exp_excluded}
                act_set = {(e.get("ride_id"), e.get("reason")) for e in act_excluded}
                if exp_set == act_set:
                    scores["quality_exclusions_correct"] = 1.0
            except Exception:
                scores["quality_exclusions_correct"] = 0.0

            # Anomalies
            try:
                exp_anom_unreal = {e["ride_id"]: float(e["speed_kmh"]) for e in expected["quality_report"]["anomalies"]["unrealistic_speed"]}
                exp_anom_hr = {e["ride_id"]: float(e["heart_rate"]) for e in expected["quality_report"]["anomalies"]["heart_rate_out_of_range"]}
                act_anom_unreal_list = quality_obj.get("anomalies", {}).get("unrealistic_speed", [])
                act_anom_hr_list = quality_obj.get("anomalies", {}).get("heart_rate_out_of_range", [])
                act_anom_unreal = {e.get("ride_id"): _parse_float(e.get("speed_kmh")) for e in act_anom_unreal_list}
                act_anom_hr = {e.get("ride_id"): _parse_float(e.get("heart_rate")) for e in act_anom_hr_list}
                unreal_ids_match = set(exp_anom_unreal.keys()) == set(act_anom_unreal.keys())
                hr_ids_match = set(exp_anom_hr.keys()) == set(act_anom_hr.keys())
                unreal_vals_match = unreal_ids_match and all(_almost_equal(exp_anom_unreal[rid], act_anom_unreal.get(rid)) for rid in exp_anom_unreal.keys())
                hr_vals_match = hr_ids_match and all(_almost_equal(exp_anom_hr[rid], act_anom_hr.get(rid)) for rid in exp_anom_hr.keys())
                if unreal_ids_match and hr_ids_match and unreal_vals_match and hr_vals_match:
                    scores["quality_anomalies_correct"] = 1.0
            except Exception:
                scores["quality_anomalies_correct"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()