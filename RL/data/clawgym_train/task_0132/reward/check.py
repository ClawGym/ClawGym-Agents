import json
import os
import sys
import hashlib

def sha256_hex_lower(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def load_jsonl_lines(path):
    lines = []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            s = raw.strip()
            if s == "":
                continue
            try:
                obj = json.loads(s)
            except Exception:
                return None, False
            lines.append(obj)
    return lines, True

def is_iso_like(s: str) -> bool:
    # Minimal check: non-empty string; exact ISO-8601 not strictly required per rubric
    return isinstance(s, str) and len(s) > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "trace_exists": False,
        "trace_nonempty_lines": False,
        "trace_lines_parse_and_shape": False,
        "sent_has_three_with_jsonrpc": False,
        "sent_order_and_ids": False,
        "prompt_structure_and_hash_matches_input": False,
        "summary_exists_and_parse": False,
        "summary_fields_types_and_values": False,
        "counts_match": False,
        "stopreason_and_timeout_consistency": False,
        "summary_prompt_hash_matches_input_and_trace": False,
        "readme_exists_and_length": False,
        "readme_mentions_required_terms": False,
    }

    # Prepare paths
    trace_path = os.path.join(output_dir, "trace.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    readme_path = os.path.join(output_dir, "README.md")
    prompt_path = os.path.join(input_dir, "prompt.txt")

    # Compute prompt hash from input (if available)
    prompt_text = None
    prompt_hash = None
    try:
        if os.path.isfile(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_text = f.read()
            prompt_hash = sha256_hex_lower(prompt_text)
    except Exception:
        prompt_text = None
        prompt_hash = None

    # Load and validate trace.jsonl
    trace_lines = None
    if os.path.isfile(trace_path):
        checks["trace_exists"] = True
        trace_lines, parse_ok = load_jsonl_lines(trace_path)
        if parse_ok and trace_lines is not None and len(trace_lines) > 0:
            checks["trace_nonempty_lines"] = True
            # Validate each line has required shape
            shape_ok = True
            for obj in trace_lines:
                if not isinstance(obj, dict):
                    shape_ok = False
                    break
                if "direction" not in obj or "json" not in obj or "time" not in obj:
                    shape_ok = False
                    break
                if obj["direction"] not in ["sent", "received"]:
                    shape_ok = False
                    break
                if not isinstance(obj["json"], dict):
                    shape_ok = False
                    break
                if not is_iso_like(obj["time"]):
                    shape_ok = False
                    break
            if shape_ok:
                checks["trace_lines_parse_and_shape"] = True

            # Compute sent and received subsets
            sent = [o for o in trace_lines if isinstance(o, dict) and o.get("direction") == "sent"]
            received = [o for o in trace_lines if isinstance(o, dict) and o.get("direction") == "received"]

            # At least three sent lines with json.jsonrpc == "2.0"
            sent_with_jsonrpc = [o for o in sent if isinstance(o.get("json"), dict) and o["json"].get("jsonrpc") == "2.0"]
            if len(sent_with_jsonrpc) >= 3:
                checks["sent_has_three_with_jsonrpc"] = True

            # Order and IDs check for first occurrences in sent list
            first_init_idx = None
            first_new_idx = None
            first_prompt_idx = None
            init_id_ok = False
            new_id_ok = False
            prompt_id_ok = False
            for idx, o in enumerate(sent):
                j = o.get("json", {})
                if not isinstance(j, dict):
                    continue
                m = j.get("method")
                if m == "initialize" and first_init_idx is None:
                    first_init_idx = idx
                    init_id_ok = (j.get("id") == 0 and j.get("jsonrpc") == "2.0")
                if m == "session/new" and first_new_idx is None:
                    first_new_idx = idx
                    new_id_ok = (j.get("id") == 1 and j.get("jsonrpc") == "2.0")
                if m == "session/prompt" and first_prompt_idx is None:
                    first_prompt_idx = idx
                    prompt_id_ok = (j.get("id") == 2 and j.get("jsonrpc") == "2.0")
            if (
                first_init_idx is not None and
                first_new_idx is not None and
                first_prompt_idx is not None and
                first_init_idx < first_new_idx < first_prompt_idx and
                init_id_ok and new_id_ok and prompt_id_ok
            ):
                checks["sent_order_and_ids"] = True

            # Prompt structure and hash vs input
            prompt_struct_ok = False
            if first_prompt_idx is not None:
                j = sent[first_prompt_idx]["json"]
                params = j.get("params")
                if isinstance(params, dict) and "prompt" in params and isinstance(params["prompt"], list):
                    prompt_arr = params["prompt"]
                    if len(prompt_arr) == 1 and isinstance(prompt_arr[0], dict):
                        elem = prompt_arr[0]
                        if elem.get("type") == "text" and isinstance(elem.get("text"), str):
                            # Compute hash of sent prompt text and compare with input hash
                            sent_prompt_text = elem.get("text")
                            if prompt_hash is not None:
                                if sha256_hex_lower(sent_prompt_text) == prompt_hash:
                                    prompt_struct_ok = True
                            else:
                                # If input prompt missing, cannot validate hash; keep False
                                prompt_struct_ok = False
            if prompt_struct_ok:
                checks["prompt_structure_and_hash_matches_input"] = True

        else:
            # parse failed or empty -> keep False defaults
            pass

    # Load and validate summary.json
    summary = None
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            checks["summary_exists_and_parse"] = True
        except Exception:
            summary = None

    if summary is not None and trace_lines is not None:
        # Validate fields and types and exact values for attemptedMethods and ids
        fields_ok = True

        required_keys = [
            "attemptedMethods",
            "ids",
            "sentCount",
            "receivedCount",
            "stopReason",
            "promptTextSha256",
            "timedOut",
        ]
        for k in required_keys:
            if k not in summary:
                fields_ok = False
        if fields_ok:
            # Types and exact values
            if not (isinstance(summary["attemptedMethods"], list) and summary["attemptedMethods"] == ["initialize", "session/new", "session/prompt"]):
                fields_ok = False
            if not (isinstance(summary["ids"], dict) and summary["ids"] == {"initialize": 0, "new": 1, "prompt": 2}):
                fields_ok = False
            if not isinstance(summary.get("sentCount"), int):
                fields_ok = False
            if not isinstance(summary.get("receivedCount"), int):
                fields_ok = False
            # stopReason can be None or allowed strings
            stop_reason = summary.get("stopReason", None)
            if stop_reason is not None and not isinstance(stop_reason, str):
                fields_ok = False
            if not isinstance(summary.get("promptTextSha256"), str):
                fields_ok = False
            if not isinstance(summary.get("timedOut"), bool):
                fields_ok = False

        if fields_ok:
            checks["summary_fields_types_and_values"] = True

            # Counts match
            sent_count = len([o for o in trace_lines if isinstance(o, dict) and o.get("direction") == "sent"])
            recv_count = len([o for o in trace_lines if isinstance(o, dict) and o.get("direction") == "received"])
            if summary["sentCount"] == sent_count and summary["receivedCount"] == recv_count:
                checks["counts_match"] = True

            # stopReason validity and timedOut consistency
            allowed_reasons = {"end_turn", "cancelled", "max_tokens"}
            sr = summary.get("stopReason")
            sr_ok = (sr is None) or (isinstance(sr, str) and sr in allowed_reasons)
            to_ok = (summary.get("timedOut") is True and sr is None) or (summary.get("timedOut") is False and sr is not None)
            if sr_ok and to_ok:
                checks["stopreason_and_timeout_consistency"] = True

            # promptTextSha256 equals input prompt hash and equals sent prompt hash
            prompt_hash_ok = False
            if prompt_hash is not None and isinstance(summary.get("promptTextSha256"), str):
                if summary["promptTextSha256"] == prompt_hash:
                    # Also verify sent prompt text hash matches
                    sent = [o for o in trace_lines if isinstance(o, dict) and o.get("direction") == "sent"]
                    sent_prompt_lines = []
                    for o in sent:
                        j = o.get("json", {})
                        if isinstance(j, dict) and j.get("method") == "session/prompt":
                            sent_prompt_lines.append(j)
                    # Use the first occurrence for comparison
                    if len(sent_prompt_lines) >= 1:
                        j = sent_prompt_lines[0]
                        params = j.get("params", {})
                        if isinstance(params, dict) and isinstance(params.get("prompt"), list) and len(params["prompt"]) == 1 and isinstance(params["prompt"][0], dict):
                            elem = params["prompt"][0]
                            if elem.get("type") == "text" and isinstance(elem.get("text"), str):
                                if sha256_hex_lower(elem["text"]) == summary["promptTextSha256"]:
                                    prompt_hash_ok = True
            if prompt_hash_ok:
                checks["summary_prompt_hash_matches_input_and_trace"] = True

    # README checks
    if os.path.isfile(readme_path):
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                readme = f.read()
            if isinstance(readme, str) and len(readme) >= 200:
                checks["readme_exists_and_length"] = True
            # Required substrings
            terms_ok = all(term in readme for term in ["JSON-RPC", "trace.jsonl", "summary.json"])
            if terms_ok:
                checks["readme_mentions_required_terms"] = True
        except Exception:
            pass

    # Determine reward: 1.0 only if all checks pass
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()