import json
import os
import re
import sys

def read_text_trim_newlines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
        # Trim only trailing newline characters, keep other whitespace
        return data.rstrip("\r\n")
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        # Split preserving no trailing empty line
        for ln in raw.splitlines():
            if ln.strip() == "":
                # Empty line is invalid per strict requirements
                return None, False
            try:
                obj = json.loads(ln)
                if not isinstance(obj, dict):
                    return None, False
                lines.append(obj)
            except Exception:
                return None, False
        return lines, True
    except Exception:
        return None, False

def is_int_like(x):
    # Ensure x is int but not bool
    return isinstance(x, int) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "messages_file_exists": False,
        "state_file_exists": False,
        "readme_file_exists": False,
        "messages_valid_jsonl": False,
        "initialize_line_valid": False,
        "session_new_line_valid": False,
        "ids_sequential": False,
        "jsonrpc_all_2_0": False,
        "prompts_count_match": False,
        "prompt_lines_valid": False,
        "state_structure_valid": False,
        "state_messageCount_matches": False,
        "sessionId_consistent_with_state": False,
        "readme_mentions_ids_cwd_and_count": False
    }

    # Paths
    prompts_path = os.path.join(input_dir, "prompts.json")
    project_dir_path = os.path.join(input_dir, "project_dir.txt")
    messages_path = os.path.join(output_dir, "messages.jsonl")
    state_path = os.path.join(output_dir, "state.json")
    readme_path = os.path.join(output_dir, "readme.md")

    # Load inputs
    prompts = load_json(prompts_path)
    if isinstance(prompts, list) and all(isinstance(p, str) for p in prompts):
        expected_prompts = prompts
    else:
        expected_prompts = None  # If input invalid, do not award related checks

    cwd_value = read_text_trim_newlines(project_dir_path)

    # Existence checks
    if os.path.isfile(messages_path):
        checks["messages_file_exists"] = True
    if os.path.isfile(state_path):
        checks["state_file_exists"] = True
    if os.path.isfile(readme_path):
        checks["readme_file_exists"] = True

    # Early gating for no-op baseline: if any required file is missing, reward must be 0.0
    # We will still compute other checks where possible, but final reward will be forced to 0.0.
    required_files_present = checks["messages_file_exists"] and checks["state_file_exists"] and checks["readme_file_exists"]

    messages = None
    messages_ok = False
    if checks["messages_file_exists"]:
        messages, messages_ok = parse_jsonl(messages_path)
        if messages_ok and isinstance(messages, list) and len(messages) >= 2:
            checks["messages_valid_jsonl"] = True

    state_data = None
    if checks["state_file_exists"]:
        state_data = load_json(state_path)

    # Validate state structure
    process_ok = False
    session_ok = False
    polling_ok = False
    message_count_ok = False
    if isinstance(state_data, dict):
        process_id = state_data.get("processSessionId")
        opencode_id = state_data.get("opencodeSessionId")
        message_count = state_data.get("messageCount")
        polling = state_data.get("pollingPlan")

        if isinstance(process_id, str) and re.fullmatch(r"bg_\d+", process_id or ""):
            process_ok = True
        if isinstance(opencode_id, str) and re.fullmatch(r"sess_[a-z0-9]{22}", opencode_id or ""):
            session_ok = True
        if isinstance(polling, dict):
            if polling.get("intervalSeconds") == 2 and polling.get("maxPolls") == 150:
                polling_ok = True
        if is_int_like(message_count) and message_count >= 0:
            message_count_ok = True

        if process_ok and session_ok and polling_ok and message_count_ok:
            checks["state_structure_valid"] = True

    # If messages parsed, perform detailed validations
    if checks["messages_valid_jsonl"]:
        # IDs sequential
        ids = [m.get("id") for m in messages]
        ids_sequential = all(is_int_like(i) for i in ids) and ids == list(range(len(messages)))
        if ids_sequential:
            checks["ids_sequential"] = True

        # All jsonrpc == "2.0"
        jsonrpc_ok = all(m.get("jsonrpc") == "2.0" for m in messages)
        if jsonrpc_ok:
            checks["jsonrpc_all_2_0"] = True

        # First line: initialize
        first = messages[0]
        init_ok = (
            first.get("method") == "initialize" and
            first.get("id") == 0 and
            first.get("jsonrpc") == "2.0"
        )
        params = first.get("params")
        if init_ok and isinstance(params, dict):
            proto_ok = params.get("protocolVersion") == 1
            cc = params.get("clientCapabilities")
            ci = params.get("clientInfo")
            cc_ok = False
            ci_ok = False
            if isinstance(cc, dict):
                fs = cc.get("fs")
                term = cc.get("terminal")
                fs_ok = isinstance(fs, dict) and fs.get("readTextFile") is True and fs.get("writeTextFile") is True
                term_ok = term is True
                cc_ok = fs_ok and term_ok
            if isinstance(ci, dict):
                ci_ok = ci.get("name") == "clawdbot" and ci.get("title") == "Clawdbot" and ci.get("version") == "1.0.0"
            if proto_ok and cc_ok and ci_ok:
                checks["initialize_line_valid"] = True

        # Second line: session/new
        second = messages[1]
        sn_ok = (
            second.get("method") == "session/new" and
            second.get("id") == 1 and
            second.get("jsonrpc") == "2.0"
        )
        sn_params = second.get("params")
        if sn_ok and isinstance(sn_params, dict) and isinstance(cwd_value, str):
            cwd_ok = sn_params.get("cwd") == cwd_value
            mcp_ok = isinstance(sn_params.get("mcpServers"), list) and len(sn_params.get("mcpServers")) == 0
            if cwd_ok and mcp_ok:
                checks["session_new_line_valid"] = True

        # Prompt lines
        prompt_lines = messages[2:] if len(messages) >= 2 else []
        prompts_expected_len = len(expected_prompts) if isinstance(expected_prompts, list) else None
        if prompts_expected_len is not None and len(prompt_lines) == prompts_expected_len:
            checks["prompts_count_match"] = True

        # Validate each prompt line
        prompt_lines_valid = True
        sessionId_consistent = True
        if prompts_expected_len is not None and session_ok:
            state_session_id = state_data.get("opencodeSessionId") if isinstance(state_data, dict) else None
            for idx, (msg, expected_text) in enumerate(zip(prompt_lines, expected_prompts)):
                # Expected id starts at 2
                expected_id = 2 + idx
                if not (
                    msg.get("method") == "session/prompt" and
                    is_int_like(msg.get("id")) and msg.get("id") == expected_id and
                    msg.get("jsonrpc") == "2.0"
                ):
                    prompt_lines_valid = False
                    break
                p = msg.get("params")
                if not isinstance(p, dict):
                    prompt_lines_valid = False
                    break
                # sessionId equals state opencodeSessionId
                if p.get("sessionId") != state_session_id:
                    sessionId_consistent = False
                    prompt_lines_valid = False
                    break
                prompt = p.get("prompt")
                if not (isinstance(prompt, list) and len(prompt) == 1 and isinstance(prompt[0], dict)):
                    prompt_lines_valid = False
                    break
                item = prompt[0]
                if not (item.get("type") == "text" and isinstance(item.get("text"), str) and item.get("text") == expected_text):
                    prompt_lines_valid = False
                    break
        else:
            prompt_lines_valid = False
            sessionId_consistent = False

        if prompt_lines_valid:
            checks["prompt_lines_valid"] = True
        if sessionId_consistent:
            checks["sessionId_consistent_with_state"] = True

        # state.messageCount matches number of request lines in messages.jsonl
        if isinstance(state_data, dict) and is_int_like(state_data.get("messageCount")):
            if state_data.get("messageCount") == len(messages):
                checks["state_messageCount_matches"] = True

    # Validate readme includes required mentions
    if checks["readme_file_exists"] and isinstance(state_data, dict):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
        except Exception:
            readme_text = ""
        pid = state_data.get("processSessionId")
        sid = state_data.get("opencodeSessionId")
        msg_count_in_file = None
        if checks.get("messages_valid_jsonl"):
            msg_count_in_file = len(messages)
        contains_ids = isinstance(pid, str) and pid in readme_text and isinstance(sid, str) and sid in readme_text
        contains_cwd = isinstance(cwd_value, str) and cwd_value in readme_text
        contains_count = isinstance(msg_count_in_file, int) and (str(msg_count_in_file) in readme_text)
        if contains_ids and contains_cwd and contains_count:
            checks["readme_mentions_ids_cwd_and_count"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_files_present:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()