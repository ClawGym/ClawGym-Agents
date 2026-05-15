import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _compute_summary_from_tasks_csv(csv_path: Path) -> Optional[Dict[str, Any]]:
    rows = _load_csv_dicts(csv_path)
    if rows is None:
        return None
    statuses = ["todo", "in_progress", "done", "blocked"]
    by_status: Dict[str, int] = {s: 0 for s in statuses}
    by_assignee: Dict[str, int] = {}
    total = 0
    for row in rows:
        total += 1
        status = (row.get("status") or "").strip()
        assignee = (row.get("assignee") or "").strip()
        if status in statuses:
            by_status[status] += 1
        else:
            by_status["todo"] += 1
        if assignee:
            by_assignee[assignee] = by_assignee.get(assignee, 0) + 1
    for s in statuses:
        by_status.setdefault(s, 0)
    return {
        "total_tasks": total,
        "by_status": dict(by_status),
        "by_assignee": dict(by_assignee),
    }


def _find_section_bounds(lines: List[str], header_predicate, start_index: int = 0) -> Optional[Tuple[int, int]]:
    header_idx = None
    for i in range(start_index, len(lines)):
        if header_predicate(lines[i]):
            header_idx = i
            break
    if header_idx is None:
        return None

    def is_any_header(line: str) -> bool:
        stripped = line.strip()
        return (
            stripped == "Summary:"
            or stripped == "Risks/Blockers:"
            or stripped == "Next steps:"
            or stripped.startswith("Highlights")
        )

    end = len(lines)
    for j in range(header_idx + 1, len(lines)):
        if is_any_header(lines[j]):
            end = j
            break
    return (header_idx + 1, end)


def _parse_status_report(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    first_non_empty = None
    for ln in lines:
        if ln.strip():
            first_non_empty = ln.strip()
            break
    title_ok = first_non_empty == "Volunteer Remediation Team - Weekly Status"
    bounds_summary = _find_section_bounds(lines, lambda l: l.strip() == "Summary:")
    summary_data = {
        "has_summary_section": bounds_summary is not None,
        "total_tasks": None,
        "status_counts": {},
        "raw_json_line": None,
        "raw_json_value_line": None,
    }
    if bounds_summary:
        s, e = bounds_summary
        content = [ln.strip() for ln in lines[s:e] if ln.strip() != ""]
        for ln in content:
            m = re.match(r"Total tasks:\s*(\d+)\s*$", ln)
            if m:
                summary_data["total_tasks"] = int(m.group(1))
                break
        for ln in content:
            m = re.match(r"(todo|in_progress|done|blocked):\s*(\d+)\s*$", ln)
            if m:
                summary_data["status_counts"][m.group(1)] = int(m.group(2))
        for idx, ln in enumerate(content):
            if ln == "Raw summary JSON:":
                summary_data["raw_json_line"] = ln
                if idx + 1 < len(content):
                    summary_data["raw_json_value_line"] = content[idx + 1]
                break
    bounds_high = _find_section_bounds(lines, lambda l: l.strip().startswith("Highlights"))
    highlights_lines: List[str] = []
    if bounds_high:
        s, e = bounds_high
        for ln in lines[s:e]:
            if ln.strip().startswith("- "):
                highlights_lines.append(ln.strip())
    bounds_risks = _find_section_bounds(lines, lambda l: l.strip() == "Risks/Blockers:")
    risks_lines: List[str] = []
    if bounds_risks:
        s, e = bounds_risks
        for ln in lines[s:e]:
            if ln.strip().startswith("- "):
                risks_lines.append(ln.strip())
    bounds_next = _find_section_bounds(lines, lambda l: l.strip() == "Next steps:")
    next_steps_lines: List[str] = []
    if bounds_next:
        s, e = bounds_next
        for ln in lines[s:e]:
            if ln.strip().startswith("- "):
                next_steps_lines.append(ln.strip())

    return {
        "title_ok": title_ok,
        "summary": summary_data,
        "highlights": highlights_lines,
        "risks": risks_lines,
        "next_steps": next_steps_lines,
    }


def _canonical_compact_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _validate_tests_output(text: str) -> bool:
    if text is None:
        return False
    t = text.strip().lower()
    has_passed = re.search(r"\b\d+\s+passed\b", t) is not None or "passed" in t
    has_failed = ("failed" in t) or ("error" in t) or ("traceback" in t)
    return bool(has_passed and not has_failed)


def _extract_expected_highlights(updates_path: Path) -> Optional[List[str]]:
    updates = _load_jsonl(updates_path)
    if updates is None:
        return None

    def _key(u: Dict[str, Any]):
        try:
            tid = int(u.get("task_id", 0) or 0)
        except Exception:
            tid = 0
        return (u.get("updated_at", ""), -tid)

    try:
        sorted_updates = sorted(updates, key=_key, reverse=True)
    except Exception:
        return None
    top3 = sorted_updates[:3]
    expected = []
    for u in top3:
        task_id = u.get("task_id")
        update_text = u.get("update")
        if task_id is None or update_text is None:
            return None
        expected.append(f"- [{task_id}] {update_text}")
    return expected


def _expected_risks_lines(tasks_csv: Path) -> Optional[List[str]]:
    rows = _load_csv_dicts(tasks_csv)
    if rows is None:
        return None
    lines = []
    for r in rows:
        status = (r.get("status") or "").strip()
        if status == "blocked":
            try:
                task_id = int((r.get("task_id") or "").strip())
            except Exception:
                return None
            description = (r.get("description") or "").strip()
            assignee = (r.get("assignee") or "").strip()
            lines.append(f"- [{task_id}] {description} — {assignee}")
    return lines


def _expected_next_steps_lines(tasks_csv: Path) -> Optional[List[str]]:
    rows = _load_csv_dicts(tasks_csv)
    if rows is None:
        return None
    lines = []
    for r in rows:
        status = (r.get("status") or "").strip()
        if status == "in_progress":
            try:
                task_id = int((r.get("task_id") or "").strip())
            except Exception:
                return None
            description = (r.get("description") or "").strip()
            assignee = (r.get("assignee") or "").strip()
            lines.append(f"- {assignee}: [{task_id}] {description}")
    return lines


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    build_dir = workspace / "build"
    data_dir = workspace / "data"

    scores: Dict[str, float] = {
        "summary_json_exists": 0.0,
        "summary_json_valid_and_matches_computation": 0.0,
        "tests_results_exists": 0.0,
        "tests_all_passed": 0.0,
        "status_report_exists": 0.0,
        "status_report_title_correct": 0.0,
        "status_report_summary_counts_match_summary_json": 0.0,
        "status_report_raw_json_line_exact": 0.0,
        "status_report_highlights_top3_correct": 0.0,
        "status_report_risks_blockers_correct": 0.0,
        "status_report_next_steps_correct": 0.0,
        "announcement_exists": 0.0,
        "announcement_under_120_words": 0.0,
        "announcement_includes_required_phrases": 0.0,
        "announcement_call_to_action_present": 0.0,
    }

    summary_json_path = build_dir / "summary.json"
    if summary_json_path.exists():
        scores["summary_json_exists"] = 1.0
        summary_obj = _load_json(summary_json_path)
        expected_summary = _compute_summary_from_tasks_csv(data_dir / "tasks.csv")
        if summary_obj is not None and expected_summary is not None and summary_obj == expected_summary:
            scores["summary_json_valid_and_matches_computation"] = 1.0

    test_results_path = build_dir / "test_results.txt"
    if test_results_path.exists():
        scores["tests_results_exists"] = 1.0
        test_output = _read_text(test_results_path)
        if test_output is not None and _validate_tests_output(test_output):
            scores["tests_all_passed"] = 1.0

    status_report_path = build_dir / "status_report.md"
    if status_report_path.exists():
        scores["status_report_exists"] = 1.0
        parsed = _parse_status_report(status_report_path)
        if parsed is not None:
            if parsed.get("title_ok"):
                scores["status_report_title_correct"] = 1.0
            summary_in_report = parsed.get("summary") or {}
            summary_obj = _load_json(summary_json_path) if summary_json_path.exists() else None
            if summary_obj is not None and summary_in_report.get("has_summary_section"):
                total_ok = summary_in_report.get("total_tasks") == summary_obj.get("total_tasks")
                by_status = summary_obj.get("by_status") or {}
                statuses_required = ["todo", "in_progress", "done", "blocked"]
                per_status_ok = True
                for s in statuses_required:
                    if summary_in_report["status_counts"].get(s) != by_status.get(s):
                        per_status_ok = False
                        break
                if total_ok and per_status_ok:
                    scores["status_report_summary_counts_match_summary_json"] = 1.0
                raw_line = summary_in_report.get("raw_json_line")
                raw_value_line = summary_in_report.get("raw_json_value_line")
                expected_compact = _canonical_compact_json(summary_obj)
                if raw_line == "Raw summary JSON:" and raw_value_line == expected_compact:
                    scores["status_report_raw_json_line_exact"] = 1.0
            expected_high = _extract_expected_highlights(data_dir / "updates.jsonl")
            if expected_high is not None:
                provided_high = parsed.get("highlights") or []
                if provided_high == expected_high:
                    scores["status_report_highlights_top3_correct"] = 1.0
            expected_risks = _expected_risks_lines(data_dir / "tasks.csv")
            if expected_risks is not None:
                provided_risks = parsed.get("risks") or []
                if sorted(provided_risks) == sorted(expected_risks):
                    scores["status_report_risks_blockers_correct"] = 1.0
            expected_next = _expected_next_steps_lines(data_dir / "tasks.csv")
            if expected_next is not None:
                provided_next = parsed.get("next_steps") or []
                if sorted(provided_next) == sorted(expected_next):
                    scores["status_report_next_steps_correct"] = 1.0

    announcement_path = build_dir / "announcement_rewrite.txt"
    if announcement_path.exists():
        scores["announcement_exists"] = 1.0
        ann_text = _read_text(announcement_path) or ""
        wc = _word_count(ann_text)
        if wc < 120:
            scores["announcement_under_120_words"] = 1.0
        lower = ann_text.lower()
        if "thank you" in lower and "let's coordinate" in lower:
            scores["announcement_includes_required_phrases"] = 1.0
        statuses_required = ["todo", "in_progress", "done", "blocked"]
        has_reply = "reply" in lower
        has_all_statuses = all(s in lower for s in statuses_required)
        if has_reply and has_all_statuses:
            scores["announcement_call_to_action_present"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()