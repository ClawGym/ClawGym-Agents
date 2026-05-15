import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_bool(val: str) -> bool:
    if val is None:
        return False
    return str(val).strip().lower() == "true"


def _parse_float(val: str) -> Optional[float]:
    try:
        return float(str(val).strip())
    except Exception:
        return None


def _iter_session_csv_files(workspace: Path) -> List[Path]:
    sessions_dir = workspace / "input" / "sessions"
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return []
    return sorted([p for p in sessions_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])


def _parse_date_from_filename(name: str) -> Optional[datetime]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d")
    except Exception:
        return None


def _iso_date_from_filename(name: str) -> Optional[str]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path) -> Optional[dict]:
    csv_paths = _iter_session_csv_files(workspace)
    all_rows: List[Dict[str, str]] = []
    for p in csv_paths:
        rows = _read_csv_rows(p)
        if rows is None:
            return None
        all_rows.extend(rows)

    total_participants = len(all_rows)

    sessions_completed = 0
    passes = 0
    durations: List[float] = []
    dept_cov: Dict[str, int] = {}
    issues_count: Dict[str, int] = {}

    for row in all_rows:
        dept = (row.get("department") or "").strip()
        if dept:
            dept_cov[dept] = dept_cov.get(dept, 0) + 1

        completed = _parse_bool(row.get("completed", "FALSE"))
        passed = _parse_bool(row.get("passed", "FALSE"))
        if completed:
            sessions_completed += 1
            dur = _parse_float(row.get("duration_min", ""))
            if dur is None:
                return None
            durations.append(dur)
        if passed:
            passes += 1

        issues_field = row.get("issues", "")
        parts = [p.strip().lower() for p in str(issues_field).split(";")]
        for label in parts:
            if not label or label == "none":
                continue
            issues_count[label] = issues_count.get(label, 0) + 1

    if sessions_completed > 0:
        pass_rate_percent = round((passes / sessions_completed) * 100.0, 1)
    else:
        pass_rate_percent = 0.0

    if durations:
        avg_duration = round(sum(durations) / len(durations), 1)
    else:
        avg_duration = 0.0

    sorted_issues = sorted(issues_count.items(), key=lambda kv: (-kv[1], kv[0]))
    top_issues = [{"label": lbl, "count": cnt} for lbl, cnt in sorted_issues[:3]]

    dates = []
    for p in csv_paths:
        s = _iso_date_from_filename(p.name)
        if s:
            dates.append(s)
    latest_session_date = ""
    if dates:
        latest_session_date = max(dates)

    expected = {
        "total_participants": total_participants,
        "sessions_completed": sessions_completed,
        "passes": passes,
        "pass_rate_percent": pass_rate_percent,
        "average_duration_min": avg_duration,
        "department_coverage": dept_cov,
        "top_issues": top_issues,
        "latest_session_date": latest_session_date,
        "processed_files_sorted": [p.name for p in sorted(csv_paths, key=lambda p: (_parse_date_from_filename(p.name) or datetime.min, p.name))],
    }
    return expected


def _find_subject_line(lines: List[str]) -> Optional[str]:
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            content = stripped[len("subject:"):].strip()
            return content
    if lines:
        first = lines[0].strip()
        if first:
            return first
    return None


def _split_sections(lines: List[str]) -> Dict[str, Tuple[int, int]]:
    section_names = ["highlights", "metrics", "top issues", "risks", "processed files", "next steps"]
    indices: Dict[str, int] = {}
    for i, line in enumerate(lines):
        s = line.strip().lower()
        for sec in section_names:
            if s.startswith(sec):
                if sec == "metrics" and s.startswith("metrics"):
                    indices.setdefault("metrics", i)
                elif sec == "highlights" and s.startswith("highlights"):
                    indices.setdefault("highlights", i)
                elif sec == "top issues" and s.startswith("top issues"):
                    indices.setdefault("top issues", i)
                elif sec == "risks" and s.startswith("risks"):
                    indices.setdefault("risks", i)
                elif sec == "processed files" and s.startswith("processed files"):
                    indices.setdefault("processed files", i)
                elif sec == "next steps" and s.startswith("next steps"):
                    indices.setdefault("next steps", i)
    ranges: Dict[str, Tuple[int, int]] = {}
    sorted_starts = sorted(indices.items(), key=lambda kv: kv[1])
    for idx, (name, start) in enumerate(sorted_starts):
        end = len(lines)
        if idx + 1 < len(sorted_starts):
            end = sorted_starts[idx + 1][1]
        ranges[name] = (start, end)
    return ranges


def _section_text(lines: List[str], ranges: Dict[str, Tuple[int, int]], name: str) -> str:
    rng = ranges.get(name)
    if not rng:
        return ""
    start, end = rng
    text = "\n".join(lines[start:end]).strip()
    return text


def _contains_no_placeholders(text: str) -> bool:
    placeholders = [
        "[SUBJECT_PLACEHOLDER]",
        "[HIGHLIGHTS_PLACEHOLDER]",
        "[TOTAL_PARTICIPANTS]",
        "[SESSIONS_COMPLETED]",
        "[PASS_RATE_PERCENT]",
        "[AVERAGE_DURATION_MIN]",
        "[TOP_ISSUES_LIST]",
        "[PASTE_RISKS_HERE]",
        "[FILES_LIST]",
        "[NEXT_STEPS_PLACEHOLDER]",
    ]
    for ph in placeholders:
        if ph in text:
            return False
    return True


def _email_metrics_match_json(metrics_text: str, jm: dict) -> bool:
    expected_map = {
        "total participants": str(jm.get("total_participants")),
        "completed": str(jm.get("sessions_completed")),
        "passes": str(jm.get("passes")),
        "pass rate": f"{float(jm.get('pass_rate_percent')):.1f}%",
        "avg duration": f"{float(jm.get('average_duration_min')):.1f}",
    }
    lines = [l.strip() for l in metrics_text.splitlines() if l.strip()]
    found = {k: False for k in expected_map.keys()}

    for k, expected_val in expected_map.items():
        for line in lines:
            if k in line.lower():
                if expected_val in line:
                    found[k] = True
                    break
    return all(found.values())


def _email_top_issues_match_json(top_text: str, jm: dict) -> bool:
    try:
        top = jm.get("top_issues", [])
        if not isinstance(top, list) or len(top) != 3:
            return False
    except Exception:
        return False
    lines = [l.strip().lower() for l in top_text.splitlines() if l.strip()]
    indices = []
    for item in top:
        label = str(item.get("label", "")).lower()
        count = item.get("count")
        if not label or not isinstance(count, int):
            return False
        expected_num = str(count)
        idx_found = None
        for idx, line in enumerate(lines):
            if label in line and re.search(r'(^|\D){}(\D|$)'.format(re.escape(expected_num)), line):
                idx_found = idx
                break
        if idx_found is None:
            return False
        indices.append(idx_found)
    return indices == sorted(indices)


def _email_risks_verbatim(risks_text: str, workspace: Path) -> bool:
    risk_path = workspace / "input" / "risk_notes.md"
    src = _safe_read_text(risk_path)
    if src is None:
        return False
    expected_lines = [l.rstrip() for l in src.splitlines() if l.strip()]
    actual_lines = [l.rstrip() for l in risks_text.splitlines() if l.strip()]
    return expected_lines == actual_lines


def _email_files_list_correct(proc_text: str, expected_files: List[str]) -> bool:
    lines = [l.strip() for l in proc_text.splitlines() if l.strip()]
    found_files = []
    for l in lines:
        m = re.findall(r'([0-9]{4}-[0-9]{2}-[0-9]{2}_[A-Za-z0-9_\-]+\.csv)', l)
        for fname in m:
            found_files.append(fname)
    return found_files == expected_files and len(found_files) == len(expected_files)


def _email_highlights_has_numbers(high_text: str, jm: dict) -> bool:
    tp = str(jm.get("total_participants"))
    pr = f"{float(jm.get('pass_rate_percent')):.1f}%"
    lower = high_text.lower()
    return tp in high_text and pr in high_text and "highlight" in lower


def _email_next_steps_lowest_department(next_text: str, jm: dict) -> bool:
    dept_cov = jm.get("department_coverage", {})
    if not isinstance(dept_cov, dict) or not dept_cov:
        return False
    min_count = min(dept_cov.values())
    lowest_depts = sorted([d for d, c in dept_cov.items() if c == min_count])
    target = lowest_depts[0]
    text = next_text.strip()
    dept_pattern = re.compile(r'\b{}\b'.format(re.escape(target)), flags=re.IGNORECASE)
    has_dept = bool(dept_pattern.search(text))
    has_prioritize = "priorit" in text.lower()
    return has_dept and has_prioritize


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "status_metrics_json_valid": 0.0,
        "status_metrics_values_correct": 0.0,
        "weekly_email_exists": 0.0,
        "weekly_email_no_placeholders": 0.0,
        "weekly_email_subject_correct": 0.0,
        "weekly_email_metrics_match_json": 0.0,
        "weekly_email_top_issues_match_json": 0.0,
        "weekly_email_risks_verbatim": 0.0,
        "weekly_email_processed_files_correct": 0.0,
        "weekly_email_highlights_mentions_numbers": 0.0,
        "weekly_email_next_steps_lowest_department": 0.0,
    }

    expected = _compute_expected_metrics(workspace)
    status_path = workspace / "output" / "status_metrics.json"
    jm = _safe_load_json(status_path)
    if jm is not None and isinstance(jm, dict):
        scores["status_metrics_json_valid"] = 1.0

    if expected is not None and jm is not None and isinstance(jm, dict):
        try:
            ok = True
            req_fields = [
                "total_participants",
                "sessions_completed",
                "passes",
                "pass_rate_percent",
                "average_duration_min",
                "department_coverage",
                "top_issues",
                "latest_session_date",
            ]
            for f in req_fields:
                if f not in jm:
                    ok = False
            if ok:
                ok = ok and (jm.get("total_participants") == expected["total_participants"])
                ok = ok and (jm.get("sessions_completed") == expected["sessions_completed"])
                ok = ok and (jm.get("passes") == expected["passes"])
                pr = jm.get("pass_rate_percent")
                ad = jm.get("average_duration_min")
                ok = ok and isinstance(pr, (int, float)) and abs(float(pr) - float(expected["pass_rate_percent"])) < 1e-9
                ok = ok and isinstance(ad, (int, float)) and abs(float(ad) - float(expected["average_duration_min"])) < 1e-9
                ok = ok and (jm.get("department_coverage") == expected["department_coverage"])
                top = jm.get("top_issues")
                if not (isinstance(top, list) and len(top) == len(expected["top_issues"])):
                    ok = False
                else:
                    for a, b in zip(top, expected["top_issues"]):
                        if not (isinstance(a, dict) and a.get("label") == b.get("label") and a.get("count") == b.get("count")):
                            ok = False
                            break
                ok = ok and (jm.get("latest_session_date") == expected["latest_session_date"])
            scores["status_metrics_values_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["status_metrics_values_correct"] = 0.0

    email_path = workspace / "output" / "weekly_update_email.md"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        scores["weekly_email_exists"] = 1.0
        scores["weekly_email_no_placeholders"] = 1.0 if _contains_no_placeholders(email_text) else 0.0

        lines = email_text.splitlines()
        subject_content = _find_subject_line(lines)
        exp_latest = None
        if expected is not None:
            exp_latest = expected.get("latest_session_date") or ""
        elif jm is not None:
            exp_latest = str(jm.get("latest_session_date") or "")
        else:
            exp_latest = ""
        expected_subject = f"AR Pilot Update — Week Ending {exp_latest}" if exp_latest else None
        if expected_subject:
            ok_subject = False
            if subject_content and subject_content.strip() == expected_subject:
                ok_subject = True
            scores["weekly_email_subject_correct"] = 1.0 if ok_subject else 0.0

        ranges = _split_sections(lines)
        metrics_text = _section_text(lines, ranges, "metrics")
        top_text = _section_text(lines, ranges, "top issues")
        risks_text = _section_text(lines, ranges, "risks")
        proc_text = _section_text(lines, ranges, "processed files")
        high_text = _section_text(lines, ranges, "highlights")
        next_text = _section_text(lines, ranges, "next steps")

        if jm is not None and isinstance(jm, dict) and metrics_text:
            scores["weekly_email_metrics_match_json"] = 1.0 if _email_metrics_match_json(metrics_text, jm) else 0.0

        if jm is not None and isinstance(jm, dict) and top_text:
            scores["weekly_email_top_issues_match_json"] = 1.0 if _email_top_issues_match_json(top_text, jm) else 0.0

        if risks_text:
            scores["weekly_email_risks_verbatim"] = 1.0 if _email_risks_verbatim(risks_text, workspace) else 0.0

        if expected is not None and proc_text:
            scores["weekly_email_processed_files_correct"] = 1.0 if _email_files_list_correct(proc_text, expected["processed_files_sorted"]) else 0.0

        if jm is not None and isinstance(jm, dict) and high_text:
            scores["weekly_email_highlights_mentions_numbers"] = 1.0 if _email_highlights_has_numbers(high_text, jm) else 0.0

        if jm is not None and isinstance(jm, dict) and next_text:
            scores["weekly_email_next_steps_lowest_department"] = 1.0 if _email_next_steps_lowest_department(next_text, jm) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()