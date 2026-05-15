import json
import os
import re
import sys
import base64
from datetime import datetime

def workspace():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def joinp(*args):
    return os.path.join(*args)

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def is_numeric(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def is_base58_like(s):
    # Base58 alphabet without 0,O,I,l
    return isinstance(s, str) and len(s) > 0 and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", s) is not None

def is_base64_like_and_decodable(s):
    if not isinstance(s, str) or len(s) == 0:
        return False
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False

def is_iso_like(s):
    if not isinstance(s, str) or len(s) < 10:
        return False
    # Accept RFC3339/ISO-8601 variants with optional Z
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        # fromisoformat handles many common cases
        datetime.fromisoformat(t)
        return True
    except Exception:
        # Fall back to simple date-only or datetime presence
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return True
        if "T" in s and re.match(r"^\d{4}-\d{2}-\d{2}T", s):
            return True
        return False

def main():
    ws = workspace()
    input_dir = joinp(ws, "input")
    output_dir = joinp(ws, "output")

    checks = {
        "address_json_ok": False,
        "airdrop_json_ok": False,
        "sign_json_ok": False,
        "verify_json_ok": False,
        "proof_package_json_ok": False,
        "summary_md_ok": False,
    }

    # Build expected inputs
    input_file = joinp(input_dir, "link_request.json")
    try:
        req = read_json(input_file)
    except Exception:
        req = None

    # Expected parameters from input for validation
    expected_agent_id = None
    expected_message = None
    expected_network = "devnet"
    if isinstance(req, dict):
        agent_id = req.get("agent_id")
        message_prefix = req.get("message_prefix", "")
        expected_agent_id = agent_id
        if agent_id is not None:
            expected_message = f"{message_prefix}{agent_id}"

    # Validate address.json
    address_path = joinp(output_dir, "address.json")
    address_data = None
    address_val = None
    if os.path.isfile(address_path):
        try:
            address_data = read_json(address_path)
            net = address_data.get("network")
            addr = address_data.get("address")
            # Solana base58 address regex (32-44 chars)
            addr_ok = isinstance(addr, str) and re.fullmatch(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", addr or "") is not None
            if net == expected_network and addr_ok:
                checks["address_json_ok"] = True
                address_val = addr
        except Exception:
            pass

    # Validate airdrop.json
    airdrop_path = joinp(output_dir, "airdrop.json")
    if os.path.isfile(airdrop_path):
        try:
            airdrop_data = read_json(airdrop_path)
            net = airdrop_data.get("network")
            addr = airdrop_data.get("address")
            requested = airdrop_data.get("requestedSol")
            sig = airdrop_data.get("airdropSignature")
            sol = airdrop_data.get("sol")
            addr_ok = isinstance(addr, str) and re.fullmatch(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", addr or "") is not None
            requested_ok = is_numeric(requested) and float(requested) >= 0.2
            sig_ok = isinstance(sig, str) and len(sig) > 0
            sol_ok = is_numeric(sol)
            if net == expected_network and addr_ok and requested_ok and sig_ok and sol_ok:
                checks["airdrop_json_ok"] = True
        except Exception:
            pass

    # Validate sign.json
    sign_path = joinp(output_dir, "sign.json")
    sign_data = None
    if os.path.isfile(sign_path):
        try:
            sign_data = read_json(sign_path)
            net = sign_data.get("network")
            addr = sign_data.get("address")
            msg = sign_data.get("message")
            sig58 = sign_data.get("signatureBase58")
            sig64 = sign_data.get("signatureBase64")

            addr_match = (address_val is not None and addr == address_val)
            msg_match = (expected_message is not None and msg == expected_message)
            sig58_ok = is_base58_like(sig58)
            sig64_ok = is_base64_like_and_decodable(sig64)

            if net == expected_network and addr_match and msg_match and sig58_ok and sig64_ok:
                checks["sign_json_ok"] = True
        except Exception:
            pass

    # Validate verify.json
    verify_path = joinp(output_dir, "verify.json")
    if os.path.isfile(verify_path) and sign_data is not None:
        try:
            verify_data = read_json(verify_path)
            net = verify_data.get("network")
            addr = verify_data.get("address")
            msg = verify_data.get("message")
            valid = verify_data.get("valid")
            addr_match = (isinstance(sign_data.get("address"), str) and addr == sign_data.get("address"))
            msg_match = (isinstance(sign_data.get("message"), str) and msg == sign_data.get("message"))
            valid_ok = (valid is True)
            if net == expected_network and addr_match and msg_match and valid_ok:
                checks["verify_json_ok"] = True
        except Exception:
            pass

    # Validate proof_package.json
    proof_path = joinp(output_dir, "proof_package.json")
    if os.path.isfile(proof_path):
        try:
            proof = read_json(proof_path)
            agent_ok = (expected_agent_id is not None and proof.get("agent_id") == expected_agent_id)
            net_ok = (proof.get("network") == expected_network)
            wallet_ok = (address_val is not None and proof.get("wallet_address") == address_val)
            msg_ok = (expected_message is not None and proof.get("message") == expected_message)
            sig58_ok = isinstance(proof.get("signature_base58"), str) and len(proof.get("signature_base58")) > 0
            sig64_ok = isinstance(proof.get("signature_base64"), str) and len(proof.get("signature_base64")) > 0
            created_ok = is_iso_like(proof.get("created_at"))
            if agent_ok and net_ok and wallet_ok and msg_ok and sig58_ok and sig64_ok and created_ok:
                checks["proof_package_json_ok"] = True
        except Exception:
            pass

    # Validate summary.md
    summary_path = joinp(output_dir, "summary.md")
    if os.path.isfile(summary_path) and expected_message is not None:
        try:
            txt = read_text(summary_path)
            exact_line = f"Exact message signed: {expected_message}"
            has_exact = exact_line in txt
            has_devnet = "devnet" in txt
            lower = txt.lower()
            has_keep = "keep" in lower
            has_keypair = "keypair" in lower
            if has_exact and has_devnet and has_keep and has_keypair:
                checks["summary_md_ok"] = True
        except Exception:
            pass

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty, reward should be 0.0
    if not os.path.isdir(output_dir) or len([name for name in os.listdir(output_dir)]) == 0:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()