import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Validate non-empty and header present
            if reader.fieldnames is None or len(reader.fieldnames) == 0:
                return None
            return rows
    except Exception:
        return None


def _parse_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the specific YAML structure used here.
    Expected keys:
      - watch_dir: "input/inbox"
      - file_glob: "overdose_calls_*.csv"
      - threshold_alert: 8
      - message:
          max_chars: 700
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    cfg: Dict[str, Any] = {}
    # Simple regex-based extraction for top-level keys
    watch_dir_match = re.search(r'^\s*watch_dir:\s*["\']?([^"\']+?)["\']?\s*$', text, re.MULTILINE)
    file_glob_match = re.search(r'^\s*file_glob:\s*["\']?([^"\']+?)["\']?\s*$', text, re.MULTILINE)
    threshold_match = re.search(r'^\s*threshold_alert:\s*([+-]?\d+(?:\.\d+)?)\s*$', text, re.MULTILINE)

    # For message.max_chars: either nested or dot notation; we look inside a message block or any 'max_chars'
    max_chars_val: Optional[float] = None
    # First try to find within a message block
    lines = text.splitlines()
    msg_block = False
    msg_indent = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*message:\s*$', line):
            msg_block = True
            msg_indent = len(line) - len(line.lstrip(" "))
            continue
        if msg_block:
            # End of block if indentation less or empty line
            indent = len(line) - len(line.lstrip(" "))
            if indent <= (msg_indent or 0) and line.strip() != "":
                # Out of block
                msg_block = False
            else:
                m = re.search(r'^\s*max_chars:\s*([+-]?\d+(?:\.\d+)?)\s*$', line)
                if m:
                    try:
                        max_chars_val = float(m.group(1))
                    except Exception:
                        pass
    # Fallback: search anywhere
    if max_chars_val is None:
        m_any = re.search(r'^\s*max_chars:\s*([+-]?\d+(?:\.\d+)?)\s*$', text, re.MULTILINE)
        if m_any:
            try:
                max_chars_val = float(m_any.group(1))
            except Exception:
                max_chars_val = None

    if watch_dir_match:
        cfg["watch_dir"] = watch_dir_match.group(1).strip()
    if file_glob_match:
        cfg["file_glob"] = file_glob_match.group(1).strip()
    if threshold_match:
        try:
            # keep numeric (int if integer-like)
            val = float(threshold_match.group(1))
            cfg["threshold_alert"] = int(val) if val.is_integer() else val
        except Exception:
            pass
    if max_chars_val is not None:
        cfg.setdefault("message", {})
        # store as int if integer
        cfg["message"]["max_chars"] = int(max_chars_val) if float(max_chars_val).is_integer() else max_chars_val

    # Ensure at least one expected key is present
    if not any(k in cfg for k in ["watch_dir", "file_glob", "threshold_alert"]) and not ("message" in cfg and "max_chars" in cfg.get("message", {})):
        return None
    return cfg


def _find_weekly_csv(workspace: Path) -> Optional[Path]:
    """
    Attempt to locate the weekly CSV for 2024-01-07 in either staging or inbox.
    """
    candidates = [
        workspace / "input" / "inbox" / "overdose_calls_2024-01-07.csv",
        workspace / "input" / "staging" / "overdose_calls_2024-01-07.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    # As a last resort, search recursively for a matching filename
    for p in workspace.rglob("overdose_calls_2024-01-07.csv"):
        return p
    return None


def _compute_weekly_stats(current_csv: Path, reference_csv: Path) -> Optional[Dict[str, Any]]:
    current_rows = _load_csv_dicts(current_csv)
    if current_rows is None:
        return None
    total_calls = len(current_rows)

    # response_minutes avg
    try:
        resp_vals = [float(r["response_minutes"]) for r in current_rows]
    except Exception:
        return None
    avg_response = round(sum(resp_vals) / total_calls, 1) if total_calls > 0 else 0.0

    # total naloxone doses
    try:
        total_doses = sum(float(r["naloxone_doses"]) for r in current_rows)
    except Exception:
        return None
    # counts by outcome
    revived_count = 0
    transported_count = 0
    declined_count = 0
    for r in current_rows:
        outcome = str(r.get("outcome", "")).strip().lower()
        if outcome == "revived":
            revived_count += 1
        elif outcome == "transported":
            transported_count += 1
        elif outcome == "declined":
            declined_count += 1

    # percent change vs last week
    percent_change: Any = "NA"
    if reference_csv.exists():
        ref_rows = _load_csv_dicts(reference_csv)
        if ref_rows is not None and len(ref_rows) > 0:
            last_calls = len(ref_rows)
            if last_calls > 0:
                percent_change = round(((total_calls - last_calls) / last_calls) * 100.0, 1)

    return {
        "total_calls": total_calls,
        "avg_response_minutes": avg_response,
        "total_naloxone_doses": total_doses,
        "revived_count": revived_count,
        "transported_count": transported_count,
        "declined_count": declined_count,
        "percent_change_calls_vs_last_week": percent_change,
    }


def _parse_summary_csv(path: Path) -> Optional[Tuple[List[str], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if len(rows) < 2:
            return None
        header = rows[0]
        data = rows[1]
        return header, data
    except Exception:
        return None


def _extract_numbers_near(text: str, keyword_patterns: List[str], number: float, tolerance: float = 0.05, window: int = 40) -> bool:
    """
    Checks if a number approximately equal to `number` appears within a nearby window of any keyword pattern.
    """
    # Make a flexible regex for the target number: allow optional +, optional .0 if integer
    if float(number).is_integer():
        num_pattern = r'[+]?%d(?:\.0)?' % int(number)
    else:
        # Fixed one decimal preferred
        num_str = f"{number:.1f}"
        # Accept both 1-dec and trimmed form without trailing zero if .0
        num_pattern = re.escape(num_str)
    matches = False
    lowered = text.lower()
    for kw in keyword_patterns:
        for m in re.finditer(kw, lowered):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            chunk = lowered[start:end]
            if re.search(rf'\b{num_pattern}\b', chunk):
                matches = True
                break
        if matches:
            break
    return matches


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_present_and_header": 0.0,
        "summary_values_correct": 0.0,
        "message_file_present_and_constraints": 0.0,
        "message_includes_metrics": 0.0,
        "message_includes_alert_request": 0.0,
        "config_log_present": 0.0,
        "config_log_keys_checklist": 0.0,
        "config_log_watch_dir_and_match_count": 0.0,
        "config_log_types_validation": 0.0,
    }

    # Expected output paths
    summary_path = workspace / "out" / "weekly" / "summary_2024-01-07.csv"
    message_path = workspace / "out" / "messages" / "community_update_2024-01-07.txt"
    config_log_path = workspace / "out" / "logs" / "config_check.txt"

    # Load config for thresholds and limits
    cfg = _parse_yaml_config(workspace / "config" / "alerts.yaml")

    # Compute expected stats from inputs
    weekly_csv = _find_weekly_csv(workspace)
    ref_csv = workspace / "input" / "reference" / "last_week.csv"
    expected_stats: Optional[Dict[str, Any]] = None
    if weekly_csv is not None and ref_csv.exists():
        expected_stats = _compute_weekly_stats(weekly_csv, ref_csv)
    elif weekly_csv is not None:
        expected_stats = _compute_weekly_stats(weekly_csv, Path("/nonexistent/reference.csv"))

    # 1) Summary CSV checks
    parsed = _parse_summary_csv(summary_path) if summary_path.exists() else None
    expected_header = [
        "date",
        "total_calls",
        "avg_response_minutes",
        "total_naloxone_doses",
        "revived_count",
        "transported_count",
        "declined_count",
        "percent_change_calls_vs_last_week",
    ]
    if parsed is not None:
        header, data = parsed
        if header == expected_header and len(data) == len(expected_header):
            # format check passed
            if data[0] == "2024-01-07":
                scores["summary_file_present_and_header"] = 1.0
            else:
                scores["summary_file_present_and_header"] = 0.0
        else:
            scores["summary_file_present_and_header"] = 0.0
    else:
        scores["summary_file_present_and_header"] = 0.0

    # Values correctness
    if parsed is not None and expected_stats is not None:
        _, data = parsed
        try:
            # data mapping by header order
            data_map = dict(zip(expected_header, data))
            ok = True
            # date
            ok &= data_map.get("date") == "2024-01-07"
            # integers and floats
            # total_calls
            ok &= int(float(data_map.get("total_calls", ""))) == int(expected_stats["total_calls"])
            # avg_response_minutes - float with 1 decimal
            avg_val = float(str(data_map.get("avg_response_minutes", "")).lstrip("+"))
            ok &= abs(avg_val - float(expected_stats["avg_response_minutes"])) < 1e-6
            # total_naloxone_doses
            doses_val = float(str(data_map.get("total_naloxone_doses", "")).lstrip("+"))
            ok &= abs(doses_val - float(expected_stats["total_naloxone_doses"])) < 1e-6
            # counts
            ok &= int(float(data_map.get("revived_count", ""))) == int(expected_stats["revived_count"])
            ok &= int(float(data_map.get("transported_count", ""))) == int(expected_stats["transported_count"])
            ok &= int(float(data_map.get("declined_count", ""))) == int(expected_stats["declined_count"])
            # percent change
            pct_field = data_map.get("percent_change_calls_vs_last_week", "")
            if expected_stats["percent_change_calls_vs_last_week"] == "NA":
                ok &= pct_field.strip().upper() == "NA"
            else:
                try:
                    pct_val = float(str(pct_field).lstrip("+"))
                    ok &= abs(pct_val - float(expected_stats["percent_change_calls_vs_last_week"])) < 1e-6
                except Exception:
                    ok = False
            scores["summary_values_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["summary_values_correct"] = 0.0
    else:
        scores["summary_values_correct"] = 0.0

    # 2) Message checks
    msg_text = _read_text_safe(message_path) if message_path.exists() else None
    if msg_text is not None:
        # Constraints: single paragraph, no bullet points, under max_chars
        constraints_ok = True
        stripped = msg_text.strip()
        # Single paragraph: no blank lines; treat multiple lines without empty separators as one paragraph allowed; require exactly one paragraph block.
        paragraphs = [p for p in re.split(r'\n\s*\n', stripped) if p.strip() != ""]
        if len(paragraphs) != 1:
            constraints_ok = False
        # No bullet points: lines starting with -, *, •
        for line in stripped.splitlines():
            if re.match(r'^\s*[-*\u2022]\s+', line):
                constraints_ok = False
                break
        # Under char limit
        max_chars = None
        if cfg and "message" in cfg and isinstance(cfg["message"], dict) and "max_chars" in cfg["message"]:
            try:
                max_chars = int(float(cfg["message"]["max_chars"]))
            except Exception:
                max_chars = None
        if max_chars is not None:
            if len(stripped) > max_chars:
                constraints_ok = False
        # Reasonable length > 0
        if len(stripped) == 0:
            constraints_ok = False
        scores["message_file_present_and_constraints"] = 1.0 if constraints_ok else 0.0

        # Includes metrics: calls, percent change, avg minutes, doses
        # Use context keywords to detect association
        metrics_ok_count = 0
        total_required = 4
        if expected_stats is not None:
            # calls
            calls_ok = _extract_numbers_near(stripped, [r'calls?', r'\bcalls?\b'], float(expected_stats["total_calls"]), window=50)
            # doses
            doses_ok = _extract_numbers_near(stripped, [r'doses?', r'\bdose\b'], float(expected_stats["total_naloxone_doses"]), window=50)
            # avg minutes: look near "min", "minute", "response"
            avg_expected = float(expected_stats["avg_response_minutes"])
            avg_ok = _extract_numbers_near(stripped, [r'\bmin(?:ute)?s?\b', r'\bresponse\b', r'\bavg\b', r'\baverage\b'], avg_expected, window=50)
            # percent change: look for % or 'percent'
            pct_ok = False
            pct_val = expected_stats["percent_change_calls_vs_last_week"]
            if pct_val != "NA":
                # Accept forms near % or percent
                pct_ok = _extract_numbers_near(stripped, [r'%', r'percent'], float(pct_val), window=50)
            else:
                pct_ok = True  # If no reference, they might include "NA"; consider satisfied
            metrics_ok_count += 1 if calls_ok else 0
            metrics_ok_count += 1 if pct_ok else 0
            metrics_ok_count += 1 if avg_ok else 0
            metrics_ok_count += 1 if doses_ok else 0
        # Partial credit
        scores["message_includes_metrics"] = metrics_ok_count / total_required if total_required > 0 else 0.0

        # Alert request if total_calls >= threshold_alert
        alert_req_ok = False
        if expected_stats is not None and cfg is not None and "threshold_alert" in cfg:
            try:
                threshold = float(cfg["threshold_alert"])
                if expected_stats["total_calls"] >= threshold:
                    # Must contain a short request for extra volunteers for Friday outreach
                    # Check for 'Friday' and 'volunteer' (case-insensitive)
                    lower = stripped.lower()
                    contains_friday = "friday" in lower
                    contains_volunteer = "volunteer" in lower
                    alert_req_ok = contains_friday and contains_volunteer
                else:
                    # If not over threshold, do not require
                    alert_req_ok = True
            except Exception:
                alert_req_ok = False
        scores["message_includes_alert_request"] = 1.0 if alert_req_ok else 0.0
    else:
        scores["message_file_present_and_constraints"] = 0.0
        scores["message_includes_metrics"] = 0.0
        scores["message_includes_alert_request"] = 0.0

    # 3) Config log checks
    log_text = _read_text_safe(config_log_path) if config_log_path.exists() else None
    if log_text is not None:
        scores["config_log_present"] = 1.0
        lower_log = log_text.lower()

        # Keys checklist: watch_dir, file_glob, threshold_alert, message.max_chars
        keys_ok = all([
            "watch_dir" in lower_log,
            "file_glob" in lower_log,
            "threshold_alert" in lower_log,
            ("message.max_chars" in lower_log) or ("message" in lower_log and "max_chars" in lower_log),
        ])
        scores["config_log_keys_checklist"] = 1.0 if keys_ok else 0.0

        # Watch dir exists or was created and match count
        watch_dir_ok = False
        # any line with 'watch_dir' and ('exist' or 'created')
        for line in lower_log.splitlines():
            if "watch_dir" in line and ("exist" in line or "created" in line or "exists" in line):
                watch_dir_ok = True
                break

        # match count extraction
        match_count_in_log: Optional[int] = None
        for line in lower_log.splitlines():
            if "match" in line:  # matches/matched/matching
                nums = re.findall(r'\b\d+\b', line)
                if nums:
                    # choose the last number on the last matching line to avoid incidental numbers
                    match_count_in_log = int(nums[-1])
        # Compute actual matches based on config
        actual_match_count: Optional[int] = None
        if cfg is not None and "watch_dir" in cfg and "file_glob" in cfg:
            watch_dir_path = workspace / cfg["watch_dir"]
            try:
                pattern = cfg["file_glob"]
                if watch_dir_path.exists():
                    actual_match_count = len(list(watch_dir_path.glob(pattern)))
                else:
                    actual_match_count = 0
            except Exception:
                actual_match_count = None

        match_count_ok = False
        if match_count_in_log is not None and actual_match_count is not None:
            match_count_ok = (match_count_in_log == actual_match_count)
        # Prefer strict result of 1 matched file as per task; if actual cannot be computed but log says 1, accept partial
        config_watch_and_match_ok = watch_dir_ok and match_count_ok
        scores["config_log_watch_dir_and_match_count"] = 1.0 if config_watch_and_match_ok else 0.0

        # Types validation: ensure types checked, especially threshold_alert numeric
        types_ok = False
        # look for 'type', 'numeric', 'number', 'int', or 'float' mentions
        if ("type" in lower_log or "numeric" in lower_log or "number" in lower_log or "int" in lower_log or "float" in lower_log) and ("threshold_alert" in lower_log):
            types_ok = True
        # Also accept if both 'message.max_chars' and one of the type words present
        if not types_ok and ("message.max_chars" in lower_log or ("message" in lower_log and "max_chars" in lower_log)):
            if "type" in lower_log or "numeric" in lower_log or "number" in lower_log or "int" in lower_log or "float" in lower_log:
                types_ok = True
        scores["config_log_types_validation"] = 1.0 if types_ok else 0.0
    else:
        scores["config_log_present"] = 0.0
        scores["config_log_keys_checklist"] = 0.0
        scores["config_log_watch_dir_and_match_count"] = 0.0
        scores["config_log_types_validation"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()