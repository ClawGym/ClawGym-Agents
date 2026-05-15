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

def is_nonempty_file(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def has_heading_with_keyword(text, keyword):
    # Matches markdown headings like #, ##, ### at the line start (ignoring leading spaces)
    # and checks if keyword appears in that heading (case-insensitive).
    if text is None:
        return False
    kw = keyword.lower()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if kw in s.lower():
                return True
    return False

def count_md_checkboxes(text):
    if text is None:
        return 0
    count = 0
    # Accept "- [ ]" (unchecked) and "- [x]" or "- [X]" (checked)
    pattern = re.compile(r'^\s*-\s*\[\s*(?: |x|X)\s*\]\s+', re.IGNORECASE)
    for line in text.splitlines():
        if pattern.search(line):
            count += 1
    return count

def extract_latency_entry_for_ip(latency_list, ip):
    # Find an entry whose "ip" equals the ip or whose "host" string contains the ip (case-insensitive)
    if not isinstance(latency_list, list):
        return None
    for entry in latency_list:
        if not isinstance(entry, dict):
            continue
        ip_field = entry.get("ip")
        host_field = entry.get("host")
        found = False
        if isinstance(ip_field, str) and ip_field.strip() == ip:
            found = True
        elif isinstance(host_field, str) and ip in host_field:
            found = True
        elif isinstance(ip_field, str) and ip in ip_field:
            found = True
        if found:
            return entry
    return None

def has_latency_metrics(entry):
    # Must include avg/min/max/jitter with possible "_ms" suffix
    if not isinstance(entry, dict):
        return False
    def has_metric(base):
        # Accept e.g., "avg" or "avg_ms"
        for key in (base, f"{base}_ms"):
            if key in entry and isinstance(entry[key], (int, float)):
                return True
        return False
    return all(has_metric(m) for m in ("avg", "min", "max", "jitter"))

def has_numeric_fields(obj, fields):
    if not isinstance(obj, dict):
        return False
    for f in fields:
        if f not in obj or not isinstance(obj[f], (int, float)):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) iptables_change_plan.md checks
    plan_path = os.path.join(output_dir, "iptables_change_plan.md")
    plan_text = read_text(plan_path) if is_nonempty_file(plan_path) else None

    checks["plan_exists_nonempty"] = plan_text is not None

    # Phrase checks (case-insensitive)
    def contains_phrase(text, phrase):
        return text is not None and phrase.lower() in text.lower()

    checks["plan_has_principle_of_least_privilege"] = contains_phrase(plan_text, "principle of least privilege")
    checks["plan_has_logging"] = contains_phrase(plan_text, "logging")
    checks["plan_has_staging"] = contains_phrase(plan_text, "staging")
    checks["plan_has_rollback"] = contains_phrase(plan_text, "rollback")

    # Headings for sections
    checks["plan_heading_intro"] = has_heading_with_keyword(plan_text, "intro")
    checks["plan_heading_quickstart"] = has_heading_with_keyword(plan_text, "quickstart")
    checks["plan_heading_patterns"] = has_heading_with_keyword(plan_text, "patterns")
    checks["plan_heading_debugging"] = has_heading_with_keyword(plan_text, "debugging")
    checks["plan_heading_performance"] = has_heading_with_keyword(plan_text, "performance")
    checks["plan_heading_security"] = has_heading_with_keyword(plan_text, "security")
    checks["plan_heading_migration"] = has_heading_with_keyword(plan_text, "migration")
    checks["plan_heading_cheatsheet"] = has_heading_with_keyword(plan_text, "cheatsheet")

    # 2) code_review.md checks
    cr_path = os.path.join(output_dir, "code_review.md")
    cr_text = read_text(cr_path) if is_nonempty_file(cr_path) else None
    checks["code_review_exists_nonempty"] = cr_text is not None

    def has_category_heading(text, phrase):
        if text is None:
            return False
        # Prefer heading lines containing the phrase; fallback to presence anywhere if needed
        if has_heading_with_keyword(text, phrase):
            return True
        # Fallback: presence anywhere
        return phrase.lower() in text.lower()

    checks["cr_heading_critical_issues"] = has_category_heading(cr_text, "Critical Issues")
    checks["cr_heading_state_schema_issues"] = has_category_heading(cr_text, "State Schema Issues")
    checks["cr_heading_graph_structure_issues"] = has_category_heading(cr_text, "Graph Structure Issues")
    checks["cr_heading_async_issues"] = has_category_heading(cr_text, "Async Issues")
    checks["cr_heading_tool_integration_issues"] = has_category_heading(cr_text, "Tool Integration Issues")
    checks["cr_heading_checkpointing_issues"] = has_category_heading(cr_text, "Checkpointing Issues")
    checks["cr_heading_performance_issues"] = has_category_heading(cr_text, "Performance Issues")

    # At least 10 Markdown checklist items
    checks["cr_has_10_checklist_items"] = (count_md_checkboxes(cr_text) >= 10)

    # 3) network_test.json checks
    net_path = os.path.join(output_dir, "network_test.json")
    net_obj = None
    net_valid_json = False
    if is_nonempty_file(net_path):
        try:
            with open(net_path, "r", encoding="utf-8") as f:
                net_obj = json.load(f)
            net_valid_json = isinstance(net_obj, dict)
        except Exception:
            net_obj = None
            net_valid_json = False

    checks["network_json_exists_valid"] = net_valid_json

    has_top_keys = False
    latency_list = None
    download_obj = None
    upload_obj = None
    if net_valid_json:
        has_top_keys = all(k in net_obj for k in ("timestamp", "latency", "download", "upload"))
        latency_list = net_obj.get("latency")
        download_obj = net_obj.get("download")
        upload_obj = net_obj.get("upload")
    checks["network_has_required_keys"] = bool(has_top_keys)

    # Latency coverage for each IP and metrics per entry
    ips = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    for ip in ips:
        key_cover = f"network_latency_covers_{ip.replace('.', '_')}"
        key_metrics = f"network_latency_metrics_{ip.replace('.', '_')}"
        if net_valid_json and isinstance(latency_list, list):
            entry = extract_latency_entry_for_ip(latency_list, ip)
            covers = entry is not None
            checks[key_cover] = covers
            checks[key_metrics] = has_latency_metrics(entry) if covers else False
        else:
            checks[key_cover] = False
            checks[key_metrics] = False

    # Download/Upload numeric fields
    checks["network_download_fields_numeric"] = has_numeric_fields(download_obj, ["bytes", "elapsed_s", "speed_mbps"]) if net_valid_json else False
    checks["network_upload_fields_numeric"] = has_numeric_fields(upload_obj, ["bytes", "elapsed_s", "speed_mbps"]) if net_valid_json else False

    # 4) inter_agent_message.txt checks
    msg_path = os.path.join(output_dir, "inter_agent_message.txt")
    msg_text = read_text(msg_path) if is_nonempty_file(msg_path) else None
    checks["message_exists_nonempty"] = msg_text is not None

    def first_line_starts_with(text, prefix):
        if text is None:
            return False
        first = text.splitlines()[0] if text.splitlines() else ""
        return first.startswith(prefix)

    checks["message_starts_required_prefix"] = first_line_starts_with(msg_text, "[From Agent ops] ")
    def contains_ci(text, word):
        return text is not None and (word.lower() in text.lower())

    checks["message_mentions_netops"] = contains_ci(msg_text, "netops")
    checks["message_mentions_firewall"] = contains_ci(msg_text, "firewall")
    checks["message_mentions_acknowledge"] = contains_ci(msg_text, "acknowledge")
    checks["message_mentions_output_network_test_json"] = ("output/network_test.json" in msg_text) if msg_text is not None else False

    # Compute reward as average of all checks that are True
    # All checks depend on output artifacts; if none exist, all False -> reward 0.0
    total_checks = len(checks)
    true_checks = sum(1 for v in checks.values() if v)
    reward = (true_checks / total_checks) if total_checks > 0 else 0.0

    # Ensure baseline: if output directory missing or empty -> reward 0.0 naturally (all checks False)
    # Clip reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()