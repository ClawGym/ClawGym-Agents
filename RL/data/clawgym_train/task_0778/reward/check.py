import csv
import json
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _safe_import_analytics(workspace: Path):
    """
    Attempt to import app.analytics from the given workspace path.
    Returns (module_or_None, error_message_or_None).
    """
    try:
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        return importlib.import_module("app.analytics"), None
    except Exception as e:
        return None, f"{e}"


def _compute_expected_from_input(input_csv: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    """
    Returns (rows, expectation) where expectation is a dict holding
    - far_cry_titles: {title: {'sessions': int, 'total': int, 'avg': float, 'median': float}}
    - franchise_summary: {franchise: {'sessions': int, 'total': int, 'avg': float}}
    - far_cry_titles_sorted: [title...]
    - franchises_sorted: [franchise...]
    """
    rows = _safe_read_csv_dicts(input_csv)
    if rows is None:
        return None, None

    # Normalize and compute minutes as ints for expectations
    norm_rows: List[Dict[str, Any]] = []
    for r in rows:
        rr = dict(r)
        try:
            mins = int(rr.get("minutes", "0"))
        except Exception:
            mins = 0
        rr["minutes"] = mins
        rr["franchise"] = (rr.get("franchise") or "").strip()
        rr["game_title"] = (rr.get("game_title") or "").strip()
        norm_rows.append(rr)

    # Far Cry title-level summaries
    fc_rows = [r for r in norm_rows if r.get("franchise") == "Far Cry"]
    by_title: Dict[str, List[int]] = {}
    for r in fc_rows:
        t = r.get("game_title", "")
        by_title.setdefault(t, []).append(r.get("minutes", 0))
    far_cry_titles = {}
    for t, mins_list in by_title.items():
        mins_sorted = sorted(mins_list)
        sessions = len(mins_list)
        total = sum(mins_list)
        avg = round(total / sessions, 2) if sessions else 0.0
        # median
        if sessions:
            mid = sessions // 2
            if sessions % 2 == 1:
                median_val = float(mins_sorted[mid])
            else:
                median_val = (mins_sorted[mid - 1] + mins_sorted[mid]) / 2.0
        else:
            median_val = 0.0
        median_val = round(median_val, 2)
        far_cry_titles[t] = {
            "sessions": sessions,
            "total": total,
            "avg": avg,
            "median": median_val,
        }
    far_cry_titles_sorted = sorted(far_cry_titles.keys())

    # Franchise-level summaries
    by_franchise: Dict[str, List[int]] = {}
    for r in norm_rows:
        f = r.get("franchise", "")
        by_franchise.setdefault(f, []).append(r.get("minutes", 0))
    franchise_summary = {}
    for f, mins_list in by_franchise.items():
        sessions = len(mins_list)
        total = sum(mins_list)
        avg = round((total / sessions) if sessions else 0.0, 2)
        franchise_summary[f] = {
            "sessions": sessions,
            "total": total,
            "avg": avg,
        }
    franchises_sorted = sorted(franchise_summary.keys())

    exp = {
        "far_cry_titles": far_cry_titles,
        "far_cry_titles_sorted": far_cry_titles_sorted,
        "franchise_summary": franchise_summary,
        "franchises_sorted": franchises_sorted,
    }
    return norm_rows, exp


def _parse_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _format_two_decimals(val: float) -> str:
    return f"{val:.2f}"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "analytics_module_exists": 0.0,
        "analytics_functions_present": 0.0,
        "load_sessions_row_count_matches_input": 0.0,
        "summarize_by_title_far_cry_correct": 0.0,
        "summarize_by_franchise_correct": 0.0,
        "far_cry_summary_csv_present_and_schema": 0.0,
        "far_cry_summary_csv_values_and_sort": 0.0,
        "overall_by_franchise_csv_present_and_schema": 0.0,
        "overall_by_franchise_csv_values_and_sort": 0.0,
        "tests_file_exists_and_imports": 0.0,
        "test_report_exists_and_ok": 0.0,
        "cli_entrypoint_present": 0.0,
    }

    input_csv = workspace / "input" / "sessions.csv"
    far_cry_csv = workspace / "output" / "far_cry_summary.csv"
    overall_csv = workspace / "output" / "overall_by_franchise.csv"
    tests_file = workspace / "tests" / "test_analytics.py"
    test_report = workspace / "output" / "test_report.txt"
    analytics_py = workspace / "app" / "analytics.py"

    # Expectations from input
    rows, exp = _compute_expected_from_input(input_csv)
    if rows is None or exp is None:
        expected_rows_count = None
    else:
        expected_rows_count = len(rows)

    # Check analytics module exists
    if analytics_py.exists():
        scores["analytics_module_exists"] = 1.0

    # Import analytics
    analytics_mod, import_err = _safe_import_analytics(workspace)

    # Check functions present
    required_funcs = ("load_sessions", "summarize_by_title", "summarize_by_franchise")
    if analytics_mod is not None:
        missing = [fn for fn in required_funcs if not hasattr(analytics_mod, fn)]
        if not missing:
            scores["analytics_functions_present"] = 1.0

    # load_sessions behavior: row count matches input file
    if analytics_mod is not None and hasattr(analytics_mod, "load_sessions") and expected_rows_count is not None:
        try:
            loader = getattr(analytics_mod, "load_sessions")
            loaded_rows = loader(str(input_csv))
            if isinstance(loaded_rows, list) and len(loaded_rows) == expected_rows_count:
                scores["load_sessions_row_count_matches_input"] = 1.0
        except Exception:
            pass

    # summarize_by_title correctness for Far Cry
    if analytics_mod is not None and hasattr(analytics_mod, "summarize_by_title") and hasattr(analytics_mod, "load_sessions") and exp is not None:
        try:
            loader = getattr(analytics_mod, "load_sessions")
            title_summarizer = getattr(analytics_mod, "summarize_by_title")
            loaded_rows = loader(str(input_csv))
            results = title_summarizer(loaded_rows, "Far Cry")
            ok = True
            if not isinstance(results, list):
                ok = False
            else:
                res_by_title = {}
                for r in results:
                    t = r.get("title") or r.get("game_title") or r.get("name")
                    if t is None:
                        ok = False
                        break
                    res_by_title[str(t)] = r
                expected_titles = set(exp["far_cry_titles"].keys())
                if set(res_by_title.keys()) != expected_titles:
                    ok = False
                else:
                    for t, ev in exp["far_cry_titles"].items():
                        rv = res_by_title.get(t, {})
                        sessions_ok = isinstance(rv.get("sessions"), int) and rv.get("sessions") == ev["sessions"]
                        total_ok = isinstance(rv.get("total_minutes"), int) and rv.get("total_minutes") == ev["total"]
                        avg_val = rv.get("avg_minutes")
                        median_val = rv.get("median_minutes")
                        avg_ok = isinstance(avg_val, float) and round(avg_val, 2) == ev["avg"]
                        median_ok = isinstance(median_val, float) and round(median_val, 2) == ev["median"]
                        if not (sessions_ok and total_ok and avg_ok and median_ok):
                            ok = False
                            break
            scores["summarize_by_title_far_cry_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["summarize_by_title_far_cry_correct"] = 0.0

    # summarize_by_franchise correctness
    if analytics_mod is not None and hasattr(analytics_mod, "summarize_by_franchise") and hasattr(analytics_mod, "load_sessions") and exp is not None:
        try:
            loader = getattr(analytics_mod, "load_sessions")
            fr_summarizer = getattr(analytics_mod, "summarize_by_franchise")
            loaded_rows = loader(str(input_csv))
            results = fr_summarizer(loaded_rows)
            okf = True
            if not isinstance(results, list):
                okf = False
            else:
                res_by_franchise = {}
                for r in results:
                    f = r.get("franchise")
                    if f is None:
                        okf = False
                        break
                    res_by_franchise[str(f)] = r
                expected_franchises = set(exp["franchise_summary"].keys())
                if set(res_by_franchise.keys()) != expected_franchises:
                    okf = False
                else:
                    for f, ev in exp["franchise_summary"].items():
                        rv = res_by_franchise.get(f, {})
                        sessions_ok = isinstance(rv.get("sessions"), int) and rv.get("sessions") == ev["sessions"]
                        total_ok = isinstance(rv.get("total_minutes"), int) and rv.get("total_minutes") == ev["total"]
                        avg_val = rv.get("avg_minutes")
                        avg_ok = isinstance(avg_val, float) and round(avg_val, 2) == ev["avg"]
                        if not (sessions_ok and total_ok and avg_ok):
                            okf = False
                            break
            scores["summarize_by_franchise_correct"] = 1.0 if okf else 0.0
        except Exception:
            pass

    # CSV outputs present and schema
    # Far Cry summary CSV schema
    fc_schema_ok = False
    if far_cry_csv.exists():
        header, rows_csv = _parse_csv_with_header(far_cry_csv)
        if header is not None and rows_csv is not None:
            expected_header = ["title", "sessions", "total_minutes", "avg_minutes", "median_minutes"]
            if header == expected_header:
                fc_schema_ok = True
    scores["far_cry_summary_csv_present_and_schema"] = 1.0 if fc_schema_ok else 0.0

    # Far Cry summary CSV values and sort
    fc_values_ok = False
    if fc_schema_ok and exp is not None:
        header, rows_csv = _parse_csv_with_header(far_cry_csv)
        try:
            titles_in_csv = [row["title"] for row in rows_csv]
            sort_ok = titles_in_csv == sorted(titles_in_csv)
            set_ok = set(titles_in_csv) == set(exp["far_cry_titles"].keys())
            vals_ok = True
            for row in rows_csv:
                t = row["title"]
                ev = exp["far_cry_titles"].get(t)
                if ev is None:
                    vals_ok = False
                    break
                try:
                    sessions = int(row["sessions"])
                    total = int(row["total_minutes"])
                except Exception:
                    vals_ok = False
                    break
                avg_str = row["avg_minutes"]
                median_str = row["median_minutes"]
                expected_avg_str = _format_two_decimals(ev["avg"])
                expected_median_str = _format_two_decimals(ev["median"])
                if not (sessions == ev["sessions"] and total == ev["total"] and avg_str == expected_avg_str and median_str == expected_median_str):
                    vals_ok = False
                    break
            fc_values_ok = sort_ok and set_ok and vals_ok
        except Exception:
            fc_values_ok = False
    scores["far_cry_summary_csv_values_and_sort"] = 1.0 if fc_values_ok else 0.0

    # Overall by franchise CSV schema
    overall_schema_ok = False
    if overall_csv.exists():
        header, rows_csv = _parse_csv_with_header(overall_csv)
        if header is not None and rows_csv is not None:
            expected_header = ["franchise", "sessions", "total_minutes", "avg_minutes"]
            if header == expected_header:
                overall_schema_ok = True
    scores["overall_by_franchise_csv_present_and_schema"] = 1.0 if overall_schema_ok else 0.0

    # Overall by franchise CSV values and sort
    overall_values_ok = False
    if overall_schema_ok and exp is not None:
        header, rows_csv = _parse_csv_with_header(overall_csv)
        try:
            fr_in_csv = [row["franchise"] for row in rows_csv]
            sort_ok = fr_in_csv == sorted(fr_in_csv)
            set_ok = set(fr_in_csv) == set(exp["franchise_summary"].keys())
            vals_ok = True
            for row in rows_csv:
                f = row["franchise"]
                ev = exp["franchise_summary"].get(f)
                if ev is None:
                    vals_ok = False
                    break
                try:
                    sessions = int(row["sessions"])
                    total = int(row["total_minutes"])
                except Exception:
                    vals_ok = False
                    break
                avg_str = row["avg_minutes"]
                expected_avg_str = _format_two_decimals(ev["avg"])
                if not (sessions == ev["sessions"] and total == ev["total"] and avg_str == expected_avg_str):
                    vals_ok = False
                    break
            overall_values_ok = sort_ok and set_ok and vals_ok
        except Exception:
            overall_values_ok = False
    scores["overall_by_franchise_csv_values_and_sort"] = 1.0 if overall_values_ok else 0.0

    # Tests file exists and appears to import app.analytics using unittest
    tests_ok = False
    if tests_file.exists():
        text = _safe_read_text(tests_file) or ""
        imports_unittest = "unittest" in text
        imports_analytics = ("import app.analytics" in text) or ("from app import analytics" in text) or ("from app.analytics" in text)
        tests_ok = imports_unittest and imports_analytics
    scores["tests_file_exists_and_imports"] = 1.0 if tests_ok else 0.0

    # Test report exists and shows OK
    report_ok = False
    if test_report.exists():
        rep = _safe_read_text(test_report) or ""
        if ("Ran " in rep) and ("OK" in rep):
            report_ok = True
    scores["test_report_exists_and_ok"] = 1.0 if report_ok else 0.0

    # CLI entrypoint present: check if __main__ block exists and mentions output paths
    cli_ok = False
    if analytics_py.exists():
        text = _safe_read_text(analytics_py) or ""
        main_guard = "if __name__ == \"__main__\":" in text or "if __name__ == '__main__':" in text
        mentions_far_cry_output = "output/far_ry" in text  # small tolerance for variations
        # Ensure exact paths as required if present
        mentions_far_cry_output_exact = "output/far_cry_summary.csv" in text
        mentions_overall_output = "output/overall_by_franchise.csv" in text
        cli_ok = main_guard and mentions_overall_output and (mentions_far_cry_output or mentions_far_cry_output_exact)
    scores["cli_entrypoint_present"] = 1.0 if cli_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()