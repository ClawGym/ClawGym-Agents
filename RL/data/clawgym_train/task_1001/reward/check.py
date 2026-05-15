import json
import os
import sys
import hashlib
import subprocess
import re

def is_lower_hex(s):
    return isinstance(s, str) and len(s) % 2 == 0 and re.fullmatch(r"[0-9a-f]+", s) is not None

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def run_openssl_ige_encrypt(plaintext: bytes, key_hex: str, iv_hex: str):
    # Uses system openssl for AES-256-IGE with no padding and no salt
    # Returns ciphertext bytes or None on failure
    try:
        proc = subprocess.run(
            ["openssl", "enc", "-aes-256-ige", "-K", key_hex, "-iv", iv_hex, "-nopad", "-nosalt"],
            input=plaintext,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout

def to_hex(b: bytes) -> str:
    return b.hex()

def from_hex(h: str) -> bytes:
    return bytes.fromhex(h)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "parsed_input_ok": False,
        "has_result_json": False,
        "has_notes_md": False,
        "fields_valid_format": False,
        "msg_key_correct": False,
        "aes_key_correct": False,
        "aes_iv_correct": False,
        "ciphertext_correct": False,
        "auth_key_id_correct": False,
        "packet_hex_correct": False,
        "notes_nonempty": False,
        "impl_optional_ok": False,
    }

    # Paths
    vectors_path = os.path.join(input_dir, "mtproto_vectors.json")
    result_path = os.path.join(output_dir, "mtproto", "result.json")
    notes_path = os.path.join(output_dir, "mtproto", "notes.md")
    impl_path = os.path.join(output_dir, "mtproto", "impl.py")

    # Load input vectors
    vectors = load_json(vectors_path)
    auth_key_bytes = None
    plaintext_bytes = None
    if isinstance(vectors, dict) and "auth_key" in vectors and "plaintext" in vectors:
        try:
            ak_hex = vectors["auth_key"]
            pt_hex = vectors["plaintext"]
            if is_lower_hex(ak_hex) and is_lower_hex(pt_hex):
                auth_key_bytes = from_hex(ak_hex)
                plaintext_bytes = from_hex(pt_hex)
                # Validate lengths: auth_key should be 32 bytes as per task; plaintext multiple of 16
                if len(auth_key_bytes) == 32 and (len(plaintext_bytes) % 16 == 0) and len(plaintext_bytes) > 0:
                    checks["parsed_input_ok"] = True
        except Exception:
            pass

    # Check existence of outputs
    if os.path.isfile(result_path):
        checks["has_result_json"] = True
    if os.path.isfile(notes_path):
        checks["has_notes_md"] = True
        try:
            if os.path.getsize(notes_path) > 0:
                checks["notes_nonempty"] = True
        except Exception:
            pass

    # Optional impl.py checks (does not affect positive scoring)
    if os.path.isfile(impl_path):
        try:
            with open(impl_path, "r", encoding="utf-8") as f:
                impl_text = f.read()
            if ("def derive_keys" in impl_text and
                "def aes_ige_encrypt" in impl_text and
                ("AES-256-IGE" in impl_text or "MTProto" in impl_text or "aes-256-ige" in impl_text)):
                checks["impl_optional_ok"] = True
        except Exception:
            pass

    # If no result.json or input not parsed, we cannot proceed with core checks
    if not checks["has_result_json"] or not checks["parsed_input_ok"]:
        # Compute reward at end
        reward = 0.0
        result = {"reward": reward}
        result.update(checks)
        print(json.dumps(result))
        return

    # Load result.json
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            result_json = json.load(f)
    except Exception:
        result_json = None

    # Validate fields and formatting
    fields_ok = False
    if isinstance(result_json, dict):
        required_fields = ["auth_key_id", "msg_key", "aes_key", "aes_iv", "ciphertext", "packet_hex"]
        if all(k in result_json for k in required_fields):
            try:
                auth_key_id_hex = result_json["auth_key_id"]
                msg_key_hex = result_json["msg_key"]
                aes_key_hex = result_json["aes_key"]
                aes_iv_hex = result_json["aes_iv"]
                ciphertext_hex = result_json["ciphertext"]
                packet_hex = result_json["packet_hex"]

                # Format checks
                fmt_ok = True
                # Lowercase hex and lengths
                if not (is_lower_hex(auth_key_id_hex) and len(auth_key_id_hex) == 16):
                    fmt_ok = False
                if not (is_lower_hex(msg_key_hex) and len(msg_key_hex) == 32):
                    fmt_ok = False
                if not (is_lower_hex(aes_key_hex) and len(aes_key_hex) == 64):
                    fmt_ok = False
                if not (is_lower_hex(aes_iv_hex) and len(aes_iv_hex) == 64):
                    fmt_ok = False
                if not (is_lower_hex(ciphertext_hex) and len(ciphertext_hex) % 32 == 0 and len(ciphertext_hex) > 0):
                    fmt_ok = False
                if not is_lower_hex(packet_hex):
                    fmt_ok = False

                if fmt_ok:
                    checks["fields_valid_format"] = True
                    fields_ok = True
            except Exception:
                pass

    # If formatting OK, recompute expected values and compare
    if fields_ok and checks["parsed_input_ok"]:
        # Compute msg_key = SHA256(plaintext || auth_key)[8:24]
        msg_key_bytes = sha256(plaintext_bytes + auth_key_bytes)[8:24]
        msg_key_ok = (to_hex(msg_key_bytes) == result_json["msg_key"])
        checks["msg_key_correct"] = msg_key_ok

        # Compute x and y per task (with provided slicing)
        x = sha256(msg_key_bytes + auth_key_bytes[:36])
        y = sha256(auth_key_bytes[40:76] + msg_key_bytes)

        # Derive 32-byte aes_key and aes_iv using the complete MTProto 2.0 pattern
        # Given the task's abbreviated formula, we extend it to 32 bytes as standard:
        # aes_key = x[:8] || y[8:24] || x[24:32]
        # aes_iv  = y[:8] || x[8:16] || y[24:32] || x[16:24]
        aes_key_bytes = x[0:8] + y[8:24] + x[24:32]
        aes_iv_bytes = y[0:8] + x[8:16] + y[24:32] + x[16:24]

        checks["aes_key_correct"] = (to_hex(aes_key_bytes) == result_json["aes_key"])
        checks["aes_iv_correct"] = (to_hex(aes_iv_bytes) == result_json["aes_iv"])

        # Compute ciphertext using AES-256-IGE with 32-byte IV, no padding
        ciphertext_calc = run_openssl_ige_encrypt(plaintext_bytes, to_hex(aes_key_bytes), to_hex(aes_iv_bytes))
        if ciphertext_calc is not None:
            ciphertext_hex_calc = to_hex(ciphertext_calc)
            checks["ciphertext_correct"] = (ciphertext_hex_calc == result_json["ciphertext"])
        else:
            # Cannot verify without OpenSSL; leave as False
            checks["ciphertext_correct"] = False

        # Compute auth_key_id = SHA256(auth_key)[:8]
        auth_key_id_bytes = sha256(auth_key_bytes)[:8]
        checks["auth_key_id_correct"] = (to_hex(auth_key_id_bytes) == result_json["auth_key_id"])

        # Check packet_hex = auth_key_id || msg_key || ciphertext
        expected_packet_hex = to_hex(auth_key_id_bytes) + to_hex(msg_key_bytes) + result_json["ciphertext"]
        checks["packet_hex_correct"] = (expected_packet_hex == result_json["packet_hex"])

    # Compute reward: average of core deterministic checks.
    core_checks = [
        "has_result_json",
        "has_notes_md",
        "fields_valid_format",
        "msg_key_correct",
        "aes_key_correct",
        "aes_iv_correct",
        "ciphertext_correct",
        "auth_key_id_correct",
        "packet_hex_correct",
        "notes_nonempty",
    ]
    # If outputs missing, ensure reward is 0.0 (no-op baseline)
    passed = sum(1 for k in core_checks if checks.get(k, False))
    total = len(core_checks)
    reward = (passed / total) if total > 0 else 0.0
    # No credit if result.json missing or empty core artifacts
    if not checks["has_result_json"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()