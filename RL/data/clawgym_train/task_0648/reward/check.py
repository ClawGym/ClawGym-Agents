import json
import os
import sys

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def file_contains_line(path, exact_line):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.rstrip("\n").strip() == exact_line:
                    return True
        return False
    except Exception:
        return False

def file_contains_all_substrings(path, substrings):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return all(s in content for s in substrings)
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False (no-op baseline yields reward 0.0)
    checks = {
        # Daily cron checks
        "daily_exists": False,
        "daily_valid_fields": False,
        "daily_msg_native": False,
        "daily_msg_skills_update": False,
        "daily_msg_429": False,
        # Monthly cron checks
        "monthly_exists": False,
        "monthly_valid_fields": False,
        "monthly_msg_native": False,
        "monthly_msg_record_version": False,
        "monthly_msg_openclaw_update": False,
        "monthly_msg_skills_update": False,
        "monthly_msg_429": False,
        # Plan checks
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_has_targeted_required": False,
        "plan_targeted_order": False,
        "plan_targeted_excludes_local": False,
        "plan_has_ignored_array": False,
        # Reporting format
        "reporting_exists": False,
        "reporting_contains_required": False,
        # Runbook checks
        "runbook_exists": False,
        "runbook_contains_required": False,
    }

    # Paths
    daily_path = os.path.join(output_dir, "cron", "daily_skills.json")
    monthly_path = os.path.join(output_dir, "cron", "monthly_core_plus_skills.json")
    plan_path = os.path.join(output_dir, "plan", "target_skills.json")
    reporting_path = os.path.join(output_dir, "reporting_format.txt")
    runbook_path = os.path.join(output_dir, "runbook.md")

    # 1) Daily skills-only cron JSON
    if os.path.isfile(daily_path):
        checks["daily_exists"] = True
        daily_json, daily_err = read_json_file(daily_path)
        if daily_json is not None and isinstance(daily_json, dict):
            expected_keys = {"name", "cron", "tz", "session", "announce", "message"}
            if set(daily_json.keys()) == expected_keys:
                if (
                    daily_json.get("name") == "Daily Skills Auto-Update"
                    and daily_json.get("cron") == "15 4 * * *"
                    and daily_json.get("tz") == "America/New_York"
                    and daily_json.get("session") == "current"
                    and daily_json.get("announce") is True
                    and isinstance(daily_json.get("message"), str)
                    and len(daily_json.get("message")) > 0
                ):
                    checks["daily_valid_fields"] = True

                    msg = daily_json.get("message", "")
                    if "Use native OpenClaw commands only" in msg:
                        checks["daily_msg_native"] = True
                    if "openclaw skills update" in msg:
                        checks["daily_msg_skills_update"] = True
                    if "429 Rate limit exceeded" in msg:
                        checks["daily_msg_429"] = True

    # 2) Monthly core + skills cron JSON
    if os.path.isfile(monthly_path):
        checks["monthly_exists"] = True
        monthly_json, monthly_err = read_json_file(monthly_path)
        if monthly_json is not None and isinstance(monthly_json, dict):
            expected_keys = {"name", "cron", "tz", "session", "announce", "message"}
            if set(monthly_json.keys()) == expected_keys:
                if (
                    monthly_json.get("name") == "Monthly OpenClaw Auto-Update"
                    and monthly_json.get("cron") == "0 5 1-7 * 6"
                    and monthly_json.get("tz") == "America/New_York"
                    and monthly_json.get("session") == "isolated"
                    and monthly_json.get("announce") is True
                    and isinstance(monthly_json.get("message"), str)
                    and len(monthly_json.get("message")) > 0
                ):
                    checks["monthly_valid_fields"] = True

                    msg = monthly_json.get("message", "")
                    if "Use native OpenClaw commands only" in msg:
                        checks["monthly_msg_native"] = True
                    if "record the current OpenClaw version" in msg:
                        checks["monthly_msg_record_version"] = True
                    if "openclaw update" in msg:
                        checks["monthly_msg_openclaw_update"] = True
                    if "openclaw skills update" in msg:
                        checks["monthly_msg_skills_update"] = True
                    if "429 Rate limit exceeded" in msg:
                        checks["monthly_msg_429"] = True

    # 3) Plan target_skills.json
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_json, plan_err = read_json_file(plan_path)
        if (
            plan_json is not None
            and isinstance(plan_json, dict)
            and "targeted" in plan_json
            and "ignored" in plan_json
            and isinstance(plan_json["targeted"], list)
            and isinstance(plan_json["ignored"], list)
        ):
            checks["plan_json_valid"] = True

            targeted = plan_json["targeted"]
            ignored = plan_json["ignored"]

            required_in_targeted = {
                "auto-updater-openclaw",
                "agent-memory-templates",
                "afrexai-ai-adoption-readiness",
            }
            if all(item in targeted for item in required_in_targeted):
                checks["plan_has_targeted_required"] = True

            # Order: first two items must be specific sequence
            if len(targeted) >= 2:
                if targeted[0] == "auto-updater-openclaw" and targeted[1] == "agent-memory-templates":
                    checks["plan_targeted_order"] = True

            # Ensure excluded items are not present in targeted
            excluded = {"company-experimental-skill", "local-utils"}
            if not any(item in targeted for item in excluded):
                checks["plan_targeted_excludes_local"] = True

            # Ignored array presence already checked; ensure it's a list
            if isinstance(ignored, list):
                checks["plan_has_ignored_array"] = True

    # 4) Reporting format
    if os.path.isfile(reporting_path):
        checks["reporting_exists"] = True
        has_header = file_contains_line(reporting_path, "OpenClaw Update Complete")
        has_labels = file_contains_all_substrings(
            reporting_path, ["Skills updated:", "Already current:", "Issues:"]
        )
        if has_header and has_labels:
            checks["reporting_contains_required"] = True

    # 5) Runbook
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        phrases = [
            "skills auto-update",
            "core updates are opt-in",
            "per-skill updates",
            "429 Rate limit exceeded",
            "session",
        ]
        if file_contains_all_substrings(runbook_path, phrases):
            checks["runbook_contains_required"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=True))

if __name__ == "__main__":
    main()