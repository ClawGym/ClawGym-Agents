import json
import os
import re
import sys

def load_json(path):
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

def count_words(text):
    # Simple word count by whitespace
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def has_heading(text, target_variants):
    # Match lines that equal a target heading (case-insensitive), trimming spaces
    lines = [ln.strip() for ln in text.splitlines()]
    low_lines = [ln.lower() for ln in lines]
    targets = [t.lower() for t in target_variants]
    for ln in low_lines:
        if ln in targets:
            return True
    return False

def is_int_in_range(value, low, high):
    if isinstance(value, bool):  # exclude booleans which are ints in Python
        return False
    if isinstance(value, int):
        return low <= value <= high
    return False

def is_number_or_null(value):
    if value is None:
        return True
    if isinstance(value, bool):  # exclude booleans
        return False
    return isinstance(value, (int, float))

def validate_session_log(obj):
    checks = {
        "session_log_json_valid": False,
        "session_log_top_keys_exact": False,
        "agent_name_unique_pattern": False,
        "mission_nonempty": False,
        "check_in_success_boolean": False,
        "check_in_nightstand_echo_type": False,
        "check_in_room_type_type": False,
        "interactions_feed_sample_sufficient": False,
        "interactions_shout_content_length_ok": False,
        "interactions_replies_present_and_valid": False,
        "interactions_endorsements_present_and_valid": False,
        "interactions_dm_fields_valid": False,
        "karma_plan_actions_valid": False,
        "karma_plan_pre_post_types_ok": False,
        "thread_fields_valid": False,
        "art_gallery_fields_valid": False,
        "art_dream_fields_valid": False,
        "complaints_fields_valid": False,
        "errors_array_valid": False,
    }

    if not isinstance(obj, dict):
        return checks

    checks["session_log_json_valid"] = True

    expected_top_keys = [
        "agent_name",
        "mission",
        "check_in",
        "interactions",
        "karma_plan",
        "thread",
        "art_contributions",
        "complaints",
        "errors"
    ]
    obj_keys = list(obj.keys())
    # Exact top-level key set regardless of order
    checks["session_log_top_keys_exact"] = set(obj_keys) == set(expected_top_keys)

    # agent_name pattern
    agent_name = obj.get("agent_name")
    if isinstance(agent_name, str) and agent_name.strip():
        if re.fullmatch(r".+[-_][0-9]{4,}", agent_name.strip()):
            checks["agent_name_unique_pattern"] = True

    # mission non-empty
    mission = obj.get("mission")
    if isinstance(mission, str) and mission.strip():
        checks["mission_nonempty"] = True

    # check_in fields
    check_in = obj.get("check_in")
    if isinstance(check_in, dict):
        ci_success = check_in.get("success")
        if isinstance(ci_success, bool):
            checks["check_in_success_boolean"] = True
        nightstand = check_in.get("nightstand_echo", "MISSING_SENTINEL")
        if nightstand is None or isinstance(nightstand, str):
            checks["check_in_nightstand_echo_type"] = (nightstand != "MISSING_SENTINEL")
        room_type = check_in.get("room_type", "MISSING_SENTINEL")
        if room_type is None or isinstance(room_type, str):
            checks["check_in_room_type_type"] = (room_type != "MISSING_SENTINEL")

    # interactions
    interactions = obj.get("interactions")
    if isinstance(interactions, dict):
        # feed_sample
        feed_sample = interactions.get("feed_sample")
        if isinstance(feed_sample, list) and len(feed_sample) >= 3:
            valid_items = True
            for it in feed_sample:
                if not isinstance(it, dict):
                    valid_items = False
                    break
                idv = it.get("id")
                auth = it.get("author")
                if not (isinstance(idv, str) and idv.strip() and isinstance(auth, str) and auth.strip()):
                    valid_items = False
                    break
            if valid_items:
                checks["interactions_feed_sample_sufficient"] = True
        # shout
        shout = interactions.get("shout")
        if isinstance(shout, dict):
            content = shout.get("content")
            if isinstance(content, str) and len(content) >= 20:
                checks["interactions_shout_content_length_ok"] = True
        # replies
        replies = interactions.get("replies")
        if isinstance(replies, list) and len(replies) >= 1:
            valid_replies = True
            for rp in replies:
                if not isinstance(rp, dict):
                    valid_replies = False
                    break
                rto = rp.get("reply_to")
                rc = rp.get("content")
                if not (isinstance(rto, str) and rto.strip() and isinstance(rc, str) and rc.strip()):
                    valid_replies = False
                    break
            if valid_replies:
                checks["interactions_replies_present_and_valid"] = True
        # endorsements
        endorsements = interactions.get("endorsements")
        if isinstance(endorsements, list) and len(endorsements) >= 1:
            valid_ends = True
            for en in endorsements:
                if not isinstance(en, dict):
                    valid_ends = False
                    break
                tid = en.get("target_id")
                if not (isinstance(tid, str) and tid.strip()):
                    valid_ends = False
                    break
            if valid_ends:
                checks["interactions_endorsements_present_and_valid"] = True
        # dm
        dm = interactions.get("dm")
        if isinstance(dm, dict):
            attempted = dm.get("attempted")
            result = dm.get("result")
            valid = isinstance(attempted, bool) and (result in ("sent", "skipped"))
            if valid and result == "skipped":
                # If reason present, must be non-empty
                if "reason" in dm:
                    valid = isinstance(dm["reason"], str) and dm["reason"].strip() != ""
            if valid:
                checks["interactions_dm_fields_valid"] = True

    # karma_plan
    karma_plan = obj.get("karma_plan")
    if isinstance(karma_plan, dict):
        # actions must contain at least one of minibar or garden
        actions = karma_plan.get("actions")
        if isinstance(actions, list) and len(actions) >= 1:
            lowered = [str(a).lower() for a in actions]
            if ("minibar" in lowered) or ("garden" in lowered):
                checks["karma_plan_actions_valid"] = True
        pre_k = karma_plan.get("pre_karma", "MISSING_SENTINEL")
        post_k = karma_plan.get("post_karma", "MISSING_SENTINEL")
        if pre_k != "MISSING_SENTINEL" and post_k != "MISSING_SENTINEL":
            if is_number_or_null(pre_k) and is_number_or_null(post_k):
                checks["karma_plan_pre_post_types_ok"] = True

    # thread
    thread = obj.get("thread")
    if isinstance(thread, dict):
        attempted = thread.get("attempted", "MISSING")
        valid_thread = isinstance(attempted, bool)
        if valid_thread and attempted:
            mode = thread.get("mode")
            mode_ok = mode in ("joined", "created")
            has_id_or_name = isinstance(thread.get("thread_id"), str) or isinstance(thread.get("thread_name"), str)
            valid_thread = mode_ok and has_id_or_name
        if valid_thread and not attempted:
            # if reason present, it must be non-empty string
            if "reason" in thread:
                reason = thread.get("reason")
                valid_thread = isinstance(reason, str) and reason.strip() != ""
        if valid_thread:
            checks["thread_fields_valid"] = True

    # art_contributions
    art = obj.get("art_contributions")
    if isinstance(art, dict):
        gallery = art.get("gallery")
        if isinstance(gallery, dict):
            gal_attempted = gallery.get("attempted", "MISSING")
            valid_gallery = isinstance(gal_attempted, bool)
            if valid_gallery and gal_attempted:
                x = gallery.get("x")
                y = gallery.get("y")
                color = gallery.get("color")
                valid_gallery = (
                    is_int_in_range(x, 0, 63) and
                    is_int_in_range(y, 0, 63) and
                    isinstance(color, str) and re.fullmatch(r"^#[0-9A-Fa-f]{6}$", color) is not None
                )
            if valid_gallery:
                checks["art_gallery_fields_valid"] = True
        dream = art.get("dream")
        if isinstance(dream, dict):
            dr_attempted = dream.get("attempted", "MISSING")
            valid_dream = isinstance(dr_attempted, bool)
            if valid_dream and dr_attempted:
                payload = dream.get("binary_payload")
                valid_dream = isinstance(payload, str) and len(payload) == 24 and re.fullmatch(r"^[01]{24}$", payload) is not None
            if valid_dream:
                checks["art_dream_fields_valid"] = True

    # complaints
    complaints = obj.get("complaints")
    if isinstance(complaints, dict):
        cnt = complaints.get("count", None)
        items = complaints.get("items", None)
        valid_complaints = isinstance(cnt, int) and cnt >= 0
        if valid_complaints:
            if cnt == 0:
                valid_complaints = isinstance(items, list) and len(items) == 0
            else:
                if isinstance(items, list) and len(items) == cnt:
                    each_ok = True
                    for it in items:
                        if not isinstance(it, dict):
                            each_ok = False
                            break
                        rt = it.get("request_type")
                        msg = it.get("message")
                        if not (isinstance(rt, str) and rt.strip() and isinstance(msg, str) and msg.strip()):
                            each_ok = False
                            break
                    valid_complaints = each_ok
                else:
                    valid_complaints = False
        if valid_complaints:
            checks["complaints_fields_valid"] = True

    # errors
    errors = obj.get("errors", None)
    if isinstance(errors, list):
        checks["errors_array_valid"] = True

    return checks

def validate_transcript(path):
    checks = {
        "transcript_parses_and_min_lines": False,
        "transcript_required_actions_present": False
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return checks

    # Remove empty lines
    content_lines = [ln for ln in lines if ln.strip() != ""]
    parsed = []
    for ln in content_lines:
        try:
            obj = json.loads(ln)
            parsed.append(obj)
        except Exception:
            parsed = None
            break

    if parsed is not None and len(parsed) >= 6:
        checks["transcript_parses_and_min_lines"] = True
        actions = set()
        for obj in parsed:
            if isinstance(obj, dict):
                act = obj.get("action")
                if isinstance(act, str):
                    actions.add(act)
        required = {"check_in", "get_motel_feed", "interact_shout", "interact_reply", "endorse"}
        if required.issubset(actions):
            checks["transcript_required_actions_present"] = True

    return checks

def validate_reflection(text):
    checks = {
        "reflection_min_word_count": False,
        "reflection_has_required_headings": False
    }
    if count_words(text) >= 200:
        checks["reflection_min_word_count"] = True
    # Headings variants for the middle one
    what_worked = ["What worked"]
    what_didnt = ["What didn’t", "What didn't"]
    next_steps = ["Next steps"]
    has_all = (
        has_heading(text, what_worked) and
        has_heading(text, what_didnt) and
        has_heading(text, next_steps)
    )
    if has_all:
        checks["reflection_has_required_headings"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        "all_required_outputs_exist": False,
        "session_log_exists": False,
        "session_log_json_valid": False,
        "session_log_top_keys_exact": False,
        "agent_name_unique_pattern": False,
        "mission_nonempty": False,
        "check_in_success_boolean": False,
        "check_in_nightstand_echo_type": False,
        "check_in_room_type_type": False,
        "interactions_feed_sample_sufficient": False,
        "interactions_shout_content_length_ok": False,
        "interactions_replies_present_and_valid": False,
        "interactions_endorsements_present_and_valid": False,
        "interactions_dm_fields_valid": False,
        "karma_plan_actions_valid": False,
        "karma_plan_pre_post_types_ok": False,
        "thread_fields_valid": False,
        "art_gallery_fields_valid": False,
        "art_dream_fields_valid": False,
        "complaints_fields_valid": False,
        "errors_array_valid": False,
        "transcript_exists": False,
        "transcript_parses_and_min_lines": False,
        "transcript_required_actions_present": False,
        "reflection_exists": False,
        "reflection_min_word_count": False,
        "reflection_has_required_headings": False
    }

    # Required artifacts
    session_log_path = os.path.join(output_dir, "session_log.json")
    transcript_path = os.path.join(output_dir, "transcript.jsonl")
    reflection_path = os.path.join(output_dir, "reflection.md")

    # Existence checks
    session_exists = os.path.isfile(session_log_path)
    transcript_exists = os.path.isfile(transcript_path)
    reflection_exists = os.path.isfile(reflection_path)

    checks["session_log_exists"] = session_exists
    checks["transcript_exists"] = transcript_exists
    checks["reflection_exists"] = reflection_exists
    checks["all_required_outputs_exist"] = (session_exists and transcript_exists and reflection_exists)

    # Validate session_log.json
    if session_exists:
        ok, data = load_json(session_log_path)
        if ok:
            sess_checks = validate_session_log(data)
            for k, v in sess_checks.items():
                checks[k] = v

    # Validate transcript.jsonl
    if transcript_exists:
        tr_checks = validate_transcript(transcript_path)
        for k, v in tr_checks.items():
            checks[k] = v

    # Validate reflection.md
    if reflection_exists:
        ok, text = read_text(reflection_path)
        if ok:
            refl_checks = validate_reflection(text)
            for k, v in refl_checks.items():
                checks[k] = v

    # Compute reward
    # No-op baseline: if any required artifact missing, reward must be exactly 0.0
    if not checks["all_required_outputs_exist"]:
        reward = 0.0
    else:
        # Count only validation checks (exclude existence aggregation flag)
        scored_keys = [k for k in checks.keys() if k != "all_required_outputs_exist"]
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks[k])
        reward = (passed / total) if total > 0 else 0.0
        # Clamp
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()