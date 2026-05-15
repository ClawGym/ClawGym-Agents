import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_plan_markdown(text: str) -> List[Dict[str, Optional[str]]]:
    lines = text.splitlines()
    programs = []
    i = 0
    header_re = re.compile(r'^\s*(\d+)\)\s*(.+?)\s+—\s+(.+?)\s*$')
    intake_re = re.compile(r'^\s*-\s*Intended intake:\s*(.+?)\s*$')
    budget_re = re.compile(r'^\s*-\s*Annual budget \(USD\):\s*([\d]+)\s*$')
    scholarship_re = re.compile(r'^\s*-\s*Scholarship expectation:\s*(Yes|No)\s*$', re.IGNORECASE)
    validation_re = re.compile(r'^\s*-\s*Validation:\s*(.+?)\s*$')

    while i < len(lines):
        m = header_re.match(lines[i])
        if m:
            institution = m.group(2).strip()
            program_name = m.group(3).strip()
            intake = None
            budget = None
            scholarship = None
            validation = None
            j = i + 1
            while j < len(lines):
                if header_re.match(lines[j]):
                    break
                mi = intake_re.match(lines[j])
                mb = budget_re.match(lines[j])
                ms = scholarship_re.match(lines[j])
                mv = validation_re.match(lines[j])
                if mi:
                    intake = mi.group(1).strip()
                elif mb:
                    budget = mb.group(1).strip()
                elif ms:
                    scholarship = ms.group(1).strip().capitalize()
                elif mv:
                    validation = mv.group(1).strip()
                j += 1
            programs.append({
                "institution": institution,
                "program_name": program_name,
                "intended_intake": intake,
                "annual_budget_usd": budget,
                "scholarship_expectation": scholarship,
                "validation_text": validation
            })
            i = j
        else:
            i += 1
    return programs


def _compute_expected_checks(plan_prog: Dict[str, Optional[str]], catalog_rows: List[Dict[str, str]]) -> Dict[str, bool]:
    inst = (plan_prog.get("institution") or "").strip().casefold()
    pname = (plan_prog.get("program_name") or "").strip().casefold()
    budget_str = (plan_prog.get("annual_budget_usd") or "").strip()
    intake = (plan_prog.get("intended_intake") or "").strip()
    scholarship_expect = (plan_prog.get("scholarship_expectation") or "").strip().capitalize()

    match_row = None
    for row in catalog_rows:
        rinstitution = (row.get("institution", "")).strip().casefold()
        rprogram = (row.get("program_name", "")).strip().casefold()
        if rinstitution == inst and rprogram == pname:
            match_row = row
            break

    exists_in_catalog = match_row is not None

    tuition_budget_ok = False
    intake_match = False
    scholarship_expectation_match = False

    if exists_in_catalog:
        try:
            tuition = float(str(match_row.get("annual_tuition_usd", "")).strip())
        except Exception:
            tuition = None
        try:
            budget_val = float(budget_str) if budget_str != "" else None
        except Exception:
            budget_val = None
        if tuition is not None and budget_val is not None:
            tuition_budget_ok = budget_val >= tuition
        else:
            tuition_budget_ok = False

        intake_months_raw = str(match_row.get("intake_months", "")).strip()
        months = [m.strip().casefold() for m in intake_months_raw.split(";") if m.strip() != ""]
        intake_match = intake.strip().casefold() in months if intake else False

        sch_csv = str(match_row.get("scholarship_available", "")).strip().capitalize()
        scholarship_expectation_match = (scholarship_expect == sch_csv and scholarship_expect in {"Yes", "No"})
    else:
        tuition_budget_ok = False
        intake_match = False
        scholarship_expectation_match = False

    return {
        "exists_in_catalog": exists_in_catalog,
        "tuition_budget_ok": tuition_budget_ok,
        "intake_match": intake_match,
        "scholarship_expectation_match": scholarship_expectation_match
    }


def _expected_failed_checks_list(checks: Dict[str, bool]) -> List[str]:
    ordered_keys = ["exists_in_catalog", "intake_match", "scholarship_expectation_match", "tuition_budget_ok"]
    failed = [k for k in ordered_keys if not checks.get(k, False)]
    return failed


def _load_json_safe(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_sections(markdown_text: str) -> Dict[str, Tuple[int, int]]:
    lines = markdown_text.splitlines()
    sections = {}
    titles_order = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            norm = title.lower()
            if norm in ["inputs found", "results", "failures"]:
                titles_order.append((norm, idx))
    for i, (name, start) in enumerate(titles_order):
        end = len(lines)
        if i + 1 < len(titles_order):
            end = titles_order[i + 1][1]
        sections[name] = (start, end)
    return sections


def _section_text(markdown_text: str, section_range: Tuple[int, int]) -> str:
    lines = markdown_text.splitlines()
    start, end = section_range
    content_lines = lines[start + 1:end]
    return "\n".join(content_lines).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tests_report_exists": 0.0,
        "tests_report_structure_correct": 0.0,
        "tests_report_content_correct": 0.0,
        "plan_md_validation_lines_correct": 0.0,
        "validation_summary_exists": 0.0,
        "validation_summary_sections_present_and_ordered": 0.0,
        "validation_summary_inputs_found_includes_required_paths": 0.0,
        "validation_summary_results_correct": 0.0,
        "validation_summary_failures_correct": 0.0,
    }

    catalog_path = workspace / "data" / "programs.csv"
    plan_path = workspace / "docs" / "application_plan.md"
    report_json_path = workspace / "tests" / "program_plan_validation.json"
    summary_md_path = workspace / "reports" / "validation_summary.md"

    catalog_rows = None
    plan_text = None
    plan_programs: List[Dict[str, Optional[str]]] = []

    catalog_ok = False
    plan_ok = False

    if catalog_path.is_file():
        catalog_rows = _load_csv_dicts(catalog_path)
        if catalog_rows is not None:
            catalog_ok = True

    if plan_path.is_file():
        plan_text = _read_text_safe(plan_path)
        if plan_text is not None:
            plan_programs = _parse_plan_markdown(plan_text)
            if len(plan_programs) > 0:
                plan_ok = True

    expected_by_key: Dict[Tuple[str, str], Dict[str, bool]] = {}
    expected_pass_fail: Dict[Tuple[str, str], str] = {}
    expected_failed_checks_by_key: Dict[Tuple[str, str], List[str]] = {}
    if catalog_ok and plan_ok:
        for prog in plan_programs:
            key = (prog["institution"], prog["program_name"])
            checks = _compute_expected_checks(prog, catalog_rows)
            expected_by_key[key] = checks
            failed_checks = _expected_failed_checks_list(checks)
            expected_failed_checks_by_key[key] = failed_checks
            overall = "pass" if all(checks.values()) else "fail"
            expected_pass_fail[key] = overall

    if report_json_path.is_file():
        scores["tests_report_exists"] = 1.0
        data = _load_json_safe(report_json_path)
        if isinstance(data, list) and len(data) >= 1:
            per_program_entries = data[:-1]
            summary_entry = data[-1]
            structure_ok = True
            if not isinstance(summary_entry, dict) or "summary" not in summary_entry or not isinstance(summary_entry["summary"], dict):
                structure_ok = False
            else:
                summary_obj = summary_entry["summary"]
                if not all(k in summary_obj for k in ["total", "passed", "failed"]):
                    structure_ok = False
                else:
                    if not (isinstance(summary_obj["total"], int) and isinstance(summary_obj["passed"], int) and isinstance(summary_obj["failed"], int)):
                        structure_ok = False
            for entry in per_program_entries:
                if not isinstance(entry, dict):
                    structure_ok = False
                    break
                required_keys = ["institution", "program_name", "exists_in_catalog", "tuition_budget_ok", "intake_match", "scholarship_expectation_match", "overall"]
                if not all(k in entry for k in required_keys):
                    structure_ok = False
                    break
                if not isinstance(entry["institution"], str) or not isinstance(entry["program_name"], str):
                    structure_ok = False
                    break
                if not isinstance(entry["exists_in_catalog"], bool) or not isinstance(entry["tuition_budget_ok"], bool) or not isinstance(entry["intake_match"], bool) or not isinstance(entry["scholarship_expectation_match"], bool):
                    structure_ok = False
                    break
                if not isinstance(entry["overall"], str) or entry["overall"] not in ("pass", "fail"):
                    structure_ok = False
                    break
            if structure_ok:
                scores["tests_report_structure_correct"] = 1.0

            if catalog_ok and plan_ok and scores["tests_report_structure_correct"] == 1.0:
                content_ok = True
                json_map: Dict[Tuple[str, str], Dict[str, object]] = {}
                for entry in per_program_entries:
                    key = (entry["institution"], entry["program_name"])
                    if key in json_map:
                        content_ok = False
                        break
                    json_map[key] = entry

                expected_keys_set = set(expected_by_key.keys())
                json_keys_set = set(json_map.keys())
                if json_keys_set != expected_keys_set:
                    content_ok = False
                else:
                    for key in expected_keys_set:
                        exp_checks = expected_by_key[key]
                        exp_overall = expected_pass_fail[key]
                        ent = json_map[key]
                        if ent["exists_in_catalog"] != exp_checks["exists_in_catalog"]:
                            content_ok = False
                            break
                        if ent["tuition_budget_ok"] != exp_checks["tuition_budget_ok"]:
                            content_ok = False
                            break
                        if ent["intake_match"] != exp_checks["intake_match"]:
                            content_ok = False
                            break
                        if ent["scholarship_expectation_match"] != exp_checks["scholarship_expectation_match"]:
                            content_ok = False
                            break
                        if ent["overall"] != exp_overall:
                            content_ok = False
                            break
                if content_ok:
                    summary = summary_entry["summary"]
                    total_expected = len(expected_by_key)
                    passed_expected = sum(1 for v in expected_pass_fail.values() if v == "pass")
                    failed_expected = total_expected - passed_expected
                    if not (summary.get("total") == total_expected and summary.get("passed") == passed_expected and summary.get("failed") == failed_expected):
                        content_ok = False

                if content_ok:
                    scores["tests_report_content_correct"] = 1.0

    if plan_ok and catalog_ok:
        all_correct = True
        if plan_text is not None:
            lines = plan_text.splitlines()
            for line in lines:
                if re.search(r'\bValidation:\s*pending\b', line, re.IGNORECASE):
                    all_correct = False
                    break
        if all_correct:
            for prog in plan_programs:
                key = (prog["institution"], prog["program_name"])
                checks = expected_by_key.get(key, None)
                if checks is None:
                    all_correct = False
                    break
                failed_checks = _expected_failed_checks_list(checks)
                if len(failed_checks) == 0:
                    expected_val_line = "PASS"
                else:
                    expected_val_line = f"FAIL (list_failed_checks: {', '.join(failed_checks)})"
                actual_val_text = prog.get("validation_text")
                if actual_val_text is None:
                    all_correct = False
                    break
                if actual_val_text != expected_val_line:
                    all_correct = False
                    break
        if all_correct:
            scores["plan_md_validation_lines_correct"] = 1.0

    if summary_md_path.is_file():
        scores["validation_summary_exists"] = 1.0
        summary_text = _read_text_safe(summary_md_path)
        if summary_text is not None:
            sections = _extract_sections(summary_text)
            has_inputs = "inputs found" in sections
            has_results = "results" in sections
            expected_fail_section = None
            if catalog_ok and plan_ok:
                failures_exist = any(v == "fail" for v in expected_pass_fail.values())
                expected_fail_section = True if failures_exist else False

            ordered_ok = False
            if has_inputs and has_results:
                idx_inputs = sections["inputs found"][0]
                idx_results = sections["results"][0]
                if idx_inputs < idx_results:
                    if expected_fail_section is None:
                        if "failures" in sections:
                            idx_fail = sections["failures"][0]
                            ordered_ok = idx_results < idx_fail
                        else:
                            ordered_ok = True
                    elif expected_fail_section:
                        if "failures" in sections:
                            idx_fail = sections["failures"][0]
                            ordered_ok = idx_results < idx_fail
                        else:
                            ordered_ok = False
                    else:
                        ordered_ok = ("failures" not in sections)
            if ordered_ok:
                scores["validation_summary_sections_present_and_ordered"] = 1.0

            if has_inputs:
                inputs_text = _section_text(summary_text, sections["inputs found"])
                bullets = [ln.strip() for ln in inputs_text.splitlines() if ln.strip().startswith("- ")]
                has_catalog_ref = any("data/programs.csv" in b for b in bullets)
                has_plan_ref = any("docs/application_plan.md" in b for b in bullets)
                if catalog_path.is_file() and plan_path.is_file() and has_catalog_ref and has_plan_ref:
                    scores["validation_summary_inputs_found_includes_required_paths"] = 1.0

            if has_results and catalog_ok and plan_ok:
                results_text = _section_text(summary_text, sections["results"])
                total_expected = len(expected_by_key)
                passed_expected = sum(1 for v in expected_pass_fail.values() if v == "pass")
                failed_expected = total_expected - passed_expected

                def _num_present(txt: str, n: int) -> bool:
                    return re.search(r'\b' + re.escape(str(n)) + r'\b', txt) is not None

                if _num_present(results_text.lower(), total_expected) and _num_present(results_text.lower(), passed_expected) and _num_present(results_text.lower(), failed_expected):
                    scores["validation_summary_results_correct"] = 1.0

            if catalog_ok and plan_ok:
                failures_expected = { (k[0], k[1]): expected_failed_checks_by_key[k] for k in expected_failed_checks_by_key if len(expected_failed_checks_by_key[k]) > 0 }
                if len(failures_expected) == 0:
                    if "failures" not in sections:
                        scores["validation_summary_failures_correct"] = 1.0
                else:
                    if "failures" in sections:
                        failures_text = _section_text(summary_text, sections["failures"])
                        entries: Dict[Tuple[str, str], str] = {}
                        for ln in failures_text.splitlines():
                            line = ln.strip()
                            if not line:
                                continue
                            if line.startswith("- "):
                                line = line[2:].strip()
                            if ":" not in line or "—" not in line:
                                continue
                            left, right = line.split(":", 1)
                            left = left.strip()
                            right = right.strip()
                            parts = left.split("—")
                            if len(parts) != 2:
                                continue
                            inst = parts[0].strip()
                            pname = parts[1].strip()
                            entries[(inst, pname)] = right
                        if set(entries.keys()) == set(failures_expected.keys()):
                            ok = True
                            for key, fail_list in failures_expected.items():
                                expected_str = ", ".join(fail_list)
                                if entries.get(key) != expected_str:
                                    ok = False
                                    break
                            if ok:
                                scores["validation_summary_failures_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()