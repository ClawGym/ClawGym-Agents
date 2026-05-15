import json
import os
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_jsonl(path):
    objects = []
    errors = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for idx, raw in enumerate(f):
                line = raw.strip()
                if line == "":
                    # Treat empty lines as present but invalid for "each object must include keys"
                    errors.append(f"Line {idx+1} is empty")
                    continue
                try:
                    obj = json.loads(line)
                    objects.append((idx + 1, obj))
                except Exception as e:
                    errors.append(f"Line {idx+1} parse error: {e}")
    except Exception as e:
        return None, [str(e)]
    return objects, errors

def is_non_empty_string(v):
    return isinstance(v, str) and len(v.strip()) > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "expressions_file_exists": False,
        "expressions_min_two_lines": False,
        "expressions_lines_valid": False,
        "signature_claim_correct": False,
        "behavior_claim_correct": False,
        "transfer_file_exists": False,
        "transfer_valid_json": False,
        "transfer_to_matches": False,
        "transfer_visibility_public": False,
        "transfer_payload_type_correct": False,
        "transfer_expression_refs_match": False,
        "transfer_context_correct": False,
        "identity_file_exists": False,
        "identity_valid_json": False,
        "identity_has_address_and_public_key": False,
        "readme_exists": False,
        "readme_nonempty": False,
        "readme_required_terms": False,
        "readme_mentions_expression_ids": False,
    }

    # Prepare expected values from inputs where needed
    plugin_manifest_path = os.path.join(input_dir, "plugin_manifest.json")
    usage_report_path = os.path.join(input_dir, "usage_report.json")
    handoff_to_path = os.path.join(input_dir, "handoff_to.txt")

    expected_subject = None
    expected_object = None
    expected_to = None

    plugin_manifest, _ = read_json(plugin_manifest_path)
    if plugin_manifest and isinstance(plugin_manifest, dict):
        name = plugin_manifest.get("name")
        version = plugin_manifest.get("version")
        sha256 = plugin_manifest.get("sha256")
        if is_non_empty_string(name) and is_non_empty_string(version):
            expected_subject = f"plugin:{name}@{version}"
        if is_non_empty_string(sha256):
            expected_object = f"sha256:{sha256}"

    handoff_to_text, _ = read_text(handoff_to_path)
    if handoff_to_text is not None:
        expected_to = handoff_to_text.strip()

    # 1) Validate expressions.jsonl
    expressions_path = os.path.join(output_dir, "expressions.jsonl")
    signature_expr_id = None
    behavior_expr_id = None
    expressions_ok_per_line = True
    expressions_objects = []

    if os.path.isfile(expressions_path):
        checks["expressions_file_exists"] = True
        parsed, errors = parse_jsonl(expressions_path)
        if parsed is not None:
            # Count non-empty lines
            non_empty_lines_count = sum(1 for _, _ in parsed) + sum(1 for e in errors if "is empty" in e)
            # But requirement is at least two JSON lines; thus based on parsed objects only
            if len(parsed) >= 2:
                checks["expressions_min_two_lines"] = True

            # Validate each parsed line must include required keys and constraints
            for (lineno, obj) in parsed:
                if not isinstance(obj, dict):
                    expressions_ok_per_line = False
                    continue
                # Keys presence
                has_et = "expression_type" in obj
                has_payload = "payload" in obj
                has_id = "expression_id" in obj
                if not (has_et and has_payload and has_id):
                    expressions_ok_per_line = False
                    continue
                # expression_type must equal "claim"
                if obj.get("expression_type") != "claim":
                    expressions_ok_per_line = False
                # payload must be object
                if not isinstance(obj.get("payload"), dict):
                    expressions_ok_per_line = False
                # expression_id must be non-empty string
                if not is_non_empty_string(obj.get("expression_id")):
                    expressions_ok_per_line = False

            # If there were parsing errors (non-empty lines that failed to parse), that violates "Parse each line as JSON"
            # We consider only non-empty lines; errors list may include parse errors and empty-line notices
            parse_errors = [e for e in errors if "parse error" in e.lower()]
            if parse_errors:
                expressions_ok_per_line = False

            checks["expressions_lines_valid"] = expressions_ok_per_line

            # Find required claims
            # Signature claim
            sig_found_ok = False
            beh_found_ok = False
            sig_subject = expected_subject
            sig_object = expected_object
            for _, obj in parsed:
                if not isinstance(obj, dict) or not isinstance(obj.get("payload"), dict):
                    continue
                payload = obj.get("payload", {})
                claim_type = payload.get("claim_type")
                predicate = payload.get("predicate")
                subject = payload.get("subject")
                pobj = payload.get("object")

                # Signature claim check
                if claim_type == "artifact/signature" and predicate == "signed":
                    if expected_subject is not None and expected_object is not None:
                        if subject == expected_subject and pobj == expected_object:
                            sig_found_ok = True
                            signature_expr_id = obj.get("expression_id")
                    else:
                        # If inputs missing, we cannot confirm; keep False
                        pass

            # Behavior claim check
            for _, obj in parsed:
                if not isinstance(obj, dict) or not isinstance(obj.get("payload"), dict):
                    continue
                payload = obj.get("payload", {})
                claim_type = payload.get("claim_type")
                predicate = payload.get("predicate")
                subject = payload.get("subject")
                pobj = payload.get("object")
                evidence_refs = payload.get("evidence_refs")

                if claim_type == "behavior/report" and predicate == "used_successfully":
                    subject_ok = (expected_subject is not None and subject == expected_subject)
                    object_ok = is_non_empty_string(pobj)
                    evidence_ok = isinstance(evidence_refs, list) and len(evidence_refs) > 0
                    if subject_ok and object_ok and evidence_ok:
                        beh_found_ok = True
                        behavior_expr_id = obj.get("expression_id")

            checks["signature_claim_correct"] = sig_found_ok
            checks["behavior_claim_correct"] = beh_found_ok

    # 2) Validate transfer.json
    transfer_path = os.path.join(output_dir, "transfer.json")
    transfer_obj = None
    if os.path.isfile(transfer_path):
        checks["transfer_file_exists"] = True
        transfer_obj, err = read_json(transfer_path)
        if isinstance(transfer_obj, dict):
            checks["transfer_valid_json"] = True

            # to matches
            to_val = transfer_obj.get("to")
            if expected_to is not None and is_non_empty_string(to_val) and to_val == expected_to:
                checks["transfer_to_matches"] = True

            # visibility == "public"
            if transfer_obj.get("visibility") == "public":
                checks["transfer_visibility_public"] = True

            # payload object and type
            payload = transfer_obj.get("payload")
            if isinstance(payload, dict):
                if payload.get("type") == "task_handoff":
                    checks["transfer_payload_type_correct"] = True

                # expression_refs match exactly the two expression IDs from required claims
                expr_refs = payload.get("expression_refs")
                if isinstance(expr_refs, list) and all(is_non_empty_string(x) for x in expr_refs):
                    # Must include exactly the two IDs for signature and behavior claims
                    if signature_expr_id and behavior_expr_id:
                        refs_set = set(expr_refs)
                        expected_set = {signature_expr_id, behavior_expr_id}
                        if len(expr_refs) == 2 and refs_set == expected_set:
                            checks["transfer_expression_refs_match"] = True

                # context
                if payload.get("context") == "release review":
                    checks["transfer_context_correct"] = True

    # 3) Validate identity_summary.json
    identity_path = os.path.join(output_dir, "identity_summary.json")
    if os.path.isfile(identity_path):
        checks["identity_file_exists"] = True
        identity_obj, err = read_json(identity_path)
        if isinstance(identity_obj, dict):
            checks["identity_valid_json"] = True
            addr = identity_obj.get("address")
            pubk = identity_obj.get("public_key")
            if is_non_empty_string(addr) and is_non_empty_string(pubk):
                checks["identity_has_address_and_public_key"] = True

    # 4) Validate README.md
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        content, err = read_text(readme_path)
        if content is not None:
            if len(content.strip()) > 0:
                checks["readme_nonempty"] = True
            low = content.lower()
            # Must contain the words "risk" and "rotation" and either "attestation" or "signed"
            if ("risk" in low) and ("rotation" in low) and ("attestation" in low or "signed" in low):
                checks["readme_required_terms"] = True

            # Must mention the handed off expression_ids (the two IDs)
            if signature_expr_id and behavior_expr_id:
                if (signature_expr_id in content) and (behavior_expr_id in content):
                    checks["readme_mentions_expression_ids"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 when no outputs
    output_exists = os.path.isdir(output_dir) and any(True for _ in os.scandir(output_dir))
    if not output_exists:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()