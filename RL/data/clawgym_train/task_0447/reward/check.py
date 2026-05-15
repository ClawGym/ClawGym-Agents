import json
import sys
from pathlib import Path
from datetime import datetime
import importlib.util
import csv


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_module_from_path(name: str, file_path: Path):
    try:
        spec = importlib.util.spec_from_file_location(name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _safe_csv_read(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
        return header, rows
    except Exception:
        return None


def _parse_date_yyyy_mm_dd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_file_uses_real_functions": 0.0,
        "filter_returns_5_events_inclusive": 0.0,
        "aggregation_matches_expected": 0.0,
        "test_report_indicates_passing": 0.0,
        "aggregates_csv_exact_content": 0.0,
    }

    # Check tests/test_aggregator.py presence and basic content requirements
    tests_file = workspace / "tests" / "test_aggregator.py"
    tests_text = _safe_read_text(tests_file)
    if tests_text is not None:
        # Confirm it imports from src.aggregator and references the required date range and input file
        uses_import = ("from src.aggregator import" in tests_text) or ("import src.aggregator" in tests_text)
        mentions_dates = ("2020-01-01" in tests_text and "2020-01-31" in tests_text)
        mentions_input = ("input/events_small.csv" in tests_text)
        # Also check references to functions likely used
        references_functions = ("filter_by_date_range" in tests_text and "aggregate_incidents_by_governorate" in tests_text)
        if uses_import and mentions_dates and mentions_input and references_functions:
            scores["tests_file_uses_real_functions"] = 1.0

    # Load aggregator module and validate filtering and aggregation behavior on provided input
    aggregator_path = workspace / "src" / "aggregator.py"
    aggregator = _load_module_from_path("aggregator_module", aggregator_path)
    events_csv_path = workspace / "input" / "events_small.csv"
    header_rows = _safe_csv_read(events_csv_path)

    if aggregator is not None and header_rows is not None:
        # Load events using aggregator if possible, otherwise fall back to CSV parsing
        try:
            events = aggregator.read_events_csv(str(events_csv_path))
        except Exception:
            # Fallback if read_events_csv is not available or fails
            _, rows = header_rows
            events = rows

        # Prepare dates
        start_date = _parse_date_yyyy_mm_dd("2020-01-01")
        end_date = _parse_date_yyyy_mm_dd("2020-01-31")

        try:
            filtered = aggregator.filter_by_date_range(events, start_date, end_date)
            # Validate inclusive behavior: exactly 5 events, include 2020-01-31, exclude 2020-02-01, all within inclusive bounds
            dates = []
            includes_jan31 = False
            excludes_feb01 = True
            within_bounds = True
            for e in filtered:
                d = e.get("date")
                if isinstance(d, str):
                    pd = _parse_date_yyyy_mm_dd(d)
                else:
                    pd = d
                if pd is None:
                    within_bounds = False
                    break
                dates.append(pd)
                if pd == _parse_date_yyyy_mm_dd("2020-01-31"):
                    includes_jan31 = True
                if pd == _parse_date_yyyy_mm_dd("2020-02-01"):
                    excludes_feb01 = False
                if not (start_date <= pd <= end_date):
                    within_bounds = False
            if len(filtered) == 5 and includes_jan31 and excludes_feb01 and within_bounds:
                scores["filter_returns_5_events_inclusive"] = 1.0

            # Validate aggregation
            try:
                agg = aggregator.aggregate_incidents_by_governorate(filtered)
                expected = {
                    "Aleppo": {"event_count": 2, "total_fatalities": 4},
                    "Damascus": {"event_count": 2, "total_fatalities": 2},
                    "Idlib": {"event_count": 1, "total_fatalities": 5},
                }
                if agg == expected:
                    scores["aggregation_matches_expected"] = 1.0
            except Exception:
                pass
        except Exception:
            pass

    # Validate pytest run summary report
    report_path = workspace / "output" / "test_report.txt"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        lower = report_text.lower()
        if ("passed" in lower) and ("failed" not in lower) and ("error" not in lower):
            scores["test_report_indicates_passing"] = 1.0

    # Validate output/aggregates.csv exact content
    aggregates_csv = workspace / "output" / "aggregates.csv"
    parsed = _safe_csv_read(aggregates_csv)
    if parsed is not None:
        header, rows = parsed
        expected_header = ["governorate", "event_count", "total_fatalities"]
        expected_rows = [
            {"governorate": "Aleppo", "event_count": "2", "total_fatalities": "4"},
            {"governorate": "Damascus", "event_count": "2", "total_fatalities": "2"},
            {"governorate": "Idlib", "event_count": "1", "total_fatalities": "5"},
        ]
        # Check header order and exact rows and sort order
        if header == expected_header:
            # Normalize rows to only expected fields and exact ordering
            normalized_rows = []
            for r in rows:
                # If any required field missing, fail
                if not all(k in r for k in expected_header):
                    normalized_rows = None
                    break
                normalized_rows.append(
                    {k: str(r.get(k, "")) for k in expected_header}
                )
            if normalized_rows is not None and normalized_rows == expected_rows:
                # Verify sorted by governorate ascending
                govs = [r["governorate"] for r in normalized_rows]
                if govs == sorted(govs):
                    scores["aggregates_csv_exact_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()