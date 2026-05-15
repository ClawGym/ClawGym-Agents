import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


ALLOWED_TECHNICAL_INPUTS = {
    "config/app.env",
    "k8s/deployment.yaml",
    "infra/s3.tf.txt",
    "source/api.py",
}

SEVERITY_ORDER = {"High": 3, "Medium": 2, "Low": 1}


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def load_json_file(path: Path) -> Optional[object]:
    txt = read_text_file(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def count_sentence_endings(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return len(re.findall(r"[.!?]", text))


def find_section(lines: List[str], title: str) -> Tuple[int, int]:
    def is_heading_line(line: str, t: str) -> bool:
        s = line.strip()
        s2 = s.lstrip("#").strip()
        s2_nocolon = s2[:-1].strip() if s2.endswith(":") else s2
        return s2_nocolon.lower() == t.lower()

    start = -1
    for idx, line in enumerate(lines):
        if is_heading_line(line, title):
            start = idx
            break
    if start == -1:
        return -1, -1

    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        s2 = s.lstrip("#").strip()
        s2_nocolon = s2[:-1].strip() if s2.endswith(":") else s2
        if s.startswith("#") or s2_nocolon.lower() in {"context", "action items"}:
            return start, j
    return start, len(lines)


def extract_checklist_lines(section_lines: List[str]) -> List[str]:
    checklist = []
    pattern = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+")
    for line in section_lines:
        if pattern.search(line):
            checklist.append(line.rstrip("\n"))
    return checklist


def get_action_items_section_lines(content: str) -> List[str]:
    lines = content.splitlines()
    start, end = find_section(lines, "Action Items")
    if start == -1:
        return []
    return lines[start + 1:end]


def get_context_section_present(content: str) -> bool:
    lines = content.splitlines()
    start, end = find_section(lines, "Context")
    if start == -1:
        return False
    return True if (end - start) >= 1 else False


def choose_top_three_issues(findings: List[dict]) -> List[str]:
    categorized: Dict[str, List[dict]] = {"High": [], "Medium": [], "Low": []}
    for f in findings:
        sev = f.get("severity")
        if sev in categorized:
            categorized[sev].append(f)
    top: List[str] = []
    for sev in ["High", "Medium", "Low"]:
        for f in categorized[sev]:
            issue = f.get("issue")
            if isinstance(issue, str) and issue and issue not in top:
                top.append(issue)
            if len(top) >= 3:
                return top[:3]
    return top[:3]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "security_report_exists_and_parseable": 0.0,
        "security_report_structure_valid": 0.0,
        "security_report_findings_fields_valid": 0.0,
        "security_report_file_coverage": 0.0,
        "security_report_evidence_matches": 0.0,
        "security_report_summary_counts_match": 0.0,
        "meeting_actions_sections_present": 0.0,
        "meeting_actions_cover_high_findings": 0.0,
        "meeting_actions_owner_roles_assigned_for_high": 0.0,
        "meeting_actions_references_valid_ids": 0.0,
        "stakeholder_update_word_count_and_tone": 0.0,
        "stakeholder_update_includes_top_three_risks": 0.0,
        "stakeholder_update_includes_next_steps_phrase": 0.0,
    }

    report_path = workspace / "output" / "security_risk_report.json"
    meeting_path = workspace / "output" / "meeting_actions.md"
    update_path = workspace / "output" / "stakeholder_update.txt"

    report_obj = load_json_file(report_path)
    if isinstance(report_obj, dict):
        scores["security_report_exists_and_parseable"] = 1.0
    else:
        report_obj = None

    findings = []
    summary = None
    structure_ok = False
    if report_obj is not None:
        findings = report_obj.get("findings")
        summary = report_obj.get("summary")
        if isinstance(findings, list) and isinstance(summary, dict):
            structure_ok = True
    scores["security_report_structure_valid"] = 1.0 if structure_ok else 0.0

    findings_fields_ok = False
    evidence_matches_ok = False
    file_coverage_ok = False
    summary_counts_ok = False

    if structure_ok:
        ids = set()
        fields_valid = True
        evidence_ok = True
        for f in findings:
            if not isinstance(f, dict):
                fields_valid = False
                break
            req_fields = ["id", "file_path", "location", "issue", "severity", "rationale", "evidence", "recommendation"]
            for k in req_fields:
                if k not in f:
                    fields_valid = False
                    break
            if not fields_valid:
                break
            if not (isinstance(f["id"], str) and f["id"].strip()):
                fields_valid = False
                break
            if f["id"] in ids:
                fields_valid = False
                break
            ids.add(f["id"])
            if not (isinstance(f["file_path"], str) and f["file_path"] in ALLOWED_TECHNICAL_INPUTS):
                fields_valid = False
                break
            if not (isinstance(f["location"], str) and f["location"].strip()):
                fields_valid = False
                break
            if not (isinstance(f["issue"], str) and f["issue"].strip()):
                fields_valid = False
                break
            if f.get("severity") not in SEVERITY_ORDER:
                fields_valid = False
                break
            rationale = f.get("rationale")
            if not (isinstance(rationale, str) and rationale.strip()):
                fields_valid = False
                break
            sentences = count_sentence_endings(rationale)
            if not (1 <= sentences <= 3):
                fields_valid = False
                break
            evidence = f.get("evidence")
            if not (isinstance(evidence, str) and evidence.strip()):
                fields_valid = False
                break
            recommendation = f.get("recommendation")
            if not (isinstance(recommendation, str) and recommendation.strip()):
                fields_valid = False
                break

        findings_fields_ok = fields_valid

        if fields_valid:
            for f in findings:
                file_path = f["file_path"]
                evidence = f["evidence"]
                referenced_file = workspace / file_path
                content = read_text_file(referenced_file)
                if content is None:
                    evidence_ok = False
                    break
                if evidence not in content:
                    norm_ev = re.sub(r"\s+", " ", evidence.strip())
                    norm_content = re.sub(r"\s+", " ", content)
                    if norm_ev not in norm_content:
                        evidence_ok = False
                        break
        evidence_matches_ok = evidence_ok

        file_paths_in_findings = {f["file_path"] for f in findings if isinstance(f, dict) and "file_path" in f}
        file_coverage_ok = ALLOWED_TECHNICAL_INPUTS.issubset(file_paths_in_findings)

        if isinstance(summary, dict):
            total_findings = summary.get("total_findings")
            by_sev = summary.get("by_severity")
            if isinstance(total_findings, int) and isinstance(by_sev, dict):
                keys_ok = all(k in by_sev and isinstance(by_sev[k], int) for k in ["High", "Medium", "Low"])
                if keys_ok and total_findings == len(findings):
                    counts = {"High": 0, "Medium": 0, "Low": 0}
                    for f in findings:
                        sev = f.get("severity")
                        if sev in counts:
                            counts[sev] += 1
                    if all(counts[k] == by_sev.get(k, -1) for k in counts.keys()):
                        summary_counts_ok = True

    scores["security_report_findings_fields_valid"] = 1.0 if findings_fields_ok else 0.0
    scores["security_report_file_coverage"] = 1.0 if file_coverage_ok else 0.0
    scores["security_report_evidence_matches"] = 1.0 if evidence_matches_ok else 0.0
    scores["security_report_summary_counts_match"] = 1.0 if summary_counts_ok else 0.0

    meeting_content = read_text_file(meeting_path)
    if meeting_content is not None:
        context_present = get_context_section_present(meeting_content)
        action_lines = get_action_items_section_lines(meeting_content)
        lines = meeting_content.splitlines()
        ai_start, _ = find_section(lines, "Action Items")
        action_present = ai_start != -1
        scores["meeting_actions_sections_present"] = 1.0 if (context_present and action_present) else 0.0
    else:
        action_lines = []
        scores["meeting_actions_sections_present"] = 0.0

    checklist_lines = extract_checklist_lines(action_lines) if action_lines else []

    if report_obj is not None and isinstance(findings, list) and meeting_content is not None:
        high_ids = [f["id"] for f in findings if isinstance(f, dict) and f.get("severity") == "High" and isinstance(f.get("id"), str)]
        if len(high_ids) == 0:
            scores["meeting_actions_cover_high_findings"] = 1.0
            scores["meeting_actions_owner_roles_assigned_for_high"] = 1.0
        else:
            cover_all = True
            owners_ok = True
            for hid in high_ids:
                lines_with_id = [ln for ln in checklist_lines if hid in ln]
                if not lines_with_id:
                    cover_all = False
                else:
                    owner_roles = ("App Team", "DevOps", "Security")
                    if not any(any(role in ln for role in owner_roles) for ln in lines_with_id):
                        owners_ok = False
            scores["meeting_actions_cover_high_findings"] = 1.0 if cover_all else 0.0
            scores["meeting_actions_owner_roles_assigned_for_high"] = 1.0 if owners_ok else 0.0

        if checklist_lines:
            json_ids = set(f["id"] for f in findings if isinstance(f, dict) and isinstance(f.get("id"), str))
            valid_ref_count = 0
            for ln in checklist_lines:
                if any(_id in ln for _id in json_ids):
                    valid_ref_count += 1
            scores["meeting_actions_references_valid_ids"] = 1.0 if valid_ref_count == len(checklist_lines) and len(checklist_lines) > 0 else 0.0
        else:
            scores["meeting_actions_references_valid_ids"] = 0.0
    else:
        scores["meeting_actions_cover_high_findings"] = 0.0
        scores["meeting_actions_owner_roles_assigned_for_high"] = 0.0
        scores["meeting_actions_references_valid_ids"] = 0.0

    update_text = read_text_file(update_path)
    if update_text is not None:
        words = re.findall(r"\b\w+\b", update_text)
        word_count_ok = len(words) <= 180 and len(words) > 0
        tone_ok = bool(re.search(r"\b(thank|appreciat)", update_text, flags=re.IGNORECASE))
        scores["stakeholder_update_word_count_and_tone"] = 1.0 if (word_count_ok and tone_ok) else 0.0

        if report_obj is not None and isinstance(findings, list) and len(findings) > 0:
            top_three = choose_top_three_issues(findings)
            present_all = True
            upd_lower = update_text.lower()
            for issue in top_three:
                if not isinstance(issue, str) or not issue.strip():
                    present_all = False
                    break
                if issue.lower() not in upd_lower:
                    present_all = False
                    break
            scores["stakeholder_update_includes_top_three_risks"] = 1.0 if (len(top_three) > 0 and present_all) else 0.0
        else:
            scores["stakeholder_update_includes_top_three_risks"] = 0.0

        if re.search(r"\bnext steps?\b", update_text, flags=re.IGNORECASE) or re.search(r"\bwe(?:'| )?ll\b|\bwe will\b", update_text, flags=re.IGNORECASE):
            scores["stakeholder_update_includes_next_steps_phrase"] = 1.0
        else:
            scores["stakeholder_update_includes_next_steps_phrase"] = 0.0
    else:
        scores["stakeholder_update_word_count_and_tone"] = 0.0
        scores["stakeholder_update_includes_top_three_risks"] = 0.0
        scores["stakeholder_update_includes_next_steps_phrase"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()