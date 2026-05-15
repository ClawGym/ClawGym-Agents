import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_line_title(line):
    # Remove leading markdown heading symbols and surrounding whitespace
    l = line.strip()
    l = re.sub(r"^\s*#+\s*", "", l)
    return l.strip()

def extract_section(content, title):
    # Extract lines under a markdown section starting with '## <title>'
    lines = content.splitlines()
    section_start = None
    for i, line in enumerate(lines):
        if normalize_line_title(line) == title and line.strip().startswith("#"):
            # ensure it's a heading line, we accept any number of '#'
            section_start = i
            break
    if section_start is None:
        # Try to find exact title on a line even if not a heading
        for i, line in enumerate(lines):
            if normalize_line_title(line) == title:
                section_start = i
                break
    if section_start is None:
        return []
    # Find next heading of same or higher level (lines starting with '##')
    end = len(lines)
    for j in range(section_start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    return lines[section_start+1:end]

def count_checkboxes_under_section(content, section_title):
    section_lines = extract_section(content, section_title)
    count = 0
    for line in section_lines:
        # Matches "- [ ]", "- [x]", "- [X]" with optional spaces
        if re.match(r'^\s*-\s*\[\s*(?:x|X)?\s*\]', line):
            count += 1
    return count

def json_has_three_items(data):
    if isinstance(data, list):
        return len(data) == 3
    if isinstance(data, dict):
        return len(data.keys()) == 3
    return False

def iterate_mappings(data):
    # Yield each mapping object regardless of top-level type
    if isinstance(data, list):
        for item in data:
            yield item
    elif isinstance(data, dict):
        for key in data:
            yield data[key]

def has_required_fields(mapping):
    required = ["name", "slug", "version", "source_registry", "download_url", "risk_signals"]
    if not isinstance(mapping, dict):
        return False
    for k in required:
        if k not in mapping:
            return False
    return True

def has_both_registries(mappings):
    saw_skillhub = False
    saw_clawhub = False
    for m in mappings:
        if not isinstance(m, dict):
            continue
        src = m.get("source_registry", "")
        if src == "skillhub":
            saw_skillhub = True
        if src == "clawhub":
            saw_clawhub = True
    return saw_skillhub and saw_clawhub

def contains_all_keywords(text, keywords):
    t = text.lower()
    return all(k.lower() in t for k in keywords)

def contains_any_keyword(text, keywords):
    t = text.lower()
    return any(k.lower() in t for k in keywords)

def has_required_titles_in_session_status(content):
    titles = ["Current state", "What it means", "Recommended next step"]
    found = {t: False for t in titles}
    for line in content.splitlines():
        title = normalize_line_title(line)
        if title in found:
            found[title] = True
    return all(found.values())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) search_plan.json
        "search_plan_exists": False,
        "search_plan_valid_json": False,
        "search_plan_has_three_items": False,
        "search_plan_fields_present": False,
        "search_plan_has_both_registries": False,
        # 2) pre_install_summary.md
        "pre_install_summary_exists": False,
        "pre_install_contains_keywords": False,
        "pre_install_contains_commands": False,
        # 3) BRIEF.md
        "brief_exists": False,
        "brief_has_sections": False,
        "brief_mentions_required_terms": False,
        "brief_has_min_checkboxes": False,
        # 4) EVALUATOR_PROMPT.md
        "evaluator_prompt_exists": False,
        "evaluator_contains_exact_sentence": False,
        "evaluator_references_contract_and_phrases": False,
        # 5) session_status.md
        "session_status_exists": False,
        "session_status_has_required_sections": False,
    }

    # 1) search_plan.json checks
    sp_path = os.path.join(output_dir, "search_plan.json")
    if os.path.isfile(sp_path):
        checks["search_plan_exists"] = True
        data = load_json(sp_path)
        if data is not None:
            checks["search_plan_valid_json"] = True
            if json_has_three_items(data):
                checks["search_plan_has_three_items"] = True
                mappings = list(iterate_mappings(data))
                # fields present for all three
                if all(has_required_fields(m) for m in mappings):
                    checks["search_plan_fields_present"] = True
                # both registries
                if has_both_registries(mappings):
                    checks["search_plan_has_both_registries"] = True

    # 2) pre_install_summary.md checks
    pis_path = os.path.join(output_dir, "pre_install_summary.md")
    if os.path.isfile(pis_path):
        checks["pre_install_summary_exists"] = True
        content = read_text(pis_path) or ""
        # Required keywords: "skillhub", "clawhub", "fallback", "version", and "risk" or "risk signals"
        keywords_all = ["skillhub", "clawhub", "fallback", "version"]
        kw_all_ok = contains_all_keywords(content, keywords_all)
        kw_risk_ok = contains_any_keyword(content, ["risk", "risk signals"])
        if kw_all_ok and kw_risk_ok:
            checks["pre_install_contains_keywords"] = True
        # Commands must include "skillhub search" and "clawhub search"
        if contains_all_keywords(content, ["skillhub search", "clawhub search"]):
            checks["pre_install_contains_commands"] = True

    # 3) BRIEF.md checks
    brief_path = os.path.join(output_dir, "BRIEF.md")
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        brief = read_text(brief_path) or ""
        # Required section headings
        required_sections = [
            "## Background",
            "## Objective",
            "## Sprint Contract",
            "## Related Files",
            "## Constraints",
            "## Handoff Requirements",
        ]
        if all(rs in brief for rs in required_sections):
            checks["brief_has_sections"] = True
        # Must mention "/quote" and "/swap", "referrer", error codes "422", "529", "500", and "slippage"
        terms_ok = all(term in brief for term in ["/quote", "/swap", "referrer", "422", "529", "500", "slippage"])
        if terms_ok:
            checks["brief_mentions_required_terms"] = True
        # At least six checkbox items under Sprint Contract
        num_checkboxes = count_checkboxes_under_section(brief, "Sprint Contract")
        if num_checkboxes >= 6:
            checks["brief_has_min_checkboxes"] = True

    # 4) EVALUATOR_PROMPT.md checks
    eval_path = os.path.join(output_dir, "EVALUATOR_PROMPT.md")
    if os.path.isfile(eval_path):
        checks["evaluator_prompt_exists"] = True
        eval_txt = read_text(eval_path) or ""
        # Exact sentence
        if "Your job is to find problems, not to praise." in eval_txt:
            checks["evaluator_contains_exact_sentence"] = True
        # Must reference "Sprint Contract" and include phrases "Functional completeness" and "Code/content quality"
        if all(p in eval_txt for p in ["Sprint Contract", "Functional completeness", "Code/content quality"]):
            checks["evaluator_references_contract_and_phrases"] = True

    # 5) session_status.md checks
    ss_path = os.path.join(output_dir, "session_status.md")
    if os.path.isfile(ss_path):
        checks["session_status_exists"] = True
        ss_txt = read_text(ss_path) or ""
        if has_required_titles_in_session_status(ss_txt):
            checks["session_status_has_required_sections"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output dir is missing or empty (no files), reward = 0.0
    try:
        output_exists = os.path.isdir(output_dir)
        output_files = []
        if output_exists:
            for root, dirs, files in os.walk(output_dir):
                for fn in files:
                    output_files.append(os.path.join(root, fn))
        if (not output_exists) or (len(output_files) == 0):
            reward = 0.0
    except Exception:
        # If we cannot inspect, be conservative
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()