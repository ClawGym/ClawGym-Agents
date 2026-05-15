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

def file_exists(path):
    return os.path.isfile(path)

def parse_json_array_with_schema(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False, None
    if not isinstance(data, list):
        return False, None
    allowed_sli_types = {"availability", "latency", "freshness", "correctness"}
    for item in data:
        if not isinstance(item, dict):
            return False, data
        required_keys = {"service", "journey", "sli_type", "measure", "source"}
        if not required_keys.issubset(set(item.keys())):
            return False, data
        sli_type = item.get("sli_type")
        if sli_type not in allowed_sli_types:
            return False, data
    return True, data

def validate_yaml_like(content):
    """
    Attempt to validate YAML using PyYAML if available; otherwise use a conservative pattern check.
    Returns (ok, had_window_30d, has_required_fields, has_dependencies_flag)
    """
    had_window_30d = False
    has_required_fields = False
    has_dependencies_flag = False
    # Try to import yaml if available
    loader_ok = False
    try:
        import yaml  # type: ignore
        loader_ok = True
    except Exception:
        loader_ok = False

    if loader_ok:
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(content)
            # Walk through objects to find any dict with required keys
            def walk(obj):
                nonlocal had_window_30d, has_required_fields, has_dependencies_flag
                if isinstance(obj, dict):
                    keys = set(obj.keys())
                    # Ensure presence of required fields in some dict
                    if {"journey", "target", "window", "measurement"}.issubset(keys):
                        has_required_fields = True or has_required_fields
                        if obj.get("window") == "30d":
                            had_window_30d = True or had_window_30d
                        if "dependencies_considered" in obj and isinstance(obj.get("dependencies_considered"), bool):
                            has_dependencies_flag = True or has_dependencies_flag
                    # Continue walking values
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        walk(v)
            walk(data)
            ok = has_required_fields and had_window_30d and has_dependencies_flag
            return ok, had_window_30d, has_required_fields, has_dependencies_flag
        except Exception:
            # fall back to pattern validation
            pass

    # Fallback: simple pattern-based checks
    lower = content.lower()
    # require explicit "window: 30d"
    had_window_30d = "window: 30d" in lower
    has_required_fields = ("journey:" in lower and "target:" in lower and "measurement:" in lower)
    # Look for the exact key "dependencies_considered:"
    dep_flag_pattern = re.compile(r'^\s*dependencies_considered:\s*(true|false)\s*$', re.IGNORECASE | re.MULTILINE)
    has_dependencies_flag = bool(dep_flag_pattern.search(content))
    ok = had_window_30d and has_required_fields and has_dependencies_flag
    return ok, had_window_30d, has_required_fields, has_dependencies_flag

def has_line_starting_with(content, prefix, case_sensitive=True):
    if content is None:
        return False
    for line in content.splitlines():
        # allow leading whitespace but otherwise must start with prefix
        stripped = line.lstrip()
        if case_sensitive:
            if stripped.startswith(prefix):
                return True
        else:
            if stripped.lower().startswith(prefix.lower()):
                return True
    return False

def count_list_items(content):
    if content is None:
        return 0
    count = 0
    for line in content.splitlines():
        s = line.lstrip()
        if s.startswith("- ") or s.startswith("* "):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected output files
    expected_files = {
        "QUEUE.md": os.path.join(output_dir, "QUEUE.md"),
        "SESSION-STATE.md": os.path.join(output_dir, "SESSION-STATE.md"),
        "phases.md": os.path.join(output_dir, "phases.md"),
        "slis.json": os.path.join(output_dir, "slis.json"),
        "slos.yaml": os.path.join(output_dir, "slos.yaml"),
        "error_budget_policy.md": os.path.join(output_dir, "error_budget_policy.md"),
        "alerts.md": os.path.join(output_dir, "alerts.md"),
        "toil_roadmap.md": os.path.join(output_dir, "toil_roadmap.md"),
        "delegation_plan.md": os.path.join(output_dir, "delegation_plan.md"),
        "resume_point.md": os.path.join(output_dir, "resume_point.md"),
    }

    checks = {}

    # Individual presence checks
    for name, path in expected_files.items():
        checks[f"has_{name.replace('.', '_').replace('-', '_')}"] = file_exists(path)

    # Aggregate presence check
    presence_all_ok = all(file_exists(p) for p in expected_files.values())
    checks["presence_all_ok"] = presence_all_ok

    # Content checks, initialized to False
    checks["queue_sections_ok"] = False
    checks["session_resume_ok"] = False
    checks["phases_mentions_ok"] = False
    checks["slis_json_schema_ok"] = False
    checks["slos_yaml_ok"] = False
    checks["error_policy_thresholds_ok"] = False
    checks["alerts_keywords_ok"] = False
    checks["toil_roadmap_requirements_ok"] = False
    checks["delegation_plan_keywords_ok"] = False
    checks["resume_point_requirements_ok"] = False

    # QUEUE.md content
    q_path = expected_files["QUEUE.md"]
    if file_exists(q_path):
        q_content = read_text(q_path)
        if q_content is not None:
            lower = q_content.lower()
            has_ready = "ready" in lower
            has_in_progress = "in progress" in lower
            has_done = "done" in lower
            has_blocked = "blocked" in lower
            checks["queue_sections_ok"] = all([has_ready, has_in_progress, has_done, has_blocked])

    # SESSION-STATE.md content
    s_path = expected_files["SESSION-STATE.md"]
    if file_exists(s_path):
        s_content = read_text(s_path)
        if s_content is not None:
            has_resume_point = "resume point" in s_content.lower()
            has_next_exact_step_line = has_line_starting_with(s_content, "Next exact step:", case_sensitive=True)
            checks["session_resume_ok"] = has_resume_point and has_next_exact_step_line

    # phases.md content
    p_path = expected_files["phases.md"]
    if file_exists(p_path):
        p_content = read_text(p_path)
        if p_content is not None:
            lower = p_content.lower()
            checks["phases_mentions_ok"] = all(kw in lower for kw in ["inspect", "plan", "execute", "validate", "report"])

    # slis.json content
    slis_path = expected_files["slis.json"]
    if file_exists(slis_path):
        ok, _data = parse_json_array_with_schema(slis_path)
        checks["slis_json_schema_ok"] = ok

    # slos.yaml content
    slos_path = expected_files["slos.yaml"]
    if file_exists(slos_path):
        slos_text = read_text(slos_path)
        if slos_text is not None:
            ok, _w30d, _req, _dep = validate_yaml_like(slos_text)
            checks["slos_yaml_ok"] = ok

    # error_budget_policy.md content
    ebp_path = expected_files["error_budget_policy.md"]
    if file_exists(ebp_path):
        ebp_content = read_text(ebp_path)
        if ebp_content is not None:
            lower = ebp_content.lower()
            has_25 = "25%" in ebp_content
            has_50 = "50%" in ebp_content
            has_100 = "100%" in ebp_content
            has_ship = "ship" in lower
            has_freeze = "freeze" in lower
            checks["error_policy_thresholds_ok"] = all([has_25, has_50, has_100, has_ship, has_freeze])

    # alerts.md content
    alerts_path = expected_files["alerts.md"]
    if file_exists(alerts_path):
        alerts_content = read_text(alerts_path)
        if alerts_content is not None:
            lower = alerts_content.lower()
            has_symptom_based = "symptom-based" in lower
            has_sev1 = "sev1" in lower
            has_runbook = "runbook" in lower
            has_pages_limit = "pages per engineer" in lower
            checks["alerts_keywords_ok"] = all([has_symptom_based, has_sev1, has_runbook, has_pages_limit])

    # toil_roadmap.md content
    toil_path = expected_files["toil_roadmap.md"]
    if file_exists(toil_path):
        toil_content = read_text(toil_path)
        if toil_content is not None:
            lower = toil_content.lower()
            has_owner = "owner" in lower
            has_50pct = "50%" in toil_content
            list_items = count_list_items(toil_content)
            checks["toil_roadmap_requirements_ok"] = has_owner and has_50pct and (list_items >= 2)

    # delegation_plan.md content
    del_path = expected_files["delegation_plan.md"]
    if file_exists(del_path):
        del_content = read_text(del_path)
        if del_content is not None:
            lower = del_content.lower()
            has_parallel = "parallel" in lower
            has_delegate = "delegate" in lower
            checks["delegation_plan_keywords_ok"] = has_parallel and has_delegate

    # resume_point.md content
    rp_path = expected_files["resume_point.md"]
    if file_exists(rp_path):
        rp_content = read_text(rp_path)
        if rp_content is not None:
            lower = rp_content.lower()
            has_resume_point = "resume point" in lower
            has_deliverable = "deliverable" in lower
            has_completed = "completed" in lower
            has_saved_artifacts = "saved artifacts" in lower
            has_next_exact_step_line = has_line_starting_with(rp_content, "Next exact step:", case_sensitive=True)
            checks["resume_point_requirements_ok"] = all([
                has_resume_point,
                has_deliverable,
                has_completed,
                has_saved_artifacts,
                has_next_exact_step_line
            ])

    # Compute reward as average of key content checks + aggregate presence
    scored_checks = [
        "presence_all_ok",
        "queue_sections_ok",
        "session_resume_ok",
        "phases_mentions_ok",
        "slis_json_schema_ok",
        "slos_yaml_ok",
        "error_policy_thresholds_ok",
        "alerts_keywords_ok",
        "toil_roadmap_requirements_ok",
        "delegation_plan_keywords_ok",
        "resume_point_requirements_ok",
    ]
    total = len(scored_checks)
    passed = sum(1 for k in scored_checks if checks.get(k, False))

    # No-op baseline: if no outputs at all, reward must be 0.0
    any_output = any(checks.get(f"has_{name.replace('.', '_').replace('-', '_')}", False) for name in expected_files.keys())
    if not any_output:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    # Clamp reward
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print exactly one JSON object
    result = {"reward": reward}
    # Include all checks for transparency
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()