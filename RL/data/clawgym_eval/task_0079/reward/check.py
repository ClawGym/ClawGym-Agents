import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_key(obj, key):
    # Recursive search for first occurrence of key in nested dict/list
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = find_key(it, key)
            if found is not None:
                return found
    return None

def to_int(x):
    try:
        if isinstance(x, bool):
            return int(x)
        return int(str(x).strip())
    except Exception:
        return None

def to_str(x):
    try:
        if x is None:
            return None
        return str(x)
    except Exception:
        return None

def to_float(x):
    try:
        if isinstance(x, bool):
            return float(int(x))
        return float(x)
    except Exception:
        try:
            return float(str(x))
        except Exception:
            return None

def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def implied_rate(amount_out, amount_in):
    try:
        return round(float(amount_out) / float(amount_in), 6)
    except Exception:
        return None

def normalize_evm_addr(addr):
    if addr is None:
        return None
    return addr.lower()

def get_token_info_fields(token_info_json):
    """Extract tokenId (str), chainId (int), contract (str), tokenDecimal (int) from token-info snapshot."""
    if token_info_json is None:
        return None
    node = token_info_json
    if isinstance(node, dict) and isinstance(node.get("data"), dict):
        node = node["data"]
    token_id = find_key(node, "tokenId")
    chain_id = find_key(node, "chainId")
    contract = find_key(node, "contract")
    token_decimal = find_key(node, "tokenDecimal")

    token_id = to_str(token_id) if token_id is not None else None
    chain_id = to_int(chain_id) if chain_id is not None else None
    contract = to_str(contract) if contract is not None else None
    token_decimal = to_int(token_decimal) if token_decimal is not None else None

    if token_id is None or chain_id is None or contract is None or token_decimal is None:
        return None
    return {
        "tokenId": token_id,
        "chainId": chain_id,
        "contract": contract,
        "tokenDecimal": token_decimal,
    }

def get_swap_quote_fields(quote_json):
    """Extract amountIn, amountOut, tokenInPrice, tokenOutPrice, fee from swap-quote snapshot."""
    if quote_json is None:
        return None
    node = quote_json
    if isinstance(node, dict) and isinstance(node.get("data"), dict):
        node = node["data"]

    amount_in = find_key(node, "amountIn")
    amount_out = find_key(node, "amountOut")
    token_in_price = find_key(node, "tokenInPrice")
    token_out_price = find_key(node, "tokenOutPrice")
    fee = find_key(node, "fee")

    amount_in = to_float(amount_in)
    amount_out = to_float(amount_out)
    token_in_price = to_float(token_in_price)
    token_out_price = to_float(token_out_price)
    fee = to_float(fee)

    if None in (amount_in, amount_out, token_in_price, token_out_price, fee):
        return None
    return {
        "amountIn": amount_in,
        "amountOut": amount_out,
        "tokenInPrice": token_in_price,
        "tokenOutPrice": token_out_price,
        "fee": fee,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "param_payloads_exists": False,
        "param_eth_ok": False,
        "param_bnb_ok": False,
        "param_sol_ok": False,
        "quotes_summary_exists": False,
        "quotes_eth_ok": False,
        "quotes_bnb_ok": False,
        "quotes_sol_ok": False,
        "quotes_highest_ok": False,
        "quotes_report_exists": False,
        "report_pairs_ok": False,
        "report_lines_ok": False,
        "report_final_line_ok": False,
    }

    # Load input token-info and quote snapshots
    inputs = {
        "eth_to_usdc": {
            "token_info_path": os.path.join(input_dir, "eth_usdc_token_info.json"),
            "quote_path": os.path.join(input_dir, "eth_usdc_swap_quote.json"),
            "expected_chain": 2003,
            "native_decimals": 18,
            "native_address": "",  # EVM native token address is empty string for swap-quote parameter
        },
        "bnb_to_usdt": {
            "token_info_path": os.path.join(input_dir, "bsc_usdt_token_info.json"),
            "quote_path": os.path.join(input_dir, "bsc_usdt_swap_quote.json"),
            "expected_chain": 2002,
            "native_decimals": 18,
            "native_address": "",
        },
        "sol_to_usdt": {
            "token_info_path": os.path.join(input_dir, "sol_usdt_token_info.json"),
            "quote_path": os.path.join(input_dir, "sol_usdt_swap_quote.json"),
            "expected_chain": 2001,
            "native_decimals": 9,
            "native_address": "So11111111111111111111111111111111111111111",
        },
    }

    token_infos = {}
    quotes = {}
    for key, meta in inputs.items():
        ti = load_json(meta["token_info_path"])
        qi = load_json(meta["quote_path"])
        tif = get_token_info_fields(ti)
        qf = get_swap_quote_fields(qi)
        token_infos[key] = tif
        quotes[key] = qf

    # Read output files
    param_payloads_path = os.path.join(output_dir, "param_payloads.json")
    quotes_summary_path = os.path.join(output_dir, "quotes_summary.json")
    quotes_report_path = os.path.join(output_dir, "quotes_report.md")

    param_payloads = load_json(param_payloads_path)
    if isinstance(param_payloads, dict):
        checks["param_payloads_exists"] = True

    quotes_summary = load_json(quotes_summary_path)
    if isinstance(quotes_summary, dict):
        checks["quotes_summary_exists"] = True

    # Validate param_payloads contents
    def check_param_for(key):
        if not checks["param_payloads_exists"]:
            return False
        if key not in param_payloads or not isinstance(param_payloads[key], dict):
            return False
        obj = param_payloads[key]
        meta = inputs[key]
        tif = token_infos.get(key)
        qf = quotes.get(key)
        if tif is None or qf is None:
            return False

        chain_expected = tif["chainId"]
        # Basic required fields existence
        required_fields = [
            "chainId", "tokenInId", "tokenOutId", "tokenInAddress", "tokenOutAddress",
            "tokenInDecimals", "tokenOutDecimals", "fromChainId", "toChainId", "slippage", "amountIn"
        ]
        for rf in required_fields:
            if rf not in obj:
                return False

        # Types and values
        try:
            chainId = to_int(obj.get("chainId"))
            fromChainId = to_int(obj.get("fromChainId"))
            toChainId = to_int(obj.get("toChainId"))
            tokenInId = to_str(obj.get("tokenInId"))
            tokenOutId = to_str(obj.get("tokenOutId"))
            tokenInAddress = to_str(obj.get("tokenInAddress"))
            tokenOutAddress = to_str(obj.get("tokenOutAddress"))
            tokenInDecimals = to_int(obj.get("tokenInDecimals"))
            tokenOutDecimals = to_int(obj.get("tokenOutDecimals"))
            slippage = to_float(obj.get("slippage"))
            amountIn = to_float(obj.get("amountIn"))
        except Exception:
            return False

        # Chain IDs must match token info
        if chainId != chain_expected or fromChainId != chain_expected or toChainId != chain_expected:
            return False

        # tokenInId should be native chain id as string
        if tokenInId != str(chain_expected):
            return False

        # tokenOutId must match token-info
        if tokenOutId != tif["tokenId"]:
            return False

        # tokenInAddress native rules
        # EVM chains (2002,2003,2004,2007): empty string; Solana(2001): So111...
        if chain_expected == 2001:
            if tokenInAddress != meta["native_address"]:
                return False
        else:
            if tokenInAddress != "":
                return False

        # tokenOutAddress must match token-info contract (case-insensitive for EVM addresses, exact for Solana)
        if chain_expected == 2001:
            if tokenOutAddress != tif["contract"]:
                return False
        else:
            if normalize_evm_addr(tokenOutAddress) != normalize_evm_addr(tif["contract"]):
                return False

        # Decimals
        if tokenInDecimals != meta["native_decimals"]:
            return False
        if tokenOutDecimals != tif["tokenDecimal"]:
            return False

        # Slippage
        if not almost_equal(slippage, 0.1, tol=1e-9):
            return False

        # amountIn must equal snapshot amountIn
        if not almost_equal(amountIn, quotes[key]["amountIn"], tol=1e-9):
            return False

        return True

    checks["param_eth_ok"] = check_param_for("eth_to_usdc")
    checks["param_bnb_ok"] = check_param_for("bnb_to_usdt")
    checks["param_sol_ok"] = check_param_for("sol_to_usdt")

    # Validate quotes_summary contents
    def check_quotes_for(key):
        if not checks["quotes_summary_exists"]:
            return False
        if key not in quotes_summary or not isinstance(quotes_summary[key], dict):
            return False
        obj = quotes_summary[key]
        qf = quotes.get(key)
        tif = token_infos.get(key)
        if qf is None or tif is None:
            return False

        # Extract fields
        amountIn = to_float(obj.get("amountIn"))
        amountOut = to_float(obj.get("amountOut"))
        tokenInPrice = to_float(obj.get("tokenInPrice"))
        tokenOutPrice = to_float(obj.get("tokenOutPrice"))
        fee = to_float(obj.get("fee"))
        impliedRate_out = obj.get("impliedRate")
        chainMatch = obj.get("chainMatch")

        # Verify presence
        if None in (amountIn, amountOut, tokenInPrice, tokenOutPrice, fee):
            return False
        # Compare with expected from quote snapshot
        if not almost_equal(amountIn, qf["amountIn"]):
            return False
        if not almost_equal(amountOut, qf["amountOut"]):
            return False
        if not almost_equal(tokenInPrice, qf["tokenInPrice"]):
            return False
        if not almost_equal(tokenOutPrice, qf["tokenOutPrice"]):
            return False
        if not almost_equal(fee, qf["fee"]):
            return False

        # impliedRate recomputation
        expected_implied = implied_rate(amountOut, amountIn)
        if expected_implied is None:
            return False
        implied_val = to_float(impliedRate_out)
        if implied_val is None or not almost_equal(implied_val, expected_implied, tol=1e-6):
            return False

        # chainMatch must be true and also match from param_payloads values if available
        if chainMatch is not True:
            return False
        # If param payloads present, verify fromChainId == toChainId == chainId
        pp = param_payloads.get(key) if isinstance(param_payloads, dict) else None
        if pp:
            fc = to_int(pp.get("fromChainId"))
            tc = to_int(pp.get("toChainId"))
            cc = to_int(pp.get("chainId"))
            if fc is None or tc is None or cc is None or not (fc == tc == cc == tif["chainId"]):
                return False

        return True

    checks["quotes_eth_ok"] = check_quotes_for("eth_to_usdc")
    checks["quotes_bnb_ok"] = check_quotes_for("bnb_to_usdt")
    checks["quotes_sol_ok"] = check_quotes_for("sol_to_usdt")

    # Validate highestInputUsdSymbol and highestInputUsdValue
    if checks["quotes_summary_exists"]:
        highest_symbol = quotes_summary.get("highestInputUsdSymbol")
        highest_value = to_float(quotes_summary.get("highestInputUsdValue"))
        # Compute expected highest from swap quotes
        in_prices = {
            "ETH": quotes["eth_to_usdc"]["tokenInPrice"] if quotes.get("eth_to_usdc") else None,
            "BNB": quotes["bnb_to_usdt"]["tokenInPrice"] if quotes.get("bnb_to_usdt") else None,
            "SOL": quotes["sol_to_usdt"]["tokenInPrice"] if quotes.get("sol_to_usdt") else None,
        }
        # Ensure all present
        if None not in in_prices.values():
            exp_symbol = max(in_prices.items(), key=lambda kv: kv[1])[0]
            exp_value = in_prices[exp_symbol]
            if highest_symbol == exp_symbol and highest_value is not None and almost_equal(highest_value, exp_value):
                checks["quotes_highest_ok"] = True

    # Validate quotes_report.md
    if os.path.isfile(quotes_report_path):
        checks["quotes_report_exists"] = True
        try:
            with open(quotes_report_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""

        # Must include literal substrings
        substrings_ok = (
            ("ETH->USDC" in content) and
            ("BNB->USDT" in content) and
            ("SOL->USDT" in content)
        )
        checks["report_pairs_ok"] = substrings_ok

        # Line count: at least 3 non-empty lines and at most 5
        lines = [ln for ln in content.splitlines() if ln.strip() != ""]
        if len(lines) >= 3 and len(lines) <= 5:
            checks["report_lines_ok"] = True

        # Final line exactly equal
        if lines:
            if lines[-1].strip() == "Highest USD per unit of input: ETH":
                checks["report_final_line_ok"] = True

    # Compute reward as proportion of passed checks among scored ones.
    # Only checks that depend on output files contribute to reward (all our checks do).
    total_checks = 0
    passed_checks = 0
    for k, v in checks.items():
        total_checks += 1
        if v:
            passed_checks += 1

    # No-op baseline: if output is missing/empty causing all checks False -> reward 0.0
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    result = {"reward": round(reward, 6)}
    # Add all checks
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()