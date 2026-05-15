import json
import os
import sys
import re
from copy import deepcopy

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def deep_equal(a, b):
    return a == b

def list_contains_dict(lst, target):
    for item in lst:
        if item == target:
            return True
    return False

def find_agent_entry(agents_list, agent_id):
    for e in agents_list:
        if isinstance(e, dict) and e.get("id") == agent_id:
            return e
    return None

def unique_list(lst):
    seen = set()
    for x in lst:
        if x in seen:
            return False
        seen.add(x)
    return True

def preserved_unrelated_fields(input_cfg, updated_cfg):
    # Top-level keys unchanged excluding modified sections
    modified_top = {"agents", "bindings", "channels", "tools"}
    for k, v in input_cfg.items():
        if k in modified_top:
            continue
        if k not in updated_cfg:
            return False
        if not deep_equal(v, updated_cfg[k]):
            return False

    # Agents: all original entries present and unchanged (on core fields)
    in_agents_list = (((input_cfg.get("agents") or {}).get("list")) or [])
    up_agents_list = (((updated_cfg.get("agents") or {}).get("list")) or [])
    for orig in in_agents_list:
        if not isinstance(orig, dict):
            return False
        match = find_agent_entry(up_agents_list, orig.get("id"))
        if match is None:
            return False
        # Compare core fields for unchanged values
        for key in ["id", "name", "workspace", "agentDir"]:
            if orig.get(key) != match.get(key):
                return False

    # Bindings: all original binding objects are still present (as deep-equal objects)
    in_bindings = input_cfg.get("bindings") or []
    up_bindings = updated_cfg.get("bindings") or []
    for orig_b in in_bindings:
        if not list_contains_dict(up_bindings, orig_b):
            return False

    # Channels: unchanged except for addition of new telegram account
    in_channels = input_cfg.get("channels")
    up_channels = updated_cfg.get("channels")
    if in_channels is None:
        # If input had no channels, nothing to preserve here
        return True

    if up_channels is None:
        return False

    # For channel keys other than 'telegram', deep-equal
    for ch_key, ch_val in in_channels.items():
        if ch_key != "telegram":
            if ch_key not in up_channels or not deep_equal(ch_val, up_channels[ch_key]):
                return False

    in_tel = in_channels.get("telegram")
    up_tel = up_channels.get("telegram")
    if in_tel is None:
        # If no telegram in input, nothing else to preserve
        return True
    if up_tel is None:
        return False

    # For telegram subkeys other than 'accounts', deep-equal
    for t_key, t_val in in_tel.items():
        if t_key != "accounts":
            if t_key not in up_tel or not deep_equal(t_val, up_tel[t_key]):
                return False

    # For accounts: ensure all existing accounts are preserved exactly
    in_accounts = (in_tel.get("accounts") or {})
    up_accounts = (up_tel.get("accounts") or {})
    for acc_key, acc_val in in_accounts.items():
        if acc_key not in up_accounts or not deep_equal(acc_val, up_accounts[acc_key]):
            return False

    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    input_config_path = os.path.join(input_dir, "openclaw.json")
    input_params_path = os.path.join(input_dir, "params.json")
    updated_config_path = os.path.join(output_dir, "openclaw.updated.json")
    validation_json_path = os.path.join(output_dir, "validation.json")

    # Initialize checks
    checks = {
        "has_updated_json": False,
        "valid_json": False,
        "agent_entry_correct": False,
        "bindings_entry_correct": False,
        "telegram_account_correct": False,
        "allow_from_is_string": False,
        "tools_agentToAgent_correct": False,
        "sessions_visibility_correct": False,
        "no_duplicate_allow_entries": False,
        "preserved_unrelated_fields": False,
        "soul_md_ok": False,
        "agents_md_ok": False,
        "change_log_ok": False,
        "validation_json_ok": False
    }

    params = load_json(input_params_path)
    input_cfg = load_json(input_config_path)
    updated_cfg = None

    # Derive expected values if params available
    agent_id = None
    agent_name = None
    bot_token = None
    allow_from = None
    description = None

    if isinstance(params, dict):
        agent_id = params.get("agent_id")
        agent_name = params.get("agent_name")
        bot_token = params.get("bot_token")
        allow_from = params.get("allow_from")
        description = params.get("description")

    # Check updated JSON existence and validity
    if os.path.isfile(updated_config_path):
        checks["has_updated_json"] = True
        updated_cfg = load_json(updated_config_path)
        if isinstance(updated_cfg, dict):
            checks["valid_json"] = True

    # Proceed with content checks only if we have valid JSON and required params
    if checks["valid_json"] and all([agent_id, agent_name, bot_token is not None, allow_from is not None, description is not None]):
        # 1) agents.list entry
        agents_list = (((updated_cfg.get("agents") or {}).get("list")) or [])
        new_entry = find_agent_entry(agents_list, agent_id)
        expected_workspace = f"state/workspace-{agent_id}"
        expected_agent_dir = f"state/agents/{agent_id}/agent"
        if new_entry is not None:
            conds = [
                new_entry.get("name") == agent_name,
                new_entry.get("workspace") == expected_workspace,
                new_entry.get("agentDir") == expected_agent_dir
            ]
            # Ensure exactly one entry for this id
            count_id = sum(1 for e in agents_list if isinstance(e, dict) and e.get("id") == agent_id)
            if all(conds) and count_id == 1:
                checks["agent_entry_correct"] = True

        # 2) bindings entry
        bindings = updated_cfg.get("bindings") or []
        b_ok = False
        for b in bindings:
            if not isinstance(b, dict):
                continue
            if b.get("agentId") == agent_id:
                match = b.get("match") or {}
                if match.get("channel") == "telegram" and match.get("accountId") == agent_id:
                    b_ok = True
                    break
        checks["bindings_entry_correct"] = b_ok

        # 3) channels.telegram.accounts entry
        channels = updated_cfg.get("channels") or {}
        telegram = channels.get("telegram") or {}
        accounts = telegram.get("accounts") or {}
        acct = accounts.get(agent_id)
        tel_ok = False
        allow_from_is_str = False
        if isinstance(acct, dict):
            enabled_ok = (acct.get("enabled") is True)
            bot_ok = (acct.get("botToken") == bot_token)
            dm_ok = (acct.get("dmPolicy") == "pairing")
            gp_ok = (acct.get("groupPolicy") == "allowlist")
            streaming_ok = (acct.get("streaming") == "off")
            af = acct.get("allowFrom")
            af_ok = False
            if isinstance(af, list) and len(af) >= 1:
                allow_from_is_str = isinstance(af[0], str)
                af_ok = (af[0] == str(allow_from))
            tel_ok = all([enabled_ok, bot_ok, dm_ok, gp_ok, streaming_ok, af_ok])
        checks["telegram_account_correct"] = tel_ok
        checks["allow_from_is_string"] = allow_from_is_str

        # 4) tools.agentToAgent and sessions.visibility
        tools = updated_cfg.get("tools") or {}
        a2a = tools.get("agentToAgent") or {}
        enabled_true = (a2a.get("enabled") is True)
        allow = a2a.get("allow")
        a2a_ok = False
        no_dups = False
        if isinstance(allow, list):
            # exactly once for 'main' and agent_id
            count_main = sum(1 for x in allow if x == "main")
            count_new = sum(1 for x in allow if x == agent_id)
            no_dups = unique_list(allow)
            if enabled_true and count_main == 1 and count_new == 1:
                a2a_ok = True
        checks["tools_agentToAgent_correct"] = a2a_ok
        checks["no_duplicate_allow_entries"] = no_dups

        sessions = tools.get("sessions") or {}
        vis_ok = (sessions.get("visibility") == "all")
        checks["sessions_visibility_correct"] = vis_ok

        # 5) Preservation of unrelated fields
        if isinstance(input_cfg, dict):
            checks["preserved_unrelated_fields"] = preserved_unrelated_fields(input_cfg, updated_cfg)

        # 6) SOUL.md
        soul_path = os.path.join(output_dir, f"workspace-{agent_id}", "SOUL.md")
        soul_txt = read_text(soul_path)
        if soul_txt is not None:
            # Header
            header_ok = re.search(rf"^#\s*{re.escape(agent_name)}\s*$", soul_txt, re.MULTILINE) is not None
            # Identity sentence exact as spec
            identity_sentence = f"You are {agent_name}, {description}."
            identity_ok = (identity_sentence in soul_txt)
            # Core Responsibilities contains description
            core_ok = ("Core Responsibilities" in soul_txt) and (description in soul_txt)
            # Personality bullets contain three items
            p1 = re.search(r"^-+\s*Action-oriented", soul_txt, re.IGNORECASE | re.MULTILINE) is not None or ("- Action-oriented" in soul_txt)
            p2 = re.search(r"^-+\s*Proactive reporting", soul_txt, re.IGNORECASE | re.MULTILINE) is not None or ("- Proactive reporting" in soul_txt)
            p3 = re.search(r"^-+\s*Professional", soul_txt, re.IGNORECASE | re.MULTILINE) is not None or ("- Professional" in soul_txt)
            # Rules lines
            r1_sub = "Do not execute high-risk operations without confirmation"
            r2_sub = "Always notify the user before executing operations that require manual approval"
            r1_ok = r1_sub in soul_txt
            r2_ok = r2_sub in soul_txt
            checks["soul_md_ok"] = all([header_ok, identity_ok, core_ok, p1, p2, p3, r1_ok, r2_ok])

        # 7) AGENTS.md
        agents_md_path = os.path.join(output_dir, f"workspace-{agent_id}", "AGENTS.md")
        agents_md_txt = read_text(agents_md_path)
        if agents_md_txt is not None:
            # Mentions main and this agent id
            has_main = re.search(r"\bmain\b", agents_md_txt) is not None
            has_self = re.search(rf"\b{re.escape(agent_id)}\b", agents_md_txt) is not None
            # Collaboration rules steps
            s1 = "Confirm task goal and priority" in agents_md_txt
            s2 = "Break down execution steps" in agents_md_txt
            s3 = ("Execute and record results" in agents_md_txt) or ("Execute and record results" in agents_md_txt)
            s4 = "Report results back to main upon completion" in agents_md_txt
            checks["agents_md_ok"] = all([has_main, has_self, s1, s2, s3, s4])

        # 8) change-log.md mentions required areas
        change_log_path = os.path.join(output_dir, "change-log.md")
        change_txt = read_text(change_log_path)
        if change_txt is not None:
            needed_mentions = [
                "agents.list",
                "bindings",
                "channels.telegram.accounts",
                "tools.agentToAgent",
                "sessions.visibility",
            ]
            checks["change_log_ok"] = all(m in change_txt for m in needed_mentions)

        # 9) validation.json correctness
        val = load_json(validation_json_path)
        if isinstance(val, dict):
            try:
                v_valid_json = bool(val.get("valid_json") is True) == bool(checks["valid_json"])
                v_added = isinstance(val.get("added_agent"), dict) and val["added_agent"].get("id") == agent_id and val["added_agent"].get("name") == agent_name
                v_paths = isinstance(val.get("paths"), dict) and val["paths"].get("new_workspace") == expected_workspace and val["paths"].get("new_agent_dir") == expected_agent_dir
                v_tel_key = val.get("telegram_account_key") == agent_id
                v_allow_from_str = bool(val.get("allow_from_is_string") is True) == bool(checks["allow_from_is_string"])
                v_tools_list = val.get("tools_agentToAgent_contains")
                allow_from_cfg = (a2a.get("allow") if isinstance(a2a, dict) else None)
                v_tools_contains_ok = isinstance(v_tools_list, list) and isinstance(allow_from_cfg, list) and set(v_tools_list) == set(allow_from_cfg)
                v_sess_vis = val.get("sessions_visibility") == "all"
                v_no_dups = bool(val.get("no_duplicate_allow_entries") is True) == bool(checks["no_duplicate_allow_entries"])
                checks["validation_json_ok"] = all([v_valid_json, v_added, v_paths, v_tel_key, v_allow_from_str, v_tools_contains_ok, v_sess_vis, v_no_dups])
            except Exception:
                checks["validation_json_ok"] = False

    # Compute reward: average of True checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output directory missing or empty of required artifacts, ensure reward is 0.0
    # If nothing under output or no files exist, force 0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If no files exist at all in output, zero
        any_output_files = False
        for _, _, files in os.walk(output_dir):
            if files:
                any_output_files = True
                break
        if not any_output_files:
            reward = 0.0

    # Print result JSON as last line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()