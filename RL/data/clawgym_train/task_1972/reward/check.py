import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs

def load_jsonl(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.read().splitlines():
                if raw.strip() == "":
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    return None, f"Invalid JSON line: {raw[:120]}"
                lines.append(obj)
        return lines, None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, str(e)

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, str(e)

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as e:
        return None, str(e)

def is_valid_evm_address(addr):
    return isinstance(addr, str) and re.fullmatch(r"0x[a-fA-F0-9]{40}", addr) is not None

def is_decimal_string(s):
    return isinstance(s, str) and re.fullmatch(r"\d+(\.\d+)?", s) is not None

def to_base_units(amount_str, decimals):
    # floor(amount * 10^decimals) using integer math
    if not is_decimal_string(amount_str):
        return None
    parts = amount_str.split(".")
    whole = parts[0]
    frac = parts[1] if len(parts) > 1 else ""
    if decimals < 0:
        return None
    if len(frac) < decimals:
        frac = frac + "0" * (decimals - len(frac))
    else:
        frac = frac[:decimals]  # floor extra digits
    try:
        whole_i = int(whole) if whole else 0
        frac_i = int(frac) if frac else 0
        val = whole_i * (10 ** decimals) + frac_i
        return str(val)
    except Exception:
        return None

def short_address(addr):
    if not isinstance(addr, str) or len(addr) < 14:
        return None
    return f"{addr[:8]}...{addr[-6:]}"

def normalize_addr(addr):
    return addr.lower() if isinstance(addr, str) else addr

def parse_trust_deeplink(url):
    """
    Returns (ok, parsed) where parsed has keys: scheme, netloc, path, asset, address, amount
    """
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        asset = q.get("asset", [None])[0]
        address = q.get("address", [None])[0]
        amount = q.get("amount", [None])[0]
        return True, {
            "scheme": u.scheme,
            "netloc": u.netloc,
            "path": u.path,
            "asset": asset,
            "address": address,
            "amount": amount
        }
    except Exception:
        return False, {}

def unique_list(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "links_exists": False,
        "links_three_lines": False,
        "links_valid_objects": False,
        "links_wallet_trust": False,
        "links_wallet_matches_preference": False,
        "intents_fields_valid": False,
        "intents_chain_ids_valid": False,
        "intents_to_valid": False,
        "intents_assets_valid": False,
        "intents_decimals_correct": False,
        "intents_amount_human_format": False,
        "intents_base_units_correct": False,
        "intents_erc20_token_present": False,
        "intents_erc20_usdc_token_correct": False,
        "deeplinks_trust_format_correct": False,
        "message_templates_exact": False,
        "verify_exists": False,
        "verify_three_lines": False,
        "verify_valid_objects": False,
        "verify_fields_format": False,
        "verify_matches_links": False,
        "sanity_exists": False,
        "sanity_valid_json": False,
        "sanity_total_payments": False,
        "sanity_wallet_trust": False,
        "sanity_chains_include_required": False,
        "sanity_tokens_include_required": False,
        "sanity_consistent_with_links": False,
    }

    # Expected references from input
    # Wallet preference
    wallet_pref_path = os.path.join(input_dir, "wallet_preference.txt")
    wallet_pref_raw, _ = load_text(wallet_pref_path)
    pref_norm = None
    if wallet_pref_raw is not None:
        pref_norm = wallet_pref_raw.strip().lower()
        if pref_norm not in ("metamask", "trust"):
            pref_norm = "metamask"

    # Payments rows count (for cross-check counts if needed)
    payments_csv_path = os.path.join(input_dir, "payments.csv")
    input_row_count = None
    try:
        with open(payments_csv_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
            if lines:
                # assume header present; if not, we still count data lines
                # try to detect header by column names
                header = lines[0]
                has_header = any(h in header.lower() for h in ["payeraddress", "recipientaddress", "assettype", "amountdecimal", "chainid"])
                data_lines = lines[1:] if has_header else lines
                input_row_count = len(data_lines)
    except Exception:
        input_row_count = None

    # Constants/mappings
    allowed_chain_ids_for_links = {1, 8453, 11155111}  # as per reward summary
    usdc_by_chain = {
        1: "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        8453: "0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
        11155111: "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238",
        84532: "0x036CbD53842c5426634e7929541eC2318f3dCf7e",
    }

    # 1) links.jsonl
    links_path = os.path.join(output_dir, "links.jsonl")
    links, links_err = load_jsonl(links_path)
    if links is not None:
        checks["links_exists"] = True
        nonempty_count = len(links)
        if nonempty_count == 3:
            checks["links_three_lines"] = True
        # Ensure all are dicts with required keys
        required_keys = {"intent", "wallet", "deeplink", "messageTemplate"}
        objs_ok = True
        for obj in links:
            if not isinstance(obj, dict):
                objs_ok = False
                break
            if not required_keys.issubset(set(obj.keys())):
                objs_ok = False
                break
        if objs_ok:
            checks["links_valid_objects"] = True

        # Wallet checks
        wallet_trust_all = True
        wallet_pref_match_all = True
        for obj in links:
            w = obj.get("wallet")
            if w != "trust":
                wallet_trust_all = False
            if pref_norm is not None and w != pref_norm:
                wallet_pref_match_all = False
        if objs_ok and wallet_trust_all:
            checks["links_wallet_trust"] = True
        if objs_ok and pref_norm is not None and wallet_pref_match_all:
            checks["links_wallet_matches_preference"] = True

        # Intent-level checks
        intents_present_all = True
        chain_ids_valid_all = True
        to_valid_all = True
        assets_valid_all = True
        decimals_correct_all = True
        amount_human_format_all = True
        base_units_correct_all = True
        erc20_token_present_all = True
        erc20_usdc_token_correct_all = True
        deeplink_ok_all = True
        message_template_ok_all = True

        for obj in links:
            intent = obj.get("intent")
            if not isinstance(intent, dict):
                intents_present_all = False
                continue

            # required intent fields
            required_intent_fields = {"chainId", "asset", "to", "amountHuman", "amountBaseUnits", "decimals", "symbol"}
            if not required_intent_fields.issubset(set(intent.keys())):
                intents_present_all = False

            # chainId numeric and within allowed
            cid = intent.get("chainId")
            try:
                cid_num = int(cid)
            except Exception:
                chain_ids_valid_all = False
                cid_num = None
            else:
                if cid_num not in allowed_chain_ids_for_links:
                    chain_ids_valid_all = False

            # to address valid
            to_addr = intent.get("to")
            if not is_valid_evm_address(to_addr):
                to_valid_all = False

            # asset valid
            asset = intent.get("asset")
            if asset not in ("ETH", "ERC20"):
                assets_valid_all = False

            # decimals correct per asset
            dec = intent.get("decimals")
            if isinstance(dec, bool):  # guard against True/False
                decimals_correct_all = False
            try:
                dec_num = int(dec)
            except Exception:
                decimals_correct_all = False
                dec_num = None
            else:
                if asset == "ETH" and dec_num != 18:
                    decimals_correct_all = False
                if asset == "ERC20" and dec_num != 6:
                    decimals_correct_all = False

            # amountHuman format
            amt_h = intent.get("amountHuman")
            if not is_decimal_string(amt_h):
                amount_human_format_all = False

            # amountBaseUnits correct
            abu = intent.get("amountBaseUnits")
            expected_abu = None
            if is_decimal_string(amt_h) and isinstance(dec_num, int):
                expected_abu = to_base_units(amt_h, dec_num)
            if not isinstance(abu, str) or (expected_abu is None) or (normalize_int_str(abu) != normalize_int_str(expected_abu)):
                base_units_correct_all = False

            # ERC20 token presence and correctness
            if asset == "ERC20":
                token = intent.get("token")
                if not token or not is_valid_evm_address(token):
                    erc20_token_present_all = False
                else:
                    # must match standard USDC address for chain
                    expected = usdc_by_chain.get(cid_num)
                    if expected is None:
                        # If chain not mapped, we cannot validate; but for this task allowed chains are mapped.
                        erc20_usdc_token_correct_all = False
                    else:
                        if normalize_addr(token) != normalize_addr(expected):
                            erc20_usdc_token_correct_all = False

            # Deeplink correctness for Trust Wallet
            deeplink = obj.get("deeplink")
            ok_url, parsed = parse_trust_deeplink(deeplink if isinstance(deeplink, str) else "")
            dl_ok = True
            if not ok_url:
                dl_ok = False
            else:
                if parsed["scheme"] != "https" or parsed["netloc"] != "link.trustwallet.com" or parsed["path"] != "/send":
                    dl_ok = False
                # Check address and amount
                if normalize_addr(parsed.get("address")) != normalize_addr(to_addr):
                    dl_ok = False
                if parsed.get("amount") != amt_h:
                    dl_ok = False
                # Check asset param
                asset_param = parsed.get("asset")
                if asset == "ETH":
                    if asset_param != "c60":
                        dl_ok = False
                elif asset == "ERC20":
                    token = intent.get("token")
                    if not token:
                        dl_ok = False
                    else:
                        # must be c60_t<token>
                        expected_asset_param = "c60_t" + token
                        # Accept case-insensitive token casing
                        if not isinstance(asset_param, str):
                            dl_ok = False
                        else:
                            # Split prefix
                            if not asset_param.lower().startswith("c60_t0x"):
                                dl_ok = False
                            else:
                                # compare address part case-insensitively
                                addr_part = asset_param[len("c60_t"):]
                                if normalize_addr(addr_part) != normalize_addr(token):
                                    dl_ok = False
                else:
                    dl_ok = False
            if not dl_ok:
                deeplink_ok_all = False

            # Message template exact
            symbol = intent.get("symbol")
            expected_short = short_address(to_addr) if isinstance(to_addr, str) else None
            expected_msg = None
            if is_decimal_string(amt_h) and isinstance(symbol, str) and expected_short:
                expected_msg = f"Payment request: {amt_h} {symbol} to {expected_short}. Tap to open Trust Wallet and approve. Reject if recipient or amount doesn't match."
            msg = obj.get("messageTemplate")
            if not (isinstance(msg, str) and expected_msg is not None and msg == expected_msg):
                message_template_ok_all = False

        if objs_ok and intents_present_all:
            checks["intents_fields_valid"] = True
        if objs_ok and chain_ids_valid_all:
            checks["intents_chain_ids_valid"] = True
        if objs_ok and to_valid_all:
            checks["intents_to_valid"] = True
        if objs_ok and assets_valid_all:
            checks["intents_assets_valid"] = True
        if objs_ok and decimals_correct_all:
            checks["intents_decimals_correct"] = True
        if objs_ok and amount_human_format_all:
            checks["intents_amount_human_format"] = True
        if objs_ok and base_units_correct_all:
            checks["intents_base_units_correct"] = True
        if objs_ok and erc20_token_present_all:
            checks["intents_erc20_token_present"] = True
        if objs_ok and erc20_usdc_token_correct_all:
            checks["intents_erc20_usdc_token_correct"] = True
        if objs_ok and deeplink_ok_all:
            checks["deeplinks_trust_format_correct"] = True
        if objs_ok and message_template_ok_all:
            checks["message_templates_exact"] = True

    # 2) verify_intents.jsonl
    verify_path = os.path.join(output_dir, "verify_intents.jsonl")
    verify_lines, verify_err = load_jsonl(verify_path)
    if verify_lines is not None:
        checks["verify_exists"] = True
        if len(verify_lines) == 3:
            checks["verify_three_lines"] = True
        # valid objects and fields
        vf_ok = True
        vf_fields_ok = True
        if verify_lines:
            for obj in verify_lines:
                if not isinstance(obj, dict):
                    vf_ok = False
                    break
                required = {"chainId", "from", "to", "asset", "amount", "symbol"}
                if not required.issubset(set(obj.keys())):
                    vf_fields_ok = False
                # field formats
                try:
                    int(obj.get("chainId"))
                except Exception:
                    vf_fields_ok = False
                if not is_valid_evm_address(obj.get("from")):
                    vf_fields_ok = False
                if not is_valid_evm_address(obj.get("to")):
                    vf_fields_ok = False
                if obj.get("asset") not in ("ETH", "ERC20"):
                    vf_fields_ok = False
                if not is_decimal_string(obj.get("amount")):
                    vf_fields_ok = False
                if not isinstance(obj.get("symbol"), str):
                    vf_fields_ok = False
        if vf_ok:
            checks["verify_valid_objects"] = True
        if vf_ok and vf_fields_ok:
            checks["verify_fields_format"] = True

        # Cross-check with links by line index
        if verify_lines is not None and links is not None and len(verify_lines) == len(links) == 3:
            match_all = True
            for i in range(3):
                v = verify_lines[i]
                l = links[i]
                intent = l.get("intent", {})
                try:
                    if int(v.get("chainId")) != int(intent.get("chainId")):
                        match_all = False
                    if normalize_addr(v.get("to")) != normalize_addr(intent.get("to")):
                        match_all = False
                    if v.get("asset") != intent.get("asset"):
                        match_all = False
                    if v.get("amount") != intent.get("amountHuman"):
                        match_all = False
                    if v.get("symbol") != intent.get("symbol"):
                        match_all = False
                except Exception:
                    match_all = False
            if match_all:
                checks["verify_matches_links"] = True

    # 3) sanity.json
    sanity_path = os.path.join(output_dir, "sanity.json")
    sanity, sanity_err = load_json(sanity_path)
    if sanity is not None:
        checks["sanity_exists"] = True
        if isinstance(sanity, dict):
            checks["sanity_valid_json"] = True

            # totalPayments
            if sanity.get("totalPayments") == 3:
                checks["sanity_total_payments"] = True

            # wallet trust
            if sanity.get("wallet") == "trust":
                checks["sanity_wallet_trust"] = True

            # chains includes 1, 8453, 11155111
            chains = sanity.get("chains")
            chains_include = False
            if isinstance(chains, list):
                try:
                    chain_set = set(int(x) for x in chains)
                    if {1, 8453, 11155111}.issubset(chain_set):
                        chains_include = True
                except Exception:
                    chains_include = False
            if chains_include:
                checks["sanity_chains_include_required"] = True

            # tokens includes USDC and ETH
            tokens = sanity.get("tokens")
            tokens_include = False
            if isinstance(tokens, list):
                tok_set = set([str(x) for x in tokens])
                if {"USDC", "ETH"}.issubset(tok_set):
                    tokens_include = True
            if tokens_include:
                checks["sanity_tokens_include_required"] = True

            # Consistency with links (unique chains/symbols)
            consistent = False
            if links is not None and isinstance(chains, list) and isinstance(tokens, list):
                try:
                    links_chains = unique_list([int(obj.get("intent", {}).get("chainId")) for obj in links])
                    links_syms = unique_list([obj.get("intent", {}).get("symbol") for obj in links])
                    sanity_chain_set = set(int(x) for x in chains)
                    sanity_token_set = set(str(x) for x in tokens)
                    if set(links_chains).issubset(sanity_chain_set) and set(links_syms).issubset(sanity_token_set):
                        consistent = True
                except Exception:
                    consistent = False
            if consistent:
                checks["sanity_consistent_with_links"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if checks["links_exists"] or checks["verify_exists"] or checks["sanity_exists"] else 0.0

    # Ensure 0.0 for no-op baseline (no outputs)
    if not os.path.isdir(output_dir) or (not checks["links_exists"] and not checks["verify_exists"] and not checks["sanity_exists"]):
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

def normalize_int_str(s):
    # normalize integer string (remove leading zeros)
    if not isinstance(s, str):
        return None
    if not re.fullmatch(r"\d+", s):
        return None
    return str(int(s)) if s != "0" else "0"

if __name__ == "__main__":
    main()