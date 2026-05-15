import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None

def load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_file(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None

def parse_workflow(path: Path) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    content = read_text(path)
    steps = []
    step_map = {}
    if not content:
        return steps, step_map
    for line in content.splitlines():
        m = re.match(r'\s*\[(STEP-\d+)\]\s*(.+)$', line.strip())
        if m:
            step_id = m.group(1).strip()
            step_title = m.group(2).strip()
            steps.append({"step_id": step_id, "step_title": step_title})
            step_map[step_id] = step_title
    return steps, step_map

def tokenize_ids(value: str) -> List[str]:
    if value is None:
        return []
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]

def checklist_expected_header() -> List[str]:
    return [
        "requirement_category",
        "requirement_statement",
        "source_org",
        "source_title",
        "publication_year",
        "applies_to",
        "workflow_step_ids",
        "notes",
    ]

def parse_agenda_date(path: Path) -> Optional[datetime]:
    content = read_text(path)
    if not content:
        return None
    m = re.search(r'Meeting Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', content)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except Exception:
            return None
    return None

def detect_audio_only(text: str) -> bool:
    t = text.lower()
    patterns = [
        r'\baudio-only\b', r'\baudio only\b', r'\btelephone-only\b', r'\btelephonic\b',
        r'\bvoice-only\b', r'\bvoice only\b', r'\baudio fallback\b', r'\bfallback\b.*\baudio\b'
    ]
    return any(re.search(p, t) for p in patterns)

def detect_identity_verification(text: str) -> bool:
    t = text.lower()
    if "identity" in t and ("verify" in t or "verification" in t):
        return True
    if re.search(r'\bphoto id\b', t):
        return True
    return False

def detect_privacy(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["privacy", "hipaa", "security", "confidential", "phi", "data"])

def detect_documentation_billing(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["documentation", "billing", "coding", "modifier", "claim"])

def normalize_counts_map(d: Dict[str, int]) -> Dict[str, int]:
    return {k: int(v) for k, v in d.items()}

def extract_action_items_section(text: str) -> str:
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*#*\s*Action Items\s*$', line, flags=re.IGNORECASE):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    for j in range(start_idx, len(lines)):
        if re.match(r'^\s*#', lines[j]) and not re.match(r'^\s*#*\s*Action Items\s*$', lines[j], flags=re.IGNORECASE):
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx])

def extract_section_presence(text: str, section_name: str) -> bool:
    for line in text.splitlines():
        if re.match(r'^\s*#*\s*' + re.escape(section_name) + r'\s*$', line, flags=re.IGNORECASE):
            return True
    return False

def parse_date_strings_in_line(line: str) -> List[str]:
    results = set()
    for m in re.finditer(r'([0-9]{4})-([0-9]{2})-([0-9]{2})', line):
        try:
            d = datetime.strptime(m.group(0), "%Y-%m-%d")
            results.add(d.strftime("%Y-%m-%d"))
        except Exception:
            pass
    for m in re.finditer(r'\b([0-9]{2})/([0-9]{2})/([0-9]{4})\b', line):
        try:
            d = datetime.strptime(m.group(0), "%m/%d/%Y")
            results.add(d.strftime("%Y-%m-%d"))
        except Exception:
            pass
    for m in re.finditer(r'\b([0-9]{2})-([0-9]{2})-([0-9]{4})\b', line):
        try:
            d = datetime.strptime(m.group(0), "%m-%d-%Y")
            results.add(d.strftime("%Y-%m-%d"))
        except Exception:
            pass
    months = ("January","February","March","April","May","June","July","August","September","October","November","December")
    month_regex = r'(' + '|'.join(months) + r')\s+([0-9]{1,2}),\s*([0-9]{4})'
    for m in re.finditer(month_regex, line):
        try:
            d = datetime.strptime(m.group(0), "%B %d, %Y")
            results.add(d.strftime("%Y-%m-%d"))
        except Exception:
            pass
    return list(results)

def parse_attendees_roles(path: Path) -> Tuple[List[str], List[str]]:
    roles = []
    names = []
    content = read_text(path)
    if not content:
        return roles, names
    attendee_section = False
    for line in content.splitlines():
        if re.match(r'^\s*Attendees\s*$', line):
            attendee_section = True
            continue
        if attendee_section:
            if re.match(r'^\s*Agenda\s*$', line):
                break
            m = re.match(r'^\s*-\s*([^:]+):\s*(.+)$', line)
            if m:
                role = m.group(1).strip()
                name = m.group(2).strip()
                roles.append(role)
                names.append(name)
    return roles, names

def compute_step_counts_from_checklist(rows: List[Dict[str, str]], valid_step_ids: set) -> Dict[str, int]:
    counts = {sid: 0 for sid in valid_step_ids}
    for row in rows:
        ids = tokenize_ids(row.get("workflow_step_ids", ""))
        for sid in ids:
            if sid in counts:
                counts[sid] += 1
    return counts

def infer_constraints_from_checklist(rows: List[Dict[str, str]]) -> Dict[str, bool]:
    has_audio = False
    has_identity = False
    has_privacy_req = False
    has_doc_bill = False
    for row in rows:
        text = (row.get("requirement_category","") + " " + row.get("requirement_statement","")).strip()
        if detect_audio_only(text):
            has_audio = True
        if detect_identity_verification(text):
            has_identity = True
        if detect_privacy(text):
            has_privacy_req = True
        if detect_documentation_billing(text):
            has_doc_bill = True
    return {
        "has_audio_only_requirement": has_audio,
        "has_identity_verification_requirement": has_identity,
        "has_privacy_requirement": has_privacy_req,
        "has_documentation_billing_requirement": has_doc_bill,
    }

def compute_counts_by_key(rows: List[Dict[str, str]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        val = row.get(key, "")
        counts[val] = counts.get(val, 0) + 1
    return counts

def has_markdown_headings(text: str, min_headings: int = 4) -> bool:
    count = 0
    for line in text.splitlines():
        if re.match(r'^\s*#{1,6}\s+\S', line):
            count += 1
    return count >= min_headings

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "search_queries_minimum": 0.0,
        "checklist_columns_and_parseable": 0.0,
        "checklist_min_requirements": 0.0,
        "checklist_applies_to_values_valid": 0.0,
        "checklist_publication_years_valid": 0.0,
        "checklist_two_orgs_min_requirements": 0.0,
        "checklist_contains_audio_only_requirement": 0.0,
        "checklist_contains_identity_verification_requirement": 0.0,
        "checklist_contains_privacy_requirement": 0.0,
        "checklist_contains_documentation_billing_requirement": 0.0,
        "checklist_workflow_ids_valid": 0.0,
        "coverage_report_structure_valid": 0.0,
        "coverage_steps_counts_match_checklist": 0.0,
        "coverage_steps_uncovered_correct": 0.0,
        "coverage_counts_by_category_correct": 0.0,
        "coverage_source_org_counts_correct": 0.0,
        "coverage_constraints_alignment_with_checklist": 0.0,
        "coverage_constraints_all_true": 0.0,
        "consent_form_rewrite_placeholders_preserved": 0.0,
        "consent_form_rewrite_contains_audio_only_clause": 0.0,
        "consent_form_rewrite_contains_identity_verification": 0.0,
        "consent_form_rewrite_contains_privacy_disclosure": 0.0,
        "consent_form_rewrite_has_headings": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_min_five_action_items": 0.0,
        "meeting_notes_due_dates_requirements": 0.0,
        "meeting_notes_assignments_to_roles": 0.0,
    }

    teleworkflow_path = workspace / "input" / "telemedicine_workflow.md"
    consent_draft_path = workspace / "input" / "draft_consent_form.md"
    agenda_path = workspace / "input" / "agenda.md"
    output_dir = workspace / "output"
    search_queries_path = output_dir / "search_queries.txt"
    checklist_path = output_dir / "compliance_checklist.csv"
    coverage_report_path = output_dir / "coverage_report.json"
    consent_rewrite_path = output_dir / "consent_form_rewrite.md"
    meeting_notes_path = output_dir / "meeting_notes.md"

    steps_list, step_title_map = parse_workflow(teleworkflow_path)
    valid_step_ids = set(step_title_map.keys())

    search_text = read_text(search_queries_path)
    if search_text is not None:
        lines = [ln for ln in (l.strip() for l in search_text.splitlines()) if ln]
        if len(lines) >= 3:
            scores["search_queries_minimum"] = 1.0

    header, rows = read_csv_file(checklist_path)
    checklist_ok = False
    if header is not None and rows is not None:
        if header == checklist_expected_header():
            checklist_ok = True
            scores["checklist_columns_and_parseable"] = 1.0

    if checklist_ok:
        if len(rows) >= 8:
            scores["checklist_min_requirements"] = 1.0

        valid_applies = {"video", "audio", "both"}
        applies_valid = all((row.get("applies_to","") in valid_applies) for row in rows)
        if applies_valid:
            scores["checklist_applies_to_values_valid"] = 1.0

        years_ok = True
        for row in rows:
            y = row.get("publication_year","").strip()
            if not re.match(r'^\d{4}$', y):
                years_ok = False
                break
            year_i = int(y)
            if not (1990 <= year_i <= 2030):
                years_ok = False
                break
        if years_ok:
            scores["checklist_publication_years_valid"] = 1.0

        org_counts = compute_counts_by_key(rows, "source_org")
        orgs_with_two = [org for org, cnt in org_counts.items() if cnt >= 2]
        if len(orgs_with_two) >= 2:
            scores["checklist_two_orgs_min_requirements"] = 1.0

        has_audio = any(detect_audio_only((r.get("requirement_category","") + " " + r.get("requirement_statement",""))) for r in rows)
        if has_audio:
            scores["checklist_contains_audio_only_requirement"] = 1.0

        has_identity = any(detect_identity_verification((r.get("requirement_category","") + " " + r.get("requirement_statement",""))) for r in rows)
        if has_identity:
            scores["checklist_contains_identity_verification_requirement"] = 1.0

        has_priv = any(detect_privacy((r.get("requirement_category","") + " " + r.get("requirement_statement",""))) for r in rows)
        if has_priv:
            scores["checklist_contains_privacy_requirement"] = 1.0

        has_docbill = any(detect_documentation_billing((r.get("requirement_category","") + " " + r.get("requirement_statement",""))) for r in rows)
        if has_docbill:
            scores["checklist_contains_documentation_billing_requirement"] = 1.0

        workflow_ids_ok = True
        if not valid_step_ids:
            workflow_ids_ok = False
        else:
            for row in rows:
                ids = tokenize_ids(row.get("workflow_step_ids", ""))
                if not ids:
                    workflow_ids_ok = False
                    break
                for sid in ids:
                    if sid not in valid_step_ids:
                        workflow_ids_ok = False
                        break
                if not workflow_ids_ok:
                    break
        if workflow_ids_ok:
            scores["checklist_workflow_ids_valid"] = 1.0

    coverage = load_json(coverage_report_path)
    if coverage is not None and isinstance(coverage, dict):
        required_keys = ["steps", "steps_uncovered", "counts_by_category", "source_org_counts", "constraints_check", "assumptions"]
        structure_ok = all(k in coverage for k in required_keys)
        types_ok = (
            isinstance(coverage.get("steps"), list) and
            isinstance(coverage.get("steps_uncovered"), list) and
            isinstance(coverage.get("counts_by_category"), dict) and
            isinstance(coverage.get("source_org_counts"), dict) and
            isinstance(coverage.get("constraints_check"), dict) and
            isinstance(coverage.get("assumptions"), str)
        )
        if structure_ok and types_ok:
            scores["coverage_report_structure_valid"] = 1.0

        if checklist_ok and valid_step_ids and isinstance(coverage.get("steps"), list):
            computed_counts = compute_step_counts_from_checklist(rows, valid_step_ids)
            steps_ok = True
            coverage_steps = {}
            for item in coverage["steps"]:
                if not isinstance(item, dict):
                    steps_ok = False
                    break
                sid = item.get("step_id")
                title = item.get("step_title")
                cnt = item.get("matched_requirements_count")
                if sid is None or title is None or cnt is None:
                    steps_ok = False
                    break
                coverage_steps[sid] = {"title": title, "count": cnt}
            if steps_ok:
                for sid, title in step_title_map.items():
                    if sid not in coverage_steps:
                        steps_ok = False
                        break
                    if coverage_steps[sid]["title"] != title:
                        steps_ok = False
                        break
                    if int(coverage_steps[sid]["count"]) != int(computed_counts.get(sid, 0)):
                        steps_ok = False
                        break
            if steps_ok:
                scores["coverage_steps_counts_match_checklist"] = 1.0

            if "steps_uncovered" in coverage and isinstance(coverage["steps_uncovered"], list):
                expected_uncovered = sorted([sid for sid, cnt in computed_counts.items() if cnt == 0])
                actual_uncovered = sorted([sid for sid in coverage["steps_uncovered"] if isinstance(sid, str)])
                if expected_uncovered == actual_uncovered:
                    scores["coverage_steps_uncovered_correct"] = 1.0

            computed_cat_counts = compute_counts_by_key(rows, "requirement_category")
            if isinstance(coverage.get("counts_by_category"), dict):
                cov_cat = {str(k): int(v) for k, v in coverage["counts_by_category"].items()}
                if normalize_counts_map(computed_cat_counts) == cov_cat:
                    scores["coverage_counts_by_category_correct"] = 1.0

            computed_org_counts = compute_counts_by_key(rows, "source_org")
            if isinstance(coverage.get("source_org_counts"), dict):
                cov_org = {str(k): int(v) for k, v in coverage["source_org_counts"].items()}
                if normalize_counts_map(computed_org_counts) == cov_org:
                    scores["coverage_source_org_counts_correct"] = 1.0

            inferred_constraints = infer_constraints_from_checklist(rows)
            cov_constraints = coverage.get("constraints_check", {})
            align_ok = (
                isinstance(cov_constraints, dict) and
                all(k in cov_constraints for k in [
                    "has_audio_only_requirement",
                    "has_identity_verification_requirement",
                    "has_privacy_requirement",
                    "has_documentation_billing_requirement",
                ])
            )
            if align_ok:
                alignment = True
                for k, v in inferred_constraints.items():
                    if bool(cov_constraints.get(k)) != bool(v):
                        alignment = False
                        break
                if alignment:
                    scores["coverage_constraints_alignment_with_checklist"] = 1.0
                if all(inferred_constraints.values()):
                    scores["coverage_constraints_all_true"] = 1.0

    consent_text = read_text(consent_rewrite_path)
    if consent_text is not None:
        placeholders = ["[PATIENT_NAME]", "[DATE]", "[CLINIC_NAME]", "[DOB]", "[PROVIDER_NAME]", "[STATE]", "[CONTACT_PHONE]", "[CONTACT_EMAIL]"]
        if all(ph in consent_text for ph in placeholders):
            scores["consent_form_rewrite_placeholders_preserved"] = 1.0
        if detect_audio_only(consent_text):
            scores["consent_form_rewrite_contains_audio_only_clause"] = 1.0
        if detect_identity_verification(consent_text):
            scores["consent_form_rewrite_contains_identity_verification"] = 1.0
        if detect_privacy(consent_text):
            scores["consent_form_rewrite_contains_privacy_disclosure"] = 1.0
        if has_markdown_headings(consent_text, min_headings=4):
            scores["consent_form_rewrite_has_headings"] = 1.0

    meeting_text = read_text(meeting_notes_path)
    if meeting_text is not None:
        sections_required = ["Attendees", "Summary", "Decisions", "Action Items", "Open Questions"]
        if all(extract_section_presence(meeting_text, s) for s in sections_required):
            scores["meeting_notes_sections_present"] = 1.0

        action_section = extract_action_items_section(meeting_text)
        action_lines = []
        for line in action_section.splitlines():
            if re.match(r'^\s*[-*]\s+.+', line) or re.match(r'^\s*\d+\.\s+.+', line):
                action_lines.append(line.strip())
        if len(action_lines) >= 5:
            scores["meeting_notes_min_five_action_items"] = 1.0

        meeting_date = parse_agenda_date(agenda_path)
        if meeting_date:
            due_7 = (meeting_date + timedelta(days=7)).strftime("%Y-%m-%d")
            due_14 = (meeting_date + timedelta(days=14)).strftime("%Y-%m-%d")
            count_due_7 = 0
            count_due_14 = 0
            for line in action_lines:
                dates_in_line = parse_date_strings_in_line(line)
                if due_7 in dates_in_line:
                    count_due_7 += 1
                if due_14 in dates_in_line:
                    count_due_14 += 1
            if count_due_7 >= 2 and count_due_14 >= 2:
                scores["meeting_notes_due_dates_requirements"] = 1.0

        roles, names = parse_attendees_roles(agenda_path)
        if action_lines:
            assigned_count = 0
            for line in action_lines:
                if any(role in line for role in roles) or any(name in line for name in names):
                    assigned_count += 1
            if assigned_count >= 5:
                scores["meeting_notes_assignments_to_roles"] = 1.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()