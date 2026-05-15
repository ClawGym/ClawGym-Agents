import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def split_lines(text):
    return text.splitlines() if text is not None else []

def find_label_value(lines, label):
    # Matches "Label: value" (case-insensitive), returns value (stripped) or None
    pat = re.compile(r'^\s*' + re.escape(label) + r'\s*:\s*(.+?)\s*$', re.IGNORECASE)
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            return m.group(1).strip(), i
    return None, None

def find_heading_index(lines, label):
    # Matches markdown headings like "## Label", returns index or None
    pat = re.compile(r'^\s*#{1,6}\s*' + re.escape(label) + r'\s*$', re.IGNORECASE)
    for i, ln in enumerate(lines):
        if pat.match(ln):
            return i
    return None

def collect_bullets_from(lines, start_idx):
    # Collect contiguous bullet list lines starting after start_idx
    bullets = []
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j].rstrip()
        if not ln.strip():
            break
        if re.match(r'^\s*#{1,6}\s*\w', ln):  # next heading
            break
        # Allow -, * bullets; strip leading markers and spaces
        m = re.match(r'^\s*[-*]\s+(.*\S)\s*$', ln)
        if m:
            bullets.append(m.group(1).strip())
            continue
        # Stop if a non-bullet encountered
        if ln.strip():
            # tolerate numbered list like "1. item"
            m2 = re.match(r'^\s*\d+\.\s+(.*\S)\s*$', ln)
            if m2:
                bullets.append(m2.group(1).strip())
                continue
            break
    return bullets

def extract_section_text_after_heading(lines, label):
    # For headings like "## What", collect the first non-empty line as the value
    idx = find_heading_index(lines, label)
    if idx is None:
        return None
    for j in range(idx + 1, len(lines)):
        ln = lines[j].strip()
        if not ln:
            continue
        if re.match(r'^\s*#{1,6}\s*\w', ln):
            break
        return ln
    return None

def extract_bullets_by_label(lines, label):
    # Try "Label:" then bullets, else "## Label" heading then bullets
    _, idx = find_label_value(lines, label)
    bullets = []
    if idx is not None:
        bullets = collect_bullets_from(lines, idx)
        if bullets:
            return bullets
    idx2 = find_heading_index(lines, label)
    if idx2 is not None:
        bullets = collect_bullets_from(lines, idx2)
        if bullets:
            return bullets
    return []

def extract_value_by_label(lines, label):
    # Try "Label: value" inline, else "## Label" + first paragraph line
    val, _ = find_label_value(lines, label)
    if val:
        return val
    val2 = extract_section_text_after_heading(lines, label)
    return val2

def extract_next_action(lines):
    pat = re.compile(r'^\s*next action\s*:\s*(.+?)\s*$', re.IGNORECASE)
    for ln in lines:
        m = pat.match(ln)
        if m:
            return m.group(1).strip()
    # Try heading then first line
    idx = find_heading_index(lines, "Next Action")
    if idx is not None:
        for j in range(idx + 1, len(lines)):
            ln = lines[j].strip()
            if not ln:
                continue
            if re.match(r'^\s*#{1,6}\s*\w', ln):
                break
            return ln
    return None

def extract_tasks_with_tags(lines):
    # Return dict tag -> list of task texts (sans tag)
    tasks = {"planning": [], "build": [], "launch": []}
    # Pattern supports "- [ ] [planning] Task", "- [planning] Task", "[build] Task"
    patterns = [
        re.compile(r'^\s*[-*]\s*\[\s*\]\s*\[(planning|build|launch)\]\s*(.+?)\s*$', re.IGNORECASE),
        re.compile(r'^\s*[-*]\s*\[(planning|build|launch)\]\s*(.+?)\s*$', re.IGNORECASE),
        re.compile(r'^\s*\[(planning|build|launch)\]\s*(.+?)\s*$', re.IGNORECASE),
    ]
    for ln in lines:
        for pat in patterns:
            m = pat.match(ln)
            if m:
                tag = m.group(1).lower()
                text = m.group(2).strip()
                if text:
                    tasks[tag].append(text)
                break
    return tasks

def normalize_lines(lines):
    return [ln.rstrip("\n") for ln in lines]

def find_section_block(lines, heading_label):
    # Return the lines contained under a heading (exclusive) until next heading or EOF
    idx = find_heading_index(lines, heading_label)
    if idx is None:
        return []
    block = []
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if re.match(r'^\s*#{1,6}\s*\w', ln):
            break
        block.append(ln)
    return block

def checkbox_line_for(task_text):
    # Build regex that matches a checklist item with exact task text
    return re.compile(r'^\s*[-*]\s*\[\s\]\s*' + re.escape(task_text) + r'\s*$', re.IGNORECASE)

def has_checkbox_for(block_lines, task_text):
    rx = checkbox_line_for(task_text)
    for ln in block_lines:
        if rx.match(ln):
            return True
    return False

def parse_brief(brief_path):
    text = read_text(brief_path)
    if text is None:
        return None
    lines = split_lines(text)
    # Extract fields
    what = extract_value_by_label(lines, "What")
    why = extract_value_by_label(lines, "Why")
    deadline = None
    # Prefer exact YYYY-MM-DD after "Deadline:"
    val, _ = find_label_value(lines, "Deadline")
    if val:
        m = re.match(r'^\s*(\d{4}-\d{2}-\d{2})\s*$', val)
        if m:
            deadline = m.group(1)
    if not deadline:
        # search anywhere
        for ln in lines:
            m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', ln)
            if m and "deadline" in ln.lower():
                deadline = m.group(1)
                break
    ptype = extract_value_by_label(lines, "Type")
    # Contact line
    contact_line_val, _ = find_label_value(lines, "Contact")
    if not contact_line_val:
        contact_line_val, _ = find_label_value(lines, "Client Contact")
    if not contact_line_val:
        contact_line_val, _ = find_label_value(lines, "Point of Contact")
    # Deliverables bullets
    deliverables = extract_bullets_by_label(lines, "Deliverables")
    # Done Criteria bullets
    done_criteria = extract_bullets_by_label(lines, "Done Criteria")
    # Next Action
    next_action = extract_next_action(lines)
    # Tasks with tags
    tasks_by_tag = extract_tasks_with_tags(lines)
    return {
        "what": what,
        "why": why,
        "deadline": deadline,
        "type": ptype,
        "contact_line": contact_line_val.strip() if isinstance(contact_line_val, str) else None,
        "deliverables": deliverables,
        "done_criteria": done_criteria,
        "next_action": next_action,
        "tasks": tasks_by_tag,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir exists but not used for scoring
    # Build expected paths
    project_slug = "acmeco-website-cro-overhaul"
    base_dir = os.path.join(output_dir, "projects", project_slug)
    readme_path = os.path.join(base_dir, "README.md")
    tasks_path = os.path.join(base_dir, "tasks.md")
    notes_path = os.path.join(base_dir, "notes.md")
    comm_path = os.path.join(base_dir, "communication-log.md")
    delivs_path = os.path.join(base_dir, "deliverables.md")
    phase1_tasks = os.path.join(base_dir, "phase-1-planning", "tasks.md")
    phase1_notes = os.path.join(base_dir, "phase-1-planning", "notes.md")
    phase2_tasks = os.path.join(base_dir, "phase-2-build-test", "tasks.md")
    phase2_notes = os.path.join(base_dir, "phase-2-build-test", "notes.md")
    phase3_tasks = os.path.join(base_dir, "phase-3-launch", "tasks.md")
    phase3_notes = os.path.join(base_dir, "phase-3-launch", "notes.md")

    checks = {
        "dir_exists": False,
        "readme_exists": False,
        "tasks_exists": False,
        "notes_exists": False,
        "comm_log_exists": False,
        "deliverables_exists": False,
        "phase1_tasks_exists": False,
        "phase1_notes_exists": False,
        "phase2_tasks_exists": False,
        "phase2_notes_exists": False,
        "phase3_tasks_exists": False,
        "phase3_notes_exists": False,
        "readme_what": False,
        "readme_why": False,
        "readme_deadline": False,
        "readme_type": False,
        "readme_contact": False,
        "readme_done_criteria": False,
        "readme_deliverables": False,
        "tasks_next_action": False,
        "tasks_headings": False,
        "tasks_checkboxes": False,
        "root_tasks_all": False,
        "phase_planning_tasks": False,
        "phase_build_tasks": False,
        "phase_launch_tasks": False,
        "notes_headings": False,
        "comm_kickoff": False,
        "deliverables_checklist": False,
    }

    # Parse brief to compute expected values
    brief_path = os.path.join(input_dir, "project_brief.md")
    brief = parse_brief(brief_path)

    # Directory and file existence
    if os.path.isdir(base_dir):
        checks["dir_exists"] = True

    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
    if os.path.isfile(tasks_path):
        checks["tasks_exists"] = True
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
    if os.path.isfile(comm_path):
        checks["comm_log_exists"] = True
    if os.path.isfile(delivs_path):
        checks["deliverables_exists"] = True

    if os.path.isfile(phase1_tasks):
        checks["phase1_tasks_exists"] = True
    if os.path.isfile(phase1_notes):
        checks["phase1_notes_exists"] = True
    if os.path.isfile(phase2_tasks):
        checks["phase2_tasks_exists"] = True
    if os.path.isfile(phase2_notes):
        checks["phase2_notes_exists"] = True
    if os.path.isfile(phase3_tasks):
        checks["phase3_tasks_exists"] = True
    if os.path.isfile(phase3_notes):
        checks["phase3_notes_exists"] = True

    # If brief missing or couldn't parse essential fields, all content checks should remain False
    # Proceed only if brief is parsed
    if brief is not None:
        # README validation
        if checks["readme_exists"]:
            readme_text = read_text(readme_path) or ""
            readme_lines = split_lines(readme_text)

            # What
            what_line, _ = find_label_value(readme_lines, "What")
            if brief.get("what") and what_line is not None and what_line.strip() == brief["what"].strip():
                checks["readme_what"] = True

            # Why
            why_line, _ = find_label_value(readme_lines, "Why")
            if brief.get("why") and why_line is not None and why_line.strip() == brief["why"].strip():
                checks["readme_why"] = True

            # Deadline
            dl_line, _ = find_label_value(readme_lines, "Deadline")
            if brief.get("deadline") and dl_line is not None and dl_line.strip() == brief["deadline"].strip():
                checks["readme_deadline"] = True

            # Type: Client
            type_val, _ = find_label_value(readme_lines, "Type")
            if type_val is not None and type_val.strip() == "Client":
                checks["readme_type"] = True

            # Contact line exact
            contact_val, _ = find_label_value(readme_lines, "Contact")
            if brief.get("contact_line") and contact_val is not None and contact_val.strip() == brief["contact_line"].strip():
                checks["readme_contact"] = True

            # Done Criteria bullets: compare sets exactly
            readme_done = extract_bullets_by_label(readme_lines, "Done Criteria")
            expected_done = [d.strip() for d in (brief.get("done_criteria") or []) if d and d.strip()]
            if expected_done and readme_done:
                if set(readme_done) == set(expected_done) and len(readme_done) == len(expected_done):
                    checks["readme_done_criteria"] = True

            # Deliverables bullets: compare sets exactly
            readme_delivs = extract_bullets_by_label(readme_lines, "Deliverables")
            expected_delivs = [d.strip() for d in (brief.get("deliverables") or []) if d and d.strip()]
            if expected_delivs and readme_delivs:
                if set(readme_delivs) == set(expected_delivs) and len(readme_delivs) == len(expected_delivs):
                    checks["readme_deliverables"] = True

        # Root tasks.md validation
        if checks["tasks_exists"]:
            t_text = read_text(tasks_path) or ""
            t_lines = [ln for ln in split_lines(t_text)]
            # First non-empty line NEXT ACTION
            first_non_empty = None
            for ln in t_lines:
                if ln.strip():
                    first_non_empty = ln.strip()
                    break
            na = brief.get("next_action")
            if first_non_empty and na:
                m = re.match(r'^NEXT ACTION:\s*(.+)\s*$', first_non_empty)
                if m and m.group(1) == na:
                    checks["tasks_next_action"] = True

            # Headings for Planning, Build & Test, Launch
            plan_idx = find_heading_index(t_lines, "Planning")
            build_idx = find_heading_index(t_lines, "Build & Test")
            launch_idx = find_heading_index(t_lines, "Launch")
            if plan_idx is not None and build_idx is not None and launch_idx is not None:
                checks["tasks_headings"] = True

            # Check presence of checkboxes in each section
            plan_block = find_section_block(t_lines, "Planning")
            build_block = find_section_block(t_lines, "Build & Test")
            launch_block = find_section_block(t_lines, "Launch")
            has_cb = any(re.match(r'^\s*[-*]\s*\[\s\]\s+.+', ln) for ln in plan_block) and \
                     any(re.match(r'^\s*[-*]\s*\[\s\]\s+.+', ln) for ln in build_block) and \
                     any(re.match(r'^\s*[-*]\s*\[\s\]\s+.+', ln) for ln in launch_block)
            if has_cb:
                checks["tasks_checkboxes"] = True

            # All tasks present under correct headings
            tasks_ok = True
            exp_plan = brief.get("tasks", {}).get("planning", []) if brief.get("tasks") else []
            exp_build = brief.get("tasks", {}).get("build", []) if brief.get("tasks") else []
            exp_launch = brief.get("tasks", {}).get("launch", []) if brief.get("tasks") else []

            for txt in exp_plan:
                if not has_checkbox_for(plan_block, txt):
                    tasks_ok = False
                    break
            if tasks_ok:
                for txt in exp_build:
                    if not has_checkbox_for(build_block, txt):
                        tasks_ok = False
                        break
            if tasks_ok:
                for txt in exp_launch:
                    if not has_checkbox_for(launch_block, txt):
                        tasks_ok = False
                        break
            if tasks_ok and (exp_plan or exp_build or exp_launch):
                checks["root_tasks_all"] = True

        # Phase tasks distribution
        # Planning
        if checks["phase1_tasks_exists"]:
            p1_text = read_text(phase1_tasks) or ""
            p1_lines = split_lines(p1_text)
            exp_plan = brief.get("tasks", {}).get("planning", []) if brief.get("tasks") else []
            if exp_plan:
                all_present = True
                for t in exp_plan:
                    found = False
                    rx = checkbox_line_for(t)
                    for ln in p1_lines:
                        if rx.match(ln):
                            found = True
                            break
                    if not found:
                        all_present = False
                        break
                if all_present:
                    checks["phase_planning_tasks"] = True

        # Build & Test
        if checks["phase2_tasks_exists"]:
            p2_text = read_text(phase2_tasks) or ""
            p2_lines = split_lines(p2_text)
            exp_build = brief.get("tasks", {}).get("build", []) if brief.get("tasks") else []
            if exp_build:
                all_present = True
                for t in exp_build:
                    found = False
                    rx = checkbox_line_for(t)
                    for ln in p2_lines:
                        if rx.match(ln):
                            found = True
                            break
                    if not found:
                        all_present = False
                        break
                if all_present:
                    checks["phase_build_tasks"] = True

        # Launch
        if checks["phase3_tasks_exists"]:
            p3_text = read_text(phase3_tasks) or ""
            p3_lines = split_lines(p3_text)
            exp_launch = brief.get("tasks", {}).get("launch", []) if brief.get("tasks") else []
            if exp_launch:
                all_present = True
                for t in exp_launch:
                    found = False
                    rx = checkbox_line_for(t)
                    for ln in p3_lines:
                        if rx.match(ln):
                            found = True
                            break
                    if not found:
                        all_present = False
                        break
                if all_present:
                    checks["phase_launch_tasks"] = True

        # Root notes.md headings
        if checks["notes_exists"]:
            n_text = read_text(notes_path) or ""
            has_decisions = re.search(r'^\s*##\s*Decisions\s*$', n_text, re.IGNORECASE | re.MULTILINE) is not None
            has_research = re.search(r'^\s*##\s*Research\s*$', n_text, re.IGNORECASE | re.MULTILINE) is not None
            if has_decisions and has_research:
                checks["notes_headings"] = True

        # Communication log kickoff
        if checks["comm_log_exists"]:
            c_text = read_text(comm_path) or ""
            if c_text and re.search(r'kickoff', c_text, re.IGNORECASE):
                checks["comm_kickoff"] = True

        # Deliverables checklist file
        if checks["deliverables_exists"]:
            d_text = read_text(delivs_path) or ""
            expected_delivs = [d.strip() for d in (brief.get("deliverables") or []) if d and d.strip()]
            if expected_delivs:
                ok = True
                for d in expected_delivs:
                    rx = re.compile(r'^\s*[-*]\s*\[\s\]\s*' + re.escape(d) + r'\s*$', re.MULTILINE)
                    if not rx.search(d_text or ""):
                        ok = False
                        break
                # Ensure number of checklist items equals expected
                # Count unchecked items
                found_items = re.findall(r'^\s*[-*]\s*\[\s\]\s*(.+?)\s*$', d_text or "", re.MULTILINE)
                if ok and len(found_items) == len(expected_delivs):
                    checks["deliverables_checklist"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # Ensure no-op baseline: if no output dir or no files, reward stays 0.0
    if passed > 0:
        reward = round(passed / total, 6)

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()