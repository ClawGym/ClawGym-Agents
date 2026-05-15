import json
import os
import re
import sys
from typing import Dict, Optional, Tuple, List

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_frontmatter(md: str) -> Tuple[bool, Dict[str, str], int]:
    """
    Returns (ok, fields, end_index_of_frontmatter_block)
    ok = True if frontmatter exists and is delimited by --- at start and closing ---.
    fields = dict of top-level keys to raw text values (best-effort, including block scalars)
    end_index_of_frontmatter_block = index in the md string where frontmatter ends (position after closing --- line)
    """
    if not md.startswith("---"):
        return (False, {}, 0)
    # Find the end '---' line. It must be on its own line after the opening.
    lines = md.splitlines(keepends=True)
    if not lines:
        return (False, {}, 0)
    # First line should be '---'
    if lines[0].strip() != "---":
        return (False, {}, 0)
    end_idx_line = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx_line = i
            break
    if end_idx_line is None:
        return (False, {}, 0)
    # Collect frontmatter lines between 1 and end_idx_line-1
    fm_lines = [l for l in lines[1:end_idx_line]]
    # Build a simple YAML-like parser for top-level keys
    fields: Dict[str, str] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        # Only consider non-indented top-level keys
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.*)\s*$', line)
        if m:
            key = m.group(1)
            remainder = m.group(2)
            # Block scalar start
            if remainder in ("|", ">", "|-", ">-"):
                i += 1
                block_lines: List[str] = []
                while i < len(fm_lines):
                    nxt = fm_lines[i]
                    # Stop if next potential top-level key (no indentation and matches key:)
                    if re.match(r'^[A-Za-z0-9_]+\s*:\s*', nxt):
                        break
                    # For block scalars, include as-is; strip a single leading indent if present
                    block_lines.append(nxt.rstrip("\n"))
                    i += 1
                value = "\n".join(block_lines).strip()
                fields[key] = value
                continue
            else:
                # Inline scalar, can be empty or text
                fields[key] = remainder.strip()
                i += 1
                continue
        else:
            # Not a top-level key; skip
            i += 1
    # Compute end index in original string
    end_pos = sum(len(l) for l in lines[: end_idx_line + 1])
    return (True, fields, end_pos)

def has_required_headings(body: str) -> bool:
    # Required headings: "## Triggers", "## Steps", "## Output Templates", "## Edge Cases", "## Rules", "## Why this skill"
    reqs = [
        "## Triggers",
        "## Steps",
        "## Output Templates",
        "## Edge Cases",
        "## Rules",
        "## Why this skill",
    ]
    body_lower = body.lower()
    for h in reqs:
        if h.lower() not in body_lower:
            return False
    return True

def count_numbered_steps(body: str) -> int:
    # Count lines that start with numbered list indicators. The spec emphasizes '1.' or '1)', but we accept any number.
    count = 0
    for line in body.splitlines():
        if re.match(r'^\s*(?:\d+)[\.\)]\s+', line):
            count += 1
    return count

def summary_has_two_signals(text: str) -> bool:
    # Try to detect presence of at least two "signals". We look for a line containing 'signals' with multiple items,
    # or count occurrences of the word 'signal' (>=2), or bullet-style signals section.
    t = text.lower()
    # Count occurrences of the word 'signal'
    if len(re.findall(r'\bsignal[s]?\b', t)) >= 2:
        return True
    # Look for a 'signals:' line with commas
    for line in t.splitlines():
        if 'signals' in line:
            # Extract items after colon
            parts = line.split(':', 1)
            if len(parts) == 2:
                items = [p.strip() for p in re.split(r'[;,]', parts[1]) if p.strip()]
                if len(items) >= 2:
                    return True
    # Look for bullet points under a Signals section
    lines = t.splitlines()
    in_signals_section = False
    bullets = 0
    for line in lines:
        if 'signals' in line and (line.strip().endswith(':') or line.strip().startswith('signals')):
            in_signals_section = True
            bullets = 0
            continue
        if in_signals_section:
            if line.strip().startswith(('-', '*')):
                bullets += 1
            elif line.strip() == "" or line.strip().startswith('#'):
                # End section on empty or new header
                if bullets >= 2:
                    return True
                in_signals_section = False
    return False

def find_skill_dirs(skills_root: str) -> List[str]:
    dirs = []
    if not os.path.isdir(skills_root):
        return dirs
    for entry in os.listdir(skills_root):
        p = os.path.join(skills_root, entry)
        if os.path.isdir(p):
            md_path = os.path.join(p, "SKILL.md")
            if os.path.isfile(md_path):
                dirs.append(p)
    return dirs

def load_json(path: str) -> Optional[object]:
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

    checks: Dict[str, bool] = {
        "has_one_skill_dir": False,
        "skill_dir_name_valid": False,
        "skill_md_exists": False,
        "frontmatter_exact_two_keys": False,
        "frontmatter_has_name_and_description": False,
        "description_has_trigger_language": False,
        "has_required_headings": False,
        "has_at_least_three_numbered_steps": False,
        "why_section_has_metrics": False,
        "pattern_tracker_has_required_fields": False,
        "pattern_tracker_skill_linked": False,
        "pattern_tracker_stats_increment": False,
        "skills_audit_valid": False,
        "skills_audit_length_ok": False,
        "skills_audit_entries_schema_ok": False,
        "skills_audit_includes_new_skill": False,
        "summary_includes_workflow_and_signals": False,
        "summary_includes_skill_dir_name": False,
        "summary_includes_stats_update": False,
    }

    # Locate the skill output
    skills_root = os.path.join(output_dir, "skills")
    skill_dirs = find_skill_dirs(skills_root)
    if len(skill_dirs) == 1:
        checks["has_one_skill_dir"] = True
        skill_dir = skill_dirs[0]
        skill_dir_name = os.path.basename(skill_dir)
        if re.match(r'^[a-z0-9][a-z0-9-]*$', skill_dir_name):
            checks["skill_dir_name_valid"] = True
        # Parse SKILL.md
        md_path = os.path.join(skill_dir, "SKILL.md")
        if os.path.isfile(md_path):
            checks["skill_md_exists"] = True
            md = read_text(md_path) or ""
            ok_fm, fields, fm_end = parse_frontmatter(md)
            # Validate frontmatter: delimited and exactly two keys
            if ok_fm:
                # Exactly two keys: name and description
                keys = set(fields.keys())
                if keys == {"name", "description"}:
                    checks["frontmatter_exact_two_keys"] = True
                if "name" in keys and "description" in keys:
                    checks["frontmatter_has_name_and_description"] = True
                # Description trigger language
                desc = fields.get("description", "")
                if re.search(r'\b(use when|when to use|trigger)\b', desc, flags=re.IGNORECASE):
                    checks["description_has_trigger_language"] = True
            # Body checks
            body = md[fm_end:] if fm_end > 0 else md
            if has_required_headings(body):
                checks["has_required_headings"] = True
            if count_numbered_steps(body) >= 3:
                checks["has_at_least_three_numbered_steps"] = True
            # Why this skill metrics required
            body_lower = body.lower()
            has_time = re.search(r'time\s*saved', body_lower) is not None
            has_freq = re.search(r'\bfrequency\b', body_lower) is not None
            has_value = re.search(r'\bvalue(\s*score)?\b', body_lower) is not None
            if has_time and has_freq and has_value:
                checks["why_section_has_metrics"] = True
        else:
            skill_dir_name = os.path.basename(skill_dir)
    else:
        skill_dir = None
        skill_dir_name = None

    # Validate pattern-tracker.json
    pt_path = os.path.join(output_dir, "pattern-tracker.json")
    pt = load_json(pt_path)
    if isinstance(pt, dict) and "patterns" in pt and "stats" in pt and isinstance(pt.get("patterns"), list) and isinstance(pt.get("stats"), dict):
        # Check at least one valid pattern object
        valid_pattern_found = False
        linked_to_skill = False
        for p in pt["patterns"]:
            if not isinstance(p, dict):
                continue
            id_ok = isinstance(p.get("id"), str) and len(p.get("id")) > 0
            workflow_ok = isinstance(p.get("workflow"), str) and len(p.get("workflow")) > 0
            signals_ok = isinstance(p.get("signals"), list) and len(p.get("signals")) >= 1
            score_ok = isinstance(p.get("score"), (int, float)) and p.get("score") >= 7
            date_ok = isinstance(p.get("firstSeen"), str) and re.match(r'^\d{4}-\d{2}-\d{2}$', p.get("firstSeen")) is not None
            times_ok = isinstance(p.get("timesSeen"), (int, float)) and p.get("timesSeen") >= 2
            suggested_ok = p.get("suggested") is True
            accepted_ok = p.get("accepted") is None or isinstance(p.get("accepted"), bool)
            skill_created_ok = isinstance(p.get("skillCreated"), str) and len(p.get("skillCreated")) > 0
            if id_ok and workflow_ok and signals_ok and score_ok and date_ok and times_ok and suggested_ok and accepted_ok and skill_created_ok:
                valid_pattern_found = True
                if skill_dir_name and p.get("skillCreated") == skill_dir_name:
                    linked_to_skill = True
        if valid_pattern_found:
            checks["pattern_tracker_has_required_fields"] = True
        if linked_to_skill:
            checks["pattern_tracker_skill_linked"] = True
        # Stats increment present
        stats = pt.get("stats", {})
        # At least one numeric counter >=1 among patternsDetected or skillsSuggested (or other plausible keys)
        increment_keys = ["patternsDetected", "skillsSuggested", "skillsAccepted", "skillsDeclined"]
        inc_present = False
        for k, v in stats.items():
            if k in increment_keys and isinstance(v, (int, float)) and v >= 1:
                inc_present = True
                break
        if inc_present:
            checks["pattern_tracker_stats_increment"] = True

    # Validate skills-audit.json
    audit_path = os.path.join(output_dir, "skills-audit.json")
    audit = load_json(audit_path)
    if isinstance(audit, list):
        checks["skills_audit_valid"] = True
        if len(audit) >= 3:
            checks["skills_audit_length_ok"] = True
        # Check each entry schema
        schema_ok = True
        includes_new = False
        fm_name = None
        # Try to get frontmatter name for matching
        # Re-use earlier parsed fields if available
        # If we didn't parse, attempt to parse now if possible
        if skill_dir and os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
            md_content = read_text(os.path.join(skill_dir, "SKILL.md")) or ""
            ok_fm2, fields2, _ = parse_frontmatter(md_content)
            if ok_fm2:
                fm_name = fields2.get("name")
        for entry in audit:
            if not isinstance(entry, dict):
                schema_ok = False
                break
            # Required keys
            keys_needed = ["skill_name", "clarity", "completeness", "format", "triggers", "overall", "suggestions"]
            if not all(k in entry for k in keys_needed):
                schema_ok = False
                break
            # Types and ranges
            if not isinstance(entry["skill_name"], str):
                schema_ok = False
                break
            if not (isinstance(entry["clarity"], int) and 1 <= entry["clarity"] <= 10):
                schema_ok = False
                break
            if not (isinstance(entry["completeness"], int) and 1 <= entry["completeness"] <= 10):
                schema_ok = False
                break
            if not (isinstance(entry["format"], int) and 1 <= entry["format"] <= 10):
                schema_ok = False
                break
            if not (isinstance(entry["triggers"], int) and 1 <= entry["triggers"] <= 10):
                schema_ok = False
                break
            if entry["overall"] not in ["A", "B", "C", "D", "F"]:
                schema_ok = False
                break
            if not isinstance(entry["suggestions"], list):
                schema_ok = False
                break
            # Include new skill check
            if skill_dir_name and (entry["skill_name"] == skill_dir_name or (fm_name and entry["skill_name"] == fm_name)):
                includes_new = True
        if schema_ok:
            checks["skills_audit_entries_schema_ok"] = True
        if includes_new:
            checks["skills_audit_includes_new_skill"] = True

    # Validate summary.txt
    summary_path = os.path.join(output_dir, "summary.txt")
    summary_txt = read_text(summary_path)
    if summary_txt is not None:
        # Contains the detected workflow (check for the word 'workflow' and some length)
        has_workflow_word = re.search(r'\bworkflow\b', summary_txt, flags=re.IGNORECASE) is not None
        has_two_signals = summary_has_two_signals(summary_txt)
        if has_workflow_word and has_two_signals:
            checks["summary_includes_workflow_and_signals"] = True
        # Contains the new skill directory name
        if skill_dir_name and skill_dir_name in summary_txt:
            checks["summary_includes_skill_dir_name"] = True
        # Contains a stats key name and its value (e.g., patternsDetected: 1)
        stats_keys = ["patternsDetected", "skillsSuggested", "skillsAccepted", "skillsDeclined"]
        stats_ok = False
        for k in stats_keys:
            # Look for 'key' followed by some non-digit chars then a number
            if re.search(rf'\b{k}\b[^\d\n]*\d+', summary_txt):
                stats_ok = True
                break
        if stats_ok:
            checks["summary_includes_stats_update"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Explicit no-op baseline: if required artifacts missing (e.g., no skill dir and no pattern tracker and no audit and no summary) set reward to 0.0
    # This will already be the case since passed == 0. Ensure precision.
    if passed == 0:
        reward = 0.0

    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()