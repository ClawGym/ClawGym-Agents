import json
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
import sys


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _float_eq(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except Exception:
        return False


def _as_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _as_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, int):
            return val
        if isinstance(val, float) and val.is_integer():
            return int(val)
        s = str(val).strip()
        return int(s)
    except Exception:
        return None


def _norm_str(s: Any) -> str:
    return str(s).strip().lower()


def _parse_exam_str(item: str) -> Tuple[str, Optional[str]]:
    name = item.strip()
    code = None
    m = re.search(r"\(([^)]+)\)\s*$", name)
    if m:
        code = m.group(1).strip()
        name = name[: m.start()].strip()
    return (name, code)


def _canon_exam(entry: Any) -> Tuple[str, str]:
    if isinstance(entry, dict):
        name = entry.get("name") or entry.get("exam") or entry.get("title") or ""
        code = entry.get("code") or ""
        return (_norm_str(name), _norm_str(code))
    elif isinstance(entry, str):
        name, code = _parse_exam_str(entry)
        return (_norm_str(name), _norm_str(code or ""))
    else:
        return (_norm_str(str(entry)), "")


def _canon_exam_set(items: Any) -> set:
    if not isinstance(items, list):
        return set()
    return set(_canon_exam(x) for x in items)


def _canon_str_set(items: Any) -> set:
    if not isinstance(items, list):
        return set()
    return set(_norm_str(x) for x in items)


def _extract_state_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    state_path = workspace / "input" / "state_requirements.json"
    state = _load_json(state_path)
    if not isinstance(state, dict):
        return None
    coursework = {}
    for r in state.get("coursework_requirements", []):
        area = r.get("area")
        credits = r.get("credits")
        if isinstance(area, str) and isinstance(credits, (int, float)):
            coursework[area] = int(credits)
    state_exams = []
    for ex in state.get("required_exams", []):
        if isinstance(ex, dict):
            name = ex.get("name")
            code = ex.get("code")
            if isinstance(name, str):
                state_exams.append({"name": name, "code": str(code) if code is not None else ""})
    return {
        "min_gpa": state.get("min_gpa"),
        "student_teaching_weeks": state.get("student_teaching", {}).get("required_weeks"),
        "background_check": state.get("background_check", []),
        "required_exams": state_exams,
        "coursework": coursework,
    }


def _extract_university_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    uni_path = workspace / "input" / "university_advising_sheet.csv"
    rows = _load_csv(uni_path)
    if rows is None:
        return None
    min_gpa = None
    student_teaching_weeks = None
    background_check = []
    exams_list = []
    coursework = {}
    for row in rows:
        category = (row.get("category") or "").strip()
        subcategory = (row.get("subcategory") or "").strip()
        value = (row.get("value") or "").strip()
        units = (row.get("units") or "").strip()
        if category.lower() == "min gpa" and subcategory.lower() == "policy":
            min_gpa = _as_float(value)
        if category.lower() == "student teaching" and subcategory.lower() == "policy":
            w = _as_int(value)
            if units.lower() == "weeks":
                student_teaching_weeks = w
        if category.lower() == "background check" and subcategory.lower() == "policy":
            if value.lower().strip() == "state only":
                background_check = ["Riverland State"]
            else:
                parts = re.split(r"[;,]", value)
                background_check = [p.strip() for p in parts if p.strip()]
        if category.lower() == "required exams" and subcategory.lower() == "exam":
            if value:
                parts = [p.strip() for p in value.split(";") if p.strip()]
                for p in parts:
                    name, code = _parse_exam_str(p)
                    exams_list.append({"name": name, "code": code or ""})
        if subcategory.lower() == "coursework":
            credits = _as_int(value)
            if credits is not None:
                coursework[category] = credits
    return {
        "min_gpa": min_gpa,
        "student_teaching_weeks": student_teaching_weeks,
        "background_check": background_check,
        "required_exams": exams_list,
        "coursework": coursework,
    }


def _extract_student(workspace: Path) -> Optional[Dict[str, Any]]:
    stud_path = workspace / "input" / "student_coursework.json"
    data = _load_json(stud_path)
    if not isinstance(data, dict):
        return None
    return data


def _load_verification_report(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / "output" / "verification_report.json"
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _validate_structure(report: Dict[str, Any]) -> bool:
    required_keys = [
        "state_summary",
        "university_summary",
        "consistencies",
        "discrepancies",
        "student_status_vs_state",
        "student_status_vs_university",
    ]
    for k in required_keys:
        if k not in report:
            return False
    if not isinstance(report["state_summary"], dict):
        return False
    if not isinstance(report["university_summary"], dict):
        return False
    if not isinstance(report["consistencies"], list):
        return False
    if not isinstance(report["discrepancies"], list):
        return False
    if not isinstance(report["student_status_vs_state"], dict):
        return False
    if not isinstance(report["student_status_vs_university"], dict):
        return False
    for key in ["student_status_vs_state", "student_status_vs_university"]:
        ss = report.get(key, {})
        if not isinstance(ss, dict):
            return False
        if "gpa_ok" not in ss or "missing_coursework" not in ss or "missing_exams" not in ss or "background_check_gaps" not in ss:
            return False
        if not isinstance(ss["gpa_ok"], bool):
            return False
        if not isinstance(ss["missing_coursework"], list):
            return False
        if not isinstance(ss["missing_exams"], list):
            return False
        if not isinstance(ss["background_check_gaps"], list):
            return False
    return True


def _compare_summaries(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    if "min_gpa" in expected:
        if _as_float(actual.get("min_gpa")) is None or not _float_eq(actual.get("min_gpa"), expected.get("min_gpa")):
            return False
    if "student_teaching_weeks" in expected:
        a_weeks = _as_int(actual.get("student_teaching_weeks"))
        e_weeks = _as_int(expected.get("student_teaching_weeks"))
        if a_weeks is None or e_weeks is None or a_weeks != e_weeks:
            return False
    a_bg = _canon_str_set(actual.get("background_check", []))
    e_bg = _canon_str_set(expected.get("background_check", []))
    if a_bg != e_bg:
        return False
    a_exams = _canon_exam_set(actual.get("required_exams", []))
    e_exams = _canon_exam_set(expected.get("required_exams", []))
    if a_exams != e_exams:
        return False
    a_cw = actual.get("coursework", {})
    if not isinstance(a_cw, dict):
        return False
    if set(a_cw.keys()) != set(expected.get("coursework", {}).keys()):
        return False
    for k, v in expected.get("coursework", {}).items():
        if _as_int(a_cw.get(k)) != _as_int(v):
            return False
    return True


def _find_item_presence(entries: List[Dict[str, Any]], label_keywords: List[str]) -> bool:
    for e in entries:
        item = str(e.get("item", "")).lower()
        if all(kw.lower() in item for kw in label_keywords):
            return True
    return False


def _extract_discrepancy_entries(report: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cons = report.get("consistencies", [])
    disc = report.get("discrepancies", [])
    cons_list = cons if isinstance(cons, list) else []
    disc_list = disc if isinstance(disc, list) else []
    return cons_list, disc_list


def _compute_missing_coursework(required: Dict[str, int], completed_list: List[Dict[str, Any]]) -> List[Dict[str, int]]:
    completed = {item.get("area"): _as_int(item.get("credits")) or 0 for item in completed_list if isinstance(item, dict) and "area" in item}
    missing = []
    for area, req in required.items():
        got = completed.get(area, 0)
        miss = (req or 0) - (got or 0)
        if miss > 0:
            missing.append({"area": area, "missing_credits": miss})
    missing.sort(key=lambda x: x["area"].lower())
    return missing


def _compute_missing_exams(required_exams: List[Dict[str, Any]], student_exams: List[Dict[str, Any]]) -> List[str]:
    passed = set()
    for ex in student_exams or []:
        if isinstance(ex, dict) and str(ex.get("status", "")).lower() == "passed":
            nm = ex.get("name") or ex.get("exam") or ""
            code = ex.get("code") or ""
            passed.add(_canon_exam({"name": nm, "code": code}))
    missing_names = []
    for ex in required_exams:
        c = _canon_exam(ex)
        if c not in passed:
            name = ex.get("name") if isinstance(ex, dict) else None
            code = ex.get("code") if isinstance(ex, dict) else None
            if not name and isinstance(ex, str):
                name, code = _parse_exam_str(ex)
            disp = name
            if code:
                disp = f"{name} ({code})"
            missing_names.append(disp or (c[0]))
    return missing_names


def _compute_background_gaps(required_agencies: List[str], student_checks: Dict[str, Any]) -> List[str]:
    required = set(_canon_str_set(required_agencies))
    gaps = []
    if not isinstance(student_checks, dict):
        gaps = [a for a in sorted(required)]
        return gaps
    for agency in required:
        found = None
        for k, v in student_checks.items():
            if _norm_str(k) == agency:
                found = v
                break
        status = str(found).lower() if found is not None else ""
        if status != "submitted":
            gaps.append(agency)
    return [g for g in gaps]


def _status_matches(expected_missing: List[Dict[str, int]], actual_missing: Any) -> bool:
    if not isinstance(actual_missing, list):
        return False

    def to_map(lst):
        m = {}
        for it in lst:
            if isinstance(it, dict) and "area" in it and "missing_credits" in it:
                m[str(it["area"]).strip()] = _as_int(it["missing_credits"])
        return m

    e_map = to_map(expected_missing)
    a_map = to_map(actual_missing)
    return e_map == a_map


def _check_run_log(workspace: Path) -> Tuple[bool, bool, bool]:
    log_path = workspace / "output" / "run_log.txt"
    txt = _read_text(log_path)
    if txt is None:
        return (False, False, False)
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return (True, False, False)
    has_command = "verify_requirements.py" in lines[0]
    has_status = False
    if len(lines) >= 2:
        status_line = lines[1]
        exit_match = re.search(r"exit\s*code\s*[:=]\s*(-?\d+)", status_line, re.IGNORECASE)
        ts_match = re.search(r"\d{4}-\d{2}-\d{2}", status_line) or re.search(r"\d{2}:\d{2}(:\d{2})?", status_line)
        has_status = (exit_match is not None) and (ts_match is not None)
    return (True, has_command, has_status)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "verify_script_exists": 0.0,
        "run_log_present_and_formatted": 0.0,
        "verification_report_exists_and_well_formed": 0.0,
        "state_summary_matches_input": 0.0,
        "university_summary_matches_input": 0.0,
        "comparisons_cover_required_items": 0.0,
        "student_status_vs_state_correct": 0.0,
        "student_status_vs_university_correct": 0.0,
        "status_update_covers_facts": 0.0,
        "status_update_lists_discrepancies": 0.0,
        "status_update_has_next_steps": 0.0,
        "advisor_email_has_context": 0.0,
        "advisor_email_lists_discrepancies": 0.0,
        "advisor_email_requests_confirmation": 0.0,
        "advisor_email_mentions_report": 0.0,
    }

    script_path = workspace / "tools" / "verify_requirements.py"
    if script_path.exists() and script_path.is_file():
        scores["verify_script_exists"] = 1.0

    exists, has_cmd, has_status = _check_run_log(workspace)
    if exists and has_cmd and has_status:
        scores["run_log_present_and_formatted"] = 1.0

    state_expected = _extract_state_expected(workspace)
    uni_expected = _extract_university_expected(workspace)
    student_data = _extract_student(workspace)

    report = _load_verification_report(workspace)
    if report is not None and _validate_structure(report):
        scores["verification_report_exists_and_well_formed"] = 1.0

        state_summary = report.get("state_summary", {})
        if isinstance(state_expected, dict) and _compare_summaries(state_summary, state_expected):
            scores["state_summary_matches_input"] = 1.0

        uni_summary = report.get("university_summary", {})
        if isinstance(uni_expected, dict) and _compare_summaries(uni_summary, uni_expected):
            scores["university_summary_matches_input"] = 1.0

        cons_list, disc_list = _extract_discrepancy_entries(report)
        coverage_ok = True
        if not _find_item_presence(disc_list, ["gpa"]):
            coverage_ok = False
        if not _find_item_presence(disc_list, ["student", "teaching"]) and not _find_item_presence(disc_list, ["teaching", "weeks"]):
            coverage_ok = False
        if not _find_item_presence(disc_list, ["background", "check"]):
            coverage_ok = False
        if not _find_item_presence(disc_list, ["exam"]):
            coverage_ok = False
        area_status_expected = {
            "Music Theory": "discrepancy",
            "Music History": "consistency",
            "Conducting": "discrepancy",
            "Instrumental Techniques": "consistency",
            "Vocal Pedagogy": "discrepancy",
            "Education Core": "discrepancy",
            "Special Education": "consistency",
            "ESL/ELL": "discrepancy",
        }
        for area, status in area_status_expected.items():
            if status == "consistency":
                if not _find_item_presence(cons_list, [area.lower()]):
                    coverage_ok = False
            else:
                if not _find_item_presence(disc_list, [area.lower()]):
                    coverage_ok = False
        if coverage_ok:
            scores["comparisons_cover_required_items"] = 1.0

        if isinstance(state_expected, dict) and isinstance(student_data, dict):
            ss_state = report.get("student_status_vs_state", {})
            gpa = _as_float(student_data.get("gpa"))
            min_gpa = _as_float(state_expected.get("min_gpa"))
            gpa_ok_expected = (gpa is not None and min_gpa is not None and gpa >= min_gpa)
            gpa_ok_actual = ss_state.get("gpa_ok")
            missing_expected = _compute_missing_coursework(state_expected.get("coursework", {}), student_data.get("completed_coursework", []))
            missing_actual = ss_state.get("missing_coursework", [])
            missing_exams_expected = _compute_missing_exams(state_expected.get("required_exams", []), student_data.get("exams", []))

            def norm_exam_names(lst):
                out = set()
                for it in lst or []:
                    if isinstance(it, str):
                        nm, code = _parse_exam_str(it)
                        out.add((_norm_str(nm), _norm_str(code or "")))
                    elif isinstance(it, dict):
                        out.add((_norm_str(it.get("name") or ""), _norm_str(it.get("code") or "")))
                    else:
                        out.add((_norm_str(str(it)), ""))
                return out

            missing_exams_actual = ss_state.get("missing_exams", [])
            gaps_expected = _compute_background_gaps(state_expected.get("background_check", []), student_data.get("background_check", {}))
            gaps_actual = ss_state.get("background_check_gaps", [])
            status_ok = True
            if gpa_ok_actual is not gpa_ok_expected:
                status_ok = False
            if not _status_matches(missing_expected, missing_actual):
                status_ok = False
            if norm_exam_names(missing_exams_expected) != norm_exam_names(missing_exams_actual):
                status_ok = False
            if _canon_str_set(gaps_expected) != _canon_str_set(gaps_actual):
                status_ok = False
            if status_ok:
                scores["student_status_vs_state_correct"] = 1.0

        if isinstance(uni_expected, dict) and isinstance(student_data, dict):
            ss_uni = report.get("student_status_vs_university", {})
            gpa = _as_float(student_data.get("gpa"))
            min_gpa = _as_float(uni_expected.get("min_gpa"))
            gpa_ok_expected = (gpa is not None and min_gpa is not None and gpa >= min_gpa)
            gpa_ok_actual = ss_uni.get("gpa_ok")
            missing_expected = _compute_missing_coursework(uni_expected.get("coursework", {}), student_data.get("completed_coursework", []))
            missing_actual = ss_uni.get("missing_coursework", [])
            missing_exams_expected = _compute_missing_exams(uni_expected.get("required_exams", []), student_data.get("exams", []))
            missing_exams_actual = ss_uni.get("missing_exams", [])
            gaps_expected = _compute_background_gaps(uni_expected.get("background_check", []), student_data.get("background_check", {}))
            gaps_actual = ss_uni.get("background_check_gaps", [])
            status_ok = True
            if gpa_ok_actual is not gpa_ok_expected:
                status_ok = False
            if not _status_matches(missing_expected, missing_actual):
                status_ok = False

            def norm_exam_names_u(lst):
                out = set()
                for it in lst or []:
                    if isinstance(it, str):
                        nm, code = _parse_exam_str(it)
                        out.add((_norm_str(nm), _norm_str(code or "")))
                    elif isinstance(it, dict):
                        out.add((_norm_str(it.get("name") or ""), _norm_str(it.get("code") or "")))
                    else:
                        out.add((_norm_str(str(it)), ""))
                return out

            if norm_exam_names_u(missing_exams_expected) != norm_exam_names_u(missing_exams_actual):
                status_ok = False
            if _canon_str_set(gaps_expected) != _canon_str_set(gaps_actual):
                status_ok = False
            if status_ok:
                scores["student_status_vs_university_correct"] = 1.0

    status_path = workspace / "output" / "status_update.md"
    status_txt = _read_text(status_path)
    if status_txt:
        txt = status_txt.lower()
        facts_ok = True
        facts_ok = facts_ok and ("3.0" in txt or "3,0" in txt)
        facts_ok = facts_ok and ("14" in txt and "week" in txt)
        facts_ok = facts_ok and ("fbi" in txt) and ("riverland state" in txt)
        facts_ok = facts_ok and ("praxis" in txt) and ("basic skills" in txt)
        if facts_ok:
            scores["status_update_covers_facts"] = 1.0

        disc_ok = True
        disc_ok = disc_ok and ("14" in txt and "16" in txt and "week" in txt)
        disc_ok = disc_ok and ("background" in txt and "fbi" in txt)
        any_course_disc = any(k in txt for k in ["esl/ell", "education core", "music theory", "vocal pedagogy", "conducting"])
        disc_ok = disc_ok and any_course_disc
        if disc_ok:
            scores["status_update_lists_discrepancies"] = 1.0

        ns_ok = ("next steps" in txt) or ("action" in txt) or ("plan" in txt)
        if ns_ok and (("praxis" in txt) or ("fbi" in txt) or ("conducting" in txt) or ("education core" in txt) or ("esl/ell" in txt)):
            scores["status_update_has_next_steps"] = 1.0

    email_path = workspace / "output" / "draft_email_to_advisor.txt"
    email_txt = _read_text(email_path)
    if email_txt:
        etxt = email_txt
        ltxt = etxt.lower()
        context_ok = ("music education" in ltxt) and (("k-12" in ltxt) or ("k–12" in etxt) or ("k—12" in etxt)) and ("cross" in ltxt or "checking" in ltxt or "verify" in ltxt)
        if context_ok:
            scores["advisor_email_has_context"] = 1.0

        bullets = [ln for ln in etxt.splitlines() if re.match(r"^\s*[-*\u2022]\s+", ln)]

        def bullet_contains(keywords: List[str]) -> bool:
            for b in bullets:
                bl = b.lower()
                if all(k.lower() in bl for k in keywords):
                    if ("state" in bl and "univer" in bl) or (" vs " in b.lower()) or (len(re.findall(r"\b\d+(\.\d+)?\b", bl)) >= 2):
                        return True
            return False

        disc_checks = [
            bullet_contains(["gpa"]),
            bullet_contains(["student", "teaching"]),
            bullet_contains(["background", "check"]),
            bullet_contains(["exam"]),
        ]
        coursework_areas = ["music theory", "music history", "conducting", "instrumental techniques", "vocal pedagogy", "education core", "special education", "esl/ell"]
        cw_count = sum(1 for area in coursework_areas if bullet_contains([area]))
        if all(disc_checks) and cw_count >= 2:
            scores["advisor_email_lists_discrepancies"] = 1.0

        req_ok = ("confirm" in ltxt or "confirmation" in ltxt) and ("graduation" in ltxt) and ("student teaching" in ltxt or "clearance" in ltxt) and ("piano" in ltxt)
        if req_ok:
            scores["advisor_email_requests_confirmation"] = 1.0

        if "output/verification_report.json" in etxt or "verification_report.json" in etxt:
            scores["advisor_email_mentions_report"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()