import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return [line.rstrip("\n") for line in f.readlines()]
    except Exception:
        return []

def parse_validation_json(path, required_actions):
    """
    Returns (valid_json: bool, per_action_presence: dict)
    per_action_presence maps action name -> bool
    """
    presence = {a: False for a in required_actions}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid = True
    except Exception:
        return False, presence

    def any_true_bool_field(d):
        # Prefer conventional names first
        for key in ("present", "appears", "found", "exists", "included"):
            if isinstance(d, dict) and isinstance(d.get(key), bool) and d.get(key) is True:
                return True
        # Fallback: any boolean True in dict
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, bool) and v is True:
                    return True
        return False

    # Object case: keys might be action names or entries
    if isinstance(data, dict):
        # Direct key mapping
        for action in required_actions:
            if action in data:
                val = data[action]
                if isinstance(val, bool):
                    presence[action] = val is True
                elif isinstance(val, dict):
                    presence[action] = any_true_bool_field(val)
            else:
                # Search values for objects with action/name field
                found = False
                for v in data.values():
                    if isinstance(v, dict):
                        name = v.get("action") or v.get("name") or v.get("action_name")
                        if name == action:
                            if isinstance(v.get("present"), bool):
                                presence[action] = v.get("present") is True
                            else:
                                presence[action] = any_true_bool_field(v)
                            found = True
                            break
                if not found:
                    presence[action] = False
    elif isinstance(data, list):
        for action in required_actions:
            matched_items = [item for item in data if isinstance(item, dict) and (item.get("action") == action or item.get("name") == action or item.get("action_name") == action)]
            if matched_items:
                # If multiple, any with a true presence wins
                ok = False
                for item in matched_items:
                    if isinstance(item.get("present"), bool):
                        if item.get("present") is True:
                            ok = True
                            break
                    elif any_true_bool_field(item):
                        ok = True
                        break
                presence[action] = ok
            else:
                # If array contains raw strings, accept that too
                if any(isinstance(item, str) and item == action for item in data):
                    presence[action] = True
                else:
                    presence[action] = False
    else:
        # Unsupported structure
        pass

    return True, presence

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # workflow.applescript.txt checks
        "workflow_exists": False,
        "workflow_nonempty": False,
        "workflow_contains_tell_automator": False,
        "workflow_contains_make_new_workflow": False,
        "workflow_contains_execute_wf": False,
        "workflow_contains_get_selected": False,
        "workflow_contains_filter": False,
        "workflow_contains_rename": False,
        "workflow_contains_move": False,
        "workflow_contains_add_word": False,

        # runbook.md checks
        "runbook_exists": False,
        "runbook_nonempty": False,
        "runbook_has_prerun_section": False,
        "runbook_has_two_step_line": False,
        "runbook_has_final_check_line": False,
        "runbook_has_postrun_section": False,

        # test_input.txt checks
        "test_input_exists": False,
        "test_input_line_count_ok": False,

        # validation.json checks
        "validation_exists": False,
        "validation_json_valid": False,
        "validation_all_actions_present_true": False,
    }

    # Paths
    wf_path = os.path.join(output_dir, "workflow.applescript.txt")
    runbook_path = os.path.join(output_dir, "runbook.md")
    test_input_path = os.path.join(output_dir, "test_input.txt")
    validation_path = os.path.join(output_dir, "validation.json")

    # 1) workflow.applescript.txt
    if os.path.isfile(wf_path):
        checks["workflow_exists"] = True
        content = read_text(wf_path)
        if content.strip():
            checks["workflow_nonempty"] = True
            # Required literal substrings (case-sensitive)
            if 'tell application "Automator"' in content:
                checks["workflow_contains_tell_automator"] = True
            if "make new workflow" in content:
                checks["workflow_contains_make_new_workflow"] = True
            if "execute wf" in content:
                checks["workflow_contains_execute_wf"] = True
            if "Get Selected Finder Items" in content:
                checks["workflow_contains_get_selected"] = True
            if "Filter Finder Items" in content:
                checks["workflow_contains_filter"] = True
            if "Rename Finder Items" in content:
                checks["workflow_contains_rename"] = True
            if "Move Finder Items" in content:
                checks["workflow_contains_move"] = True
            # Evidence of adding actions individually
            # Presence of the word "add" is sufficient per requirements.
            if "add" in content:
                checks["workflow_contains_add_word"] = True

    # 2) runbook.md
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        rcontent = read_text(runbook_path)
        if rcontent.strip():
            checks["runbook_nonempty"] = True
            # Pre-run checklist section (case-insensitive)
            rc_low = rcontent.lower()
            if ("pre-run" in rc_low) or ("preflight" in rc_low) or ("checklist" in rc_low):
                checks["runbook_has_prerun_section"] = True

            # Two-step confirmation wording
            # Must include a line containing "This run will" and "Confirm this exact target."
            # (both phrases in the same or consecutive lines)
            lines = read_lines(runbook_path)
            # Also a line containing "Final check: proceed"
            has_final_check = any("Final check: proceed" in ln for ln in lines)
            if has_final_check:
                checks["runbook_has_final_check_line"] = True

            has_two_step = False
            for i, ln in enumerate(lines):
                has_this_run = ("This run will" in ln)
                has_confirm = ("Confirm this exact target." in ln)
                if has_this_run and has_confirm:
                    has_two_step = True
                    break
                if has_this_run:
                    # Check next line for confirm phrase
                    if i + 1 < len(lines) and "Confirm this exact target." in lines[i + 1]:
                        has_two_step = True
                        break
                if has_confirm:
                    # Check previous line for "This run will"
                    if i - 1 >= 0 and "This run will" in lines[i - 1]:
                        has_two_step = True
                        break
            if has_two_step:
                checks["runbook_has_two_step_line"] = True

            # Post-run verification section
            if ("post-run" in rc_low) or ("verification" in rc_low):
                checks["runbook_has_postrun_section"] = True

    # 3) test_input.txt
    if os.path.isfile(test_input_path):
        checks["test_input_exists"] = True
        tlines = [ln for ln in read_lines(test_input_path) if ln.strip() != ""]
        if 2 <= len(tlines) <= 10:
            checks["test_input_line_count_ok"] = True

    # 4) validation.json
    required_actions = [
        "Get Selected Finder Items",
        "Filter Finder Items",
        "Rename Finder Items",
        "Move Finder Items",
    ]
    if os.path.isfile(validation_path):
        checks["validation_exists"] = True
        valid_json, per_action = parse_validation_json(validation_path, required_actions)
        if valid_json:
            checks["validation_json_valid"] = True
            if all(per_action.get(a, False) is True for a in required_actions):
                checks["validation_all_actions_present_true"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline already satisfied by the calculation: if nothing exists, reward stays 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()