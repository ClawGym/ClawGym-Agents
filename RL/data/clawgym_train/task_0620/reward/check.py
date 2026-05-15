import json
import os
import re
import sys
from collections import OrderedDict

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    proj_root = os.path.join(output_dir, "projctl")
    checks = OrderedDict()

    # Initialize all checks as False
    check_names = [
        # Structure
        "projctl_dir_exists",
        "readme_exists",
        "has_source_dir",
        "has_cli_entry_file",
        "has_packaging_metadata",
        # Commands and flags (presence in code or README as appropriate)
        "has_init_cmd",
        "has_list_cmd",
        "has_config_cmd",
        "has_process_cmd",
        "has_completion_cmd",
        "has_config_get_set_doc",
        "has_help_option",
        "has_version_option",
        "has_json_flag",
        "has_quiet_flag",
        "mentions_stdin_support",
        "has_error_exit_calls",
        # README content checks
        "readme_has_installation",
        "readme_has_usage",
        "readme_has_examples",
        "readme_has_configuration",
        "readme_has_exit_codes",
        "readme_mentions_precedence_and_locations",
        "readme_example_uses_sample_projects",
        "readme_mentions_pipelines_or_stdin",
        "readme_mentions_json_quiet",
        # Tests
        "tests_dir_exists",
        "tests_cover_help_version",
        # Hygiene
        "no_machine_specific_paths",
        # Combined pipeline-friendly design
        "pipeline_friendly_design",
    ]
    for name in check_names:
        checks[name] = False

    # No-op baseline: if output/projctl missing, reward must be 0.0
    if not os.path.isdir(proj_root):
        reward = 0.0
        result = OrderedDict([("reward", reward)])
        result.update(checks)
        print(json.dumps(result))
        return

    checks["projctl_dir_exists"] = True

    # Collect files
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py", ".ts", ".js"}
    code_exts = {".py", ".ts", ".js"}
    all_files = []
    code_files = []
    readme_path = os.path.join(proj_root, "README.md")
    tests_dir = os.path.join(proj_root, "tests")

    for root, dirs, files in os.walk(proj_root):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in allowed_exts:
                fpath = os.path.join(root, fname)
                all_files.append(fpath)
                if ext in code_exts:
                    code_files.append(fpath)

    # Read README
    readme_text = ""
    if os.path.isfile(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                readme_text = f.read()
            checks["readme_exists"] = True
        except Exception:
            pass

    # Gather code text (for string presence checks)
    code_texts = []
    for f in code_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                code_texts.append(fh.read())
        except Exception:
            code_texts.append("")
    all_code_text = "\n".join(code_texts)

    # Source directory detection
    source_dir_candidates = {"src", "lib", "app", "cli", "bin"}
    has_source_dir = False
    source_dirs_found = []
    try:
        for entry in os.listdir(proj_root):
            full = os.path.join(proj_root, entry)
            if os.path.isdir(full) and entry in source_dir_candidates:
                # Confirm it contains at least one code file
                contains_code = False
                for r, d, files in os.walk(full):
                    if any(os.path.splitext(f)[1].lower() in code_exts for f in files):
                        contains_code = True
                        break
                if contains_code:
                    has_source_dir = True
                    source_dirs_found.append(full)
        checks["has_source_dir"] = has_source_dir
    except Exception:
        pass

    # CLI entry file detection: cli.* or main.* within project or source dirs
    def find_entry_files():
        entry_names = {"cli", "main"}
        for f in all_files:
            base = os.path.basename(f)
            name, ext = os.path.splitext(base)
            if ext.lower() in code_exts and name in entry_names:
                return True
        return False

    checks["has_cli_entry_file"] = find_entry_files()

    # Packaging metadata detection (Node package.json with proper bin mapping)
    def detect_packaging_metadata(project_root):
        pkg_json_path = os.path.join(project_root, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                bin_field = data.get("bin")
                pkg_name = data.get("name", "")
                if isinstance(bin_field, dict):
                    # Accept explicit "projctl" key
                    if "projctl" in bin_field and isinstance(bin_field["projctl"], str):
                        return True
                elif isinstance(bin_field, str):
                    # If bin is a string, then the executable name equals package name
                    if pkg_name == "projctl" and isinstance(bin_field, str):
                        return True
            except Exception:
                pass
        # Accept alternative JSON metadata file that maps console entry
        # e.g., "entry_points.json" with {"console_scripts": {"projctl": "module:func"}}
        alt_paths = [os.path.join(project_root, "entry_points.json")]
        for p in alt_paths:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cs = data.get("console_scripts", {})
                    if isinstance(cs, dict) and "projctl" in cs:
                        return True
                except Exception:
                    pass
        return False

    checks["has_packaging_metadata"] = detect_packaging_metadata(proj_root)

    # Command/flag presence: scan code (primary) and README (secondary where allowed)
    def present_in_code(token: str) -> bool:
        return token in all_code_text

    def present_in_docs(token: str) -> bool:
        return token.lower() in readme_text.lower() if readme_text else False

    # Commands
    checks["has_init_cmd"] = present_in_code("init")
    checks["has_list_cmd"] = present_in_code("list")
    checks["has_config_cmd"] = present_in_code("config")
    checks["has_process_cmd"] = present_in_code("process")
    # completion can appear in code or README
    checks["has_completion_cmd"] = present_in_code("completion") or present_in_docs("completion")

    # Config get/set (code or README)
    has_get = present_in_code("get") or present_in_docs("get")
    has_set = present_in_code("set") or present_in_docs("set")
    checks["has_config_get_set_doc"] = has_get and has_set

    # Standard options
    checks["has_help_option"] = present_in_code("--help") or present_in_code("-h")
    checks["has_version_option"] = present_in_code("--version") or present_in_code("-v")

    # Output mode flags
    checks["has_json_flag"] = present_in_code("--json") or present_in_docs("--json")
    checks["has_quiet_flag"] = present_in_code("--quiet") or present_in_docs("--quiet")

    # stdin support: check for 'stdin' or 'standard input' mention in code or README
    mentions_stdin = ("stdin" in all_code_text.lower()) or ("standard input" in all_code_text.lower()) or present_in_docs("stdin") or present_in_docs("standard input")
    checks["mentions_stdin_support"] = mentions_stdin

    # Helpful error handling: look for sys.exit(1|2...), process.exit(1|2...), or "raise typer.Exit" patterns
    error_exit_patterns = [
        r"sys\.exit\(\s*[1-9]\d*\s*\)",
        r"process\.exit\(\s*[1-9]\d*\s*\)",
        r"raise\s+SystemExit\(\s*[1-9]\d*\s*\)",
        r"typer\.Exit\(",
        r"click\.Exit\(",
        r"raise\s+typer\.Exit",
    ]
    has_error_exit_calls = False
    for pat in error_exit_patterns:
        if re.search(pat, all_code_text):
            has_error_exit_calls = True
            break
    checks["has_error_exit_calls"] = has_error_exit_calls

    # README content checks
    def readme_has(keyword: str) -> bool:
        return keyword.lower() in readme_text.lower() if readme_text else False

    checks["readme_has_installation"] = readme_has("Installation")
    checks["readme_has_usage"] = readme_has("Usage")
    checks["readme_has_examples"] = readme_has("Examples")
    checks["readme_has_configuration"] = readme_has("Configuration")
    checks["readme_has_exit_codes"] = readme_has("Exit codes") or readme_has("Exit Codes")

    # precedence and locations hints
    precedence_ok = False
    if readme_text:
        if "precedence" in readme_text.lower():
            # look for hints of user/system config locations
            location_hints = ["XDG", "~/.config", ".config", "HOME", "home directory", "APPDATA", "USERPROFILE", "%APPDATA%"]
            if any(h.lower() in readme_text.lower() for h in location_hints):
                precedence_ok = True
    checks["readme_mentions_precedence_and_locations"] = precedence_ok

    # README example referencing input/sample_projects.json
    checks["readme_example_uses_sample_projects"] = "input/sample_projects.json" in (readme_text or "")

    # README mentions pipelines or stdin
    checks["readme_mentions_pipelines_or_stdin"] = readme_has("stdin") or readme_has("pipe") or readme_has("piping")

    # README mentions JSON and quiet modes
    checks["readme_mentions_json_quiet"] = (readme_has("--json") or readme_has("JSON")) and (readme_has("--quiet") or readme_has("quiet"))

    # Tests presence
    tests_files = []
    if os.path.isdir(tests_dir):
        checks["tests_dir_exists"] = True
        for root, dirs, files in os.walk(tests_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in allowed_exts:
                    tests_files.append(os.path.join(root, fname))
    else:
        checks["tests_dir_exists"] = False

    found_help_ref = False
    found_version_ref = False
    for tf in tests_files:
        try:
            with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                tcontent = f.read()
                if "--help" in tcontent or "-h" in tcontent:
                    found_help_ref = True
                if "--version" in tcontent or "-v" in tcontent:
                    found_version_ref = True
        except Exception:
            continue
    checks["tests_cover_help_version"] = found_help_ref and found_version_ref

    # Path hygiene across all allowed-ext files in project root
    bad_path_found = False
    bad_patterns = [
        "/Users/",
        "/home/",
        "C:\\",
        "C:/",
    ]
    # Also consider generic Windows drive letter patterns like "D:\" etc.
    drive_regex = re.compile(r"[A-Za-z]:\\")
    for f in all_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            if any(bp in content for bp in bad_patterns) or drive_regex.search(content):
                bad_path_found = True
                break
        except Exception:
            # Ignore unreadable files
            continue
    checks["no_machine_specific_paths"] = not bad_path_found

    # Combined pipeline-friendly design: both flags in code and README mentions pipe/stdin
    checks["pipeline_friendly_design"] = checks["has_json_flag"] and checks["has_quiet_flag"] and checks["readme_mentions_pipelines_or_stdin"]

    # Scoring
    weights = {
        # Structure (0.30)
        "projctl_dir_exists": 0.05,
        "readme_exists": 0.05,
        "has_source_dir": 0.05,
        "has_cli_entry_file": 0.05,
        "has_packaging_metadata": 0.10,
        # Commands and flags (0.35)
        "has_init_cmd": 0.03,
        "has_list_cmd": 0.03,
        "has_config_cmd": 0.03,
        "has_process_cmd": 0.03,
        "has_completion_cmd": 0.03,
        "has_config_get_set_doc": 0.04,
        "has_help_option": 0.03,
        "has_version_option": 0.03,
        "has_json_flag": 0.03,
        "has_quiet_flag": 0.03,
        "mentions_stdin_support": 0.04,
        "has_error_exit_calls": 0.03,
        # README (0.25)
        "readme_has_installation": 0.025,
        "readme_has_usage": 0.025,
        "readme_has_examples": 0.025,
        "readme_has_configuration": 0.025,
        "readme_has_exit_codes": 0.025,
        "readme_mentions_precedence_and_locations": 0.05,
        "readme_example_uses_sample_projects": 0.025,
        "readme_mentions_pipelines_or_stdin": 0.025,
        "readme_mentions_json_quiet": 0.025,
        # Tests (0.05)
        "tests_dir_exists": 0.025,
        "tests_cover_help_version": 0.025,
        # Hygiene (0.05)
        "no_machine_specific_paths": 0.05,
        # Combined pipeline-friendly design (0.0 extra, tracked only)
        "pipeline_friendly_design": 0.0,
    }

    # If projctl_dir_exists is False, force all dependent checks to remain False (already initialized)
    # Compute reward as weighted sum
    reward = 0.0
    for key, passed in checks.items():
        w = weights.get(key, 0.0)
        if passed:
            reward += w

    # Ensure reward is exactly 0.0 if output is empty or missing required artifacts
    # Here we consider "required artifacts" minimally as the project directory and README
    if not checks["projctl_dir_exists"]:
        reward = 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = OrderedDict([("reward", reward)])
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()