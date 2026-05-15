import base64
import hashlib
import json
import os
import sys

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks (all False until verified)
checks = {
    "cryptography_available": False,             # not counted toward reward
    "input_config_read": False,                  # not counted toward reward
    "input_message_read": False,                 # not counted toward reward
    "keys_exist_private": False,
    "keys_exist_public": False,
    "keys_are_ed25519": False,
    "key_pair_matches": False,
    "agent_id_file_exists": False,
    "agent_id_matches": False,
    "signature_file_exists": False,
    "message_signature_valid": False,
    "agent_card_exists": False,
    "agent_card_fields_match_config": False,
    "agent_card_signature_valid": False,
    "security_notes_present": False,
}

# Try importing cryptography
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    checks["cryptography_available"] = True
except Exception:
    checks["cryptography_available"] = False

# Read inputs
config_path = os.path.join(input_dir, "agent_config.json")
message_path = os.path.join(input_dir, "message.txt")

config = None
message_bytes = None

# Read config
try:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    checks["input_config_read"] = True
except Exception:
    config = None

# Read message (binary, exact)
try:
    with open(message_path, "rb") as f:
        message_bytes = f.read()
    checks["input_message_read"] = True
except Exception:
    message_bytes = None

# Proceed only if config readable for expected file names
name = None
if isinstance(config, dict):
    name = config.get("name")

# Prepare expected paths if name is available
private_key_path = None
public_key_path = None
if isinstance(name, str) and name != "":
    private_key_path = os.path.join(output_dir, "keys", f"{name}_private.pem")
    public_key_path = os.path.join(output_dir, "keys", f"{name}_public.pem")

# Check key file existence
if private_key_path and os.path.isfile(private_key_path):
    checks["keys_exist_private"] = True
if public_key_path and os.path.isfile(public_key_path):
    checks["keys_exist_public"] = True

loaded_private = None
loaded_public = None
public_pem_bytes = None

# Load keys and verify Ed25519 + pairing
if checks["cryptography_available"] and checks["keys_exist_private"] and checks["keys_exist_public"]:
    try:
        with open(private_key_path, "rb") as f:
            private_pem = f.read()
        with open(public_key_path, "rb") as f:
            public_pem_bytes = f.read()

        # Load keys
        try:
            loaded_private = serialization.load_pem_private_key(private_pem, password=None)
        except Exception:
            loaded_private = None

        try:
            loaded_public = serialization.load_pem_public_key(public_pem_bytes)
        except Exception:
            loaded_public = None

        # Check Ed25519 type
        if isinstance(loaded_private, ed25519.Ed25519PrivateKey) and isinstance(loaded_public, ed25519.Ed25519PublicKey):
            checks["keys_are_ed25519"] = True

        # Check key pairing by comparing public bytes
        if loaded_private is not None and loaded_public is not None:
            try:
                derived_public = loaded_private.public_key()
                derived_pub_bytes = derived_public.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                )
                saved_pub_bytes = loaded_public.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                )
                if derived_pub_bytes == saved_pub_bytes:
                    checks["key_pair_matches"] = True
            except Exception:
                pass
    except Exception:
        pass

# Agent ID checks
agent_id_path = os.path.join(output_dir, "agent_id.txt")
expected_agent_id = None

# Compute expected agent ID from raw public key PEM bytes, truncated 32 hex chars
if public_pem_bytes is not None:
    try:
        expected_agent_id = hashlib.sha256(public_pem_bytes).hexdigest()[:32]
    except Exception:
        expected_agent_id = None

# Read agent_id.txt and compare exact content
if os.path.isfile(agent_id_path):
    checks["agent_id_file_exists"] = True
    try:
        with open(agent_id_path, "rb") as f:
            content = f.read()
        # Exact match required: no trailing spaces or newline
        try:
            file_text = content.decode("utf-8")
        except Exception:
            file_text = None
        if expected_agent_id is not None and isinstance(file_text, str) and file_text == expected_agent_id:
            checks["agent_id_matches"] = True
    except Exception:
        pass

# Message signature verification
signature_path = os.path.join(output_dir, "signature.txt")
if os.path.isfile(signature_path):
    checks["signature_file_exists"] = True

if checks["signature_file_exists"] and checks["cryptography_available"] and isinstance(loaded_public, ed25519.Ed25519PublicKey) and isinstance(message_bytes, (bytes, bytearray)):
    try:
        with open(signature_path, "r", encoding="utf-8") as f:
            sig_b64 = f.read().strip()
        sig_bytes = base64.b64decode(sig_b64, validate=True)
        # Verify signature
        loaded_public.verify(sig_bytes, message_bytes)
        checks["message_signature_valid"] = True
    except Exception:
        checks["message_signature_valid"] = False

# Agent Card validation
agent_card_path = os.path.join(output_dir, "agent_card.json")
agent_card = None
if os.path.isfile(agent_card_path):
    checks["agent_card_exists"] = True
    try:
        with open(agent_card_path, "r", encoding="utf-8") as f:
            agent_card = json.load(f)
    except Exception:
        agent_card = None

# Agent Card fields match config and version/agent_id
if isinstance(agent_card, dict) and isinstance(config, dict):
    try:
        required_fields = ["agent_id", "name", "description", "endpoint", "capabilities", "version", "signature"]
        has_all = all(k in agent_card for k in required_fields)
        if has_all:
            fields_match = True
            # agent_id
            if not (isinstance(agent_card.get("agent_id"), str) and expected_agent_id is not None and agent_card.get("agent_id") == expected_agent_id):
                fields_match = False
            # version
            if agent_card.get("version") != "1.0.0":
                fields_match = False
            # exact metadata matches config
            if agent_card.get("name") != config.get("name"):
                fields_match = False
            if agent_card.get("description") != config.get("description"):
                fields_match = False
            if agent_card.get("endpoint") != config.get("endpoint"):
                fields_match = False
            # capabilities must be an array and equal to config's capabilities
            caps = agent_card.get("capabilities")
            cfg_caps = config.get("capabilities")
            if not isinstance(caps, list):
                fields_match = False
            else:
                if caps != cfg_caps:
                    fields_match = False

            if fields_match:
                checks["agent_card_fields_match_config"] = True
    except Exception:
        pass

# Agent Card signature verification: remove 'signature', serialize with sorted keys, default separators, UTF-8
if isinstance(agent_card, dict) and checks["cryptography_available"] and isinstance(loaded_public, ed25519.Ed25519PublicKey):
    try:
        sig_b64 = agent_card.get("signature")
        if isinstance(sig_b64, str):
            sig_bytes = base64.b64decode(sig_b64, validate=True)
            unsigned = dict(agent_card)
            unsigned.pop("signature", None)
            # default Python json separators with sort_keys=True, ensure_ascii=True
            canonical = json.dumps(unsigned, sort_keys=True)
            canonical_bytes = canonical.encode("utf-8")
            loaded_public.verify(sig_bytes, canonical_bytes)
            checks["agent_card_signature_valid"] = True
    except Exception:
        checks["agent_card_signature_valid"] = False

# Security notes presence
security_notes_path = os.path.join(output_dir, "security_notes.md")
if os.path.isfile(security_notes_path):
    try:
        with open(security_notes_path, "r", encoding="utf-8") as f:
            notes = f.read().lower()
        has_cmd_line = ("command line" in notes)
        has_password = ("password" in notes)
        has_priv_key = ("private key" in notes)
        has_perm = ("permission" in notes) or ("permissions" in notes)
        has_backup = ("backup" in notes) or ("backed up" in notes)
        if has_cmd_line and has_password and has_priv_key and has_perm and has_backup:
            checks["security_notes_present"] = True
    except Exception:
        pass

# Compute reward as fraction of output-dependent checks passed
scored_checks = [
    "keys_exist_private",
    "keys_exist_public",
    "keys_are_ed25519",
    "key_pair_matches",
    "agent_id_file_exists",
    "agent_id_matches",
    "signature_file_exists",
    "message_signature_valid",
    "agent_card_exists",
    "agent_card_fields_match_config",
    "agent_card_signature_valid",
    "security_notes_present",
]
passed = sum(1 for k in scored_checks if checks.get(k, False))
total = len(scored_checks)
reward = (passed / total) if total > 0 else 0.0

# No-op baseline: if output is empty or missing required artifacts, ensure reward is 0.0
# This is naturally enforced because no checks will pass.

# Print final JSON (single line)
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))