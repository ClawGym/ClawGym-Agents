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

def parse_frontmatter_and_body(text):
    # Returns (frontmatter_text, body_text) or (None, None) if not properly delimited
    if text is None:
        return None, None
    lines = text.splitlines()
    if not lines:
        return None, None
    if lines[0].strip() != "---":
        return None, None
    # find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, None
    fm_text = "\n".join(lines[1:end_idx])
    body_text = "\n".join(lines[end_idx+1:]) if end_idx + 1 < len(lines) else ""
    return fm_text, body_text

def get_frontmatter_field(fm_text, field_name):
    # Simple single-line field parser: field_name: value
    # Returns value string stripped of surrounding quotes if present, else None
    if fm_text is None:
        return None
    for raw in fm_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(rf"^{re.escape(field_name)}\s*:", line):
            # split on first colon
            parts = line.split(":", 1)
            val = parts[1].strip()
            # strip surrounding single or double quotes if they wrap entire value
            if (len(val) >= 2) and ((val[0] == val[-1]) and val[0] in ['"', "'"]):
                val = val[1:-1]
            return val
    return None

def has_markdown_table(body_text):
    if body_text is None:
        return False
    lines = body_text.splitlines()
    for i in range(len(lines) - 1):
        l1 = lines[i]
        l2 = lines[i + 1]
        if "|" in l1:
            if re.match(r"^\s*\|?\s*[:\-\|\s]+\s*\|?\s*$", l2):
                # ensure there is at least one '-' in separator line
                if "-" in l2 or ":" in l2:
                    return True
    return False

def has_fenced_code_with_language(body_text):
    if body_text is None:
        return False
    for line in body_text.splitlines():
        if re.match(r"^\s*```[A-Za-z0-9_+\-]+\s*$", line):
            return True
    return False

def contains_required_phrases(text, phrases):
    if text is None:
        return False
    tl = text.lower()
    return any(p.lower() in tl for p in phrases)

def nonempty_file(path):
    text = read_text(path)
    if text is None:
        return False
    return bool(text.strip())

def compute_reward(checks_dict):
    total = len(checks_dict)
    passed = sum(1 for v in checks_dict.values() if v is True)
    if total == 0:
        return 0.0
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    audit_path = os.path.join(output_dir, "audit", "report.md")
    plan_path = os.path.join(output_dir, "plan", "fix_plan.md")
    skill_path = os.path.join(output_dir, "improved-skill", "SKILL.md")
    ref_antipatterns_path = os.path.join(output_dir, "improved-skill", "references", "anti-patterns.md")
    ref_scoring_path = os.path.join(output_dir, "improved-skill", "references", "scoring.md")
    resume_path = os.path.join(output_dir, "notes", "resume.md")

    checks = {
        # Audit report checks
        "audit_score_line": False,
        "audit_has_severities": False,
        "audit_has_checklist_id": False,

        # Fix plan checks
        "plan_has_severities": False,
        "plan_has_before_after": False,

        # Improved skill frontmatter/body checks
        "skill_starts_with_frontmatter": False,
        "skill_name_correct": False,
        "skill_description_valid_length_and_triggers": False,
        "skill_frontmatter_no_angle_brackets": False,
        "skill_body_max_500_lines": False,
        "skill_has_routing_table_section": False,
        "skill_links_to_anti_patterns": False,
        "skill_links_to_scoring": False,
        "skill_has_troubleshooting_section": False,
        "skill_has_markdown_table": False,
        "skill_has_fenced_code_with_language": False,
        "skill_no_unicode_arrows": False,
        "skill_no_baseDir_placeholder": False,

        # Reference files existence
        "references_antipatterns_nonempty": False,
        "references_scoring_nonempty": False,

        # Resume checkpoint
        "resume_has_checkpoint_phrases": False,
    }

    # 1) Audit report checks
    audit_text = read_text(audit_path)
    if audit_text is not None:
        # Score line: start with "Score:" and end with "/10"
        for raw_line in audit_text.splitlines():
            sline = raw_line.strip()
            if sline.startswith("Score:") and sline.endswith("/10"):
                checks["audit_score_line"] = True
                break
        # Must include HIGH / MEDIUM / LOW at least once each (case-insensitive)
        al = audit_text.lower()
        if ("high" in al) and ("medium" in al) and ("low" in al):
            checks["audit_has_severities"] = True
        # Checklist ID-like token (S#, F#, C#, L#, SEC#, X#)
        if re.search(r"\b(S\d+|F\d+|C\d+|L\d+|SEC\d+|X\d+)\b", audit_text):
            checks["audit_has_checklist_id"] = True

    # 2) Plan checks
    plan_text = read_text(plan_path)
    if plan_text is not None:
        pl = plan_text.lower()
        if ("high" in pl) and ("medium" in pl) and ("low" in pl):
            checks["plan_has_severities"] = True
        # Before and After occurrences
        if re.search(r"\bbefore\s*:", plan_text, flags=re.IGNORECASE) and re.search(r"\bafter\s*:", plan_text, flags=re.IGNORECASE):
            checks["plan_has_before_after"] = True

    # 3) Improved skill checks
    skill_text = read_text(skill_path)
    if skill_text is not None:
        fm_text, body_text = parse_frontmatter_and_body(skill_text)
        if fm_text is not None:
            checks["skill_starts_with_frontmatter"] = True
            # name: improved-skill
            name_val = get_frontmatter_field(fm_text, "name")
            if isinstance(name_val, str) and name_val.strip() == "improved-skill":
                checks["skill_name_correct"] = True
            # description: length 1-300 and includes trigger phrases
            desc_val = get_frontmatter_field(fm_text, "description")
            if isinstance(desc_val, str):
                desc_clean = desc_val.strip()
                desc_len = len(desc_clean)
                # no angle brackets in entire frontmatter values
                if "<" not in fm_text and ">" not in fm_text:
                    checks["skill_frontmatter_no_angle_brackets"] = True
                triggers = ["create skill", "improve skill", "audit skill", "scan skill"]
                has_trigger = contains_required_phrases(desc_clean, triggers)
                if 1 <= desc_len <= 300 and has_trigger:
                    checks["skill_description_valid_length_and_triggers"] = True
        # Body checks
        if body_text is not None:
            # body <= 500 lines
            body_lines = body_text.splitlines()
            if len(body_lines) <= 500:
                checks["skill_body_max_500_lines"] = True
            # contains "Routing table"
            if re.search(r"routing table", body_text, flags=re.IGNORECASE):
                checks["skill_has_routing_table_section"] = True
            # links to references using relative markdown syntax
            if "(references/anti-patterns.md)" in body_text:
                checks["skill_links_to_anti_patterns"] = True
            if "(references/scoring.md)" in body_text:
                checks["skill_links_to_scoring"] = True
            # Troubleshooting section
            if re.search(r"troubleshooting", body_text, flags=re.IGNORECASE):
                checks["skill_has_troubleshooting_section"] = True
            # Markdown table detection
            if has_markdown_table(body_text):
                checks["skill_has_markdown_table"] = True
            # Fenced code block with language
            if has_fenced_code_with_language(body_text):
                checks["skill_has_fenced_code_with_language"] = True
            # No unicode arrows
            if ("→" not in body_text) and ("←" not in body_text):
                checks["skill_no_unicode_arrows"] = True
            # No {baseDir}
            if "{baseDir}" not in body_text:
                checks["skill_no_baseDir_placeholder"] = True

    # 4) Reference files must exist and be non-empty
    if nonempty_file(ref_antipatterns_path):
        checks["references_antipatterns_nonempty"] = True
    if nonempty_file(ref_scoring_path):
        checks["references_scoring_nonempty"] = True

    # 5) Resume checkpoint note
    resume_text = read_text(resume_path)
    if resume_text is not None:
        rl = resume_text.lower()
        if ("resume point" in rl) and ("next exact step:" in rl):
            checks["resume_has_checkpoint_phrases"] = True

    reward = compute_reward(checks)
    # No-op baseline: if no outputs at all, reward must be 0.0 (our compute_reward already yields 0 if nothing passes)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()