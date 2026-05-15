import json
import os
import re
import sys

def load_jsonl_lines(path):
    lines = []
    if not os.path.isfile(path):
        return lines
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                # Preserve index with a placeholder None to keep counts aligned if needed
                lines.append(None)
                continue
            try:
                obj = json.loads(line)
                lines.append(obj)
            except Exception:
                lines.append(None)
    return lines

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return []

def count_placeholders(text):
    pattern = re.compile(r"\[[A-Z_]+:[0-9a-f]{8,}\]")
    return len(pattern.findall(text))

def extract_placeholder_types(text):
    pattern = re.compile(r"\[([A-Z_]+):([0-9a-f]{8,})\]")
    return [m.group(1) for m in pattern.finditer(text)]

def extract_placeholders(text):
    pattern = re.compile(r"\[([A-Z_]+):([0-9a-f]{8,})\]")
    return [m.group(0) for m in pattern.finditer(text)]

def find_email_placeholders(messages):
    # Returns list of full placeholder tokens for EMAIL_ADDRESS in provided message strings
    pattern = re.compile(r"\[EMAIL_ADDRESS:([0-9a-f]{8,})\]")
    results = []
    for msg in messages:
        if not isinstance(msg, str):
            continue
        m = pattern.findall(msg)
        # Collect full tokens to compare exact equality
        results.extend([f"[EMAIL_ADDRESS:{h}]" for h in m])
    return results

def contains_long_digit_sequence(text, min_len=15):
    # Normalize spaces and hyphens commonly used in card formatting
    normalized = re.sub(r"[ \-]", "", text)
    return re.search(r"\d{" + str(min_len) + r",}", normalized) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_masked_support_tickets": False,
        "has_mask_index": False,
        "has_masking_report": False,
        "has_checkpoints": False,
        "has_runbook": False,
        "line_count_match": False,
        "ids_preserved": False,
        "messages_field_present": False,
        "no_prohibited_strings": False,
        "no_creditcard_numbers": False,
        "placeholder_pattern_present": False,
        "email_placeholder_consistent": False,
        "types_subset_present": False,
        "mask_index_valid": False,
        "masking_report_keywords": False,
        "checkpoints_qas": False,
        "runbook_structure": False,
    }

    # Paths
    input_jsonl_path = os.path.join(input_dir, "support_tickets.jsonl")
    masked_jsonl_path = os.path.join(output_dir, "masked_support_tickets.jsonl")
    mask_index_path = os.path.join(output_dir, "mask_index.json")
    masking_report_path = os.path.join(output_dir, "masking_report.md")
    checkpoints_path = os.path.join(output_dir, "checkpoints.md")
    runbook_path = os.path.join(output_dir, "runbook.md")

    # Presence checks
    checks["has_masked_support_tickets"] = os.path.isfile(masked_jsonl_path)
    checks["has_mask_index"] = os.path.isfile(mask_index_path)
    checks["has_masking_report"] = os.path.isfile(masking_report_path)
    checks["has_checkpoints"] = os.path.isfile(checkpoints_path)
    checks["has_runbook"] = os.path.isfile(runbook_path)

    # Load input and output for further checks
    input_lines_raw = read_lines(input_jsonl_path)
    output_lines_raw = read_lines(masked_jsonl_path) if checks["has_masked_support_tickets"] else []
    input_objs = load_jsonl_lines(input_jsonl_path)
    output_objs = load_jsonl_lines(masked_jsonl_path) if checks["has_masked_support_tickets"] else []

    # Line count match
    if checks["has_masked_support_tickets"] and os.path.isfile(input_jsonl_path):
        if len(output_lines_raw) == len(input_lines_raw):
            checks["line_count_match"] = True

    # JSONL validity, id preservation and message field
    if checks["line_count_match"] and len(output_objs) == len(input_objs) and len(input_objs) > 0:
        ids_ok = True
        messages_ok = True
        for idx in range(len(input_objs)):
            in_obj = input_objs[idx]
            out_obj = output_objs[idx]
            # Ensure both parsed correctly
            if not isinstance(in_obj, dict) or not isinstance(out_obj, dict):
                ids_ok = False
                messages_ok = False
                break
            # id preserved
            if "id" not in in_obj or "id" not in out_obj or in_obj["id"] != out_obj["id"]:
                ids_ok = False
            # message field present
            if "message" not in out_obj:
                messages_ok = False
        checks["ids_preserved"] = ids_ok
        checks["messages_field_present"] = messages_ok

    # Prohibited raw strings should not appear anywhere in masked JSONL file
    prohibited_fragments = [
        "john.doe@example.com",
        "sk-live-",
        "mongodb://user:pass",
        "-----BEGIN RSA PRIVATE KEY-----",
        "415-555-1234",
        "555-867-5309",
        "Summer2026!",
        "Winter2025",
        "secret=abc+/==",
    ]
    if checks["has_masked_support_tickets"]:
        masked_file_text = read_text(masked_jsonl_path)
        if masked_file_text != "":
            checks["no_prohibited_strings"] = not any(fragment in masked_file_text for fragment in prohibited_fragments)

    # No long digit sequences (15+ digits) remain in messages (credit cards)
    if checks["messages_field_present"]:
        cc_ok = True
        for out_obj in output_objs:
            if not isinstance(out_obj, dict):
                cc_ok = False
                break
            msg = out_obj.get("message", "")
            if isinstance(msg, str):
                if contains_long_digit_sequence(msg, min_len=15):
                    cc_ok = False
                    break
            else:
                # If message is not a string, fail
                cc_ok = False
                break
        checks["no_creditcard_numbers"] = cc_ok

    # Placeholder pattern presence
    placeholder_pattern = re.compile(r"\[[A-Z_]+:[0-9a-f]{8,}\]")
    if checks["has_masked_support_tickets"]:
        masked_text = read_text(masked_jsonl_path)
        if masked_text and placeholder_pattern.search(masked_text):
            checks["placeholder_pattern_present"] = True

    # Email placeholder consistency for lines containing john.doe@example.com in input
    if checks["messages_field_present"]:
        indices_with_email = []
        for i, raw in enumerate(input_lines_raw):
            if "john.doe@example.com" in raw:
                indices_with_email.append(i)
        if indices_with_email:
            placeholders_in_those = []
            for i in indices_with_email:
                out_obj = output_objs[i]
                if isinstance(out_obj, dict):
                    msg = out_obj.get("message", "")
                    if isinstance(msg, str):
                        phs = find_email_placeholders([msg])
                        # Require at least one EMAIL_ADDRESS placeholder in those lines
                        if not phs:
                            placeholders_in_those.append(None)
                        else:
                            # If multiple, take set — but identity requires all equal across lines
                            # Collect the first placeholder token for comparison
                            placeholders_in_those.append(phs[0])
                    else:
                        placeholders_in_those.append(None)
                else:
                    placeholders_in_those.append(None)
            # Check all non-None are identical and none are None
            if placeholders_in_those and all(p is not None for p in placeholders_in_those):
                unique_tokens = set(placeholders_in_those)
                checks["email_placeholder_consistent"] = (len(unique_tokens) == 1)
            else:
                checks["email_placeholder_consistent"] = False
        else:
            # If no such lines exist in input, do not penalize this check provided output exists
            # Set to True only if masked file exists to avoid giving credit with no output
            checks["email_placeholder_consistent"] = checks["has_masked_support_tickets"]

    # Types subset presence in placeholders across file
    if checks["has_masked_support_tickets"]:
        masked_text_all = read_text(masked_jsonl_path)
        types_found = set(extract_placeholder_types(masked_text_all))
        expected_subset = {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "PASSWORD", "API_KEY", "PRIVATE_KEY", "DB_CONNECTION"}
        # Require at least 3 of these types present to consider subset represented
        if len(types_found.intersection(expected_subset)) >= 3:
            checks["types_subset_present"] = True

    # mask_index.json validity
    if checks["has_mask_index"] and checks["has_masked_support_tickets"]:
        try:
            with open(mask_index_path, "r", encoding="utf-8") as f:
                idx_data = json.load(f)
            entities = idx_data.get("entities")
            total_masks = idx_data.get("total_masks")
            placeholders_list = idx_data.get("placeholders")
            valid_structure = isinstance(entities, dict) and isinstance(placeholders_list, list) and (isinstance(total_masks, int) or isinstance(total_masks, float))
            placeholders_valid = True
            ph_pattern = re.compile(r"\[[A-Z_]+:[0-9a-f]{8,}\]")
            if valid_structure:
                for p in placeholders_list:
                    if not isinstance(p, str) or ph_pattern.fullmatch(p) is None:
                        placeholders_valid = False
                        break
            # Count placeholder occurrences in masked file
            ph_occurrences = count_placeholders(read_text(masked_jsonl_path))
            total_masks_ok = isinstance(total_masks, (int, float)) and int(total_masks) >= ph_occurrences
            email_count_ok = False
            if isinstance(entities, dict) and "EMAIL_ADDRESS" in entities:
                try:
                    email_count_ok = int(entities["EMAIL_ADDRESS"]) >= 1
                except Exception:
                    email_count_ok = False
            checks["mask_index_valid"] = bool(valid_structure and placeholders_valid and total_masks_ok and email_count_ok)
        except Exception:
            checks["mask_index_valid"] = False

    # masking_report.md keywords and entity mentions
    if checks["has_masking_report"]:
        report_text = read_text(masking_report_path)
        if report_text:
            has_risk = ("risk" in report_text.lower())
            has_restoration = ("restoration" in report_text.lower())
            # Look for at least three of these entity names mentioned plainly
            names = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "PASSWORD", "API_KEY", "PRIVATE_KEY", "DB_CONNECTION", "URL", "TOKEN", "SECRET"]
            count_mentions = sum(1 for n in names if n in report_text)
            if has_risk and has_restoration and count_mentions >= 3:
                checks["masking_report_keywords"] = True

    # checkpoints.md Q&A pairs
    if checks["has_checkpoints"]:
        cp_text = read_text(checkpoints_path)
        if cp_text:
            q_count = cp_text.count("Q:")
            a_count = cp_text.count("A:")
            if q_count >= 3 and a_count >= 3:
                checks["checkpoints_qas"] = True

    # runbook.md structure
    if checks["has_runbook"]:
        rb_text = read_text(runbook_path)
        if rb_text:
            has_stages = all(re.search(r"Stage\s*{}".format(i), rb_text, flags=re.IGNORECASE) for i in [1, 2, 3, 4])
            has_verification = ("verification" in rb_text.lower())
            has_rollback = ("rollback" in rb_text.lower())
            if has_stages and has_verification and has_rollback:
                checks["runbook_structure"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if required outputs are missing, ensure reward is 0.0
    required_presence = ["has_masked_support_tickets", "has_mask_index", "has_masking_report", "has_checkpoints", "has_runbook"]
    if not all(checks[k] for k in required_presence):
        # If any required artifact missing, overall reward should be 0
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()