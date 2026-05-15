import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def load_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n\r") for line in f.readlines()], None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "messages_json_exists": False,
        "summary_txt_exists": False,
        "messages_json_valid": False,
        "config_echo_present": False,
        "config_echo_matches": False,
        "channels_keys_match": False,
        "messages_count_valid": False,
        "messages_lengths_valid": False,
        "messages_anchor_included": False,
        "messages_no_exclamations": False,
        "messages_no_forbidden": False,
        "risk_line_included_when_required": False,
        "summary_structure_valid": False,
        "summary_channels_order_valid": False,
        "summary_messages_per_channel_valid": False,
        "summary_anchor_phrase_valid": False,
        "summary_no_exclamations_flag_valid": False,
    }

    # Paths
    config_path = os.path.join(input_dir, "config.json")
    forbidden_path = os.path.join(input_dir, "forbidden_words.txt")
    risk_template_path = os.path.join(input_dir, "risk_template.txt")

    messages_path = os.path.join(output_dir, "messages.json")
    summary_path = os.path.join(output_dir, "summary.txt")

    # Load input config
    config, config_err = load_json(config_path)
    if config is None:
        # If we cannot load config, no positive checks can pass
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Extract config elements
    response_delay = config.get("response_delay")
    speech_speed = config.get("speech_speed")
    caution_coefficient = config.get("caution_coefficient")
    risk_reminder = config.get("risk_reminder")
    config_channels = config.get("channels", [])
    max_chars_map = config.get("max_chars", {})
    anchor_phrase = config.get("anchor_phrase", "")

    # Load forbidden words
    forbidden_lines, _ = load_text_lines(forbidden_path)
    forbidden_words = []
    if forbidden_lines is not None:
        for line in forbidden_lines:
            w = line.strip()
            if w != "":
                forbidden_words.append(w.lower())

    # Load risk template
    risk_line = ""
    risk_lines, _ = load_text_lines(risk_template_path)
    if risk_lines is not None:
        # Join lines with newline if multiple lines; spec says "exact risk reminder sentence to include"
        # We will treat the entire file as the line content joined by newline if multiple lines.
        # Usually it is one line; if multiple, include full content as a single string for substring check.
        risk_line = "\n".join(risk_lines)

    # Check existence of outputs
    if os.path.isfile(messages_path):
        checks["messages_json_exists"] = True
    if os.path.isfile(summary_path):
        checks["summary_txt_exists"] = True

    # Parse messages.json
    messages_data = None
    if checks["messages_json_exists"]:
        messages_data, err = load_json(messages_path)
        if messages_data is not None and isinstance(messages_data, dict):
            checks["messages_json_valid"] = True

    # Validate config_echo
    if checks["messages_json_valid"]:
        config_echo = messages_data.get("config_echo")
        if isinstance(config_echo, dict):
            checks["config_echo_present"] = True
            # Verify exact fields and equality
            expected_echo = {
                "response_delay": response_delay,
                "speech_speed": speech_speed,
                "caution_coefficient": caution_coefficient,
                "risk_reminder": risk_reminder,
            }
            # Must match exactly in keys and values
            if set(config_echo.keys()) == set(expected_echo.keys()):
                values_match = True
                for k, v in expected_echo.items():
                    if config_echo.get(k) != v:
                        values_match = False
                        break
                if values_match:
                    checks["config_echo_matches"] = True

    # Validate channels object structure
    channels_obj = None
    if checks["messages_json_valid"]:
        channels_obj = messages_data.get("channels")
        if isinstance(channels_obj, dict) and isinstance(config_channels, list):
            # Check keys match exactly the array set
            if set(channels_obj.keys()) == set(config_channels) and len(channels_obj.keys()) == len(config_channels):
                checks["channels_keys_match"] = True

    # Validate per-message constraints
    # Proceed only if channels keys match
    if checks["channels_keys_match"]:
        # Validate messages per channel: exactly 3 strings
        count_ok = True
        lengths_ok = True
        anchor_ok = True
        exclam_ok = True
        forbidden_ok = True
        risk_ok = True  # evaluated below conditionally

        for ch in config_channels:
            msgs = channels_obj.get(ch)
            if not isinstance(msgs, list) or len(msgs) != 3:
                count_ok = False
                # We still need to avoid processing non-lists
                continue

            # Ensure all are strings
            for m in msgs:
                if not isinstance(m, str):
                    count_ok = False
                    break
            if not count_ok:
                continue

            # Length per channel
            max_len = None
            if isinstance(max_chars_map, dict) and ch in max_chars_map:
                max_len = max_chars_map[ch]
            # If max_len is not provided or not numeric, consider length check failed
            if not isinstance(max_len, (int, float)):
                lengths_ok = False
                # Still check other constraints but lengths already failed

            # Check each message constraints
            for idx, m in enumerate(msgs):
                # Length
                if lengths_ok and max_len is not None:
                    if len(m) > int(max_len):
                        lengths_ok = False
                # Anchor phrase inclusion
                if anchor_phrase and anchor_phrase not in m:
                    anchor_ok = False
                # No exclamation marks
                if "!" in m:
                    exclam_ok = False
                # Forbidden words check (case-insensitive substring)
                low = m.lower()
                for fw in forbidden_words:
                    if fw and fw in low:
                        forbidden_ok = False
                        break

            # Risk reminder line in 3rd message if required
            if risk_reminder is True:
                third_msg = msgs[2] if len(msgs) >= 3 else ""
                if not isinstance(third_msg, str) or (risk_line and risk_line not in third_msg):
                    risk_ok = False

        checks["messages_count_valid"] = count_ok
        checks["messages_lengths_valid"] = lengths_ok
        checks["messages_anchor_included"] = anchor_ok
        checks["messages_no_exclamations"] = exclam_ok
        checks["messages_no_forbidden"] = forbidden_ok
        # Only set risk check after messages.json exists and structure checked
        # If risk_reminder is False, the requirement is vacuously satisfied but only if messages file exists and keys matched
        checks["risk_line_included_when_required"] = (risk_ok if risk_reminder is True else True)

    # Validate summary.txt
    if checks["summary_txt_exists"]:
        lines, err = load_text_lines(summary_path)
        if lines is not None:
            # Exactly four non-empty lines
            non_empty = [ln for ln in lines if ln is not None and ln.strip() != ""]
            if len(lines) == 4 and all(ln.strip() != "" for ln in lines):
                checks["summary_structure_valid"] = True

                # Line 1: channels:
                l1 = lines[0].strip()
                channels_order_ok = False
                if l1.lower().startswith("channels:"):
                    after = l1[len("channels:"):].strip()
                    # Split by commas and strip whitespace
                    if after == "":
                        parsed_channels = []
                    else:
                        parsed_channels = [p.strip() for p in after.split(",")]
                    # Compare to config_channels exactly in order
                    if parsed_channels == config_channels:
                        channels_order_ok = True

                # Line 2: messages_per_channel: 3
                l2 = lines[1].strip()
                mpc_ok = False
                if l2.lower().startswith("messages_per_channel:"):
                    val = l2[len("messages_per_channel:"):].strip()
                    if val == "3":
                        mpc_ok = True

                # Line 3: anchor_phrase: <config anchor>
                l3 = lines[2].strip()
                anchor_line_ok = False
                if l3.lower().startswith("anchor_phrase:"):
                    val = l3[len("anchor_phrase:"):].strip()
                    if val == (anchor_phrase if anchor_phrase is not None else ""):
                        anchor_line_ok = True

                # Line 4: no_exclamations: yes
                l4 = lines[3].strip()
                no_exclam_flag_ok = False
                if l4.lower().startswith("no_exclamations:"):
                    val = l4[len("no_exclamations:"):].strip()
                    if val.lower() == "yes":
                        no_exclam_flag_ok = True

                checks["summary_channels_order_valid"] = channels_order_ok
                checks["summary_messages_per_channel_valid"] = mpc_ok
                checks["summary_anchor_phrase_valid"] = anchor_line_ok
                checks["summary_no_exclamations_flag_valid"] = no_exclam_flag_ok

    # Compute final reward
    # Success requires all checks to pass
    all_checks = list(checks.values())
    reward = 1.0 if all(all_checks) else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()