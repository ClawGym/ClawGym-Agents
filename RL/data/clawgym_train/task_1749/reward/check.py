import json
import os
import sys
from typing import List, Tuple, Optional

def get_workspace_root(argv: List[str]) -> str:
    return argv[1] if len(argv) > 1 else "/root/.openclaw/workspace"

def read_file_lines(path: str) -> Optional[List[str]]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except Exception:
        return None

def find_section_range(lines: List[str], level_prefix: str, keyword_ci: str) -> Optional[Tuple[int, int]]:
    """
    Find the start (inclusive) and end (exclusive) line indices of a section that:
    - starts with a header line beginning with level_prefix (e.g., '## ' or '### ')
    - contains keyword_ci case-insensitively in the header line
    The end is the next header of the same level or end of file.
    """
    keyword_lower = keyword_ci.lower()
    start = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(level_prefix) and keyword_lower in stripped.lower():
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].lstrip()
        if stripped.startswith(level_prefix):
            end = j
            break
    return (start, end)

def section_has_table_pipe(lines: List[str], section_range: Optional[Tuple[int, int]]) -> bool:
    if not section_range:
        return False
    s, e = section_range
    for line in lines[s:e]:
        if "|" in line:
            return True
    return False

def section_bullet_count(lines: List[str], section_range: Optional[Tuple[int, int]], bullet_prefix="- ") -> int:
    if not section_range:
        return 0
    s, e = section_range
    count = 0
    for line in lines[s:e]:
        if line.strip().startswith(bullet_prefix):
            count += 1
    return count

def count_lines_starting_with(lines: List[str], prefix: str) -> int:
    return sum(1 for l in lines if l.startswith(prefix))

def main():
    workspace_root = get_workspace_root(sys.argv)
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # task_plan.md checks
        "task_plan_exists": False,
        "task_plan_has_goal": False,
        "task_plan_has_phases_header": False,
        "task_plan_has_5_phase_headers": False,
        "task_plan_has_5_complete_statuses": False,
        "task_plan_decisions_section_with_table": False,
        "task_plan_errors_section_with_table": False,

        # findings.md checks
        "findings_exists": False,
        "findings_has_requirements": False,
        "findings_has_research_findings": False,
        "findings_has_technical_decisions": False,
        "findings_technical_decisions_has_table": False,

        # progress.md checks
        "progress_exists": False,
        "progress_has_session_line": False,
        "progress_actions_taken_has_5_bullets": False,
        "progress_has_errors_section": False,

        # project_charter.md checks
        "project_charter_exists": False,
        "project_charter_has_title": False,
        "project_charter_has_goals": False,
        "project_charter_has_constraints": False,
        "project_charter_has_milestones": False,
        "project_charter_has_3_bullets": False,
    }

    # Paths
    task_plan_path = os.path.join(output_dir, "task_plan.md")
    findings_path = os.path.join(output_dir, "findings.md")
    progress_path = os.path.join(output_dir, "progress.md")
    project_charter_path = os.path.join(output_dir, "project_charter.md")

    # Task Plan checks
    if os.path.isfile(task_plan_path):
        checks["task_plan_exists"] = True
        lines = read_file_lines(task_plan_path) or []
        content = "\n".join(lines)

        # Required headers
        if "## Goal" in content:
            checks["task_plan_has_goal"] = True
        if "## Phases" in content:
            checks["task_plan_has_phases_header"] = True

        # Counts
        if content.count("### Phase") >= 5:
            checks["task_plan_has_5_phase_headers"] = True
        if content.count("**Status:** complete") >= 5:
            checks["task_plan_has_5_complete_statuses"] = True

        # Decisions section with table
        dec_range = find_section_range(lines, level_prefix="##", keyword_ci="Decisions")
        if dec_range and section_has_table_pipe(lines, dec_range):
            checks["task_plan_decisions_section_with_table"] = True

        # Errors section with table
        err_range = find_section_range(lines, level_prefix="##", keyword_ci="Errors")
        if err_range and section_has_table_pipe(lines, err_range):
            checks["task_plan_errors_section_with_table"] = True

    # Findings checks
    if os.path.isfile(findings_path):
        checks["findings_exists"] = True
        lines_f = read_file_lines(findings_path) or []
        content_f = "\n".join(lines_f)
        if "## Requirements" in content_f:
            checks["findings_has_requirements"] = True
        if "## Research Findings" in content_f:
            checks["findings_has_research_findings"] = True
        # Technical Decisions header
        tech_dec_range = find_section_range(lines_f, level_prefix="##", keyword_ci="Technical Decisions")
        if tech_dec_range is not None:
            checks["findings_has_technical_decisions"] = True
            if section_has_table_pipe(lines_f, tech_dec_range):
                checks["findings_technical_decisions_has_table"] = True

    # Progress checks
    if os.path.isfile(progress_path):
        checks["progress_exists"] = True
        lines_p = read_file_lines(progress_path) or []

        # ## Session: line
        for line in lines_p:
            if line.startswith("## Session:"):
                checks["progress_has_session_line"] = True
                break

        # Actions Taken section with at least 5 bullets "- "
        actions_range = find_section_range(lines_p, level_prefix="###", keyword_ci="Actions Taken")
        if actions_range is not None:
            if section_bullet_count(lines_p, actions_range, bullet_prefix="- ") >= 5:
                checks["progress_actions_taken_has_5_bullets"] = True

        # Errors section exists
        if find_section_range(lines_p, level_prefix="###", keyword_ci="Errors") is not None:
            checks["progress_has_errors_section"] = True

    # Project Charter checks
    if os.path.isfile(project_charter_path):
        checks["project_charter_exists"] = True
        lines_c = read_file_lines(project_charter_path) or []
        content_c = "\n".join(lines_c)
        if "## Title" in content_c:
            checks["project_charter_has_title"] = True
        if "## Goals" in content_c:
            checks["project_charter_has_goals"] = True
        if "## Constraints" in content_c:
            checks["project_charter_has_constraints"] = True
        if "## Milestones" in content_c:
            checks["project_charter_has_milestones"] = True
        # At least 3 bullet lines starting with "- " anywhere
        bullets_total = sum(1 for l in lines_c if l.strip().startswith("- "))
        if bullets_total >= 3:
            checks["project_charter_has_3_bullets"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure no-op baseline: if output dir missing or all main required files missing -> reward 0
    # However, our fractional computation already yields 0.0 when no checks pass.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()