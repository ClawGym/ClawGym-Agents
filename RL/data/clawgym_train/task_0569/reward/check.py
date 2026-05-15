import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def to_int_or_none(v):
    try:
        return int(v)
    except Exception:
        return None

def find_tasks_by_request(tasks, request_text):
    res = []
    for t in tasks:
        if isinstance(t, dict) and t.get("request_text") == request_text:
            res.append(t)
    return res

def has_blocked_with_notes(task):
    status = task.get("status")
    notes = task.get("notes")
    return status == "blocked" and isinstance(notes, str) and ("BLOCKED:" in notes)

def assignment_pair_in_text(text, task_id, title):
    if text is None:
        return False
    # Check if both id and title appear in the text (id can be '#ID' or 'ID')
    id_patterns = [fr"\b{task_id}\b", fr"#\s*{task_id}\b"]
    id_found = any(re.search(p, text) for p in id_patterns)
    title_found = (title in text)
    return bool(id_found and title_found)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_tasks_json": False,
        "tasks_json_is_array": False,
        "contains_expected_tasks": False,
        "parent_child_relations_correct": False,
        "integrations_blocked_with_notes": False,
        "status_distribution_ok": False,
        "assignments_present_ok": False,
        "has_backlog_copy": False,
        "backlog_copy_matches": False,
        "has_runbook": False,
        "runbook_contains_keywords": False,
        "has_assignment_summary": False,
        "assignment_summary_lists_per_agent": False,
    }

    # Paths
    tasks_json_path = os.path.join(output_dir, "tasks.json")
    backlog_copy_path = os.path.join(output_dir, "backlog_copy.csv")
    runbook_path = os.path.join(output_dir, "runbook.md")
    assignment_summary_path = os.path.join(output_dir, "assignment_summary.md")

    # Expected items
    expected_epics = [
        "Marketing Site Refresh",
        "Internal Dev Tooling",
    ]
    expected_subtasks = {
        "Marketing Site Refresh": [
            "Audit existing pages and analytics",
            "Create wireframes for homepage and pricing",
            "Implement responsive layout refactor",
        ],
        "Internal Dev Tooling": [
            "Set up lint-staged and pre-commit hooks",
            "Write initial ADR for mono-repo structure",
            "Create CLI scaffolding for project bootstrap",
        ],
    }
    expected_integrations = [
        "QA & Integration Sign-off for Marketing Site Refresh",
        "QA & Integration Sign-off for Internal Dev Tooling",
    ]
    expected_request_texts = expected_epics + expected_subtasks["Marketing Site Refresh"] + expected_subtasks["Internal Dev Tooling"] + expected_integrations

    # Check tasks.json
    tasks = None
    if os.path.isfile(tasks_json_path):
        checks["has_tasks_json"] = True
        tasks = load_json(tasks_json_path)
        if isinstance(tasks, list):
            checks["tasks_json_is_array"] = True

    # Proceed with tasks-dependent checks only if tasks is a list
    if isinstance(tasks, list):
        # contains_expected_tasks
        found_all = True
        for rt in expected_request_texts:
            matches = find_tasks_by_request(tasks, rt)
            if len(matches) == 0:
                found_all = False
                break
        checks["contains_expected_tasks"] = found_all

        # Parent-child relations
        # Map epic request_text -> id
        epics_ids = {}
        epics_found = True
        for epic in expected_epics:
            matches = find_tasks_by_request(tasks, epic)
            if not matches:
                epics_found = False
                break
            # Take the first match's id
            epic_id = to_int_or_none(matches[0].get("id"))
            if epic_id is None:
                epics_found = False
                break
            epics_ids[epic] = epic_id

        parent_child_ok = False
        if epics_found:
            parent_child_ok = True
            # For each subtask in each epic, ensure at least one matching task has parent_id == epic id
            for epic, sub_list in expected_subtasks.items():
                eid = epics_ids.get(epic)
                for sub in sub_list:
                    sub_matches = find_tasks_by_request(tasks, sub)
                    if not sub_matches:
                        parent_child_ok = False
                        break
                    # Check if any has correct parent_id
                    good = False
                    for sm in sub_matches:
                        pid = sm.get("parent_id")
                        pid_int = to_int_or_none(pid)
                        if pid_int == eid:
                            good = True
                            break
                    if not good:
                        parent_child_ok = False
                        break
                if not parent_child_ok:
                    break
        checks["parent_child_relations_correct"] = parent_child_ok

        # Integrations blocked with "BLOCKED:" in notes
        integ_ok = True
        for name in expected_integrations:
            imatches = find_tasks_by_request(tasks, name)
            if not imatches:
                integ_ok = False
                break
            # At least one of the matches must be blocked with notes containing "BLOCKED:"
            if not any(has_blocked_with_notes(t) for t in imatches):
                integ_ok = False
                break
        checks["integrations_blocked_with_notes"] = integ_ok

        # Status distribution: at least one done, at least one in_progress
        any_done = any(isinstance(t, dict) and t.get("status") == "done" for t in tasks)
        any_in_progress = any(isinstance(t, dict) and t.get("status") == "in_progress" for t in tasks)
        checks["status_distribution_ok"] = bool(any_done and any_in_progress)

        # Assignments presence: at least one alpha and one beta
        any_alpha = any(isinstance(t, dict) and t.get("assignee") == "alpha" for t in tasks)
        any_beta = any(isinstance(t, dict) and t.get("assignee") == "beta" for t in tasks)
        checks["assignments_present_ok"] = bool(any_alpha and any_beta)

    # backlog_copy.csv checks
    if os.path.isfile(backlog_copy_path):
        checks["has_backlog_copy"] = True
        text = read_text(backlog_copy_path)
        if text is not None:
            # Normalize lines: strip trailing spaces, ignore empty lines
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
            expected_lines = [
                "epic,subtask,priority",
                "Marketing Site Refresh,,7",
                "Marketing Site Refresh,Audit existing pages and analytics,6",
                "Marketing Site Refresh,Create wireframes for homepage and pricing,8",
                "Marketing Site Refresh,Implement responsive layout refactor,7",
                "Internal Dev Tooling,,5",
                "Internal Dev Tooling,Set up lint-staged and pre-commit hooks,6",
                "Internal Dev Tooling,Write initial ADR for mono-repo structure,5",
                "Internal Dev Tooling,Create CLI scaffolding for project bootstrap,7",
            ]
            # Order-insensitive equality with exact content and exact count
            if len(lines) == len(expected_lines) and set(lines) == set(expected_lines):
                checks["backlog_copy_matches"] = True

    # runbook.md checks
    runbook_text = None
    if os.path.isfile(runbook_path):
        checks["has_runbook"] = True
        runbook_text = read_text(runbook_path)
        if runbook_text is not None:
            low = runbook_text.lower()
            required_subs = [
                "task create",
                "task depend",
                "task claim",
                "task note",
                "task block",
                "task complete",
                "task export",
                "plan",
                "risks",
            ]
            if all(s in low for s in required_subs):
                checks["runbook_contains_keywords"] = True

    # assignment_summary.md checks
    assignment_text = None
    if os.path.isfile(assignment_summary_path):
        checks["has_assignment_summary"] = True
        assignment_text = read_text(assignment_summary_path)
        if assignment_text is not None and isinstance(tasks, list):
            low = assignment_text.lower()
            # Must include both agent names
            has_alpha_name = "alpha" in low
            has_beta_name = "beta" in low

            # Find any alpha and beta assigned tasks from tasks.json
            alpha_tasks = [(to_int_or_none(t.get("id")), t.get("request_text")) for t in tasks if isinstance(t, dict) and t.get("assignee") == "alpha"]
            beta_tasks = [(to_int_or_none(t.get("id")), t.get("request_text")) for t in tasks if isinstance(t, dict) and t.get("assignee") == "beta"]

            alpha_listed = False
            for tid, title in alpha_tasks:
                if tid is not None and isinstance(title, str):
                    if assignment_pair_in_text(assignment_text, tid, title):
                        alpha_listed = True
                        break

            beta_listed = False
            for tid, title in beta_tasks:
                if tid is not None and isinstance(title, str):
                    if assignment_pair_in_text(assignment_text, tid, title):
                        beta_listed = True
                        break

            if has_alpha_name and has_beta_name and alpha_listed and beta_listed:
                checks["assignment_summary_lists_per_agent"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward is 0.0 for explicit no-op baseline (no output dir or empty of required artifacts)
    # If none of the artifact presence checks are true, keep reward 0.0
    artifact_presence = any([
        checks["has_tasks_json"],
        checks["has_backlog_copy"],
        checks["has_runbook"],
        checks["has_assignment_summary"],
    ])
    if not artifact_presence:
        reward = 0.0

    # Bound reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()