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

def find_first_matching_file(directory, pattern):
    try:
        rx = re.compile(pattern)
        for name in os.listdir(directory):
            if rx.fullmatch(name):
                return os.path.join(directory, name)
    except Exception:
        pass
    return None

def extract_mission_strings(obj):
    missions = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and "mission" in k.lower():
                    if isinstance(v, str):
                        missions.append(v.strip())
                    elif isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                missions.append(item.strip())
                # Recurse
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(obj)
    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for m in missions:
        if m and m not in seen:
            ordered.append(m)
            seen.add(m)
    return ordered

def load_json(path):
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None

def has_substring_ci(text, substring):
    return substring.lower() in text.lower()

def any_line_contains_both(text, token, char):
    for line in text.splitlines():
        if token.lower() in line.lower() and char in line:
            return True
    return False

def extract_taglines_from_voice(voice_text):
    lines = voice_text.splitlines()
    taglines = set()

    # Helper to clean a tagline-like phrase
    def clean(s):
        s = s.strip()
        # Strip leading bullet markers
        if s.startswith("- ") or s.startswith("* "):
            s = s[2:].strip()
        # Remove leading labels like "Primary:" or "Secondary:"
        s = re.sub(r'^(Primary|Secondary|Alt|Alternate)\s*:\s*', '', s, flags=re.IGNORECASE).strip()
        # Remove surrounding quotes
        s = s.strip('\'"').strip()
        return s

    # Collect from Tagline sections
    indices = [i for i, ln in enumerate(lines) if "tagline" in ln.lower()]
    for idx in indices:
        for j in range(idx + 1, min(idx + 11, len(lines))):
            ln = lines[j].strip()
            if not ln:
                continue
            # Stop if next header
            if ln.startswith("#"):
                break
            if ln.startswith("- ") or ln.startswith("* "):
                t = clean(ln)
                if 3 <= len(t) <= 100:
                    taglines.add(t)
            elif ":" in ln and any(key in ln.lower() for key in ["primary", "secondary"]):
                parts = ln.split(":", 1)
                t = clean(parts[1])
                if 3 <= len(t) <= 100:
                    taglines.add(t)
            else:
                # If line is short and sentence-like, consider as possible tagline
                if 3 <= len(ln) <= 80 and len(ln.split()) <= 10:
                    t = clean(ln)
                    if 3 <= len(t) <= 100:
                        taglines.add(t)

    # Fallback: quoted phrases anywhere
    for ln in lines:
        for m in re.findall(r'["“](.+?)["”]', ln):
            t = clean(m)
            if 3 <= len(t) <= 100:
                taglines.add(t)

    # Add example taglines mentioned in task as fallback (will not harm if also present in voice)
    taglines.update({"Charge with confidence", "Powering every mile"})

    # Return as list preserving order (approximate by insertion into list)
    seen = set()
    ordered = []
    for t in taglines:
        tl = t.strip()
        if tl and tl.lower() not in seen:
            ordered.append(tl)
            seen.add(tl.lower())
    return ordered

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # File existence and naming
        "analysis_file_exists": False,
        "analysis_filename_pattern_ok": False,
        "guidelines_file_exists": False,
        "guidelines_filename_pattern_ok": False,

        # Brand name presence
        "analysis_contains_brand_name": False,
        "guidelines_contains_brand_name": False,

        # Analysis required content
        "analysis_contains_mission": False,
        "analysis_has_exec_summary_header": False,
        "analysis_has_brand_identity_header": False,
        "analysis_has_visual_identity_header": False,
        "analysis_has_voice_messaging_header": False,
        "analysis_has_target_audience_header": False,
        "analysis_has_competitive_positioning_header": False,
        "analysis_has_touchpoint_audit_header": False,
        "analysis_has_implementation_roadmap_header": False,
        "analysis_has_success_metrics_header": False,
        "analysis_has_touchpoint_table_header_exact": False,
        "analysis_has_website_row": False,
        "analysis_has_social_media_row": False,
        "analysis_has_email_row": False,
        "analysis_contains_archetype_word": False,
        "analysis_has_target_percent_line": False,

        # Guidelines required content
        "guidelines_has_brand_story_header": False,
        "guidelines_has_visual_identity_header": False,
        "guidelines_has_voice_messaging_header": False,
        "guidelines_has_brand_applications_header": False,
        "guidelines_has_consistency_checklist_header": False,
        "guidelines_contains_hex_1E88E5": False,
        "guidelines_contains_hex_00C853": False,
        "guidelines_contains_font_inter": False,
        "guidelines_contains_font_source_sans_pro": False,
        "guidelines_contains_wcag": False,
        "guidelines_contains_tagline_from_voice": False,
    }

    # Prepare input references
    brand_brief_path = os.path.join(input_dir, "brand_brief.json")
    voice_messaging_path = os.path.join(input_dir, "voice_messaging.md")

    # Load mission strings from JSON
    mission_strings = []
    brand_brief = load_json(brand_brief_path)
    if brand_brief is not None:
        mission_strings = extract_mission_strings(brand_brief)

    # Load voice taglines
    voice_text = read_text(voice_messaging_path)
    voice_taglines = extract_taglines_from_voice(voice_text)

    # Find output files
    analysis_pattern = r"brand-analysis-AuroraCharge-\d{4}-\d{2}-\d{2}\.md"
    guidelines_pattern = r"brand-guidelines-AuroraCharge-\d{4}-\d{2}-\d{2}\.md"

    analysis_path = None
    guidelines_path = None

    if os.path.isdir(output_dir):
        analysis_path = find_first_matching_file(output_dir, analysis_pattern)
        guidelines_path = find_first_matching_file(output_dir, guidelines_pattern)

    # Process analysis file
    analysis_content = ""
    if analysis_path and os.path.isfile(analysis_path):
        checks["analysis_file_exists"] = True
        if re.fullmatch(analysis_pattern, os.path.basename(analysis_path)) is not None:
            checks["analysis_filename_pattern_ok"] = True

        analysis_content = read_text(analysis_path)

        # Brand name
        if "AuroraCharge" in analysis_content:
            checks["analysis_contains_brand_name"] = True

        # Mission presence (exact string match for any mission found)
        if mission_strings:
            for m in mission_strings:
                if m and m in analysis_content:
                    checks["analysis_contains_mission"] = True
                    break
        # If no mission found in input, do not award credit (remains False)

        # Section headers (case-insensitive)
        if has_substring_ci(analysis_content, "Executive Summary"):
            checks["analysis_has_exec_summary_header"] = True
        if has_substring_ci(analysis_content, "Brand Identity Analysis"):
            checks["analysis_has_brand_identity_header"] = True
        if has_substring_ci(analysis_content, "Visual Identity Analysis"):
            checks["analysis_has_visual_identity_header"] = True
        if has_substring_ci(analysis_content, "Voice and Messaging Analysis"):
            checks["analysis_has_voice_messaging_header"] = True
        if has_substring_ci(analysis_content, "Target Audience Analysis"):
            checks["analysis_has_target_audience_header"] = True
        if has_substring_ci(analysis_content, "Competitive Positioning"):
            checks["analysis_has_competitive_positioning_header"] = True
        if has_substring_ci(analysis_content, "Brand Touchpoint Audit"):
            checks["analysis_has_touchpoint_audit_header"] = True
        if has_substring_ci(analysis_content, "Implementation Roadmap"):
            checks["analysis_has_implementation_roadmap_header"] = True
        if has_substring_ci(analysis_content, "Success Metrics"):
            checks["analysis_has_success_metrics_header"] = True

        # Touchpoint table header exact line
        if "Touchpoint | Consistency | Quality | Notes" in analysis_content:
            checks["analysis_has_touchpoint_table_header_exact"] = True

        # Rows for Website, Social Media, Email (look for lines with token and a pipe)
        if any_line_contains_both(analysis_content, "Website", "|"):
            checks["analysis_has_website_row"] = True
        if any_line_contains_both(analysis_content, "Social Media", "|"):
            checks["analysis_has_social_media_row"] = True
        if any_line_contains_both(analysis_content, "Email", "|"):
            checks["analysis_has_email_row"] = True

        # Archetype presence
        if re.search(r"archetype", analysis_content, flags=re.IGNORECASE):
            checks["analysis_contains_archetype_word"] = True

        # Target percent line
        for line in analysis_content.splitlines():
            if re.search(r"target", line, flags=re.IGNORECASE) and "%" in line:
                checks["analysis_has_target_percent_line"] = True
                break

    # Process guidelines file
    guidelines_content = ""
    if guidelines_path and os.path.isfile(guidelines_path):
        checks["guidelines_file_exists"] = True
        if re.fullmatch(guidelines_pattern, os.path.basename(guidelines_path)) is not None:
            checks["guidelines_filename_pattern_ok"] = True

        guidelines_content = read_text(guidelines_path)

        # Brand name
        if "AuroraCharge" in guidelines_content:
            checks["guidelines_contains_brand_name"] = True

        # Section headers (case-insensitive)
        if has_substring_ci(guidelines_content, "Brand Story"):
            checks["guidelines_has_brand_story_header"] = True
        if has_substring_ci(guidelines_content, "Visual Identity"):
            checks["guidelines_has_visual_identity_header"] = True
        if has_substring_ci(guidelines_content, "Voice and Messaging"):
            checks["guidelines_has_voice_messaging_header"] = True
        if has_substring_ci(guidelines_content, "Brand Applications"):
            checks["guidelines_has_brand_applications_header"] = True
        if has_substring_ci(guidelines_content, "Brand Consistency Checklist"):
            checks["guidelines_has_consistency_checklist_header"] = True

        # Hex codes (case-insensitive)
        gl_lower = guidelines_content.lower()
        if "#1e88e5" in gl_lower:
            checks["guidelines_contains_hex_1E88E5"] = True
        if "#00c853" in gl_lower:
            checks["guidelines_contains_hex_00C853"] = True

        # Fonts (case-insensitive substring)
        if re.search(r"\bInter\b", guidelines_content, flags=re.IGNORECASE):
            checks["guidelines_contains_font_inter"] = True
        if re.search(r"\bSource\s+Sans\s+Pro\b", guidelines_content, flags=re.IGNORECASE):
            checks["guidelines_contains_font_source_sans_pro"] = True

        # WCAG mention
        if "wcag" in gl_lower:
            checks["guidelines_contains_wcag"] = True

        # Tagline from voice messaging
        gl_lower_full = guidelines_content.lower()
        for t in voice_taglines:
            if t and t.lower() in gl_lower_full:
                checks["guidelines_contains_tagline_from_voice"] = True
                break

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if both files are missing or output dir missing, reward must be 0.0
    if not checks["analysis_file_exists"] and not checks["guidelines_file_exists"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()