import json
import os
import sys
import re

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_models(models):
    norm = []
    for m in models or []:
        if isinstance(m, dict):
            mid = str(m.get("id", "")).strip()
            alias = m.get("alias", None)
            alias = "" if alias is None else str(alias).strip()
            if mid:
                norm.append({"id": mid, "alias": alias})
        else:
            # Unsupported shape; skip
            pass
    return norm

def extract_models_and_default(models_json):
    models = []
    current_default = None
    if isinstance(models_json, dict):
        # Common keys
        for key in ["models", "inventory", "available", "list"]:
            if isinstance(models_json.get(key), list):
                models = normalize_models(models_json.get(key))
                break
        # default keys
        for dkey in ["current_default", "default", "current", "default_model"]:
            if models_json.get(dkey):
                current_default = str(models_json.get(dkey)).strip()
                break
    elif isinstance(models_json, list):
        models = normalize_models(models_json)
        current_default = None
    return models, current_default

def read_test_matrix(path):
    data = safe_read_json(path)
    mapping = {}
    if isinstance(data, dict):
        # assume id -> status mapping
        for k, v in data.items():
            if isinstance(v, str):
                mapping[str(k).strip()] = v.strip().lower()
    elif isinstance(data, list):
        # array of objects with id/status
        for item in data:
            if isinstance(item, dict):
                mid = item.get("id")
                status = item.get("status")
                if mid is not None and isinstance(status, str):
                    mapping[str(mid).strip()] = status.strip().lower()
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                mapping[str(item[0]).strip()] = str(item[1]).strip().lower()
    return mapping

def read_selection(path):
    data = safe_read_json(path)
    chosen = None
    restart_confirm = None
    if isinstance(data, dict):
        # chosen model
        for k in ["model", "selection", "chosen", "name", "id", "value"]:
            if k in data and isinstance(data[k], str):
                chosen = data[k].strip()
                break
        # restart approval
        if "restart" in data:
            rv = data["restart"]
            if isinstance(rv, bool):
                restart_confirm = rv
            elif isinstance(rv, str):
                restart_confirm = rv.strip().lower() in ["yes", "y", "true", "1"]
    return chosen, restart_confirm

def resolve_model_id(chosen, models):
    # Exact match by id or alias
    if not chosen:
        return None
    chosen_s = str(chosen).strip()
    # First, check id match
    for m in models:
        if m["id"] == chosen_s:
            return m["id"]
    # Then alias match
    for m in models:
        if m["alias"] and m["alias"] == chosen_s:
            return m["id"]
    return None

def parse_verification_lines(text):
    lines = text.splitlines()
    kv = {}
    for line in lines:
        if not isinstance(line, str):
            continue
        l = line.strip()
        # Match exact prefixes
        for key in ["Current default:", "Chosen model:", "Session test:", "Config update:", "Gateway restart:"]:
            if l.startswith(key):
                kv[key] = l[len(key):].strip()
    return kv

def find_best_practice_entry(text):
    # Return the first match region content after heading
    pattern = re.compile(r"^## \[LRN-(\d{8})-([A-Za-z0-9]{3})\] best_practice\s*$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    # Find next heading or EOF
    next_m = pattern.search(text, pos=start)
    end = next_m.start() if next_m else len(text)
    return text[m.start():end]

def models_to_set(models):
    # For comparison: set of tuples (id, alias)
    return set((m["id"], m.get("alias", "") or "") for m in models)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks; all False by default
    checks = {
        "execution_exists": False,
        "execution_json_valid": False,
        "presented_models_mirror_input": False,
        "presented_current_default_matches_input": False,
        "selection_input_matches": False,
        "selection_resolved_id_correct": False,
        "session_test_status_matches_matrix": False,
        "session_test_checked_against_literal": False,
        # Plan checks
        "plan_exists": False,
        "plan_lists_models_and_current_default": False,
        "plan_mentions_chosen_and_safety_gate": False,
        # Verification checks
        "verification_exists": False,
        "verification_lines_consistent_with_execution": False,
        # Learnings checks
        "learnings_best_practice_entry_present": False,
    }

    # Paths
    models_path = os.path.join(input_dir, "models.json")
    test_matrix_path = os.path.join(input_dir, "test_matrix.json")
    selection_path = os.path.join(input_dir, "selection.json")

    execution_path = os.path.join(output_dir, "execution.json")
    plan_path = os.path.join(output_dir, "plan.md")
    verification_path = os.path.join(output_dir, "verification.txt")
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")

    # Read inputs
    models_json = safe_read_json(models_path)
    test_matrix = read_test_matrix(test_matrix_path)
    chosen_value, restart_confirm_expected = read_selection(selection_path)
    models_list, current_default_input = extract_models_and_default(models_json or {})

    # Defaults
    resolved_expected = resolve_model_id(chosen_value, models_list) if chosen_value else None

    # Read plan
    plan_text = read_text_file(plan_path)
    if isinstance(plan_text, str):
        checks["plan_exists"] = True

    # Read execution
    execution_json = safe_read_json(execution_path)
    if execution_json is not None:
        checks["execution_exists"] = True
        # Validate JSON structure minimally
        if isinstance(execution_json, dict):
            checks["execution_json_valid"] = True

    # Read verification
    verification_text = read_text_file(verification_path)
    if isinstance(verification_text, str):
        checks["verification_exists"] = True

    # Read learnings
    learnings_text = read_text_file(learnings_path)
    if isinstance(learnings_text, str):
        # Find at least one best_practice entry with required fields
        entry = find_best_practice_entry(learnings_text)
        if entry:
            # Check required lines/sections within the entry
            required_fragments = [
                "**Logged**:",
                "**Priority**:",
                "**Status**:",
                "**Area**:",
                "### Summary",
                "### Details",
                "### Suggested Action",
            ]
            if all(fragment in entry for fragment in required_fragments):
                checks["learnings_best_practice_entry_present"] = True

    # Validate plan contents
    if checks["plan_exists"]:
        pt = plan_text
        # Must list all models (id or alias) and include a line beginning with "Current default:"
        has_current_line = False
        listed_all_models = True
        for line in pt.splitlines():
            if line.strip().startswith("Current default:"):
                val = line.strip()[len("Current default:"):].strip()
                if current_default_input is not None and val == str(current_default_input):
                    has_current_line = True
        # For each model, check if its id or alias appears anywhere in the plan text
        lower_pt = pt.lower()
        for m in models_list:
            mid = m["id"]
            alias = m.get("alias", "")
            # Consider listed if id OR non-empty alias appears
            listed = False
            if mid and mid.lower() in lower_pt:
                listed = True
            elif alias and alias.lower() in lower_pt:
                listed = True
            if not listed:
                listed_all_models = False
                break
        # Mentions chosen model and states a session-only test before config write
        mentions_chosen = False
        if chosen_value:
            mentions_chosen = str(chosen_value).lower() in lower_pt or (resolved_expected and resolved_expected.lower() in lower_pt)
        safety_gate = False
        # Look for "session-only" or mention "session" and "test" and "before"
        if "session-only" in lower_pt:
            safety_gate = True
        elif ("session" in lower_pt and "test" in lower_pt and ("before" in lower_pt or "prior" in lower_pt)):
            safety_gate = True

        if has_current_line:
            checks["plan_lists_models_and_current_default"] = listed_all_models and has_current_line
        else:
            checks["plan_lists_models_and_current_default"] = False
        checks["plan_mentions_chosen_and_safety_gate"] = mentions_chosen and safety_gate

    # Validate execution.json
    branch_checks = {}
    session_status = None
    restart_confirm_in_exec = None

    if checks["execution_json_valid"]:
        ex = execution_json

        # presented.models equals input models set (order-agnostic) and current_default matches
        presented = ex.get("presented", {})
        p_models = normalize_models(presented.get("models") if isinstance(presented, dict) else None)
        input_models_set = models_to_set(models_list)
        presented_models_set = models_to_set(p_models)
        if input_models_set and input_models_set == presented_models_set:
            checks["presented_models_mirror_input"] = True

        p_current_default = (presented.get("current_default") if isinstance(presented, dict) else None)
        if current_default_input is not None and p_current_default == current_default_input:
            checks["presented_current_default_matches_input"] = True

        # selection input and resolved id
        sel = ex.get("selection", {})
        sel_input = sel.get("input") if isinstance(sel, dict) else None
        if chosen_value is not None and sel_input == chosen_value:
            checks["selection_input_matches"] = True

        resolved_in_exec = sel.get("resolved_model_id") if isinstance(sel, dict) else None
        if resolved_expected is not None and resolved_in_exec == resolved_expected:
            checks["selection_resolved_id_correct"] = True

        # session test
        st = ex.get("session_test", {})
        st_status = st.get("status") if isinstance(st, dict) else None
        if isinstance(st_status, str):
            session_status = st_status.strip().lower()
        checked_against = st.get("checked_against") if isinstance(st, dict) else None
        if checked_against == "input/test_matrix.json":
            checks["session_test_checked_against_literal"] = True

        if resolved_expected is not None and session_status in ["pass", "fail"]:
            expected_status = test_matrix.get(resolved_expected, None)
            if expected_status is not None and expected_status == session_status:
                checks["session_test_status_matches_matrix"] = True

        # config update and restart branch checks
        cu = ex.get("config_update", {}) if isinstance(ex, dict) else {}
        rs = ex.get("restart", {}) if isinstance(ex, dict) else {}

        # Determine restart confirmed from execution.json
        restart_confirm_in_exec = rs.get("confirmed") if isinstance(rs, dict) else None

        if session_status == "pass":
            # Config update must be attempted and verified with new_default == resolved id
            cu_attempted = bool(cu.get("attempted") is True)
            cu_verified = bool(cu.get("verified") is True)
            cu_new_default = cu.get("new_default")
            config_ok = cu_attempted and cu_verified and (cu_new_default == resolved_expected)
            branch_checks["config_update_on_pass_correct"] = config_ok

            # Restart confirmation must reflect input selection
            if restart_confirm_expected is not None and isinstance(restart_confirm_in_exec, bool):
                restart_confirm_match = (restart_confirm_in_exec == restart_confirm_expected)
            else:
                restart_confirm_match = False
            branch_checks["restart_on_pass_confirmed_matches_selection"] = restart_confirm_match

            # Restart behavior branch
            if restart_confirm_in_exec is True and config_ok:
                # Must be attempted and success
                r_attempted = bool(rs.get("attempted") is True)
                r_status = rs.get("status")
                branch_checks["restart_on_pass_confirmed_branch_correct"] = r_attempted and (r_status == "success")
            elif restart_confirm_in_exec is False and config_ok:
                # Must be skipped
                r_attempted = bool(rs.get("attempted") is True)
                r_status = rs.get("status")
                branch_checks["restart_on_pass_denied_branch_correct"] = (r_attempted is False) and (r_status == "skipped")
            # If config_ok is False, leave both False (do not award)
        elif session_status == "fail":
            # Config update must not be attempted/verified; restart skipped
            cu_attempted = bool(cu.get("attempted") is True)
            cu_verified = bool(cu.get("verified") is True)
            rs_attempted = bool(rs.get("attempted") is True)
            rs_status = rs.get("status")
            branch_checks["config_and_restart_on_fail_correct"] = (cu_attempted is False) and (cu_verified is False) and (rs_attempted is False) and (rs_status == "skipped")

        # Merge branch checks
        for k, v in branch_checks.items():
            checks[k] = bool(v)

    # Validate verification.txt consistency with execution.json
    if checks["verification_exists"] and checks["execution_json_valid"]:
        kv = parse_verification_lines(verification_text)
        valid_lines = True

        # Current default
        presented = execution_json.get("presented", {}) if isinstance(execution_json, dict) else {}
        ex_current_default = presented.get("current_default") if isinstance(presented, dict) else None
        if kv.get("Current default:") != (ex_current_default if ex_current_default is not None else ""):
            valid_lines = False

        # Chosen model equals selection.resolved_model_id
        sel = execution_json.get("selection", {}) if isinstance(execution_json, dict) else {}
        ex_resolved = sel.get("resolved_model_id") if isinstance(sel, dict) else None
        if kv.get("Chosen model:") != (ex_resolved if ex_resolved is not None else ""):
            valid_lines = False

        # Session test equals session_test.status
        st = execution_json.get("session_test", {}) if isinstance(execution_json, dict) else {}
        ex_st = st.get("status") if isinstance(st, dict) else None
        if (kv.get("Session test:") or "").strip().lower() != (str(ex_st).strip().lower() if isinstance(ex_st, str) else ""):
            valid_lines = False

        # Config update: applied if verified true else skipped
        cu = execution_json.get("config_update", {}) if isinstance(execution_json, dict) else {}
        verified = bool(cu.get("verified") is True)
        expected_cu_line = "applied" if verified else "skipped"
        if (kv.get("Config update:") or "").strip().lower() != expected_cu_line:
            valid_lines = False

        # Gateway restart: equals restart.status
        rs = execution_json.get("restart", {}) if isinstance(execution_json, dict) else {}
        rs_status = rs.get("status") if isinstance(rs, dict) else None
        if (kv.get("Gateway restart:") or "").strip().lower() != (str(rs_status).strip().lower() if isinstance(rs_status, str) else ""):
            valid_lines = False

        if valid_lines:
            checks["verification_lines_consistent_with_execution"] = True

    # Compute reward as average of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Enforce no-op baseline: if output/ missing or no required artifacts, reward must be 0.0
    # Required artifacts minimal: execution.json must exist and be valid
    if not checks["execution_exists"] or not checks["execution_json_valid"]:
        reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()