import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def count_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip() != "")
    except Exception:
        return 0

def parse_topics_csv(path):
    topics = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = row.get("topic")
                if isinstance(t, str) and t.strip():
                    topics.append(t.strip())
    except Exception:
        pass
    return topics

def parse_messages_jsonl(path):
    topics = set()
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                    t = obj.get("topic")
                    if isinstance(t, str):
                        topics.add(t)
                except Exception:
                    # If a line is not valid JSON, still count it as a record for minimal validation
                    records.append({"_raw": line})
    except Exception:
        pass
    return topics, records

def parse_consume_count(path):
    text = read_text(path)
    if not text:
        return None
    # Try to find a number near "consume_count"
    lines = text.splitlines()
    for ln in lines:
        if re.search(r'consume_count', ln, flags=re.IGNORECASE):
            m = re.search(r'(\d+)', ln)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    pass
    # Fallback: first integer anywhere in file
    m = re.search(r'(\d+)', text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def file_exists(path):
    return os.path.isfile(path)

def dir_has_any_files(path):
    if not os.path.isdir(path):
        return False
    for _, _, files in os.walk(path):
        if files:
            return True
    return False

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def jsonl_line_is_object(line):
    s = line.strip()
    return s.startswith("{") and s.endswith("}")

def get_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f]
    except Exception:
        return []

def contains_all_topics(text, topics):
    for t in topics:
        if t not in text:
            return False
    return True

def produce_log_topics_covered(log_lines, topics):
    # Check that at least one line contains each topic substring
    for t in topics:
        found = any((t in ln) for ln in log_lines)
        if not found:
            return False
    return True

def consumed_counts_valid_for_all(output_dir, topics, max_n):
    if max_n is None or max_n < 1:
        return False
    for t in topics:
        p = os.path.join(output_dir, "consumed", f"{t}.jsonl")
        if not os.path.isfile(p):
            return False
        cnt = count_nonempty_lines(p)
        if cnt < 1 or cnt > max_n:
            return False
    return True

def consumed_lines_jsonlike_for_all(output_dir, topics):
    for t in topics:
        p = os.path.join(output_dir, "consumed", f"{t}.jsonl")
        if not os.path.isfile(p):
            return False
        lines = get_lines(p)
        has_at_least_one = False
        for ln in lines:
            if ln.strip() == "":
                continue
            has_at_least_one = True
            if not jsonl_line_is_object(ln):
                return False
        if not has_at_least_one:
            return False
    return True

def consumed_files_exist_for_all(output_dir, topics):
    for t in topics:
        p = os.path.join(output_dir, "consumed", f"{t}.jsonl")
        if not os.path.isfile(p):
            return False
    return True

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks (all False)
checks = {
    "has_topics_actions": False,
    "topics_actions_covers_all_topics": False,
    "has_produce_log": False,
    "produce_log_min_lines": False,
    "produce_log_topics_covered": False,
    "consumed_all_topics_present": False,
    "consumed_counts_valid": False,
    "consumed_lines_jsonlike": False,
    "has_workflow_json": False,
    "workflow_json_keys_valid": False,
    "workflow_active_false": False,
    "has_runbook_md": False,
    "runbook_required_terms": False,
    "has_monero_config_json": False,
    "monero_config_threads_and_tls": False,
    "has_telemetry_md": False,
    "telemetry_terms_present": False,
    "mining_telemetry_consumed_present": False,
    "has_lifegoals_plan": False,
    "lifegoals_plan_has_SMART": False,
    "lifegoals_events_consumed_present": False,
}

# No-op baseline: if output dir missing or empty, reward must be 0.0
output_has_files = dir_has_any_files(output_dir)

# Parse input references
topics_csv_path = os.path.join(input_dir, "topics.csv")
messages_jsonl_path = os.path.join(input_dir, "messages.jsonl")
spec_md_path = os.path.join(input_dir, "spec.md")

topics_in_csv = parse_topics_csv(topics_csv_path)
distinct_topics_from_msgs, msg_records = parse_messages_jsonl(messages_jsonl_path)
consume_count = parse_consume_count(spec_md_path)

# 1) topics_actions.md
topics_actions_path = os.path.join(output_dir, "topics_actions.md")
if file_exists(topics_actions_path):
    checks["has_topics_actions"] = True
    content = read_text(topics_actions_path)
    # Must contain every topic name from input/topics.csv as exact substrings (case sensitive)
    if topics_in_csv and contains_all_topics(content, topics_in_csv):
        checks["topics_actions_covers_all_topics"] = True

# 2) produce_log.txt
produce_log_path = os.path.join(output_dir, "produce_log.txt")
if file_exists(produce_log_path):
    checks["has_produce_log"] = True
    log_lines = get_lines(produce_log_path)
    # Must have at least as many lines as records in input/messages.jsonl
    records_count = sum(1 for r in msg_records)  # includes parsed and fallback raw
    if len([ln for ln in log_lines if ln.strip() != ""]) >= records_count and records_count > 0:
        checks["produce_log_min_lines"] = True
    # Must include at least one occurrence of each distinct topic appearing in input/messages.jsonl
    if distinct_topics_from_msgs and produce_log_topics_covered(log_lines, distinct_topics_from_msgs):
        checks["produce_log_topics_covered"] = True

# 3) consumed per topic files
# For each distinct topic in input/messages.jsonl:
# output/consumed/<topic>.jsonl must exist, contain between 1 and N lines inclusive,
# and each line should look like JSON object.
if distinct_topics_from_msgs:
    if consumed_files_exist_for_all(output_dir, distinct_topics_from_msgs):
        checks["consumed_all_topics_present"] = True
    if consume_count is not None and consume_count > 0:
        if consumed_counts_valid_for_all(output_dir, distinct_topics_from_msgs, consume_count):
            checks["consumed_counts_valid"] = True
    if consumed_lines_jsonlike_for_all(output_dir, distinct_topics_from_msgs):
        checks["consumed_lines_jsonlike"] = True

# 4) workflow.json and runbook.md
workflow_json_path = os.path.join(output_dir, "workflow.json")
runbook_md_path = os.path.join(output_dir, "runbook.md")
wf = load_json(workflow_json_path)
if wf is not None:
    checks["has_workflow_json"] = True
    required_keys = {"name", "nodes", "connections", "settings", "active"}
    if required_keys.issubset(set(wf.keys())):
        checks["workflow_json_keys_valid"] = True
        if wf.get("active") is False:
            checks["workflow_active_false"] = True
if file_exists(runbook_md_path):
    checks["has_runbook_md"] = True
    rb_text = read_text(runbook_md_path)
    # include the words "webhook", "Idempotency", "Retry", "Review queue", and "run_id"
    need_terms = ["webhook", "Idempotency", "Retry", "Review queue", "run_id"]
    found_all = True
    low = rb_text.lower()
    for term in need_terms:
        if term.lower() not in low:
            found_all = False
            break
    if found_all:
        checks["runbook_required_terms"] = True

# 5) monero config and telemetry
monero_config_path = os.path.join(output_dir, "monero", "config.json")
monero_telemetry_md_path = os.path.join(output_dir, "monero", "telemetry.md")
monero_cfg = load_json(monero_config_path)
if monero_cfg is not None:
    checks["has_monero_config_json"] = True
    # include "max-threads-hint": 20 and a pool config where "tls" is true
    threads_ok = False
    tls_ok = False
    # max-threads-hint may be nested under "cpu" or top-level; check both
    try:
        if monero_cfg.get("cpu", {}).get("max-threads-hint") == 20 or monero_cfg.get("max-threads-hint") == 20:
            threads_ok = True
    except Exception:
        threads_ok = False
    try:
        pools = monero_cfg.get("pools", [])
        if isinstance(pools, list):
            for p in pools:
                if isinstance(p, dict) and p.get("tls") is True:
                    tls_ok = True
                    break
    except Exception:
        tls_ok = False
    if threads_ok and tls_ok:
        checks["monero_config_threads_and_tls"] = True
if file_exists(monero_telemetry_md_path):
    checks["has_telemetry_md"] = True
    tel_text = read_text(monero_telemetry_md_path).lower()
    if ("telemetry" in tel_text) and (("hashrate" in tel_text) or ("rx/0" in tel_text)):
        checks["telemetry_terms_present"] = True

# mining telemetry consumed presence
mining_consumed_path = os.path.join(output_dir, "consumed", "mining.telemetry.jsonl")
if file_exists(mining_consumed_path):
    if count_nonempty_lines(mining_consumed_path) > 0:
        checks["mining_telemetry_consumed_present"] = True

# 6) lifegoals plan and events consumed presence
lifegoals_plan_path = os.path.join(output_dir, "lifegoals_plan.md")
if file_exists(lifegoals_plan_path):
    checks["has_lifegoals_plan"] = True
    plan_text = read_text(lifegoals_plan_path)
    if "SMART" in plan_text:
        checks["lifegoals_plan_has_SMART"] = True

lifegoals_events_consumed_path = os.path.join(output_dir, "consumed", "lifegoals.events.jsonl")
if file_exists(lifegoals_events_consumed_path):
    if count_nonempty_lines(lifegoals_events_consumed_path) > 0:
        checks["lifegoals_events_consumed_present"] = True

# Compute reward
# If output dir missing or has no files, reward is exactly 0.0
if not output_has_files:
    reward = 0.0
else:
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

# Print final JSON (exactly one object on last non-empty line)
print(json.dumps({"reward": reward, **checks}))