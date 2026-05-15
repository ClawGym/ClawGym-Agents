import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_has_exact_keys": False,
        "plan_project_name_ok": False,
        "plan_bash_themes_dir_ok": False,
        "plan_commands_ok": False,
        "usage_exists": False,
        "usage_has_export_line": False,
        "usage_has_all_commands": False,
        "usage_no_absolute_paths": False,
    }

    # Expected values per task specification
    expected_project_name = "acme-web"
    expected_bash_themes_dir = "output/.bash-themes"
    expected_commands = [
        "bash-themes init",
        "bash-themes template python",
        "bash-themes config",
        "bash-themes check",
        "bash-themes build",
        "bash-themes test",
        "bash-themes docs",
        "bash-themes status",
        "bash-themes deploy",
        "bash-themes clean",
    ]

    # Check plan.json
    plan_path = os.path.join(output_dir, "plan.json")
    plan_data = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
            checks["plan_valid_json"] = True
        except Exception:
            plan_data = None

    if plan_data is not None and isinstance(plan_data, dict):
        keys = set(plan_data.keys())
        required_keys = {"project_name", "bash_themes_dir", "commands"}
        if keys == required_keys:
            checks["plan_has_exact_keys"] = True

            # Validate project_name
            if isinstance(plan_data.get("project_name"), str) and plan_data["project_name"] == expected_project_name:
                checks["plan_project_name_ok"] = True

            # Validate bash_themes_dir
            if isinstance(plan_data.get("bash_themes_dir"), str) and plan_data["bash_themes_dir"] == expected_bash_themes_dir:
                checks["plan_bash_themes_dir_ok"] = True

            # Validate commands
            cmds = plan_data.get("commands")
            if isinstance(cmds, list) and all(isinstance(c, str) for c in cmds):
                if cmds == expected_commands:
                    checks["plan_commands_ok"] = True

    # Check USAGE.md
    usage_path = os.path.join(output_dir, "USAGE.md")
    usage_content = None
    if os.path.isfile(usage_path):
        checks["usage_exists"] = True
        try:
            with open(usage_path, "r", encoding="utf-8") as f:
                usage_content = f.read()
        except Exception:
            usage_content = None

    if isinstance(usage_content, str):
        # Must contain the exact line
        lines = usage_content.splitlines()
        required_export_line = "export BASH_THEMES_DIR=output/.bash-themes"
        if any(line == required_export_line for line in lines):
            checks["usage_has_export_line"] = True

        # Must contain all commands (as substrings anywhere in content)
        if all(cmd in usage_content for cmd in expected_commands):
            checks["usage_has_all_commands"] = True

        # No absolute paths (POSIX starting with '/', Windows drive like 'C:\', or '~' home)
        def is_abs_line(s: str) -> bool:
            st = s.lstrip()
            if st.startswith("/"):
                return True
            if st.startswith("~"):
                return True
            if re.match(r"^[A-Za-z]:\\", st):
                return True
            return False

        if not any(is_abs_line(line) for line in lines):
            checks["usage_no_absolute_paths"] = True

    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()