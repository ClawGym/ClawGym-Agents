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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compare_close(a, b, eps=0.005):
    try:
        return abs(float(a) - float(b)) <= eps
    except Exception:
        return False

def section_ranges(text, headers):
    # Returns dict {header: (start_index, end_index)} for each header.
    # end_index is start of next header or len(text)
    indices = []
    for h in headers:
        idx = text.find(h)
        indices.append(idx)
    if any(i == -1 for i in indices):
        return None, False  # missing headers
    # ensure order strictly increasing
    in_order = all(indices[i] < indices[i+1] for i in range(len(indices)-1))
    ranges = {}
    for i, h in enumerate(headers):
        start = indices[i]
        end = indices[i+1] if i+1 < len(indices) else len(text)
        ranges[h] = (start, end)
    return ranges, in_order

def extract_lines(text, start, end):
    return text[start:end].splitlines()

def find_line_with_token(lines, token):
    matches = [ln for ln in lines if token in ln]
    return matches[0] if matches else None

def line_has_all_tokens(line, tokens):
    return all(t in line for t in tokens)

def gather_totals(items, status_filter=None):
    totals = {}
    for it in items:
        if status_filter is None or it.get("claim_status") == status_filter:
            ccy = it.get("currency")
            amt = it.get("amount", 0)
            if isinstance(amt, (int, float)) and isinstance(ccy, str):
                totals[ccy] = totals.get(ccy, 0.0) + float(amt)
    return totals

def sum_by_category_currency(items, status_filter="ready"):
    # returns dict like {(currency, category): sum}
    acc = {}
    for it in items:
        if it.get("claim_status") != status_filter:
            continue
        ccy = it.get("currency")
        cat = it.get("category")
        amt = it.get("amount", 0)
        if isinstance(amt, (int, float)) and isinstance(ccy, str) and isinstance(cat, str):
            key = (ccy, cat)
            acc[key] = acc.get(key, 0.0) + float(amt)
    return acc

def is_two_decimals_str(s):
    return re.fullmatch(r"\d+\.\d{2}", s) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # normalized.json presence and structure
        "has_normalized_json": False,
        "normalized_is_array_len_10": False,
        "normalized_schema_valid": False,
        "normalized_policy_risk_all_not_provided": False,
        "normalized_no_block_reason_for_ready": False,
        "normalized_block_reason_for_blocked": False,
        "normalized_ids_match_expected": False,
        "normalized_statuses_match_expected": False,
        "totals_ready_match_expected": False,
        "totals_blocked_match_expected": False,
        "counts_blocked_and_missing_doc_match_expected": False,

        # claim_pack.txt checks
        "has_claim_pack": False,
        "text_has_three_sections_in_order": False,
        "text_ready_section_items_correct": False,
        "text_blocked_section_items_correct": False,
        "text_blocked_reasons_exact": False,
        "text_ready_lines_have_status_and_policy": False,
        "text_blocked_lines_have_status_policy_reason": False,
        "text_totals_present": False,
        "text_category_totals_present": False,
        "text_missing_doc_and_blocked_count_present": False,
        "text_next_action_has_period": False,
    }

    # Expected constants from task specification
    expected_ready_ids = {"E-001", "E-005", "E-008", "E-010"}
    expected_blocked_map = {
        "E-002": "missing business purpose",
        "E-003": "unreadable receipt",
        "E-004": "missing receipt",
        "E-006": "suspected duplicate",
        "E-007": "suspected duplicate",
        "E-011": "missing receipt",
    }
    expected_all_ids = expected_ready_ids.union(set(expected_blocked_map.keys()))
    expected_ready_totals = {"USD": 464.79, "EUR": 120.00}
    expected_blocked_totals = {"USD": 209.55}
    expected_blocked_count = 6
    expected_missing_doc_count = 3
    expected_period = "2026-03-01 to 2026-03-31"
    expected_category_totals_ready = [
        ("USD", "transport", 374.80),
        ("USD", "office", 89.99),
        ("EUR", "lodging", 120.00),
    ]
    allowed_receipt_status = {"attached", "missing", "unreadable"}
    allowed_categories = {"transport", "meal", "lodging", "software", "office", "misc"}
    allowed_payment_methods = {"card", "cash", "transfer"}
    allowed_block_reasons = {
        "missing receipt",
        "unreadable receipt",
        "missing business purpose",
        "suspected duplicate",
    }

    # Load outputs
    normalized_path = os.path.join(output_dir, "normalized.json")
    claim_pack_path = os.path.join(output_dir, "claim_pack.txt")

    normalized = None
    if os.path.isfile(normalized_path):
        normalized = read_json(normalized_path)
        if isinstance(normalized, list):
            checks["has_normalized_json"] = True
            if len(normalized) == 10:
                checks["normalized_is_array_len_10"] = True

    # Validate normalized schema and content if present
    if checks["has_normalized_json"]:
        schema_ok = True
        policy_all_ok = True
        no_block_reason_for_ready = True
        block_reason_for_blocked = True
        ids = set()
        id_to_obj = {}
        for obj in normalized if isinstance(normalized, list) else []:
            # Required keys
            req_keys = ["item_id", "date", "merchant", "amount", "currency", "category",
                        "payment_method", "business_purpose", "receipt_status", "policy_risk", "claim_status"]
            if not all(k in obj for k in req_keys):
                schema_ok = False
            # Types and enums
            if not isinstance(obj.get("item_id"), str): schema_ok = False
            if not isinstance(obj.get("date"), str): schema_ok = False
            if not isinstance(obj.get("merchant"), str): schema_ok = False
            if not isinstance(obj.get("amount"), (int, float)): schema_ok = False
            if not isinstance(obj.get("currency"), str): schema_ok = False
            if not isinstance(obj.get("category"), str) or obj.get("category") not in allowed_categories: schema_ok = False
            if not isinstance(obj.get("payment_method"), str) or obj.get("payment_method") not in allowed_payment_methods: schema_ok = False
            # business_purpose may be empty string? The schema requires presence; allow empty string type.
            if not isinstance(obj.get("business_purpose"), (str, type(None))): schema_ok = False
            if not isinstance(obj.get("receipt_status"), str) or obj.get("receipt_status") not in allowed_receipt_status: schema_ok = False
            if obj.get("policy_risk") != "policy not provided":
                policy_all_ok = False
            if not isinstance(obj.get("claim_status"), str) or obj.get("claim_status") not in {"ready", "blocked"}: schema_ok = False

            # block_reason presence rules
            if obj.get("claim_status") == "ready":
                if "block_reason" in obj and obj.get("block_reason") not in (None, "",):
                    no_block_reason_for_ready = False
                # If present but empty, we still consider it a violation because spec says present only for blocked
                if "block_reason" in obj:
                    no_block_reason_for_ready = False
            else:
                # blocked
                if "block_reason" not in obj or not isinstance(obj.get("block_reason"), str) or obj.get("block_reason") not in allowed_block_reasons:
                    block_reason_for_blocked = False

            # Collect ids
            if isinstance(obj.get("item_id"), str):
                ids.add(obj["item_id"])
                id_to_obj[obj["item_id"]] = obj

        checks["normalized_schema_valid"] = schema_ok
        checks["normalized_policy_risk_all_not_provided"] = policy_all_ok
        checks["normalized_no_block_reason_for_ready"] = no_block_reason_for_ready
        checks["normalized_block_reason_for_blocked"] = block_reason_for_blocked

        # IDs match expected set
        if ids == expected_all_ids and len(ids) == 10:
            checks["normalized_ids_match_expected"] = True

        # Statuses and reasons match expected map
        statuses_ok = True
        if ids == expected_all_ids:
            # ready set
            for rid in expected_ready_ids:
                o = id_to_obj.get(rid)
                if not o or o.get("claim_status") != "ready":
                    statuses_ok = False
            # blocked with reasons
            for bid, breason in expected_blocked_map.items():
                o = id_to_obj.get(bid)
                if not o or o.get("claim_status") != "blocked" or o.get("block_reason") != breason:
                    statuses_ok = False
        else:
            statuses_ok = False
        checks["normalized_statuses_match_expected"] = statuses_ok

        # Totals and counts from normalized.json
        if isinstance(normalized, list):
            ready_totals = gather_totals(normalized, status_filter="ready")
            blocked_totals = gather_totals(normalized, status_filter="blocked")
            # Ready totals must exactly match currencies and values
            ready_currency_set_ok = set(ready_totals.keys()) == set(expected_ready_totals.keys())
            ready_values_ok = all(compare_close(ready_totals.get(ccy, 0.0), amt) for ccy, amt in expected_ready_totals.items())
            if ready_currency_set_ok and ready_values_ok:
                checks["totals_ready_match_expected"] = True

            blocked_currency_set_ok = set(blocked_totals.keys()) == set(expected_blocked_totals.keys())
            blocked_values_ok = all(compare_close(blocked_totals.get(ccy, 0.0), amt) for ccy, amt in expected_blocked_totals.items())
            if blocked_currency_set_ok and blocked_values_ok:
                checks["totals_blocked_match_expected"] = True

            blocked_count = sum(1 for it in normalized if it.get("claim_status") == "blocked")
            missing_doc_count = sum(1 for it in normalized if it.get("receipt_status") in {"missing", "unreadable"})
            if blocked_count == expected_blocked_count and missing_doc_count == expected_missing_doc_count:
                checks["counts_blocked_and_missing_doc_match_expected"] = True

    # Validate claim_pack.txt
    if os.path.isfile(claim_pack_path):
        checks["has_claim_pack"] = True
        text = read_text(claim_pack_path)
        if isinstance(text, str):
            headers = ["Ready:", "Blocked:", "Next action:"]
            ranges, in_order = section_ranges(text, headers)
            if ranges and in_order:
                checks["text_has_three_sections_in_order"] = True

                # Extract sections
                ready_start, ready_end = ranges["Ready:"]
                blocked_start, blocked_end = ranges["Blocked:"]
                next_action_start, next_action_end = ranges["Next action:"]
                ready_lines = extract_lines(text, ready_start, blocked_start)
                blocked_lines = extract_lines(text, blocked_start, next_action_start)
                next_action_lines = extract_lines(text, next_action_start, next_action_end)

                # Ready section items correct: contains all ready ids and no blocked ids
                ready_contains_all = all(any(rid in ln for ln in ready_lines) for rid in expected_ready_ids)
                ready_contains_no_blocked = all(not any(bid in ln for ln in ready_lines) for bid in expected_blocked_map.keys())
                if ready_contains_all and ready_contains_no_blocked:
                    checks["text_ready_section_items_correct"] = True

                # Blocked section items correct: contains all blocked ids and no ready ids
                blocked_contains_all = all(any(bid in ln for ln in blocked_lines) for bid in expected_blocked_map.keys())
                blocked_contains_no_ready = all(not any(rid in ln for ln in blocked_lines) for rid in expected_ready_ids)
                if blocked_contains_all and blocked_contains_no_ready:
                    checks["text_blocked_section_items_correct"] = True

                # Block reasons exact on same line for each blocked item
                reasons_ok = True
                status_policy_blocked_ok = True
                for bid, breason in expected_blocked_map.items():
                    line = find_line_with_token(blocked_lines, bid)
                    if not line or breason not in line:
                        reasons_ok = False
                    # check presence of claim_status=blocked and policy_risk=policy not provided
                    if not line or "claim_status=blocked" not in line or "policy_risk=policy not provided" not in line:
                        status_policy_blocked_ok = False
                if reasons_ok:
                    checks["text_blocked_reasons_exact"] = True
                if status_policy_blocked_ok:
                    checks["text_blocked_lines_have_status_policy_reason"] = True

                # Ready lines have claim_status=ready and policy_risk on each listed ready item line
                status_policy_ready_ok = True
                for rid in expected_ready_ids:
                    line = find_line_with_token(ready_lines, rid)
                    if not line or "claim_status=ready" not in line or "policy_risk=policy not provided" not in line:
                        status_policy_ready_ok = False
                if status_policy_ready_ok:
                    checks["text_ready_lines_have_status_and_policy"] = True

                # Totals present: look for labels and amounts (two decimals)
                totals_present = False
                content_lines = ready_lines + blocked_lines + next_action_lines
                content_text = "\n".join(content_lines)
                # require labels present
                has_total_ready_label = "total_claim_ready" in content_text
                has_total_blocked_label = "total_blocked" in content_text
                # amounts
                has_ready_usd_amt = "USD 464.79" in content_text
                has_ready_eur_amt = "EUR 120.00" in content_text
                has_blocked_usd_amt = "USD 209.55" in content_text
                if has_total_ready_label and has_total_blocked_label and has_ready_usd_amt and has_ready_eur_amt and has_blocked_usd_amt:
                    totals_present = True
                if totals_present:
                    checks["text_totals_present"] = True

                # Category totals by currency for ready items (all 3 tokens on same line)
                category_ok = True
                found_triplets = []
                for (ccy, cat, amt) in expected_category_totals_ready:
                    amt_str = f"{amt:.2f}"
                    triplet_found = False
                    for ln in content_lines:
                        if ccy in ln and cat in ln and amt_str in ln:
                            triplet_found = True
                            break
                    found_triplets.append(triplet_found)
                    if not triplet_found:
                        category_ok = False
                if category_ok:
                    checks["text_category_totals_present"] = True

                # blocked_count and missing_doc_count presence with values on same line
                counts_ok = False
                has_blocked_count = any(("blocked_count" in ln and "6" in ln) for ln in content_lines)
                has_missing_doc_count = any(("missing_doc_count" in ln and "3" in ln) for ln in content_lines)
                if has_blocked_count and has_missing_doc_count:
                    counts_ok = True
                if counts_ok:
                    checks["text_missing_doc_and_blocked_count_present"] = True

                # Next action has period
                next_action_text = "\n".join(next_action_lines)
                if expected_period in next_action_text:
                    checks["text_next_action_has_period"] = True

    # Compute final reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # No-op baseline: if both outputs missing or essential artifacts missing, reward 0.0 automatically
    # Otherwise scale by fraction of passed checks
    if any(checks.values()):
      reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()