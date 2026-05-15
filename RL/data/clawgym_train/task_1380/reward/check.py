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

def read_lines(path):
    txt = read_text(path)
    if txt is None:
        return None
    # Normalize line endings
    return txt.splitlines()

def is_nonempty_file(path):
    try:
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return len(content.strip()) > 0
    except Exception:
        return False

def get_project_title_from_request(request_path):
    lines = read_lines(request_path)
    if not lines:
        return None
    # Prefer first markdown heading line
    for line in lines:
        if line.strip().startswith("#"):
            # remove leading #'s and spaces
            title = line.lstrip("#").strip()
            if title:
                return title
    # fallback: first non-empty line
    for line in lines:
        if line.strip():
            return line.strip()
    return None

def parse_constraints(constraints_path):
    # Expect JSON with fields like budget_tier, max_concurrent, retry_limit (case-insensitive tolerant)
    default = {"budget_tier": None, "max_concurrent": None, "retry_limit": None}
    try:
        with open(constraints_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # case-insensitive key access
        lower_map = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
        # attempt various key variants
        budget = lower_map.get("budget_tier")
        if budget is None:
            # fallback: maybe "budget"
            budget = lower_map.get("budget") or lower_map.get("tier")
        max_conc = lower_map.get("max_concurrent")
        if max_conc is None:
            max_conc = lower_map.get("max_concurrency") or lower_map.get("max_concurrent_agents") or lower_map.get("max_agents")
        retry = lower_map.get("retry_limit")
        if retry is None:
            retry = lower_map.get("retries") or lower_map.get("max_retries")
        # normalize types/strings
        if isinstance(budget, str):
            budget_str = budget.strip().lower()
        elif budget is not None:
            budget_str = str(budget).strip().lower()
        else:
            budget_str = None
        def to_int(v):
            try:
                return int(v)
            except Exception:
                try:
                    return int(str(v).strip())
                except Exception:
                    return None
        max_conc_int = to_int(max_conc) if max_conc is not None else None
        retry_int = to_int(retry) if retry is not None else None
        return {"budget_tier": budget_str, "max_concurrent": max_conc_int, "retry_limit": retry_int}
    except Exception:
        return default

def find_section_indices_by_headings(lines, ordered_headings):
    # Return dict of heading -> index if found in order
    indices = {}
    last_idx = -1
    for heading in ordered_headings:
        found = None
        for i in range(last_idx + 1, len(lines)):
            line = lines[i].strip()
            # consider markdown headings like "# Scope", "## Scope", or plain "Scope" or "Scope:"
            stripped = line.lstrip("#").strip()
            stripped = stripped[:-1].strip() if stripped.endswith(":") else stripped
            if stripped.lower() == heading.lower():
                found = i
                break
        if found is None:
            return None
        indices[heading] = found
        last_idx = found
    return indices

def get_section_text(lines, start_idx, next_idx):
    # Extract text between start_idx+1 and next_idx (exclusive)
    a = start_idx + 1
    b = next_idx if next_idx is not None else len(lines)
    if a < 0 or a >= len(lines):
        return ""
    b = max(a, min(b, len(lines)))
    return "\n".join(lines[a:b])

def file_contains_exact_line(lines, exact):
    for line in lines:
        if line.strip() == exact:
            return True
    return False

def line_starts_with_exact(lines, exact):
    if not lines:
        return False
    first = lines[0].strip()
    return first == exact

def check_tasks_array_in_state(state, expected_outputs):
    if not isinstance(state, dict):
        return False
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return False
    if len(tasks) != 3:
        return False
    # Collect outputs and statuses
    outputs = set()
    for t in tasks:
        if not isinstance(t, dict):
            return False
        status = t.get("status")
        outp = t.get("output")
        if status != "completed":
            return False
        if not isinstance(outp, str):
            return False
        outputs.add(outp)
    return outputs == set(expected_outputs)

def check_state_outputs_exist_nonempty(workspace_root, outputs):
    for p in outputs:
        abs_p = os.path.join(workspace_root, p.lstrip("/"))
        if not is_nonempty_file(abs_p):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    ow = os.path.join(output_dir, "workspace", "orch-001")
    req_path = os.path.join(ow, "requirements.md")
    plan_path = os.path.join(ow, "final-plan.md")
    task1_path = os.path.join(ow, "tasks", "task-1", "output.md")
    task2_path = os.path.join(ow, "tasks", "task-2", "output.md")
    task3_path = os.path.join(ow, "tasks", "task-3", "output.md")
    ver_dir = os.path.join(ow, "verification")
    ver_comp_path = os.path.join(ver_dir, "completeness-report.md")
    ver_acc_path = os.path.join(ver_dir, "accuracy-report.md")
    ver_hall_path = os.path.join(ver_dir, "hallucination-report.md")
    ver_int_path = os.path.join(ver_dir, "integration-report.md")
    ver_final_path = os.path.join(ver_dir, "final-verdict.md")
    state_path = os.path.join(ow, "orche-state.json")

    # Reference inputs
    request_md_path = os.path.join(input_dir, "request.md")
    constraints_json_path = os.path.join(input_dir, "constraints.json")

    project_title = get_project_title_from_request(request_md_path) or ""
    constraints = parse_constraints(constraints_json_path)

    checks = {
        "req_exists": False,
        "req_has_sections_order": False,
        "req_has_approval_line": False,
        "req_scope_title_match": False,
        "req_constraints_reflect": False,

        "plan_exists": False,
        "plan_has_tasks_T1_T2_T3": False,
        "plan_has_exact_dependency_line": False,
        "plan_has_cost_substrings": False,
        "plan_has_rollback_section_and_bullets_T1_T2_T3": False,

        "task1_exists_and_content": False,
        "task2_exists_and_content": False,
        "task3_exists_and_content": False,

        "ver_completeness_exists": False,
        "ver_accuracy_exists": False,
        "ver_hallucination_14_pass": False,
        "ver_integration_exists": False,
        "ver_final_verdict_pass_zero_regressions": False,

        "state_exists_and_fields": False,
        "state_tasks_outputs_match": False
    }

    # Requirements checks
    if is_nonempty_file(req_path):
        checks["req_exists"] = True
        req_lines = read_lines(req_path) or []
        # Sections order
        section_order = ["Scope", "Constraints", "Deliverables", "Feasibility"]
        sec_indices = find_section_indices_by_headings(req_lines, section_order)
        if sec_indices is not None:
            checks["req_has_sections_order"] = True
            # Approval line exactly last non-empty line
            last_non_empty = ""
            for line in reversed(req_lines):
                if line.strip():
                    last_non_empty = line.strip()
                    break
            if last_non_empty == "User approval: APPROVED":
                checks["req_has_approval_line"] = True
            # Scope title presence
            scope_text = get_section_text(req_lines, sec_indices["Scope"], sec_indices["Constraints"])
            if project_title and (project_title in scope_text):
                checks["req_scope_title_match"] = True
            # Constraints reflect constraints.json
            constraints_text = get_section_text(req_lines, sec_indices["Constraints"], sec_indices["Deliverables"])
            expected_budget = constraints.get("budget_tier")
            expected_max = constraints.get("max_concurrent")
            expected_retry = constraints.get("retry_limit")
            # Build expected substrings, require all if they are known
            ok_constraints = True
            if expected_budget is not None:
                if f"budget tier: {expected_budget}" not in constraints_text.lower():
                    ok_constraints = False
            if expected_max is not None:
                # Look for exact "max concurrent: <n>"
                if f"max concurrent: {expected_max}" not in constraints_text.lower():
                    ok_constraints = False
            if expected_retry is not None:
                if f"retry limit: {expected_retry}" not in constraints_text.lower():
                    ok_constraints = False
            # If constraints.json did not yield values, do not pass
            if expected_budget is None or expected_max is None or expected_retry is None:
                ok_constraints = False
            if ok_constraints:
                checks["req_constraints_reflect"] = True

    # Plan checks
    if is_nonempty_file(plan_path):
        checks["plan_exists"] = True
        plan_lines = read_lines(plan_path) or []
        plan_text = "\n".join(plan_lines)
        # Task list for T1, T2, T3 exactly
        has_t1 = "T1" in plan_text
        has_t2 = "T2" in plan_text
        has_t3 = "T3" in plan_text
        # Ensure no T4..T9 to assert exactly 3 tasks named T1..T3 (best effort)
        no_extra = not re.search(r"\bT[4-9]\b", plan_text)
        if has_t1 and has_t2 and has_t3 and no_extra:
            checks["plan_has_tasks_T1_T2_T3"] = True
        # Exact dependency line
        if file_contains_exact_line(plan_lines, "Dependencies: T3 depends on T1 and T2"):
            checks["plan_has_exact_dependency_line"] = True
        # Cost/safety substrings reflecting constraints.json values
        expected_budget = constraints.get("budget_tier")
        expected_max = constraints.get("max_concurrent")
        expected_retry = constraints.get("retry_limit")
        cost_ok = True
        if expected_budget is None or expected_max is None or expected_retry is None:
            cost_ok = False
        else:
            low = plan_text.lower()
            if f"budget tier: {expected_budget}" not in low:
                cost_ok = False
            if f"max concurrent: {expected_max}" not in low:
                cost_ok = False
            if f"retry limit: {expected_retry}" not in low:
                cost_ok = False
        if cost_ok:
            checks["plan_has_cost_substrings"] = True
        # Rollback strategies section with bullets for each task
        has_section = "rollback strategies" in plan_text.lower()
        # Find bullet lines mentioning T1, T2, T3
        bullets = [ln for ln in plan_lines if ln.strip().startswith(("-","*"))]
        mentions = {
            "T1": any("T1" in b for b in bullets),
            "T2": any("T2" in b for b in bullets),
            "T3": any("T3" in b for b in bullets),
        }
        if has_section and all(mentions.values()):
            checks["plan_has_rollback_section_and_bullets_T1_T2_T3"] = True

    # Task 1 checks
    if is_nonempty_file(task1_path):
        lines1 = read_lines(task1_path) or []
        ok = line_starts_with_exact(lines1, "Task-1 Completed")
        if ok and project_title and any(project_title in ln for ln in lines1):
            checks["task1_exists_and_content"] = True

    # Task 2 checks
    if is_nonempty_file(task2_path):
        lines2 = read_lines(task2_path) or []
        ok2 = line_starts_with_exact(lines2, "Task-2 Completed")
        text2 = "\n".join(lines2)
        if ok2 and ("max concurrent agents: 3" in text2) and ("budget tier: caution" in text2.lower()):
            checks["task2_exists_and_content"] = True

    # Task 3 checks
    if is_nonempty_file(task3_path):
        lines3 = read_lines(task3_path) or []
        ok3 = line_starts_with_exact(lines3, "Task-3 Completed")
        text3 = "\n".join(lines3)
        if ok3 and ("Integration summary" in text3) and ("Consolidated" in text3):
            checks["task3_exists_and_content"] = True

    # Verification files
    if is_nonempty_file(ver_comp_path):
        checks["ver_completeness_exists"] = True
    if is_nonempty_file(ver_acc_path):
        checks["ver_accuracy_exists"] = True
    if is_nonempty_file(ver_int_path):
        checks["ver_integration_exists"] = True
    # Hallucination report exact 14 lines "H-1 PASS" .. "H-14 PASS"
    if os.path.isfile(ver_hall_path):
        hall_lines = read_lines(ver_hall_path) or []
        expected = [f"H-{i} PASS" for i in range(1, 15)]
        if hall_lines == expected:
            checks["ver_hallucination_14_pass"] = True
    # Final verdict
    if os.path.isfile(ver_final_path):
        vlines = read_lines(ver_final_path) or []
        vtext = "\n".join(vlines)
        has_pass = "PASS" in vtext
        has_reg_line = any(ln.strip() == "regressions: 0" for ln in vlines)
        if has_pass and has_reg_line and is_nonempty_file(ver_final_path):
            checks["ver_final_verdict_pass_zero_regressions"] = True

    # State file
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            fields_ok = (
                isinstance(state, dict)
                and state.get("taskId") == "orch-001"
                and state.get("phase") == 3
                and state.get("status") == "completed"
                and state.get("retryCount") == 0
                and state.get("maxRetries") == 3
            )
            if fields_ok:
                checks["state_exists_and_fields"] = True
            # Check tasks array and outputs
            # Expected output paths as relative from workspace root (no leading slash)
            expected_outputs_rel = [
                os.path.join("output", "workspace", "orch-001", "tasks", "task-1", "output.md"),
                os.path.join("output", "workspace", "orch-001", "tasks", "task-2", "output.md"),
                os.path.join("output", "workspace", "orch-001", "tasks", "task-3", "output.md"),
            ]
            if check_tasks_array_in_state(state, expected_outputs_rel):
                # Confirm those files exist and are non-empty
                if check_state_outputs_exist_nonempty(workspace_root, expected_outputs_rel):
                    checks["state_tasks_outputs_match"] = True
        except Exception:
            pass

    # Reward calculation
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        # If no output artifacts at all, ensure 0.0
        # Basic gating: require at least one core artifact such as requirements or plan or any task to give partial credit
        any_output_artifact = any([
            checks["req_exists"],
            checks["plan_exists"],
            checks["task1_exists_and_content"],
            checks["task2_exists_and_content"],
            checks["task3_exists_and_content"],
            checks["ver_completeness_exists"],
            checks["ver_accuracy_exists"],
            checks["ver_hallucination_14_pass"],
            checks["ver_integration_exists"],
            checks["ver_final_verdict_pass_zero_regressions"],
            checks["state_exists_and_fields"],
            checks["state_tasks_outputs_match"]
        ])
        if any_output_artifact:
            reward = round(passed / total_checks, 6)
        else:
            reward = 0.0

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()