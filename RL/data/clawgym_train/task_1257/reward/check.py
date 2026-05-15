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

def parse_csv_simple(text):
    """
    Parse a simple two-column CSV: action_id,label.
    Header row is optional. Returns list of (action_id, label).
    """
    rows = []
    if text is None:
        return rows
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    for i, line in enumerate(lines):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            # skip malformed rows
            continue
        # Detect and skip header on first line
        if i == 0 and parts[0].lower() == "action_id" and parts[1].lower() == "label":
            continue
        rows.append((parts[0], parts[1]))
    return rows

def expected_label_for_action(action):
    """
    Apply deterministic rules:
    - sensitive if type in {"delete","install","system_config","send_message"}
    - sensitive if type == "external_api" AND method in {"POST","PUT","PATCH","DELETE"}
    - safe if type in {"read","search","list","web_fetch","memory_search"}
    - safe if type == "external_api" AND method == "GET"
    Returns "sensitive", "safe", or None if unknown/indeterminate.
    """
    typ = (action.get("type") or "").strip()
    method = (action.get("method") or "").strip().upper()
    sensitive_types = {"delete", "install", "system_config", "send_message"}
    safe_types = {"read", "search", "list", "web_fetch", "memory_search"}

    if typ in sensitive_types:
        return "sensitive"
    if typ in safe_types:
        return "safe"
    if typ == "external_api":
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return "sensitive"
        if method == "GET":
            return "safe"
        # Unknown method -> indeterminate
        return None
    # Unknown type -> indeterminate
    return None

def ci_contains(text, needle):
    return needle.lower() in (text or "").lower()

def count_tc_lines(text):
    if text is None:
        return 0
    return sum(1 for l in text.splitlines() if re.match(r'^\s*TC\d+', l))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_auth_gate_policy": False,
        "has_classification_csv": False,
        "has_gate_wrapper_py": False,
        "has_test_plan_md": False,
        "classification_complete": False,
        "classification_labels_valid": False,
        "classification_correct": False,
        "policy_sections_present": False,
        "policy_bilingual_refusal_present": False,
        "wrapper_has_functions": False,
        "wrapper_has_status_url": False,
        "wrapper_has_hasSession_key": False,
        "wrapper_has_bilingual_messages": False,
        "wrapper_refs_manifest": False,
        "wrapper_simulates_execution": False,
        "test_plan_tc_count_ok": False,
        "test_plan_has_unauthenticated": False,
        "test_plan_has_authenticated": False,
        "test_plan_has_session": False,
        "test_plan_has_rate": False,
        "test_plan_has_passkey": False,
        "test_plan_has_audit": False,
    }

    # Paths
    manifest_path = os.path.join(input_dir, "ops_manifest.json")
    policy_path = os.path.join(output_dir, "auth_gate_policy.md")
    csv_path = os.path.join(output_dir, "classification.csv")
    wrapper_path = os.path.join(output_dir, "gate_wrapper.py")
    test_plan_path = os.path.join(output_dir, "test_plan.md")

    # Presence checks
    policy_text = read_text(policy_path)
    csv_text = read_text(csv_path)
    wrapper_text = read_text(wrapper_path)
    test_plan_text = read_text(test_plan_path)

    checks["has_auth_gate_policy"] = policy_text is not None
    checks["has_classification_csv"] = csv_text is not None
    checks["has_gate_wrapper_py"] = wrapper_text is not None
    checks["has_test_plan_md"] = test_plan_text is not None

    # Classification checks (depend on CSV and manifest)
    manifest = load_json(manifest_path)
    csv_rows = parse_csv_simple(csv_text) if csv_text is not None else []

    if manifest is not None and csv_rows:
        # Build sets/maps
        manifest_ids = []
        expected_map = {}
        for a in manifest:
            aid = a.get("action_id")
            if not isinstance(aid, str):
                # Ensure IDs as strings for consistent matching
                aid = str(aid) if aid is not None else None
            if aid is None:
                continue
            manifest_ids.append(aid)
            expected_map[aid] = expected_label_for_action(a)

        csv_ids = [r[0] for r in csv_rows]
        csv_labels = {r[0]: (r[1] or "").strip().lower() for r in csv_rows}

        # classification_complete: every manifest id appears exactly once, and no extras
        manifest_set = set(manifest_ids)
        csv_set = set(csv_ids)
        # Check duplicate entries in CSV
        duplicates = len(csv_ids) != len(set(csv_ids))
        checks["classification_complete"] = (csv_set == manifest_set) and (not duplicates)

        # classification_labels_valid: labels only sensitive/safe for all rows
        valid_labels = {"sensitive", "safe"}
        checks["classification_labels_valid"] = all(lbl in valid_labels for lbl in csv_labels.values()) and len(csv_labels) == len(csv_ids)

        # classification_correct: each csv label matches expected_map per rules exactly
        all_match = True
        for aid in manifest_ids:
            exp = expected_map.get(aid, None)
            lbl = csv_labels.get(aid, None)
            # Must have label and expected determinate
            if lbl is None or exp is None or lbl != exp:
                all_match = False
                break
        checks["classification_correct"] = all_match

    # Policy content checks
    if policy_text is not None:
        has_sensitive_phrase = ci_contains(policy_text, "Sensitive actions")
        has_safe_phrase = ci_contains(policy_text, "Safe actions")
        checks["policy_sections_present"] = has_sensitive_phrase and has_safe_phrase

        # Bilingual refusal messages: exact phrases anywhere (case-sensitive for Portuguese accents; English can be case-insensitive)
        has_en_refusal = ci_contains(policy_text, "Authentication required")
        has_pt_refusal = "Autenticação necessária" in policy_text
        checks["policy_bilingual_refusal_present"] = has_en_refusal and has_pt_refusal

    # Wrapper implementation checks
    if wrapper_text is not None:
        # Functions existence
        has_check_auth = re.search(r'\bdef\s+check_auth\b', wrapper_text) is not None
        has_perform_action = re.search(r'\bdef\s+perform_action\b', wrapper_text) is not None
        checks["wrapper_has_functions"] = has_check_auth and has_perform_action

        # Status URL and host
        has_status_path = "/status" in wrapper_text
        has_host = "127.0.0.1:8456" in wrapper_text
        checks["wrapper_has_status_url"] = has_status_path and has_host

        # hasSession key
        checks["wrapper_has_hasSession_key"] = "hasSession" in wrapper_text

        # Bilingual messages
        has_en_msg = "Authentication required" in wrapper_text
        has_pt_msg = "Autenticação necessária" in wrapper_text
        checks["wrapper_has_bilingual_messages"] = has_en_msg and has_pt_msg

        # Manifest reference
        checks["wrapper_refs_manifest"] = "input/ops_manifest.json" in wrapper_text

        # Non-destructive simulation evidence
        checks["wrapper_simulates_execution"] = "EXECUTED" in wrapper_text

    # Test plan coverage checks
    if test_plan_text is not None:
        tc_count = count_tc_lines(test_plan_text)
        checks["test_plan_tc_count_ok"] = 5 <= tc_count <= 8

        # Keywords
        t_lower = test_plan_text.lower()
        checks["test_plan_has_unauthenticated"] = ("unauthenticated" in t_lower) or ("not authenticated" in t_lower)
        checks["test_plan_has_authenticated"] = "authenticated" in t_lower
        checks["test_plan_has_session"] = "session" in t_lower  # for expiry handling
        checks["test_plan_has_rate"] = "rate" in t_lower        # for rate limiting
        checks["test_plan_has_passkey"] = "passkey" in t_lower
        checks["test_plan_has_audit"] = "audit" in t_lower

    # Compute reward: fraction of passed checks; baseline 0.0 if no outputs
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if any([checks["has_auth_gate_policy"], checks["has_classification_csv"], checks["has_gate_wrapper_py"], checks["has_test_plan_md"]]) else 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()