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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_fact_line(line: str) -> str:
    s = line.strip()
    # remove a single leading bullet marker if present
    if s.startswith("- "):
        s = s[2:].strip()
    elif s.startswith("* "):
        s = s[2:].strip()
    return s

def contains_all_criteria(text: str, items):
    if text is None:
        return False
    for it in items or []:
        if it is None:
            return False
        if str(it) not in text:
            return False
    return True

def list_extra_md_files(root_dir, allowed_md_filenames):
    extras = []
    if not os.path.isdir(root_dir):
        return ["<workspace root missing>"]
    try:
        for name in os.listdir(root_dir):
            p = os.path.join(root_dir, name)
            if os.path.isfile(p) and name.lower().endswith(".md"):
                if name not in allowed_md_filenames:
                    extras.append(name)
    except Exception:
        return ["<error listing>"]
    return extras

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Load input/system.json for expectations
system_json_path = os.path.join(input_dir, "system.json")
system = read_json(system_json_path) or {}

# Extract expected fields with safe defaults
active_project = system.get("active_project", {}) if isinstance(system.get("active_project", {}), dict) else {}
project_name = active_project.get("name")
project_goal = active_project.get("goal")
success_criteria = active_project.get("success_criteria", [])
execution_tasks = active_project.get("execution_tasks", [])

automation = system.get("automation", {}) if isinstance(system.get("automation", {}), dict) else {}
heartbeat_window = automation.get("heartbeat_window")
reflect_time = automation.get("reflect_time")

daily_log_date = system.get("daily_log_date")
today_facts = system.get("today_facts", [])

notes = system.get("notes")
expected_risk_substring = None
expect_risk_prefix = "Risk:"
if isinstance(notes, dict):
    risk = notes.get("risk")
    if isinstance(risk, str) and risk.strip():
        expected_risk_substring = risk.strip()
elif isinstance(notes, str):
    # Try to extract after "Risk:" if present, else use full string
    s = notes.strip()
    if "Risk:" in s:
        # take the substring from "Risk:" to the end-of-line
        idx = s.find("Risk:")
        line = s[idx:].splitlines()[0].strip()
        # expected substring will be the part after "Risk:" if present, else full line
        if line.lower().startswith("risk:"):
            expected_risk_substring = line[len("Risk:"):].strip()
        else:
            expected_risk_substring = line
    else:
        expected_risk_substring = s

# Build expected paths
ws_root = os.path.join(output_dir, "workspace")
rescue_root = os.path.join(output_dir, "rescue")

# main root files
mem_path = os.path.join(ws_root, "MEMORY.md")
agents_path = os.path.join(ws_root, "AGENTS.md")
heartbeat_path = os.path.join(ws_root, "HEARTBEAT.md")
automation_path = os.path.join(ws_root, "AUTOMATION.md")

# memory files
daily_memory_path = os.path.join(ws_root, "memory", f"{daily_log_date}.md") if daily_log_date else None
topics_user_prefs_path = os.path.join(ws_root, "memory", "topics", "user-prefs.md")
topics_workflows_path = os.path.join(ws_root, "memory", "topics", "workflows.md")

# project files
index_path = os.path.join(ws_root, "projects", "INDEX.md")
project_dir = os.path.join(ws_root, "projects", project_name) if project_name else None
prd_path = os.path.join(project_dir, "PRD.md") if project_dir else None
exec_plan_path = os.path.join(project_dir, "EXECUTION_PLAN.md") if project_dir else None
progress_path = os.path.join(project_dir, "PROGRESS.md") if project_dir else None

# skills files
reflect_skill_path = os.path.join(ws_root, "skills", "reflect-mode", "SKILL.md")
scout_skill_path = os.path.join(ws_root, "skills", "scout-mode", "SKILL.md")
closer_skill_path = os.path.join(ws_root, "skills", "closer-mode", "SKILL.md")
ops_skill_path = os.path.join(ws_root, "skills", "ops-mode", "SKILL.md")

# rescue files
rescue_agents_path = os.path.join(rescue_root, "AGENTS.md")
rescue_memory_path = os.path.join(rescue_root, "MEMORY.md")

checks = {
    "workspace_memory_exists": False,
    "workspace_memory_arch_phrase": False,
    "workspace_memory_mentions_main_rescue": False,
    "workspace_memory_mentions_index": False,

    "workspace_agents_exists": False,
    "workspace_agents_describes_isolated": False,

    "workspace_heartbeat_exists": False,
    "workspace_heartbeat_contains_ok": False,
    "workspace_heartbeat_references_real_file": False,

    "workspace_automation_exists": False,
    "workspace_automation_has_heartbeat_window": False,
    "workspace_automation_has_reflect_time": False,
    "workspace_automation_refs_progress": False,
    "workspace_automation_refs_daily_memory": False,

    "workspace_daily_memory_exists": False,
    "workspace_daily_memory_contains_all_today_facts": False,

    "workspace_topics_user_prefs_exists": False,
    "workspace_topics_workflows_exists": False,
    "workspace_topics_workflows_promotion_line": False,

    "workspace_index_exists": False,
    "workspace_index_mentions_project_name": False,
    "workspace_index_points_prd": False,

    "workspace_prd_exists": False,
    "workspace_prd_has_goal": False,
    "workspace_prd_has_all_success_criteria": False,

    "workspace_exec_plan_exists": False,
    "workspace_exec_plan_has_all_tasks": False,

    "workspace_progress_exists": False,
    "workspace_progress_has_risk_line": False,

    "skill_reflect_exists": False,
    "skill_reflect_mentions_reflect_mode": False,
    "skill_reflect_reads_memory_and_progress": False,

    "skill_scout_exists": False,
    "skill_scout_heading": False,

    "skill_closer_exists": False,
    "skill_closer_heading": False,

    "skill_ops_exists": False,
    "skill_ops_heading": False,

    "rescue_agents_exists": False,
    "rescue_agents_emergency_not_second_main": False,
    "rescue_memory_exists": False,

    "no_extra_md_in_workspace_root": False,
}

# MEMORY.md checks
mem_text = read_text(mem_path)
if mem_text is not None:
    checks["workspace_memory_exists"] = True
    if "Architecture: Fire Dragon Fruit" in mem_text:
        checks["workspace_memory_arch_phrase"] = True
    low = mem_text.lower()
    if ("main" in low) and ("rescue" in low):
        checks["workspace_memory_mentions_main_rescue"] = True
    if "projects/INDEX.md" in mem_text or "projects/index.md" in mem_text:
        checks["workspace_memory_mentions_index"] = True

# AGENTS.md checks
agents_text = read_text(agents_path)
if agents_text is not None:
    checks["workspace_agents_exists"] = True
    low = agents_text.lower()
    # must mention main and rescue and a phrase indicating isolation / not mixed
    isolation_phrases = ["not be mixed", "do not share", "isolated", "must not be mixed", "memories must not be mixed"]
    isolation_ok = any(p in low for p in isolation_phrases)
    if ("main" in low and "rescue" in low and isolation_ok):
        checks["workspace_agents_describes_isolated"] = True

# HEARTBEAT.md checks
hb_text = read_text(heartbeat_path)
if hb_text is not None:
    checks["workspace_heartbeat_exists"] = True
    if "HEARTBEAT_OK" in hb_text:
        checks["workspace_heartbeat_contains_ok"] = True
    # references at least one real file path (progress or daily memory)
    ref_ok = False
    if project_name and progress_path:
        rel_progress_path = os.path.relpath(progress_path, ws_root).replace("\\", "/")
        if rel_progress_path in hb_text:
            ref_ok = True
    if daily_log_date and daily_memory_path:
        rel_daily_path = os.path.relpath(daily_memory_path, ws_root).replace("\\", "/")
        if rel_daily_path in hb_text:
            ref_ok = True
    checks["workspace_heartbeat_references_real_file"] = ref_ok

# AUTOMATION.md checks
auto_text = read_text(automation_path)
if auto_text is not None:
    checks["workspace_automation_exists"] = True
    if isinstance(heartbeat_window, str) and heartbeat_window in auto_text:
        checks["workspace_automation_has_heartbeat_window"] = True
    if isinstance(reflect_time, str) and reflect_time in auto_text:
        checks["workspace_automation_has_reflect_time"] = True
    # must reference both projects/<project>/PROGRESS.md and memory/<daily_log_date>.md
    if project_name and progress_path:
        rel_progress_path = os.path.relpath(progress_path, ws_root).replace("\\", "/")
        if rel_progress_path in auto_text:
            checks["workspace_automation_refs_progress"] = True
    if daily_log_date and daily_memory_path:
        rel_daily_path = os.path.relpath(daily_memory_path, ws_root).replace("\\", "/")
        if rel_daily_path in auto_text:
            checks["workspace_automation_refs_daily_memory"] = True

# Daily memory checks
daily_text = read_text(daily_memory_path) if daily_memory_path else None
if daily_text is not None:
    checks["workspace_daily_memory_exists"] = True
    # Ensure each today_fact appears as a separate line (allow leading bullet markers)
    lines = [normalize_fact_line(l) for l in daily_text.splitlines()]
    all_ok = True
    for fact in today_facts or []:
        if not any(normalize_fact_line(l) == fact for l in lines):
            all_ok = False
            break
    checks["workspace_daily_memory_contains_all_today_facts"] = all_ok

# Topics user prefs
if read_text(topics_user_prefs_path) is not None:
    checks["workspace_topics_user_prefs_exists"] = True

# Topics workflows
tw_text = read_text(topics_workflows_path)
if tw_text is not None:
    checks["workspace_topics_workflows_exists"] = True
    if "Promotion path: raw facts -> daily logs -> topic files -> MEMORY.md" in tw_text:
        checks["workspace_topics_workflows_promotion_line"] = True

# INDEX.md
index_text = read_text(index_path)
if index_text is not None:
    checks["workspace_index_exists"] = True
    if isinstance(project_name, str) and project_name in index_text:
        checks["workspace_index_mentions_project_name"] = True
    if project_name and prd_path:
        rel_prd_path = os.path.relpath(prd_path, ws_root).replace("\\", "/")
        if rel_prd_path in index_text:
            checks["workspace_index_points_prd"] = True

# PRD.md
prd_text = read_text(prd_path) if prd_path else None
if prd_text is not None:
    checks["workspace_prd_exists"] = True
    if isinstance(project_goal, str) and project_goal in prd_text:
        checks["workspace_prd_has_goal"] = True
    if contains_all_criteria(prd_text, success_criteria):
        checks["workspace_prd_has_all_success_criteria"] = True

# EXECUTION_PLAN.md
exec_text = read_text(exec_plan_path) if exec_plan_path else None
if exec_text is not None:
    checks["workspace_exec_plan_exists"] = True
    if contains_all_criteria(exec_text, execution_tasks):
        checks["workspace_exec_plan_has_all_tasks"] = True

# PROGRESS.md
progress_text = read_text(progress_path) if progress_path else None
if progress_text is not None:
    checks["workspace_progress_exists"] = True
    risk_ok = False
    if "Risk:" in (progress_text or ""):
        if expected_risk_substring:
            # require that progress contains the expected risk content too
            if expected_risk_substring in progress_text:
                risk_ok = True
        else:
            # At least contains a risk line
            risk_ok = True
    checks["workspace_progress_has_risk_line"] = risk_ok

# Skills - reflect
reflect_text = read_text(reflect_skill_path)
if reflect_text is not None:
    checks["skill_reflect_exists"] = True
    if "Reflect Mode" in reflect_text:
        checks["skill_reflect_mentions_reflect_mode"] = True
    # must reference both memory/YYYY-MM-DD.md and projects/*/PROGRESS.md (literal patterns)
    if ("memory/YYYY-MM-DD.md" in reflect_text) and ("projects/*/PROGRESS.md" in reflect_text):
        checks["skill_reflect_reads_memory_and_progress"] = True

# Skills - scout
scout_text = read_text(scout_skill_path)
if scout_text is not None:
    checks["skill_scout_exists"] = True
    if "Scout Mode" in scout_text:
        checks["skill_scout_heading"] = True

# Skills - closer
closer_text = read_text(closer_skill_path)
if closer_text is not None:
    checks["skill_closer_exists"] = True
    if "Closer Mode" in closer_text:
        checks["skill_closer_heading"] = True

# Skills - ops
ops_text = read_text(ops_skill_path)
if ops_text is not None:
    checks["skill_ops_exists"] = True
    if "Ops Mode" in ops_text:
        checks["skill_ops_heading"] = True

# Rescue checks
rescue_agents_text = read_text(rescue_agents_path)
if rescue_agents_text is not None:
    checks["rescue_agents_exists"] = True
    low = rescue_agents_text.lower()
    if ("emergency continuity" in low) and ("not a second main" in low):
        checks["rescue_agents_emergency_not_second_main"] = True

if read_text(rescue_memory_path) is not None:
    checks["rescue_memory_exists"] = True

# No extra .md in workspace root beyond required list
allowed_root_md = {"MEMORY.md", "AGENTS.md", "HEARTBEAT.md", "AUTOMATION.md"}
extras = list_extra_md_files(ws_root, allowed_root_md)
checks["no_extra_md_in_workspace_root"] = (len(extras) == 0)

# Compute reward as proportion of checks passed
total_checks = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = 0.0
if total_checks > 0:
    reward = passed / total_checks

# Ensure reward is within [0,1] float
try:
    reward = float(max(0.0, min(1.0, reward)))
except Exception:
    reward = 0.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))