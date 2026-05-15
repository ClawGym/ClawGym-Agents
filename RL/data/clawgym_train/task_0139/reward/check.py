import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                if raw.strip() == "":
                    continue
                try:
                    lines.append(json.loads(raw))
                except Exception:
                    return None
        return lines
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is unused but kept for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "requests_exists": False,
        "requests_line_count_4": False,
        "request0_initialize_ok": False,
        "request1_session_new_ok": False,
        "request2_prompt_ok": False,
        "request3_prompt_ok": False,
        "summary_exists": False,
        "summary_fields_ok": False,
    }

    # Defaults and expected values from inputs (used only to verify outputs)
    prompts_expected = []
    config_expected = None

    # Load expected prompts from input
    prompts_path = os.path.join(input_dir, "prompts.jsonl")
    if os.path.isfile(prompts_path):
        prompts_lines = load_jsonl_lines(prompts_path)
        if isinstance(prompts_lines, list):
            for obj in prompts_lines[:2]:
                if isinstance(obj, dict) and "text" in obj and isinstance(obj["text"], str):
                    prompts_expected.append(obj["text"])

    # Load expected clientInfo from config.json
    config_path = os.path.join(input_dir, "config.json")
    if os.path.isfile(config_path):
        cfg = load_json_file(config_path)
        if isinstance(cfg, dict):
            name = cfg.get("name")
            title = cfg.get("title")
            version = cfg.get("version")
            if isinstance(name, str) and isinstance(title, str) and isinstance(version, str):
                config_expected = {"name": name, "title": title, "version": version}

    # Validate requests.jsonl
    requests_path = os.path.join(output_dir, "requests.jsonl")
    requests = None
    if os.path.isfile(requests_path):
        checks["requests_exists"] = True
        requests = load_jsonl_lines(requests_path)
        if isinstance(requests, list) and len(requests) == 4:
            checks["requests_line_count_4"] = True

            # Line 0: initialize
            req0 = requests[0]
            if isinstance(req0, dict):
                conds = []
                conds.append(req0.get("method") == "initialize")
                conds.append(req0.get("id") == 0)
                conds.append(req0.get("jsonrpc") == "2.0")

                params0 = req0.get("params")
                if isinstance(params0, dict):
                    conds.append(params0.get("protocolVersion") == 1)
                    cc = params0.get("clientCapabilities")
                    if isinstance(cc, dict):
                        fs = cc.get("fs")
                        term = cc.get("terminal")
                        conds.append(term is True)
                        if isinstance(fs, dict):
                            conds.append(fs.get("readTextFile") is True)
                            conds.append(fs.get("writeTextFile") is True)
                        else:
                            conds.append(False)
                    else:
                        conds.append(False)
                    # clientInfo from input/config.json
                    ci = params0.get("clientInfo")
                    if isinstance(ci, dict) and isinstance(config_expected, dict):
                        conds.append(ci.get("name") == config_expected["name"])
                        conds.append(ci.get("title") == config_expected["title"])
                        conds.append(ci.get("version") == config_expected["version"])
                    else:
                        conds.append(False)
                else:
                    conds.append(False)

                if all(conds):
                    checks["request0_initialize_ok"] = True

            # Line 1: session/new
            req1 = requests[1]
            if isinstance(req1, dict):
                conds1 = []
                conds1.append(req1.get("method") == "session/new")
                conds1.append(req1.get("id") == 1)
                params1 = req1.get("params")
                if isinstance(params1, dict):
                    conds1.append(params1.get("cwd") == "input/")
                    mcp = params1.get("mcpServers")
                    conds1.append(isinstance(mcp, list))
                else:
                    conds1.append(False)
                if all(conds1):
                    checks["request1_session_new_ok"] = True

            # Line 2: first session/prompt
            req2 = requests[2]
            if isinstance(req2, dict):
                conds2 = []
                conds2.append(req2.get("method") == "session/prompt")
                conds2.append(req2.get("id") == 2)
                params2 = req2.get("params")
                if isinstance(params2, dict):
                    prompt2 = params2.get("prompt")
                    if isinstance(prompt2, list) and len(prompt2) >= 1 and isinstance(prompt2[0], dict):
                        first = prompt2[0]
                        conds2.append(first.get("type") == "text")
                        # Need expected prompt text from input
                        if len(prompts_expected) >= 1:
                            conds2.append(first.get("text") == prompts_expected[0])
                        else:
                            conds2.append(False)
                    else:
                        conds2.append(False)
                else:
                    conds2.append(False)
                if all(conds2):
                    checks["request2_prompt_ok"] = True

            # Line 3: second session/prompt
            req3 = requests[3]
            if isinstance(req3, dict):
                conds3 = []
                conds3.append(req3.get("method") == "session/prompt")
                conds3.append(req3.get("id") == 3)
                params3 = req3.get("params")
                if isinstance(params3, dict):
                    prompt3 = params3.get("prompt")
                    if isinstance(prompt3, list) and len(prompt3) >= 1 and isinstance(prompt3[0], dict):
                        first3 = prompt3[0]
                        conds3.append(first3.get("type") == "text")
                        if len(prompts_expected) >= 2:
                            conds3.append(first3.get("text") == prompts_expected[1])
                        else:
                            conds3.append(False)
                    else:
                        conds3.append(False)
                else:
                    conds3.append(False)
                if all(conds3):
                    checks["request3_prompt_ok"] = True

    # Validate summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary = load_json_file(summary_path)
        if isinstance(summary, dict):
            conds_s = []
            # Required fields
            conds_s.append(summary.get("messageIds") == [0, 1, 2, 3])
            conds_s.append(summary.get("promptsCount") == 2)
            conds_s.append(summary.get("cwd") == "input/")
            ci = summary.get("clientInfo")
            if isinstance(ci, dict) and isinstance(config_expected, dict):
                conds_s.append(ci.get("name") == config_expected["name"])
                conds_s.append(ci.get("title") == config_expected["title"])
                conds_s.append(ci.get("version") == config_expected["version"])
            else:
                conds_s.append(False)
            if all(conds_s):
                checks["summary_fields_ok"] = True

    # Scoring weights
    weights = {
        "requests_exists": 0.10,
        "requests_line_count_4": 0.10,
        "request0_initialize_ok": 0.20,
        "request1_session_new_ok": 0.20,
        "request2_prompt_ok": 0.15,
        "request3_prompt_ok": 0.15,
        "summary_exists": 0.05,
        "summary_fields_ok": 0.05,
    }

    # No-op baseline: if output directory missing or both outputs missing, reward 0.0
    reward = 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            reward += w

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()