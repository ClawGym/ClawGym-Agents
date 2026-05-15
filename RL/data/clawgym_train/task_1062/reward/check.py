import json
import os
import re
import sys
from datetime import datetime

def iso_like(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}T', s))

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_events_jsonl(path):
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    events.append(obj)
                except json.JSONDecodeError:
                    # Skip invalid lines
                    pass
    except Exception:
        return []
    return events

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_messages_json": False,
        "messages_schema_valid": False,
        "messages_count_matches_input": False,
        "titles_clean": False,
        "severity_priority_mapping": False,
        "ev002_read_and_archived": False,
        "others_unread_unarchived": False,
        "has_unread_json": False,
        "unread_json_counts_match": False,
        "unread_json_only_unread_nonarchived": False,
        "has_unread_html": False,
        "unread_html_has_header": False,
        "unread_html_priority_indicator_ok": False,
        "unread_html_no_urgent_if_no_unread_urgent": False,
        "has_all_md": False,
        "all_md_has_header": False,
        "all_md_no_urgent_if_no_nonarchived_urgent": False,
        "has_changelog": False,
        "changelog_mentions_ev002": False,
    }

    # Paths
    events_path = os.path.join(input_dir, "events.jsonl")
    messages_path = os.path.join(output_dir, "inbox", "messages.json")
    unread_json_path = os.path.join(output_dir, "inbox_unread.json")
    unread_html_path = os.path.join(output_dir, "inbox_unread.html")
    all_md_path = os.path.join(output_dir, "inbox_all.md")
    changelog_path = os.path.join(output_dir, "inbox_changelog.txt")

    events = parse_events_jsonl(events_path)

    # Load messages.json
    messages_data = load_json(messages_path)
    if isinstance(messages_data, dict):
        checks["has_messages_json"] = True

    messages = []
    if checks["has_messages_json"]:
        # Basic schema checks
        last_updated_ok = "lastUpdated" in messages_data and iso_like(messages_data.get("lastUpdated"))
        msgs = messages_data.get("messages")
        if isinstance(msgs, list) and last_updated_ok:
            # Validate each message object
            all_msgs_valid = True
            titles_clean = True
            for m in msgs:
                if not isinstance(m, dict):
                    all_msgs_valid = False
                    break
                # Required fields
                id_ok = isinstance(m.get("id"), str) and len(m.get("id", "")) > 0
                title_ok = isinstance(m.get("title"), str)
                message_ok = isinstance(m.get("message"), str)
                priority_ok = m.get("priority") in {"urgent", "important", "normal"}
                read_ok = isinstance(m.get("read"), bool)
                archived_ok = isinstance(m.get("archived"), bool)
                created_ok = isinstance(m.get("createdAt"), str) and iso_like(m.get("createdAt"))
                readAt_val = m.get("readAt")
                readAt_ok = (readAt_val is None) or (isinstance(readAt_val, str) and iso_like(readAt_val))
                if not (id_ok and title_ok and message_ok and priority_ok and read_ok and archived_ok and created_ok and readAt_ok):
                    all_msgs_valid = False
                    break
                # Title must not start with '[' (clean title requirement)
                if isinstance(m.get("title"), str) and m.get("title").startswith("["):
                    titles_clean = False
                messages.append(m)
            if all_msgs_valid:
                checks["messages_schema_valid"] = True
            if all_msgs_valid and titles_clean:
                checks["titles_clean"] = True

    # Count match with input events
    if checks["messages_schema_valid"]:
        if len(messages) == len(events) and len(events) > 0:
            checks["messages_count_matches_input"] = True

    # Build helper indices
    def lc(s): return (s or "").lower()

    # Map events to message by matching title substring
    severity_map = {"high": "urgent", "medium": "important", "low": "normal"}
    event_to_msg_index = {}
    evt_map_ok_count = 0
    ev002_idx = None

    if checks["messages_schema_valid"]:
        for i, ev in enumerate(events):
            ev_title = lc(ev.get("title", ""))
            ev_sev = lc(ev.get("severity", ""))
            wanted_priority = severity_map.get(ev_sev)
            matched_idx = None
            matched_priority_ok = False
            for j, m in enumerate(messages):
                if ev_title and ev_title in lc(m.get("title", "")):
                    matched_idx = j
                    if wanted_priority is not None and m.get("priority") == wanted_priority:
                        matched_priority_ok = True
                    break
            if matched_idx is not None and matched_priority_ok:
                evt_map_ok_count += 1
                event_to_msg_index[i] = matched_idx
            # Track EV-002 index (by event_id)
            if str(ev.get("event_id", "")) == "EV-002":
                ev002_idx = matched_idx

        if evt_map_ok_count == len(events) and len(events) > 0:
            checks["severity_priority_mapping"] = True

    # EV-002 must be read and archived with non-null readAt; others must be unread and unarchived
    if checks["messages_schema_valid"] and checks["severity_priority_mapping"]:
        ev002_ok = False
        others_ok = True
        # EV-002
        if ev002_idx is not None:
            m = messages[ev002_idx]
            if m.get("read") is True and m.get("archived") is True and (isinstance(m.get("readAt"), str) and iso_like(m.get("readAt"))):
                ev002_ok = True
        # Others
        ev002_msg_obj = messages[ev002_idx] if ev002_idx is not None else None
        for m in messages:
            if ev002_msg_obj is not None and m is ev002_msg_obj:
                continue
            # All others should be read=false and archived=false
            if not (m.get("read") is False and m.get("archived") is False):
                others_ok = False
                break
        if ev002_ok:
            checks["ev002_read_and_archived"] = True
        if others_ok:
            checks["others_unread_unarchived"] = True

    # Compute counts for unread/archived/non-archived
    unread_nonarch = []
    nonarch = []
    archived = []
    if checks["messages_schema_valid"]:
        for m in messages:
            if m.get("archived"):
                archived.append(m)
            else:
                nonarch.append(m)
                if not m.get("read"):
                    unread_nonarch.append(m)

    # unread.json checks
    unread_json = load_json(unread_json_path)
    if isinstance(unread_json, dict):
        checks["has_unread_json"] = True
        msgs_arr = unread_json.get("messages")
        unread_num = unread_json.get("unread")
        total_num = unread_json.get("total")
        archived_num = unread_json.get("archived")
        if isinstance(msgs_arr, list) and isinstance(unread_num, int) and isinstance(total_num, int) and isinstance(archived_num, int):
            # Counts
            if checks["messages_schema_valid"]:
                if unread_num == len(unread_nonarch) and total_num == len(nonarch) and archived_num == len(archived):
                    checks["unread_json_counts_match"] = True
            # Ensure messages are only unread & non-archived (as far as we can tell)
            only_unread_nonarch = True
            allowed_titles = set(m.get("title") for m in unread_nonarch if isinstance(m.get("title"), str))
            for itm in msgs_arr:
                if isinstance(itm, dict):
                    # If present, enforce read/archived flags
                    if "read" in itm and itm.get("read") is not False:
                        only_unread_nonarch = False
                        break
                    if "archived" in itm and itm.get("archived") is not False:
                        only_unread_nonarch = False
                        break
                    # If title present, ensure it maps to an allowed unread/non-archived title
                    if "title" in itm and isinstance(itm.get("title"), str):
                        if itm["title"] not in allowed_titles:
                            # Not strictly failing if agent omitted titles; but if present and not matching, fail
                            only_unread_nonarch = False
                            break
                else:
                    # Non-dict entry cannot be validated; mark as fail
                    only_unread_nonarch = False
                    break
            if only_unread_nonarch:
                checks["unread_json_only_unread_nonarchived"] = True

    # unread.html checks
    unread_html = load_text(unread_html_path)
    if isinstance(unread_html, str):
        checks["has_unread_html"] = True
        if "<b>📬 Inbox</b>" in unread_html:
            checks["unread_html_has_header"] = True

        # Priority indicator presence logic:
        # If there is at least one unread important -> expect "[IMPORTANT]"
        # Else if at least one unread urgent -> expect "[URGENT]"
        # Else (no unread urgent or important), pass by default
        unread_important = [m for m in unread_nonarch if m.get("priority") == "important"]
        unread_urgent = [m for m in unread_nonarch if m.get("priority") == "urgent"]
        priority_indicator_ok = False
        if len(unread_important) > 0:
            priority_indicator_ok = ("[IMPORTANT]" in unread_html)
        elif len(unread_urgent) > 0:
            priority_indicator_ok = ("[URGENT]" in unread_html)
        else:
            # Only normal items; no tag required
            priority_indicator_ok = True
        if priority_indicator_ok:
            checks["unread_html_priority_indicator_ok"] = True

        # If there are urgent items but none are unread (i.e., all urgent are archived or read+archived),
        # ensure the unread HTML does NOT contain "URGENT"
        total_urgent = [m for m in messages if m.get("priority") == "urgent"]
        if len(total_urgent) > 0 and len(unread_urgent) == 0:
            if "URGENT" not in unread_html:
                checks["unread_html_no_urgent_if_no_unread_urgent"] = True
        else:
            # Not applicable; consider as pass since requirement is conditional
            checks["unread_html_no_urgent_if_no_unread_urgent"] = True

    # all.md checks
    all_md = load_text(all_md_path)
    if isinstance(all_md, str):
        checks["has_all_md"] = True
        if "**📬 Inbox**" in all_md:
            checks["all_md_has_header"] = True
        # If there are no non-archived urgent items (i.e., all urgent items are archived),
        # ensure file does NOT contain "URGENT"
        nonarch_urgent = [m for m in nonarch if m.get("priority") == "urgent"]
        archived_urgent = [m for m in archived if m.get("priority") == "urgent"]
        if len(nonarch_urgent) == 0 and len(archived_urgent) > 0:
            if "URGENT" not in all_md:
                checks["all_md_no_urgent_if_no_nonarchived_urgent"] = True
        else:
            # Not applicable; pass
            checks["all_md_no_urgent_if_no_nonarchived_urgent"] = True

    # changelog checks
    changelog = load_text(changelog_path)
    if isinstance(changelog, str) and len(changelog.strip()) > 0:
        checks["has_changelog"] = True
        lower_ch = changelog.lower()
        if ("ev-002" in lower_ch) and ("read" in lower_ch) and ("archiv" in lower_ch):
            checks["changelog_mentions_ev002"] = True

    # Compute reward
    # No-op baseline: if no output artifacts, reward must be 0.0; this will naturally result as all checks False.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Guard numeric bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()