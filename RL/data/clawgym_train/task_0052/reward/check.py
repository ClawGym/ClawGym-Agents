import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _run_impact_check(workspace: Path) -> Optional[Dict[str, Any]]:
    script = workspace / "input" / "impact_check.py"
    route = workspace / "input" / "route.csv"
    zones = workspace / "input" / "protected_zones.json"
    if not (script.is_file() and route.is_file() and zones.is_file()):
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--route", str(route), "--zones", str(zones)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return {"stdout": proc.stdout, "stderr": proc.stderr, "code": proc.returncode}
    except Exception:
        return None


def _parse_summary_from_text(text: str) -> Optional[Tuple[int, int, int]]:
    # Expect line like: SUMMARY: segments=5, errors=2, warnings=2
    m = re.search(r"SUMMARY:\s*segments\s*=\s*(\d+)\s*,\s*errors\s*=\s*(\d+)\s*,\s*warnings\s*=\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _parse_log(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    if not lines:
        return None
    # Exit code should be on the last line and formatted as EXIT_CODE: <number>
    last = lines[-1].strip()
    m_exit = re.fullmatch(r"EXIT_CODE:\s*(-?\d+)", last)
    exit_code = int(m_exit.group(1)) if m_exit else None

    summary = _parse_summary_from_text(text)
    return {
        "text": text,
        "lines": lines,
        "exit_code": exit_code,
        "summary": summary,
    }


def _calc_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    # Prefer to run the script to compute expected behavior deterministically
    result = _run_impact_check(workspace)
    if result is None:
        return None
    summary = _parse_summary_from_text(result["stdout"] + "\n" + result["stderr"])
    return {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "code": result["code"],
        "summary": summary,
    }


def _find_required_log_messages(text: str) -> Dict[str, bool]:
    # Look for key messages for S2, S3, S4, S5 with expected markers
    checks = {
        "has_s2_warning": False,
        "has_s3_error_missing_zone": False,
        "has_s4_error_no_entry": False,
        "has_s5_warning_seasonal": False,
    }
    # Simplify search by checking presence of substrings with some flexibility
    checks["has_s2_warning"] = bool(
        re.search(r"WARNING:.*Segment\s+S2.*wetland_buffer.*buffer-50m", text, re.IGNORECASE | re.DOTALL)
    )
    checks["has_s3_error_missing_zone"] = bool(
        re.search(r"ERROR:.*Segment\s+S3.*missing\s+zone_id", text, re.IGNORECASE | re.DOTALL)
    )
    checks["has_s4_error_no_entry"] = bool(
        re.search(r"ERROR:.*Segment\s+S4.*nesting_area.*no-entry", text, re.IGNORECASE | re.DOTALL)
    )
    checks["has_s5_warning_seasonal"] = bool(
        re.search(r"WARNING:.*Segment\s+S5.*park_access.*seasonal-closure", text, re.IGNORECASE | re.DOTALL)
    )
    return checks


def _extract_count_from_report(text: str, label: str) -> Optional[int]:
    # Try multiple patterns: "label=5", "label: 5", "5 label(s)"
    # 1) label=<num> or label: <num>
    m = re.search(rf"{re.escape(label)}\s*[:=]\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 2) <num> label
    m2 = re.search(rf"(\d+)\s+{re.escape(label)}s?\b", text, re.IGNORECASE)
    if m2:
        return int(m2.group(1))
    return None


def _status_update_sentence_count(text: str) -> Optional[int]:
    # Find "Status Update" section and count sentences (., !, ?)
    m = re.search(r"Status Update", text, re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    # take the next 600 characters or until end
    snippet = text[start:start + 600]
    # Stop at next markdown header if present
    hdr = re.search(r"\n\s*#+\s", snippet)
    if hdr:
        snippet = snippet[:hdr.start()]
    # Count sentences (approx)
    sentences = re.split(r"[.!?]+", snippet)
    # Count non-empty trimmed sentences
    count = sum(1 for s in sentences if s.strip())
    return count if count > 0 else None


def _parse_action_plan(action_plan_text: str) -> Dict[str, Any]:
    # Parse tasks by splitting on '- id:' at line starts; collect chunks and key fields
    tasks: List[Dict[str, Any]] = []
    lines = action_plan_text.splitlines()
    indices = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*-\s+id:\s*\S+", ln):
            indices.append(i)
    indices.append(len(lines))
    for idx in range(len(indices) - 1):
        start = indices[idx]
        end = indices[idx + 1]
        chunk_lines = lines[start:end]
        chunk_text = "\n".join(chunk_lines)
        # Extract id
        m_id = re.search(r"^\s*-\s+id:\s*(\S+)", chunk_lines[0])
        task_id = m_id.group(1) if m_id else None
        has_title = bool(re.search(r"^\s*title:\s*.+", chunk_text, re.MULTILINE))
        has_prereqs = bool(re.search(r"^\s*prereqs:\s*(\[.*\]|$)", chunk_text, re.MULTILINE))
        has_prereqs_list = has_prereqs or bool(re.search(r"^\s*prereqs:\s*$\n(\s*-\s*.+\n)+", chunk_text, re.MULTILINE))
        m_due = re.search(r"^\s*due_date:\s*(\d{4}-\d{2}-\d{2})", chunk_text, re.MULTILINE)
        due_date = m_due.group(1) if m_due else None
        has_owner = bool(re.search(r"^\s*owner:\s*.+", chunk_text, re.MULTILINE))
        has_deliverables = bool(re.search(r"^\s*deliverables:\s*(\[.*\]|$)", chunk_text, re.MULTILINE))
        has_deliverables_list = has_deliverables or bool(re.search(r"^\s*deliverables:\s*$\n(\s*-\s*.+\n)+", chunk_text, re.MULTILINE))
        tasks.append({
            "id": task_id,
            "chunk": chunk_text,
            "has_title": has_title,
            "has_prereqs": has_prereqs_list,
            "due_date": due_date,
            "has_owner": has_owner,
            "has_deliverables": has_deliverables_list,
        })
    # Extract all due dates
    all_due_dates = []
    for t in tasks:
        if t["due_date"]:
            all_due_dates.append(t["due_date"])
    return {"tasks": tasks, "all_due_dates": all_due_dates}


def _parse_dates(dates: List[str]) -> List[datetime]:
    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(d, "%Y-%m-%d"))
        except Exception:
            continue
    return parsed


def _earliest_due_date(dates: List[str]) -> Optional[str]:
    parsed = _parse_dates(dates)
    if not parsed:
        return None
    earliest = min(parsed)
    return earliest.strftime("%Y-%m-%d")


def _find_bulleted_lines_with_dates(text: str) -> Tuple[List[str], List[str]]:
    bullets = []
    dates = []
    for ln in text.splitlines():
        if re.match(r"^\s*[-*]\s+", ln):
            bullets.append(ln)
            for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", ln):
                dates.append(m.group(1))
    return bullets, dates


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "impact_log_present": 0.0,
        "log_summary_matches_expected": 0.0,
        "log_exit_code_line_correct": 0.0,
        "log_includes_required_messages": 0.0,
        "compliance_report_present": 0.0,
        "report_counts_match_log": 0.0,
        "report_lists_problem_segments": 0.0,
        "report_has_status_update_2_to_4_sentences": 0.0,
        "action_plan_present_min_5_tasks_with_fields": 0.0,
        "action_plan_references_segments_and_restrictions": 0.0,
        "public_update_rewritten_present_and_length_reduced": 0.0,
        "public_update_includes_restricted_error_count_and_earliest_due_date": 0.0,
        "email_present": 0.0,
        "email_summarizes_counts": 0.0,
        "email_bullets_cover_action_plan_due_dates": 0.0,
    }

    # Paths
    log_path = workspace / "outputs" / "logs" / "impact_check_output.txt"
    report_path = workspace / "outputs" / "compliance_report.md"
    action_plan_path = workspace / "outputs" / "action_plan.yaml"
    public_update_path = workspace / "outputs" / "messages" / "public_update_rewritten.txt"
    email_path = workspace / "outputs" / "messages" / "email_to_organizers.txt"
    original_public_update_path = workspace / "input" / "public_update_draft.txt"

    # Compute expected by running the script, if possible
    expected = _calc_expected_from_inputs(workspace)

    # Parse produced log file
    log_info = _parse_log(log_path) if log_path.is_file() else None
    if log_info:
        scores["impact_log_present"] = 1.0

    # Validate log summary vs expected
    if log_info and expected and expected.get("summary"):
        expected_summary = expected["summary"]  # (segments, errors, warnings)
        log_summary = log_info.get("summary")
        if log_summary == expected_summary:
            scores["log_summary_matches_expected"] = 1.0

    # Validate exit code line format and correctness
    if log_info:
        exit_code = log_info.get("exit_code")
        if exit_code is not None:
            # Check last line format OK
            # Check logical consistency with summary
            summary = log_info.get("summary")
            consistent = False
            if summary:
                seg, err, warn = summary
                expected_code = 2 if err and err > 0 else (1 if warn and warn > 0 else 0)
                consistent = (expected_code == exit_code)
            # If also have expected from running, ensure match with that too
            if expected:
                consistent = consistent and (exit_code == expected.get("code"))
            if consistent:
                scores["log_exit_code_line_correct"] = 1.0

    # Validate log contains required messages
    if log_info:
        checks = _find_required_log_messages(log_info["text"])
        if all(checks.values()):
            scores["log_includes_required_messages"] = 1.0

    # Compliance report checks
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["compliance_report_present"] = 1.0
        # Counts match log
        if log_info and log_info.get("summary"):
            seg_c, err_c, warn_c = log_info["summary"]
            seg_r = _extract_count_from_report(report_text, "segments")
            err_r = _extract_count_from_report(report_text, "errors")
            warn_r = _extract_count_from_report(report_text, "warnings")
            if seg_r == seg_c and err_r == err_c and warn_r == warn_c:
                scores["report_counts_match_log"] = 1.0
        # Problem segments listed
        # Require S2-wetland_buffer-buffer-50m, S4-nesting_area-no-entry, S5-park_access-seasonal-closure
        # and S3 missing zone mention
        ok_s2 = bool(re.search(r"S2", report_text)) and bool(re.search(r"wetland_buffer", report_text)) and bool(re.search(r"buffer-50m", report_text))
        ok_s4 = bool(re.search(r"S4", report_text)) and bool(re.search(r"nesting_area", report_text)) and bool(re.search(r"no-entry", report_text))
        ok_s5 = bool(re.search(r"S5", report_text)) and bool(re.search(r"park_access", report_text)) and bool(re.search(r"seasonal-closure", report_text))
        ok_s3 = bool(re.search(r"S3", report_text)) and bool(re.search(r"missing\s+zone", report_text, re.IGNORECASE))
        if ok_s2 and ok_s4 and ok_s5 and ok_s3:
            scores["report_lists_problem_segments"] = 1.0
        # Status Update 2-4 sentences
        scount = _status_update_sentence_count(report_text)
        if scount is not None and 2 <= scount <= 4:
            scores["report_has_status_update_2_to_4_sentences"] = 1.0

    # Action plan checks
    action_plan_text = _read_text(action_plan_path)
    parsed_action_plan: Optional[Dict[str, Any]] = None
    if action_plan_text is not None:
        parsed_action_plan = _parse_action_plan(action_plan_text)
        tasks = parsed_action_plan["tasks"]
        # Validate at least 5 tasks and each task has required fields
        if len(tasks) >= 5:
            per_task_ok = True
            for t in tasks:
                # id present, title, prereqs, due_date format, owner, deliverables
                if not (t["id"] and t["has_title"] and t["has_prereqs"] and t["due_date"] and t["has_owner"] and t["has_deliverables"]):
                    per_task_ok = False
                    break
                # validate date format
                try:
                    datetime.strptime(t["due_date"], "%Y-%m-%d")
                except Exception:
                    per_task_ok = False
                    break
            if per_task_ok:
                scores["action_plan_present_min_5_tasks_with_fields"] = 1.0

        # References to segments and restrictions
        ap_text = action_plan_text
        has_s2 = "S2" in ap_text
        has_s3 = "S3" in ap_text
        has_s4 = "S4" in ap_text
        has_s5 = "S5" in ap_text
        has_buf = "buffer-50m" in ap_text
        has_seasonal = "seasonal-closure" in ap_text
        has_noentry = "no-entry" in ap_text
        # For S3, ensure some mention of zone issue
        has_s3_issue = bool(re.search(r"S3", ap_text)) and bool(re.search(r"zone[_\s-]?id|missing\s+zone", ap_text, re.IGNORECASE))
        if has_s2 and has_s3 and has_s4 and has_s5 and has_buf and has_seasonal and has_noentry and has_s3_issue:
            scores["action_plan_references_segments_and_restrictions"] = 1.0

    # Public update rewritten
    rewritten_text = _read_text(public_update_path)
    if rewritten_text is not None:
        # Length reduction by about 30% compared to original (by characters)
        orig_text = _read_text(original_public_update_path) or ""
        if orig_text:
            if len(rewritten_text) <= 0.7 * len(orig_text):
                scores["public_update_rewritten_present_and_length_reduced"] = 1.0
        # Includes restricted-zone error count (no-entry count) and earliest due date from action plan
        ok_facts = False
        if parsed_action_plan:
            earliest = _earliest_due_date(parsed_action_plan["all_due_dates"])
        else:
            earliest = None
        restricted_no_entry_count = None
        if log_info and log_info.get("text"):
            # Count no-entry errors from log text
            restricted_no_entry_count = len(re.findall(r"ERROR:.*no-entry", log_info["text"], re.IGNORECASE))
        # Check presence
        has_due_date = (earliest is not None) and (earliest in rewritten_text)
        has_restricted_count = False
        if restricted_no_entry_count is not None:
            # Look for either exact phrase or number near "restricted" or "no-entry"
            num_str = str(restricted_no_entry_count)
            pattern = re.compile(rf"(restricted|no-entry)[^0-9]{{0,20}}{re.escape(num_str)}|{re.escape(num_str)}[^a-zA-Z]{{0,10}}(restricted|no-entry)", re.IGNORECASE)
            if pattern.search(rewritten_text):
                has_restricted_count = True
        if has_due_date and has_restricted_count:
            ok_facts = True
        if ok_facts:
            scores["public_update_includes_restricted_error_count_and_earliest_due_date"] = 1.0

    # Email checks
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["email_present"] = 1.0
        # Summarize counts with exact errors and warnings counts (from log summary)
        if log_info and log_info.get("summary"):
            _, err_c, warn_c = log_info["summary"]
            # Look for "<num> errors" and "<num> warnings" (order independent)
            has_err = bool(re.search(rf"\b{err_c}\b\s+errors?\b|\berrors?\b\s*[:=]\s*\b{err_c}\b", email_text, re.IGNORECASE))
            has_warn = bool(re.search(rf"\b{warn_c}\b\s+warnings?\b|\bwarnings?\b\s*[:=]\s*\b{warn_c}\b", email_text, re.IGNORECASE))
            if has_err and has_warn:
                scores["email_summarizes_counts"] = 1.0
        # Bulleted list of requested actions aligned with tasks from action_plan, each with due_date
        if parsed_action_plan:
            all_due_dates = parsed_action_plan["all_due_dates"]
            bullets, bullet_dates = _find_bulleted_lines_with_dates(email_text)
            # Require at least as many bullets-with-dates as tasks (i.e., one per task), and coverage of all due dates
            if bullets and len([d for d in bullet_dates]) >= len(all_due_dates) and all(d in bullet_dates for d in all_due_dates):
                scores["email_bullets_cover_action_plan_due_dates"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()