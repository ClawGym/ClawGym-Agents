import json
import os
import re
import sys
from typing import Any, Dict, List

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def to_bool(value: Any) -> bool:
    return isinstance(value, bool)

def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0

def get_int(value: Any):
    try:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip():
            return int(float(value.strip()))
    except Exception:
        return None
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "has_messages_json": False,
        "messages_json_array_len_4": False,
        "messages_fields_valid": False,
        "has_summary_md": False,
        "ids_match_input": False,
        "channel_ops_call_then_slack": False,
        "channel_inv_email": False,
        "channel_client_email": False,
        "channel_friend_whatsapp": False,
        "escalation_inv_true": False,
        "escalation_ops_true_if_keywords": False,
        "escalation_client_true_if_keywords": False,
        "escalation_friend_false": False,
        "schedule_inv_morning_true": False,
        "schedule_others_hours_rule": False,
        "no_commit_language_all": False,
        "summary_has_all_ids": False,
        "summary_escalation_count_matches": False,
    }

    # Load input requests for reference
    input_requests_path = os.path.join(input_dir, "requests.json")
    input_requests = read_json(input_requests_path)
    input_items: List[Dict[str, Any]] = input_requests if isinstance(input_requests, list) else []
    # Build reference maps and defaults
    default_expected_ids = {"ops-urgent-123", "inv-001", "client-complaint-77", "friend-042"}
    input_ids = set()
    id_to_request: Dict[str, Dict[str, Any]] = {}
    for item in input_items:
        if isinstance(item, dict):
            rid = item.get("id")
            if isinstance(rid, str):
                input_ids.add(rid)
                id_to_request[rid] = item
    if not input_ids:
        input_ids = default_expected_ids

    # Load outputs
    messages_path = os.path.join(output_dir, "messages.json")
    summary_path = os.path.join(output_dir, "summary.md")

    messages_data = None
    if os.path.isfile(messages_path):
        checks["has_messages_json"] = True
        messages_data = read_json(messages_path)

    if isinstance(messages_data, list) and len(messages_data) == 4:
        checks["messages_json_array_len_4"] = True

    # Validate fields and build id map for messages
    required_keys = [
        "id",
        "recommended_channel",
        "escalate",
        "schedule_for_morning",
        "timing_notes",
        "tone_notes",
        "draft",
    ]
    id_to_message: Dict[str, Dict[str, Any]] = {}
    if checks["messages_json_array_len_4"]:
        fields_ok = True
        for obj in messages_data:
            if not isinstance(obj, dict):
                fields_ok = False
                break
            for k in required_keys:
                if k not in obj:
                    fields_ok = False
                    break
            if not fields_ok:
                break
            # Type checks
            if not is_nonempty_string(obj.get("id")):
                fields_ok = False
                break
            if not is_nonempty_string(obj.get("recommended_channel")):
                fields_ok = False
                break
            if not to_bool(obj.get("escalate")):
                # escalate must be boolean
                fields_ok = False
                break
            if not to_bool(obj.get("schedule_for_morning")):
                # schedule_for_morning must be boolean
                fields_ok = False
                break
            if not is_nonempty_string(obj.get("timing_notes")):
                fields_ok = False
                break
            if not is_nonempty_string(obj.get("tone_notes")):
                fields_ok = False
                break
            if not is_nonempty_string(obj.get("draft")):
                fields_ok = False
                break
            id_to_message[obj["id"]] = obj
        if fields_ok:
            checks["messages_fields_valid"] = True

    # IDs match input
    if checks["messages_fields_valid"]:
        output_ids = set(id_to_message.keys())
        if output_ids == input_ids and len(output_ids) == 4:
            checks["ids_match_input"] = True

    # Channel selection constraints
    if checks["messages_fields_valid"]:
        # Expected channels by ID
        expected_channels = {
            "ops-urgent-123": "call_then_slack",
            "inv-001": "email",
            "client-complaint-77": "email",
            "friend-042": "whatsapp",
        }
        # ops
        ops_msg = id_to_message.get("ops-urgent-123")
        if isinstance(ops_msg, dict) and ops_msg.get("recommended_channel") == expected_channels["ops-urgent-123"]:
            checks["channel_ops_call_then_slack"] = True
        # inv
        inv_msg = id_to_message.get("inv-001")
        if isinstance(inv_msg, dict) and inv_msg.get("recommended_channel") == expected_channels["inv-001"]:
            checks["channel_inv_email"] = True
        # client
        client_msg = id_to_message.get("client-complaint-77")
        if isinstance(client_msg, dict) and client_msg.get("recommended_channel") == expected_channels["client-complaint-77"]:
            checks["channel_client_email"] = True
        # friend
        friend_msg = id_to_message.get("friend-042")
        if isinstance(friend_msg, dict) and friend_msg.get("recommended_channel") == expected_channels["friend-042"]:
            checks["channel_friend_whatsapp"] = True

    # Escalation logic
    if checks["messages_fields_valid"]:
        # investor must be escalated
        inv_m = id_to_message.get("inv-001")
        if isinstance(inv_m, dict) and inv_m.get("escalate") is True:
            checks["escalation_inv_true"] = True

        # ops emergency escalate if content contains urgency keywords
        ops_req = id_to_request.get("ops-urgent-123", {})
        ops_content = str(ops_req.get("content", "")).lower()
        ops_keywords = ["urgent", "emergency", "production down"]
        ops_triggers = any(kw in ops_content for kw in ops_keywords)
        ops_m = id_to_message.get("ops-urgent-123")
        if ops_triggers and isinstance(ops_m, dict) and ops_m.get("escalate") is True:
            checks["escalation_ops_true_if_keywords"] = True

        # client complaint escalate if complaint keywords present
        client_req = id_to_request.get("client-complaint-77", {})
        client_content = str(client_req.get("content", "")).lower()
        client_keywords = ["disappointed", "cancel", "refund", "contract"]
        client_triggers = any(kw in client_content for kw in client_keywords)
        client_m = id_to_message.get("client-complaint-77")
        if client_triggers and isinstance(client_m, dict) and client_m.get("escalate") is True:
            checks["escalation_client_true_if_keywords"] = True

        # friend must not be escalated
        friend_m = id_to_message.get("friend-042")
        if isinstance(friend_m, dict) and friend_m.get("escalate") is False:
            checks["escalation_friend_false"] = True

    # Timing rule
    if checks["messages_fields_valid"]:
        # inv-001 schedule_for_morning = true if recipient_local_hour < 6
        inv_req = id_to_request.get("inv-001", {})
        inv_hour = get_int(inv_req.get("recipient_local_hour"))
        inv_m = id_to_message.get("inv-001")
        if inv_m is not None and isinstance(inv_hour, int) and inv_hour < 6:
            if inv_m.get("schedule_for_morning") is True:
                checks["schedule_inv_morning_true"] = True

        # For all items: if recipient_local_hour is available
        # require schedule_for_morning True iff hour < 6, else False
        all_ok = True
        for rid, msg in id_to_message.items():
            req = id_to_request.get(rid, {})
            hour = get_int(req.get("recipient_local_hour"))
            if isinstance(hour, int):
                expected = (hour < 6)
                if msg.get("schedule_for_morning") is not expected:
                    all_ok = False
                    break
        checks["schedule_others_hours_rule"] = all_ok

    # No commitment language in drafts
    if checks["messages_fields_valid"]:
        banned_substrings = [
            "deliver by",
            "we can deliver by",
            "commit to",
            "guarantee",
            "refund approved",
            "we will refund",
        ]
        drafts_ok = True
        for msg in id_to_message.values():
            draft = str(msg.get("draft", "")).lower()
            if any(bad in draft for bad in banned_substrings):
                drafts_ok = False
                break
        checks["no_commit_language_all"] = drafts_ok

    # Summary checks
    summary_content = ""
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        summary_content = read_text(summary_path)

    if checks["has_summary_md"] and checks["messages_fields_valid"]:
        # Ensure each id appears in at least one line
        lines = [ln.strip() for ln in summary_content.splitlines()]
        ids_present = True
        for rid in id_to_message.keys():
            if not any(rid in ln for ln in lines):
                ids_present = False
                break
        checks["summary_has_all_ids"] = ids_present

        # Final line must be Escalations: X and match count
        non_empty_lines = [ln for ln in lines if ln.strip()]
        last_line = non_empty_lines[-1] if non_empty_lines else ""
        m = re.match(r"^Escalations:\s+(\d+)$", last_line.strip())
        if m:
            reported = int(m.group(1))
            actual = sum(1 for mobj in id_to_message.values() if mobj.get("escalate") is True)
            if reported == actual:
                checks["summary_escalation_count_matches"] = True

    # Compute reward as ratio of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no outputs at all, force reward to 0.0
    outputs_exist = os.path.isfile(messages_path) or os.path.isfile(summary_path)
    if not outputs_exist:
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()