import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Roadmap JSON checks
        "has_roadmap_file": False,
        "roadmap_parsed": False,
        "roadmap_has_required_top_keys": False,
        "roadmap_current_profile_fields": False,
        "roadmap_target_profile_fields": False,
        "roadmap_phases_valid": False,

        # Moralis overview checks
        "moralis_file_exists": False,
        "moralis_has_required_keywords": False,
        "moralis_has_questions_section": False,
        "moralis_has_q_line": False,
        "moralis_has_a_line": False,

        # NAS checklist checks
        "nas_file_exists": False,
        "nas_contains_required_phrases": False,

        # Paradox analysis checks
        "paradox_file_exists": False,
        "paradox_has_required_headings": False,
        "paradox_has_verification_line": False,
        "paradox_has_anchor_line": False,
    }

    # 1) Validate output/roadmap.json
    roadmap_path = os.path.join(output_dir, "roadmap.json")
    roadmap_obj = None
    if os.path.isfile(roadmap_path):
        checks["has_roadmap_file"] = True
        try:
            with open(roadmap_path, "r", encoding="utf-8") as f:
                roadmap_obj = json.load(f)
            checks["roadmap_parsed"] = True
        except Exception:
            roadmap_obj = None

    if roadmap_obj is not None and isinstance(roadmap_obj, dict):
        top_keys_required = ["roadmapId", "currentProfile", "targetProfile", "phases", "recommendedLearningResources", "nextSteps"]
        if all(k in roadmap_obj for k in top_keys_required):
            checks["roadmap_has_required_top_keys"] = True

        # currentProfile validation
        cp = roadmap_obj.get("currentProfile", {})
        cp_ok = (
            isinstance(cp, dict)
            and isinstance(cp.get("role"), str)
            and isinstance(cp.get("level"), str)
            and isinstance(cp.get("yearsExperience"), (int, float))
        )
        checks["roadmap_current_profile_fields"] = bool(cp_ok)

        # targetProfile validation
        tp = roadmap_obj.get("targetProfile", {})
        tp_ok = (
            isinstance(tp, dict)
            and isinstance(tp.get("role"), str)
            and isinstance(tp.get("level"), str)
            and isinstance(tp.get("estimatedTimeframe"), str)
        )
        checks["roadmap_target_profile_fields"] = bool(tp_ok)

        # phases validation
        phases = roadmap_obj.get("phases")
        phases_ok = isinstance(phases, list) and len(phases) >= 3
        if phases_ok:
            each_ok = True
            for item in phases:
                if not isinstance(item, dict):
                    each_ok = False
                    break
                # Required fields per phase
                if "phase" not in item or "duration" not in item or "title" not in item or "skills" not in item or "certifications" not in item or "projects" not in item:
                    each_ok = False
                    break
                if not isinstance(item.get("phase"), (int, float)):
                    each_ok = False
                    break
                if not isinstance(item.get("duration"), str):
                    each_ok = False
                    break
                if not isinstance(item.get("title"), str):
                    each_ok = False
                    break
                # skills, certifications, projects must be arrays of strings
                for key in ("skills", "certifications", "projects"):
                    arr = item.get(key)
                    if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
                        each_ok = False
                        break
                if not each_ok:
                    break
            phases_ok = phases_ok and each_ok
        checks["roadmap_phases_valid"] = bool(phases_ok)

    roadmap_valid = all([
        checks["has_roadmap_file"],
        checks["roadmap_parsed"],
        checks["roadmap_has_required_top_keys"],
        checks["roadmap_current_profile_fields"],
        checks["roadmap_target_profile_fields"],
        checks["roadmap_phases_valid"],
    ])

    # 2) Validate output/moralis_overview.md
    moralis_path = os.path.join(output_dir, "moralis_overview.md")
    moralis_text = ""
    if os.path.isfile(moralis_path):
        checks["moralis_file_exists"] = True
        try:
            with open(moralis_path, "r", encoding="utf-8", errors="replace") as f:
                moralis_text = f.read()
        except Exception:
            moralis_text = ""

    if moralis_text:
        # Required substrings
        req_keywords = ["Data API", "Streams", "Compute Units (CUs)", "Solana"]
        if all(kw in moralis_text for kw in req_keywords):
            checks["moralis_has_required_keywords"] = True

        if "Questions Answered" in moralis_text:
            checks["moralis_has_questions_section"] = True

        # Count lines starting with Q: and A:
        q_count = 0
        a_count = 0
        for line in moralis_text.splitlines():
            if line.startswith("Q:"):
                q_count += 1
            if line.startswith("A:"):
                a_count += 1
        checks["moralis_has_q_line"] = q_count >= 1
        checks["moralis_has_a_line"] = a_count >= 1

    moralis_valid = all([
        checks["moralis_file_exists"],
        checks["moralis_has_required_keywords"],
        checks["moralis_has_questions_section"],
        checks["moralis_has_q_line"],
        checks["moralis_has_a_line"],
    ])

    # 3) Validate output/nas_hardening_checklist.md
    nas_path = os.path.join(output_dir, "nas_hardening_checklist.md")
    nas_text = ""
    if os.path.isfile(nas_path):
        checks["nas_file_exists"] = True
        try:
            with open(nas_path, "r", encoding="utf-8", errors="replace") as f:
                nas_text = f.read()
        except Exception:
            nas_text = ""

    if nas_text:
        req_phrases = ["3-2-1", "Expose ZERO ports", "SMB", "NFS", "Disable admin", "UPS"]
        if all(p in nas_text for p in req_phrases):
            checks["nas_contains_required_phrases"] = True

    nas_valid = all([
        checks["nas_file_exists"],
        checks["nas_contains_required_phrases"],
    ])

    # 4) Validate output/paradox_analysis.md
    paradox_path = os.path.join(output_dir, "paradox_analysis.md")
    paradox_text = ""
    if os.path.isfile(paradox_path):
        checks["paradox_file_exists"] = True
        try:
            with open(paradox_path, "r", encoding="utf-8", errors="replace") as f:
                paradox_text = f.read()
        except Exception:
            paradox_text = ""

    expected_hash = "4716afb4c528c6a4c952d61cb96634c962856014736e06191c1b122f13dbce70"
    expected_anchor = "SCENAR_TEMPORAL_PARADOX_GLYPH"

    if paradox_text:
        # Headings presence (case-sensitive substrings)
        headings_ok = all([
            "Contradiction map" in paradox_text,
            "Inversion test" in paradox_text,
            "Essence extraction" in paradox_text,
            "Receipts" in paradox_text,
            "Misuse warning" in paradox_text,
        ])
        checks["paradox_has_required_headings"] = bool(headings_ok)

        # Verification line: starts with "Verification:" followed by the exact hash value
        ver_ok = False
        anc_ok = False
        for line in paradox_text.splitlines():
            if line.startswith("Verification:"):
                # Extract after colon and strip spaces
                after = line[len("Verification:"):].strip()
                if after == expected_hash:
                    ver_ok = True
            if line.startswith("Anchor:"):
                after_a = line[len("Anchor:"):].strip()
                if expected_anchor in after_a:
                    anc_ok = True
        checks["paradox_has_verification_line"] = ver_ok
        checks["paradox_has_anchor_line"] = anc_ok

    paradox_valid = all([
        checks["paradox_file_exists"],
        checks["paradox_has_required_headings"],
        checks["paradox_has_verification_line"],
        checks["paradox_has_anchor_line"],
    ])

    # Reward calculation: average of four artifact validations
    valid_bools = [roadmap_valid, moralis_valid, nas_valid, paradox_valid]
    reward = sum(1.0 if b else 0.0 for b in valid_bools) / 4.0

    # Ensure no-op baseline gets 0.0
    # (This is already satisfied since all files missing => reward 0.0)

    result = {
        "reward": reward,
        # Detail flags
        "has_roadmap_file": checks["has_roadmap_file"],
        "roadmap_parsed": checks["roadmap_parsed"],
        "roadmap_has_required_top_keys": checks["roadmap_has_required_top_keys"],
        "roadmap_current_profile_fields": checks["roadmap_current_profile_fields"],
        "roadmap_target_profile_fields": checks["roadmap_target_profile_fields"],
        "roadmap_phases_valid": checks["roadmap_phases_valid"],

        "moralis_file_exists": checks["moralis_file_exists"],
        "moralis_has_required_keywords": checks["moralis_has_required_keywords"],
        "moralis_has_questions_section": checks["moralis_has_questions_section"],
        "moralis_has_q_line": checks["moralis_has_q_line"],
        "moralis_has_a_line": checks["moralis_has_a_line"],

        "nas_file_exists": checks["nas_file_exists"],
        "nas_contains_required_phrases": checks["nas_contains_required_phrases"],

        "paradox_file_exists": checks["paradox_file_exists"],
        "paradox_has_required_headings": checks["paradox_has_required_headings"],
        "paradox_has_verification_line": checks["paradox_has_verification_line"],
        "paradox_has_anchor_line": checks["paradox_has_anchor_line"],
    }

    print(json.dumps(result))

if __name__ == "__main__":
    main()