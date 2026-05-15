import json
import csv
import sys
import subprocess
import shlex
from pathlib import Path
from statistics import median


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_strict(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _run_checker(workspace: Path):
    """
    Run: python input/noise_checker.py input/party_noise.csv
    Capture stdout+stderr merged, and exit code. Return (exit_code, lines:list[str]).
    """
    script = workspace / "input" / "noise_checker.py"
    csv_path = workspace / "input" / "party_noise.csv"
    if not script.exists() or not csv_path.exists():
        return None, None
    cmd = [sys.executable, str(script), str(csv_path.relative_to(workspace) if csv_path.is_relative_to(workspace) else csv_path)]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        out = proc.stdout or ""
        lines = out.splitlines()
        return proc.returncode, lines
    except Exception:
        return None, None


def _parse_log_metrics(lines):
    """
    Given merged log lines, compute:
    - total_lines
    - info_count, warning_count, error_count
    - unique_messages: {"WARNING":[...], "ERROR":[...]} with texts after prefixes (trim leading space)
    """
    total_lines = len(lines)
    info = 0
    warn = 0
    err = 0
    warn_msgs = []
    err_msgs = []
    seen_warn = set()
    seen_err = set()
    for ln in lines:
        if ln.startswith("INFO:"):
            info += 1
        elif ln.startswith("WARNING:"):
            warn += 1
            msg = ln[len("WARNING:"):].lstrip()
            if msg not in seen_warn:
                seen_warn.add(msg)
                warn_msgs.append(msg)
        elif ln.startswith("ERROR:"):
            err += 1
            msg = ln[len("ERROR:"):].lstrip()
            if msg not in seen_err:
                seen_err.add(msg)
                err_msgs.append(msg)
    return {
        "total_lines": total_lines,
        "info_count": info,
        "warning_count": warn,
        "error_count": err,
        "unique_messages": {
            "WARNING": warn_msgs,
            "ERROR": err_msgs,
        },
    }


def _compute_expected_stats_from_input_csv(csv_path: Path):
    """
    Compute per-room stats using only valid readings (non-negative numeric).
    Returns dict: room -> {
        'n_readings', 'mean_dB', 'median_dB', 'max_dB',
        'count_ge85', 'count_ge95', 'pct_ge85', 'pct_ge95'
    }
    """
    header, rows = _parse_csv_strict(csv_path)
    if header is None or rows is None:
        return None
    expected_headers = ["timestamp", "room", "decibel"]
    if sorted(header or []) != sorted(expected_headers):
        # We'll still attempt to read fields by name; if missing, fail
        return None
    by_room = {}
    for row in rows:
        room = (row.get("room") or "").strip()
        raw = (row.get("decibel") or "").strip()
        try:
            value = float(raw)
        except Exception:
            continue
        if value < 0:
            continue
        if not room:
            continue
        by_room.setdefault(room, []).append(value)
    stats = {}
    for room, values in by_room.items():
        if not values:
            continue
        n = len(values)
        mean_val = sum(values) / n
        med_val = median(values)
        max_val = max(values)
        ge85 = sum(1 for v in values if v >= 85.0)
        ge95 = sum(1 for v in values if v >= 95.0)
        stats[room] = {
            "n_readings": n,
            "mean_dB": mean_val,
            "median_dB": med_val,
            "max_dB": max_val,
            "count_ge85": ge85,
            "count_ge95": ge95,
            "pct_ge85": ge85 / n if n else 0.0,
            "pct_ge95": ge95 / n if n else 0.0,
        }
    return stats


def _load_student_stats(stats_path: Path):
    header, rows = _parse_csv_strict(stats_path)
    if header is None or rows is None:
        return None, None
    expected_header = [
        "room",
        "n_readings",
        "mean_dB",
        "median_dB",
        "max_dB",
        "count_ge85",
        "count_ge95",
        "pct_ge85",
        "pct_ge95",
    ]
    if header != expected_header:
        return None, None
    out = {}
    for row in rows:
        try:
            room = row["room"]
            n = int(row["n_readings"])
            mean_val = float(row["mean_dB"])
            med_val = float(row["median_dB"])
            max_val = float(row["max_dB"])
            ge85 = int(row["count_ge85"])
            ge95 = int(row["count_ge95"])
            pct85 = float(row["pct_ge85"])
            pct95 = float(row["pct_ge95"])
        except Exception:
            return None, None
        out[room] = {
            "n_readings": n,
            "mean_dB": mean_val,
            "median_dB": med_val,
            "max_dB": max_val,
            "count_ge85": ge85,
            "count_ge95": ge95,
            "pct_ge85": pct85,
            "pct_ge95": pct95,
        }
    return expected_header, out


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w.strip()])


def _contains_number_three(text: str) -> bool:
    import re
    # Check digit 3
    if re.search(r'\b3\b', text):
        return True
    # Check word 'three'
    if re.search(r'\bthree\b', text, flags=re.IGNORECASE):
        return True
    return False


def _mentions_loud_room_statement(text: str) -> bool:
    # Check that both rooms are mentioned somewhere
    lower = text.lower()
    has_living = ("living room" in lower) or ("living_room" in lower)
    has_kitchen = "kitchen" in lower
    if not (has_living and has_kitchen):
        return False
    # Split into simple sentences
    import re
    sentences = re.split(r'[.!?\n]+', lower)
    for s in sentences:
        if ("living room" in s) or ("living_room" in s):
            if (("more" in s) or ("most" in s) or ("higher" in s) or ("often" in s) or ("usually" in s) or ("frequent" in s)):
                if ("loud" in s) or ("often" in s) or ("louder" in s):
                    return True
    # If not found via sentence heuristic, fallback: presence of 'loud' with 'more' anywhere
    if ("loud" in lower or "louder" in lower) and ("more" in lower or "higher" in lower or "often" in lower or "most" in lower):
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "noise_checker_log_exists_and_merged": 0.0,
        "log_analysis_matches_log_and_exit_code": 0.0,
        "log_content_matches_expected": 0.0,
        "decibel_stats_correct": 0.0,
        "spikes_consistent_between_stats_and_log": 0.0,
        "kid_summary_length_and_tone": 0.0,
        "kid_summary_loud_room_statement": 0.0,
        "kid_summary_spike_count_mentioned": 0.0,
        "kid_summary_data_issues_mentioned": 0.0,
    }

    # Paths
    log_path = workspace / "output" / "noise_checker_raw.log"
    analysis_path = workspace / "output" / "log_analysis.json"
    stats_path = workspace / "output" / "decibel_stats.csv"
    kid_path = workspace / "output" / "kid_friendly_summary.txt"
    input_csv = workspace / "input" / "party_noise.csv"
    input_checker = workspace / "input" / "noise_checker.py"

    # Load student's log
    log_text = _read_text(log_path)
    if log_text is not None:
        log_lines = log_text.splitlines()
    else:
        log_lines = None

    # Check log exists and contains merged stdout+stderr (presence of INFO, WARNING, ERROR)
    if log_lines is not None and len(log_lines) > 0:
        has_info = any(ln.startswith("INFO:") for ln in log_lines)
        has_warning = any(ln.startswith("WARNING:") for ln in log_lines)
        has_error = any(ln.startswith("ERROR:") for ln in log_lines)
        if has_info and has_warning and has_error:
            scores["noise_checker_log_exists_and_merged"] = 1.0

    # Run checker to get expected output and exit code
    exp_exit_code, exp_lines = _run_checker(workspace)

    # Validate log content matches expected
    if log_lines is not None and exp_lines is not None:
        # Compare exact lines after stripping trailing newlines (already splitlines)
        if log_lines == exp_lines:
            scores["log_content_matches_expected"] = 1.0

    # Validate log_analysis.json against student's log and exit code
    analysis = _load_json(analysis_path)
    if analysis is not None and log_lines is not None:
        # Structure checks
        keys_ok = all(k in analysis for k in ["exit_code", "total_lines", "info_count", "warning_count", "error_count", "unique_messages"])
        um = analysis.get("unique_messages") if isinstance(analysis, dict) else None
        um_ok = isinstance(um, dict) and "WARNING" in um and "ERROR" in um and isinstance(um.get("WARNING"), list) and isinstance(um.get("ERROR"), list)
        if keys_ok and um_ok:
            metrics = _parse_log_metrics(log_lines)
            counts_match = (
                analysis.get("total_lines") == metrics["total_lines"] and
                analysis.get("info_count") == metrics["info_count"] and
                analysis.get("warning_count") == metrics["warning_count"] and
                analysis.get("error_count") == metrics["error_count"]
            )
            # unique messages: compare as sets to avoid order sensitivity
            um_warn_set_student = set(um.get("WARNING", []))
            um_err_set_student = set(um.get("ERROR", []))
            um_warn_set_from_log = set(metrics["unique_messages"]["WARNING"])
            um_err_set_from_log = set(metrics["unique_messages"]["ERROR"])
            unique_match = (um_warn_set_student == um_warn_set_from_log) and (um_err_set_student == um_err_set_from_log)
            # exit code: should match actual run if we were able to run, else at least be int
            exit_ok = isinstance(analysis.get("exit_code"), int)
            if exp_exit_code is not None:
                exit_ok = exit_ok and (analysis.get("exit_code") == exp_exit_code)
            if counts_match and unique_match and exit_ok:
                scores["log_analysis_matches_log_and_exit_code"] = 1.0

    # Validate decibel_stats.csv correctness against expected computed from input csv
    expected_stats = _compute_expected_stats_from_input_csv(input_csv) if input_csv.exists() else None
    header, student_stats = _load_student_stats(stats_path)
    if expected_stats is not None and student_stats is not None:
        # Must have exactly two rooms and both present
        rooms_ok = set(student_stats.keys()) == set(expected_stats.keys())
        values_ok = True
        if rooms_ok:
            for room, exp in expected_stats.items():
                stu = student_stats.get(room, {})
                # Integers exact match
                if stu.get("n_readings") != exp["n_readings"]:
                    values_ok = False
                    break
                if stu.get("count_ge85") != exp["count_ge85"]:
                    values_ok = False
                    break
                if stu.get("count_ge95") != exp["count_ge95"]:
                    values_ok = False
                    break
                # Floats with tolerance
                if not _almost_equal(stu.get("mean_dB", 0.0), exp["mean_dB"]):
                    values_ok = False
                    break
                if not _almost_equal(stu.get("median_dB", 0.0), exp["median_dB"]):
                    values_ok = False
                    break
                if not _almost_equal(stu.get("max_dB", 0.0), exp["max_dB"]):
                    values_ok = False
                    break
                if not _almost_equal(stu.get("pct_ge85", 0.0), exp["pct_ge85"]):
                    values_ok = False
                    break
                if not _almost_equal(stu.get("pct_ge95", 0.0), exp["pct_ge95"]):
                    values_ok = False
                    break
        else:
            values_ok = False
        if values_ok:
            scores["decibel_stats_correct"] = 1.0

    # Consistency between stats and log warnings: sum count_ge95 equals warning_count
    if student_stats is not None and analysis is not None:
        try:
            total_spikes = sum(v["count_ge95"] for v in student_stats.values())
            warn_count = int(analysis.get("warning_count"))
            if total_spikes == warn_count:
                scores["spikes_consistent_between_stats_and_log"] = 1.0
        except Exception:
            pass

    # Kid-friendly summary checks
    kid_text = _read_text(kid_path)
    if kid_text is not None:
        wc = _word_count(kid_text)
        # Length 120-180 inclusive, and must not include words "ERROR" or "WARNING" (uppercase as specified)
        no_banned = ("ERROR" not in kid_text) and ("WARNING" not in kid_text)
        if 120 <= wc <= 180 and no_banned:
            scores["kid_summary_length_and_tone"] = 1.0
        # Loud room statement
        if _mentions_loud_room_statement(kid_text):
            scores["kid_summary_loud_room_statement"] = 1.0
        # Spike count mentioned (3)
        if _contains_number_three(kid_text):
            scores["kid_summary_spike_count_mentioned"] = 1.0
        # Data issues mentioned in plain language
        lower = kid_text.lower()
        issues_terms = ["missing", "non-numeric", "not a number", "negative", "impossible", "invalid", "bad number", "data issue", "problem"]
        if any(term in lower for term in issues_terms):
            scores["kid_summary_data_issues_mentioned"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()