import json
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

def load_json(path: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def deep_find_strings(obj: Any) -> List[str]:
    out: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                out.append(k)
            out.extend(deep_find_strings(v))
    elif isinstance(obj, list):
        for it in obj:
            out.extend(deep_find_strings(it))
    elif isinstance(obj, str):
        out.append(obj)
    return out

def normalize_type(t: Any) -> Optional[str]:
    if isinstance(t, list):
        for x in t:
            nt = normalize_type(x)
            if nt:
                return nt
        return None
    if not isinstance(t, str):
        return None
    s = t.strip().lower()
    if s in ("string", "integer", "number", "boolean", "object", "array"):
        return s
    if s in ("int",):
        return "integer"
    if s in ("float", "double", "decimal"):
        return "number"
    if s in ("bool",):
        return "boolean"
    return s

def jsonschema_has_type(prop: Any, expected: str) -> bool:
    if not isinstance(prop, dict):
        return False
    t = prop.get("type")
    if t is None:
        # If no type specified, cannot verify; consider False to enforce schema presence
        return False
    if isinstance(t, list):
        return expected in [normalize_type(x) for x in t if isinstance(x, str)]
    return normalize_type(t) == expected

def collect_tools_from_architecture(arch: Dict[str, Any]) -> Set[str]:
    found: Set[str] = set()
    # Search per-agent tools
    agents = arch.get("agents")
    def collect_from_obj(o: Any):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and "tool" in k.lower():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                found.add(item)
                    elif isinstance(v, dict):
                        for kk, vv in v.items():
                            if isinstance(kk, str):
                                found.add(kk)
                            if isinstance(vv, str):
                                found.add(vv)
                collect_from_obj(v)
        elif isinstance(o, list):
            for it in o:
                collect_from_obj(it)
    if isinstance(agents, list):
        for ag in agents:
            collect_from_obj(ag)
    # Top-level mappings
    for key in ["tools_mapping", "tool_mapping", "tool_to_agent", "tools_to_agents"]:
        if isinstance(arch.get(key), dict):
            for tool_name in arch[key].keys():
                if isinstance(tool_name, str):
                    found.add(tool_name)
    # Also scan top-level "tools" array of strings if present
    if isinstance(arch.get("tools"), list):
        for t in arch["tools"]:
            if isinstance(t, str):
                found.add(t)
    return set(x for x in found if isinstance(x, str))

def get_expected_tools(input_tools_json: Any) -> List[Dict[str, Any]]:
    tools_list: List[Dict[str, Any]] = []
    if isinstance(input_tools_json, dict) and isinstance(input_tools_json.get("tools"), list):
        for t in input_tools_json["tools"]:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                tools_list.append(t)
    elif isinstance(input_tools_json, list):
        for t in input_tools_json:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                tools_list.append(t)
    return tools_list

def extract_tool_params(tool: Dict[str, Any]) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []
    inputs = tool.get("inputs")
    if isinstance(inputs, list):
        for p in inputs:
            if isinstance(p, dict) and isinstance(p.get("name"), str):
                params.append(p)
    return params

def properties_match_inputs(properties: Any, inputs: List[Dict[str, Any]]) -> bool:
    if not isinstance(properties, dict):
        return False
    for p in inputs:
        pname = p.get("name")
        ptype = p.get("type")
        if not isinstance(pname, str):
            return False
        if pname not in properties:
            return False
        # If type given, ensure JSON schema property has matching type
        if isinstance(ptype, str):
            if not jsonschema_has_type(properties[pname], normalize_type(ptype) or ptype.lower()):
                return False
    return True

def required_match_inputs(required_list: Any, inputs: List[Dict[str, Any]]) -> bool:
    if not isinstance(required_list, list):
        return False
    req_set = set([n for n in required_list if isinstance(n, str)])
    expected_req = set([p["name"] for p in inputs if isinstance(p.get("required"), bool) and p["required"]])
    # All expected required must be included
    if not expected_req.issubset(req_set):
        return False
    # No required names that are not any input names
    all_input_names = set(p["name"] for p in inputs)
    if not req_set.issubset(all_input_names):
        return False
    return True

def find_recommendations_list(obj: Any) -> Optional[List[Any]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        recs = obj.get("recommendations")
        if isinstance(recs, list):
            return recs
    return None

def has_heading_h2(text: str) -> bool:
    for line in text.splitlines():
        if line.strip().startswith("##"):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # Architecture files
        "has_architecture_json": False,
        "architecture_pattern_valid": False,
        "architecture_agents_valid": False,
        "architecture_communication_valid": False,
        "architecture_safety_mentions": False,
        "architecture_tools_mapped_all": False,
        "has_architecture_diagram": False,
        "diagram_mermaid_and_arrow": False,
        "diagram_contains_pattern": False,
        "has_architecture_roadmap_json": False,
        "roadmap_phases_valid": False,
        # Tool schemas
        "has_tools_openai_json": False,
        "tools_openai_match_inputs": False,
        "has_tools_anthropic_json": False,
        "tools_anthropic_match_inputs": False,
        "has_tools_validation_json": False,
        "tools_validation_covers_all": False,
        # Evaluation files
        "has_evaluation_json": False,
        "evaluation_required_keys": False,
        "evaluation_summary_success_rate_bounds": False,
        "has_evaluation_summary_json": False,
        "evaluation_summary_keys": False,
        "has_evaluation_recommendations_json": False,
        "recommendations_count_and_fields": False,
        # Rationale
        "has_design_rationale_md": False,
        "rationale_length_and_heading_and_pattern": False,
    }

    # Paths
    arch_json_path = os.path.join(output_dir, "architecture.json")
    arch_diagram_path = os.path.join(output_dir, "architecture_diagram.md")
    arch_roadmap_path = os.path.join(output_dir, "architecture_roadmap.json")

    tools_openai_path = os.path.join(output_dir, "tools_openai.json")
    tools_anthropic_path = os.path.join(output_dir, "tools_anthropic.json")
    tools_validation_path = os.path.join(output_dir, "tools_validation.json")

    evaluation_path = os.path.join(output_dir, "evaluation.json")
    evaluation_summary_path = os.path.join(output_dir, "evaluation_summary.json")
    evaluation_recs_path = os.path.join(output_dir, "evaluation_recommendations.json")

    rationale_path = os.path.join(output_dir, "design_rationale.md")

    input_tools_path = os.path.join(input_dir, "tools.json")

    # Load expected tool set from input
    input_tools_json, _ = load_json(input_tools_path)
    expected_tools: List[Dict[str, Any]] = get_expected_tools(input_tools_json) if input_tools_json is not None else []
    expected_tool_names: Set[str] = set([t["name"] for t in expected_tools if isinstance(t.get("name"), str)])

    # 1) Architecture.json
    arch_json, arch_err = load_json(arch_json_path)
    if arch_json is not None and isinstance(arch_json, dict):
        checks["has_architecture_json"] = True

        # pattern
        pattern = arch_json.get("pattern")
        allowed_patterns = {"Single Agent", "Supervisor", "Swarm", "Hierarchical", "Pipeline"}
        if isinstance(pattern, str) and pattern in allowed_patterns:
            checks["architecture_pattern_valid"] = True

        # agents
        agents = arch_json.get("agents")
        if isinstance(agents, list) and len(agents) >= 3:
            # each agent must include identity/name and responsibilities
            valid_all = True
            for ag in agents:
                if not isinstance(ag, dict):
                    valid_all = False
                    break
                has_name = False
                if isinstance(ag.get("name"), str) and ag.get("name").strip():
                    has_name = True
                identity = ag.get("identity")
                if isinstance(identity, dict) and isinstance(identity.get("name"), str) and identity.get("name").strip():
                    has_name = True or has_name
                has_resp = False
                resp = ag.get("responsibilities")
                if isinstance(resp, list) and len(resp) > 0:
                    has_resp = True
                if not (has_name and has_resp):
                    valid_all = False
                    break
            if valid_all:
                checks["architecture_agents_valid"] = True

        # communication object with pattern field
        comm = arch_json.get("communication")
        if isinstance(comm, dict) and isinstance(comm.get("pattern"), str) and comm.get("pattern").strip():
            checks["architecture_communication_valid"] = True

        # safety mentions both "input validation" and "output filtering"
        safety = arch_json.get("safety")
        if safety is not None:
            strings = " ".join(deep_find_strings(safety)).lower()
            if ("input validation" in strings) and ("output filtering" in strings):
                checks["architecture_safety_mentions"] = True

        # tools mapping referencing tool names from input/tools.json assigned to at least one agent
        if expected_tool_names:
            mapped = collect_tools_from_architecture(arch_json)
            if expected_tool_names.issubset(mapped):
                checks["architecture_tools_mapped_all"] = True

    # 1b) architecture_diagram.md
    diagram_text, diag_err = read_text(arch_diagram_path)
    if diagram_text is not None:
        checks["has_architecture_diagram"] = True
        low = diagram_text.lower()
        if ("```mermaid" in low) and ("-->" in diagram_text):
            checks["diagram_mermaid_and_arrow"] = True
        # include pattern label somewhere
        if isinstance(arch_json, dict):
            pattern = arch_json.get("pattern")
            if isinstance(pattern, str) and pattern.lower() in low:
                checks["diagram_contains_pattern"] = True

    # 1c) architecture_roadmap.json
    arch_roadmap, road_err = load_json(arch_roadmap_path)
    if arch_roadmap is not None and isinstance(arch_roadmap, dict):
        checks["has_architecture_roadmap_json"] = True
        phases = arch_roadmap.get("phases")
        if isinstance(phases, list) and len(phases) >= 3:
            ok_phases = True
            for ph in phases:
                if not isinstance(ph, dict):
                    ok_phases = False
                    break
                if not (isinstance(ph.get("name"), str) and ph.get("name").strip()):
                    ok_phases = False
                    break
                # deliverables could be a list or dict; require existence
                deliv = ph.get("deliverables")
                if deliv is None:
                    ok_phases = False
                    break
            if ok_phases:
                checks["roadmap_phases_valid"] = True

    # 2) tools_openai.json
    tools_openai, openai_err = load_json(tools_openai_path)
    if tools_openai is not None and isinstance(tools_openai, dict):
        checks["has_tools_openai_json"] = True
        functions = tools_openai.get("functions")
        if isinstance(functions, list) and expected_tools:
            # names set must match exactly the tool names from input
            fn_names = set([f.get("name") for f in functions if isinstance(f, dict) and isinstance(f.get("name"), str)])
            if fn_names == expected_tool_names and len(functions) == len(expected_tools):
                all_ok = True
                # validate schema for each function
                tool_by_name = {t["name"]: t for t in expected_tools}
                for f in functions:
                    if not isinstance(f, dict):
                        all_ok = False
                        break
                    name = f.get("name")
                    desc = f.get("description")
                    params = f.get("parameters")
                    if not (isinstance(name, str) and isinstance(desc, str) and isinstance(params, dict)):
                        all_ok = False
                        break
                    if not jsonschema_has_type(params, "object"):
                        all_ok = False
                        break
                    props = params.get("properties")
                    req = params.get("required")
                    expected_inputs = extract_tool_params(tool_by_name[name])
                    if not properties_match_inputs(props, expected_inputs):
                        all_ok = False
                        break
                    if not required_match_inputs(req, expected_inputs):
                        all_ok = False
                        break
                if all_ok:
                    checks["tools_openai_match_inputs"] = True

    # 2b) tools_anthropic.json
    tools_anthropic, anth_err = load_json(tools_anthropic_path)
    if tools_anthropic is not None and isinstance(tools_anthropic, dict):
        checks["has_tools_anthropic_json"] = True
        tools_arr = tools_anthropic.get("tools")
        if isinstance(tools_arr, list) and expected_tools:
            t_names = set([t.get("name") for t in tools_arr if isinstance(t, dict) and isinstance(t.get("name"), str)])
            if t_names == expected_tool_names and len(tools_arr) == len(expected_tools):
                all_ok_a = True
                tool_by_name = {t["name"]: t for t in expected_tools}
                for t in tools_arr:
                    if not isinstance(t, dict):
                        all_ok_a = False
                        break
                    name = t.get("name")
                    desc = t.get("description")
                    inp = t.get("input_schema")
                    if not (isinstance(name, str) and isinstance(desc, str) and isinstance(inp, dict)):
                        all_ok_a = False
                        break
                    if not jsonschema_has_type(inp, "object"):
                        all_ok_a = False
                        break
                    props = inp.get("properties")
                    req = inp.get("required")
                    expected_inputs = extract_tool_params(tool_by_name[name])
                    if not properties_match_inputs(props, expected_inputs):
                        all_ok_a = False
                        break
                    if not required_match_inputs(req, expected_inputs):
                        all_ok_a = False
                        break
                if all_ok_a:
                    checks["tools_anthropic_match_inputs"] = True

    # 2c) tools_validation.json
    tools_validation, val_err = load_json(tools_validation_path)
    if tools_validation is not None:
        checks["has_tools_validation_json"] = True
        # Normalize to dict name -> entry
        name_to_entry: Dict[str, Any] = {}
        if isinstance(tools_validation, dict):
            # could be dict of name->entry or object with "tools"
            if isinstance(tools_validation.get("tools"), list):
                for entry in tools_validation["tools"]:
                    if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                        name_to_entry[entry["name"]] = entry
            else:
                for k, v in tools_validation.items():
                    if isinstance(v, dict):
                        name_to_entry[k] = v
        elif isinstance(tools_validation, list):
            for entry in tools_validation:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    name_to_entry[entry["name"]] = entry
        ok_val = True
        if expected_tools:
            for tool in expected_tools:
                tname = tool.get("name")
                entry = name_to_entry.get(tname)
                if not entry:
                    ok_val = False
                    break
                # Must include idempotent (boolean) and rate_limits (any object/dict)
                if not isinstance(entry.get("idempotent"), bool):
                    ok_val = False
                    break
                rl = entry.get("rate_limits")
                if not isinstance(rl, (dict, list, str, int, float)) and rl is not None:
                    # allow simple scalar or dict/list; but must exist
                    pass
                if rl is None:
                    ok_val = False
                    break
                # Inputs must enumerate each tool input with name, type, required
                v_inputs = entry.get("inputs")
                expected_inputs = extract_tool_params(tool)
                if not isinstance(v_inputs, list):
                    ok_val = False
                    break
                v_map = {vi.get("name"): vi for vi in v_inputs if isinstance(vi, dict) and isinstance(vi.get("name"), str)}
                for p in expected_inputs:
                    vi = v_map.get(p.get("name"))
                    if not vi:
                        ok_val = False
                        break
                    if "type" not in vi or normalize_type(vi.get("type")) != normalize_type(p.get("type")):
                        ok_val = False
                        break
                    if not isinstance(vi.get("required"), bool) or bool(vi.get("required")) != bool(p.get("required")):
                        ok_val = False
                        break
                if not ok_val:
                    break
        else:
            ok_val = False
        if ok_val:
            checks["tools_validation_covers_all"] = True

    # 3) Evaluation files
    evaluation, eval_err = load_json(evaluation_path)
    if evaluation is not None and isinstance(evaluation, dict):
        checks["has_evaluation_json"] = True
        required_keys_ok = True
        for k in ["summary", "system_metrics", "agent_metrics", "tool_usage_analysis", "error_analysis", "bottleneck_analysis", "optimization_recommendations"]:
            if k not in evaluation:
                required_keys_ok = False
                break
        if required_keys_ok:
            # Type checks
            if not isinstance(evaluation.get("summary"), dict):
                required_keys_ok = False
            if not isinstance(evaluation.get("system_metrics"), dict):
                required_keys_ok = False
            if not isinstance(evaluation.get("agent_metrics"), dict):
                required_keys_ok = False
            if not isinstance(evaluation.get("tool_usage_analysis"), dict):
                required_keys_ok = False
            if not isinstance(evaluation.get("error_analysis"), list):
                required_keys_ok = False
            if not isinstance(evaluation.get("bottleneck_analysis"), list):
                required_keys_ok = False
            if not (isinstance(evaluation.get("optimization_recommendations"), list) and len(evaluation.get("optimization_recommendations")) >= 2):
                required_keys_ok = False
        if required_keys_ok:
            checks["evaluation_required_keys"] = True
        # success_rate bounds
        summ = evaluation.get("summary")
        if isinstance(summ, dict):
            sr = summ.get("success_rate")
            if isinstance(sr, (int, float)) and 0 <= float(sr) <= 1:
                checks["evaluation_summary_success_rate_bounds"] = True

    # evaluation_summary.json
    eval_summary, es_err = load_json(evaluation_summary_path)
    if eval_summary is not None and isinstance(eval_summary, dict):
        checks["has_evaluation_summary_json"] = True
        overall_health_ok = isinstance(eval_summary.get("overall_health"), str)
        key_metric_ok = False
        if isinstance(eval_summary.get("success_rate"), (int, float)):
            key_metric_ok = True
        if isinstance(eval_summary.get("total_cost_usd"), (int, float)):
            key_metric_ok = True
        checks["evaluation_summary_keys"] = overall_health_ok and key_metric_ok

    # evaluation_recommendations.json
    eval_recs, er_err = load_json(evaluation_recs_path)
    if eval_recs is not None:
        checks["has_evaluation_recommendations_json"] = True
        recs = find_recommendations_list(eval_recs)
        if isinstance(recs, list) and len(recs) >= 2:
            all_ok = True
            for r in recs:
                if not (isinstance(r, dict) and isinstance(r.get("priority"), str) and isinstance(r.get("title"), str)):
                    all_ok = False
                    break
            if all_ok:
                checks["recommendations_count_and_fields"] = True

    # 4) design_rationale.md
    rationale_text, rat_err = read_text(rationale_path)
    if rationale_text is not None:
        checks["has_design_rationale_md"] = True
        long_enough = len(rationale_text) >= 500
        has_h2 = has_heading_h2(rationale_text)
        pattern_ok = False
        if isinstance(arch_json, dict):
            pattern = arch_json.get("pattern")
            if isinstance(pattern, str) and (pattern.lower() in rationale_text.lower()):
                pattern_ok = True
        checks["rationale_length_and_heading_and_pattern"] = bool(long_enough and has_h2 and pattern_ok)

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0: if output dir missing or empty, force reward 0.0
    if not os.path.isdir(output_dir) or not any(True for _ in os.scandir(output_dir)):
        reward = 0.0

    # Print result JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()