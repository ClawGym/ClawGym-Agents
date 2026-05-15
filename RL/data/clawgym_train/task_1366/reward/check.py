import json
import os
import sys

def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    objs = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            # Treat empty lines as lines but they are invalid for this task
            raise ValueError(f"Empty line at {i}")
        try:
            obj = json.loads(line)
        except Exception as e:
            raise ValueError(f"Invalid JSON on line {i}: {e}")
        if not isinstance(obj, dict):
            raise ValueError(f"Line {i} is not a JSON object")
        objs.append(obj)
    return objs

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "clean_transcript_exists": False,
        "clean_transcript_has_10_lines": False,
        "clean_transcript_valid_json_and_fields": False,
        "transcript_order_matches_input": False,
        "transcript_texts_expected": False,
        "violations_exists": False,
        "violations_valid_json": False,
        "violations_messages_all_ids": False,
        "violations_profane_words_expected": False,
        "violations_blocked_flags_expected": False,
        "violations_totals_expected": False,
    }

    # Expected outputs as per task specification
    expected_texts = {
        1: "What the *** is this?",
        2: "You are such a *** talker.",
        3: "*** move.",
        4: "This is *** and *** everywhere.",
        5: "I need to assess the situation in Scunthorpe.",
        6: "Stop being a ***!",
        7: "What the *** was that?",
        8: "No profanity here.",
        9: "*** is not okay, but assess should be ignored.",
        10: "He said '***' but spaced.",
    }
    expected_ids = list(range(1, 11))

    expected_profane_per_id = {
        1: ["fuck"],
        2: ["shit"],
        3: ["bastard"],
        4: ["shit", "fuck"],
        5: [],
        6: ["jerkface"],
        7: ["fuck"],
        8: [],
        9: ["ass"],
        10: ["bitch"],
    }
    expected_totals = {"fuck": 3, "shit": 2, "bastard": 1, "jerkface": 1, "ass": 1, "bitch": 1}

    # Read input/messages.jsonl to validate ordering and id/userId preservation
    input_messages_path = os.path.join(input_dir, "messages.jsonl")
    input_messages = []
    try:
        if os.path.isfile(input_messages_path):
            input_messages = read_jsonl(input_messages_path)
    except Exception:
        # If inputs cannot be read, order check will fail later; do not award for input reading
        input_messages = []

    # --- Validate clean_transcript.jsonl ---
    clean_path = os.path.join(output_dir, "clean_transcript.jsonl")
    if os.path.isfile(clean_path):
        checks["clean_transcript_exists"] = True
        try:
            out_lines = read_jsonl(clean_path)
            if len(out_lines) == 10:
                checks["clean_transcript_has_10_lines"] = True

            # Validate that each line has id, userId, text
            valid_fields = True
            for obj in out_lines:
                if not all(k in obj for k in ("id", "userId", "text")):
                    valid_fields = False
                    break
            if valid_fields:
                checks["clean_transcript_valid_json_and_fields"] = True

            # Validate order matches input (id and userId aligned with input order)
            if input_messages and len(input_messages) == 10 and len(out_lines) == 10:
                order_ok = True
                for i in range(10):
                    in_obj = input_messages[i]
                    out_obj = out_lines[i]
                    if in_obj.get("id") != out_obj.get("id") or in_obj.get("userId") != out_obj.get("userId"):
                        order_ok = False
                        break
                if order_ok:
                    checks["transcript_order_matches_input"] = True

            # Validate texts match expected for each id
            texts_ok = True
            for obj in out_lines:
                msg_id = obj.get("id")
                if not isinstance(msg_id, int) or msg_id not in expected_texts:
                    texts_ok = False
                    break
                if obj.get("text") != expected_texts[msg_id]:
                    texts_ok = False
                    break
            if texts_ok and len(out_lines) == 10:
                checks["transcript_texts_expected"] = True

        except Exception:
            # Any parsing error keeps relevant checks as False
            pass

    # --- Validate violations.json ---
    violations_path = os.path.join(output_dir, "violations.json")
    if os.path.isfile(violations_path):
        checks["violations_exists"] = True
        try:
            with open(violations_path, "r", encoding="utf-8") as f:
                vio = json.load(f)
            if isinstance(vio, dict) and "messages" in vio and "totals" in vio and isinstance(vio["messages"], list) and isinstance(vio["totals"], dict):
                checks["violations_valid_json"] = True

                # Validate messages cover ids 1..10 and content matches
                msgs = vio["messages"]
                by_id = {}
                ids_ok = True
                for m in msgs:
                    if not isinstance(m, dict):
                        ids_ok = False
                        break
                    if "id" not in m or "profaneWords" not in m or "blocked" not in m:
                        ids_ok = False
                        break
                    mid = m["id"]
                    by_id[mid] = m
                expected_id_set = set(expected_ids)
                if ids_ok and set(by_id.keys()) == expected_id_set:
                    checks["violations_messages_all_ids"] = True

                # Validate profaneWords match exactly as specified (order-sensitive)
                prof_ok = True
                if checks["violations_messages_all_ids"]:
                    for mid in expected_ids:
                        expected_list = expected_profane_per_id[mid]
                        got_list = by_id[mid].get("profaneWords")
                        if not isinstance(got_list, list):
                            prof_ok = False
                            break
                        # Ensure all are strings
                        if any(not isinstance(w, str) for w in got_list):
                            prof_ok = False
                            break
                        if got_list != expected_list:
                            prof_ok = False
                            break
                if prof_ok:
                    checks["violations_profane_words_expected"] = True

                # Validate blocked flags are all False as specified
                blocked_ok = True
                if checks["violations_messages_all_ids"]:
                    for mid in expected_ids:
                        if by_id[mid].get("blocked") is not False:
                            blocked_ok = False
                            break
                if blocked_ok:
                    checks["violations_blocked_flags_expected"] = True

                # Validate totals match exactly
                totals_ok = vio.get("totals") == expected_totals
                if totals_ok:
                    checks["violations_totals_expected"] = True

        except Exception:
            # Keep violation checks as False on errors
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 when no artifacts produced (no-op baseline)
    # If both primary artifacts are missing, force reward 0.0
    if not checks["clean_transcript_exists"] and not checks["violations_exists"]:
        reward = 0.0

    # Print final JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()