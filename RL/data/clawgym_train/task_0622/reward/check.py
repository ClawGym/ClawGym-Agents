import json
import os
import sys
import hashlib
import base64
import re

def join_root(root, rel_path):
    return os.path.join(root, rel_path.replace("/", os.sep))

def file_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

# Minimal DER parsing utilities for RSA public key (SPKI or PKCS#1) and PKCS#1 v1.5 verification

class DerParseError(Exception):
    pass

def _der_read_length(data: bytes, i: int):
    if i >= len(data):
        raise DerParseError("Unexpected end while reading length")
    first = data[i]
    i += 1
    if first < 0x80:
        return first, i
    num_bytes = first & 0x7F
    if num_bytes == 0 or i + num_bytes > len(data):
        raise DerParseError("Invalid DER length")
    length = 0
    for _ in range(num_bytes):
        length = (length << 8) | data[i]
        i += 1
    return length, i

def _der_expect_tag(data: bytes, i: int, tag: int):
    if i >= len(data) or data[i] != tag:
        raise DerParseError(f"Expected tag {hex(tag)} at {i}")
    i += 1
    length, i = _der_read_length(data, i)
    end = i + length
    if end > len(data):
        raise DerParseError("DER content exceeds buffer")
    return data[i:end], end

def _der_read_integer_as_int(data: bytes, i: int):
    content, end = _der_expect_tag(data, i, 0x02)  # INTEGER
    # Strip leading zero if present to enforce positive
    if len(content) > 0 and content[0] == 0x00:
        content = content[1:]
    if len(content) == 0:
        raise DerParseError("Empty INTEGER")
    return int.from_bytes(content, "big"), end

def parse_rsa_public_key_from_der_spki(der: bytes):
    # SubjectPublicKeyInfo
    spki_seq, pos = _der_expect_tag(der, 0, 0x30)  # SEQUENCE
    # Inside spki_seq
    i = 0
    # AlgorithmIdentifier (ignore details)
    _, alg_end = _der_expect_tag(spki_seq, i, 0x30)  # SEQUENCE
    i = alg_end
    # subjectPublicKey BIT STRING
    bitstr, i = _der_expect_tag(spki_seq, i, 0x03)
    if len(bitstr) < 1:
        raise DerParseError("Invalid BIT STRING")
    unused_bits = bitstr[0]
    if unused_bits != 0:
        raise DerParseError("Unsupported BIT STRING with unused bits")
    rsa_der = bitstr[1:]
    # RSAPublicKey
    rsa_seq, _ = _der_expect_tag(rsa_der, 0, 0x30)
    j = 0
    n, j = _der_read_integer_as_int(rsa_seq, j)
    e, j = _der_read_integer_as_int(rsa_seq, j)
    return n, e

def parse_rsa_public_key_from_der_pkcs1(der: bytes):
    # RSAPublicKey ::= SEQUENCE { modulus INTEGER, publicExponent INTEGER }
    rsa_seq, pos = _der_expect_tag(der, 0, 0x30)
    i = 0
    n, i = _der_read_integer_as_int(rsa_seq, i)
    e, i = _der_read_integer_as_int(rsa_seq, i)
    return n, e

def load_pem_public_key(path: str):
    # Supports "-----BEGIN PUBLIC KEY-----" (SPKI) and "-----BEGIN RSA PUBLIC KEY-----" (PKCS#1)
    text = open(path, "rb").read().decode("ascii", errors="strict")
    def extract_pem_block(label):
        m = re.search(r"-----BEGIN " + re.escape(label) + r"-----\r?\n([A-Za-z0-9+/=\r\n]+)-----END " + re.escape(label) + r"-----", text, flags=re.MULTILINE)
        if not m:
            return None
        b64_body = re.sub(r"\s+", "", m.group(1))
        return base64.b64decode(b64_body)
    der = extract_pem_block("PUBLIC KEY")
    if der is not None:
        try:
            return parse_rsa_public_key_from_der_spki(der)
        except DerParseError:
            pass
    der = extract_pem_block("RSA PUBLIC KEY")
    if der is not None:
        try:
            return parse_rsa_public_key_from_der_pkcs1(der)
        except DerParseError:
            pass
    # Also try CERTIFICATE (extract SPKI inside X.509 cert) as a fallback
    cert_der = extract_pem_block("CERTIFICATE")
    if cert_der is not None:
        # Minimal X.509 parse: Certificate ::= SEQUENCE { tbsCertificate SEQUENCE, signatureAlgorithm, signatureValue }
        cert_seq, pos = _der_expect_tag(cert_der, 0, 0x30)
        i = 0
        tbs, i = _der_expect_tag(cert_seq, i, 0x30)
        # TBS Certificate has many fields; we need subjectPublicKeyInfo which is usually after version/serial/signature/issuer/validity/subject
        # This simplistic parser scans for BIT STRING that decodes to RSAPublicKey within SPKI
        # We search within tbs for a SPKI structure by looking for a SEQUENCE (spki) that contains BIT STRING with RSAPublicKey.
        k = 0
        while k < len(tbs):
            try:
                # Peek tag
                if tbs[k] != 0x30:
                    # Skip unknown TLV
                    # Read generic TLV
                    tag = tbs[k]
                    _, nxt = _der_expect_tag(tbs, k, tag)
                    k = nxt
                    continue
                seq_bytes, nxt = _der_expect_tag(tbs, k, 0x30)
                # Try interpret as SPKI
                x = 0
                _, x_alg_end = _der_expect_tag(seq_bytes, x, 0x30)
                x = x_alg_end
                bitstr, x = _der_expect_tag(seq_bytes, x, 0x03)
                if len(bitstr) >= 1 and bitstr[0] == 0x00:
                    rsa_der = bitstr[1:]
                    rsa_seq, _ = _der_expect_tag(rsa_der, 0, 0x30)
                    y = 0
                    n, y = _der_read_integer_as_int(rsa_seq, y)
                    e, y = _der_read_integer_as_int(rsa_seq, y)
                    return n, e
                k = nxt
            except DerParseError:
                # Not SPKI, continue scanning
                k = nxt if 'nxt' in locals() else k + 1
        raise DerParseError("Could not locate SPKI in certificate")
    raise DerParseError("Unsupported public key PEM format")

def pkcs1v15_verify_sha256(public_key, msg: bytes, sig: bytes) -> bool:
    n, e = public_key
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    s_int = int.from_bytes(sig, "big")
    if s_int <= 0 or s_int >= n:
        return False
    em_int = pow(s_int, e, n)
    em = em_int.to_bytes(k, "big")
    # EMSA-PKCS1-v1_5 encoding check
    if len(em) < 11:
        return False
    if not (em[0] == 0x00 and em[1] == 0x01):
        return False
    # PS = 0xFF ... 0xFF, then 0x00 separator
    try:
        idx_zero = em.index(b"\x00", 2)
    except ValueError:
        return False
    ps = em[2:idx_zero]
    if len(ps) < 8 or any(b != 0xFF for b in ps):
        return False
    # DigestInfo for SHA-256
    digest = hashlib.sha256(msg).digest()
    digest_info_prefix = bytes.fromhex(
        "3031300d060960864801650304020105000420"
    )
    expected = digest_info_prefix + digest
    trailer = em[idx_zero + 1:]
    return trailer == expected

def is_lowercase_hex(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    for ch in s:
        if ch not in "0123456789abcdef":
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected paths (relative)
    app_rel = "input/artifacts/app_config.json"
    change_rel = "input/artifacts/CHANGELOG.md"
    pubkey_rel = "input/keys/test_public_key.txt"
    sig_app_rel = "output/signatures/app_config.json.sig.txt"
    sig_change_rel = "output/signatures/CHANGELOG.md.sig.txt"
    manifest_rel = "output/manifest.json"
    readme_rel = "output/README.md"

    # Absolute paths
    app_path = join_root(workspace_root, app_rel)
    change_path = join_root(workspace_root, change_rel)
    pubkey_path = join_root(workspace_root, pubkey_rel)
    sig_app_path = join_root(workspace_root, sig_app_rel)
    sig_change_path = join_root(workspace_root, sig_change_rel)
    manifest_path = join_root(workspace_root, manifest_rel)
    readme_path = join_root(workspace_root, readme_rel)

    checks = {
        "sig_app_exists": False,
        "sig_changelog_exists": False,
        "manifest_exists": False,
        "manifest_schema_valid": False,
        "manifest_paths_match": False,
        "manifest_hashes_match": False,
        "sig_app_verifies": False,
        "sig_changelog_verifies": False,
        "readme_exists": False,
        "readme_mentions_algo": False,
        "readme_instructions_paths": False,
        "readme_warns_private_key": False,
    }

    # Signature files existence
    if os.path.isfile(sig_app_path):
        checks["sig_app_exists"] = True
    if os.path.isfile(sig_change_path):
        checks["sig_changelog_exists"] = True

    # Manifest checks
    manifest_data = None
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            # Schema validation
            schema_ok = isinstance(manifest_data, dict) and "artifacts" in manifest_data and len(manifest_data.keys()) == 1
            artifacts_list = manifest_data.get("artifacts", None)
            schema_ok = schema_ok and isinstance(artifacts_list, list) and len(artifacts_list) == 2
            if schema_ok:
                per_item_ok = True
                for item in artifacts_list:
                    if not (isinstance(item, dict) and set(item.keys()) == {"artifact", "signature", "sha256"}):
                        per_item_ok = False
                        break
                schema_ok = schema_ok and per_item_ok
            checks["manifest_schema_valid"] = bool(schema_ok)

            if checks["manifest_schema_valid"]:
                # Paths match check (order-insensitive)
                required_pairs = {
                    (app_rel, sig_app_rel),
                    (change_rel, sig_change_rel),
                }
                got_pairs = set()
                for item in artifacts_list:
                    got_pairs.add((item.get("artifact"), item.get("signature")))
                checks["manifest_paths_match"] = (got_pairs == required_pairs)

                # Hashes match
                try:
                    app_bytes = file_bytes(app_path)
                    change_bytes = file_bytes(change_path)
                    app_hash = sha256_hex(app_bytes)
                    change_hash = sha256_hex(change_bytes)
                    # Build mapping artifact->expected hash
                    expected_hashes = {
                        app_rel: app_hash,
                        change_rel: change_hash,
                    }
                    all_match = True
                    for item in artifacts_list:
                        art = item["artifact"]
                        h = item["sha256"]
                        if art not in expected_hashes:
                            all_match = False
                            break
                        if not is_lowercase_hex(h):
                            all_match = False
                            break
                        if h != expected_hashes[art]:
                            all_match = False
                            break
                    checks["manifest_hashes_match"] = all_match
                except Exception:
                    checks["manifest_hashes_match"] = False
        except Exception:
            # Any failure leaves schema/path/hash checks as False
            pass

    # Signature verification (only if signature files exist and public key exists)
    if checks["sig_app_exists"] and checks["sig_changelog_exists"] and os.path.isfile(pubkey_path):
        try:
            public_key = load_pem_public_key(pubkey_path)
            # Verify app_config.json
            try:
                app_bytes = file_bytes(app_path)
                sig_bytes = file_bytes(sig_app_path)
                if pkcs1v15_verify_sha256(public_key, app_bytes, sig_bytes):
                    checks["sig_app_verifies"] = True
            except Exception:
                checks["sig_app_verifies"] = False
            # Verify CHANGELOG.md
            try:
                change_bytes = file_bytes(change_path)
                sig_bytes2 = file_bytes(sig_change_path)
                if pkcs1v15_verify_sha256(public_key, change_bytes, sig_bytes2):
                    checks["sig_changelog_verifies"] = True
            except Exception:
                checks["sig_changelog_verifies"] = False
        except Exception:
            # Could not load public key or verify; leave as False
            pass

    # README checks
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        try:
            content = open(readme_path, "r", encoding="utf-8", errors="replace").read()
            low = content.lower()
            # Algorithm mention: PKCS#1 v1.5 and SHA-256
            mentions_pkcs = ("pkcs#1 v1.5" in low) or ("pkcs1 v1.5" in low)
            mentions_sha256 = ("sha-256" in low) or ("sha256" in low)
            checks["readme_mentions_algo"] = bool(mentions_pkcs and mentions_sha256)
            # Instructions paths: ensure public key path and both artifacts and signatures paths appear
            required_strings = [
                pubkey_rel,
                app_rel,
                sig_app_rel,
                change_rel,
                sig_change_rel,
            ]
            checks["readme_instructions_paths"] = all(s in content for s in required_strings)
            # Security notes: must include "private key" and one of "never"/"do not share"/"keep secret"
            has_private_key_phrase = "private key" in low
            has_warning_word = ("never" in low) or ("do not share" in low) or ("keep secret" in low)
            checks["readme_warns_private_key"] = bool(has_private_key_phrase and has_warning_word)
        except Exception:
            # Leave as False if any error
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty and no files produced, reward should be 0.0
    # This naturally holds because no checks would pass.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()