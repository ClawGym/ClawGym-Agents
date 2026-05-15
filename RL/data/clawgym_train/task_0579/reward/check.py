import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f], None
    except Exception as e:
        return None, str(e)

def normalize_percent(value):
    # Converts progress to whole-number percentage string like "85%"
    try:
        if isinstance(value, (int, float)):
            v = float(value)
            if 0.0 <= v <= 1.0:
                pct = int(round(v * 100))
            else:
                pct = int(round(v))
            return f"{pct}%"
        # If string, try to parse float
        if isinstance(value, str):
            v = float(value.strip())
            if 0.0 <= v <= 1.0:
                pct = int(round(v * 100))
            else:
                pct = int(round(v))
            return f"{pct}%"
    except Exception:
        pass
    return None

def contains_case_insensitive(haystack, needle):
    return needle.lower() in haystack.lower()

def find_line_matching(lines, predicate):
    for line in lines:
        if predicate(line):
            return line
    return None

def json_equal(a, b):
    # Compare JSON structures by value
    try:
        return a == b
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_actions_json": False,
        "has_transcript_md": False,
        "has_final_state_json": False,
        "list_before_matches": False,
        "actions_include_list": False,
        "actions_include_clarify_2_4": False,
        "actions_include_kill_2": False,
        "actions_include_info_3": False,
        "actions_include_kill_all_last": False,
        "list_after_empty": False,
        "final_state_empty": False,
        "transcript_has_listing": False,
        "transcript_has_clarify_2_4_with_labels": False,
        "transcript_has_kill2_confirmation": False,
        "transcript_has_progress_for_3": False,
        "transcript_has_all_stopped": False,
    }

    tasks_path = os.path.join(input_dir, "tasks.json")
    requests_path = os.path.join(input_dir, "requests.jsonl")
    actions_path = os.path.join(output_dir, "actions.json")
    transcript_path = os.path.join(output_dir, "transcript.md")
    final_state_path = os.path.join(output_dir, "final_state.json")

    # Load input tasks
    tasks, tasks_err = read_json(tasks_path)
    if not isinstance(tasks, list):
        tasks = []
    task_count = len(tasks)
    labels = [t.get("label", "") for t in tasks]
    percents = [normalize_percent(t.get("progress", None)) for t in tasks]

    # Required outputs exist?
    actions_json, actions_err = read_json(actions_path)
    if actions_err is None and isinstance(actions_json, dict):
        checks["has_actions_json"] = True

    transcript_lines, transcript_err = read_text_lines(transcript_path)
    if transcript_err is None and isinstance(transcript_lines, list):
        # must contain at least 5 lines
        if len([ln for ln in transcript_lines if ln.strip() != ""]) >= 5:
            checks["has_transcript_md"] = True

    final_state_json, final_state_err = read_json(final_state_path)
    if final_state_err is None and isinstance(final_state_json, list):
        checks["has_final_state_json"] = True

    # If any required artifact missing, baseline reward must be 0.0
    required_present = checks["has_actions_json"] and checks["has_transcript_md"] and checks["has_final_state_json"]

    # Perform actions.json checks if available
    if checks["has_actions_json"]:
        # list_before identical to input/tasks.json
        list_before = actions_json.get("list_before")
        if list_before is not None and json_equal(list_before, tasks):
            checks["list_before_matches"] = True

        actions = actions_json.get("actions")
        if isinstance(actions, list) and len(actions) > 0:
            # contains a "list" action
            if any(isinstance(a, dict) and a.get("type") == "list" for a in actions):
                checks["actions_include_list"] = True

            # clarify action referencing #2 and #4 by number and label
            # Only applicable if we have at least 4 tasks
            if task_count >= 4:
                label2 = labels[1] if len(labels) >= 2 else ""
                label4 = labels[3] if len(labels) >= 4 else ""
                clarify_ok = False
                for a in actions:
                    if not isinstance(a, dict) or a.get("type") != "clarify":
                        continue
                    options_key = None
                    for k in ("options", "candidates", "choices", "targets"):
                        if isinstance(a.get(k), list):
                            options_key = k
                            break
                    if options_key is None:
                        continue
                    opts = a.get(options_key, [])
                    found2 = any(
                        isinstance(o, dict) and o.get("number") == 2 and str(o.get("label", "")) == str(label2)
                        for o in opts
                    )
                    found4 = any(
                        isinstance(o, dict) and o.get("number") == 4 and str(o.get("label", "")) == str(label4)
                        for o in opts
                    )
                    if found2 and found4:
                        clarify_ok = True
                        break
                if clarify_ok:
                    checks["actions_include_clarify_2_4"] = True

            # kill action targeting #2 with correct label
            if task_count >= 2:
                label2 = labels[1]
                kill2_ok = any(
                    isinstance(a, dict) and a.get("type") == "kill" and a.get("number") == 2 and str(a.get("label", "")) == str(label2)
                    for a in actions
                )
                if kill2_ok:
                    checks["actions_include_kill_2"] = True

            # info (or progress) action for #3 with correct label
            if task_count >= 3:
                label3 = labels[2]
                info3_ok = any(
                    isinstance(a, dict)
                    and a.get("type") in ("info", "progress")
                    and a.get("number") == 3
                    and str(a.get("label", "")) == str(label3)
                    for a in actions
                )
                if info3_ok:
                    checks["actions_include_info_3"] = True

            # kill_all is last
            if len(actions) >= 1:
                last = actions[-1]
                if isinstance(last, dict) and last.get("type") == "kill_all":
                    checks["actions_include_kill_all_last"] = True

        # list_after must be an empty array if kill_all at end
        list_after = actions_json.get("list_after")
        if isinstance(list_after, list) and len(list_after) == 0:
            checks["list_after_empty"] = True

    # final_state.json must be empty list
    if checks["has_final_state_json"]:
        if isinstance(final_state_json, list) and len(final_state_json) == 0:
            checks["final_state_empty"] = True

    # transcript checks
    if checks["has_transcript_md"] and task_count >= 1:
        # Build expected listing tokens
        # Must mention "<N> tasks" and include each "#i", label, percent
        # Find a line mentioning "<N> tasks"
        def listing_pred(line):
            # contains "{N} tasks" case-insensitive
            return contains_case_insensitive(line, f"{task_count} tasks")
        listing_line = find_line_matching(transcript_lines, listing_pred)

        if listing_line is not None:
            listing_ok = True
            for idx in range(task_count):
                num = idx + 1
                label = labels[idx] if idx < len(labels) else ""
                pct = percents[idx] if idx < len(percents) else None
                # Require "#<num>", label, and "<pct>%"
                if pct is None:
                    listing_ok = False
                    break
                if not contains_case_insensitive(listing_line, f"#{num}"):
                    listing_ok = False
                    break
                if not contains_case_insensitive(listing_line, str(label)):
                    listing_ok = False
                    break
                if not contains_case_insensitive(listing_line, pct):
                    listing_ok = False
                    break
            if listing_ok:
                checks["transcript_has_listing"] = True

        # Clarify line: asks to confirm #2 or #4, includes both labels
        if task_count >= 4:
            label2 = labels[1]
            label4 = labels[3]
            def clarify_pred(line):
                has_nums = ("#2" in line) and ("#4" in line)
                has_labels = contains_case_insensitive(line, str(label2)) and contains_case_insensitive(line, str(label4))
                # look for interrogative or confirm keyword to ensure it is a clarification style
                has_prompt = re.search(r"\b(confirm|which|choose|please)\b", line, flags=re.IGNORECASE) is not None or "?" in line
                return has_nums and has_labels and has_prompt
            clarify_line = find_line_matching(transcript_lines, clarify_pred)
            if clarify_line is not None:
                checks["transcript_has_clarify_2_4_with_labels"] = True

        # Kill #2 confirmation line
        if task_count >= 2:
            label2 = labels[1]
            def kill2_pred(line):
                # Accept "Stopped/Killed/Ended task #2"
                has_ref = re.search(r"\b(stopped|killed|ended)\b\s+task\s+#?2", line, flags=re.IGNORECASE) is not None
                has_label = contains_case_insensitive(line, str(label2))
                return has_ref and has_label
            if find_line_matching(transcript_lines, kill2_pred) is not None:
                checks["transcript_has_kill2_confirmation"] = True

        # Progress for #3 line
        if task_count >= 3:
            pct3 = percents[2]
            def info3_pred(line):
                has_num = "#3" in line
                has_pct = pct3 is not None and contains_case_insensitive(line, pct3)
                return has_num and has_pct
            if find_line_matching(transcript_lines, info3_pred) is not None:
                checks["transcript_has_progress_for_3"] = True

        # Final all-stopped line
        def all_stopped_pred(line):
            # look for "all ... background ... tasks ... stopped"
            return re.search(r"\ball\b.*\bbackground\b.*\btasks?\b.*\bstopped\b", line, flags=re.IGNORECASE) is not None
        if find_line_matching(transcript_lines, all_stopped_pred) is not None:
            checks["transcript_has_all_stopped"] = True

    # Compute reward
    # If any required artifact missing → reward 0.0
    if not required_present:
        reward = 0.0
    else        :
        # Proportion of checks passed (exclude the three existence checks from denominator since required_present already ensures them)
        scored_keys = [
            "list_before_matches",
            "actions_include_list",
            "actions_include_clarify_2_4",
            "actions_include_kill_2",
            "actions_include_info_3",
            "actions_include_kill_all_last",
            "list_after_empty",
            "final_state_empty",
            "transcript_has_listing",
            "transcript_has_clarify_2_4_with_labels",
            "transcript_has_kill2_confirmation",
            "transcript_has_progress_for_3",
            "transcript_has_all_stopped",
        ]
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        total = len(scored_keys)
        reward = passed / total if total > 0 else 0.0

    # Prepare result JSON
    result = {"reward": round(reward, 6)}
    # Include individual checks in output
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()