import json
import os
import sys
import re

def read_jsonl(path):
    items = []
    if not os.path.isfile(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except Exception:
                # Malformed line; include a placeholder to let validation fail later
                items.append({"__parse_error__": True})
    return items

def load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_block(text, tag):
    # Returns content between <tag> and </tag> or None
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    start_idx = text.find(start_tag)
    if start_idx == -1:
        return None
    start_idx += len(start_tag)
    end_idx = text.find(end_tag, start_idx)
    if end_idx == -1:
        return None
    return text[start_idx:end_idx]

def count_period_sentences(s):
    if not isinstance(s, str):
        return 0
    # Collapse sequences of periods to a single period to avoid ellipsis inflation
    collapsed = re.sub(r"\.{2,}", ".", s)
    return collapsed.count(".")

def normalize_id(x):
    # Normalize ids to string for comparison across input/output
    try:
        return str(x)
    except Exception:
        return None

def get_expected_agents(raw_text):
    t = raw_text.lower()
    expected = set()
    # Clarifier triggers
    if "+ask" in t or any(phrase in t for phrase in ["make it better", "not sure", "unclear", "messy"]):
        expected.add("clarifier")
    # Codebase researcher triggers
    if any(phrase in t for phrase in ["this project", "our api", "refactor", "integrate", "existing code"]):
        expected.add("codebase-researcher")
    # Web researcher triggers
    if any(phrase in t for phrase in ["best practices", "latest", "2024", "2025", "current standards"]):
        expected.add("web-researcher")
    return expected

def collect_clarification_strings(clar_value):
    strings = []
    if isinstance(clar_value, str):
        strings.append(clar_value)
    elif isinstance(clar_value, list):
        for v in clar_value:
            if isinstance(v, str):
                strings.append(v)
            elif isinstance(v, (int, float)):
                strings.append(str(v))
    elif isinstance(clar_value, (int, float)):
        strings.append(str(clar_value))
    elif isinstance(clar_value, dict):
        for v in clar_value.values():
            strings.extend(collect_clarification_strings(v))
    return strings

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "optimized_file_exists": False,
        "ids_match": False,
        "fields_valid": False,
        "tags_present": False,
        "task_numbered_steps": False,
        "filler_removed": False,
        "routing_ok": False,
        "type_constraints_ok": False,
        "clarifications_used": False,
        "explanations_ok": False,
        "routing_report_ok": False
    }

    # Load inputs
    prompts_path = os.path.join(input_dir, "prompts.jsonl")
    clarifications_path = os.path.join(input_dir, "clarifications.json")
    input_prompts = read_jsonl(prompts_path)
    clarifications = load_json(clarifications_path) or {}

    # Build reference id map and raw texts
    input_id_to_text = {}
    for obj in input_prompts:
        if isinstance(obj, dict) and "__parse_error__" not in obj and "id" in obj and "text" in obj:
            input_id_to_text[normalize_id(obj["id"])] = str(obj["text"])

    # Load outputs
    opt_path = os.path.join(output_dir, "optimized_prompts.jsonl")
    routing_report_path = os.path.join(output_dir, "routing_report.md")

    opt_exists = os.path.isfile(opt_path)
    if opt_exists:
        checks["optimized_file_exists"] = True

    # Early set for routing_report existence (will further validate content later)
    routing_report_exists = os.path.isfile(routing_report_path)

    opt_items = []
    if opt_exists:
        opt_items = read_jsonl(opt_path)

    # Prepare structures to validate
    allowed_types = {"coding", "writing", "analysis", "creative", "data"}

    # If optimized output exists, validate ids and structure
    ids_match = False
    fields_valid = True
    tags_present = True
    task_steps_ok = True
    filler_removed_ok = True
    routing_ok = True
    type_constraints_ok = True
    clarifications_used_ok = True
    explanations_ok = True

    if opt_exists:
        # Validate id matching and counts
        input_ids = list(input_id_to_text.keys())
        input_id_set = set(input_ids)

        # Parse opt_items into a dict by id (normalized)
        out_by_id = {}
        out_ids_list = []
        parse_error = False
        for item in opt_items:
            if not isinstance(item, dict):
                parse_error = True
                break
            if "id" not in item:
                parse_error = True
                break
            nid = normalize_id(item["id"])
            out_ids_list.append(nid)
            if nid in out_by_id:
                # duplicate id
                parse_error = True
                break
            out_by_id[nid] = item

        if not parse_error:
            out_id_set = set(out_by_id.keys())
            # Exactly one per input id with matching sets and same count
            if out_id_set == input_id_set and len(out_by_id) == len(input_id_set) and len(opt_items) == len(input_id_set):
                ids_match = True

        checks["ids_match"] = ids_match

        # Proceed with deeper checks only if ids match
        if ids_match:
            # Load routing_report content if exists
            routing_report_content = ""
            if routing_report_exists:
                try:
                    with open(routing_report_path, "r", encoding="utf-8") as f:
                        routing_report_content = f.read()
                except Exception:
                    routing_report_content = ""

            # Iterate per id
            for nid in input_ids:
                item = out_by_id.get(nid)
                # Field checks
                if not isinstance(item, dict):
                    fields_valid = False
                    break

                # Required fields presence and type
                if "detected_type" not in item or "agents" not in item or "optimized_prompt" not in item or "explanation" not in item:
                    fields_valid = False
                    break

                detected_type = item["detected_type"]
                agents = item["agents"]
                optimized_prompt = item["optimized_prompt"]
                explanation = item["explanation"]

                if detected_type not in allowed_types:
                    fields_valid = False
                    break
                if not isinstance(agents, list):
                    fields_valid = False
                    break
                if not isinstance(optimized_prompt, str) or not isinstance(explanation, str):
                    fields_valid = False
                    break

                # Tags presence
                tag_names = ["role", "task", "constraints", "output"]
                for tag in tag_names:
                    if f"<{tag}>" not in optimized_prompt or f"</{tag}>" not in optimized_prompt:
                        tags_present = False
                        break
                if not tags_present:
                    break

                # Numbered steps inside <task>
                task_block = extract_block(optimized_prompt, "task")
                if task_block is None:
                    task_steps_ok = False
                else:
                    if ("1." not in task_block) or ("2." not in task_block):
                        task_steps_ok = False

                # Filler removal
                low_opt = optimized_prompt.lower()
                if ("please" in low_opt) or ("i want you to" in low_opt):
                    filler_removed_ok = False

                # Routing checks
                raw_text = input_id_to_text.get(nid, "")
                expected_agents = get_expected_agents(raw_text)
                agents_norm = set([str(a).strip().lower() for a in agents if isinstance(a, (str, int, float))])
                for ea in expected_agents:
                    if ea not in agents_norm:
                        routing_ok = False
                        break
                if not routing_ok:
                    break

                # Type-specific constraints inside <constraints>
                constraints_block = extract_block(optimized_prompt, "constraints")
                if constraints_block is None:
                    type_constraints_ok = False
                else:
                    cb_low = constraints_block.lower()
                    if detected_type == "writing":
                        cond_aud = ("audience" in cb_low)
                        cond_tone = ("tone" in cb_low)
                        cond_len = ("length" in cb_low) or ("words" in cb_low)
                        if not (cond_aud and cond_tone and cond_len):
                            type_constraints_ok = False
                    elif detected_type == "coding":
                        cond_edge = ("edge case" in cb_low) or ("edge cases" in cb_low)
                        cond_err = ("error" in cb_low)
                        if not (cond_edge and cond_err):
                            type_constraints_ok = False
                    elif detected_type == "data":
                        cond_in = ("input" in cb_low)
                        cond_out = ("output" in cb_low)
                        cond_format = ("json" in cb_low) or ("csv" in cb_low)
                        if not (cond_in and cond_out and cond_format):
                            type_constraints_ok = False
                    # For analysis/creative, no extra constraints

                # Clarifications incorporation (if exist for id)
                clar_entry = None
                # clarifications keys may be str or numeric; normalize
                for k, v in clarifications.items():
                    if normalize_id(k) == nid:
                        clar_entry = v
                        break
                if clar_entry is not None:
                    # Collect all answer strings
                    strings_needed = []
                    if isinstance(clar_entry, dict):
                        for val in clar_entry.values():
                            strings_needed.extend(collect_clarification_strings(val))
                    else:
                        strings_needed.extend(collect_clarification_strings(clar_entry))
                    low_prompt = optimized_prompt.lower()
                    for s in strings_needed:
                        if isinstance(s, str):
                            if s.strip() == "":
                                continue
                            if s.lower() not in low_prompt:
                                clarifications_used_ok = False
                                break
                        else:
                            # Non-string converted handled in aggregator
                            continue
                    if not clarifications_used_ok:
                        break

                # Explanation sentence count between 2 and 4 (counting periods)
                num_periods = count_period_sentences(explanation)
                if not (2 <= num_periods <= 4):
                    explanations_ok = False

            # End for each id
        else:
            # If ids do not match, other checks remain False
            fields_valid = False
            tags_present = False
            task_steps_ok = False
            filler_removed_ok = False
            routing_ok = False
            type_constraints_ok = False
            clarifications_used_ok = False
            explanations_ok = False

        checks["fields_valid"] = fields_valid
        checks["tags_present"] = tags_present
        checks["task_numbered_steps"] = task_steps_ok
        checks["filler_removed"] = filler_removed_ok
        checks["routing_ok"] = routing_ok
        checks["type_constraints_ok"] = type_constraints_ok
        checks["clarifications_used"] = clarifications_used_ok
        checks["explanations_ok"] = explanations_ok

    # routing_report_ok: existence and for each id, includes id and expected agents per routing rule
    routing_report_ok = False
    if opt_exists and checks["ids_match"]:
        # Only evaluate routing report if we know the expected agents by id
        if routing_report_exists:
            try:
                with open(routing_report_path, "r", encoding="utf-8") as f:
                    rr = f.read()
            except Exception:
                rr = ""
            rr_low = rr.lower()
            all_ids_present = True
            per_id_agents_ok = True
            for nid, raw_text in input_id_to_text.items():
                # Check id present
                if (nid is None) or (str(nid) not in rr):
                    all_ids_present = False
                    break
                # For each expected agent, ensure it appears near the id occurrence
                expected_agents = get_expected_agents(raw_text)
                if expected_agents:
                    # Find first occurrence and inspect window after it
                    idx = rr.find(str(nid))
                    window = rr_low[idx: idx + 300] if idx != -1 else ""
                    for ea in expected_agents:
                        if ea not in window:
                            per_id_agents_ok = False
                            break
                    if not per_id_agents_ok:
                        break
            routing_report_ok = all_ids_present and per_id_agents_ok
    checks["routing_report_ok"] = routing_report_ok

    # Compute reward: only artifact-dependent checks count; gate on optimized_file_exists
    scored_keys = [
        "optimized_file_exists",
        "ids_match",
        "fields_valid",
        "tags_present",
        "task_numbered_steps",
        "filler_removed",
        "routing_ok",
        "type_constraints_ok",
        "clarifications_used",
        "explanations_ok",
        "routing_report_ok"
    ]

    # No-op baseline: if main optimized file missing, reward = 0.0
    if not checks["optimized_file_exists"]:
        reward = 0.0
    else:
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        # To strongly require core presence, keep proportional score
        reward = passed / total if total > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print result JSON as the last line
    result = {"reward": reward}
    # Preserve order: reward first, then checks
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()