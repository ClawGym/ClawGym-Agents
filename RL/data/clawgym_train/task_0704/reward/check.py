import csv
import json
import os
import re
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_frontmatter_and_body(md_text: str) -> Tuple[Optional[str], Optional[str]]:
    # Expect frontmatter delimited by ---
    lines = md_text.splitlines()
    if len(lines) < 3:
        return None, None
    if lines[0].strip() != "---":
        return None, None
    # find closing ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, None
    fm = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx+1:]) if end_idx + 1 < len(lines) else ""
    return fm, body

def parse_yaml_frontmatter(fm: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for simple key: value and list values.
    Supports:
      key: value
      key: "value" or 'value'
      key: [a, b, c]
      key:
        - a
        - b
        - c
    Scalars are parsed as strings; integers recognized if purely digits.
    """
    result: Dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    key_re = re.compile(r'^([A-Za-z0-9_\-]+)\s*:\s*(.*)$')
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = key_re.match(line)
        if not m:
            i += 1
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        # If val is empty, maybe a block list or empty string
        if val == "":
            # Look ahead for list items
            j = i + 1
            items: List[str] = []
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip().startswith("- "):
                    item = nxt.split("- ", 1)[1].strip()
                    item = strip_quotes(item)
                    items.append(item)
                    j += 1
                else:
                    # If encounters another top-level key or an empty/indented line not a list
                    nm = key_re.match(nxt)
                    if nm:
                        break
                    # Skip blank lines within block
                    if not nxt.strip():
                        j += 1
                        continue
                    # Unknown content, break to avoid infinite loop
                    break
            if items:
                result[key] = items
                i = j
                continue
            else:
                # Empty string value
                result[key] = ""
                i += 1
                continue
        # Inline list?
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if inner == "":
                result[key] = []
            else:
                parts = [strip_quotes(p.strip()) for p in inner.split(",")]
                result[key] = [p for p in parts if p != ""]
            i += 1
            continue
        # Scalar
        sval = strip_quotes(val)
        # Try int conversion for numeric fields like current_step if appropriate
        if sval.isdigit():
            try:
                ival = int(sval)
                result[key] = ival
            except Exception:
                result[key] = sval
        else:
            result[key] = sval
        i += 1
    return result

def strip_quotes(s: str) -> str:
    if (len(s) >= 2) and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s

def find_section(body: str, heading: str) -> Tuple[bool, str]:
    """
    Find section starting with a line that starts with '## <heading>'
    Return (found, section_text) where section_text is content until next '## ' or end.
    """
    lines = body.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("## ") and line.strip()[3:].strip().lower() == heading.lower():
            start_idx = idx
            break
    if start_idx is None:
        return False, ""
    # Find next heading
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().lower().startswith("## "):
            end_idx = j
            break
    section = "\n".join(lines[start_idx + 1:end_idx])
    return True, section

def count_numbered_checkboxes(section_text: str) -> int:
    count = 0
    for line in section_text.splitlines():
        if re.match(r'^\s*\d+\.\s*\[\s*\]\s+.+', line):
            count += 1
    return count

def has_observation_key(section_text: str, key: str) -> bool:
    # Look for a bullet line containing e.g., - [description]
    pattern = r'^\s*-\s*\[' + re.escape(key) + r'\]'
    for line in section_text.splitlines():
        if re.search(pattern, line):
            return True
    return False

def valid_date_yyyy_mm_dd(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    return re.match(r'^\d{4}-\d{2}-\d{2}$', s) is not None

def load_csv_rows(path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Normalize keys and strip whitespace
                row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                # Expect columns: slug,title,assignee,priority
                rows.append(row)
    except Exception:
        return []
    return rows

def load_json_file(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def check_parent(parent_path: str) -> Dict[str, bool]:
    checks: Dict[str, bool] = {
        "parent_exists": False,
        "parent_frontmatter_type_task": False,
        "parent_frontmatter_title_contains": False,
        "parent_frontmatter_description_nonempty": False,
        "parent_frontmatter_status_active": False,
        "parent_frontmatter_priority_present": False,
        "parent_frontmatter_steps_len_ge3": False,
        "parent_frontmatter_current_step_1": False,
        "parent_frontmatter_started_date_valid": False,
        "parent_body_has_observations_heading": False,
        "parent_body_observations_has_description_key": False,
        "parent_body_observations_has_status_key": False,
        "parent_body_observations_has_assigned_to_key": False,
        "parent_body_observations_has_current_step_key": False,
        "parent_body_has_steps_heading": False,
        "parent_body_steps_has_3_checkboxes": False,
        "parent_body_has_context_heading": False,
        "parent_context_mentions_brief_and_context": False,
    }
    text = read_text(parent_path)
    if text is None:
        return checks
    checks["parent_exists"] = True
    fm_text, body = extract_frontmatter_and_body(text)
    if fm_text is None or body is None:
        return checks
    fm = parse_yaml_frontmatter(fm_text)
    # Frontmatter checks
    if str(fm.get("type", "")).strip().lower() == "task":
        checks["parent_frontmatter_type_task"] = True
    title_val = str(fm.get("title", ""))
    if "Q2 Onboarding Revamp" in title_val:
        checks["parent_frontmatter_title_contains"] = True
    desc_val = str(fm.get("description", ""))
    if isinstance(desc_val, str) and desc_val.strip() != "":
        checks["parent_frontmatter_description_nonempty"] = True
    if str(fm.get("status", "")).strip().lower() == "active":
        checks["parent_frontmatter_status_active"] = True
    if "priority" in fm and str(fm.get("priority", "")).strip() != "":
        checks["parent_frontmatter_priority_present"] = True
    steps = fm.get("steps")
    if isinstance(steps, list) and len(steps) >= 3:
        checks["parent_frontmatter_steps_len_ge3"] = True
    if fm.get("current_step") == 1:
        checks["parent_frontmatter_current_step_1"] = True
    if valid_date_yyyy_mm_dd(fm.get("started")):
        checks["parent_frontmatter_started_date_valid"] = True
    # Body sections
    obs_found, obs_section = find_section(body, "Observations")
    if obs_found:
        checks["parent_body_has_observations_heading"] = True
        if has_observation_key(obs_section, "description"):
            checks["parent_body_observations_has_description_key"] = True
        if has_observation_key(obs_section, "status"):
            checks["parent_body_observations_has_status_key"] = True
        if has_observation_key(obs_section, "assigned_to"):
            checks["parent_body_observations_has_assigned_to_key"] = True
        if has_observation_key(obs_section, "current_step"):
            checks["parent_body_observations_has_current_step_key"] = True
    steps_found, steps_section = find_section(body, "Steps")
    if steps_found:
        checks["parent_body_has_steps_heading"] = True
        if count_numbered_checkboxes(steps_section) >= 3:
            checks["parent_body_steps_has_3_checkboxes"] = True
    ctx_found, ctx_section = find_section(body, "Context")
    if ctx_found:
        checks["parent_body_has_context_heading"] = True
        ctx_text = ctx_section
        if ("input/brief.md" in ctx_text) and ("input/context.md" in ctx_text):
            checks["parent_context_mentions_brief_and_context"] = True
    return checks

def check_children(tasks_csv_path: str, tasks_dir: str) -> Dict[str, bool]:
    checks: Dict[str, bool] = {
        "children_all_exist": False,
        "children_frontmatter_type_task_all": False,
        "children_title_match_csv_all": False,
        "children_assigned_to_match_csv_all": False,
        "children_priority_match_csv_all": False,
        "children_status_active_all": False,
        "children_parent_task_correct_all": False,
        "children_steps_len_ge3_all": False,
        "children_current_step_1_all": False,
        "children_description_nonempty_all": False,
        "children_started_date_valid_all": False,
        "children_body_has_observations_heading_all": False,
        "children_observations_have_required_keys_all": False,
        "children_body_has_steps_heading_all": False,
        "children_body_steps_has_3_checkboxes_all": False,
        "children_body_has_context_heading_all": False,
        "children_context_mentions_input_path_all": False,
    }
    rows = load_csv_rows(tasks_csv_path)
    if len(rows) == 0:
        # Avoid vacuous pass conditions: keep all False
        return checks
    exists_all = True
    type_all = True
    title_all = True
    assign_all = True
    priority_all = True
    status_all = True
    parent_all = True
    stepslen_all = True
    curstep_all = True
    desc_all = True
    started_all = True
    obs_heading_all = True
    obs_keys_all = True
    steps_heading_all = True
    steps_boxes_all = True
    ctx_heading_all = True
    ctx_path_all = True

    for r in rows:
        slug = str(r.get("slug", "")).strip()
        title = str(r.get("title", "")).strip()
        assignee = str(r.get("assignee", "")).strip()
        priority_val = str(r.get("priority", "")).strip()
        child_path = os.path.join(tasks_dir, f"{slug}.md")
        text = read_text(child_path)
        if text is None:
            exists_all = False
            # If missing, all dependent checks for this child should fail
            type_all = False
            title_all = False
            assign_all = False
            priority_all = False
            status_all = False
            parent_all = False
            stepslen_all = False
            curstep_all = False
            desc_all = False
            started_all = False
            obs_heading_all = False
            obs_keys_all = False
            steps_heading_all = False
            steps_boxes_all = False
            ctx_heading_all = False
            ctx_path_all = False
            continue
        # It exists
        fm_text, body = extract_frontmatter_and_body(text)
        if fm_text is None or body is None:
            # Fail all checks for malformed note
            type_all = False
            title_all = False
            assign_all = False
            priority_all = False
            status_all = False
            parent_all = False
            stepslen_all = False
            curstep_all = False
            desc_all = False
            started_all = False
            obs_heading_all = False
            obs_keys_all = False
            steps_heading_all = False
            steps_boxes_all = False
            ctx_heading_all = False
            ctx_path_all = False
            continue
        fm = parse_yaml_frontmatter(fm_text)
        # Frontmatter validations
        if not (str(fm.get("type", "")).strip().lower() == "task"):
            type_all = False
        if not (str(fm.get("title", "")).strip() == title):
            title_all = False
        if not (str(fm.get("assigned_to", "")).strip() == assignee):
            assign_all = False
        if not (str(fm.get("priority", "")).strip() == priority_val):
            priority_all = False
        if not (str(fm.get("status", "")).strip().lower() == "active"):
            status_all = False
        if not (str(fm.get("parent_task", "")).strip() == "Q2 Onboarding Revamp"):
            parent_all = False
        steps = fm.get("steps")
        if not (isinstance(steps, list) and len(steps) >= 3):
            stepslen_all = False
        if not (fm.get("current_step") == 1):
            curstep_all = False
        desc_field = fm.get("description", "")
        if not (isinstance(desc_field, str) and desc_field.strip() != ""):
            desc_all = False
        if not valid_date_yyyy_mm_dd(fm.get("started")):
            started_all = False
        # Body sections
        obs_found, obs_section = find_section(body, "Observations")
        if not obs_found:
            obs_heading_all = False
            obs_keys_all = False
        else:
            keys_present = (
                has_observation_key(obs_section, "description")
                and has_observation_key(obs_section, "status")
                and has_observation_key(obs_section, "assigned_to")
                and has_observation_key(obs_section, "current_step")
            )
            if not keys_present:
                obs_keys_all = False
        steps_found, steps_section = find_section(body, "Steps")
        if not steps_found:
            steps_heading_all = False
            steps_boxes_all = False
        else:
            if count_numbered_checkboxes(steps_section) < 3:
                steps_boxes_all = False
        ctx_found, ctx_section = find_section(body, "Context")
        if not ctx_found:
            ctx_heading_all = False
            ctx_path_all = False
        else:
            ctx_text = ctx_section
            # At least one of input/brief.md or input/context.md
            if not (("input/brief.md" in ctx_text) or ("input/context.md" in ctx_text)):
                ctx_path_all = False

    checks["children_all_exist"] = exists_all
    checks["children_frontmatter_type_task_all"] = type_all and exists_all
    checks["children_title_match_csv_all"] = title_all and exists_all
    checks["children_assigned_to_match_csv_all"] = assign_all and exists_all
    checks["children_priority_match_csv_all"] = priority_all and exists_all
    checks["children_status_active_all"] = status_all and exists_all
    checks["children_parent_task_correct_all"] = parent_all and exists_all
    checks["children_steps_len_ge3_all"] = stepslen_all and exists_all
    checks["children_current_step_1_all"] = curstep_all and exists_all
    checks["children_description_nonempty_all"] = desc_all and exists_all
    checks["children_started_date_valid_all"] = started_all and exists_all
    checks["children_body_has_observations_heading_all"] = obs_heading_all and exists_all
    checks["children_observations_have_required_keys_all"] = obs_keys_all and exists_all
    checks["children_body_has_steps_heading_all"] = steps_heading_all and exists_all
    checks["children_body_steps_has_3_checkboxes_all"] = steps_boxes_all and exists_all
    checks["children_body_has_context_heading_all"] = ctx_heading_all and exists_all
    checks["children_context_mentions_input_path_all"] = ctx_path_all and exists_all
    return checks

def check_index(index_path: str, rows: List[Dict[str, str]]) -> Dict[str, bool]:
    checks: Dict[str, bool] = {
        "index_exists": False,
        "index_valid_json": False,
        "index_initiative_correct": False,
        "index_tasks_length_matches_csv": False,
        "index_tasks_match_csv_fields": False,
        "index_tasks_status_active_all": False,
    }
    data = load_json_file(index_path)
    if data is None:
        return checks
    checks["index_exists"] = True
    # Must be dict with keys 'initiative' and 'tasks'
    if isinstance(data, dict) and "initiative" in data and "tasks" in data and isinstance(data.get("tasks"), list):
        checks["index_valid_json"] = True
        if data.get("initiative") == "Q2 Onboarding Revamp":
            checks["index_initiative_correct"] = True
        # tasks length equals rows length (avoid vacuous passes if rows empty)
        if len(rows) > 0 and len(data.get("tasks", [])) == len(rows):
            checks["index_tasks_length_matches_csv"] = True
        elif len(rows) == 0:
            # If no csv rows, do not allow vacuous pass
            checks["index_tasks_length_matches_csv"] = False
        # Match fields per row
        tasks_ok = True
        status_all_active = True
        # Build map from slug to object (assume unique slugs)
        idx_by_slug = {}
        for t in data.get("tasks", []):
            if isinstance(t, dict) and "slug" in t:
                idx_by_slug[str(t.get("slug"))] = t
        for r in rows:
            slug = str(r.get("slug", "")).strip()
            title = str(r.get("title", "")).strip()
            assignee = str(r.get("assignee", "")).strip()
            priority_val = str(r.get("priority", "")).strip()
            obj = idx_by_slug.get(slug)
            if obj is None:
                tasks_ok = False
                status_all_active = False
                break
            if str(obj.get("title", "")).strip() != title:
                tasks_ok = False
            if str(obj.get("assigned_to", "")).strip() != assignee:
                tasks_ok = False
            if str(obj.get("priority", "")).strip() != priority_val:
                tasks_ok = False
            if str(obj.get("status", "")).strip().lower() != "active":
                status_all_active = False
        checks["index_tasks_match_csv_fields"] = tasks_ok and (len(rows) > 0)
        checks["index_tasks_status_active_all"] = status_all_active and (len(rows) > 0)
    else:
        checks["index_valid_json"] = False
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    tasks_dir = os.path.join(output_dir, "tasks")

    # Paths
    parent_path = os.path.join(tasks_dir, "Q2-Onboarding-Revamp.md")
    csv_path = os.path.join(input_dir, "tasks.csv")
    index_path = os.path.join(tasks_dir, "index.json")

    # Load CSV for expectations
    rows = load_csv_rows(csv_path)

    checks_all: OrderedDict[str, bool] = OrderedDict()

    # Parent checks
    parent_checks = check_parent(parent_path)
    for k, v in parent_checks.items():
        checks_all[k] = v

    # Children checks
    children_checks = check_children(csv_path, tasks_dir)
    for k, v in children_checks.items():
        checks_all[k] = v

    # Index checks
    index_checks = check_index(index_path, rows)
    for k, v in index_checks.items():
        checks_all[k] = v

    # Compute reward: fraction of checks that are True
    total = len(checks_all)
    passed = sum(1 for v in checks_all.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total
    # No-op baseline: if output is missing or empty, ensure reward is 0.0
    # If parent does not exist and no children and no index -> reward should be 0
    if not os.path.isdir(tasks_dir):
        reward = 0.0
    else:
        # If none of key artifacts exist, set to 0.0
        key_exist = os.path.isfile(parent_path) or os.path.isfile(index_path) or any(
            f.endswith(".md") and f != "Q2-Onboarding-Revamp.md" for f in os.listdir(tasks_dir) if os.path.isfile(os.path.join(tasks_dir, f))
        )
        if not key_exist:
            reward = 0.0

    out = OrderedDict()
    out["reward"] = round(reward, 6)
    for k, v in checks_all.items():
        out[k] = bool(v)
    print(json.dumps(out))

if __name__ == "__main__":
    main()