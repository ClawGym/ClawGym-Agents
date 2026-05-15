import json
import os
import re
import sys

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

def is_lower_hex(s):
    return bool(re.fullmatch(r"[0-9a-f]+", s or ""))

def last_nonempty_line(text):
    if text is None:
        return None
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.rstrip("\n")
    return None

def parse_md_table_for_owner_deadline(md_text):
    """
    Find an Action Items-like table and count rows that have non-empty Owner and a date in Deadline/Due column.
    Accepts headers containing both 'Owner' and either 'Deadline' or 'Due' (case-insensitive).
    """
    if not md_text:
        return (False, 0)
    lines = md_text.splitlines()
    found_header = False
    owner_idx = None
    deadline_idx = None
    data_rows = 0
    valid_rows_with_owner_and_date = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "|" in line:
            # Potential header row
            # Skip if looks like separator row
            if re.match(r"^\s*\|?\s*-[-\s|:]+\|?\s*$", line):
                i += 1
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            # detect header containing Owner and Deadline/Due
            lower_cols = [c.lower() for c in cols]
            if ("owner" in lower_cols) and (("deadline" in lower_cols) or ("due" in lower_cols)):
                owner_idx = lower_cols.index("owner")
                if "deadline" in lower_cols:
                    deadline_idx = lower_cols.index("deadline")
                else:
                    deadline_idx = lower_cols.index("due")
                # Next line should be separator (optional), then data rows
                # Move to next lines to count data
                # Look ahead: skip one separator row if present
                j = i + 1
                if j < len(lines) and re.match(r"^\s*\|?\s*:?-?-+[:\-\s|]+\|?\s*$", lines[j].strip()):
                    j += 1
                found_header = True
                # Count data rows until a non-table line
                while j < len(lines):
                    l = lines[j].strip()
                    if "|" not in l:
                        break
                    if re.match(r"^\s*\|?\s*-[-\s|:]+\|?\s*$", l):
                        j += 1
                        continue
                    row_cols = [c.strip() for c in l.strip("|").split("|")]
                    # Ensure the row has enough columns
                    if max(owner_idx, deadline_idx) < len(row_cols):
                        data_rows += 1
                        owner_val = row_cols[owner_idx]
                        deadline_val = row_cols[deadline_idx]
                        has_owner = bool(owner_val and owner_val.lower() != "owner")
                        has_date = bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", deadline_val))
                        if has_owner and has_date:
                            valid_rows_with_owner_and_date += 1
                    else:
                        # not enough columns; treat as end of table
                        break
                    j += 1
                break
        i += 1
    return (found_header and data_rows > 0, valid_rows_with_owner_and_date)

def extract_signed_by_fingerprint(md_text):
    line = last_nonempty_line(md_text or "")
    if not line:
        return None, False
    m = re.match(r"^\s*Signed-By:\s*(\S{16})\s*$", line)
    if not m:
        return None, False
    return m.group(1), True

def is_iso_date(date_str):
    if not isinstance(date_str, str):
        return False
    # Accept YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}Z", date_str):
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) summary.md checks
        "summary_exists": False,
        "summary_has_header": False,
        "summary_has_key_decisions": False,
        "summary_has_action_items_table": False,
        "summary_has_effectiveness_score": False,
        "summary_has_two_action_items_complete": False,
        "summary_signed_by_line_at_end": False,

        # 2) plan.json checks
        "plan_valid_json": False,
        "plan_has_keys_and_lengths": False,
        "plan_steps_valid": False,
        "plan_safety_valid": False,

        # 3) memory.md checks
        "memory_exists": False,
        "memory_line_count_leq_50": False,
        "memory_has_both_headings": False,
        "memory_mentions_deadline": False,

        # 4) corrections.md checks
        "corrections_exists": False,
        "corrections_has_date_and_keyword": False,

        # 5) experiments.md checks
        "experiments_exists": False,
        "experiments_has_baseline": False,
        "experiments_has_magi_and_status": False,

        # 6) identity and signature checks
        "identity_valid_json": False,
        "identity_fields_valid": False,
        "signature_valid_json": False,
        "signature_fields_valid": False,
        "summary_signed_by_matches_identity": False,
    }

    # Paths
    summary_path = os.path.join(output_dir, "summary.md")
    plan_path = os.path.join(output_dir, "plan.json")
    memory_path = os.path.join(output_dir, "memory.md")
    corrections_path = os.path.join(output_dir, "corrections.md")
    experiments_path = os.path.join(output_dir, "experiments.md")
    identity_path = os.path.join(output_dir, "identity.json")
    signature_path = os.path.join(output_dir, "signature.json")

    # 1) summary.md
    summary_text = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary_text = read_text(summary_path) or ""
        # header
        if re.search(r"^\s*#\s*Meeting Summary:", summary_text, re.IGNORECASE | re.MULTILINE):
            checks["summary_has_header"] = True
        # Key Decisions section
        if re.search(r"^\s*##\s*Key Decisions\s*$", summary_text, re.IGNORECASE | re.MULTILINE):
            checks["summary_has_key_decisions"] = True
        # Action Items table and count of valid rows
        has_table, rows_with_owner_and_date = parse_md_table_for_owner_deadline(summary_text)
        if has_table:
            checks["summary_has_action_items_table"] = True
        if rows_with_owner_and_date >= 2:
            checks["summary_has_two_action_items_complete"] = True
        # Effectiveness Score line
        if re.search(r"Effectiveness Score:\s*\[?\s*\d+(\.\d+)?\s*/\s*10\s*\]?", summary_text, re.IGNORECASE):
            checks["summary_has_effectiveness_score"] = True
        # Signed-By at end
        signed_fp, signed_line_ok = extract_signed_by_fingerprint(summary_text)
        if signed_line_ok:
            checks["summary_signed_by_line_at_end"] = True
    # 2) plan.json
    plan_obj = load_json(plan_path)
    if plan_obj is not None:
        checks["plan_valid_json"] = True
        if isinstance(plan_obj, dict) and "steps" in plan_obj and "safety" in plan_obj and isinstance(plan_obj.get("steps"), list) and isinstance(plan_obj.get("safety"), dict):
            steps = plan_obj["steps"]
            safety = plan_obj["safety"]
            if 3 <= len(steps) <= 5:
                checks["plan_has_keys_and_lengths"] = True
            # steps validation
            steps_valid = True
            for step in steps:
                if not isinstance(step, dict):
                    steps_valid = False
                    break
                name = step.get("name")
                mode = step.get("mode")
                if not isinstance(name, str) or not name.strip():
                    steps_valid = False
                    break
                if mode not in ("sequential", "parallel"):
                    steps_valid = False
                    break
            if steps_valid:
                checks["plan_steps_valid"] = True
            # safety validation
            max_sub = safety.get("max_subagents")
            loop_prev = safety.get("loop_prevention")
            max_ok = isinstance(max_sub, (int, float)) and max_sub <= 5
            loop_ok = isinstance(loop_prev, bool) and loop_prev is True
            if max_ok and loop_ok:
                checks["plan_safety_valid"] = True

    # 3) memory.md
    memory_text = None
    if os.path.isfile(memory_path):
        checks["memory_exists"] = True
        memory_text = read_text(memory_path) or ""
        # line count <= 50
        lines = memory_text.splitlines()
        if len(lines) <= 50:
            checks["memory_line_count_leq_50"] = True
        # headings
        has_rules = re.search(r"^\s*##\s*Rules \(verified,\s*kept\)\s*$", memory_text, re.IGNORECASE | re.MULTILINE) is not None
        has_applied = re.search(r"^\s*##\s*Applied \(awaiting measurement\)\s*$", memory_text, re.IGNORECASE | re.MULTILINE) is not None
        if has_rules and has_applied:
            checks["memory_has_both_headings"] = True
        # mentions deadline in either section
        # find ranges of sections
        deadline_found = False
        if has_rules and has_applied:
            # find indices
            idx_rules = None
            idx_applied = None
            for idx, l in enumerate(lines):
                if re.match(r"^\s*##\s*Rules \(verified,\s*kept\)\s*$", l, re.IGNORECASE):
                    idx_rules = idx
                if re.match(r"^\s*##\s*Applied \(awaiting measurement\)\s*$", l, re.IGNORECASE):
                    idx_applied = idx
            if idx_rules is not None and idx_applied is not None:
                # search within Rules section
                for l in lines[idx_rules+1: idx_applied]:
                    if re.search(r"deadline", l, re.IGNORECASE):
                        deadline_found = True
                        break
                # search within Applied section
                if not deadline_found:
                    for l in lines[idx_applied+1:]:
                        if re.search(r"deadline", l, re.IGNORECASE):
                            deadline_found = True
                            break
        else:
            # fallback: anywhere
            if re.search(r"deadline", memory_text or "", re.IGNORECASE):
                deadline_found = True
        if deadline_found:
            checks["memory_mentions_deadline"] = True

    # 4) corrections.md
    if os.path.isfile(corrections_path):
        checks["corrections_exists"] = True
        corr_text = read_text(corrections_path) or ""
        found_line = False
        for l in corr_text.splitlines():
            if re.search(r"^\s*\d{4}-\d{2}-\d{2}\s*\|", l) and re.search(r"(deadline|effectiveness)", l, re.IGNORECASE):
                found_line = True
                break
        if found_line:
            checks["corrections_has_date_and_keyword"] = True

    # 5) experiments.md
    if os.path.isfile(experiments_path):
        checks["experiments_exists"] = True
        exp_text = read_text(experiments_path) or ""
        has_baseline = any(("baseline" in l.lower()) for l in exp_text.splitlines())
        if has_baseline:
            checks["experiments_has_baseline"] = True
        # find at least one other experiment row with magi 2/3 or 3/3 and status
        statuses = ("keep", "discard", "revert", "crash")
        has_magi_status = False
        for l in exp_text.splitlines():
            low = l.lower()
            if "baseline" in low:
                continue
            if ("2/3" in l or "3/3" in l) and any(s in low for s in statuses):
                has_magi_status = True
                break
        if has_magi_status:
            checks["experiments_has_magi_and_status"] = True

    # 6) identity.json and signature.json
    identity = load_json(identity_path)
    if identity is not None:
        checks["identity_valid_json"] = True
        alias = identity.get("alias")
        public_key = identity.get("public_key")
        fingerprint = identity.get("fingerprint")
        fields_ok = isinstance(alias, str) and alias.strip() and isinstance(public_key, str) and len(public_key) >= 64 and is_lower_hex(public_key) and isinstance(fingerprint, str) and fingerprint == public_key[:16]
        if fields_ok:
            checks["identity_fields_valid"] = True

    signature = load_json(signature_path)
    if signature is not None:
        checks["signature_valid_json"] = True
        # Only validate if identity is valid to avoid exceptions; but independent checks can still pass partially
        sig_ok = False
        if isinstance(signature, dict):
            msg_file = signature.get("message_file")
            sig_fp = signature.get("fingerprint")
            sig_date = signature.get("date")
            sig_val = signature.get("signature")
            msg_ok = (msg_file == "output/summary.md")
            fp_ok = isinstance(sig_fp, str) and identity is not None and signature.get("fingerprint") == identity.get("fingerprint")
            date_ok = is_iso_date(sig_date)
            expected_sig = None
            if isinstance(sig_fp, str) and isinstance(sig_date, str):
                expected_sig = (f"{sig_fp}|{sig_date}|summary")[::-1]
            sig_match = isinstance(sig_val, str) and expected_sig is not None and sig_val == expected_sig
            if msg_ok and fp_ok and date_ok and sig_match:
                sig_ok = True
        if sig_ok:
            checks["signature_fields_valid"] = True

    # Cross-check summary Signed-By with identity
    if checks["summary_signed_by_line_at_end"] and identity is not None and checks.get("identity_fields_valid"):
        s_text = summary_text or ""
        fp_line, ok_line = extract_signed_by_fingerprint(s_text)
        if ok_line and fp_line == identity.get("fingerprint"):
            checks["summary_signed_by_matches_identity"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, force 0.0
    if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, name))]) == 0):
        reward = 0.0

    result = {"reward": reward}
    # Preserve insertion order with reward first
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()