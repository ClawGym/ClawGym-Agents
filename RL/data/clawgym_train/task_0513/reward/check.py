import json
import csv
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
        return header
    except Exception:
        return None


def _parse_invalid_ids_from_report(text: str) -> Set[str]:
    invalid_ids: Set[str] = set()
    for line in text.splitlines():
        if line.startswith("ERROR record_id="):
            # Format: ERROR record_id=<rid>: <message>
            try:
                after_eq = line.split("ERROR record_id=", 1)[1]
                rid = after_eq.split(":", 1)[0].strip()
                if rid:
                    invalid_ids.add(rid)
            except Exception:
                continue
    return invalid_ids


def _run_validator(workspace: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Run the provided validator and return (stdout_text, error_message).
    """
    script = workspace / "tools" / "validate_logs.py"
    csv_path = workspace / "input" / "operational_logs_1964.csv"
    if not script.exists() or not csv_path.exists():
        return None, "missing_script_or_input"
    try:
        res = subprocess.run(
            [sys.executable, str(script), str(csv_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace),
            timeout=10,
            check=False,
            text=True,
        )
        # We only care about stdout verbatim
        return res.stdout, None
    except Exception as e:
        return None, f"exception:{e}"


def _parse_time_hhmm(t: str) -> Optional[int]:
    try:
        dt = datetime.strptime(t, "%H:%M")
        return dt.hour * 60 + dt.minute
    except Exception:
        return None


def _compute_expected_invalid_ids(workspace: Path) -> Optional[Set[str]]:
    stdout_text, err = _run_validator(workspace)
    if stdout_text is None:
        return None
    return _parse_invalid_ids_from_report(stdout_text)


def _filter_expected_valid_records(rows: List[Dict[str, str]], invalid_ids: Set[str]) -> List[Dict[str, str]]:
    return [r for r in rows if r.get("record_id", "") not in invalid_ids]


def _sorted_by_date_then_train(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # date is YYYY-MM-DD, so lexicographic sort works for date; train_id sort lexicographic
    return sorted(rows, key=lambda r: (r.get("date", ""), r.get("train_id", "")))


def _compute_arrival_delays(rows: List[Dict[str, str]]) -> Dict[str, int]:
    """
    Compute arrival_delay_minutes for each record by record_id.
    Returns dict mapping record_id -> delay_minutes (int).
    If parsing fails for a row, it will be omitted from the dict.
    """
    delays: Dict[str, int] = {}
    for r in rows:
        rid = str(r.get("record_id", "")).strip()
        sa = r.get("scheduled_arrival", "")
        aa = r.get("actual_arrival", "")
        m_sa = _parse_time_hhmm(sa)
        m_aa = _parse_time_hhmm(aa)
        if rid and m_sa is not None and m_aa is not None:
            delays[rid] = m_aa - m_sa
    return delays


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_report_verbatim": 0.0,
        "invalid_ids_consistent_with_validator": 0.0,
        "cleaned_logs_filtering_and_header": 0.0,
        "cleaned_logs_sorted_by_date_then_train": 0.0,
        "summary_json_totals_and_on_time_rate": 0.0,
        "summary_json_per_class_aggregates": 0.0,
        "top10_arrival_delays_correct": 0.0,
    }

    input_csv = workspace / "input" / "operational_logs_1964.csv"
    validator_script = workspace / "tools" / "validate_logs.py"
    report_path = workspace / "outputs" / "logs" / "validation_report.txt"
    cleaned_path = workspace / "outputs" / "analysis" / "cleaned_logs.csv"
    summary_path = workspace / "outputs" / "analysis" / "summary.json"
    top10_path = workspace / "outputs" / "analysis" / "top_10_arrival_delays.csv"

    # Baseline: load input CSV header and rows
    input_header = _read_csv_header(input_csv) if input_csv.exists() else None
    input_rows = _read_csv_dicts(input_csv) if input_csv.exists() else None

    # Run validator to get expected stdout and invalid IDs
    validator_stdout, run_err = _run_validator(workspace)
    expected_invalid_ids = _parse_invalid_ids_from_report(validator_stdout) if validator_stdout is not None else None

    # 1) Validation report verbatim check
    report_text = _read_text(report_path)
    if report_text is not None and validator_stdout is not None and report_text == validator_stdout:
        scores["validation_report_verbatim"] = 1.0
    else:
        scores["validation_report_verbatim"] = 0.0

    # 2) Invalid IDs consistent with validator
    if report_text is not None and expected_invalid_ids is not None:
        parsed_ids_from_report = _parse_invalid_ids_from_report(report_text)
        if parsed_ids_from_report == expected_invalid_ids:
            scores["invalid_ids_consistent_with_validator"] = 1.0
        else:
            scores["invalid_ids_consistent_with_validator"] = 0.0
    else:
        scores["invalid_ids_consistent_with_validator"] = 0.0

    # Prepare expected valid records and computed expectations
    expected_valid_records: Optional[List[Dict[str, str]]] = None
    expected_delays: Optional[Dict[str, int]] = None
    expected_sorted_records: Optional[List[Dict[str, str]]] = None
    if input_rows is not None and expected_invalid_ids is not None:
        expected_valid_records = _filter_expected_valid_records(input_rows, expected_invalid_ids)
        expected_sorted_records = _sorted_by_date_then_train(expected_valid_records)
        expected_delays = _compute_arrival_delays(expected_valid_records)

    # 3) Cleaned logs filtering and header
    cleaned_header = _read_csv_header(cleaned_path) if cleaned_path.exists() else None
    cleaned_rows = _read_csv_dicts(cleaned_path) if cleaned_path.exists() else None
    if cleaned_header is not None and cleaned_rows is not None and input_header is not None and expected_valid_records is not None:
        # Header preserved
        header_ok = cleaned_header == input_header
        # Filtering: only valid present and all valid included
        cleaned_ids = {r.get("record_id", "") for r in cleaned_rows}
        expected_valid_ids = {r.get("record_id", "") for r in expected_valid_records}
        filtering_ok = (cleaned_ids == expected_valid_ids)
        if header_ok and filtering_ok:
            scores["cleaned_logs_filtering_and_header"] = 1.0
        else:
            scores["cleaned_logs_filtering_and_header"] = 0.0
    else:
        scores["cleaned_logs_filtering_and_header"] = 0.0

    # 4) Cleaned logs sorted by date then train_id
    if cleaned_rows is not None:
        # Verify non-decreasing by (date, train_id)
        sorted_ok = True
        prev_key = None
        for r in cleaned_rows:
            key = (r.get("date", ""), r.get("train_id", ""))
            if prev_key is not None and key < prev_key:
                sorted_ok = False
                break
            prev_key = key
        scores["cleaned_logs_sorted_by_date_then_train"] = 1.0 if sorted_ok else 0.0
    else:
        scores["cleaned_logs_sorted_by_date_then_train"] = 0.0

    # 5) Summary JSON totals and on_time_rate, and 6) per_class aggregates
    summary = _load_json(summary_path) if summary_path.exists() else None
    if summary is not None and expected_valid_records is not None and expected_delays is not None:
        # Expected services analyzed
        exp_services = len(expected_valid_records)
        # Expected on_time_rate as percentage (<=5 minutes considered on-time)
        on_time_count = sum(1 for rid, d in expected_delays.items() if d <= 5)
        exp_on_time_rate = (on_time_count / exp_services * 100.0) if exp_services > 0 else 0.0

        # Check structure
        top_level_keys_ok = isinstance(summary, dict) and set(summary.keys()) == {"totals", "on_time_rate", "per_class"}
        totals = summary.get("totals")
        per_class_list = summary.get("per_class")

        # Totals and on_time_rate
        totals_ok = isinstance(totals, dict) and "services_analyzed" in totals and isinstance(totals.get("services_analyzed"), int)
        on_time_ok = isinstance(summary.get("on_time_rate"), (int, float))
        totals_value_ok = totals_ok and (totals.get("services_analyzed") == exp_services)
        on_time_value_ok = on_time_ok and _float_eq(float(summary.get("on_time_rate")), float(exp_on_time_rate))

        # Per-class expected
        # Build expected per_class dict mapping class -> (count, avg_delay)
        per_class_expected: Dict[str, Tuple[int, float]] = {}
        # Build delays per class
        class_to_delays: Dict[str, List[int]] = {}
        for r in expected_valid_records:
            cls = r.get("locomotive_class", "")
            rid = r.get("record_id", "")
            if cls is None:
                cls = ""
            if rid in expected_delays:
                class_to_delays.setdefault(cls, []).append(expected_delays[rid])
        for cls, vals in class_to_delays.items():
            avg = _mean([float(v) for v in vals])
            per_class_expected[cls] = (len(vals), float(avg if avg is not None else 0.0))

        per_class_ok = False
        if isinstance(per_class_list, list):
            # Validate each item structure and aggregate
            seen_classes: Set[str] = set()
            item_struct_ok = True
            content_ok = True
            for item in per_class_list:
                if not (isinstance(item, dict) and set(item.keys()) == {"locomotive_class", "services", "avg_arrival_delay_minutes"}):
                    item_struct_ok = False
                    break
                cls = item.get("locomotive_class")
                services = item.get("services")
                avg_delay = item.get("avg_arrival_delay_minutes")
                if not isinstance(cls, str) or not isinstance(services, int) or not isinstance(avg_delay, (int, float)):
                    item_struct_ok = False
                    break
                seen_classes.add(cls)
                if cls not in per_class_expected:
                    content_ok = False
                    break
                exp_services_cls, exp_avg_cls = per_class_expected[cls]
                if services != exp_services_cls or not _float_eq(float(avg_delay), float(exp_avg_cls)):
                    content_ok = False
                    break
            # Ensure there are no missing or extra classes
            if item_struct_ok and content_ok and seen_classes == set(per_class_expected.keys()):
                per_class_ok = True

        # Assign scores
        if top_level_keys_ok and totals_value_ok and on_time_value_ok:
            scores["summary_json_totals_and_on_time_rate"] = 1.0
        else:
            scores["summary_json_totals_and_on_time_rate"] = 0.0

        scores["summary_json_per_class_aggregates"] = 1.0 if per_class_ok else 0.0
    else:
        scores["summary_json_totals_and_on_time_rate"] = 0.0
        scores["summary_json_per_class_aggregates"] = 0.0

    # 7) Top 10 arrival delays CSV correctness
    if top10_path.exists() and expected_valid_records is not None and expected_delays is not None:
        header = _read_csv_header(top10_path)
        rows = _read_csv_dicts(top10_path)
        required_cols = ["record_id", "date", "train_id", "locomotive_class", "origin", "destination", "arrival_delay_minutes"]
        if header == required_cols and rows is not None:
            # Expected top K by delay desc
            # Build expected sorted list of (rid, delay) pairs
            expected_pairs = [(r.get("record_id", ""), expected_delays.get(r.get("record_id", ""), None)) for r in expected_valid_records]
            expected_pairs = [(rid, d) for (rid, d) in expected_pairs if rid and d is not None]
            expected_pairs.sort(key=lambda x: (-x[1], rid_as_int_safe(x[0])))
            k = min(10, len(expected_pairs))
            expected_top = expected_pairs[:k]
            expected_top_ids = [rid for rid, _ in expected_top]
            expected_delay_map = {rid: d for rid, d in expected_pairs}

            # Helper: parse arrival_delay_minutes as int
            def parse_int_safe(s: str) -> Optional[int]:
                try:
                    return int(str(s).strip())
                except Exception:
                    try:
                        # Accept float string if given, convert to int if integral
                        f = float(str(s).strip())
                        if abs(f - int(f)) < 1e-9:
                            return int(f)
                    except Exception:
                        pass
                return None

            # Validate row count
            row_count_ok = (len(rows) == k)

            # Validate sorting descending by arrival_delay_minutes
            sorting_ok = True
            prev = None
            for r in rows:
                cur_val = parse_int_safe(r.get("arrival_delay_minutes", ""))
                if cur_val is None:
                    sorting_ok = False
                    break
                if prev is not None and cur_val > prev:
                    sorting_ok = False
                    break
                prev = cur_val

            # Validate content: set of record_ids matches expected top IDs (multiset check; unique IDs here)
            file_ids = [str(r.get("record_id", "")).strip() for r in rows]
            content_ids_ok = set(file_ids) == set(expected_top_ids) and len(file_ids) == len(expected_top_ids)

            # Validate each row's delay matches expected and belongs to cleaned set
            delays_ok = True
            for r in rows:
                rid = str(r.get("record_id", "")).strip()
                d_val = parse_int_safe(r.get("arrival_delay_minutes", ""))
                if rid not in expected_delay_map or d_val is None or d_val != expected_delay_map[rid]:
                    delays_ok = False
                    break

            if row_count_ok and sorting_ok and content_ids_ok and delays_ok:
                scores["top10_arrival_delays_correct"] = 1.0
            else:
                scores["top10_arrival_delays_correct"] = 0.0
        else:
            scores["top10_arrival_delays_correct"] = 0.0
    else:
        scores["top10_arrival_delays_correct"] = 0.0

    return scores


def rid_as_int_safe(rid: str) -> int:
    try:
        return int(rid)
    except Exception:
        # Fallback stable conversion: numeric prefix or zero
        digits = ''.join(ch for ch in rid if ch.isdigit())
        try:
            return int(digits) if digits else 0
        except Exception:
            return 0


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()