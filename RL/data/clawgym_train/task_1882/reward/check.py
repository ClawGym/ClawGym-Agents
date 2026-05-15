import json
import os
import sys

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def read_jsonl(path):
    lines = read_lines(path)
    if lines is None:
        return None
    objs = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            return None
        objs.append(obj)
    return objs

def get_input_ids(input_jsonl_path):
    objs = read_jsonl(input_jsonl_path)
    if objs is None:
        return None
    ids = []
    for obj in objs:
        if "id" not in obj:
            return None
        ids.append(obj["id"])
    return ids

def parse_rewrite(rewrite_path):
    lines = read_lines(rewrite_path)
    if lines is None:
        return None
    # Use non-empty lines only to enforce "exactly three lines per section"
    non_empty = [ln for ln in lines if ln.strip() != ""]
    return non_empty

def check_decisions_structure(decisions, allowed_decisions, allowed_triage):
    # Verify keys and types for each object
    for obj in decisions:
        required_keys = [
            "id",
            "decision_class",
            "triage_class",
            "worth_trying",
            "assumptions",
            "defaults_used",
            "recommended_next_action",
            "one_question_if_needed",
            "reasoning_summary",
            "task_state_path",
        ]
        for k in required_keys:
            if k not in obj:
                return False
        if obj["decision_class"] not in allowed_decisions:
            return False
        if obj["triage_class"] not in allowed_triage:
            return False
        if not isinstance(obj["worth_trying"], bool):
            return False
        if not isinstance(obj["assumptions"], list):
            return False
        if not isinstance(obj["defaults_used"], list):
            return False
        if not isinstance(obj["recommended_next_action"], str):
            return False
        oq = obj["one_question_if_needed"]
        if oq is not None and not isinstance(oq, str):
            return False
        if not isinstance(obj["reasoning_summary"], str):
            return False
        if len(obj["reasoning_summary"]) > 300:
            return False
        if not isinstance(obj["task_state_path"], str):
            return False
        if obj["task_state_path"] != "output/.tasks/supervisor-demo.md":
            return False
    return True

def check_decisions_order(decisions, input_ids):
    if len(decisions) != len(input_ids):
        return False
    for i, obj in enumerate(decisions):
        if obj.get("id") != input_ids[i]:
            return False
    return True

def parse_rewrite_sections(non_empty_lines, expected_section_count):
    # Expect exactly 3 non-empty lines per section
    if len(non_empty_lines) != expected_section_count * 3:
        return None
    sections = []
    for i in range(expected_section_count):
        h = non_empty_lines[i * 3 + 0]
        d = non_empty_lines[i * 3 + 1]
        m = non_empty_lines[i * 3 + 2]
        if not h.startswith("## "):
            return None
        if not d.startswith("Decision: "):
            return None
        if not m.startswith("Message: "):
            return None
        sec_id = h[3:].strip()
        decision_val = d.split("Decision:", 1)[1].strip()
        message_val = m.split("Message:", 1)[1].strip()
        sections.append((sec_id, decision_val, message_val))
    return sections

def check_rewrite_matches_decisions(sections, decisions):
    # ids and decisions must match order and value
    if len(sections) != len(decisions):
        return False
    for i, (sec_id, decision_val, _) in enumerate(sections):
        if sec_id != decisions[i].get("id"):
            return False
        if decision_val != decisions[i].get("decision_class"):
            return False
    return True

def check_message_rules(sections, decisions):
    # For AUTO: message must NOT contain '?' and must include one of substrings
    # For CONFIRM or ESCALATE: message must contain at least one '?'
    ok = True
    for i, (_, _, message) in enumerate(sections):
        dc = decisions[i].get("decision_class")
        msg_lower = message.lower()
        if dc == "AUTO":
            if "?" in message:
                ok = False
                break
            required_subs = ["assumption", "assume", "default", "proceed", "continuing"]
            if not any(s in msg_lower for s in required_subs):
                ok = False
                break
        elif dc in {"CONFIRM", "ESCALATE"}:
            if "?" not in message:
                ok = False
                break
        else:
            ok = False
            break
    return ok

def check_task_state_fields(task_state_path, allowed_status):
    lines = read_lines(task_state_path)
    if lines is None:
        return False, False, False
    # Find indices of labeled fields in order
    labels = [
        "Title:",
        "Status:",
        "Started:",
        "Last Updated:",
        "Completed Steps:",
        "Current Blocker:",
        "Next Step:",
    ]
    # We require these labels in this order with "Completed Steps:" followed by >=2 bullet lines immediately
    # Build a map of label -> index
    idx = {}
    cursor = 0
    for lab in labels:
        # Advance to exact lab at beginning of a line
        found = None
        for j in range(cursor, len(lines)):
            if lines[j].startswith(lab):
                found = j
                break
        if found is None:
            return False, False, False
        idx[lab] = found
        cursor = found + 1

    # Verify order strictly increasing
    prev = -1
    for lab in labels:
        if idx[lab] <= prev:
            return False, False, False
        prev = idx[lab]

    # Status value check
    status_line = lines[idx["Status:"]]
    status_val = status_line.split("Status:", 1)[1].strip().lower()
    status_ok = status_val in allowed_status

    # Completed Steps bullets: require at least two bullet lines immediately after "Completed Steps:"
    bullets_ok = False
    cs_index = idx["Completed Steps:"] + 1
    bullet_count = 0
    j = cs_index
    while j < len(lines):
        ln = lines[j]
        if ln.startswith("Current Blocker:"):
            break
        if ln.startswith("- ") or ln.startswith("* "):
            bullet_count += 1
        else:
            # If a non-bullet line appears before "Current Blocker:", structure violates "immediately after" bullets requirement
            return True, False, status_ok
        j += 1
    bullets_ok = bullet_count >= 2

    fields_ok = True
    return fields_ok, bullets_ok, status_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_decisions_file": False,
        "decisions_count_matches_input": False,
        "decisions_preserve_order": False,
        "decisions_valid_structure": False,
        "rewrite_exists": False,
        "rewrite_sections_count_ok": False,
        "rewrite_structure_ok": False,
        "rewrite_matches_decisions": False,
        "rewrite_message_rules": False,
        "task_state_exists": False,
        "task_state_fields_order_ok": False,
        "task_state_bullets_count_ok": False,
        "task_state_status_valid": False,
    }

    decisions_path = os.path.join(output_dir, "decisions.jsonl")
    rewrite_path = os.path.join(output_dir, "rewrite.md")
    task_state_path = os.path.join(output_dir, ".tasks", "supervisor-demo.md")
    input_drafts_path = os.path.join(input_dir, "drafts.jsonl")

    allowed_decisions = {"AUTO", "CONFIRM", "ESCALATE"}
    allowed_triage = {"FINE", "NEEDS_NUDGE", "STUCK", "DONE", "ESCALATE"}
    allowed_status = {"active", "paused", "done", "stuck", "escalate"}

    # Check presence of required output artifacts
    if os.path.isfile(decisions_path):
        checks["has_decisions_file"] = True
    if os.path.isfile(rewrite_path):
        checks["rewrite_exists"] = True
    if os.path.isfile(task_state_path):
        checks["task_state_exists"] = True

    # If any required artifact is missing, baseline 0.0
    required_present = checks["has_decisions_file"] and checks["rewrite_exists"] and checks["task_state_exists"]

    # Proceed with detailed checks only if required artifacts are present
    input_ids = None
    decisions = None
    if required_present:
        input_ids = get_input_ids(input_drafts_path)
        decisions = read_jsonl(decisions_path)

        # Count match
        if input_ids is not None and decisions is not None:
            checks["decisions_count_matches_input"] = len(decisions) == len(input_ids)

        # Preserve order by id
        if input_ids is not None and decisions is not None and checks["decisions_count_matches_input"]:
            checks["decisions_preserve_order"] = check_decisions_order(decisions, input_ids)

        # Structure validity
        if decisions is not None:
            checks["decisions_valid_structure"] = check_decisions_structure(decisions, allowed_decisions, allowed_triage)

        # Rewrite structure
        non_empty_lines = parse_rewrite(rewrite_path) if checks["rewrite_exists"] else None
        sections = None
        if non_empty_lines is not None and input_ids is not None:
            expected_section_count = len(input_ids)
            checks["rewrite_sections_count_ok"] = len(non_empty_lines) == expected_section_count * 3
            sections = parse_rewrite_sections(non_empty_lines, expected_section_count)
            checks["rewrite_structure_ok"] = sections is not None

        # Cross-file consistency
        if sections is not None and decisions is not None and checks["decisions_preserve_order"]:
            checks["rewrite_matches_decisions"] = check_rewrite_matches_decisions(sections, decisions)
            checks["rewrite_message_rules"] = check_message_rules(sections, decisions)

        # Task-state fields
        if checks["task_state_exists"]:
            fields_ok, bullets_ok, status_ok = check_task_state_fields(task_state_path, allowed_status)
            checks["task_state_fields_order_ok"] = fields_ok
            checks["task_state_bullets_count_ok"] = bullets_ok
            checks["task_state_status_valid"] = status_ok

    # Compute reward
    if not required_present:
        reward = 0.0
    else:
        # Average across all checks
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
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