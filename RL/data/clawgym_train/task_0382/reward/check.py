import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows, reader.fieldnames if reader.fieldnames is not None else []
    except Exception:
        return None, None


def _load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists() or not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, bool):
            return 1 if x else 0
        if isinstance(x, (int,)):
            return int(x)
        if isinstance(x, float) and x.is_integer():
            return int(x)
        s = str(x).strip()
        if s == "":
            return None
        # Allow floats representing integers
        val = float(s)
        if val.is_integer():
            return int(val)
        return int(s)
    except Exception:
        return None


def _to_bool(x: Any) -> Optional[bool]:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(int(x))
    s = str(x).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-3) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _parse_timecode_mmss(s: str) -> Optional[int]:
    try:
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        m = int(parts[0])
        sec = int(parts[1])
        if not (0 <= sec < 60) or m < 0:
            return None
        return m * 60 + sec
    except Exception:
        return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return (vals[mid - 1] + vals[mid]) / 2.0


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    verses_path = workspace / "input" / "verse_timing.csv"
    setlist_path = workspace / "input" / "dj_setlist.csv"
    verses_rows, _ = _read_csv_dicts(verses_path)
    setlist_rows, _ = _read_csv_dicts(setlist_path)
    if verses_rows is None or setlist_rows is None:
        return None

    # Build setlist map
    setlist_by_track: Dict[str, Dict[str, Any]] = {}
    for row in setlist_rows:
        tid = row.get("track_id", "").strip()
        title = row.get("track_title", "").strip()
        bpm = _to_float(row.get("bpm"))
        if not tid or bpm is None:
            continue
        setlist_by_track[tid] = {"track_title": title, "bpm": bpm}

    # Aggregate verses per track and per session
    verses_by_track: Dict[str, List[Dict[str, Any]]] = {}
    sessions: Dict[str, List[Dict[str, Any]]] = {}

    for row in verses_rows:
        tid = row.get("track_id", "").strip()
        sdate = row.get("session_date", "").strip()
        offbeat = _to_float(row.get("offbeat_entries"))
        wpm = _to_float(row.get("words_per_minute"))
        stc = row.get("start_timecode", "")
        etc = row.get("end_timecode", "")
        start_sec = _parse_timecode_mmss(stc) if isinstance(stc, str) else None
        end_sec = _parse_timecode_mmss(etc) if isinstance(etc, str) else None
        if tid:
            verses_by_track.setdefault(tid, []).append(
                {"offbeat": offbeat, "wpm": wpm}
            )
        if sdate:
            sessions.setdefault(sdate, []).append(
                {
                    "track_id": tid,
                    "offbeat": offbeat,
                    "wpm": wpm,
                    "start": start_sec,
                    "end": end_sec,
                }
            )

    # Compute expected track_flow_stats
    expected_track_stats: Dict[str, Dict[str, Any]] = {}
    for tid, verses in verses_by_track.items():
        if tid not in setlist_by_track:
            continue
        # Filter out None values in wpm/offbeat
        wpms = [v["wpm"] for v in verses if v["wpm"] is not None]
        offbeats = [v["offbeat"] for v in verses if v["offbeat"] is not None]
        # Only consider verses with both metrics present
        count = min(len(wpms), len(offbeats))
        if count == 0:
            continue
        mean_wpm = sum(wpms[:count]) / count
        mean_offbeat = sum(offbeats[:count]) / count
        bpm = _to_float(setlist_by_track[tid]["bpm"])
        words_per_beat = mean_wpm / bpm if (bpm is not None and bpm != 0) else None
        flow_match = None
        if words_per_beat is not None and mean_offbeat is not None:
            flow_match = (1.0 <= words_per_beat <= 1.3) and (mean_offbeat <= 1.0)
        expected_track_stats[tid] = {
            "track_id": tid,
            "track_title": setlist_by_track[tid]["track_title"],
            "bpm": bpm,
            "mean_wpm": mean_wpm,
            "mean_offbeat_entries": mean_offbeat,
            "words_per_beat": words_per_beat,
            "flow_match": flow_match,
        }

    # Compute expected session_summary
    expected_sessions: Dict[str, Dict[str, Any]] = {}
    for sdate, verses in sessions.items():
        # Totals
        total_verses = len(verses)
        total_offbeat_entries = 0.0
        weighted_sum = 0.0
        total_duration = 0.0
        bpm_values_for_median: List[float] = []
        for v in verses:
            offb = _to_float(v["offbeat"])
            if offb is not None:
                total_offbeat_entries += offb
            wpm = _to_float(v["wpm"])
            start = v["start"]
            end = v["end"]
            duration = None
            if isinstance(start, int) and isinstance(end, int):
                duration = max(0, end - start)
            if wpm is not None and duration is not None:
                weighted_sum += wpm * duration
                total_duration += duration
            # BPM list for median: only if track id exists in setlist
            tid = v["track_id"]
            if tid in setlist_by_track:
                bpm = _to_float(setlist_by_track[tid]["bpm"])
                if bpm is not None:
                    bpm_values_for_median.append(bpm)
        duration_weighted_avg_wpm = None
        if total_duration > 0:
            duration_weighted_avg_wpm = weighted_sum / total_duration
        median_bpm = _median(bpm_values_for_median)
        expected_sessions[sdate] = {
            "session_date": sdate,
            "total_verses": total_verses,
            "total_offbeat_entries": total_offbeat_entries,
            "duration_weighted_avg_wpm": duration_weighted_avg_wpm,
            "median_bpm": median_bpm,
        }

    # Compute expected data quality report
    verse_track_ids = set(verses_by_track.keys())
    setlist_ids = set(setlist_by_track.keys())
    unmatched_in_setlist = sorted([tid for tid in setlist_ids if tid not in verse_track_ids])
    unmatched_in_verses = sorted([tid for tid in verse_track_ids if tid not in setlist_ids])

    return {
        "expected_track_stats": expected_track_stats,
        "expected_sessions": expected_sessions,
        "expected_unmatched_in_setlist": unmatched_in_setlist,
        "expected_unmatched_in_verses": unmatched_in_verses,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "track_flow_stats_file_presence_and_columns": 0.0,
        "track_flow_stats_content_correct": 0.0,
        "session_summary_file_presence_and_fields": 0.0,
        "session_summary_values_correct": 0.0,
        "data_quality_report_file_presence_and_fields": 0.0,
        "data_quality_report_values_correct": 0.0,
    }

    # Paths
    tfs_path = workspace / "output" / "track_flow_stats.csv"
    ss_path = workspace / "output" / "session_summary.json"
    dqr_path = workspace / "output" / "data_quality_report.json"

    # Check track_flow_stats.csv presence and columns
    tfs_rows, tfs_fields = _read_csv_dicts(tfs_path)
    required_tfs_cols = [
        "track_id",
        "track_title",
        "bpm",
        "mean_wpm",
        "mean_offbeat_entries",
        "words_per_beat",
        "flow_match",
    ]
    if tfs_rows is not None and tfs_fields is not None:
        if all(col in tfs_fields for col in required_tfs_cols):
            scores["track_flow_stats_file_presence_and_columns"] = 1.0

    # Check session_summary.json presence and fields
    ss_data = _load_json(ss_path)
    ss_fields_ok = False
    if isinstance(ss_data, list):
        # Accept empty list as structurally valid but fields will be checked in content stage
        ss_fields_ok = True
        for item in ss_data:
            if not isinstance(item, dict):
                ss_fields_ok = False
                break
            # Must contain required keys
            req = [
                "session_date",
                "total_verses",
                "total_offbeat_entries",
                "duration_weighted_avg_wpm",
                "median_bpm",
            ]
            if not all(k in item for k in req):
                ss_fields_ok = False
                break
    if ss_fields_ok:
        scores["session_summary_file_presence_and_fields"] = 1.0

    # Check data_quality_report.json presence and fields
    dqr_data = _load_json(dqr_path)
    dqr_fields_ok = False
    if isinstance(dqr_data, dict):
        if "unmatched_tracks_in_setlist" in dqr_data and "unmatched_track_ids_in_verses" in dqr_data:
            if isinstance(dqr_data.get("unmatched_tracks_in_setlist"), list) and isinstance(
                dqr_data.get("unmatched_track_ids_in_verses"), list
            ):
                dqr_fields_ok = True
    if dqr_fields_ok:
        scores["data_quality_report_file_presence_and_fields"] = 1.0

    # Compute expected values from inputs
    expected = _compute_expected_from_inputs(workspace)

    # Content correctness for track_flow_stats.csv
    if expected is not None and tfs_rows is not None:
        expected_track_stats: Dict[str, Dict[str, Any]] = expected["expected_track_stats"]
        expected_ids = set(expected_track_stats.keys())

        # Build student map and count duplicates
        student_map: Dict[str, Dict[str, Any]] = {}
        seen_ids: Dict[str, int] = {}
        for row in tfs_rows:
            tid = str(row.get("track_id", "")).strip()
            if not tid:
                continue
            student_map[tid] = row
            seen_ids[tid] = seen_ids.get(tid, 0) + 1
        duplicates_count = sum(max(0, c - 1) for c in seen_ids.values())
        student_ids = set(student_map.keys())
        extra_ids = student_ids - expected_ids

        per_track_correct = 0
        for tid, expvals in expected_track_stats.items():
            row = student_map.get(tid)
            if row is None:
                continue
            title_ok = (str(row.get("track_title", "")).strip() == str(expvals["track_title"]).strip())
            bpm_ok = _approx_equal(_to_float(row.get("bpm")), _to_float(expvals["bpm"]))
            mean_wpm_ok = _approx_equal(_to_float(row.get("mean_wpm")), _to_float(expvals["mean_wpm"]))
            mean_offbeat_ok = _approx_equal(
                _to_float(row.get("mean_offbeat_entries")), _to_float(expvals["mean_offbeat_entries"])
            )
            words_per_beat_ok = _approx_equal(
                _to_float(row.get("words_per_beat")), _to_float(expvals["words_per_beat"])
            )
            flow_match_student = _to_bool(row.get("flow_match"))
            flow_match_expected = bool(expvals["flow_match"]) if expvals["flow_match"] is not None else None
            flow_ok = (flow_match_student == flow_match_expected)
            if title_ok and bpm_ok and mean_wpm_ok and mean_offbeat_ok and words_per_beat_ok and flow_ok:
                per_track_correct += 1

        denom = max(1, len(expected_ids) + len(extra_ids) + duplicates_count)
        scores["track_flow_stats_content_correct"] = per_track_correct / denom

    # Content correctness for session_summary.json
    if expected is not None and isinstance(ss_data, list):
        expected_sessions: Dict[str, Dict[str, Any]] = expected["expected_sessions"]
        expected_dates = set(expected_sessions.keys())

        # Build student map by session_date
        student_map: Dict[str, Dict[str, Any]] = {}
        count_by_date: Dict[str, int] = {}
        for item in ss_data:
            if not isinstance(item, dict):
                continue
            sdate = str(item.get("session_date", "")).strip()
            if not sdate:
                continue
            # Keep the first occurrence for scoring; duplicates penalized via counts
            if sdate not in student_map:
                student_map[sdate] = item
            count_by_date[sdate] = count_by_date.get(sdate, 0) + 1
        duplicates_count = sum(max(0, c - 1) for c in count_by_date.values())
        extra_dates = set(student_map.keys()) - expected_dates

        per_session_correct = 0
        for sdate, expvals in expected_sessions.items():
            item = student_map.get(sdate)
            if item is None:
                continue
            # Compare fields
            tv_ok = (_to_int(item.get("total_verses")) == _to_int(expvals["total_verses"]))
            toe_ok = _approx_equal(
                _to_float(item.get("total_offbeat_entries")),
                _to_float(expvals["total_offbeat_entries"]),
                tol=1e-6,
            )
            dwa_ok = _approx_equal(
                _to_float(item.get("duration_weighted_avg_wpm")),
                _to_float(expvals["duration_weighted_avg_wpm"]),
                tol=1e-2,
            )
            mb_ok = _approx_equal(
                _to_float(item.get("median_bpm")),
                _to_float(expvals["median_bpm"]),
                tol=1e-6,
            )
            if tv_ok and toe_ok and dwa_ok and mb_ok:
                per_session_correct += 1

        denom = max(1, len(expected_dates) + len(extra_dates) + duplicates_count)
        scores["session_summary_values_correct"] = per_session_correct / denom

    # Content correctness for data_quality_report.json
    if expected is not None and isinstance(dqr_data, dict):
        exp_unmatched_in_setlist = set(expected["expected_unmatched_in_setlist"])
        exp_unmatched_in_verses = set(expected["expected_unmatched_in_verses"])

        stu_unmatched_in_setlist = dqr_data.get("unmatched_tracks_in_setlist")
        stu_unmatched_in_verses = dqr_data.get("unmatched_track_ids_in_verses")

        part_scores = []
        if isinstance(stu_unmatched_in_setlist, list):
            try:
                stu_set1 = set(str(x).strip() for x in stu_unmatched_in_setlist)
                part_scores.append(1.0 if stu_set1 == exp_unmatched_in_setlist else 0.0)
            except Exception:
                part_scores.append(0.0)
        else:
            part_scores.append(0.0)

        if isinstance(stu_unmatched_in_verses, list):
            try:
                stu_set2 = set(str(x).strip() for x in stu_unmatched_in_verses)
                part_scores.append(1.0 if stu_set2 == exp_unmatched_in_verses else 0.0)
            except Exception:
                part_scores.append(0.0)
        else:
            part_scores.append(0.0)

        if part_scores:
            scores["data_quality_report_values_correct"] = sum(part_scores) / len(part_scores)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()