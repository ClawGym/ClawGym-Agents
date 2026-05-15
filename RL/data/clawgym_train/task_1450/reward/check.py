import json
import csv
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from statistics import median
from typing import Optional, List, Dict, Any, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_rows_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path) -> Optional[Dict[str, Any]]:
    issues_path = workspace / "input" / "coordination_issues.csv"
    log_path = workspace / "input" / "check_log.txt"
    rows = _read_csv_rows_safe(issues_path)
    log_text = _read_text_safe(log_path)
    if rows is None or log_text is None:
        return None

    total_issues = len(rows)
    open_issues = 0
    resolved_issues = 0
    by_severity: Dict[str, int] = {}
    durations: List[int] = []
    all_dates: List[date] = []
    by_project: Dict[str, Dict[str, int]] = {}

    for r in rows:
        status = (r.get("status") or "").strip()
        severity = (r.get("severity") or "").strip()
        project = (r.get("project") or "").strip()
        opened_at = _parse_iso_date(r.get("opened_at") or "")
        resolved_at = _parse_iso_date(r.get("resolved_at") or "")

        if opened_at:
            all_dates.append(opened_at)
        if resolved_at:
            all_dates.append(resolved_at)

        if status == "open":
            open_issues += 1
        if status == "resolved":
            resolved_issues += 1
            if opened_at and resolved_at:
                delta_days = (resolved_at - opened_at).days
                durations.append(delta_days)

        if severity:
            by_severity[severity] = by_severity.get(severity, 0) + 1

        if project:
            proj = by_project.setdefault(project, {"open": 0, "resolved": 0})
            if status == "open":
                proj["open"] += 1
            if status == "resolved":
                proj["resolved"] += 1

    avg_resolution_days = None
    median_resolution_days = None
    if durations:
        avg_resolution_days = round(sum(durations) / len(durations), 2)
        # Median could be float if even count
        median_resolution_days = float(median(durations))

    overdue_open_issues = 0
    if all_dates:
        max_dt = max(all_dates)
        threshold = max_dt - timedelta(days=14)
        for r in rows:
            if (r.get("status") or "").strip() == "open":
                opened_at = _parse_iso_date(r.get("opened_at") or "")
                if opened_at and opened_at <= threshold:
                    overdue_open_issues += 1

    # Parse log details
    lines = log_text.splitlines()
    computed_error_count = sum(1 for ln in lines if ln.startswith("ERROR:"))
    computed_warning_count = sum(1 for ln in lines if ln.startswith("WARNING:"))
    summary_error_count: Optional[int] = None
    summary_warning_count: Optional[int] = None
    for ln in lines:
        if ln.startswith("SUMMARY:"):
            # Expect "SUMMARY: X errors, Y warnings"
            try:
                part = ln.split("SUMMARY:", 1)[1].strip()
                # Split by commas and parse
                # Example: "4 errors, 3 warnings"
                pieces = [p.strip() for p in part.split(",")]
                # First piece: "4 errors"
                # Second piece: "3 warnings"
                se = pieces[0].split()[0]
                sw = pieces[1].split()[0]
                summary_error_count = int(se)
                summary_warning_count = int(sw)
            except Exception:
                summary_error_count = None
                summary_warning_count = None
            break

    exit_code = 0
    for ln in lines:
        if "exit code" in ln:
            # E.g., "Process finished with exit code 1"
            try:
                tail = ln.split("exit code", 1)[1]
                n = int(tail.strip().split()[0])
                exit_code = n
            except Exception:
                pass

    # Top error messages
    error_counts: Dict[str, int] = {}
    for ln in lines:
        if ln.startswith("ERROR:"):
            msg = ln[len("ERROR:"):].strip()
            error_counts[msg] = error_counts.get(msg, 0) + 1
    # Sort by count desc, then message asc for determinism (though grading won't require tiebreak)
    top_error_messages = sorted(
        [{"message": m, "count": c} for m, c in error_counts.items()],
        key=lambda x: (-x["count"], x["message"])
    )

    counts_match = (
        summary_error_count is not None
        and summary_warning_count is not None
        and summary_error_count == computed_error_count
        and summary_warning_count == computed_warning_count
    )

    expected = {
        "total_issues": total_issues,
        "open_issues": open_issues,
        "resolved_issues": resolved_issues,
        "by_severity": by_severity,
        "avg_resolution_days": avg_resolution_days,
        "median_resolution_days": median_resolution_days,
        "overdue_open_issues": overdue_open_issues,
        "by_project": by_project,
        "log": {
            "computed_error_count": computed_error_count,
            "computed_warning_count": computed_warning_count,
            "summary_error_count": summary_error_count,
            "summary_warning_count": summary_warning_count,
            "counts_match": counts_match,
            "exit_code": exit_code,
            "top_error_messages": top_error_messages,
        },
    }
    return expected


def _float_equal_to_2_decimals(value: Any, expected: float) -> bool:
    try:
        v = float(value)
    except Exception:
        return False
    return round(v, 2) == round(expected, 2)


def _numbers_equal(a: Any, b: Any) -> bool:
    try:
        # Treat as numbers (int/float)
        va = float(a)
        vb = float(b)
        return abs(va - vb) < 1e-9
    except Exception:
        return False


def _find_section_indices(lines: List[str], section_name: str) -> Optional[int]:
    for idx, line in enumerate(lines):
        if section_name in line:
            return idx
    return None


def _extract_block(lines: List[str], start_idx: int, next_section_names: List[str]) -> List[str]:
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        for name in next_section_names:
            if name in lines[i]:
                end_idx = i
                return lines[start_idx + 1:end_idx]
    return lines[start_idx + 1:end_idx]


def _line_contains_numbers(line: str, numbers: List[int]) -> bool:
    found = []
    for n in numbers:
        if str(n) in line:
            found.append(n)
    return len(found) == len(numbers)


def _find_line_with_all(lines: List[str], required_substrings: List[str]) -> Optional[str]:
    for line in lines:
        ok = True
        for s in required_substrings:
            if s not in line:
                ok = False
                break
        if ok:
            return line
    return None


def _check_message_with_count(block_lines: List[str], message: str, count: int) -> bool:
    # Look for line containing the message and number on same or next line
    for i, line in enumerate(block_lines):
        if message in line:
            if str(count) in line:
                return True
            if i + 1 < len(block_lines) and str(count) in block_lines[i + 1]:
                return True
            return False
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_present": 0.0,
        "metrics_json_exists": 0.0,
        "status_report_exists": 0.0,
        "metrics_json_parseable": 0.0,
        "metrics_total_open_resolved_correct": 0.0,
        "metrics_by_severity_correct": 0.0,
        "metrics_resolution_stats_correct": 0.0,
        "metrics_overdue_open_issues_correct": 0.0,
        "metrics_by_project_correct": 0.0,
        "log_counts_correct_computed": 0.0,
        "log_summary_counts_parsed": 0.0,
        "log_counts_match_correct": 0.0,
        "log_exit_code_correct": 0.0,
        "log_top_error_messages_correct": 0.0,
        "log_top_error_messages_sorted": 0.0,
        "report_overview_contains_counts": 0.0,
        "report_issue_metrics_severity_bullets": 0.0,
        "report_issue_metrics_project_lines": 0.0,
        "report_log_diagnostics_contains_required": 0.0,
        "report_next_steps_overdue_bullet": 0.0,
    }

    # Check script presence
    script_path = workspace / "tools" / "generate_status.py"
    if script_path.is_file():
        scores["script_present"] = 1.0

    metrics_path = workspace / "output" / "metrics.json"
    report_path = workspace / "output" / "status_report.md"

    if metrics_path.is_file():
        scores["metrics_json_exists"] = 1.0
    if report_path.is_file():
        scores["status_report_exists"] = 1.0

    expected = _compute_expected_metrics(workspace)

    metrics = _load_json_safe(metrics_path) if metrics_path.is_file() else None
    if metrics is not None and isinstance(metrics, dict):
        scores["metrics_json_parseable"] = 1.0

    # Metrics checks only if both expected and metrics present
    if expected is not None and isinstance(metrics, dict):
        # total, open, resolved
        try:
            if (
                int(metrics.get("total_issues", -1)) == expected["total_issues"]
                and int(metrics.get("open_issues", -1)) == expected["open_issues"]
                and int(metrics.get("resolved_issues", -1)) == expected["resolved_issues"]
            ):
                scores["metrics_total_open_resolved_correct"] = 1.0
        except Exception:
            pass

        # by_severity dict of counts
        try:
            ms = metrics.get("by_severity", {})
            if isinstance(ms, dict):
                # Convert counts to ints, compare exactly on keys and values
                ms_int = {str(k): int(v) for k, v in ms.items()}
                if ms_int == expected["by_severity"]:
                    scores["metrics_by_severity_correct"] = 1.0
        except Exception:
            pass

        # avg and median resolution days
        try:
            avg_ok = (
                (expected["avg_resolution_days"] is None and metrics.get("avg_resolution_days") in (None, "null"))
                or (expected["avg_resolution_days"] is not None and _float_equal_to_2_decimals(metrics.get("avg_resolution_days"), expected["avg_resolution_days"]))
            )
            med_ok = (
                (expected["median_resolution_days"] is None and metrics.get("median_resolution_days") in (None, "null"))
                or (expected["median_resolution_days"] is not None and _numbers_equal(metrics.get("median_resolution_days"), expected["median_resolution_days"]))
            )
            if avg_ok and med_ok:
                scores["metrics_resolution_stats_correct"] = 1.0
        except Exception:
            pass

        # overdue_open_issues
        try:
            if int(metrics.get("overdue_open_issues", -1)) == expected["overdue_open_issues"]:
                scores["metrics_overdue_open_issues_correct"] = 1.0
        except Exception:
            pass

        # by_project structure
        try:
            mp = metrics.get("by_project", {})
            ok = isinstance(mp, dict)
            if ok:
                for proj, counts in expected["by_project"].items():
                    if proj not in mp or not isinstance(mp[proj], dict):
                        ok = False
                        break
                    try:
                        if int(mp[proj].get("open", -1)) != counts["open"]:
                            ok = False
                            break
                        if int(mp[proj].get("resolved", -1)) != counts["resolved"]:
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
                # Also ensure no unexpected projects?
                if ok:
                    if set(mp.keys()) != set(expected["by_project"].keys()):
                        ok = False
            if ok:
                scores["metrics_by_project_correct"] = 1.0
        except Exception:
            pass

        # Log nested checks
        log_obj = metrics.get("log") if isinstance(metrics, dict) else None
        if isinstance(log_obj, dict):
            # computed counts
            try:
                if int(log_obj.get("computed_error_count", -1)) == expected["log"]["computed_error_count"] and int(
                    log_obj.get("computed_warning_count", -1)
                ) == expected["log"]["computed_warning_count"]:
                    scores["log_counts_correct_computed"] = 1.0
            except Exception:
                pass

            # summary counts parsed
            try:
                se = log_obj.get("summary_error_count", None)
                sw = log_obj.get("summary_warning_count", None)
                # Accept None or null mapping
                if expected["log"]["summary_error_count"] is None and se is None and expected["log"]["summary_warning_count"] is None and sw is None:
                    scores["log_summary_counts_parsed"] = 1.0
                elif expected["log"]["summary_error_count"] is not None and expected["log"]["summary_warning_count"] is not None:
                    if int(se) == expected["log"]["summary_error_count"] and int(sw) == expected["log"]["summary_warning_count"]:
                        scores["log_summary_counts_parsed"] = 1.0
            except Exception:
                pass

            # counts_match
            try:
                cm = log_obj.get("counts_match", None)
                if isinstance(cm, bool) and cm == expected["log"]["counts_match"]:
                    scores["log_counts_match_correct"] = 1.0
            except Exception:
                pass

            # exit_code
            try:
                if int(log_obj.get("exit_code", -1)) == expected["log"]["exit_code"]:
                    scores["log_exit_code_correct"] = 1.0
            except Exception:
                pass

            # top_error_messages: counts and membership
            try:
                tem = log_obj.get("top_error_messages", None)
                ok_counts = False
                ok_sorted = False
                if isinstance(tem, list):
                    # counts check: match set and counts
                    exp_map = {e["message"]: e["count"] for e in expected["log"]["top_error_messages"]}
                    got_map = {}
                    all_counts_non_increasing = True
                    prev = None
                    for item in tem:
                        if not isinstance(item, dict):
                            all_counts_non_increasing = False
                            break
                        msg = item.get("message")
                        cnt = item.get("count")
                        try:
                            cnti = int(cnt)
                        except Exception:
                            all_counts_non_increasing = False
                            break
                        got_map[msg] = cnti
                        if prev is None:
                            prev = cnti
                        else:
                            if cnti > prev:
                                all_counts_non_increasing = False
                            prev = cnti
                    if exp_map == got_map:
                        ok_counts = True
                    if all_counts_non_increasing:
                        ok_sorted = True
                if ok_counts:
                    scores["log_top_error_messages_correct"] = 1.0
                if ok_sorted:
                    scores["log_top_error_messages_sorted"] = 1.0
            except Exception:
                pass

    # Status report checks
    report_text = _read_text_safe(report_path) if report_path.is_file() else None
    if expected is not None and isinstance(report_text, str):
        lines = report_text.splitlines()

        # Overview section: one line summarizing total, open, resolved
        ov_idx = _find_section_indices(lines, "Overview")
        if ov_idx is not None:
            # Next non-empty line
            summary_line = None
            for i in range(ov_idx + 1, len(lines)):
                if lines[i].strip():
                    summary_line = lines[i]
                    break
            if summary_line and _line_contains_numbers(summary_line, [expected["total_issues"], expected["open_issues"], expected["resolved_issues"]]):
                scores["report_overview_contains_counts"] = 1.0

        # Issue Metrics section
        im_idx = _find_section_indices(lines, "Issue Metrics")
        if im_idx is not None:
            im_block = _extract_block(lines, im_idx, ["Log Diagnostics", "Next Steps", "Overview"])
            # Severity bullets: look for bullet lines containing each severity and its count
            severities_ok = True
            for sev, cnt in expected["by_severity"].items():
                found = False
                for ln in im_block:
                    if ln.strip().startswith(("-", "*")) and (sev in ln) and (str(cnt) in ln):
                        found = True
                        break
                if not found:
                    severities_ok = False
                    break
            if severities_ok:
                scores["report_issue_metrics_severity_bullets"] = 1.0

            # Project lines like "<Project> — Open: <n>, Resolved: <n>"
            projects_ok = True
            for proj, counts in expected["by_project"].items():
                found_line = _find_line_with_all(im_block, [proj, "Open", "Resolved"])
                if not found_line:
                    projects_ok = False
                    break
                # Check numbers appear
                if not (_line_contains_numbers(found_line, [counts["open"], counts["resolved"]])):
                    projects_ok = False
                    break
            if projects_ok:
                scores["report_issue_metrics_project_lines"] = 1.0

        # Log Diagnostics section
        ld_idx = _find_section_indices(lines, "Log Diagnostics")
        if ld_idx is not None:
            ld_block = _extract_block(lines, ld_idx, ["Next Steps", "Overview", "Issue Metrics"])
            ok_exit = any(("exit code" in ln and str(expected["log"]["exit_code"]) in ln) for ln in ld_block)
            ok_err = any(("error" in ln.lower() and str(expected["log"]["computed_error_count"]) in ln) for ln in ld_block)
            ok_warn = any(("warning" in ln.lower() and str(expected["log"]["computed_warning_count"]) in ln) for ln in ld_block)
            cm_expected_strs = ["true"] if expected["log"]["counts_match"] else ["false"]
            ok_cm = any(("counts_match" in ln.lower() and any(s in ln.lower() for s in cm_expected_strs)) for ln in ld_block)
            # Top error messages with counts
            tem_ok = True
            for item in expected["log"]["top_error_messages"]:
                if not _check_message_with_count(ld_block, item["message"], item["count"]):
                    tem_ok = False
                    break
            if ok_exit and ok_err and ok_warn and ok_cm and tem_ok:
                scores["report_log_diagnostics_contains_required"] = 1.0

        # Next Steps: bullet includes "Overdue open issues: <n>"
        ns_idx = _find_section_indices(lines, "Next Steps")
        if ns_idx is not None:
            ns_block = _extract_block(lines, ns_idx, ["Overview", "Issue Metrics", "Log Diagnostics"])
            overdue_line_ok = False
            phrase = f"Overdue open issues: {expected['overdue_open_issues']}"
            for ln in ns_block:
                if ln.strip().startswith(("-", "*")) and phrase in ln:
                    overdue_line_ok = True
                    break
            if overdue_line_ok:
                scores["report_next_steps_overdue_bullet"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()