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

def file_exists_nonempty(path):
    if not os.path.isfile(path):
        return False
    try:
        return os.path.getsize(path) > 0
    except Exception:
        return False

def validate_questions_jsonl(path):
    # Returns dict with detailed checks
    checks = {
        "q_exists": False,
        "q_nonempty": False,
        "q_valid_json_and_keys": False,
        "q_min_8": False,
        "q_phases_covered": False,
        "q_single_question_marks": False,
        "q_nonempty_fields": False,
    }
    if not os.path.isfile(path):
        return checks

    checks["q_exists"] = True

    try:
        lines = []
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line == "":
                    continue
                lines.append(line)
    except Exception:
        # Cannot read; leave others False
        return checks

    if len(lines) > 0:
        checks["q_nonempty"] = True

    objs = []
    valid_schema = True
    phases_seen = set()
    single_q_ok = True
    nonempty_fields_ok = True

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            valid_schema = False
            continue
        # Validate keys
        if not isinstance(obj, dict):
            valid_schema = False
            continue
        for key in ("phase", "question", "recommended_answer"):
            if key not in obj:
                valid_schema = False
        if "phase" in obj and not isinstance(obj["phase"], str):
            valid_schema = False
        if "question" in obj and not isinstance(obj["question"], str):
            valid_schema = False
        if "recommended_answer" in obj and not isinstance(obj["recommended_answer"], str):
            valid_schema = False
        if not valid_schema:
            continue

        # Phase must be in {"0","1","2","3"}
        if obj["phase"] not in {"0", "1", "2", "3"}:
            valid_schema = False

        question = obj.get("question", "")
        ra = obj.get("recommended_answer", "")

        # Exactly one '?'
        if question.count("?") != 1:
            single_q_ok = False

        # Non-empty fields
        if len(question.strip()) == 0 or len(ra.strip()) == 0:
            nonempty_fields_ok = False

        phases_seen.add(obj["phase"])
        objs.append(obj)

    if valid_schema and len(objs) == len(lines) and len(lines) > 0:
        checks["q_valid_json_and_keys"] = True

    if len(objs) >= 8:
        checks["q_min_8"] = True

    if {"0", "1", "2", "3"}.issubset(phases_seen):
        checks["q_phases_covered"] = True

    if single_q_ok and len(objs) > 0:
        checks["q_single_question_marks"] = True

    if nonempty_fields_ok and len(objs) > 0:
        checks["q_nonempty_fields"] = True

    return checks

def contains_case_insensitive(haystack, needle):
    return needle.lower() in haystack.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) questions.jsonl checks
    q_path = os.path.join(output_dir, "questions.jsonl")
    q_checks = validate_questions_jsonl(q_path)
    checks.update(q_checks)

    # 2) phase_summaries.md presence and required strings
    phase_summaries_path = os.path.join(output_dir, "phase_summaries.md")
    checks["phase_summaries_exists"] = os.path.isfile(phase_summaries_path)
    phase_summaries_text = read_text(phase_summaries_path) if checks["phase_summaries_exists"] else None
    if phase_summaries_text is None:
        checks["phase_summaries_has_phases_0_1_2_3"] = False
    else:
        has_all = (
            contains_case_insensitive(phase_summaries_text, "Phase 0")
            and contains_case_insensitive(phase_summaries_text, "Phase 1")
            and contains_case_insensitive(phase_summaries_text, "Phase 2")
            and contains_case_insensitive(phase_summaries_text, "Phase 3")
        )
        checks["phase_summaries_has_phases_0_1_2_3"] = has_all

    # 3) synthesis.md presence and required sections
    synthesis_path = os.path.join(output_dir, "synthesis.md")
    checks["synthesis_exists"] = os.path.isfile(synthesis_path)
    synthesis_text = read_text(synthesis_path) if checks["synthesis_exists"] else None
    if synthesis_text is None:
        checks["synthesis_has_decisions"] = False
        checks["synthesis_has_open_items"] = False
        checks["synthesis_has_risks"] = False
        checks["synthesis_has_success_criteria"] = False
    else:
        checks["synthesis_has_decisions"] = contains_case_insensitive(synthesis_text, "Decisions")
        checks["synthesis_has_open_items"] = contains_case_insensitive(synthesis_text, "Open Items")
        checks["synthesis_has_risks"] = contains_case_insensitive(synthesis_text, "Risks")
        checks["synthesis_has_success_criteria"] = contains_case_insensitive(synthesis_text, "Success Criteria")

    # 4) constitution.md exists and non-empty
    constitution_path = os.path.join(output_dir, "memory", "constitution.md")
    checks["constitution_exists_nonempty"] = file_exists_nonempty(constitution_path)

    # 5) Spec artifact tree required files
    spec_base = os.path.join(output_dir, "specs", "notification-feature")
    spec_md_path = os.path.join(spec_base, "spec.md")
    data_model_path = os.path.join(spec_base, "data-model.md")
    contracts_dir = os.path.join(spec_base, "contracts")
    tasks_path = os.path.join(spec_base, "tasks.md")
    checklist_path = os.path.join(spec_base, "checklists", "requirements.md")

    # Existence checks
    checks["spec_md_exists"] = os.path.isfile(spec_md_path)
    checks["data_model_exists"] = os.path.isfile(data_model_path)
    checks["contracts_dir_exists"] = os.path.isdir(contracts_dir)
    checks["tasks_exists"] = os.path.isfile(tasks_path)
    checks["checklists_requirements_exists"] = os.path.isfile(checklist_path)

    # Content checks within artifacts
    # spec.md Given/When/Then counts and [NEEDS CLARIFICATION] cap
    if checks["spec_md_exists"]:
        spec_text = read_text(spec_md_path) or ""
        given_count = spec_text.count("Given")
        when_count = spec_text.count("When")
        then_count = spec_text.count("Then")
        needs_clar_count = spec_text.count("[NEEDS CLARIFICATION]")
        checks["spec_has_min_scenarios"] = (given_count >= 2 and when_count >= 2 and then_count >= 2)
        checks["spec_needs_clarification_cap_ok"] = (needs_clar_count <= 3)
    else:
        checks["spec_has_min_scenarios"] = False
        checks["spec_needs_clarification_cap_ok"] = False

    # tasks.md: at least two lines include [US\d+] and at least one "- [ ]"
    if checks["tasks_exists"]:
        tasks_text = read_text(tasks_path) or ""
        lines = tasks_text.splitlines()
        us_line_count = 0
        for line in lines:
            if re.search(r"\[US\d+\]", line):
                us_line_count += 1
        checks["tasks_has_user_story_refs"] = us_line_count >= 2
        checks["tasks_has_checklist_marker"] = "- [ ]" in tasks_text
    else:
        checks["tasks_has_user_story_refs"] = False
        checks["tasks_has_checklist_marker"] = False

    # data-model.md: non-empty and includes at least one entity name reference (line starting with "- " or "# " or "##")
    if checks["data_model_exists"]:
        dm_text = read_text(data_model_path) or ""
        nonempty = len(dm_text.strip()) > 0
        has_entity_heuristic = False
        for line in dm_text.splitlines():
            s = line.lstrip()
            if s.startswith("- ") or s.startswith("# ") or s.startswith("##"):
                has_entity_heuristic = True
                break
        checks["data_model_nonempty_with_entities"] = nonempty and has_entity_heuristic
    else:
        checks["data_model_nonempty_with_entities"] = False

    # contracts/: at least one .md file present
    if checks["contracts_dir_exists"]:
        try:
            md_files = [f for f in os.listdir(contracts_dir) if f.endswith(".md") and os.path.isfile(os.path.join(contracts_dir, f))]
        except Exception:
            md_files = []
        checks["contracts_has_md_file"] = len(md_files) >= 1
    else:
        checks["contracts_has_md_file"] = False

    # checklists/requirements.md existence already set; no extra content checks required

    # Compute reward: fraction of checks passed
    # Only checks that depend on outputs contribute (all above do).
    bool_values = [v for v in checks.values() if isinstance(v, bool)]
    passed = sum(1 for v in bool_values if v)
    total = len(bool_values) if len(bool_values) > 0 else 1
    reward = passed / total

    # Explicitly ensure no-op baseline yields 0.0 when outputs missing or empty
    # If output dir missing or none of the primary artifacts exist, set reward to 0.0
    primary_artifacts = [
        q_checks.get("q_exists", False),
        checks["phase_summaries_exists"],
        checks["synthesis_exists"],
        checks["constitution_exists_nonempty"],
        checks["spec_md_exists"],
        checks["data_model_exists"],
        checks["contracts_dir_exists"],
        checks["tasks_exists"],
        checks["checklists_requirements_exists"],
    ]
    if not os.path.isdir(output_dir) or not any(primary_artifacts):
        reward = 0.0

    # Build result with "reward" first
    result = {"reward": round(reward, 6)}
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()