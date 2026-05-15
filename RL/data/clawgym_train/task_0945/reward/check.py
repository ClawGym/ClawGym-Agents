import json
import os
import sys
import glob
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def header_line_exact(lines, header):
    # exact case-sensitive header line: "## Header"
    pattern = rf'^\s*{re.escape(header)}\s*$'
    for ln in lines:
        if re.match(pattern, ln):
            return True
    return False

def header_md_ci(lines, header_text):
    # markdown header with case-insensitive match: lines starting with '#' and then header text (ci)
    for ln in lines:
        if ln.strip().startswith("#"):
            after = ln.lstrip("#").strip()
            if after.lower() == header_text.lower():
                return True
    return False

def validate_status_json(path):
    data = read_json(path)
    if not isinstance(data, dict):
        return False, False, 0, 0
    # required fields
    progress = data.get("progress")
    totalTasks = data.get("totalTasks")
    tasksCompleted = data.get("tasksCompleted")
    agents = data.get("agents")
    structure_ok = True
    if not (is_number(progress) and 0 <= progress <= 100):
        structure_ok = False
    if not (is_number(totalTasks) and totalTasks >= 0):
        structure_ok = False
    if not (is_number(tasksCompleted) and tasksCompleted >= 0):
        structure_ok = False
    if not isinstance(agents, list) or len(agents) == 0:
        structure_ok = False
    else:
        for a in agents:
            if not isinstance(a, dict):
                structure_ok = False
                break
            if not isinstance(a.get("id"), str) or not isinstance(a.get("name"), str):
                structure_ok = False
                break
            caps = a.get("capabilities")
            if not (isinstance(caps, list) or isinstance(caps, str)):
                structure_ok = False
                break
    progress_ok = False
    if structure_ok and progress is not None and progress >= 90:
        progress_ok = True
    # return also totals to compare with project file if needed
    tc = int(tasksCompleted) if is_number(tasksCompleted) else 0
    tt = int(totalTasks) if is_number(totalTasks) else 0
    return structure_ok, progress_ok, tt, tc

def find_valid_project_file(data_dir):
    # returns (path, json)
    candidates = glob.glob(os.path.join(data_dir, "*-project.json"))
    candidates.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    for p in candidates:
        j = read_json(p)
        if isinstance(j, dict):
            if isinstance(j.get("projectId"), str) and isinstance(j.get("goal"), str):
                if isinstance(j.get("taskTypes"), list) and isinstance(j.get("tasks"), list):
                    return p, j
    return None, None

def validate_project_json(proj_json):
    # basic structure
    ok_structure = True
    if not isinstance(proj_json, dict):
        return False, False, False, 0, 0
    if not (isinstance(proj_json.get("projectId"), str) and isinstance(proj_json.get("goal"), str)):
        ok_structure = False
    task_types = proj_json.get("taskTypes")
    tasks = proj_json.get("tasks")
    if not (isinstance(task_types, list) and isinstance(tasks, list)):
        ok_structure = False
    # required task types include planning, design, development
    types_include = False
    if isinstance(task_types, list):
        st = set([str(t).lower() for t in task_types])
        if {"planning", "design", "development"}.issubset(st):
            types_include = True
    # validate tasks have required fields and count completes
    complete_count = 0
    total_count = 0
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            has_id = "id" in t
            has_name = "name" in t
            has_type = "type" in t
            has_status = "status" in t
            if not (has_id and has_name and has_type and has_status):
                ok_structure = False
            else:
                total_count += 1
                if str(t.get("status")).lower() == "complete":
                    complete_count += 1
    at_least_one_complete = complete_count >= 1
    return ok_structure, types_include, at_least_one_complete, total_count, complete_count

def validate_agent_files(data_dir):
    mem_paths = glob.glob(os.path.join(data_dir, "agent-*-memory.json"))
    state_paths = glob.glob(os.path.join(data_dir, "agent-*-state.json"))
    valid_mem = 0
    for p in mem_paths:
        j = read_json(p)
        if not isinstance(j, dict):
            continue
        if not (isinstance(j.get("id"), str) and isinstance(j.get("name"), str)):
            continue
        caps = j.get("capabilities")
        if not isinstance(caps, list):
            continue
        tc = j.get("tasksCompleted")
        if not is_number(tc):
            continue
        valid_mem += 1
    valid_state = 0
    for p in state_paths:
        j = read_json(p)
        if not isinstance(j, dict):
            continue
        if not isinstance(j.get("agentId"), str):
            continue
        if not isinstance(j.get("status"), str):
            continue
        prog = j.get("progress")
        if not (is_number(prog) and 0 <= prog <= 100):
            continue
        valid_state += 1
    return (len(mem_paths) >= 3 and valid_mem >= 3), (len(state_paths) >= 3 and valid_state >= 3)

def validate_agent_md(file_path):
    txt = read_text(file_path)
    if txt is None:
        return False, False
    has_phrases = ("MUST BE USED" in txt) and ("Use PROACTIVELY" in txt)
    lines = txt.splitlines()
    needed_headers = [
        "## Your Role",
        "## Blocking Check",
        "## Input",
        "## Process",
        "## Output",
        "## Quality Checklist",
        "## Common Issues",
    ]
    headers_ok = all(header_line_exact(lines, h) for h in needed_headers)
    return has_phrases, headers_ok

def validate_agents_md(output_dir):
    agents_dir = os.path.join(output_dir, "agents")
    files = [
        os.path.join(agents_dir, "research.md"),
        os.path.join(agents_dir, "design.md"),
        os.path.join(agents_dir, "development.md"),
    ]
    all_exist = all(os.path.isfile(p) for p in files)
    if not all_exist:
        return False, False
    phrases_ok_all = True
    headers_ok_all = True
    for p in files:
        phrases_ok, headers_ok = validate_agent_md(p)
        if not phrases_ok:
            phrases_ok_all = False
        if not headers_ok:
            headers_ok_all = False
    return phrases_ok_all, headers_ok_all

def validate_sbom(path):
    j = read_json(path)
    if not isinstance(j, dict):
        return False
    if "bomFormat" in j and j.get("bomFormat") == "CycloneDX":
        return True
    if "spdxVersion" in j and isinstance(j.get("spdxVersion"), str):
        return True
    return False

def validate_compliance_report(path):
    txt = read_text(path)
    if txt is None:
        return False
    required_frameworks = [
        "OWASP LLM Top 10",
        "NIST AI RMF",
        "EU AI Act",
        "AISVS v1.0",
    ]
    # All frameworks must be present as plain substrings (case-sensitive per spec)
    frameworks_ok = all(fr in txt for fr in required_frameworks)
    # Must mention "policy" and "scan" (substring match)
    policy_scan_ok = ("policy" in txt.lower() and "scan" in txt.lower())
    # Include at least one of words "risk" or "classification"
    risk_ok = ("risk" in txt.lower() or "classification" in txt.lower())
    return frameworks_ok and policy_scan_ok and risk_ok

def validate_amazon_analysis(path):
    txt = read_text(path)
    if txt is None:
        return False, False
    lines = txt.splitlines()
    sections = {
        "Summary": header_md_ci(lines, "Summary"),
        "Specific Data": header_md_ci(lines, "Specific Data"),
        "Action Items": header_md_ci(lines, "Action Items"),
        "Next Steps": header_md_ci(lines, "Next Steps"),
    }
    headers_ok = all(sections.values())
    has_estimate_symbol = "⚠️" in txt
    return headers_ok, has_estimate_symbol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    data_dir = os.path.join(output_dir, "data")
    compliance_dir = os.path.join(output_dir, "compliance")
    analysis_dir = os.path.join(output_dir, "analysis")
    agents_dir = os.path.join(output_dir, "agents")

    checks = {
        "status_json_valid": False,
        "status_progress_ge_90": False,
        "project_file_exists_and_valid": False,
        "project_task_types_include_all": False,
        "project_has_completed_task": False,
        "project_near_completion_consistent": False,
        "agent_memory_files_valid_ge_3": False,
        "agent_state_files_valid_ge_3": False,
        "agent_prompts_have_triggers": False,
        "agent_prompts_have_required_headers": False,
        "sbom_valid": False,
        "compliance_report_valid": False,
        "amazon_headers_ok": False,
        "amazon_has_estimate_marker": False,
    }

    # 1) status.json
    status_path = os.path.join(output_dir, "status.json")
    status_tt = 0
    status_tc = 0
    if os.path.isfile(status_path):
        s_ok, s_prog_ok, status_tt, status_tc = validate_status_json(status_path)
        checks["status_json_valid"] = s_ok
        checks["status_progress_ge_90"] = s_prog_ok

    # 2) project file under output/data/*-project.json
    proj_path, proj_json = (None, None)
    if os.path.isdir(data_dir):
        proj_path, proj_json = find_valid_project_file(data_dir)
    if proj_json is not None:
        p_ok, types_include, have_complete, total_count, complete_count = validate_project_json(proj_json)
        checks["project_file_exists_and_valid"] = p_ok
        checks["project_task_types_include_all"] = types_include
        checks["project_has_completed_task"] = have_complete
        # Near-completion consistency: >= 90% complete if totals available, and match status.json counts if provided
        near_completion = False
        if total_count > 0:
            ratio = complete_count / float(total_count)
            if ratio >= 0.9:
                near_completion = True
        # Cross-check with status.json if it is valid
        if checks["status_json_valid"]:
            # If totalTasks > 0 in status, require consistency within tolerance
            if status_tt > 0 and total_count > 0:
                # allow small mismatches but require close alignment
                totals_align = abs(status_tt - total_count) <= 2
                completes_align = abs(status_tc - complete_count) <= 2
                near_completion = near_completion and totals_align and completes_align
        checks["project_near_completion_consistent"] = near_completion

    # 3) agent memory/state files
    if os.path.isdir(data_dir):
        mem_ok, state_ok = validate_agent_files(data_dir)
        checks["agent_memory_files_valid_ge_3"] = mem_ok
        checks["agent_state_files_valid_ge_3"] = state_ok

    # 4) agent instruction files
    if os.path.isdir(agents_dir):
        phrases_ok, headers_ok = validate_agents_md(output_dir)
        checks["agent_prompts_have_triggers"] = phrases_ok
        checks["agent_prompts_have_required_headers"] = headers_ok

    # 5) compliance deliverables
    sbom_path = os.path.join(compliance_dir, "sbom.json")
    if os.path.isfile(sbom_path):
        checks["sbom_valid"] = validate_sbom(sbom_path)
    report_path = os.path.join(compliance_dir, "report.md")
    if os.path.isfile(report_path):
        checks["compliance_report_valid"] = validate_compliance_report(report_path)

    # 6) Amazon analysis
    amazon_path = os.path.join(analysis_dir, "amazon-analysis.md")
    if os.path.isfile(amazon_path):
        headers_ok, has_est = validate_amazon_analysis(amazon_path)
        checks["amazon_headers_ok"] = headers_ok
        checks["amazon_has_estimate_marker"] = has_est

    # Compute reward as fraction of checks passed; no-op baseline yields 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()