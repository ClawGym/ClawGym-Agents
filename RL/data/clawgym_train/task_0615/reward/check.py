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

def is_nonempty_string(x):
    return isinstance(x, str) and len(x.strip()) > 0

def parse_frontmatter(md_text):
    # Returns (frontmatter_str, body_str) or (None, None) if not present
    if md_text is None:
        return None, None
    lines = md_text.splitlines()
    if not lines:
        return None, None
    # Find first non-empty line
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return None, None
    start = idx
    idx += 1
    while idx < len(lines) and lines[idx].strip() != "---":
        idx += 1
    if idx >= len(lines):
        return None, None
    end = idx
    fm = "\n".join(lines[start + 1:end])
    body = "\n".join(lines[end + 1:])
    return fm, body

def strip_quotes(s):
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def find_block(lines, key):
    # returns (start_index, indent, end_index_exclusive) for block 'key:'
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}\s*:\s*$", line):
            indent = len(line) - len(line.lstrip(" "))
            # find end of block: next line with indent <= this indent (and non-empty)
            j = i + 1
            while j < len(lines):
                line_j = lines[j]
                if line_j.strip() == "":
                    j += 1
                    continue
                indent_j = len(line_j) - len(line_j.lstrip(" "))
                if indent_j <= indent:
                    break
                j += 1
            return i, indent, j
    return None, None, None

def find_key_value(lines, parent_indent, key, start, end):
    # find 'key: value' within start..end-1 where indent > parent_indent
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$")
    for i in range(start, end):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            continue
        m = pattern.match(line)
        if m:
            return strip_quotes(m.group(1))
    return None

def find_nested_block(lines, parent_indent, key, start, end):
    # find 'key:' defining nested block within start..end-1 with indent > parent_indent
    for i in range(start, end):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            continue
        if re.match(rf"^\s*{re.escape(key)}\s*:\s*$", line):
            # determine end of this sub-block
            j = i + 1
            while j < end:
                line_j = lines[j]
                if line_j.strip() == "":
                    j += 1
                    continue
                indent_j = len(line_j) - len(line_j.lstrip(" "))
                if indent_j <= indent:
                    break
                j += 1
            return i, indent, j
    return None, None, None

def parse_capabilities(lines, block_start, block_indent, block_end):
    # collect lines starting with "- " under capabilities:
    items = []
    for i in range(block_start + 1, block_end):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= block_indent:
            continue
        m = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if m:
            items.append(strip_quotes(m.group(1)))
    return items

def parse_version(frontmatter_text):
    for line in frontmatter_text.splitlines():
        m = re.match(r'^\s*version\s*:\s*(.+?)\s*$', line)
        if m:
            return strip_quotes(m.group(1))
    return None

def candidate_paths_entries(text):
    # Extract lines under "Candidate paths" heading until next known heading
    headings = ["Goal", "Constraints", "Candidate paths", "Current action", "Evidence", "Next move", "Stop reason"]
    lines = text.splitlines()
    idx = None
    # Accept heading with optional colon, case-insensitive match
    def is_heading_line(line):
        s = line.strip()
        s = s[:-1] if s.endswith(":") else s
        return s in headings
    for i, line in enumerate(lines):
        s = line.strip()
        base = s[:-1] if s.endswith(":") else s
        if base == "Candidate paths":
            idx = i
            break
    if idx is None:
        return []
    j = idx + 1
    entries = []
    while j < len(lines):
        s = lines[j].strip()
        if is_heading_line(lines[j]):
            break
        if s != "":
            # consider bullet or numbered list or paragraph line
            if s.startswith("- ") or s.startswith("* ") or re.match(r"^\d+\.\s+", s) or True:
                entries.append(s)
        j += 1
    # Remove any blank lines stored (should not be any)
    entries = [e for e in entries if e.strip()]
    return entries

def check_integer(n):
    return isinstance(n, int)

def check_number(n):
    return isinstance(n, (int, float))

def last_non_empty_line(lines):
    for line in reversed(lines):
        if line.strip() != "":
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {}

    # Paths
    wf_path = os.path.join(output_dir, "workflow_blueprint.json")
    ac_path = os.path.join(output_dir, "agent-card.md")
    prog_path = os.path.join(output_dir, "progress.md")
    rp_path = os.path.join(output_dir, "rate_plan.json")

    # 1) workflow_blueprint.json checks
    checks["wf_exists"] = os.path.isfile(wf_path)
    wf_json = load_json(wf_path) if checks["wf_exists"] else None
    checks["wf_valid_json"] = wf_json is not None

    checks["wf_has_top_keys"] = False
    checks["wf_workflow_name"] = False
    checks["wf_trigger_present"] = False
    checks["wf_steps_length"] = False
    checks["wf_steps_fields_and_types"] = False
    checks["wf_steps_order_sequence"] = False
    checks["wf_steps_type_coverage_llm"] = False
    checks["wf_steps_type_coverage_http"] = False
    checks["wf_steps_type_coverage_db_or_task"] = False
    checks["wf_has_new_email_name"] = False
    checks["wf_has_webhook_ticket_name"] = False
    checks["wf_has_rate_limit_step_with_good_on_failure"] = False

    if checks["wf_valid_json"]:
        status = wf_json.get("status")
        summary = wf_json.get("summary")
        artifacts = wf_json.get("artifacts")
        details = wf_json.get("details")
        checks["wf_has_top_keys"] = (
            isinstance(status, str) and
            isinstance(summary, str) and
            isinstance(artifacts, list) and
            isinstance(details, dict)
        )
        if isinstance(details, dict):
            checks["wf_workflow_name"] = details.get("workflow_name") == "Feedback Triage Automation"
            trigger = details.get("trigger")
            checks["wf_trigger_present"] = is_nonempty_string(trigger)
            steps = details.get("steps")
            if isinstance(steps, list):
                checks["wf_steps_length"] = len(steps) >= 7
                # Validate step fields and types
                allowed_types = {"http", "llm", "db", "task"}
                allowed_on_failure = {"retry", "skip", "stop"}
                step_orders = []
                all_fields_ok = True
                has_llm = False
                has_http = False
                has_db_or_task = False
                has_new_email = False
                has_webhook_ticket = False
                has_rate_limit_step = False
                rate_limit_step_on_failure_ok = False
                for step in steps:
                    order = step.get("order")
                    name = step.get("name")
                    stype = step.get("type")
                    onf = step.get("on_failure")
                    if not (isinstance(order, int) and is_nonempty_string(name) and isinstance(stype, str) and isinstance(onf, str)):
                        all_fields_ok = False
                    if isinstance(stype, str) and stype not in allowed_types:
                        all_fields_ok = False
                    if isinstance(onf, str) and onf not in allowed_on_failure:
                        all_fields_ok = False
                    if isinstance(order, int):
                        step_orders.append(order)
                    if isinstance(stype, str):
                        if stype == "llm":
                            has_llm = True
                        if stype == "http":
                            has_http = True
                        if stype in {"db", "task"}:
                            has_db_or_task = True
                    if is_nonempty_string(name):
                        lname = name.lower()
                        if "new_email" in lname:
                            has_new_email = True
                        if "webhook_ticket" in lname:
                            has_webhook_ticket = True
                        if "rate limit" in lname:
                            has_rate_limit_step = True
                            if isinstance(onf, str) and onf in {"retry", "skip"}:
                                rate_limit_step_on_failure_ok = True
                checks["wf_steps_fields_and_types"] = all_fields_ok
                # Order sequence check
                if step_orders:
                    sorted_orders = sorted(step_orders)
                    checks["wf_steps_order_sequence"] = sorted_orders[0] == 1 and all(
                        sorted_orders[i] == i + 1 for i in range(len(sorted_orders))
                    )
                checks["wf_steps_type_coverage_llm"] = has_llm
                checks["wf_steps_type_coverage_http"] = has_http
                checks["wf_steps_type_coverage_db_or_task"] = has_db_or_task
                checks["wf_has_new_email_name"] = has_new_email
                checks["wf_has_webhook_ticket_name"] = has_webhook_ticket
                checks["wf_has_rate_limit_step_with_good_on_failure"] = has_rate_limit_step and rate_limit_step_on_failure_ok

    # 2) agent-card.md checks
    checks["ac_exists"] = os.path.isfile(ac_path)
    ac_text = read_text(ac_path) if checks["ac_exists"] else None
    checks["ac_frontmatter_present"] = False
    checks["ac_version_is_1"] = False
    checks["ac_channels_email_present"] = False
    checks["ac_channels_webhook_has_url_method"] = False
    checks["ac_channels_webhook_url_https"] = False
    checks["ac_capabilities_include_support_tickets"] = False
    checks["ac_body_has_for_agents"] = False
    checks["ac_body_has_response_time"] = False

    if ac_text is not None:
        fm, body = parse_frontmatter(ac_text)
        checks["ac_frontmatter_present"] = fm is not None and body is not None
        if fm is not None:
            version_val = parse_version(fm)
            checks["ac_version_is_1"] = (version_val == "1")
            fm_lines = fm.splitlines()
            # channels block
            c_start, c_indent, c_end = find_block(fm_lines, "channels")
            email_val = None
            webhook_url = None
            webhook_method = None
            if c_start is not None:
                # email
                email_val = find_key_value(fm_lines, c_indent, "email", c_start + 1, c_end)
                if email_val is not None and email_val.strip() != "":
                    checks["ac_channels_email_present"] = True
                # webhook nested
                w_start, w_indent, w_end = find_nested_block(fm_lines, c_indent, "webhook", c_start + 1, c_end)
                if w_start is not None:
                    webhook_url = find_key_value(fm_lines, w_indent, "url", w_start + 1, w_end)
                    webhook_method = find_key_value(fm_lines, w_indent, "method", w_start + 1, w_end)
                    if webhook_url is not None and webhook_method is not None and webhook_method.strip() != "":
                        checks["ac_channels_webhook_has_url_method"] = True
                        if isinstance(webhook_url, str) and webhook_url.startswith("https://"):
                            checks["ac_channels_webhook_url_https"] = True
            # capabilities block
            cap_start, cap_indent, cap_end = find_block(fm_lines, "capabilities")
            if cap_start is not None:
                caps = parse_capabilities(fm_lines, cap_start, cap_indent, cap_end)
                if any(str(c).strip() == "support_tickets" for c in caps):
                    checks["ac_capabilities_include_support_tickets"] = True
        if body is not None:
            checks["ac_body_has_for_agents"] = ("For agents" in body)
            checks["ac_body_has_response_time"] = ("Response time:" in body)

    # 3) progress.md checks
    checks["prog_exists"] = os.path.isfile(prog_path)
    prog_text = read_text(prog_path) if checks["prog_exists"] else None
    checks["prog_has_goal"] = False
    checks["prog_has_constraints"] = False
    checks["prog_has_candidate_paths"] = False
    checks["prog_has_current_action"] = False
    checks["prog_has_evidence"] = False
    checks["prog_has_next_move_or_stop_reason"] = False
    checks["prog_candidate_paths_has_two_entries"] = False
    checks["prog_has_classification_keyword"] = False

    if prog_text is not None:
        lines = [ln.strip() for ln in prog_text.splitlines()]
        def has_heading(name):
            return any((ln == name or ln == f"{name}:") for ln in lines)
        checks["prog_has_goal"] = has_heading("Goal")
        checks["prog_has_constraints"] = has_heading("Constraints")
        checks["prog_has_candidate_paths"] = has_heading("Candidate paths")
        checks["prog_has_current_action"] = has_heading("Current action")
        checks["prog_has_evidence"] = has_heading("Evidence")
        checks["prog_has_next_move_or_stop_reason"] = has_heading("Next move") or has_heading("Stop reason")

        entries = candidate_paths_entries(prog_text)
        # Count distinct non-empty entries (simple heuristic)
        checks["prog_candidate_paths_has_two_entries"] = len(entries) >= 2

        lowered = prog_text.lower()
        for kw in ["continue", "repair", "switch", "clarify", "stop"]:
            if kw in lowered:
                checks["prog_has_classification_keyword"] = True
                break

    # 4) rate_plan.json checks
    checks["rp_exists"] = os.path.isfile(rp_path)
    rp_json = load_json(rp_path) if checks["rp_exists"] else None
    checks["rp_valid_json"] = rp_json is not None
    checks["rp_has_apis_keys"] = False
    checks["rp_openai_fields_types"] = False
    checks["rp_zendesk_fields_types"] = False

    def validate_api_block(obj):
        if not isinstance(obj, dict):
            return False
        limit = obj.get("limit")
        windowMs = obj.get("windowMs")
        retry = obj.get("retry")
        maxRetries = obj.get("maxRetries")
        queueSize = obj.get("queueSize")
        strategy = obj.get("strategy")
        if not (check_number(limit) and limit > 0):
            return False
        if not (check_number(windowMs) and windowMs > 0):
            return False
        if not isinstance(retry, bool):
            return False
        if not (check_integer(maxRetries) and maxRetries >= 1):
            return False
        if not (check_integer(queueSize) and queueSize >= 1):
            return False
        if not (isinstance(strategy, str) and strategy in {"conservative", "aggressive", "batch"}):
            return False
        return True

    if checks["rp_valid_json"]:
        apis = rp_json.get("apis")
        if isinstance(apis, dict) and "openai" in apis and "zendesk" in apis:
            checks["rp_has_apis_keys"] = True
            checks["rp_openai_fields_types"] = validate_api_block(apis.get("openai"))
            checks["rp_zendesk_fields_types"] = validate_api_block(apis.get("zendesk"))

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or none of the four expected files exist, reward = 0.0
    expected_files_exist = any(os.path.isfile(p) for p in [wf_path, ac_path, prog_path, rp_path])
    if not os.path.isdir(output_dir) or not expected_files_exist:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()