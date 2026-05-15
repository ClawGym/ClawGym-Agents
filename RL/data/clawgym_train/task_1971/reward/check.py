import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def split_lines(text):
    return text.splitlines() if text is not None else []

def has_section_title(lines, title):
    # Matches a markdown section title like "## First Steps" or plain "First Steps"
    for ln in lines:
        s = ln.strip()
        # Remove leading markdown heading markers and spaces
        s2 = s.lstrip('#').strip()
        if s2 == title:
            return True
    return False

def contains_all_phrases(text, phrases):
    if text is None:
        return False
    return all(p in text for p in phrases)

def lines_contain_all_exact(lines, exact_lines):
    if not lines:
        return False
    line_set = [ln.strip() for ln in lines]
    return all(ex in line_set for ex in exact_lines)

def find_indices_of_phrase(lines, phrase):
    idxs = []
    if not lines:
        return idxs
    for i, ln in enumerate(lines):
        if phrase in ln:
            idxs.append(i)
    return idxs

def window_has_label(lines, start_idx, label, max_lookahead=8):
    if not lines:
        return False
    end = min(len(lines), start_idx + 1 + max_lookahead)
    for i in range(start_idx + 1, end):
        s = lines[i].lstrip()
        if s.startswith(label):
            return True
    return False

def parse_index_items(index_text):
    try:
        obj = json.loads(index_text)
    except Exception:
        return None, False
    items = None
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        if "items" in obj and isinstance(obj["items"], list):
            items = obj["items"]
        else:
            # Maybe a dict keyed by id
            vals = list(obj.values())
            if all(isinstance(v, dict) for v in vals) and all("id" in v for v in vals):
                items = vals
    return items, True if items is not None else False

def includes_cover(includes_list, required_list):
    if not isinstance(includes_list, list):
        return False
    # ensure all required are present as substrings in at least one include entry
    for req in required_list:
        found = False
        for inc in includes_list:
            if isinstance(inc, str) and req in inc:
                found = True
                break
        if not found:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    kit_dir = os.path.join(output_dir, "kit")
    quickstart_path = os.path.join(kit_dir, "quickstart.md")
    migration_path = os.path.join(kit_dir, "migration_plan.md")
    security_path = os.path.join(kit_dir, "security_checklist.md")
    troubleshooting_path = os.path.join(kit_dir, "troubleshooting.md")
    performance_path = os.path.join(kit_dir, "performance.md")
    index_path = os.path.join(kit_dir, "index.json")

    checks = {
        # Existence checks
        "files_exist_quickstart": False,
        "files_exist_migration_plan": False,
        "files_exist_security_checklist": False,
        "files_exist_troubleshooting": False,
        "files_exist_performance": False,
        "files_exist_index": False,

        # quickstart content checks
        "quickstart_has_first_steps_title": False,
        "quickstart_has_all_first_steps": False,

        # migration content checks
        "migration_has_pre_migration_checklist_title": False,
        "migration_has_all_pre_migration_checklist_items": False,
        "migration_has_migration_steps_title": False,
        "migration_has_all_migration_steps_items": False,

        # security content checks
        "security_has_auth_title": False,
        "security_has_data_title": False,
        "security_has_network_title": False,
        "security_has_all_reference_bullets": False,
        "security_has_mfa_phrase": False,

        # troubleshooting content checks per error
        "troubleshooting_connection_refused": False,
        "troubleshooting_permission_denied": False,
        "troubleshooting_timeout": False,
        "troubleshooting_invalid_input": False,

        # performance content checks
        "performance_has_optimization_strategies_title": False,
        "performance_has_all_strategies": False,

        # index.json checks
        "index_is_valid_json": False,
        "index_has_required_entries": False,
        "index_paths_correct": False,
        "index_includes_cover_requirements": False,
    }

    # Existence
    checks["files_exist_quickstart"] = os.path.isfile(quickstart_path)
    checks["files_exist_migration_plan"] = os.path.isfile(migration_path)
    checks["files_exist_security_checklist"] = os.path.isfile(security_path)
    checks["files_exist_troubleshooting"] = os.path.isfile(troubleshooting_path)
    checks["files_exist_performance"] = os.path.isfile(performance_path)
    checks["files_exist_index"] = os.path.isfile(index_path)

    # quickstart.md content
    if checks["files_exist_quickstart"]:
        q_text = read_text(quickstart_path)
        q_lines = split_lines(q_text)
        checks["quickstart_has_first_steps_title"] = has_section_title(q_lines, "First Steps")
        quickstart_items = [
            "Run the hello-world example",
            "Review the default configuration",
            "Try a simple real-world task",
            "Explore available commands and options",
        ]
        checks["quickstart_has_all_first_steps"] = contains_all_phrases(q_text or "", quickstart_items)

    # migration_plan.md content
    if checks["files_exist_migration_plan"]:
        m_text = read_text(migration_path)
        m_lines = split_lines(m_text)
        checks["migration_has_pre_migration_checklist_title"] = has_section_title(m_lines, "Pre-Migration Checklist")
        pre_migration_checkbox_lines = [
            "- [ ] Current system fully documented",
            "- [ ] Complete backup taken and verified",
            "- [ ] Target environment prepared",
            "- [ ] Rollback plan documented",
            "- [ ] Stakeholders notified",
        ]
        checks["migration_has_all_pre_migration_checklist_items"] = lines_contain_all_exact(m_lines, pre_migration_checkbox_lines)

        checks["migration_has_migration_steps_title"] = has_section_title(m_lines, "Migration Steps")
        migration_steps_lines = [
            "1. Prepare target environment",
            "2. Export data from source",
            "3. Transform data if needed",
            "4. Import to target",
            "5. Verify data integrity",
            "6. Update configurations",
            "7. Test all functionality",
            "8. Switch traffic / go live",
        ]
        checks["migration_has_all_migration_steps_items"] = lines_contain_all_exact(m_lines, migration_steps_lines)

    # security_checklist.md content
    if checks["files_exist_security_checklist"]:
        s_text = read_text(security_path)
        s_lines = split_lines(s_text)
        checks["security_has_auth_title"] = has_section_title(s_lines, "Authentication & Authorization")
        checks["security_has_data_title"] = has_section_title(s_lines, "Data Protection")
        checks["security_has_network_title"] = has_section_title(s_lines, "Network Security")

        # Bullet points from reference
        auth_bullets = [
            "Use strong, unique credentials",
            "Implement role-based access control",
            "Enable multi-factor authentication where possible",
            "Regularly review and rotate credentials",
        ]
        data_bullets = [
            "Encrypt data at rest and in transit",
            "Implement proper backup procedures",
            "Follow data retention policies",
            "Sanitize inputs to prevent injection",
        ]
        net_bullets = [
            "Use firewalls and network segmentation",
            "Monitor for suspicious activity",
            "Keep all software patched and updated",
            "Disable unnecessary services and ports",
        ]
        all_bullets = auth_bullets + data_bullets + net_bullets
        checks["security_has_all_reference_bullets"] = contains_all_phrases(s_text or "", all_bullets)
        checks["security_has_mfa_phrase"] = ("multi-factor authentication" in (s_text or ""))

    # troubleshooting.md content
    if checks["files_exist_troubleshooting"]:
        t_text = read_text(troubleshooting_path)
        t_lines = split_lines(t_text)
        error_phrases = {
            "Connection refused": "troubleshooting_connection_refused",
            "Permission denied": "troubleshooting_permission_denied",
            "Timeout": "troubleshooting_timeout",
            "Invalid input": "troubleshooting_invalid_input",
        }
        for err, key in error_phrases.items():
            idxs = find_indices_of_phrase(t_lines, err)
            has_both = False
            for idx in idxs:
                has_diag = window_has_label(t_lines, idx, "Diagnosis:")
                has_fix = window_has_label(t_lines, idx, "Fix:")
                if has_diag and has_fix:
                    has_both = True
                    break
            checks[key] = has_both

    # performance.md content
    if checks["files_exist_performance"]:
        p_text = read_text(performance_path)
        p_lines = split_lines(p_text)
        checks["performance_has_optimization_strategies_title"] = has_section_title(p_lines, "Optimization Strategies")
        strategies = ["Caching", "Batching", "Indexing", "Compression", "Parallel Processing"]
        checks["performance_has_all_strategies"] = contains_all_phrases(p_text or "", strategies)

    # index.json checks
    if checks["files_exist_index"]:
        idx_text = read_text(index_path)
        items, parsed = parse_index_items(idx_text or "")
        checks["index_is_valid_json"] = True if parsed else False

        if items is not None:
            # Build lookup by id
            id_map = {}
            for it in items:
                if isinstance(it, dict) and "id" in it:
                    id_map[it["id"]] = it

            required_ids = ["quickstart", "migration_plan", "security_checklist", "troubleshooting", "performance"]
            checks["index_has_required_entries"] = all(rid in id_map for rid in required_ids)

            expected_paths = {
                "quickstart": "output/kit/quickstart.md",
                "migration_plan": "output/kit/migration_plan.md",
                "security_checklist": "output/kit/security_checklist.md",
                "troubleshooting": "output/kit/troubleshooting.md",
                "performance": "output/kit/performance.md",
            }

            paths_ok = True
            includes_ok = True

            # Required includes per id
            quickstart_required_includes = [
                "Run the hello-world example",
                "Review the default configuration",
                "Try a simple real-world task",
                "Explore available commands and options",
            ]
            migration_required_includes = [
                "Current system fully documented",
                "Complete backup taken and verified",
                "Target environment prepared",
                "Rollback plan documented",
                "Stakeholders notified",
            ]
            security_required_includes = [
                "Authentication & Authorization",
                "Data Protection",
                "Network Security",
                "multi-factor authentication",
            ]
            troubleshooting_required_includes = [
                "Connection refused",
                "Permission denied",
                "Timeout",
                "Invalid input",
            ]
            performance_required_includes = [
                "Caching",
                "Batching",
                "Indexing",
                "Compression",
                "Parallel Processing",
            ]

            expected_includes = {
                "quickstart": quickstart_required_includes,
                "migration_plan": migration_required_includes,
                "security_checklist": security_required_includes,
                "troubleshooting": troubleshooting_required_includes,
                "performance": performance_required_includes,
            }

            if checks["index_has_required_entries"]:
                for rid in required_ids:
                    obj = id_map.get(rid, {})
                    pth = obj.get("path")
                    if pth != expected_paths[rid]:
                        paths_ok = False
                    incs = obj.get("includes")
                    # For migration, allow presence with or without "- [ ] " prefix because we use substring matching
                    if not includes_cover(incs, expected_includes[rid]):
                        includes_ok = False
            else:
                paths_ok = False
                includes_ok = False

            checks["index_paths_correct"] = paths_ok
            checks["index_includes_cover_requirements"] = includes_ok

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()