import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_int(val: Any) -> Optional[int]:
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val) if val.is_integer() else None
    if isinstance(val, str):
        s = val.strip()
        if re.fullmatch(r"-?\d+", s):
            try:
                return int(s)
            except Exception:
                return None
    return None


def _sum_columns(rows: List[Dict[str, str]], columns: List[str]) -> Optional[Dict[str, int]]:
    totals: Dict[str, int] = {c: 0 for c in columns}
    try:
        for row in rows:
            for c in columns:
                if c not in row:
                    return None
                iv = _parse_int(row[c])
                if iv is None:
                    return None
                totals[c] += iv
        return totals
    except Exception:
        return None


def _extract_section_lines(md_text: str, section_name: str, subsequent_section_names: List[str]) -> Optional[List[str]]:
    lines = md_text.splitlines()
    lower_lines = [ln.lower() for ln in lines]
    start_idx = None
    for i, ln in enumerate(lower_lines):
        if section_name.lower() in ln:
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        for next_name in subsequent_section_names:
            if next_name.lower() in lower_lines[i]:
                end_idx = i
                break
        if end_idx != len(lines):
            break
    return lines[start_idx:end_idx]


def _line_has_number(line: str, number: int) -> bool:
    return re.search(rf"\b{re.escape(str(number))}\b", line) is not None


def _find_line_for_check(section_lines: List[str], col: str, gl_val: int, ss_val: int, expected_label: str) -> bool:
    col_lower = col.lower()
    expected_label = expected_label.lower()
    for ln in section_lines:
        ln_lower = ln.lower()
        if col_lower in ln_lower and expected_label in ln_lower:
            # Require both numbers to appear explicitly in the line
            if _line_has_number(ln, gl_val) and _line_has_number(ln, ss_val):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Expected paths and columns
    game_logs_path = workspace / "data" / "game_logs_2021.csv"
    season_summary_path = workspace / "data" / "season_summary_2021.csv"
    json_output_path = workspace / "output" / "validation_results_2021.json"
    report_output_path = workspace / "reports" / "validation_report_2021.md"
    readme_path = workspace / "docs" / "README.md"
    expected_columns = ["AB", "R", "H", "HR", "RBI", "BB"]

    scores = {
        "json_file_exists": 0.0,
        "json_structure_fields_valid": 0.0,
        "json_files_row_counts_correct": 0.0,
        "json_columns_checked_exact": 0.0,
        "json_passes_list_correct": 0.0,
        "json_failures_list_correct": 0.0,
        "report_file_exists": 0.0,
        "report_files_scanned_section_correct": 0.0,
        "report_checks_section_correct": 0.0,
        "report_summary_section_correct": 0.0,
        "readme_placeholder_replaced": 0.0,
        "readme_status_line_correct": 0.0,
        "readme_links_present": 0.0,
    }

    # Read CSVs when available
    gl_rows = _safe_read_csv_dicts(game_logs_path) if game_logs_path.exists() else None
    ss_rows = _safe_read_csv_dicts(season_summary_path) if season_summary_path.exists() else None

    gl_row_count = len(gl_rows) if gl_rows is not None else None
    ss_row_count = len(ss_rows) if ss_rows is not None else None

    gl_sums = _sum_columns(gl_rows, expected_columns) if gl_rows is not None else None

    ss_totals: Optional[Dict[str, int]] = None
    if ss_rows is not None:
        target_row: Optional[Dict[str, str]] = None
        for row in ss_rows:
            if _parse_int(row.get("year")) == 2021:
                target_row = row
                break
        if target_row is None and len(ss_rows) > 0:
            target_row = ss_rows[0]
        if target_row is not None:
            tmp_totals: Dict[str, int] = {}
            ok = True
            for c in expected_columns:
                if c not in target_row:
                    ok = False
                    break
                iv = _parse_int(target_row[c])
                if iv is None:
                    ok = False
                    break
                tmp_totals[c] = iv
            if ok:
                ss_totals = tmp_totals

    passes_set: Optional[set] = None
    fails_set: Optional[set] = None
    failures_detail: Optional[Dict[str, Tuple[int, int]]] = None
    if gl_sums is not None and ss_totals is not None:
        passes_set = set()
        fails_set = set()
        failures_detail = {}
        for c in expected_columns:
            if gl_sums[c] == ss_totals[c]:
                passes_set.add(c)
            else:
                fails_set.add(c)
                failures_detail[c] = (gl_sums[c], ss_totals[c])

    # JSON checks
    json_obj = _safe_load_json(json_output_path) if json_output_path.exists() else None
    if json_output_path.exists():
        scores["json_file_exists"] = 1.0

    if isinstance(json_obj, dict):
        has_season = "season" in json_obj
        has_files = "files" in json_obj and isinstance(json_obj["files"], dict)
        has_cols = "columns_checked" in json_obj and isinstance(json_obj["columns_checked"], list)
        has_passes = "passes" in json_obj and isinstance(json_obj["passes"], list)
        has_failures = "failures" in json_obj and isinstance(json_obj["failures"], list)
        season_ok = False
        if has_season:
            season_ok = (_parse_int(json_obj["season"]) == 2021)
        if has_season and has_files and has_cols and has_passes and has_failures and season_ok:
            scores["json_structure_fields_valid"] = 1.0

        files_counts_ok = False
        if has_files and gl_row_count is not None and ss_row_count is not None:
            files_obj = json_obj["files"]
            expected_files = {
                "data/game_logs_2021.csv": gl_row_count,
                "data/season_summary_2021.csv": ss_row_count,
            }
            key_match = set(files_obj.keys()) == set(expected_files.keys())
            values_match = True
            if key_match:
                for k, expected_rc in expected_files.items():
                    v = files_obj.get(k)
                    if not isinstance(v, dict) or "rows" not in v or not isinstance(v["rows"], int):
                        values_match = False
                        break
                    if v["rows"] != expected_rc:
                        values_match = False
                        break
            else:
                values_match = False
            files_counts_ok = key_match and values_match
        scores["json_files_row_counts_correct"] = 1.0 if files_counts_ok else 0.0

        cols_checked_ok = False
        if has_cols:
            cols = json_obj["columns_checked"]
            cols_checked_ok = cols == expected_columns
        scores["json_columns_checked_exact"] = 1.0 if cols_checked_ok else 0.0

        passes_ok = False
        if has_passes and passes_set is not None:
            try:
                json_passes_set = set(json_obj["passes"])
                passes_ok = json_passes_set == passes_set
            except Exception:
                passes_ok = False
        scores["json_passes_list_correct"] = 1.0 if passes_ok else 0.0

        failures_ok = False
        if has_failures and fails_set is not None and failures_detail is not None:
            try:
                jfails = json_obj["failures"]
                jfmap: Dict[str, Tuple[int, int]] = {}
                valid_objs = True
                for item in jfails:
                    if not isinstance(item, dict):
                        valid_objs = False
                        break
                    if "field" not in item or "game_logs_total" not in item or "season_summary_total" not in item:
                        valid_objs = False
                        break
                    fld = item["field"]
                    glv = _parse_int(item["game_logs_total"])
                    ssv = _parse_int(item["season_summary_total"])
                    if not isinstance(fld, str) or glv is None or ssv is None:
                        valid_objs = False
                        break
                    jfmap[fld] = (glv, ssv)
                if valid_objs:
                    failures_ok = set(jfmap.keys()) == fails_set
                    if failures_ok:
                        for fld in fails_set:
                            if jfmap.get(fld) != failures_detail.get(fld):
                                failures_ok = False
                                break
            except Exception:
                failures_ok = False
        scores["json_failures_list_correct"] = 1.0 if failures_ok else 0.0

    # Report checks
    report_text = _safe_read_text(report_output_path) if report_output_path.exists() else None
    if report_output_path.exists():
        scores["report_file_exists"] = 1.0

    if isinstance(report_text, str) and gl_row_count is not None and ss_row_count is not None:
        # Files Scanned section
        files_lines = _extract_section_lines(report_text, "Files Scanned", ["Checks", "Summary"])
        files_scanned_ok = False
        if files_lines is not None:
            gl_ok = False
            ss_ok = False
            for ln in files_lines:
                if "data/game_logs_2021.csv" in ln and _line_has_number(ln, gl_row_count):
                    gl_ok = True
                if "data/season_summary_2021.csv" in ln and _line_has_number(ln, ss_row_count):
                    ss_ok = True
            files_scanned_ok = gl_ok and ss_ok
        scores["report_files_scanned_section_correct"] = 1.0 if files_scanned_ok else 0.0

        # Checks section
        checks_lines = _extract_section_lines(report_text, "Checks", ["Summary"])
        checks_ok = False
        if checks_lines is not None and gl_sums is not None and ss_totals is not None:
            all_cols_ok = True
            for c in expected_columns:
                expected_label = "pass" if gl_sums[c] == ss_totals[c] else "fail"
                if not _find_line_for_check(checks_lines, c, gl_sums[c], ss_totals[c], expected_label):
                    all_cols_ok = False
                    break
            checks_ok = all_cols_ok
        scores["report_checks_section_correct"] = 1.0 if checks_ok else 0.0

        # Summary section
        summary_lines = _extract_section_lines(report_text, "Summary", [])
        summary_ok = False
        if summary_lines is not None and passes_set is not None and fails_set is not None:
            summary_text = "\n".join(summary_lines)
            st_lower = summary_text.lower()
            expected_overall = "pass" if len(fails_set) == 0 else "fail"
            has_overall = expected_overall in st_lower
            pass_count = len(passes_set)
            fail_count = len(fails_set)
            has_pass_count = re.search(rf"\b{pass_count}\b", summary_text) is not None
            has_fail_count = re.search(rf"\b{fail_count}\b", summary_text) is not None
            # Require mentions of pass/fail counts and overall status word
            summary_ok = has_overall and has_pass_count and has_fail_count
        scores["report_summary_section_correct"] = 1.0 if summary_ok else 0.0

    # README checks
    readme_text = _safe_read_text(readme_path) if readme_path.exists() else None
    if isinstance(readme_text, str) and passes_set is not None and fails_set is not None:
        placeholder = "- 2021: Pending (no checks run)"
        scores["readme_placeholder_replaced"] = 1.0 if placeholder not in readme_text else 0.0

        # Limit search to Validation Status section if available
        section_lines = _extract_section_lines(readme_text, "Validation Status", ["## "]) or readme_text.splitlines()
        status_line = None
        for ln in section_lines:
            if ln.strip().startswith("- 2021:"):
                status_line = ln.strip()
                break

        status_line_ok = False
        links_ok = False
        if status_line is not None:
            expected_overall = "Pass" if len(fails_set) == 0 else "Fail"
            has_overall = expected_overall in status_line
            if expected_overall == "Fail":
                m = re.search(r"\((.*?)\)", status_line)
                if m:
                    inside = m.group(1)
                    items = [x.strip() for x in inside.split(",") if x.strip()]
                    status_line_ok = set(items) == fails_set and has_overall
                else:
                    status_line_ok = False
            else:
                status_line_ok = has_overall

            links_ok = ("reports/validation_report_2021.md" in status_line) and ("output/validation_results_2021.json" in status_line)

        scores["readme_status_line_correct"] = 1.0 if status_line_ok else 0.0
        scores["readme_links_present"] = 1.0 if links_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()