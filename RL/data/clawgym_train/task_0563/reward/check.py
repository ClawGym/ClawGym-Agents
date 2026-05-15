import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_non_empty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        non_empty = [ln for ln in lines if ln.strip() != ""]
        return lines, non_empty
    except Exception:
        return None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "messages_file_14_lines": False,                      # 1
        "json_and_required_keys": False,                      # 2
        "mode_base_name_and_message_coach": False,            # 3
        "types_and_times_match_config": False,                # 4
        "intensity_used_valid_range_and_int_type": False,     # 5
        "seven_unique_dates_two_per_day": False,              # 6
        "toned_down_on_miss_streak": False,                   # 7
        "backhanded_when_yesterday_quests_positive": False,   # 8
        "acknowledges_effort_always_true": False,             # 9
        "message_length_80_320": False,                       # 10
        "safety_banned_words_absent": False,                  # 11
        "summary_file_exists_nonempty": False,                # 12
    }

    # Paths
    messages_path = os.path.join(output_dir, "messages.jsonl")
    summary_path = os.path.join(output_dir, "summary.md")
    config_path = os.path.join(input_dir, "config.json")

    # 1) messages.jsonl exists and has exactly 14 non-empty lines
    parsed_entries = []
    all_json_parsed = True
    lines, non_empty = read_non_empty_lines(messages_path)
    if non_empty is not None and len(non_empty) == 14:
        checks["messages_file_14_lines"] = True

    # 2) Every line parses as JSON and contains all required keys
    required_keys = {
        "date",
        "type",
        "time",
        "mode",
        "custom_name",
        "base_intensity",
        "intensity_used",
        "toned_down",
        "yesterday_quests",
        "miss_streak",
        "includes_backhanded_compliment",
        "acknowledges_effort",
        "message",
    }

    if checks["messages_file_14_lines"]:
        for ln in non_empty:
            try:
                obj = json.loads(ln)
            except Exception:
                all_json_parsed = False
                break
            # Check required keys
            if not required_keys.issubset(set(obj.keys())):
                all_json_parsed = False
                break
            parsed_entries.append(obj)

        if all_json_parsed and len(parsed_entries) == 14:
            checks["json_and_required_keys"] = True

    # Load config for time checks
    config = load_json(config_path)
    config_morning = None
    config_evening = None
    if isinstance(config, dict):
        config_morning = config.get("morning_checkin")
        config_evening = config.get("evening_review")

    # 3) mode === "savage"; base_intensity === 8; custom_name contains "Coach Rekt"; message contains "Coach Rekt"
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            if e.get("mode") != "savage":
                ok = False
                break
            if e.get("base_intensity") != 8:
                ok = False
                break
            cn = e.get("custom_name")
            msg = e.get("message")
            if not (isinstance(cn, str) and "Coach Rekt" in cn):
                ok = False
                break
            if not (isinstance(msg, str) and "Coach Rekt" in msg):
                ok = False
                break
        if ok:
            checks["mode_base_name_and_message_coach"] = True

    # 4) type is morning|evening; time equals configured times; and config times are expected "07:00" and "21:30"
    # This check passes only if:
    # - config is present and has morning_checkin and evening_review
    # - config times equal "07:00" and "21:30"
    # - each entry has time matching the config time for its type
    if checks["json_and_required_keys"] and isinstance(config_morning, str) and isinstance(config_evening, str):
        expected_morning = "07:00"
        expected_evening = "21:30"
        ok = (config_morning == expected_morning) and (config_evening == expected_evening)
        if ok:
            for e in parsed_entries:
                t = e.get("type")
                ti = e.get("time")
                if t not in ("morning", "evening"):
                    ok = False
                    break
                if t == "morning" and ti != config_morning:
                    ok = False
                    break
                if t == "evening" and ti != config_evening:
                    ok = False
                    break
            if ok:
                checks["types_and_times_match_config"] = True

    # 5) intensity_used is an integer between 1 and 10
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            val = e.get("intensity_used")
            if not isinstance(val, int):
                ok = False
                break
            if not (1 <= val <= 10):
                ok = False
                break
        if ok:
            checks["intensity_used_valid_range_and_int_type"] = True

    # 6) Exactly 7 unique dates and exactly 2 entries per date (1 morning, 1 evening)
    if checks["json_and_required_keys"]:
        from collections import defaultdict
        dates = defaultdict(list)
        for e in parsed_entries:
            dates[e.get("date")].append(e)
        ok = True
        if len(dates.keys()) != 7:
            ok = False
        else:
            for d, items in dates.items():
                if len(items) != 2:
                    ok = False
                    break
                types = sorted([it.get("type") for it in items])
                if types != ["evening", "morning"]:
                    ok = False
                    break
        if ok:
            checks["seven_unique_dates_two_per_day"] = True

    # 7) For entries where miss_streak >= 2: toned_down true and intensity_used <= 5
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            ms = e.get("miss_streak")
            td = e.get("toned_down")
            iu = e.get("intensity_used")
            try:
                ms_val = int(ms)
            except Exception:
                ok = False
                break
            if ms_val >= 2:
                if not (td is True and isinstance(iu, int) and iu <= 5):
                    ok = False
                    break
        if ok:
            checks["toned_down_on_miss_streak"] = True

    # 8) For entries where yesterday_quests > 0 and mode is savage, includes_backhanded_compliment must be true
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            yq = e.get("yesterday_quests")
            ibc = e.get("includes_backhanded_compliment")
            if e.get("mode") == "savage":
                try:
                    yq_val = int(yq)
                except Exception:
                    ok = False
                    break
                if yq_val > 0 and ibc is not True:
                    ok = False
                    break
        if ok:
            checks["backhanded_when_yesterday_quests_positive"] = True

    # 9) acknowledges_effort must be true for all entries
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            if e.get("acknowledges_effort") is not True:
                ok = False
                break
        if ok:
            checks["acknowledges_effort_always_true"] = True

    # 10) Each message length between 80 and 320 characters inclusive
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            msg = e.get("message")
            if not isinstance(msg, str):
                ok = False
                break
            ln = len(msg)
            if not (80 <= ln <= 320):
                ok = False
                break
        if ok:
            checks["message_length_80_320"] = True

    # 11) Safety filter: banned substrings absent
    banned = ["worthless", "idiot", "stupid", "failure", "hate", "pathetic", "hopeless", "dumb", "trash", "useless", "kill", "die"]
    if checks["json_and_required_keys"]:
        ok = True
        for e in parsed_entries:
            msg = e.get("message")
            if not isinstance(msg, str):
                ok = False
                break
            low = msg.lower()
            if any(b in low for b in banned):
                ok = False
                break
        if ok:
            checks["safety_banned_words_absent"] = True

    # 12) summary.md exists and is non-empty
    try:
        if os.path.isfile(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            if isinstance(content, str) and content.strip() != "":
                checks["summary_file_exists_nonempty"] = True
    except Exception:
        pass

    # Compute reward (fraction of checks passed)
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output directory missing or messages/summary missing, reward should be 0.0
    # Our checks already reflect that; ensure strict bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()