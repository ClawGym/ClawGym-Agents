import json
import os
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_integer_like_number(x):
    # Must be a JSON number, not a string, and integer-like
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return True
    if isinstance(x, float):
        return abs(x - int(x)) < 1e-9
    return False

def contains_acl_command(commands, pattern_required_parts, required_path, require_recursive=False):
    """
    commands: list of strings
    pattern_required_parts: list of substrings that must be present
    required_path: path string that must appear in the command
    require_recursive: if True, ensure '-R' appears
    """
    for cmd in commands:
        if not isinstance(cmd, str):
            continue
        s = cmd.strip()
        if require_recursive and "-R" not in s:
            continue
        ok = True
        for part in pattern_required_parts:
            if part not in s:
                ok = False
                break
        if not ok:
            continue
        if required_path not in s:
            # Also accept if quoted path appears
            if f'"{required_path}"' not in s and f"'{required_path}'" not in s:
                continue
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Read inputs
    version_path = os.path.join(input_dir, "obsidian_version.txt")
    vault_path_path = os.path.join(input_dir, "vault_path.txt")
    policy_yaml_path = os.path.join(input_dir, "policy.yaml")  # referenced for context; not scored directly

    version_text = read_text_file(version_path)
    vault_path_text = read_text_file(vault_path_path)
    # Trim inputs
    version_value = version_text.strip() if isinstance(version_text, str) else None
    vault_path_value = vault_path_text.strip() if isinstance(vault_path_text, str) else None

    vault_basename = None
    if vault_path_value:
        # Normalize trailing slashes (basename of "/" is "", but vault_path should be absolute non-root or /root)
        vp = vault_path_value[:-1] if vault_path_value.endswith("/") and vault_path_value != "/" else vault_path_value
        vault_basename = os.path.basename(vp) if vp else ""

    # Initialize checks
    checks = {}
    # Install plan checks
    checks["install_plan_exists"] = False
    checks["install_plan_version"] = False
    checks["install_plan_download_url"] = False
    checks["install_plan_packages"] = False
    checks["install_plan_create_user"] = False
    checks["install_plan_wrapper_path"] = False
    checks["install_plan_ownership_change"] = False

    # Obsidian config checks
    checks["obsidian_config_exists"] = False
    checks["obsidian_config_cli_true"] = False
    checks["obsidian_config_vault_key"] = False
    checks["obsidian_config_vault_fields"] = False

    # Wrapper python checks
    checks["wrapper_py_exists"] = False
    checks["wrapper_py_target_path"] = False
    checks["wrapper_py_xvfb_sequence"] = False
    checks["wrapper_py_su_user"] = False
    checks["wrapper_py_cd_vault"] = False
    checks["wrapper_py_sets_executable"] = False

    # ACL plan checks
    checks["acl_plan_exists"] = False
    checks["acl_plan_commands_array"] = False
    checks["acl_plan_recursive_rwx"] = False
    checks["acl_plan_recursive_default_rwx"] = False
    checks["acl_plan_root_traversal"] = False  # only required if /root vault; otherwise non-blocking
    checks["acl_plan_no_chown"] = False

    # Verification.txt checks
    checks["verification_exists"] = False
    checks["verification_has_commands"] = False

    # Report.md checks
    checks["report_exists"] = False
    checks["report_contains_version"] = False
    checks["report_contains_wrapper_path"] = False
    checks["report_contains_vault_path"] = False
    checks["report_contains_all_verification_cmds"] = False

    # Paths to outputs
    install_plan_file = os.path.join(output_dir, "install_plan.json")
    obsidian_config_file = os.path.join(output_dir, "obsidian_config.json")
    wrapper_py_file = os.path.join(output_dir, "obsidian_wrapper.py")
    acl_plan_file = os.path.join(output_dir, "acl_plan.json")
    verification_file = os.path.join(output_dir, "verification.txt")
    report_file = os.path.join(output_dir, "report.md")

    # 1) install_plan.json
    plan = read_json_file(install_plan_file)
    if isinstance(plan, dict):
        checks["install_plan_exists"] = True
        # version
        if version_value is not None and plan.get("obsidian_version") == version_value:
            checks["install_plan_version"] = True
        # download_url
        expected_url = None
        if version_value:
            expected_url = f"https://github.com/obsidianmd/obsidian-releases/releases/download/v{version_value}/obsidian_{version_value}_amd64.deb"
        if expected_url and plan.get("download_url") == expected_url:
            checks["install_plan_download_url"] = True
        # packages includes curl, xvfb, acl, libasound2
        packages = plan.get("packages")
        if isinstance(packages, list):
            lower_pkgs = [str(p).strip().lower() for p in packages]
            required = {"curl", "xvfb", "acl", "libasound2"}
            if required.issubset(set(lower_pkgs)):
                checks["install_plan_packages"] = True
        # create_user
        if plan.get("create_user") == "obsidian":
            checks["install_plan_create_user"] = True
        # wrapper_path
        if plan.get("wrapper_path") == "/usr/local/bin/obs":
            checks["install_plan_wrapper_path"] = True
        # ownership_change == "none"
        if plan.get("ownership_change") == "none":
            checks["install_plan_ownership_change"] = True

    # 2) obsidian_config.json
    config = read_json_file(obsidian_config_file)
    if isinstance(config, dict):
        checks["obsidian_config_exists"] = True
        if config.get("cli") is True:
            checks["obsidian_config_cli_true"] = True
        vaults = config.get("vaults")
        if isinstance(vaults, dict) and vault_basename is not None and vault_basename in vaults:
            checks["obsidian_config_vault_key"] = True
            v_entry = vaults.get(vault_basename, {})
            ok_path = (v_entry.get("path") == vault_path_value)
            ok_open = (v_entry.get("open") is True)
            ok_ts = is_integer_like_number(v_entry.get("ts"))
            if ok_path and ok_open and ok_ts:
                checks["obsidian_config_vault_fields"] = True

    # 3) obsidian_wrapper.py
    wrapper_content = read_text_file(wrapper_py_file)
    if isinstance(wrapper_content, str):
        checks["wrapper_py_exists"] = True
        if "/usr/local/bin/obs" in wrapper_content:
            checks["wrapper_py_target_path"] = True
        if "xvfb-run -a /usr/bin/obsidian --disable-gpu" in wrapper_content:
            checks["wrapper_py_xvfb_sequence"] = True
        if "su - obsidian -c" in wrapper_content:
            checks["wrapper_py_su_user"] = True
        if vault_path_value and f"cd {vault_path_value}" in wrapper_content:
            checks["wrapper_py_cd_vault"] = True
        # Evidence of setting executable permissions
        if "os.chmod" in wrapper_content or "chmod" in wrapper_content:
            checks["wrapper_py_sets_executable"] = True

    # 4) acl_plan.json
    acl = read_json_file(acl_plan_file)
    if isinstance(acl, dict):
        checks["acl_plan_exists"] = True
        commands = acl.get("commands")
        if isinstance(commands, list) and all(isinstance(x, str) for x in commands):
            checks["acl_plan_commands_array"] = True
            # Must include recursive rwx and default rwx for vault path
            if vault_path_value:
                rwx_ok = contains_acl_command(
                    commands,
                    ["setfacl", "-m", "u:obsidian:rwx"],
                    vault_path_value,
                    require_recursive=True
                )
                d_rwx_ok = contains_acl_command(
                    commands,
                    ["setfacl", "-m", "d:u:obsidian:rwx"],
                    vault_path_value,
                    require_recursive=True
                )
                checks["acl_plan_recursive_rwx"] = rwx_ok
                checks["acl_plan_recursive_default_rwx"] = d_rwx_ok

                # If vault under /root or is /root, must include traversal ACL on /root
                needs_root_traversal = (vault_path_value == "/root" or vault_path_value.startswith("/root/"))
                if needs_root_traversal:
                    root_traversal_ok = contains_acl_command(
                        commands,
                        ["setfacl", "-m", "u:obsidian:--x", "/root"],
                        "/root",
                        require_recursive=False
                    )
                    checks["acl_plan_root_traversal"] = root_traversal_ok
                else:
                    # Not required; passing this check by default for non-/root vaults
                    checks["acl_plan_root_traversal"] = True

            # None may contain "chown"
            lower_concat = "\n".join(commands).lower()
            checks["acl_plan_no_chown"] = ("chown" not in lower_concat)

    # 5) verification.txt
    ver_text = read_text_file(verification_file)
    required_ver_cmds = [
        'obs help',
        'obs vault',
        'obs daily:path',
        'obs daily:append content="skill verification"',
        'obs daily:read',
        'obs search query="skill verification"',
    ]
    if isinstance(ver_text, str):
        checks["verification_exists"] = True
        lines = [ln.strip() for ln in ver_text.splitlines() if ln.strip() != ""]
        has_all = all(cmd in lines for cmd in required_ver_cmds)
        checks["verification_has_commands"] = has_all

    # 6) report.md
    report_text = read_text_file(report_file)
    if isinstance(report_text, str):
        checks["report_exists"] = True
        if version_value and version_value in report_text:
            checks["report_contains_version"] = True
        if "/usr/local/bin/obs" in report_text:
            checks["report_contains_wrapper_path"] = True
        if vault_path_value and vault_path_value in report_text:
            checks["report_contains_vault_path"] = True
        has_all_cmds_in_report = all(cmd in report_text for cmd in required_ver_cmds)
        checks["report_contains_all_verification_cmds"] = has_all_cmds_in_report

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline if output/ is empty or missing artifacts => reward should be 0.0
    # Our fraction already yields 0.0 if nothing exists.

    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()