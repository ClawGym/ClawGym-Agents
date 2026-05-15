import json
import os
import sys

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

def contains_all(text, substrings):
    return all(s in text for s in substrings)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # alignment-hub.md checks
        "hub_exists": False,
        "hub_has_sections": False,
        "hub_has_mermaid": False,
        "hub_has_capability_ids": False,
        "hub_has_adapter_selected": False,
        "hub_has_adapter_registry_entry": False,

        # news/digest.md checks
        "news_exists": False,
        "news_has_5_bullets": False,
        "news_has_3_links": False,

        # reminders/nag-config.json checks
        "nag_config_exists": False,
        "nag_config_valid_json": False,
        "nag_config_has_required_fields": False,
        "nag_config_confirm_patterns_len_ge3": False,

        # reminders/nag-state.json checks
        "nag_state_exists": False,
        "nag_state_valid_json": False,
        "nag_state_has_top_fields": False,
        "nag_state_matches_id_and_defaults": False,

        # performance/profiling-plan.md checks
        "profiling_plan_exists": False,
        "profiling_plan_has_sections": False,
        "profiling_plan_forbidden_tools_absent": False,

        # performance/adapter-native-profiler.yaml checks
        "adapter_yaml_exists": False,
        "adapter_yaml_has_required_fields": False,
        "adapter_yaml_has_id": False,

        # Cross-file checks
        "reminder_id_consistency": False,
        "adapter_id_consistency": False,
    }

    # Paths
    hub_path = os.path.join(output_dir, "alignment-hub.md")
    news_path = os.path.join(output_dir, "news", "digest.md")
    nag_config_path = os.path.join(output_dir, "reminders", "nag-config.json")
    nag_state_path = os.path.join(output_dir, "reminders", "nag-state.json")
    profiling_plan_path = os.path.join(output_dir, "performance", "profiling-plan.md")
    adapter_yaml_path = os.path.join(output_dir, "performance", "adapter-native-profiler.yaml")

    # 1) alignment-hub.md
    hub_text = read_text(hub_path)
    if hub_text is not None:
        checks["hub_exists"] = True

        required_sections = [
            "intent_snapshot:",
            "intent_lint:",
            "autonomy:",
            "strictness_policy:",
            "capability_matrix:",
            "phases:",
            "decision_log:",
            "change_log:",
            "conformance:",
        ]
        if contains_all(hub_text, required_sections):
            checks["hub_has_sections"] = True

        if "```mermaid" in hub_text and "graph TD" in hub_text:
            checks["hub_has_mermaid"] = True

        canonical_ids = [
            "intent.capture",
            "intent.lint",
            "intent.clarify",
            "plan.phase",
            "research.external",
            "repo.local.write",
            "verify.run",
            "report.emit",
            "user.checkin",
        ]
        if contains_all(hub_text, canonical_ids):
            checks["hub_has_capability_ids"] = True

        # capability_matrix.adapters_selected contains adapter-native-profiler (approximate via substring)
        if ("capability_matrix:" in hub_text) and ("adapters_selected" in hub_text) and ("adapter-native-profiler" in hub_text):
            checks["hub_has_adapter_selected"] = True

        # adapters registry block with validation_status present
        if ("adapters:" in hub_text) and ("adapter-native-profiler" in hub_text) and ("validation_status" in hub_text):
            checks["hub_has_adapter_registry_entry"] = True

    # 2) news/digest.md
    news_text = read_text(news_path)
    if news_text is not None:
        checks["news_exists"] = True
        lines = news_text.splitlines()
        bullet_count = sum(1 for ln in lines if ln.startswith("- "))
        if bullet_count >= 5:
            checks["news_has_5_bullets"] = True
        if news_text.lower().count("http") >= 3:
            checks["news_has_3_links"] = True

    # 3) reminders/nag-config.json
    nag_config = read_json(nag_config_path)
    if nag_config is not None:
        checks["nag_config_exists"] = True
        checks["nag_config_valid_json"] = True

        first_id = None
        try:
            reminders = nag_config.get("reminders")
            if isinstance(reminders, list) and len(reminders) >= 1 and isinstance(reminders[0], dict):
                r0 = reminders[0]
                required_keys = ["id", "label", "scheduleFirst", "nagAfter", "confirmPatterns", "tone"]
                has_required = all(k in r0 for k in required_keys)
                if has_required and isinstance(r0.get("confirmPatterns"), list):
                    checks["nag_config_has_required_fields"] = True
                    if len(r0.get("confirmPatterns", [])) >= 3:
                        checks["nag_config_confirm_patterns_len_ge3"] = True
                    first_id = r0.get("id")
        except Exception:
            pass
    else:
        # file missing or invalid
        if os.path.isfile(nag_config_path):
            checks["nag_config_exists"] = True

    # 4) reminders/nag-state.json
    nag_state = read_json(nag_state_path)
    if nag_state is not None:
        checks["nag_state_exists"] = True
        checks["nag_state_valid_json"] = True

        if isinstance(nag_state.get("date"), str) and isinstance(nag_state.get("reminders"), dict):
            checks["nag_state_has_top_fields"] = True

        # match ID and defaults
        try:
            if isinstance(nag_state.get("reminders"), dict):
                # use first_id from config if available
                if first_id and first_id in nag_state["reminders"]:
                    entry = nag_state["reminders"][first_id]
                    if isinstance(entry, dict) and entry.get("confirmed") is False and entry.get("nagCount") == 0:
                        checks["nag_state_matches_id_and_defaults"] = True
                        checks["reminder_id_consistency"] = True
        except Exception:
            pass
    else:
        if os.path.isfile(nag_state_path):
            checks["nag_state_exists"] = True

    # 5) performance/profiling-plan.md
    plan_text = read_text(profiling_plan_path)
    if plan_text is not None:
        checks["profiling_plan_exists"] = True
        required_headers = [
            "## Profiling Steps",
            "## Symbolication Strategy",
            "## Hotspot Ranking",
            "## Risks & Assumptions",
        ]
        if contains_all(plan_text, required_headers):
            checks["profiling_plan_has_sections"] = True
        lower = plan_text.lower()
        forbidden = ["xctrace", "instruments", "atos", "vmmap", "otool"]
        if not any(s in lower for s in forbidden):
            checks["profiling_plan_forbidden_tools_absent"] = True

    # 6) performance/adapter-native-profiler.yaml
    adapter_text = read_text(adapter_yaml_path)
    if adapter_text is not None:
        checks["adapter_yaml_exists"] = True
        required_adapter_fields = [
            "adapter_spec:",
            "id:",
            "description:",
            "capabilities:",
            "auth:",
            "inputs:",
            "outputs:",
            "result_schema:",
            "failure_modes:",
            "fallbacks:",
            "provenance:",
            "created_by:",
            "created_at:",
            "environment_assumptions:",
            "tool_access_required:",
        ]
        if contains_all(adapter_text, required_adapter_fields):
            checks["adapter_yaml_has_required_fields"] = True
        if "id: adapter-native-profiler" in adapter_text:
            checks["adapter_yaml_has_id"] = True

    # Cross-file adapter consistency: hub has adapter selected and YAML has the id
    if checks["hub_has_adapter_selected"] and checks["adapter_yaml_has_id"]:
        checks["adapter_id_consistency"] = True

    # Compute reward: fraction of passed objective checks
    # All checks here are objective and depend on output/.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    # Print exactly one JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()