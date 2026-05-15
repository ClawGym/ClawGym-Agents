import json
import os
import sys
import csv
import shlex

def load_universe(csv_path):
    symbols_stock = []
    symbols_crypto = []
    seen_stock = set()
    seen_crypto = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalize headers to lower-case
        field_map = {k: k.lower() for k in reader.fieldnames or []}
        for row in reader:
            # Normalize keys
            lower_row = {field_map.get(k, k).lower(): v for k, v in row.items()}
            category = (lower_row.get("category") or "").strip().lower()
            symbol = (lower_row.get("symbol") or "").strip()
            if not category or not symbol:
                continue
            if category == "stock":
                if symbol not in seen_stock:
                    symbols_stock.append(symbol)
                    seen_stock.add(symbol)
            elif category == "crypto":
                if symbol not in seen_crypto:
                    symbols_crypto.append(symbol)
                    seen_crypto.add(symbol)
            else:
                # Ignore unknown categories
                continue
    return symbols_stock, symbols_crypto

def load_monitor_spec(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    # Required fields
    history_days_stock = int(obj["history_days_stock"])
    history_days_crypto = int(obj["history_days_crypto"])
    macro_series = list(obj["macro_series"])
    macro_limit = int(obj["macro_limit"])
    # Optional fields present but unused for command generation specifics (we still parse)
    # filing_types, filings_latest_only may be present, but we follow the fixed spec
    return {
        "history_days_stock": history_days_stock,
        "history_days_crypto": history_days_crypto,
        "macro_series": macro_series,
        "macro_limit": macro_limit,
    }

def expected_items(symbols_stock, symbols_crypto, spec):
    exp = []
    # Stocks
    for s in symbols_stock:
        base = f"output/data/stocks/{s}"
        exp.extend([
            ("stock", s, "quote", f"{base}/quote.json"),
            ("stock", s, "history", f"{base}/history.json"),
            ("stock", s, "earnings", f"{base}/earnings.json"),
            ("stock", s, "dividends", f"{base}/dividends.json"),
            ("stock", s, "options_calls", f"{base}/options_calls.json"),
            ("stock", s, "filings_10-K_latest", f"{base}/filings_10-K_latest.json"),
        ])
    # Crypto
    for c in symbols_crypto:
        base = f"output/data/crypto/{c}"
        exp.extend([
            ("crypto", c, "price", f"{base}/price.json"),
            ("crypto", c, "history", f"{base}/history.json"),
        ])
    # Macro
    for m in spec["macro_series"]:
        exp.append(("macro", m, "macro", f"output/data/macro/{m}.json"))
    return exp

def parse_command_line(line):
    # Returns parsed dict or None if invalid
    # Structure: {category,id,datatype,path, flags_ok, redirect_ok, details...}
    result = {
        "valid": False,
        "path": None,
        "category": None,
        "id": None,
        "datatype": None,
        "flags_ok": False,
        "redirect_ok": False,
        "has_json": False,
        "has_no_cache": False,
        "options_calls_flag": False,
        "filing_10k_latest": False,
        "stock_history_days": None,
        "crypto_history_days": None,
        "macro_limit": None,
        "macro_worldbank": False,
        "subcommand": None,
    }
    # Check single redirection '>'
    if line.count(">") != 1:
        return result
    lhs, rhs = line.split(">", 1)
    lhs = lhs.strip()
    rhs = rhs.strip()
    # Validate redirection path
    if rhs.startswith("output/") and rhs.endswith(".json"):
        result["redirect_ok"] = True
        result["path"] = rhs
    # Tokenize lhs
    try:
        tokens = shlex.split(lhs)
    except Exception:
        return result
    if not tokens:
        return result
    if tokens[0] != "omd":
        return result
    # Must include --json and --no-cache
    has_json = "--json" in tokens
    has_no_cache = "--no-cache" in tokens
    result["has_json"] = has_json
    result["has_no_cache"] = has_no_cache
    # Find primary subcommand index
    known_cmds = {"quote","search","financials","history","earnings","dividends","options","filing","insiders","crypto","macro","sources","config"}
    sub_idx = None
    for i in range(1, len(tokens)):
        t = tokens[i]
        if t in known_cmds:
            sub_idx = i
            result["subcommand"] = t
            break
    if sub_idx is None:
        return result
    # Parse by subcommand
    ok = False
    dtype = None
    category = None
    id_ = None
    # Helper to get option value
    def get_opt_value(name_short, name_long):
        val = None
        for j in range(sub_idx+1, len(tokens)):
            if name_short and tokens[j] == name_short and j+1 < len(tokens):
                return tokens[j+1]
            if name_long and tokens[j] == name_long and j+1 < len(tokens):
                return tokens[j+1]
        return val
    # Helper for presence flags
    def has_flag(flag):
        return flag in tokens
    if tokens[sub_idx] == "quote":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "quote"
            ok = True
    elif tokens[sub_idx] == "history":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "history"
            # days
            days_val = get_opt_value(None, "--days")
            if days_val is not None:
                try:
                    result["stock_history_days"] = int(days_val)
                except ValueError:
                    pass
            ok = True
    elif tokens[sub_idx] == "earnings":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "earnings"
            ok = True
    elif tokens[sub_idx] == "dividends":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "dividends"
            ok = True
    elif tokens[sub_idx] == "options":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "options_calls"
            # must have -t call
            t_val = get_opt_value("-t", None)
            if t_val is not None and t_val.lower() == "call":
                result["options_calls_flag"] = True
            ok = True
    elif tokens[sub_idx] == "filing":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "stock"
            dtype = "filings_10-K_latest"
            type_val = get_opt_value(None, "--type")
            latest_flag = has_flag("--latest")
            if type_val == "10-K" and latest_flag:
                result["filing_10k_latest"] = True
            ok = True
    elif tokens[sub_idx] == "crypto":
        # either: crypto SYMBOL (price) or crypto history SYMBOL -d N
        if sub_idx+1 < len(tokens):
            next_tok = tokens[sub_idx+1]
            if next_tok == "history":
                if sub_idx+2 < len(tokens):
                    id_ = tokens[sub_idx+2]
                    category = "crypto"
                    dtype = "history"
                    d_val = get_opt_value("-d", None)
                    if d_val is not None:
                        try:
                            result["crypto_history_days"] = int(d_val)
                        except ValueError:
                            pass
                    ok = True
            else:
                id_ = next_tok
                category = "crypto"
                dtype = "price"
                ok = True
    elif tokens[sub_idx] == "macro":
        if sub_idx+1 < len(tokens):
            id_ = tokens[sub_idx+1]
            category = "macro"
            dtype = "macro"
            lim_val = get_opt_value(None, "--limit")
            if lim_val is not None:
                try:
                    result["macro_limit"] = int(lim_val)
                except ValueError:
                    pass
            src_val = get_opt_value(None, "--source")
            if src_val is not None and src_val.lower() == "worldbank":
                result["macro_worldbank"] = True
            ok = True
    # Validate flags
    result["flags_ok"] = has_json and has_no_cache
    if ok and result["redirect_ok"] and result["flags_ok"]:
        result["valid"] = True
    result["category"] = category
    result["id"] = id_
    result["datatype"] = dtype
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "inputs_parsed": False,
        "commands_exists": False,
        "commands_flags_present": False,
        "redirects_valid": False,
        "no_duplicate_paths": False,
        "stocks_coverage": False,
        "crypto_coverage": False,
        "macro_coverage": False,
        "days_values_correct": False,
        "options_calls_flag": False,
        "filing_10k_latest": False,
        "macro_limit_correct": False,
        "macro_worldbank_for_gdp": False,
        "manifest_exists": False,
        "manifest_matches_commands": False,
        "readme_exists": False,
        "readme_contains_required": False,
    }

    universe_csv = os.path.join(input_dir, "universe.csv")
    spec_json = os.path.join(input_dir, "monitor_spec.json")

    # Try parse inputs
    try:
        symbols_stock, symbols_crypto = load_universe(universe_csv)
        spec = load_monitor_spec(spec_json)
        checks["inputs_parsed"] = True
    except Exception:
        # Parsing failed; without inputs we cannot award positive credit
        symbols_stock, symbols_crypto, spec = [], [], {"history_days_stock": None, "history_days_crypto": None, "macro_series": [], "macro_limit": None}

    # Read commands.txt
    commands_path = os.path.join(output_dir, "commands.txt")
    lines = []
    if os.path.isfile(commands_path):
        try:
            with open(commands_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip()]
        except Exception:
            lines = []
    checks["commands_exists"] = bool(lines)

    parsed = []
    if lines:
        for ln in lines:
            parsed.append(parse_command_line(ln))

        # All lines must have flags and redirects valid
        checks["commands_flags_present"] = all(p.get("has_json") and p.get("has_no_cache") for p in parsed)
        checks["redirects_valid"] = all(p.get("redirect_ok") for p in parsed)

        # No duplicate paths
        rhs_paths = [p.get("path") for p in parsed if p.get("path")]
        checks["no_duplicate_paths"] = len(rhs_paths) == len(set(rhs_paths)) and len(rhs_paths) == len(parsed)

    # Build observed mapping from commands
    # Map key (category,id,datatype) -> path and parsed info
    observed = {}
    all_valid = True
    for p in parsed:
        if not p.get("valid"):
            all_valid = False
        k = (p.get("category"), p.get("id"), p.get("datatype"))
        if None in k:
            continue
        observed[k] = {"path": p.get("path"), "info": p}

    # Build expected
    exp_items = expected_items(symbols_stock, symbols_crypto, spec) if checks["inputs_parsed"] else []

    # Coverage checks
    if checks["inputs_parsed"] and lines:
        # Stocks coverage
        stock_needed = [it for it in exp_items if it[0] == "stock"]
        checks["stocks_coverage"] = all((cat, sid, dtype) in observed and observed[(cat, sid, dtype)]["path"] == path for (cat, sid, dtype, path) in stock_needed)
        # Crypto coverage
        crypto_needed = [it for it in exp_items if it[0] == "crypto"]
        checks["crypto_coverage"] = all((cat, sid, dtype) in observed and observed[(cat, sid, dtype)]["path"] == path for (cat, sid, dtype, path) in crypto_needed)
        # Macro coverage
        macro_needed = [it for it in exp_items if it[0] == "macro"]
        checks["macro_coverage"] = all((cat, sid, dtype) in observed and observed[(cat, sid, dtype)]["path"] == path for (cat, sid, dtype, path) in macro_needed)

        # Days values correct
        days_ok = True
        for (cat, sid, dtype, path) in stock_needed:
            if dtype == "history":
                info = observed.get((cat, sid, dtype), {}).get("info")
                if not info or info.get("stock_history_days") != spec["history_days_stock"]:
                    days_ok = False
                    break
        if days_ok:
            for (cat, sid, dtype, path) in crypto_needed:
                if dtype == "history":
                    info = observed.get((cat, sid, dtype), {}).get("info")
                    if not info or info.get("crypto_history_days") != spec["history_days_crypto"]:
                        days_ok = False
                        break
        checks["days_values_correct"] = days_ok

        # Options calls flag
        opt_ok = True
        for (cat, sid, dtype, path) in stock_needed:
            if dtype == "options_calls":
                info = observed.get((cat, sid, dtype), {}).get("info")
                if not info or not info.get("options_calls_flag"):
                    opt_ok = False
                    break
        checks["options_calls_flag"] = opt_ok

        # Filing flags
        filing_ok = True
        for (cat, sid, dtype, path) in stock_needed:
            if dtype == "filings_10-K_latest":
                info = observed.get((cat, sid, dtype), {}).get("info")
                if not info or not info.get("filing_10k_latest"):
                    filing_ok = False
                    break
        checks["filing_10k_latest"] = filing_ok

        # Macro limit and worldbank for GDP
        macro_limit_ok = True
        macro_worldbank_gdp_ok = True
        for (cat, sid, dtype, path) in macro_needed:
            info = observed.get((cat, sid, dtype), {}).get("info")
            if not info:
                macro_limit_ok = False
                macro_worldbank_gdp_ok = False
                break
            if info.get("macro_limit") != spec["macro_limit"]:
                macro_limit_ok = False
            if sid == "NY.GDP.MKTP.CD":
                if not info.get("macro_worldbank"):
                    macro_worldbank_gdp_ok = False
        checks["macro_limit_correct"] = macro_limit_ok
        checks["macro_worldbank_for_gdp"] = macro_worldbank_gdp_ok

    # Manifest checks
    manifest_path = os.path.join(output_dir, "manifest.json")
    manifest_entries = None
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_entries = json.load(f)
            if isinstance(manifest_entries, list):
                checks["manifest_exists"] = True
        except Exception:
            manifest_entries = None

    if checks["manifest_exists"] and lines:
        # Build expected from commands actually present (observed)
        cmd_items = []
        for k, v in observed.items():
            category, id_, dtype = k
            path = v["path"]
            if None not in (category, id_, dtype, path):
                cmd_items.append((category, id_, dtype, path))
        manifest_ok = True
        # Validate each manifest entry has required keys and matches one command entry
        manifest_tuples = []
        for entry in manifest_entries:
            if not isinstance(entry, dict):
                manifest_ok = False
                break
            if not all(k in entry for k in ["category", "id", "datatype", "path"]):
                manifest_ok = False
                break
            cat = entry["category"]
            if cat not in ("stock", "crypto", "macro"):
                manifest_ok = False
                break
            tup = (entry["category"], entry["id"], entry["datatype"], entry["path"])
            manifest_tuples.append(tup)
        # Compare sets: exactly one object per command/file
        if manifest_ok:
            if set(manifest_tuples) != set(cmd_items):
                manifest_ok = False
        checks["manifest_matches_commands"] = manifest_ok

    # README checks
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
            checks["readme_exists"] = len(readme_text.strip()) > 0
            if checks["readme_exists"]:
                has_output_data = "output/data" in readme_text
                has_commands_txt = "commands.txt" in readme_text
                checks["readme_contains_required"] = has_output_data and has_commands_txt
        except Exception:
            pass

    # Compute reward
    reward = 0.0
    if checks["commands_exists"] and checks["inputs_parsed"]:
        scored_keys = [
            "commands_flags_present",
            "redirects_valid",
            "no_duplicate_paths",
            "stocks_coverage",
            "crypto_coverage",
            "macro_coverage",
            "days_values_correct",
            "options_calls_flag",
            "filing_10k_latest",
            "macro_limit_correct",
            "macro_worldbank_for_gdp",
            "manifest_exists",
            "manifest_matches_commands",
            "readme_exists",
            "readme_contains_required",
        ]
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0
    else:
        reward = 0.0

    # Ensure numeric bounds
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()