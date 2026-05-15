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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_sections(md_text):
    # Returns (sections_list_in_order, section_to_lines_dict)
    lines = md_text.splitlines()
    headers = []
    for i, line in enumerate(lines):
        if line.strip().startswith("## "):
            headers.append((i, line.strip()))
    sections_order = [h for _, h in headers]
    section_map = {}
    for idx, (start_i, header) in enumerate(headers):
        end_i = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        # Content between start_i+1 and end_i (exclusive)
        content = lines[start_i + 1:end_i]
        section_map[header] = content
    return sections_order, section_map

def task_lines(lines):
    # Return lines that look like task items starting with "- ["
    return [ln for ln in lines if ln.strip().startswith("- [")]

def section_contains_exact_task(section_lines, checkbox_prefix, task_text):
    needle = f"{checkbox_prefix}{task_text}"
    for ln in section_lines:
        if ln.strip() == needle:
            return True
    return False

def section_contains_task_text(section_lines, task_text):
    for ln in section_lines:
        # Match if task text appears in the line (verbatim)
        if task_text in ln:
            return True
    return False

def all_checkbox_markers_valid(section_map):
    # Ready, Blocked => "- [ ]"
    # In Progress, Done Today => "- [x]"
    cfg = {
        "## Ready": "- [ ]",
        "## Blocked": "- [ ]",
        "## In Progress": "- [x]",
        "## Done Today": "- [x]",
    }
    for sec, prefix in cfg.items():
        if sec in section_map:
            for ln in task_lines(section_map[sec]):
                s = ln.strip()
                if not s.startswith(prefix):
                    return False
    return True

def headings_exact_and_count(sections_order):
    # Must be exactly 4 sections with these headings and no extras
    expected = ["## Ready", "## In Progress", "## Done Today", "## Blocked"]
    return sections_order == expected

def extract_section_lines(section_map, name):
    return section_map.get(name, [])

def has_timestamp_like(text):
    # Accept either full datetime or time; prefer full date-time.
    patterns = [
        r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?\b",
        r"\b\d{2}:\d{2}(:\d{2})?\b",
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "has_queue_md": False,
        "has_state_json": False,
        "has_log": False,
        "headings_correct": False,
        "moved_task_in_inprogress": False,
        "moved_task_not_in_ready": False,
        "checkbox_markers_valid": False,
        "moved_line_exact_no_annotation": False,
        "state_fields_valid": False,
        "state_current_task_match": False,
        "state_status_running": False,
        "state_progress_zero": False,
        "state_started_at_format": False,
        "state_estimated_completion_format": False,
        "log_contains_task": False,
        "log_mentions_start": False,
        "log_has_timestamp_like": False,
    }

    expected_task = "Download BTC 1h data (priority: Medium)"

    # Check output/QUEUE.md
    queue_path = os.path.join(output_dir, "QUEUE.md")
    queue_text = read_text(queue_path)
    if isinstance(queue_text, str):
        checks["has_queue_md"] = True
        sections_order, section_map = parse_sections(queue_text)

        # Headings must be exactly 4 and in this order, no extra text
        if headings_exact_and_count(sections_order):
            checks["headings_correct"] = True

            # Validate checkbox markers per section
            if all_checkbox_markers_valid(section_map):
                checks["checkbox_markers_valid"] = True

            # Verify moved task appears under In Progress with - [x]
            inprog_lines = extract_section_lines(section_map, "## In Progress")
            ready_lines = extract_section_lines(section_map, "## Ready")

            if section_contains_exact_task(inprog_lines, "- [x] ", expected_task):
                checks["moved_task_in_inprogress"] = True

                # Ensure exact moved line has no extra annotations (exact equality)
                # Find the line and ensure exact match
                found_exact = False
                for ln in task_lines(inprog_lines):
                    if ln.strip() == f"- [x] {expected_task}":
                        found_exact = True
                        break
                checks["moved_line_exact_no_annotation"] = found_exact

            # Ensure task no longer appears under Ready
            # Check that task text is not present in any Ready line
            if not section_contains_task_text(ready_lines, expected_task):
                checks["moved_task_not_in_ready"] = True

    # Check output/task_state.json
    state_path = os.path.join(output_dir, "task_state.json")
    state = load_json(state_path)
    if isinstance(state, dict):
        checks["has_state_json"] = True
        required_keys = {"current_task", "task_status", "estimated_completion", "progress", "started_at"}
        keys_ok = required_keys.issubset(state.keys())
        types_ok = (
            isinstance(state.get("current_task"), str) and
            isinstance(state.get("task_status"), str) and
            isinstance(state.get("estimated_completion"), str) and
            isinstance(state.get("progress"), str) and
            isinstance(state.get("started_at"), str)
        )
        checks["state_fields_valid"] = bool(keys_ok and types_ok)

        if state.get("current_task") == expected_task:
            checks["state_current_task_match"] = True

        if state.get("task_status") == "running":
            checks["state_status_running"] = True

        if state.get("progress") == "0%":
            checks["state_progress_zero"] = True

        # Timestamp-like patterns
        est = state.get("estimated_completion")
        if isinstance(est, str) and re.search(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", est):
            checks["state_estimated_completion_format"] = True

        started = state.get("started_at")
        if isinstance(started, str) and re.search(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", started):
            checks["state_started_at_format"] = True

    # Check output/logs/heartbeat.txt
    log_path = os.path.join(output_dir, "logs", "heartbeat.txt")
    log_text = read_text(log_path)
    if isinstance(log_text, str):
        checks["has_log"] = True
        if expected_task in log_text:
            checks["log_contains_task"] = True
        if re.search(r"\b(start|started|begin|began|initiate|initiated)\b", log_text, flags=re.IGNORECASE):
            checks["log_mentions_start"] = True
        if has_timestamp_like(log_text):
            checks["log_has_timestamp_like"] = True

    # Compute reward as fraction of passed checks.
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total

    # No-op baseline: if no outputs exist, reward must be 0.0 (already ensured)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()