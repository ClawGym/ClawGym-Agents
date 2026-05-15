import json
import csv
import sys
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


EXPECTED_COLUMNS = [
    "session_date",
    "track",
    "session_label",
    "total_runs",
    "best_et_s",
    "avg_et_s",
    "stdev_et_s",
    "avg_reaction_s",
    "red_light_count",
    "left_lane_runs",
    "right_lane_runs",
    "within_0.02_count",
]


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [row for row in reader]
            return list(reader.fieldnames), rows
    except Exception:
        return None, None


def _float_or_none(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _parse_bool(value: str) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return v in ("true", "1", "yes", "y", "t")


def _compute_mean(values: List[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _compute_sample_stdev(values: List[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    mean = _compute_mean(values)
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(var)


def _round3(x: float) -> float:
    return round(x, 3)


def _gather_input_runs(workspace: Path) -> Tuple[bool, Dict[str, List[Dict[str, str]]]]:
    """Return (ok, runs_by_date)"""
    logs_dir = workspace / "input" / "logs"
    runs_by_date: Dict[str, List[Dict[str, str]]] = {}
    if not logs_dir.exists():
        return False, runs_by_date
    csv_files = sorted([p for p in logs_dir.rglob("*.csv") if p.is_file()])
    if not csv_files:
        # No CSVs
        return True, runs_by_date
    for csv_path in csv_files:
        header, rows = _safe_read_csv(csv_path)
        if header is None or rows is None:
            return False, {}
        for r in rows:
            date = (r.get("session_date") or "").strip()
            if not date:
                # malformed row
                return False, {}
            runs_by_date.setdefault(date, []).append(r)
    return True, runs_by_date


def _compute_expected_summary(runs_by_date: Dict[str, List[Dict[str, str]]]) -> Dict[str, Dict[str, object]]:
    """Compute expected metrics per session_date."""
    summary: Dict[str, Dict[str, object]] = {}
    for date, rows in runs_by_date.items():
        # Track and session_label assumed consistent within a date
        tracks = {(rows[i].get("track") or "").strip() for i in range(len(rows))}
        labels = {(rows[i].get("session_label") or "").strip() for i in range(len(rows))}
        track = next(iter(tracks)) if tracks else ""
        session_label = next(iter(labels)) if labels else ""

        # numeric fields
        et_vals: List[float] = []
        rt_vals: List[float] = []
        red_count = 0
        left_count = 0
        right_count = 0
        malformed = False
        for r in rows:
            et = _float_or_none(r.get("et_s") or "")
            rt = _float_or_none(r.get("reaction_time_s") or "")
            if et is None or rt is None:
                malformed = True
                break
            et_vals.append(et)
            rt_vals.append(rt)
            if _parse_bool(r.get("red_light") or ""):
                red_count += 1
            lane = (r.get("lane") or "").strip().lower()
            if lane == "left":
                left_count += 1
            elif lane == "right":
                right_count += 1

        if malformed or not et_vals or not rt_vals:
            summary[date] = {
                "session_date": date,
                "track": track,
                "session_label": session_label,
                "total_runs": 0,
                "best_et_s": None,
                "avg_et_s": None,
                "stdev_et_s": None,
                "avg_reaction_s": None,
                "red_light_count": None,
                "left_lane_runs": None,
                "right_lane_runs": None,
                "within_0.02_count": None,
            }
            continue

        total_runs = len(rows)
        best_et = min(et_vals)
        avg_et = _compute_mean(et_vals)
        stdev_et = _compute_sample_stdev(et_vals)
        avg_rt = _compute_mean(rt_vals)

        # within 0.02 using unrounded mean
        mean_for_within = avg_et
        within_count = sum(1 for x in et_vals if abs(x - mean_for_within) <= 0.02)

        summary[date] = {
            "session_date": date,
            "track": track,
            "session_label": session_label,
            "total_runs": total_runs,
            "best_et_s": best_et,
            "avg_et_s": _round3(avg_et),
            "stdev_et_s": _round3(stdev_et),
            "avg_reaction_s": _round3(avg_rt),
            "red_light_count": red_count,
            "left_lane_runs": left_count,
            "right_lane_runs": right_count,
            "within_0.02_count": within_count,
        }
    return summary


def _load_output_summary(workspace: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    out_path = workspace / "output" / "session_summary.csv"
    if not out_path.exists():
        return False, None, None
    header, rows = _safe_read_csv(out_path)
    if header is None or rows is None:
        return False, None, None
    return True, header, rows


def _almost_equal(a: Optional[float], b: Optional[float], tol: float = 5e-4) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _parse_int_safe(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        try:
            f = float(str(s).strip())
            return int(f)
        except Exception:
            return None


def _map_summary_by_date(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for r in rows:
        date = (r.get("session_date") or "").strip()
        if date:
            result[date] = r
    return result


def _most_recent_date_str(dates: List[str]) -> Optional[str]:
    from datetime import datetime
    max_dt = None
    max_str = None
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            continue
        if max_dt is None or dt > max_dt:
            max_dt = dt
            max_str = d
    return max_str


def _parse_email_headers_and_body(text: str) -> Tuple[Dict[str, str], str]:
    # Expect simple "Key: value" lines at top; collect To, CC, From, Subject
    headers: Dict[str, str] = {}
    lines = text.splitlines()
    body_start_idx = 0
    for i, line in enumerate(lines):
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key.lower() in ("to", "cc", "from", "subject"):
                headers[key] = val
                continue
        if i > 0 and not line.strip().startswith(("To:", "CC:", "From:", "Subject:")):
            body_start_idx = i
            break
    body = "\n".join(lines[body_start_idx:]).strip()
    return headers, body


def _find_metric_value_in_text(body: str, label: str) -> Optional[float]:
    # Search lines containing the label (case-insensitive), then extract the first numeric value on that line
    pattern = re.compile(re.escape(label), re.IGNORECASE)
    for line in body.splitlines():
        if pattern.search(line):
            num_match = re.search(r"[-+]?\d+(?:\.\d+)?", line)
            if num_match:
                try:
                    return float(num_match.group(0))
                except Exception:
                    continue
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "build_script_present": 0.0,
        "session_summary_exists_and_columns": 0.0,
        "session_summary_row_coverage": 0.0,
        "session_summary_metrics_correct": 0.0,
        "latest_session_email_exists": 0.0,
        "latest_session_email_recipients_correct": 0.0,
        "latest_session_email_subject_correct": 0.0,
        "latest_session_email_body_has_session_info": 0.0,
        "latest_session_email_metrics_match_summary": 0.0,
    }

    # Check build script presence
    build_script = workspace / "tools" / "build_session_summary.py"
    if build_script.exists() and build_script.is_file():
        scores["build_script_present"] = 1.0

    # Load inputs to compute expected
    ok_inputs, runs_by_date = _gather_input_runs(workspace)
    expected_summary = _compute_expected_summary(runs_by_date) if ok_inputs else {}

    # Load output summary
    out_ok, out_header, out_rows = _load_output_summary(workspace)
    if out_ok and out_header is not None and out_rows is not None:
        # Columns check
        if out_header == EXPECTED_COLUMNS:
            scores["session_summary_exists_and_columns"] = 1.0
        else:
            scores["session_summary_exists_and_columns"] = 0.0

        # Row coverage check
        expected_dates = set(expected_summary.keys()) if ok_inputs else set()
        actual_map = _map_summary_by_date(out_rows)
        actual_dates = set(actual_map.keys())
        if expected_dates and expected_dates == actual_dates:
            scores["session_summary_row_coverage"] = 1.0
        else:
            scores["session_summary_row_coverage"] = 0.0

        # Metrics correctness check
        metrics_ok = True
        if expected_dates and actual_dates >= expected_dates:
            for date, exp in expected_summary.items():
                row = actual_map.get(date)
                if not row:
                    metrics_ok = False
                    break
                # track and session_label
                if (row.get("track") or "").strip() != (exp.get("track") or "").strip():
                    metrics_ok = False
                if (row.get("session_label") or "").strip() != (exp.get("session_label") or "").strip():
                    metrics_ok = False

                def parse_int_field(field: str) -> Optional[int]:
                    return _parse_int_safe(row.get(field) or "")

                def parse_float_field(field: str) -> Optional[float]:
                    return _parse_float_safe(row.get(field) or "")

                tr = parse_int_field("total_runs")
                rl = parse_int_field("red_light_count")
                ll = parse_int_field("left_lane_runs")
                rr = parse_int_field("right_lane_runs")
                w02 = parse_int_field("within_0.02_count")
                if tr != exp.get("total_runs"):
                    metrics_ok = False
                if rl != exp.get("red_light_count"):
                    metrics_ok = False
                if ll != exp.get("left_lane_runs"):
                    metrics_ok = False
                if rr != exp.get("right_lane_runs"):
                    metrics_ok = False
                if w02 != exp.get("within_0.02_count"):
                    metrics_ok = False

                best_et = parse_float_field("best_et_s")
                avg_et = parse_float_field("avg_et_s")
                stdev_et = parse_float_field("stdev_et_s")
                avg_rt = parse_float_field("avg_reaction_s")

                if not _almost_equal(best_et, exp.get("best_et_s")):
                    metrics_ok = False
                if not _almost_equal(avg_et, exp.get("avg_et_s")):
                    metrics_ok = False
                if not _almost_equal(stdev_et, exp.get("stdev_et_s")):
                    metrics_ok = False
                if not _almost_equal(avg_rt, exp.get("avg_reaction_s")):
                    metrics_ok = False

                if not metrics_ok:
                    break
        else:
            metrics_ok = False

        scores["session_summary_metrics_correct"] = 1.0 if metrics_ok else 0.0
    else:
        scores["session_summary_exists_and_columns"] = 0.0
        scores["session_summary_row_coverage"] = 0.0
        scores["session_summary_metrics_correct"] = 0.0

    # Email checks
    email_path = workspace / "output" / "latest_session_email.txt"
    email_text = _safe_read_text(email_path) if email_path.exists() else None
    if email_text is not None:
        scores["latest_session_email_exists"] = 1.0
        headers, body = _parse_email_headers_and_body(email_text)

        # Load contacts
        contacts = _safe_load_json(workspace / "input" / "team_contacts.json") or {}
        driver_email = (((contacts.get("driver") or {}).get("email")) or "").strip()
        crew_email = (((contacts.get("crew_chief") or {}).get("email")) or "").strip()
        analyst_email = (((contacts.get("data_analyst") or {}).get("email")) or "").strip()

        # Recipients check
        to_ok = (headers.get("To", "").strip() == crew_email) if crew_email else False
        cc_ok = (headers.get("CC", "").strip() == analyst_email) if analyst_email else False
        from_ok = (headers.get("From", "").strip() == driver_email) if driver_email else False
        if to_ok and cc_ok and from_ok:
            scores["latest_session_email_recipients_correct"] = 1.0

        # Determine most recent session date from inputs
        most_recent_date = _most_recent_date_str(sorted(expected_summary.keys())) if expected_summary else None

        # Subject check
        subject_ok = False
        out_ok2, out_header2, out_rows2 = out_ok, out_header, out_rows
        if out_ok2 and most_recent_date:
            out_map = _map_summary_by_date(out_rows2 or [])
            recent_row = out_map.get(most_recent_date)
            if recent_row:
                expected_subject = f"Session Summary - {most_recent_date} - {(recent_row.get('track') or '').strip()}"
                if (headers.get("Subject") or "").strip() == expected_subject:
                    subject_ok = True
        scores["latest_session_email_subject_correct"] = 1.0 if subject_ok else 0.0

        # Body has session info: label, date, track
        body_info_ok = False
        if out_ok and most_recent_date:
            out_map2 = _map_summary_by_date(out_rows or [])
            recent_row2 = out_map2.get(most_recent_date)
            if recent_row2:
                label = (recent_row2.get("session_label") or "").strip()
                track = (recent_row2.get("track") or "").strip()
                date_str = most_recent_date
                if label and track and date_str and (label in body) and (track in body) and (date_str in body):
                    body_info_ok = True
        scores["latest_session_email_body_has_session_info"] = 1.0 if body_info_ok else 0.0

        # Metrics in email match summary for most recent session
        metrics_match = False
        if out_ok and most_recent_date:
            out_map3 = _map_summary_by_date(out_rows or [])
            recent_row3 = out_map3.get(most_recent_date)
            if recent_row3:
                checks = [
                    ("total_runs", "int"),
                    ("best_et_s", "float"),
                    ("avg_et_s", "float"),
                    ("stdev_et_s", "float"),
                    ("avg_reaction_s", "float"),
                    ("red_light_count", "int"),
                    ("left_lane_runs", "int"),
                    ("right_lane_runs", "int"),
                    ("within_0.02_count", "int"),
                ]
                all_ok = True
                for label, typ in checks:
                    val_in_email = _find_metric_value_in_text(body, label)
                    if val_in_email is None:
                        all_ok = False
                        break
                    sv = recent_row3.get(label) or ""
                    if typ == "int":
                        expected_val = _parse_int_safe(sv)
                        if expected_val is None:
                            all_ok = False
                            break
                        if int(round(val_in_email)) != expected_val:
                            all_ok = False
                            break
                    else:
                        expected_val_f = _parse_float_safe(sv)
                        if expected_val_f is None:
                            all_ok = False
                            break
                        if not _almost_equal(val_in_email, expected_val_f, tol=5e-4):
                            all_ok = False
                            break
                metrics_match = all_ok
        scores["latest_session_email_metrics_match_summary"] = 1.0 if metrics_match else 0.0
    else:
        scores["latest_session_email_exists"] = 0.0
        scores["latest_session_email_recipients_correct"] = 0.0
        scores["latest_session_email_subject_correct"] = 0.0
        scores["latest_session_email_body_has_session_info"] = 0.0
        scores["latest_session_email_metrics_match_summary"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()