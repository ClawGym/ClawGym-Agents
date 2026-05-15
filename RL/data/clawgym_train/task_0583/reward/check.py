import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_sha256_prefixed(s):
    if not isinstance(s, str):
        return False
    return bool(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", s))

def ensure_expected_sha256(raw):
    # Accept either plain 64-hex or already prefixed "sha256:<hex>"
    if isinstance(raw, str):
        if re.fullmatch(r"[0-9a-fA-F]{64}", raw or ""):
            return "sha256:" + raw.lower()
        if is_sha256_prefixed(raw):
            return "sha256:" + raw.split(":", 1)[1].lower()
    return None

def get_int(val):
    return val if isinstance(val, int) else None

def contains_digit(s):
    return any(ch.isdigit() for ch in s) if isinstance(s, str) else False

def find_log_index_near_id(md_lines, expr_id, expected_log_index):
    """
    Look for a line that contains the expression id, and in that line or up to the next 2 lines,
    find a 'log index' label and an integer. If expected_log_index is provided (int), ensure it matches.
    """
    pattern = re.compile(r"log[_\s]*index", re.IGNORECASE)
    for i, line in enumerate(md_lines):
        if expr_id in line:
            # Check this line and next two lines
            for j in range(i, min(i + 3, len(md_lines))):
                if pattern.search(md_lines[j]):
                    # Extract integer near label
                    m = re.search(r"log[_\s]*index[^0-9]*([0-9]+)", md_lines[j], flags=re.IGNORECASE)
                    if m:
                        val = int(m.group(1))
                        if expected_log_index is None or val == expected_log_index:
                            return True
    return False

def text_contains_case_insensitive(text, substr):
    return substr.lower() in text.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks as False
    checks = {
        # Signature JSON checks
        "signature_exists": False,
        "signature_type_and_claim_fields_valid": False,
        "signature_subject_matches_input": False,
        "signature_hash_format_and_matches_input": False,
        "signature_expression_id_present": False,
        "signature_timestamp_present": False,
        "signature_log_index_int": False,

        # Attestation JSON checks
        "attestation_exists": False,
        "attestation_type_and_claim_fields_valid": False,
        "attestation_subject_matches_signature": False,
        "attestation_predicate_non_empty": False,
        "attestation_object_has_digit": False,
        "attestation_evidence_refs_include_signature_id": False,
        "attestation_expression_id_present": False,
        "attestation_timestamp_present": False,
        "attestation_log_index_gt_signature": False,

        # Transfer JSON checks
        "transfer_exists": False,
        "transfer_structure_valid": False,
        "transfer_visibility_public": False,
        "transfer_to_non_empty": False,
        "transfer_expression_refs_match_both_ids": False,
        "transfer_timestamp_present": False,
        "transfer_log_index_gt_attestation": False,

        # Cross-artifact consistency
        "log_indices_strictly_increasing": False,

        # Audit summary checks
        "audit_summary_exists": False,
        "audit_has_required_sections": False,
        "audit_mentions_rotation": False,
        "audit_lists_ids_in_order_and_log_indices_labeled": False,
        "audit_includes_subject_and_hash": False,
        "audit_includes_all_timestamps": False,
        "audit_includes_transfer_log_index_labeled": False,
    }

    # Load inputs (reference only)
    plugin_ok, plugin_data = read_json(os.path.join(input_dir, "plugin.json"))
    test_ok, test_data = read_json(os.path.join(input_dir, "test_results.json"))
    recipient_ok, recipient_data = read_json(os.path.join(input_dir, "recipient.json"))

    expected_subject = None
    expected_hash = None
    if plugin_ok and isinstance(plugin_data, dict):
        name = plugin_data.get("name")
        version = plugin_data.get("version")
        sha_raw = plugin_data.get("sha256") or plugin_data.get("sha") or plugin_data.get("hash")
        if isinstance(name, str) and isinstance(version, str):
            expected_subject = f"plugin:{name}-{version}"
        expected_hash = ensure_expected_sha256(sha_raw)

    # Load outputs
    sig_path = os.path.join(output_dir, "plugin_signature.json")
    att_path = os.path.join(output_dir, "behavior_attestation.json")
    tr_path = os.path.join(output_dir, "transfer_receipt.json")
    md_path = os.path.join(output_dir, "audit_summary.md")

    sig_ok, sig = read_json(sig_path)
    if sig_ok and isinstance(sig, dict):
        checks["signature_exists"] = True
        # Validate structure
        expr_type = sig.get("expression_type")
        payload = sig.get("payload")
        claim_type_ok = isinstance(payload, dict) and payload.get("claim_type") == "artifact/signature"
        subject = payload.get("subject") if isinstance(payload, dict) else None
        predicate = payload.get("predicate") if isinstance(payload, dict) else None
        obj = payload.get("object") if isinstance(payload, dict) else None

        if expr_type == "claim" and claim_type_ok and isinstance(subject, str) and predicate == "signed" and isinstance(obj, str) and is_sha256_prefixed(obj):
            checks["signature_type_and_claim_fields_valid"] = True

        # Subject match input
        if expected_subject and isinstance(subject, str) and subject == expected_subject:
            checks["signature_subject_matches_input"] = True

        # Hash match input
        if expected_hash and isinstance(obj, str) and obj.lower() == expected_hash:
            checks["signature_hash_format_and_matches_input"] = True

        # expression_id
        sig_expr_id = sig.get("expression_id")
        if isinstance(sig_expr_id, str) and sig_expr_id.strip():
            checks["signature_expression_id_present"] = True
        else:
            sig_expr_id = None

        # timestamp
        sig_ts = sig.get("timestamp")
        if isinstance(sig_ts, str) and sig_ts.strip():
            checks["signature_timestamp_present"] = True
        else:
            sig_ts = None

        # log_index
        sig_log_index = get_int(sig.get("log_index"))
        if sig_log_index is not None:
            checks["signature_log_index_int"] = True
        else:
            sig_log_index = None
    else:
        sig = {}
        sig_expr_id = None
        sig_ts = None
        sig_log_index = None
        subject = None
        obj = None

    att_ok, att = read_json(att_path)
    if att_ok and isinstance(att, dict):
        checks["attestation_exists"] = True
        a_expr_type = att.get("expression_type")
        a_payload = att.get("payload")
        a_claim_type_ok = isinstance(a_payload, dict) and a_payload.get("claim_type") == "behavior/report"
        a_subject = a_payload.get("subject") if isinstance(a_payload, dict) else None
        a_predicate = a_payload.get("predicate") if isinstance(a_payload, dict) else None
        a_object = a_payload.get("object") if isinstance(a_payload, dict) else None
        a_evidence_refs = a_payload.get("evidence_refs") if isinstance(a_payload, dict) else None

        if a_expr_type == "claim" and a_claim_type_ok and isinstance(a_subject, str):
            checks["attestation_type_and_claim_fields_valid"] = True

        if isinstance(a_predicate, str) and a_predicate.strip():
            checks["attestation_predicate_non_empty"] = True

        if isinstance(a_object, str) and contains_digit(a_object):
            checks["attestation_object_has_digit"] = True

        # subject matches signature subject
        if isinstance(a_subject, str) and isinstance(subject, str) and a_subject == subject:
            checks["attestation_subject_matches_signature"] = True

        # evidence refs includes sig id
        if isinstance(a_evidence_refs, list) and sig_expr_id and any(ref == sig_expr_id for ref in a_evidence_refs):
            checks["attestation_evidence_refs_include_signature_id"] = True

        # expression_id
        att_expr_id = att.get("expression_id")
        if isinstance(att_expr_id, str) and att_expr_id.strip():
            checks["attestation_expression_id_present"] = True
        else:
            att_expr_id = None

        # timestamp
        att_ts = att.get("timestamp")
        if isinstance(att_ts, str) and att_ts.strip():
            checks["attestation_timestamp_present"] = True
        else:
            att_ts = None

        # log_index > signature
        att_log_index = get_int(att.get("log_index"))
        if att_log_index is not None and isinstance(sig_log_index, int) and att_log_index > sig_log_index:
            checks["attestation_log_index_gt_signature"] = True
        else:
            # Ensure defined for later
            att_log_index = att_log_index if isinstance(att_log_index, int) else None
    else:
        att = {}
        att_expr_id = None
        att_ts = None
        att_log_index = None
        a_subject = None

    tr_ok, tr = read_json(tr_path)
    if tr_ok and isinstance(tr, dict):
        checks["transfer_exists"] = True
        tr_to = tr.get("to")
        tr_visibility = tr.get("visibility")
        tr_payload = tr.get("payload")

        # Structure: payload.type == "task_handoff", payload.expression_refs includes exactly the two ids
        structure_valid = (
            isinstance(tr_payload, dict) and
            tr_payload.get("type") == "task_handoff" and
            isinstance(tr_payload.get("expression_refs"), list)
        )
        if structure_valid:
            checks["transfer_structure_valid"] = True

        if isinstance(tr_visibility, str) and tr_visibility.lower() == "public":
            checks["transfer_visibility_public"] = True

        if isinstance(tr_to, str) and tr_to.strip():
            checks["transfer_to_non_empty"] = True

        # expression_refs exact two and equal to {sig_expr_id, att_expr_id}
        tr_expr_refs = tr_payload.get("expression_refs") if isinstance(tr_payload, dict) else None
        if isinstance(tr_expr_refs, list) and sig_expr_id and att_expr_id:
            ref_set = set([x for x in tr_expr_refs if isinstance(x, str)])
            target_set = set([sig_expr_id, att_expr_id])
            if len(tr_expr_refs) == 2 and ref_set == target_set:
                checks["transfer_expression_refs_match_both_ids"] = True

        tr_ts = tr.get("timestamp")
        if isinstance(tr_ts, str) and tr_ts.strip():
            checks["transfer_timestamp_present"] = True
        else:
            tr_ts = None

        tr_log_index = get_int(tr.get("log_index"))
        if tr_log_index is not None and isinstance(att_log_index, int) and tr_log_index > att_log_index:
            checks["transfer_log_index_gt_attestation"] = True
        else:
            tr_log_index = tr_log_index if isinstance(tr_log_index, int) else None
    else:
        tr = {}
        tr_ts = None
        tr_log_index = None

    # Cross: strictly increasing log indices if all are ints
    if isinstance(sig_log_index, int) and isinstance(att_log_index, int) and isinstance(tr_log_index, int):
        if sig_log_index < att_log_index < tr_log_index:
            checks["log_indices_strictly_increasing"] = True

    # Audit summary checks
    if os.path.isfile(md_path):
        checks["audit_summary_exists"] = True
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md_text = f.read()
        except Exception:
            md_text = ""
        md_lines = md_text.splitlines()

        # Required sections (case-insensitive): "Authorship", "Integrity", "Ordering", "Transfer authenticity"
        sections_ok = all(
            text_contains_case_insensitive(md_text, title)
            for title in ["Authorship", "Integrity", "Ordering", "Transfer authenticity"]
        )
        if sections_ok:
            checks["audit_has_required_sections"] = True

        # Mentions "rotation"
        if text_contains_case_insensitive(md_text, "rotation"):
            checks["audit_mentions_rotation"] = True

        # Includes subject and hash from signature
        if isinstance(subject, str) and isinstance(obj, str):
            if (subject in md_text) and (obj in md_text):
                checks["audit_includes_subject_and_hash"] = True

        # Lists the two expression_ids (signature and attestation) in ascending order, and includes labeled log indices
        ids_in_order = False
        labeled_ok = False
        if isinstance(sig_expr_id, str) and isinstance(att_expr_id, str):
            pos_sig = md_text.find(sig_expr_id)
            pos_att = md_text.find(att_expr_id)
            if pos_sig != -1 and pos_att != -1 and pos_sig < pos_att:
                ids_in_order = True

            # Check that each id has a nearby labeled log index matching the numeric values
            labeled_sig = find_log_index_near_id(md_lines, sig_expr_id, sig_log_index if isinstance(sig_log_index, int) else None)
            labeled_att = find_log_index_near_id(md_lines, att_expr_id, att_log_index if isinstance(att_log_index, int) else None)
            labeled_ok = labeled_sig and labeled_att

        if ids_in_order and labeled_ok:
            checks["audit_lists_ids_in_order_and_log_indices_labeled"] = True

        # Includes all timestamps
        ts_ok = True
        for ts in [sig_ts, att_ts, tr_ts]:
            if isinstance(ts, str):
                if ts not in md_text:
                    ts_ok = False
            else:
                ts_ok = False
        if ts_ok:
            checks["audit_includes_all_timestamps"] = True

        # Includes transfer log index labeled in markdown
        if isinstance(tr_log_index, int):
            # Search for a line with 'log index' and the transfer log index number
            tr_log_found = any(re.search(r"log[_\s]*index[^0-9]*" + re.escape(str(tr_log_index)), line, flags=re.IGNORECASE) for line in md_lines)
            if tr_log_found:
                checks["audit_includes_transfer_log_index_labeled"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no outputs at all, force reward to 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If the three main JSON outputs are all missing, force reward 0
        essential = ["signature_exists", "attestation_exists", "transfer_exists"]
        if not any(checks.get(k, False) for k in essential):
            reward = 0.0

    # Print final JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()