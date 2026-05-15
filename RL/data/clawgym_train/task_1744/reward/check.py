import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception:
        pass
    return rows

def has_nonempty_file(path):
    try:
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) <= 0:
            return False
        # Also ensure content has some non-whitespace
        content = read_text(path)
        if content is None:
            return False
        return len(content.strip()) > 0
    except Exception:
        return False

def find_section_text(content, heading):
    # Return the text under "## <heading>" until next heading starting with '#'
    lines = content.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    # Collect until next line that starts with '#'
    section_lines = []
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("#"):
            break
        section_lines.append(lines[j])
    return "\n".join(section_lines)

def has_decisions_table_with_row(content):
    # Look for a header row that includes Decision and Rationale, then a non-separator row starting with '|'
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and ("Decision" in line and "Rationale" in line):
            # Look ahead for at least one non-separator data row
            for j in range(i+1, len(lines)):
                l2 = lines[j].rstrip("\n")
                if not l2.strip().startswith("|"):
                    # header ended
                    break
                # Skip separator lines that are mostly dashes and pipes
                stripped = l2.strip()
                only_sep_chars = stripped.replace("|", "").replace(" ", "")
                # If contains at least one non '-' character (e.g., letters, numbers), it's a data row
                if any(ch not in "-:" for ch in only_sep_chars):
                    # Additionally ensure there's at least one non-separator visible content beyond pipes/spaces
                    content_chars = re.sub(r"[|\s:-]", "", stripped)
                    if len(content_chars) > 0:
                        return True
            # If we didn't find a data row for this header, continue searching further headers
    return False

def contains_all_substrings(content, substrings):
    return all(s in content for s in substrings)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    task_plan_path = os.path.join(output_dir, "task_plan.md")
    findings_path = os.path.join(output_dir, "findings.md")
    progress_path = os.path.join(output_dir, "progress.md")

    # Initialize checks
    checks = {
        "task_plan_exists": False,
        "findings_exists": False,
        "progress_exists": False,
        "goal_in_task_plan_section": False,
        "five_phases_present": False,
        "five_status_complete": False,
        "decisions_table_in_task_plan": False,
        "findings_requirements_verbatim": False,
        "findings_constraints_verbatim": False,
        "visual_browser_section_present": False,
        "progress_test_row_files_exist_yes": False,
        "reboot_check_present": False,
        "three_strike_attempts_present": False,
    }

    # Existence and non-empty
    if has_nonempty_file(task_plan_path):
        checks["task_plan_exists"] = True
        task_plan_content = read_text(task_plan_path)
    else:
        task_plan_content = ""

    if has_nonempty_file(findings_path):
        checks["findings_exists"] = True
        findings_content = read_text(findings_path)
    else:
        findings_content = ""

    if has_nonempty_file(progress_path):
        checks["progress_exists"] = True
        progress_content = read_text(progress_path)
    else:
        progress_content = ""

    # Only proceed with content-dependent checks if corresponding file exists
    # task_plan.md: goal string in Goal section
    expected_goal = "Create a file-based execution plan for a three-sprint internal data cleanup project for the product analytics team."
    if checks["task_plan_exists"]:
        goal_section_text = find_section_text(task_plan_content, "Goal")
        if expected_goal in goal_section_text:
            checks["goal_in_task_plan_section"] = True

        # five phases: count "### Phase"
        if task_plan_content.count("### Phase") >= 5:
            checks["five_phases_present"] = True

        # at least five occurrences of "**Status:** complete"
        if task_plan_content.count("**Status:** complete") >= 5:
            checks["five_status_complete"] = True

        # decisions table present with at least one non-header row
        if has_decisions_table_with_row(task_plan_content):
            checks["decisions_table_in_task_plan"] = True

    # findings.md checks
    if checks["findings_exists"]:
        required_requirements = [
            "Use persistent markdown files to track plan, findings, and progress",
            "Mark each phase status and update them to 'complete' when done",
            "Document at least one decision with rationale",
            "Capture at least two constraints from risk register",
        ]
        if contains_all_substrings(findings_content, required_requirements):
            checks["findings_requirements_verbatim"] = True

        required_constraints = [
            "No external network access; all planning offline.",
            "All outputs must be under output/ directory only.",
        ]
        if contains_all_substrings(findings_content, required_constraints):
            checks["findings_constraints_verbatim"] = True

        if "## Visual/Browser Findings" in findings_content:
            checks["visual_browser_section_present"] = True

    # progress.md checks
    if checks["progress_exists"]:
        # Test Results row containing both "files_exist" and "yes" on the same line
        found_test_row = False
        for line in progress_content.splitlines():
            if ("files_exist" in line) and ("yes" in line):
                found_test_row = True
                break
        checks["progress_test_row_files_exist_yes"] = found_test_row

        # 5-Question Reboot Check - presence of all five prompts
        reboot_prompts = [
            "Where am I?",
            "Where am I going?",
            "What's the goal?",
            "What have I learned?",
            "What have I done?",
        ]
        if contains_all_substrings(progress_content, reboot_prompts):
            checks["reboot_check_present"] = True

    # 3-Strike Protocol attempts in either task_plan.md or progress.md
    attempts_needed = ["Attempt 1", "Attempt 2", "Attempt 3"]
    in_task_plan = contains_all_substrings(task_plan_content, attempts_needed) if checks["task_plan_exists"] else False
    in_progress = contains_all_substrings(progress_content, attempts_needed) if checks["progress_exists"] else False
    if in_task_plan or in_progress:
        checks["three_strike_attempts_present"] = True

    # Reward calculation
    # Explicit no-op baseline: if output/ missing/empty -> reward 0.0
    required_files_ok = checks["task_plan_exists"] and checks["findings_exists"] and checks["progress_exists"]
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_files_ok:
        reward = 0.0
    else:
        # All checks must pass for full success; otherwise proportional
        reward = passed_checks / total_checks
        if passed_checks == total_checks:
            reward = 1.0

    # Clamp reward
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()