import json
import os
import sys

def is_non_empty_string(v):
    return isinstance(v, str) and len(v.strip()) > 0

def is_positive_int(v):
    return isinstance(v, int) and v > 0

def is_number_ge_one(v):
    return (isinstance(v, int) or isinstance(v, float)) and v >= 1

def validate_top_level(obj):
    # Required top-level keys and basic types
    required = {
        "roadmapId": str,
        "sessionId": str,
        "generatedAt": str,
        "phases": list,
        "skillGaps": list,
        "milestones": list,
        "recommendedResources": dict,
    }
    for k, t in required.items():
        if k not in obj:
            return False
        if not isinstance(obj[k], t):
            return False
    # Strings should be non-empty for id/session/time
    if not (is_non_empty_string(obj["roadmapId"]) and is_non_empty_string(obj["sessionId"]) and is_non_empty_string(obj["generatedAt"])):
        return False
    return True

def validate_phases(phases):
    if not isinstance(phases, list) or len(phases) < 3:
        return False
    for p in phases:
        if not isinstance(p, dict):
            return False
        if "phase" not in p or "title" not in p or "duration" not in p or "objectives" not in p or "coursework" not in p or "projects" not in p or "certifications" not in p:
            return False
        if not isinstance(p["phase"], int):
            return False
        if not is_non_empty_string(p["title"]):
            return False
        if not is_non_empty_string(p["duration"]):
            return False
        if not isinstance(p["objectives"], list) or len(p["objectives"]) < 2:
            return False
        if not isinstance(p["coursework"], list) or len(p["coursework"]) < 1:
            return False
        if not isinstance(p["projects"], list) or len(p["projects"]) < 1:
            return False
        if not isinstance(p["certifications"], list):
            return False
    return True

def validate_skill_gaps(skill_gaps):
    if not isinstance(skill_gaps, list) or len(skill_gaps) < 2:
        return False
    for sg in skill_gaps:
        if not isinstance(sg, dict):
            return False
        for k in ("skill", "currentLevel", "targetLevel"):
            if k not in sg or not isinstance(sg[k], str):
                return False
    return True

def validate_milestones(milestones):
    if not isinstance(milestones, list) or len(milestones) < 3:
        return False
    for m in milestones:
        if not isinstance(m, dict):
            return False
        if "month" not in m or "description" not in m:
            return False
        if not is_positive_int(m["month"]):
            return False
        if not is_non_empty_string(m["description"]):
            return False
    return True

def validate_resources(resources):
    if not isinstance(resources, dict):
        return False
    needed = ["courses", "books", "tutorials", "projects", "certifications"]
    for k in needed:
        if k not in resources:
            return False
        if not is_number_ge_one(resources[k]):
            return False
    return True

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    fg_path = os.path.join(output_dir, "fresh_grad", "roadmap.json")
    sw_path = os.path.join(output_dir, "switcher", "roadmap.json")
    cmp_path = os.path.join(output_dir, "comparison.md")

    checks = {
        "fg_exists": False,
        "fg_valid_json": False,
        "fg_has_required_keys": False,
        "fg_phases_structure": False,
        "fg_skillgaps_structure": False,
        "fg_milestones_structure": False,
        "fg_resources_structure": False,
        "sw_exists": False,
        "sw_valid_json": False,
        "sw_has_required_keys": False,
        "sw_phases_structure": False,
        "sw_skillgaps_structure": False,
        "sw_milestones_structure": False,
        "sw_resources_structure": False,
        "files_distinct": False,
        "comparison_exists": False,
        "comparison_has_sections": False,
        "comparison_mentions_profiles": False,
    }

    fg_obj = None
    sw_obj = None

    # Fresh Grad
    if os.path.isfile(fg_path):
        checks["fg_exists"] = True
        fg_obj = read_json(fg_path)
        if isinstance(fg_obj, dict):
            checks["fg_valid_json"] = True
            if validate_top_level(fg_obj):
                checks["fg_has_required_keys"] = True
                if validate_phases(fg_obj.get("phases", [])):
                    checks["fg_phases_structure"] = True
                if validate_skill_gaps(fg_obj.get("skillGaps", [])):
                    checks["fg_skillgaps_structure"] = True
                if validate_milestones(fg_obj.get("milestones", [])):
                    checks["fg_milestones_structure"] = True
                if validate_resources(fg_obj.get("recommendedResources", {})):
                    checks["fg_resources_structure"] = True

    # Switcher
    if os.path.isfile(sw_path):
        checks["sw_exists"] = True
        sw_obj = read_json(sw_path)
        if isinstance(sw_obj, dict):
            checks["sw_valid_json"] = True
            if validate_top_level(sw_obj):
                checks["sw_has_required_keys"] = True
                if validate_phases(sw_obj.get("phases", [])):
                    checks["sw_phases_structure"] = True
                if validate_skill_gaps(sw_obj.get("skillGaps", [])):
                    checks["sw_skillgaps_structure"] = True
                if validate_milestones(sw_obj.get("milestones", [])):
                    checks["sw_milestones_structure"] = True
                if validate_resources(sw_obj.get("recommendedResources", {})):
                    checks["sw_resources_structure"] = True

    # Distinctness check (only if both parsed)
    if isinstance(fg_obj, dict) and isinstance(sw_obj, dict):
        try:
            if fg_obj.get("sessionId") != sw_obj.get("sessionId"):
                checks["files_distinct"] = True
            else:
                # Compare phases content
                if fg_obj.get("phases") != sw_obj.get("phases"):
                    checks["files_distinct"] = True
        except Exception:
            checks["files_distinct"] = False

    # Comparison file checks
    if os.path.isfile(cmp_path):
        checks["comparison_exists"] = True
        txt = read_text(cmp_path)
        if isinstance(txt, str):
            low = txt.lower()
            required_markers = [
                "starting points",
                "per-phase comparison",
                "top 3 skill gaps",
                "30-60-90",
                "resource preferences",
                "timeline alignment",
            ]
            if all(m in low for m in required_markers):
                checks["comparison_has_sections"] = True
            if ("fresh grad" in low) and ("career switcher" in low):
                checks["comparison_mentions_profiles"] = True

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()