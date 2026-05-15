import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def file_has_line_exact(path, expected):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()
        return content == expected
    except Exception:
        return False

def contains_any(text, patterns, case_insensitive=True):
    if text is None:
        return False
    if case_insensitive:
        text_l = text.lower()
        for p in patterns:
            if p.lower() in text_l:
                return True
        return False
    else:
        for p in patterns:
            if p in text:
                return True
        return False

def contains_all(text, patterns, case_insensitive=True):
    if text is None:
        return False
    if case_insensitive:
        text_l = text.lower()
        for p in patterns:
            if p.lower() not in text_l:
                return False
        return True
    else:
        for p in patterns:
            if p not in text:
                return False
        return True

def find_line_contains_all(lines, phrase):
    # Return True if any line contains the phrase (case-insensitive)
    phrase_l = phrase.lower()
    for ln in lines:
        if phrase_l in ln.lower():
            return True
    return False

def has_exponential_backoff_pattern(text):
    if text is None:
        return False
    tl = text.lower()
    # Require presence of check_status usage, sleep invocation, variables for backoff and cap
    has_check = "check_status.sh" in tl
    # Look for time.sleep or sleep(
    has_sleep_call = "sleep(" in tl
    # Look for variables
    has_vars = ("sleep_time" in tl or "sleeptime" in tl or "sleep_ms" in tl) and ("max_sleep" in tl or "maxsleep" in tl or "cap" in tl)
    # Look for increment or min with cap
    inc_pattern = re.search(r"(sleep_time\s*\+\=|\bsleep_time\s*=\s*sleep_time\s*\+)", tl) is not None
    min_cap_pattern = ("min(" in tl and ("max_sleep" in tl or "maxsleep" in tl or "cap" in tl))
    increases_toward_cap = inc_pattern or min_cap_pattern
    return has_check and has_sleep_call and has_vars and increases_toward_cap

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "orchestrator_exists": False,
        "orchestrator_reads_config": False,
        "orchestrator_health_polling": False,
        "orchestrator_calls_update_providers": False,
        "orchestrator_calls_create_session": False,
        "orchestrator_calls_save_state": False,
        "orchestrator_calls_send_message": False,
        "orchestrator_calls_get_diff": False,
        "orchestrator_has_monitor_modes": False,
        "orchestrator_exponential_backoff": False,
        "orchestrator_reads_task_spec": False,
        "orchestrator_writes_outputs": False,
        "placeholder_session_id": False,
        "placeholder_diff_summary": False,
        "run_log_has_all_steps": False,
        "runbook_how_to_run": False,
        "runbook_mentions_outputs": False,
        "runbook_monitor_modes": False
    }

    # Paths
    orchestrator_path = os.path.join(output_dir, "orchestrator.py")
    session_id_path = os.path.join(output_dir, "session_id.txt")
    diff_summary_path = os.path.join(output_dir, "diff_summary.txt")
    run_log_path = os.path.join(output_dir, "run_log.txt")
    runbook_path = os.path.join(output_dir, "runbook.md")

    # Orchestrator existence
    if os.path.isfile(orchestrator_path):
        checks["orchestrator_exists"] = True
        orch_text = read_text(orchestrator_path)
        # Reads ./config.json and uses base_url and projects_base_dir
        if (
            contains_all(orch_text, ["config.json"]) and
            contains_any(orch_text, ["base_url"]) and
            contains_any(orch_text, ["projects_base_dir"])
        ):
            checks["orchestrator_reads_config"] = True

        # Health check polling against /global/health
        if contains_any(orch_text, ["/global/health"]) and contains_any(orch_text, ["while", "for"]) and contains_any(orch_text, ["sleep("]):
            checks["orchestrator_health_polling"] = True

        # Invokes helper scripts
        if contains_any(orch_text, ["./scripts/update_providers.sh", "update_providers.sh"]):
            checks["orchestrator_calls_update_providers"] = True
        if contains_any(orch_text, ["./scripts/create_session.sh", "create_session.sh"]):
            checks["orchestrator_calls_create_session"] = True
        if contains_any(orch_text, ["./scripts/save_state.sh", "save_state.sh"]):
            checks["orchestrator_calls_save_state"] = True
        if contains_any(orch_text, ["./scripts/send_message.sh", "send_message.sh"]):
            checks["orchestrator_calls_send_message"] = True
        if contains_any(orch_text, ["./scripts/get_diff.sh", "get_diff.sh"]):
            checks["orchestrator_calls_get_diff"] = True

        # Monitoring modes references
        has_monitor_session = contains_any(orch_text, ["./scripts/monitor_session.sh", "monitor_session.sh"])
        has_check_status = contains_any(orch_text, ["./scripts/check_status.sh", "check_status.sh"])
        if has_monitor_session and has_check_status:
            checks["orchestrator_has_monitor_modes"] = True

        # Exponential backoff (standard mode)
        if has_exponential_backoff_pattern(orch_text):
            checks["orchestrator_exponential_backoff"] = True

        # Reads input/task_spec.json and plan/build usage
        if contains_any(orch_text, ["input/task_spec.json"]) and contains_any(orch_text, ["project_name"]) and contains_any(orch_text, ["plan_prompt"]) and contains_any(orch_text, ["build_prompt"]):
            checks["orchestrator_reads_task_spec"] = True

        # Writes results to output files
        if contains_any(orch_text, ["output/diff_summary.txt"]) and contains_any(orch_text, ["output/session_id.txt"]):
            checks["orchestrator_writes_outputs"] = True
    else:
        orch_text = None

    # Placeholders
    if os.path.isfile(session_id_path) and file_has_line_exact(session_id_path, "NOT_EXECUTED"):
        checks["placeholder_session_id"] = True
    if os.path.isfile(diff_summary_path) and file_has_line_exact(diff_summary_path, "NOT_EXECUTED"):
        checks["placeholder_diff_summary"] = True

    # Run log required phrases
    required_runlog_phrases = [
        "Verify server health",
        "Update providers",
        "Create project",
        "Create session",
        "Send plan prompt",
        "Send build prompt",
        "Monitor",
        "Get diff summary",
    ]
    if os.path.isfile(run_log_path):
        runlog_text = read_text(run_log_path) or ""
        lines = runlog_text.splitlines()
        if all(find_line_contains_all(lines, p) for p in required_runlog_phrases):
            checks["run_log_has_all_steps"] = True

    # Runbook checks
    if os.path.isfile(runbook_path):
        runbook_text = read_text(runbook_path) or ""
        # How to run orchestrator: mention python and path to script
        if contains_any(runbook_text, ["python", "python3"]) and contains_any(runbook_text, ["output/orchestrator.py"]):
            checks["runbook_how_to_run"] = True
        # Mentions both output files
        if contains_all(runbook_text, ["output/diff_summary.txt", "output/session_id.txt"]):
            checks["runbook_mentions_outputs"] = True
        # Describes both monitoring modes: standard and realtime/real-time
        has_standard = contains_any(runbook_text, ["standard"])
        has_realtime = contains_any(runbook_text, ["realtime", "real-time", "real time"])
        if has_standard and has_realtime:
            checks["runbook_monitor_modes"] = True

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output is empty or none of the key artifacts exist, reward should be 0.0
    # If orchestrator and all main deliverables missing, set reward to 0.0
    output_exists = os.path.isdir(output_dir) and any(os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir)) if os.path.isdir(output_dir) else False
    key_artifacts = [
        checks["orchestrator_exists"],
        os.path.isfile(run_log_path),
        os.path.isfile(runbook_path),
        os.path.isfile(diff_summary_path),
        os.path.isfile(session_id_path),
    ]
    if not output_exists or not any(key_artifacts):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    # Add checks after reward to keep "reward" as the first top-level field
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()