import json
import os
import sys
from typing import Dict, Any

def is_int_strict(x: Any) -> bool:
    # Ensure it's an int but not a bool (since bool is subclass of int)
    return isinstance(x, int) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with all False (no vacuous passes)
    checks: Dict[str, bool] = {
        # Existence checks
        "file_plan_exists": False,
        "file_commands_exists": False,
        "file_summary_exists": False,
        "file_rollback_exists": False,
        # Plan content checks
        "plan_has_npm_link": False,
        "plan_has_API_KEY_token": False,
        "plan_has_check_status_phrase": False,
        "plan_has_assumptions_word": False,
        "plan_has_rollback_word": False,
        # Commands content checks
        "commands_has_check_status": False,
        "commands_has_group_list_or_create": False,
        "commands_has_create_proxy": False,
        "commands_has_create_browser": False,
        "commands_has_open_browser_at_least_two": False,
        "commands_has_get_opened_browser": False,
        "commands_no_forbidden_substrings": False,
        # Summary checks
        "summary_valid_json_fields": False,
        "summary_command_counts_match": False,
        "summary_profiles_to_open_match_and_min2": False,
        # Rollback checks
        "rollback_has_close_all": False,
        "rollback_has_cleanup": False,
    }

    # Resolve file paths
    plan_path = os.path.join(output_dir, "plan.md")
    commands_path = os.path.join(output_dir, "commands.txt")
    summary_path = os.path.join(output_dir, "summary.json")
    rollback_path = os.path.join(output_dir, "rollback.txt")

    # 1) Verify required files exist
    if os.path.isfile(plan_path):
        checks["file_plan_exists"] = True
    if os.path.isfile(commands_path):
        checks["file_commands_exists"] = True
    if os.path.isfile(summary_path):
        checks["file_summary_exists"] = True
    if os.path.isfile(rollback_path):
        checks["file_rollback_exists"] = True

    # 2) Inspect plan.md for required textual evidence
    plan_content = ""
    if checks["file_plan_exists"]:
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_content = f.read()
        except Exception:
            plan_content = ""

        if "https://www.npmjs.com/package/adspower-browser" in plan_content:
            checks["plan_has_npm_link"] = True
        if "API_KEY" in plan_content:
            checks["plan_has_API_KEY_token"] = True
        if "adspower-browser check-status" in plan_content:
            checks["plan_has_check_status_phrase"] = True
        lower_plan = plan_content.lower()
        if "assumptions" in lower_plan:
            checks["plan_has_assumptions_word"] = True
        if "rollback" in lower_plan:
            checks["plan_has_rollback_word"] = True

    # 3) Inspect commands.txt contents
    commands_content = ""
    commands_lines = []
    if checks["file_commands_exists"]:
        try:
            with open(commands_path, "r", encoding="utf-8") as f:
                commands_content = f.read()
                commands_lines = commands_content.splitlines()
        except Exception:
            commands_content = ""
            commands_lines = []

        # Presence checks (containment)
        if any("adspower-browser check-status" in line for line in commands_lines):
            checks["commands_has_check_status"] = True
        if any(("adspower-browser get-group-list" in line) or ("adspower-browser create-group" in line) for line in commands_lines):
            checks["commands_has_group_list_or_create"] = True
        if any("adspower-browser create-proxy" in line for line in commands_lines):
            checks["commands_has_create_proxy"] = True
        if any("adspower-browser create-browser" in line for line in commands_lines):
            checks["commands_has_create_browser"] = True
        open_browser_count_contains = sum(1 for line in commands_lines if "adspower-browser open-browser" in line)
        if open_browser_count_contains >= 2:
            checks["commands_has_open_browser_at_least_two"] = True
        if any("adspower-browser get-opened-browser" in line for line in commands_lines):
            checks["commands_has_get_opened_browser"] = True

        # Forbidden substrings
        forbidden_found = False
        # lower-case tokens checked in lower text
        lower_cmds = commands_content.lower()
        if "sudo" in lower_cmds or "curl" in lower_cmds or "dpkg" in lower_cmds:
            forbidden_found = True
        # case-sensitive tokens as specified
        if ("Invoke-WebRequest" in commands_content) or ("Start-Process" in commands_content):
            forbidden_found = True
        checks["commands_no_forbidden_substrings"] = not forbidden_found

    # 4) Parse summary.json and validate structure and counts
    summary_obj: Dict[str, Any] = {}
    if checks["file_summary_exists"]:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
        except Exception:
            summary_obj = {}

        # Validate required fields and types
        required_int_fields = ["groups_to_create", "proxies_to_create", "profiles_to_create", "profiles_to_open"]
        command_counts_ok = False
        ints_ok = all(field in summary_obj and is_int_strict(summary_obj[field]) for field in required_int_fields)
        if "command_counts" in summary_obj and isinstance(summary_obj["command_counts"], dict):
            cc = summary_obj["command_counts"]
            cc_required = ["create_group", "create_proxy", "create_browser", "open_browser"]
            command_counts_ok = all((key in cc) and is_int_strict(cc[key]) for key in cc_required)
        if ints_ok and command_counts_ok:
            checks["summary_valid_json_fields"] = True

        # Compute actual counts from commands.txt (exact, case-sensitive prefix match)
        if checks["file_commands_exists"]:
            def prefix_count(prefix: str) -> int:
                return sum(1 for line in commands_lines if line.startswith(prefix))
            observed_counts = {
                "create_group": prefix_count("adspower-browser create-group"),
                "create_proxy": prefix_count("adspower-browser create-proxy"),
                "create_browser": prefix_count("adspower-browser create-browser"),
                "open_browser": prefix_count("adspower-browser open-browser"),
            }

            # Match command_counts
            if checks["summary_valid_json_fields"]:
                cc = summary_obj["command_counts"]
                if all(cc[k] == observed_counts[k] for k in observed_counts.keys()):
                    checks["summary_command_counts_match"] = True

                # profiles_to_open must be >= 2 and equal to observed open-browser count
                profiles_to_open_val = summary_obj.get("profiles_to_open", -1)
                if is_int_strict(profiles_to_open_val) and profiles_to_open_val >= 2 and profiles_to_open_val == observed_counts["open_browser"]:
                    checks["summary_profiles_to_open_match_and_min2"] = True

    # 5) Inspect rollback.txt contents
    rollback_content = ""
    if checks["file_rollback_exists"]:
        try:
            with open(rollback_path, "r", encoding="utf-8") as f:
                rollback_content = f.read()
        except Exception:
            rollback_content = ""
        if "adspower-browser close-all-profiles" in rollback_content:
            checks["rollback_has_close_all"] = True
        if ("adspower-browser delete-browser" in rollback_content) or \
           ("adspower-browser delete-proxy" in rollback_content) or \
           ("adspower-browser delete-cache-v2" in rollback_content):
            checks["rollback_has_cleanup"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    # Output JSON: reward first, then checks
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()