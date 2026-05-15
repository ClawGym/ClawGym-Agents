import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "actions_json_exists": False,
        "actions_json_valid": False,
        "actions_top_level_schema_ok": False,
        "action_items_schema_valid": False,
        "actions_no_disallowed_keys": False,
        "actions_targets_valid": False,
        "actions_counts_create_ge5": False,
        "actions_counts_has_edit_time": False,
        "actions_counts_has_edit_title": False,
        "actions_counts_has_complete": False,
        "actions_counts_has_delete": False,
        "times_all_whens_match_allowed_formats": False,
        "times_has_tomorrow_at": False,
        "times_has_in_relative": False,
        "times_has_iso": False,
        "times_has_next_weekday": False,
        "times_no_next_weekday_at": False,
        "runbook_exists": False,
        "runbook_has_keywords": False,
        "notes_exists": False,
        "notes_has_keywords_and_lowercase": False,
    }

    actions_path = os.path.join(output_dir, "actions.json")
    runbook_path = os.path.join(output_dir, "runbook.txt")
    notes_path = os.path.join(output_dir, "notes.md")

    # Regex patterns for time validation
    re_in_rel = re.compile(r'^in [0-9]+ (minute|minutes|hour|hours|day|days)$')
    re_named = re.compile(r'^(later today|later|this afternoon|tonight|tomorrow)$')
    re_tomorrow_at = re.compile(r'^tomorrow at ([0-9]{1,2})(:[0-9]{2})?(am|pm)$')
    re_next_weekday = re.compile(r'^(next (monday|tuesday|wednesday|thursday|friday|saturday|sunday))$')
    re_iso = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$')
    re_disallowed = re.compile(r'^next (monday|tuesday|wednesday|thursday|friday|saturday|sunday) at\b')

    def classify_when(w):
        s = (w or "")
        s = s.strip()
        # Disallowed check
        if re_disallowed.search(s):
            return "disallowed"
        if re_in_rel.match(s):
            return "in_rel"
        if re_named.match(s):
            return "named"
        if re_tomorrow_at.match(s):
            return "tomorrow_at"
        if re_next_weekday.match(s):
            return "next_weekday"
        if re_iso.match(s):
            return "iso"
        return None

    # Validate actions.json
    if os.path.isfile(actions_path):
        checks["actions_json_exists"] = True
        ok, data = load_json_file(actions_path)
        if ok and isinstance(data, dict):
            checks["actions_json_valid"] = True
            # Top-level must be exactly {"actions": [...]}
            if set(data.keys()) == {"actions"} and isinstance(data.get("actions"), list):
                checks["actions_top_level_schema_ok"] = True

                actions = data["actions"]

                # Counters and flags
                count_create = 0
                count_edit_time = 0
                count_edit_title = 0
                count_complete = 0
                count_delete = 0

                # Per-action schema validation
                all_actions_schema_ok = True
                any_action_seen = False

                # Disallowed keys anywhere in action dict (including nested target)
                disallowed_keys_absent = True

                # Target validation
                all_targets_valid = True
                any_target_seen = False

                # Time validation and variety
                seen_when_count = 0
                all_whens_valid = True
                has_tomorrow_at = False
                has_in_rel = False
                has_iso = False
                has_next_weekday = False
                no_disallowed_combo = True

                allowed_actions = {"create", "edit_time", "edit_title", "complete", "delete"}

                for item in actions:
                    if not isinstance(item, dict):
                        all_actions_schema_ok = False
                        continue
                    any_action_seen = True

                    # Check disallowed keys anywhere inside this action object
                    def contains_disallowed_keys(obj):
                        if isinstance(obj, dict):
                            for k, v in obj.items():
                                if k in ("list", "recurring"):
                                    return True
                                if isinstance(v, (dict, list)):
                                    if contains_disallowed_keys(v):
                                        return True
                        elif isinstance(obj, list):
                            for elem in obj:
                                if contains_disallowed_keys(elem):
                                    return True
                        return False

                    if contains_disallowed_keys(item):
                        disallowed_keys_absent = False

                    action_type = item.get("action")
                    if not isinstance(action_type, str) or action_type not in allowed_actions:
                        all_actions_schema_ok = False
                        continue

                    # Define allowed keys per action
                    if action_type == "create":
                        expected_keys = {"action", "title", "when"}
                    elif action_type == "edit_time":
                        expected_keys = {"action", "target", "when"}
                    elif action_type == "edit_title":
                        expected_keys = {"action", "target", "new_title"}
                    elif action_type == "complete":
                        expected_keys = {"action", "target"}
                    elif action_type == "delete":
                        expected_keys = {"action", "target"}
                    else:
                        expected_keys = set()

                    # Enforce no extra or missing keys
                    if set(item.keys()) != expected_keys:
                        all_actions_schema_ok = False
                        continue

                    # Validate fields based on action
                    if action_type == "create":
                        title = item.get("title")
                        when = item.get("when")
                        if not (isinstance(title, str) and title.strip()):
                            all_actions_schema_ok = False
                        if not isinstance(when, str):
                            all_actions_schema_ok = False
                        else:
                            seen_when_count += 1
                            cls = classify_when(when)
                            if cls is None or cls == "disallowed":
                                all_whens_valid = False
                            if cls == "disallowed":
                                no_disallowed_combo = False
                            if cls == "tomorrow_at":
                                has_tomorrow_at = True
                            if cls == "in_rel":
                                has_in_rel = True
                            if cls == "iso":
                                has_iso = True
                            if cls == "next_weekday":
                                has_next_weekday = True
                        count_create += 1

                    elif action_type == "edit_time":
                        target = item.get("target")
                        when = item.get("when")
                        if not isinstance(target, dict) or set(target.keys()) != {"title_contains"}:
                            all_actions_schema_ok = False
                        else:
                            any_target_seen = True
                            tc = target.get("title_contains")
                            if not (isinstance(tc, str) and tc.strip()):
                                all_targets_valid = False
                        if not isinstance(when, str):
                            all_actions_schema_ok = False
                        else:
                            seen_when_count += 1
                            cls = classify_when(when)
                            if cls is None or cls == "disallowed":
                                all_whens_valid = False
                            if cls == "disallowed":
                                no_disallowed_combo = False
                            if cls == "tomorrow_at":
                                has_tomorrow_at = True
                            if cls == "in_rel":
                                has_in_rel = True
                            if cls == "iso":
                                has_iso = True
                            if cls == "next_weekday":
                                has_next_weekday = True
                        count_edit_time += 1

                    elif action_type == "edit_title":
                        target = item.get("target")
                        new_title = item.get("new_title")
                        if not isinstance(target, dict) or set(target.keys()) != {"title_contains"}:
                            all_actions_schema_ok = False
                        else:
                            any_target_seen = True
                            tc = target.get("title_contains")
                            if not (isinstance(tc, str) and tc.strip()):
                                all_targets_valid = False
                        if not (isinstance(new_title, str) and new_title.strip()):
                            all_actions_schema_ok = False
                        count_edit_title += 1

                    elif action_type == "complete":
                        target = item.get("target")
                        if not isinstance(target, dict) or set(target.keys()) != {"title_contains"}:
                            all_actions_schema_ok = False
                        else:
                            any_target_seen = True
                            tc = target.get("title_contains")
                            if not (isinstance(tc, str) and tc.strip()):
                                all_targets_valid = False
                        count_complete += 1

                    elif action_type == "delete":
                        target = item.get("target")
                        if not isinstance(target, dict) or set(target.keys()) != {"title_contains"}:
                            all_actions_schema_ok = False
                        else:
                            any_target_seen = True
                            tc = target.get("title_contains")
                            if not (isinstance(tc, str) and tc.strip()):
                                all_targets_valid = False
                        count_delete += 1

                # Update checks based on gathered info
                if any_action_seen and all_actions_schema_ok:
                    checks["action_items_schema_valid"] = True
                if any_action_seen and disallowed_keys_absent:
                    checks["actions_no_disallowed_keys"] = True
                if any_target_seen and all_targets_valid:
                    checks["actions_targets_valid"] = True

                # Counts
                if count_create >= 5:
                    checks["actions_counts_create_ge5"] = True
                if count_edit_time >= 1:
                    checks["actions_counts_has_edit_time"] = True
                if count_edit_title >= 1:
                    checks["actions_counts_has_edit_title"] = True
                if count_complete >= 1:
                    checks["actions_counts_has_complete"] = True
                if count_delete >= 1:
                    checks["actions_counts_has_delete"] = True

                # Time validations and variety
                if seen_when_count > 0 and all_whens_valid:
                    checks["times_all_whens_match_allowed_formats"] = True
                if seen_when_count > 0 and no_disallowed_combo:
                    checks["times_no_next_weekday_at"] = True
                if has_tomorrow_at:
                    checks["times_has_tomorrow_at"] = True
                if has_in_rel:
                    checks["times_has_in_relative"] = True
                if has_iso:
                    checks["times_has_iso"] = True
                if has_next_weekday:
                    checks["times_has_next_weekday"] = True

    # Validate runbook.txt
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        try:
            content = open(runbook_path, "r", encoding="utf-8").read().lower()
            needed = ["create", "reschedule", "complete", "delete"]
            has_keywords = all(word in content for word in needed)
            has_title_ref = "title" in content
            if has_keywords and has_title_ref:
                checks["runbook_has_keywords"] = True
        except Exception:
            pass

    # Validate notes.md
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            content = open(notes_path, "r", encoding="utf-8").read().lower()
            has_any_keyword = any(k in content for k in ["assumption", "conflict", "timezone"])
            has_lowercase = "lowercase" in content
            if has_any_keyword and has_lowercase:
                checks["notes_has_keywords_and_lowercase"] = True
        except Exception:
            pass

    success = all(checks.values())
    reward = 1.0 if success else 0.0
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()