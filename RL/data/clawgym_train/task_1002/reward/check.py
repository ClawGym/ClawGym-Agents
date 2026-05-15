import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Set

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_exists(path: str) -> bool:
    return os.path.isfile(path)

def find_sync_flag_in_yaml(yaml_path: str) -> Optional[bool]:
    # Minimal parser to detect a boolean for key 'sync_from_builtin'
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # match key: value
                m = re.match(r"(?i)^\s*sync_from_builtin\s*:\s*(.+?)\s*$", stripped)
                if m:
                    val = m.group(1).strip().strip('"').strip("'").lower()
                    if val in ("true", "yes", "1"):
                        return True
                    if val in ("false", "no", "0"):
                        return False
        return None
    except Exception:
        return None

def knowledge_index_listed_md_files(index_content: str) -> List[str]:
    # Find .md references excluding INDEX.md
    found = re.findall(r"([A-Za-z0-9_\-\/]+\.md)", index_content)
    files = []
    for f in found:
        base = os.path.basename(f)
        if base.lower() == "index.md":
            continue
        files.append(base)
    # unique preserve order
    seen: Set[str] = set()
    uniq = []
    for x in files:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq

def any_copied_line(src_text: str, dst_text: str) -> bool:
    # Check that at least one non-empty meaningful line from src appears in dst
    # Normalize whitespace
    dst_norm = dst_text
    for line in src_text.splitlines():
        line_clean = line.strip()
        if len(line_clean) >= 12:
            if line_clean in dst_norm:
                return True
    return False

def contains_date(text: str) -> bool:
    return re.search(r"\b\d{4}-\d{2}-\d{2}\b", text) is not None

def run_health_check(script_path: str, cwd: str) -> Optional[str]:
    try:
        res = subprocess.run(
            ["python3", script_path],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )
        # Combine stdout and stderr for safety but primarily stdout
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        return out
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    memory_root = os.path.join(output_dir, "memory")
    config_path = os.path.join(memory_root, "config.md")
    root_index_path = os.path.join(memory_root, "INDEX.md")

    projects_dir = os.path.join(memory_root, "projects")
    people_dir = os.path.join(memory_root, "people")
    decisions_dir = os.path.join(memory_root, "decisions")
    knowledge_dir = os.path.join(memory_root, "knowledge")
    collections_dir = os.path.join(memory_root, "collections")

    projects_index_path = os.path.join(projects_dir, "INDEX.md")
    people_index_path = os.path.join(people_dir, "INDEX.md")
    decisions_index_path = os.path.join(decisions_dir, "INDEX.md")
    knowledge_index_path = os.path.join(knowledge_dir, "INDEX.md")
    collections_index_path = os.path.join(collections_dir, "INDEX.md")

    helios_project_path = os.path.join(projects_dir, "helios-launch.md")
    alice_person_path = os.path.join(people_dir, "alice-kim.md")

    sync_dir = os.path.join(memory_root, "sync")
    sync_index_path = os.path.join(sync_dir, "INDEX.md")
    sync_prefs_path = os.path.join(sync_dir, "preferences.md")
    sync_decisions_path = os.path.join(sync_dir, "decisions.md")

    maintenance_path = os.path.join(memory_root, "maintenance.md")

    tools_dir = os.path.join(memory_root, "tools")
    health_check_script = os.path.join(tools_dir, "health_check.py")

    setup_yaml_path = os.path.join(input_dir, "setup.yaml")
    builtin_memory_path = os.path.join(input_dir, "builtin_memory.md")

    checks = {
        "has_config": False,
        "config_has_created_line": False,
        "config_has_categories_min_set": False,
        "config_sync_flag_aligned": False,

        "has_root_index": False,
        "root_links_projects": False,
        "root_links_people": False,
        "root_links_decisions": False,
        "root_links_knowledge": False,
        "root_links_collections": False,

        "projects_index_exists": False,
        "people_index_exists": False,
        "decisions_index_exists": False,
        "knowledge_index_exists": False,
        "collections_index_exists": False,

        "projects_index_refs_helios": False,
        "people_index_refs_alice": False,
        "collections_index_refs_books": False,
        "knowledge_index_refs_two_topics": False,

        "decisions_file_has_helios_db_choice_fields": False,

        "helios_links_alice": False,
        "helios_links_decision": False,

        "sync_index_exists": False,
        "sync_index_has_last_sync_date": False,
        "sync_preferences_exists": False,
        "sync_decisions_exists": False,
        "sync_preferences_copied_phrase": False,
        "sync_decisions_copied_phrase": False,

        "maintenance_exists": False,
        "maintenance_has_sections_and_next_date": False,

        "tools_health_check_exists": False,
        "tools_health_check_runs_and_reports_total": False,
    }

    # Config checks
    if file_exists(config_path):
        checks["has_config"] = True
        config_text = read_text(config_path) or ""
        if re.search(r"(?im)^\s*created\s*:\s*.+", config_text):
            checks["config_has_created_line"] = True
        # Verify at least the standard categories are listed
        categories_present = all(
            s in config_text.lower()
            for s in ["projects", "people", "decisions", "knowledge", "collections"]
        )
        if categories_present:
            checks["config_has_categories_min_set"] = True
        # Align sync flag with input/setup.yaml
        sync_in_setup = find_sync_flag_in_yaml(setup_yaml_path)
        m = re.search(r"(?im)^\s*sync_from_builtin\s*:\s*(.+)$", config_text)
        if m and sync_in_setup is not None:
            val = m.group(1).strip().strip('"').strip("'").lower()
            config_sync = True if val in ("true", "yes", "1") else False
            if config_sync == sync_in_setup:
                checks["config_sync_flag_aligned"] = True

    # Root index checks
    if file_exists(root_index_path):
        checks["has_root_index"] = True
        root_idx_text = read_text(root_index_path) or ""
        if "projects/INDEX.md".lower() in root_idx_text.lower():
            checks["root_links_projects"] = True
        if "people/INDEX.md".lower() in root_idx_text.lower():
            checks["root_links_people"] = True
        if "decisions/INDEX.md".lower() in root_idx_text.lower():
            checks["root_links_decisions"] = True
        if "knowledge/INDEX.md".lower() in root_idx_text.lower():
            checks["root_links_knowledge"] = True
        if "collections/INDEX.md".lower() in root_idx_text.lower():
            checks["root_links_collections"] = True

    # Category index existence
    if file_exists(projects_index_path):
        checks["projects_index_exists"] = True
    if file_exists(people_index_path):
        checks["people_index_exists"] = True
    if file_exists(decisions_index_path):
        checks["decisions_index_exists"] = True
    if file_exists(knowledge_index_path):
        checks["knowledge_index_exists"] = True
    if file_exists(collections_index_path):
        checks["collections_index_exists"] = True

    # Category index references
    if checks["projects_index_exists"]:
        proj_idx = read_text(projects_index_path) or ""
        if "helios-launch.md".lower() in proj_idx.lower():
            checks["projects_index_refs_helios"] = True

    if checks["people_index_exists"]:
        ppl_idx = read_text(people_index_path) or ""
        if "alice-kim.md".lower() in ppl_idx.lower():
            checks["people_index_refs_alice"] = True

    if checks["collections_index_exists"]:
        coll_idx = read_text(collections_index_path) or ""
        if "books.md".lower() in coll_idx.lower():
            checks["collections_index_refs_books"] = True

    if checks["knowledge_index_exists"]:
        know_idx = read_text(knowledge_index_path) or ""
        md_files = knowledge_index_listed_md_files(know_idx)
        # ensure at least two unique topic files exist in knowledge_dir
        existing = 0
        for nf in md_files:
            if nf.lower() == "index.md":
                continue
            if file_exists(os.path.join(knowledge_dir, nf)):
                existing += 1
        if existing >= 2:
            checks["knowledge_index_refs_two_topics"] = True

    # Decisions content check: "Database choice for Helios" and template fields
    decisions_ok = False
    decision_file_linked_from_helios = None
    if os.path.isdir(decisions_dir):
        for root, _, files in os.walk(decisions_dir):
            for fn in files:
                if not fn.lower().endswith(".md"):
                    continue
                fpath = os.path.join(root, fn)
                content = read_text(fpath) or ""
                if re.search(r"database choice for helios", content, flags=re.IGNORECASE):
                    # verify template fields present
                    fields = ["Decision:", "Options considered:", "Reasoning:", "Outcome:", "Revisit:"]
                    if all(field in content for field in fields):
                        decisions_ok = True
                        decision_file_linked_from_helios = os.path.relpath(fpath, decisions_dir)
                        break
            if decisions_ok:
                break
    if decisions_ok:
        checks["decisions_file_has_helios_db_choice_fields"] = True

    # Cross-references in helios project
    if file_exists(helios_project_path):
        helios_text = read_text(helios_project_path) or ""
        if "people/alice-kim.md".lower() in helios_text.lower():
            checks["helios_links_alice"] = True
        # Look for a link to decisions/*.md
        m = re.search(r"\((decisions\/[A-Za-z0-9_\-\/]+\.md(?:#[^)]+)?)\)|\bdecisions\/[A-Za-z0-9_\-\/]+\.md", helios_text)
        if m:
            checks["helios_links_decision"] = True

    # Sync checks
    if file_exists(sync_index_path):
        checks["sync_index_exists"] = True
        sync_index_text = read_text(sync_index_path) or ""
        if re.search(r"last\s*sync", sync_index_text, flags=re.IGNORECASE) and contains_date(sync_index_text):
            checks["sync_index_has_last_sync_date"] = True

    if file_exists(sync_prefs_path):
        checks["sync_preferences_exists"] = True

    if file_exists(sync_decisions_path):
        checks["sync_decisions_exists"] = True

    # Copy verification from builtin memory
    builtin_text = read_text(builtin_memory_path) or ""
    if checks["sync_preferences_exists"] and builtin_text:
        prefs_text = read_text(sync_prefs_path) or ""
        if any_copied_line(builtin_text, prefs_text):
            checks["sync_preferences_copied_phrase"] = True

    if checks["sync_decisions_exists"] and builtin_text:
        sync_dec_text = read_text(sync_decisions_path) or ""
        if any_copied_line(builtin_text, sync_dec_text):
            checks["sync_decisions_copied_phrase"] = True

    # Maintenance checks
    if file_exists(maintenance_path):
        checks["maintenance_exists"] = True
        maint_text = read_text(maintenance_path) or ""
        has_weekly = re.search(r"(?i)\bweekly\b", maint_text) is not None
        has_monthly = re.search(r"(?i)\bmonthly\b", maint_text) is not None
        has_next = re.search(r"(?i)next\s+maintenance", maint_text) is not None and contains_date(maint_text)
        if has_weekly and has_monthly and has_next:
            checks["maintenance_has_sections_and_next_date"] = True

    # Health check tool
    if file_exists(health_check_script):
        checks["tools_health_check_exists"] = True
        output = run_health_check(health_check_script, cwd=workspace_root)
        if output and ("Total files:" in output):
            checks["tools_health_check_runs_and_reports_total"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # Enforce explicit no-op baseline: if output/memory is missing or empty of required artifacts, reward must be 0.0
    if not os.path.isdir(memory_root):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()