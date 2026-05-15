import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # Presence checks
        "has_agent_graph": False,
        "has_readme": False,
        "has_metacognition": False,
        "has_sample_runs": False,
        # agent_graph.py content checks
        "ag_typed_state": False,
        "ag_annotated": False,
        "ag_add_messages": False,
        "ag_stategraph": False,
        "ag_add_node": False,
        "ag_add_edge": False,
        "ag_add_conditional_edges": False,
        "ag_toolnode": False,
        "ag_interrupt_hitl": False,
        "ag_checkpointer_persist": False,
        "ag_streaming_support": False,
        "ag_invoke_support": False,
        # README.md content checks
        "readme_keywords_all": False,
        # METACOGNITION.md content checks
        "meta_has_all_stages": False,
        # sample_runs.json checks
        "samples_valid_json": False,
        "samples_has_true_case": False,
        "samples_has_false_case": False,
        "samples_has_expected_flow": False,
        "samples_examples_ge2": False,
    }

    # Resolve paths
    agent_graph_path = os.path.join(output_dir, "agent_graph.py")
    readme_path = os.path.join(output_dir, "README.md")
    metacog_path = os.path.join(output_dir, "METACOGNITION.md")
    samples_path = os.path.join(output_dir, "sample_runs.json")

    # Presence
    if os.path.isfile(agent_graph_path):
        checks["has_agent_graph"] = True
    if os.path.isfile(readme_path):
        checks["has_readme"] = True
    if os.path.isfile(metacog_path):
        checks["has_metacognition"] = True
    if os.path.isfile(samples_path):
        checks["has_sample_runs"] = True

    # agent_graph.py structural/code-pattern checks
    if checks["has_agent_graph"]:
        ag = read_text(agent_graph_path)
        ag_lower = ag.lower()

        # Typed state and reducers
        if "TypedDict" in ag:
            checks["ag_typed_state"] = True
        if "Annotated" in ag:
            checks["ag_annotated"] = True
        if "add_messages" in ag:
            checks["ag_add_messages"] = True

        # Graph construction and edges
        if "StateGraph" in ag:
            checks["ag_stategraph"] = True
        if "add_node(" in ag:
            checks["ag_add_node"] = True
        if "add_edge(" in ag:
            checks["ag_add_edge"] = True
        if "add_conditional_edges(" in ag:
            checks["ag_add_conditional_edges"] = True

        # Tool execution integration
        if "ToolNode" in ag:
            checks["ag_toolnode"] = True

        # Human-in-the-loop and persistence within compile
        # We consider satisfied if both 'compile(' and the respective keyword appear in the file.
        if ("compile(" in ag) and ("interrupt_before=" in ag):
            checks["ag_interrupt_hitl"] = True
        if ("compile(" in ag) and ("checkpointer=" in ag):
            checks["ag_checkpointer_persist"] = True

        # Streaming and invocation support
        if ".stream(" in ag or " stream(" in ag:
            checks["ag_streaming_support"] = True
        if "invoke(" in ag:
            checks["ag_invoke_support"] = True

    # README keywords (case-insensitive)
    if checks["has_readme"]:
        rd = read_text(readme_path).lower()
        # Required keywords
        required_tokens = [
            "state schema",
            "reducers",
            "control flow",
            "conditional routing",
            "persistence",
            "streaming",
            "supervisor",
        ]
        # Accept both hyphenated and spaced forms for human-in-the-loop and multi-actor
        human_tokens_ok = ("human-in-the-loop" in rd) or ("human in the loop" in rd)
        multiactor_tokens_ok = ("multi-actor" in rd) or ("multi actor" in rd)

        if all(tok in rd for tok in required_tokens) and human_tokens_ok and multiactor_tokens_ok:
            checks["readme_keywords_all"] = True

    # METACOGNITION.md stage names (exact phrases)
    if checks["has_metacognition"]:
        mc = read_text(metacog_path)
        stages = [
            "Intent Decoding",
            "Difficulty Assessment",
            "Boundary Declaration",
            "Execution Monitoring",
            "Delivery Validation",
        ]
        if all(s in mc for s in stages):
            checks["meta_has_all_stages"] = True

    # sample_runs.json validity and contents
    if checks["has_sample_runs"]:
        content = read_text(samples_path)
        # JSON validity
        parsed = None
        try:
            parsed = json.loads(content)
            checks["samples_valid_json"] = True
        except Exception:
            parsed = None

        # Presence of true/false requires_approval and expected_flow
        if '"requires_approval": true' in content:
            checks["samples_has_true_case"] = True
        if '"requires_approval": false' in content:
            checks["samples_has_false_case"] = True
        if '"expected_flow"' in content:
            checks["samples_has_expected_flow"] = True

        # Count at least two example objects
        if parsed is not None:
            count_objs = 0
            if isinstance(parsed, list):
                count_objs = sum(1 for x in parsed if isinstance(x, dict))
            elif isinstance(parsed, dict):
                # Count dict-like entries in values
                count_objs = sum(1 for v in parsed.values() if isinstance(v, dict))
                # If values are lists of dicts, count at least first two dicts total
                if count_objs == 0:
                    lsts = [v for v in parsed.values() if isinstance(v, list)]
                    for lst in lsts:
                        for x in lst:
                            if isinstance(x, dict):
                                count_objs += 1
            if count_objs >= 2:
                checks["samples_examples_ge2"] = True

    # Compute reward: fraction of passed checks.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or all four deliverables missing, reward must be 0.0
    essential_missing = not (checks["has_agent_graph"] or checks["has_readme"] or checks["has_metacognition"] or checks["has_sample_runs"])
    if (not os.path.isdir(output_dir)) or essential_missing:
        reward = 0.0
    else:
        # Normalized score between 0 and 1
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print final JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()