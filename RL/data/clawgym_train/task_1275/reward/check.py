import json
import os
import sys
import re

def read_payload():
    path = os.environ.get("OPENCLAW_REWARD_PAYLOAD")
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def find_line_index_startswith(lines, prefix, start=0, end=None):
    if end is None:
        end = len(lines)
    for i in range(start, min(end, len(lines))):
        if lines[i].startswith(prefix):
            return i
    return -1

def count_lines_startswith(lines, prefix, start=0, end=None):
    if end is None:
        end = len(lines)
    cnt = 0
    for i in range(start, min(end, len(lines))):
        if lines[i].startswith(prefix):
            cnt += 1
    return cnt

def check_iteration_block(block_lines, expected_headings):
    # Returns (order_ok, counts_ok, indices_map, plan_has_1)
    indices = {}
    last_index = -1
    counts_ok = True
    order_ok = True
    for heading in expected_headings:
        count = count_lines_startswith(block_lines, heading, 0, len(block_lines))
        if count != 1:
            counts_ok = False
        idx = find_line_index_startswith(block_lines, heading, 0, len(block_lines))
        indices[heading] = idx
        if idx == -1 or (last_index != -1 and idx <= last_index):
            order_ok = False
        last_index = idx if idx != -1 else last_index
    # Plan step "1." within next 10 lines after "Plan (linear):"
    plan_idx = indices.get("Plan (linear):", -1)
    plan_has_1 = False
    if plan_idx != -1:
        upper = min(plan_idx + 11, len(block_lines))
        for j in range(plan_idx + 1, upper):
            if block_lines[j].lstrip().startswith("1."):
                plan_has_1 = True
                break
    return order_ok, counts_ok, indices, plan_has_1

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    payload = read_payload()
    expected_foundation = payload.get("user_query", "")

    plan_path = os.path.join(output_dir, "plan.md")
    checks = {
        "file_exists": False,
        "file_nonempty": False,
        "foundation_line_present": False,
        "foundation_verbatim_on_line": False,
        "foundation_verbatim_in_file": False,
        "system_domain_line_present": False,
        "assumptions_section_present": False,
        "assumptions_has_bullet": False,
        "domain_lock_active_present": False,
        "iterations_exact_three": False,
        "no_iteration_4_or_more": False,
        "iteration1_labels_order_correct": False,
        "iteration2_labels_order_correct": False,
        "iteration3_labels_order_correct": False,
        "iteration1_plan_has_step1": False,
        "iteration2_plan_has_step1": False,
        "iteration3_plan_has_step1": False,
        "iteration1_dependencies_none": False,
        "no_banned_phrases": False,
    }

    content = ""
    lines = []
    if os.path.isfile(plan_path):
        checks["file_exists"] = True
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.splitlines()
            if len(content.strip()) > 0:
                checks["file_nonempty"] = True
        except Exception:
            # leave other checks as False
            pass

    if checks["file_exists"] and checks["file_nonempty"]:
        # Foundation line
        foundation_idx = find_line_index_startswith(lines, "FOUNDATION:")
        if foundation_idx != -1:
            checks["foundation_line_present"] = True
            # verbatim check on the same line
            if expected_foundation and expected_foundation in lines[foundation_idx]:
                checks["foundation_verbatim_on_line"] = True
        # verbatim present anywhere
        if expected_foundation and expected_foundation in content:
            checks["foundation_verbatim_in_file"] = True

        # System domain
        sysdom_idx = find_line_index_startswith(lines, "SYSTEM DOMAIN:")
        if sysdom_idx != -1:
            # Non-empty after colon
            after = lines[sysdom_idx][len("SYSTEM DOMAIN:"):].strip()
            if len(after) >= 1:
                checks["system_domain_line_present"] = True

        # Assumptions section
        assumptions_idx = find_line_index_startswith(lines, "ASSUMPTIONS:")
        if assumptions_idx != -1:
            checks["assumptions_section_present"] = True
            # Look for at least one bullet "- " within the next 50 lines
            bullet_found = False
            upper = min(assumptions_idx + 51, len(lines))
            for i in range(assumptions_idx + 1, upper):
                if lines[i].startswith("- "):
                    bullet_found = True
                    break
            if bullet_found:
                checks["assumptions_has_bullet"] = True

        # Domain lock
        for ln in lines:
            if ln.strip() == "DOMAIN LOCK: ACTIVE":
                checks["domain_lock_active_present"] = True
                break

        # Iterations detection
        iter1_positions = [i for i, ln in enumerate(lines) if ln.strip() == "Iteration 1"]
        iter2_positions = [i for i, ln in enumerate(lines) if ln.strip() == "Iteration 2"]
        iter3_positions = [i for i, ln in enumerate(lines) if ln.strip() == "Iteration 3"]
        # check no Iteration 4 or higher
        no_iter_4_plus = True
        iter_4_plus_pattern = re.compile(r"^Iteration\s+([0-9]+)\s*$")
        for ln in lines:
            m = iter_4_plus_pattern.match(ln.strip())
            if m:
                try:
                    num = int(m.group(1))
                    if num >= 4:
                        no_iter_4_plus = False
                        break
                except Exception:
                    pass
        checks["no_iteration_4_or_more"] = no_iter_4_plus

        if len(iter1_positions) == 1 and len(iter2_positions) == 1 and len(iter3_positions) == 1 and checks["no_iteration_4_or_more"]:
            # Ensure order in file
            i1 = iter1_positions[0]
            i2 = iter2_positions[0]
            i3 = iter3_positions[0]
            if i1 < i2 < i3:
                checks["iterations_exact_three"] = True

                # Split blocks
                block1 = lines[i1 + 1:i2]
                block2 = lines[i2 + 1:i3]
                block3 = lines[i3 + 1:len(lines)]

                expected_headings = [
                    "Feature:",
                    "Inclusions:",
                    "Exclusions:",
                    "Plan (linear):",
                    "Required Inputs:",
                    "Produced Outputs:",
                    "Dependencies:",
                    "Success Condition:",
                ]

                # Iteration 1
                order_ok1, counts_ok1, indices1, plan_has_1_it1 = check_iteration_block(block1, expected_headings)
                checks["iteration1_labels_order_correct"] = bool(order_ok1 and counts_ok1)
                checks["iteration1_plan_has_step1"] = plan_has_1_it1

                # Dependencies none for iteration 1
                dep_idx1 = find_line_index_startswith(block1, "Dependencies:")
                dep_none = False
                if dep_idx1 != -1:
                    dep_line = block1[dep_idx1]
                    if "none" in dep_line.lower():
                        dep_none = True
                    else:
                        # check next non-empty line for 'none'
                        for j in range(dep_idx1 + 1, min(dep_idx1 + 3, len(block1))):
                            if block1[j].strip() and ("none" in block1[j].lower()):
                                dep_none = True
                                break
                checks["iteration1_dependencies_none"] = dep_none

                # Iteration 2
                order_ok2, counts_ok2, indices2, plan_has_1_it2 = check_iteration_block(block2, expected_headings)
                checks["iteration2_labels_order_correct"] = bool(order_ok2 and counts_ok2)
                checks["iteration2_plan_has_step1"] = plan_has_1_it2

                # Iteration 3
                order_ok3, counts_ok3, indices3, plan_has_1_it3 = check_iteration_block(block3, expected_headings)
                checks["iteration3_labels_order_correct"] = bool(order_ok3 and counts_ok3)
                checks["iteration3_plan_has_step1"] = plan_has_1_it3

        # Banned phrases absence (case-insensitive)
        banned = [
            "summary",
            "summaries",
            "meta commentary",
            "vision",
            "stop autonomous-feature-planner",
            "stop planning",
        ]
        lower_content = content.lower()
        has_banned = any(b in lower_content for b in banned)
        checks["no_banned_phrases"] = not has_banned

    # Compute reward
    # If no file or empty, reward must be 0.0
    if not (checks["file_exists"] and checks["file_nonempty"]):
        reward = 0.0
    else:
        total_points = len(checks)
        passed_points = sum(1 for v in checks.values() if v)
        reward = passed_points / float(total_points) if total_points > 0 else 0.0

    # Output JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()