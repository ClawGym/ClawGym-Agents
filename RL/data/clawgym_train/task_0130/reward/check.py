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

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected constants from task spec
    expected_provider = "OpenAI"
    expected_auth_method = "login"
    expected_session = "LandingPage Popup CRO Audit"
    expected_login_url = "https://auth.opencode.dev/openai/start?token=abc123"

    # Initialize checks
    checks = {
        "has_session_log": False,
        "has_approved_plan": False,
        "has_implementation_requests": False,
        "has_artifacts_json": False,
        "log_has_opencode_before_sessions": False,
        "log_slash_command_order": False,
        "log_selected_session_line": False,
        "log_selected_model_provider_line": False,
        "log_contains_login_url": False,
        "log_plan_before_build": False,
        "log_switched_back_and_returned_to_build": False,
        "plan_min_steps": False,
        "impl_requests_exactly_two_prefixed_lines": False,
        "artifacts_fields_valid": False
    }

    # Paths
    session_log_path = os.path.join(output_dir, "session_log.txt")
    approved_plan_path = os.path.join(output_dir, "approved_plan.md")
    impl_requests_path = os.path.join(output_dir, "implementation_requests.txt")
    artifacts_json_path = os.path.join(output_dir, "artifacts.json")

    # Load files
    session_log = read_text(session_log_path)
    if session_log is not None:
        checks["has_session_log"] = True

        # Order checks
        idx_opencode = session_log.find("opencode")
        idx_sessions = session_log.find("/sessions")
        idx_models = session_log.find("/models")
        idx_agents = session_log.find("/agents")

        if idx_opencode != -1 and idx_sessions != -1 and idx_opencode < idx_sessions:
            checks["log_has_opencode_before_sessions"] = True

        if idx_sessions != -1 and idx_models != -1 and idx_agents != -1:
            if idx_sessions < idx_models < idx_agents:
                checks["log_slash_command_order"] = True

        # Selected session exact line
        lines = session_log.splitlines()
        if any(line.strip() == f"Selected session: {expected_session}" for line in lines):
            checks["log_selected_session_line"] = True

        # Selected model provider exact line
        if any(line.strip() == f"Selected model provider: {expected_provider}" for line in lines):
            checks["log_selected_model_provider_line"] = True

        # Login URL presence
        if expected_login_url in session_log:
            checks["log_contains_login_url"] = True

        # Plan before Build
        idx_plan_sel = session_log.find("Selected agent: Plan")
        idx_build_sel = session_log.find("Selected agent: Build")
        if idx_plan_sel != -1 and idx_build_sel != -1 and idx_plan_sel < idx_build_sel:
            checks["log_plan_before_build"] = True

        # Switched back to Plan and then returned to Build
        idx_switched_back = session_log.find("Switched back to Plan")
        # Find any later Build selection after switch back
        later_build_found = False
        if idx_switched_back != -1:
            idx_build_after = session_log.find("Selected agent: Build", idx_switched_back + 1)
            if idx_build_after != -1:
                later_build_found = True
        if idx_switched_back != -1 and later_build_found:
            checks["log_switched_back_and_returned_to_build"] = True

    # Plan steps
    plan_steps_count = 0
    approved_plan = read_text(approved_plan_path)
    if approved_plan is not None:
        checks["has_approved_plan"] = True
        for line in approved_plan.splitlines():
            if line.startswith("- "):
                plan_steps_count += 1
        if plan_steps_count >= 6:
            checks["plan_min_steps"] = True

    # Implementation requests
    impl_requests_text = read_text(impl_requests_path)
    if impl_requests_text is not None:
        checks["has_implementation_requests"] = True
        nonempty_lines = [ln for ln in (l.strip("\n\r") for l in impl_requests_text.splitlines()) if ln.strip() != ""]
        prefixed = [ln for ln in nonempty_lines if ln.startswith("BUILD REQUEST:")]
        if len(nonempty_lines) == 2 and len(prefixed) == 2:
            checks["impl_requests_exactly_two_prefixed_lines"] = True

    # Artifacts json
    artifacts = read_json(artifacts_json_path)
    if isinstance(artifacts, dict):
        checks["has_artifacts_json"] = True
        try:
            provider_ok = artifacts.get("provider") == expected_provider
            auth_method_ok = artifacts.get("auth_method") == expected_auth_method
            selected_session_ok = artifacts.get("selected_session") == expected_session
            selected_model_provider_ok = artifacts.get("selected_model_provider") == expected_provider
            login_link_ok = artifacts.get("login_link") == expected_login_url
            auth_confirmed_ok = artifacts.get("auth_confirmed") is True
            plan_steps_count_ok = isinstance(artifacts.get("plan_steps_count"), int) and artifacts.get("plan_steps_count") == plan_steps_count and plan_steps_count >= 6
            plan_revisions_ok = artifacts.get("plan_revisions") == 1
            build_requests_ok = artifacts.get("build_requests") == 2
            switched_back_ok = artifacts.get("switched_back_to_plan_on_question") is True
            completed_ok = artifacts.get("completed") is True

            if all([
                provider_ok,
                auth_method_ok,
                selected_session_ok,
                selected_model_provider_ok,
                login_link_ok,
                auth_confirmed_ok,
                plan_steps_count_ok,
                plan_revisions_ok,
                build_requests_ok,
                switched_back_ok,
                completed_ok
            ]):
                checks["artifacts_fields_valid"] = True
        except Exception:
            checks["artifacts_fields_valid"] = False

    # Compute reward: 1.0 only if all checks True
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()