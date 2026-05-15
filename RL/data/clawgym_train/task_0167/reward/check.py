import json
import os
import sys
import re

def leading_spaces(s: str) -> int:
    return len(s) - len(s.lstrip(' '))

def find_section(lines, key):
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}:"):
            indent = leading_spaces(line)
            # Determine end of this section (next line with indent <= current indent)
            j = i + 1
            n = len(lines)
            while j < n:
                if lines[j].strip() == "":
                    j += 1
                    continue
                ind = leading_spaces(lines[j])
                if ind <= indent:
                    break
                j += 1
            return i, j, indent
    return None

def list_subkeys(lines, start, end, parent_indent):
    subsections = {}
    i = start + 1
    while i < end:
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        ind = leading_spaces(line)
        if ind <= parent_indent:
            break
        stripped = line.strip()
        # Match "key:" or "key: <inline>"
        m = re.match(r'^([A-Za-z0-9_\-]+)\s*:\s*(.*)$', stripped)
        if m and not stripped.startswith('- '):
            key = m.group(1).strip()
            inline_value = m.group(2).strip()
            key_indent = ind
            # find block end
            j = i + 1
            while j < end:
                l2 = lines[j]
                if l2.strip() == "":
                    j += 1
                    continue
                ind2 = leading_spaces(l2)
                if ind2 <= key_indent:
                    break
                j += 1
            subsections[key] = {"start": i, "end": j, "indent": key_indent, "inline": inline_value}
            i = j
        else:
            i += 1
    return subsections

def parse_inline_list(text):
    # expects something like "[a, b, c]" possibly with quotes
    if not text.startswith('['):
        return None
    end_bracket = text.find(']')
    if end_bracket == -1:
        return None
    content = text[1:end_bracket].strip()
    if not content:
        return []
    items = [x.strip().strip("'\"") for x in content.split(',')]
    return items

def parse_models_in_block(lines, start, end):
    # Looks for "models:" line and parses inline list or subsequent "- item" lines
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("models:"):
            after = stripped[len("models:"):].strip()
            # inline list case
            items = None
            if after:
                items = parse_inline_list(after)
                if items is not None:
                    return items
            # multi-line list items
            base_indent = leading_spaces(lines[i])
            j = i + 1
            list_items = []
            while j < end:
                l2 = lines[j]
                if l2.strip() == "":
                    j += 1
                    continue
                ind2 = leading_spaces(l2)
                if ind2 <= base_indent:
                    break
                st2 = l2.strip()
                if st2.startswith('- '):
                    val = st2[2:].strip().strip("'\"")
                    list_items.append(val)
                j += 1
            return list_items
    return None

def block_has_trigger(lines, start, end):
    # Accept 'triggers:' (inline or list), or 'trigger:' or 'description:' with non-empty value
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith('triggers:'):
            after = stripped[len('triggers:'):].strip()
            if after:
                items = parse_inline_list(after)
                if items is not None:
                    return len(items) > 0
            # look for list items
            base_indent = leading_spaces(lines[i])
            j = i + 1
            found_item = False
            while j < end:
                l2 = lines[j]
                if l2.strip() == "":
                    j += 1
                    continue
                ind2 = leading_spaces(l2)
                if ind2 <= base_indent:
                    break
                if l2.strip().startswith('- '):
                    content = l2.strip()[2:].strip()
                    if content:
                        found_item = True
                        break
                j += 1
            if found_item:
                return True
        if stripped.startswith('trigger:'):
            val = stripped.split(':', 1)[1].strip()
            if val and val not in ['null', '~']:
                return True
        if stripped.startswith('description:'):
            val = stripped.split(':', 1)[1].strip()
            if val and val not in ['null', '~']:
                return True
    return False

def parse_chain_models(lines, chain_block):
    # chain_block: dict with start, end, inline
    inline = chain_block.get("inline", "")
    if inline and inline != "":
        inline_items = parse_inline_list(inline)
        if inline_items is not None:
            return inline_items
    # Otherwise parse list items under this block
    start = chain_block["start"]
    end = chain_block["end"]
    # Items are lines starting with "- " under the chain block
    list_items = []
    base_indent = leading_spaces(lines[start])
    for i in range(start + 1, end):
        l = lines[i]
        if l.strip() == "":
            continue
        ind = leading_spaces(l)
        if ind <= base_indent:
            break
        st = l.strip()
        if st.startswith('- '):
            val = st[2:].strip().strip("'\"")
            list_items.append(val)
    return list_items

def load_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_iso8601_basic(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # Simple check: YYYY-MM-DDTHH:MM:SS with optional fractional seconds and timezone
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', s))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "workflow_exists": False,
        "workflow_routing_rules_types_present": False,
        "workflow_routing_primary_models_match": False,
        "workflow_routing_has_triggers": False,
        "workflow_fallback_chains_present": False,
        "workflow_fallback_reasoning_order_ok": False,
        "workflow_fallback_production_order_ok": False,
        "workflow_fallback_classification_order_ok": False,
        "plan_exists": False,
        "plan_json_valid": False,
        "plan_length_matches_tasks": False,
        "plan_ids_match_tasks": False,
        "plan_fields_valid": False,
        "plan_models_match_constraints": False,
        "plan_channels_policy_ok": False,
        "plan_fallback_chains_ok": False,
        "qc_exists": False,
        "qc_two_lines": False,
        "qc_tasks_T3_T4_only": False,
        "qc_steps_structure_ok": False,
        "qc_steps_models_order_ok": False,
        "qc_timestamps_present": False,
        "qc_deliver_confidence_and_concerns_ok": False,
    }

    # Expected mappings per task spec
    expected_model_by_type = {
        "strategy": "claude-opus-4-6",
        "production": "claude-sonnet-4-6",
        "coding_and_scoring": "gpt-4o",
        "classification": "claude-haiku-4-5",
    }
    expected_fallback_chain_by_type = {
        "strategy": "reasoning",
        "production": "production",
        "coding_and_scoring": "production",
        "classification": "classification",
    }
    expected_fallback_order = {
        "reasoning": ["claude-opus-4-6", "gpt-4o", "claude-sonnet-4-6", "gemini-2.5-pro"],
        "production": ["claude-sonnet-4-6", "gpt-4o", "grok-3"],
        "classification": ["claude-haiku-4-5", "claude-sonnet-4-6"],
    }

    # Load input tasks
    tasks_path = os.path.join(input_dir, "tasks.json")
    tasks, tasks_err = load_json_file(tasks_path)
    tasks_by_id = {}
    if tasks and isinstance(tasks, list):
        for t in tasks:
            if isinstance(t, dict) and "id" in t:
                tasks_by_id[t["id"]] = t

    # 1) Validate workflow.yaml
    workflow_path = os.path.join(output_dir, "workflow.yaml")
    if os.path.isfile(workflow_path):
        checks["workflow_exists"] = True
        text, err = read_text(workflow_path)
        if text is not None:
            lines = text.splitlines()

            # Find routing_rules section
            rr_section = find_section(lines, "routing_rules")
            routing_types_present = False
            primary_models_match = False
            has_triggers = False
            if rr_section:
                rr_start, rr_end, rr_indent = rr_section
                rr_sub = list_subkeys(lines, rr_start, rr_end, rr_indent)
                needed_types = set(["strategy", "production", "coding_and_scoring", "classification"])
                found_types = set(rr_sub.keys()) & needed_types
                if found_types == needed_types:
                    routing_types_present = True
                    # Check primary models and triggers
                    models_ok = True
                    triggers_ok = True
                    for tname in needed_types:
                        block = rr_sub.get(tname)
                        if not block:
                            models_ok = False
                            triggers_ok = False
                            continue
                        models = parse_models_in_block(lines, block["start"], block["end"])
                        if not models or len(models) == 0:
                            models_ok = False
                        else:
                            if models[0] != expected_model_by_type[tname]:
                                models_ok = False
                        if not block_has_trigger(lines, block["start"], block["end"]):
                            triggers_ok = False
                    primary_models_match = models_ok
                    has_triggers = triggers_ok
            checks["workflow_routing_rules_types_present"] = routing_types_present
            checks["workflow_routing_primary_models_match"] = primary_models_match
            checks["workflow_routing_has_triggers"] = has_triggers

            # Find fallback_chains section
            fb_section = find_section(lines, "fallback_chains")
            fb_present = False
            fb_reasoning_ok = False
            fb_production_ok = False
            fb_classification_ok = False
            if fb_section:
                fb_start, fb_end, fb_indent = fb_section
                fb_sub = list_subkeys(lines, fb_start, fb_end, fb_indent)
                required_chains = set(["reasoning", "production", "classification"])
                if required_chains.issubset(set(fb_sub.keys())):
                    fb_present = True
                    # Parse each chain order
                    for cname in ["reasoning", "production", "classification"]:
                        c_block = fb_sub.get(cname)
                        if not c_block:
                            continue
                        models = parse_chain_models(lines, c_block)
                        if models == expected_fallback_order[cname]:
                            if cname == "reasoning":
                                fb_reasoning_ok = True
                            elif cname == "production":
                                fb_production_ok = True
                            elif cname == "classification":
                                fb_classification_ok = True
            checks["workflow_fallback_chains_present"] = fb_present
            checks["workflow_fallback_reasoning_order_ok"] = fb_reasoning_ok
            checks["workflow_fallback_production_order_ok"] = fb_production_ok
            checks["workflow_fallback_classification_order_ok"] = fb_classification_ok

    # 2) Validate plan.json
    plan_path = os.path.join(output_dir, "plan.json")
    plan, plan_err = (None, None)
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan, plan_err = load_json_file(plan_path)
        if plan_err is None and isinstance(plan, list):
            checks["plan_json_valid"] = True
            # Must have one entry per task id and no extras
            plan_ids = [p.get("id") for p in plan if isinstance(p, dict)]
            plan_ids_set = set(pid for pid in plan_ids if pid is not None)
            tasks_ids_set = set(tasks_by_id.keys())
            if len(plan_ids_set) == len(tasks_ids_set) and plan_ids_set == tasks_ids_set and len(plan) == len(tasks_by_id):
                checks["plan_length_matches_tasks"] = True
                checks["plan_ids_match_tasks"] = True
            # Validate each entry fields and policies
            fields_ok = True
            models_ok = True
            channels_ok = True
            fallbacks_ok = True
            for p in plan if isinstance(plan, list) else []:
                if not isinstance(p, dict):
                    fields_ok = False
                    models_ok = False
                    channels_ok = False
                    fallbacks_ok = False
                    break
                # Check presence of required fields
                required_fields = ["id", "assigned_model", "channel", "fallback_chain"]
                for rf in required_fields:
                    if rf not in p:
                        fields_ok = False
                pid = p.get("id")
                t = tasks_by_id.get(pid)
                if not t:
                    models_ok = False
                    channels_ok = False
                    fallbacks_ok = False
                    continue
                ttype = t.get("type")
                expected_model = expected_model_by_type.get(ttype)
                if p.get("assigned_model") != expected_model:
                    models_ok = False
                # Channel policy: interactive -> subscription ; else -> api
                interactive = bool(t.get("interactive", False))
                channel_expected = "subscription" if interactive else "api"
                if p.get("channel") != channel_expected:
                    channels_ok = False
                # Fallback chain by type
                expected_chain = expected_fallback_chain_by_type.get(ttype)
                if p.get("fallback_chain") != expected_chain:
                    fallbacks_ok = False
            checks["plan_fields_valid"] = fields_ok
            checks["plan_models_match_constraints"] = models_ok
            checks["plan_channels_policy_ok"] = channels_ok
            checks["plan_fallback_chains_ok"] = fallbacks_ok

    # 3) Validate qc_traces.jsonl
    qc_path = os.path.join(output_dir, "qc_traces.jsonl")
    if os.path.isfile(qc_path):
        checks["qc_exists"] = True
        text, err = read_text(qc_path)
        if text is not None:
            lines = [ln for ln in text.splitlines() if ln.strip() != ""]
            if len(lines) == 2:
                checks["qc_two_lines"] = True
                parsed = []
                parse_ok = True
                for ln in lines:
                    try:
                        obj = json.loads(ln)
                        parsed.append(obj)
                    except Exception:
                        parse_ok = False
                        break
                if parse_ok:
                    ids = set([o.get("task_id") for o in parsed if isinstance(o, dict)])
                    if ids == {"T3", "T4"}:
                        checks["qc_tasks_T3_T4_only"] = True
                    # Validate steps
                    steps_structure_ok = True
                    steps_models_ok = True
                    timestamps_ok = True
                    deliver_ok = True
                    for o in parsed:
                        steps = o.get("steps")
                        if not isinstance(steps, list) or len(steps) != 5:
                            steps_structure_ok = False
                            steps_models_ok = False
                            timestamps_ok = False
                            deliver_ok = False
                            break
                        expected_names = ["produce", "review", "cross_check", "incorporate", "deliver"]
                        expected_models = ["claude-sonnet-4-6", "claude-sonnet-4-6", "gpt-4o", "claude-opus-4-6", "claude-opus-4-6"]
                        for idx, step in enumerate(steps):
                            if not isinstance(step, dict):
                                steps_structure_ok = False
                                steps_models_ok = False
                                timestamps_ok = False
                                deliver_ok = False
                                break
                            # step number and name
                            if step.get("step") != idx + 1 or step.get("name") != expected_names[idx]:
                                steps_structure_ok = False
                            # model checks
                            if step.get("model") != expected_models[idx]:
                                steps_models_ok = False
                            # timestamp presence and format
                            ts = step.get("timestamp")
                            if not is_iso8601_basic(ts):
                                timestamps_ok = False
                            # deliver step extra fields
                            if idx == 4:
                                conf = step.get("confidence")
                                concerns = step.get("unresolved_concerns")
                                if not isinstance(conf, int) or conf < 0 or conf > 100:
                                    deliver_ok = False
                                if not isinstance(concerns, list):
                                    deliver_ok = False
                    checks["qc_steps_structure_ok"] = steps_structure_ok
                    checks["qc_steps_models_order_ok"] = steps_models_ok
                    checks["qc_timestamps_present"] = timestamps_ok
                    checks["qc_deliver_confidence_and_concerns_ok"] = deliver_ok

    # Compute reward as average of True checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Baseline no-op: if output dir missing or empty or key required artifacts missing -> ensure 0
    required_files = [
        os.path.join(output_dir, "workflow.yaml"),
        os.path.join(output_dir, "plan.json"),
        os.path.join(output_dir, "qc_traces.jsonl"),
    ]
    if not all(os.path.isfile(p) for p in required_files):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()