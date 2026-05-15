import csv
import json
import math
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _to_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _to_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return None


def _format_num(x: float) -> str:
    # Always format to two decimals
    return f"{x:.2f}"


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return float((s[mid - 1] + s[mid]) / 2.0)


def _compute_practice_summary(workspace: Path) -> Optional[List[Dict[str, str]]]:
    # Read input
    in_path = workspace / "input" / "practice_log.csv"
    header, rows = _read_csv(in_path)
    if header is None or rows is None:
        return None

    # Validate necessary columns
    required_cols = {"exercise", "minutes", "bpm", "errors", "take_type", "valid"}
    if not required_cols.issubset(set(header)):
        return None

    # Filter rows: valid == 1 and take_type == "practice"
    filtered = []
    for r in rows:
        v = _to_int(r.get("valid", ""))
        if v != 1:
            continue
        if r.get("take_type", "") != "practice":
            continue
        minutes = _to_float(r.get("minutes", ""))
        bpm = _to_float(r.get("bpm", ""))
        errors = _to_int(r.get("errors", ""))
        exercise = r.get("exercise", "")
        if minutes is None or bpm is None or errors is None or exercise == "":
            continue
        filtered.append({
            "exercise": exercise,
            "minutes": minutes,
            "bpm": bpm,
            "errors": errors,
        })

    # Group by exercise
    groups: Dict[str, Dict[str, float]] = {}
    bpm_lists: Dict[str, List[float]] = {}
    counts: Dict[str, int] = {}
    for row in filtered:
        ex = row["exercise"]
        groups.setdefault(ex, {"total_minutes": 0.0, "total_errors": 0.0, "sum_bpm": 0.0})
        bpm_lists.setdefault(ex, [])
        counts.setdefault(ex, 0)
        groups[ex]["total_minutes"] += float(row["minutes"])
        groups[ex]["total_errors"] += float(row["errors"])
        groups[ex]["sum_bpm"] += float(row["bpm"])
        bpm_lists[ex].append(float(row["bpm"]))
        counts[ex] += 1

    # Build summary rows
    results: List[Dict[str, str]] = []
    for ex, agg in groups.items():
        takes = counts.get(ex, 0)
        if takes <= 0:
            continue
        total_minutes = agg["total_minutes"]
        sum_bpm = agg["sum_bpm"]
        bpms = bpm_lists.get(ex, [])
        avg_bpm = sum_bpm / takes if takes > 0 else 0.0
        median_bpm = _median(bpms)
        max_bpm = max(bpms) if bpms else 0.0
        total_errors = agg["total_errors"]
        avg_errors_per_min = (total_errors / total_minutes) if total_minutes > 0 else 0.0

        results.append({
            "exercise": ex,
            "total_minutes": _format_num(total_minutes),
            "takes": _format_num(float(takes)),
            "avg_bpm": _format_num(avg_bpm),
            "median_bpm": _format_num(median_bpm),
            "max_bpm": _format_num(max_bpm),
            "total_errors": _format_num(total_errors),
            "avg_errors_per_min": _format_num(avg_errors_per_min),
        })

    # Sort by avg_errors_per_min desc, then exercise asc
    def sort_key(d: Dict[str, str]):
        return (-float(d["avg_errors_per_min"]), d["exercise"])

    results.sort(key=sort_key)
    return results


def _compute_song_timing_summary(workspace: Path) -> Optional[List[Dict[str, str]]]:
    cat_path = workspace / "input" / "songs_catalog.csv"
    meas_path = workspace / "input" / "song_bpm_measurements.csv"
    cat_header, cat_rows = _read_csv(cat_path)
    meas_header, meas_rows = _read_csv(meas_path)
    if cat_header is None or cat_rows is None or meas_header is None or meas_rows is None:
        return None

    # Validate columns
    if not {"song", "target_bpm"}.issubset(set(cat_header)):
        return None
    if not {"song", "take_id", "bar", "bpm", "valid"}.issubset(set(meas_header)):
        return None

    # Build catalog map
    catalog: Dict[str, float] = {}
    for r in cat_rows:
        song = r.get("song", "")
        target_bpm = _to_float(r.get("target_bpm", ""))
        if song == "" or target_bpm is None:
            continue
        catalog[song] = target_bpm

    # Filter measurements: valid == 1 and song in catalog
    by_song_bpms: Dict[str, List[float]] = {}
    by_song_takes: Dict[str, set] = {}
    for r in meas_rows:
        v = _to_int(r.get("valid", ""))
        if v != 1:
            continue
        song = r.get("song", "")
        if song not in catalog:
            continue
        bpm = _to_float(r.get("bpm", ""))
        take_id = r.get("take_id", "")
        if bpm is None or take_id == "":
            continue
        by_song_bpms.setdefault(song, []).append(float(bpm))
        by_song_takes.setdefault(song, set()).add(take_id)

    # Build summary
    results: List[Dict[str, str]] = []
    for song, bpms in by_song_bpms.items():
        N = len(bpms)
        if N <= 0:
            continue
        mean_bpm = sum(bpms) / N
        # population standard deviation
        variance = sum((x - mean_bpm) ** 2 for x in bpms) / N
        std_bpm = math.sqrt(variance)
        target_bpm = catalog[song]
        mean_abs_dev = sum(abs(x - target_bpm) for x in bpms) / N
        timing_risk = std_bpm + mean_abs_dev
        bars_count = N
        takes_count = len(by_song_takes.get(song, set()))
        results.append({
            "song": song,
            "target_bpm": _format_num(target_bpm),
            "mean_bpm": _format_num(mean_bpm),
            "std_bpm": _format_num(std_bpm),
            "mean_abs_deviation": _format_num(mean_abs_dev),
            "timing_risk_score": _format_num(timing_risk),
            "bars_count": _format_num(float(bars_count)),
            "takes_count": _format_num(float(takes_count)),
        })

    # Sort by timing_risk_score desc; tie by song asc
    def sort_key(d: Dict[str, str]):
        return (-float(d["timing_risk_score"]), d["song"])

    results.sort(key=sort_key)
    return results


def _compute_focus_shortlists(
    practice_summary: Optional[List[Dict[str, str]]],
    song_timing_summary: Optional[List[Dict[str, str]]],
) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]]]:
    top_exercises = None
    if practice_summary is not None:
        # Already sorted by avg_errors_per_min desc then exercise asc
        top_exercises = []
        for row in practice_summary[:3]:
            top_exercises.append({
                "exercise": row["exercise"],
                "avg_errors_per_min": row["avg_errors_per_min"],
                "total_minutes": row["total_minutes"],
            })

    top_songs = None
    if song_timing_summary is not None:
        # Already sorted by timing_risk_score desc then song asc
        top_songs = []
        for row in song_timing_summary[:3]:
            top_songs.append({
                "song": row["song"],
                "timing_risk_score": row["timing_risk_score"],
                "std_bpm": row["std_bpm"],
                "mean_abs_deviation": row["mean_abs_deviation"],
            })

    return top_exercises, top_songs


def _read_output_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    # Returns (header, rows as list of list of strings in header order)
    header, rows = _read_csv(path)
    if header is None or rows is None:
        return None, None
    ordered_rows: List[List[str]] = []
    for r in rows:
        ordered_rows.append([r.get(col, "") for col in header])
    return header, ordered_rows


def _rows_from_dicts(dict_rows: List[Dict[str, str]], columns: List[str]) -> List[List[str]]:
    out = []
    for d in dict_rows:
        out.append([d.get(c, "") for c in columns])
    return out


def _compare_rows(expected: List[List[str]], actual: List[List[str]]) -> bool:
    if len(expected) != len(actual):
        return False
    for e_row, a_row in zip(expected, actual):
        if len(e_row) != len(a_row):
            return False
        for ev, av in zip(e_row, a_row):
            if ev != av:
                return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "practice_summary_structure": 0.0,
        "practice_summary_content": 0.0,
        "song_timing_summary_structure": 0.0,
        "song_timing_summary_content": 0.0,
        "top_exercises_structure": 0.0,
        "top_exercises_content": 0.0,
        "top_songs_structure": 0.0,
        "top_songs_content": 0.0,
        "analyze_script_present": 0.0,
        "analyze_script_cli_flags": 0.0,
    }

    # Expected columns
    practice_cols = [
        "exercise", "total_minutes", "takes", "avg_bpm", "median_bpm", "max_bpm", "total_errors", "avg_errors_per_min"
    ]
    song_cols = [
        "song", "target_bpm", "mean_bpm", "std_bpm", "mean_abs_deviation", "timing_risk_score", "bars_count", "takes_count"
    ]
    top_ex_cols = ["exercise", "avg_errors_per_min", "total_minutes"]
    top_song_cols = ["song", "timing_risk_score", "std_bpm", "mean_abs_deviation"]

    # Compute expected from inputs
    expected_practice = _compute_practice_summary(workspace)
    expected_song = _compute_song_timing_summary(workspace)
    expected_top_ex, expected_top_song = _compute_focus_shortlists(expected_practice, expected_song)

    # Paths to outputs
    practice_out = workspace / "output" / "practice_summary.csv"
    song_out = workspace / "output" / "song_timing_summary.csv"
    top_ex_out = workspace / "output" / "top_exercises_by_errors.csv"
    top_song_out = workspace / "output" / "top_songs_by_timing_risk.csv"

    # Check practice_summary.csv
    p_header, p_rows = _read_output_csv(practice_out)
    if p_header is not None and p_rows is not None and p_header == practice_cols:
        scores["practice_summary_structure"] = 1.0
        if expected_practice is not None:
            expected_rows = _rows_from_dicts(expected_practice, practice_cols)
            if _compare_rows(expected_rows, p_rows):
                scores["practice_summary_content"] = 1.0

    # Check song_timing_summary.csv
    s_header, s_rows = _read_output_csv(song_out)
    if s_header is not None and s_rows is not None and s_header == song_cols:
        scores["song_timing_summary_structure"] = 1.0
        if expected_song is not None:
            expected_rows = _rows_from_dicts(expected_song, song_cols)
            if _compare_rows(expected_rows, s_rows):
                scores["song_timing_summary_content"] = 1.0

    # Check top_exercises_by_errors.csv
    te_header, te_rows = _read_output_csv(top_ex_out)
    if te_header is not None and te_rows is not None and te_header == top_ex_cols:
        scores["top_exercises_structure"] = 1.0
        if expected_top_ex is not None:
            expected_rows = _rows_from_dicts(expected_top_ex, top_ex_cols)
            if _compare_rows(expected_rows, te_rows):
                scores["top_exercises_content"] = 1.0

    # Check top_songs_by_timing_risk.csv
    ts_header, ts_rows = _read_output_csv(top_song_out)
    if ts_header is not None and ts_rows is not None and ts_header == top_song_cols:
        scores["top_songs_structure"] = 1.0
        if expected_top_song is not None:
            expected_rows = _rows_from_dicts(expected_top_song, top_song_cols)
            if _compare_rows(expected_rows, ts_rows):
                scores["top_songs_content"] = 1.0

    # Check analyze_practice.py existence and CLI flags
    script_path = workspace / "analyze_practice.py"
    if script_path.exists() and script_path.is_file():
        scores["analyze_script_present"] = 1.0
        try:
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            required_flags = ["--practice", "--catalog", "--measurements", "--outdir"]
            if all(flag in content for flag in required_flags):
                scores["analyze_script_cli_flags"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()