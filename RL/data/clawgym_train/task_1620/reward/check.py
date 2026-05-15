import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_iso8601(ts: str) -> Optional[datetime]:
    try:
        # Handle Z suffix
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _parse_alerts_yaml(path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Minimal YAML parser for the specific alerts.yaml structure (standard library only).
    Expects a mapping of sections with simple key: float pairs, like:
    temp:
      min_c: 12.0
      max_c: 28.0
      max_rate_c_per_hr: 1.0
    """
    text = _read_text(path)
    if text is None:
        return None
    result: Dict[str, Dict[str, float]] = {}
    current_section: Optional[str] = None
    try:
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            if not line.startswith(" ") and line.endswith(":"):
                # section header
                current_section = line[:-1].strip()
                result[current_section] = {}
            elif current_section is not None:
                # key/value within section
                # expect "  key: value"
                stripped = line.strip()
                if ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # Handle floats and ints
                    try:
                        if val.lower() in ("true", "false"):
                            # Not expected but handle gracefully
                            num_val = 1.0 if val.lower() == "true" else 0.0
                        else:
                            num_val = float(val)
                        result[current_section][key] = num_val
                    except Exception:
                        # If value is not numeric, skip parsing; invalid for our needs
                        return None
                else:
                    # Malformed line in section
                    return None
            else:
                # Found key-value without a section
                return None
        return result
    except Exception:
        return None


def _parse_csv_rows(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    rows: List[Dict[str, Any]] = []
    try:
        reader = csv.DictReader(text.splitlines())
        expected_fields = [
            "timestamp", "batch_id", "vessel_id", "temp_c", "brix", "pH", "dissolved_oxygen_mgL"
        ]
        if reader.fieldnames is None or any(f not in reader.fieldnames for f in expected_fields):
            return None
        for r in reader:
            ts = r.get("timestamp", "")
            dt = _parse_iso8601(ts)
            if dt is None:
                return None
            try:
                temp_c = float(r["temp_c"])
                brix = float(r["brix"])
                pH = float(r["pH"])
                do = float(r["dissolved_oxygen_mgL"])
            except Exception:
                return None
            rows.append({
                "timestamp": r["timestamp"],
                "dt": dt,
                "batch_id": r["batch_id"],
                "vessel_id": r["vessel_id"],
                "temp_c": temp_c,
                "brix": brix,
                "pH": pH,
                "dissolved_oxygen_mgL": do,
            })
        return rows
    except Exception:
        return None


def _group_by_batch_sorted(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    batches: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        batches.setdefault(r["batch_id"], []).append(r)
    for b in batches.values():
        b.sort(key=lambda x: x["dt"])
    return batches


def _compute_expected_events(
    rows: List[Dict[str, Any]],
    alerts: Dict[str, Dict[str, float]],
    source_file: str
) -> List[Dict[str, Any]]:
    """
    Compute expected events according to specification.
    """
    temp_min = alerts.get("temp", {}).get("min_c")
    temp_max = alerts.get("temp", {}).get("max_c")
    temp_max_rate = alerts.get("temp", {}).get("max_rate_c_per_hr")
    brix_min_drop = alerts.get("brix_drop", {}).get("min_drop_per_hr")
    pH_min = alerts.get("pH", {}).get("min")
    pH_max = alerts.get("pH", {}).get("max")
    do_max = alerts.get("dissolved_oxygen", {}).get("max_mgL")

    # Fall back to required default for temp.max_rate_c_per_hr if missing
    if temp_max_rate is None:
        temp_max_rate = 1.0

    events: List[Dict[str, Any]] = []
    # Single-reading events
    for r in rows:
        # temp_out_of_range
        if temp_min is not None and r["temp_c"] < temp_min:
            events.append({
                "source_file": source_file,
                "batch_id": r["batch_id"],
                "timestamp": r["timestamp"],
                "event_type": "temp_out_of_range",
                "metric": "temp_c",
                "value": r["temp_c"],
                "threshold": temp_min,
            })
        elif temp_max is not None and r["temp_c"] > temp_max:
            events.append({
                "source_file": source_file,
                "batch_id": r["batch_id"],
                "timestamp": r["timestamp"],
                "event_type": "temp_out_of_range",
                "metric": "temp_c",
                "value": r["temp_c"],
                "threshold": temp_max,
            })
        # pH_out_of_range
        if pH_min is not None and r["pH"] < pH_min:
            events.append({
                "source_file": source_file,
                "batch_id": r["batch_id"],
                "timestamp": r["timestamp"],
                "event_type": "pH_out_of_range",
                "metric": "pH",
                "value": r["pH"],
                "threshold": pH_min,
            })
        elif pH_max is not None and r["pH"] > pH_max:
            events.append({
                "source_file": source_file,
                "batch_id": r["batch_id"],
                "timestamp": r["timestamp"],
                "event_type": "pH_out_of_range",
                "metric": "pH",
                "value": r["pH"],
                "threshold": pH_max,
            })
        # oxygen_high
        if do_max is not None and r["dissolved_oxygen_mgL"] > do_max:
            events.append({
                "source_file": source_file,
                "batch_id": r["batch_id"],
                "timestamp": r["timestamp"],
                "event_type": "oxygen_high",
                "metric": "dissolved_oxygen_mgL",
                "value": r["dissolved_oxygen_mgL"],
                "threshold": do_max,
            })

    # Pair-based events
    batches = _group_by_batch_sorted(rows)
    for batch_id, readings in batches.items():
        for i in range(1, len(readings)):
            prev = readings[i - 1]
            curr = readings[i]
            dt_hours = (curr["dt"] - prev["dt"]).total_seconds() / 3600.0
            # Skip zero or negative intervals
            if dt_hours <= 0:
                continue
            # rapid_temp_rise: only consider increases
            delta_temp = curr["temp_c"] - prev["temp_c"]
            if delta_temp > 0 and temp_max_rate is not None:
                rate_c_per_hr = delta_temp / dt_hours
                if rate_c_per_hr > temp_max_rate:
                    events.append({
                        "source_file": source_file,
                        "batch_id": batch_id,
                        "timestamp": curr["timestamp"],  # later reading timestamp
                        "event_type": "rapid_temp_rise",
                        "metric": "temp_rate_c_per_hr",
                        "value": rate_c_per_hr,
                        "threshold": temp_max_rate,
                    })
            # brix_drop_below_min: only evaluate when later reading has lower Brix
            if curr["brix"] < prev["brix"] and brix_min_drop is not None:
                delta_brix = prev["brix"] - curr["brix"]
                rate_brix_per_hr = delta_brix / dt_hours
                if rate_brix_per_hr < brix_min_drop:
                    events.append({
                        "source_file": source_file,
                        "batch_id": batch_id,
                        "timestamp": curr["timestamp"],  # later reading timestamp
                        "event_type": "brix_drop_below_min",
                        "metric": "brix_drop_per_hr",
                        "value": rate_brix_per_hr,
                        "threshold": brix_min_drop,
                    })
    return events


def _load_events_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    results: List[Dict[str, Any]] = []
    try:
        for ln in lines:
            obj = json.loads(ln)
            if not isinstance(obj, dict):
                return None
            results.append(obj)
        return results
    except Exception:
        return None


def _validate_events_schema(
    events: List[Dict[str, Any]],
    expected_source_basename: str
) -> bool:
    required_keys = {"source_file", "batch_id", "timestamp", "event_type", "metric", "value", "threshold"}
    allowed_types = {
        "temp_out_of_range": "temp_c",
        "rapid_temp_rise": "temp_rate_c_per_hr",
        "pH_out_of_range": "pH",
        "oxygen_high": "dissolved_oxygen_mgL",
        "brix_drop_below_min": "brix_drop_per_hr",
    }
    for ev in events:
        if set(ev.keys()) != required_keys and not required_keys.issubset(set(ev.keys())):
            return False
        # Types and values
        if ev.get("event_type") not in allowed_types:
            return False
        expected_metric = allowed_types[ev["event_type"]]
        if ev.get("metric") != expected_metric:
            return False
        # Numeric checks
        try:
            float(ev.get("value"))
            float(ev.get("threshold"))
        except Exception:
            return False
        # timestamp is ISO-8601
        if _parse_iso8601(str(ev.get("timestamp"))) is None:
            return False
        # source_file should end with basename or equal to path
        sf = str(ev.get("source_file"))
        if not (sf.endswith(expected_source_basename) or sf == f"input/incoming/{expected_source_basename}"):
            # Allow also absolute or other relative paths ending with the basename
            if Path(sf).name != expected_source_basename:
                return False
    return True


def _events_key(ev: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(ev.get("event_type")), str(ev.get("batch_id")), str(ev.get("timestamp")))


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _count_events_by_type(events: List[Dict[str, Any]]) -> Dict[str, int]:
    tally: Dict[str, int] = {}
    for ev in events:
        et = str(ev.get("event_type"))
        tally[et] = tally.get(et, 0) + 1
    return tally


def _find_processed_files(path: Path) -> Optional[List[str]]:
    data = _safe_json_load(path)
    if data is None:
        return None
    try:
        # Accept simple list of strings
        if isinstance(data, list):
            return [str(x) for x in data]
        elif isinstance(data, dict):
            # Accept {"files": [...]} or {"processed": [...]}
            if "files" in data and isinstance(data["files"], list):
                return [str(x) for x in data["files"]]
            if "processed" in data and isinstance(data["processed"], list):
                return [str(x) for x in data["processed"]]
        return None
    except Exception:
        return None


def _report_contains_counts(md: str, total_readings: int, unique_batches: int) -> bool:
    import re
    md_lower = md.lower()
    # Total readings processed
    total_match = re.search(r"total.*readings.*processed.*?(\d+)", md_lower)
    unique_match = re.search(r"unique.*batches.*?(\d+)", md_lower)
    if not total_match or not unique_match:
        return False
    try:
        total_val = int(total_match.group(1))
        unique_val = int(unique_match.group(1))
        return total_val == total_readings and unique_val == unique_batches
    except Exception:
        return False


def _extract_event_tally_from_report(md: str, event_types: List[str]) -> Dict[str, Optional[int]]:
    """
    Attempt to extract tally counts from markdown for the given event types.
    Looks for lines mentioning the event type and a number, choosing the first found number.
    """
    import re
    lines = md.splitlines()
    results: Dict[str, Optional[int]] = {et: None for et in event_types}
    for et in event_types:
        pattern = re.compile(rf"{re.escape(et)}.*?(\d+)", re.IGNORECASE)
        counts: List[int] = []
        for ln in lines:
            m = pattern.search(ln)
            if m:
                try:
                    counts.append(int(m.group(1)))
                except Exception:
                    pass
        if counts:
            # Prefer the maximum number found to avoid counting bullets
            results[et] = max(counts)
    return results


def _bulleted_events_coverage(md: str, expected_events: List[Dict[str, Any]]) -> float:
    """
    Check coverage of expected events in report bullets (lines starting with '-' or '*').
    A match requires the bullet line to contain both the event_type and timestamp.
    """
    lines = md.splitlines()
    bullets = [ln for ln in lines if ln.strip().startswith(("-", "*"))]
    matched = 0
    for ev in expected_events:
        et = ev["event_type"]
        ts = ev["timestamp"]
        found = any((et in b and ts in b) for b in bullets)
        if found:
            matched += 1
    total = len(expected_events)
    return (matched / total) if total > 0 else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_updated_temp_max_rate": 0.0,
        "state_processed_files_contains_csv": 0.0,
        "events_file_schema_valid": 0.0,
        "events_expected_presence_ratio": 0.0,
        "events_exact_count_match": 0.0,
        "rapid_temp_rise_threshold_used_in_events": 0.0,
        "report_contains_date_and_counts": 0.0,
        "report_contains_batch_ids": 0.0,
        "report_events_tally_correctness_ratio": 0.0,
        "report_bulleted_events_coverage_ratio": 0.0,
    }

    # Paths
    csv_path = workspace / "input" / "incoming" / "fermentation_2025-04-18.csv"
    config_path = workspace / "config" / "alerts.yaml"
    events_path = workspace / "logs" / "events.jsonl"
    state_path = workspace / "state" / "processed_files.json"
    report_path = workspace / "reports" / "daily_status.md"

    expected_source_basename = "fermentation_2025-04-18.csv"
    expected_source_file = f"input/incoming/{expected_source_basename}"

    # Config check: verify temp.max_rate_c_per_hr == 1.0
    alerts = _parse_alerts_yaml(config_path)
    if alerts is not None:
        temp_section = alerts.get("temp", {})
        max_rate = temp_section.get("max_rate_c_per_hr")
        if max_rate is not None and _float_close(max_rate, 1.0):
            scores["config_updated_temp_max_rate"] = 1.0

    # Parse CSV for recomputation
    csv_rows = _parse_csv_rows(csv_path)
    # fallbacks if CSV missing
    total_readings = len(csv_rows) if csv_rows is not None else 0
    unique_batches_count = 0
    batch_ids: List[str] = []
    expected_events: List[Dict[str, Any]] = []
    if csv_rows is not None:
        batch_ids = sorted(list({r["batch_id"] for r in csv_rows}))
        unique_batches_count = len(batch_ids)
        if alerts is None:
            # Attempt with required defaults if config missing
            alerts = {
                "temp": {"min_c": 12.0, "max_c": 28.0, "max_rate_c_per_hr": 1.0},
                "brix_drop": {"min_drop_per_hr": 0.05},
                "pH": {"min": 3.1, "max": 3.9},
                "dissolved_oxygen": {"max_mgL": 1.0},
            }
        expected_events = _compute_expected_events(csv_rows, alerts, expected_source_file)

    # State check
    processed_list = _find_processed_files(state_path)
    if processed_list is not None:
        # Accept membership if path or basename appears
        normalized = set(processed_list)
        if (expected_source_file in normalized) or (expected_source_basename in normalized) or any(
            Path(p).name == expected_source_basename for p in normalized
        ):
            scores["state_processed_files_contains_csv"] = 1.0

    # Events file checks
    actual_events = _load_events_jsonl(events_path)
    if actual_events is not None:
        if _validate_events_schema(actual_events, expected_source_basename):
            scores["events_file_schema_valid"] = 1.0

        # Compare expected vs actual
        expected_keys = {_events_key(ev) for ev in expected_events}
        actual_keys = {_events_key(ev) for ev in actual_events}
        intersect = expected_keys.intersection(actual_keys)
        presence_ratio = (len(intersect) / len(expected_keys)) if expected_keys else 0.0
        scores["events_expected_presence_ratio"] = presence_ratio

        # Exact count match
        scores["events_exact_count_match"] = 1.0 if len(actual_events) == len(expected_events) else 0.0

        # Verify metrics, values, thresholds for matched keys
        expected_map = { _events_key(ev): ev for ev in expected_events }
        actual_map = { _events_key(ev): ev for ev in actual_events }
        # Also check rapid_temp_rise threshold usage
        rapid_ok = False
        for k in intersect:
            exp_ev = expected_map[k]
            act_ev = actual_map[k]
            # metric name equal
            metric_ok = (exp_ev["metric"] == act_ev.get("metric"))
            # numeric values close
            try:
                v_ok = _float_close(float(exp_ev["value"]), float(act_ev.get("value")))
                t_ok = _float_close(float(exp_ev["threshold"]), float(act_ev.get("threshold")))
            except Exception:
                v_ok = False
                t_ok = False
            # count rapid threshold usage
            if exp_ev["event_type"] == "rapid_temp_rise" and t_ok and _float_close(float(act_ev.get("threshold")), 1.0):
                rapid_ok = True
            # We don't score these individually; rapid_ok scored separately below

        scores["rapid_temp_rise_threshold_used_in_events"] = 1.0 if rapid_ok else 0.0

    # Report checks
    report_text = _read_text(report_path)
    if report_text is not None:
        # Date presence
        has_date = "2025-04-18" in report_text
        counts_ok = _report_contains_counts(report_text, total_readings, unique_batches_count) if csv_rows is not None else False
        if has_date and counts_ok:
            scores["report_contains_date_and_counts"] = 1.0

        # Batch IDs presence
        if batch_ids:
            present = all(b in report_text for b in batch_ids)
            scores["report_contains_batch_ids"] = 1.0 if present else 0.0

        # Tally correctness ratio
        event_types = ["temp_out_of_range", "rapid_temp_rise", "pH_out_of_range", "oxygen_high", "brix_drop_below_min"]
        expected_tally = _count_events_by_type(expected_events)
        extracted_tally = _extract_event_tally_from_report(report_text, event_types)
        correct = 0
        total_types = len(event_types)
        for et in event_types:
            found = extracted_tally.get(et)
            if found is not None and expected_tally.get(et, 0) == found:
                correct += 1
        scores["report_events_tally_correctness_ratio"] = (correct / total_types) if total_types > 0 else 0.0

        # Bulleted events coverage ratio
        scores["report_bulleted_events_coverage_ratio"] = _bulleted_events_coverage(report_text, expected_events) if expected_events else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()