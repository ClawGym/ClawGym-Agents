import json
import os
import sys

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def contains_ci(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()

def check_workflow_json(workflow_obj, raw_text: str) -> dict:
    checks = {
        "workflow_json_valid": False,
        "workflow_structure_keys": False,
        "workflow_active_false": False,
        "cron_trigger_present": False,
        "timezone_in_workflow": False,
        "run_id_in_workflow": False,
        "idempotency_node_present": False,
        "logging_node_present": False,
        "review_queue_node_present": False,
        "retry_or_backoff_present": False,
        "source_sftp_hint_present": False,
        "secrets_not_present": False,
    }
    if not isinstance(workflow_obj, dict):
        return checks

    checks["workflow_json_valid"] = True

    # Structure keys
    has_keys = all(k in workflow_obj for k in ("name", "nodes", "connections", "settings", "active"))
    if has_keys and isinstance(workflow_obj.get("nodes"), list) and isinstance(workflow_obj.get("connections"), dict) and isinstance(workflow_obj.get("settings"), dict):
        checks["workflow_structure_keys"] = True

    # Active false
    if workflow_obj.get("active") is False:
        checks["workflow_active_false"] = True

    # Nodes analysis
    nodes = workflow_obj.get("nodes") if isinstance(workflow_obj.get("nodes"), list) else []
    # Helper to iterate node names/types
    node_names = []
    node_types = []
    for n in nodes:
        if isinstance(n, dict):
            name = str(n.get("name") or "")
            ntype = str(n.get("type") or "")
            node_names.append(name)
            node_types.append(ntype)

    # Cron trigger node
    for t in node_types:
        if "n8n-nodes-base.cron".lower() in t.lower():
            checks["cron_trigger_present"] = True
            break

    # Timezone presence
    if contains_ci(raw_text, "America/New_York"):
        checks["timezone_in_workflow"] = True

    # run_id evidence
    if contains_ci(raw_text, "run_id"):
        checks["run_id_in_workflow"] = True

    # Idempotency node
    if any(("dedup" in n.lower()) or ("idempot" in n.lower()) for n in node_names):
        checks["idempotency_node_present"] = True

    # Logging/audit node
    if any(("log" in n.lower()) or ("logger" in n.lower()) for n in node_names):
        checks["logging_node_present"] = True

    # Review queue node
    if any(("review queue" in n.lower()) or ("review" in n.lower()) for n in node_names):
        checks["review_queue_node_present"] = True

    # Retry/backoff/error evidence
    if any(s in raw_text.lower() for s in ("retry", "backoff", "error")):
        checks["retry_or_backoff_present"] = True

    # Optional source hint: SFTP/FTP in name or type
    if any(("sftp" in x.lower()) or ("ftp" in x.lower()) for x in (node_names + node_types)):
        checks["source_sftp_hint_present"] = True

    # Secrets check
    forbidden = ("sk-", "bearer ", "password", "api_key", "apikey", "x-api-key")
    if not any(f in raw_text.lower() for f in forbidden):
        checks["secrets_not_present"] = True

    return checks

def check_runbook(text: str) -> dict:
    checks = {
        "runbook_has_sections": False,
        "runbook_timezone_present": False,
        "runbook_dedup_key_mentions_email_and_created_at": False,
        "runbook_phrases_present": False,
    }
    lower = text.lower()
    # Sections (case-insensitive). Accept "logging & audit" or "logging and audit".
    required_sections = [
        "purpose",
        "triggers",
        "inputs",
        "outputs",
        "idempotency",
        "error handling",
        # For logging & audit, accept either form
        # We'll check this separately for flexibility
        "operational checks",
    ]
    has_required = all(s in lower for s in required_sections)
    has_logging_audit = ("logging & audit" in lower) or ("logging and audit" in lower)
    if has_required and has_logging_audit:
        checks["runbook_has_sections"] = True

    if "america/new_york" in lower:
        checks["runbook_timezone_present"] = True

    if ("email" in lower) and ("created_at" in lower):
        checks["runbook_dedup_key_mentions_email_and_created_at"] = True

    # Phrases: "review queue" AND "exponential backoff" AND ("no silent failure" OR "stop the line")
    has_review_queue = "review queue" in lower
    has_backoff = "exponential backoff" in lower
    has_no_silent_or_stop = ("no silent failure" in lower) or ("stop the line" in lower)
    if has_review_queue and has_backoff and has_no_silent_or_stop:
        checks["runbook_phrases_present"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_workflow_json": False,
        "workflow_json_valid": False,
        "workflow_structure_keys": False,
        "workflow_active_false": False,
        "cron_trigger_present": False,
        "timezone_in_workflow": False,
        "run_id_in_workflow": False,
        "idempotency_node_present": False,
        "logging_node_present": False,
        "review_queue_node_present": False,
        "retry_or_backoff_present": False,
        "source_sftp_hint_present": False,
        "secrets_not_present": False,
        "has_runbook_md": False,
        "runbook_has_sections": False,
        "runbook_timezone_present": False,
        "runbook_dedup_key_mentions_email_and_created_at": False,
        "runbook_phrases_present": False,
    }

    # Check workflow.json
    workflow_path = os.path.join(output_dir, "workflow.json")
    if os.path.isfile(workflow_path):
        checks["has_workflow_json"] = True
        raw_workflow = read_text(workflow_path)
        workflow_obj = load_json(workflow_path)
        wf_checks = check_workflow_json(workflow_obj, raw_workflow)
        checks.update(wf_checks)

    # Check runbook.md
    runbook_path = os.path.join(output_dir, "runbook.md")
    if os.path.isfile(runbook_path):
        checks["has_runbook_md"] = True
        runbook_text = read_text(runbook_path)
        rb_checks = check_runbook(runbook_text)
        checks.update(rb_checks)

    # Scoring
    # Required checks exclude the optional SFTP hint.
    required_keys = [
        "has_workflow_json",
        "workflow_json_valid",
        "workflow_structure_keys",
        "workflow_active_false",
        "cron_trigger_present",
        "timezone_in_workflow",
        "run_id_in_workflow",
        "idempotency_node_present",
        "logging_node_present",
        "review_queue_node_present",
        "retry_or_backoff_present",
        "secrets_not_present",
        "has_runbook_md",
        "runbook_has_sections",
        "runbook_timezone_present",
        "runbook_dedup_key_mentions_email_and_created_at",
        "runbook_phrases_present",
    ]
    passed_required = sum(1 for k in required_keys if checks.get(k, False))
    total_required = len(required_keys)
    reward = 0.0
    if total_required > 0:
        reward = passed_required / total_required
    # Optional small bonus for SFTP hint (non-fatal)
    if checks.get("source_sftp_hint_present"):
        reward += 0.02
    if reward > 1.0:
        reward = 1.0
    # No-op baseline: if no outputs or missing required artifacts, this will already be 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()