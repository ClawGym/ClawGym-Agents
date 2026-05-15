import json
import os
import re
import sys
import hashlib
import hmac

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def is_base64ish(s):
    if not isinstance(s, str) or not s:
        return False
    # Base64 characters and padding
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", s):
        return False
    # Length should be multiple of 4 for standard base64
    if len(s) % 4 != 0:
        return False
    return True

def is_hex64_lower(s):
    return isinstance(s, str) and re.fullmatch(r"[0-9a-f]{64}", s) is not None

def is_number_not_bool(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def sha256_hex(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()

def hmac_sha256_hex(key_bytes, data_bytes):
    return hmac.new(key_bytes, data_bytes, hashlib.sha256).hexdigest()

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Envelopes - small
        "small_envelope_exists": False,
        "small_envelope_json_valid": False,
        "small_envelope_version_ok": False,
        "small_envelope_encrypted_obj": False,
        "small_envelope_type_direct": False,
        "small_envelope_algorithm_rsa_oaep": False,
        "small_envelope_encrypted_field_base64": False,
        "small_envelope_no_hybrid_fields": False,
        "small_envelope_signature_base64": False,
        "small_envelope_timestamp_number": False,

        # Envelopes - large
        "large_envelope_exists": False,
        "large_envelope_json_valid": False,
        "large_envelope_version_ok": False,
        "large_envelope_encrypted_obj": False,
        "large_envelope_type_hybrid": False,
        "large_envelope_algorithm_contains_aes256gcm": False,
        "large_envelope_required_fields_present_base64": False,
        "large_envelope_signature_base64": False,
        "large_envelope_timestamp_number": False,

        # Fingerprints
        "fingerprints_exists": False,
        "fingerprints_json_valid": False,
        "fingerprints_keys_present": False,
        "fingerprints_values_format": False,
        "fingerprint_alice_correct": False,
        "fingerprint_bob_correct": False,

        # HMACs
        "hmacs_exists": False,
        "hmacs_json_valid": False,
        "hmacs_keys_present": False,
        "hmacs_values_format": False,
        "hmac_small_correct": False,
        "hmac_large_correct": False,

        # README
        "readme_exists": False,
        "readme_length_ok": False,
        "readme_contains_keywords": False,
    }

    # Paths
    small_env_path = os.path.join(output_dir, "secure_envelopes", "alice_to_bob_small.json")
    large_env_path = os.path.join(output_dir, "secure_envelopes", "alice_to_bob_large.json")
    fingerprints_path = os.path.join(output_dir, "fingerprints.json")
    hmacs_path = os.path.join(output_dir, "hmacs.json")
    readme_path = os.path.join(output_dir, "readme.md")

    # 1) Validate small envelope
    if os.path.isfile(small_env_path):
        checks["small_envelope_exists"] = True
        ok, data = load_json(small_env_path)
        if ok and isinstance(data, dict):
            checks["small_envelope_json_valid"] = True
            if data.get("version") == "1.0":
                checks["small_envelope_version_ok"] = True
            enc = data.get("encrypted")
            if isinstance(enc, dict):
                checks["small_envelope_encrypted_obj"] = True
                if enc.get("type") == "direct":
                    checks["small_envelope_type_direct"] = True
                if enc.get("algorithm") == "RSA-OAEP":
                    checks["small_envelope_algorithm_rsa_oaep"] = True
                # base64 for 'encrypted'
                if "encrypted" in enc and is_base64ish(enc.get("encrypted")):
                    checks["small_envelope_encrypted_field_base64"] = True
                # Ensure hybrid fields absent
                hybrid_absent = not any(k in enc for k in ["encryptedKey", "iv", "authTag"])
                if hybrid_absent:
                    checks["small_envelope_no_hybrid_fields"] = True
            # signature base64-like
            if "signature" in data and is_base64ish(data.get("signature")):
                checks["small_envelope_signature_base64"] = True
            # timestamp number
            if "timestamp" in data and is_number_not_bool(data.get("timestamp")):
                checks["small_envelope_timestamp_number"] = True

    # 1) Validate large envelope
    if os.path.isfile(large_env_path):
        checks["large_envelope_exists"] = True
        ok, data = load_json(large_env_path)
        if ok and isinstance(data, dict):
            checks["large_envelope_json_valid"] = True
            if data.get("version") == "1.0":
                checks["large_envelope_version_ok"] = True
            enc = data.get("encrypted")
            if isinstance(enc, dict):
                checks["large_envelope_encrypted_obj"] = True
                if enc.get("type") == "hybrid":
                    checks["large_envelope_type_hybrid"] = True
                alg = enc.get("algorithm", "")
                if isinstance(alg, str) and "AES-256-GCM" in alg:
                    checks["large_envelope_algorithm_contains_aes256gcm"] = True
                # required fields: encryptedKey, iv, authTag, encrypted base64-like
                required = ["encryptedKey", "iv", "authTag", "encrypted"]
                present_and_b64 = all((k in enc and is_base64ish(enc.get(k))) for k in required)
                if present_and_b64:
                    checks["large_envelope_required_fields_present_base64"] = True
            # signature base64-like
            if "signature" in data and is_base64ish(data.get("signature")):
                checks["large_envelope_signature_base64"] = True
            # timestamp number
            if "timestamp" in data and is_number_not_bool(data.get("timestamp")):
                checks["large_envelope_timestamp_number"] = True

    # 2) Fingerprints
    if os.path.isfile(fingerprints_path):
        checks["fingerprints_exists"] = True
        ok, fp = load_json(fingerprints_path)
        if ok and isinstance(fp, dict):
            checks["fingerprints_json_valid"] = True
            if "alice_public" in fp and "bob_public" in fp:
                checks["fingerprints_keys_present"] = True
            # format
            values_format_ok = (
                isinstance(fp.get("alice_public"), str) and
                isinstance(fp.get("bob_public"), str) and
                is_hex64_lower(fp.get("alice_public")) and
                is_hex64_lower(fp.get("bob_public"))
            )
            if values_format_ok:
                checks["fingerprints_values_format"] = True

            # compute expected
            alice_pub_path = os.path.join(input_dir, "keys", "alice_public.txt")
            bob_pub_path = os.path.join(input_dir, "keys", "bob_public.txt")
            try:
                if os.path.isfile(alice_pub_path):
                    alice_bytes = read_bytes(alice_pub_path)
                    alice_hash = sha256_hex(alice_bytes)
                    if fp.get("alice_public") == alice_hash:
                        checks["fingerprint_alice_correct"] = True
                if os.path.isfile(bob_pub_path):
                    bob_bytes = read_bytes(bob_pub_path)
                    bob_hash = sha256_hex(bob_bytes)
                    if fp.get("bob_public") == bob_hash:
                        checks["fingerprint_bob_correct"] = True
            except Exception:
                # leave as False if any issue
                pass

    # 3) HMACs
    if os.path.isfile(hmacs_path):
        checks["hmacs_exists"] = True
        ok, hm = load_json(hmacs_path)
        if ok and isinstance(hm, dict):
            checks["hmacs_json_valid"] = True
            if "small" in hm and "large" in hm:
                checks["hmacs_keys_present"] = True
            # values are lowercase hex length 64
            vals_fmt = (
                isinstance(hm.get("small"), str) and
                isinstance(hm.get("large"), str) and
                is_hex64_lower(hm.get("small")) and
                is_hex64_lower(hm.get("large"))
            )
            if vals_fmt:
                checks["hmacs_values_format"] = True

            # compute expected using exact file bytes and secret bytes
            secret_path = os.path.join(input_dir, "shared_secret.txt")
            small_msg_path = os.path.join(input_dir, "messages", "small.txt")
            large_msg_path = os.path.join(input_dir, "messages", "large.txt")
            try:
                if os.path.isfile(secret_path) and os.path.isfile(small_msg_path):
                    key = read_bytes(secret_path)
                    small_bytes = read_bytes(small_msg_path)
                    expected_small = hmac_sha256_hex(key, small_bytes)
                    if hm.get("small") == expected_small:
                        checks["hmac_small_correct"] = True
                if os.path.isfile(secret_path) and os.path.isfile(large_msg_path):
                    key = read_bytes(secret_path)
                    large_bytes = read_bytes(large_msg_path)
                    expected_large = hmac_sha256_hex(key, large_bytes)
                    if hm.get("large") == expected_large:
                        checks["hmac_large_correct"] = True
            except Exception:
                pass

    # 4) README
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            lines = content.splitlines()
            if len(lines) <= 300:
                checks["readme_length_ok"] = True
            lower = content.lower()
            required_terms = ["direct", "hybrid", "hmac", "fingerprint", "security", "verification"]
            if all(term in lower for term in required_terms):
                checks["readme_contains_keywords"] = True
        except Exception:
            pass

    # Compute reward as average of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0: if no output directory or empty, reward stays 0.0 naturally
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()