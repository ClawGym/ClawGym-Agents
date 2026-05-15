import json
import os
import re
import sys
from typing import Any, Dict, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_first_port(obj: Any) -> Optional[int]:
    # Prefer likely locations then recursive search
    if isinstance(obj, dict):
        for k in ("gateway", "gategway", "gateaway", "gateWay", "gatewayz"):
            if k in obj and isinstance(obj[k], dict):
                v = obj[k].get("port")
                if isinstance(v, int):
                    return v
        if isinstance(obj.get("port"), int):
            return obj.get("port")
        for v in obj.values():
            res = find_first_port(v)
            if res is not None:
                return res
    elif isinstance(obj, list):
        for el in obj:
            res = find_first_port(el)
            if res is not None:
                return res
    return None

def find_first_workspace(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        if isinstance(obj.get("workspace"), str):
            return obj.get("workspace")
        for v in obj.values():
            res = find_first_workspace(v)
            if res:
                return res
    elif isinstance(obj, list):
        for el in obj:
            res = find_first_workspace(el)
            if res:
                return res
    return None

def extract_port_and_workspace(input_path: str) -> (Optional[int], Optional[str]):
    text = read_text(input_path)
    expected_port = None
    expected_workspace = None
    if text is None:
        return None, None
    data = None
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if data is not None:
        expected_port = find_first_port(data)
        expected_workspace = find_first_workspace(data)
    if expected_port is None:
        # Fallback regex for port
        m = re.search(r'"port"\s*:\s*(\d+)', text)
        if m:
            try:
                expected_port = int(m.group(1))
            except Exception:
                expected_port = None
    if expected_workspace is None:
        # Fallback regex for workspace
        m2 = re.search(r'"workspace"\s*:\s*"([^"]+)"', text)
        if m2:
            expected_workspace = m2.group(1)
    return expected_port, expected_workspace

def dict_get(d: Dict, path: list, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

def has_main_agent_with_workspace(config: Dict, expected_workspace: Optional[str]) -> (bool, bool):
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return False, False
    the_list = agents.get("list")
    if not isinstance(the_list, list):
        return False, False
    main_present = False
    main_workspace_ok = False
    # Evaluate defaults workspace as fallback
    defaults_workspace = None
    if isinstance(agents.get("defaults"), dict):
        if isinstance(agents["defaults"].get("workspace"), str):
            defaults_workspace = agents["defaults"]["workspace"]
    for item in the_list:
        if isinstance(item, dict) and item.get("agentId") == "main":
            main_present = True
            # Determine effective main workspace
            effective_ws = None
            if isinstance(item.get("workspace"), str):
                effective_ws = item["workspace"]
            elif defaults_workspace:
                effective_ws = defaults_workspace
            if expected_workspace is None:
                # If we don't know expected, we cannot assert preservation; consider it not preserved
                main_workspace_ok = False
            else:
                main_workspace_ok = (effective_ws == expected_workspace)
            break
    return main_present, main_workspace_ok

def check_bind_auth(config: Dict) -> bool:
    gateway = config.get("gateway", {})
    bind = gateway.get("bind")
    if bind == "lan":
        auth = gateway.get("auth")
        if not isinstance(auth, dict):
            return False
        mode = auth.get("mode")
        if mode not in {"token", "password"}:
            return False
        if mode == "token":
            token = auth.get("token")
            if not isinstance(token, str) or not token.strip():
                return False
            if token.strip() == "change-me-please":
                return False
        if mode == "password":
            password = auth.get("password")
            if not isinstance(password, str) or not password.strip():
                return False
            if password.strip() == "change-me-please":
                return False
        return True
    else:
        # Any non-lan bind is considered safe for this check
        return True

def check_telegram_constraints(config: Dict) -> (bool, bool):
    channels = config.get("channels")
    if not isinstance(channels, dict):
        return True, True
    telegram = channels.get("telegram")
    if telegram is None:
        return True, True
    if not isinstance(telegram, dict):
        return False, False
    # must NOT include botToken and NOT include streaming
    no_secrets = ("botToken" not in telegram) and ("streaming" not in telegram)
    # streamMode if present must be valid
    stream_mode_ok = True
    if "streamMode" in telegram:
        stream_mode_ok = telegram["streamMode"] in {"off", "partial", "block"}
    return no_secrets, stream_mode_ok

def check_notes_keywords(notes_text: str) -> bool:
    if not notes_text:
        return False
    lower = notes_text.lower()
    keywords = ["gateway", "reload", "bind", "agents", "commands", "bottoken", "secret", "unknown"]
    found = set()
    for kw in keywords:
        if kw in lower:
            # special handling: 'bottoken' or 'secret' counts as one, but they are separate here
            found.add(kw)
    # count presence across categories, but require at least 4 distinct hits
    # treat bottoken/secret as separate acceptable hits
    bullet_lines = [ln for ln in notes_text.splitlines() if ln.strip().startswith(("-", "*"))]
    return len(found) >= 4 and len(bullet_lines) >= 1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    broken_input_path = os.path.join(input_dir, "broken_openclaw.json")
    expected_port, expected_workspace = extract_port_and_workspace(broken_input_path)
    if expected_port is None:
        # Fallback to known task hint
        expected_port = 19000

    output_config_path = os.path.join(output_dir, "openclaw_fixed.json")
    fix_notes_path = os.path.join(output_dir, "fix_notes.md")

    checks: Dict[str, bool] = {
        "output_exists": False,
        "json_valid": False,
        "valid_top_level_keys": False,
        "port_preserved": False,
        "reload_valid": False,
        "bind_auth_safe": False,
        "agents_main_present": False,
        "agents_workspace_preserved": False,
        "commands_config_safe": False,
        "telegram_no_bottoken_or_streaming": False,
        "telegram_streammode_valid": False,
        "fix_notes_exists": False,
        "fix_notes_keywords": False,
    }

    config = None
    if os.path.isfile(output_config_path):
        checks["output_exists"] = True
        config = load_json(output_config_path)
        if isinstance(config, dict):
            checks["json_valid"] = True

            # Valid top-level keys subset
            allowed_keys = {
                "gateway", "commands", "agents", "channels",
                "session", "sandbox", "cron", "hooks",
                "tools", "browser", "skills", "models", "env"
            }
            top_keys = set(config.keys())
            if top_keys.issubset(allowed_keys):
                checks["valid_top_level_keys"] = True

            # Port preserved
            if isinstance(dict_get(config, ["gateway", "port"]), int):
                checks["port_preserved"] = (dict_get(config, ["gateway", "port"]) == expected_port)

            # Reload valid
            reload_val = dict_get(config, ["gateway", "reload"])
            if isinstance(reload_val, str) and reload_val in {"hybrid", "hot", "restart", "off"}:
                checks["reload_valid"] = True

            # Bind/auth safety
            checks["bind_auth_safe"] = check_bind_auth(config)

            # Agents checks
            main_present, main_ws_ok = has_main_agent_with_workspace(config, expected_workspace)
            checks["agents_main_present"] = main_present
            # Only mark preserved true if main is present and workspace matches expected when we have expected
            checks["agents_workspace_preserved"] = main_ws_ok if main_present else False

            # Commands config safe (must not be true)
            commands = config.get("commands")
            if isinstance(commands, dict):
                cfg = commands.get("config")
                checks["commands_config_safe"] = (cfg is not True)
            else:
                # Absence is safe
                checks["commands_config_safe"] = True

            # Telegram constraints
            no_secrets, stream_mode_ok = check_telegram_constraints(config)
            checks["telegram_no_bottoken_or_streaming"] = no_secrets
            checks["telegram_streammode_valid"] = stream_mode_ok

    # Fix notes checks
    if os.path.isfile(fix_notes_path):
        checks["fix_notes_exists"] = True
        notes_text = read_text(fix_notes_path) or ""
        checks["fix_notes_keywords"] = check_notes_keywords(notes_text)

    # Compute reward as fraction of checks passed; baseline empty output yields 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()