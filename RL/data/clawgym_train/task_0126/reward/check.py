import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def lines(text):
    return text.splitlines() if text is not None else []

def find_first_line_starting(text_lines, prefix):
    for ln in text_lines:
        if ln.strip().startswith(prefix):
            return ln.strip()
    return None

def extract_after_colon(line):
    if not line:
        return ""
    idx = line.find(":")
    if idx == -1:
        return ""
    return line[idx+1:].strip()

def parse_issue_blocks(report_text):
    # Split by issue markers "─── ISSUE"
    # Keep blocks as text including lines until next marker or end
    if not report_text:
        return []
    lns = report_text.splitlines()
    blocks = []
    current = []
    inside = False
    for ln in lns:
        if "─── ISSUE" in ln:
            if inside and current:
                blocks.append("\n".join(current))
                current = []
            inside = True
            current = [ln]
        elif inside:
            current.append(ln)
    if inside and current:
        blocks.append("\n".join(current))
    return blocks

def extract_component_from_block(block_text):
    for ln in block_text.splitlines():
        if ln.strip().lower().startswith("component:"):
            return extract_after_colon(ln).strip()
    return ""

def contains_case_insensitive(text, substr):
    return substr.lower() in (text or "").lower()

def parse_env_paths(env_text):
    state_dir = None
    config_path = None

    if not env_text:
        return (None, None)

    # Try explicit STATE_DIR, CONFIG formats first
    patterns_state = [
        r'(?i)\bSTATE_DIR\b[^\S\r\n]*[:=][^\S\r\n]*(.+)$',
        r'(?i)\bState dir[^\S\r\n]*\([^)]+\)[^\S\r\n]*:[^\S\r\n]*(.+)$',
        r'(?i)\bState dir[^\S\r\n]*:[^\S\r\n]*(.+)$',
    ]
    patterns_config = [
        r'(?i)\bCONFIG(?:_PATH)?\b[^\S\r\n]*[:=][^\S\r\n]*(.+)$',
        r'(?i)\bConfig[^\S\r\n]*\([^)]+\)[^\S\r\n]*:[^\S\r\n]*(.+)$',
        r'(?i)\bConfig[^\S\r\n]*:[^\S\r\n]*(.+)$',
    ]

    for pat in patterns_state:
        m = re.search(pat, env_text, flags=re.MULTILINE)
        if m and m.group(1):
            cand = m.group(1).strip()
            # Remove wrapping quotes if any
            if (cand.startswith('"') and cand.endswith('"')) or (cand.startswith("'") and cand.endswith("'")):
                cand = cand[1:-1]
            state_dir = cand
            break

    for pat in patterns_config:
        m = re.search(pat, env_text, flags=re.MULTILINE)
        if m and m.group(1):
            cand = m.group(1).strip()
            if (cand.startswith('"') and cand.endswith('"')) or (cand.startswith("'") and cand.endswith("'")):
                cand = cand[1:-1]
            config_path = cand
            break

    return (state_dir, config_path)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    report_path = os.path.join(output_dir, "recovery_report.txt")
    issues_json_path = os.path.join(output_dir, "issues.json")
    env_path = os.path.join(input_dir, "env.txt")

    checks = {
        "has_recovery_report_file": False,
        "has_issues_json_file": False,
        "header_present": False,
        "footer_present": False,
        "has_status_line": False,
        "status_value_valid": False,
        "os_mentions_windows": False,
        "has_state_dir_line": False,
        "state_dir_matches_env": False,
        "has_config_line": False,
        "config_matches_env": False,
        "has_gateway_line": False,
        "gateway_unreachable_and_port_18789": False,
        "has_channels_line": False,
        "channels_mentions_telegram_and_discord": False,
        "has_agents_line": False,
        "has_security_line": False,
        "security_count_two": False,
        "has_at_least_five_issue_blocks": False,
        "components_cover_required": False,
        "config_issue_has_node_bom_with_path": False,
        "gateway_issue_has_schtasks_action": False,
        "channel_issue_has_deep_probe": False,
        "security_issue_has_icacls_action": False,
        "memory_issue_references_fts": False,
        "evidence_contains_econnrefused": False,
        "evidence_contains_fts": False,
        "issues_json_valid_array": False,
        "issues_json_len_at_least_5": False,
        "issues_json_fields_present": False,
        "issues_json_components_cover_required": False,
    }

    report_text = read_text(report_path)
    issues_json_text = read_text(issues_json_path)
    env_text = read_text(env_path)

    # Required file presence
    if report_text is not None:
        checks["has_recovery_report_file"] = True
    if issues_json_text is not None:
        checks["has_issues_json_file"] = True

    # Early no-op baseline: if either required output is missing, reward must be 0.0
    # We'll still compute other checks for transparency, but final reward will be forced to 0.0.
    # Continue computing when present.
    report_lines = lines(report_text)

    # Header/footer
    if report_text:
        if "═══ OPENCLAW RECOVERY REPORT ═══" in report_text:
            checks["header_present"] = True
        if "═══ END REPORT ═══" in report_text:
            checks["footer_present"] = True

    # STATUS line and value
    status_line = find_first_line_starting(report_lines, "STATUS:")
    if status_line:
        checks["has_status_line"] = True
        status_val = extract_after_colon(status_line).upper()
        if "FAIL" in status_val or "DEGRADED" in status_val:
            checks["status_value_valid"] = True

    # OS line mentions Windows
    os_line = find_first_line_starting(report_lines, "OS:")
    if os_line and contains_case_insensitive(os_line, "windows"):
        checks["os_mentions_windows"] = True

    # STATE_DIR
    state_dir_line = find_first_line_starting(report_lines, "STATE_DIR:")
    if state_dir_line:
        checks["has_state_dir_line"] = True

    # CONFIG
    config_line = find_first_line_starting(report_lines, "CONFIG:")
    if config_line:
        checks["has_config_line"] = True

    # From env, obtain expected paths for matching
    env_state_dir, env_config_path = parse_env_paths(env_text or "")

    if state_dir_line and env_state_dir:
        if env_state_dir in state_dir_line:
            checks["state_dir_matches_env"] = True

    if config_line and env_config_path:
        if env_config_path in config_line:
            checks["config_matches_env"] = True

    # GATEWAY line
    gateway_line = find_first_line_starting(report_lines, "GATEWAY:")
    if gateway_line:
        checks["has_gateway_line"] = True
        if contains_case_insensitive(gateway_line, "unreachable") and "port 18789" in gateway_line:
            checks["gateway_unreachable_and_port_18789"] = True

    # CHANNELS
    channels_line = find_first_line_starting(report_lines, "CHANNELS:")
    if channels_line:
        checks["has_channels_line"] = True
        if contains_case_insensitive(channels_line, "telegram") and contains_case_insensitive(channels_line, "discord"):
            checks["channels_mentions_telegram_and_discord"] = True

    # AGENTS line
    agents_line = find_first_line_starting(report_lines, "AGENTS:")
    if agents_line:
        checks["has_agents_line"] = True

    # SECURITY line with count 2
    security_line = find_first_line_starting(report_lines, "SECURITY:")
    if security_line:
        checks["has_security_line"] = True
        if "2" in security_line:
            checks["security_count_two"] = True

    # Issue blocks
    blocks = parse_issue_blocks(report_text or "")
    if len(blocks) >= 5:
        checks["has_at_least_five_issue_blocks"] = True

    # Components coverage in report
    required_components = {"gateway", "channel", "config", "memory", "security"}
    present_components = set()
    for b in blocks:
        comp = extract_component_from_block(b).strip().lower()
        if comp:
            present_components.add(comp)
    if required_components.issubset(present_components):
        checks["components_cover_required"] = True

    # Specific checks within blocks:

    # Config issue node -e with config path
    config_block_ok = False
    if env_config_path:
        for b in blocks:
            comp = extract_component_from_block(b).strip().lower()
            if comp == "config":
                if "node -e" in b and env_config_path in b:
                    config_block_ok = True
                    break
    checks["config_issue_has_node_bom_with_path"] = config_block_ok

    # Gateway issue has schtasks in ACTION_REQUIRED
    gateway_block_ok = False
    for b in blocks:
        comp = extract_component_from_block(b).strip().lower()
        if comp == "gateway":
            if contains_case_insensitive(b, "schtasks"):
                gateway_block_ok = True
                break
    checks["gateway_issue_has_schtasks_action"] = gateway_block_ok

    # Channel issue has "openclaw status --deep"
    channel_block_ok = False
    for b in blocks:
        comp = extract_component_from_block(b).strip().lower()
        if comp == "channel":
            if "openclaw status --deep" in b:
                channel_block_ok = True
                break
    checks["channel_issue_has_deep_probe"] = channel_block_ok

    # Security issue has icacls in ACTION_REQUIRED
    security_block_ok = False
    for b in blocks:
        comp = extract_component_from_block(b).strip().lower()
        if comp == "security":
            if contains_case_insensitive(b, "icacls"):
                security_block_ok = True
                break
    checks["security_issue_has_icacls_action"] = security_block_ok

    # Memory issue references fts unavailable or fts5
    memory_block_ok = False
    for b in blocks:
        comp = extract_component_from_block(b).strip().lower()
        if comp == "memory":
            if contains_case_insensitive(b, "fts unavailable") or contains_case_insensitive(b, "fts5"):
                memory_block_ok = True
                break
    checks["memory_issue_references_fts"] = memory_block_ok

    # Evidence substrings
    if contains_case_insensitive(report_text or "", "econnrefused"):
        checks["evidence_contains_econnrefused"] = True
    if contains_case_insensitive(report_text or "", "fts unavailable") or contains_case_insensitive(report_text or "", "fts5"):
        checks["evidence_contains_fts"] = True

    # issues.json validations
    issues_array = None
    try:
        parsed = json.loads(issues_json_text) if issues_json_text is not None else None
        if isinstance(parsed, list):
            checks["issues_json_valid_array"] = True
            issues_array = parsed
    except Exception:
        issues_array = None

    if isinstance(issues_array, list):
        if len(issues_array) >= 5:
            checks["issues_json_len_at_least_5"] = True

        # fields presence
        fields_ok = True
        for item in issues_array:
            if not isinstance(item, dict):
                fields_ok = False
                break
            for key in ["component", "severity", "finding", "evidence"]:
                if key not in item or not isinstance(item[key], str) or item[key] == "":
                    fields_ok = False
                    break
            if not fields_ok:
                break
        checks["issues_json_fields_present"] = fields_ok

        # components coverage
        comp_set = set()
        for item in issues_array:
            if isinstance(item, dict) and isinstance(item.get("component"), str):
                comp_set.add(item["component"].strip().lower())
        if required_components.issubset(comp_set):
            checks["issues_json_components_cover_required"] = True

    # Compute reward
    # If missing required files, reward must be 0.0
    if not (checks["has_recovery_report_file"] and checks["has_issues_json_file"]):
        reward = 0.0
    else:
        # Count total checks excluding presence of files? We include all booleans.
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Scale to [0,1]
        reward = passed / total if total > 0 else 0.0

    # Print exactly one JSON object
    output = {"reward": round(reward, 6)}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()