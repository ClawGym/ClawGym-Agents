import json
import os
import re
import sys

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

def get_workspace_root():
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # openclaw.secure.json checks
        "secure_json_exists": False,
        "secure_json_valid": False,
        "gateway_bind_loopback": False,
        "gateway_port_18789": False,
        "gateway_auth_mode_token": False,
        "gateway_auth_token_hex64": False,
        "tailscale_mode_serve": False,
        "no_placeholder_token": False,
        "preserved_top_level_keys": False,

        # permissions_fix.txt checks
        "perm_file_exists": False,
        "perm_contains_required_lines": False,

        # ufw_rules.md checks
        "ufw_file_exists": False,
        "ufw_has_required_lines": False,
        "ufw_no_allow_port": False,
        "ufw_tailscale_ok": False,  # only enforced if Tailscale is referenced
        "ufw_has_reason_sentence": False,

        # mdns_disable.txt checks
        "mdns_file_exists": False,
        "mdns_line_ok": False,

        # audit_plan.md checks
        "audit_plan_exists": False,
        "audit_has_node_version": False,
        "audit_has_security_audit": False,
        "audit_has_ssh_and_lockout": False,
        "audit_has_rollback_or_restore": False,
    }

    # Paths
    input_config_path = os.path.join(input_dir, "openclaw.json")
    secure_json_path = os.path.join(output_dir, "openclaw.secure.json")
    perm_path = os.path.join(output_dir, "permissions_fix.txt")
    ufw_path = os.path.join(output_dir, "ufw_rules.md")
    mdns_path = os.path.join(output_dir, "mdns_disable.txt")
    audit_path = os.path.join(output_dir, "audit_plan.md")

    # Load input config (for preserved_top_level_keys)
    input_config, input_err = load_json_file(input_config_path)

    # 1) Validate openclaw.secure.json
    if os.path.isfile(secure_json_path):
        checks["secure_json_exists"] = True
        raw_content, raw_err = read_text(secure_json_path)
        out_config, out_err = load_json_file(secure_json_path)
        if out_config is not None and out_err is None:
            checks["secure_json_valid"] = True

            # gateway.bind == "loopback"
            try:
                bind_val = out_config.get("gateway", {}).get("bind", None)
                if isinstance(bind_val, str) and bind_val == "loopback":
                    checks["gateway_bind_loopback"] = True
            except Exception:
                pass

            # gateway.port == 18789 (numeric)
            try:
                port_val = out_config.get("gateway", {}).get("port", None)
                if isinstance(port_val, int) and port_val == 18789:
                    checks["gateway_port_18789"] = True
            except Exception:
                pass

            # auth mode/token checks
            try:
                auth = out_config.get("gateway", {}).get("auth", {})
                mode = auth.get("mode", None)
                token = auth.get("token", None)
                if isinstance(mode, str) and mode == "token":
                    checks["gateway_auth_mode_token"] = True
                if isinstance(token, str) and re.fullmatch(r"[0-9a-fA-F]{64}", token or ""):
                    checks["gateway_auth_token_hex64"] = True
            except Exception:
                pass

            # tailscale.mode == "serve" either under gateway.tailscale or top-level tailscale
            ts_ok = False
            try:
                gw_ts = out_config.get("gateway", {}).get("tailscale", None)
                if isinstance(gw_ts, dict) and gw_ts.get("mode") == "serve":
                    ts_ok = True
            except Exception:
                pass
            try:
                top_ts = out_config.get("tailscale", None)
                if isinstance(top_ts, dict) and top_ts.get("mode") == "serve":
                    ts_ok = True
            except Exception:
                pass
            if ts_ok:
                checks["tailscale_mode_serve"] = True

            # no placeholder tokens
            try:
                if isinstance(raw_content, str):
                    lc = raw_content.lower()
                    if "your_64_char_hex_token" not in lc and "replace_me" not in lc:
                        checks["no_placeholder_token"] = True
            except Exception:
                pass

            # preserved top-level keys from input
            try:
                if isinstance(input_config, dict):
                    input_keys = set(input_config.keys())
                    out_keys = set(out_config.keys())
                    if input_keys.issubset(out_keys):
                        checks["preserved_top_level_keys"] = True
            except Exception:
                pass

    # 2) Validate permissions_fix.txt
    if os.path.isfile(perm_path):
        checks["perm_file_exists"] = True
        perm_content, _ = read_text(perm_path)
        if isinstance(perm_content, str):
            lines = [ln.strip() for ln in perm_content.splitlines() if ln.strip() != ""]
            required_lines = {
                "chmod 700 ~/.openclaw",
                "chmod 600 ~/.openclaw/openclaw.json",
                "chmod 700 ~/.openclaw/credentials",
            }
            if required_lines.issubset(set(lines)):
                checks["perm_contains_required_lines"] = True

    # 3) Validate ufw_rules.md
    if os.path.isfile(ufw_path):
        checks["ufw_file_exists"] = True
        ufw_content, _ = read_text(ufw_path)
        if isinstance(ufw_content, str):
            # Required lines
            required_ufw = [
                "sudo ufw default deny incoming",
                "sudo ufw default allow outgoing",
                "sudo ufw allow ssh",
                "sudo ufw enable",
            ]
            has_required = all(line in ufw_content for line in required_ufw)
            if has_required:
                checks["ufw_has_required_lines"] = True

            # Must NOT allow gateway port
            if "sudo ufw allow 18789" not in ufw_content:
                checks["ufw_no_allow_port"] = True

            # If mentions Tailscale, must include allow on tailscale0
            lc = ufw_content.lower()
            if "tailscale" in lc:
                if "sudo ufw allow in on tailscale0" in ufw_content:
                    checks["ufw_tailscale_ok"] = True
                else:
                    checks["ufw_tailscale_ok"] = False
            else:
                # Not mentioning tailscale; do not penalize this check, but keep it False so it does not contribute
                checks["ufw_tailscale_ok"] = False

            # Reason sentence: contains "should not" and one of ("open","expose","public")
            reason_ok = ("should not" in lc) and (("open" in lc) or ("expose" in lc) or ("public" in lc))
            if reason_ok:
                checks["ufw_has_reason_sentence"] = True

    # 4) Validate mdns_disable.txt
    if os.path.isfile(mdns_path):
        checks["mdns_file_exists"] = True
        mdns_content, _ = read_text(mdns_path)
        if isinstance(mdns_content, str):
            lines = mdns_content.splitlines()
            if len([ln for ln in lines if ln.strip() != ""]) == 1:
                only_line = [ln for ln in lines if ln.strip() != ""][0].strip()
                if "export CLAWDBOT_DISABLE_BONJOUR=1" in only_line:
                    # Ensure it's exactly single export line
                    if only_line == "export CLAWDBOT_DISABLE_BONJOUR=1":
                        checks["mdns_line_ok"] = True

    # 5) Validate audit_plan.md
    if os.path.isfile(audit_path):
        checks["audit_plan_exists"] = True
        audit_content, _ = read_text(audit_path)
        if isinstance(audit_content, str):
            lc = audit_content.lower()
            # Node.js v22.12.0 substring
            if "node.js v22.12.0" in lc:
                checks["audit_has_node_version"] = True
            # "security audit"
            if "security audit" in lc:
                checks["audit_has_security_audit"] = True
            # "SSH" and lockout
            if ("ssh" in lc) and (("lockout" in lc) or ("lock out" in lc)):
                checks["audit_has_ssh_and_lockout"] = True
            # "rollback" or "restore"
            if ("rollback" in lc) or ("restore" in lc):
                checks["audit_has_rollback_or_restore"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Bound to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()