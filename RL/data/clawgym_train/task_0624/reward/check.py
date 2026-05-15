import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def get_section_ranges(text, markers):
    # markers: ["Step 1", "Step 2", ...]
    # Returns dict { "Step 1": (start_index, end_index), ... }
    # Case-insensitive search, non-overlapping, ordered by appearance
    ranges = {}
    positions = []
    lower = text.lower()
    for m in markers:
        idx = lower.find(m.lower())
        if idx != -1:
            positions.append((idx, m))
    positions.sort(key=lambda x: x[0])
    for i, (start, name) in enumerate(positions):
        end = len(text)
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        ranges[name] = (start, end)
    return ranges

def extract_section(text, start_marker, end_marker, markers_list):
    # Extract content between start_marker and end_marker (case-insensitive)
    ranges = get_section_ranges(text, markers_list)
    if start_marker not in ranges:
        return ""
    start, _ = ranges[start_marker]
    # Start content after the marker line occurrence
    # Move to end of the line containing the marker
    after_start = text[start:]
    nl_idx = after_start.find("\n")
    section_start = start + (nl_idx + 1 if nl_idx != -1 else 0)

    end_pos = len(text)
    if end_marker in ranges:
        end_pos = ranges[end_marker][0]
    return text[section_start:end_pos]

def count_bullets(section_text, bullet_prefix="- "):
    count = 0
    for line in section_text.splitlines():
        if line.lstrip().startswith(bullet_prefix):
            count += 1
    return count

def step4_table_ok(section_text):
    # Requirement:
    # - at least one line with 4 or more '|' characters (header candidate)
    # - and at least 2 additional subsequent lines (after that header line) that also contain '|'
    lines = section_text.splitlines()
    header_index = None
    for i, line in enumerate(lines):
        if line.count("|") >= 4:
            header_index = i
            break
    if header_index is None:
        return False
    subsequent_with_pipes = 0
    for j in range(header_index + 1, len(lines)):
        if "|" in lines[j]:
            subsequent_with_pipes += 1
        if subsequent_with_pipes >= 2:
            return True
    return False

def validate_questions_json(path):
    checks = {
        "q_exists": False,
        "q_valid_json": False,
        "q_has_required_keys": False,
        "q_surface_real_nonempty_distinct": False,
        "q_taxonomy_counts_ok": False,
        "q_root_cause_valid": False,
        "q_answerability_counts_ok": False,
    }

    if not os.path.isfile(path):
        return checks

    checks["q_exists"] = True

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        checks["q_valid_json"] = True
    except Exception:
        return checks

    # Required keys
    required_top = ["surface_question", "real_question", "taxonomy", "answerability"]
    if all(k in data for k in required_top):
        checks["q_has_required_keys"] = True

    # Surface vs real
    try:
        s = str(data.get("surface_question", "")).strip()
        r = str(data.get("real_question", "")).strip()
        if s and r and s.lower() != r.lower():
            checks["q_surface_real_nonempty_distinct"] = True
    except Exception:
        pass

    # Taxonomy counts
    try:
        taxonomy = data.get("taxonomy", {})
        clarifying = taxonomy.get("clarifying", [])
        reframing = taxonomy.get("reframing", [])
        assumption_surfacing = taxonomy.get("assumption_surfacing", [])
        decision_forcing = taxonomy.get("decision_forcing", [])
        if (
            isinstance(clarifying, list) and len([x for x in clarifying if isinstance(x, str) and x.strip()]) >= 3
            and isinstance(reframing, list) and len([x for x in reframing if isinstance(x, str) and x.strip()]) >= 3
            and isinstance(assumption_surfacing, list) and len([x for x in assumption_surfacing if isinstance(x, str) and x.strip()]) >= 2
            and isinstance(decision_forcing, list) and len([x for x in decision_forcing if isinstance(x, str) and x.strip()]) >= 2
        ):
            checks["q_taxonomy_counts_ok"] = True
    except Exception:
        pass

    # Root cause structure
    try:
        taxonomy = data.get("taxonomy", {})
        root_cause = taxonomy.get("root_cause", {})
        problem_statement = root_cause.get("problem_statement", "")
        five_whys = root_cause.get("five_whys", [])
        valid_whys = False
        if isinstance(problem_statement, str) and problem_statement.strip():
            if isinstance(five_whys, list) and len(five_whys) == 5:
                valid_seq = True
                for i, item in enumerate(five_whys, start=1):
                    if not isinstance(item, dict):
                        valid_seq = False
                        break
                    why_val = item.get("why", None)
                    answer = item.get("answer", "")
                    if why_val != i or not isinstance(answer, str) or not answer.strip():
                        valid_seq = False
                        break
                if valid_seq:
                    valid_whys = True
        if valid_whys:
            checks["q_root_cause_valid"] = True
    except Exception:
        pass

    # Answerability counts
    try:
        answerability = data.get("answerability", {})
        anw = answerability.get("answerable_now", [])
        al = answerability.get("answerable_later", [])
        un = answerability.get("unanswerable", [])
        if (
            isinstance(anw, list) and len([x for x in anw if isinstance(x, str) and x.strip()]) >= 1
            and isinstance(al, list) and len([x for x in al if isinstance(x, str) and x.strip()]) >= 1
            and isinstance(un, list) and len([x for x in un if isinstance(x, str) and x.strip()]) >= 1
        ):
            checks["q_answerability_counts_ok"] = True
    except Exception:
        pass

    return checks

def validate_decision_framework(path):
    checks = {
        "d_exists": False,
        "d_contains_steps_1_to_6": False,
        "d_step2_min3_bullets": False,
        "d_step3_min4_bullets": False,
        "d_step4_table_ok": False,
        "d_step5_contains_regret_and_gut": False,
        "d_step6_contains_reversible_and_threshold": False,
    }

    if not os.path.isfile(path):
        return checks

    checks["d_exists"] = True
    content = read_text(path)
    if content is None:
        return checks

    # Steps presence
    steps = [f"Step {i}" for i in range(1, 7)]
    if all(s.lower() in content.lower() for s in steps):
        checks["d_contains_steps_1_to_6"] = True

    # Extract Step 2 and Step 3 sections
    step2_section = extract_section(content, "Step 2", "Step 3", steps)
    if count_bullets(step2_section, "- ") >= 3:
        checks["d_step2_min3_bullets"] = True

    step3_section = extract_section(content, "Step 3", "Step 4", steps)
    if count_bullets(step3_section, "- ") >= 4:
        checks["d_step3_min4_bullets"] = True

    step4_section = extract_section(content, "Step 4", "Step 5", steps)
    if step4_table_ok(step4_section):
        checks["d_step4_table_ok"] = True

    step5_section = extract_section(content, "Step 5", "Step 6", steps).lower()
    if ("regret" in step5_section) and ("gut" in step5_section):
        checks["d_step5_contains_regret_and_gut"] = True

    step6_section = content[ get_section_ranges(content, steps).get("Step 6", (0, 0))[0] : ]
    # Only Step 6 area; but acceptable to scan the extracted Step 6 content similarly to others
    step6_section = extract_section(content, "Step 6", None, steps)
    s6_lower = step6_section.lower()
    has_rev = "reversible" in s6_lower
    has_digit = any(ch.isdigit() for ch in step6_section)
    if has_rev and has_digit:
        checks["d_step6_contains_reversible_and_threshold"] = True

    return checks

def validate_action_plan(path):
    checks = {
        "a_exists": False,
        "a_exactly_5_nonempty_lines": False,
        "a_each_line_has_single_valid_tag": False,
    }

    if not os.path.isfile(path):
        return checks

    checks["a_exists"] = True
    text = read_text(path)
    if text is None:
        return checks

    lines = text.splitlines()
    nonempty = [ln for ln in lines if ln.strip() != ""]
    if len(nonempty) == 5:
        checks["a_exactly_5_nonempty_lines"] = True

    # Tag validation
    allowed_tags = ["[answerable now]", "[answerable later]", "[unanswerable]"]
    ok_tags = True
    if len(nonempty) != 5:
        ok_tags = False
    else:
        for ln in nonempty:
            ll = ln.lower()
            tag_hits = sum(1 for t in allowed_tags if t in ll)
            if tag_hits != 1:
                ok_tags = False
                break
    if ok_tags:
        checks["a_each_line_has_single_valid_tag"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # questions.json checks
        "q_exists": False,
        "q_valid_json": False,
        "q_has_required_keys": False,
        "q_surface_real_nonempty_distinct": False,
        "q_taxonomy_counts_ok": False,
        "q_root_cause_valid": False,
        "q_answerability_counts_ok": False,
        # decision_framework.md checks
        "d_exists": False,
        "d_contains_steps_1_to_6": False,
        "d_step2_min3_bullets": False,
        "d_step3_min4_bullets": False,
        "d_step4_table_ok": False,
        "d_step5_contains_regret_and_gut": False,
        "d_step6_contains_reversible_and_threshold": False,
        # action_plan.txt checks
        "a_exists": False,
        "a_exactly_5_nonempty_lines": False,
        "a_each_line_has_single_valid_tag": False,
    }

    # Paths
    questions_path = os.path.join(output_dir, "questions.json")
    decision_path = os.path.join(output_dir, "decision_framework.md")
    action_path = os.path.join(output_dir, "action_plan.txt")

    # Validate each artifact
    q_checks = validate_questions_json(questions_path)
    for k, v in q_checks.items():
        checks[k] = v

    d_checks = validate_decision_framework(decision_path)
    for k, v in d_checks.items():
        checks[k] = v

    a_checks = validate_action_plan(action_path)
    for k, v in a_checks.items():
        checks[k] = v

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Build result JSON with "reward" as first field
    result = {"reward": reward}
    result.update(checks)

    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()