import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_message_from_job(job):
    msg = job.get("message")
    if isinstance(msg, str):
        return msg
    payload = job.get("payload", {})
    if isinstance(payload, dict):
        txt = payload.get("text")
        if isinstance(txt, str):
            return txt
    return ""

def starts_with_reminder(text):
    if not isinstance(text, str):
        return False
    return text.strip().startswith("Reminder:")

def any_contains(text, substrings):
    t = (text or "")
    tl = t.lower()
    for s in substrings:
        if s in tl:
            return True
    return False

def find_job_ids_by_keywords(current_jobs_data, keywords):
    ids = set()
    # current_jobs may be a list or dict with "jobs"
    entries = []
    if isinstance(current_jobs_data, list):
        entries = current_jobs_data
    elif isinstance(current_jobs_data, dict):
        if isinstance(current_jobs_data.get("jobs"), list):
            entries = current_jobs_data.get("jobs")
        else:
            # consider values if dict of jobs keyed by id
            entries = list(current_jobs_data.values())
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text_fields = []
        for k in ("name", "summary", "message"):
            v = entry.get(k)
            if isinstance(v, str):
                text_fields.append(v)
        payload = entry.get("payload")
        if isinstance(payload, dict):
            for k in ("text", "name", "summary", "message"):
                v = payload.get(k)
                if isinstance(v, str):
                    text_fields.append(v)
        combined = " ".join(text_fields).lower()
        if any(kw in combined for kw in keywords):
            job_id = entry.get("jobId") or entry.get("id")
            if isinstance(job_id, str):
                ids.add(job_id)
    return ids

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # proposed_schedules.json checks
        "proposed_exists": False,
        "proposed_valid_json": False,
        "proposed_len_ge_3": False,
        "proposed_all_fields_present": False,
        "proposed_messages_prefixed": False,
        # clarifications.md checks
        "clarifications_exists": False,
        "clarifications_contains_morning": False,
        # jobs.json checks
        "jobs_exists": False,
        "jobs_valid_json": False,
        "jobs_has_one_at_contract": False,
        "jobs_has_one_cron_standup_or_drinkwater": False,
        "jobs_all_payload_kind_systemEvent": False,
        "jobs_all_sessionTarget_main": False,
        "jobs_all_messages_prefixed": False,
        "jobs_no_sensitive_substrings": False,
        "jobs_recurring_all_confirmed": False,
        # actions.json checks
        "actions_exists": False,
        "actions_valid_json": False,
        "actions_cancel_matches_standup_jobId": False,
        "actions_snooze_matches_coffee_break_jobId": False,
        "actions_snooze_minutes_15": False,
        # warnings.md checks
        "warnings_exists": False,
        "warnings_mentions_prod_launch": False,
        "warnings_mentions_public_visibility": False,
    }

    # Proposed schedules
    proposed_path = os.path.join(output_dir, "proposed_schedules.json")
    proposed_data = load_json(proposed_path)
    if proposed_data is not None:
        checks["proposed_exists"] = True
        if isinstance(proposed_data, list):
            checks["proposed_valid_json"] = True
            if len(proposed_data) >= 3:
                checks["proposed_len_ge_3"] = True
            all_fields_ok = True
            all_prefixed = True
            for entry in proposed_data:
                if not isinstance(entry, dict):
                    all_fields_ok = False
                    all_prefixed = False
                    break
                has_fields = (
                    "id" in entry and "type" in entry and "schedule_human" in entry and "timezone" in entry and "message" in entry
                )
                type_ok = entry.get("type") in ("one-shot", "recurring")
                message = entry.get("message")
                schedule_human = entry.get("schedule_human")
                timezone = entry.get("timezone")
                id_val = entry.get("id")
                field_types_ok = (
                    isinstance(id_val, (str, int)) and isinstance(schedule_human, str) and isinstance(timezone, str) and isinstance(message, str)
                )
                if not (has_fields and type_ok and field_types_ok):
                    all_fields_ok = False
                if not starts_with_reminder(message):
                    all_prefixed = False
            if all_fields_ok:
                checks["proposed_all_fields_present"] = True
            if all_prefixed:
                checks["proposed_messages_prefixed"] = True

    # Clarifications
    clarifications_path = os.path.join(output_dir, "clarifications.md")
    clar_text = read_text(clarifications_path)
    if clar_text is not None:
        checks["clarifications_exists"] = True
        if "morning" in clar_text.lower():
            checks["clarifications_contains_morning"] = True

    # Jobs
    jobs_path = os.path.join(output_dir, "jobs.json")
    jobs_data = load_json(jobs_path)
    if jobs_data is not None:
        checks["jobs_exists"] = True
        jobs_list = None
        if isinstance(jobs_data, list):
            jobs_list = jobs_data
            checks["jobs_valid_json"] = True
        elif isinstance(jobs_data, dict) and isinstance(jobs_data.get("jobs"), list):
            jobs_list = jobs_data.get("jobs")
            checks["jobs_valid_json"] = True

        if isinstance(jobs_list, list):
            # payload.kind == systemEvent for all
            payload_ok_all = True
            session_target_ok_all = True
            messages_prefixed_all = True
            sensitive_absent_all = True
            has_at_contract = False
            has_cron_standup_or_water = False
            recurring_confirmed_all = True  # remains True only if every recurring has a confirmation flag True
            found_any_recurring = False

            for job in jobs_list:
                if not isinstance(job, dict):
                    payload_ok_all = False
                    session_target_ok_all = False
                    messages_prefixed_all = False
                    sensitive_absent_all = False
                    recurring_confirmed_all = False
                    continue
                payload_kind = None
                payload = job.get("payload")
                if isinstance(payload, dict):
                    payload_kind = payload.get("kind")
                if payload_kind != "systemEvent":
                    payload_ok_all = False

                session_target = job.get("sessionTarget")
                if session_target != "main":
                    session_target_ok_all = False

                message_text = get_message_from_job(job)
                if not starts_with_reminder(message_text):
                    messages_prefixed_all = False

                msg_lower = message_text.lower()
                if any_contains(msg_lower, ["token", "secret", "key"]):
                    sensitive_absent_all = False

                sched = job.get("schedule", {})
                if isinstance(sched, dict):
                    kind = sched.get("kind")
                    if kind == "at":
                        if "contract" in msg_lower or "send the contract" in msg_lower:
                            has_at_contract = True
                    elif kind == "cron":
                        if ("stand up" in msg_lower) or ("drink water" in msg_lower):
                            has_cron_standup_or_water = True
                        found_any_recurring = True
                        # confirmation flags
                        conf_flags = [
                            job.get("confirmed"),
                            job.get("explicit_confirmation"),
                            job.get("confirmation"),
                            sched.get("confirmed"),
                        ]
                        if True not in conf_flags:
                            recurring_confirmed_all = False

            if payload_ok_all:
                checks["jobs_all_payload_kind_systemEvent"] = True
            if session_target_ok_all:
                checks["jobs_all_sessionTarget_main"] = True
            if messages_prefixed_all:
                checks["jobs_all_messages_prefixed"] = True
            if sensitive_absent_all:
                checks["jobs_no_sensitive_substrings"] = True
            if has_at_contract:
                checks["jobs_has_one_at_contract"] = True
            if has_cron_standup_or_water:
                checks["jobs_has_one_cron_standup_or_drinkwater"] = True
            # If there are no recurring jobs, the requirement cannot be met; keep False
            if found_any_recurring and recurring_confirmed_all:
                checks["jobs_recurring_all_confirmed"] = True

    # Actions
    actions_path = os.path.join(output_dir, "actions.json")
    actions_data = load_json(actions_path)
    if actions_data is not None:
        checks["actions_exists"] = True
        if isinstance(actions_data, dict):
            checks["actions_valid_json"] = True
            cancel_obj = actions_data.get("cancel")
            snooze_obj = actions_data.get("snooze")
            # minutes check
            if isinstance(snooze_obj, dict) and snooze_obj.get("minutes") == 15:
                checks["actions_snooze_minutes_15"] = True

            # Read current_jobs.json for jobId mapping only if outputs exist
            current_jobs_path = os.path.join(input_dir, "current_jobs.json")
            current_jobs_data = load_json(current_jobs_path)

            standup_ids = set()
            coffee_ids = set()
            if current_jobs_data is not None:
                standup_ids = find_job_ids_by_keywords(current_jobs_data, ["stand up"])
                coffee_ids = find_job_ids_by_keywords(current_jobs_data, ["coffee break"])

            if isinstance(cancel_obj, dict):
                cj_id = cancel_obj.get("jobId")
                if isinstance(cj_id, str) and cj_id in standup_ids and len(standup_ids) > 0:
                    checks["actions_cancel_matches_standup_jobId"] = True

            if isinstance(snooze_obj, dict):
                sj_id = snooze_obj.get("jobId")
                if isinstance(sj_id, str) and sj_id in coffee_ids and len(coffee_ids) > 0:
                    checks["actions_snooze_matches_coffee_break_jobId"] = True

    # Warnings
    warnings_path = os.path.join(output_dir, "warnings.md")
    warnings_text = read_text(warnings_path)
    if warnings_text is not None:
        checks["warnings_exists"] = True
        wlower = warnings_text.lower()
        if "#prod-launch" in warnings_text:
            checks["warnings_mentions_prod_launch"] = True
        if ("public" in wlower) and (("visibility" in wlower) or ("visible" in wlower)):
            checks["warnings_mentions_public_visibility"] = True

    # Compute reward: average of passed checks
    total_points = len(checks)
    passed_points = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_points > 0:
        reward = passed_points / total_points
    # No-op baseline: if output dir missing or all outputs missing, reward should be 0.0
    output_exists = os.path.isdir(output_dir)
    if not output_exists:
        reward = 0.0
    else:
        # If none of the primary artifacts exist, force 0.0
        primary_artifacts_present = any(os.path.isfile(os.path.join(output_dir, f)) for f in [
            "proposed_schedules.json", "clarifications.md", "jobs.json", "actions.json", "warnings.md"
        ])
        if not primary_artifacts_present:
            reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()