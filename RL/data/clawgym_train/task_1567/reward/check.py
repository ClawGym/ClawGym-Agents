import json
import csv
import sys
import math
from pathlib import Path
from typing import List, Dict, Any, Optional


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    rows: List[Dict[str, Any]] = []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rows.append({
                        "track_id": row.get("track_id", "").strip(),
                        "onset_sec": float(row.get("onset_sec", "nan")),
                        "pitch_midi": int(row.get("pitch_midi", "0")),
                        "velocity": float(row.get("velocity", "nan")),
                        "section": row.get("section", "").strip(),
                    })
                except Exception:
                    return None
    except Exception:
        return None
    return rows


def _safe_load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_generic(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    else:
        return (s[mid - 1] + s[mid]) / 2.0


def _std_pop(values: List[float]) -> float:
    if not values:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / len(values))


def _cv(values: List[float]) -> float:
    mu = _mean(values)
    if mu == 0.0:
        return 0.0
    return _std_pop(values) / mu


def _iois_from_onsets(onsets: List[float]) -> List[float]:
    if not onsets:
        return []
    s = sorted(onsets)
    return [s[i] - s[i - 1] for i in range(1, len(s))]


def _compute_track_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    onsets = [r["onset_sec"] for r in rows]
    total_events = len(rows)
    duration = (max(onsets) - min(onsets)) if total_events > 0 else 0.0
    events_per_minute = (total_events / duration * 60.0) if duration > 0.0 else 0.0
    iois = _iois_from_onsets(onsets)
    ioi_stats = {
        "mean": _mean(iois),
        "median": _median(iois),
        "std": _std_pop(iois),
        "min": min(iois) if iois else 0.0,
        "max": max(iois) if iois else 0.0,
        "cv": _cv(iois),
    }
    mean_velocity = _mean([r["velocity"] for r in rows]) if total_events > 0 else 0.0
    counts: Dict[str, int] = {str(pc): 0 for pc in range(12)}
    for r in rows:
        pc = r["pitch_midi"] % 12
        counts[str(pc)] += 1
    proportions: Dict[str, float] = {k: (counts[k] / total_events if total_events > 0 else 0.0) for k in counts}
    return {
        "total_events": total_events,
        "duration_sec": duration,
        "events_per_minute": events_per_minute,
        "ioi_stats": ioi_stats,
        "mean_velocity": mean_velocity,
        "pitch_class_histogram": {
            "counts": counts,
            "proportions": proportions,
        },
    }


def _compute_section_stats(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        sec = r["section"]
        by_section.setdefault(sec, []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for sec, srows in by_section.items():
        onsets = sorted([r["onset_sec"] for r in srows])
        events = len(srows)
        duration = (max(onsets) - min(onsets)) if events > 0 else 0.0
        iois = [onsets[i] - onsets[i - 1] for i in range(1, len(onsets))]
        mean_ioi = _mean(iois)
        cv_ioi = _cv(iois)
        mean_velocity = _mean([r["velocity"] for r in srows]) if events > 0 else 0.0
        out[sec] = {
            "events": events,
            "duration_sec": duration,
            "mean_ioi_sec": mean_ioi,
            "cv_ioi": cv_ioi,
            "mean_velocity": mean_velocity,
        }
    return out


def _float_close(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        fa = float(a)
        fb = float(b)
    except Exception:
        return False
    if math.isfinite(fa) and math.isfinite(fb):
        return abs(fa - fb) <= tol
    return False


def _parse_track_summary(path: Path) -> Optional[Dict[str, Any]]:
    data = _safe_load_json(path)
    if data is None or not isinstance(data, dict):
        return None
    tracks = data.get("tracks", None)
    if not isinstance(tracks, list):
        return None
    indexed: Dict[str, Any] = {}
    for t in tracks:
        if not isinstance(t, dict):
            return None
        tid = t.get("track_id")
        if tid not in ("session1", "session2"):
            continue
        indexed[tid] = t
    if not indexed:
        return None
    return indexed


def _validate_track_summary_structure(track_summary: Dict[str, Any]) -> bool:
    required_keys = {"total_events", "duration_sec", "events_per_minute", "ioi_stats", "mean_velocity", "pitch_class_histogram"}
    for tid in ("session1", "session2"):
        t = track_summary.get(tid)
        if t is None:
            return False
        if not required_keys.issubset(set(t.keys())):
            return False
        ioi = t.get("ioi_stats")
        if not isinstance(ioi, dict):
            return False
        for k in ("mean", "median", "std", "min", "max", "cv"):
            if k not in ioi:
                return False
        pch = t.get("pitch_class_histogram")
        if not isinstance(pch, dict):
            return False
        counts = pch.get("counts")
        props = pch.get("proportions")
        if not isinstance(counts, dict) or not isinstance(props, dict):
            return False
        for pc in range(12):
            k = str(pc)
            if k not in counts or k not in props:
                return False
    return True


def _parse_section_stats(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_read_csv_generic(path)
    if rows is None:
        return None
    expected_cols = ["track_id", "section", "events", "duration_sec", "mean_ioi_sec", "cv_ioi", "mean_velocity"]
    if any(col not in rows[0] for col in expected_cols) if rows else True:
        return None
    return rows


def _parse_pch_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_read_csv_generic(path)
    if rows is None:
        return None
    expected_cols = ["track_id", "pitch_class", "count", "proportion"]
    if any(col not in rows[0] for col in expected_cols) if rows else True:
        return None
    return rows


def _extract_pair_values(section_obj: Any) -> Optional[Dict[str, float]]:
    if not isinstance(section_obj, dict):
        return None
    for _, v in section_obj.items():
        if isinstance(v, dict):
            if "session1" in v and "session2" in v:
                try:
                    return {"session1": float(v["session1"]), "session2": float(v["session2"])}
                except Exception:
                    continue
    return None


def _extract_higher_track(section_obj: Any) -> Optional[str]:
    if not isinstance(section_obj, dict):
        return None
    for _, v in section_obj.items():
        if isinstance(v, str) and v in ("session1", "session2"):
            return v
    return None


def _extract_difference_value(section_obj: Any) -> Optional[float]:
    if not isinstance(section_obj, dict):
        return None
    for k, v in section_obj.items():
        if isinstance(k, str) and ("diff" in k.lower() or "difference" in k.lower()):
            try:
                return float(v)
            except Exception:
                continue
    return None


def _validate_log_contains_required_checks(log_text: str) -> bool:
    lines = [ln.strip().lower() for ln in log_text.splitlines() if ln.strip()]
    if not lines:
        return False

    def has_check(track: str, keywords: List[str]) -> bool:
        for ln in lines:
            if ("pass" in ln or "fail" in ln) and track.lower() in ln and all(kw in ln for kw in keywords):
                return True
        return False

    checks = [
        ("session1", ["total_events", "input"]),
        ("session2", ["total_events", "input"]),
        ("session1", ["section", "sum", "events"]),
        ("session2", ["section", "sum", "events"]),
        ("session1", ["pitch", "sum"]),
        ("session2", ["pitch", "sum"]),
        ("session1", ["duration", "ioi"]),
        ("session2", ["duration", "ioi"]),
    ]
    return all(has_check(track, kw) for track, kw in checks)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "track_summary_file_exists": 0.0,
        "track_summary_structure_valid": 0.0,
        "track_summary_values_session1_correct": 0.0,
        "track_summary_values_session2_correct": 0.0,
        "section_stats_file_exists": 0.0,
        "section_stats_session1_correct": 0.0,
        "section_stats_session2_correct": 0.0,
        "pitch_class_histogram_file_exists": 0.0,
        "pitch_class_histogram_session1_correct": 0.0,
        "pitch_class_histogram_session2_correct": 0.0,
        "comparison_json_file_exists": 0.0,
        "comparison_irregularity_correct": 0.0,
        "comparison_event_rate_correct": 0.0,
        "total_events_equals_sum_sections_session1": 0.0,
        "total_events_equals_sum_sections_session2": 0.0,
        "pitch_class_counts_sum_session1": 0.0,
        "pitch_class_counts_sum_session2": 0.0,
        "validation_log_exists": 0.0,
        "validation_log_contains_required_checks": 0.0,
    }

    input1 = _safe_read_csv(workspace / "input" / "transcriptions" / "bailey_session1.csv")
    input2 = _safe_read_csv(workspace / "input" / "transcriptions" / "bailey_session2.csv")

    expected: Dict[str, Any] = {}
    if input1 is not None:
        expected["session1"] = {
            "track": _compute_track_metrics(input1),
            "sections": _compute_section_stats(input1),
        }
    if input2 is not None:
        expected["session2"] = {
            "track": _compute_track_metrics(input2),
            "sections": _compute_section_stats(input2),
        }

    ts_path = workspace / "outputs" / "track_summary.json"
    track_summary = _parse_track_summary(ts_path)
    if track_summary is not None:
        scores["track_summary_file_exists"] = 1.0
        if _validate_track_summary_structure(track_summary):
            scores["track_summary_structure_valid"] = 1.0
            for tid in ("session1", "session2"):
                key = f"track_summary_values_{tid}_correct"
                if tid in expected and tid in track_summary:
                    exp = expected[tid]["track"]
                    out = track_summary[tid]
                    ok = True
                    ok = ok and (out.get("total_events") == exp["total_events"])
                    ok = ok and _float_close(out.get("duration_sec"), exp["duration_sec"])
                    ok = ok and _float_close(out.get("events_per_minute"), exp["events_per_minute"])
                    ioi_out = out.get("ioi_stats", {})
                    ioi_exp = exp["ioi_stats"]
                    for k in ("mean", "median", "std", "min", "max", "cv"):
                        ok = ok and _float_close(ioi_out.get(k), ioi_exp[k])
                    ok = ok and _float_close(out.get("mean_velocity"), exp["mean_velocity"])
                    pch_out = out.get("pitch_class_histogram", {})
                    counts_out = pch_out.get("counts", {})
                    props_out = pch_out.get("proportions", {})
                    for pc in range(12):
                        kpc = str(pc)
                        ok = ok and (counts_out.get(kpc) == exp["pitch_class_histogram"]["counts"][kpc])
                        ok = ok and _float_close(props_out.get(kpc), exp["pitch_class_histogram"]["proportions"][kpc])
                    scores[key] = 1.0 if ok else 0.0
                else:
                    scores[key] = 0.0
        else:
            scores["track_summary_structure_valid"] = 0.0
            scores["track_summary_values_session1_correct"] = 0.0
            scores["track_summary_values_session2_correct"] = 0.0
    else:
        scores["track_summary_file_exists"] = 0.0

    ss_path = workspace / "outputs" / "section_stats.csv"
    section_stats_rows = _parse_section_stats(ss_path)
    if section_stats_rows is not None:
        scores["section_stats_file_exists"] = 1.0
        by_track_section: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in section_stats_rows:
            tid = row.get("track_id", "")
            sec = row.get("section", "")
            if tid not in by_track_section:
                by_track_section[tid] = {}
            by_track_section[tid][sec] = row
        for tid in ("session1", "session2"):
            key = f"section_stats_{tid}_correct"
            if tid in expected and tid in by_track_section:
                exp_secs = expected[tid]["sections"]
                out_secs = by_track_section[tid]
                ok = all(s in out_secs for s in exp_secs.keys())
                if not ok:
                    scores[key] = 0.0
                else:
                    ok_all = True
                    for sec, exp in exp_secs.items():
                        out = out_secs[sec]
                        try:
                            out_events = int(out.get("events", "0"))
                            out_duration = float(out.get("duration_sec", "nan"))
                            out_mean_ioi = float(out.get("mean_ioi_sec", "nan"))
                            out_cv_ioi = float(out.get("cv_ioi", "nan"))
                            out_mean_vel = float(out.get("mean_velocity", "nan"))
                        except Exception:
                            ok_all = False
                            break
                        if out_events != exp["events"]:
                            ok_all = False
                            break
                        if not _float_close(out_duration, exp["duration_sec"]):
                            ok_all = False
                            break
                        if not _float_close(out_mean_ioi, exp["mean_ioi_sec"]):
                            ok_all = False
                            break
                        if not _float_close(out_cv_ioi, exp["cv_ioi"]):
                            ok_all = False
                            break
                        if not _float_close(out_mean_vel, exp["mean_velocity"]):
                            ok_all = False
                            break
                    scores[key] = 1.0 if ok_all else 0.0
            else:
                scores[key] = 0.0

        if track_summary is not None and _validate_track_summary_structure(track_summary):
            for tid in ("session1", "session2"):
                key = f"total_events_equals_sum_sections_{tid}"
                if tid in by_track_section and tid in track_summary:
                    sum_sec_events = 0
                    for sec_row in by_track_section[tid].values():
                        try:
                            sum_sec_events += int(sec_row.get("events", "0"))
                        except Exception:
                            sum_sec_events = -1
                            break
                    total_events = track_summary[tid].get("total_events", None)
                    scores[key] = 1.0 if (sum_sec_events == total_events) else 0.0
                else:
                    scores[key] = 0.0
        else:
            scores["total_events_equals_sum_sections_session1"] = 0.0
            scores["total_events_equals_sum_sections_session2"] = 0.0
    else:
        scores["section_stats_file_exists"] = 0.0

    pch_path = workspace / "outputs" / "pitch_class_histogram.csv"
    pch_rows = _parse_pch_csv(pch_path)
    if pch_rows is not None:
        scores["pitch_class_histogram_file_exists"] = 1.0
        by_track_pc: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in pch_rows:
            tid = row.get("track_id", "")
            pc = row.get("pitch_class", "")
            by_track_pc.setdefault(tid, {})[pc] = row

        for tid in ("session1", "session2"):
            key_correct = f"pitch_class_histogram_{tid}_correct"
            key_sum = f"pitch_class_counts_sum_{tid}"
            ok = True
            sum_counts = 0
            if tid in expected and tid in by_track_pc:
                exp_counts = expected[tid]["track"]["pitch_class_histogram"]["counts"]
                exp_props = expected[tid]["track"]["pitch_class_histogram"]["proportions"]
                for pc in range(12):
                    kpc = str(pc)
                    row = by_track_pc[tid].get(kpc)
                    if row is None:
                        ok = False
                        break
                    try:
                        count = int(row.get("count", "0"))
                        prop = float(row.get("proportion", "nan"))
                    except Exception:
                        ok = False
                        break
                    sum_counts += count
                    if count != exp_counts[kpc]:
                        ok = False
                        break
                    if not _float_close(prop, exp_props[kpc]):
                        ok = False
                        break
                scores[key_correct] = 1.0 if ok else 0.0
                total_events_ref = None
                if track_summary is not None and tid in track_summary:
                    total_events_ref = track_summary[tid].get("total_events")
                elif tid in expected:
                    total_events_ref = expected[tid]["track"]["total_events"]
                scores[key_sum] = 1.0 if (total_events_ref is not None and sum_counts == total_events_ref) else 0.0
            else:
                scores[key_correct] = 0.0
                scores[key_sum] = 0.0
    else:
        scores["pitch_class_histogram_file_exists"] = 0.0

    comp_path = workspace / "outputs" / "comparison.json"
    comp_data = _safe_load_json(comp_path)
    if comp_data is not None and isinstance(comp_data, dict):
        scores["comparison_json_file_exists"] = 1.0
        irregularity = comp_data.get("irregularity", None)
        event_rate = comp_data.get("event_rate", None)
        irr_ok = False
        evt_ok = False
        if irregularity is not None and "session1" in expected and "session2" in expected:
            pair = _extract_pair_values(irregularity)
            higher = _extract_higher_track(irregularity)
            diff_val = _extract_difference_value(irregularity)
            if pair is not None and higher is not None and diff_val is not None:
                cv1 = expected["session1"]["track"]["ioi_stats"]["cv"]
                cv2 = expected["session2"]["track"]["ioi_stats"]["cv"]
                expected_higher = "session1" if cv1 > cv2 else "session2" if cv2 > cv1 else None
                if expected_higher is None:
                    irr_ok = _float_close(pair["session1"], cv1) and _float_close(pair["session2"], cv2) and _float_close(diff_val, abs(cv1 - cv2))
                else:
                    irr_ok = (_float_close(pair["session1"], cv1) and
                              _float_close(pair["session2"], cv2) and
                              _float_close(diff_val, abs(cv1 - cv2)) and
                              higher == expected_higher)
        if event_rate is not None and "session1" in expected and "session2" in expected:
            pair = _extract_pair_values(event_rate)
            higher = _extract_higher_track(event_rate)
            diff_val = _extract_difference_value(event_rate)
            if pair is not None and higher is not None and diff_val is not None:
                er1 = expected["session1"]["track"]["events_per_minute"]
                er2 = expected["session2"]["track"]["events_per_minute"]
                expected_higher = "session1" if er1 > er2 else "session2" if er2 > er1 else None
                if expected_higher is None:
                    evt_ok = _float_close(pair["session1"], er1) and _float_close(pair["session2"], er2) and _float_close(diff_val, abs(er1 - er2))
                else:
                    evt_ok = (_float_close(pair["session1"], er1) and
                              _float_close(pair["session2"], er2) and
                              _float_close(diff_val, abs(er1 - er2)) and
                              higher == expected_higher)
        scores["comparison_irregularity_correct"] = 1.0 if irr_ok else 0.0
        scores["comparison_event_rate_correct"] = 1.0 if evt_ok else 0.0
    else:
        scores["comparison_json_file_exists"] = 0.0

    val_log_path = workspace / "outputs" / "validation_log.txt"
    if val_log_path.exists():
        scores["validation_log_exists"] = 1.0
        try:
            log_text = val_log_path.read_text(encoding="utf-8")
        except Exception:
            log_text = ""
        if _validate_log_contains_required_checks(log_text):
            scores["validation_log_contains_required_checks"] = 1.0
    else:
        scores["validation_log_exists"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()