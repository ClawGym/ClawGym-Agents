import json
import os
import re
import sys
from datetime import datetime

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_nonempty_text_file(path):
    try:
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return len(content.strip()) > 0
    except Exception:
        return False

def is_hex_sha(s):
    if not isinstance(s, str):
        return False
    if not (7 <= len(s) <= 40):
        return False
    return re.fullmatch(r"[0-9a-fA-F]+", s) is not None

def is_iso8601_like(s):
    if not isinstance(s, str):
        return False
    if "T" not in s:
        return False
    # Basic regex check: YYYY-MM-DDTHH:MM:SS with optional fractional and timezone
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s):
        return False
    # Try parsing with fromisoformat, handling 'Z'
    try:
        ss = s
        if ss.endswith("Z"):
            ss = ss[:-1] + "+00:00"
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "extracted_tasks_json_exists": False,
        "extracted_tasks_valid": False,
        "extracted_tasks_count_ge_2": False,
        "per_task_artifacts_present": False,
        "per_task_implementer_reports_nonempty": False,
        "per_task_spec_json_valid": False,
        "per_task_cq_json_valid": False,
        "per_task_spec_method_code_inspection": False,
        "per_task_sha_valid": False,
        "per_task_statuses_pass": False,
        "execution_trace_exists": False,
        "execution_trace_valid": False,
        "execution_steps_monotonic": False,
        "per_task_event_order_ok": False,
        "clarification_qna_enforced": False,
        "implementer_subagent_ids_unique": False,
        "no_parallelization_enforced": False,
        "review_gating_enforced": False,
        "todo_exists": False,
        "todo_valid": False,
        "todo_all_true": False,
        "branch_file_valid": False,
        "final_review_contains_phrase": False,
    }

    # 1) Task extraction checks
    extracted_path = os.path.join(output_dir, "extracted_tasks.json")
    tasks = []
    if os.path.isfile(extracted_path):
        checks["extracted_tasks_json_exists"] = True
        ok, data = load_json(extracted_path)
        if ok and isinstance(data, list):
            valid_structure = True
            for el in data:
                if not isinstance(el, dict):
                    valid_structure = False
                    break
                for key in ("id", "title", "full_text", "context"):
                    if key not in el or not isinstance(el[key], str) or not el[key].strip():
                        valid_structure = False
                        break
                if not valid_structure:
                    break
            if valid_structure:
                checks["extracted_tasks_valid"] = True
                tasks = [el["id"] for el in data]
                if len(data) >= 2:
                    checks["extracted_tasks_count_ge_2"] = True

    # 2) Per-task artifacts
    per_task_present = True
    reports_nonempty = True
    spec_valid_all = True
    cq_valid_all = True
    method_ci_all = True
    shas_valid_all = True
    statuses_pass_all = True

    if checks["extracted_tasks_valid"]:
        for tid in tasks:
            task_dir = os.path.join(output_dir, "tasks", tid)
            impl_path = os.path.join(task_dir, "implementer_report.md")
            spec_path = os.path.join(task_dir, "spec_review.json")
            cq_path = os.path.join(task_dir, "code_quality_review.json")

            # Presence
            if not (os.path.isdir(task_dir) and os.path.isfile(impl_path) and os.path.isfile(spec_path) and os.path.isfile(cq_path)):
                per_task_present = False

            # Implementer report non-empty
            if not is_nonempty_text_file(impl_path):
                reports_nonempty = False

            # spec_review.json
            ok_s, spec = load_json(spec_path)
            if not (ok_s and isinstance(spec, dict)):
                spec_valid_all = False
            else:
                # Required keys
                if not all(k in spec for k in ("status", "issues", "method", "base_sha", "head_sha")):
                    spec_valid_all = False
                else:
                    if spec.get("method") != "code-inspection":
                        method_ci_all = False
                    # issues array
                    if not isinstance(spec.get("issues"), list):
                        spec_valid_all = False
                    # statuses pass
                    if spec.get("status") != "pass":
                        statuses_pass_all = False
                    # SHAs
                    if not (is_hex_sha(spec.get("base_sha")) and is_hex_sha(spec.get("head_sha"))):
                        shas_valid_all = False

            # code_quality_review.json
            ok_c, cq = load_json(cq_path)
            if not (ok_c and isinstance(cq, dict)):
                cq_valid_all = False
            else:
                if not all(k in cq for k in ("status", "strengths", "issues", "base_sha", "head_sha")):
                    cq_valid_all = False
                else:
                    if not isinstance(cq.get("strengths"), list):
                        cq_valid_all = False
                    if not isinstance(cq.get("issues"), list):
                        cq_valid_all = False
                    # statuses pass
                    if cq.get("status") != "pass":
                        statuses_pass_all = False
                    # SHAs
                    if not (is_hex_sha(cq.get("base_sha")) and is_hex_sha(cq.get("head_sha"))):
                        shas_valid_all = False

        checks["per_task_artifacts_present"] = per_task_present and len(tasks) > 0
        checks["per_task_implementer_reports_nonempty"] = reports_nonempty and len(tasks) > 0
        checks["per_task_spec_json_valid"] = spec_valid_all and len(tasks) > 0
        checks["per_task_cq_json_valid"] = cq_valid_all and len(tasks) > 0
        checks["per_task_spec_method_code_inspection"] = method_ci_all and len(tasks) > 0
        checks["per_task_sha_valid"] = shas_valid_all and len(tasks) > 0
        checks["per_task_statuses_pass"] = statuses_pass_all and len(tasks) > 0

    # 3) Execution trace checks
    exec_path = os.path.join(output_dir, "execution_trace.json")
    events = []
    if os.path.isfile(exec_path):
        checks["execution_trace_exists"] = True
        ok_e, edata = load_json(exec_path)
        if ok_e and isinstance(edata, dict) and isinstance(edata.get("events"), list):
            events = edata["events"]
            # Validate event structure
            allowed_types = {
                "clarifications_asked",
                "clarifications_answered",
                "implementer_start",
                "implementer_finish",
                "spec_review_start",
                "spec_review_finish",
                "code_quality_review_start",
                "code_quality_review_finish",
            }
            structure_ok = True
            for ev in events:
                if not isinstance(ev, dict):
                    structure_ok = False
                    break
                if not isinstance(ev.get("step"), int):
                    structure_ok = False
                    break
                if not isinstance(ev.get("task_id"), str):
                    structure_ok = False
                    break
                if not isinstance(ev.get("event_type"), str) or ev.get("event_type") not in allowed_types:
                    structure_ok = False
                    break
                if not isinstance(ev.get("subagent_id"), str):
                    structure_ok = False
                    break
                if not is_iso8601_like(ev.get("timestamp")):
                    structure_ok = False
                    break
            if structure_ok:
                checks["execution_trace_valid"] = True

            # Steps monotonic: steps strictly increasing by 1 starting at 1 in array order
            if checks["execution_trace_valid"] and len(events) > 0:
                monotonic = True
                for idx, ev in enumerate(events, start=1):
                    if ev.get("step") != idx:
                        monotonic = False
                        break
                checks["execution_steps_monotonic"] = monotonic

            # Per-task event order
            per_task_order_ok = True
            review_gating_ok = True
            if checks["execution_trace_valid"]:
                # Build index lookup by (task_id, event_type) -> first index
                idx_by_task_type = {}
                for i, ev in enumerate(events):
                    key = (ev["task_id"], ev["event_type"])
                    if key not in idx_by_task_type:
                        idx_by_task_type[key] = i
                # Check required order for each task in tasks (if we have tasks)
                task_ids_to_check = tasks if tasks else list({ev["task_id"] for ev in events})
                for tid in task_ids_to_check:
                    required_seq = [
                        "implementer_start",
                        "implementer_finish",
                        "spec_review_start",
                        "spec_review_finish",
                        "code_quality_review_start",
                        "code_quality_review_finish",
                    ]
                    indices = []
                    missing = False
                    for et in required_seq:
                        if (tid, et) in idx_by_task_type:
                            indices.append(idx_by_task_type[(tid, et)])
                        else:
                            missing = True
                            break
                    if missing:
                        per_task_order_ok = False
                        review_gating_ok = False
                        continue
                    # Order ascending
                    if not all(indices[i] < indices[i+1] for i in range(len(indices)-1)):
                        per_task_order_ok = False
                    # Review gating: spec_review_finish before code_quality_review_start
                    if not (indices[3] < indices[4]):
                        review_gating_ok = False
            checks["per_task_event_order_ok"] = per_task_order_ok and checks["execution_trace_valid"]
            checks["review_gating_enforced"] = review_gating_ok and checks["execution_trace_valid"]

            # Clarifications Q&A enforced for at least one task
            clarification_ok = False
            if checks["execution_trace_valid"]:
                # For each task, ensure asked < answered < implementer_start
                by_task_idxs = {}
                for i, ev in enumerate(events):
                    tid = ev["task_id"]
                    by_task_idxs.setdefault(tid, {}).setdefault(ev["event_type"], []).append(i)
                for tid, mapping in by_task_idxs.items():
                    asked_idxs = mapping.get("clarifications_asked", [])
                    answered_idxs = mapping.get("clarifications_answered", [])
                    impl_start_idxs = mapping.get("implementer_start", [])
                    if asked_idxs and answered_idxs and impl_start_idxs:
                        if min(asked_idxs) < min(answered_idxs) < min(impl_start_idxs):
                            clarification_ok = True
                            break
            checks["clarification_qna_enforced"] = clarification_ok and checks["execution_trace_valid"]

            # Subagent uniqueness for implementer_start across different tasks
            subagent_unique = False
            if checks["execution_trace_valid"]:
                task_to_subagent = {}
                for ev in events:
                    if ev["event_type"] == "implementer_start":
                        tid = ev["task_id"]
                        if tid not in task_to_subagent:
                            task_to_subagent[tid] = ev["subagent_id"]
                # Ensure different tasks have different subagent_ids
                subagents = list(task_to_subagent.values())
                if len(subagents) == len(set(subagents)) and len(subagents) >= max(1, len(tasks) if tasks else 1):
                    subagent_unique = True
            checks["implementer_subagent_ids_unique"] = subagent_unique and checks["execution_trace_valid"]

            # No parallelization: the first implementer_start of any later task occurs only after previous task's code_quality_review_finish
            no_parallel_ok = False
            if checks["execution_trace_valid"]:
                # Determine order of tasks by first implementer_start step (index)
                first_impl_idx = {}
                cq_finish_idx = {}
                for i, ev in enumerate(events):
                    tid = ev["task_id"]
                    if ev["event_type"] == "implementer_start" and tid not in first_impl_idx:
                        first_impl_idx[tid] = i
                    if ev["event_type"] == "code_quality_review_finish":
                        # last occurrence for finish is fine; but we need at least one
                        cq_finish_idx[tid] = i
                # Sort tasks by implementer_start index
                ordered_tasks = sorted(first_impl_idx.items(), key=lambda x: x[1])
                if len(ordered_tasks) >= 2:
                    ok_chain = True
                    for idx in range(len(ordered_tasks) - 1):
                        prev_tid, prev_start_i = ordered_tasks[idx]
                        next_tid, next_start_i = ordered_tasks[idx + 1]
                        # prev task must have cqr finish before next implementer_start
                        if prev_tid not in cq_finish_idx:
                            ok_chain = False
                            break
                        if not (cq_finish_idx[prev_tid] < next_start_i):
                            ok_chain = False
                            break
                    no_parallel_ok = ok_chain
                elif len(ordered_tasks) == 1:
                    # Single task trivially no parallel
                    no_parallel_ok = True
            checks["no_parallelization_enforced"] = no_parallel_ok and checks["execution_trace_valid"]

    # 4) Todo tracker
    todo_path = os.path.join(output_dir, "todo.json")
    if os.path.isfile(todo_path):
        checks["todo_exists"] = True
        ok_t, tdata = load_json(todo_path)
        valid_todo = False
        all_true = False
        if ok_t:
            # Accept either dict keyed by task_id, or list of entries with id field
            task_ids = tasks if tasks else []
            entries = {}
            if isinstance(tdata, dict):
                entries = tdata
                valid_todo = True
            elif isinstance(tdata, list):
                # Convert to dict by id if possible
                try:
                    entries = {el["id"]: el for el in tdata if isinstance(el, dict) and "id" in el}
                    valid_todo = True
                except Exception:
                    valid_todo = False
            else:
                valid_todo = False

            if valid_todo:
                all_true_flag = True
                if task_ids:
                    # Ensure every task id present with booleans
                    for tid in task_ids:
                        if tid not in entries or not isinstance(entries[tid], dict):
                            all_true_flag = False
                            break
                        v = entries[tid]
                        for k in ("implementer_done", "spec_review_pass", "code_quality_pass", "complete"):
                            if k not in v or not isinstance(v[k], bool) or v[k] is not True:
                                all_true_flag = False
                                break
                        if not all_true_flag:
                            break
                else:
                    # If no tasks parsed, require at least one entry and all booleans true
                    if not entries:
                        all_true_flag = False
                    else:
                        for v in entries.values():
                            if not isinstance(v, dict):
                                all_true_flag = False
                                break
                            for k in ("implementer_done", "spec_review_pass", "code_quality_pass", "complete"):
                                if k not in v or not isinstance(v[k], bool) or v[k] is not True:
                                    all_true_flag = False
                                    break
                            if not all_true_flag:
                                break
                all_true = all_true_flag

        checks["todo_valid"] = valid_todo
        checks["todo_all_true"] = all_true and valid_todo

    # 5) Branch and final review
    branch_path = os.path.join(output_dir, "branch.txt")
    if os.path.isfile(branch_path):
        try:
            with open(branch_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            nonempty_lines = [ln.strip() for ln in lines if ln.strip() != ""]
            if len(nonempty_lines) == 1:
                name = nonempty_lines[0]
                if name.lower() not in ("main", "master"):
                    checks["branch_file_valid"] = True
        except Exception:
            pass

    final_review_path = os.path.join(output_dir, "final_review.md")
    if os.path.isfile(final_review_path):
        try:
            with open(final_review_path, "r", encoding="utf-8") as f:
                content = f.read().lower()
            if ("ready to merge" in content) or ("all requirements met" in content):
                checks["final_review_contains_phrase"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Ensure baseline no-op yields 0.0 if output missing/empty
    # If output dir is missing or empty of the primary required artifacts, force reward to 0.0
    critical_files = [
        os.path.join(output_dir, "extracted_tasks.json"),
        os.path.join(output_dir, "execution_trace.json"),
        os.path.join(output_dir, "todo.json"),
        os.path.join(output_dir, "branch.txt"),
        os.path.join(output_dir, "final_review.md"),
    ]
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        any_critical_exists = any(os.path.isfile(p) for p in critical_files)
        if not any_critical_exists:
            reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()