import json
import os
import sys
import csv
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def d(val):
    # Convert numeric or numeric-like to Decimal safely
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    if isinstance(val, str):
        return Decimal(val.strip())
    raise InvalidOperation(f"Unsupported numeric type: {type(val)}")

Q = Decimal("0.01")

def round2_dec(x: Decimal) -> Decimal:
    return x.quantize(Q, rounding=ROUND_HALF_UP)

def fmt2(x: Decimal) -> str:
    return f"{round2_dec(x):.2f}"

def median_dec(values):
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    else:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / Decimal(2)

def build_expected(input_data):
    # Expected structure:
    # {
    #   "beatsPerBarDefault": <int>,
    #   "normalization": {"min": <num>, "max": <num>},
    #   "tracks": [
    #      {"id": "...", "intervals": [...], "beatsPerBar": <int>?}
    #      or {"id": "...", "timestamps": [...], "beatsPerBar": <int>?}
    #   ]
    # }
    norm = input_data.get("normalization", {}) if isinstance(input_data, dict) else {}
    if "min" not in norm or "max" not in norm:
        raise ValueError("Input normalization thresholds missing min/max.")
    norm_min = d(norm["min"])
    norm_max = d(norm["max"])

    beats_default = input_data.get("beatsPerBarDefault", None)
    if beats_default is None:
        raise ValueError("Input missing beatsPerBarDefault.")
    try:
        beats_default_int = int(beats_default)
    except Exception:
        raise ValueError("beatsPerBarDefault must be an integer.")

    tracks = input_data.get("tracks", [])
    if not isinstance(tracks, list) or len(tracks) == 0:
        raise ValueError("Input tracks missing or empty.")

    expected_by_id = {}

    for t in tracks:
        if not isinstance(t, dict):
            raise ValueError("Each track must be an object.")
        tid = t.get("id")
        if not tid:
            raise ValueError("Track missing id.")
        has_intervals = "intervals" in t and isinstance(t["intervals"], list)
        has_timestamps = "timestamps" in t and isinstance(t["timestamps"], list)
        if has_intervals and has_timestamps:
            raise ValueError(f"Track {tid} has both intervals and timestamps.")
        if not (has_intervals or has_timestamps):
            raise ValueError(f"Track {tid} missing intervals or timestamps.")

        if has_intervals:
            source = "intervals"
            intervals = [d(x) for x in t["intervals"]]
            if len(intervals) < 1:
                raise ValueError(f"Track {tid} must have at least one interval.")
            if any(x <= 0 for x in intervals):
                raise ValueError(f"Track {tid} intervals must be > 0.")
            tap_count = len(intervals) + 1
        else:
            source = "timestamps"
            timestamps = [d(x) for x in t["timestamps"]]
            if len(timestamps) < 2:
                raise ValueError(f"Track {tid} must have at least two timestamps.")
            diffs = []
            for i in range(1, len(timestamps)):
                diff = timestamps[i] - timestamps[i-1]
                if diff <= 0:
                    raise ValueError(f"Track {tid} timestamps must be strictly increasing.")
                diffs.append(diff)
            intervals = diffs
            tap_count = len(timestamps)

        # Compute average and median (Decimal)
        avg = sum(intervals, Decimal(0)) / Decimal(len(intervals))
        med = median_dec(intervals)

        # Round averageIntervalMs and medianIntervalMs to 2 decimals
        avg_r = round2_dec(avg)
        med_r = round2_dec(med)

        # rawBpm = 60000 / averageIntervalMs (use rounded average per instruction)
        if avg_r <= 0:
            raise ValueError(f"Track {tid} average interval must be > 0.")
        raw_bpm = Decimal("60000") / avg_r
        raw_bpm_r = round2_dec(raw_bpm)

        # Normalize: use rawBpm (rounded) for comparison and operation
        if raw_bpm_r < norm_min:
            norm_bpm = raw_bpm_r * Decimal(2)
        elif raw_bpm_r > norm_max:
            norm_bpm = raw_bpm_r / Decimal(2)
        else:
            norm_bpm = raw_bpm_r
        norm_bpm_r = round2_dec(norm_bpm)

        # msPerBeatRaw = 60000 / rawBpm (rounded)
        if raw_bpm_r <= 0:
            raise ValueError(f"Track {tid} rawBpm must be > 0.")
        ms_per_beat_raw = Decimal("60000") / raw_bpm_r
        ms_per_beat_raw_r = round2_dec(ms_per_beat_raw)

        # msPerBeatNormalized = 60000 / normalizedBpm (rounded)
        if norm_bpm_r <= 0:
            raise ValueError(f"Track {tid} normalizedBpm must be > 0.")
        ms_per_beat_norm = Decimal("60000") / norm_bpm_r
        ms_per_beat_norm_r = round2_dec(ms_per_beat_norm)

        # beatsPerBar from track or default
        beats = t.get("beatsPerBar", beats_default_int)
        try:
            beats_int = int(beats)
        except Exception:
            raise ValueError(f"Track {tid} beatsPerBar must be integer or omitted.")
        # msPerBarNormalized = msPerBeatNormalized * beatsPerBar (rounded)
        ms_per_bar_norm = ms_per_beat_norm_r * Decimal(beats_int)
        ms_per_bar_norm_r = round2_dec(ms_per_bar_norm)

        expected_by_id[tid] = {
            "id": tid,
            "source": source,
            "tapCount": tap_count,
            "averageIntervalMs": fmt2(avg_r),
            "medianIntervalMs": fmt2(med_r),
            "rawBpm": fmt2(raw_bpm_r),
            "normalizedBpm": fmt2(norm_bpm_r),
            "msPerBeatRaw": fmt2(ms_per_beat_raw_r),
            "msPerBeatNormalized": fmt2(ms_per_beat_norm_r),
            "beatsPerBar": beats_int,
            "msPerBarNormalized": fmt2(ms_per_bar_norm_r),
        }

    return expected_by_id

def parse_json_report(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def to_decimal_string_from_json_value(val):
    # Accept ints, floats, or numeric strings; convert to Decimal and format to two decimals
    try:
        dec = d(val)
    except Exception:
        return None
    return fmt2(dec)

def validate_json(output_json_path, expected_by_id):
    result = {
        "json_parse_ok": False,
        "json_tracks_count_match": False,
        "json_tracks_all_match_values": False,
        "json_ids": set(),
        "json_tracks_by_id": {},
    }
    try:
        data = parse_json_report(output_json_path)
    except Exception:
        return result  # stays False
    # Validate structure
    if not isinstance(data, dict):
        return result
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return result
    # Build mapping
    by_id = {}
    ids = set()
    for item in tracks:
        if isinstance(item, dict) and "id" in item:
            tid = item.get("id")
            if isinstance(tid, str):
                ids.add(tid)
                by_id[tid] = item
    result["json_parse_ok"] = True
    result["json_ids"] = ids
    result["json_tracks_by_id"] = by_id
    # Count match (exact set)
    expected_ids = set(expected_by_id.keys())
    result["json_tracks_count_match"] = (ids == expected_ids)
    # Values match for each expected id
    all_match = True
    for tid, exp in expected_by_id.items():
        item = by_id.get(tid)
        if item is None:
            all_match = False
            break
        # Check fields exist and match
        # source
        if item.get("source") != exp["source"]:
            all_match = False
            break
        # tapCount must be integer equal
        if item.get("tapCount") != exp["tapCount"]:
            all_match = False
            break
        # beatsPerBar must be integer equal
        if item.get("beatsPerBar") != exp["beatsPerBar"]:
            all_match = False
            break
        # Numeric fields: compare as two-decimal strings
        for key in [
            "averageIntervalMs",
            "medianIntervalMs",
            "rawBpm",
            "normalizedBpm",
            "msPerBeatRaw",
            "msPerBeatNormalized",
            "msPerBarNormalized",
        ]:
            val = item.get(key)
            if val is None:
                all_match = False
                break
            got = to_decimal_string_from_json_value(val)
            if got is None or got != exp[key]:
                all_match = False
                break
        if not all_match:
            break
    result["json_tracks_all_match_values"] = all_match
    return result

def parse_csv_summary(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().splitlines()
    # Allow possible trailing empty lines
    lines = [line for line in content if line.strip() != ""]
    if not lines:
        return None, None
    header = lines[0]
    rows = []
    for line in lines[1:]:
        # Use csv reader to handle commas safely
        for row in csv.reader([line]):
            rows.append(row)
    return header, rows

def validate_csv(output_csv_path, expected_by_id, json_by_id=None):
    result = {
        "csv_header_ok": False,
        "csv_rows_count_match": False,
        "csv_rows_values_match": False,
        "csv_matches_json": False,
    }
    try:
        header, rows = parse_csv_summary(output_csv_path)
    except Exception:
        return result
    if header == "trackId,rawBpm,normalizedBpm,beatsPerBar,msPerBarNormalized":
        result["csv_header_ok"] = True
    else:
        # Early return? Keep checking only if header ok gates others.
        pass

    if not result["csv_header_ok"]:
        return result

    # Build mapping from rows; ensure no duplicates
    csv_map = {}
    for row in rows:
        if len(row) != 5:
            # malformed row
            continue
        track_id = row[0].strip()
        csv_map[track_id] = {
            "rawBpm": row[1].strip(),
            "normalizedBpm": row[2].strip(),
            "beatsPerBar": row[3].strip(),
            "msPerBarNormalized": row[4].strip(),
        }

    expected_ids = set(expected_by_id.keys())
    csv_ids = set(csv_map.keys())
    result["csv_rows_count_match"] = (csv_ids == expected_ids)

    # Value checks
    all_match = True
    for tid, exp in expected_by_id.items():
        if tid not in csv_map:
            all_match = False
            break
        row = csv_map[tid]
        # Compare with expected (strings)
        if row["rawBpm"] != exp["rawBpm"]:
            all_match = False
            break
        if row["normalizedBpm"] != exp["normalizedBpm"]:
            all_match = False
            break
        # beatsPerBar integer string
        if row["beatsPerBar"] != str(exp["beatsPerBar"]):
            all_match = False
            break
        if row["msPerBarNormalized"] != exp["msPerBarNormalized"]:
            all_match = False
            break
    result["csv_rows_values_match"] = all_match

    # CSV matches JSON values (if JSON provided)
    if json_by_id is None:
        # If no JSON provided, base on expected equivalence
        result["csv_matches_json"] = result["csv_rows_values_match"]
    else:
        match_json = True
        for tid in expected_by_id.keys():
            if tid not in csv_map or tid not in json_by_id:
                match_json = False
                break
            row = csv_map[tid]
            j = json_by_id[tid]
            # Compare JSON values formatted to two decimals to CSV strings
            def json_num_str(key):
                val = j.get(key)
                s = to_decimal_string_from_json_value(val)
                return s
            if row["rawBpm"] != json_num_str("rawBpm"):
                match_json = False
                break
            if row["normalizedBpm"] != json_num_str("normalizedBpm"):
                match_json = False
                break
            if row["beatsPerBar"] != str(j.get("beatsPerBar")):
                match_json = False
                break
            if row["msPerBarNormalized"] != json_num_str("msPerBarNormalized"):
                match_json = False
                break
        result["csv_matches_json"] = match_json

    return result

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "output_json_exists": False,
        "output_csv_exists": False,
        "json_parse_ok": False,
        "json_tracks_count_match": False,
        "json_tracks_all_match_values": False,
        "csv_header_ok": False,
        "csv_rows_count_match": False,
        "csv_rows_values_match": False,
        "csv_matches_json": False,
    }

    # Load input to compute expected
    input_path = os.path.join(input_dir, "tempo_requests.json")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            input_data = json.load(f)
        expected_by_id = build_expected(input_data)
    except Exception:
        # If input missing or malformed, all checks remain False, reward 0.
        expected_by_id = {}

    # Check outputs exist
    json_path = os.path.join(output_dir, "tempo_report.json")
    csv_path = os.path.join(output_dir, "tempo_summary.csv")

    if os.path.isfile(json_path):
        checks["output_json_exists"] = True
    if os.path.isfile(csv_path):
        checks["output_csv_exists"] = True

    json_validation = {}
    if checks["output_json_exists"] and expected_by_id:
        json_validation = validate_json(json_path, expected_by_id)
        checks["json_parse_ok"] = json_validation.get("json_parse_ok", False)
        checks["json_tracks_count_match"] = json_validation.get("json_tracks_count_match", False)
        checks["json_tracks_all_match_values"] = json_validation.get("json_tracks_all_match_values", False)

    if checks["output_csv_exists"] and expected_by_id:
        csv_validation = validate_csv(
            csv_path,
            expected_by_id,
            json_validation.get("json_tracks_by_id") if checks["json_parse_ok"] else None
        )
        checks["csv_header_ok"] = csv_validation.get("csv_header_ok", False)
        checks["csv_rows_count_match"] = csv_validation.get("csv_rows_count_match", False)
        checks["csv_rows_values_match"] = csv_validation.get("csv_rows_values_match", False)
        checks["csv_matches_json"] = csv_validation.get("csv_matches_json", False)

    # Reward weighting
    weights = {
        "output_json_exists": 0.1,
        "output_csv_exists": 0.1,
        "json_parse_ok": 0.15,
        "json_tracks_count_match": 0.15,
        "json_tracks_all_match_values": 0.25,
        "csv_header_ok": 0.05,
        "csv_rows_count_match": 0.1,
        "csv_rows_values_match": 0.1,
        "csv_matches_json": 0.1,
    }

    reward = 0.0
    # Ensure no-op baseline: if no expected (due to missing input) or no outputs, reward must be 0.0
    # Our weighting naturally yields 0 when outputs missing or checks fail.
    for key, w in weights.items():
        if checks.get(key, False):
            reward += w
    # Clamp to [0, 1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()