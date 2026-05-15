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

def parse_scalar(value_str):
    v = value_str.strip()
    if v == "" or v.lower() == "null":
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    # Try int then float
    try:
        if v.lower().startswith("0x"):  # hex number not expected here
            return v
        if re.match(r"^-?\d+$", v):
            return int(v)
        if re.match(r"^-?\d+\.\d+$", v):
            return float(v)
    except Exception:
        pass
    # Strip quotes if present
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v

def parse_simple_yaml(path):
    """
    Minimal YAML parser for simple nested mappings with scalar values.
    Supports keys like:
    hardVeto:
      maxPriceImpactPct: 10
      minPoolTVLUSD: 1000
    lp:
      ilPctConservative: 20
    swap:
      conservative:
        priceImpactMinPctForNonApprove: 1.0
    """
    text = read_text(path)
    if text is None:
        return None
    root = {}
    stack = [(-1, root)]
    for raw_line in text.splitlines():
        # Remove comments
        line = raw_line.split("#", 1)[0].rstrip("\n\r")
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")
        # Ignore list items - not expected in this policy file
        if content.lstrip().startswith("- "):
            # Not supported; skip
            continue
        # Move up stack to correct parent based on indent
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1]
        if ":" in content:
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # Start a new nested dict
                new_map = {}
                current_dict[key] = new_map
                stack.append((indent, new_map))
            else:
                current_dict[key] = parse_scalar(val)
        else:
            # Line without colon not supported; skip
            continue
    return root

def any_unverified_tokens(op):
    # Direct boolean
    if isinstance(op.get("tokenVerified"), bool) and not op["tokenVerified"]:
        return True
    # keys ending with Verified
    for k, v in op.items():
        if isinstance(v, bool) and k.lower().endswith("verified") and not v:
            return True
    # tokens structure
    tokens = op.get("tokens")
    if isinstance(tokens, list):
        for t in tokens:
            if isinstance(t, dict):
                for k, v in t.items():
                    if isinstance(v, bool) and (k.lower() == "verified" or k.lower().endswith("verified")) and not v:
                        return True
    elif isinstance(tokens, dict):
        for _, t in tokens.items():
            if isinstance(t, dict):
                for k, v in t.items():
                    if isinstance(v, bool) and (k.lower() == "verified" or k.lower().endswith("verified")) and not v:
                        return True
    return False

def to_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace("%", "")
        return float(s)
    except Exception:
        return None

def to_lower_str(x, default=None):
    if isinstance(x, str):
        return x.lower()
    return default

def check_summary_mentions_id_and_decision(summary_text, op_id, decision):
    for line in summary_text.splitlines():
        if op_id in line and decision in line:
            return True
    return False

def extract_numbered_list_lines(summary_text):
    lines = []
    for line in summary_text.splitlines():
        if re.match(r"^\s*\d+[\.\)]\s+", line):
            lines.append(line.strip())
    return lines

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks to False
    checks = {
        "assessments_exists": False,
        "summary_exists": False,
        "assessments_json_valid_array": False,
        "assessments_count_matches": False,
        "ids_match_exactly": False,
        "schema_fields_ok": False,
        "dimensions_applicability_ok": False,
        "policy_hard_veto_enforced": False,
        "policy_hard_veto_dimension_alignment": False,
        "policy_lp_conservative_il_veto": False,
        "policy_swap_conservative_non_approve": False,
        "mitigations_required_for_non_approve": False,
        "reasoning_nonempty": False,
        "summary_mentions_all_ids_and_decisions": False,
        "summary_includes_safest_to_riskiest_ordered_list": False,
        "summary_mentions_hard_veto_reason_if_any": False,
    }

    assessments_path = os.path.join(output_dir, "assessments.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Existence checks
    if os.path.isfile(assessments_path):
        checks["assessments_exists"] = True
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True

    # If required artifacts missing, reward must be exactly 0.0 at end.
    # Still compute other checks conditionally if possible.
    operations_path = os.path.join(input_dir, "operations.json")
    policies_path = os.path.join(input_dir, "policies.yaml")
    operations = load_json(operations_path) or []
    policies = parse_simple_yaml(policies_path) or {}

    # Build convenient policy values
    hard_veto = policies.get("hardVeto", {})
    lp_policy = policies.get("lp", {})
    swap_policy = policies.get("swap", {})
    swap_conservative = {}
    if isinstance(swap_policy, dict):
        swap_conservative = swap_policy.get("conservative", {}) or {}

    max_price_impact_hv = to_float(hard_veto.get("maxPriceImpactPct"))
    min_pool_tvl_hv = to_float(hard_veto.get("minPoolTVLUSD"))
    il_pct_conservative = to_float(lp_policy.get("ilPctConservative"))
    swap_conserv_nonapprove_priceimpact = to_float(swap_conservative.get("priceImpactMinPctForNonApprove"))

    expected_ids = []
    op_by_id = {}
    if isinstance(operations, list):
        for op in operations:
            op_id = str(op.get("id")) if "id" in op else None
            if op_id:
                expected_ids.append(op_id)
                op_by_id[op_id] = op

    assessments = None
    if checks["assessments_exists"]:
        assessments = load_json(assessments_path)
        if isinstance(assessments, list):
            checks["assessments_json_valid_array"] = True

    # Validate counts and ids
    if checks["assessments_json_valid_array"]:
        if len(assessments) == len(expected_ids) and len(expected_ids) > 0:
            checks["assessments_count_matches"] = True
        ids_in_assessments = []
        if assessments is not None:
            for item in assessments:
                if isinstance(item, dict) and "id" in item:
                    ids_in_assessments.append(str(item["id"]))
        if sorted(ids_in_assessments) == sorted(expected_ids) and len(expected_ids) > 0:
            checks["ids_match_exactly"] = True

    # Schema field validation and dimensions applicability
    allowed_decisions = {"APPROVE", "CONDITIONAL_APPROVE", "VETO", "HARD_VETO"}
    allowed_composite = {"LOW", "MEDIUM", "HIGH"}
    allowed_dim_vals = {"LOW", "MEDIUM", "HIGH", "N/A"}
    allowed_risk_tol = {"conservative", "moderate", "aggressive"}

    schema_ok_all = True
    dims_applic_ok_all = True
    mitigations_ok_all = True
    reasoning_ok_all = True

    hard_veto_enforced_all = True
    hard_veto_dim_align_all = True
    lp_conservative_veto_all = True
    swap_conservative_nonapprove_all = True

    # For summary checks later
    final_decisions_by_id = {}

    if checks["assessments_json_valid_array"] and checks["ids_match_exactly"]:
        for item in assessments:
            if not isinstance(item, dict):
                schema_ok_all = False
                dims_applic_ok_all = False
                mitigations_ok_all = False
                reasoning_ok_all = False
                hard_veto_enforced_all = False
                hard_veto_dim_align_all = False
                lp_conservative_veto_all = False
                swap_conservative_nonapprove_all = False
                continue
            # Required fields presence and value checks
            required_fields = [
                "id",
                "operationSummary",
                "riskTolerance",
                "decision",
                "compositeRisk",
                "dimensions",
                "hardVetoTriggers",
                "reasoning",
                "mitigations",
            ]
            for f in required_fields:
                if f not in item:
                    schema_ok_all = False
            # id
            op_id = str(item.get("id", ""))
            if op_id not in op_by_id:
                schema_ok_all = False
            # operationSummary
            if not isinstance(item.get("operationSummary"), str) or not item.get("operationSummary").strip():
                schema_ok_all = False
            # riskTolerance
            if item.get("riskTolerance") not in allowed_risk_tol:
                schema_ok_all = False
            # decision
            decision = item.get("decision")
            if decision not in allowed_decisions:
                schema_ok_all = False
            # compositeRisk
            if item.get("compositeRisk") not in allowed_composite:
                schema_ok_all = False
            # dimensions
            dims = item.get("dimensions")
            if not isinstance(dims, dict):
                schema_ok_all = False
            else:
                for k in ["Slippage", "ImpermanentLoss", "Liquidity", "SmartContract", "Bridge"]:
                    if k not in dims or dims.get(k) not in allowed_dim_vals:
                        schema_ok_all = False
            # hardVetoTriggers
            hvt = item.get("hardVetoTriggers")
            if not isinstance(hvt, list):
                schema_ok_all = False
            # reasoning
            if not isinstance(item.get("reasoning"), str) or not item.get("reasoning").strip():
                schema_ok_all = False
                reasoning_ok_all = False
            # mitigations
            mit = item.get("mitigations")
            if not isinstance(mit, list):
                schema_ok_all = False

            # Applicability rules for dimensions
            op = op_by_id.get(op_id, {})
            op_type = to_lower_str(op.get("type"), "")
            if isinstance(dims, dict):
                if op_type == "swap":
                    if dims.get("ImpermanentLoss") != "N/A":
                        dims_applic_ok_all = False
                if op_type == "lp":
                    if dims.get("Bridge") != "N/A":
                        dims_applic_ok_all = False
                if op_type == "bridge":
                    if dims.get("ImpermanentLoss") != "N/A":
                        dims_applic_ok_all = False

            # Mitigations required when decision != APPROVE
            if decision != "APPROVE":
                if not isinstance(mit, list) or len(mit) == 0:
                    mitigations_ok_all = False

            # Record final decision for summary check
            if op_id:
                final_decisions_by_id[op_id] = decision

        # Apply policy rule checks per operation
        for item in assessments:
            if not isinstance(item, dict):
                continue
            op_id = str(item.get("id", ""))
            op = op_by_id.get(op_id, {})
            decision = item.get("decision")
            dims = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
            hvt_list = item.get("hardVetoTriggers") if isinstance(item.get("hardVetoTriggers"), list) else []
            op_type = to_lower_str(op.get("type"), "")
            priceImpactPct = to_float(op.get("priceImpactPct"))
            poolTVLUSD = to_float(op.get("poolTVLUSD"))
            amountUSD = to_float(op.get("amountUSD"))
            bridgeLiquidityUSD = to_float(op.get("bridgeLiquidityUSD"))
            risk_tol_input = to_lower_str(op.get("riskTolerance"), "moderate")

            # Detect hard veto triggers
            triggers = []
            if any_unverified_tokens(op):
                triggers.append("unverified_token")
            if min_pool_tvl_hv is not None and poolTVLUSD is not None and poolTVLUSD < min_pool_tvl_hv:
                triggers.append("pool_tvl_below_min")
            if max_price_impact_hv is not None and priceImpactPct is not None and priceImpactPct >= max_price_impact_hv:
                triggers.append("price_impact_exceeds_hard_veto")
            if op_type == "bridge" and amountUSD is not None and bridgeLiquidityUSD is not None and amountUSD > bridgeLiquidityUSD:
                triggers.append("bridge_amount_exceeds_liquidity")

            has_hv = len(triggers) > 0

            # Enforce HARD_VETO decision and reasons if required
            if has_hv:
                if decision != "HARD_VETO":
                    hard_veto_enforced_all = False
                # Triggers listed and mention triggering condition
                hvt_text = " ".join([str(x) for x in hvt_list]).lower()
                # Must contain at least one reason mentioning a trigger
                reason_keywords = []
                if "unverified_token" in triggers:
                    reason_keywords.append("unverified")
                if "pool_tvl_below_min" in triggers:
                    reason_keywords.extend(["pool tvl", "tvl"])
                if "price_impact_exceeds_hard_veto" in triggers:
                    reason_keywords.append("price impact")
                if "bridge_amount_exceeds_liquidity" in triggers:
                    reason_keywords.extend(["bridge liquidity", "exceeds liquidity", "amount exceeds"])
                # Check if any keyword is present
                if not any(kw in hvt_text for kw in reason_keywords):
                    hard_veto_enforced_all = False
                # Dimension alignment checks
                if "price_impact_exceeds_hard_veto" in triggers:
                    if dims.get("Slippage") != "HIGH":
                        hard_veto_dim_align_all = False
                if "unverified_token" in triggers:
                    if dims.get("SmartContract") != "HIGH":
                        hard_veto_dim_align_all = False
                if "bridge_amount_exceeds_liquidity" in triggers:
                    if dims.get("Bridge") != "HIGH" or decision != "HARD_VETO":
                        hard_veto_dim_align_all = False
            # LP conservative IL veto (unless hard veto applies)
            if (not has_hv) and op_type == "lp" and risk_tol_input == "conservative" and il_pct_conservative is not None:
                il_est = to_float(op.get("estimatedILAnnPct"))
                if il_est is not None and il_est >= il_pct_conservative:
                    if decision != "VETO":
                        lp_conservative_veto_all = False
            # Swap conservative non-approve for price impact threshold (unless hard veto)
            if (not has_hv) and op_type == "swap" and risk_tol_input == "conservative" and swap_conserv_nonapprove_priceimpact is not None:
                if priceImpactPct is not None and priceImpactPct >= swap_conserv_nonapprove_priceimpact:
                    if decision == "APPROVE":
                        swap_conservative_nonapprove_all = False

    # Assign aggregate checks
    if checks["assessments_json_valid_array"]:
        checks["schema_fields_ok"] = schema_ok_all
        checks["dimensions_applicability_ok"] = dims_applic_ok_all
        checks["mitigations_required_for_non_approve"] = mitigations_ok_all
        checks["reasoning_nonempty"] = reasoning_ok_all
        checks["policy_hard_veto_enforced"] = hard_veto_enforced_all
        checks["policy_hard_veto_dimension_alignment"] = hard_veto_dim_align_all
        checks["policy_lp_conservative_il_veto"] = lp_conservative_veto_all
        checks["policy_swap_conservative_non_approve"] = swap_conservative_nonapprove_all

    # Summary validations
    summary_text = read_text(summary_path) if checks["summary_exists"] else None
    if isinstance(summary_text, str):
        # Mentions ids and their decision on same line
        all_lines_ok = True
        for oid, dec in final_decisions_by_id.items():
            if not check_summary_mentions_id_and_decision(summary_text, oid, dec):
                all_lines_ok = False
                break
        checks["summary_mentions_all_ids_and_decisions"] = all_lines_ok

        # "safest to riskiest" phrase and an ordered list
        if re.search(r"safest\s+to\s+riskiest", summary_text, flags=re.IGNORECASE):
            numbered = extract_numbered_list_lines(summary_text)
            if len(numbered) >= 2:
                checks["summary_includes_safest_to_riskiest_ordered_list"] = True

        # Mentions at least one hard-veto reason if any HARD_VETO present
        any_hv = any(dec == "HARD_VETO" for dec in final_decisions_by_id.values())
        if any_hv:
            st_lower = summary_text.lower()
            # Look for keywords indicating reasons
            reason_keywords = ["unverified", "price impact", "pool tvl", "bridge liquidity", "exceeds liquidity", "amount exceeds", "min pool tvl"]
            if ("hard_veto" in st_lower or "hard-veto" in st_lower or "hard veto" in st_lower or "hardveto" in st_lower) and any(kw in st_lower for kw in reason_keywords):
                checks["summary_mentions_hard_veto_reason_if_any"] = True
        else:
            # If no HARD_VETO operations, this check is vacuously true? Do not award positive points for checks not depending on outputs.
            # Keep it False to avoid vacuous pass.
            pass

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Enforce baseline: if any required artifact missing, reward must be 0.0
    if not (checks["assessments_exists"] and checks["summary_exists"]):
        reward = 0.0
    else:
        # Normalized score
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    # Print result JSON (single line, reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()