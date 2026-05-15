import json
import csv
import sys
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_file(path: Path) -> Optional[Any]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        return None
                    records.append(obj)
                except Exception:
                    return None
    except Exception:
        return None
    return records


def _parse_simple_yaml_session(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser tailored for the expected config/session.yaml structure:
    tolerance_bpm: <int>
    overhead_seconds_between_songs: <int>
    target_bpm_by_song:
      <song>: <int>
      ...
    Returns dict with these keys or None on failure.
    """
    text = _read_text(path)
    if text is None:
        return None
    tolerance_bpm: Optional[int] = None
    overhead: Optional[int] = None
    targets: Dict[str, int] = {}
    current_section: Optional[str] = None
    try:
        lines = text.splitlines()
        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            # Top-level key with or without value
            if not line.startswith(" "):
                if ":" not in line:
                    return None
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "target_bpm_by_song":
                    current_section = "target_bpm_by_song"
                    continue
                current_section = None
                if key == "tolerance_bpm":
                    try:
                        tolerance_bpm = int(val)
                    except Exception:
                        return None
                elif key == "overhead_seconds_between_songs":
                    try:
                        overhead = int(val)
                    except Exception:
                        return None
                else:
                    # Unknown top-level keys are ignored
                    pass
            else:
                # Indented: likely inside target_bpm_by_song
                if current_section == "target_bpm_by_song":
                    stripped = line.strip()
                    if ":" not in stripped:
                        return None
                    song_key, val = stripped.split(":", 1)
                    song_key = song_key.strip()
                    val = val.strip()
                    if not song_key:
                        return None
                    try:
                        bpm_val = int(val)
                    except Exception:
                        return None
                    targets[song_key] = bpm_val
                else:
                    # Unexpected indentation
                    return None
        if tolerance_bpm is None or overhead is None:
            return None
        return {
            "tolerance_bpm": tolerance_bpm,
            "overhead_seconds_between_songs": overhead,
            "target_bpm_by_song": targets,
        }
    except Exception:
        return None


def _parse_csv_dict(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            headers = [h for h in reader.fieldnames]
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if isinstance(s, str):
            return float(s.strip())
        return None
    except Exception:
        return None


def _to_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, bool):
            return int(s)
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            if s.is_integer():
                return int(s)
            return None
        if isinstance(s, str):
            s2 = s.strip()
            if s2.lower().endswith(".0"):
                s2 = s2[:-2]
            return int(s2)
        return None
    except Exception:
        return None


def _to_bool(s: Any) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if isinstance(s, (int, float)):
        return bool(int(s))
    if isinstance(s, str):
        val = s.strip().lower()
        if val in {"true", "t", "yes", "y", "1"}:
            return True
        if val in {"false", "f", "no", "n", "0"}:
            return False
    return None


def _almost_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _compute_expected(setlist: Dict[str, Any], logs: List[Dict[str, Any]], session: Dict[str, Any]) -> Dict[str, Any]:
    # Extract inputs
    tolerance = session.get("tolerance_bpm")
    overhead = session.get("overhead_seconds_between_songs")
    targets: Dict[str, int] = session.get("target_bpm_by_song", {})
    order = setlist.get("order", [])
    # Build song list in order
    song_names = [item["song"] for item in order if isinstance(item, dict) and "song" in item]
    base_lengths = {item["song"]: item.get("base_length_seconds") for item in order if isinstance(item, dict) and "song" in item}
    # Filter logs to songs in setlist
    logs_by_song: Dict[str, List[float]] = {name: [] for name in song_names}
    for rec in logs:
        song = rec.get("song")
        bpm = rec.get("measured_bpm")
        if song in logs_by_song:
            try:
                bpmf = float(bpm)
                logs_by_song[song].append(bpmf)
            except Exception:
                # skip malformed bpm
                return {}
    expected_rows: List[Dict[str, Any]] = []
    expected_json_songs: List[Dict[str, Any]] = []
    total_adjusted = 0.0
    for name in song_names:
        target_bpm = targets.get(name)
        if target_bpm is None:
            # Missing target is an error case; return empty to signal failure
            return {}
        samples = logs_by_song.get(name, [])
        if len(samples) == 0:
            avg_bpm = float(target_bpm)
            within = True
            sample_count = 0
        else:
            avg_bpm = sum(samples) / len(samples)
            diff = avg_bpm - float(target_bpm)
            within = abs(diff) <= float(tolerance)
            sample_count = len(samples)
        bpm_diff = avg_bpm - float(target_bpm)
        expected_rows.append({
            "song": name,
            "target_bpm": float(target_bpm),
            "avg_bpm": float(avg_bpm),
            "bpm_diff": float(bpm_diff),
            "within_tolerance": within,
            "sample_count": int(sample_count),
        })
        base_len = base_lengths.get(name)
        if base_len is None:
            return {}
        # adjusted_length_seconds
        if sample_count == 0:
            adjusted = float(base_len)
        else:
            if avg_bpm == 0:
                # avoid division by zero, treat as no adjustment
                adjusted = float(base_len)
            else:
                adjusted = float(base_len) * (float(target_bpm) / float(avg_bpm))
        total_adjusted += adjusted
        expected_json_songs.append({
            "song": name,
            "base_length_seconds": float(base_len),
            "target_bpm": float(target_bpm),
            "avg_bpm": float(avg_bpm),
            "adjusted_length_seconds": float(adjusted),
            "within_tolerance": within,
        })
    transitions = max(0, len(song_names) - 1)
    total_playtime = total_adjusted + transitions * float(overhead)
    expected = {
        "bpm_rows": expected_rows,
        "json_songs": expected_json_songs,
        "festival": setlist.get("festival"),
        "date": setlist.get("date"),
        "overhead": float(overhead),
        "total_playtime": float(total_playtime),
        "song_names": song_names,
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "bpm_summary_exists_and_header": 0.0,
        "bpm_summary_per_song_values": 0.0,
        "set_duration_exists_and_fields": 0.0,
        "set_duration_per_song_values": 0.0,
        "set_duration_total_playtime": 0.0,
    }

    # Load inputs
    config_path = workspace / "config" / "session.yaml"
    setlist_path = workspace / "input" / "setlist.json"
    logs_path = workspace / "input" / "practice_logs.jsonl"

    session = _parse_simple_yaml_session(config_path)
    setlist = _load_json_file(setlist_path)
    logs = _parse_jsonl(logs_path)

    # If inputs are missing or malformed, grading checks cannot proceed
    if not (isinstance(session, dict) and isinstance(setlist, dict) and isinstance(logs, list)):
        # Return all zeros gracefully
        return scores

    # Compute expected
    expected = _compute_expected(setlist, logs, session)
    if not expected or "bpm_rows" not in expected:
        return scores

    expected_bpm_rows = expected["bpm_rows"]
    expected_song_order = expected["song_names"]

    # Check bpm_summary.csv
    bpm_csv_path = workspace / "analysis" / "bpm_summary.csv"
    parsed_csv = _parse_csv_dict(bpm_csv_path)
    if parsed_csv is not None:
        headers, rows = parsed_csv
        expected_headers = ["song", "target_bpm", "avg_bpm", "bpm_diff", "within_tolerance", "sample_count"]
        if headers == expected_headers and len(rows) == len(expected_bpm_rows):
            scores["bpm_summary_exists_and_header"] = 1.0

        # Validate per-row values in order
        total = len(expected_bpm_rows)
        if total > 0 and len(rows) == total:
            correct = 0
            per_row_ok = True
            for idx, (row, exp) in enumerate(zip(rows, expected_bpm_rows)):
                # song order exact
                song_ok = (row.get("song", "").strip() == exp["song"])
                tbpm = _to_float(row.get("target_bpm"))
                avg = _to_float(row.get("avg_bpm"))
                diff = _to_float(row.get("bpm_diff"))
                wt = _to_bool(row.get("within_tolerance"))
                sc = _to_int(row.get("sample_count"))
                tbpm_ok = tbpm is not None and _almost_equal(tbpm, exp["target_bpm"], tol=1e-2)
                avg_ok = avg is not None and _almost_equal(avg, exp["avg_bpm"], tol=1e-2)
                diff_ok = diff is not None and _almost_equal(diff, exp["bpm_diff"], tol=1e-2)
                wt_ok = wt is not None and wt == exp["within_tolerance"]
                sc_ok = sc is not None and sc == exp["sample_count"]
                if song_ok and tbpm_ok and avg_ok and diff_ok and wt_ok and sc_ok:
                    correct += 1
                else:
                    per_row_ok = False
            scores["bpm_summary_per_song_values"] = correct / float(total)
        else:
            scores["bpm_summary_per_song_values"] = 0.0
    else:
        scores["bpm_summary_exists_and_header"] = 0.0
        scores["bpm_summary_per_song_values"] = 0.0

    # Check set_duration_estimate.json
    set_json_path = workspace / "analysis" / "set_duration_estimate.json"
    set_json = _load_json_file(set_json_path)
    if isinstance(set_json, dict):
        # Structure and fields
        has_fields = True
        # Required top-level fields
        festival_ok = set_json.get("festival") == expected["festival"]
        date_ok = set_json.get("date") == expected["date"]
        overhead_val = set_json.get("overhead_seconds_between_songs", None)
        overhead_ok = _to_float(overhead_val) is not None and _almost_equal(float(overhead_val), expected["overhead"], tol=1e-6)
        songs_list = set_json.get("songs")
        songs_ok = isinstance(songs_list, list) and len(songs_list) == len(expected["json_songs"])
        if not (festival_ok and date_ok and overhead_ok and songs_ok):
            has_fields = False
        if has_fields:
            scores["set_duration_exists_and_fields"] = 1.0

        # Per-song checks
        if isinstance(songs_list, list) and len(songs_list) == len(expected["json_songs"]):
            total = len(expected["json_songs"])
            correct = 0
            for idx, (cand, exp) in enumerate(zip(songs_list, expected["json_songs"])):
                if not isinstance(cand, dict):
                    continue
                song_ok = cand.get("song") == exp["song"]
                base_ok = _to_float(cand.get("base_length_seconds")) is not None and _almost_equal(float(cand.get("base_length_seconds")), exp["base_length_seconds"], tol=1e-2)
                tbpm_ok = _to_float(cand.get("target_bpm")) is not None and _almost_equal(float(cand.get("target_bpm")), exp["target_bpm"], tol=1e-2)
                avg_ok = _to_float(cand.get("avg_bpm")) is not None and _almost_equal(float(cand.get("avg_bpm")), exp["avg_bpm"], tol=1e-2)
                adj_ok = _to_float(cand.get("adjusted_length_seconds")) is not None and _almost_equal(float(cand.get("adjusted_length_seconds")), exp["adjusted_length_seconds"], tol=1e-2)
                wt_val = cand.get("within_tolerance")
                wt_ok = _to_bool(wt_val) is not None and _to_bool(wt_val) == exp["within_tolerance"]
                if song_ok and base_ok and tbpm_ok and avg_ok and adj_ok and wt_ok:
                    correct += 1
            scores["set_duration_per_song_values"] = correct / float(total) if total > 0 else 0.0
        else:
            scores["set_duration_per_song_values"] = 0.0

        # Total playtime check
        total_play = set_json.get("total_playtime_seconds")
        tp_ok = _to_float(total_play) is not None and _almost_equal(float(total_play), expected["total_playtime"], tol=1e-2)
        scores["set_duration_total_playtime"] = 1.0 if tp_ok else 0.0
    else:
        scores["set_duration_exists_and_fields"] = 0.0
        scores["set_duration_per_song_values"] = 0.0
        scores["set_duration_total_playtime"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()