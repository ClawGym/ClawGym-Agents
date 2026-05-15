import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VALIDATION_COMMAND = "python3 scripts/validate.py --input data/exhibits.json --schema pipeline/config.json --out out/validation-report.json"


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def validate_record_against_cfg(rec: dict, cfg: dict) -> Tuple[str, List[Dict[str, str]]]:
    issues: List[Dict[str, str]] = []

    def add_issue(field: str, code: str, msg: str) -> None:
        issues.append({
            "field": field,
            "code": code,
            "message": msg
        })

    # Required fields
    for field in cfg.get("required_fields", []):
        if field not in rec:
            add_issue(field, "MISSING_FIELD", f"Missing required field {field}")

    # Title checks
    if "title" in rec:
        if not isinstance(rec["title"], str) or not rec["title"].strip():
            add_issue("title", "EMPTY_TITLE", "Title must be a non-empty string")

    # Date format
    if "date" in rec:
        date_regex = cfg.get("date_regex")
        if date_regex:
            try:
                if not re.match(date_regex, str(rec["date"])):
                    add_issue("date", "DATE_FORMAT", "Invalid date format, expected YYYY-MM-DD")
            except re.error:
                # If regex malformed, treat as failure of format
                add_issue("date", "DATE_FORMAT", "Invalid date format, expected YYYY-MM-DD")

    # URL format
    if "url" in rec:
        url_regex = cfg.get("url_regex")
        if url_regex:
            try:
                if not re.match(url_regex, str(rec["url"])):
                    add_issue("url", "URL_FORMAT", "Invalid URL format, expected http(s)://")
            except re.error:
                add_issue("url", "URL_FORMAT", "Invalid URL format, expected http(s)://")

    # Tags checks
    if "tags" in rec:
        tags = rec["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            add_issue("tags", "TAGS_TYPE", "Tags must be a list of strings")
        else:
            if len(tags) == 0:
                add_issue("tags", "TAGS_EMPTY", "Tags list must not be empty")
            allowed = set(cfg.get("allowed_tags", []))
            unknown = [t for t in tags if t not in allowed]
            if unknown:
                add_issue("tags", "TAG_UNKNOWN", f"Unknown tag(s): {', '.join(unknown)}")

    status = "pass" if len(issues) == 0 else "fail"
    return status, issues


def compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    cfg_path = workspace / "pipeline" / "config.json"
    data_path = workspace / "data" / "exhibits.json"
    cfg = safe_load_json(cfg_path)
    data = safe_load_json(data_path)
    if cfg is None or data is None or not isinstance(data, list):
        return None
    checks: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    for rec in data:
        rec_id = rec.get("id", "(no-id)")
        rec_title = rec.get("title", "(no-title)")
        status, issues = validate_record_against_cfg(rec, cfg)
        if status == "pass":
            passed += 1
        else:
            failed += 1
        checks.append({
            "id": rec_id,
            "title": rec_title,
            "status": status,
            "issues": issues
        })
    return {
        "summary": {
            "total": len(data),
            "passed": passed,
            "errors": failed,
            "warnings": 0
        },
        "checks": checks
    }


def extract_section_lines(lines: List[str], section: str, section_names: List[str]) -> List[str]:
    # Find the section by a heading line containing the section name (case-insensitive)
    def is_section_heading(line: str, name: str) -> bool:
        pattern = r"^\s*#*\s*" + re.escape(name) + r"\b.*$"
        return re.search(pattern, line, flags=re.IGNORECASE) is not None

    indices = [i for i, ln in enumerate(lines) if is_section_heading(ln, section)]
    if not indices:
        return []
    start = indices[0] + 1
    # Find next section heading among known section names
    next_idx = len(lines)
    for i in range(start, len(lines)):
        for nm in section_names:
            if is_section_heading(lines[i], nm):
                next_idx = i
                break
        if next_idx != len(lines) and next_idx != start:
            break
    return lines[start:next_idx]


def parse_summary_counts(text: str) -> Dict[str, Optional[int]]:
    # Extract total, passed, failed, warnings numbers from text
    result: Dict[str, Optional[int]] = {"total": None, "passed": None, "failed": None, "warnings": None}
    lower = text.lower()
    # generic extractor: find number following keyword
    for key in ["total", "passed", "failed", "warnings"]:
        m = re.search(r"\b" + key + r"\b[^0-9]*(\d+)", lower, flags=re.IGNORECASE)
        if m:
            try:
                result[key] = int(m.group(1))
            except Exception:
                result[key] = None
    # Also handle "total exhibits"
    if result["total"] is None:
        m2 = re.search(r"\btotal\s+exhibits\b[^0-9]*(\d+)", lower, flags=re.IGNORECASE)
        if m2:
            try:
                result["total"] = int(m2.group(1))
            except Exception:
                result["total"] = None
    return result


def find_lines_with_id_and_title(lines: List[str], rec_id: str, title: str) -> List[str]:
    result = []
    for ln in lines:
        if rec_id in ln and title in ln:
            result.append(ln)
    return result


def extract_issue_tokens_from_text(text: str) -> List[Tuple[str, str]]:
    # tokens like CODE(field)
    tokens: List[Tuple[str, str]] = []
    for code, field in re.findall(r"\b([A-Z_]+)\s*\(\s*([^)]+)\s*\)", text):
        tokens.append((code.strip(), field.strip()))
    return tokens


def is_bullet_line(line: str) -> bool:
    return bool(re.match(r"^\s*[-*•]\s+", line))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_exists": 0.0,
        "report_summary_counts_correct": 0.0,
        "report_checks_issues_correct": 0.0,
        "notes_exists": 0.0,
        "notes_summary_matches_report": 0.0,
        "notes_failures_list_complete": 0.0,
        "notes_action_items_per_failed": 0.0,
        "notes_next_steps_contains_command": 0.0,
        "email_exists": 0.0,
        "email_subject_counts_correct": 0.0,
        "email_body_greeting_and_summary_counts": 0.0,
        "email_failed_list_complete": 0.0,
        "email_contains_rerun_command": 0.0,
        "email_closing_mentions_meeting_and_notes": 0.0,
    }

    # Paths
    report_path = workspace / "out" / "validation-report.json"
    notes_path = workspace / "out" / "meeting-notes.md"
    email_path = workspace / "out" / "email-to-volunteers.txt"

    # Load actual report
    report = safe_load_json(report_path)
    if report is not None and isinstance(report, dict):
        scores["report_exists"] = 1.0

    # Compute expected report from inputs (without writing)
    expected = compute_expected_from_inputs(workspace)

    # Check report summary counts align with expected
    if report is not None and isinstance(report, dict) and expected is not None:
        rep_sum = report.get("summary") or {}
        exp_sum = expected.get("summary") or {}
        if all(k in rep_sum and k in exp_sum for k in ["total", "passed", "errors", "warnings"]):
            if (rep_sum["total"] == exp_sum["total"] and
                rep_sum["passed"] == exp_sum["passed"] and
                rep_sum["errors"] == exp_sum["errors"] and
                rep_sum["warnings"] == exp_sum["warnings"]):
                scores["report_summary_counts_correct"] = 1.0

    # Check report checks and issues correctness
    if report is not None and isinstance(report, dict) and expected is not None:
        rep_checks = report.get("checks")
        exp_checks = expected.get("checks")
        if isinstance(rep_checks, list) and isinstance(exp_checks, list) and len(rep_checks) == len(exp_checks):
            # Build mapping by id
            rep_by_id: Dict[str, Dict[str, Any]] = {c.get("id"): c for c in rep_checks}
            exp_by_id: Dict[str, Dict[str, Any]] = {c.get("id"): c for c in exp_checks}
            matched = 0
            total = len(exp_checks)
            for rec_id, exp in exp_by_id.items():
                rep = rep_by_id.get(rec_id)
                if not rep:
                    continue
                status_ok = rep.get("status") == exp.get("status")
                # Compare issues by (code, field) pairs regardless of order
                exp_pairs = {(i.get("code"), i.get("field")) for i in (exp.get("issues") or [])}
                rep_pairs = {(i.get("code"), i.get("field")) for i in (rep.get("issues") or [])}
                issues_ok = exp_pairs == rep_pairs
                if status_ok and issues_ok:
                    matched += 1
            if total > 0:
                scores["report_checks_issues_correct"] = matched / total

    # For downstream checks, rely on the report-derived counts and issues
    summary_from_report = None
    failed_from_report: List[Dict[str, Any]] = []
    if report is not None and isinstance(report, dict):
        summary_from_report = report.get("summary") or {}
        checks = report.get("checks") or []
        for c in checks:
            if isinstance(c, dict) and c.get("status") == "fail":
                failed_from_report.append(c)

    # Meeting notes checks
    notes_text = safe_read_text(notes_path)
    if notes_text is not None:
        scores["notes_exists"] = 1.0
        lines = notes_text.splitlines()
        section_names = ["Summary", "Failures", "Action Items", "Next Steps"]

        # Summary counts in notes must match the report
        if summary_from_report is not None:
            summary_lines = extract_section_lines(lines, "Summary", section_names)
            summary_str = "\n".join(summary_lines)
            parsed = parse_summary_counts(summary_str)
            if (parsed.get("total") == summary_from_report.get("total") and
                parsed.get("passed") == summary_from_report.get("passed") and
                parsed.get("failed") == summary_from_report.get("errors") and
                parsed.get("warnings") == summary_from_report.get("warnings")):
                scores["notes_summary_matches_report"] = 1.0

        # Failures section completeness: list each failed exhibit with id, title, and issue tokens
        failures_lines = extract_section_lines(lines, "Failures", section_names)
        if failed_from_report and failures_lines:
            ok_count = 0
            for rec in failed_from_report:
                rec_id = rec.get("id", "")
                title = rec.get("title", "")
                needed_tokens = [f"{i.get('code')}({i.get('field')})" for i in (rec.get("issues") or [])]
                candidate_lines = find_lines_with_id_and_title(failures_lines, rec_id, title)
                found = False
                for ln in candidate_lines:
                    if all(tok in ln for tok in needed_tokens):
                        found = True
                        break
                if found:
                    ok_count += 1
            if len(failed_from_report) > 0:
                scores["notes_failures_list_complete"] = ok_count / len(failed_from_report)
        elif not failed_from_report:
            # No failures: treat as satisfied
            scores["notes_failures_list_complete"] = 1.0

        # Action Items section: for each failed exhibit, at least two bullets: Archivist + Web volunteer
        action_lines = extract_section_lines(lines, "Action Items", section_names)
        if failed_from_report and action_lines:
            per_rec_ok = 0
            for rec in failed_from_report:
                rec_id = rec.get("id", "")
                issue_fields = {i.get("field", "") for i in (rec.get("issues") or [])}
                archivist_ok = False
                web_ok = False
                for ln in action_lines:
                    if not is_bullet_line(ln):
                        continue
                    lnl = ln.lower()
                    if rec_id in ln and "archivist" in lnl:
                        # Require mention of at least one issue field to ensure specificity
                        if any(f in ln for f in issue_fields if f):
                            archivist_ok = True
                    if rec_id in ln and ("web volunteer" in lnl):
                        # Require link/asset verification keywords
                        if any(k in lnl for k in ["link", "url", "asset", "image"]):
                            web_ok = True
                if archivist_ok and web_ok:
                    per_rec_ok += 1
            if len(failed_from_report) > 0:
                scores["notes_action_items_per_failed"] = per_rec_ok / len(failed_from_report)
        elif not failed_from_report:
            scores["notes_action_items_per_failed"] = 1.0

        # Next Steps line must include exact rerun command
        if VALIDATION_COMMAND in notes_text:
            scores["notes_next_steps_contains_command"] = 1.0

    # Email checks
    email_text = safe_read_text(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        email_lines = email_text.splitlines()

        # Subject line
        subject_line = ""
        for ln in email_lines:
            if ln.lower().startswith("subject:"):
                subject_line = ln
                break
        if subject_line and summary_from_report is not None:
            subj_ok = "[QA] Digital Exhibit results" in subject_line
            m = re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", subject_line)
            if m:
                try:
                    s_passed = int(m.group(1))
                    s_failed = int(m.group(2))
                except Exception:
                    s_passed = s_failed = -1
                subj_ok = subj_ok and (s_passed == summary_from_report.get("passed")) and (s_failed == summary_from_report.get("errors"))
            else:
                subj_ok = False
            if subj_ok:
                scores["email_subject_counts_correct"] = 1.0

        # Body greeting and summary counts
        body_lines = email_lines[email_lines.index(subject_line)+1:] if subject_line in email_lines else email_lines
        body_text_lower = "\n".join(body_lines).lower()
        greeting_ok = "bayou history volunteers" in body_text_lower
        counts_ok = False
        if summary_from_report is not None:
            passed = summary_from_report.get("passed")
            failed = summary_from_report.get("errors")
            # Look for both numbers in body with words passed/failed
            body_text = "\n".join(body_lines)
            passed_ok = re.search(rf"\b{re.escape(str(passed))}\b\s+passed", body_text, flags=re.IGNORECASE) is not None
            failed_ok = re.search(rf"\b{re.escape(str(failed))}\b\s+failed", body_text, flags=re.IGNORECASE) is not None
            counts_ok = passed_ok and failed_ok
        if greeting_ok and counts_ok:
            scores["email_body_greeting_and_summary_counts"] = 1.0

        # Failed list completeness
        if failed_from_report:
            bullets = [ln for ln in body_lines if is_bullet_line(ln)]
            ok_count = 0
            for rec in failed_from_report:
                rec_id = rec.get("id", "")
                title = rec.get("title", "")
                needed_tokens = [f"{i.get('code')}({i.get('field')})" for i in (rec.get("issues") or [])]
                found = False
                for b in bullets:
                    if rec_id in b and title in b:
                        # look for parenthetical tokens
                        # Ensure each needed token appears somewhere in the line (commonly inside parentheses)
                        if all(tok in b for tok in needed_tokens):
                            found = True
                            break
                if found:
                    ok_count += 1
            if len(failed_from_report) > 0:
                scores["email_failed_list_complete"] = ok_count / len(failed_from_report)
        else:
            scores["email_failed_list_complete"] = 1.0

        # Rerun command presence
        if VALIDATION_COMMAND in email_text:
            scores["email_contains_rerun_command"] = 1.0

        # Closing line mentions next committee meeting and notes path
        closing_ok = ("committee meeting" in email_text.lower()) and ("out/meeting-notes.md" in email_text)
        if closing_ok:
            scores["email_closing_mentions_meeting_and_notes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()