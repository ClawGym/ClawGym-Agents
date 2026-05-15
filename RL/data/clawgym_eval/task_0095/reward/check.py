import json
import math
import os
import sys

def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_klines_closes(path):
    data = read_json(path)
    closes = []
    if isinstance(data, list):
        for row in data:
            # Expect Binance kline array: [openTime, open, high, low, close, volume, ...]
            try:
                closes.append(float(row[4]))
            except Exception:
                # If not a list-like, try dict with 'close'
                if isinstance(row, dict) and "close" in row:
                    closes.append(float(row["close"]))
                else:
                    raise
    return closes

def parse_1h_open(path):
    data = read_json(path)
    # Expect a list with one kline row; open is index 1
    if isinstance(data, list) and len(data) >= 1:
        row = data[0]
        try:
            return float(row[1])
        except Exception:
            # Fallback: dict with key 'open'
            if isinstance(row, dict) and "open" in row:
                return float(row["open"])
    # Fallback: direct number
    try:
        return float(data)
    except Exception:
        raise ValueError("Cannot parse 1h open price from input/klines_1h_open.json")

def compute_sigma_1m(closes):
    rets = []
    for i in range(len(closes) - 1):
        a = closes[i]
        b = closes[i + 1]
        if a != 0:
            rets.append((b - a) / a)
    if len(rets) >= 2:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        sigma = math.sqrt(var)
    else:
        sigma = 0.0
    return sigma

def compute_expected(input_dir):
    # Load inputs
    open_px = parse_1h_open(os.path.join(input_dir, "klines_1h_open.json"))
    params = read_json(os.path.join(input_dir, "params.json"))
    spot = float(params.get("spot"))
    minutes_left = float(params.get("minutes_left"))
    EDGE_MIN = float(params.get("EDGE_MIN"))
    z_guard = float(params.get("z_guard"))
    Z_HOLD = float(params.get("Z_HOLD"))
    market = read_json(os.path.join(input_dir, "market_prices.json"))
    price_up = float(market.get("price_up"))
    price_down = float(market.get("price_down"))
    closes = parse_klines_closes(os.path.join(input_dir, "klines_1m.json"))
    sigma_1m = compute_sigma_1m(closes)
    # Compute z and fair
    cur_ret = 0.0 if open_px == 0 else (spot - open_px) / open_px
    stdev = sigma_1m * math.sqrt(max(0.0, minutes_left))
    denom = max(stdev, 1e-9)
    z = cur_ret / denom
    fair_up = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    fair_down = 1.0 - fair_up
    edge_up = fair_up - price_up
    edge_down = fair_down - price_down
    # Guardrails
    blocked = []
    if abs(z) >= z_guard:
        if z > 0:
            blocked.append("Down")
        elif z < 0:
            blocked.append("Up")
    # Decision
    allowed = []
    if "Up" not in blocked and edge_up > EDGE_MIN:
        allowed.append(("Up", edge_up))
    if "Down" not in blocked and edge_down > EDGE_MIN:
        allowed.append(("Down", edge_down))
    decision_options = []
    if not allowed:
        decision_options = ["None"]
    else:
        # Choose the side with the highest edge; accept ties both ways
        allowed_sorted = sorted(allowed, key=lambda x: x[1], reverse=True)
        best_edge = allowed_sorted[0][1]
        best_sides = [s for s, e in allowed if abs(e - best_edge) <= 1e-9]
        decision_options = best_sides
    # Hold to preclose condition
    def hold_flag_for_side(side):
        if side == "Up":
            return z >= Z_HOLD
        if side == "Down":
            return z <= -Z_HOLD
        return False
    return {
        "open_px": open_px,
        "spot": spot,
        "minutes_left": minutes_left,
        "sigma_1m": sigma_1m,
        "z": z,
        "fair_up": fair_up,
        "fair_down": fair_down,
        "market": {"price_up": price_up, "price_down": price_down},
        "edges": {"edge_up": edge_up, "edge_down": edge_down},
        "guardrails": {"z_guard": z_guard, "blocked_required": blocked},
        "decision_options": decision_options,
        "EDGE_MIN": EDGE_MIN,
        "Z_HOLD": Z_HOLD,
        "hold_flag_for_side": hold_flag_for_side,
        "closes": closes,
    }

def load_events_jsonl(path):
    events = []
    if not os.path.isfile(path):
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                events.append(j)
            except Exception:
                continue
    return events

def check_analysis(output_dir, expected):
    checks = {
        "analysis_exists": False,
        "analysis_fields": False,
        "analysis_values": False,
        "analysis_guardrails": False,
        "analysis_decision": False,
    }
    path = os.path.join(output_dir, "analysis.json")
    if not os.path.isfile(path):
        return checks
    checks["analysis_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return checks
    # Field presence
    def has_path(obj, keys):
        o = obj
        for k in keys:
            if not isinstance(o, dict) or k not in o:
                return False
            o = o[k]
        return True
    required_paths = [
        ("open_px",),
        ("spot",),
        ("minutes_left",),
        ("sigma_1m",),
        ("z",),
        ("fair_up",),
        ("fair_down",),
        ("market", "price_up"),
        ("market", "price_down"),
        ("edge_up",),
        ("edge_down",),
        ("guardrails", "z_guard"),
        ("guardrails", "blocked"),
        ("decision", "enter"),
        ("decision", "reason"),
        ("decision", "hold_to_preclose"),
    ]
    fields_ok = all(has_path(j, p) for p in required_paths)
    checks["analysis_fields"] = fields_ok
    if not fields_ok:
        return checks
    # Values check
    try:
        vals_ok = True
        vals_ok &= almost_equal(j["open_px"], expected["open_px"], 1e-6)
        vals_ok &= almost_equal(j["spot"], expected["spot"], 1e-6)
        vals_ok &= almost_equal(j["minutes_left"], expected["minutes_left"], 1e-6)
        vals_ok &= almost_equal(j["sigma_1m"], expected["sigma_1m"], 1e-6)
        vals_ok &= almost_equal(j["z"], expected["z"], 1e-6)
        vals_ok &= almost_equal(j["fair_up"], expected["fair_up"], 1e-6)
        vals_ok &= almost_equal(j["fair_down"], expected["fair_down"], 1e-6)
        vals_ok &= almost_equal(j["market"]["price_up"], expected["market"]["price_up"], 1e-6)
        vals_ok &= almost_equal(j["market"]["price_down"], expected["market"]["price_down"], 1e-6)
        # Edges
        vals_ok &= almost_equal(j["edge_up"], expected["edges"]["edge_up"], 1e-6)
        vals_ok &= almost_equal(j["edge_down"], expected["edges"]["edge_down"], 1e-6)
        checks["analysis_values"] = bool(vals_ok)
        # Guardrails
        guard_ok = True
        guard_ok &= almost_equal(j["guardrails"]["z_guard"], expected["guardrails"]["z_guard"], 1e-6)
        blocked_reported = j["guardrails"].get("blocked", [])
        if not isinstance(blocked_reported, list):
            blocked_reported = []
        # Must include required blocks
        for b in expected["guardrails"]["blocked_required"]:
            if b not in blocked_reported:
                guard_ok = False
                break
        checks["analysis_guardrails"] = bool(guard_ok)
        # Decision
        decision_ok = True
        enter = str(j["decision"].get("enter"))
        reason = j["decision"].get("reason")
        hold = bool(j["decision"].get("hold_to_preclose"))
        # reason must be a string
        if not isinstance(reason, str):
            decision_ok = False
        # Decision correctness: accept "None" if no allowed; otherwise accept any in expected options
        options = expected["decision_options"]
        if options == ["None"]:
            if enter != "None":
                decision_ok = False
            # No hold when no entry
            if hold:
                decision_ok = False
        else:
            if enter not in options:
                decision_ok = False
            # Hold flag check
            expected_hold = expected["hold_flag_for_side"](enter)
            if bool(hold) != bool(expected_hold):
                decision_ok = False
        checks["analysis_decision"] = bool(decision_ok)
    except Exception:
        # Any parsing or missing field error leaves checks as is
        pass
    return checks

def check_fills(output_dir, input_dir, expected):
    checks = {
        "fills_exists": False,
        "fills_header_ok": False,
        "fills_count_ok": False,
        "fills_values_ok": False,
    }
    path = os.path.join(output_dir, "fills_explained.tsv")
    if not os.path.isfile(path):
        return checks
    checks["fills_exists"] = True
    events = load_events_jsonl(os.path.join(input_dir, "events.jsonl"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return checks
    if not lines:
        return checks
    header = lines[0]
    expected_header = "ts\tside\ttoken\tpx\tfair_up\tz\tagainst_trend"
    checks["fills_header_ok"] = (header == expected_header)
    data_lines = lines[1:]
    # The number of data lines should match number of events
    checks["fills_count_ok"] = (len(data_lines) == len(events))
    if not checks["fills_count_ok"]:
        # Cannot reliably check values if count mismatch
        return checks
    # Compute expected fair_up and z once
    z = expected["z"]
    fair_up = expected["fair_up"]
    values_ok = True
    for idx, (line, evt) in enumerate(zip(data_lines, events)):
        parts = line.split("\t")
        if len(parts) != 7:
            values_ok = False
            break
        ts, side, token, px_s, fair_up_s, z_s, against = parts
        # Match fields from events
        if str(ts) != str(evt.get("ts", "")):
            values_ok = False; break
        if str(side) != str(evt.get("side", "")):
            values_ok = False; break
        if str(token) != str(evt.get("token", "")):
            values_ok = False; break
        try:
            px_out = float(px_s)
            px_in = float(evt.get("px"))
            if not almost_equal(px_out, px_in, 1e-6):
                values_ok = False; break
        except Exception:
            values_ok = False; break
        # fair_up and z must match expected computed values within tolerance
        try:
            if not almost_equal(float(fair_up_s), fair_up, 1e-6):
                values_ok = False; break
            if not almost_equal(float(z_s), z, 1e-6):
                values_ok = False; break
        except Exception:
            values_ok = False; break
        # against_trend logic
        token_str = str(token)
        expected_against = "YES" if (("Up" in token_str and z < -0.25) or ("Down" in token_str and z > 0.25)) else "NO"
        if against != expected_against:
            values_ok = False; break
    checks["fills_values_ok"] = bool(values_ok)
    return checks

def check_regime(output_dir, input_dir):
    checks = {
        "regime_exists": False,
        "regime_values_ok": False,
    }
    path = os.path.join(output_dir, "regime.json")
    if not os.path.isfile(path):
        return checks
    checks["regime_exists"] = True
    try:
        j = read_json(path)
    except Exception:
        return checks
    # Compute expected regime metrics
    closes = parse_klines_closes(os.path.join(input_dir, "klines_1m.json"))
    try:
        ret5 = closes[-1] / closes[-6] - 1.0
        ret15 = closes[-1] / closes[-16] - 1.0
        slope10 = closes[-1] - closes[-11]
        last15_low = min(closes[-16:])
        prev15_low = min(closes[-31:-15])
        stabilized = (ret5 > 0.0005) and (slope10 > 0) and (last15_low >= prev15_low) and (ret15 > -0.0025)
    except Exception:
        return checks
    try:
        ok = True
        ok &= almost_equal(j.get("ret5"), ret5, 1e-9)
        ok &= almost_equal(j.get("ret15"), ret15, 1e-9)
        ok &= almost_equal(j.get("slope10"), slope10, 1e-9)
        ok &= almost_equal(j.get("last15_low"), last15_low, 1e-9)
        ok &= almost_equal(j.get("prev15_low"), prev15_low, 1e-9)
        ok &= (bool(j.get("stabilized")) == bool(stabilized))
        checks["regime_values_ok"] = bool(ok)
    except Exception:
        pass
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Prepare checks dict with defaults False
    checks = {
        "analysis_exists": False,
        "analysis_fields": False,
        "analysis_values": False,
        "analysis_guardrails": False,
        "analysis_decision": False,
        "fills_exists": False,
        "fills_header_ok": False,
        "fills_count_ok": False,
        "fills_values_ok": False,
        "regime_exists": False,
        "regime_values_ok": False,
    }
    try:
        expected = compute_expected(input_dir)
    except Exception:
        expected = None
    # Analysis checks
    if expected is not None:
        analysis_checks = check_analysis(output_dir, expected)
        checks.update(analysis_checks)
        # Fills checks
        fills_checks = check_fills(output_dir, input_dir, expected)
        checks.update(fills_checks)
    else:
        # Still can check file existence but values depend on inputs; leave as False
        pass
    # Regime checks
    regime_checks = check_regime(output_dir, input_dir)
    checks.update(regime_checks)
    # Compute reward
    reward = 0.0
    # Analysis weights (0.34 total)
    if checks["analysis_exists"]:
        reward += 0.04
    if checks["analysis_fields"]:
        reward += 0.06
    if checks["analysis_values"]:
        reward += 0.15
    if checks["analysis_guardrails"]:
        reward += 0.05
    if checks["analysis_decision"]:
        reward += 0.04
    # Fills weights (0.33 total)
    if checks["fills_exists"]:
        reward += 0.05
    if checks["fills_header_ok"]:
        reward += 0.03
    if checks["fills_count_ok"]:
        reward += 0.05
    if checks["fills_values_ok"]:
        reward += 0.20
    # Regime weights (0.33 total)
    if checks["regime_exists"]:
        reward += 0.05
    if checks["regime_values_ok"]:
        reward += 0.28
    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, reward))
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()