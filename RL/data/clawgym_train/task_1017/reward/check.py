import json
import os
import sys

def load_jsonl(path):
    objs = []
    raw_lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                # Keep raw lines and skip purely empty lines for JSONL counting
                raw_lines.append(line)
                if line.strip() == "":
                    continue
                try:
                    obj = json.loads(line)
                    objs.append(obj)
                except json.JSONDecodeError:
                    return False, raw_lines, objs
        return True, raw_lines, objs
    except Exception:
        return False, [], []

def ends_with_icon(s, icon):
    # Ensure no trailing whitespace and ends with the exact icon
    if s != s.rstrip():
        return False
    return s.endswith(icon)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "responses_exists": False,
        "assessment_exists": False,
        "responses_valid_jsonl": False,
        "responses_four_lines": False,
        "responses_fields_valid": False,
        "ids_match_input": False,
        "score_mode_mapping_ok": False,
        "action_command_ok": False,
        "icon_rules_ok": False,
        "variety_requirement_met": False,
        "assessment_mentions_ids": False,
    }

    # Paths
    prompts_path = os.path.join(input_dir, "prompts.jsonl")
    responses_path = os.path.join(output_dir, "responses.jsonl")
    assessment_path = os.path.join(output_dir, "assessment.md")

    # Read input prompts ids
    input_ids = set()
    input_loaded = False
    if os.path.isfile(prompts_path):
        ok_input, input_lines_raw, input_objs = load_jsonl(prompts_path)
        if ok_input:
            for o in input_objs:
                if isinstance(o, dict) and "id" in o and isinstance(o["id"], str):
                    input_ids.add(o["id"])
            # Consider input loaded if we got at least one id or file parsed fine
            input_loaded = True

    # Check files existence
    if os.path.isfile(responses_path):
        checks["responses_exists"] = True

    if os.path.isfile(assessment_path):
        # Must be non-empty
        try:
            if os.path.getsize(assessment_path) > 0:
                checks["assessment_exists"] = True
        except Exception:
            pass

    # Early parse responses if present
    responses_objs = []
    responses_nonempty_lines = []
    responses_parsed_ok = False
    if checks["responses_exists"]:
        ok_responses, raw_lines, objs = load_jsonl(responses_path)
        # Count non-empty lines
        nonempty_lines = [ln for ln in raw_lines if ln.strip() != ""]
        responses_nonempty_lines = nonempty_lines
        if ok_responses:
            checks["responses_valid_jsonl"] = True
            responses_parsed_ok = True
            responses_objs = objs

        # Must be exactly 4 JSONL lines (non-empty)
        if len(nonempty_lines) == 4:
            checks["responses_four_lines"] = True

    # Validate fields
    fields_valid = False
    ids_from_responses = set()
    score_mode_ok = True
    action_command_ok = True
    icon_rules_ok = True
    if responses_parsed_ok and checks["responses_four_lines"]:
        required_modes = {"fast", "standard", "reasoning", "extended"}
        allowed_actions = {"/reasoning on", "/reasoning off"}

        def score_to_expected_mode(score):
            if score <= 2:
                return "fast"
            elif 3 <= score <= 5:
                return "standard"
            elif 6 <= score <= 7:
                return "reasoning"
            else:
                return "extended"

        all_fields_ok = True
        for obj in responses_objs:
            # Must be dict
            if not isinstance(obj, dict):
                all_fields_ok = False
                break

            # Check presence and types
            if "id" not in obj or "score" not in obj or "mode" not in obj or "action_command" not in obj or "response" not in obj:
                all_fields_ok = False
                break

            _id = obj["id"]
            score = obj["score"]
            mode = obj["mode"]
            action = obj["action_command"]
            response = obj["response"]

            if not isinstance(_id, str):
                all_fields_ok = False
                break
            ids_from_responses.add(_id)

            # score integer 0-10
            if not isinstance(score, int) or score < 0 or score > 10:
                all_fields_ok = False
                break

            # mode allowed set
            if not isinstance(mode, str) or mode not in required_modes:
                all_fields_ok = False
                break

            # action allowed set
            if not isinstance(action, str) or action not in allowed_actions:
                all_fields_ok = False
                break

            # response non-empty string
            if not isinstance(response, str) or len(response.strip()) == 0:
                all_fields_ok = False
                break

            # Score-to-mode mapping
            expected_mode = score_to_expected_mode(score)
            if mode != expected_mode:
                score_mode_ok = False

            # Action command mapping
            expected_action = "/reasoning on" if score >= 6 else "/reasoning off"
            if action != expected_action:
                action_command_ok = False

            # Icon placement rules
            # For fast/standard: must not contain 🧠 or 🧠🔥 anywhere
            brain = "🧠"
            brain_fire = "🧠🔥"
            if mode in ("fast", "standard"):
                if (brain in response) or (brain_fire in response):
                    icon_rules_ok = False
            elif mode == "reasoning":
                # must end with single 🧠, no trailing whitespace, and must not contain 🧠🔥 anywhere
                if (brain_fire in response) or (not ends_with_icon(response, brain)):
                    icon_rules_ok = False
            elif mode == "extended":
                # must end with 🧠🔥, no trailing whitespace
                if not ends_with_icon(response, brain_fire):
                    icon_rules_ok = False

        if all_fields_ok:
            checks["responses_fields_valid"] = True

        # IDs match input
        if input_loaded and len(input_ids) > 0:
            if ids_from_responses == input_ids:
                checks["ids_match_input"] = True

        if checks["responses_fields_valid"]:
            if score_mode_ok:
                checks["score_mode_mapping_ok"] = True
            if action_command_ok:
                checks["action_command_ok"] = True
            if icon_rules_ok:
                checks["icon_rules_ok"] = True

        # Variety requirement: at least one 🧠, at least one 🧠🔥, at least one no icon at end
        has_reasoning_icon = False
        has_extended_icon = False
        has_no_icon_end = False
        brain = "🧠"
        brain_fire = "🧠🔥"
        if checks["responses_fields_valid"]:
            for obj in responses_objs:
                resp = obj.get("response", "")
                m = obj.get("mode", "")
                # Determine end icons
                if m == "reasoning" and ends_with_icon(resp, brain) and (brain_fire not in resp):
                    has_reasoning_icon = True
                if m == "extended" and ends_with_icon(resp, brain_fire):
                    has_extended_icon = True
                if m in ("fast", "standard"):
                    # No icon allowed anywhere; already enforced. Check end has no icon.
                    if not resp.endswith(brain) and not resp.endswith(brain_fire):
                        has_no_icon_end = True
            if has_reasoning_icon and has_extended_icon and has_no_icon_end:
                checks["variety_requirement_met"] = True

    # Assessment mentions each id at least once
    if checks["assessment_exists"] and input_loaded and len(input_ids) > 0:
        try:
            with open(assessment_path, "r", encoding="utf-8") as f:
                assessment_text = f.read()
            mentions_all = True
            for _id in input_ids:
                if _id not in assessment_text:
                    mentions_all = False
                    break
            if mentions_all and len(assessment_text.strip()) > 0:
                checks["assessment_mentions_ids"] = True
        except Exception:
            pass

    # Compute reward
    # No-op baseline: if responses.jsonl missing, reward must be 0.0
    if not checks["responses_exists"]:
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0

    # Output result JSON
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()