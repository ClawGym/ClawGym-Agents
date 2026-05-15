import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_checkboxes(text):
    if not text:
        return 0
    # Matches lines like "- [ ] ..." with optional leading spaces
    pattern = re.compile(r'^\s*-\s*\[\s*\]\s*', re.MULTILINE)
    return len(pattern.findall(text))

def contains_in_order(text, tokens):
    """
    Case-insensitive ordered containment check.
    Returns True if each token appears after the previous one.
    """
    if text is None:
        return False
    s = text.lower()
    pos = -1
    for tok in tokens:
        t = tok.lower()
        idx = s.find(t, pos + 1)
        if idx == -1:
            return False
        pos = idx
    return True

def has_any_word(text, words):
    if text is None:
        return False
    s = text.lower()
    return any(w.lower() in s for w in words)

def has_word_regex(text, pattern):
    if text is None:
        return False
    return re.search(pattern, text, flags=re.IGNORECASE) is not None

def validate_stories_schema(obj):
    """
    Validate stories.json structure:
    - array length 3..6
    - each element is object with:
        * title: non-empty string
        * description: non-empty string
        * dependencies: list (may be empty)
        * acceptance_criteria: list of length >= 2 (prefer strings)
    """
    if not isinstance(obj, list):
        return (False, False)  # array_length_valid, schema_valid
    length_ok = 3 <= len(obj) <= 6
    if not length_ok:
        # Still check schema across existing items only if within bounds per spec
        pass
    all_ok = True
    for item in obj:
        if not isinstance(item, dict):
            all_ok = False
            break
        title = item.get("title")
        description = item.get("description")
        deps = item.get("dependencies")
        ac = item.get("acceptance_criteria")
        if not (isinstance(title, str) and title.strip()):
            all_ok = False
            break
        if not (isinstance(description, str) and description.strip()):
            all_ok = False
            break
        if not isinstance(deps, list):
            all_ok = False
            break
        if not (isinstance(ac, list) and len(ac) >= 2):
            all_ok = False
            break
        # If acceptance_criteria items are present, prefer strings
        for x in ac:
            if not isinstance(x, (str,)):
                all_ok = False
                break
        if not all_ok:
            break
    return (length_ok, all_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False)
    checks = {
        # task.txt checks
        "task_exists": False,
        "task_nonempty": False,
        "task_has_acceptance_section": False,
        "task_has_min_checkboxes": False,
        "task_has_rollout_plan": False,
        # stories.json checks
        "stories_exists": False,
        "stories_valid_json": False,
        "stories_array_length_valid": False,
        "stories_schema_valid": False,
        # runbook.md checks
        "runbook_exists": False,
        "runbook_has_pipeline_order": False,
        "runbook_mentions_status_resume_logs_dashboard": False,
        "runbook_mentions_polling_and_force_trigger": False,
        "runbook_no_brand_names": False,
        # acceptance_checklist.md checks
        "checklist_exists": False,
        "checklist_has_min_checkboxes": False,
    }

    # Paths
    task_path = os.path.join(output_dir, "task.txt")
    stories_path = os.path.join(output_dir, "stories.json")
    runbook_path = os.path.join(output_dir, "runbook.md")
    checklist_path = os.path.join(output_dir, "acceptance_checklist.md")

    # Validate task.txt
    if os.path.isfile(task_path):
        checks["task_exists"] = True
        task_text = read_text(task_path)
        if task_text is not None and task_text.strip():
            checks["task_nonempty"] = True
            # Acceptance Criteria section label (case-insensitive)
            if "acceptance criteria" in task_text.lower():
                checks["task_has_acceptance_section"] = True
            # At least 5 checkbox lines
            if count_checkboxes(task_text) >= 5:
                checks["task_has_min_checkboxes"] = True
            # Rollout plan presence: keywords "rollout" or "roll-out"
            if has_any_word(task_text, ["rollout", "roll-out"]):
                checks["task_has_rollout_plan"] = True

    # Validate stories.json
    if os.path.isfile(stories_path):
        checks["stories_exists"] = True
        try:
            with open(stories_path, "r", encoding="utf-8") as f:
                stories_obj = json.load(f)
            checks["stories_valid_json"] = True
            length_ok, schema_ok = validate_stories_schema(stories_obj)
            if length_ok:
                checks["stories_array_length_valid"] = True
            if schema_ok:
                checks["stories_schema_valid"] = True
        except Exception:
            # leave flags as initialized (False)
            pass

    # Validate runbook.md
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        runbook_text = read_text(runbook_path) or ""
        # Pipeline tokens in order: plan -> setup -> develop -> verify -> test -> PR -> review
        tokens = ["plan", "setup", "develop", "verify", "test", "PR", "review"]
        if contains_in_order(runbook_text, tokens):
            checks["runbook_has_pipeline_order"] = True
        # Mentions: status, resume, logs, dashboard
        needed = ["status", "resume", "logs", "dashboard"]
        if all(word.lower() in runbook_text.lower() for word in needed):
            checks["runbook_mentions_status_resume_logs_dashboard"] = True
        # Polling delays + force/trigger mention
        poll_regex = r"\bpoll\w*"  # poll, polling, poller
        has_polling = has_word_regex(runbook_text, poll_regex)
        has_force_or_trigger = any(w in runbook_text.lower() for w in ["force", "trigger"])
        if has_polling and has_force_or_trigger:
            checks["runbook_mentions_polling_and_force_trigger"] = True
        # Must NOT contain brand names "antfarm" or "openclaw" (case-insensitive)
        text_lc = runbook_text.lower()
        if ("antfarm" not in text_lc) and ("openclaw" not in text_lc):
            checks["runbook_no_brand_names"] = True

    # Validate acceptance_checklist.md
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        checklist_text = read_text(checklist_path)
        if checklist_text is not None:
            if count_checkboxes(checklist_text) >= 8:
                checks["checklist_has_min_checkboxes"] = True

    # Compute reward: proportion of passed checks; ensure 0.0 for no-op
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Print final result JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()