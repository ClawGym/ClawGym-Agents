import json
import os
import re
import sys

def count_words(text):
    # Count words by splitting on whitespace
    return len([w for w in re.split(r"\s+", text.strip()) if w])

def extract_sections(lines, summary_type):
    """
    Given file lines and expected summary_type ("Brief" or "Extended"),
    extract:
      - header line and declared count
      - body lines between header and "💡 KEY POINTS"
      - key points section lines after "💡 KEY POINTS" and before "⚠️ OMITTED" or Sources
      - omitted section lines after "⚠️ OMITTED" and before Sources
      - last non-empty line text
    Returns a dict with parsed components and positions.
    """
    result = {
        "header_valid": False,
        "declared_count": None,
        "header_index": None,
        "keypoints_index": None,
        "omitted_index": None,
        "sources_line": None,
        "body_text": "",
        "keypoint_bullet_lines": [],
        "has_keypoints_section": False,
        "has_omitted_section": False,
        "omitted_content_lines": [],
    }

    # Normalize lines by keeping original but also compute stripped variants
    stripped = [ln.rstrip("\n") for ln in lines]
    # Find first non-empty line (header)
    header_idx = None
    for i, ln in enumerate(stripped):
        if ln.strip():
            header_idx = i
            break

    if header_idx is None:
        return result  # no content

    header_line = stripped[header_idx].strip()

    # Match header pattern
    if summary_type == "Brief":
        m = re.fullmatch(r"📝 SUMMARY \(Brief: (\d+)\)", header_line)
    else:
        m = re.fullmatch(r"📝 SUMMARY \(Extended: (\d+)\)", header_line)

    if m:
        result["header_valid"] = True
        result["declared_count"] = int(m.group(1))
        result["header_index"] = header_idx

    # Find indices for sections
    keypoints_idx = None
    omitted_idx = None
    for i in range(header_idx + 1 if header_idx is not None else 0, len(stripped)):
        if stripped[i].strip() == "💡 KEY POINTS":
            keypoints_idx = i
            break
    if keypoints_idx is not None:
        result["has_keypoints_section"] = True
        result["keypoints_index"] = keypoints_idx

    for i in range((keypoints_idx + 1) if keypoints_idx is not None else 0, len(stripped)):
        if stripped[i].strip() == "⚠️ OMITTED":
            omitted_idx = i
            break
    if omitted_idx is not None:
        result["has_omitted_section"] = True
        result["omitted_index"] = omitted_idx

    # Find last non-empty line (for Sources check)
    last_nonempty = ""
    for ln in reversed(stripped):
        if ln.strip():
            last_nonempty = ln.strip()
            break
    result["sources_line"] = last_nonempty

    # Extract body text: between header and keypoints section
    if result["header_valid"] and keypoints_idx is not None:
        body_lines = stripped[header_idx + 1:keypoints_idx]
        # Keep all lines; join with spaces to count words across paragraphs consistently
        # Exclude empty lines in counting by join with space
        body_text = "\n".join(body_lines).strip()
        result["body_text"] = body_text

    # Extract key points bullet lines: between keypoints and omitted (or sources/end)
    if keypoints_idx is not None:
        end_idx_for_kp = omitted_idx if omitted_idx is not None else len(stripped)
        kp_section_lines = stripped[keypoints_idx + 1:end_idx_for_kp]
        bullet_lines = [ln for ln in kp_section_lines if ln.strip().startswith("• ")]
        result["keypoint_bullet_lines"] = bullet_lines

    # Extract omitted content lines: between omitted and Sources/end
    if omitted_idx is not None:
        # Up to the end or the sources line (we do not know index of sources, but we'll exclude the exact sources line at the end when checking content)
        omitted_content = stripped[omitted_idx + 1:]
        # Remove any trailing empty lines at end
        while omitted_content and not omitted_content[-1].strip():
            omitted_content.pop()
        # If last non-empty line is Sources, remove it from omitted_content
        if result["sources_line"] and omitted_content:
            # find last non-empty index in omitted_content
            j = len(omitted_content) - 1
            while j >= 0 and not omitted_content[j].strip():
                j -= 1
            if j >= 0 and omitted_content[j].strip() == result["sources_line"]:
                omitted_content = omitted_content[:j]
                # Also strip trailing empties again
                while omitted_content and not omitted_content[-1].strip():
                    omitted_content.pop()
        result["omitted_content_lines"] = omitted_content

    return result

def evaluate_executive(path):
    checks = {
        "exec_file_exists": False,
        "exec_header_pattern": False,
        "exec_body_word_count_leq_110": False,
        "exec_declared_matches_body_within_15": False,
        "exec_keypoints_section_present": False,
        "exec_keypoints_bullets_3_to_5": False,
        "exec_omitted_section_present": False,
        "exec_omitted_has_content": False,
        "exec_sources_line_exact": False,
    }
    if not os.path.isfile(path):
        return checks

    checks["exec_file_exists"] = True
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    parsed = extract_sections(lines, "Brief")

    if parsed["header_valid"]:
        checks["exec_header_pattern"] = True

    # Body word count and declared comparison
    body_text = parsed["body_text"]
    if body_text:
        body_count = count_words(body_text)
        if body_count <= 110:
            checks["exec_body_word_count_leq_110"] = True
        if parsed["declared_count"] is not None and abs(body_count - parsed["declared_count"]) <= 15:
            checks["exec_declared_matches_body_within_15"] = True

    # Key points section and bullets
    if parsed["has_keypoints_section"]:
        checks["exec_keypoints_section_present"] = True
        num_bullets = len(parsed["keypoint_bullet_lines"])
        if 3 <= num_bullets <= 5:
            checks["exec_keypoints_bullets_3_to_5"] = True

    # Omitted section presence and content
    if parsed["has_omitted_section"]:
        checks["exec_omitted_section_present"] = True
        # At least one non-empty line
        has_content = any(ln.strip() for ln in parsed["omitted_content_lines"])
        if has_content:
            checks["exec_omitted_has_content"] = True

    # Sources line exact match
    expected_sources = "Sources: input/product_strategy.md, input/user_interviews.jsonl, input/analytics.csv"
    if parsed["sources_line"] == expected_sources:
        checks["exec_sources_line_exact"] = True

    return checks

def evaluate_technical(path):
    checks = {
        "tech_file_exists": False,
        "tech_header_pattern": False,
        "tech_body_word_count_between_220_380": False,
        "tech_declared_matches_body_within_30": False,
        "tech_keypoints_section_present": False,
        "tech_keypoints_bullets_5_to_8": False,
        "tech_omitted_valid": False,  # True if omitted section absent OR present with non-empty content
        "tech_sources_line_exact": False,
    }
    if not os.path.isfile(path):
        return checks

    checks["tech_file_exists"] = True
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    parsed = extract_sections(lines, "Extended")

    if parsed["header_valid"]:
        checks["tech_header_pattern"] = True

    # Body word count and declared comparison
    body_text = parsed["body_text"]
    if body_text:
        body_count = count_words(body_text)
        if 220 <= body_count <= 380:
            checks["tech_body_word_count_between_220_380"] = True
        if parsed["declared_count"] is not None and abs(body_count - parsed["declared_count"]) <= 30:
            checks["tech_declared_matches_body_within_30"] = True

    # Key points section and bullets
    if parsed["has_keypoints_section"]:
        checks["tech_keypoints_section_present"] = True
        num_bullets = len(parsed["keypoint_bullet_lines"])
        if 5 <= num_bullets <= 8:
            checks["tech_keypoints_bullets_5_to_8"] = True

    # Omitted section optional: valid if absent, or present with at least one non-empty line
    if not parsed["has_omitted_section"]:
        checks["tech_omitted_valid"] = True
    else:
        has_content = any(ln.strip() for ln in parsed["omitted_content_lines"])
        if has_content:
            checks["tech_omitted_valid"] = True

    # Sources line exact match
    expected_sources = "Sources: input/product_strategy.md, input/user_interviews.jsonl, input/analytics.csv"
    if parsed["sources_line"] == expected_sources:
        checks["tech_sources_line_exact"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    exec_path = os.path.join(output_dir, "executive_brief.md")
    tech_path = os.path.join(output_dir, "technical_summary.md")

    checks = {}
    exec_checks = evaluate_executive(exec_path)
    tech_checks = evaluate_technical(tech_path)
    checks.update(exec_checks)
    checks.update(tech_checks)

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)

    reward = 0.0
    if total > 0:
        reward = passed / total

    # Print single JSON object
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()