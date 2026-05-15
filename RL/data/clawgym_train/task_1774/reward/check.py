import json
import os
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def has_line_equal(text, target):
    for line in text.splitlines():
        if line.strip() == target:
            return True
    return False

def has_line_starting_with(text, prefix):
    for line in text.splitlines():
        if line.strip().lower().startswith(prefix.lower()):
            return True
    return False

def find_done_when_bullets(text):
    lines = text.splitlines()
    count = 0
    in_done = False
    for line in lines:
        s = line.strip()
        if not in_done:
            if s.lower() == "done_when:":
                in_done = True
        else:
            if s.startswith("- "):
                count += 1
            elif s == "" or not s.startswith("- "):
                # Stop counting when a blank line or a non-bullet line appears after bullets
                # However, if there are interspersed blank lines, we break at first non-bullet or blank line after bullets start.
                if count > 0:
                    break
                # If no bullets counted yet and line is blank, continue
    return count

def contains_case_insensitive(text, substr):
    return substr.lower() in text.lower()

def check_schedule_days(days_list, expected_days):
    if not isinstance(days_list, list):
        return False
    norm = [str(d).strip().lower() for d in days_list]
    return set(norm) == set(expected_days) and len(norm) == len(expected_days)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    plan_path = os.path.join(output_dir, "plan.md")
    build_path = os.path.join(output_dir, "handoffs", "BUILD-LP-001.txt")
    intel_path = os.path.join(output_dir, "handoffs", "INTEL-CONTENT-001.txt")
    ops_path = os.path.join(output_dir, "handoffs", "OPS-QA-001.txt")
    router_config_path = os.path.join(output_dir, "router.config.json")
    router_schedule_path = os.path.join(output_dir, "router.schedule.json")

    # Plan checks
    plan_text = read_text(plan_path)
    checks["plan_exists"] = plan_text is not None
    checks["plan_has_revenue_string"] = False
    checks["plan_has_delegate_rule"] = False
    checks["plan_mentions_task_ids"] = False
    checks["plan_mentions_approval_or_budget_gate"] = False
    if plan_text is not None:
        checks["plan_has_revenue_string"] = "$1M/yr" in plan_text
        checks["plan_has_delegate_rule"] = ("delegate" in plan_text.lower()) and ("10 seconds" in plan_text.lower())
        ids_ok = ("BUILD-LP-001" in plan_text) and ("INTEL-CONTENT-001" in plan_text) and ("OPS-QA-001" in plan_text)
        checks["plan_mentions_task_ids"] = ids_ok
        checks["plan_mentions_approval_or_budget_gate"] = ("no spend" in plan_text.lower()) or ("approval" in plan_text.lower())

    # BUILD handoff checks
    build_text = read_text(build_path)
    checks["build_exists"] = build_text is not None
    checks["build_has_handoff_line"] = False
    checks["build_from_pixel"] = False
    checks["build_to_forge"] = False
    checks["build_task_id_ok"] = False
    checks["build_priority_high"] = False
    checks["build_summary_mentions_snippetscribe"] = False
    checks["build_context_timezone"] = False
    checks["build_deliver_to_build"] = False
    checks["build_deadline_exact"] = False
    checks["build_done_when_section_has_3_bullets"] = False
    checks["build_done_when_includes_join_waitlist"] = False
    checks["build_done_when_includes_features"] = False
    checks["build_done_when_includes_mobile_first"] = False
    if build_text is not None:
        checks["build_has_handoff_line"] = has_line_equal(build_text, "HANDOFF")
        checks["build_from_pixel"] = "from: pixel" in build_text
        checks["build_to_forge"] = "to: forge" in build_text
        checks["build_task_id_ok"] = "task_id: BUILD-LP-001" in build_text
        checks["build_priority_high"] = "priority: high" in build_text
        # summary mentions SnippetScribe in the summary line
        summary_lines = [ln for ln in build_text.splitlines() if ln.strip().lower().startswith("summary:")]
        checks["build_summary_mentions_snippetscribe"] = any("snippetscribe" in ln.lower() for ln in summary_lines)
        checks["build_context_timezone"] = "timezone: Europe/Rome" in build_text
        checks["build_deliver_to_build"] = "deliver_to: Build topic" in build_text
        checks["build_deadline_exact"] = "deadline: 2026-04-19 18:00 Europe/Rome" in build_text
        bullet_count = find_done_when_bullets(build_text)
        checks["build_done_when_section_has_3_bullets"] = bullet_count >= 3
        checks["build_done_when_includes_join_waitlist"] = contains_case_insensitive(build_text, "Join the waitlist")
        checks["build_done_when_includes_features"] = contains_case_insensitive(build_text, "Features")
        checks["build_done_when_includes_mobile_first"] = contains_case_insensitive(build_text, "mobile-first")

    # INTEL handoff checks
    intel_text = read_text(intel_path)
    checks["intel_exists"] = intel_text is not None
    checks["intel_has_handoff_line"] = False
    checks["intel_from_pixel"] = False
    checks["intel_to_scout"] = False
    checks["intel_task_id_ok"] = False
    checks["intel_priority_medium"] = False
    checks["intel_summary_mentions_snippetscribe"] = False
    checks["intel_context_timezone"] = False
    checks["intel_deliver_to_intel"] = False
    checks["intel_deadline_exact"] = False
    checks["intel_done_when_section_has_4_bullets"] = False
    checks["intel_done_when_includes_3_competitor_taglines"] = False
    checks["intel_done_when_includes_source_url"] = False
    checks["intel_done_when_includes_micro_saas_matter"] = False
    checks["intel_done_when_includes_7_sections"] = False
    if intel_text is not None:
        checks["intel_has_handoff_line"] = has_line_equal(intel_text, "HANDOFF")
        checks["intel_from_pixel"] = "from: pixel" in intel_text
        checks["intel_to_scout"] = "to: scout" in intel_text
        checks["intel_task_id_ok"] = "task_id: INTEL-CONTENT-001" in intel_text
        checks["intel_priority_medium"] = "priority: medium" in intel_text
        summary_lines_i = [ln for ln in intel_text.splitlines() if ln.strip().lower().startswith("summary:")]
        checks["intel_summary_mentions_snippetscribe"] = any("snippetscribe" in ln.lower() for ln in summary_lines_i)
        checks["intel_context_timezone"] = "timezone: Europe/Rome" in intel_text
        checks["intel_deliver_to_intel"] = "deliver_to: Intel topic" in intel_text
        checks["intel_deadline_exact"] = "deadline: 2026-04-19 15:00 Europe/Rome" in intel_text
        bullet_count_i = find_done_when_bullets(intel_text)
        checks["intel_done_when_section_has_4_bullets"] = bullet_count_i >= 4
        checks["intel_done_when_includes_3_competitor_taglines"] = contains_case_insensitive(intel_text, "3 competitor taglines")
        checks["intel_done_when_includes_source_url"] = contains_case_insensitive(intel_text, "source URL")
        checks["intel_done_when_includes_micro_saas_matter"] = contains_case_insensitive(intel_text, "Why micro-SaaS landing pages still matter in 2026")
        checks["intel_done_when_includes_7_sections"] = contains_case_insensitive(intel_text, "7 sections")

    # OPS handoff checks
    ops_text = read_text(ops_path)
    checks["ops_exists"] = ops_text is not None
    checks["ops_has_handoff_line"] = False
    checks["ops_from_pixel"] = False
    checks["ops_to_sentinel"] = False
    checks["ops_task_id_ok"] = False
    checks["ops_priority_high"] = False
    checks["ops_summary_mentions_snippetscribe"] = False
    checks["ops_context_timezone"] = False
    checks["ops_deliver_to_ops"] = False
    checks["ops_deadline_exact"] = False
    checks["ops_done_when_section_has_5_bullets"] = False
    checks["ops_done_when_includes_root_responds_200"] = False
    checks["ops_done_when_includes_api_health"] = False
    checks["ops_done_when_includes_status_ok"] = False
    checks["ops_done_when_includes_5_minute_check"] = False
    checks["ops_done_when_includes_echo_alert"] = False
    if ops_text is not None:
        checks["ops_has_handoff_line"] = has_line_equal(ops_text, "HANDOFF")
        checks["ops_from_pixel"] = "from: pixel" in ops_text
        checks["ops_to_sentinel"] = "to: sentinel" in ops_text
        checks["ops_task_id_ok"] = "task_id: OPS-QA-001" in ops_text
        checks["ops_priority_high"] = "priority: high" in ops_text
        summary_lines_o = [ln for ln in ops_text.splitlines() if ln.strip().lower().startswith("summary:")]
        checks["ops_summary_mentions_snippetscribe"] = any("snippetscribe" in ln.lower() for ln in summary_lines_o)
        checks["ops_context_timezone"] = "timezone: Europe/Rome" in ops_text
        checks["ops_deliver_to_ops"] = "deliver_to: Ops topic" in ops_text
        checks["ops_deadline_exact"] = "deadline: 2026-04-18 12:00 Europe/Rome" in ops_text
        bullet_count_o = find_done_when_bullets(ops_text)
        checks["ops_done_when_section_has_5_bullets"] = bullet_count_o >= 5
        checks["ops_done_when_includes_root_responds_200"] = contains_case_insensitive(ops_text, "/ responds 200")
        checks["ops_done_when_includes_api_health"] = contains_case_insensitive(ops_text, "/api/health")
        checks["ops_done_when_includes_status_ok"] = contains_case_insensitive(ops_text, "status: ok")
        checks["ops_done_when_includes_5_minute_check"] = contains_case_insensitive(ops_text, "5-minute check")
        checks["ops_done_when_includes_echo_alert"] = contains_case_insensitive(ops_text, "echo ALERT")

    # Router config JSON checks
    config_text = read_text(router_config_path)
    config_json = load_json(router_config_path) if config_text is not None else None
    checks["router_config_exists"] = config_text is not None
    checks["router_config_json_valid"] = config_json is not None
    # Initialize JSON checks to False
    checks["config_prefix_mini_model_ok"] = False
    checks["config_prefix_mini_fallback_ok"] = False
    checks["config_prefix_codex_model_ok"] = False
    checks["config_prefix_codex_fallback_ok"] = False
    checks["config_alias_m_ok"] = False
    checks["config_alias_c_ok"] = False
    checks["config_default_model_ok"] = False
    checks["config_safety_lockpath_ok"] = False
    checks["config_logging_path_ok"] = False

    if config_json is not None and isinstance(config_json, dict):
        prefix_map = config_json.get("prefixMap", {})
        alias_map = config_json.get("aliasMap", {})
        safety = config_json.get("safety", {})
        logging_cfg = config_json.get("logging", {})
        # prefix @mini
        if isinstance(prefix_map, dict) and "@mini" in prefix_map:
            m = prefix_map.get("@mini", {})
            if isinstance(m, dict):
                checks["config_prefix_mini_model_ok"] = m.get("model") == "minimax/MiniMax-M2.5"
                checks["config_prefix_mini_fallback_ok"] = m.get("fallbackModel") == "openai-codex/gpt-5.3-codex"
        # prefix @codex
        if isinstance(prefix_map, dict) and "@codex" in prefix_map:
            m = prefix_map.get("@codex", {})
            if isinstance(m, dict):
                checks["config_prefix_codex_model_ok"] = m.get("model") == "openai-codex/gpt-5.3-codex"
                checks["config_prefix_codex_fallback_ok"] = m.get("fallbackModel") == "minimax/MiniMax-M2.5"
        # aliases
        if isinstance(alias_map, dict):
            checks["config_alias_m_ok"] = alias_map.get("@m") == "@mini"
            checks["config_alias_c_ok"] = alias_map.get("@c") == "@codex"
        # defaultModel
        checks["config_default_model_ok"] = config_json.get("defaultModel") == "openai-codex/gpt-5.3-codex"
        # safety.lockPath
        if isinstance(safety, dict):
            checks["config_safety_lockpath_ok"] = safety.get("lockPath") == "./.router-switch.lock"
        # logging.path
        if isinstance(logging_cfg, dict):
            checks["config_logging_path_ok"] = logging_cfg.get("path") == "./router.log.jsonl"

    # Router schedule JSON checks
    schedule_text = read_text(router_schedule_path)
    schedule_json = load_json(router_schedule_path) if schedule_text is not None else None
    checks["router_schedule_exists"] = schedule_text is not None
    checks["router_schedule_json_valid"] = schedule_json is not None
    checks["schedule_timezone_ok"] = False
    checks["schedule_rules_len_two"] = False
    checks["schedule_has_workday_rule"] = False
    checks["schedule_workday_days_ok"] = False
    checks["schedule_workday_start_ok"] = False
    checks["schedule_workday_end_ok"] = False
    checks["schedule_workday_model_ok"] = False
    checks["schedule_workday_priority_ok"] = False
    checks["schedule_workday_enabled_ok"] = False
    checks["schedule_has_night_rule"] = False
    checks["schedule_night_days_ok"] = False
    checks["schedule_night_start_ok"] = False
    checks["schedule_night_end_ok"] = False
    checks["schedule_night_model_ok"] = False
    checks["schedule_night_priority_ok"] = False
    checks["schedule_night_enabled_ok"] = False

    if schedule_json is not None and isinstance(schedule_json, dict):
        checks["schedule_timezone_ok"] = schedule_json.get("timezone") == "Europe/Rome"
        rules = schedule_json.get("rules", [])
        if isinstance(rules, list):
            checks["schedule_rules_len_two"] = len(rules) == 2
            # Map by id
            rules_by_id = {}
            for r in rules:
                if isinstance(r, dict) and "id" in r:
                    rules_by_id[r["id"]] = r
            work = rules_by_id.get("workday_codex")
            night = rules_by_id.get("night_mini")
            checks["schedule_has_workday_rule"] = work is not None
            checks["schedule_has_night_rule"] = night is not None
            # Workday checks
            if work is not None:
                checks["schedule_workday_days_ok"] = check_schedule_days(work.get("days"), ["mon", "tue", "wed", "thu", "fri"])
                checks["schedule_workday_start_ok"] = work.get("start") == "09:00"
                checks["schedule_workday_end_ok"] = work.get("end") == "18:00"
                checks["schedule_workday_model_ok"] = work.get("model") == "openai-codex/gpt-5.3-codex"
                checks["schedule_workday_priority_ok"] = work.get("priority") == 10
                checks["schedule_workday_enabled_ok"] = bool(work.get("enabled") is True)
            # Night checks
            if night is not None:
                checks["schedule_night_days_ok"] = check_schedule_days(night.get("days"), ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
                checks["schedule_night_start_ok"] = night.get("start") == "18:00"
                checks["schedule_night_end_ok"] = night.get("end") == "09:00"
                checks["schedule_night_model_ok"] = night.get("model") == "minimax/MiniMax-M2.5"
                checks["schedule_night_priority_ok"] = night.get("priority") == 1
                checks["schedule_night_enabled_ok"] = bool(night.get("enabled") is True)

    # Compute reward with category weights
    # Plan category (0.2)
    plan_checks = [
        "plan_exists",
        "plan_has_revenue_string",
        "plan_has_delegate_rule",
        "plan_mentions_task_ids",
        "plan_mentions_approval_or_budget_gate",
    ]
    plan_score = sum(1 for k in plan_checks if checks.get(k)) / len(plan_checks) if len(plan_checks) > 0 else 0.0
    # Build category (0.2)
    build_checks = [
        "build_exists",
        "build_has_handoff_line",
        "build_from_pixel",
        "build_to_forge",
        "build_task_id_ok",
        "build_priority_high",
        "build_summary_mentions_snippetscribe",
        "build_context_timezone",
        "build_deliver_to_build",
        "build_deadline_exact",
        "build_done_when_section_has_3_bullets",
        "build_done_when_includes_join_waitlist",
        "build_done_when_includes_features",
        "build_done_when_includes_mobile_first",
    ]
    build_score = sum(1 for k in build_checks if checks.get(k)) / len(build_checks) if len(build_checks) > 0 else 0.0
    # Intel category (0.2)
    intel_checks = [
        "intel_exists",
        "intel_has_handoff_line",
        "intel_from_pixel",
        "intel_to_scout",
        "intel_task_id_ok",
        "intel_priority_medium",
        "intel_summary_mentions_snippetscribe",
        "intel_context_timezone",
        "intel_deliver_to_intel",
        "intel_deadline_exact",
        "intel_done_when_section_has_4_bullets",
        "intel_done_when_includes_3_competitor_taglines",
        "intel_done_when_includes_source_url",
        "intel_done_when_includes_micro_saas_matter",
        "intel_done_when_includes_7_sections",
    ]
    intel_score = sum(1 for k in intel_checks if checks.get(k)) / len(intel_checks) if len(intel_checks) > 0 else 0.0
    # Ops category (0.2)
    ops_checks = [
        "ops_exists",
        "ops_has_handoff_line",
        "ops_from_pixel",
        "ops_to_sentinel",
        "ops_task_id_ok",
        "ops_priority_high",
        "ops_summary_mentions_snippetscribe",
        "ops_context_timezone",
        "ops_deliver_to_ops",
        "ops_deadline_exact",
        "ops_done_when_section_has_5_bullets",
        "ops_done_when_includes_root_responds_200",
        "ops_done_when_includes_api_health",
        "ops_done_when_includes_status_ok",
        "ops_done_when_includes_5_minute_check",
        "ops_done_when_includes_echo_alert",
    ]
    ops_score = sum(1 for k in ops_checks if checks.get(k)) / len(ops_checks) if len(ops_checks) > 0 else 0.0
    # Router config category (0.1)
    cfg_checks = [
        "router_config_exists",
        "router_config_json_valid",
        "config_prefix_mini_model_ok",
        "config_prefix_mini_fallback_ok",
        "config_prefix_codex_model_ok",
        "config_prefix_codex_fallback_ok",
        "config_alias_m_ok",
        "config_alias_c_ok",
        "config_default_model_ok",
        "config_safety_lockpath_ok",
        "config_logging_path_ok",
    ]
    cfg_score = sum(1 for k in cfg_checks if checks.get(k)) / len(cfg_checks) if len(cfg_checks) > 0 else 0.0
    # Router schedule category (0.1)
    sched_checks = [
        "router_schedule_exists",
        "router_schedule_json_valid",
        "schedule_timezone_ok",
        "schedule_rules_len_two",
        "schedule_has_workday_rule",
        "schedule_workday_days_ok",
        "schedule_workday_start_ok",
        "schedule_workday_end_ok",
        "schedule_workday_model_ok",
        "schedule_workday_priority_ok",
        "schedule_workday_enabled_ok",
        "schedule_has_night_rule",
        "schedule_night_days_ok",
        "schedule_night_start_ok",
        "schedule_night_end_ok",
        "schedule_night_model_ok",
        "schedule_night_priority_ok",
        "schedule_night_enabled_ok",
    ]
    sched_score = sum(1 for k in sched_checks if checks.get(k)) / len(sched_checks) if len(sched_checks) > 0 else 0.0

    reward = (
        0.2 * plan_score +
        0.2 * build_score +
        0.2 * intel_score +
        0.2 * ops_score +
        0.1 * cfg_score +
        0.1 * sched_score
    )

    # No-op baseline guard: if output dir missing or all main artifacts missing, reward must be 0.0
    required_artifacts = [plan_text, build_text, intel_text, ops_text, config_text, schedule_text]
    if not os.path.isdir(output_dir) or all(artifact is None for artifact in required_artifacts):
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    # Merge checks (booleans)
    for k, v in checks.items():
        result[k] = bool(v)

    print(json.dumps(result))

if __name__ == "__main__":
    main()