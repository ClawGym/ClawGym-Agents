import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional


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


def _safe_read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_time_log(rows: List[Dict[str, str]]) -> Tuple[Optional[datetime], Optional[datetime], Dict[str, int], Dict[str, Dict[str, int]], Dict[str, Dict[str, int]]]:
    """
    Returns: (start_date, end_date, total_minutes_by_child, minutes_by_child_subject, minutes_by_child_topic)
    Dates are datetime.date objects (kept as datetime for simplicity with .date()).
    """
    all_dates = []
    total_by_child: Dict[str, int] = {}
    by_child_subject: Dict[str, Dict[str, int]] = {}
    by_child_topic: Dict[str, Dict[str, int]] = {}
    for row in rows:
        try:
            date_str = row.get("date", "").strip()
            child = row.get("child", "").strip()
            subject = row.get("subject", "").strip()
            topic = row.get("topic", "").strip()
            minutes = int(row.get("minutes", "").strip())
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            # Malformed row -> cause parse failure by returning Nones
            return (None, None, {}, {}, {})
        all_dates.append(dt)
        total_by_child[child] = total_by_child.get(child, 0) + minutes
        by_child_subject.setdefault(child, {})
        by_child_subject[child][subject] = by_child_subject[child].get(subject, 0) + minutes
        by_child_topic.setdefault(child, {})
        by_child_topic[child][topic] = by_child_topic[child].get(topic, 0) + minutes
    if not all_dates:
        return (None, None, total_by_child, by_child_subject, by_child_topic)
    start = min(all_dates)
    end = max(all_dates)
    return (start, end, total_by_child, by_child_subject, by_child_topic)


def _parse_notes(notes_dir: Path) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], List[Path]]:
    """
    Parses all *.md under notes_dir.
    Returns (achievements_by_child, challenges_by_child, files_list)
    Bullets are returned as exact lines including '- ' prefix, trimmed of trailing whitespace.
    """
    achievements: Dict[str, List[str]] = {"Maya": [], "Leo": []}
    challenges: Dict[str, List[str]] = {"Maya": [], "Leo": []}
    files = sorted(notes_dir.glob("*.md"))
    for p in files:
        text = _safe_read_text(p)
        if text is None:
            continue
        lines = text.splitlines()
        current_section = None
        for raw in lines:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.lower().startswith("## achievements"):
                current_section = "achievements"
                continue
            if stripped.lower().startswith("## challenges"):
                current_section = "challenges"
                continue
            # End section on next heading
            if stripped.startswith("## "):
                current_section = None
            if current_section in ("achievements", "challenges"):
                m = re.match(r'^\s*-\s*(Maya|Leo):\s*(.+)$', line)
                if m:
                    child = m.group(1)
                    bullet = line.strip()
                    if current_section == "achievements":
                        achievements.setdefault(child, []).append(bullet)
                    else:
                        challenges.setdefault(child, []).append(bullet)
    return achievements, challenges, files


def _get_child_section(report_text: str, child: str) -> str:
    """
    Attempt to extract the section for a child based on headings containing the child's name.
    If not found, return the entire report text.
    """
    lines = report_text.splitlines()
    start_idx = None
    end_idx = None
    child_lower = child.lower()
    for idx, line in enumerate(lines):
        sl = line.strip()
        if sl.startswith("#") and child_lower in sl.lower():
            start_idx = idx
            break
    if start_idx is None:
        return report_text
    for idx in range(start_idx + 1, len(lines)):
        sl = lines[idx].strip()
        if sl.startswith("#") and (("maya" in sl.lower() and child_lower != "maya") or ("leo" in sl.lower() and child_lower != "leo") or ("sources" in sl.lower())):
            end_idx = idx
            break
    section_lines = lines[start_idx:end_idx] if end_idx is not None else lines[start_idx:]
    return "\n".join(section_lines)


def _paragraphs(text: str) -> List[str]:
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paras.append("\n".join(current))
    return paras


def _contains_subject_minutes(section_text: str, subject: str, minutes: int) -> bool:
    for line in section_text.splitlines():
        if subject in line and re.search(rf'\b{minutes}\b', line):
            return True
    return False


def _contains_topic_minutes(section_text: str, topic: str, minutes: int) -> bool:
    for line in section_text.splitlines():
        if topic in line and re.search(rf'\b{minutes}\b', line):
            return True
    return False


def _round_percent(numerator: int, denominator: int) -> int:
    if denominator == 0:
        return 0
    return int(round((numerator / denominator) * 100))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "progress_report_present": 0.0,
        "summary_json_present": 0.0,
        "reporting_period_correct_in_report": 0.0,
        "overview_totals_present": 0.0,
        "maya_subject_minutes_listed": 0.0,
        "leo_subject_minutes_listed": 0.0,
        "maya_goal_progress_correct": 0.0,
        "leo_goal_progress_correct": 0.0,
        "maya_top_topics_listed": 0.0,
        "leo_top_topics_listed": 0.0,
        "maya_achievements_included": 0.0,
        "leo_achievements_included": 0.0,
        "maya_challenges_included": 0.0,
        "leo_challenges_included": 0.0,
        "maya_next_steps_correct": 0.0,
        "leo_next_steps_correct": 0.0,
        "sources_section_complete": 0.0,
        "summary_period_correct": 0.0,
        "summary_children_values_correct": 0.0,
        "summary_minutes_by_subject_correct": 0.0,
        "summary_top_topics_correct": 0.0,
        "summary_files_inspected_correct": 0.0,
    }

    # Paths
    time_log_path = workspace / "input" / "time_log.csv"
    goals_path = workspace / "input" / "goals.json"
    notes_dir = workspace / "input" / "notes"
    progress_report_path = workspace / "output" / "progress_report.md"
    summary_json_path = workspace / "output" / "summary.json"

    # Load inputs
    rows = _safe_read_csv_rows(time_log_path) if time_log_path.exists() else None
    goals = _safe_load_json(goals_path) if goals_path.exists() else None
    achievements_by_child, challenges_by_child, notes_files = ({}, {}, [])
    if notes_dir.exists() and notes_dir.is_dir():
        achievements_by_child, challenges_by_child, notes_files = _parse_notes(notes_dir)
    # Compute expected values if inputs are valid
    start_dt = None
    end_dt = None
    total_by_child: Dict[str, int] = {}
    by_child_subject: Dict[str, Dict[str, int]] = {}
    by_child_topic: Dict[str, Dict[str, int]] = {}
    if rows is not None:
        start_dt, end_dt, total_by_child, by_child_subject, by_child_topic = _parse_time_log(rows)
    # Parse goals totals
    goal_minutes_total: Dict[str, int] = {}
    goal_minutes_by_subject: Dict[str, Dict[str, int]] = {}
    if goals and isinstance(goals, dict):
        children_obj = goals.get("children", {})
        if isinstance(children_obj, dict):
            for child, data in children_obj.items():
                gbs = {}
                if isinstance(data, dict):
                    gbs = data.get("goal_minutes_by_subject", {}) or {}
                if isinstance(gbs, dict):
                    goal_minutes_by_subject[child] = {}
                    total = 0
                    malformed = False
                    for subj, mins in gbs.items():
                        try:
                            val = int(mins)
                        except Exception:
                            malformed = True
                            break
                        goal_minutes_by_subject[child][subj] = val
                        total += val
                    goal_minutes_total[child] = 0 if malformed else total

    # Read outputs
    report_text = _safe_read_text(progress_report_path) if progress_report_path.exists() else None
    summary_obj = _safe_load_json(summary_json_path) if summary_json_path.exists() else None

    # Existence checks
    if progress_report_path.exists() and isinstance(report_text, str):
        scores["progress_report_present"] = 1.0
    if summary_json_path.exists() and isinstance(summary_obj, dict):
        scores["summary_json_present"] = 1.0

    # Prepare expected values only if inputs were valid
    inputs_ok = (
        rows is not None
        and start_dt is not None
        and end_dt is not None
        and isinstance(goals, dict)
        and isinstance(goal_minutes_by_subject, dict)
    )
    # Reporting period in report
    if report_text and start_dt and end_dt:
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")
        period_ok = False
        for line in report_text.splitlines():
            if start_str in line and end_str in line and line.strip().startswith("#"):
                period_ok = True
                break
        scores["reporting_period_correct_in_report"] = 1.0 if period_ok else 0.0

    # Overview paragraph totals per child
    if report_text and total_by_child:
        paras = _paragraphs(report_text)
        maya_total = total_by_child.get("Maya", 0)
        leo_total = total_by_child.get("Leo", 0)
        overview_ok = False
        for p in paras:
            if ("Maya" in p and "Leo" in p and
                re.search(rf'\b{maya_total}\b', p) and
                re.search(rf'\b{leo_total}\b', p)):
                overview_ok = True
                break
        scores["overview_totals_present"] = 1.0 if overview_ok else 0.0

    # Per-child sections and checks
    children = ["Maya", "Leo"]
    if report_text and inputs_ok:
        for child in children:
            section = _get_child_section(report_text, child)
            # Subject minutes listed
            subj_ok = True
            subj_minutes = by_child_subject.get(child, {})
            for subj, mins in subj_minutes.items():
                if not _contains_subject_minutes(section, subj, mins):
                    subj_ok = False
                    break
            key = "maya_subject_minutes_listed" if child == "Maya" else "leo_subject_minutes_listed"
            scores[key] = 1.0 if subj_ok and len(subj_minutes) > 0 else 0.0

            # Goal progress: total vs goal and percentage
            total_mins = total_by_child.get(child, 0)
            goal_total = goal_minutes_total.get(child, 0)
            percent = _round_percent(total_mins, goal_total if goal_total else 0)
            numbers_present = (re.search(rf'\b{total_mins}\b', section) is not None) and (re.search(rf'\b{goal_total}\b', section) is not None)
            percent_present = (re.search(rf'\b' + str(percent) + r'%\b', section) is not None)
            key = "maya_goal_progress_correct" if child == "Maya" else "leo_goal_progress_correct"
            scores[key] = 1.0 if numbers_present and percent_present else 0.0

            # Top 3 topics by time
            topics = by_child_topic.get(child, {})
            sorted_topics = sorted(topics.items(), key=lambda kv: (-kv[1], kv[0]))
            top3 = sorted_topics[:3]
            topics_ok = True if top3 else False
            for topic, mins in top3:
                if not _contains_topic_minutes(section, topic, mins):
                    topics_ok = False
                    break
            key = "maya_top_topics_listed" if child == "Maya" else "leo_top_topics_listed"
            scores[key] = 1.0 if topics_ok else 0.0

            # Achievements bullets included (in child's section)
            ach_bullets = achievements_by_child.get(child, []) if achievements_by_child else []
            ach_ok = True if ach_bullets else False
            for b in ach_bullets:
                if b not in section:
                    ach_ok = False
                    break
            key = "maya_achievements_included" if child == "Maya" else "leo_achievements_included"
            scores[key] = 1.0 if ach_ok else 0.0

            # Challenges bullets included (in child's section)
            ch_bullets = challenges_by_child.get(child, []) if challenges_by_child else []
            ch_ok = True if ch_bullets else False
            for b in ch_bullets:
                if b not in section:
                    ch_ok = False
                    break
            key = "maya_challenges_included" if child == "Maya" else "leo_challenges_included"
            scores[key] = 1.0 if ch_ok else 0.0

            # Next steps
            next_steps_ok = False
            child_goals = goal_minutes_by_subject.get(child, {})
            if child_goals:
                lowest_subject = None
                lowest_ratio = None
                for subj, gmins in child_goals.items():
                    logged = by_child_subject.get(child, {}).get(subj, 0)
                    ratio = (logged / gmins) if gmins > 0 else 0.0
                    if lowest_ratio is None or ratio < lowest_ratio:
                        lowest_ratio = ratio
                        lowest_subject = subj
                plan_text = f"Plan an extra 30-minute session on {lowest_subject}" if lowest_subject else None
                section_contains_plan = (plan_text in section) if plan_text else False
                if ch_bullets:
                    first_challenge_text = ch_bullets[0]
                    addr_expected = "Address: " + re.sub(r'^\s*-\s*', '', first_challenge_text).strip()
                    section_contains_address = addr_expected in section
                else:
                    section_contains_address = True
                next_steps_ok = bool(section_contains_plan and section_contains_address)
            key = "maya_next_steps_correct" if child == "Maya" else "leo_next_steps_correct"
            scores[key] = 1.0 if next_steps_ok else 0.0

    # Sources section complete
    if report_text:
        has_sources_heading = any(line.strip().startswith("#") and "sources" in line.strip().lower() for line in report_text.splitlines())
        expected_files = [str(Path("input") / "time_log.csv"), str(Path("input") / "goals.json")]
        expected_files += [str(Path("input") / "notes" / p.name) for p in notes_files]
        all_listed = True if expected_files else False
        for ef in expected_files:
            if ef not in report_text:
                all_listed = False
                break
        scores["sources_section_complete"] = 1.0 if (has_sources_heading and all_listed and expected_files) else 0.0

    # Summary JSON checks
    if isinstance(summary_obj, dict) and inputs_ok:
        # Period
        start_str = start_dt.strftime("%Y-%m-%d") if start_dt else None
        end_str = end_dt.strftime("%Y-%m-%d") if end_dt else None
        period_obj = summary_obj.get("period", {})
        period_ok = isinstance(period_obj, dict) and period_obj.get("start") == start_str and period_obj.get("end") == end_str
        scores["summary_period_correct"] = 1.0 if period_ok else 0.0

        # Files inspected
        expected_files = [str(Path("input") / "time_log.csv"), str(Path("input") / "goals.json")]
        expected_files += [str(Path("input") / "notes" / p.name) for p in notes_files]
        files_inspected = summary_obj.get("files_inspected")
        files_ok = False
        if isinstance(files_inspected, list):
            files_ok = set(files_inspected) == set(expected_files)
        scores["summary_files_inspected_correct"] = 1.0 if files_ok else 0.0

        # Children values
        children_list = summary_obj.get("children")
        children_ok = False
        mins_by_subject_ok = False
        tops_ok = False
        if isinstance(children_list, list):
            expected_children = {}
            for child in ["Maya", "Leo"]:
                total_mins = total_by_child.get(child, 0)
                goal_total = goal_minutes_total.get(child, 0)
                percent = _round_percent(total_mins, goal_total if goal_total else 0)
                expected_children[child] = {
                    "total_minutes": total_mins,
                    "goal_minutes_total": goal_total,
                    "goal_progress_percent": percent,
                    "minutes_by_subject": by_child_subject.get(child, {}),
                    "top_topics": sorted(sorted(by_child_topic.get(child, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:3], key=lambda kv: (-kv[1], kv[0])),
                    "achievements_count": len(achievements_by_child.get(child, [])) if achievements_by_child else 0,
                    "challenges_count": len(challenges_by_child.get(child, [])) if challenges_by_child else 0,
                }
            found = {c.get("name"): c for c in children_list if isinstance(c, dict) and "name" in c}
            try:
                children_ok = True
                mins_by_subject_ok = True
                tops_ok = True
                for cname, exp in expected_children.items():
                    cobj = found.get(cname)
                    if not isinstance(cobj, dict):
                        children_ok = False
                        mins_by_subject_ok = False
                        tops_ok = False
                        break
                    if cobj.get("total_minutes") != exp["total_minutes"]:
                        children_ok = False
                    if cobj.get("goal_minutes_total") != exp["goal_minutes_total"]:
                        children_ok = False
                    if cobj.get("goal_progress_percent") != exp["goal_progress_percent"]:
                        children_ok = False
                    # minutes_by_subject exact match
                    mbs = cobj.get("minutes_by_subject")
                    if mbs != exp["minutes_by_subject"]:
                        mins_by_subject_ok = False
                    # top topics: validate that the set of top topics and their minutes include the expected three (order not enforced)
                    tt = cobj.get("top_topics")
                    if not isinstance(tt, list):
                        tops_ok = False
                    else:
                        tt_pairs = set()
                        try:
                            for item in tt:
                                if not isinstance(item, dict):
                                    continue
                                tt_pairs.add((item.get("topic"), int(item.get("minutes"))))
                        except Exception:
                            tops_ok = False
                        exp_pairs = set(exp["top_topics"])
                        exp_pairs2 = set((t, m) for (t, m) in exp_pairs)
                        if not exp_pairs2.issubset(tt_pairs):
                            tops_ok = False
                    # achievements_count and challenges_count
                    if cobj.get("achievements_count") != exp["achievements_count"]:
                        children_ok = False
                    if cobj.get("challenges_count") != exp["challenges_count"]:
                        children_ok = False
            except Exception:
                children_ok = False
                mins_by_subject_ok = False
                tops_ok = False
        scores["summary_children_values_correct"] = 1.0 if children_ok else 0.0
        scores["summary_minutes_by_subject_correct"] = 1.0 if mins_by_subject_ok else 0.0
        scores["summary_top_topics_correct"] = 1.0 if tops_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()