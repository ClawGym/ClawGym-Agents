import json
import os
import sys
import hashlib

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_list_of_strings(x):
    return isinstance(x, list) and all(isinstance(i, str) for i in x)

def compute_sha256_joined(prompts):
    # prompts are strings; join with a single '\n' and no trailing newline
    joined = "\n".join(prompts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()

def subsequence(subseq, seq):
    # Check if subseq is a subsequence of seq (order preserved)
    it = iter(seq)
    return all(any(a == b for b in it) for a in subseq)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all False
    checks = {
        "has_session_report": False,
        "session_report_parse_ok": False,
        "has_required_fields": False,
        "matched_preferences_valid": False,
        "selected_model_consistent": False,
        "prompts_count_correct": False,
        "prompts_sha256_correct": False,
        "responses_valid": False,
        "has_diagnostics": False,
        "diag_installed_line": False,
        "diag_selected_line": False,
        "diag_ran_line": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "session_report.json")
    diag_path = os.path.join(output_dir, "diagnostics.txt")

    session = None

    # Check existence of files
    if os.path.isfile(report_path):
        checks["has_session_report"] = True
        session, err = load_json_file(report_path)
        if session is not None and isinstance(session, dict):
            checks["session_report_parse_ok"] = True
        else:
            checks["session_report_parse_ok"] = False
    else:
        checks["has_session_report"] = False

    # Validate session JSON structure and constraints
    if checks["session_report_parse_ok"]:
        # Required fields presence
        required_keys = [
            "preferences",
            "prompts",
            "installed_models",
            "matched_preferences",
            "selected_model",
            "ran_inference",
            "prompts_count",
            "prompts_sha256",
            "responses",
        ]
        has_all_keys = all(k in session for k in required_keys)

        # Type checks for basic fields
        types_ok = True
        if not is_list_of_strings(session.get("preferences")):
            types_ok = False
        if not is_list_of_strings(session.get("prompts")):
            types_ok = False
        # installed_models array; elements must be strings if present
        im = session.get("installed_models")
        if not isinstance(im, list) or any(not isinstance(i, str) for i in im if im):
            types_ok = False
        # matched_preferences array strings
        if not isinstance(session.get("matched_preferences"), list) or any(not isinstance(i, str) for i in session.get("matched_preferences")):
            types_ok = False
        # selected_model: null or string
        sm = session.get("selected_model")
        if sm is not None and not isinstance(sm, str):
            types_ok = False
        # ran_inference: boolean
        if not isinstance(session.get("ran_inference"), bool):
            types_ok = False
        # prompts_count: integer number
        if not isinstance(session.get("prompts_count"), int):
            types_ok = False
        # prompts_sha256: string
        if not isinstance(session.get("prompts_sha256"), str):
            types_ok = False
        # responses: array
        if not isinstance(session.get("responses"), list):
            types_ok = False

        checks["has_required_fields"] = has_all_keys and types_ok

        # matched_preferences validity: elements must exist in preferences and installed_models; order matches preferences
        mp_valid = False
        if checks["has_required_fields"]:
            prefs = session["preferences"]
            installed = session["installed_models"]
            matched = session["matched_preferences"]
            # each element in matched must be in prefs and installed
            membership_ok = all((m in prefs) and (m in installed) for m in matched)
            # order preserved relative to prefs
            order_ok = subsequence(matched, prefs)
            mp_valid = membership_ok and order_ok
        checks["matched_preferences_valid"] = mp_valid

        # selected_model consistency with ran_inference and matched_preferences
        sm_ok = False
        if checks["has_required_fields"]:
            selected = session["selected_model"]
            ran = session["ran_inference"]
            matched = session["matched_preferences"]
            # ran must be true iff selected is not None
            ran_selected_consistent = (ran and selected is not None) or ((not ran) and selected is None)
            # if matched non-empty, selected must equal matched[0]; if empty, selected must be None
            if matched:
                selected_consistent_with_matched = (selected == matched[0])
            else:
                selected_consistent_with_matched = (selected is None)
            sm_ok = ran_selected_consistent and selected_consistent_with_matched
        checks["selected_model_consistent"] = sm_ok

        # prompts_count check
        pc_ok = False
        if checks["has_required_fields"]:
            pc_ok = (session["prompts_count"] == len(session["prompts"]))
        checks["prompts_count_correct"] = pc_ok

        # prompts_sha256 correctness based on 'prompts' field
        sha_ok = False
        if checks["has_required_fields"]:
            computed = compute_sha256_joined(session["prompts"])
            sha_ok = (computed == session["prompts_sha256"])
        checks["prompts_sha256_correct"] = sha_ok

        # responses consistency
        resp_ok = False
        if checks["has_required_fields"]:
            ran = session["ran_inference"]
            responses = session["responses"]
            prompts = session["prompts"]
            if ran:
                # responses length equals prompts_count
                length_ok = isinstance(responses, list) and (len(responses) == session["prompts_count"])
                # each item has prompt equal to prompts[i] and response is string
                items_ok = True
                if length_ok:
                    for i, r in enumerate(responses):
                        if not isinstance(r, dict):
                            items_ok = False
                            break
                        if "prompt" not in r or "response" not in r:
                            items_ok = False
                            break
                        if r["prompt"] != prompts[i]:
                            items_ok = False
                            break
                        if not isinstance(r["response"], str):
                            items_ok = False
                            break
                resp_ok = length_ok and items_ok
            else:
                # selected_model is null and responses is empty array and reason is present non-empty
                selected = session["selected_model"]
                reason = session.get("reason", None)
                resp_ok = (selected is None) and isinstance(responses, list) and (len(responses) == 0) and isinstance(reason, str) and len(reason.strip()) > 0
        checks["responses_valid"] = resp_ok

    # Validate diagnostics.txt
    if os.path.isfile(diag_path):
        checks["has_diagnostics"] = True
        try:
            with open(diag_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []

        def has_labeled_line(prefix):
            for line in lines:
                if line.startswith(prefix):
                    # require some content after the prefix
                    return len(line) > len(prefix)
            return False

        checks["diag_installed_line"] = has_labeled_line("Installed models checked: ")
        checks["diag_selected_line"] = has_labeled_line("Selected model: ")
        checks["diag_ran_line"] = has_labeled_line("Ran inference: ")
    else:
        checks["has_diagnostics"] = False

    # Compute reward with gating: if either required file missing, reward is 0.0
    # Define weights summing to 1.0
    weights = {
        "has_session_report": 0.08,
        "session_report_parse_ok": 0.00,  # this is foundational, included in has_required_fields; avoid double counting
        "has_required_fields": 0.18,
        "matched_preferences_valid": 0.10,
        "selected_model_consistent": 0.12,
        "prompts_count_correct": 0.08,
        "prompts_sha256_correct": 0.10,
        "responses_valid": 0.16,
        "has_diagnostics": 0.00,  # gating handled separately
        "diag_installed_line": 0.06,
        "diag_selected_line": 0.06,
        "diag_ran_line": 0.06,
    }

    # Gate: no reward if either main artifacts missing
    if not (checks["has_session_report"] and checks["has_diagnostics"]):
        reward = 0.0
    else:
        reward = 0.0
        for k, w in weights.items():
            if w <= 0:
                continue
            if checks.get(k, False):
                reward += w
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object as the last non-empty line
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()