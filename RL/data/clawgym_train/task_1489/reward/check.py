import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                # Skip completely empty rows
                if row is None:
                    continue
                if all(v is None or str(v).strip() == "" for v in row.values()):
                    continue
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _floats_close(a: float, b: float, tol: float = 0.1) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _extract_numbers(text: str) -> List[float]:
    nums = []
    if not text:
        return nums
    for m in re.finditer(r"-?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    # Split on ., ! or ? followed by space or end
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    # Clean empties
    parts = [p.strip() for p in parts if p.strip()]
    return parts


def _read_hr_series(path: Path) -> Optional[List[Tuple[float, float]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    series = []
    for row in rows:
        ts = row.get("timestamp_sec")
        hr = row.get("heart_rate_bpm")
        if ts is None or hr is None:
            return None
        tsv = _parse_float(str(ts))
        hrv = _parse_float(str(hr))
        if tsv is None or hrv is None:
            return None
        series.append((tsv, hrv))
    if not series:
        return None
    # Sort by timestamp just in case
    series.sort(key=lambda x: x[0])
    return series


def _compute_session_metrics_from_series(series: List[Tuple[float, float]]) -> Dict[str, float]:
    # Duration
    timestamps = [t for t, _ in series]
    hrs = [hr for _, hr in series]
    duration_min = max(timestamps) - min(timestamps)
    duration_min = duration_min / 60.0 if duration_min >= 0 else 0.0

    # Mean HR - simple average of all samples
    mean_hr_simple = sum(hrs) / len(hrs)

    # Alternative mean HR - time-weighted over intervals using left sample values
    if len(series) >= 2:
        total_seconds = 0.0
        tw_sum = 0.0
        for i in range(len(series) - 1):
            dt = series[i + 1][0] - series[i][0]
            if dt < 0:
                # Non-monotonic timestamps: fallback to 0 contribution for this interval
                dt = 0.0
            tw_sum += series[i][1] * dt
            total_seconds += dt
        mean_hr_weighted = (tw_sum / total_seconds) if total_seconds > 0 else mean_hr_simple
    else:
        mean_hr_weighted = mean_hr_simple

    max_hr_bpm = max(hrs)

    # Zones using left sample over intervals
    zone_low_sec = 0.0
    zone_mod_sec = 0.0
    zone_high_sec = 0.0
    for i in range(len(series) - 1):
        hr = series[i][1]
        dt = series[i + 1][0] - series[i][0]
        if dt < 0:
            dt = 0.0
        if hr < 90:
            zone_low_sec += dt
        elif hr < 130:
            zone_mod_sec += dt
        else:
            zone_high_sec += dt

    metrics = {
        "duration_min": round(duration_min, 1),
        "mean_hr_simple": round(mean_hr_simple, 1),
        "mean_hr_weighted": round(mean_hr_weighted / 60.0 * 60.0, 1),  # keep consistent rounding
        "max_hr_bpm": round(max_hr_bpm, 1),
        "zone_low_min": round(zone_low_sec / 60.0, 1),
        "zone_moderate_min": round(zone_mod_sec / 60.0, 1),
        "zone_high_min": round(zone_high_sec / 60.0, 1),
    }
    return metrics


def _load_inputs(workspace: Path) -> Optional[Dict]:
    sessions_path = workspace / "input" / "sessions.csv"
    hr_dir = workspace / "input" / "hr_data"
    if not sessions_path.exists() or not hr_dir.exists():
        return None
    sessions_rows = _safe_read_csv_dicts(sessions_path)
    if sessions_rows is None:
        return None
    # Validate required columns
    required_cols = {"session_id", "date", "activity", "claimed_passion"}
    if not sessions_rows:
        # Empty sessions
        return {
            "sessions": [],
            "hr_files": [],
        }
    if set(sessions_rows[0].keys()) != required_cols:
        # Allow extra columns? Be strict: require exact columns as specification
        if not required_cols.issubset(set(sessions_rows[0].keys())):
            return None
    hr_files = list(hr_dir.glob("*.csv"))
    return {"sessions": sessions_rows, "hr_files": hr_files}


def _compute_expected(workspace: Path) -> Optional[Dict]:
    loaded = _load_inputs(workspace)
    if loaded is None:
        return None
    sessions_rows = loaded["sessions"]
    hr_files = loaded["hr_files"]

    session_ids = [r["session_id"] for r in sessions_rows]
    hr_basenames = [p.name for p in hr_files]
    hr_ids = [p.stem for p in hr_files]

    missing_series = sorted([sid for sid in session_ids if sid not in hr_ids])
    orphan_series = sorted([bn for bn in hr_basenames if Path(bn).stem not in session_ids])

    # Per-session metrics for those with series
    expected_metrics = {}
    for r in sessions_rows:
        sid = r["session_id"]
        if sid in hr_ids:
            hr_path = workspace / "input" / "hr_data" / f"{sid}.csv"
            series = _read_hr_series(hr_path)
            if series is None:
                continue
            metrics = _compute_session_metrics_from_series(series)
            expected_metrics[sid] = {
                "session_id": sid,
                "activity": r["activity"],
                "claimed_passion": r["claimed_passion"],
                "duration_min": metrics["duration_min"],
                "mean_hr_bpm_simple": metrics["mean_hr_simple"],
                "mean_hr_bpm_weighted": metrics["mean_hr_weighted"],
                "max_hr_bpm": metrics["max_hr_bpm"],
                "zone_low_min": metrics["zone_low_min"],
                "zone_moderate_min": metrics["zone_moderate_min"],
                "zone_high_min": metrics["zone_high_min"],
                "series_file_suffix": f"{sid}.csv",
                "series_file_rel": f"input/hr_data/{sid}.csv",
            }

    # Aggregates only from sessions with metrics
    by_activity = {}
    by_passion = {"yes": [], "no": []}
    for sid, row in expected_metrics.items():
        # we'll choose simple means as canonical expected, but record list for mean-of-means
        mean_val = row["mean_hr_bpm_simple"]
        act = row["activity"]
        by_activity.setdefault(act, []).append(mean_val)
        passion = row["claimed_passion"]
        if passion in by_passion:
            by_passion[passion].append(mean_val)

    by_activity_agg = {}
    for act, means in by_activity.items():
        if means:
            by_activity_agg[act] = {
                "count": len(means),
                "mean_of_means_hr_bpm": sum(means) / len(means),
            }

    by_passion_agg = {}
    for k in ["yes", "no"]:
        vals = by_passion.get(k, [])
        if vals:
            by_passion_agg[k] = {
                "count": len(vals),
                "mean_of_means_hr_bpm": sum(vals) / len(vals),
            }
        else:
            by_passion_agg[k] = {
                "count": 0,
                "mean_of_means_hr_bpm": None,
            }

    if by_passion_agg["yes"]["mean_of_means_hr_bpm"] is not None and by_passion_agg["no"]["mean_of_means_hr_bpm"] is not None:
        diff = by_passion_agg["yes"]["mean_of_means_hr_bpm"] - by_passion_agg["no"]["mean_of_means_hr_bpm"]
    else:
        diff = None

    verdict_expected = None
    if diff is not None:
        verdict_expected = "passion_higher" if diff > 5.0 else "no_difference_or_lower"

    expected = {
        "sessions_expected": len(sessions_rows),
        "sessions_with_series": len(expected_metrics),
        "missing_series": missing_series,
        "orphan_series": orphan_series,
        "metrics": expected_metrics,
        "aggregates": {
            "by_activity": by_activity_agg,
            "by_passion": by_passion_agg,
            "passion_minus_nonpassion_mean_hr": diff,
            "verdict": verdict_expected,
        },
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_metrics_exists_and_header": 0.0,
        "metrics_row_count_and_session_coverage": 0.0,
        "metrics_values_correct": 0.0,
        "metrics_series_file_field_valid": 0.0,
        "metrics_numeric_format_one_decimal": 0.0,
        "summary_exists_and_structure": 0.0,
        "summary_counts_and_lists_correct": 0.0,
        "summary_aggregates_correct": 0.0,
        "summary_verdict_correct": 0.0,
        "status_exists_and_length": 0.0,
        "status_reports_counts_means_verdict": 0.0,
        "status_mentions_missing_and_orphan": 0.0,
    }

    expected = _compute_expected(workspace)
    output_dir = workspace / "output"
    metrics_path = output_dir / "metrics.csv"
    summary_path = output_dir / "summary.json"
    status_path = output_dir / "status.txt"

    # Gate: if inputs missing, can't meaningfully grade; keep zeros
    if expected is None:
        return scores

    # Check metrics.csv existence and header
    metrics_rows = None
    if metrics_path.exists():
        metrics_rows = _safe_read_csv_dicts(metrics_path)
    if metrics_rows is not None and len(metrics_rows) >= 0:
        expected_header = [
            "session_id",
            "activity",
            "claimed_passion",
            "duration_min",
            "mean_hr_bpm",
            "max_hr_bpm",
            "zone_low_min",
            "zone_moderate_min",
            "zone_high_min",
            "series_file",
        ]
        actual_header = list(metrics_rows[0].keys()) if metrics_rows else []
        if actual_header == expected_header:
            scores["output_metrics_exists_and_header"] = 1.0

    # metrics row coverage
    if scores["output_metrics_exists_and_header"] == 1.0:
        # Build map by session_id
        out_by_sid = {}
        duplicate_sid = False
        for row in metrics_rows:
            sid = row.get("session_id", "")
            if sid in out_by_sid:
                duplicate_sid = True
            out_by_sid[sid] = row
        expected_sids = set(expected["metrics"].keys())
        out_sids = set(out_by_sid.keys())
        if (out_sids == expected_sids) and (not duplicate_sid):
            scores["metrics_row_count_and_session_coverage"] = 1.0

        # Compare values
        total_checks = 0
        passed_checks = 0
        series_suffix_ok_count = 0
        series_suffix_total = 0
        numeric_format_total = 0
        numeric_format_ok = 0

        for sid, exp in expected["metrics"].items():
            row = out_by_sid.get(sid)
            if not row:
                continue
            # activity and claimed_passion exact match
            total_checks += 2
            if row.get("activity") == exp["activity"]:
                passed_checks += 1
            if row.get("claimed_passion") == exp["claimed_passion"]:
                passed_checks += 1

            # duration_min
            total_checks += 1
            rv = _parse_float(row.get("duration_min", ""))
            if rv is not None and _floats_close(rv, exp["duration_min"], tol=0.05):
                passed_checks += 1

            # mean_hr_bpm: accept either simple or time-weighted within tol
            total_checks += 1
            rv = _parse_float(row.get("mean_hr_bpm", ""))
            simple_ok = rv is not None and _floats_close(rv, exp["mean_hr_bpm_simple"], tol=0.1)
            weighted_ok = rv is not None and _floats_close(rv, exp["mean_hr_bpm_weighted"], tol=0.1)
            if simple_ok or weighted_ok:
                passed_checks += 1

            # max_hr_bpm
            total_checks += 1
            rv = _parse_float(row.get("max_hr_bpm", ""))
            if rv is not None and _floats_close(rv, exp["max_hr_bpm"], tol=0.05):
                passed_checks += 1

            # zones
            for col, val in [
                ("zone_low_min", exp["zone_low_min"]),
                ("zone_moderate_min", exp["zone_moderate_min"]),
                ("zone_high_min", exp["zone_high_min"]),
            ]:
                total_checks += 1
                rv = _parse_float(row.get(col, ""))
                if rv is not None and _floats_close(rv, val, tol=0.05):
                    passed_checks += 1

            # series_file suffix acceptance
            series_suffix_total += 1
            sf = row.get("series_file", "")
            if isinstance(sf, str) and sf.endswith(exp["series_file_suffix"]):
                series_suffix_ok_count += 1

            # numeric formatting: exactly one decimal place for numeric columns
            for col in ["duration_min", "mean_hr_bpm", "max_hr_bpm", "zone_low_min", "zone_moderate_min", "zone_high_min"]:
                numeric_format_total += 1
                sval = row.get(col, "")
                if isinstance(sval, str) and re.fullmatch(r"-?\d+\.\d", sval.strip()):
                    numeric_format_ok += 1

        if total_checks > 0:
            scores["metrics_values_correct"] = passed_checks / total_checks
        if series_suffix_total > 0:
            scores["metrics_series_file_field_valid"] = series_suffix_ok_count / series_suffix_total
        if numeric_format_total > 0:
            scores["metrics_numeric_format_one_decimal"] = numeric_format_ok / numeric_format_total

    # summary.json checks
    summary = None
    if summary_path.exists():
        summary = _safe_load_json(summary_path)
    if isinstance(summary, dict):
        # Structure presence
        keys_ok = all(k in summary for k in ["sessions_expected", "sessions_with_series", "missing_series", "orphan_series", "aggregates", "verdict"])
        aggr = summary.get("aggregates", {})
        aggr_ok = isinstance(aggr, dict) and "by_activity" in aggr and "by_passion" in aggr and "passion_minus_nonpassion_mean_hr" in aggr
        if keys_ok and aggr_ok:
            scores["summary_exists_and_structure"] = 1.0

        # Counts and lists
        try:
            counts_ok = (
                int(summary.get("sessions_expected", -1)) == expected["sessions_expected"] and
                int(summary.get("sessions_with_series", -1)) == expected["sessions_with_series"]
            )
            # Lists: sort and compare
            ms = summary.get("missing_series", [])
            os = summary.get("orphan_series", [])
            ms_ok = isinstance(ms, list) and sorted([str(x) for x in ms]) == expected["missing_series"]
            os_ok = isinstance(os, list) and sorted([str(x) for x in os]) == expected["orphan_series"]
            if counts_ok and ms_ok and os_ok:
                scores["summary_counts_and_lists_correct"] = 1.0
        except Exception:
            pass

        # Aggregates correctness with tolerance
        try:
            aggr = summary.get("aggregates", {})
            checks = 0
            passed = 0

            # by_activity: check expected activities present in expected
            by_act = aggr.get("by_activity", {})
            if isinstance(by_act, dict):
                for act, exp_vals in expected["aggregates"]["by_activity"].items():
                    # require presence
                    if act in by_act and isinstance(by_act[act], dict):
                        checks += 2
                        cand_count = by_act[act].get("count", None)
                        cand_mean = by_act[act].get("mean_of_means_hr_bpm", None)
                        if isinstance(cand_count, int) and cand_count == exp_vals["count"]:
                            passed += 1
                        if isinstance(cand_mean, (int, float)) and _floats_close(float(cand_mean), float(exp_vals["mean_of_means_hr_bpm"]), tol=0.5):
                            passed += 1
                    else:
                        checks += 2  # both fail

            # by_passion
            by_pas = aggr.get("by_passion", {})
            if isinstance(by_pas, dict):
                for k in ["yes", "no"]:
                    checks += 2
                    cand = by_pas.get(k, {})
                    if isinstance(cand, dict):
                        cand_count = cand.get("count", None)
                        cand_mean = cand.get("mean_of_means_hr_bpm", None)
                        exp_vals = expected["aggregates"]["by_passion"][k]
                        exp_count = exp_vals["count"]
                        exp_mean = exp_vals["mean_of_means_hr_bpm"]
                        if isinstance(cand_count, int) and cand_count == exp_count:
                            passed += 1
                        if (exp_mean is None and cand_mean is None) or (isinstance(cand_mean, (int, float)) and exp_mean is not None and _floats_close(float(cand_mean), float(exp_mean), tol=0.5)):
                            passed += 1
                    # else both fail by default

            if checks > 0:
                scores["summary_aggregates_correct"] = passed / checks

            # passion_minus_nonpassion_mean_hr and verdict
            diff_cand = aggr.get("passion_minus_nonpassion_mean_hr", None)
            verdict_cand = str(summary.get("verdict"))
            diff_exp = expected["aggregates"]["passion_minus_nonpassion_mean_hr"]
            verdict_exp = expected["aggregates"]["verdict"]
            diff_ok = (isinstance(diff_cand, (int, float)) and diff_exp is not None and _floats_close(float(diff_cand), float(diff_exp), tol=0.5))
            verdict_ok = (verdict_cand == verdict_exp)
            if diff_ok and verdict_ok:
                scores["summary_verdict_correct"] = 1.0
        except Exception:
            pass

    # status.txt checks
    status_text = None
    if status_path.exists():
        status_text = _safe_read_text(status_path)

    if isinstance(status_text, str):
        sentences = _split_sentences(status_text)
        if 3 <= len(sentences) <= 6:
            scores["status_exists_and_length"] = 1.0

        # Reports counts and means and verdict
        sub_checks = 0
        sub_pass = 0

        # Counts: sessions_expected and sessions_with_series as digits
        nums = _extract_numbers(status_text)
        # Check presence of expected counts
        sub_checks += 2
        if expected["sessions_expected"] in [int(n) for n in nums if abs(n - int(n)) < 1e-9]:
            sub_pass += 1
        if expected["sessions_with_series"] in [int(n) for n in nums if abs(n - int(n)) < 1e-9]:
            sub_pass += 1

        # Means: passion and non-passion means
        # Use expected aggregates means (simple means expected)
        pas_mean = expected["aggregates"]["by_passion"]["yes"]["mean_of_means_hr_bpm"]
        non_mean = expected["aggregates"]["by_passion"]["no"]["mean_of_means_hr_bpm"]
        if pas_mean is not None and non_mean is not None:
            sub_checks += 2
            close_to_passion = any(abs(n - pas_mean) <= 0.5 for n in nums)
            close_to_non = any(abs(n - non_mean) <= 0.5 for n in nums)
            if close_to_passion:
                sub_pass += 1
            if close_to_non:
                sub_pass += 1

        # Verdict presence
        sub_checks += 1
        verdict_exp = expected["aggregates"]["verdict"]
        if verdict_exp and verdict_exp in status_text:
            sub_pass += 1

        # Why (mention bpm): look for 'bpm' and some numeric context
        sub_checks += 1
        if re.search(r"\bbpm\b", status_text, flags=re.IGNORECASE):
            sub_pass += 1

        if sub_checks > 0:
            scores["status_reports_counts_means_verdict"] = sub_pass / sub_checks

        # Mentions missing_series and orphan_series
        miss = expected["missing_series"]
        orph = expected["orphan_series"]
        mention_ok = True
        if miss:
            for m in miss:
                if m not in status_text:
                    mention_ok = False
                    break
        if orph and mention_ok:
            for o in orph:
                if o not in status_text:
                    mention_ok = False
                    break
        if (not miss and not orph) or mention_ok:
            scores["status_mentions_missing_and_orphan"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()