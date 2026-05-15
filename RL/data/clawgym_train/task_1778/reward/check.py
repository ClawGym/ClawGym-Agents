import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def extract_headings(markdown_text):
    headings = []
    for line in markdown_text.splitlines():
        m = re.match(r'^\s*#{1,6}\s+(.+?)\s*$', line)
        if m:
            name = m.group(1).strip()
            if name:
                headings.append(name)
    return headings

def has_candidates_items_after_section(text, section_header, min_count=1):
    # Find section start
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            start_idx = i + 1
            break
    if start_idx is None:
        return False
    cnt = 0
    for i in range(start_idx, len(lines)):
        if lines[i].strip().startswith("## "):  # next section
            break
        if re.match(r'^\s*-\s+', lines[i]):
            cnt += 1
    return cnt >= min_count

def check_incident_blocks(text):
    # Blocks start with "## " line; within each, require the four lines
    lines = text.splitlines()
    blocks = []
    current = []
    for line in lines:
        if line.startswith("## "):
            if current:
                blocks.append(current)
            current = [line]
        else:
            if current is not None:
                current.append(line)
    if current:
        blocks.append(current)
    # Evaluate each block
    for blk in blocks:
        miss = any(l.strip().startswith("- Miss:") for l in blk)
        late = any(l.strip().startswith("Late catch:") for l in blk)
        better = any(l.strip().startswith("Better breakpoint:") for l in blk)
        promote = any(l.strip().startswith("Promote:") for l in blk)
        if miss and late and better and promote:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "memory_exists": False,
        "memory_has_sections": False,
        "memory_status_fields": False,
        "checkpoints_exists": False,
        "checkpoints_has_header": False,
        "checkpoints_confirmed_min3": False,
        "checkpoints_candidates_min1": False,
        "incidents_exists": False,
        "incidents_block_valid": False,
        "plan_exists": False,
        "plan_has_breakpoints_3": False,
        "plan_has_depth_line": False,
        "plan_references_2_phases": False,
        "steering_exists": False,
        "steering_mentions_quiet_inflection_outcome_critique": False,
    }

    # Paths
    mem_path = os.path.join(output_dir, "memory.md")
    chk_path = os.path.join(output_dir, "checkpoints.md")
    inc_path = os.path.join(output_dir, "incidents.md")
    plan_path = os.path.join(output_dir, "plan_with_breakpoints.md")
    steer_path = os.path.join(output_dir, "steering_snippets.md")
    project_plan_path = os.path.join(input_dir, "project_plan.md")

    # memory.md checks
    if os.path.isfile(mem_path):
        checks["memory_exists"] = True
        mem_text = read_text(mem_path)
        # Sections presence
        if ("Status" in mem_text) and ("Context" in mem_text) and ("Notes" in mem_text):
            checks["memory_has_sections"] = True
        # Status fields lines: starting with status:, version:, last:
        status_field_ok = False
        for line in mem_text.splitlines():
            # Accept lines that start with the required keys (leading spaces allowed)
            if re.match(r'^\s*status:\s*', line):
                s_ok = True
                break
        else:
            s_ok = False
        v_ok = any(re.match(r'^\s*version:\s*', l) for l in mem_text.splitlines())
        l_ok = any(re.match(r'^\s*last:\s*', l) for l in mem_text.splitlines())
        if s_ok and v_ok and l_ok:
            checks["memory_status_fields"] = True

    # checkpoints.md checks
    if os.path.isfile(chk_path):
        checks["checkpoints_exists"] = True
        chk_text = read_text(chk_path)
        if "# Checkpoints" in chk_text:
            checks["checkpoints_has_header"] = True
        # Confirmed lines counting
        confirmed_count = 0
        for line in chk_text.splitlines():
            # Must match pattern "- [" and contain specified tokens
            if ("- [" in line) and ("-> Trigger:" in line) and ("| Depth:" in line) and ("| Ask:" in line):
                confirmed_count += 1
        if confirmed_count >= 3:
            checks["checkpoints_confirmed_min3"] = True
        # Candidates section with at least 1 item "- "
        if has_candidates_items_after_section(chk_text, "## Candidates", min_count=1):
            checks["checkpoints_candidates_min1"] = True

    # incidents.md checks
    if os.path.isfile(inc_path):
        checks["incidents_exists"] = True
        inc_text = read_text(inc_path)
        if check_incident_blocks(inc_text):
            checks["incidents_block_valid"] = True

    # plan_with_breakpoints.md checks
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_text = read_text(plan_path)
        # at least 3 occurrences of "=== Breakpoint"
        if plan_text.count("=== Breakpoint") >= 3:
            checks["plan_has_breakpoints_3"] = True
        # at least one line containing "Depth:"
        if any("Depth:" in l for l in plan_text.splitlines()):
            checks["plan_has_depth_line"] = True
        # references at least two distinct phases from input/project_plan.md by name
        proj_text = read_text(project_plan_path)
        phase_names = extract_headings(proj_text)
        referenced = set()
        if phase_names:
            for name in phase_names:
                if name and name in plan_text:
                    referenced.add(name)
        if len(referenced) >= 2:
            checks["plan_references_2_phases"] = True

    # steering_snippets.md checks
    if os.path.isfile(steer_path):
        checks["steering_exists"] = True
        steer_text = read_text(steer_path).strip()
        if steer_text:
            # Must mention maintaining quiet, outcome-focused critique at inflection points.
            lower = steer_text.lower()
            if ("quiet" in lower) and ("inflection" in lower) and ("critique" in lower) and ("outcome" in lower):
                checks["steering_mentions_quiet_inflection_outcome_critique"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Baseline: if output dir missing or empty, or if none of the five required files exist, reward must be 0.0
    required_files = [mem_path, chk_path, inc_path, plan_path, steer_path]
    required_exist = [os.path.isfile(p) for p in required_files]
    if not any(required_exist):
        reward = 0.0

    # Print JSON as last line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()