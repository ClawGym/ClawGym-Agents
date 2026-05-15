import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()
    except Exception:
        return None

def has_yaml_front_matter_with_keys(text, required_keys):
    # Must begin with '---' at the very start of file
    if not text.startswith("---"):
        return False
    lines = text.splitlines()
    # find second '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None or end_idx <= 1:
        return False
    block = "\n".join(lines[1:end_idx])
    block_lower = block.lower()
    # naive key presence check "key:" in the block
    for key in required_keys:
        pattern = re.compile(r'^\s*' + re.escape(key.lower()) + r'\s*:', re.MULTILINE)
        if not pattern.search(block_lower):
            return False
    return True

def count_subheadings(text, prefix="### "):
    return sum(1 for line in text.splitlines() if line.startswith(prefix))

def contains_section_heading(text, title, level="##"):
    # case-insensitive match of a markdown heading line
    pattern = re.compile(r'^\s*' + re.escape(level) + r'\s+' + re.escape(title) + r'\s*$', re.IGNORECASE | re.MULTILINE)
    return bool(pattern.search(text))

def extract_section(text, title):
    # Extract section content starting at heading that equals title (any # level), until next heading
    lines = text.splitlines()
    start_idx = None
    start_level = None
    heading_re = re.compile(r'^(\s{0,3}#{1,6})\s+(.*\S)\s*$')
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            lvl = len(m.group(1).strip())
            name = m.group(2).strip()
            if name.lower() == title.lower():
                start_idx = i + 1
                start_level = lvl
                break
    if start_idx is None:
        return None
    # collect until next heading (any level)
    content_lines = []
    for j in range(start_idx, len(lines)):
        if heading_re.match(lines[j]):
            break
        content_lines.append(lines[j])
    return "\n".join(content_lines)

def paragraph_contains_all_keywords(text, keywords):
    # Split by blank lines into paragraphs
    paragraphs = re.split(r'\n\s*\n', text, flags=re.MULTILINE)
    keywords_lower = [k.lower() for k in keywords]
    for p in paragraphs:
        pl = p.lower()
        if all(k in pl for k in keywords_lower):
            return True
    return False

def line_with_prefix_and_length(lines, prefix, min_len, max_len):
    for line in lines:
        if line.startswith(prefix):
            value = line[len(prefix):]
            # do not strip internal spaces; stripping trailing newline and surrounding spaces is ok
            value = value.rstrip("\r\n")
            value_stripped = value.strip()
            length = len(value_stripped)
            if min_len <= length <= max_len:
                return True
    return False

def find_line_index_matching(lines, pattern):
    rx = re.compile(pattern, re.IGNORECASE)
    for idx, line in enumerate(lines):
        if rx.match(line):
            return idx
    return -1

def count_lines_starting_with(lines, prefix):
    return sum(1 for line in lines if line.startswith(prefix))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # SKILL.md checks
        "skill_exists": False,
        "skill_front_matter_has_version_name_description": False,
        "skill_has_overview_section": False,
        "skill_has_core_capabilities_section": False,
        "skill_has_at_least_four_subheadings": False,
        "skill_has_workflow_ingest_validate_transform_export": False,
        "skill_has_resources_section_and_lists_dirs": False,
        "skill_has_no_template_scaffolding": False,

        # validators.py checks
        "validators_exists": False,
        "validators_has_required_functions": False,
        "validators_has_main_guard": False,
        "validators_prints_validators_ready": False,

        # guide.md checks
        "guide_exists": False,
        "guide_has_schema_heading": False,
        "guide_has_naming_heading": False,
        "guide_has_async_task_orchestration_section": False,
        "guide_async_section_mentions_all_keywords": False,

        # assets/templates/README.md
        "assets_templates_readme_exists_and_nonempty": False,

        # slides.md checks
        "slides_exists": False,
        "slides_mentions_skill_name": False,
        "slides_has_min_separators": False,
        "slides_has_qa": False,

        # landing.md checks
        "landing_exists": False,
        "landing_has_valid_meta_title_length": False,
        "landing_has_valid_meta_description_length": False,
        "landing_has_h1_with_data_ingestion": False,
        "landing_has_min_faq_pairs": False,
        "landing_has_seo_score_line": False,
        "landing_has_breakdown_keywords_after_score": False,
    }

    # 1) SKILL.md
    skill_path = os.path.join(output_dir, "SKILL.md")
    skill_text = read_text(skill_path)
    if skill_text is not None:
        checks["skill_exists"] = True
        # front matter with version, name, description
        if has_yaml_front_matter_with_keys(skill_text, ["version", "name", "description"]):
            checks["skill_front_matter_has_version_name_description"] = True
        # Overview section
        if contains_section_heading(skill_text, "Overview", level="##"):
            checks["skill_has_overview_section"] = True
        # Core Capabilities section
        if contains_section_heading(skill_text, "Core Capabilities", level="##"):
            checks["skill_has_core_capabilities_section"] = True
        # at least four subheadings starting with '### '
        if count_subheadings(skill_text, "### ") >= 4:
            checks["skill_has_at_least_four_subheadings"] = True
        # workflow mention ingest, validate, transform, export in single paragraph
        if paragraph_contains_all_keywords(skill_text, ["ingest", "validate", "transform", "export"]):
            checks["skill_has_workflow_ingest_validate_transform_export"] = True
        # Resources section and mentions of scripts/, references/, assets/
        if contains_section_heading(skill_text, "Resources", level="##"):
            if ("scripts/" in skill_text) and ("references/" in skill_text) and ("assets/" in skill_text):
                checks["skill_has_resources_section_and_lists_dirs"] = True
        # must NOT contain 'Structuring This Skill' or 'TODO'
        lower_text = skill_text.lower()
        if "structuring this skill".lower() not in lower_text and "todo" not in lower_text:
            checks["skill_has_no_template_scaffolding"] = True

    # 2) validators.py
    validators_path = os.path.join(output_dir, "scripts", "validators.py")
    validators_text = read_text(validators_path)
    if validators_text is not None:
        checks["validators_exists"] = True
        low_val = validators_text.lower()
        has_funcs = all(s in validators_text for s in ["def validate_csv", "def validate_json", "def validate_xml"])
        if has_funcs:
            checks["validators_has_required_functions"] = True
        if 'if __name__ == "__main__":' in validators_text:
            checks["validators_has_main_guard"] = True
        if "validators ready" in low_val:
            checks["validators_prints_validators_ready"] = True

    # 3) guide.md
    guide_path = os.path.join(output_dir, "references", "guide.md")
    guide_text = read_text(guide_path)
    if guide_text is not None:
        checks["guide_exists"] = True
        # Schema heading
        schema_heading = re.search(r'^\s*#{1,6}\s+Schema\s*$', guide_text, re.IGNORECASE | re.MULTILINE)
        if schema_heading:
            checks["guide_has_schema_heading"] = True
        # Naming heading
        naming_heading = re.search(r'^\s*#{1,6}\s+Naming\s*$', guide_text, re.IGNORECASE | re.MULTILINE)
        if naming_heading:
            checks["guide_has_naming_heading"] = True
        # Async Task Orchestration section
        async_heading_match = None
        lines = guide_text.splitlines()
        heading_re = re.compile(r'^(\s{0,3}#{1,6})\s+(.*\S)\s*$')
        for i, line in enumerate(lines):
            m = heading_re.match(line)
            if m:
                name = m.group(2).strip()
                if name.lower() == "async task orchestration":
                    async_heading_match = i
                    break
        if async_heading_match is not None:
            checks["guide_has_async_task_orchestration_section"] = True
            # Extract section content until next heading
            content_lines = []
            for j in range(async_heading_match + 1, len(lines)):
                if heading_re.match(lines[j]):
                    break
                content_lines.append(lines[j])
            content = "\n".join(content_lines).lower()
            if (
                "priority" in content and
                "retry" in content and
                ("dependency" in content or "dependencies" in content) and
                "concurrency" in content and
                "timeout" in content and
                "logging" in content
            ):
                checks["guide_async_section_mentions_all_keywords"] = True

    # 4) assets/templates/README.md
    assets_readme_path = os.path.join(output_dir, "assets", "templates", "README.md")
    assets_text = read_text(assets_readme_path)
    if assets_text is not None and len(assets_text.strip()) > 0:
        checks["assets_templates_readme_exists_and_nonempty"] = True

    # 5) onboarding slides
    slides_path = os.path.join(output_dir, "onboarding", "slides.md")
    slides_text = read_text(slides_path)
    slides_lines = read_lines(slides_path)
    if slides_text is not None and slides_lines is not None:
        checks["slides_exists"] = True
        if "data-ingest-pro".lower() in slides_text.lower():
            checks["slides_mentions_skill_name"] = True
        separators = sum(1 for ln in slides_lines if ln.strip() == "---")
        if separators >= 8:
            checks["slides_has_min_separators"] = True
        if "q&a" in slides_text.lower():
            checks["slides_has_qa"] = True

    # 6) landing page
    landing_path = os.path.join(output_dir, "landing", "landing.md")
    landing_text = read_text(landing_path)
    landing_lines = read_lines(landing_path)
    if landing_text is not None and landing_lines is not None:
        checks["landing_exists"] = True
        if line_with_prefix_and_length(landing_lines, "Meta Title: ", 50, 60):
            checks["landing_has_valid_meta_title_length"] = True
        if line_with_prefix_and_length(landing_lines, "Meta Description: ", 150, 160):
            checks["landing_has_valid_meta_description_length"] = True
        # H1 with 'data ingestion'
        h1_ok = False
        for ln in landing_lines:
            if ln.startswith("# "):
                if "data ingestion" in ln.lower():
                    h1_ok = True
                    break
        if h1_ok:
            checks["landing_has_h1_with_data_ingestion"] = True
        # FAQ pairs
        q_count = count_lines_starting_with(landing_lines, "Q:")
        a_count = count_lines_starting_with(landing_lines, "A:")
        if q_count >= 3 and a_count >= 3:
            checks["landing_has_min_faq_pairs"] = True
        # SEO score line
        score_idx = find_line_index_matching(landing_lines, r'^\s*SEO Score:\s*\d{1,3}/100\s*$')
        if score_idx != -1:
            checks["landing_has_seo_score_line"] = True
            # breakdown after score line: needs at least 5 of keywords
            rest = "\n".join(landing_lines[score_idx + 1:]).lower()
            keywords = ["keyword", "length", "readability", "headings", "meta", "internal links", "external links", "faq"]
            present = set()
            for kw in keywords:
                if kw in rest:
                    present.add(kw)
            if len(present) >= 5:
                checks["landing_has_breakdown_keywords_after_score"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0 and passed > 0:
        reward = passed / total
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()