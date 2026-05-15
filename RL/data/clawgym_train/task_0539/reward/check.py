import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def is_0x_hex(s, length):
    if not isinstance(s, str):
        return False
    pattern = r"^0x[a-fA-F0-9]{" + str(length) + r"}$"
    return re.fullmatch(pattern, s) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # File existence and parsing
        "has_summary_json": False,
        "summary_json_parses": False,
        "has_rpc_url_txt": False,
        "has_readme": False,

        # Top-level JSON keys and types
        "json_has_required_top_keys": False,
        "json_chain_id_correct": False,
        "json_mode_correct": False,
        "json_fork_from_correct": False,
        "json_block_number_correct": False,
        "json_rpc_url_format_valid": False,

        # Funded accounts validation
        "json_funded_accounts_len_5": False,
        "json_funded_accounts_indices_valid": False,
        "json_funded_accounts_addresses_valid": False,
        "json_funded_accounts_private_keys_valid": False,
        "json_funded_accounts_balances_keys_exact": False,
        "json_funded_accounts_balances_values_correct": False,

        # Contracts validation
        "json_contracts_keys_exact": False,
        "json_contracts_values_correct": False,

        # Pools validation
        "json_pools_include_usdc_weth_005": False,
        "json_pools_include_usdc_weth_030": False,

        # Cross-file consistency
        "rpc_url_txt_matches_json": False,

        # README rubric checks
        "readme_has_local_testnet_ready": False,
        "readme_mentions_chain_id_and_block": False,
        "readme_lists_5_accounts_and_balances": False,
        "readme_shows_key_contract_addresses": False,
        "readme_includes_two_available_pools": False,
        "readme_has_test_keys_mainnet_warning": False,
        "readme_has_next_steps_bullets": False,
    }

    summary_path = os.path.join(output_dir, "testnet_summary.json")
    rpc_txt_path = os.path.join(output_dir, "rpc_url.txt")
    readme_path = os.path.join(output_dir, "README.md")

    # Expected constants
    expected_chain_id = 31337
    expected_mode = "fork"
    expected_fork_from = "ethereum"
    expected_block_number = 19234567
    expected_balances = {
        "ETH": 10000,
        "USDC": 1000000,
        "USDT": 1000000,
        "DAI": 10000,
        "WETH": 100,
        "UNI": 10000,
    }
    expected_balance_keys = set(expected_balances.keys())
    expected_contracts = {
        "V3Factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "NonfungiblePositionManager": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
        "UniversalRouter": "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD",
        "Permit2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "QuoterV2": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
    }
    pool_addr_005 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
    pool_addr_030 = "0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8"

    summary = None

    # Check summary JSON existence and parsing
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        summary, err = load_json(summary_path)
        if summary is not None and isinstance(summary, dict):
            checks["summary_json_parses"] = True

    # Validate JSON structure and content
    rpc_url_value = None
    funded_addresses_from_json = []
    if checks["summary_json_parses"]:
        # Top-level keys and types
        top_keys_ok = True
        required_top = {
            "rpc_url": str,
            "chain_id": (int, float),  # numeric per spec; prefer int but accept float numerically equal
            "mode": str,
            "fork_from": str,
            "block_number": (int, float),
            "funded_accounts": list,
            "contracts": dict,
            "available_pools": list,
        }
        for key, typ in required_top.items():
            if key not in summary:
                top_keys_ok = False
                break
            val = summary.get(key)
            if isinstance(typ, tuple):
                if not isinstance(val, typ):
                    top_keys_ok = False
                    break
            else:
                if not isinstance(val, typ):
                    top_keys_ok = False
                    break
        checks["json_has_required_top_keys"] = top_keys_ok

        # Specific field checks
        # chain_id
        if "chain_id" in summary and isinstance(summary["chain_id"], (int, float)):
            checks["json_chain_id_correct"] = (int(summary["chain_id"]) == expected_chain_id)

        # mode
        if "mode" in summary and isinstance(summary["mode"], str):
            checks["json_mode_correct"] = (summary["mode"] == expected_mode)

        # fork_from
        if "fork_from" in summary and isinstance(summary["fork_from"], str):
            checks["json_fork_from_correct"] = (summary["fork_from"] == expected_fork_from)

        # block_number
        if "block_number" in summary and isinstance(summary["block_number"], (int, float)):
            checks["json_block_number_correct"] = (int(summary["block_number"]) == expected_block_number)

        # rpc_url format
        if "rpc_url" in summary and isinstance(summary["rpc_url"], str):
            rpc_url_value = summary["rpc_url"]
            if re.fullmatch(r"^http://127\.0\.0\.1:\d{2,5}$", rpc_url_value):
                checks["json_rpc_url_format_valid"] = True

        # funded_accounts
        funded_accounts = summary.get("funded_accounts")
        if isinstance(funded_accounts, list):
            checks["json_funded_accounts_len_5"] = (len(funded_accounts) == 5)

            indices_ok = True
            addresses_ok = True
            keys_ok = True
            values_ok = True
            privkeys_ok = True

            for i, acct in enumerate(funded_accounts):
                if not isinstance(acct, dict):
                    indices_ok = False
                    addresses_ok = False
                    keys_ok = False
                    values_ok = False
                    privkeys_ok = False
                    break
                # index
                idx = acct.get("index")
                if not isinstance(idx, (int, float)) or int(idx) != (i + 1):
                    indices_ok = False
                # address
                addr = acct.get("address")
                if not is_0x_hex(addr, 40):
                    addresses_ok = False
                else:
                    funded_addresses_from_json.append(addr)
                # private_key
                pk = acct.get("private_key")
                if not is_0x_hex(pk, 64):
                    privkeys_ok = False
                # balances keys and values
                balances = acct.get("balances")
                if not isinstance(balances, dict):
                    keys_ok = False
                    values_ok = False
                else:
                    if set(balances.keys()) != expected_balance_keys:
                        keys_ok = False
                    else:
                        # Check numeric equality for each
                        for k, expected_val in expected_balances.items():
                            v = balances.get(k)
                            if not isinstance(v, (int, float)):
                                values_ok = False
                                break
                            if float(v) != float(expected_val):
                                values_ok = False
                                break

            checks["json_funded_accounts_indices_valid"] = indices_ok and checks["json_funded_accounts_len_5"]
            checks["json_funded_accounts_addresses_valid"] = addresses_ok and checks["json_funded_accounts_len_5"]
            checks["json_funded_accounts_private_keys_valid"] = privkeys_ok and checks["json_funded_accounts_len_5"]
            checks["json_funded_accounts_balances_keys_exact"] = keys_ok and checks["json_funded_accounts_len_5"]
            checks["json_funded_accounts_balances_values_correct"] = values_ok and checks["json_funded_accounts_len_5"]

        # contracts
        contracts = summary.get("contracts")
        if isinstance(contracts, dict):
            checks["json_contracts_keys_exact"] = (set(contracts.keys()) == set(expected_contracts.keys()))
            values_match = True
            if checks["json_contracts_keys_exact"]:
                for k, v in expected_contracts.items():
                    if contracts.get(k) != v:
                        values_match = False
                        break
            else:
                values_match = False
            checks["json_contracts_values_correct"] = values_match

        # available_pools - include two specific addresses
        pools = summary.get("available_pools")
        if isinstance(pools, list):
            has_005 = False
            has_030 = False
            for item in pools:
                if isinstance(item, dict):
                    addr = item.get("address")
                    if addr == pool_addr_005:
                        has_005 = True
                    if addr == pool_addr_030:
                        has_030 = True
            checks["json_pools_include_usdc_weth_005"] = has_005
            checks["json_pools_include_usdc_weth_030"] = has_030

    # Cross-file rpc_url.txt
    if os.path.isfile(rpc_txt_path):
        checks["has_rpc_url_txt"] = True
        content, err = read_text(rpc_txt_path)
        # Only compare if we have the rpc_url from JSON
        if content is not None and rpc_url_value is not None:
            # Accept exact match or exactly one trailing newline
            if content == rpc_url_value:
                checks["rpc_url_txt_matches_json"] = True
            elif content == rpc_url_value + "\n":
                checks["rpc_url_txt_matches_json"] = True
            else:
                checks["rpc_url_txt_matches_json"] = False

    # README checks
    readme_content = None
    if os.path.isfile(readme_path):
        checks["has_readme"] = True
        readme_content, err = read_text(readme_path)

    if isinstance(readme_content, str):
        lower = readme_content.lower()

        # Local Testnet Ready
        checks["readme_has_local_testnet_ready"] = ("local testnet ready" in lower)

        # Mentions chain id and block number
        has_chain_id = "31337" in readme_content
        has_block = "19234567" in readme_content
        checks["readme_mentions_chain_id_and_block"] = has_chain_id and has_block

        # Lists 5 accounts and balances: require all 5 addresses from JSON to appear and token symbols appear
        accounts_ok = False
        if funded_addresses_from_json and len(funded_addresses_from_json) == 5:
            addresses_present = all(addr in readme_content for addr in funded_addresses_from_json)
            tokens_present = all(tok in readme_content for tok in expected_balance_keys)
            accounts_ok = addresses_present and tokens_present
        checks["readme_lists_5_accounts_and_balances"] = accounts_ok

        # Shows key contract addresses
        contracts_ok = all(addr in readme_content for addr in expected_contracts.values())
        checks["readme_shows_key_contract_addresses"] = contracts_ok

        # Includes two available pools (by address presence)
        pools_ok = (pool_addr_005 in readme_content) and (pool_addr_030 in readme_content)
        checks["readme_includes_two_available_pools"] = pools_ok

        # Explicit warning that these are test-only keys and must never be used on mainnet
        # Look for 'test' and 'key' and 'mainnet' and 'never' words
        has_test = re.search(r"\btest[-\s]?only\b", lower) or re.search(r"\btest\b", lower)
        has_key_word = re.search(r"\bkey\b", lower) or re.search(r"\bkeys\b", lower)
        has_mainnet = "mainnet" in lower
        has_never = "never" in lower
        checks["readme_has_test_keys_mainnet_warning"] = bool(has_test and has_key_word and has_mainnet and has_never)

        # Next Steps: section with at least three actionable bullets relevant to swaps/LP testing
        next_steps_ok = False
        # Find "Next Steps" location
        ns_match = re.search(r"next steps", lower)
        if ns_match:
            start = ns_match.start()
            segment = readme_content[start:]
            # Count bullet lines after Next Steps
            lines = segment.splitlines()
            # Skip the first line which is the title row
            bullet_lines = []
            started = False
            for ln in lines:
                if not started:
                    # Once we pass the line that contains "Next Steps", start collecting
                    if re.search(r"next steps", ln, flags=re.IGNORECASE):
                        started = True
                        continue
                # Collect bullets
                if re.match(r"^\s*[\-\*\u2022]\s+", ln):
                    bullet_lines.append(ln.strip())

            # Define relevant keywords
            keywords = [
                "swap", "quote", "pool", "liquidity", "lp", "advance time", "time", "fund", "configure", "wallet",
                "approve", "position", "add liquidity", "create", "uniswap"
            ]
            actionable_count = 0
            for b in bullet_lines:
                b_lower = b.lower()
                if any(kw in b_lower for kw in keywords):
                    actionable_count += 1
            next_steps_ok = actionable_count >= 3
        checks["readme_has_next_steps_bullets"] = next_steps_ok

    # Compute reward as fraction of passed checks; ensure 0 if no artifacts or empty output
    # No-op baseline: if output directory missing or none of the three required files exist, reward = 0.0
    required_files_exist = any([checks["has_summary_json"], checks["has_rpc_url_txt"], checks["has_readme"]])
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if required_files_exist:
        reward = passed_checks / total_checks
    else:
        reward = 0.0

    # Ensure reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()