import json
import os
import sys
from typing import Any, Dict, List

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, e

def read_text(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, e

def mask_api_key(api_key: str) -> str:
    if not isinstance(api_key, str):
        return ""
    n = len(api_key)
    if n <= 6:
        # If too short, mask entire key (still deterministic)
        return "*" * n
    return api_key[:4] + ("*" * (n - 6)) + api_key[-2:]

def contains_ci(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()

def check_block_patterns(patterns: List[Any]) -> Dict[str, bool]:
    # Accept strings or objects that can be stringified; search substrings case-insensitively
    # Required: one pattern for rm -rf, one for curl | sh, one for wget | sh
    have_rm_rf = False
    have_curl_pipe_sh = False
    have_wget_pipe_sh = False
    for p in patterns:
        s = p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)
        s_low = s.lower()
        # rm -rf: accept if contains 'rm' and '-rf' anywhere in the same pattern
        if ("rm" in s_low) and ("-rf" in s_low):
            have_rm_rf = True
        # curl | sh: require 'curl', '|' and 'sh'
        if ("curl" in s_low) and ("|" in s_low) and ("sh" in s_low):
            have_curl_pipe_sh = True
        # wget | sh: require 'wget', '|' and 'sh'
        if ("wget" in s_low) and ("|" in s_low) and ("sh" in s_low):
            have_wget_pipe_sh = True
    return {
        "have_rm_rf": have_rm_rf,
        "have_curl_pipe_sh": have_curl_pipe_sh,
        "have_wget_pipe_sh": have_wget_pipe_sh,
    }

def list_has_all_str(lst: List[str], required: List[str]) -> bool:
    s = set(lst) if isinstance(lst, list) else set()
    return all(item in s for item in required)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    tools_path = os.path.join(input_dir, "tools.json")
    req_path = os.path.join(input_dir, "security_request.json")
    config_path = os.path.join(output_dir, "security", "config.json")
    policies_path = os.path.join(output_dir, "security", "policies.json")
    wrapped_path = os.path.join(output_dir, "security", "wrapped_tools.json")
    readme_path = os.path.join(output_dir, "security", "readme.md")
    risk_path = os.path.join(output_dir, "security", "risk_register.md")

    checks: Dict[str, bool] = {
        # config.json checks
        "config_exists": False,
        "config_json_valid": False,
        "config_security_enabled_true": False,
        "config_tier_matches_input": False,
        "config_limits_match_tier": False,
        "config_api_masked_present": False,
        "config_api_mask_correct": False,
        "config_no_raw_api_key": False,
        # policies.json checks
        "policies_exists": False,
        "policies_json_valid": False,
        "policies_prompt_injection": False,
        "policies_tool_access": False,
        "policies_command_validation": False,
        "policies_rate_limit_match": False,
        # wrapped_tools.json checks
        "wrapped_exists": False,
        "wrapped_json_valid": False,
        "wrapped_length_match": False,
        "wrapped_all_wrapped_true": False,
        "wrapped_checks_present": False,
        # readme.md checks
        "readme_exists": False,
        "readme_sections_present": False,
        # risk_register.md checks
        "risk_exists": False,
        "risk_min_5_with_mitigation": False,
    }

    # Load inputs (do not score on this alone)
    tools, tools_err = load_json(tools_path)
    req, req_err = load_json(req_path)
    requested_tier = None
    requested_rate = None
    requested_api_key = None
    if isinstance(req, dict):
        requested_tier = req.get("tier")
        requested_rate = req.get("rateLimit")
        requested_api_key = req.get("apiKey")

    # Defaults
    default_rate = {"maxRequests": 50, "windowMs": 60000}

    # Check config.json
    if os.path.isfile(config_path):
        checks["config_exists"] = True
        config_text, _ = read_text(config_path)
        config, config_err = load_json(config_path)
        if isinstance(config, dict):
            checks["config_json_valid"] = True
            # securityEnabled true
            if config.get("securityEnabled") is True:
                checks["config_security_enabled_true"] = True
            # tier matches input (expected "pro" per task input)
            if requested_tier is not None and config.get("tier") == requested_tier:
                checks["config_tier_matches_input"] = True
            # limits object appropriate to tier
            limits_ok = False
            limits = config.get("limits")
            tier = requested_tier
            if isinstance(limits, dict) and isinstance(tier, str):
                tier_low = tier.lower()
                if tier_low == "free":
                    # free: { maxTools: 10, maxDailyRequests: 1000 }
                    limits_ok = (limits.get("maxTools") == 10 and limits.get("maxDailyRequests") == 1000)
                elif tier_low == "pro":
                    # pro: { maxTools: 100, customPolicies: true }
                    limits_ok = (limits.get("maxTools") == 100 and limits.get("customPolicies") is True)
                elif tier_low == "enterprise":
                    # enterprise: { unlimited: true, sla: "99.99%" }
                    limits_ok = (limits.get("unlimited") is True and limits.get("sla") == "99.99%")
            if limits_ok:
                checks["config_limits_match_tier"] = True
            # apiKeyMasked present and correct; also ensure raw key not present
            api_masked = config.get("apiKeyMasked")
            if isinstance(api_masked, str) and len(api_masked) > 0:
                checks["config_api_masked_present"] = True
                if isinstance(requested_api_key, str):
                    expected_mask = mask_api_key(requested_api_key)
                    if api_masked == expected_mask:
                        checks["config_api_mask_correct"] = True
                # ensure raw key not present anywhere in config file text
                if config_text is not None and isinstance(requested_api_key, str):
                    if requested_api_key not in config_text:
                        checks["config_no_raw_api_key"] = True
        else:
            # Invalid JSON: cannot pass JSON-dependent checks
            pass

    # Check policies.json
    if os.path.isfile(policies_path):
        checks["policies_exists"] = True
        policies, pol_err = load_json(policies_path)
        if isinstance(policies, dict):
            checks["policies_json_valid"] = True
            pol = policies.get("policies")
            if isinstance(pol, dict):
                # Prompt injection
                pi = pol.get("promptInjection")
                if isinstance(pi, dict):
                    if pi.get("enabled") is True and pi.get("action") == "block" and pi.get("sensitivity") == "high":
                        checks["policies_prompt_injection"] = True
                # Tool access
                ta = pol.get("toolAccess")
                if isinstance(ta, dict):
                    dangerous = ta.get("dangerous")
                    require_approval = ta.get("requireApproval")
                    if isinstance(dangerous, list) and require_approval is True:
                        if list_has_all_str(dangerous, ["exec", "write", "delete", "sudo"]):
                            checks["policies_tool_access"] = True
                # Command validation
                cv = pol.get("commandValidation")
                if isinstance(cv, dict):
                    cv_enabled = cv.get("enabled") is True
                    block_patterns = cv.get("blockPatterns")
                    have_patterns = False
                    if isinstance(block_patterns, list):
                        bp = check_block_patterns(block_patterns)
                        have_patterns = (bp["have_rm_rf"] and bp["have_curl_pipe_sh"] and bp["have_wget_pipe_sh"])
                    if cv_enabled and have_patterns:
                        checks["policies_command_validation"] = True
                # Rate limit
                rl = pol.get("rateLimit")
                expected_rate = requested_rate if isinstance(requested_rate, dict) else default_rate
                if isinstance(rl, dict):
                    if rl.get("maxRequests") == expected_rate.get("maxRequests") and rl.get("windowMs") == expected_rate.get("windowMs"):
                        checks["policies_rate_limit_match"] = True

    # Check wrapped_tools.json
    if os.path.isfile(wrapped_path):
        checks["wrapped_exists"] = True
        wrapped, w_err = load_json(wrapped_path)
        if isinstance(wrapped, list):
            checks["wrapped_json_valid"] = True
            # Compare length with tools input
            tools_list = tools if isinstance(tools, list) else []
            if len(wrapped) == len(tools_list) and len(wrapped) > 0:
                checks["wrapped_length_match"] = True
            # Verify each entry has name in input tools, wrapped true, and checks present
            names_in_input = set()
            if isinstance(tools_list, list):
                for t in tools_list:
                    if isinstance(t, dict) and isinstance(t.get("name"), str):
                        names_in_input.add(t["name"])
            all_wrapped_true = True
            checks_present = True
            for entry in wrapped:
                if not isinstance(entry, dict):
                    all_wrapped_true = False
                    checks_present = False
                    break
                name = entry.get("name")
                wrapped_flag = entry.get("wrapped")
                pre_checks = entry.get("preExecutionChecks")
                if name not in names_in_input:
                    all_wrapped_true = False
                if wrapped_flag is not True:
                    all_wrapped_true = False
                if not (isinstance(pre_checks, list) and list_has_all_str(pre_checks, ["prompt_injection_scan", "command_pattern_validation", "rate_limit"])):
                    checks_present = False
            if all_wrapped_true:
                checks["wrapped_all_wrapped_true"] = True
            if checks_present:
                checks["wrapped_checks_present"] = True

    # Check readme.md
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme_text, _ = read_text(readme_path)
        if isinstance(readme_text, str):
            lt = readme_text.lower()
            if ("activation plan" in lt) and ("change management" in lt) and ("rollback" in lt):
                checks["readme_sections_present"] = True

    # Check risk_register.md
    if os.path.isfile(risk_path):
        checks["risk_exists"] = True
        risk_text, _ = read_text(risk_path)
        if isinstance(risk_text, str):
            # Count "Risk:" occurrences that have mitigation text on same or subsequent line
            lines = risk_text.splitlines()
            count_with_mitigation = 0
            for idx, line in enumerate(lines):
                if "Risk:" in line:
                    # Look for mitigation on same or next 2 lines
                    mitigation_found = False
                    window = [line]
                    if idx + 1 < len(lines):
                        window.append(lines[idx + 1])
                    if idx + 2 < len(lines):
                        window.append(lines[idx + 2])
                    for wline in window:
                        if "Mitigation" in wline or "mitigation" in wline:
                            # also require some non-empty text after the word
                            mitigation_found = True
                            break
                    if mitigation_found:
                        count_with_mitigation += 1
            if count_with_mitigation >= 5:
                checks["risk_min_5_with_mitigation"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if output dir missing or none of the required artifacts exist, reward must be 0.0
    required_any_exist = any([
        checks["config_exists"],
        checks["policies_exists"],
        checks["wrapped_exists"],
        checks["readme_exists"],
        checks["risk_exists"],
    ])
    reward = (passed / total_checks) if required_any_exist and total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()