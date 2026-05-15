import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_csv_cases(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return None
    if not text:
        return None
    header = text[0].split(",")
    rows = []
    for line in text[1:]:
        if not line.strip():
            continue
        parts = []
        current = ""
        in_quote = False
        for ch in line:
            if ch == '"' and not in_quote:
                in_quote = True
                current += ch
            elif ch == '"' and in_quote:
                in_quote = False
                current += ch
            elif ch == ',' and not in_quote:
                parts.append(current)
                current = ""
            else:
                current += ch
        parts.append(current)
        if len(parts) != len(header):
            return None
        row = {h.strip(): p.strip() for h, p in zip(header, parts)}
        rows.append(row)
    return rows


def import_beam_module(workspace: Path):
    try:
        sys.path.insert(0, str(workspace))
        import importlib
        beam = importlib.import_module("src.beam")
        return beam
    except Exception:
        return None
    finally:
        if str(workspace) in sys.path:
            try:
                sys.path.remove(str(workspace))
            except ValueError:
                pass


def compute_deflections_from_function(workspace: Path, cases: List[Dict[str, str]]) -> Optional[Dict[str, float]]:
    beam = import_beam_module(workspace)
    if beam is None or not hasattr(beam, "cantilever_udl_max_deflection"):
        return None
    results = {}
    for row in cases:
        try:
            case_id = row["case_id"]
            E_GPa = float(row["E_GPa"])
            I_m4 = float(eval(row["I_m4"])) if any(ch in row["I_m4"] for ch in ("e", "E")) else float(row["I_m4"])
            L_m = float(row["L_m"])
            w = float(row["w_N_per_m"])
            val = float(beam.cantilever_udl_max_deflection(E_GPa, I_m4, L_m, w))
            results[case_id] = val
        except Exception:
            return None
    return results


def parse_pytest_report_counts(text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    # Extract passed and failed counts; ignore skipped/xfail for this task
    passed = None
    failed = None
    # Search all summary lines
    # Examples: "3 passed in 0.12s", "2 passed, 1 failed in 0.12s"
    # Capture last occurrence
    passed_matches = list(re.finditer(r"(\d+)\s+passed", text))
    failed_matches = list(re.finditer(r"(\d+)\s+failed", text))
    if passed_matches:
        passed = int(passed_matches[-1].group(1))
    if failed_matches:
        failed = int(failed_matches[-1].group(1))
    if passed is None and failed is None:
        return None, None, None
    if passed is None:
        passed = 0
    if failed is None:
        failed = 0
    total = passed + failed
    return total, passed, failed


def extract_failure_info(text: str, case_ids: List[str]) -> Tuple[List[str], List[str]]:
    lines = text.splitlines()
    failure_lines = []
    failed_cases_set = set()
    for line in lines:
        if "FAILED" in line or "AssertionError" in line:
            for cid in case_ids:
                if cid in line:
                    failure_lines.append(line)
                    failed_cases_set.add(cid)
    # Deduplicate while preserving order
    seen = set()
    unique_failure_lines = []
    for ln in failure_lines:
        if ln not in seen:
            unique_failure_lines.append(ln)
            seen.add(ln)
    failed_cases = [cid for cid in case_ids if cid in failed_cases_set]
    return failed_cases, unique_failure_lines


def parse_markdown_table_cases(md_text: str) -> Optional[Dict[str, Dict[str, str]]]:
    # Find header line with required columns in order
    lines = [ln.strip() for ln in md_text.splitlines()]
    header_idx = None
    headers = None
    for i, ln in enumerate(lines):
        if "|" in ln and "case_id" in ln and "expected_max_deflection_m" in ln and "computed_max_deflection_m" in ln and "status" in ln:
            # parse columns
            parts = [c.strip(" `") for c in ln.split("|")]
            parts = [p for p in parts if p != ""]
            # Expect exactly these four in order
            try:
                idx_case = parts.index("case_id")
                idx_exp = parts.index("expected_max_deflection_m")
                idx_comp = parts.index("computed_max_deflection_m")
                idx_status = parts.index("status")
                # ensure order
                if [idx_case, idx_exp, idx_comp, idx_status] == sorted([idx_case, idx_exp, idx_comp, idx_status]):
                    headers = parts
                    header_idx = i
                    break
            except ValueError:
                continue
    if header_idx is None or headers is None:
        return None
    # Parse rows following header; skip possible separator line
    rows = {}
    for ln in lines[header_idx + 1:]:
        if not ln or "|" not in ln:
            continue
        # Skip alignment separator
        if set(ln.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        parts = [c.strip() for c in ln.split("|")]
        parts = [p for p in parts if p != ""]
        if len(parts) < 4:
            continue
        # Map header names to values by index
        try:
            idx_case = headers.index("case_id")
            idx_exp = headers.index("expected_max_deflection_m")
            idx_comp = headers.index("computed_max_deflection_m")
            idx_status = headers.index("status")
        except ValueError:
            return None
        try:
            case_id = parts[idx_case]
            expected = parts[idx_exp]
            computed = parts[idx_comp]
            status = parts[idx_status].upper()
        except IndexError:
            continue
        if not case_id:
            continue
        rows[case_id] = {
            "expected": expected,
            "computed": computed,
            "status": status,
        }
    return rows if rows else None


def safe_float(val: str) -> Optional[float]:
    try:
        if any(ch in val for ch in ("e", "E")):
            return float(val)
        return float(val)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_exist_and_parametrized": 0.0,
        "tests_use_ids_case_id": 0.0,
        "tests_call_function_and_tolerance": 0.0,
        "tests_assertion_message_includes_case_info": 0.0,
        "pytest_report_parsed": 0.0,
        "validation_summary_structure_and_consistency": 0.0,
        "lab_report_validated_table_consistency": 0.0,
        "meeting_notes_content": 0.0,
        "email_to_ta_content": 0.0,
        "cross_artifact_consistency_counts": 0.0,
    }

    # Load reference cases
    cases_csv_path = workspace / "data" / "reference_cases.csv"
    cases_rows = parse_csv_cases(cases_csv_path) or []
    case_ids = [row.get("case_id", "") for row in cases_rows if "case_id" in row]
    case_ids = [cid for cid in case_ids if cid]

    # 1) tests/test_beam.py checks
    test_file = workspace / "tests" / "test_beam.py"
    test_text = read_text_safe(test_file)
    if test_text is not None:
        # Exists and parametrized reading CSV
        cond_param = ("pytest.mark.parametrize" in test_text) and ("data/reference_cases.csv" in test_text) and ("case_id" in test_text)
        if cond_param:
            scores["tests_exist_and_parametrized"] = 1.0
        # ids for node IDs
        if "ids=" in test_text and "case_id" in test_text:
            scores["tests_use_ids_case_id"] = 1.0
        # calls function and uses tolerance 1e-6
        if ("cantilever_udl_max_deflection" in test_text) and ("1e-6" in test_text):
            scores["tests_call_function_and_tolerance"] = 1.0
        # assertion message content: includes case_id, expected, computed
        # Heuristic: presence of 'assert' and all three keywords in file
        if ("assert" in test_text) and ("case_id" in test_text) and ("expected" in test_text) and ("computed" in test_text):
            scores["tests_assertion_message_includes_case_info"] = 1.0

    # 2) pytest report parsing
    report_path = workspace / "output" / "test_report.txt"
    report_text = read_text_safe(report_path)
    total_r = None
    passed_r = None
    failed_r = None
    failed_cases_from_report: List[str] = []
    failure_lines: List[str] = []
    if report_text is not None:
        total_r, passed_r, failed_r = parse_pytest_report_counts(report_text)
        if total_r is not None and passed_r is not None and failed_r is not None:
            scores["pytest_report_parsed"] = 1.0
        if case_ids:
            failed_cases_from_report, failure_lines = extract_failure_info(report_text, case_ids)

    # 3) validation_summary.json checks
    summary_path = workspace / "output" / "validation_summary.json"
    summary = load_json_safe(summary_path)
    summary_ok = False
    if summary is not None and isinstance(summary, dict):
        required_keys = {"total", "passed", "failed", "failed_cases", "failure_lines"}
        has_keys = required_keys.issubset(set(summary.keys()))
        types_ok = isinstance(summary.get("total"), int) and isinstance(summary.get("passed"), int) and isinstance(summary.get("failed"), int) and isinstance(summary.get("failed_cases"), list) and isinstance(summary.get("failure_lines"), list)
        if has_keys and types_ok and report_text is not None and passed_r is not None and failed_r is not None:
            counts_match = (summary["passed"] == passed_r) and (summary["failed"] == failed_r) and (summary["total"] == (passed_r + failed_r))
            # failed_cases should be subset of known case_ids and match those seen in report if any were detected
            failed_cases_list = summary.get("failed_cases", [])
            # If we detected failed cases from report, compare sets; otherwise, accept as long as all failed cases appear in report text.
            failed_cases_in_report_text = all((cid in report_text) for cid in failed_cases_list)
            if failed_cases_from_report:
                failed_cases_match = sorted(failed_cases_list) == sorted(failed_cases_from_report)
            else:
                failed_cases_match = failed_cases_in_report_text
            # failure_lines must be verbatim lines from report that include each failing case_id
            failure_lines_list = summary.get("failure_lines", [])
            # All failure_lines must appear in report_text and contain at least one failing case_id if any
            lines_in_report = all((ln in report_text) for ln in failure_lines_list)
            if failed_cases_list:
                each_fail_referenced = all(any((cid in ln) for ln in failure_lines_list) for cid in failed_cases_list)
            else:
                each_fail_referenced = True
            summary_ok = counts_match and failed_cases_match and lines_in_report and each_fail_referenced
    if summary_ok:
        scores["validation_summary_structure_and_consistency"] = 1.0

    # 4) lab_report_validated.md parsing and consistency
    lab_validated_path = workspace / "docs" / "lab_report_validated.md"
    lab_text = read_text_safe(lab_validated_path)
    lab_ok = False
    if lab_text is not None:
        table = parse_markdown_table_cases(lab_text)
        if table is not None and case_ids:
            # Ensure all cases present
            all_present = all(cid in table for cid in case_ids)
            # Compute values using function
            computed_func = compute_deflections_from_function(workspace, cases_rows) if cases_rows else None
            computed_match = True
            if computed_func is None:
                computed_match = False
            else:
                for cid in case_ids:
                    row = table.get(cid, {})
                    comp_str = row.get("computed", "")
                    comp_val = safe_float(comp_str)
                    if comp_val is None:
                        computed_match = False
                        break
                    func_val = computed_func.get(cid)
                    if func_val is None or abs(comp_val - func_val) > 1e-6:
                        computed_match = False
                        break
            # Status consistency with summary (if available)
            status_ok = True
            if summary_ok:
                failed_cases_list = summary.get("failed_cases", [])
                for cid in case_ids:
                    status = table.get(cid, {}).get("status", "").upper()
                    expected_status = "FAIL" if cid in failed_cases_list else "PASS"
                    if status != expected_status:
                        status_ok = False
                        break
                # Count consistency
                pass_count_table = sum(1 for cid in case_ids if table.get(cid, {}).get("status", "").upper() == "PASS")
                fail_count_table = sum(1 for cid in case_ids if table.get(cid, {}).get("status", "").upper() == "FAIL")
                counts_match_summary = (pass_count_table == summary.get("passed")) and (fail_count_table == summary.get("failed")) and ((pass_count_table + fail_count_table) == summary.get("total"))
            else:
                counts_match_summary = False
            lab_ok = all_present and computed_match and status_ok and counts_match_summary
    if lab_ok:
        scores["lab_report_validated_table_consistency"] = 1.0

    # 5) meeting_notes.md checks
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    meeting_text = read_text_safe(meeting_notes_path)
    meeting_ok = False
    if meeting_text is not None:
        lines = [ln.strip() for ln in meeting_text.splitlines() if ln.strip()]
        # Brief summary of how validation was performed (1-2 sentences) - heuristic: mentions pytest/tests or CSV or src/beam.py
        mentions_method = any(term in meeting_text for term in ["pytest", "tests", "data/reference_cases.csv", "src/beam.py", "CSV"])
        failing_ids_from_summary = summary.get("failed_cases", []) if summary_ok else []
        # Bullet list of failing case_ids if any
        bullet_lines = [ln for ln in lines if ln.startswith(("-", "*"))]
        if failing_ids_from_summary:
            bullets_have_ids = all(any(cid in bl for bl in bullet_lines) for cid in failing_ids_from_summary)
            # At least one action item per failing case_id with owner "me"
            action_items_ok = all(any((cid in ln and "me" in ln) for ln in bullet_lines) for cid in failing_ids_from_summary)
        else:
            bullets_have_ids = True
            action_items_ok = True
        meeting_ok = mentions_method and bullets_have_ids and action_items_ok
    if meeting_ok:
        scores["meeting_notes_content"] = 1.0

    # 6) email_to_TA.txt checks
    email_path = workspace / "output" / "email_to_TA.txt"
    email_text = read_text_safe(email_path)
    email_ok = False
    if email_text is not None:
        lines = [ln.strip() for ln in email_text.splitlines() if ln.strip()]
        has_subject = any(ln.lower().startswith("subject:") for ln in lines)
        # include pass/fail counts consistent with summary
        counts_ok = False
        if summary_ok:
            passed = summary.get("passed")
            failed = summary.get("failed")
            # search for patterns like "X passed" and "Y failed" or "Passed: X" "Failed: Y"
            passed_found = re.search(rf"\b{passed}\s+passed\b", email_text, flags=re.IGNORECASE) or re.search(rf"passed\s*[:\-]\s*{passed}\b", email_text, flags=re.IGNORECASE)
            failed_found = re.search(rf"\b{failed}\s+failed\b", email_text, flags=re.IGNORECASE) or re.search(rf"failed\s*[:\-]\s*{failed}\b", email_text, flags=re.IGNORECASE)
            counts_ok = bool(passed_found and failed_found)
        # list artifact paths
        paths_ok = all(p in email_text for p in [
            "output/test_report.txt",
            "output/validation_summary.json",
            "docs/lab_report_validated.md",
            "output/meeting_notes.md",
        ])
        has_question = "?" in email_text
        email_ok = has_subject and counts_ok and paths_ok and has_question
    if email_ok:
        scores["email_to_ta_content"] = 1.0

    # 7) cross artifact consistency counts
    cross_ok = False
    if summary_ok and report_text is not None and passed_r is not None and failed_r is not None and lab_ok:
        # check summary counts vs report counts already in summary_ok
        # additionally ensure failed_cases from report match table statuses
        table_fail_ids = []
        if lab_text is not None:
            table = parse_markdown_table_cases(lab_text) or {}
            for cid in case_ids:
                if table.get(cid, {}).get("status", "").upper() == "FAIL":
                    table_fail_ids.append(cid)
        # Compare sorted sets
        report_fail_ids = sorted(failed_cases_from_report) if failed_cases_from_report else sorted(summary.get("failed_cases", []))
        cross_ok = (sorted(summary.get("failed_cases", [])) == report_fail_ids == sorted(table_fail_ids)) and \
                   (summary.get("passed") == passed_r) and (summary.get("failed") == failed_r)
    if cross_ok:
        scores["cross_artifact_consistency_counts"] = 1.0

    return scores


def main() -> None:
    import argparse
    import sys as _sys
    parser = argparse.ArgumentParser(description="Grader for beam deflection validation task")
    parser.add_argument("workspace_path", nargs="?", default=".", help="Path to the workspace root")
    args = parser.parse_args()
    result = grade([], args.workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()