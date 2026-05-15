import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def flatten_strings(obj):
    strings = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                strings.append(k)
            strings.extend(flatten_strings(v))
    elif isinstance(obj, list):
        for it in obj:
            strings.extend(flatten_strings(it))
    return strings

def contains_disallowed_host(text):
    if not isinstance(text, str):
        return False
    t = text.lower()
    disallowed = [
        "api.openai.com",
        "openai.com",
        "platform.openai.com",
        "openrouter.ai",
        "anthropic.com",
        "cohere.ai",
        "ai.googleapis.com",
    ]
    return any(s in t for s in disallowed)

def last_non_empty_print(obj):
    # Only print one JSON object as the last non-empty line
    print(json.dumps(obj))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks as False
    checks = {
        # migration_plan.json checks
        "mp_exists": False,
        "mp_json_valid": False,
        "mp_has_required_keys": False,
        "mp_base_url_ok": False,
        "mp_endpoints_ok": False,
        "mp_has_reachability_step": False,
        "mp_no_cloud_hosts": False,

        # chat_smoke.json checks
        "chat_exists": False,
        "chat_json_valid": False,
        "chat_has_fields": False,
        "chat_model_placeholder_ok": False,
        "chat_messages_ready_ok": False,
        "chat_temperature_zero": False,

        # embeddings_smoke.json checks
        "emb_exists": False,
        "emb_json_valid": False,
        "emb_has_fields": False,
        "emb_model_placeholder_ok": False,
        "emb_input_nonempty_array": False,

        # client_example.py checks
        "client_exists": False,
        "client_contains_base_url": False,
        "client_contains_model_and_messages": False,
        "client_contains_ready": False,
        "client_no_cloud_hosts": False,

        # troubleshooting.md checks
        "trouble_exists": False,
        "trouble_mentions_baseurl_or_port": False,
        "trouble_mentions_model_not_found": False,
        "trouble_mentions_empty": False,
        "trouble_mentions_first_token": False,
        "trouble_mentions_embeddings": False,
    }

    # 1) migration_plan.json
    mp_path = os.path.join(output_dir, "migration_plan.json")
    if os.path.isfile(mp_path):
        checks["mp_exists"] = True
        mp_text = read_text(mp_path)
        mp_json = load_json(mp_path)
        if mp_json is not None and isinstance(mp_json, dict):
            checks["mp_json_valid"] = True
            # Required keys
            base_url = mp_json.get("base_url")
            steps = mp_json.get("steps")
            endpoints = mp_json.get("endpoints")
            if isinstance(base_url, str) and isinstance(steps, list) and isinstance(endpoints, list):
                checks["mp_has_required_keys"] = True
                # base_url must be exact
                if base_url == "http://localhost:1234/v1":
                    checks["mp_base_url_ok"] = True
                # endpoints must include "chat/completions", "responses", "embeddings"
                def has_endpoint_keyword(target):
                    return any(isinstance(e, str) and (target in e) for e in endpoints)
                if has_endpoint_keyword("chat/completions") and has_endpoint_keyword("responses") and has_endpoint_keyword("embeddings"):
                    checks["mp_endpoints_ok"] = True
                # steps must include a reachability check referencing "/v1/models"
                step_strings = flatten_strings(steps)
                if any("/v1/models" in s for s in step_strings if isinstance(s, str)):
                    checks["mp_has_reachability_step"] = True
            # no cloud hostnames anywhere in file text
            if isinstance(mp_text, str) and not contains_disallowed_host(mp_text):
                checks["mp_no_cloud_hosts"] = True

    # 2) chat_smoke.json
    chat_path = os.path.join(output_dir, "chat_smoke.json")
    if os.path.isfile(chat_path):
        checks["chat_exists"] = True
        chat_json = load_json(chat_path)
        if chat_json is not None and isinstance(chat_json, dict):
            checks["chat_json_valid"] = True
            model = chat_json.get("model")
            messages = chat_json.get("messages")
            temperature = chat_json.get("temperature")
            if isinstance(model, str) and isinstance(messages, list):
                checks["chat_has_fields"] = True
                if "LOCAL_" in model:
                    checks["chat_model_placeholder_ok"] = True
                # messages must include a user message with "READY" in content
                found_ready = False
                for m in messages:
                    if isinstance(m, dict):
                        role = m.get("role")
                        content = m.get("content")
                        if isinstance(role, str) and isinstance(content, str):
                            if role.lower() == "user" and ("ready" in content.lower()):
                                found_ready = True
                                break
                if found_ready:
                    checks["chat_messages_ready_ok"] = True
            # temperature must be 0
            if temperature == 0 or temperature == 0.0:
                checks["chat_temperature_zero"] = True

    # 3) embeddings_smoke.json
    emb_path = os.path.join(output_dir, "embeddings_smoke.json")
    if os.path.isfile(emb_path):
        checks["emb_exists"] = True
        emb_json = load_json(emb_path)
        if emb_json is not None and isinstance(emb_json, dict):
            checks["emb_json_valid"] = True
            model = emb_json.get("model")
            inp = emb_json.get("input")
            if isinstance(model, str) and isinstance(inp, list):
                checks["emb_has_fields"] = True
                if "LOCAL_" in model:
                    checks["emb_model_placeholder_ok"] = True
                # input must be non-empty array of strings
                if isinstance(inp, list) and len(inp) > 0 and all(isinstance(x, str) for x in inp):
                    checks["emb_input_nonempty_array"] = True

    # 4) client_example.py
    client_path = os.path.join(output_dir, "client_example.py")
    if os.path.isfile(client_path):
        checks["client_exists"] = True
        client_text = read_text(client_path) or ""
        # must contain literal base URL
        if "http://localhost:1234/v1" in client_text:
            checks["client_contains_base_url"] = True
        # must reference both "model" and "messages"
        if ("model" in client_text) and ("messages" in client_text):
            checks["client_contains_model_and_messages"] = True
        # must include "READY"
        if "READY" in client_text:
            checks["client_contains_ready"] = True
        # must not contain cloud hostnames
        if not contains_disallowed_host(client_text):
            checks["client_no_cloud_hosts"] = True

    # 5) troubleshooting.md
    trouble_path = os.path.join(output_dir, "troubleshooting.md")
    if os.path.isfile(trouble_path):
        checks["trouble_exists"] = True
        t_text = read_text(trouble_path) or ""
        t_low = t_text.lower()
        # mentions "base URL" or "port"
        if ("base url" in t_low) or ("port" in t_low):
            checks["trouble_mentions_baseurl_or_port"] = True
        # mentions "model not found"
        if "model not found" in t_low:
            checks["trouble_mentions_model_not_found"] = True
        # mentions "empty" (for empty outputs)
        if "empty" in t_low:
            checks["trouble_mentions_empty"] = True
        # mentions "first token"
        if "first token" in t_low:
            checks["trouble_mentions_first_token"] = True
        # mentions "embeddings" (endpoint mismatch)
        if "embeddings" in t_low:
            checks["trouble_mentions_embeddings"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Enforce exact 0.0 for no-op baseline (no outputs or nothing passed)
    # If none of the artifact-dependent checks passed, reward must be 0.0
    if passed == 0:
        reward = 0.0

    # Print result JSON with "reward" as the first field
    result = {"reward": reward}
    result.update(checks)
    last_non_empty_print(result)

if __name__ == "__main__":
    main()