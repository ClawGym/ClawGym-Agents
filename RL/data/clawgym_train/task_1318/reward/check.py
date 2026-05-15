import json
import sys
import subprocess
import re
import csv
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None, None


def _run_checker(workspace: Path, csv_path: Path) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    try:
        cmd = [sys.executable, str(workspace / "tools" / "translate_lint.py"), str(csv_path)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        return None, None, None


def _combine_output(stdout: Optional[str], stderr: Optional[str]) -> str:
    s = (stdout or "")
    e = (stderr or "")
    if s and e:
        return s + ("\n" if not s.endswith("\n") else "") + e
    return s or e


def _parse_checker_output(all_output: str) -> Dict[str, Any]:
    summary_re = re.compile(r"SUMMARY\s+rows=(\d+)\s+errors=(\d+)\s+warnings=(\d+)")
    row_re = re.compile(r"ROW\s+(\S+)\s+(ERROR|WARNING)\s+([A-Z_]+)(?:\s+lang=(\w+))?")
    lines = [ln.strip() for ln in all_output.splitlines() if ln.strip() != ""]
    summary_line = None
    rows = errors = warnings = None
    for ln in lines:
        m = summary_re.search(ln)
        if m:
            rows = int(m.group(1))
            errors = int(m.group(2))
            warnings = int(m.group(3))
            summary_line = m.group(0)
    issue_counts: Dict[str, int] = {}
    issue_examples: Dict[str, List[Dict[str, Any]]] = {}
    for ln in lines:
        m = row_re.match(ln)
        if not m:
            continue
        row_id, level, code, lang = m.group(1), m.group(2), m.group(3), m.group(4)
        issue_counts[code] = issue_counts.get(code, 0) + 1
        lst = issue_examples.setdefault(code, [])
        if len(lst) < 5:  # keep a few examples
            lst.append({"id": row_id, "level": level, "code": code, "lang": lang})
    return {
        "summary_line": summary_line,
        "rows": rows,
        "errors": errors,
        "warnings": warnings,
        "issue_counts": issue_counts,
        "issue_examples": issue_examples,
        "lines": lines,
    }


def _extract_exit_code_from_log(text: str) -> Optional[int]:
    # Look for patterns like "exit code: 0" or "Exit Code=2"
    m = re.search(r"(?i)exit\s*code\s*[:=]\s*(-?\d+)", text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _find_int_near_tokens(report_text: str, tokens: List[str]) -> List[int]:
    # Returns all integers found on lines that contain any of the tokens
    counts: List[int] = []
    for ln in report_text.splitlines():
        if any(tok.lower() in ln.lower() for tok in tokens):
            for n in re.findall(r"\d+", ln):
                try:
                    counts.append(int(n))
                except Exception:
                    continue
    return counts


def _contains_line_subset(log_text: str, expected_lines: List[str]) -> bool:
    # Ensure each non-empty expected line is present as substring somewhere in log_text
    for ln in expected_lines:
        if not ln.strip():
            continue
        if ln not in log_text:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "translated_csv_exists": 0.0,
        "translated_csv_header_exact": 0.0,
        "translated_csv_row_count_matches_input": 0.0,
        "translated_csv_base_fields_preserved": 0.0,
        "translated_csv_row_order_preserved": 0.0,
        "translated_csv_es_non_empty_all": 0.0,
        "translated_csv_fr_non_empty_all": 0.0,
        "translated_csv_no_placeholders": 0.0,
        "check_log_exists": 0.0,
        "check_log_contains_summary": 0.0,
        "check_log_exit_code_recorded": 0.0,
        "check_log_exit_code_correct": 0.0,
        "check_log_contains_all_checker_output_lines": 0.0,
        "status_report_exists": 0.0,
        "status_report_purpose_and_rowcount": 0.0,
        "status_report_coverage_counts_correct": 0.0,
        "status_report_includes_summary_line": 0.0,
        "status_report_pass_fail_correct": 0.0,
        "status_report_issue_counts_by_code_correct": 0.0,
        "status_report_examples_per_issue_type": 0.0,
        "status_report_recommendations_present": 0.0,
    }

    input_csv = workspace / "input" / "quotes_en.csv"
    out_csv = workspace / "output" / "translated_quotes.csv"
    log_path = workspace / "output" / "check_log.txt"
    report_path = workspace / "output" / "status_report.md"

    # Load input CSV (source of truth for base fields)
    input_rows, input_header = _load_csv_dicts(input_csv)
    if input_rows is None or input_header is None:
        # Cannot proceed with comparisons; keep related checks at 0.0
        input_rows = []
        input_header = []

    # Check translated CSV
    if out_csv.exists():
        scores["translated_csv_exists"] = 1.0
        out_rows, out_header = _load_csv_dicts(out_csv)
        if out_rows is not None and out_header is not None:
            required_header = ['id', 'speaker', 'year', 'source', 'quote_en', 'es', 'fr']
            if out_header == required_header:
                scores["translated_csv_header_exact"] = 1.0
            # Row count matches input exactly
            if input_rows:
                if len(out_rows) == len(input_rows):
                    scores["translated_csv_row_count_matches_input"] = 1.0
                # Row order preserved and base fields preserved
                order_ok = True
                base_ok = True
                placeholders_ok = True
                es_non_empty = True
                fr_non_empty = True
                for idx, (in_row, out_row) in enumerate(zip(input_rows, out_rows)):
                    # Check base fields equality
                    for col in ['id', 'speaker', 'year', 'source', 'quote_en']:
                        in_val = (in_row.get(col) or "")
                        out_val = (out_row.get(col) or "")
                        if in_val != out_val:
                            base_ok = False
                    # Check order via id equality (base_ok covers this too), but extra check on id sequence
                    if (in_row.get('id') or "") != (out_row.get('id') or ""):
                        order_ok = False
                    # Check non-empty translations
                    es_val = (out_row.get('es') or "").strip()
                    fr_val = (out_row.get('fr') or "").strip()
                    if es_val == "":
                        es_non_empty = False
                    if fr_val == "":
                        fr_non_empty = False
                    # Check placeholders
                    if 'TODO' in (out_row.get('es') or "") or 'TBD' in (out_row.get('es') or ""):
                        placeholders_ok = False
                    if 'TODO' in (out_row.get('fr') or "") or 'TBD' in (out_row.get('fr') or ""):
                        placeholders_ok = False
                if base_ok:
                    scores["translated_csv_base_fields_preserved"] = 1.0
                if order_ok and len(out_rows) == len(input_rows):
                    scores["translated_csv_row_order_preserved"] = 1.0
                if es_non_empty and len(out_rows) == len(input_rows) and len(out_rows) > 0:
                    scores["translated_csv_es_non_empty_all"] = 1.0
                if fr_non_empty and len(out_rows) == len(input_rows) and len(out_rows) > 0:
                    scores["translated_csv_fr_non_empty_all"] = 1.0
                if placeholders_ok:
                    scores["translated_csv_no_placeholders"] = 1.0
    # Run checker to compare with log and to get issues and summary
    rerun_exit, rerun_stdout, rerun_stderr = (None, None, None)
    rerun_parse: Dict[str, Any] = {}
    if out_csv.exists():
        rerun_exit, rerun_stdout, rerun_stderr = _run_checker(workspace, out_csv)
        combined = _combine_output(rerun_stdout, rerun_stderr)
        rerun_parse = _parse_checker_output(combined)

    # Check log file
    if log_path.exists():
        scores["check_log_exists"] = 1.0
        log_text = _read_text_safe(log_path) or ""
        # Contains summary
        if "SUMMARY rows=" in log_text:
            scores["check_log_contains_summary"] = 1.0
        # Exit code recorded
        noted_code = _extract_exit_code_from_log(log_text)
        if noted_code is not None:
            scores["check_log_exit_code_recorded"] = 1.0
        # Exit code correct (compare to rerun)
        if noted_code is not None and rerun_exit is not None and noted_code == rerun_exit:
            scores["check_log_exit_code_correct"] = 1.0
        # Contains all checker output lines
        if rerun_stdout is not None or rerun_stderr is not None:
            combined = _combine_output(rerun_stdout, rerun_stderr)
            combined_lines = [ln for ln in combined.splitlines() if ln.strip()]
            if _contains_line_subset(log_text, combined_lines):
                scores["check_log_contains_all_checker_output_lines"] = 1.0

    # Status report checks
    if report_path.exists():
        scores["status_report_exists"] = 1.0
        report_text = _read_text_safe(report_path) or ""
        # Purpose and rowcount
        # Look for mention of Spanish/es and French/fr and the numeric row count
        row_count = len(input_rows) if input_rows else None
        purpose_ok = False
        langs_ok = False
        rows_ok = False
        if re.search(r"\b(spanish|es)\b", report_text, flags=re.IGNORECASE) and re.search(r"\b(french|fr)\b", report_text, flags=re.IGNORECASE):
            langs_ok = True
        if row_count is not None and re.search(rf"\b{row_count}\b", report_text):
            rows_ok = True
        # Consider purpose stated if both langs and row count are present
        if langs_ok and rows_ok:
            purpose_ok = True
        if purpose_ok:
            scores["status_report_purpose_and_rowcount"] = 1.0

        # Coverage counts
        out_rows, out_header = _load_csv_dicts(out_csv) if out_csv.exists() else (None, None)
        coverage_ok = False
        if out_rows is not None:
            es_cov = sum(1 for r in out_rows if (r.get("es") or "").strip() != "")
            fr_cov = sum(1 for r in out_rows if (r.get("fr") or "").strip() != "")
            es_counts_found = _find_int_near_tokens(report_text, ["es", "spanish"])
            fr_counts_found = _find_int_near_tokens(report_text, ["fr", "french"])
            es_ok = es_cov in es_counts_found
            fr_ok = fr_cov in fr_counts_found
            if es_ok and fr_ok:
                coverage_ok = True
        if coverage_ok:
            scores["status_report_coverage_counts_correct"] = 1.0

        # Include summary line
        rerun_summary = rerun_parse.get("summary_line")
        if rerun_summary and rerun_summary in report_text:
            scores["status_report_includes_summary_line"] = 1.0

        # Pass/fail correctness
        if rerun_exit is not None:
            if rerun_exit == 0:
                if re.search(r"\bpass(ed)?\b", report_text, flags=re.IGNORECASE):
                    scores["status_report_pass_fail_correct"] = 1.0
            else:
                if re.search(r"\bfail(ed)?\b", report_text, flags=re.IGNORECASE):
                    scores["status_report_pass_fail_correct"] = 1.0

        # Issue counts by code correctness
        counts_ok = True
        issue_counts: Dict[str, int] = rerun_parse.get("issue_counts") or {}
        for code, cnt in issue_counts.items():
            # For each code present, ensure the report lists the code and the exact count
            # Accept if a line contains the code and the count number
            pattern = re.compile(rf"{re.escape(code)}", flags=re.IGNORECASE)
            if not pattern.search(report_text):
                counts_ok = False
                break
            # Check for the count
            if not re.search(rf"{re.escape(code)}.*\b{cnt}\b", report_text, flags=re.IGNORECASE | re.DOTALL):
                # Also allow count before code on same paragraph/line
                if not re.search(rf"\b{cnt}\b.*{re.escape(code)}", report_text, flags=re.IGNORECASE | re.DOTALL):
                    counts_ok = False
                    break
        if issue_counts and counts_ok:
            scores["status_report_issue_counts_by_code_correct"] = 1.0
        elif not issue_counts:
            # No issues; consider this correct if report mentions zero errors and warnings or pass indication already checked
            # If pass was correct and summary included, accept this check
            if scores["status_report_includes_summary_line"] == 1.0 and scores["status_report_pass_fail_correct"] == 1.0:
                scores["status_report_issue_counts_by_code_correct"] = 1.0

        # Examples per issue type (at least one example per present code)
        examples_ok = True
        if issue_counts:
            for code in issue_counts.keys():
                # Look for the code plus an id and a language tag
                found_for_code = False
                # Simple heuristic: line containing code and 'id' and a number and (es|fr)
                lines = report_text.splitlines()
                for ln in lines:
                    if re.search(rf"{re.escape(code)}", ln, flags=re.IGNORECASE) and re.search(r"\bid\b", ln, flags=re.IGNORECASE) and re.search(r"\b(es|fr|spanish|french)\b", ln, flags=re.IGNORECASE):
                        if re.search(r"\b\d+\b", ln):
                            found_for_code = True
                            break
                if not found_for_code:
                    examples_ok = False
                    break
        else:
            examples_ok = True  # no issues => no examples needed
        if examples_ok:
            scores["status_report_examples_per_issue_type"] = 1.0

        # Recommendations present (look for "next steps" or "recommend" or imperative verbs like "fix")
        if re.search(r"next steps", report_text, flags=re.IGNORECASE) or re.search(r"recommend", report_text, flags=re.IGNORECASE) or re.search(r"\bfix\b", report_text, flags=re.IGNORECASE) or re.search(r"\baddress\b", report_text, flags=re.IGNORECASE):
            scores["status_report_recommendations_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()