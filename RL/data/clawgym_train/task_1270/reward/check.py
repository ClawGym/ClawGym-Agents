import json
import os
import re
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_lower_hex_64(s):
    return isinstance(s, str) and re.fullmatch(r"[0-9a-f]{64}", s) is not None

def get_status_value(v):
    # Accept either a string or an object with "status"
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        # look for "status" key, case-insensitive
        for k in v.keys():
            if k.lower() == "status":
                val = v[k]
                if isinstance(val, str):
                    return val
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "passport_exists": False,
        "passport_identity_valid": False,
        "passport_pubkey_valid": False,
        "passport_attested_true": False,
        "passport_values_floor_complete": False,

        "delegation_exists": False,
        "delegation_valid": False,
        "delegation_notes_ok": False,

        "receipts_exists": False,
        "receipts_types_ok": False,
        "receipts_fields_ok": False,
        "receipts_signed_by_orchestrator": False,

        "merkle_exists": False,
        "merkle_valid": False,

        "audit_exists": False,
        "audit_valid": False,

        "announcement_exists": False,
        "announcement_valid": False,

        "retrospective_exists": False,
    }

    # Paths
    passport_path = os.path.join(output_dir, "passport", "agent.json")
    delegation_path = os.path.join(output_dir, "delegations", "delegation.json")
    delegation_notes_path = os.path.join(output_dir, "delegations", "notes.txt")
    receipts_path = os.path.join(output_dir, "receipts", "work_receipts.json")
    merkle_path = os.path.join(output_dir, "proofs", "merkle.json")
    audit_report_path = os.path.join(output_dir, "audit", "audit_report.json")
    retrospective_path = os.path.join(output_dir, "audit", "retrospective.md")
    announcement_path = os.path.join(output_dir, "agora", "announcement.json")

    # Inputs used for validation (do not award credit solely for reading)
    collaborator_passport_path = os.path.join(input_dir, "collaborator_passport.json")

    # Load artifacts
    passport = load_json_file(passport_path)
    if isinstance(passport, dict):
        checks["passport_exists"] = True

    passport_pubkey = None
    if checks["passport_exists"]:
        name_ok = passport.get("name") == "orchestrator"
        owner_ok = passport.get("owner") == "alex"
        if name_ok and owner_ok:
            checks["passport_identity_valid"] = True

        pk = passport.get("publicKey")
        if is_lower_hex_64(pk):
            checks["passport_pubkey_valid"] = True
            passport_pubkey = pk

        if passport.get("attested") is True:
            checks["passport_attested_true"] = True

        # values_floor: either dict with keys F-001..F-007, or list of objects with code fields
        vf = passport.get("values_floor")
        needed_codes = {f"F-00{i}" for i in range(1, 8)}
        vf_ok = False
        if isinstance(vf, dict):
            # keys may include extra, require at least those seven
            keys = set(k for k in vf.keys())
            if needed_codes.issubset(keys):
                vf_ok = True
        elif isinstance(vf, list):
            codes = set()
            for item in vf:
                if isinstance(item, dict):
                    code = item.get("code")
                    if isinstance(code, str):
                        codes.add(code)
            if needed_codes.issubset(codes):
                vf_ok = True
        if vf_ok:
            checks["passport_values_floor_complete"] = True

    # Delegation validation
    delegation = load_json_file(delegation_path)
    if isinstance(delegation, dict):
        checks["delegation_exists"] = True

    collaborator = load_json_file(collaborator_passport_path)
    collaborator_pk = None
    collaborator_ok = False
    if isinstance(collaborator, dict):
        c_pk = collaborator.get("publicKey")
        c_attested = collaborator.get("attested")
        if isinstance(c_pk, str) and is_lower_hex_64(c_pk) and (c_attested is True or c_attested == True):
            collaborator_pk = c_pk
            collaborator_ok = True

    if checks["delegation_exists"] and collaborator_ok:
        # to matches collaborator public key exactly
        to_ok = delegation.get("to") == collaborator_pk

        # scope exactly ["code_execution"]
        scope = delegation.get("scope")
        scope_ok = isinstance(scope, list) and len(scope) == 1 and scope[0] == "code_execution"

        # limit <= 300
        limit = delegation.get("limit")
        limit_ok = (isinstance(limit, (int, float))) and (limit <= 300)

        # depth == 1
        depth = delegation.get("depth")
        depth_ok = (isinstance(depth, (int, float))) and (int(depth) == 1)

        # hours <= 24
        hours = delegation.get("hours")
        hours_ok = (isinstance(hours, (int, float))) and (hours <= 24)

        if to_ok and scope_ok and limit_ok and depth_ok and hours_ok:
            checks["delegation_valid"] = True

    # Delegation notes
    notes_txt = load_text_file(delegation_notes_path)
    if isinstance(notes_txt, str):
        # length >= 200 and contains 'revocation' or 'revoke' (case-insensitive)
        if len(notes_txt) >= 200:
            lower = notes_txt.lower()
            if ("revocation" in lower) or ("revoke" in lower):
                checks["delegation_notes_ok"] = True

    # Receipts
    receipts = load_json_file(receipts_path)
    if isinstance(receipts, list):
        checks["receipts_exists"] = True

    receipts_len = 0
    if checks["receipts_exists"]:
        receipts_len = len(receipts)
        types = [r.get("type") for r in receipts if isinstance(r, dict)]
        has_planning = any(t == "planning" for t in types)
        has_review = any(t == "review" for t in types)
        if receipts_len >= 2 and has_planning and has_review:
            checks["receipts_types_ok"] = True

        # Every receipt has scope == "coordination", result == "success", summary non-empty string
        fields_ok = True
        for r in receipts:
            if not isinstance(r, dict):
                fields_ok = False
                break
            if r.get("scope") != "coordination":
                fields_ok = False
                break
            if r.get("result") != "success":
                fields_ok = False
                break
            summary = r.get("summary")
            if not (isinstance(summary, str) and len(summary.strip()) > 0):
                fields_ok = False
                break
        if fields_ok:
            checks["receipts_fields_ok"] = True

        # signedBy matches passport publicKey
        if passport_pubkey is not None:
            signed_ok = True
            for r in receipts:
                if not isinstance(r, dict) or r.get("signedBy") != passport_pubkey:
                    signed_ok = False
                    break
            if signed_ok:
                checks["receipts_signed_by_orchestrator"] = True

    # Merkle proof
    merkle = load_json_file(merkle_path)
    if isinstance(merkle, dict):
        checks["merkle_exists"] = True

    if checks["merkle_exists"] and checks["receipts_exists"]:
        algo_ok = merkle.get("algorithm") == "sha256"
        root_ok = is_lower_hex_64(merkle.get("root"))
        receipts_count = merkle.get("receipts")
        receipts_count_ok = isinstance(receipts_count, int) and receipts_count == receipts_len
        leaves_ok = True
        if "leaves" in merkle:
            leaves = merkle.get("leaves")
            if not (isinstance(leaves, list) and len(leaves) == receipts_len):
                leaves_ok = False
        if algo_ok and root_ok and receipts_count_ok and leaves_ok:
            checks["merkle_valid"] = True

    # Audit report
    audit = load_json_file(audit_report_path)
    if isinstance(audit, dict):
        checks["audit_exists"] = True

    if checks["audit_exists"]:
        codes = [f"F-00{i}" for i in range(1, 8)]
        present_all = all(code in audit for code in codes)
        if present_all:
            statuses_ok = True
            # F-001..F-005 -> pass
            for i in range(1, 6):
                code = f"F-00{i}"
                status = get_status_value(audit.get(code))
                if not (isinstance(status, str) and status.lower() == "pass"):
                    statuses_ok = False
                    break
            # F-006..F-007 -> pass or consideration
            if statuses_ok:
                for i in range(6, 8):
                    code = f"F-00{i}"
                    status = get_status_value(audit.get(code))
                    if not (isinstance(status, str) and status.lower() in {"pass", "consideration"}):
                        statuses_ok = False
                        break
            if statuses_ok:
                checks["audit_valid"] = True

    # Announcement
    announcement = load_json_file(announcement_path)
    if isinstance(announcement, dict):
        checks["announcement_exists"] = True

    if checks["announcement_exists"] and passport_pubkey is not None:
        topic_ok = announcement.get("topic") == "sprint-complete"
        signer_ok = announcement.get("signer") == passport_pubkey
        message = announcement.get("message")
        message_ok = isinstance(message, str) and len(message) >= 40
        if topic_ok and signer_ok and message_ok:
            checks["announcement_valid"] = True

    # Retrospective
    retro = load_text_file(retrospective_path)
    if isinstance(retro, str):
        lower = retro.lower()
        if len(retro) >= 300 and ("non-deception".lower() in lower) and ("proportionality".lower() in lower):
            checks["retrospective_exists"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure 0.0 on no-op baseline (no relevant output artifacts)
    # If nothing under output exists or all artifact-dependent checks are false, reward is already 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()