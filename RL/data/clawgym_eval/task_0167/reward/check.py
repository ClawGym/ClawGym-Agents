import json
import os
import sys
from datetime import datetime

def nearly_equal(a, b, tol=1e-2):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_get(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def parse_leaderboard(lb):
    # Accept list or dict with "data"
    rows = lb
    if isinstance(lb, dict):
        rows = lb.get("data") or lb.get("rows") or lb.get("leaders") or []
    if not isinstance(rows, list):
        rows = []
    result = []
    for w in rows:
        name = safe_get(w, ["name", "userName", "pseudonym"], "")
        address = safe_get(w, ["address", "proxyWallet"], "")
        pnl = safe_get(w, ["pnl", "profit"], 0.0)
        vol = safe_get(w, ["vol", "volume"], 0.0)
        if address:
            result.append({
                "name": str(name),
                "address": str(address),
                "pnl": float(pnl) if isinstance(pnl, (int, float, str)) and str(pnl).strip() != "" else 0.0,
                "vol": float(vol) if isinstance(vol, (int, float, str)) and str(vol).strip() != "" else 0.0,
            })
    return result

def parse_positions_list(data):
    # positions may be a list at top-level or under a key
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["positions", "data", "items"]:
            if key in data and isinstance(data[key], list):
                return data[key]
    return []

def normalize_position(p, markets_map):
    # Extract fields with flexible keys
    condition_id = safe_get(p, ["conditionId", "condition_id", "marketId", "conditionID", "id"])
    if condition_id is None:
        return None
    condition_id = str(condition_id)

    outcome_raw = safe_get(p, ["outcome", "side"])
    outcome = str(outcome_raw).strip().upper() if outcome_raw is not None else None
    if outcome not in ("YES", "NO"):
        # try normalizing truthy/falsey
        if str(outcome_raw).lower() in ("y", "true", "1"):
            outcome = "YES"
        elif str(outcome_raw).lower() in ("n", "false", "0"):
            outcome = "NO"
        else:
            # leave as-is uppercase token
            outcome = str(outcome_raw).strip().upper() if outcome_raw is not None else ""

    shares = safe_get(p, ["shares", "size", "quantity", "qty", "currentValue"])
    try:
        shares = float(shares)
    except Exception:
        return None

    avg_price = safe_get(p, ["avg_price", "avgPrice", "averagePrice"])
    curr_price = safe_get(p, ["curr_price", "curPrice", "currentPrice", "price"])

    try:
        avg_price = float(avg_price)
    except Exception:
        avg_price = None
    try:
        curr_price = float(curr_price)
    except Exception:
        curr_price = None

    # Require prices to compute results
    if avg_price is None or curr_price is None:
        return None

    # Title resolution
    title = safe_get(p, ["market_title", "title", "market", "question"])
    market_title = str(title) if title else markets_map.get(condition_id) or condition_id

    position_usd = curr_price * shares
    pnl_usd = (curr_price - avg_price) * shares

    return {
        "conditionId": condition_id,
        "market_title": market_title,
        "outcome": outcome,
        "shares": shares,
        "avg_price": avg_price,
        "curr_price": curr_price,
        "position_usd": position_usd,
        "pnl_usd": pnl_usd,
    }

def compute_expected(workspace_root, min_threshold=10.0):
    input_dir = os.path.join(workspace_root, "input")
    # Load leaderboard and markets
    lb_path = os.path.join(input_dir, "leaderboard.json")
    mk_path = os.path.join(input_dir, "markets.json")
    positions_dir = os.path.join(input_dir, "positions")

    lb = read_json(lb_path)
    markets = read_json(mk_path)
    # markets.json assumed mapping of conditionId to question string
    if isinstance(markets, dict):
        markets_map = {str(k): str(v) for k, v in markets.items()}
    else:
        # fallback if provided as list of {conditionId, question}
        markets_map = {}
        if isinstance(markets, list):
            for m in markets:
                cid = safe_get(m, ["conditionId", "id"])
                q = safe_get(m, ["question", "title"])
                if cid and q:
                    markets_map[str(cid)] = str(q)

    whales_lb = parse_leaderboard(lb)
    # Intersect with positions files present
    available_files = set()
    if os.path.isdir(positions_dir):
        for fn in os.listdir(positions_dir):
            if fn.lower().endswith(".json"):
                available_files.add(fn[:-5])  # strip .json

    whales = []
    for w in whales_lb:
        if w["address"] in available_files:
            whales.append(w)

    # Ensure deterministic set (expected exactly three)
    whales_by_addr = {w["address"]: w for w in whales}

    # Build expected positions per whale
    expected_whale_positions = {}
    for addr, whale in whales_by_addr.items():
        path = os.path.join(positions_dir, f"{addr}.json")
        try:
            pdata = read_json(path)
        except Exception:
            pdata = []
        plist = parse_positions_list(pdata)
        normalized = []
        for p in plist:
            norm = normalize_position(p, markets_map)
            if norm is None:
                continue
            if norm["position_usd"] >= min_threshold:
                # Ensure market_title resolution uses markets mapping if available
                resolved_title = markets_map.get(norm["conditionId"], norm["market_title"])
                norm["market_title"] = resolved_title
                normalized.append(norm)
        expected_whale_positions[addr] = normalized

    # Compute signals
    # group key: (conditionId, outcome)
    groups = {}
    for addr, positions in expected_whale_positions.items():
        name = whales_by_addr.get(addr, {}).get("name", "")
        for p in positions:
            key = (p["conditionId"], p["outcome"])
            g = groups.setdefault(key, {"conditionId": p["conditionId"], "outcome": p["outcome"], "market_title": p["market_title"], "whales": []})
            g["whales"].append({
                "address": addr,
                "name": name,
                "position_usd": p["position_usd"],
            })

    expected_signals = []
    for key, g in groups.items():
        whales_list = g["whales"]
        num_whales = len(whales_list)
        total_position_usd = sum(w["position_usd"] for w in whales_list)
        conviction = None
        if num_whales >= 2:
            conviction = "high"
        elif num_whales == 1 and total_position_usd >= 50000:
            conviction = "medium"
        if conviction:
            expected_signals.append({
                "conditionId": g["conditionId"],
                "market_title": g["market_title"],
                "outcome": g["outcome"],
                "conviction": conviction,
                "num_whales": num_whales,
                "total_position_usd": total_position_usd,
                "whales": whales_list,
            })

    return whales_by_addr, expected_whale_positions, expected_signals, markets_map

def validate_whale_positions(out_path, whales_by_addr, expected_whale_positions, markets_map, min_threshold=10.0):
    checks = {
        "whale_positions_exists": False,
        "whale_positions_json_valid": False,
        "whale_positions_min_threshold": False,
        "whales_count_and_identity": False,
        "whales_have_pnl_vol_numeric": False,
        "positions_titles_resolved": False,
        "positions_values_correct": False,
        "positions_filter_applied": False,
        "positions_counts_match": False,
    }
    if not os.path.isfile(out_path):
        return checks

    checks["whale_positions_exists"] = True

    try:
        data = read_json(out_path)
        checks["whale_positions_json_valid"] = isinstance(data, dict)
    except Exception:
        return checks

    if not isinstance(data, dict):
        return checks

    # min_position_usd
    if "min_position_usd" in data and data["min_position_usd"] == 10:
        checks["whale_positions_min_threshold"] = True

    whales = data.get("whales")
    if not isinstance(whales, list):
        return checks

    # Check count and identity (addresses and names)
    expected_addresses = set(whales_by_addr.keys())
    out_addresses = set()
    name_match = True
    for w in whales:
        addr = w.get("address")
        name = w.get("name")
        if isinstance(addr, str):
            out_addresses.add(addr)
            exp = whales_by_addr.get(addr)
            if exp:
                if str(name) != str(exp["name"]):
                    name_match = False
    if out_addresses == expected_addresses and name_match and len(whales) == len(expected_addresses):
        checks["whales_count_and_identity"] = True

    # Check pnl and vol numeric
    pnl_vol_ok = True
    for w in whales:
        pnl = w.get("pnl")
        vol = w.get("vol")
        try:
            _ = float(pnl)
            _ = float(vol)
        except Exception:
            pnl_vol_ok = False
            break
    checks["whales_have_pnl_vol_numeric"] = pnl_vol_ok

    # Positions per whale
    titles_ok = True
    values_ok = True
    filter_ok = True
    counts_ok = True

    # Build mapping from out whales by address
    whales_by_addr_out = {w.get("address"): w for w in whales if isinstance(w, dict) and "address" in w}

    for addr, expected_positions in expected_whale_positions.items():
        out_w = whales_by_addr_out.get(addr)
        out_positions = out_w.get("positions") if isinstance(out_w, dict) else None
        if not isinstance(out_positions, list):
            counts_ok = False
            values_ok = False
            titles_ok = False
            filter_ok = False
            continue

        # Check filter: no positions under threshold
        for p in out_positions:
            pos_usd = p.get("position_usd")
            try:
                if float(pos_usd) < min_threshold:
                    filter_ok = False
                    break
            except Exception:
                filter_ok = False
                break

        # Compare counts
        if len(out_positions) != len(expected_positions):
            counts_ok = False

        # Build index by (conditionId, outcome)
        out_index = {}
        for p in out_positions:
            cid = str(p.get("conditionId"))
            outcome = str(p.get("outcome")).upper() if p.get("outcome") else ""
            out_index[(cid, outcome)] = p

        for ep in expected_positions:
            key = (ep["conditionId"], ep["outcome"])
            op = out_index.get(key)
            if not op:
                values_ok = False
                titles_ok = False
                continue
            # Title
            exp_title = markets_map.get(ep["conditionId"], ep["market_title"])
            if str(op.get("market_title")) != str(exp_title):
                titles_ok = False
            # Numeric fields
            try:
                shares_ok = nearly_equal(op.get("shares"), ep["shares"], tol=1e-4)
                avg_ok = nearly_equal(op.get("avg_price"), ep["avg_price"], tol=1e-4)
                curr_ok = nearly_equal(op.get("curr_price"), ep["curr_price"], tol=1e-4)
                pos_ok = nearly_equal(op.get("position_usd"), ep["position_usd"], tol=1e-2)
                pnl_ok = nearly_equal(op.get("pnl_usd"), ep["pnl_usd"], tol=1e-2)
                if not (shares_ok and avg_ok and curr_ok and pos_ok and pnl_ok):
                    values_ok = False
            except Exception:
                values_ok = False

    checks["positions_titles_resolved"] = titles_ok
    checks["positions_values_correct"] = values_ok
    checks["positions_filter_applied"] = filter_ok
    checks["positions_counts_match"] = counts_ok

    return checks

def validate_signals(out_path, expected_signals, markets_map, min_threshold=10.0):
    checks = {
        "signals_exists": False,
        "signals_json_valid": False,
        "signals_min_threshold": False,
        "signals_count_correct": False,
        "signals_groups_correct": False,
        "signals_values_correct": False,
        "signals_no_extras": False,
    }
    if not os.path.isfile(out_path):
        return checks

    checks["signals_exists"] = True

    try:
        data = read_json(out_path)
        checks["signals_json_valid"] = isinstance(data, dict)
    except Exception:
        return checks

    if not isinstance(data, dict):
        return checks

    if "min_position_usd" in data and data["min_position_usd"] == 10:
        checks["signals_min_threshold"] = True

    out_signals = data.get("signals")
    if not isinstance(out_signals, list):
        return checks

    # Count check
    if len(out_signals) == len(expected_signals):
        checks["signals_count_correct"] = True

    # Build index for comparison: (conditionId, outcome)
    def key_sig(s):
        return (str(s.get("conditionId")), str(s.get("outcome")).upper() if s.get("outcome") else "")

    out_index = {key_sig(s): s for s in out_signals}

    groups_ok = True
    values_ok = True

    for es in expected_signals:
        key = (es["conditionId"], es["outcome"])
        osig = out_index.get(key)
        if not osig:
            groups_ok = False
            values_ok = False
            continue
        # Title
        exp_title = markets_map.get(es["conditionId"], es["market_title"])
        if str(osig.get("market_title")) != str(exp_title):
            groups_ok = False
        # Conviction and counts
        if osig.get("conviction") != es["conviction"]:
            values_ok = False
        if int(osig.get("num_whales") or -1) != int(es["num_whales"]):
            values_ok = False
        # Total
        if not nearly_equal(osig.get("total_position_usd"), es["total_position_usd"], tol=1e-2):
            values_ok = False
        # Whales list contents (addresses and per-position_usd)
        ow = osig.get("whales")
        if not isinstance(ow, list):
            values_ok = False
            continue
        exp_addr_map = {w["address"]: w for w in es["whales"]}
        out_addr_map = {w.get("address"): w for w in ow if isinstance(w, dict) and w.get("address")}
        if set(exp_addr_map.keys()) != set(out_addr_map.keys()):
            values_ok = False
        else:
            for addr, ew in exp_addr_map.items():
                ow_entry = out_addr_map.get(addr)
                if not ow_entry:
                    values_ok = False
                    continue
                # Check position_usd per whale
                if not nearly_equal(ow_entry.get("position_usd"), ew["position_usd"], tol=1e-2):
                    values_ok = False
                # Name is optional in spec but we verify if present
                if "name" in ow_entry:
                    if str(ow_entry["name"]) != str(ew["name"]):
                        values_ok = False

    checks["signals_groups_correct"] = groups_ok
    checks["signals_values_correct"] = values_ok

    # No extras: ensure that every out signal is expected
    expected_keys = {(es["conditionId"], es["outcome"]) for es in expected_signals}
    out_keys = set(out_index.keys())
    if out_keys == expected_keys:
        checks["signals_no_extras"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Compute expected from inputs
    try:
        whales_by_addr, expected_whale_positions, expected_signals, markets_map = compute_expected(workspace_root, min_threshold=10.0)
    except Exception:
        # If inputs missing or malformed, we cannot grant reward, but we should still output JSON
        whales_by_addr, expected_whale_positions, expected_signals, markets_map = {}, {}, [], {}

    # Validate outputs
    whale_positions_path = os.path.join(output_dir, "whale_positions.json")
    signals_path = os.path.join(output_dir, "signals.json")

    checks_wp = validate_whale_positions(whale_positions_path, whales_by_addr, expected_whale_positions, markets_map, min_threshold=10.0)
    checks_sig = validate_signals(signals_path, expected_signals, markets_map, min_threshold=10.0)

    checks = {}
    checks.update(checks_wp)
    checks.update(checks_sig)

    # Compute reward: proportion of passed checks; baseline 0.0 if outputs missing or empty
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # Ensure baseline no-op yields 0.0
    if not checks.get("whale_positions_exists") and not checks.get("signals_exists"):
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": float(reward)}
    result.update(checks)

    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()