import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _canonicalize_newlines(s: str) -> str:
    lines = s.splitlines()
    return "\n".join([ln.rstrip() for ln in lines]).strip()


def _parse_patient_feedback(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    items = []
    try:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Memory:"):
                items.append(stripped[len("Memory:"):].strip())
            elif stripped.startswith("Thanks:"):
                items.append(stripped[len("Thanks:"):].strip())
        return items
    except Exception:
        return None


def _parse_shift_actions(path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text(path)
    if text is None:
        return None
    teams = {"child-life-team", "gratitude-committee", "volunteer-logistics"}
    pattern = re.compile(r'^Action\[(?P<team>[^\]]+)\]:\s*(?P<desc>.+)$')
    out: Dict[str, List[str]] = {t: [] for t in teams}
    try:
        for line in text.splitlines():
            stripped = line.strip()
            m = pattern.match(stripped)
            if not m:
                continue
            team = m.group("team").strip()
            desc = m.group("desc").strip()
            if team in out:
                out[team].append(desc)
        return out
    except Exception:
        return None


def _normalize_heading_text(line: str) -> Optional[str]:
    s = line.strip()
    if not s:
        return None
    if s.startswith("#"):
        s2 = s.lstrip("#").strip()
        return s2 if s2 else None
    # Also allow plain-line headings as lenient support
    return s


def _find_section_indices(lines: List[str], section_title: str) -> Optional[Tuple[int, int]]:
    section_start = None
    for i, line in enumerate(lines):
        title = _normalize_heading_text(line)
        if title == section_title:
            section_start = i
            break
    if section_start is None:
        return None
    for j in range(section_start + 1, len(lines)):
        t = _normalize_heading_text(lines[j])
        if t is not None and j != section_start:
            return (section_start + 1, j - 1)
    return (section_start + 1, len(lines) - 1)


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(("-", "*")):
            if len(s) >= 2 and s[1] == " ":
                bullets.append(s[2:].strip())
            else:
                bullets.append(s[1:].strip())
    return bullets


def _parse_action_items_by_team(lines: List[str], teams: List[str]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {t: [] for t in teams}
    team_set = set(teams)
    current_team: Optional[str] = None
    other_section_titles = {"Memories & Gratitude", "Action Items by Team"}
    for ln in lines:
        title = _normalize_heading_text(ln)
        if title:
            if title in team_set:
                current_team = title
                continue
            if title in other_section_titles:
                current_team = None
                continue
        if current_team is not None:
            s = ln.strip()
            if s.startswith(("-", "*")):
                if len(s) >= 2 and s[1] == " ":
                    txt = s[2:].strip()
                else:
                    txt = s[1:].strip()
                result[current_team].append(txt)
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_routing_rules_updated": 0.0,
        "process_script_unchanged": 0.0,
        "assigned_tasks_file_present": 0.0,
        "assigned_tasks_correct_and_complete": 0.0,
        "meeting_notes_file_present": 0.0,
        "meeting_notes_memories_section_correct": 0.0,
        "meeting_notes_team_subsections_present": 0.0,
        "meeting_notes_tasks_listed_under_correct_team": 0.0,
        "meeting_notes_shift_actions_included": 0.0,
    }

    # Check process_tasks.py unchanged (string compare after normalizing newlines)
    process_script_path = workspace / "input/process_tasks.py"
    expected_process_script = """import os
import json
from pathlib import Path

INPUT_TASKS = Path("input/tasks.jsonl")
INPUT_WORKFLOW = Path("input/workflow.json")
OUTPUT_DIR = Path("output")
OUTPUT_ASSIGNED = OUTPUT_DIR / "assigned_tasks.jsonl"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path):
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def write_jsonl(path: Path, records):
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\\n")


def assign_tasks(tasks, rules, fallback):
    assigned = []
    for t in tasks:
        team = fallback
        tags = t.get("tags", [])
        for tag in tags:
            if tag in rules:
                team = rules[tag]
                break
        out = dict(t)
        out["assigned_team"] = team
        assigned.append(out)
    return assigned


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not INPUT_TASKS.exists():
        raise FileNotFoundError(f"Missing tasks file: {INPUT_TASKS}")
    if not INPUT_WORKFLOW.exists():
        raise FileNotFoundError(f"Missing workflow config: {INPUT_WORKFLOW}")

    workflow = load_json(INPUT_WORKFLOW)
    routing = workflow.get("routing", {})
    rules = routing.get("rules", {})
    fallback = routing.get("fallback_team", "unassigned")

    tasks = read_jsonl(INPUT_TASKS)
    assigned = assign_tasks(tasks, rules, fallback)
    write_jsonl(OUTPUT_ASSIGNED, assigned)

if __name__ == "__main__":
    main()
"""
    actual_script = _read_text(process_script_path)
    script_unchanged = False
    if actual_script is not None:
        if _canonicalize_newlines(actual_script) == _canonicalize_newlines(expected_process_script):
            script_unchanged = True

    # Load config and check rules holistically
    workflow_path = workspace / "input/workflow.json"
    workflow = _load_json(workflow_path)
    rules = {}
    fallback_team = None
    if workflow is not None and isinstance(workflow, dict):
        routing = workflow.get("routing", {})
        if isinstance(routing, dict):
            rules = routing.get("rules", {}) or {}
            fallback_team = routing.get("fallback_team", None)

    # Single strict config check: all required rules present and preserved
    config_ok = False
    if isinstance(rules, dict):
        if (
            rules.get("supplies") == "volunteer-logistics"
            and rules.get("playroom") == "child-life-team"
            and rules.get("pediatrics") == "child-life-team"
            and rules.get("gratitude") == "gratitude-committee"
            and fallback_team == "unassigned"
        ):
            config_ok = True
            scores["config_routing_rules_updated"] = 1.0

    # Only award script unchanged if config is correctly updated (avoid baseline credit)
    if config_ok and script_unchanged:
        scores["process_script_unchanged"] = 1.0

    # Read input tasks
    input_tasks_path = workspace / "input/tasks.jsonl"
    input_tasks = _read_jsonl(input_tasks_path) or []

    # Assigned tasks output checks
    assigned_path = workspace / "output/assigned_tasks.jsonl"
    assigned_records = _read_jsonl(assigned_path)
    if assigned_records is not None:
        scores["assigned_tasks_file_present"] = 1.0

    # Compute expected assignment based on current config (script logic)
    expected_assignment: Dict[str, str] = {}
    expected_titles: Dict[str, str] = {}
    if input_tasks and isinstance(rules, dict):
        expected_fallback = fallback_team if isinstance(fallback_team, str) else "unassigned"
        for t in input_tasks:
            tid = t.get("id")
            title = t.get("title")
            if tid is not None:
                expected_titles[tid] = title
            team = expected_fallback
            tags = t.get("tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    if tag in rules:
                        team = rules[tag]
                        break
            if tid is not None:
                expected_assignment[tid] = team

    # Validate assigned tasks correctness and completeness
    if assigned_records is not None and input_tasks:
        ok = True
        assigned_by_id: Dict[str, dict] = {}
        for rec in assigned_records:
            tid = rec.get("id")
            if tid in assigned_by_id:
                ok = False
                break
            assigned_by_id[tid] = rec
        if ok:
            if set(assigned_by_id.keys()) != set([t.get("id") for t in input_tasks]):
                ok = False
        if ok:
            for tid, exp_team in expected_assignment.items():
                rec = assigned_by_id.get(tid)
                if rec is None:
                    ok = False
                    break
                if rec.get("assigned_team") != exp_team:
                    ok = False
                    break
        if ok:
            scores["assigned_tasks_correct_and_complete"] = 1.0

    # Meeting notes existence
    meeting_path = workspace / "output/meeting_notes.md"
    meeting_text = _read_text(meeting_path)
    if meeting_text is not None:
        scores["meeting_notes_file_present"] = 1.0

    # Prepare expected memory and thanks items
    patient_feedback_path = workspace / "input/notes/patient_feedback.md"
    expected_memories = _parse_patient_feedback(patient_feedback_path) or []

    # Prepare expected shift actions
    nurse_shift_notes_path = workspace / "input/notes/nurse_shift_notes.md"
    expected_actions = _parse_shift_actions(nurse_shift_notes_path) or {}

    # Validate meeting notes structure and content
    if meeting_text is not None:
        lines = meeting_text.splitlines()
        # Check "Memories & Gratitude" section bullets match expected
        mem_section = _find_section_indices(lines, "Memories & Gratitude")
        mem_ok = False
        if mem_section is not None:
            s, e = mem_section
            mem_lines = lines[s:e+1] if e >= s else []
            mem_bullets = _extract_bullets(mem_lines)
            if mem_bullets == expected_memories:
                mem_ok = True
        if mem_ok:
            scores["meeting_notes_memories_section_correct"] = 1.0

        # Action items by team section
        action_section = _find_section_indices(lines, "Action Items by Team")
        team_subsections_ok = False
        tasks_under_team_ok = False
        shift_actions_ok = False

        teams_from_assigned = set()
        if assigned_records is not None:
            for rec in assigned_records:
                at = rec.get("assigned_team")
                if isinstance(at, str):
                    teams_from_assigned.add(at)
        teams_from_actions = {t for t, lst in expected_actions.items() if lst} if expected_actions else set()
        all_teams = sorted(list(teams_from_assigned.union(teams_from_actions)))

        if action_section is not None:
            s2, e2 = action_section
            action_lines = lines[s2:e2+1] if e2 >= s2 else []
            per_team_bullets = _parse_action_items_by_team(action_lines, all_teams)

            if all(team in per_team_bullets for team in all_teams):
                team_subsections_ok = True

            # Validate task bullets placement and uniqueness
            if assigned_records is not None:
                task_pattern = re.compile(r'^\[Task:\s*(?P<id>[^\s\u2014\]]+)\s+\u2014\s+(?P<title>.+)\]$')
                found_task_locations: Dict[str, str] = {}
                found_task_titles: Dict[str, str] = {}
                duplicate_found = False
                unknown_task_bullets = False
                for team, bullets in per_team_bullets.items():
                    for b in bullets:
                        m = task_pattern.match(b)
                        if m:
                            tid = m.group("id").strip()
                            ttitle = m.group("title").strip()
                            if tid in found_task_locations:
                                duplicate_found = True
                            found_task_locations[tid] = team
                            found_task_titles[tid] = ttitle
                expected_ids = [t.get("id") for t in input_tasks] if input_tasks else []
                # Unknown task bullets detection: if any found id not in expected_ids
                if found_task_locations and expected_ids:
                    extra_ids = set(found_task_locations.keys()) - set(expected_ids)
                    if extra_ids:
                        unknown_task_bullets = True
                tasks_ok = True
                if duplicate_found or unknown_task_bullets:
                    tasks_ok = False
                if tasks_ok:
                    for rec in assigned_records:
                        tid = rec.get("id")
                        team = rec.get("assigned_team")
                        title = rec.get("title")
                        if tid not in found_task_locations:
                            tasks_ok = False
                            break
                        if found_task_locations[tid] != team:
                            tasks_ok = False
                            break
                        if found_task_titles.get(tid) != title:
                            tasks_ok = False
                            break
                    if tasks_ok and set(found_task_locations.keys()) != set(expected_ids):
                        tasks_ok = False
                if tasks_ok:
                    tasks_under_team_ok = True

            # Validate shift actions presence: each expected action per team must appear as a bullet under that team
            if expected_actions is not None:
                actions_ok = True
                for team, expected_list in expected_actions.items():
                    if not expected_list:
                        continue
                    bullets = per_team_bullets.get(team, [])
                    for exp in expected_list:
                        if exp not in bullets:
                            actions_ok = False
                            break
                    if not actions_ok:
                        break
                if actions_ok:
                    shift_actions_ok = True

        if team_subsections_ok:
            scores["meeting_notes_team_subsections_present"] = 1.0
        if tasks_under_team_ok:
            scores["meeting_notes_tasks_listed_under_correct_team"] = 1.0
        if shift_actions_ok:
            scores["meeting_notes_shift_actions_included"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()