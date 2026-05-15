import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def extract_entries(obj):
    # Return a flat list of dict entries that could contain "file" and "keyword"
    entries = []
    if isinstance(obj, list):
        entries.extend([e for e in obj if isinstance(e, dict)])
    elif isinstance(obj, dict):
        if "file" in obj and "keyword" in obj:
            entries.append(obj)
        else:
            # Common container keys
            for key in ("sources", "entries", "items", "data", "results"):
                v = obj.get(key)
                if isinstance(v, list):
                    entries.extend([e for e in v if isinstance(e, dict)])
    return entries

def main():
    # Workspace root handling
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (artifact-dependent checks start False)
    checks = {
        "checklist_exists": False,
        "checklist_has_header": False,
        "task_define_success_criteria": False,
        "task_provision_staging_env": False,
        "task_prepare_training_materials": False,
        "task_data_export_import_dry_run": False,
        "task_security_review_signoff": False,
        "context_json_exists": False,
        "context_json_valid": False,
        "context_json_has_correct_entry": False,
        "context_json_excludes_wrong_source_for_keyword": False,
    }

    # Expected substrings in the checklist
    header_required = "Phase 2: Pilot"
    required_tasks = {
        "task_define_success_criteria": 'Define success criteria for pilot (Owner: Mia, Due: 2026-04-18)',
        "task_provision_staging_env": 'Provision staging environment for 25 users (Owner: DevOps, Due: 2026-04-20)',
        "task_prepare_training_materials": 'Prepare training materials (Owner: L&D, Due: 2026-04-22)',
        "task_data_export_import_dry_run": 'Data export/import dry-run (Owner: Raj, Due: 2026-04-23)',
        "task_security_review_signoff": 'Security review sign-off (Owner: Priya, Due: 2026-04-25)',
    }

    # Paths
    checklist_path = os.path.join(output_dir, "nimbus_checklist.md")
    context_json_path = os.path.join(output_dir, "context_sources.json")

    # Validate checklist
    checklist_text = read_text(checklist_path)
    if isinstance(checklist_text, str):
        checks["checklist_exists"] = True
        if header_required in checklist_text:
            checks["checklist_has_header"] = True
        for key, substr in required_tasks.items():
            if substr in checklist_text:
                checks[key] = True

    # Validate context_sources.json
    context_obj, valid_json = load_json(context_json_path)
    if context_obj is not None or valid_json:
        # If load_json attempted, mark existence accordingly
        # Existence strictly means file is present on disk
        if os.path.isfile(context_json_path):
            checks["context_json_exists"] = True
        # JSON parse validity
        if valid_json:
            checks["context_json_valid"] = True

            entries = extract_entries(context_obj)
            # Correct entry requirement
            correct_file = "input/sessions/agentA-2026-04-08.jsonl"
            keyword = "Phase 2: Pilot"
            has_correct = any(
                isinstance(e, dict)
                and e.get("file") == correct_file
                and e.get("keyword") == keyword
                for e in entries
            )
            if has_correct:
                checks["context_json_has_correct_entry"] = True
                # Exclusion: must not list agentB file for the same keyword
                wrong_file = "input/sessions/agentB-2026-03-30.jsonl"
                any_wrong_for_keyword = any(
                    isinstance(e, dict)
                    and e.get("keyword") == keyword
                    and e.get("file") == wrong_file
                    for e in entries
                )
                checks["context_json_excludes_wrong_source_for_keyword"] = not any_wrong_for_keyword

    # Scoring weights
    weight_map = {
        "checklist_exists": 0.05,
        "checklist_has_header": 0.05,
        "task_define_success_criteria": 0.10,
        "task_provision_staging_env": 0.10,
        "task_prepare_training_materials": 0.10,
        "task_data_export_import_dry_run": 0.10,
        "task_security_review_signoff": 0.10,
        "context_json_exists": 0.05,
        "context_json_valid": 0.05,
        "context_json_has_correct_entry": 0.25,
        "context_json_excludes_wrong_source_for_keyword": 0.05,
    }

    # Ensure no-op baseline yields 0.0
    reward = 0.0
    for k, passed in checks.items():
        if passed:
            reward += weight_map.get(k, 0.0)

    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

    # Output single JSON object as last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()