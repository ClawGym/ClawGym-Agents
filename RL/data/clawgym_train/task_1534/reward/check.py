import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def split_frontmatter(content):
    lines = content.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "---":
        # find closing ---
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                front = "\n".join(lines[1:i])
                body = "\n".join(lines[i+1:])
                return front, body
    return "", content

def parse_frontmatter(front):
    name = None
    description = None
    metadata_obj = None
    for line in front.splitlines():
        # Simple YAML key: value detection
        if re.match(r'^\s*name\s*:', line):
            val = line.split(":", 1)[1].strip()
            name = val.strip().strip('"').strip("'")
        elif re.match(r'^\s*description\s*:', line):
            val = line.split(":", 1)[1].strip()
            description = val.strip().strip('"').strip("'")
        elif re.match(r'^\s*metadata\s*:', line):
            val = line.split(":", 1)[1].strip()
            # Expect inline JSON
            if val:
                try:
                    metadata_obj = json.loads(val)
                except Exception:
                    metadata_obj = None
    return name, description, metadata_obj

def find_table_in_markdown(body):
    # Look for any markdown table heuristic: a line with '|' followed by a separator line with '-' and '|'
    lines = body.splitlines()
    for idx in range(len(lines) - 1):
        l1 = lines[idx]
        l2 = lines[idx + 1]
        if '|' in l1 and '|' in l2 and '-' in l2:
            return True
    # Fallback: any single line with '|' might indicate table
    for l in lines:
        if '|' in l:
            return True
    return False

def has_numbered_h3(body):
    # check for "### 1." or similar
    return re.search(r'(?m)^\s*###\s*\d+\.', body) is not None

def count_examples_rows(body):
    # Find "## Examples" and count '|' lines after it
    lines = body.splitlines()
    idx = None
    for i, l in enumerate(lines):
        if l.strip().lower().startswith("## examples"):
            idx = i
            break
    if idx is None:
        return 0
    count = 0
    for l in lines[idx+1:]:
        if "|" in l:
            count += 1
    return count

def extract_references_paths(body):
    # Extract paths like {baseDir}/references/anything.ext
    # Allow letters, numbers, underscores, hyphens, dots, slashes
    pattern = re.compile(r'\{baseDir\}/references/([A-Za-z0-9._\-/]+)')
    return pattern.findall(body)

def normalize_and_check_within(base_dir, path):
    abs_path = os.path.normpath(os.path.join(base_dir, path))
    # Ensure abs_path is within base_dir
    try:
        return abs_path.startswith(os.path.abspath(base_dir) + os.sep), abs_path
    except Exception:
        return False, abs_path

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    skill_dir = os.path.join(output_dir, "skills", "kanban-notes")
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    readme_path = os.path.join(skill_dir, "README.md")
    references_dir = os.path.join(skill_dir, "references")

    quality_dir = os.path.join(output_dir, "quality")
    checklist_path = os.path.join(quality_dir, "kanban-notes_checklist.json")
    rubric_path = os.path.join(quality_dir, "kanban-notes_rubric.md")

    checks = {
        "skill_dir_exists": False,
        "skill_md_exists": False,
        "readme_exists": False,
        "quality_checklist_exists": False,
        "rubric_exists": False,

        "fm_name_matches": False,
        "fm_description_has_use_when": False,
        "fm_metadata_has_jq": False,

        "body_has_workflow_section": False,
        "body_has_numbered_steps": False,
        "body_has_exec_block": False,
        "body_has_table": False,
        "body_uses_baseDir": False,
        "body_has_error_handling": False,
        "body_has_confirmation_step": False,
        "examples_section_present": False,
        "examples_count_at_least_3": False,
        "skill_md_under_500_lines": False,
        "no_dead_references": False,

        "readme_has_install_command": False,
        "readme_has_usage_section": False,
        "readme_mentions_jq": False,

        "checklist_valid_json": False,
        "checklist_required_bools_all_true": False,
        "rubric_has_required_headings": False,
    }

    # Structure presence
    if os.path.isdir(skill_dir):
        checks["skill_dir_exists"] = True
    if os.path.isfile(skill_md_path):
        checks["skill_md_exists"] = True
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
    if os.path.isfile(checklist_path):
        checks["quality_checklist_exists"] = True
    if os.path.isfile(rubric_path):
        checks["rubric_exists"] = True

    # SKILL.md content checks
    if checks["skill_md_exists"]:
        content = read_text(skill_md_path) or ""
        line_count = len(content.splitlines())
        if line_count < 500:
            checks["skill_md_under_500_lines"] = True

        front, body = split_frontmatter(content)
        name, description, metadata_obj = parse_frontmatter(front)

        if name == "kanban-notes":
            checks["fm_name_matches"] = True
        if description and ("use when" in description.lower()):
            checks["fm_description_has_use_when"] = True

        # Metadata jq in requires.bins
        if isinstance(metadata_obj, dict):
            try:
                bins = metadata_obj.get("openclaw", {}).get("requires", {}).get("bins", [])
                if isinstance(bins, list) and "jq" in bins:
                    checks["fm_metadata_has_jq"] = True
            except Exception:
                pass

        body_lower = body.lower()
        if "## Workflow" in body or "## workflow" in body_lower:
            checks["body_has_workflow_section"] = True
        if has_numbered_h3(body):
            checks["body_has_numbered_steps"] = True
        if ('"tool": "exec"' in body) and ('"command":' in body):
            checks["body_has_exec_block"] = True
        if "{baseDir}" in body:
            checks["body_uses_baseDir"] = True
        if "error handling" in body_lower:
            checks["body_has_error_handling"] = True
        # Confirmation step: look for confirm + before writing/changing
        if ("confirm" in body_lower) and (("before writing" in body_lower) or ("before changing" in body_lower)):
            checks["body_has_confirmation_step"] = True
        # Table detection
        if find_table_in_markdown(body):
            checks["body_has_table"] = True
        # Examples section and rows
        if "## examples" in body_lower:
            checks["examples_section_present"] = True
            rows = count_examples_rows(body)
            if rows >= 4:
                checks["examples_count_at_least_3"] = True
        # Dead references check
        refs = extract_references_paths(body)
        if refs:
            all_exist = True
            for rel in refs:
                ok_within, abs_path = normalize_and_check_within(references_dir, rel)
                if (not ok_within) or (not os.path.isfile(abs_path)):
                    all_exist = False
                    break
            checks["no_dead_references"] = all_exist
        else:
            # If no references are cited, then trivially no dead references
            checks["no_dead_references"] = True

    # README checks
    if checks["readme_exists"]:
        readme = read_text(readme_path) or ""
        readme_lower = readme.lower()
        if "clawhub install kanban-notes" in readme:
            checks["readme_has_install_command"] = True
        if "## usage" in readme_lower:
            checks["readme_has_usage_section"] = True
        if "jq" in readme_lower:
            checks["readme_mentions_jq"] = True

    # Checklist JSON checks
    checklist_required_keys = [
        "name_matches",
        "description_has_use_when",
        "metadata_has_jq",
        "has_workflow_section",
        "has_numbered_steps",
        "has_exec_block",
        "uses_baseDir",
        "has_table",
        "examples_count_at_least_3",
        "error_handling_present",
        "confirmation_step_present",
        "readme_has_install_command",
        "under_500_lines",
        "no_dead_references",
    ]
    checklist_json_obj = None
    if checks["quality_checklist_exists"]:
        raw = read_text(checklist_path)
        if raw is not None:
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    checklist_json_obj = obj
                    checks["checklist_valid_json"] = True
            except Exception:
                checklist_json_obj = None

    if checks["checklist_valid_json"] and isinstance(checklist_json_obj, dict):
        all_true = True
        for key in checklist_required_keys:
            val = checklist_json_obj.get(key, None)
            if not isinstance(val, bool) or not val:
                all_true = False
                break
        checks["checklist_required_bools_all_true"] = all_true

    # Rubric headings presence
    if checks["rubric_exists"]:
        rubric = read_text(rubric_path) or ""
        required_headings = [
            "Intent Alignment",
            "Imperative Workflow",
            "Examples Realism",
            "Error Handling Quality",
            "Confirmation Safety",
        ]
        has_all = all(h in rubric for h in required_headings)
        checks["rubric_has_required_headings"] = has_all

    # Compute reward: average of all checks
    bool_values = list(checks.values())
    total = len(bool_values)
    passed = sum(1 for v in bool_values if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output is missing or empty, reward must be 0.0
    output_exists = os.path.isdir(os.path.join(workspace_root, "output"))
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()