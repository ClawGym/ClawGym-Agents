import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Tuple[List[str], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return [], None


def _compute_time_score(due_date: str) -> int:
    # Due date thresholds compared lexicographically (YYYY-MM-DD)
    if due_date <= "2026-05-27":
        return 100
    elif due_date <= "2026-06-10":
        return 80
    elif due_date <= "2026-06-30":
        return 60
    else:
        return 30


def _severity_bonus(severity: str) -> int:
    mapping = {"High": 20, "Medium": 10, "Low": 0}
    return mapping.get(severity, 0)


def _compute_expected_priority(tasks_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Filter: status != "Done" and category in ["Residency", "Healthcare"]
    filtered = []
    for r in tasks_rows:
        status = (r.get("status") or "").strip()
        category = (r.get("category") or "").strip()
        if status == "Done":
            continue
        if category not in {"Residency", "Healthcare"}:
            continue
        # Compute urgency score
        due_date = (r.get("due_date") or "").strip()
        severity = (r.get("severity") or "").strip()
        time_score = _compute_time_score(due_date)
        bonus = _severity_bonus(severity)
        urgency_score = time_score + bonus
        # Build row with required columns
        expected_row = {
            "id": (r.get("id") or "").strip(),
            "category": category,
            "task_name": (r.get("task_name") or "").strip(),
            "due_date": due_date,
            "status": status,
            "severity": severity,
            "tags": (r.get("tags") or "").strip(),
            "urgency_score": str(urgency_score),
            # urgency_rank will be assigned after sorting
            "urgency_rank": "",  # placeholder
        }
        filtered.append(expected_row)
    # Sort by: urgency_score desc, then due_date asc, then id asc numeric
    def sort_key(row: Dict[str, str]) -> Tuple[int, str, int]:
        try:
            uid = int(row["id"])
        except Exception:
            uid = 10**9
        try:
            uscore = int(row["urgency_score"])
        except Exception:
            uscore = -10**9
        return (-uscore, row["due_date"], uid)

    filtered.sort(key=sort_key)
    # Assign ranks
    for idx, row in enumerate(filtered, start=1):
        row["urgency_rank"] = str(idx)
    return filtered


def _compare_csv_rows(actual_rows: List[Dict[str, str]], expected_rows: List[Dict[str, str]], required_cols: List[str]) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False
    for a, e in zip(actual_rows, expected_rows):
        for col in required_cols:
            av = (a.get(col) or "").strip()
            ev = (e.get(col) or "").strip()
            if av != ev:
                return False
    return True


def _parse_notice_es(text: str) -> Dict[str, Any]:
    # Extract appointment date/time
    appointment_date = None
    appointment_time = None
    m = re.search(r"reprogramada\s+al\s+(\d{4}-\d{2}-\d{2})\s+a\s+las\s+(\d{2}:\d{2})", text, flags=re.IGNORECASE)
    if m:
        appointment_date, appointment_time = m.group(1), m.group(2)
    # Extract location line
    loc = None
    mloc = re.search(r"^-+\s*Lugar:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    if mloc:
        loc_full = mloc.group(1).strip()
        loc_full = loc_full.rstrip(".")
        # Remove "Oficina de Extranjería, " prefix if present, keep street and city
        loc = re.sub(r"^\s*Oficina de Extranjería,\s*", "", loc_full, flags=re.IGNORECASE).strip()
    # Extract required documents
    docs: List[str] = []
    mdocs = re.search(r"^-+\s*Documentación\s+requerida:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    if mdocs:
        docs_str = mdocs.group(1).strip()
        docs_str = docs_str.rstrip(".")
        parts = [p.strip() for p in docs_str.split(",") if p.strip()]
        docs = parts
    # Extract deadline
    deadline = None
    mdead = re.search(r"^-+\s*Fecha\s+límite.*?:\s*(\d{4}-\d{2}-\d{2})", text, flags=re.IGNORECASE | re.MULTILINE)
    if mdead:
        deadline = mdead.group(1)
    return {
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "location_street_city": loc,
        "required_documents": docs,
        "deadline": deadline,
    }


def _find_section(text: str, heading: str) -> Optional[str]:
    # Find a section by heading, return text from that heading to before the next major heading
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if heading.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # Next heading is any line containing one of known headings (excluding the current found line)
    known = ["Translation summary", "Task counts", "Top 3 urgent tasks"]
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        for h in known:
            if h.lower() in lines[j].lower():
                end_idx = j
                break
        if end_idx != len(lines) and end_idx == j:
            break
    section = "\n".join(lines[start_idx:end_idx])
    return section


def _extract_field(section_text: str, field_name: str) -> Optional[str]:
    # Match lines like: field_name: value
    if not section_text:
        return None
    pattern = rf"{re.escape(field_name)}\s*:\s*(.+)"
    m = re.search(pattern, section_text, flags=re.IGNORECASE)
    if not m:
        return None
    value = m.group(1).strip()
    # Trim trailing Markdown artifacts
    value = value.strip().strip("*").strip()
    return value


def _parse_top3(section_text: str) -> List[Tuple[str, str, str]]:
    # Expect lines with "id, task_name, due_date"
    triples: List[Tuple[str, str, str]] = []
    if not section_text:
        return triples
    for line in section_text.splitlines():
        s = line.strip()
        if not s:
            continue
        # Remove leading bullets
        s = re.sub(r"^[\-\*\d\.\)\s]+", "", s)
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            id_part = parts[0]
            name_part = parts[1]
            date_part = parts[2]
            if re.fullmatch(r"\d+", id_part) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part):
                triples.append((id_part, name_part, date_part))
                if len(triples) == 3:
                    break
    return triples


def _check_docs_alignment(required_docs_line: str, notice_docs: List[str]) -> bool:
    # Accept either Spanish originals or clear English equivalents.
    # Split candidate list
    if required_docs_line is None:
        return False
    cand_items = [p.strip() for p in required_docs_line.split(",") if p.strip()]
    if len(cand_items) < len(notice_docs):
        return False

    def contains_all(subs: List[str], text: str) -> bool:
        return all(sub in text for sub in subs)

    lower_items = [it.lower() for it in cand_items]

    # Expected per-notice document matchers (list of alternative token sets)
    expected_patterns: List[List[List[str]]] = [
        # "pasaporte en vigor" -> expect "pasaporte" or "passport"
        [["pasaporte"], ["passport"]],
        # "certificado de empadronamiento (padrón)" -> expect certificado/certificate and empadron/padron/registration
        [["certificado", "empadron"], ["certificate", "empadron"], ["certificate", "padron"], ["certificate", "registration"]],
        # "certificado de empleo" -> certificado/certificate + empleo/employment
        [["certificado", "empleo"], ["certificate", "employment"]],
        # "2 fotografías tamaño carné" -> include '2' and photo/foto and size/passport
        [["2", "foto"], ["2", "photograph"], ["2", "photo"]],
    ]

    matched = [False] * len(expected_patterns)
    for idx, alts in enumerate(expected_patterns):
        found = False
        for li in lower_items:
            for tokens in alts:
                if contains_all(tokens, li):
                    found = True
                    break
            if found:
                break
        matched[idx] = found

    return all(matched)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "priority_csv_structure_correct": 0.0,
        "priority_csv_content_correct": 0.0,
        "translation_summary_appointment": 0.0,
        "translation_summary_location": 0.0,
        "translation_summary_required_documents_alignment": 0.0,
        "translation_summary_deadline": 0.0,
        "task_counts_correct": 0.0,
        "top3_matches_priority_csv": 0.0,
        "top3_matches_expected": 0.0,
        "narrative_summary_present": 0.0,
        "email_es_asunto_line": 0.0,
        "email_es_contains_details": 0.0,
        "email_es_references_documents": 0.0,
        "email_es_requests_earlier_or_confirmation": 0.0,
        "email_en_subject_line": 0.0,
        "email_en_mentions_due_date_for_id7": 0.0,
        "email_en_letterhead_spanish_certificate": 0.0,
    }

    # Load inputs
    tasks_path = workspace / "input" / "tasks.csv"
    notice_path = workspace / "input" / "notice_es.txt"

    tasks_header, tasks_rows = _safe_load_csv_dicts(tasks_path)
    notice_text = _safe_read_text(notice_path)
    notice_info = _parse_notice_es(notice_text) if notice_text else None

    # Deliverable 1: output/priority_residency_tasks.csv
    out_priority_path = workspace / "output" / "priority_residency_tasks.csv"
    priority_header, priority_rows = _safe_load_csv_dicts(out_priority_path)
    required_cols = ["id", "category", "task_name", "due_date", "status", "severity", "tags", "urgency_score", "urgency_rank"]
    if priority_rows is not None:
        # Structure check: exact header order
        if priority_header == required_cols:
            scores["priority_csv_structure_correct"] = 1.0
        else:
            scores["priority_csv_structure_correct"] = 0.0

        # Content check
        if tasks_rows is not None:
            expected_rows = _compute_expected_priority(tasks_rows)
            # Normalize actual rows to only required cols
            actual_rows = []
            for r in priority_rows:
                row = {k: (r.get(k) or "").strip() for k in required_cols}
                actual_rows.append(row)
            if _compare_csv_rows(actual_rows, expected_rows, required_cols):
                scores["priority_csv_content_correct"] = 1.0
            else:
                scores["priority_csv_content_correct"] = 0.0
        else:
            scores["priority_csv_content_correct"] = 0.0
    else:
        scores["priority_csv_structure_correct"] = 0.0
        scores["priority_csv_content_correct"] = 0.0

    # Deliverable 2: output/status_report.md
    status_report_path = workspace / "output" / "status_report.md"
    status_text = _safe_read_text(status_report_path) or ""

    # Translation summary section checks
    trans_section = _find_section(status_text, "Translation summary") or status_text  # fallback to whole text

    # Appointment date/time
    exp_app_date = notice_info.get("appointment_date") if notice_info else None
    exp_app_time = notice_info.get("appointment_time") if notice_info else None
    got_app_date = _extract_field(trans_section, "appointment_date")
    got_app_time = _extract_field(trans_section, "appointment_time")
    if exp_app_date and got_app_date == exp_app_date and exp_app_time and got_app_time == exp_app_time:
        scores["translation_summary_appointment"] = 1.0

    # Location (street and city)
    exp_loc = notice_info.get("location_street_city") if notice_info else None
    got_loc = _extract_field(trans_section, "location")
    if exp_loc and got_loc:
        # Accept exact match to "street, city"
        if got_loc.strip().rstrip(".") == exp_loc:
            scores["translation_summary_location"] = 1.0

    # Required documents alignment
    exp_docs = notice_info.get("required_documents") if notice_info else None
    got_docs_line = _extract_field(trans_section, "required_documents")
    if exp_docs is not None and got_docs_line is not None:
        if _check_docs_alignment(got_docs_line, exp_docs):
            scores["translation_summary_required_documents_alignment"] = 1.0

    # Deadline
    exp_deadline = notice_info.get("deadline") if notice_info else None
    got_deadline = _extract_field(trans_section, "deadline")
    if exp_deadline and got_deadline == exp_deadline:
        scores["translation_summary_deadline"] = 1.0

    # Task counts section
    task_counts_section = _find_section(status_text, "Task counts") or status_text
    if tasks_rows is not None and task_counts_section:
        # Compute expected counts
        res_p = sum(1 for r in tasks_rows if (r.get("category") or "").strip() == "Residency" and (r.get("status") or "").strip() != "Done")
        res_d = sum(1 for r in tasks_rows if (r.get("category") or "").strip() == "Residency" and (r.get("status") or "").strip() == "Done")
        hc_p = sum(1 for r in tasks_rows if (r.get("category") or "").strip() == "Healthcare" and (r.get("status") or "").strip() != "Done")
        hc_d = sum(1 for r in tasks_rows if (r.get("category") or "").strip() == "Healthcare" and (r.get("status") or "").strip() == "Done")

        def find_count(text: str, key: str) -> Optional[int]:
            m = re.search(rf"\b{re.escape(key)}\b\s*:\s*(\d+)", text, flags=re.IGNORECASE)
            return int(m.group(1)) if m else None

        rp = find_count(task_counts_section, "residency_pending")
        rd = find_count(task_counts_section, "residency_done")
        hcp = find_count(task_counts_section, "healthcare_pending")
        hcd = find_count(task_counts_section, "healthcare_done")

        if rp == res_p and rd == res_d and hcp == hc_p and hcd == hc_d:
            scores["task_counts_correct"] = 1.0

    # Top 3 urgent tasks section
    top3_section = _find_section(status_text, "Top 3 urgent tasks") or ""
    status_top3 = _parse_top3(top3_section)

    # Compare to priority CSV top 3
    if priority_rows is not None and len(status_top3) == 3:
        # Build top3 from priority file
        pr_top3: List[Tuple[str, str, str]] = []
        for r in priority_rows[:3]:
            pr_top3.append(((r.get("id") or "").strip(), (r.get("task_name") or "").strip(), (r.get("due_date") or "").strip()))
        if status_top3 == pr_top3:
            scores["top3_matches_priority_csv"] = 1.0

    # Compare to recomputed expected
    if tasks_rows is not None and len(status_top3) == 3:
        expected_rows = _compute_expected_priority(tasks_rows)
        exp_top3: List[Tuple[str, str, str]] = []
        for r in expected_rows[:3]:
            exp_top3.append((r["id"], r["task_name"], r["due_date"]))
        if status_top3 == exp_top3:
            scores["top3_matches_expected"] = 1.0

    # Narrative summary presence: British + residency + (Spain|Spanish)
    lower_report = status_text.lower()
    if ("british" in lower_report) and ("residency" in lower_report) and ("spain" in lower_report or "spanish" in lower_report):
        scores["narrative_summary_present"] = 1.0

    # Deliverable 3: Emails
    # Spanish email to Oficina de Extranjería
    es_email_path = workspace / "output" / "email_drafts" / "draft_es_oficina.txt"
    es_email_text = _safe_read_text(es_email_path) or ""
    es_lines = es_email_text.splitlines()
    if es_lines:
        if es_lines[0].strip().startswith("Asunto:"):
            scores["email_es_asunto_line"] = 1.0
    # Contains date, time, location, deadline
    if notice_info:
        need_date = notice_info.get("appointment_date") or ""
        need_time = notice_info.get("appointment_time") or ""
        need_deadline = notice_info.get("deadline") or ""
        loc_need = notice_info.get("location_street_city") or ""
        loc_tokens = [t.strip() for t in loc_need.split(",") if t.strip()]
        location_ok = all(tok.lower() in es_email_text.lower() for tok in loc_tokens)
        if (need_date in es_email_text) and (need_time in es_email_text) and (need_deadline in es_email_text) and location_ok:
            scores["email_es_contains_details"] = 1.0
    # References documents (at least two Spanish document terms)
    lower_es = es_email_text.lower()
    doc_tokens = ["pasaporte", "empadron", "empleo", "fotograf"]
    if sum(1 for t in doc_tokens if t in lower_es) >= 2:
        scores["email_es_references_documents"] = 1.0
    # Requests earlier appointment OR confirmation
    earlier_tokens = ["adelantar", "antes", "anticipar", "tempran", "adelanto"]
    has_earlier = ("cita" in lower_es) and any(t in lower_es for t in earlier_tokens)
    has_confirm = ("confirm" in lower_es) and ("cita" in lower_es or "reprogramad" in lower_es or "fecha" in lower_es)
    if has_earlier or has_confirm:
        scores["email_es_requests_earlier_or_confirmation"] = 1.0

    # English email to HR
    en_email_path = workspace / "output" / "email_drafts" / "draft_en_hr.txt"
    en_email_text = _safe_read_text(en_email_path) or ""
    en_lines = en_email_text.splitlines()
    if en_lines:
        if en_lines[0].strip().startswith("Subject:"):
            scores["email_en_subject_line"] = 1.0
    # Due date from task id=7
    id7_due: Optional[str] = None
    if tasks_rows is not None:
        for r in tasks_rows:
            if (r.get("id") or "").strip() == "7":
                id7_due = (r.get("due_date") or "").strip()
                break
    if id7_due and id7_due in en_email_text:
        scores["email_en_mentions_due_date_for_id7"] = 1.0
    # Letterhead + Spanish + certificado de empresa
    lower_en = en_email_text.lower()
    if ("letterhead" in lower_en) and ("spanish" in lower_en) and ("certificado de empresa" in lower_en):
        scores["email_en_letterhead_spanish_certificate"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()