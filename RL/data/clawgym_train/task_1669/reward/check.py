import json
import os
import re
import sys
from typing import List, Dict, Any, Tuple

def is_time(s: str) -> bool:
    return bool(re.fullmatch(r"\d{2}:\d{2}", s)) and 0 <= int(s[:2]) <= 23 and 0 <= int(s[3:]) <= 59

def time_ge(a: str, b: str) -> bool:
    # a >= b
    ah, am = int(a[:2]), int(a[3:])
    bh, bm = int(b[:2]), int(b[3:])
    return (ah, am) >= (bh, bm)

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_jsonl(path: str) -> Tuple[bool, List[Dict[str, Any]], str]:
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception as e:
                    return False, [], f"Line {i} is not valid JSON: {e}"
                items.append(obj)
        return True, items, ""
    except Exception as e:
        return False, [], f"Failed to read jsonl: {e}"

def validate_jsonl_structure(items: List[Dict[str, Any]]) -> bool:
    for obj in items:
        if not isinstance(obj, dict):
            return False
        if "time" not in obj or "reminderId" not in obj or "kind" not in obj or "message" not in obj:
            return False
        if not isinstance(obj["time"], str) or not is_time(obj["time"]):
            return False
        if not isinstance(obj["reminderId"], str):
            return False
        if obj["kind"] not in ("nag", "escalate"):
            return False
        if not isinstance(obj["message"], str) or len(obj["message"]) == 0:
            return False
    return True

def find_section(text: str, keys: List[str], next_keys: List[str]) -> Tuple[bool, str]:
    # case-insensitive search: start at first occurrence of any key in keys
    low = text.lower()
    starts = [(low.find(k.lower()), k) for k in keys]
    starts = [t for t in starts if t[0] != -1]
    if not starts:
        return False, ""
    start = min(starts, key=lambda x: x[0])[0]
    # end at next occurrence of any key in next_keys after start
    end_positions = []
    for nk in next_keys:
        pos = low.find(nk.lower(), start + 1)
        if pos != -1:
            end_positions.append(pos)
    if end_positions:
        end = min(end_positions)
        return True, text[start:end]
    else:
        return True, text[start:]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected constants from the task spec
    today_date = "2026-04-20"
    morning_id = "morning-supplements"
    evening_id = "evening-workout"
    morning_label = "morning supplements"  # expected from spec
    evening_label = "evening workout"      # expected from spec
    morning_nag_after = "09:00"
    evening_nag_after = "19:30"
    expected_morning_times = ["09:10", "09:25", "09:35", "09:45"]
    expected_evening_times = ["19:45", "20:00", "20:10", "20:20"]
    expected_morning_kinds = {"09:10": "nag", "09:25": "nag", "09:35": "nag", "09:45": "escalate"}
    expected_evening_kinds = {"19:45": "nag", "20:00": "nag", "20:10": "nag", "20:20": "escalate"}
    disallowed_morning_time = "10:15"
    disallowed_evening_time = "20:40"
    morning_confirm_at = "09:46"
    evening_confirm_at = "20:35"
    expected_final_nag_count = 4

    # Checks dictionary initialized to False
    checks: Dict[str, bool] = {
        "file_exists_nag_messages": False,
        "file_exists_state": False,
        "file_exists_report": False,

        "jsonl_structure_valid": False,

        "state_structure_valid": False,
        "state_date_correct": False,
        "state_has_both_reminders": False,
        "state_morning_values": False,
        "state_evening_values": False,

        "messages_count_8": False,
        "messages_morning_sequence": False,
        "messages_evening_sequence": False,
        "messages_no_before_nagAfter": False,
        "messages_no_disallowed_times": False,

        "report_mentions_morning": False,
        "report_mentions_evening": False,
        "report_times_listed_morning": False,
        "report_times_listed_evening": False,
        "report_final_nagcount_morning": False,
        "report_final_nagcount_evening": False
    }

    # Paths
    nag_messages_path = os.path.join(output_dir, "nag-messages.jsonl")
    state_path = os.path.join(output_dir, "new-nag-state.json")
    report_path = os.path.join(output_dir, "report.md")

    # Existence checks
    if os.path.isfile(nag_messages_path):
        checks["file_exists_nag_messages"] = True
    if os.path.isfile(state_path):
        checks["file_exists_state"] = True
    if os.path.isfile(report_path):
        checks["file_exists_report"] = True

    # If any of the required files do not exist, the reward must be 0.0 (no-op baseline)
    all_exist = checks["file_exists_nag_messages"] and checks["file_exists_state"] and checks["file_exists_report"]

    messages_items: List[Dict[str, Any]] = []
    if checks["file_exists_nag_messages"]:
        ok, items, _err = parse_jsonl(nag_messages_path)
        if ok and validate_jsonl_structure(items):
            checks["jsonl_structure_valid"] = True
            messages_items = items

    # Validate message timeline correctness
    if checks["jsonl_structure_valid"]:
        # Group by reminderId
        by_id: Dict[str, List[Dict[str, Any]]] = {}
        for obj in messages_items:
            rid = obj["reminderId"]
            by_id.setdefault(rid, []).append(obj)

        # Count check
        total_lines = len(messages_items)
        if total_lines == 8:
            checks["messages_count_8"] = True

        # Sequence checks
        morning_msgs = by_id.get(morning_id, [])
        evening_msgs = by_id.get(evening_id, [])

        def exact_sequence_ok(msgs: List[Dict[str, Any]], exp_times: List[str], exp_kinds_map: Dict[str, str]) -> bool:
            if len(msgs) != len(exp_times):
                return False
            # Build map by time -> kind from messages
            got_map = {}
            for m in msgs:
                t = m.get("time")
                k = m.get("kind")
                if not isinstance(t, str) or not isinstance(k, str):
                    return False
                got_map[t] = k
            # Ensure times match exactly and kinds match
            for t in exp_times:
                if t not in got_map:
                    return False
                if got_map[t] != exp_kinds_map[t]:
                    return False
            # Also ensure no extra unexpected times in this group
            for t in got_map.keys():
                if t not in exp_times:
                    return False
            return True

        if exact_sequence_ok(morning_msgs, expected_morning_times, expected_morning_kinds):
            checks["messages_morning_sequence"] = True
        if exact_sequence_ok(evening_msgs, expected_evening_times, expected_evening_kinds):
            checks["messages_evening_sequence"] = True

        # No message before nagAfter
        no_before = True
        for m in morning_msgs:
            if not time_ge(m["time"], morning_nag_after):
                no_before = False
                break
        if no_before:
            for m in evening_msgs:
                if not time_ge(m["time"], evening_nag_after):
                    no_before = False
                    break
        if no_before:
            checks["messages_no_before_nagAfter"] = True

        # No disallowed extra time messages
        no_disallowed = True
        for m in morning_msgs:
            if m["time"] == disallowed_morning_time:
                no_disallowed = False
                break
        if no_disallowed:
            for m in evening_msgs:
                if m["time"] == disallowed_evening_time:
                    no_disallowed = False
                    break
        if no_disallowed:
            checks["messages_no_disallowed_times"] = True

    # Validate state file
    state_obj: Dict[str, Any] = {}
    if checks["file_exists_state"]:
        try:
            state_obj = load_json(state_path)
            if isinstance(state_obj, dict) and "date" in state_obj and "reminders" in state_obj and isinstance(state_obj["reminders"], dict):
                checks["state_structure_valid"] = True

                if state_obj.get("date") == today_date:
                    checks["state_date_correct"] = True

                rems = state_obj.get("reminders", {})
                has_morning = morning_id in rems
                has_evening = evening_id in rems
                if has_morning and has_evening:
                    checks["state_has_both_reminders"] = True

                if has_morning:
                    m = rems[morning_id]
                    if isinstance(m, dict):
                        confirmed = m.get("confirmed") is True
                        confirmedAt = m.get("confirmedAt") == morning_confirm_at
                        nagCount_ok = isinstance(m.get("nagCount"), int) and m.get("nagCount") == expected_final_nag_count
                        if confirmed and confirmedAt and nagCount_ok:
                            checks["state_morning_values"] = True

                if has_evening:
                    e = rems[evening_id]
                    if isinstance(e, dict):
                        confirmed = e.get("confirmed") is True
                        confirmedAt = e.get("confirmedAt") == evening_confirm_at
                        nagCount_ok = isinstance(e.get("nagCount"), int) and e.get("nagCount") == expected_final_nag_count
                        if confirmed and confirmedAt and nagCount_ok:
                            checks["state_evening_values"] = True

        except Exception:
            pass

    # Validate report.md content
    report_text = ""
    if checks["file_exists_report"]:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""

    if report_text:
        # Build keys for sections (id or label acceptable)
        morning_keys = [morning_id, morning_label]
        evening_keys = [evening_id, evening_label]

        # Morning section
        ok_morning, morning_section = find_section(report_text, morning_keys, evening_keys)
        if ok_morning:
            # required phrases
            if re.search(r"\bescalation occurred\b", morning_section, flags=re.IGNORECASE):
                # phrase can be any case; spec says include exactly the phrase, but we accept case-insensitive
                pass
            # check both phrases
            if ("escalation occurred" in morning_section) and ("confirmation matched" in morning_section):
                checks["report_mentions_morning"] = True

            # times present
            times_present = all(t in morning_section for t in expected_morning_times)
            if times_present:
                checks["report_times_listed_morning"] = True

            # final nagCount presence
            if re.search(r"final\s+nagCount\s*:\s*4", morning_section, flags=re.IGNORECASE):
                checks["report_final_nagcount_morning"] = True

        # Evening section
        ok_evening, evening_section = find_section(report_text, evening_keys, morning_keys)
        if ok_evening:
            if ("escalation occurred" in evening_section) and ("confirmation matched" in evening_section):
                checks["report_mentions_evening"] = True

            times_present = all(t in evening_section for t in expected_evening_times)
            if times_present:
                checks["report_times_listed_evening"] = True

            if re.search(r"final\s+nagCount\s*:\s*4", evening_section, flags=re.IGNORECASE):
                checks["report_final_nagcount_evening"] = True

    # Compute reward
    # If any required file is missing, reward is 0.0
    if not all_exist:
        reward = 0.0
    else:
        total = len(checks)
        true_count = sum(1 for v in checks.values() if v)
        # Average of checks
        reward = true_count / total if total > 0 else 0.0
        # Bound to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()