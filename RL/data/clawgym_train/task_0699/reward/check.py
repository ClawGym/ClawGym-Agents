import json
import os
import sys
import re
import csv
from datetime import datetime, timezone

def parse_iso8601(dt_str):
    if not isinstance(dt_str, str):
        raise ValueError("Not a string")
    s = dt_str.strip()
    # Normalize Zulu time
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # fromisoformat handles most ISO 8601 variants including offsets
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Try a few fallback patterns without timezone
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        raise

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def load_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return True, rows
    except Exception:
        return False, []

def url_has_token_like(url):
    if not isinstance(url, str):
        return False
    if not url.lower().startswith("http"):
        return False
    if "prt_" in url:
        return True
    # Accept any 3-letter prefix underscore + alnum token-like segment length >= 6
    if re.search(r"\b[a-z]{3}_[A-Za-z0-9]{6,}\b", url):
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # created_poll.json
        "created_poll_exists": False,
        "created_poll_valid_json": False,
        "created_poll_required_fields": False,
        "slots_count_valid": False,
        "slots_parse_and_duration_valid": False,

        # slots.csv
        "slots_csv_exists": False,
        "slots_csv_header_valid": False,
        "slots_csv_count_matches_json": False,
        "slots_csv_parseable": False,
        "slots_csv_durations_match_json": False,

        # share_message.md
        "share_message_exists": False,
        "share_message_contains_url": False,
        "share_message_contains_please_vote": False,
        "share_message_mentions_purpose": False,

        # plan.md
        "plan_exists": False,
        "plan_min_length": False,
        "plan_contains_required_phrases": False,
        "plan_contains_url": False,
    }

    created_poll_path = os.path.join(output_dir, "created_poll.json")
    slots_csv_path = os.path.join(output_dir, "slots.csv")
    share_msg_path = os.path.join(output_dir, "share_message.md")
    plan_path = os.path.join(output_dir, "plan.md")

    # Variables to share across checks
    created = None
    json_slots = []
    json_slot_durations = []
    participate_url = None
    purpose_val = None

    # Check created_poll.json
    if os.path.isfile(created_poll_path):
        checks["created_poll_exists"] = True
        ok_json, created = safe_read_json(created_poll_path)
        if ok_json and isinstance(created, dict):
            checks["created_poll_valid_json"] = True

            # Required fields
            purpose = created.get("purpose")
            tz = created.get("timeZone")
            admin_token = created.get("adminToken")
            purl = created.get("participateUrl")
            assumptions = created.get("assumptions")

            purpose_ok = isinstance(purpose, str) and purpose.strip() != ""
            tz_ok = isinstance(tz, str) and tz.strip() != ""
            admin_ok = isinstance(admin_token, str) and re.fullmatch(r"adm_.+", admin_token or "") is not None
            url_ok = url_has_token_like(purl)
            assumptions_ok = (
                (isinstance(assumptions, str) and assumptions.strip() != "") or
                (isinstance(assumptions, list) and len(assumptions) > 0)
            )

            if purpose_ok and tz_ok and admin_ok and url_ok and assumptions_ok:
                checks["created_poll_required_fields"] = True
                participate_url = purl
                purpose_val = purpose

            # Slots checks
            slots = created.get("slots")
            if isinstance(slots, list) and 3 <= len(slots) <= 6:
                checks["slots_count_valid"] = True
                all_ok = True
                json_slot_durations = []
                json_slots = slots
                for slot in slots:
                    if not isinstance(slot, dict):
                        all_ok = False
                        break
                    start = slot.get("start")
                    end = slot.get("end")
                    try:
                        ds = parse_iso8601(start)
                        de = parse_iso8601(end)
                        if de <= ds:
                            all_ok = False
                            break
                        dur_min = (de - ds).total_seconds() / 60.0
                        json_slot_durations.append(dur_min)
                        # duration 60 +/- 2 minutes tolerance
                        if abs(dur_min - 60.0) > 2.0:
                            all_ok = False
                            break
                    except Exception:
                        all_ok = False
                        break
                if all_ok:
                    checks["slots_parse_and_duration_valid"] = True

    # slots.csv checks
    if os.path.isfile(slots_csv_path):
        checks["slots_csv_exists"] = True
        ok_csv, rows = load_csv_rows(slots_csv_path)
        if ok_csv and rows:
            header = rows[0]
            if header == ["slot_id", "start_iso", "end_iso", "tz"]:
                checks["slots_csv_header_valid"] = True

            data_rows = rows[1:] if len(rows) > 1 else []
            # Count matches JSON slots
            if checks["slots_count_valid"]:
                if len(data_rows) == len(json_slots):
                    checks["slots_csv_count_matches_json"] = True

            # Parseable and durations
            csv_ok = True
            csv_durations = []
            for r in data_rows:
                # Allow rows shorter/longer but need at least 4 columns
                if len(r) < 4:
                    csv_ok = False
                    break
                start_iso = r[1].strip()
                end_iso = r[2].strip()
                try:
                    ds = parse_iso8601(start_iso)
                    de = parse_iso8601(end_iso)
                    if de <= ds:
                        csv_ok = False
                        break
                    dur_min = (de - ds).total_seconds() / 60.0
                    # Ensure reasonable slot duration
                    if dur_min <= 0:
                        csv_ok = False
                        break
                    csv_durations.append(dur_min)
                except Exception:
                    csv_ok = False
                    break
            if csv_ok:
                checks["slots_csv_parseable"] = True
                # Compare durations with JSON within 2 minutes tolerance
                if checks["slots_count_valid"] and len(csv_durations) == len(json_slot_durations):
                    # Compare pairwise; tolerant approach: all corresponding within 2 minutes
                    pairwise_ok = True
                    for a, b in zip(sorted(json_slot_durations), sorted(csv_durations)):
                        if abs(a - b) > 2.0:
                            pairwise_ok = False
                            break
                    if pairwise_ok:
                        checks["slots_csv_durations_match_json"] = True

    # share_message.md checks
    if os.path.isfile(share_msg_path):
        checks["share_message_exists"] = True
        ok_txt, share_txt = read_text(share_msg_path)
        if ok_txt and isinstance(share_txt, str):
            if participate_url and participate_url in share_txt:
                checks["share_message_contains_url"] = True
            if re.search(r"please\s+vote", share_txt, flags=re.IGNORECASE):
                checks["share_message_contains_please_vote"] = True
            if purpose_val and re.search(re.escape(purpose_val), share_txt, flags=re.IGNORECASE):
                checks["share_message_mentions_purpose"] = True

    # plan.md checks
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        ok_plan, plan_txt = read_text(plan_path)
        if ok_plan and isinstance(plan_txt, str):
            if len(plan_txt) >= 200:
                checks["plan_min_length"] = True
            phrases_ok = (
                re.search(r"admin\s+token", plan_txt, flags=re.IGNORECASE) is not None and
                re.search(r"results", plan_txt, flags=re.IGNORECASE) is not None and
                re.search(r"close", plan_txt, flags=re.IGNORECASE) is not None and
                re.search(r"poll", plan_txt, flags=re.IGNORECASE) is not None
            )
            if phrases_ok:
                checks["plan_contains_required_phrases"] = True
            if participate_url and participate_url in plan_txt:
                checks["plan_contains_url"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure exact 0.0 when no outputs were produced (no-op baseline)
    output_present = any(os.path.isfile(os.path.join(output_dir, fname)) for fname in [
        "created_poll.json", "slots.csv", "share_message.md", "plan.md"
    ])
    if not output_present:
        reward = 0.0

    # Print result JSON (reward first key)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()