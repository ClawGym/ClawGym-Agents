import json
import os
import sys
import csv

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

def read_csv_task_ids(path):
    ids = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Ensure task_id column exists
            if reader.fieldnames is None or "task_id" not in reader.fieldnames:
                return None
            for row in reader:
                tid = row.get("task_id")
                if isinstance(tid, str) and tid.strip() != "":
                    ids.append(tid.strip())
            return ids
    except Exception:
        return None

def extract_section_indices(lines, expected_titles):
    # Identify indices of top-level headings: either exact title line, or "# " + title
    indices = {}
    counts = {title: 0 for title in expected_titles}
    for idx, raw in enumerate(lines):
        line = raw.strip()
        for title in expected_titles:
            if line == title or line == ("# " + title):
                # Count occurrences
                counts[title] += 1
                # Record first index only
                if title not in indices:
                    indices[title] = idx
    # Ensure each expected title appears exactly once
    if any(counts[t] != 1 for t in expected_titles):
        return None
    # Ensure order is strictly increasing per the given expected order
    ordered = [indices[t] for t in expected_titles]
    if any(ordered[i] >= ordered[i+1] for i in range(len(ordered)-1)):
        return None
    return indices

def get_section_text(lines, indices, expected_titles, section_title):
    # Return text between section heading line and next heading among the expected_titles
    start_idx = indices.get(section_title)
    if start_idx is None:
        return ""
    # Find the next section start
    following_titles = [t for t in expected_titles if indices[t] > start_idx]
    if following_titles:
        next_start = min(indices[t] for t in following_titles)
    else:
        next_start = len(lines)
    # Exclude the heading line itself
    content_lines = lines[start_idx+1: next_start]
    return "\n".join(content_lines)

def is_string_list(value):
    if not isinstance(value, list):
        return False
    for v in value:
        if not isinstance(v, str):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "advice_exists": False,
        "advice_has_required_sections": False,
        "advice_model_tradeoff_citations": False,
        "eval_rubric_valid_structure": False,
        "eval_rubric_weights_sum_100": False,
        "eval_rubric_has_fact_checking": False,
        "prompt_templates_valid_structure": False,
        "prompt_templates_required_phrases": False,
        "routing_policy_valid_json": False,
        "routing_policy_covers_all_tasks": False,
        "routing_policy_models_exist": False,
    }

    # Load reference inputs
    models_path = os.path.join(input_dir, "models.json")
    tasks_path = os.path.join(input_dir, "tasks.csv")
    models_json = read_json(models_path)
    model_names = set()
    if isinstance(models_json, list):
        for m in models_json:
            name = m.get("name") if isinstance(m, dict) else None
            if isinstance(name, str):
                model_names.add(name)
    task_ids = read_csv_task_ids(tasks_path)
    task_ids_set = set(task_ids) if isinstance(task_ids, list) else None

    # 1) advice.md checks
    advice_path = os.path.join(output_dir, "advice.md")
    advice_text = read_text(advice_path)
    if advice_text is not None:
        content = advice_text
        if isinstance(content, str) and content.strip() != "":
            checks["advice_exists"] = True

            expected_titles = [
                "Model Recommendation",
                "Prompt Strategy",
                "Evaluation Rubric (overview)",
                "Workflow Plan",
                "Risks and Mitigations",
            ]
            lines = content.splitlines()
            indices = extract_section_indices(lines, expected_titles)
            if indices is not None:
                checks["advice_has_required_sections"] = True

                # Model Recommendation section content
                model_sec = get_section_text(lines, indices, expected_titles, "Model Recommendation")
                model_sec_lower = model_sec if isinstance(model_sec, str) else ""
                # Count at least two distinct model name matches
                cited = set()
                if model_names and isinstance(model_sec_lower, str):
                    for name in model_names:
                        if name in model_sec_lower:
                            cited.add(name)
                # Require presence of substrings "cost_score" and "power_score" as evidence of trade-off discussion
                has_cost = "cost_score" in model_sec_lower
                has_power = "power_score" in model_sec_lower
                if len(cited) >= 2 and has_cost and has_power:
                    checks["advice_model_tradeoff_citations"] = True

    # 2) eval_rubric.json checks
    rubric_path = os.path.join(output_dir, "eval_rubric.json")
    rubric_json = read_json(rubric_path)
    if isinstance(rubric_json, list) and len(rubric_json) >= 5:
        # Validate structure and collect weights
        all_struct_ok = True
        weight_sum = 0
        has_fact_checking = False
        for item in rubric_json:
            if not isinstance(item, dict):
                all_struct_ok = False
                break
            name = item.get("name")
            weight = item.get("weight")
            guidance = item.get("guidance")
            if not isinstance(name, str) or not isinstance(guidance, str) or not isinstance(weight, int):
                all_struct_ok = False
                break
            weight_sum += weight
            if name == "fact-checking":
                has_fact_checking = True
        if all_struct_ok:
            checks["eval_rubric_valid_structure"] = True
            if weight_sum == 100:
                checks["eval_rubric_weights_sum_100"] = True
            if has_fact_checking:
                checks["eval_rubric_has_fact_checking"] = True

    # 3) prompt_templates.json checks
    prompts_path = os.path.join(output_dir, "prompt_templates.json")
    prompts_json = read_json(prompts_path)
    if isinstance(prompts_json, dict) and set(prompts_json.keys()) == {"first_draft", "fact_check"}:
        structure_ok = True
        phrases_ok = True
        required_keys = {"purpose", "audience", "success_criteria", "instructions", "variables"}
        required_phrases = ["what you want", "why", "who it's for", "what good looks like"]
        for key in ["first_draft", "fact_check"]:
            val = prompts_json.get(key)
            if not isinstance(val, dict):
                structure_ok = False
                break
            if set(val.keys()) != required_keys:
                structure_ok = False
                break
            if not isinstance(val["purpose"], str):
                structure_ok = False
                break
            if not isinstance(val["audience"], str):
                structure_ok = False
                break
            if not isinstance(val["success_criteria"], str):
                structure_ok = False
                break
            if not isinstance(val["instructions"], str):
                structure_ok = False
                break
            if not is_string_list(val["variables"]):
                structure_ok = False
                break
            instr_l = val["instructions"].lower()
            for phrase in required_phrases:
                if phrase not in instr_l:
                    phrases_ok = False
        if structure_ok:
            checks["prompt_templates_valid_structure"] = True
        if structure_ok and phrases_ok:
            checks["prompt_templates_required_phrases"] = True

    # 4) routing_policy.json checks
    routing_path = os.path.join(output_dir, "routing_policy.json")
    routing_json = read_json(routing_path)
    routing_valid_json = False
    covers_all_tasks = False
    models_exist_ok = False
    if isinstance(routing_json, list):
        # validate each element structure
        elem_ok = True
        seen_task_ids = set()
        selected_models_all_valid = True
        for elem in routing_json:
            if not isinstance(elem, dict):
                elem_ok = False
                break
            tid = elem.get("task_id")
            sm = elem.get("selected_model")
            reason = elem.get("reason")
            if not isinstance(tid, str) or not isinstance(sm, str) or not isinstance(reason, str):
                elem_ok = False
                break
            if tid in seen_task_ids:
                elem_ok = False
                break
            seen_task_ids.add(tid)
            # Check selected model exists in models.json
            if not model_names or sm not in model_names:
                selected_models_all_valid = False
        if elem_ok:
            routing_valid_json = True
            checks["routing_policy_valid_json"] = True
            # coverage against tasks.csv
            if isinstance(task_ids_set, set) and len(task_ids_set) > 0:
                if seen_task_ids == task_ids_set:
                    covers_all_tasks = True
                    checks["routing_policy_covers_all_tasks"] = True
            # model validity
            if selected_models_all_valid:
                models_exist_ok = True
                checks["routing_policy_models_exist"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Ensure baseline: if output directory missing or empty and no artifacts pass, reward must be 0.0
    # Already handled by passed > 0 logic.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()