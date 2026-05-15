import csv
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

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None

def nonempty_string(s):
    return isinstance(s, str) and len(s.strip()) > 0

def contains_line_starting_with(text, prefix):
    if text is None:
        return False
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return True
    return False

def section_present(text, heading):
    if text is None:
        return False
    return heading in text

def contains_phrase(text, phrase):
    if text is None:
        return False
    return phrase in text

def contains_any(text, terms):
    if text is None:
        return False
    t = text
    return any(term in t for term in terms)

def check_mitigation_btc_latency(mitigation):
    if not nonempty_string(mitigation):
        return False
    lower = mitigation.lower()
    a = ("avoid" in lower or "avoiding" in lower) and ("btc" in mitigation or "bitcoin" in lower) and (
        "sub-6" in lower or "sub 6" in lower or "under 6" in lower or "below 6" in lower or "6-second" in lower or "6 second" in lower
    )
    b = (("Tron" in mitigation) or ("Base" in mitigation)) and (
        "low-latency" in lower or "low latency" in lower or "latency" in lower
    )
    return a or b

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_output_dir": False,
        "has_recommendation_json": False,
        "recommendation_structure_valid": False,
        "recommendation_chosen_architecture_correct": False,
        "recommendation_reasoning_nonempty": False,
        "recommendation_booleans_true": False,
        "recommendation_notes_nonempty": False,

        "has_decision_matrix_csv": False,
        "decision_matrix_header_valid": False,
        "decision_matrix_rows_present": False,
        "decision_matrix_winners_valid": False,
        "decision_matrix_has_hybrid_winner": False,

        "has_architecture_md": False,
        "architecture_has_overview": False,
        "architecture_has_payment_flow_with_phrases": False,
        "architecture_privacy_section_mentions_http_metadata": False,
        "architecture_token_chain_mentions_required": False,
        "architecture_settlement_latency_mentions_chain": False,
        "architecture_has_fallback_plan": False,
        "architecture_why_not_pure_x402_mentions_kyc_and_facilitator": False,

        "has_risk_register_json": False,
        "risk_register_is_array": False,
        "risk_register_has_required_ids": False,
        "risk_register_required_fields_nonempty": False,
        "risk_register_btc_delay_mitigation_ok": False,

        "crosscheck_latency_ref_ok": False,
    }

    # Existence checks
    if os.path.isdir(output_dir):
        checks["has_output_dir"] = True

    rec_path = os.path.join(output_dir, "recommendation.json")
    dm_path = os.path.join(output_dir, "decision_matrix.csv")
    arch_path = os.path.join(output_dir, "architecture.md")
    risk_path = os.path.join(output_dir, "risk_register.json")

    if os.path.isfile(rec_path):
        checks["has_recommendation_json"] = True
    if os.path.isfile(dm_path):
        checks["has_decision_matrix_csv"] = True
    if os.path.isfile(arch_path):
        checks["has_architecture_md"] = True
    if os.path.isfile(risk_path):
        checks["has_risk_register_json"] = True

    # recommendation.json validation
    rec = load_json(rec_path) if checks["has_recommendation_json"] else None
    if isinstance(rec, dict):
        # Validate top-level keys exactly
        expected_top_keys = {
            "chosen_architecture",
            "reasoning",
            "supports_tokens",
            "supports_chains",
            "meets_latency",
            "micropayments_viable",
            "notes",
        }
        top_keys = set(rec.keys())
        if top_keys == expected_top_keys and isinstance(rec.get("reasoning"), dict):
            # Validate reasoning keys exactly
            expected_reasoning_keys = {
                "privacy",
                "kyc",
                "token_support",
                "facilitator_dependency",
                "settlement_finality",
                "http_native",
            }
            reasoning = rec["reasoning"]
            if set(reasoning.keys()) == expected_reasoning_keys:
                checks["recommendation_structure_valid"] = True

                # chosen architecture check
                if rec.get("chosen_architecture") == "payram_as_x402_layer":
                    checks["recommendation_chosen_architecture_correct"] = True

                # Non-empty reasoning strings
                if all(nonempty_string(reasoning[k]) for k in expected_reasoning_keys):
                    checks["recommendation_reasoning_nonempty"] = True

                # Boolean checks: all must be true
                bool_fields_true = (
                    rec.get("supports_tokens") is True and
                    rec.get("supports_chains") is True and
                    rec.get("meets_latency") is True and
                    rec.get("micropayments_viable") is True
                )
                if bool_fields_true:
                    checks["recommendation_booleans_true"] = True

                # Notes: non-empty array of strings
                notes = rec.get("notes")
                if isinstance(notes, list) and len(notes) > 0 and all(isinstance(n, str) and len(n.strip()) >= 0 for n in notes):
                    checks["recommendation_notes_nonempty"] = True

    # decision_matrix.csv validation
    if checks["has_decision_matrix_csv"]:
        headers, rows = parse_csv(dm_path)
        required_headers = ["Criterion", "PayRam", "x402", "Hybrid", "Winner"]
        if headers == required_headers:
            checks["decision_matrix_header_valid"] = True

        # Required rows
        required_criteria = [
            "Privacy / Identity Isolation",
            "KYC / Facilitator Dependency",
            "Token Support (USDT/USDC/BTC)",
            "Chain Support (Tron/Base/Bitcoin)",
            "HTTP-Native Integration",
            "Settlement Finality",
            "Micropayments ($0.01)",
            "EU (MiCA) Compliance Control",
        ]
        if isinstance(rows, list):
            present = {r.get("Criterion", "") for r in rows}
            if all(c in present for c in required_criteria):
                checks["decision_matrix_rows_present"] = True

            # Winner validity per row
            allowed_winners = {
                "Privacy / Identity Isolation": {"Hybrid", "PayRam"},
                "KYC / Facilitator Dependency": {"Hybrid", "PayRam"},
                "Token Support (USDT/USDC/BTC)": {"Hybrid", "PayRam"},
                "Chain Support (Tron/Base/Bitcoin)": {"Hybrid", "PayRam"},
                "HTTP-Native Integration": {"Hybrid", "x402"},
                "Settlement Finality": {"Hybrid", "PayRam"},
                "Micropayments ($0.01)": {"Hybrid", "PayRam"},
                "EU (MiCA) Compliance Control": {"Hybrid", "PayRam"},
            }
            winners_ok = True
            has_hybrid = False
            for r in rows:
                crit = r.get("Criterion", "")
                win = r.get("Winner", "")
                if crit in allowed_winners:
                    if win not in allowed_winners[crit]:
                        winners_ok = False
                    if win == "Hybrid":
                        has_hybrid = True
            if winners_ok and checks["decision_matrix_rows_present"]:
                checks["decision_matrix_winners_valid"] = True
            if has_hybrid:
                checks["decision_matrix_has_hybrid_winner"] = True

    # architecture.md validation
    arch_text = read_text(arch_path) if checks["has_architecture_md"] else None
    if arch_text is not None:
        # # Overview line
        if contains_line_starting_with(arch_text, "# Overview"):
            checks["architecture_has_overview"] = True

        # Payment Flow section and phrases
        if section_present(arch_text, "## Payment Flow") and contains_phrase(arch_text, "unique deposit address") and contains_phrase(arch_text, "on-chain confirmation"):
            checks["architecture_has_payment_flow_with_phrases"] = True

        # Privacy considerations mentions HTTP metadata exposure risks
        if section_present(arch_text, "## Privacy Considerations") and contains_any(arch_text, ["HTTP metadata", "HTTP headers", "metadata exposure"]):
            checks["architecture_privacy_section_mentions_http_metadata"] = True

        # Token & Chain Support includes "USDT on Tron" and "BTC"
        if section_present(arch_text, "## Token & Chain Support") and ("USDT on Tron" in arch_text) and ("BTC" in arch_text):
            checks["architecture_token_chain_mentions_required"] = True

        # Settlement & Latency mentions either Tron or Base
        if section_present(arch_text, "## Settlement & Latency") and (("Tron" in arch_text) or ("Base" in arch_text)):
            checks["architecture_settlement_latency_mentions_chain"] = True

        # Fallback Plan section
        if section_present(arch_text, "## Fallback Plan"):
            checks["architecture_has_fallback_plan"] = True

        # Why not pure x402 mentions KYC and Stripe or Coinbase
        if section_present(arch_text, "## Why not pure x402"):
            has_kyc = ("KYC" in arch_text or "kyc" in arch_text)
            has_facilitator = ("Stripe" in arch_text) or ("Coinbase" in arch_text)
            if has_kyc and has_facilitator:
                checks["architecture_why_not_pure_x402_mentions_kyc_and_facilitator"] = True

    # risk_register.json validation
    risk = load_json(risk_path) if checks["has_risk_register_json"] else None
    if isinstance(risk, list):
        checks["risk_register_is_array"] = True
        # Build map by id
        by_id = {}
        for item in risk:
            if isinstance(item, dict) and "id" in item:
                by_id[item["id"]] = item
        required_ids = {"infrastructure_maintenance", "bitcoin_confirmation_delays", "x402_optimistic_settlement_risk", "eu_mica_uncertainty"}
        if required_ids.issubset(set(by_id.keys())):
            checks["risk_register_has_required_ids"] = True

            # Required fields non-empty
            fields_ok = True
            for rid in required_ids:
                obj = by_id[rid]
                if not (nonempty_string(obj.get("title")) and nonempty_string(obj.get("severity")) and nonempty_string(obj.get("mitigation"))):
                    fields_ok = False
                    break
            if fields_ok:
                checks["risk_register_required_fields_nonempty"] = True

            # Special mitigation text check for bitcoin_confirmation_delays
            btc_obj = by_id.get("bitcoin_confirmation_delays")
            if btc_obj and check_mitigation_btc_latency(btc_obj.get("mitigation", "")):
                checks["risk_register_btc_delay_mitigation_ok"] = True

    # Cross-checks
    meets_latency_true = rec.get("meets_latency") is True if isinstance(rec, dict) else False
    if meets_latency_true and checks["architecture_settlement_latency_mentions_chain"]:
        checks["crosscheck_latency_ref_ok"] = True
    elif not meets_latency_true:
        # If not true, do not grant cross-check pass (keep False)
        pass

    # Compute reward as fraction of passed checks
    # All checks depend on output/, so safe to average
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or no required files, reward must be 0.0
    required_files_present = checks["has_recommendation_json"] and checks["has_decision_matrix_csv"] and checks["has_architecture_md"] and checks["has_risk_register_json"]
    if not required_files_present:
        reward = 0.0

    # Print final JSON
    print(json.dumps({"reward": round(reward, 6), **checks}))

if __name__ == "__main__":
    main()