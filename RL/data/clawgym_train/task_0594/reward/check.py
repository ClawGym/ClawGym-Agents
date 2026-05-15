import json
import os
import sys
import re

def is_lower_hex(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return s == s.lower() and all(c in "0123456789abcdef" for c in s)

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def word_count(text: str) -> int:
    # Count words as sequences of alphanumeric/underscore bounded by whitespace/punct
    return len(re.findall(r"\b\w+\b", text))

def validate_pubkey_hex_32b(s: str) -> bool:
    return isinstance(s, str) and len(s) == 64 and is_lower_hex(s)

def validate_signature_hex_64b(s: str) -> bool:
    return isinstance(s, str) and len(s) == 128 and is_lower_hex(s)

def validate_hex_min_len_even(s: str, min_len: int) -> bool:
    return isinstance(s, str) and len(s) >= min_len and len(s) % 2 == 0 and is_lower_hex(s)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # identities.json related
        "has_identities_file": False,
        "identities_json_valid": False,
        "identities_aliases_correct": False,
        "identities_fields_present": False,
        "identities_pubkey_format": False,
        "identities_did_matches_pubkey": False,

        # signed_messages.json related
        "has_signed_messages_file": False,
        "signed_messages_json_valid": False,
        "signed_messages_count_correct": False,
        "signed_messages_pairs_covered": False,
        "signed_messages_fields_present": False,
        "signed_messages_pubkey_format": False,
        "signed_messages_pubkeys_match": False,
        "signed_messages_signature_format": False,
        "signed_messages_verified_true": False,
        "signed_messages_payloads_match_spec": False,

        # encryption_demo.json related
        "has_encryption_demo_file": False,
        "encryption_json_valid": False,
        "encryption_sessionkey_format": False,
        "encryption_nonce_format": False,
        "encryption_ciphertext_format": False,
        "encryption_decrypted_matches_secret": False,

        # handshake.md related
        "has_handshake_file": False,
        "handshake_length_ok": False,
        "handshake_contains_session_and_relay": False,
        "handshake_contains_terms": False,
        "handshake_contains_list_marker": False,
        "handshake_contains_did_prefix": False,
    }

    # Load spec from input/spec.json
    spec_path = os.path.join(input_dir, "spec.json")
    spec, spec_err = read_json_file(spec_path)
    # We will use spec values if available; but do not award credit for reading spec alone.
    expected_aliases = []
    expected_messages = []
    expected_secret = None
    expected_session_id = None
    expected_relay_url = None
    if isinstance(spec, dict):
        expected_aliases = spec.get("aliases", [])
        expected_messages = spec.get("messages", [])
        expected_secret = spec.get("secret")
        expected_session_id = spec.get("sessionId")
        expected_relay_url = spec.get("relayUrl")

    # 1) identities.json
    identities_path = os.path.join(output_dir, "identities.json")
    if os.path.isfile(identities_path):
        checks["has_identities_file"] = True
        identities, err = read_json_file(identities_path)
        if err is None and isinstance(identities, list):
            checks["identities_json_valid"] = True

            # Validate aliases and object structure
            # Must be exactly len(expected_aliases) entries and aliases exactly match spec aliases
            alias_set_ok = False
            fields_present_ok = True
            pubkey_format_ok = True
            did_match_ok = True

            if isinstance(expected_aliases, list) and len(expected_aliases) > 0:
                # Build alias set from identities
                aliases_in_file = []
                for item in identities:
                    if not isinstance(item, dict):
                        fields_present_ok = False
                        continue
                    # Required fields
                    required_fields = ["alias", "localId", "did", "publicKeyHex"]
                    for f in required_fields:
                        if f not in item or (f == "localId" and (not isinstance(item[f], str) or item[f].strip() == "")):
                            fields_present_ok = False
                    # Capture alias
                    aliases_in_file.append(item.get("alias"))
                # Check alias exact match
                try:
                    alias_set_ok = set(aliases_in_file) == set(expected_aliases) and len(identities) == len(expected_aliases)
                except Exception:
                    alias_set_ok = False

                # Now validate each identity's pubkey and DID
                for item in identities if isinstance(identities, list) else []:
                    if not isinstance(item, dict):
                        continue
                    pk = item.get("publicKeyHex")
                    did = item.get("did")
                    if not validate_pubkey_hex_32b(pk):
                        pubkey_format_ok = False
                    expected_did_prefix = "did:claw:ed25519:"
                    if not (isinstance(did, str) and did.startswith(expected_did_prefix) and pk and did == expected_did_prefix + pk):
                        did_match_ok = False

            checks["identities_aliases_correct"] = alias_set_ok
            checks["identities_fields_present"] = fields_present_ok
            checks["identities_pubkey_format"] = pubkey_format_ok
            checks["identities_did_matches_pubkey"] = did_match_ok

    # Build alias -> publicKeyHex map for cross-file checks
    alias_to_pk = {}
    if checks["identities_json_valid"] and checks["identities_fields_present"]:
        identities, _ = read_json_file(identities_path)
        if isinstance(identities, list):
            for item in identities:
                if isinstance(item, dict) and "alias" in item and "publicKeyHex" in item:
                    alias_to_pk[item["alias"]] = item["publicKeyHex"]

    # 2) signed_messages.json
    signed_path = os.path.join(output_dir, "signed_messages.json")
    if os.path.isfile(signed_path):
        checks["has_signed_messages_file"] = True
        signed, err = read_json_file(signed_path)
        if err is None and isinstance(signed, list):
            checks["signed_messages_json_valid"] = True

            # Expected count: |aliases| * |messages|
            expected_pairs_count = 0
            if isinstance(expected_aliases, list) and isinstance(expected_messages, list):
                expected_pairs_count = len(expected_aliases) * len(expected_messages)

            count_ok = (len(signed) == expected_pairs_count) if expected_pairs_count > 0 else False
            checks["signed_messages_count_correct"] = count_ok

            # Validate entries
            fields_present_ok = True
            pairs_set = set()
            all_pairs_covered = False
            pubkey_format_ok = True
            pubkeys_match_ok = True
            signature_format_ok = True
            verified_true_ok = True
            payloads_match_spec_ok = True

            # Prepare expected pairs set for coverage check
            expected_pairs = set()
            if isinstance(expected_aliases, list) and isinstance(expected_messages, list):
                for a in expected_aliases:
                    for m in expected_messages:
                        expected_pairs.add((a, m))

            for entry in signed:
                if not isinstance(entry, dict):
                    fields_present_ok = False
                    continue
                for rf in ["alias", "payload", "publicKeyHex", "signatureHex", "verified"]:
                    if rf not in entry:
                        fields_present_ok = False

                alias = entry.get("alias")
                payload = entry.get("payload")
                pk = entry.get("publicKeyHex")
                sig = entry.get("signatureHex")
                ver = entry.get("verified")

                # Track pair
                if isinstance(alias, str) and isinstance(payload, str):
                    pairs_set.add((alias, payload))

                # Payload must match one of spec messages
                if isinstance(expected_messages, list) and payload not in expected_messages:
                    payloads_match_spec_ok = False

                # Public key format in messages
                if not validate_pubkey_hex_32b(pk):
                    pubkey_format_ok = False

                # Pubkey must match identities for alias
                if alias in alias_to_pk:
                    if alias_to_pk.get(alias) != pk:
                        pubkeys_match_ok = False
                else:
                    # If identities missing or alias not found, cannot confirm match
                    pubkeys_match_ok = False

                # Signature format
                if not validate_signature_hex_64b(sig):
                    signature_format_ok = False

                # verified must be literal boolean True
                if ver is not True:
                    verified_true_ok = False

            # All pairs covered: no duplicates and equals expected set
            all_pairs_covered = (pairs_set == expected_pairs)

            checks["signed_messages_fields_present"] = fields_present_ok
            checks["signed_messages_pairs_covered"] = all_pairs_covered
            checks["signed_messages_pubkey_format"] = pubkey_format_ok
            checks["signed_messages_pubkeys_match"] = pubkeys_match_ok
            checks["signed_messages_signature_format"] = signature_format_ok
            checks["signed_messages_verified_true"] = verified_true_ok
            checks["signed_messages_payloads_match_spec"] = payloads_match_spec_ok

    # 3) encryption_demo.json
    encryption_path = os.path.join(output_dir, "encryption_demo.json")
    if os.path.isfile(encryption_path):
        checks["has_encryption_demo_file"] = True
        enc, err = read_json_file(encryption_path)
        if err is None and isinstance(enc, dict):
            checks["encryption_json_valid"] = True

            sk = enc.get("sessionKeyHex")
            nonce = enc.get("nonceHex")
            ct = enc.get("ciphertextHex")
            dec = enc.get("decrypted")

            if validate_pubkey_hex_32b(sk):  # same 64-hex validation as 32-byte key
                checks["encryption_sessionkey_format"] = True
            if isinstance(nonce, str) and len(nonce) == 48 and is_lower_hex(nonce):
                checks["encryption_nonce_format"] = True
            if validate_hex_min_len_even(ct, 32):
                checks["encryption_ciphertext_format"] = True
            if expected_secret is not None and isinstance(dec, str) and dec == expected_secret:
                checks["encryption_decrypted_matches_secret"] = True

    # 4) handshake.md
    handshake_path = os.path.join(output_dir, "handshake.md")
    if os.path.isfile(handshake_path):
        checks["has_handshake_file"] = True
        content, err = read_text_file(handshake_path)
        if err is None and isinstance(content, str):
            # Length: at least 150 words
            if word_count(content) >= 150:
                checks["handshake_length_ok"] = True

            # Must include session id and relay URL from spec
            if isinstance(expected_session_id, str) and isinstance(expected_relay_url, str):
                if (expected_session_id in content) and (expected_relay_url in content):
                    checks["handshake_contains_session_and_relay"] = True

            # Must contain words "challenge" and "signature" (case-insensitive)
            low = content.lower()
            if ("challenge" in low) and ("signature" in low):
                checks["handshake_contains_terms"] = True

            # Must contain at least one line starting with list marker
            list_marker_ok = False
            for line in content.splitlines():
                if line.startswith("- ") or line.startswith("* ") or re.match(r"^\s*\d+\.\s+", line):
                    list_marker_ok = True
                    break
            checks["handshake_contains_list_marker"] = list_marker_ok

            # Must contain substring did:claw:ed25519:
            if "did:claw:ed25519:" in content:
                checks["handshake_contains_did_prefix"] = True

    # Compute reward: proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Ensure no-op baseline is exactly 0.0 if output is missing or empty
    # If none of the "has_*_file" checks are true, reward must be 0.0
    has_any_output_file = any([
        checks["has_identities_file"],
        checks["has_signed_messages_file"],
        checks["has_encryption_demo_file"],
        checks["has_handshake_file"],
    ])

    reward = 0.0
    if has_any_output_file and total_checks > 0:
        reward = passed / total_checks

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()