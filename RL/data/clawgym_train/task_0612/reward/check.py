import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    paths = {
        "orchestration_plan": os.path.join(output_dir, "team", "orchestration_plan.md"),
        "tasks_json": os.path.join(output_dir, "team", "tasks.json"),
        "handoffs": os.path.join(output_dir, "team", "handoffs.md"),
        "build_review": os.path.join(output_dir, "team", "reviews", "build_review.md"),
        "final_approval": os.path.join(output_dir, "team", "reviews", "final_approval.md"),
        "icp": os.path.join(output_dir, "sales", "icp.yaml"),
        "sequence": os.path.join(output_dir, "sales", "sequence.md"),
        "qualification": os.path.join(output_dir, "sales", "qualification.yaml"),
        "ai_guidance": os.path.join(output_dir, "ai", "guidance.md"),
        "agents_inventory": os.path.join(output_dir, "ops", "agents_inventory.json"),
        "healthcheck": os.path.join(output_dir, "ops", "healthcheck.json"),
        "standup": os.path.join(output_dir, "ops", "standup.md"),
    }

    # Initialize checks
    checks = {
        # Existence checks
        "exists_orchestration_plan": False,
        "exists_tasks_json": False,
        "exists_handoffs": False,
        "exists_build_review": False,
        "exists_final_approval": False,
        "exists_icp": False,
        "exists_sequence": False,
        "exists_qualification": False,
        "exists_ai_guidance": False,
        "exists_agents_inventory": False,
        "exists_healthcheck": False,
        "exists_standup": False,
        # Structure/content checks
        "tasks_json_is_array": False,
        "tasks_json_has_required_keys": False,
        "tasks_json_states_cover": False,
        "plan_has_required_terms": False,
        "plan_denies_orchestrator_execution": False,
        "handoffs_has_required_sections": False,
        "build_review_has_approved_or_feedback": False,
        "final_approval_has_approved_or_feedback": False,
        "icp_has_required_sections": False,
        "sequence_has_required_content": False,
        "qualification_has_required_keys": False,
        "guidance_has_required_terms": False,
        "agents_inventory_valid": False,
        "healthcheck_valid": False,
        "standup_has_sections": False,
    }

    # 1) Existence checks
    for key, p in paths.items():
        exists_key = f"exists_{key}" if not key.startswith("exists_") else key
        if os.path.isfile(p):
            checks[exists_key] = True

    # 2) Task board structure
    if checks["exists_tasks_json"]:
        tasks_data = load_json(paths["tasks_json"])
        if isinstance(tasks_data, list):
            checks["tasks_json_is_array"] = True
            # Check required keys in each element
            required_task_keys = {"id", "title", "role", "assignee", "state", "output_path"}
            all_have_keys = True
            states = set()
            for item in tasks_data:
                if not isinstance(item, dict) or not required_task_keys.issubset(set(item.keys())):
                    all_have_keys = False
                    break
                # Collect states
                state_val = item.get("state")
                if isinstance(state_val, str):
                    states.add(state_val)
            if all_have_keys and len(tasks_data) > 0:
                checks["tasks_json_has_required_keys"] = True
            # Check state coverage
            required_states = {"Inbox", "Assigned", "In Progress", "Review", "Done"}
            if required_states.issubset(states):
                checks["tasks_json_states_cover"] = True

    # 3) Orchestration plan content
    if checks["exists_orchestration_plan"]:
        plan_text = read_text(paths["orchestration_plan"])
        if plan_text is not None:
            # Must include "Output Path", "Handoff", and lifecycle terms
            terms_ok = all(term in plan_text for term in ["Output Path", "Handoff", "Inbox", "Assigned", "In Progress", "Review", "Done"])
            checks["plan_has_required_terms"] = terms_ok
            # orchestrator does not do execution work — match presence of all three tokens
            low = plan_text.lower()
            denies = ("orchestrator" in low) and ("does not" in low) and ("execution" in low)
            checks["plan_denies_orchestrator_execution"] = denies

    # 4) Handoffs sections
    if checks["exists_handoffs"]:
        handoffs_text = read_text(paths["handoffs"])
        if handoffs_text is not None:
            low = handoffs_text.lower()
            reqs = [
                "what was done",
                "where artifacts are",
                "how to verify",
                "known issues",
            ]
            # Accept curly or straight apostrophe for What's next
            whats_curly = "what’s next"
            whats_straight = "what's next"
            has_all = all(r in low for r in reqs) and ((whats_curly in low) or (whats_straight in low))
            checks["handoffs_has_required_sections"] = has_all

    # 5) Reviews keywords
    if checks["exists_build_review"]:
        t = read_text(paths["build_review"])
        if t is not None:
            low = t.lower()
            if ("approved" in low) or ("feedback" in low):
                checks["build_review_has_approved_or_feedback"] = True
    if checks["exists_final_approval"]:
        t = read_text(paths["final_approval"])
        if t is not None:
            low = t.lower()
            if ("approved" in low) or ("feedback" in low):
                checks["final_approval_has_approved_or_feedback"] = True

    # 6) Sales kit checks
    if checks["exists_icp"]:
        t = read_text(paths["icp"])
        if t is not None:
            low = t.lower()
            if ("icp:" in low) and ("buyer_personas" in low) and ("anti-signals" in low):
                checks["icp_has_required_sections"] = True

    if checks["exists_sequence"]:
        t = read_text(paths["sequence"])
        if t is not None:
            low = t.lower()
            channels_ok = ("email" in low) and ("linkedin" in low) and ("phone" in low)
            day_pattern = re.search(r"\bday\s+\d+\b", low) is not None
            checks["sequence_has_required_content"] = channels_ok and day_pattern

    if checks["exists_qualification"]:
        t = read_text(paths["qualification"])
        if t is not None:
            low = t.lower()
            keys = ["metrics", "economic_buyer", "decision_criteria", "decision_process", "paper_process", "identified_pain", "champion", "competition", "total_score"]
            checks["qualification_has_required_keys"] = all(k in low for k in keys)

    # 7) AI guidance checks
    if checks["exists_ai_guidance"]:
        t = read_text(paths["ai_guidance"])
        if t is not None:
            low = t.lower()
            terms = ["rag", "fine-tuning", "7b", "13b", "70b", "8gb", "16gb", "48gb", "local", "api"]
            checks["guidance_has_required_terms"] = all(term in low for term in terms)

    # 8) Ops checks
    if checks["exists_agents_inventory"]:
        data = load_json(paths["agents_inventory"])
        if isinstance(data, dict) and "agents" in data and isinstance(data["agents"], list):
            agents = data["agents"]
            if len(agents) >= 1:
                all_have = True
                for a in agents:
                    if not isinstance(a, dict):
                        all_have = False
                        break
                    if "name" not in a or "role" not in a:
                        all_have = False
                        break
                if all_have:
                    checks["agents_inventory_valid"] = True

    if checks["exists_healthcheck"]:
        data = load_json(paths["healthcheck"])
        if isinstance(data, dict):
            has_keys = all(k in data for k in ["shared_dirs", "agents_inventory_path", "status"])
            path_ok = data.get("agents_inventory_path") == "output/ops/agents_inventory.json"
            if has_keys and path_ok:
                checks["healthcheck_valid"] = True

    if checks["exists_standup"]:
        t = read_text(paths["standup"])
        if t is not None:
            low = t.lower()
            sections_ok = all(s in low for s in ["completed", "in progress", "blocked", "stale"])
            checks["standup_has_sections"] = sections_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty of required artifacts, reward will already be 0.0 due to checks being False.
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()