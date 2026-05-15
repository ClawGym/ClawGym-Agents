import json
import os
import re
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def count_lines(text):
    return 0 if text is None else len([ln for ln in text.splitlines()])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) curated_list.txt checks
        "curated_exists": False,
        "curated_non_empty": False,
        "curated_min_lines": False,
        "curated_min_date_lines": False,
        # 2) context_summary.md checks
        "context_exists": False,
        "context_has_markers": False,
        # 3) roadmap.json checks
        "roadmap_exists": False,
        "roadmap_valid_json": False,
        "roadmap_required_keys_present": False,
        "roadmap_phases_len_ge_3": False,
        "roadmap_skillgaps_nonempty": False,
        "roadmap_recommendations_nonempty": False,
        "roadmap_session_match_input": False,
        # 4) update_summary.md checks
        "update_exists": False,
        "update_header_has_emoji_phrase": False,
        "update_core_version_arrow": False,
        "update_has_sections_updated_current": False,
        "update_has_failure_marker_when_failed": False,
        # 5) README.md checks
        "readme_exists": False,
        "readme_mentions_all_four": False,
        "readme_reproduce_relative_paths": False,
    }

    # 1) curated_list.txt
    curated_path = os.path.join(output_dir, "curated_list.txt")
    curated_text = None
    if os.path.isfile(curated_path):
        checks["curated_exists"] = True
        curated_text = read_text(curated_path)
        if curated_text:
            checks["curated_non_empty"] = len(curated_text.strip()) > 0
            total_lines = count_lines(curated_text)
            checks["curated_min_lines"] = total_lines >= 5
            date_pattern = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\s", re.MULTILINE)
            date_lines = date_pattern.findall(curated_text or "")
            # Count lines matching the pattern; using re to find matches per line prefix:
            # We will count matches by iterating lines.
            if curated_text:
                date_count = 0
                for ln in curated_text.splitlines():
                    if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\s", ln):
                        date_count += 1
                checks["curated_min_date_lines"] = date_count >= 5

    # 2) context_summary.md
    context_path = os.path.join(output_dir, "context_summary.md")
    context_text = None
    if os.path.isfile(context_path):
        checks["context_exists"] = True
        context_text = read_text(context_path) or ""
        required_markers = [
            "## Context Loaded",
            "Current Phase:",
            "Active Milestone:",
            "Current Task:",
            "Stale Warnings:",
        ]
        checks["context_has_markers"] = all(marker in context_text for marker in required_markers)

    # 3) roadmap.json
    roadmap_path = os.path.join(output_dir, "roadmap.json")
    roadmap_obj = None
    if os.path.isfile(roadmap_path):
        checks["roadmap_exists"] = True
        roadmap_obj = read_json(roadmap_path)
        if isinstance(roadmap_obj, dict):
            checks["roadmap_valid_json"] = True
            required_keys = ["roadmapId", "sessionId", "generatedAt", "timeline", "phases", "skillGaps", "recommendations"]
            has_keys = all(k in roadmap_obj for k in required_keys)
            types_ok = (
                isinstance(roadmap_obj.get("roadmapId"), str) and
                isinstance(roadmap_obj.get("sessionId"), str) and
                isinstance(roadmap_obj.get("generatedAt"), str) and
                isinstance(roadmap_obj.get("timeline"), str) and
                isinstance(roadmap_obj.get("phases"), list) and
                isinstance(roadmap_obj.get("skillGaps"), list) and
                isinstance(roadmap_obj.get("recommendations"), list)
            )
            checks["roadmap_required_keys_present"] = has_keys and types_ok
            if isinstance(roadmap_obj.get("phases"), list):
                checks["roadmap_phases_len_ge_3"] = len(roadmap_obj.get("phases")) >= 3
            if isinstance(roadmap_obj.get("skillGaps"), list):
                checks["roadmap_skillgaps_nonempty"] = len(roadmap_obj.get("skillGaps")) > 0
            if isinstance(roadmap_obj.get("recommendations"), list):
                checks["roadmap_recommendations_nonempty"] = len(roadmap_obj.get("recommendations")) > 0

            # sessionId match with input/assessment.json
            assessment_path = os.path.join(input_dir, "assessment.json")
            assessment_obj = read_json(assessment_path)
            if isinstance(assessment_obj, dict):
                # Expect assessmentData.sessionId in the input
                session_from_input = None
                assessment_data = assessment_obj.get("assessmentData")
                if isinstance(assessment_data, dict):
                    session_from_input = assessment_data.get("sessionId")
                # Fallback: try top-level sessionId as per sample input structure
                if session_from_input is None:
                    session_from_input = assessment_obj.get("sessionId")
                if isinstance(session_from_input, str):
                    checks["roadmap_session_match_input"] = roadmap_obj.get("sessionId") == session_from_input

    # 4) update_summary.md
    update_path = os.path.join(output_dir, "update_summary.md")
    update_text = None
    if os.path.isfile(update_path):
        checks["update_exists"] = True
        update_text = read_text(update_path) or ""
        lines = update_text.splitlines()
        header_line = lines[0] if lines else ""
        checks["update_header_has_emoji_phrase"] = ("🔄" in header_line) and ("Daily Auto-Update" in header_line)
        # core version line with arrow
        arrow_present = any("→" in ln for ln in lines)
        v_before_after_present = any(("→" in ln) and ("v" in ln) for ln in lines)
        checks["update_core_version_arrow"] = arrow_present and v_before_after_present
        # sections updated/current
        has_updated_section = any("Skills Updated" in ln for ln in lines)
        has_current_section = any("Skills Already Current" in ln for ln in lines)
        checks["update_has_sections_updated_current"] = has_updated_section and has_current_section

        # failure marker conditionally required
        # Read input/update_events.json to check if failures exist
        update_events_path = os.path.join(input_dir, "update_events.json")
        input_update = read_json(update_events_path)
        has_failures_in_input = False
        if isinstance(input_update, dict):
            skills_failed = input_update.get("skillsFailed")
            if isinstance(skills_failed, list) and len(skills_failed) > 0:
                has_failures_in_input = True
        if has_failures_in_input:
            checks["update_has_failure_marker_when_failed"] = "❌" in update_text
        else:
            # If no failures reported in input, consider this requirement satisfied only if output exists
            checks["update_has_failure_marker_when_failed"] = True

    # 5) README.md
    readme_path = os.path.join(output_dir, "README.md")
    readme_text = None
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme_text = read_text(readme_path) or ""
        mentions_curated = "curated_list.txt" in readme_text
        mentions_context = "context_summary.md" in readme_text
        mentions_roadmap = "roadmap.json" in readme_text
        mentions_update = "update_summary.md" in readme_text
        checks["readme_mentions_all_four"] = all([mentions_curated, mentions_context, mentions_roadmap, mentions_update])
        # Reproduce instructions using relative paths: require presence of input/ and output/ and the word "relative"
        has_input_ref = "input/" in readme_text
        has_output_ref = "output/" in readme_text
        mentions_relative = "relative" in readme_text.lower()
        checks["readme_reproduce_relative_paths"] = has_input_ref and has_output_ref and mentions_relative and mentions_curated

    # Compute reward as average of passed checks among all defined checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure numeric bounds [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()