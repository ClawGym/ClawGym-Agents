import json
import os
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().splitlines()
    except Exception:
        return None

def is_nonempty_line(line):
    return bool(line.strip())

def validate_calendar_item(obj):
    # Must be a dict with required fields and types
    if not isinstance(obj, dict):
        return False, False  # fields_ok, requires_true
    required_keys = ["action", "title", "requested_by", "proposed_time", "reason", "requires_confirmation"]
    for k in required_keys:
        if k not in obj:
            return False, False
    # Validate fields
    if not isinstance(obj["action"], str):
        return False, False
    if obj["action"] not in {"schedule", "reschedule", "decline", "hold"}:
        return False, False
    if not isinstance(obj["title"], str):
        return False, False
    if not isinstance(obj["requested_by"], str):
        return False, False
    pt = obj["proposed_time"]
    if pt is not None:
        if not isinstance(pt, dict):
            return False, False
        if "start" not in pt or "duration_min" not in pt:
            return False, False
        if not isinstance(pt["start"], str):
            return False, False
        if not isinstance(pt["duration_min"], (int, float)):
            return False, False
    if not isinstance(obj["reason"], str):
        return False, False
    requires_ok = (obj["requires_confirmation"] is True)
    return True, requires_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Drafts
        "drafts_dir_exists": False,
        "drafts_five_files": False,
        "drafts_subject_lines_all": False,
        "drafts_min_lines_all": False,
        # Calendar actions
        "calendar_actions_exists": False,
        "calendar_actions_valid_json": False,
        "calendar_actions_array_len_ge4": False,
        "calendar_actions_item_fields_all": False,
        "calendar_actions_requires_confirmation_all_true": False,
        "calendar_actions_has_decline": False,
        "calendar_actions_has_schedule_or_reschedule": False,
        # Brief
        "brief_exists": False,
        "brief_has_sections": False,
        # Memory and rules
        "memory_exists": False,
        "memory_lines_le_100": False,
        "memory_has_quick_rules": False,
        "memory_has_index_people_calendar": False,
        "memory_has_no_monday_morning": False,
        "memory_has_15min_buffer": False,
        "memory_has_prep_30min": False,
        "memory_has_investor_vip_always_accept": False,
        # Calendar rules file
        "calendar_rules_exists": False,
        "calendar_rules_protected_mornings_until_10": False,
        "calendar_rules_friday_afternoons_no_external": False,
        "calendar_rules_buffer_15_minutes": False,
        "calendar_rules_default_length_30": False,
        # People file
        "people_exists": False,
        "people_has_maria_chen": False,
        "people_has_david_cto": False,
    }

    # Drafts checks
    drafts_dir = os.path.join(output_dir, "drafts")
    if os.path.isdir(drafts_dir):
        checks["drafts_dir_exists"] = True
        draft_files = [os.path.join(drafts_dir, f"email_{i}.md") for i in range(1, 6)]
        if all(os.path.isfile(p) for p in draft_files):
            checks["drafts_five_files"] = True
            subjects_ok = True
            lines_ok = True
            for p in draft_files:
                lines = read_lines(p)
                if lines is None:
                    subjects_ok = False
                    lines_ok = False
                    break
                has_subject = any(l.lstrip().startswith("Subject:") for l in lines)
                nonempty_count = sum(1 for l in lines if is_nonempty_line(l))
                if not has_subject:
                    subjects_ok = False
                if nonempty_count < 3:
                    lines_ok = False
            if subjects_ok:
                checks["drafts_subject_lines_all"] = True
            if lines_ok:
                checks["drafts_min_lines_all"] = True

    # Calendar actions checks
    cal_actions_path = os.path.join(output_dir, "calendar_actions.json")
    cal_data = None
    if os.path.isfile(cal_actions_path):
        checks["calendar_actions_exists"] = True
        try:
            with open(cal_actions_path, "r", encoding="utf-8") as f:
                cal_data = json.load(f)
            checks["calendar_actions_valid_json"] = isinstance(cal_data, list)
        except Exception:
            cal_data = None
    if isinstance(cal_data, list):
        if len(cal_data) >= 4:
            checks["calendar_actions_array_len_ge4"] = True
        fields_all = True
        requires_all_true = True
        has_decline = False
        has_sched_or_resched = False
        for item in cal_data:
            fields_ok, requires_ok = validate_calendar_item(item)
            if not fields_ok:
                fields_all = False
            if not requires_ok:
                requires_all_true = False
            if isinstance(item, dict) and "action" in item:
                act = item["action"]
                if act == "decline":
                    has_decline = True
                if act in {"schedule", "reschedule"}:
                    has_sched_or_resched = True
        if fields_all:
            checks["calendar_actions_item_fields_all"] = True
        if requires_all_true:
            checks["calendar_actions_requires_confirmation_all_true"] = True
        if has_decline:
            checks["calendar_actions_has_decline"] = True
        if has_sched_or_resched:
            checks["calendar_actions_has_schedule_or_reschedule"] = True

    # Brief checks
    brief_path = os.path.join(output_dir, "briefs", "brief_board_meeting.md")
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        content = read_text(brief_path) or ""
        lc = content.lower()
        needed = ["attendee brief", "context", "logistics", "talking points"]
        if all(s in lc for s in needed):
            checks["brief_has_sections"] = True

    # Memory checks
    memory_path = os.path.join(output_dir, "secretary", "memory.md")
    mem_content = None
    if os.path.isfile(memory_path):
        checks["memory_exists"] = True
        mem_lines = read_lines(memory_path)
        if mem_lines is not None and len(mem_lines) <= 100:
            checks["memory_lines_le_100"] = True
        mem_content = read_text(memory_path) or ""
        if "## Quick Rules" in mem_content:
            checks["memory_has_quick_rules"] = True
        mem_lc = mem_content.lower()
        if ("people.md" in mem_content) and ("calendar.md" in mem_content):
            checks["memory_has_index_people_calendar"] = True
        # Rules evidence
        if "no monday morning" in mem_lc:
            checks["memory_has_no_monday_morning"] = True
        if ("15min buffer" in mem_lc) or ("15 min buffer" in mem_lc) or (("buffer" in mem_lc) and ("15" in mem_lc)):
            checks["memory_has_15min_buffer"] = True
        if ("prep time: 30min" in mem_lc) or (("prep time" in mem_lc) and (("30min" in mem_lc) or ("30 min" in mem_lc) or ("30" in mem_lc))):
            checks["memory_has_prep_30min"] = True
        if ("investor" in mem_lc) and (("vip" in mem_lc) or ("always accept" in mem_lc) or ("always accepted" in mem_lc)):
            checks["memory_has_investor_vip_always_accept"] = True

    # Calendar rules file checks
    cal_rules_path = os.path.join(output_dir, "secretary", "calendar.md")
    if os.path.isfile(cal_rules_path):
        checks["calendar_rules_exists"] = True
        cal_rules = read_text(cal_rules_path) or ""
        cr_lc = cal_rules.lower()
        # Protected mornings until 10
        if ("mornings" in cr_lc) and ("until 10" in cr_lc or "until 10:00" in cr_lc):
            checks["calendar_rules_protected_mornings_until_10"] = True
        # Friday afternoons no external meetings
        if ("friday" in cr_lc) and ("afternoon" in cr_lc or "afternoons" in cr_lc) and ("no external" in cr_lc):
            checks["calendar_rules_friday_afternoons_no_external"] = True
        # Buffer 15 minutes
        if ("buffer" in cr_lc) and ("15" in cr_lc):
            checks["calendar_rules_buffer_15_minutes"] = True
        # Default length 30 minutes
        if ("default" in cr_lc) and (("30" in cr_lc) or ("30min" in cr_lc) or ("30 min" in cr_lc)):
            checks["calendar_rules_default_length_30"] = True

    # People file checks
    people_path = os.path.join(output_dir, "secretary", "people.md")
    if os.path.isfile(people_path):
        checks["people_exists"] = True
        ppl = read_text(people_path) or ""
        ppl_lc = ppl.lower()
        if "maria chen" in ppl_lc:
            checks["people_has_maria_chen"] = True
        if "david (cto)" in ppl_lc:
            checks["people_has_david_cto"] = True

    # Compute reward: fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure reward is within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()