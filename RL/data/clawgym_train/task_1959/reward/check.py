import json
import os
import sys
import re

def parse_yaml_frontmatter(text):
    lines = text.splitlines()
    if not lines:
        return None, None, None
    if lines[0].strip() != "---":
        return None, None, None
    # Find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, None, None
    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx+1:])
    data = {}
    for ln in fm_lines:
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        if ":" in ln:
            key, val = ln.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            data[key] = val
    return data, "\n".join(fm_lines), body

def contains_pushy_trigger_language(desc):
    if not desc:
        return False
    d = desc.lower()
    return ("trigger" in d) or ("use when" in d)

def count_context_keywords(desc):
    if not desc:
        return 0
    d = desc.lower()
    keywords = ["spec", "design review", "architecture", "rfc"]
    present = set()
    for kw in keywords:
        if kw in d:
            present.add(kw)
    return len(present)

def extract_headings(body):
    # Return list of (level, text) headings
    headings = []
    for line in body.splitlines():
        if re.match(r"^\s*#{1,6}\s+\S", line):
            txt = re.sub(r"^\s*#{1,6}\s+", "", line).strip()
            headings.append(txt)
    return headings

def has_heading_like(headings, needle_variants):
    # needle_variants: list of strings (lowercase to match)
    # Accept if any heading contains any variant substring (case-insensitive)
    low_heads = [h.lower() for h in headings]
    for h in low_heads:
        for v in needle_variants:
            if v in h:
                return True
    return False

def find_section_lines(body, section_title):
    # Find heading matching section_title (case-insensitive substring), return start index in lines
    lines = body.splitlines()
    pattern = re.compile(r"^\s*#{1,6}\s+.*" + re.escape(section_title) + r".*$", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if pattern.match(line):
            return idx, lines
    return None, lines

def count_bullets_after_section(body, section_title):
    start_idx, lines = find_section_lines(body, section_title)
    if start_idx is None:
        return 0
    count = 0
    for i in range(start_idx+1, len(lines)):
        line = lines[i]
        if re.match(r"^\s*#{1,6}\s+\S", line):
            break
        if re.match(r"^\s*[-*]\s+\S", line):
            count += 1
    return count

def is_kebab_case(s):
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s or ""))

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # SKILL.md and frontmatter checks
        "skill_md_exists": False,
        "frontmatter_delimited": False,
        "frontmatter_has_name": False,
        "frontmatter_has_description": False,
        "description_length_ge_120": False,
        "description_pushy": False,
        "description_has_two_context_keywords": False,
        # Headings presence
        "heading_intent_capture": False,
        "heading_interview_questions": False,
        "heading_step_by_step": False,
        "heading_output_format": False,
        "heading_examples": False,
        "heading_test_case_design": False,
        # Draft Assertions section
        "draft_assertions_section_present": False,
        "draft_assertions_count_ge_3": False,
        # evals.json checks
        "evals_json_exists": False,
        "evals_json_valid": False,
        "evals_count_2_or_3": False,
        "evals_items_valid_schema": False,
        "skill_name_matches": False,
        # metadata checks
        "metadata_files_exist_and_count_match": False,
        "metadata_each_valid_json": False,
        "metadata_prompts_match": False,
        "metadata_kebab_case_names_all": False,
        # trigger evals checks
        "trigger_evals_exists": False,
        "trigger_evals_valid_json": False,
        "trigger_evals_length_20": False,
        "trigger_evals_items_schema_valid": False,
        "trigger_evals_counts_balanced": False,
        "trigger_evals_queries_unique_ci": False,
    }

    # Paths
    skill_md_path = os.path.join(output_dir, "spec-reviewer", "SKILL.md")
    evals_json_path = os.path.join(output_dir, "spec-reviewer", "evals", "evals.json")
    workspace_iter_dir = os.path.join(output_dir, "spec-reviewer-workspace", "iteration-1")
    trigger_evals_path = os.path.join(output_dir, "trigger_evals.json")

    # 1) Validate SKILL.md
    skill_text = safe_read_text(skill_md_path)
    if skill_text is not None:
        checks["skill_md_exists"] = True
        fm_data, fm_raw, body = parse_yaml_frontmatter(skill_text)
        if fm_data is not None:
            checks["frontmatter_delimited"] = True
            name = fm_data.get("name", "").strip() if isinstance(fm_data, dict) else ""
            desc = fm_data.get("description", "").strip() if isinstance(fm_data, dict) else ""
            if name:
                checks["frontmatter_has_name"] = True
            if desc:
                checks["frontmatter_has_description"] = True
                if len(desc) >= 120:
                    checks["description_length_ge_120"] = True
                if contains_pushy_trigger_language(desc):
                    checks["description_pushy"] = True
                if count_context_keywords(desc) >= 2:
                    checks["description_has_two_context_keywords"] = True
        else:
            # No valid frontmatter or delimiter
            body = skill_text or ""

        # Headings checks on body
        headings = extract_headings(body or "")
        # Intent Capture
        if has_heading_like(headings, ["intent capture"]):
            checks["heading_intent_capture"] = True
        # Interview Questions (allow & Edge Cases variant)
        if has_heading_like(headings, ["interview questions"]):
            checks["heading_interview_questions"] = True
        # Step-by-Step Instructions
        # Normalize hyphen vs spaces
        if has_heading_like(headings, ["step-by-step instructions", "step by step instructions"]):
            checks["heading_step_by_step"] = True
        # Output Format
        if has_heading_like(headings, ["output format"]):
            checks["heading_output_format"] = True
        # Examples
        if has_heading_like(headings, ["examples"]):
            checks["heading_examples"] = True
        # Test Case Design or Test Case Design Guidance
        if has_heading_like(headings, ["test case design", "test case design guidance"]):
            checks["heading_test_case_design"] = True

        # Draft Assertions section
        # Section title may be "Draft Assertions" case-insensitive
        bullets_count = count_bullets_after_section(body or "", "Draft Assertions")
        if bullets_count is not None and bullets_count >= 0:
            # Determine if section exists by whether we could find it: start_idx will be None if not found.
            # Use find_section_lines to check presence.
            start_idx, _ = find_section_lines(body or "", "Draft Assertions")
            if start_idx is not None:
                checks["draft_assertions_section_present"] = True
            if bullets_count >= 3:
                checks["draft_assertions_count_ge_3"] = True

    # 2) Validate evals.json and link to SKILL.md name
    evals_data = None
    if os.path.isfile(evals_json_path):
        checks["evals_json_exists"] = True
        evals_data = safe_read_json(evals_json_path)
        if isinstance(evals_data, dict) and isinstance(evals_data.get("skill_name"), str) and isinstance(evals_data.get("evals"), list):
            checks["evals_json_valid"] = True
            evals_list = evals_data.get("evals", [])
            if len(evals_list) in (2, 3):
                checks["evals_count_2_or_3"] = True
            # Validate each eval schema
            items_ok = True
            for item in evals_list:
                if not (isinstance(item, dict)
                        and isinstance(item.get("id"), int)
                        and isinstance(item.get("prompt"), str) and item.get("prompt").strip() != ""
                        and isinstance(item.get("expected_output"), str) and item.get("expected_output").strip() != ""
                        and isinstance(item.get("files"), list)):
                    items_ok = False
                    break
            if items_ok:
                checks["evals_items_valid_schema"] = True
            # Match skill_name with SKILL.md frontmatter name
            if checks["frontmatter_has_name"] and isinstance(evals_data.get("skill_name"), str):
                fm_data, _, _ = parse_yaml_frontmatter(skill_text or "") if skill_text is not None else (None, None, None)
                if isinstance(fm_data, dict):
                    fm_name = fm_data.get("name", "")
                    if fm_name == evals_data.get("skill_name"):
                        checks["skill_name_matches"] = True

    # 3) Metadata files corresponding to evals
    metadata_files = []
    if os.path.isdir(workspace_iter_dir):
        # Walk subdirectories to find eval_metadata.json
        for root, dirs, files in os.walk(workspace_iter_dir):
            for f in files:
                if f == "eval_metadata.json":
                    metadata_files.append(os.path.join(root, f))
    # Require count to match evals count
    evals_count = 0
    evals_by_id = {}
    if isinstance(evals_data, dict) and isinstance(evals_data.get("evals"), list):
        evals_list = evals_data.get("evals")
        evals_count = len(evals_list)
        for item in evals_list:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                evals_by_id[item["id"]] = item

    if evals_count and len(metadata_files) == evals_count:
        checks["metadata_files_exist_and_count_match"] = True

    metadata_all_valid = True
    metadata_prompts_match = True
    metadata_names_kebab = True

    if metadata_files and evals_by_id:
        for p in metadata_files:
            meta = safe_read_json(p)
            if not (isinstance(meta, dict)
                    and isinstance(meta.get("eval_id"), int)
                    and isinstance(meta.get("eval_name"), str) and meta.get("eval_name").strip() != ""
                    and isinstance(meta.get("prompt"), str) and meta.get("prompt").strip() != ""
                    and isinstance(meta.get("assertions"), list)):
                metadata_all_valid = False
            else:
                # kebab-case check
                if not is_kebab_case(meta.get("eval_name")):
                    metadata_names_kebab = False
                # prompt matches by eval_id
                ev = evals_by_id.get(meta.get("eval_id"))
                if not (isinstance(ev, dict) and ev.get("prompt") == meta.get("prompt")):
                    metadata_prompts_match = False
    else:
        metadata_all_valid = False
        metadata_prompts_match = False
        metadata_names_kebab = False

    if metadata_all_valid:
        checks["metadata_each_valid_json"] = True
    if metadata_prompts_match:
        checks["metadata_prompts_match"] = True
    if metadata_names_kebab:
        checks["metadata_kebab_case_names_all"] = True

    # 4) Trigger evaluation queries
    trig_data = None
    if os.path.isfile(trigger_evals_path):
        checks["trigger_evals_exists"] = True
        trig_data = safe_read_json(trigger_evals_path)
        if isinstance(trig_data, list):
            checks["trigger_evals_valid_json"] = True
            if len(trig_data) == 20:
                checks["trigger_evals_length_20"] = True
            # Schema check
            items_ok = True
            true_count = 0
            false_count = 0
            queries = []
            for itm in trig_data:
                if not (isinstance(itm, dict)
                        and isinstance(itm.get("query"), str) and itm.get("query").strip() != ""
                        and isinstance(itm.get("should_trigger"), bool)):
                    items_ok = False
                    break
                if itm.get("should_trigger"):
                    true_count += 1
                else:
                    false_count += 1
                queries.append(itm.get("query").strip().lower())
            if items_ok:
                checks["trigger_evals_items_schema_valid"] = True
            if true_count == 10 and false_count == 10:
                checks["trigger_evals_counts_balanced"] = True
            # Uniqueness case-insensitive
            if len(queries) == len(set(queries)) and len(queries) == (len(trig_data) if isinstance(trig_data, list) else 0):
                checks["trigger_evals_queries_unique_ci"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure exact 0.0 when no-op baseline (no output or missing all primary artifacts)
    # If output dir missing or empty and none of the main files exist, keep reward 0.0
    core_files_exist = any([
        checks["skill_md_exists"],
        checks["evals_json_exists"],
        checks["trigger_evals_exists"],
    ])
    if not core_files_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()