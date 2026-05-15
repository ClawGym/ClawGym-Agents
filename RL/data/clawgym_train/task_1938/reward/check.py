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

def line_map_by_label(lines, labels):
    out = {}
    for label in labels:
        out[label] = None
    for ln in lines:
        for label in labels:
            if ln.startswith(label):
                out[label] = ln[len(label):].strip()
    return out

def is_timestamp_like(s):
    if not isinstance(s, str):
        return False
    # Accept ISO-like or "YYYY-MM-DD HH:MM"
    # Use a relaxed regex that captures common patterns
    pattern = r"\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}"
    return re.search(pattern, s) is not None

def contains_section_heading(lines, heading):
    # Case-insensitive: a line starting with the heading word(s)
    h = heading.lower()
    for ln in lines:
        if ln.strip().lower().startswith(h):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Plan checks
        "has_plan_json": False,
        "plan_valid_json": False,
        "plan_has_tasks_array": False,
        "plan_tasks_len_ge_3": False,
        "plan_tasks_schema": False,
        "plan_has_next_steps_array": False,
        "plan_next_steps_len_ge_1": False,
        # Snapshot checks
        "has_task_snapshot": False,
        "snapshot_has_task_id_nonempty": False,
        "snapshot_has_description_nonempty": False,
        "snapshot_status_present_valid": False,
        "snapshot_status_completed": False,
        "snapshot_has_requested_timestamp": False,
        "snapshot_has_updated_timestamp": False,
        "snapshot_has_background_line_valid": False,
        "snapshot_has_notes_nonempty": False,
        "snapshot_has_result_nonempty": False,
        "snapshot_within_line_limit": False,
        "snapshot_within_size_limit": False,
        # Status report checks
        "has_status_report": False,
        "status_report_has_two_progress_updates": False,
        "status_report_has_outcome_section": False,
        "status_report_has_next_steps_section": False,
        # Progress log checks
        "has_progress_log": False,
        "progress_log_has_min_two_lines": False,
        "progress_log_lines_valid": False,
    }

    # 1) plan.json checks
    plan_path = os.path.join(output_dir, "plan.json")
    if os.path.isfile(plan_path):
        checks["has_plan_json"] = True
        plan_data = load_json(plan_path)
        if isinstance(plan_data, dict):
            checks["plan_valid_json"] = True
            # tasks
            tasks = plan_data.get("tasks")
            if isinstance(tasks, list):
                checks["plan_has_tasks_array"] = True
                if len(tasks) >= 3:
                    checks["plan_tasks_len_ge_3"] = True
                # Validate schema for each task
                schema_ok = True
                for t in tasks:
                    if not isinstance(t, dict):
                        schema_ok = False
                        break
                    if "title" not in t or "estimate" not in t or "dependencies" not in t or "done" not in t:
                        schema_ok = False
                        break
                    if not isinstance(t["title"], str):
                        schema_ok = False
                        break
                    if not isinstance(t["estimate"], str):
                        schema_ok = False
                        break
                    if not isinstance(t["dependencies"], list):
                        schema_ok = False
                        break
                    if not isinstance(t["done"], bool):
                        schema_ok = False
                        break
                if schema_ok:
                    checks["plan_tasks_schema"] = True
            # next_steps
            next_steps = plan_data.get("next_steps")
            if isinstance(next_steps, list):
                checks["plan_has_next_steps_array"] = True
                if len(next_steps) >= 1:
                    checks["plan_next_steps_len_ge_1"] = True

    # 2) task_state_snapshot.md checks
    snapshot_path = os.path.join(output_dir, "task_state_snapshot.md")
    if os.path.isfile(snapshot_path):
        checks["has_task_snapshot"] = True
        content = read_text(snapshot_path) or ""
        # Size limit
        if len(content.encode("utf-8")) <= 2048:
            checks["snapshot_within_size_limit"] = True
        lines = [ln.rstrip("\n") for ln in content.splitlines()]
        if len(lines) <= 50:
            checks["snapshot_within_line_limit"] = True

        labels = [
            "Task ID:",
            "Description:",
            "Status:",
            "Requested:",
            "Updated:",
            "Background:",
            "Notes:",
            "Result:",
        ]
        lm = line_map_by_label(lines, labels)

        # Task ID
        if lm["Task ID:"] and lm["Task ID:"].strip():
            checks["snapshot_has_task_id_nonempty"] = True
        # Description
        if lm["Description:"] and lm["Description:"].strip():
            checks["snapshot_has_description_nonempty"] = True
        # Status
        status_val = (lm["Status:"] or "").strip()
        valid_statuses = {"In-Progress", "Completed", "Failed", "Paused"}
        if status_val in valid_statuses:
            checks["snapshot_status_present_valid"] = True
            if status_val == "Completed":
                checks["snapshot_status_completed"] = True
        # Requested timestamp
        if lm["Requested:"] and is_timestamp_like(lm["Requested:"]):
            checks["snapshot_has_requested_timestamp"] = True
        # Updated timestamp
        if lm["Updated:"] and is_timestamp_like(lm["Updated:"]):
            checks["snapshot_has_updated_timestamp"] = True
        # Background
        bg = lm["Background:"]
        if isinstance(bg, str):
            bg_str = bg.strip()
            if bg_str == "none":
                checks["snapshot_has_background_line_valid"] = True
            else:
                # Accept if there is some descriptor content
                # Require at least some marker of structure
                structured = ("PID" in bg_str) or (" on " in bg_str) or ("—" in bg_str) or ("-" in bg_str)
                if structured and len(bg_str) > 3:
                    checks["snapshot_has_background_line_valid"] = True
        # Notes
        if lm["Notes:"] and lm["Notes:"].strip():
            checks["snapshot_has_notes_nonempty"] = True
        # Result
        if lm["Result:"] and lm["Result:"].strip():
            checks["snapshot_has_result_nonempty"] = True

    # 3) status_report.md checks
    status_report_path = os.path.join(output_dir, "status_report.md")
    if os.path.isfile(status_report_path):
        checks["has_status_report"] = True
        report_text = read_text(status_report_path) or ""
        # Count exact substring "Progress Update"
        count_progress_update = report_text.count("Progress Update")
        if count_progress_update >= 2:
            checks["status_report_has_two_progress_updates"] = True
        report_lines = [ln.rstrip("\n") for ln in report_text.splitlines()]
        if contains_section_heading(report_lines, "Outcome"):
            checks["status_report_has_outcome_section"] = True
        if contains_section_heading(report_lines, "Next Steps"):
            checks["status_report_has_next_steps_section"] = True

    # 4) progress_log.jsonl checks
    progress_log_path = os.path.join(output_dir, "progress_log.jsonl")
    if os.path.isfile(progress_log_path):
        checks["has_progress_log"] = True
        text = read_text(progress_log_path) or ""
        raw_lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if len(raw_lines) >= 2:
            checks["progress_log_has_min_two_lines"] = True
            all_valid = True
            for ln in raw_lines:
                try:
                    obj = json.loads(ln)
                    if not isinstance(obj, dict):
                        all_valid = False
                        break
                    if "timestamp" not in obj or "event" not in obj:
                        all_valid = False
                        break
                    if not isinstance(obj["timestamp"], str) or not isinstance(obj["event"], str):
                        all_valid = False
                        break
                except Exception:
                    all_valid = False
                    break
            if all_valid:
                checks["progress_log_lines_valid"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()