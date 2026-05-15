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

def extract_frontmatter(text):
    lines = text.splitlines()
    sep_indices = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
    if len(sep_indices) >= 2 and sep_indices[1] > sep_indices[0]:
        start = sep_indices[0]
        end = sep_indices[1]
        fm_lines = lines[start+1:end]
        body_lines = lines[end+1:]
        return "\n".join(fm_lines), "\n".join(body_lines)
    return None, text

def find_frontmatter_value(frontmatter, key):
    # Returns (value, line_str) where value is stripped without surrounding quotes
    # Matches lines like: key: value
    if frontmatter is None:
        return None, None
    for line in frontmatter.splitlines():
        m = re.match(r'^\s*' + re.escape(key) + r'\s*:\s*(.+?)\s*$', line)
        if m:
            raw = m.group(1).strip()
            # Strip surrounding quotes if present
            if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
                val = raw[1:-1]
            else:
                val = raw
            return val, line
    return None, None

def parse_metadata_json_from_line(line):
    # Expect metadata: { ... } on the same line
    if line is None:
        return None, False
    has_open_brace = "{" in line
    has_close_brace = "}" in line
    single_line_braces = has_open_brace and has_close_brace and (line.find("{") < line.rfind("}"))
    if not single_line_braces:
        return None, False
    json_part = line[line.find("{"): line.rfind("}")+1]
    try:
        obj = json.loads(json_part)
        return obj, True
    except Exception:
        return None, False

def get_section_bounds(body_text, heading_variants):
    lines = body_text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() in heading_variants:
            start_idx = i
            break
    if start_idx is None:
        return None, None
    # find next heading that starts with '## ' and not the same line
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("## "):
            end_idx = j
            break
    return start_idx, end_idx

def extract_section_text(body_text, heading_variants):
    start, end = get_section_bounds(body_text, heading_variants)
    if start is None:
        return None
    lines = body_text.splitlines()
    # Exclude the heading line itself
    return "\n".join(lines[start+1:end])

def count_numbered_lines(section_text):
    if not section_text:
        return 0
    count = 0
    for ln in section_text.splitlines():
        if re.match(r'^\s*\d+\.\s', ln):
            count += 1
    return count

def first_numbered_line(section_text):
    if not section_text:
        return None
    for ln in section_text.splitlines():
        if re.match(r'^\s*1\.\s', ln):
            return ln
    return None

def contains_all_substrings(text, substrings, case_insensitive=True):
    if text is None:
        return False
    hay = text.lower() if case_insensitive else text
    for s in substrings:
        needle = s.lower() if case_insensitive else s
        if needle not in hay:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    skill_dir = os.path.join(output_dir, "skills", "incident-postmortem-writer")
    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    validation_json_path = os.path.join(skill_dir, "VALIDATION.json")
    gaps_md_path = os.path.join(skill_dir, "gaps-and-assumptions.md")

    checks = {
        "skill_md_exists": False,
        "frontmatter_present": False,
        "name_correct": False,
        "description_valid": False,
        "metadata_ok": False,
        "sections_present": False,
        "protocol_steps_ge_6": False,
        "first_rule_has_no_blame": False,
        "security_mentions_network_and_credentials": False,
        "output_template_includes_required": False,
        "validation_json_ok": False,
        "gaps_and_assumptions_ok": False,
    }

    content = read_text(skill_md_path)
    if content is not None:
        checks["skill_md_exists"] = True
        frontmatter, body = extract_frontmatter(content)
        if frontmatter is not None:
            checks["frontmatter_present"] = True
            # name
            name_val, _ = find_frontmatter_value(frontmatter, "name")
            if name_val is not None:
                if name_val.strip() == "incident-postmortem-writer":
                    checks["name_correct"] = True
            # description
            desc_val, desc_line = find_frontmatter_value(frontmatter, "description")
            if desc_val is not None and desc_line is not None:
                # Single line if value exists on same line and not YAML block indicators
                single_line_ok = not desc_val.strip().endswith("|") and not desc_val.strip().endswith(">")
                # Length < 200
                length_ok = len(desc_val.strip()) < 200
                # Contains at least one trigger phrase
                triggers = ["create a postmortem", "incident report", "RCA template"]
                has_trigger = any(t.lower() in desc_val.lower() for t in triggers)
                if single_line_ok and length_ok and has_trigger:
                    checks["description_valid"] = True
            # metadata
            _, metadata_line = find_frontmatter_value(frontmatter, "metadata")
            metadata_obj, single_line_braces = parse_metadata_json_from_line(metadata_line)
            if metadata_obj is not None and single_line_braces:
                # Expect {"openclaw": {"emoji": ..., "homepage": ..., "os": [...]}}
                oc = metadata_obj.get("openclaw")
                if isinstance(oc, dict):
                    emoji_ok = "emoji" in oc
                    homepage_ok = "homepage" in oc
                    os_ok = False
                    if isinstance(oc.get("os"), list):
                        os_list = [str(x).lower() for x in oc.get("os")]
                        os_ok = all(x in os_list for x in ["darwin", "linux", "win32"])
                    if emoji_ok and homepage_ok and os_ok:
                        checks["metadata_ok"] = True

        # Sections presence
        body_text = body if frontmatter is not None else content
        required_headings = [
            "## WHEN TO TRIGGER",
            "## WHEN NOT TO TRIGGER",
            "## PREREQUISITES",
            "## SECURITY CONSIDERATIONS",
            "## RULES",
            "## OUTPUT FORMAT",
        ]
        # protocol has two variants
        protocol_variants = ["## PROTOCOL / PROCESS", "## PROTOCOL/PROCESS"]
        has_protocol = any(h in body_text for h in protocol_variants)
        has_all_other = all(h in body_text for h in required_headings)
        if has_protocol and has_all_other:
            checks["sections_present"] = True

        # Protocol steps
        protocol_section = extract_section_text(body_text, set(protocol_variants))
        steps_count = count_numbered_lines(protocol_section)
        if steps_count >= 6:
            checks["protocol_steps_ge_6"] = True

        # Rules first rule with 'no-blame'
        rules_section = extract_section_text(body_text, {"## RULES"})
        first_rule_line = first_numbered_line(rules_section)
        if first_rule_line is not None and "no-blame" in first_rule_line.lower():
            checks["first_rule_has_no_blame"] = True

        # Security mentions network and credentials
        sec_section = extract_section_text(body_text, {"## SECURITY CONSIDERATIONS"})
        if sec_section is not None and contains_all_substrings(sec_section, ["network", "credentials"], case_insensitive=True):
            checks["security_mentions_network_and_credentials"] = True

        # Output format includes required subsections
        out_section = extract_section_text(body_text, {"## OUTPUT FORMAT"})
        required_substrings = [
            "Title", "Summary", "Impact", "Timeline", "5 Whys", "Contributing Factors",
            "Detection", "Response", "What Went Well", "What Went Wrong", "Action Items"
        ]
        # Also require fields in Action Items: owner, due_date, status
        if out_section is not None:
            has_required = contains_all_substrings(out_section, required_substrings, case_insensitive=True)
            has_fields = contains_all_substrings(out_section, ["owner", "due_date", "status"], case_insensitive=True)
            if has_required and has_fields:
                checks["output_template_includes_required"] = True

    # VALIDATION.json
    val_text = read_text(validation_json_path)
    if val_text is not None:
        try:
            val = json.loads(val_text)
            # Required keys
            req_bool_keys = [
                "yaml_parses",
                "metadata_single_line",
                "description_under_200",
                "has_sections",
                "first_rule_has_no_blame",
                "security_mentions_network_and_credentials",
                "output_template_includes_required_sections",
            ]
            has_all_keys = all(k in val for k in (req_bool_keys + ["protocol_steps_count", "errors"]))
            bools_ok = has_all_keys and all(isinstance(val[k], bool) and val[k] is True for k in req_bool_keys)
            steps_ok = has_all_keys and isinstance(val["protocol_steps_count"], (int, float)) and val["protocol_steps_count"] >= 6
            errors_ok = has_all_keys and isinstance(val["errors"], list) and len(val["errors"]) == 0
            if has_all_keys and bools_ok and steps_ok and errors_ok:
                checks["validation_json_ok"] = True
        except Exception:
            pass

    # gaps-and-assumptions.md
    gaps_text = read_text(gaps_md_path)
    if gaps_text is not None:
        if ("assumptions" in gaps_text.lower()) and ("open questions" in gaps_text.lower()):
            checks["gaps_and_assumptions_ok"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if outputs missing, reward must be 0.0 (this is already ensured since all checks False)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()