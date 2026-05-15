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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def last_nonempty_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""

def find_section(text, heading):
    # Case-insensitive section extractor for "## <heading>"
    lines = text.splitlines()
    start_idx = None
    end_idx = len(lines)
    heading_re = re.compile(r"^\s*##\s*"+re.escape(heading)+r"\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if heading_re.match(line):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s*##\s+", lines[j]):  # next section
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])

def contains_heading(text, heading):
    return re.search(r"^\s*##\s*"+re.escape(heading)+r"\s*$", text, flags=re.IGNORECASE|re.MULTILINE) is not None

def line_present_case_insensitive(text, pattern):
    # Search for a line containing pattern (case-insensitive)
    pat = pattern.lower()
    for line in text.splitlines():
        if pat in line.lower():
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Load inputs used as expectations
    run_date_path = os.path.join(input_dir, "run_date.txt")
    system_state_path = os.path.join(input_dir, "system_state.json")

    run_date_str = read_text(run_date_path)
    if run_date_str is None:
        expected_date = "2026-04-15"  # fallback to expected in spec if input missing
    else:
        expected_date = run_date_str.strip()

    system_state = read_json(system_state_path) or {}
    # Derive expected values from system_state where applicable
    claw_current = None
    claw_latest = None
    if isinstance(system_state, dict):
        cb = system_state.get("clawdbot") or {}
        claw_current = cb.get("current_version")
        claw_latest = cb.get("latest_version")
    # Fallback to spec-specific versions if not provided
    if not claw_current:
        claw_current = "v2026.1.9"
    if not claw_latest:
        claw_latest = "v2026.1.10"

    skills = []
    if isinstance(system_state, dict):
        raw_skills = system_state.get("skills")
        if isinstance(raw_skills, list):
            for s in raw_skills:
                if isinstance(s, dict):
                    name = s.get("name")
                    cv = s.get("current_version")
                    lv = s.get("latest_version")
                    will_fail = bool(s.get("will_fail", False))
                    if name and cv and lv:
                        skills.append({"name": name, "current": cv, "latest": lv, "will_fail": will_fail})

    # Compute expected grouping based on inputs
    updated_skills = []
    failed_skills = []
    current_skills = []
    for s in skills:
        if s["will_fail"]:
            failed_skills.append(s)
        else:
            if s["current"] != s["latest"]:
                updated_skills.append(s)
            else:
                current_skills.append(s)

    # Paths to outputs
    cron_path = os.path.join(output_dir, "cron", "daily-auto-update.json")
    summary_path = os.path.join(output_dir, "reports", "daily-auto-update-summary.txt")
    log_filename = f"openclaw-update-{expected_date}.md"
    log_path = os.path.join(output_dir, "logs", log_filename)

    checks = {
        # Cron JSON checks
        "cron_file_exists": False,
        "cron_json_valid": False,
        "cron_schedule_expr_correct": False,
        "cron_schedule_tz_correct": False,
        "cron_missed_policy_correct": False,
        "cron_payload_kind_correct": False,
        "cron_timeout_correct": False,
        "cron_message_mentions_required": False,

        # Summary checks
        "summary_file_exists": False,
        "summary_header_ok": False,
        "summary_clawdbot_change_ok": False,
        "summary_updated_section_ok": False,
        "summary_failed_section_ok": False,
        "summary_current_section_ok": False,
        "summary_ending_status_ok": False,

        # Log checks
        "log_file_exists": False,
        "log_title_ok": False,
        "log_sections_present": False,
        "log_before_versions_ok": False,
        "log_during_commands_ok": False,
        "log_waits_ok": False,
        "log_after_status_ok": False,
        "log_update_details_ok": False,
    }

    # 1) Cron JSON checks
    cron_data = None
    if os.path.isfile(cron_path):
        checks["cron_file_exists"] = True
        cron_data = read_json(cron_path)
        if isinstance(cron_data, dict):
            checks["cron_json_valid"] = True
            # Expected exact according to spec
            schedule = cron_data.get("schedule") or {}
            if isinstance(schedule, dict):
                expr = schedule.get("expr")
                tz = schedule.get("tz")
                if expr == "0 4 * * *":
                    checks["cron_schedule_expr_correct"] = True
                if tz == "Europe/London":
                    checks["cron_schedule_tz_correct"] = True
            if cron_data.get("missedRunPolicy") == "run-immediately":
                checks["cron_missed_policy_correct"] = True
            payload = cron_data.get("payload") or {}
            if isinstance(payload, dict):
                if payload.get("kind") == "agentTurn":
                    checks["cron_payload_kind_correct"] = True
                if payload.get("timeoutSeconds") == 600:
                    checks["cron_timeout_correct"] = True
                msg = payload.get("message")
                if isinstance(msg, str) and msg.strip():
                    msg_low = msg.lower()
                    # Must mention both commands and indicate daily update and report
                    has_doctor = "clawdbot doctor" in msg_low
                    has_hub = "clawdhub update --all" in msg_low
                    # Indication: daily + update + report
                    indicates_daily = ("daily" in msg_low)
                    indicates_update = ("auto-update" in msg_low) or ("auto update" in msg_low) or ("update" in msg_low)
                    indicates_report = ("report" in msg_low)
                    if has_doctor and has_hub and indicates_daily and indicates_update and indicates_report:
                        checks["cron_message_mentions_required"] = True

    # 2) Summary checks
    summary_text = None
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True
        summary_text = read_text(summary_path) or ""
        # Header
        if re.search(r"daily\s+auto-update\s+complete", summary_text, flags=re.IGNORECASE):
            checks["summary_header_ok"] = True
        # Clawdbot version change exact string
        expected_cb_change = f"{claw_current} \u2192 {claw_latest}"
        if expected_cb_change in summary_text:
            checks["summary_clawdbot_change_ok"] = True

        # Updated section: Expect exactly 2: browser and nano-banana-pro with given versions
        # According to spec, enforce those specific items
        updated_heading_ok = re.search(r"^\s*skills\s+updated\s*\(2\)\s*$", summary_text, flags=re.IGNORECASE|re.MULTILINE) is not None
        upd1 = "browser: 1.2.0 \u2192 1.2.1" in summary_text
        upd2 = "nano-banana-pro: 3.1.0 \u2192 3.1.2" in summary_text
        if updated_heading_ok and upd1 and upd2:
            checks["summary_updated_section_ok"] = True

        # Failed section: heading and "himalaya" with "Update failed"
        failed_heading_ok = re.search(r"^\s*skills\s+failed\s*\(1\)\s*$", summary_text, flags=re.IGNORECASE|re.MULTILINE) is not None
        failed_line_ok = False
        for line in summary_text.splitlines():
            if ("himalaya" in line.lower()) and ("update failed" in line.lower()):
                failed_line_ok = True
                break
        if failed_heading_ok and failed_line_ok:
            checks["summary_failed_section_ok"] = True

        # Already current section: heading and prd, gemini
        current_heading_ok = re.search(r"^\s*skills\s+already\s+current\s*\(2\)\s*$", summary_text, flags=re.IGNORECASE|re.MULTILINE) is not None
        has_prd = re.search(r"\bprd\b", summary_text, flags=re.IGNORECASE) is not None
        has_gemini = re.search(r"\bgemini\b", summary_text, flags=re.IGNORECASE) is not None
        if current_heading_ok and has_prd and has_gemini:
            checks["summary_current_section_ok"] = True

        # Ending status line: must be "Completed with 1 error."
        last_line = last_nonempty_line(summary_text)
        if last_line == "Completed with 1 error.":
            checks["summary_ending_status_ok"] = True

    # 3) Log checks
    log_text = None
    if os.path.isfile(log_path):
        checks["log_file_exists"] = True
        log_text = read_text(log_path) or ""
        # Title must be first non-empty line
        first_nonempty = ""
        for line in log_text.splitlines():
            if line.strip():
                first_nonempty = line.strip()
                break
        expected_title = f"# OpenClaw Update Log {expected_date}"
        if first_nonempty == expected_title:
            checks["log_title_ok"] = True

        # Sections present
        if (contains_heading(log_text, "Before Update")
            and contains_heading(log_text, "During Update")
            and contains_heading(log_text, "After Update")
            and contains_heading(log_text, "Update Details")):
            checks["log_sections_present"] = True

        # Before Update versions lines
        before_sec = find_section(log_text, "Before Update") or ""
        before_has_current = re.search(r"current\s+version:\s*"+re.escape(claw_current), before_sec, flags=re.IGNORECASE) is not None
        before_has_latest = re.search(r"latest\s+version:\s*"+re.escape(claw_latest), before_sec, flags=re.IGNORECASE) is not None
        if before_has_current and before_has_latest:
            checks["log_before_versions_ok"] = True

        # During Update commands
        during_sec = find_section(log_text, "During Update") or ""
        has_doctor_cmd = "clawdbot doctor" in during_sec.lower()
        has_hub_cmd = "clawdhub update --all" in during_sec.lower()
        if has_doctor_cmd and has_hub_cmd:
            checks["log_during_commands_ok"] = True

        # Waits
        waits_ok = ("disk sync wait: 3s".lower() in log_text.lower()) and ("restart delay: 30s".lower() in log_text.lower())
        if waits_ok:
            checks["log_waits_ok"] = True

        # After Update status
        after_sec = find_section(log_text, "After Update") or ""
        if re.search(r"^\s*status:\s*updated\s*$", after_sec, flags=re.IGNORECASE|re.MULTILINE):
            checks["log_after_status_ok"] = True

        # Update Details content
        details_sec = find_section(log_text, "Update Details") or ""
        # Updated skills lines
        updA = "browser: 1.2.0 \u2192 1.2.1" in details_sec
        updB = "nano-banana-pro: 3.1.0 \u2192 3.1.2" in details_sec
        # Failed skill with failure note
        fail_line = False
        for line in details_sec.splitlines():
            if ("himalaya" in line.lower()) and (("fail" in line.lower()) or ("error" in line.lower())):
                fail_line = True
                break
        # Already current skills contain prd and gemini
        has_prd_details = re.search(r"\bprd\b", details_sec, flags=re.IGNORECASE) is not None
        has_gemini_details = re.search(r"\bgemini\b", details_sec, flags=re.IGNORECASE) is not None
        if updA and updB and fail_line and has_prd_details and has_gemini_details:
            checks["log_update_details_ok"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    # No-op baseline: if no output files at all, ensure 0.0
    any_output = any([
        checks["cron_file_exists"],
        checks["summary_file_exists"],
        checks["log_file_exists"],
    ])
    if not any_output:
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()