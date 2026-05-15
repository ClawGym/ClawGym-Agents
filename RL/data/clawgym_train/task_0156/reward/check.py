import json
import os
import sys
import re

def is_nonneg_int(x):
    return isinstance(x, int) and x >= 0

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def line_has_all(line, tokens):
    return all(tok in line for tok in tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_reproducible_commands": False,
        "has_installed_report": False,
        "has_summary": False,
        "has_package_export": False,
        "has_log": False,

        "commands_include_search": False,
        "commands_include_install": False,
        "commands_include_upgrade": False,
        "commands_include_uninstall": False,
        "commands_include_list": False,
        "commands_include_export_to_output": False,

        "installed_report_valid_schema": False,
        "summary_counts_consistent": False,
        "package_export_json_valid_nonempty": False,
        "log_nonempty": False,

        "all_required_present": False
    }

    # Resolve paths
    repro_commands_path = os.path.join(output_dir, "reproducible_commands.md")
    installed_report_path = os.path.join(output_dir, "installed_report.json")
    summary_path = os.path.join(output_dir, "summary.json")
    export_path = os.path.join(output_dir, "package_export.json")
    log_path = os.path.join(output_dir, "log.txt")

    # Existence checks
    if os.path.isfile(repro_commands_path):
        checks["has_reproducible_commands"] = True
    if os.path.isfile(installed_report_path):
        checks["has_installed_report"] = True
    if os.path.isfile(summary_path):
        checks["has_summary"] = True
    if os.path.isfile(export_path):
        checks["has_package_export"] = True
    if os.path.isfile(log_path):
        checks["has_log"] = True

    # Gate: required files must all be present
    required_present = all([
        checks["has_reproducible_commands"],
        checks["has_installed_report"],
        checks["has_summary"],
        checks["has_package_export"],
        checks["has_log"],
    ])
    checks["all_required_present"] = required_present

    if required_present:
        # Parse reproducible_commands.md
        text, err = read_text(repro_commands_path)
        if text is None:
            text = ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Lowercase for case-insensitive matching
        lc_lines = [ln.lower() for ln in lines]

        # Helper to find a line that contains pattern and required flags
        def any_line_with(substring, required_flags, optional_contains=None):
            for ln in lc_lines:
                if substring in ln:
                    if line_has_all(ln, [flag.lower() for flag in required_flags]):
                        if optional_contains is None:
                            return True
                        else:
                            if optional_contains.lower() in ln:
                                return True
            return False

        # Search command: winget search with required flags
        checks["commands_include_search"] = any_line_with(
            "winget search",
            ["--disable-interactivity", "--accept-source-agreements"]
        )

        # Install command: winget install with required flags
        checks["commands_include_install"] = any_line_with(
            "winget install",
            ["--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements"]
        )

        # Upgrade command: winget upgrade with required flags
        checks["commands_include_upgrade"] = any_line_with(
            "winget upgrade",
            ["--disable-interactivity", "--accept-source-agreements", "--accept-package-agreements"]
        )

        # Uninstall command: winget uninstall must include --disable-interactivity
        # Do not require accept-source or accept-package agreements for uninstall
        found_uninstall = False
        for ln in lc_lines:
            if "winget uninstall" in ln and "--disable-interactivity" in ln:
                found_uninstall = True
                break
        checks["commands_include_uninstall"] = found_uninstall

        # List command: winget list with required flags
        checks["commands_include_list"] = any_line_with(
            "winget list",
            ["--disable-interactivity", "--accept-source-agreements"]
        )

        # Export command: winget export with required flags and output path
        # Must include destination "output/package_export.json"
        checks["commands_include_export_to_output"] = any_line_with(
            "winget export",
            ["--disable-interactivity", "--accept-source-agreements"],
            optional_contains="output/package_export.json"
        )

        # Validate installed_report.json schema
        installed_data, err = load_json_file(installed_report_path)
        if isinstance(installed_data, dict) and "packages" in installed_data and isinstance(installed_data["packages"], list):
            packages = installed_data["packages"]
            schema_ok = True
            for p in packages:
                if not isinstance(p, dict):
                    schema_ok = False
                    break
                for key in ("id", "name", "version"):
                    if key not in p or not isinstance(p[key], str):
                        schema_ok = False
                        break
                if not schema_ok:
                    break
            checks["installed_report_valid_schema"] = schema_ok

        # Validate summary.json keys and counts
        summary_data, err = load_json_file(summary_path)
        if isinstance(summary_data, dict):
            keys_needed = ["processed", "installed", "upgraded", "uninstalled", "skipped", "not_found", "errors"]
            if all(k in summary_data for k in keys_needed):
                all_ints = all(is_nonneg_int(summary_data[k]) for k in keys_needed)
                if all_ints:
                    processed = summary_data["processed"]
                    computed = (
                        summary_data["installed"]
                        + summary_data["upgraded"]
                        + summary_data["uninstalled"]
                        + summary_data["skipped"]
                        + summary_data["not_found"]
                    )
                    if processed == computed:
                        checks["summary_counts_consistent"] = True

        # Validate package_export.json is valid JSON and non-empty
        try:
            size = os.path.getsize(export_path)
        except OSError:
            size = 0
        export_data, err = load_json_file(export_path)
        if size > 0 and export_data is not None:
            checks["package_export_json_valid_nonempty"] = True

        # Log non-empty
        log_text, err = read_text(log_path)
        if log_text is not None and len(log_text.strip()) > 0:
            checks["log_nonempty"] = True

    # Compute reward
    # If any required artifact missing, reward must be 0.0
    if not checks["all_required_present"]:
        reward = 0.0
    else:
        # Content checks to score
        content_checks = [
            "commands_include_search",
            "commands_include_install",
            "commands_include_upgrade",
            "commands_include_uninstall",
            "commands_include_list",
            "commands_include_export_to_output",
            "installed_report_valid_schema",
            "summary_counts_consistent",
            "package_export_json_valid_nonempty",
            "log_nonempty",
        ]
        passed = sum(1 for k in content_checks if checks.get(k, False))
        total = len(content_checks)
        reward = passed / total if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()