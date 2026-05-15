import sys
import json
import csv
from pathlib import Path
from typing import List, Tuple, Dict, Optional


REQUIRED_INPUT_COLUMNS = ["id", "title", "artist", "country", "city", "year", "theme"]
SUMMARY_COLUMNS = ["country", "year", "exhibitions_count", "unique_artists", "dominant_theme", "dominant_theme_share"]


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
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


def _format_share(value: float) -> str:
    # Normalize to string with exactly two decimals
    return f"{round(value, 2):.2f}"


def _compute_expected_summary(archive_files: List[Path]) -> Optional[List[Dict[str, str]]]:
    # Validate and compute aggregates from archived CSVs
    all_rows: List[Dict[str, str]] = []
    try:
        for p in archive_files:
            header, rows = _safe_read_csv_dicts(p)
            if header is None or rows is None:
                return None
            # Strict validation: archived files must have exactly required columns
            if [h.strip() for h in header] != REQUIRED_INPUT_COLUMNS:
                return None
            for r in rows:
                # Ensure required fields exist
                for k in REQUIRED_INPUT_COLUMNS:
                    if k not in r:
                        return None
                all_rows.append(r)
        # Group by (country, year)
        groups: Dict[Tuple[str, int], List[Dict[str, str]]] = {}
        for r in all_rows:
            country = r["country"].strip()
            try:
                year = int(str(r["year"]).strip())
            except Exception:
                return None
            key = (country, year)
            groups.setdefault(key, []).append(r)
        expected: List[Dict[str, str]] = []
        for (country, year), rows in groups.items():
            exhibitions_count = len(rows)
            artists = set(r["artist"].strip() for r in rows)
            unique_artists = len(artists)
            # Count themes
            theme_counts: Dict[str, int] = {}
            for r in rows:
                theme = r["theme"].strip()
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
            # Determine dominant theme with tie-breaker alphabetical
            max_count = max(theme_counts.values()) if theme_counts else 0
            candidates = [t for t, c in theme_counts.items() if c == max_count]
            dominant_theme = sorted(candidates)[0] if candidates else ""
            dominant_share = _format_share(max_count / exhibitions_count if exhibitions_count > 0 else 0.0)
            expected.append({
                "country": country,
                "year": str(year),
                "exhibitions_count": str(exhibitions_count),
                "unique_artists": str(unique_artists),
                "dominant_theme": dominant_theme,
                "dominant_theme_share": dominant_share,
            })
        # Sort deterministically by (country, year numeric)
        expected.sort(key=lambda d: (d["country"], int(d["year"])))
        return expected
    except Exception:
        return None


def _read_summary_output(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    header, rows = _safe_read_csv_dicts(path)
    if header is None or rows is None:
        return False, None
    # Check exact columns order
    if [h.strip() for h in header] != SUMMARY_COLUMNS:
        return False, None
    # Normalize rows: ensure strings and normalize dominant_theme_share to two decimals
    norm_rows: List[Dict[str, str]] = []
    try:
        for r in rows:
            country = r.get("country", "").strip()
            year_str = r.get("year", "").strip()
            exhibitions_count_str = r.get("exhibitions_count", "").strip()
            unique_artists_str = r.get("unique_artists", "").strip()
            dominant_theme = r.get("dominant_theme", "").strip()
            dom_share_str_raw = r.get("dominant_theme_share", "").strip()
            # Parse ints to validate, then back to str normalized
            year = int(year_str)
            exhibitions_count = int(exhibitions_count_str)
            unique_artists = int(unique_artists_str)
            # Parse share, then normalize format
            try:
                dom_share_float = float(dom_share_str_raw)
            except Exception:
                # In case they already formatted like "0.50", attempt replacing comma
                dom_share_str_raw = dom_share_str_raw.replace(",", ".")
                dom_share_float = float(dom_share_str_raw)
            dom_share_str = _format_share(dom_share_float)
            norm_rows.append({
                "country": country,
                "year": str(year),
                "exhibitions_count": str(exhibitions_count),
                "unique_artists": str(unique_artists),
                "dominant_theme": dominant_theme,
                "dominant_theme_share": dom_share_str,
            })
        return True, norm_rows
    except Exception:
        return False, None


def _compare_summary(expected: List[Dict[str, str]], actual: List[Dict[str, str]]) -> bool:
    def _row_key(d: Dict[str, str]) -> Tuple[str, int, int, int, str, str]:
        return (
            d["country"],
            int(d["year"]),
            int(d["exhibitions_count"]),
            int(d["unique_artists"]),
            d["dominant_theme"],
            d["dominant_theme_share"],
        )
    expected_set = set(_row_key(d) for d in expected)
    actual_set = set(_row_key(d) for d in actual)
    return expected_set == actual_set and len(expected) == len(actual)


def _events_log_has_entry(log_path: Path, filename: str) -> bool:
    content = _safe_read_text(log_path)
    if content is None:
        return False
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    for ln in lines:
        low = ln.lower()
        if filename in ln and "rows_skipped=" in low and ("processed" in low or "moved" in low or "archive" in low):
            return True
    return False


def _validation_script_ok(script_path: Path) -> bool:
    text = _safe_read_text(script_path)
    if text is None:
        return False
    low = text.lower()
    # Heuristic checks for required steps:
    # - Ensures inbox exists (mentions input/inbox)
    # - Copies the new file into inbox (mentions input/new/exhibitions_2021_q1.csv and input/inbox)
    # - Produces validation_report (mentions output/validation_report.txt)
    has_inbox_mention = "input/inbox" in low
    has_copy_mention = ("exhibitions_2021_q1.csv" in low and "input/new" in low and "input/inbox" in low)
    has_report_mention = "output/validation_report.txt" in low
    return has_inbox_mention and has_copy_mention and has_report_mention


def _readme_mentions_validation(readme_path: Path) -> bool:
    text = _safe_read_text(readme_path)
    if text is None:
        return False
    low = text.lower()
    # Look for mention of run_validation script or clear instructions referencing inbox copy and validation report.
    mentions_script = "tests/run_validation.sh" in low or "run_validation.sh" in low
    mentions_inbox_and_report = ("input/inbox" in low and "exhibitions_2021_q1.csv" in low and "validation_report" in low)
    return mentions_script or mentions_inbox_and_report


def _has_watcher_or_processor_script(workspace: Path) -> bool:
    candidates: List[Path] = []
    for pattern in ["*.py", "*.sh"]:
        candidates.extend(workspace.glob(pattern))
        for sub in ["scripts", "script", "watcher", "bin", "tools"]:
            candidates.extend((workspace / sub).glob(pattern))
    for p in candidates:
        name = p.name.lower()
        if any(k in name for k in ["watch", "processor", "process", "event", "ingest"]):
            # Avoid counting the grader itself
            if "generated_validation" in name:
                continue
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "archived_new_file_present_and_identical": 0.0,
        "summary_csv_structure_correct": 0.0,
        "summary_values_correct": 0.0,
        "events_log_contains_entry": 0.0,
        "validation_script_exists_and_references_paths": 0.0,
        "validation_report_indicates_pass": 0.0,
        "readme_mentions_validation_command": 0.0,
        "watcher_or_processor_script_present": 0.0,
    }

    # Check archived new file exists and matches input/new content
    new_file = workspace / "input" / "new" / "exhibitions_2021_q1.csv"
    archived_new_file = workspace / "input" / "archive" / "exhibitions_2021_q1.csv"
    new_bytes = _safe_read_bytes(new_file)
    archived_bytes = _safe_read_bytes(archived_new_file)
    if new_bytes is not None and archived_bytes is not None and new_bytes == archived_bytes:
        scores["archived_new_file_present_and_identical"] = 1.0

    # Compute expected summary from all archive CSVs
    archive_dir = workspace / "input" / "archive"
    archive_csvs = sorted(archive_dir.glob("*.csv"))
    expected_summary = _compute_expected_summary(archive_csvs) if archive_csvs else None

    # Check summary file structure
    summary_path = workspace / "output" / "summary_by_country_year.csv"
    header, rows = _safe_read_csv_dicts(summary_path)
    if header is not None and rows is not None and [h.strip() for h in header] == SUMMARY_COLUMNS:
        scores["summary_csv_structure_correct"] = 1.0

    # Check summary values correctness
    if expected_summary is not None and summary_path.exists():
        valid_structure, actual_rows = _read_summary_output(summary_path)
        if valid_structure and actual_rows is not None:
            if _compare_summary(expected_summary, actual_rows):
                scores["summary_values_correct"] = 1.0

    # Check events log entry for 2021 file
    events_log = workspace / "logs" / "events.log"
    if _events_log_has_entry(events_log, "exhibitions_2021_q1.csv"):
        scores["events_log_contains_entry"] = 1.0

    # Check validation script existence and content
    validation_script = workspace / "tests" / "run_validation.sh"
    if validation_script.exists() and _validation_script_ok(validation_script):
        scores["validation_script_exists_and_references_paths"] = 1.0
    else:
        # Allow fallback if README documents an equivalent single command
        readme = None
        for candidate in ["README.md", "README.txt", "README"]:
            p = workspace / candidate
            if p.exists():
                readme = p
                break
        if readme and _readme_mentions_validation(readme):
            # Partial credit is not allowed; treat as success for this key when script missing but README documents command.
            scores["validation_script_exists_and_references_paths"] = 1.0

    # Check validation report content indicates PASS and no mismatches
    validation_report = workspace / "output" / "validation_report.txt"
    report_text = _safe_read_text(validation_report)
    if report_text is not None:
        low = report_text.lower()
        has_passed = "passed" in low
        # Accept if no mismatches are reported; tolerate phrases like "no mismatches" or "mismatches: 0"
        mentions_no_mismatch = ("no mismatch" in low) or ("no mismatches" in low) or ("mismatches: 0" in low) or ("0 mismatches" in low)
        # If it doesn't mention mismatches at all but says passed, also accept
        contains_mismatch_word = "mismatch" in low or "mismatches" in low
        no_mismatch_problem = (not contains_mismatch_word) or mentions_no_mismatch
        if has_passed and no_mismatch_problem:
            scores["validation_report_indicates_pass"] = 1.0

    # Check README mentions how to run validation
    readme_found = None
    for candidate in ["README.md", "README.txt", "README"]:
        p = workspace / candidate
        if p.exists():
            readme_found = p
            break
    if readme_found and _readme_mentions_validation(readme_found):
        scores["readme_mentions_validation_command"] = 1.0

    # Check watcher/processor script presence
    if _has_watcher_or_processor_script(workspace):
        scores["watcher_or_processor_script_present"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()