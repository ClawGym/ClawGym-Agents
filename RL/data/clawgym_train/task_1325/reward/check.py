import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def normalize_heading_prefix(s):
    # Remove leading markdown heading markers and whitespace
    return s.lstrip().lstrip("#").lstrip()

def has_line_starting_with(text, label):
    if text is None:
        return False
    for line in text.splitlines():
        if normalize_heading_prefix(line).startswith(label):
            return True
    return False

def find_states_in_order(transitions, final_state):
    # Ensure there exists a subsequence Inbox -> Assigned -> In Progress -> Review -> final_state in order
    required = ["Inbox", "Assigned", "In Progress", "Review", final_state]
    idx = -1
    for state in required:
        found = False
        for i in range(idx + 1, len(transitions)):
            t = transitions[i]
            if isinstance(t, dict) and t.get("state") == state:
                idx = i
                found = True
                break
        if not found:
            return False
    return True

def get_transitions(board_path):
    try:
        with open(board_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        transitions = data.get("transitions")
        if not isinstance(transitions, list) or len(transitions) == 0:
            return False, []
        return True, transitions
    except Exception:
        return False, []

def check_handoff_labels(comment_text):
    if not isinstance(comment_text, str) or not comment_text:
        return False
    text = comment_text.lower()
    required_labels = [
        "what was done",
        "where artifacts are",
        "how to verify",
        "known issues",
        "what's next",
    ]
    return all(lbl in text for lbl in required_labels)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    spec_path = os.path.join(output_dir, "specs", "ONB-101-spec.md")
    artifact_path = os.path.join(output_dir, "artifacts", "ONB-101", "ONBOARDING.md")
    review_path = os.path.join(output_dir, "reviews", "ONB-101-review.md")
    decision_path = os.path.join(output_dir, "decisions", "ONB-101-decision.md")
    board_path = os.path.join(output_dir, "board.json")

    checks = {
        # Existence checks
        "exist_spec": False,
        "exist_artifact": False,
        "exist_review": False,
        "exist_decision": False,
        "exist_board": False,

        # Spec validations
        "spec_task_id": False,
        "spec_output_path": False,

        # Board validations
        "board_valid_json": False,
        "board_states_order": False,
        "board_review_handoff_5": False,
        "board_done_by_orchestrator": False,
        "board_no_done_by_builder": False,

        # Review validations
        "review_contains_approval_or_feedback": False,
        "review_refers_artifact_path": False,
        "review_contains_reviewer_term": False,

        # Decision log validations
        "decision_field_decision": False,
        "decision_field_date": False,
        "decision_field_author": False,
        "decision_field_status": False,
        "decision_task_onb101": False,
        "decision_section_context": False,
        "decision_section_options_considered": False,
        "decision_section_decision": False,
        "decision_section_consequences": False,

        # Artifact validations
        "artifact_has_how_to_verify": False,
    }

    # Existence
    if os.path.isfile(spec_path):
        checks["exist_spec"] = True
    if os.path.isfile(artifact_path):
        checks["exist_artifact"] = True
    if os.path.isfile(review_path):
        checks["exist_review"] = True
    if os.path.isfile(decision_path):
        checks["exist_decision"] = True
    if os.path.isfile(board_path):
        checks["exist_board"] = True

    # Spec validation
    spec_text = read_text(spec_path) if checks["exist_spec"] else None
    if spec_text:
        if "Task ID: ONB-101" in spec_text:
            checks["spec_task_id"] = True

        # Find a line starting with "Output Path:" that includes the expected path
        op_ok = False
        for line in spec_text.splitlines():
            norm = normalize_heading_prefix(line)
            if norm.startswith("Output Path:") and "output/artifacts/ONB-101" in norm:
                op_ok = True
                break
        checks["spec_output_path"] = op_ok

    # Board validations
    transitions_valid, transitions = get_transitions(board_path) if checks["exist_board"] else (False, [])
    checks["board_valid_json"] = transitions_valid

    if transitions_valid:
        # Determine if Done exists, else allow Failed
        states = [t.get("state") for t in transitions if isinstance(t, dict)]
        has_done = "Done" in states
        has_failed = "Failed" in states

        if has_done:
            checks["board_states_order"] = find_states_in_order(transitions, "Done")
        elif has_failed:
            checks["board_states_order"] = find_states_in_order(transitions, "Failed")
        else:
            checks["board_states_order"] = False

        # Review handoff by Builder with 5 labels
        review_handoff_ok = False
        for t in transitions:
            if not isinstance(t, dict):
                continue
            if t.get("state") == "Review" and t.get("by_role") == "Builder":
                if check_handoff_labels(t.get("comment", "")):
                    review_handoff_ok = True
                    break
        checks["board_review_handoff_5"] = review_handoff_ok

        # Final Done by Orchestrator (if Done present)
        done_by_orchestrator = False
        if has_done:
            last_done_idx = max(i for i, t in enumerate(transitions) if isinstance(t, dict) and t.get("state") == "Done")
            t_done = transitions[last_done_idx] if last_done_idx is not None else None
            if isinstance(t_done, dict) and t_done.get("by_role") == "Orchestrator":
                done_by_orchestrator = True
        else:
            # If no Done, this check remains False by design
            done_by_orchestrator = False
        checks["board_done_by_orchestrator"] = done_by_orchestrator

        # No Done by Builder
        no_done_by_builder = True
        for t in transitions:
            if isinstance(t, dict) and t.get("state") == "Done" and t.get("by_role") == "Builder":
                no_done_by_builder = False
                break
        checks["board_no_done_by_builder"] = no_done_by_builder

    # Review validations
    review_text = read_text(review_path) if checks["exist_review"] else None
    if review_text:
        rt_lower = review_text.lower()
        if ("approved" in rt_lower) or ("feedback" in rt_lower):
            checks["review_contains_approval_or_feedback"] = True
        if "output/artifacts/ONB-101" in review_text:
            checks["review_refers_artifact_path"] = True
        if "reviewer" in rt_lower:
            checks["review_contains_reviewer_term"] = True

    # Decision log validations
    decision_text = read_text(decision_path) if checks["exist_decision"] else None
    if decision_text:
        # Header fields as lines starting with labels (allow heading markers)
        checks["decision_field_decision"] = has_line_starting_with(decision_text, "Decision:")
        checks["decision_field_date"] = has_line_starting_with(decision_text, "Date:")
        checks["decision_field_author"] = has_line_starting_with(decision_text, "Author:")
        checks["decision_field_status"] = has_line_starting_with(decision_text, "Status:")
        if "Task: ONB-101" in decision_text:
            checks["decision_task_onb101"] = True

        # Sections present (case-insensitive substring checks)
        dt_lower = decision_text.lower()
        if re.search(r"(^|\n)\s*#*\s*context\b", decision_text, re.IGNORECASE):
            checks["decision_section_context"] = True
        if re.search(r"(^|\n)\s*#*\s*options considered\b", decision_text, re.IGNORECASE):
            checks["decision_section_options_considered"] = True
        if re.search(r"(^|\n)\s*#*\s*decision\b", decision_text, re.IGNORECASE):
            checks["decision_section_decision"] = True
        if re.search(r"(^|\n)\s*#*\s*consequences\b", decision_text, re.IGNORECASE):
            checks["decision_section_consequences"] = True

    # Artifact validation
    artifact_text = read_text(artifact_path) if checks["exist_artifact"] else None
    if artifact_text and ("how to verify" in artifact_text.lower()):
        checks["artifact_has_how_to_verify"] = True

    # Compute reward: average of all checks; if output is empty, this yields 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()