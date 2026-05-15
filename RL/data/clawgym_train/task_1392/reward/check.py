import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _normalize_header(line: str) -> str:
    # Strip markdown header markers and normalize spacing/case
    return line.strip().lstrip("#").strip().lower()


def _find_section_lines(text: str, header: str, known_headers: List[str]) -> List[str]:
    lines = text.splitlines()
    start_idx = None
    target = header.lower()
    known_set = {h.lower() for h in known_headers}
    for i, line in enumerate(lines):
        if _normalize_header(line) == target:
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    # Find next header
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        norm = _normalize_header(lines[j])
        if norm in known_set:
            end_idx = j
            break
    return lines[start_idx:end_idx]


def _extract_int_from_line(line: str) -> Optional[int]:
    num = ""
    for ch in line:
        if ch.isdigit():
            num += ch
        elif num:
            break
    if num:
        try:
            return int(num)
        except Exception:
            return None
    return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _compute_top_hotspots(metrics: dict, n: int = 3) -> Optional[List[dict]]:
    try:
        files = metrics.get("files", [])
        sorted_files = sorted(files, key=lambda x: x.get("cyclomatic_complexity", -1), reverse=True)
        return sorted_files[:n]
    except Exception:
        return None


def _compute_open_issue_counts(issues: List[dict]) -> Dict[str, int]:
    counts = {"bug": 0, "enhancement": 0, "tech-debt": 0}
    try:
        for it in issues:
            if str(it.get("status", "")).lower() != "open":
                continue
            labels = it.get("labels", [])
            for label in labels:
                low = str(label).lower()
                if low in counts:
                    counts[low] += 1
    except Exception:
        pass
    return counts


def _map_open_issues_by_component(issues: List[dict]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    try:
        for it in issues:
            if str(it.get("status", "")).lower() != "open":
                continue
            comp = it.get("component")
            iid = it.get("id")
            if not comp or not iid:
                continue
            mapping.setdefault(comp, []).append(iid)
    except Exception:
        pass
    return mapping


def _most_recent_refactor_for_file(commits: List[dict], file_path: str) -> Optional[Tuple[str, str]]:
    candidates: List[Tuple[datetime, str, str]] = []
    for c in commits:
        try:
            msg = c.get("message", "")
            files = c.get("files", [])
            if not isinstance(files, list):
                continue
            if "refactor:" in msg.lower() and file_path in files:
                d = c.get("date")
                dt = _parse_date(d) if isinstance(d, str) else None
                if dt is None:
                    # If date missing or malformed, treat as very old
                    continue
                candidates.append((dt, c.get("commit", ""), d))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, commit_hash, date_str = candidates[0]
    return (commit_hash, date_str)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_exist": 0.0,
        "report_has_required_sections": 0.0,
        "report_top_hotspots_correct": 0.0,
        "open_issues_bug_count_correct": 0.0,
        "open_issues_enhancement_count_correct": 0.0,
        "open_issues_tech_debt_count_correct": 0.0,
        "report_refactor_evidence_correct": 0.0,
        "report_recommendations_include_metrics_and_issue_ids": 0.0,
        "email_subject_valid": 0.0,
        "email_hotspot_bullets_present": 0.0,
        "email_feedback_deadline_present": 0.0,
        "meeting_agenda_covers_hotspots": 0.0,
        "meeting_action_items_complete": 0.0,
    }

    # Paths
    input_metrics_path = workspace / "input" / "code_metrics.json"
    input_issues_path = workspace / "input" / "issues.json"
    input_commits_path = workspace / "input" / "commits.jsonl"

    report_path = workspace / "output" / "code_health_report.md"
    email_path = workspace / "output" / "team_email_draft.txt"
    notes_path = workspace / "output" / "meeting_notes.md"

    # Existence check for outputs
    if report_path.exists() and email_path.exists() and notes_path.exists():
        scores["outputs_exist"] = 1.0

    # Load inputs safely
    metrics = _load_json(input_metrics_path)
    issues = _load_json(input_issues_path)
    commits = _load_jsonl(input_commits_path)

    # If inputs are malformed or missing, many checks cannot proceed
    if not isinstance(metrics, dict) or not isinstance(issues, list) or not isinstance(commits, list):
        # Return scores as-is; other checks depend on inputs
        return scores

    # Compute expected values
    top_hotspots = _compute_top_hotspots(metrics, 3) or []
    expected_paths = [f.get("path") for f in top_hotspots if isinstance(f, dict)]
    expected_cc = {f["path"]: f.get("cyclomatic_complexity") for f in top_hotspots if "path" in f}
    expected_mi = {f["path"]: f.get("maintainability_index") for f in top_hotspots if "path" in f}

    issue_counts = _compute_open_issue_counts(issues)
    issues_by_component = _map_open_issues_by_component(issues)

    refactor_expected: Dict[str, Optional[Tuple[str, str]]] = {}
    for p in expected_paths:
        refactor_expected[p] = _most_recent_refactor_for_file(commits, p)

    # Report checks
    report_text = _read_text(report_path) or ""

    required_report_headers = [
        "Top Hotspots",
        "Open Issues Summary",
        "Refactor Evidence",
        "Recommendations",
    ]
    if all(_find_section_lines(report_text, h, required_report_headers) or (h.lower() in [_normalize_header(l) for l in report_text.splitlines()]) for h in required_report_headers):
        # Check that headers exist as headers (not just content); we ensure presence by scanning lines
        present_headers = set()
        for line in report_text.splitlines():
            norm = _normalize_header(line)
            for h in required_report_headers:
                if norm == h.lower():
                    present_headers.add(h.lower())
        if len(present_headers) == len(required_report_headers):
            scores["report_has_required_sections"] = 1.0

    # Report Top Hotspots correctness
    if report_text and top_hotspots and len(expected_paths) == 3:
        th_lines = _find_section_lines(report_text, "Top Hotspots", required_report_headers)
        # Gather found paths in the section among any known metric file paths
        all_metric_paths = {f.get("path") for f in metrics.get("files", []) if isinstance(f, dict) and f.get("path")}
        # Map first occurrence line index in section for expected paths
        found_positions: Dict[str, int] = {}
        for idx, line in enumerate(th_lines):
            for p in all_metric_paths:
                if p and p in line:
                    if p not in found_positions:
                        found_positions[p] = idx
        # Validate only expected three present
        present_paths = set(found_positions.keys())
        expected_set = set(expected_paths)
        # keep only those present from any; confirm others are not present
        if present_paths & all_metric_paths:
            # Paths present but we need exactly the expected ones
            if present_paths == expected_set:
                # Check order
                order_ok = True
                indexes = [found_positions[p] for p in expected_paths]
                if indexes != sorted(indexes):
                    order_ok = False
                # Check that each path line (or near) includes CC and MI values
                values_ok = True
                for p in expected_paths:
                    pos = found_positions[p]
                    window = "\n".join(th_lines[max(0, pos):min(len(th_lines), pos + 3)])
                    cc_val = str(expected_cc.get(p))
                    mi_val = str(expected_mi.get(p))
                    if cc_val not in window or mi_val not in window:
                        values_ok = False
                        break
                if order_ok and values_ok:
                    scores["report_top_hotspots_correct"] = 1.0

    # Report Open Issues Summary counts
    if report_text and isinstance(issue_counts, dict):
        ois_lines = _find_section_lines(report_text, "Open Issues Summary", required_report_headers)

        def _check_label_count(label: str, expected: int) -> float:
            for ln in ois_lines:
                if label.lower() in ln.lower():
                    val = _extract_int_from_line(ln)
                    if val is not None and val == expected:
                        return 1.0
            return 0.0

        scores["open_issues_bug_count_correct"] = _check_label_count("bug", issue_counts.get("bug", 0))
        scores["open_issues_enhancement_count_correct"] = _check_label_count("enhancement", issue_counts.get("enhancement", 0))
        scores["open_issues_tech_debt_count_correct"] = _check_label_count("tech-debt", issue_counts.get("tech-debt", 0))

    # Report Refactor Evidence correctness
    if report_text and expected_paths:
        re_lines = _find_section_lines(report_text, "Refactor Evidence", required_report_headers)

        def _check_refactor_for_file(file_path: str, expected: Optional[Tuple[str, str]]) -> bool:
            # Find lines mentioning the file path
            indices = [i for i, ln in enumerate(re_lines) if file_path in ln]
            if not indices:
                return False
            for i in indices:
                window_lines = re_lines[i : min(len(re_lines), i + 4)]
                window_text = "\n".join(window_lines).lower()
                if expected is None:
                    if "none" in window_text:
                        return True
                else:
                    commit_hash, date_str = expected
                    # Both commit hash and date must appear
                    if commit_hash and date_str and (commit_hash.lower() in window_text) and (date_str.lower() in window_text):
                        return True
            return False

        ok = True
        for p in expected_paths:
            if not _check_refactor_for_file(p, refactor_expected.get(p)):
                ok = False
                break
        if ok:
            scores["report_refactor_evidence_correct"] = 1.0

    # Report Recommendations include metrics and issue IDs
    if report_text and expected_paths:
        rec_lines = _find_section_lines(report_text, "Recommendations", required_report_headers)

        def _has_recommendation_with_metrics_and_issues(file_path: str, cc: int, mi: int, issue_ids: List[str]) -> bool:
            # Find a line with the file path
            idxs = [i for i, ln in enumerate(rec_lines) if file_path in ln]
            if not idxs:
                return False
            for i in idxs:
                window_lines = rec_lines[i : min(len(rec_lines), i + 5)]
                window_text = "\n".join(window_lines)
                if (str(cc) in window_text) and (str(mi) in window_text):
                    # If there are open issues, ensure their IDs are mentioned
                    if issue_ids:
                        if all(iid in window_text for iid in issue_ids):
                            return True
                    else:
                        # If no issues, no requirement for issue IDs
                        return True
            return False

        ok = True
        for p in expected_paths:
            cc = expected_cc.get(p)
            mi = expected_mi.get(p)
            issue_ids = issues_by_component.get(p, [])
            if cc is None or mi is None:
                ok = False
                break
            if not _has_recommendation_with_metrics_and_issues(p, cc, mi, issue_ids):
                ok = False
                break
        if ok:
            scores["report_recommendations_include_metrics_and_issue_ids"] = 1.0

    # Email checks
    email_text = _read_text(email_path) or ""
    if email_text:
        # Subject validation
        subj_ok = False
        for line in email_text.splitlines():
            s = line.strip()
            if s.lower().startswith("subject:"):
                remainder = s[len("subject:") :].strip()
                if remainder.startswith("Proposal:"):
                    subj_ok = True
                    break
            elif s.startswith("Proposal:"):
                subj_ok = True
                break
        scores["email_subject_valid"] = 1.0 if subj_ok else 0.0

        # Bullet list includes the three hotspot files
        bullet_lines = [ln for ln in email_text.splitlines() if ln.lstrip().startswith(("-", "*"))]
        present = set()
        for p in expected_paths:
            for ln in bullet_lines:
                if p in ln:
                    present.add(p)
                    break
        scores["email_hotspot_bullets_present"] = 1.0 if len(present) == len(expected_paths) and len(expected_paths) == 3 else 0.0

        # Feedback deadline by 2026-06-01
        if ("2026-06-01" in email_text) and ("feedback" in email_text.lower()):
            scores["email_feedback_deadline_present"] = 1.0

    # Meeting notes checks
    notes_text = _read_text(notes_path) or ""
    if notes_text:
        meeting_headers = ["Agenda", "Action items"]
        agenda_lines = _find_section_lines(notes_text, "Agenda", meeting_headers)
        # Agenda must have one item for each hotspot file (presence check)
        agenda_ok = all(any(p in ln for ln in agenda_lines) for p in expected_paths)
        scores["meeting_agenda_covers_hotspots"] = 1.0 if agenda_ok else 0.0

        action_lines = _find_section_lines(notes_text, "Action items", meeting_headers)

        def _check_action_item_for_file(file_path: str, expected_issue_ids: List[str]) -> bool:
            # Find line containing file path
            idxs = [i for i, ln in enumerate(action_lines) if file_path in ln]
            if not idxs:
                return False
            for i in idxs:
                window = action_lines[i : min(len(action_lines), i + 8)]
                window_text = "\n".join(window)
                owner_ok = "Owner: TBD" in window_text
                linked_lines = [ln for ln in window if "Linked issues" in ln]
                linked_ok = False
                if expected_issue_ids:
                    if linked_lines and all(any(iid in ln for ln in linked_lines) for iid in expected_issue_ids):
                        linked_ok = True
                else:
                    if linked_lines and any("none" in ln.lower() for ln in linked_lines):
                        linked_ok = True
                scope_ok = any("Proposed scope" in ln for ln in window)
                if owner_ok and linked_ok and scope_ok:
                    return True
            return False

        actions_ok = all(_check_action_item_for_file(p, issues_by_component.get(p, [])) for p in expected_paths)
        scores["meeting_action_items_complete"] = 1.0 if actions_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()