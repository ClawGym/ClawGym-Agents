import json
import sys
import csv
import re
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_csv_read(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_float(s: Any) -> Optional[float]:
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        try:
            return float(s.strip())
        except Exception:
            return None
    return None


def _near_equal(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= tol


def _numeric_token_present(text: str, number: float) -> bool:
    # Accept a few formatted variants: integer, one decimal, two decimals
    candidates = set()
    # Base formatting with up to two decimal places
    candidates.add(f"{number:.0f}")
    candidates.add(f"{number:.1f}")
    candidates.add(f"{number:.2f}")
    # Build regex pattern to match number as a token (not part of a longer numeric string)
    for cand in candidates:
        # Escape dot
        pattern = r"(?<![\d.])" + re.escape(cand) + r"(?![\d.])"
        if re.search(pattern, text):
            return True
    return False


def _parse_settings_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for a very simple root-level mapping:
    - scalar values: ints, floats, null, strings (unquoted or quoted)
    - list values for processed_files: inline [a, b] or block:
        processed_files:
          - a
          - b
    Returns dict or None on failure.
    """
    content = _read_text(path)
    if content is None:
        return None
    lines = content.splitlines()
    result: Dict[str, Any] = {}
    i = 0
    n = len(lines)
    try:
        while i < n:
            line = lines[i]
            # Strip comments and whitespace
            if "#" in line:
                line_wo_comment = line.split("#", 1)[0]
            else:
                line_wo_comment = line
            line_stripped = line_wo_comment.rstrip()
            if not line_stripped.strip():
                i += 1
                continue
            if ":" not in line_stripped:
                # invalid root-level mapping line
                # But could be a list item for previous key
                i += 1
                continue
            key_part, val_part = line_stripped.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if key == "processed_files":
                items: List[str] = []
                if val.startswith("["):
                    # inline list
                    inline = val
                    # If doesn't end with ']', it may span multiple lines, try to accumulate
                    if not inline.endswith("]"):
                        j = i + 1
                        while j < n:
                            next_line = lines[j]
                            if "#" in next_line:
                                next_line = next_line.split("#", 1)[0]
                            inline += next_line.strip()
                            if inline.strip().endswith("]"):
                                break
                            j += 1
                        i = j
                    inside = inline.strip()
                    # Remove brackets
                    inside = inside.lstrip("[").rstrip("]")
                    if inside.strip():
                        parts = [p.strip() for p in inside.split(",")]
                        for p in parts:
                            p = p.strip().strip("'").strip('"')
                            if p:
                                items.append(p)
                else:
                    # block list
                    # Read indented lines starting with -
                    j = i + 1
                    while j < n:
                        raw = lines[j]
                        if "#" in raw:
                            raw = raw.split("#", 1)[0]
                        if not raw.strip():
                            j += 1
                            continue
                        # stop if new root key
                        if re.match(r"^\S", raw):
                            break
                        # list item lines typically have leading spaces then '- '
                        m = re.match(r"^\s*-\s*(.+?)\s*$", raw)
                        if m:
                            item = m.group(1).strip().strip("'").strip('"')
                            if item:
                                items.append(item)
                            j += 1
                        else:
                            # Not a list item; stop
                            break
                    i = j - 1
                result[key] = items
            else:
                # scalar
                v = val
                if v == "" or v.lower() == "null":
                    result[key] = None
                else:
                    # Strip quotes
                    v_clean = v.strip().strip("'").strip('"')
                    # Try int
                    try:
                        if re.fullmatch(r"-?\d+", v_clean):
                            result[key] = int(v_clean)
                        elif re.fullmatch(r"-?\d+\.\d+", v_clean):
                            result[key] = float(v_clean)
                        else:
                            result[key] = v_clean
                    except Exception:
                        result[key] = v_clean
            i += 1
        # Ensure keys exist
        # If processed_files missing, set to []
        if "processed_files" not in result or result["processed_files"] is None:
            result["processed_files"] = []
        # Normalize types
        if not isinstance(result["processed_files"], list):
            return None
        return result
    except Exception:
        return None


def _compute_expected_from_input(input_csv_path: Path) -> Optional[Dict[str, Any]]:
    headers, rows = _safe_csv_read(input_csv_path)
    if headers is None or rows is None:
        return None
    # Validate required numeric fields exist
    for field in ("participant_id", "date", "screen_time_minutes", "tabs_switched"):
        if field not in (headers or []):
            return None
    try:
        stm_vals: List[float] = []
        ts_vals: List[float] = []
        participants: List[str] = []
        per_participant: Dict[str, List[float]] = {}
        for r in rows:
            pid = r.get("participant_id", "").strip()
            participants.append(pid)
            stm = float(r["screen_time_minutes"])
            ts = float(r["tabs_switched"])
            stm_vals.append(stm)
            ts_vals.append(ts)
            per_participant.setdefault(pid, []).append(stm)
        overall = {
            "rows": len(rows),
            "participants": len(set(participants)),
            "screen_mean": round(mean(stm_vals), 2) if stm_vals else 0.0,
            "screen_median": round(float(median(stm_vals)), 2) if stm_vals else 0.0,
            "tabs_mean": round(mean(ts_vals), 2) if ts_vals else 0.0,
            "tabs_median": round(float(median(ts_vals)), 2) if ts_vals else 0.0,
        }
        per_part_mean = {pid: round(mean(vals), 2) for pid, vals in per_participant.items()}
        return {
            "headers": headers,
            "rows": rows,
            "overall": overall,
            "per_participant": per_part_mean,
        }
    except Exception:
        return None


def _extract_flagged_rows(rows: List[Dict[str, str]], threshold: float) -> List[Dict[str, str]]:
    flagged = []
    for r in rows:
        try:
            stm = float(r.get("screen_time_minutes", ""))
            if stm > threshold:
                flagged.append(r)
        except Exception:
            continue
    return flagged


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "overall_metrics_json_correct": 0.0,
        "per_participant_csv_correct": 0.0,
        "flagged_csv_correct": 0.0,
        "email_draft_content_correct": 0.0,
        "settings_yaml_updated_correct": 0.0,
        "script_present": 0.0,
    }

    # Paths
    settings_path = workspace / "config" / "settings.yaml"
    input_csv = workspace / "input" / "incoming" / "session_log_2024-03-16.csv"
    base_name = "session_log_2024-03-16"
    overall_json_path = workspace / "output" / "metrics" / f"{base_name}_overall.json"
    per_participant_csv_path = workspace / "output" / "metrics" / f"{base_name}_per_participant.csv"
    flagged_csv_path = workspace / "output" / "flags" / f"{base_name}_flagged.csv"
    email_draft_path = workspace / "output" / "drafts" / f"alert_{base_name}.txt"

    # Parse settings for threshold and processed_files
    settings = _parse_settings_yaml(settings_path) if settings_path.exists() else None
    threshold = None
    if settings and isinstance(settings.get("attention_risk_threshold_minutes"), (int, float)):
        threshold = float(settings["attention_risk_threshold_minutes"])
    else:
        # fallback default from task input if settings missing or malformed
        threshold = 240.0

    # Compute expected from input CSV
    expected = _compute_expected_from_input(input_csv) if input_csv.exists() else None

    # Check overall metrics JSON correctness
    overall_ok = False
    if expected is not None and overall_json_path.exists():
        obj = _safe_json_load(overall_json_path)
        if isinstance(obj, dict):
            try:
                rows_ok = int(obj.get("rows")) == expected["overall"]["rows"]
                parts_ok = int(obj.get("participants")) == expected["overall"]["participants"]
                stm = obj.get("screen_time_minutes", {})
                ts = obj.get("tabs_switched", {})
                stm_mean = _parse_float(stm.get("mean")) if isinstance(stm, dict) else None
                stm_median = _parse_float(stm.get("median")) if isinstance(stm, dict) else None
                ts_mean = _parse_float(ts.get("mean")) if isinstance(ts, dict) else None
                ts_median = _parse_float(ts.get("median")) if isinstance(ts, dict) else None
                stm_mean_ok = stm_mean is not None and _near_equal(stm_mean, expected["overall"]["screen_mean"])
                stm_median_ok = stm_median is not None and _near_equal(stm_median, expected["overall"]["screen_median"])
                ts_mean_ok = ts_mean is not None and _near_equal(ts_mean, expected["overall"]["tabs_mean"])
                ts_median_ok = ts_median is not None and _near_equal(ts_median, expected["overall"]["tabs_median"])
                overall_ok = all([rows_ok, parts_ok, stm_mean_ok, stm_median_ok, ts_mean_ok, ts_median_ok])
            except Exception:
                overall_ok = False
    scores["overall_metrics_json_correct"] = 1.0 if overall_ok else 0.0

    # Check per-participant CSV
    per_ok = False
    if expected is not None and per_participant_csv_path.exists():
        header, rows = _safe_csv_read(per_participant_csv_path)
        if header is not None and rows is not None:
            # Exact header
            expected_header = ["participant_id", "mean_screen_time_minutes"]
            header_ok = header == expected_header
            # Row count
            row_count_ok = len(rows) == len(expected["per_participant"])
            # Validate content
            content_ok = True
            seen = set()
            for r in rows:
                pid = r.get("participant_id", "").strip()
                seen.add(pid)
                val = _parse_float(r.get("mean_screen_time_minutes"))
                if pid not in expected["per_participant"]:
                    content_ok = False
                    break
                exp_val = expected["per_participant"][pid]
                if val is None or not _near_equal(val, exp_val):
                    content_ok = False
                    break
            # Ensure no missing participants
            missing = set(expected["per_participant"].keys()) - seen
            per_ok = header_ok and row_count_ok and content_ok and (len(missing) == 0)
    scores["per_participant_csv_correct"] = 1.0 if per_ok else 0.0

    # Check flagged CSV
    flagged_ok = False
    if expected is not None and flagged_csv_path.exists():
        f_header, f_rows = _safe_csv_read(flagged_csv_path)
        if f_header is not None and f_rows is not None:
            # Header must match original header exactly
            header_match = f_header == expected["headers"]
            # Compute expected flagged
            expected_flagged = _extract_flagged_rows(expected["rows"], threshold if threshold is not None else 240.0)
            # Check counts and that all rows are > threshold and match expected set by unique tuple of key fields
            def key_tuple(r: Dict[str, str]) -> Tuple[str, str, str]:
                return (r.get("participant_id", "").strip(),
                        r.get("date", "").strip(),
                        str(r.get("screen_time_minutes", "")).strip())
            provided_set = {key_tuple(r) for r in f_rows}
            expected_set = {key_tuple(r) for r in expected_flagged}
            count_ok = len(f_rows) == len(expected_flagged)
            all_gt_threshold = all(
                _parse_float(r.get("screen_time_minutes")) is not None and
                _parse_float(r.get("screen_time_minutes")) > (threshold if threshold is not None else 240.0)
                for r in f_rows
            )
            rows_match = provided_set == expected_set
            flagged_ok = header_match and count_ok and all_gt_threshold and rows_match
    scores["flagged_csv_correct"] = 1.0 if flagged_ok else 0.0

    # Check email draft
    email_ok = False
    if expected is not None and email_draft_path.exists():
        txt = _read_text(email_draft_path)
        if isinstance(txt, str):
            lines = txt.splitlines()
            # First two lines exact
            line1_ok = len(lines) >= 1 and lines[0].strip() == "To: research-assistant@example.edu"
            line2_ok = len(lines) >= 2 and lines[1].strip() == f"Subject: Attention risk alert for {base_name}"
            body = "\n".join(lines[2:]) if len(lines) > 2 else ""
            # Required numeric mentions in body
            thr = threshold if threshold is not None else 240.0
            rows_n = expected["overall"]["rows"]
            parts_n = expected["overall"]["participants"]
            mean_st = expected["overall"]["screen_mean"]
            median_st = expected["overall"]["screen_median"]
            thr_present = _numeric_token_present(body, thr)
            rows_present = _numeric_token_present(body, rows_n)
            parts_present = _numeric_token_present(body, parts_n)
            mean_present = _numeric_token_present(body, mean_st)
            # Accept either 195, 195.0, 195.00
            median_present = _numeric_token_present(body, median_st)
            # Bulleted list entries for flagged rows
            expected_flagged = _extract_flagged_rows(expected["rows"], thr)
            # Extract bullet lines containing the pattern
            bullet_lines = []
            for line in lines[2:]:
                if re.match(r"^\s*[-*\u2022]\s+", line) or ("participant_id=" in line and "screen_time_minutes=" in line and "date=" in line):
                    bullet_lines.append(line.strip())
            # Build required representations
            flagged_reprs = set()
            for r in expected_flagged:
                pid = r.get("participant_id", "").strip()
                stm = str(r.get("screen_time_minutes", "")).strip()
                date = r.get("date", "").strip()
                flagged_reprs.add(f"participant_id={pid}, screen_time_minutes={stm}, date={date}")
            bullets_ok = all(any(rep in bl for bl in bullet_lines) for rep in flagged_reprs) and len(bullet_lines) >= len(flagged_reprs)
            email_ok = all([line1_ok, line2_ok, thr_present, rows_present, parts_present, mean_present, median_present, bullets_ok])
    scores["email_draft_content_correct"] = 1.0 if email_ok else 0.0

    # Check settings.yaml updated: baseline_mean_screen_time and processed_files appended
    settings_ok = False
    if expected is not None and settings is not None:
        try:
            baseline = settings.get("baseline_mean_screen_time", None)
            baseline_ok = isinstance(baseline, (int, float)) and _near_equal(float(baseline), expected["overall"]["screen_mean"])
            processed = settings.get("processed_files", [])
            processed_ok = isinstance(processed, list) and ("session_log_2024-03-16.csv" in processed)
            threshold_ok = isinstance(settings.get("attention_risk_threshold_minutes"), (int, float)) and float(settings.get("attention_risk_threshold_minutes")) == (threshold if threshold is not None else 240.0)
            settings_ok = baseline_ok and processed_ok and threshold_ok
        except Exception:
            settings_ok = False
    scores["settings_yaml_updated_correct"] = 1.0 if settings_ok else 0.0

    # Script presence in scripts/ directory
    scripts_dir = workspace / "scripts"
    script_ok = False
    if scripts_dir.exists() and scripts_dir.is_dir():
        # At least one .py file
        try:
            py_files = [p for p in scripts_dir.iterdir() if p.is_file() and p.suffix == ".py"]
            script_ok = len(py_files) >= 1
        except Exception:
            script_ok = False
    scores["script_present"] = 1.0 if script_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()