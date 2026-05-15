import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _load_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
            return rows, headers, None
    except Exception as e:
        return None, None, str(e)


def _parse_simple_yaml(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        data: Dict[str, Any] = {}
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            striped = line.strip()
            if not striped or striped.startswith("#"):
                continue
            if ":" not in striped:
                continue
            key, val = striped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
                val = val[1:-1]
            data[key] = val
        return data, None
    except Exception as e:
        return None, str(e)


def _floats_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _to_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _extract_notes_struct(notes_text: str) -> Dict[str, Any]:
    attendance: List[str] = []
    lines = notes_text.splitlines()
    in_attendance = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*Attendance\s*:\s*$", line):
            in_attendance = True
            continue
        if in_attendance:
            if line.strip().startswith("- "):
                item = line.strip()[2:].strip()
                if item:
                    attendance.append(item)
            elif line.strip() == "" or re.match(r"^\s*\w", line):
                if not line.strip().startswith("- "):
                    in_attendance = False

    decisions: List[str] = []
    for m in re.finditer(r"(?m)^\s*(?:[-*]\s*)?Decision:\s*(.+)$", notes_text):
        decisions.append(m.group(1).strip())

    risks: List[str] = []
    issues: List[str] = []
    for m in re.finditer(r"(?m)^\s*(?:[-*]\s*)?Risk:\s*(.+)$", notes_text):
        risks.append(m.group(1).strip())
    for m in re.finditer(r"(?m)^\s*(?:[-*]\s*)?Issue:\s*(.+)$", notes_text):
        issues.append(m.group(1).strip())

    actions: List[Dict[str, str]] = []
    action_pattern = re.compile(
        r"(?m)^\s*-\s*Action:\s*\[(?P<id>[^\]]+)\]\s*Owner:\s*(?P<owner>[^,]+),\s*Due:\s*(?P<due>\d{4}-\d{2}-\d{2})\s*[—-]\s*(?P<desc>.+)$"
    )
    for m in action_pattern.finditer(notes_text):
        action = {
            "id": m.group("id").strip(),
            "owner": m.group("owner").strip(),
            "due_date": m.group("due").strip(),
            "description": m.group("desc").strip(),
        }
        actions.append(action)

    return {
        "attendance": attendance,
        "decisions": decisions,
        "risks": risks,
        "issues": issues,
        "actions": actions,
    }


def _compute_expected_variance(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for r in rows:
        date = r.get("date", "").strip()
        wp = r.get("work_package", "").strip()
        p = _to_float_safe(str(r.get("planned_pct", "")).strip())
        a = _to_float_safe(str(r.get("actual_pct", "")).strip())
        if p is None or a is None:
            continue
        delta = a - p
        if _floats_equal(a, p):
            status = "On Track"
        elif a < p:
            status = "Behind"
        else:
            status = "Ahead"
        result.append(
            {
                "date": date,
                "work_package": wp,
                "planned_pct": p,
                "actual_pct": a,
                "delta_pct": delta,
                "status": status,
            }
        )
    return result


def _normalize_number_str_for_regex(value: float, require_sign: Optional[str] = None) -> re.Pattern:
    abs_val = abs(value)
    int_part = int(round(abs_val))
    if _floats_equal(abs_val, float(int_part)):
        num_core = rf"{int_part}(?:\.0+)?"
    else:
        s = f"{abs_val:.4f}".rstrip("0").rstrip(".")
        num_core = re.escape(s)
    if require_sign == "-":
        sign = r"-"
    elif require_sign == "+":
        sign = r"\+"
    else:
        sign = r"-?\+?"
    pattern = rf"(?<![\d\.]){sign}{num_core}\s*%?(?![\d\.])"
    return re.compile(pattern)


def _find_window(text: str, center_idx: int, radius: int = 300) -> str:
    start = max(0, center_idx - radius)
    end = min(len(text), center_idx + radius)
    return text[start:end]


def _contains_all_emails(to_line: str, emails: List[str]) -> bool:
    tl = to_line.strip()
    if not tl.lower().startswith("to:"):
        return False
    body = tl.split(":", 1)[1]
    found_all = True
    for e in emails:
        if e not in body:
            found_all = False
            break
    return found_all


def _extract_to_and_subject_lines(content: str) -> Tuple[Optional[str], Optional[str]]:
    to_line = None
    subject_line = None
    for line in content.splitlines():
        if to_line is None and line.strip().lower().startswith("to:"):
            to_line = line.strip()
        if subject_line is None and line.strip().lower().startswith("subject:"):
            subject_line = line.strip()
        if to_line and subject_line:
            break
    return to_line, subject_line


def _subject_matches(subject_line: str, project_name: str, meeting_date: str) -> bool:
    if not subject_line.lower().startswith("subject:"):
        return False
    subj = subject_line.split(":", 1)[1].strip()
    expected_en = f"{project_name} — Action items from {meeting_date}"
    expected_hy = f"{project_name} - Action items from {meeting_date}"
    return subj == expected_en or subj == expected_hy


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "progress_variance_columns": 0.0,
        "progress_variance_values": 0.0,
        "run_command_references": 0.0,
        "summary_header_fields_present": 0.0,
        "summary_attendance_included": 0.0,
        "summary_decisions_included": 0.0,
        "summary_risks_issues_included": 0.0,
        "summary_progress_consistency": 0.0,
        "summary_action_items_included": 0.0,
        "action_items_csv_columns": 0.0,
        "action_items_csv_values_match": 0.0,
        "emails_exist_for_subcontractors": 0.0,
        "emails_to_line_correct": 0.0,
        "emails_subject_correct": 0.0,
        "emails_body_contains_actions_and_prompt": 0.0,
    }

    input_notes_path = workspace / "input" / "weekly_meeting_2026-04-15.md"
    input_progress_path = workspace / "input" / "progress_plan_actual.csv"
    input_contacts_path = workspace / "input" / "contacts.json"
    input_project_info_path = workspace / "input" / "project_info.yaml"

    out_variance_path = workspace / "output" / "progress_variance.csv"
    out_run_cmds_path = workspace / "output" / "run_commands.txt"
    out_summary_path = workspace / "output" / "weekly_site_meeting_summary.md"
    out_actions_csv_path = workspace / "output" / "action_items.csv"
    out_emails_dir = workspace / "output" / "emails"

    notes_text, _ = _read_text_safe(input_notes_path)
    progress_rows, out_progress_headers, _ = _load_csv_dicts_safe(input_progress_path)
    contacts, _ = _load_json_safe(input_contacts_path)
    project_info, _ = _parse_simple_yaml(input_project_info_path)

    expected_variance: List[Dict[str, Any]] = []
    if progress_rows is not None:
        expected_variance = _compute_expected_variance(progress_rows)

    out_rows, out_headers, _ = _load_csv_dicts_safe(out_variance_path)
    expected_headers = ["date", "work_package", "planned_pct", "actual_pct", "delta_pct", "status"]
    if out_headers is not None and out_headers == expected_headers:
        scores["progress_variance_columns"] = 1.0
    else:
        scores["progress_variance_columns"] = 0.0

    if out_rows is None or expected_variance is None or len(expected_variance) == 0:
        scores["progress_variance_values"] = 0.0
    else:
        out_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in out_rows:
            key = (str(r.get("date", "")).strip(), str(r.get("work_package", "")).strip())
            p = _to_float_safe(str(r.get("planned_pct", "")).strip())
            a = _to_float_safe(str(r.get("actual_pct", "")).strip())
            d = _to_float_safe(str(r.get("delta_pct", "")).strip())
            out_map[key] = {
                "planned_pct": p,
                "actual_pct": a,
                "delta_pct": d,
                "status": str(r.get("status", "")).strip(),
            }
        total = len(expected_variance)
        correct = 0
        for ev in expected_variance:
            key = (ev["date"], ev["work_package"])
            if key not in out_map:
                continue
            ov = out_map[key]
            if ov["planned_pct"] is None or ov["actual_pct"] is None or ov["delta_pct"] is None:
                continue
            cond = (
                _floats_equal(ov["planned_pct"], float(ev["planned_pct"]))
                and _floats_equal(ov["actual_pct"], float(ev["actual_pct"]))
                and _floats_equal(ov["delta_pct"], float(ev["delta_pct"]))
                and ov["status"] == ev["status"]
            )
            if cond:
                correct += 1
        scores["progress_variance_values"] = correct / total if total > 0 else 0.0

    run_text, _ = _read_text_safe(out_run_cmds_path)
    if run_text is None:
        scores["run_command_references"] = 0.0
    else:
        lines = [ln for ln in [ln.strip() for ln in run_text.splitlines()] if ln]
        if len(lines) >= 1 and ("input/progress_plan_actual.csv" in lines[0] and "output/progress_variance.csv" in lines[0]):
            scores["run_command_references"] = 1.0
        else:
            scores["run_command_references"] = 0.0

    notes_struct = {"attendance": [], "decisions": [], "risks": [], "issues": [], "actions": []}
    if notes_text is not None:
        notes_struct = _extract_notes_struct(notes_text)

    summary_text, _ = _read_text_safe(out_summary_path)
    if summary_text is None or project_info is None:
        scores["summary_header_fields_present"] = 0.0
    else:
        proj_name = str(project_info.get("project_name", "")).strip()
        meeting_date = str(project_info.get("meeting_date", "")).strip()
        got_proj = proj_name in summary_text
        got_date = meeting_date in summary_text
        count = 0
        if got_proj:
            count += 0.5
        if got_date:
            count += 0.5
        scores["summary_header_fields_present"] = count

    if summary_text is None or notes_text is None:
        scores["summary_attendance_included"] = 0.0
    else:
        attendance = notes_struct.get("attendance", [])
        if not attendance:
            scores["summary_attendance_included"] = 0.0
        else:
            total = len(attendance)
            covered = 0
            for name in attendance:
                if name in summary_text:
                    covered += 1
            scores["summary_attendance_included"] = covered / total if total > 0 else 0.0

    if summary_text is None or notes_text is None:
        scores["summary_decisions_included"] = 0.0
    else:
        decisions = notes_struct.get("decisions", [])
        if not decisions:
            scores["summary_decisions_included"] = 0.0
        else:
            total = len(decisions)
            covered = 0
            for dec in decisions:
                if dec in summary_text:
                    covered += 1
            scores["summary_decisions_included"] = covered / total if total > 0 else 0.0

    if summary_text is None or notes_text is None:
        scores["summary_risks_issues_included"] = 0.0
    else:
        risks = notes_struct.get("risks", [])
        issues = notes_struct.get("issues", [])
        all_items = risks + issues
        if not all_items:
            scores["summary_risks_issues_included"] = 0.0
        else:
            total = len(all_items)
            covered = 0
            for item in all_items:
                if item in summary_text:
                    covered += 1
            scores["summary_risks_issues_included"] = covered / total if total > 0 else 0.0

    if summary_text is None or out_rows is None or out_headers is None or out_headers != expected_headers:
        scores["summary_progress_consistency"] = 0.0
    else:
        total = len(out_rows)
        matched = 0
        for r in out_rows:
            wp = str(r.get("work_package", "")).strip()
            p = _to_float_safe(str(r.get("planned_pct", "")).strip())
            a = _to_float_safe(str(r.get("actual_pct", "")).strip())
            d = _to_float_safe(str(r.get("delta_pct", "")).strip())
            status = str(r.get("status", "")).strip()
            if None in (p, a, d) or not wp:
                continue
            idx = summary_text.find(wp)
            if idx < 0:
                continue
            window = _find_window(summary_text, idx, radius=400)
            p_pat = _normalize_number_str_for_regex(p)
            a_pat = _normalize_number_str_for_regex(a)
            if _floats_equal(d, 0.0):
                d_pat = _normalize_number_str_for_regex(d, require_sign=None)
            elif d < 0:
                d_pat = _normalize_number_str_for_regex(d, require_sign="-")
            else:
                d_pat = _normalize_number_str_for_regex(d, require_sign=None)
            if p_pat.search(window) and a_pat.search(window) and d_pat.search(window) and status in window:
                matched += 1
        scores["summary_progress_consistency"] = matched / total if total > 0 else 0.0

    actions_csv_rows, actions_csv_headers, _ = _load_csv_dicts_safe(out_actions_csv_path)
    expected_ai_headers = ["id", "owner", "due_date", "description"]
    if actions_csv_headers is not None and actions_csv_headers == expected_ai_headers:
        scores["action_items_csv_columns"] = 1.0
    else:
        scores["action_items_csv_columns"] = 0.0

    if actions_csv_rows is None or notes_text is None:
        scores["action_items_csv_values_match"] = 0.0
    else:
        expected_actions = notes_struct.get("actions", [])
        if not expected_actions:
            scores["action_items_csv_values_match"] = 0.0
        else:
            def norm_row(r: Dict[str, str]) -> Tuple[str, str, str, str]:
                return (
                    str(r.get("id", "")).strip(),
                    str(r.get("owner", "")).strip(),
                    str(r.get("due_date", "")).strip(),
                    str(r.get("description", "")).strip(),
                )
            expected_set = {(a["id"], a["owner"], a["due_date"], a["description"]) for a in expected_actions}
            produced_set = {norm_row(r) for r in actions_csv_rows}
            total = len(expected_set)
            matched = sum(1 for e in expected_set if e in produced_set)
            scores["action_items_csv_values_match"] = matched / total if total > 0 else 0.0

    if summary_text is None or notes_text is None:
        scores["summary_action_items_included"] = 0.0
    else:
        expected_actions = notes_struct.get("actions", [])
        if not expected_actions:
            scores["summary_action_items_included"] = 0.0
        else:
            total = len(expected_actions)
            covered = 0
            for a in expected_actions:
                id_plain = a["id"]
                id_alternatives = [id_plain, f"[{id_plain}]"]
                has_id = any(alt in summary_text for alt in id_alternatives)
                has_owner = a["owner"] in summary_text
                has_due = a["due_date"] in summary_text
                words = a["description"].split()
                snippet = " ".join(words[:8]) if words else a["description"]
                has_desc = snippet in summary_text or a["description"] in summary_text
                if has_id and has_owner and has_due and has_desc:
                    covered += 1
            scores["summary_action_items_included"] = covered / total if total > 0 else 0.0

    companies_with_actions: List[str] = []
    if contacts is not None and isinstance(contacts, dict) and notes_text is not None:
        actions = notes_struct.get("actions", [])
        owner_counts: Dict[str, int] = {}
        for a in actions:
            owner = a["owner"]
            owner_counts[owner] = owner_counts.get(owner, 0) + 1
        for company in contacts.keys():
            if owner_counts.get(company, 0) > 0:
                companies_with_actions.append(company)

    if not companies_with_actions:
        scores["emails_exist_for_subcontractors"] = 0.0
        scores["emails_to_line_correct"] = 0.0
        scores["emails_subject_correct"] = 0.0
        scores["emails_body_contains_actions_and_prompt"] = 0.0
    else:
        exist_total = len(companies_with_actions)
        exist_count = 0
        to_total = 0
        to_count = 0
        subj_total = 0
        subj_count = 0
        body_total = 0
        body_count = 0

        proj_name = str(project_info.get("project_name", "")).strip() if project_info else ""
        meeting_date = str(project_info.get("meeting_date", "")).strip() if project_info else ""

        for company in companies_with_actions:
            emails_list = contacts.get(company, []) if isinstance(contacts, dict) else []
            filename = f"email_{company.replace(' ', '_')}.txt"
            email_path = out_emails_dir / filename
            email_text, _ = _read_text_safe(email_path)
            if email_text is not None:
                exist_count += 1
            if email_text is not None and isinstance(emails_list, list) and emails_list:
                to_total += 1
                to_line, subject_line = _extract_to_and_subject_lines(email_text)
                if to_line is not None and _contains_all_emails(to_line, emails_list):
                    to_count += 1
            if email_text is not None:
                subj_total += 1
                _, subject_line = _extract_to_and_subject_lines(email_text)
                if subject_line is not None and _subject_matches(subject_line, proj_name, meeting_date):
                    subj_count += 1
            if email_text is not None and notes_text is not None:
                body_total += 1
                has_proj = proj_name in email_text if proj_name else False
                has_date = meeting_date in email_text if meeting_date else False
                company_actions = [a for a in notes_struct.get("actions", []) if a["owner"] == company]
                actions_ok = True
                for a in company_actions:
                    id_plain = a["id"]
                    id_ok = (id_plain in email_text) or (f"[{id_plain}]" in email_text)
                    due_ok = a["due_date"] in email_text
                    desc_words = a["description"].split()
                    desc_snippet = " ".join(desc_words[:10]) if desc_words else a["description"]
                    desc_ok = (desc_snippet in email_text) or (a["description"] in email_text)
                    if not (id_ok and due_ok and desc_ok):
                        actions_ok = False
                        break
                confirm_ok = bool(re.search(r"\bconfirm", email_text, flags=re.IGNORECASE))
                if has_proj and has_date and actions_ok and confirm_ok:
                    body_count += 1

        scores["emails_exist_for_subcontractors"] = exist_count / exist_total if exist_total > 0 else 0.0
        scores["emails_to_line_correct"] = to_count / to_total if to_total > 0 else 0.0
        scores["emails_subject_correct"] = subj_count / subj_total if subj_total > 0 else 0.0
        scores["emails_body_contains_actions_and_prompt"] = body_count / body_total if body_total > 0 else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()