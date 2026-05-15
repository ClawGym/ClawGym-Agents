import json
import os
import re
import sys
from datetime import datetime

def normalize_source_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")

def parse_tools_md(path):
    sources = {}
    default_source = None
    max_retries = None
    if not os.path.isfile(path):
        return sources, default_source, max_retries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.lstrip().startswith("#"):
                continue
            m = re.match(r'^MODEL_SOURCE_([A-Z0-9_]+)\s*=\s*(.+)$', line)
            if m:
                suffix = m.group(1)
                models_csv = m.group(2).strip()
                # remove inline comments if any
                models_csv = models_csv.split("#", 1)[0].strip()
                models = [s.strip() for s in models_csv.split(",") if s.strip()]
                src_name = normalize_source_name(suffix)
                sources[src_name] = models
                continue
            m = re.match(r'^DEFAULT_MODEL_SOURCE\s*=\s*(.+)$', line)
            if m:
                val = m.group(1).split("#", 1)[0].strip()
                default_source = normalize_source_name(val)
                continue
            m = re.match(r'^MODEL_QUEUE_MAX_RETRIES\s*=\s*(\d+)', line)
            if m:
                try:
                    max_retries = int(m.group(1))
                except ValueError:
                    max_retries = None
                continue
    return sources, default_source, max_retries

def parse_tasks_md(path):
    tasks = []
    if not os.path.isfile(path):
        return tasks
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    current = None
    for raw in lines:
        line = raw.strip()
        if line.lower().startswith("task:"):
            desc = line[len("task:"):].strip()
            current = {"description": desc, "goal": None}
        elif line.lower().startswith("goal:"):
            goal = line[len("goal:"):].strip()
            if current is not None:
                current["goal"] = goal
                # detect cues from description and goal
                desc_lower = (current["description"] or "").lower()
                goal_lower = (current["goal"] or "").lower()
                # dependency indicator
                current["has_dependency_indicator"] = ("after that" in desc_lower) or ("after that" in goal_lower)
                # explicit model (looking specifically for 'ollama/qwen2.5' as per task)
                explicit_model = None
                for text in [current["description"], current["goal"]]:
                    if text and "ollama/qwen2.5" in text:
                        explicit_model = "ollama/qwen2.5"
                        break
                current["explicit_model"] = explicit_model
                # send to remote
                current["send_to_remote"] = ("send to remote" in desc_lower) or ("send to remote" in goal_lower)
                # continue on fail indicator
                current["continue_anyway"] = ("continue anyway" in desc_lower) or ("continue anyway" in goal_lower) or ("previous step fails, continue" in desc_lower) or ("previous step fails, continue" in goal_lower)
                tasks.append(current)
                current = None
    return tasks

def first_model_for_source(sources, src):
    models = sources.get(src) or []
    return models[0] if models else None

def find_remote_source_name(sources):
    # choose a source that contains 'remote' in its name
    for src in sources.keys():
        if "remote" in src:
            return src
    return None

def build_expected(tasks, sources, default_source):
    # reverse mapping model->(source_name, canonical model string)
    model_to_source = {}
    for src, models in sources.items():
        for m in models:
            model_to_source[m.lower()] = (src, m)
    remote_source = find_remote_source_name(sources)
    # if default source not provided or not found, fall back to first available
    if not default_source or default_source not in sources:
        if sources:
            default_source = sorted(sources.keys())[0]
        else:
            default_source = None

    expected = []
    used_sources = set()
    # assign ids per queue incrementally as tasks are routed
    queue_counters = {}
    # we'll fill in depends_on after generating ids, but we need predecessor id available
    predecessor_ids = []  # list of ids in original order
    for idx, t in enumerate(tasks):
        # determine routing
        route_source = None
        route_model = None
        if t.get("explicit_model"):
            key = t["explicit_model"].lower()
            if key in model_to_source:
                route_source, route_model = model_to_source[key]
            else:
                # model specified but not found in mapping; assign model and leave source unknown
                route_model = t["explicit_model"]
                route_source = None
        elif t.get("send_to_remote"):
            route_source = remote_source if remote_source else default_source
            if route_source:
                route_model = first_model_for_source(sources, route_source)
        else:
            route_source = default_source
            if route_source:
                route_model = first_model_for_source(sources, route_source)

        # ensure we have a source; if model specified but source not found, try to infer
        if route_source is None and route_model:
            # try to find source by model name in mapping
            key = route_model.lower()
            if key in model_to_source:
                route_source = model_to_source[key][0]

        # assign id per queue
        if route_source is None:
            # fallback to a deterministic placeholder if no sources configured; still produce expected logically
            route_source = "unknown-source"
        used_sources.add(route_source)
        n = queue_counters.get(route_source, 0) + 1
        queue_counters[route_source] = n
        task_id = f"T-{n:03d}"
        predecessor_ids.append(task_id)  # placeholder; we'll adjust depends_on based on previous task's id across queues

        # determine depends_on/status
        has_dep = False
        if idx == 0:
            has_dep = False
        else:
            # dependency indicated by phrase
            has_dep = bool(tasks[idx].get("has_dependency_indicator"))
        depends_on = predecessor_ids[idx - 1] if has_dep else None
        status = "waiting" if has_dep else "pending"
        on_depends_fail = "continue" if tasks[idx].get("continue_anyway") else "block"

        expected.append({
            "id": task_id,
            "queue": route_source,
            "model": route_model,
            "description": t["description"],
            "goal": t["goal"],
            "status": status,
            "depends_on": depends_on,
            "on_depends_fail": on_depends_fail
        })
    return expected, used_sources

def group_expected_by_queue(expected_list):
    groups = {}
    for t in expected_list:
        q = t["queue"]
        groups.setdefault(q, []).append(t)
    return groups

def validate_id_sequence(ids):
    # ids like T-001, T-002 ... ensure sequential from 1
    nums = []
    for i in ids:
        m = re.match(r'^T-(\d+)$', i)
        if not m:
            return False
        nums.append(int(m.group(1)))
    if not nums:
        return False
    nums_sorted = sorted(nums)
    # ensure no duplicates and range is 1..N
    if nums != sorted(ids, key=lambda x: int(x.split('-')[1])) and False:
        # This was intended to compare order but we don't require order; ignore
        pass
    if nums_sorted[0] != 1:
        return False
    for i, v in enumerate(nums_sorted, start=1):
        if v != i:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    tools_md = os.path.join(input_dir, "TOOLS.md")
    tasks_md = os.path.join(input_dir, "tasks.md")

    sources, default_source, max_retries = parse_tools_md(tools_md)
    tasks = parse_tasks_md(tasks_md)
    # Build expected based on inputs
    expected_tasks, used_sources = build_expected(tasks, sources, default_source)
    expected_by_queue = group_expected_by_queue(expected_tasks)

    checks = {}
    output_checks = []

    # Queue files validations
    queues_dir = os.path.join(output_dir, "queues")
    # For each used source, expect a queue file
    all_queue_data = {}  # source -> (data, tasks_list)
    for src in sorted(used_sources):
        queue_path = os.path.join(queues_dir, f"{src}.json")
        key_exists = f"queue_{src}_exists"
        exists = os.path.isfile(queue_path)
        checks[key_exists] = exists
        output_checks.append(key_exists)

        key_valid = f"queue_{src}_valid_json"
        key_ids = f"queue_{src}_id_sequence"
        key_tasks = f"queue_{src}_tasks_match"
        checks[key_valid] = False
        checks[key_ids] = False
        checks[key_tasks] = False
        output_checks.append(key_valid)
        output_checks.append(key_ids)
        output_checks.append(key_tasks)

        if not exists:
            continue
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            checks[key_valid] = False
            continue

        # basic schema-lite
        if isinstance(data, dict) and isinstance(data.get("source"), str) and isinstance(data.get("tasks"), list) and isinstance(data.get("lastId"), str):
            checks[key_valid] = True
        else:
            checks[key_valid] = False

        if not checks[key_valid]:
            continue

        # validate id sequencing in this queue
        actual_ids = [t.get("id") for t in data.get("tasks", []) if isinstance(t, dict)]
        if actual_ids and all(isinstance(i, str) for i in actual_ids):
            seq_ok = validate_id_sequence(actual_ids)
            # lastId matches max id
            last_id = data.get("lastId")
            checks[key_ids] = seq_ok and (last_id == (f"T-{len(actual_ids):03d}"))
        else:
            checks[key_ids] = False

        # tasks match expected for this queue
        expected_tasks_for_src = expected_by_queue.get(src, [])
        # Build map by id for actual tasks
        actual_by_id = {}
        for t in data.get("tasks", []):
            if isinstance(t, dict) and isinstance(t.get("id"), str):
                actual_by_id[t["id"]] = t

        # Verify counts first
        tasks_ok = True
        if len(expected_tasks_for_src) != len(actual_by_id):
            tasks_ok = False
        else:
            # validate each expected task fields
            for et in expected_tasks_for_src:
                eid = et["id"]
                at = actual_by_id.get(eid)
                if not at:
                    tasks_ok = False
                    break
                # description and goal must be verbatim
                if at.get("description") != et["description"] or at.get("goal") != et["goal"]:
                    tasks_ok = False
                    break
                # queue field equals source name if present
                if "queue" in at and at.get("queue") != src:
                    tasks_ok = False
                    break
                # model assignment
                if et["model"] is not None and at.get("model") != et["model"]:
                    tasks_ok = False
                    break
                # status pending/waiting
                if at.get("status") not in ("pending", "waiting"):
                    tasks_ok = False
                    break
                # status correctness based on expected
                if at.get("status") != et["status"]:
                    tasks_ok = False
                    break
                # depends_on correctness; expected None maps to None
                a_dep = at.get("depends_on")
                if et["depends_on"] is None:
                    if a_dep is not None:
                        tasks_ok = False
                        break
                else:
                    if a_dep != et["depends_on"]:
                        tasks_ok = False
                        break
                # on_depends_fail correctness if present
                if "on_depends_fail" in at:
                    if at.get("on_depends_fail") != et["on_depends_fail"]:
                        tasks_ok = False
                        break

        checks[key_tasks] = tasks_ok
        if tasks_ok:
            all_queue_data[src] = (data, data.get("tasks", []))

    # Allowed statuses only across all queues
    key_allowed_statuses = "statuses_only_pending_waiting"
    checks[key_allowed_statuses] = False
    output_checks.append(key_allowed_statuses)
    allowed = True
    if all_queue_data:
        for src, (data, tasks_list) in all_queue_data.items():
            for t in tasks_list:
                st = t.get("status")
                if st not in ("pending", "waiting"):
                    allowed = False
                    break
            if not allowed:
                break
        checks[key_allowed_statuses] = allowed
    else:
        checks[key_allowed_statuses] = False

    # Cross-queue dependency chain correctness
    key_cross_deps = "cross_queue_dependencies_ok"
    checks[key_cross_deps] = False
    output_checks.append(key_cross_deps)
    # Validate that for each expected task, the depends_on id matches predecessor id, and that those ids exist in appropriate queues
    cross_ok = True
    if all_queue_data:
        # Build lookup actual presence of ids in queues
        actual_id_to_queue = {}
        for src, (data, tasks_list) in all_queue_data.items():
            for t in tasks_list:
                tid = t.get("id")
                if isinstance(tid, str):
                    actual_id_to_queue[tid] = src
        # Verify depends_on across expected
        for idx, et in enumerate(expected_tasks):
            dep = et["depends_on"]
            if dep is None:
                continue
            # predecessor id must exist in actual queues
            if dep not in actual_id_to_queue:
                cross_ok = False
                break
            # The task itself must exist too
            t_src = et["queue"]
            # Ensure task with expected id exists in its queue
            # We can get id from et["id"]
            if et["id"] not in actual_id_to_queue:
                cross_ok = False
                break
    else:
        cross_ok = False
    checks[key_cross_deps] = cross_ok

    # Reports: queue_status.txt
    reports_dir = os.path.join(output_dir, "reports")
    queue_status_path = os.path.join(reports_dir, "queue_status.txt")
    key_status_exists = "report_queue_status_exists"
    status_exists = os.path.isfile(queue_status_path)
    checks[key_status_exists] = status_exists
    output_checks.append(key_status_exists)

    # For each used source, ensure a line mentions source and pending/waiting with counts matching actual
    if status_exists:
        try:
            with open(queue_status_path, "r", encoding="utf-8") as f:
                status_lines = [ln.strip() for ln in f.readlines()]
        except Exception:
            status_lines = []
    else:
        status_lines = []

    for src in sorted(used_sources):
        key_counts = f"report_counts_{src}_ok"
        checks[key_counts] = False
        output_checks.append(key_counts)
        if not status_exists:
            continue
        # compute expected counts from actual queue JSON if available; else from expected
        if src in all_queue_data:
            actual_tasks = all_queue_data[src][1]
            pend_cnt = sum(1 for t in actual_tasks if t.get("status") == "pending")
            wait_cnt = sum(1 for t in actual_tasks if t.get("status") == "waiting")
        else:
            # fall back to expected counts (if queue file missing/invalid, this check should remain False)
            pend_cnt = sum(1 for t in expected_by_queue.get(src, []) if t.get("status") == "pending")
            wait_cnt = sum(1 for t in expected_by_queue.get(src, []) if t.get("status") == "waiting")

        found_line_ok = False
        for ln in status_lines:
            if src in ln:
                pm = re.search(r'pending[^0-9]*(\d+)', ln, flags=re.I)
                wm = re.search(r'waiting[^0-9]*(\d+)', ln, flags=re.I)
                if pm and wm:
                    try:
                        p_val = int(pm.group(1))
                        w_val = int(wm.group(1))
                        if p_val == pend_cnt and w_val == wait_cnt:
                            found_line_ok = True
                            break
                    except ValueError:
                        continue
        checks[key_counts] = found_line_ok

    # Reports: tasks_audit.json
    audit_path = os.path.join(reports_dir, "tasks_audit.json")
    key_audit_exists = "report_tasks_audit_exists"
    audit_exists = os.path.isfile(audit_path)
    checks[key_audit_exists] = audit_exists
    output_checks.append(key_audit_exists)

    key_audit_valid = "report_tasks_audit_valid"
    key_audit_match = "report_tasks_audit_matches_expected"
    checks[key_audit_valid] = False
    checks[key_audit_match] = False
    output_checks.append(key_audit_valid)
    output_checks.append(key_audit_match)

    audit_data = None
    if audit_exists:
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                audit_data = json.load(f)
        except Exception:
            audit_data = None

        # Validate structure
        if isinstance(audit_data, list) and len(audit_data) == 4:
            # check fields existence
            valid_struct = True
            for obj in audit_data:
                if not isinstance(obj, dict):
                    valid_struct = False
                    break
                required_keys = ["id", "queue", "model", "description", "goal", "status", "depends_on", "on_depends_fail"]
                for k in required_keys:
                    if k not in obj:
                        valid_struct = False
                        break
                if not valid_struct:
                    break
            checks[key_audit_valid] = valid_struct
        else:
            checks[key_audit_valid] = False

        # Validate matches expected
        if checks[key_audit_valid]:
            # map by id
            audit_by_id = {o.get("id"): o for o in audit_data if isinstance(o, dict) and isinstance(o.get("id"), str)}
            match_ok = True
            for et in expected_tasks:
                aid = et["id"]
                ao = audit_by_id.get(aid)
                if not ao:
                    match_ok = False
                    break
                # compare fields
                if ao.get("queue") != et["queue"]:
                    match_ok = False
                    break
                if et["model"] is not None and ao.get("model") != et["model"]:
                    match_ok = False
                    break
                if ao.get("description") != et["description"] or ao.get("goal") != et["goal"]:
                    match_ok = False
                    break
                if ao.get("status") != et["status"]:
                    match_ok = False
                    break
                # depends_on: None vs null
                if et["depends_on"] is None:
                    if ao.get("depends_on") is not None:
                        match_ok = False
                        break
                else:
                    if ao.get("depends_on") != et["depends_on"]:
                        match_ok = False
                        break
                if ao.get("on_depends_fail") != et["on_depends_fail"]:
                    match_ok = False
                    break
            # Also ensure IDs in audit exist in queues (consistency)
            if match_ok and all_queue_data:
                for aid, ao in audit_by_id.items():
                    qn = ao.get("queue")
                    if qn in all_queue_data:
                        ids_in_queue = {t.get("id") for t in all_queue_data[qn][1]}
                        if aid not in ids_in_queue:
                            match_ok = False
                            break
            checks[key_audit_match] = match_ok
        else:
            checks[key_audit_match] = False

    # Compute reward as fraction of output-dependent checks that passed
    total = len(output_checks)
    passed = sum(1 for k in output_checks if checks.get(k) is True)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure reward is exactly 0.0 if outputs are missing entirely
    output_exists_any = os.path.isdir(os.path.join(output_dir)) and any(
        os.path.exists(os.path.join(output_dir, p)) for p in ["queues", "reports"]
    )
    if not output_exists_any:
        reward = 0.0

    # Build final result with reward first
    result = {"reward": round(reward, 6)}
    # Merge checks
    # Sort keys for determinism
    for k in sorted(checks.keys()):
        result[k] = bool(checks[k])

    print(json.dumps(result))

if __name__ == "__main__":
    main()