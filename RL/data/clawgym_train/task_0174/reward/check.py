import sys
import os
import json
import csv

# Minimal pure-Python Keccak-256 implementation (Ethereum keccak, pad10*1 with domain 0x01)
def _rotl64(x, n):
    n &= 63
    return ((x << n) | (x >> (64 - n))) & 0xFFFFFFFFFFFFFFFF

def _keccak_f1600(state):
    RC = [
        0x0000000000000001, 0x0000000000008082,
        0x800000000000808A, 0x8000000080008000,
        0x000000000000808B, 0x0000000080000001,
        0x8000000080008081, 0x8000000000008009,
        0x000000000000008A, 0x0000000000000088,
        0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B,
        0x8000000000008089, 0x8000000000008003,
        0x8000000000008002, 0x8000000000000080,
        0x000000000000800A, 0x800000008000000A,
        0x8000000080008081, 0x8000000000008080,
        0x0000000080000001, 0x8000000080008008,
    ]
    r = [
        [ 0, 36,  3, 41, 18],
        [ 1, 44, 10, 45,  2],
        [62,  6, 43, 15, 61],
        [28, 55, 25, 21, 56],
        [27, 20, 39,  8, 14],
    ]
    for rc in RC:
        # Theta
        C = [state[x] ^ state[x+5] ^ state[x+10] ^ state[x+15] ^ state[x+20] for x in range(5)]
        D = [C[(x-1) % 5] ^ _rotl64(C[(x+1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(0, 25, 5):
                state[x+y] ^= D[x]
        # Rho and Pi
        B = [0] * 25
        for x in range(5):
            for y in range(5):
                B[y % 5 + 5*((2*x + 3*y) % 5)] = _rotl64(state[x + 5*y], r[x][y])
        # Chi
        for y in range(5):
            T = [B[5*y + x] for x in range(5)]
            for x in range(5):
                state[5*y + x] = T[x] ^ ((~T[(x+1) % 5]) & T[(x+2) % 5])
        # Iota
        state[0] ^= rc

def keccak256(data: bytes) -> bytes:
    # Keccak-256: rate = 1088 bits (136 bytes), capacity = 512 bits
    rate_bytes = 136
    # Initialize state (25 lanes of 64-bit)
    state = [0] * 25
    # Absorb full blocks
    offset = 0
    while offset + rate_bytes <= len(data):
        block = data[offset:offset+rate_bytes]
        for i in range(0, rate_bytes, 8):
            idx = i // 8
            state[idx] ^= int.from_bytes(block[i:i+8], 'little')
        _keccak_f1600(state)
        offset += rate_bytes
    # Final block with Keccak padding (domain 0x01)
    remaining = data[offset:]
    pad_len = rate_bytes - len(remaining)
    # pad: append 0x01 then zeros then last byte OR 0x80
    padded = bytearray(remaining)
    padded.append(0x01)
    padded.extend(b'\x00' * (rate_bytes - len(padded) - 1))
    padded.append(0x80)
    for i in range(0, rate_bytes, 8):
        idx = i // 8
        chunk = padded[i:i+8]
        state[idx] ^= int.from_bytes(chunk, 'little')
    _keccak_f1600(state)
    # Squeeze 32 bytes
    out = bytearray()
    while len(out) < 32:
        for i in range(0, rate_bytes, 8):
            if len(out) >= 32:
                break
            out.extend(state[i//8].to_bytes(8, 'little'))
        if len(out) >= 32:
            break
        _keccak_f1600(state)
    return bytes(out[:32])

def to_lower_hex_address(addr: str):
    if not isinstance(addr, str):
        return None
    a = addr.strip().lower()
    if a.startswith("0x"):
        a = a[2:]
    if len(a) != 40:
        return None
    try:
        int(a, 16)
    except ValueError:
        return None
    return "0x" + a

def is_lower_hex_address(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42 and addr == addr.lower() and all(c in "0123456789abcdef" for c in addr[2:])

def encode_abi_address(addr: str) -> bytes:
    # 32-byte word with last 20 bytes the address
    addr_bytes = int(addr[2:], 16).to_bytes(20, 'big')
    return b'\x00' * 12 + addr_bytes

def encode_abi_uint24(val: int) -> bytes:
    if val < 0 or val >= (1 << 24):
        raise ValueError("uint24 out of range")
    b = val.to_bytes(3, 'big')
    return b'\x00' * 29 + b

def encode_abi_int24(val: int) -> bytes:
    # two's complement in 24-bit then left-pad to 32 bytes
    if val < -(1 << 23) or val >= (1 << 23):
        raise ValueError("int24 out of range")
    if val >= 0:
        u = val
    else:
        u = (1 << 24) + val
    b = u.to_bytes(3, 'big')
    return b'\x00' * 29 + b

def abi_encode_poolkey(currency0: str, currency1: str, fee: int, tick_spacing: int, hooks: str) -> bytes:
    return b"".join([
        encode_abi_address(currency0),
        encode_abi_address(currency1),
        encode_abi_uint24(fee),
        encode_abi_int24(tick_spacing),
        encode_abi_address(hooks),
    ])

def hex_concat(*parts: bytes) -> str:
    return "0x" + "".join(p.hex() for p in parts)

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl_lines(path):
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                raise
            lines.append(obj)
    return lines

def load_wallets_csv(path):
    addrs = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if 'address' not in reader.fieldnames:
            raise ValueError("wallets.csv missing 'address' header")
        for row in reader:
            addr = row.get('address', '').strip()
            if addr:
                addrs.append(addr)
    return addrs

def compute_selector(sig: str) -> bytes:
    return keccak256(sig.encode('ascii'))[:4]

def validate_eth_call_obj(obj, to_addr_expected: str, data_prefix: str):
    # Returns (bool, reason)
    if not isinstance(obj, dict):
        return False, "object not dict"
    if obj.get("jsonrpc") != "2.0":
        return False, "jsonrpc not 2.0"
    if obj.get("method") != "eth_call":
        return False, "method not eth_call"
    if "params" not in obj or not isinstance(obj["params"], list) or len(obj["params"]) != 2:
        return False, "params not 2 items"
    call, tag = obj["params"]
    if tag != "latest":
        return False, "tag not latest"
    if not isinstance(call, dict):
        return False, "call object not dict"
    to = call.get("to")
    data = call.get("data")
    if not isinstance(to, str) or not isinstance(data, str):
        return False, "to/data not strings"
    if to != to.lower():
        return False, "address not lowercase"
    if to != to_addr_expected:
        return False, "to mismatch"
    if not data.startswith(data_prefix):
        return False, "data prefix mismatch"
    if "id" not in obj or not isinstance(obj["id"], int):
        return False, "id not integer"
    return True, ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Contract addresses
    POOL_MANAGER = "0x11c23891d9f723c4f1c6560f892e4581d87b6d8a"
    WQELT = "0xfebc6f9f0149036006c4f5ac124685e0ef48e8a2"
    ZERO = "0x" + "0"*40

    checks = {
        "has_summary_file": False,
        "summary_valid_json": False,
        "summary_entries_complete": False,
        "summary_canonicalized": False,
        "summary_poolid_correct": False,

        "has_pool_calls_file": False,
        "pool_calls_valid_jsonl": False,
        "pool_calls_count_match": False,
        "pool_calls_content_valid": False,

        "has_wqelt_file": False,
        "wqelt_calls_valid_jsonl": False,
        "wqelt_calls_count_match": False,
        "wqelt_calls_content_valid": False,
    }

    # Load inputs
    pools_path = os.path.join(input_dir, "pools.json")
    wallets_path = os.path.join(input_dir, "wallets.csv")
    try:
        pools_input = read_json(pools_path)
        if not isinstance(pools_input, list):
            raise ValueError("pools.json not a list")
    except Exception:
        pools_input = None

    try:
        wallets_input = load_wallets_csv(wallets_path)
    except Exception:
        wallets_input = None

    # 1) summary.json checks
    summary_path = os.path.join(output_dir, "summary.json")
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        try:
            summary_obj = read_json(summary_path)
            if isinstance(summary_obj, dict):
                checks["summary_valid_json"] = True
            else:
                summary_obj = None
        except Exception:
            summary_obj = None
    else:
        summary_obj = None

    expected_per_pool = {}
    if pools_input is not None:
        try:
            for p in pools_input:
                name = p.get("name")
                ca = p.get("currencyA")
                cb = p.get("currencyB")
                fee = p.get("fee")
                ts = p.get("tickSpacing")
                hooks = p.get("hooks", None)
                if name is None or ca is None or cb is None or fee is None or ts is None:
                    raise ValueError("missing pool fields")
                na = to_lower_hex_address(ca)
                nb = to_lower_hex_address(cb)
                if na is None or nb is None:
                    raise ValueError("invalid address in input pools")
                # canonical order by numeric value
                if int(na[2:], 16) < int(nb[2:], 16):
                    c0, c1 = na, nb
                else:
                    c0, c1 = nb, na
                if hooks is None:
                    hk = ZERO
                else:
                    hk = to_lower_hex_address(str(hooks))
                    if hk is None:
                        raise ValueError("invalid hooks address")
                # encode and hash
                try:
                    enc = abi_encode_poolkey(c0, c1, int(fee), int(ts), hk)
                except Exception:
                    raise
                pid = "0x" + keccak256(enc).hex()
                expected_per_pool[name] = {
                    "currency0": c0,
                    "currency1": c1,
                    "fee": int(fee),
                    "tickSpacing": int(ts),
                    "hooks": hk,
                    "poolId": pid,
                }
            # If we got here, we have expected mapping
        except Exception:
            expected_per_pool = {}

    # Validate summary against expectations
    if checks["summary_valid_json"] and expected_per_pool:
        # complete: all names present
        all_present = True
        canonical_ok = True
        poolid_ok = True
        try:
            if set(summary_obj.keys()) != set(expected_per_pool.keys()):
                all_present = False
            for name, exp in expected_per_pool.items():
                if name not in summary_obj or not isinstance(summary_obj[name], dict):
                    all_present = False
                    continue
                s = summary_obj[name]
                # Validate fields present
                for fld in ["currency0", "currency1", "fee", "tickSpacing", "hooks", "poolId"]:
                    if fld not in s:
                        all_present = False
                # Validate address formats
                for afld in ["currency0", "currency1", "hooks"]:
                    aval = s.get(afld)
                    if not (isinstance(aval, str) and is_lower_hex_address(aval)):
                        canonical_ok = False
                # Validate fee/tickSpacing
                sf = s.get("fee")
                sts = s.get("tickSpacing")
                if not (isinstance(sf, int) and isinstance(sts, int)):
                    canonical_ok = False
                # Must match expected canonical values
                if s.get("currency0") != exp["currency0"] or s.get("currency1") != exp["currency1"]:
                    canonical_ok = False
                if s.get("hooks") != exp["hooks"]:
                    canonical_ok = False
                if sf != exp["fee"] or sts != exp["tickSpacing"]:
                    canonical_ok = False
                # Validate poolId format and correctness
                pid = s.get("poolId")
                if not (isinstance(pid, str) and pid.startswith("0x") and len(pid) == 66 and pid == pid.lower()):
                    poolid_ok = False
                if pid != exp["poolId"]:
                    poolid_ok = False
        except Exception:
            all_present = False
            canonical_ok = False
            poolid_ok = False

        if all_present:
            checks["summary_entries_complete"] = True
        if canonical_ok:
            checks["summary_canonicalized"] = True
        if poolid_ok:
            checks["summary_poolid_correct"] = True

    # 2) pool_calls.jsonl checks
    pool_calls_path = os.path.join(output_dir, "pool_calls.jsonl")
    if os.path.isfile(pool_calls_path):
        checks["has_pool_calls_file"] = True
        try:
            pool_calls = read_jsonl_lines(pool_calls_path)
            checks["pool_calls_valid_jsonl"] = True
        except Exception:
            pool_calls = None
    else:
        pool_calls = None

    if pool_calls is not None and expected_per_pool:
        expected_count = 2 * len(expected_per_pool)
        if len(pool_calls) == expected_count:
            checks["pool_calls_count_match"] = True
        # Compute selectors
        sel_slot0 = compute_selector("getSlot0(bytes32)").hex()
        sel_liq = compute_selector("getLiquidity(bytes32)").hex()
        # Build expected by poolId -> required selectors set
        required = {exp["poolId"]: set([sel_slot0, sel_liq]) for exp in expected_per_pool.values()}
        content_ok = True
        try:
            for obj in pool_calls:
                # Validate structure and to address and general fields
                # We will accept either selector; determine which
                if not isinstance(obj, dict):
                    content_ok = False
                    break
                # Basic fields
                if obj.get("jsonrpc") != "2.0" or obj.get("method") != "eth_call":
                    content_ok = False
                    break
                if "params" not in obj or not isinstance(obj["params"], list) or len(obj["params"]) != 2:
                    content_ok = False
                    break
                call, tag = obj["params"]
                if tag != "latest" or not isinstance(call, dict):
                    content_ok = False
                    break
                to = call.get("to")
                data = call.get("data")
                if not (isinstance(to, str) and isinstance(data, str) and isinstance(obj.get("id"), int)):
                    content_ok = False
                    break
                if to != to.lower() or to != POOL_MANAGER:
                    content_ok = False
                    break
                if not data.startswith("0x") or len(data) != 2 + 8 + 64:
                    content_ok = False
                    break
                sel = data[2:10]
                arg = "0x" + data[10:]
                if sel not in (sel_slot0, sel_liq):
                    content_ok = False
                    break
                # Must correspond to one of expected poolIds
                if arg not in required:
                    content_ok = False
                    break
                # mark this selector as satisfied for this poolId
                if sel in required[arg]:
                    required[arg].remove(sel)
                else:
                    # duplicate selector for same poolId
                    content_ok = False
                    break
            # After processing all, ensure all required sets are empty
            if not all(len(s) == 0 for s in required.values()):
                content_ok = False
        except Exception:
            content_ok = False
        if content_ok:
            checks["pool_calls_content_valid"] = True

    # 3) wqelt_balance_calls.jsonl checks
    wqelt_calls_path = os.path.join(output_dir, "wqelt_balance_calls.jsonl")
    if os.path.isfile(wqelt_calls_path):
        checks["has_wqelt_file"] = True
        try:
            wqelt_calls = read_jsonl_lines(wqelt_calls_path)
            checks["wqelt_calls_valid_jsonl"] = True
        except Exception:
            wqelt_calls = None
    else:
        wqelt_calls = None

    if wqelt_calls is not None and wallets_input is not None:
        # Normalize expected wallet addresses to lowercase 0x
        exp_wallets = []
        valid_wallets = True
        for w in wallets_input:
            nw = to_lower_hex_address(w)
            if nw is None:
                valid_wallets = False
                break
            exp_wallets.append(nw)
        if valid_wallets:
            if len(wqelt_calls) == len(exp_wallets):
                checks["wqelt_calls_count_match"] = True
            # Build multiset/dict counts of expected occurrences (exactly once each)
            expected_remaining = {w: 1 for w in exp_wallets}
            content_ok = True
            try:
                for obj in wqelt_calls:
                    if not isinstance(obj, dict):
                        content_ok = False
                        break
                    if obj.get("jsonrpc") != "2.0" or obj.get("method") != "eth_call":
                        content_ok = False
                        break
                    if "params" not in obj or not isinstance(obj["params"], list) or len(obj["params"]) != 2:
                        content_ok = False
                        break
                    call, tag = obj["params"]
                    if tag != "latest" or not isinstance(call, dict):
                        content_ok = False
                        break
                    to = call.get("to")
                    data = call.get("data")
                    if not (isinstance(to, str) and isinstance(data, str) and isinstance(obj.get("id"), int)):
                        content_ok = False
                        break
                    if to != to.lower() or to != WQELT:
                        content_ok = False
                        break
                    if not data.startswith("0x70a08231"):
                        content_ok = False
                        break
                    # data should be selector (8 hex) + 32-byte arg (64 hex) => total length 2 + 8 + 64
                    if len(data) != 2 + 8 + 64:
                        content_ok = False
                        break
                    arg = data[2+8:]  # 64 hex chars
                    # First 24 hex chars (12 bytes) should be zeros, last 40 should be address
                    if not arg.startswith("0"*24):
                        content_ok = False
                        break
                    addr_hex = "0x" + arg[24:]
                    if addr_hex not in expected_remaining or expected_remaining[addr_hex] == 0:
                        content_ok = False
                        break
                    expected_remaining[addr_hex] -= 1
                if not all(v == 0 for v in expected_remaining.values()):
                    content_ok = False
            except Exception:
                content_ok = False
            if content_ok:
                checks["wqelt_calls_content_valid"] = True

    # Compute reward: 3 sections (summary, pool_calls, wqelt_calls) each worth ~0.3333 if all sub-checks pass
    sections = []
    # Summary section
    sec_summary = (checks["has_summary_file"] and checks["summary_valid_json"] and
                   checks["summary_entries_complete"] and checks["summary_canonicalized"] and
                   checks["summary_poolid_correct"])
    sections.append(sec_summary)
    # Pool calls section
    sec_pool = (checks["has_pool_calls_file"] and checks["pool_calls_valid_jsonl"] and
                checks["pool_calls_count_match"] and checks["pool_calls_content_valid"])
    sections.append(sec_pool)
    # WQELT calls section
    sec_wqelt = (checks["has_wqelt_file"] and checks["wqelt_calls_valid_jsonl"] and
                 checks["wqelt_calls_count_match"] and checks["wqelt_calls_content_valid"])
    sections.append(sec_wqelt)

    reward = sum(1.0 for s in sections if s) / 3.0
    # Baseline: If no output files or required artifacts missing, ensure 0.0
    # The above will naturally be 0.0 if none sections pass.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()