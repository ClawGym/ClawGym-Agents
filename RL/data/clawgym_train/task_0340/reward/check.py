import csv
import json
import math
import sys
from pathlib import Path


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "file_not_found"
    except json.JSONDecodeError:
        return None, "json_decode_error"
    except Exception as e:
        return None, f"json_error:{e}"


def _load_coco_keypoints(json_path: Path):
    data, err = _safe_load_json(json_path)
    if err is not None or not isinstance(data, dict):
        return None
    categories = data.get("categories")
    if not isinstance(categories, list):
        return None
    person_keypoints = None
    for cat in categories:
        if isinstance(cat, dict) and cat.get("name") == "person":
            kp = cat.get("keypoints")
            if isinstance(kp, list) and all(isinstance(x, str) for x in kp) and len(kp) > 0:
                person_keypoints = kp
                break
    return person_keypoints


def _read_text_lines(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            # Preserve exact lines except strip trailing newline
            lines = f.read().splitlines()
        return lines, None
    except FileNotFoundError:
        return None, "file_not_found"
    except Exception as e:
        return None, f"read_error:{e}"


def _list_input_csvs(dir_path: Path):
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted(dir_path.rglob("*.csv"))


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None, "empty_or_no_header"
            header = list(reader.fieldnames)
            rows = []
            for row in reader:
                # Ensure all header keys present
                rows.append({k: row.get(k, "") for k in header})
            return header, rows, None
    except FileNotFoundError:
        return None, None, "file_not_found"
    except Exception as e:
        return None, None, f"csv_read_error:{e}"


def _parse_int(val):
    try:
        return int(val)
    except Exception:
        # Sometimes numeric may be float-like "3.0" in user output; reject for strictness
        return None


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= tol
    return False


def _compare_standardized_output(input_header, input_rows, keypoints_set, out_path: Path) -> bool:
    # Build expected rows by filtering
    expected_rows = [row for row in input_rows if row.get("cue") in keypoints_set]
    # Read student's output
    out_header, out_rows, err = _read_csv_dicts(out_path)
    if err is not None:
        return False
    # Header must match exactly input header order and names
    if out_header != input_header:
        return False
    # Rows must match exactly (order preserved)
    if len(out_rows) != len(expected_rows):
        return False
    for erow, orow in zip(expected_rows, out_rows):
        for col in input_header:
            if (erow.get(col, "") or "") != (orow.get(col, "") or ""):
                return False
    return True


def _compute_expected_aggregations(input_files, keypoints_list):
    # Returns dicts or None if parsing issues
    keypoints_set = set(keypoints_list)
    matched_records = []  # list of (session_id, keypoint, count)
    unmatched_records = []  # list of (file_basename, cue, count)
    all_sessions = set()

    for in_path in input_files:
        header, rows, err = _read_csv_dicts(in_path)
        if err is not None:
            return None, None, None, None
        # Required columns
        for req in ("session_id", "observer", "cue", "count"):
            if req not in header:
                return None, None, None, None
        base = in_path.name
        for row in rows:
            session_id = row.get("session_id")
            cue = row.get("cue")
            cnt = _parse_int(row.get("count"))
            if session_id is None or cue is None or cnt is None:
                return None, None, None, None
            all_sessions.add(session_id)
            if cue in keypoints_set:
                matched_records.append((session_id, cue, cnt))
            else:
                unmatched_records.append((base, cue, cnt))

    # By-session aggregation
    by_session_counts = {}  # (session_id, keypoint) -> total_count
    session_totals = {}     # session_id -> total_count across matched keypoints
    for session_id, keypoint, cnt in matched_records:
        by_session_counts[(session_id, keypoint)] = by_session_counts.get((session_id, keypoint), 0) + cnt
        session_totals[session_id] = session_totals.get(session_id, 0) + cnt

    expected_by_session = {}  # (session_id, keypoint) -> (total_count, percent_of_session)
    for (session_id, keypoint), total in by_session_counts.items():
        denom = session_totals.get(session_id, 0)
        if denom == 0:
            # Shouldn't happen since total>0 if key present
            percent = 0.0
        else:
            percent = total / denom
        expected_by_session[(session_id, keypoint)] = (total, percent)

    # Overall aggregation
    total_sessions = len(all_sessions)
    total_by_keypoint = {kp: 0 for kp in keypoints_list}
    for _, keypoint, cnt in matched_records:
        total_by_keypoint[keypoint] = total_by_keypoint.get(keypoint, 0) + cnt
    expected_overall = {}  # keypoint -> (total_count, num_sessions, mean_per_session)
    for kp in keypoints_list:
        tot = total_by_keypoint.get(kp, 0)
        num_sessions = total_sessions
        mean_val = (tot / num_sessions) if num_sessions > 0 else 0.0
        expected_overall[kp] = (tot, num_sessions, mean_val)

    # Unmatched aggregation
    expected_unmatched = {}  # (file, cue) -> total_count
    for base, cue, cnt in unmatched_records:
        expected_unmatched[(base, cue)] = expected_unmatched.get((base, cue), 0) + cnt

    return expected_by_session, expected_overall, expected_unmatched, keypoints_set


def _read_by_session_csv(path: Path):
    header, rows, err = _read_csv_dicts(path)
    if err is not None:
        return None
    expected_header = ["session_id", "keypoint", "total_count", "percent_of_session"]
    if header != expected_header:
        return None
    result = {}
    for row in rows:
        sid = row.get("session_id")
        kp = row.get("keypoint")
        tot = _parse_int(row.get("total_count"))
        try:
            pct = float(row.get("percent_of_session"))
        except Exception:
            return None
        if sid is None or kp is None or tot is None or not math.isfinite(pct):
            return None
        result[(sid, kp)] = (tot, pct)
    return result


def _read_overall_csv(path: Path):
    header, rows, err = _read_csv_dicts(path)
    if err is not None:
        return None
    expected_header = ["keypoint", "total_count", "num_sessions", "mean_count_per_session"]
    if header != expected_header:
        return None
    result = {}
    for row in rows:
        kp = row.get("keypoint")
        tot = _parse_int(row.get("total_count"))
        ns = _parse_int(row.get("num_sessions"))
        try:
            meanv = float(row.get("mean_count_per_session"))
        except Exception:
            return None
        if kp is None or tot is None or ns is None or not math.isfinite(meanv):
            return None
        result[kp] = (tot, ns, meanv)
    return result


def _read_unmatched_csv(path: Path):
    header, rows, err = _read_csv_dicts(path)
    if err is not None:
        return None
    expected_header = ["file", "cue", "total_count"]
    if header != expected_header:
        return None
    result = {}
    for row in rows:
        fn = row.get("file")
        cue = row.get("cue")
        tot = _parse_int(row.get("total_count"))
        if fn is None or cue is None or tot is None:
            return None
        result[(fn, cue)] = tot
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "coco_json_valid": 0.0,
        "keypoint_names_txt_correct": 0.0,
        "standardized_outputs_correct": 0.0,
        "by_session_summary_correct": 0.0,
        "overall_summary_correct": 0.0,
        "qa_unmatched_cues_correct": 0.0,
    }

    # 1) Validate COCO JSON and extract keypoints
    coco_json_path = workspace / "external" / "coco" / "person_keypoints_val2017.json"
    keypoints = _load_coco_keypoints(coco_json_path)
    if isinstance(keypoints, list) and len(keypoints) > 0 and all(isinstance(x, str) for x in keypoints):
        scores["coco_json_valid"] = 1.0
    else:
        scores["coco_json_valid"] = 0.0
        keypoints = None

    # 1b) Check keypoint_names.txt matches JSON keypoints order exactly
    keypoints_txt_path = workspace / "external" / "coco" / "keypoint_names.txt"
    if keypoints is not None:
        lines, err = _read_text_lines(keypoints_txt_path)
        if err is None and lines == keypoints:
            scores["keypoint_names_txt_correct"] = 1.0
        else:
            scores["keypoint_names_txt_correct"] = 0.0
    else:
        scores["keypoint_names_txt_correct"] = 0.0

    # 2) Standardized outputs check across all input CSV files
    input_dir = workspace / "input" / "observations"
    input_files = _list_input_csvs(input_dir)
    if keypoints is not None and len(input_files) > 0:
        correct = 0
        total = 0
        keypoints_set = set(keypoints)
        for in_path in input_files:
            in_header, in_rows, err = _read_csv_dicts(in_path)
            out_path = workspace / "outputs" / "standardized" / (in_path.stem + "_standardized.csv")
            total += 1
            if err is not None:
                # Cannot parse input => treat as incorrect for this file
                continue
            # Ensure required columns for filtering exist
            if "cue" not in in_header:
                continue
            if _compare_standardized_output(in_header, in_rows, keypoints_set, out_path):
                correct += 1
        if total > 0:
            scores["standardized_outputs_correct"] = correct / total
        else:
            scores["standardized_outputs_correct"] = 0.0
    else:
        scores["standardized_outputs_correct"] = 0.0

    # 3) Summaries: by_session and overall
    if keypoints is not None and len(input_files) > 0:
        expected_by_session, expected_overall, expected_unmatched, _ = _compute_expected_aggregations(input_files, keypoints)
    else:
        expected_by_session = expected_overall = expected_unmatched = None

    # 3a) by_session summary
    by_session_path = workspace / "outputs" / "summary" / "by_session.csv"
    if expected_by_session is not None:
        student_by_session = _read_by_session_csv(by_session_path)
        if student_by_session is not None:
            if set(student_by_session.keys()) == set(expected_by_session.keys()):
                ok = True
                for k, (exp_tot, exp_pct) in expected_by_session.items():
                    stu_tot, stu_pct = student_by_session.get(k, (None, None))
                    if stu_tot != exp_tot or not _float_equal(stu_pct, exp_pct, tol=1e-6):
                        ok = False
                        break
                if ok:
                    scores["by_session_summary_correct"] = 1.0
                else:
                    scores["by_session_summary_correct"] = 0.0
            else:
                scores["by_session_summary_correct"] = 0.0
        else:
            scores["by_session_summary_correct"] = 0.0
    else:
        scores["by_session_summary_correct"] = 0.0

    # 3b) overall summary
    overall_path = workspace / "outputs" / "summary" / "overall.csv"
    if expected_overall is not None:
        student_overall = _read_overall_csv(overall_path)
        if student_overall is not None:
            if set(student_overall.keys()) == set(expected_overall.keys()):
                ok = True
                for kp, (exp_tot, exp_ns, exp_mean) in expected_overall.items():
                    stu_tot, stu_ns, stu_mean = student_overall.get(kp, (None, None, None))
                    if stu_tot != exp_tot or stu_ns != exp_ns or not _float_equal(stu_mean, exp_mean, tol=1e-6):
                        ok = False
                        break
                if ok:
                    scores["overall_summary_correct"] = 1.0
                else:
                    scores["overall_summary_correct"] = 0.0
            else:
                scores["overall_summary_correct"] = 0.0
        else:
            scores["overall_summary_correct"] = 0.0
    else:
        scores["overall_summary_correct"] = 0.0

    # 4) QA unmatched cues
    qa_unmatched_path = workspace / "outputs" / "qa" / "unmatched_cues.csv"
    if expected_unmatched is not None:
        student_unmatched = _read_unmatched_csv(qa_unmatched_path)
        if student_unmatched is not None:
            if set(student_unmatched.keys()) == set(expected_unmatched.keys()):
                ok = True
                for k, exp_tot in expected_unmatched.items():
                    if student_unmatched.get(k) != exp_tot:
                        ok = False
                        break
                if ok:
                    scores["qa_unmatched_cues_correct"] = 1.0
                else:
                    scores["qa_unmatched_cues_correct"] = 0.0
            else:
                scores["qa_unmatched_cues_correct"] = 0.0
        else:
            scores["qa_unmatched_cues_correct"] = 0.0
    else:
        scores["qa_unmatched_cues_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()