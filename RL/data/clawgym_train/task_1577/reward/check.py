import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_positive_int(x):
    return isinstance(x, int) and x > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) applied_actions.json checks
    applied_path = os.path.join(output_dir, "applied_actions.json")
    applied_obj = load_json_file(applied_path)
    checks["has_applied_actions_json"] = isinstance(applied_obj, dict)

    # Initialize dependent checks to False
    checks["applied_actions_keys_present"] = False
    checks["applied_actions_counts_match"] = False
    checks["applied_actions_errors_array"] = False
    checks["applied_actions_mapping_valid_ids"] = False

    if checks["has_applied_actions_json"]:
        required_keys = [
            "total_actions",
            "added_count",
            "updated_count",
            "marked_done_count",
            "reopened_count",
            "deleted_count",
            "errors",
            "add_index_to_id",
        ]
        if all(k in applied_obj for k in required_keys):
            checks["applied_actions_keys_present"] = True

            # Validate counts
            try:
                total_ok = applied_obj.get("total_actions") == 13
                added_ok = applied_obj.get("added_count") == 6
                updated_ok = applied_obj.get("updated_count") == 4
                done_ok = applied_obj.get("marked_done_count") == 1
                reopened_ok = applied_obj.get("reopened_count") == 1
                deleted_ok = applied_obj.get("deleted_count") == 1
                checks["applied_actions_counts_match"] = all([total_ok, added_ok, updated_ok, done_ok, reopened_ok, deleted_ok])
            except Exception:
                checks["applied_actions_counts_match"] = False

            # errors array
            errs = applied_obj.get("errors")
            checks["applied_actions_errors_array"] = isinstance(errs, list)

            # add_index_to_id mapping
            mapping = applied_obj.get("add_index_to_id")
            mapping_ok = isinstance(mapping, dict)
            if mapping_ok:
                required_refs = ["t1", "t2", "t3", "t4", "t5", "t6"]
                # Must contain required keys, values distinct positive integers
                has_all_keys = all(ref in mapping for ref in required_refs)
                values = [mapping.get(ref) for ref in required_refs]
                distinct = len(set(values)) == len(values)
                all_positive_ints = all(is_positive_int(v) for v in values)
                mapping_ok = has_all_keys and distinct and all_positive_ints
            checks["applied_actions_mapping_valid_ids"] = bool(mapping_ok)

    # 2) open_tasks_by_priority.json checks
    open_path = os.path.join(output_dir, "open_tasks_by_priority.json")
    open_obj = load_json_file(open_path)
    checks["has_open_tasks_json"] = isinstance(open_obj, dict)

    checks["open_tasks_length_4"] = False
    checks["open_tasks_structure_valid"] = False
    checks["open_tasks_status_open_all"] = False
    checks["open_tasks_titles_include"] = False
    checks["open_tasks_titles_exclude_renew_domain"] = False
    checks["open_tasks_sorted"] = False
    checks["open_tasks_cron_ids_for_reminders"] = False

    if checks["has_open_tasks_json"]:
        tasks = open_obj.get("tasks", None)
        if isinstance(tasks, list):
            checks["open_tasks_length_4"] = (len(tasks) == 4)

            # Structure validation
            expected_fields = {"id", "title", "priority", "status", "tags", "due_at", "remind_at", "cron_job_id"}
            structure_ok = True
            status_open_ok = True
            titles = []
            tuples_for_sort = []
            cron_ok_for_reminders = True
            for item in tasks:
                if not isinstance(item, dict) or set(item.keys()) != expected_fields:
                    structure_ok = False
                    break
                # collect titles
                titles.append(item.get("title"))
                # all status must be open
                if item.get("status") != "open":
                    status_open_ok = False
                # sorting tuple
                pr = item.get("priority")
                idv = item.get("id")
                tuples_for_sort.append((pr, idv))
                # cron id regex for tasks with remind_at not null
                remind_at = item.get("remind_at", None)
                if remind_at is not None:
                    cron = item.get("cron_job_id")
                    if not (isinstance(cron, str) and re.fullmatch(r"cron_[0-9]+", cron or "")):
                        cron_ok_for_reminders = False

            checks["open_tasks_structure_valid"] = structure_ok
            checks["open_tasks_status_open_all"] = status_open_ok

            # Titles include and exclude
            required_titles = {
                "Follow up with Acme re: Q3 SOW",
                "Book team offsite venue",
                "Fix flaky CI on api-tests",
                "Draft June newsletter",
            }
            titles_set = set(titles)
            checks["open_tasks_titles_include"] = required_titles.issubset(titles_set)
            checks["open_tasks_titles_exclude_renew_domain"] = ("Renew domain for dev blog" not in titles_set)

            # Sorted by (priority ASC, id ASC)
            sorted_ok = True
            for i in range(1, len(tuples_for_sort)):
                if tuples_for_sort[i] < tuples_for_sort[i - 1]:
                    sorted_ok = False
                    break
            checks["open_tasks_sorted"] = sorted_ok

            checks["open_tasks_cron_ids_for_reminders"] = cron_ok_for_reminders

    # 3) stale_candidates.json checks
    stale_path = os.path.join(output_dir, "stale_candidates.json")
    stale_obj = load_json_file(stale_path)
    checks["has_stale_candidates_json"] = isinstance(stale_obj, dict)

    checks["stale_candidates_ok_true"] = False
    checks["stale_candidates_policy_correct"] = False
    checks["stale_candidates_count_integer"] = False
    checks["stale_candidates_tasks_array"] = False

    if checks["has_stale_candidates_json"]:
        checks["stale_candidates_ok_true"] = stale_obj.get("ok") is True
        policy = stale_obj.get("policy")
        if isinstance(policy, dict):
            checks["stale_candidates_policy_correct"] = (policy.get("p3_days") == 30 and policy.get("p2_days") == 45)
        count_val = stale_obj.get("count")
        checks["stale_candidates_count_integer"] = isinstance(count_val, int) and count_val >= 0
        checks["stale_candidates_tasks_array"] = isinstance(stale_obj.get("tasks"), list)

    # 4) notes.md checks
    notes_path = os.path.join(output_dir, "notes.md")
    notes_text = read_text(notes_path)
    checks["has_notes_md"] = isinstance(notes_text, str)

    checks["notes_headings_once"] = False
    checks["notes_contains_priority_ref"] = False
    checks["notes_contains_tag_word"] = False

    if checks["has_notes_md"]:
        # Count exact substring occurrences (case-sensitive) for headings
        count_overview = notes_text.count("Overview")
        count_reminders = notes_text.count("Reminders Scheduled")
        count_stale = notes_text.count("Stale Review Plan")
        checks["notes_headings_once"] = (count_overview == 1 and count_reminders == 1 and count_stale == 1)

        # Priority mention
        has_p1 = "P1" in notes_text
        has_priority1 = "priority 1" in notes_text.lower()
        checks["notes_contains_priority_ref"] = has_p1 or has_priority1

        # Tag words (case-insensitive)
        lower = notes_text.lower()
        checks["notes_contains_tag_word"] = any(w in lower for w in ["sales", "ops", "engineering", "marketing"])

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no output files at all, force reward = 0.0
    any_output = any(os.path.exists(os.path.join(output_dir, p)) for p in [
        "applied_actions.json",
        "open_tasks_by_priority.json",
        "stale_candidates.json",
        "notes.md",
    ])
    if not any_output:
        reward = 0.0

    # Print single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()