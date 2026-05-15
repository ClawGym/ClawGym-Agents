import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def has_confidence_percentage(text):
    if not text:
        return False
    # Find percentages 0% to 100%
    for m in re.findall(r'\b(\d{1,3})%\b', text):
        try:
            val = int(m)
            if 0 <= val <= 100:
                return True
        except Exception:
            continue
    return False

def find_compliance_declaration_ark_version(text):
    if not text:
        return False
    # Locate "Compliance Declaration" section and search for ARK and version near it
    idx = re.search(r'compliance declaration', text, re.IGNORECASE)
    if not idx:
        return False
    start = idx.start()
    window = text[start:start+800]  # scan nearby content
    if re.search(r'\bARK\b', window, re.IGNORECASE):
        # Look for version variants around 1.x (e.g., V1, v1, 1.1, 1.1.0, Version 1.1)
        version_pat = r'(version|v)\s*[:=]?\s*v?\s*1(\.1(\.0)?)?'
        if re.search(version_pat, window, re.IGNORECASE):
            return True
        # Also accept explicit "V1" or "v1" in the window
        if re.search(r'\b[vV]\s*1\b', window):
            return True
        # Or "1.1" or "1.1.0"
        if re.search(r'\b1\.1(\.0)?\b', window):
            return True
    return False

def count_proposal_blocks(text):
    """
    Count proposal blocks that contain the 5 required labeled lines in order:
    - Detected ID:
    - Detected problem:
    - Computational modification proposal:
    - Note for user:
    - [Field for human validation]
    """
    if not text:
        return 0, 0
    lines = text.splitlines()
    id_indices = [i for i, l in enumerate(lines) if l.strip().lower().startswith("detected id:")]
    valid_blocks = 0
    for idx_i, i in enumerate(id_indices):
        # Block ends before the next "Detected ID:" or EOF
        end = id_indices[idx_i + 1] if idx_i + 1 < len(id_indices) else len(lines)
        block = lines[i:end]
        # We allow optional blank lines between fields but enforce order
        required_prefixes = [
            "detected id:",
            "detected problem:",
            "computational modification proposal:",
            "note for user:",
            "[field for human validation]"
        ]
        ptr = 0
        ok = True
        for req in required_prefixes:
            found = False
            while ptr < len(block):
                cur = block[ptr].strip().lower()
                ptr += 1
                if cur.startswith(req):
                    found = True
                    break
            if not found:
                ok = False
                break
        if ok:
            valid_blocks += 1
    # total starting "Detected ID:" lines
    total_detected_id = len(id_indices)
    return valid_blocks, total_detected_id

def task_board_simple_checks(text):
    """
    Perform simple structural checks without full YAML parsing.
    Returns a dict of booleans.
    """
    results = {
        "task_board_has_tasks_key": False,
        "task_board_at_least_three_tasks": False,
        "task_board_statuses_include_required": False,
        "task_board_each_task_has_required_fields": False,
        "task_board_histories_are_lists": False,
    }
    if not text:
        return results

    # tasks key
    if re.search(r'^\s*tasks\s*:\s*', text, re.MULTILINE):
        results["task_board_has_tasks_key"] = True

    # find task entries by "- id:"
    id_matches = list(re.finditer(r'^\s*-\s*id\s*:\s*.+', text, re.MULTILINE))
    if len(id_matches) >= 3:
        results["task_board_at_least_three_tasks"] = True

    # statuses required
    has_todo = re.search(r'^\s*status\s*:\s*TODO\s*$', text, re.MULTILINE) is not None
    has_in_progress = re.search(r'^\s*status\s*:\s*IN_PROGRESS\s*$', text, re.MULTILINE) is not None
    has_qa_review = re.search(r'^\s*status\s*:\s*QA_REVIEW\s*$', text, re.MULTILINE) is not None
    if has_todo and has_in_progress and has_qa_review:
        results["task_board_statuses_include_required"] = True

    # Check per-task fields for first three tasks
    per_task_required_ok = True
    history_list_ok = True
    # Determine block slices between - id: occurrences
    indices = [m.start() for m in id_matches]
    indices.append(len(text))
    for k in range(min(3, len(id_matches))):
        start = indices[k]
        end = indices[k+1]
        block = text[start:end]
        # Must contain title, status, description, history
        for field in ["title:", "status:", "description:", "history:"]:
            if re.search(r'^\s*' + re.escape(field) + r'\s*', block, re.MULTILINE) is None:
                per_task_required_ok = False
        # History should be a list: either "history: []" on same line or subsequent list items
        history_line_match = re.search(r'^\s*history\s*:\s*(.*)$', block, re.MULTILINE)
        if history_line_match:
            after = history_line_match.group(1).strip()
            if after == "[]":
                pass  # ok
            else:
                # find the next non-empty line after the history: line within block
                lines = block.splitlines()
                hist_idx = None
                for idx, ln in enumerate(lines):
                    if re.match(r'^\s*history\s*:', ln):
                        hist_idx = idx
                        break
                next_non_empty = None
                if hist_idx is not None:
                    for ln in lines[hist_idx+1:]:
                        if ln.strip() == "":
                            continue
                        next_non_empty = ln
                        break
                if next_non_empty is None:
                    history_list_ok = False
                else:
                    if not re.match(r'^\s*-\s+', next_non_empty):
                        history_list_ok = False
        else:
            history_list_ok = False

    if per_task_required_ok and len(id_matches) >= 3:
        results["task_board_each_task_has_required_fields"] = True
    if history_list_ok and len(id_matches) >= 3:
        results["task_board_histories_are_lists"] = True

    return results

def attestation_json_checks(path):
    checks = {
        "attestation_spec_valid_json": False,
        "attestation_spec_has_required_keys": False,
        "attestation_spec_types_and_values_valid": False,
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        checks["attestation_spec_valid_json"] = True
    except Exception:
        return checks

    required_keys = [
        "nonce",
        "solutions",
        "signature",
        "publicKey",
        "publicId",
        "timestamp",
        "responseTimeMs",
        "batchSize",
        "maxResponseTimeMs",
    ]
    if all(k in data for k in required_keys):
        checks["attestation_spec_has_required_keys"] = True
        # type and value checks
        types_ok = True
        types_ok = types_ok and isinstance(data["nonce"], str)
        types_ok = types_ok and isinstance(data["solutions"], list)
        types_ok = types_ok and isinstance(data["signature"], str)
        types_ok = types_ok and isinstance(data["publicKey"], str)
        types_ok = types_ok and isinstance(data["publicId"], str)
        types_ok = types_ok and (isinstance(data["timestamp"], (int, float)))
        types_ok = types_ok and (isinstance(data["responseTimeMs"], (int, float)))
        types_ok = types_ok and (isinstance(data["batchSize"], (int, float)))
        types_ok = types_ok and (isinstance(data["maxResponseTimeMs"], (int, float)))
        values_ok = (int(data["batchSize"]) == 5) and (int(data["maxResponseTimeMs"]) == 8000)
        checks["attestation_spec_types_and_values_valid"] = bool(types_ok and values_ok)
    return checks

def devops_cli_checks(text):
    checks = {
        "devops_cli_mentions_all_commands": False
    }
    if not text:
        return checks
    # Ensure help, run, info, status appear as whole words
    cmds = ["help", "run", "info", "status"]
    ok = True
    for c in cmds:
        if not re.search(r'\b' + re.escape(c) + r'\b', text, re.IGNORECASE):
            ok = False
            break
    checks["devops_cli_mentions_all_commands"] = ok
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) ark_compliance_report.md checks
    ark_report_path = os.path.join(output_dir, "ark_compliance_report.md")
    checks["has_ark_report"] = os.path.isfile(ark_report_path)
    ark_text = read_text(ark_report_path) if checks["has_ark_report"] else None

    checks["ark_report_has_compliance_declaration"] = False
    checks["ark_report_mentions_ark_and_version"] = False
    checks["ark_report_has_verified_facts"] = False
    checks["ark_report_has_hypotheses"] = False
    checks["ark_report_has_confidence_percentage"] = False
    checks["ark_report_exactly_three_proposal_blocks"] = False

    if ark_text is not None:
        if re.search(r'compliance declaration', ark_text, re.IGNORECASE):
            checks["ark_report_has_compliance_declaration"] = True
        checks["ark_report_mentions_ark_and_version"] = find_compliance_declaration_ark_version(ark_text)
        if re.search(r'^\s*Verified Facts\s*$', ark_text, re.MULTILINE):
            checks["ark_report_has_verified_facts"] = True
        if re.search(r'^\s*Hypotheses\s*$', ark_text, re.MULTILINE):
            checks["ark_report_has_hypotheses"] = True
        checks["ark_report_has_confidence_percentage"] = has_confidence_percentage(ark_text)
        valid_blocks, total_detected_id = count_proposal_blocks(ark_text)
        if valid_blocks == 3 and total_detected_id == 3:
            checks["ark_report_exactly_three_proposal_blocks"] = True

    # 2) TASK_BOARD.yaml checks
    task_board_path = os.path.join(output_dir, "TASK_BOARD.yaml")
    checks["has_task_board"] = os.path.isfile(task_board_path)
    tb_text = read_text(task_board_path) if checks["has_task_board"] else None
    tb_checks = {
        "task_board_has_tasks_key": False,
        "task_board_at_least_three_tasks": False,
        "task_board_statuses_include_required": False,
        "task_board_each_task_has_required_fields": False,
        "task_board_histories_are_lists": False,
    }
    if tb_text is not None:
        tb_checks = task_board_simple_checks(tb_text)
    checks.update(tb_checks)

    # 3) attestation_spec.json checks
    attestation_path = os.path.join(output_dir, "attestation_spec.json")
    checks["has_attestation_spec"] = os.path.isfile(attestation_path)
    att_checks = {
        "attestation_spec_valid_json": False,
        "attestation_spec_has_required_keys": False,
        "attestation_spec_types_and_values_valid": False,
    }
    if checks["has_attestation_spec"]:
        att_checks = attestation_json_checks(attestation_path)
    checks.update(att_checks)

    # 4) devops_cli.md checks
    devops_cli_path = os.path.join(output_dir, "devops_cli.md")
    checks["has_devops_cli"] = os.path.isfile(devops_cli_path)
    devops_text = read_text(devops_cli_path) if checks["has_devops_cli"] else None
    devops_checks = {"devops_cli_mentions_all_commands": False}
    if devops_text is not None:
        devops_checks = devops_cli_checks(devops_text)
    checks.update(devops_checks)

    # Compute reward as fraction of passed checks
    # Ensure no-op baseline: if no artifacts exist and none passed, reward 0.0
    total_checks = 0
    passed = 0
    for key, val in checks.items():
        if isinstance(val, bool):
            total_checks += 1
            if val:
                passed += 1
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()