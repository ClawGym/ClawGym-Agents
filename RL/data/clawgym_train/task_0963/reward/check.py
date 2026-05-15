import json
import os
import sys
import csv

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def num_or_null(x):
    return x is None or is_number(x)

def list_of_numbers(lst):
    if not isinstance(lst, list):
        return False
    for v in lst:
        if not is_number(v):
            return False
    return True

def validate_indicators(ind):
    if not isinstance(ind, dict):
        return False
    # rsi
    if "rsi" not in ind or not num_or_null(ind.get("rsi")):
        return False
    # macd
    macd = ind.get("macd")
    if not isinstance(macd, dict):
        return False
    for k in ("macd", "signal", "histogram"):
        if k not in macd or not num_or_null(macd.get(k)):
            return False
    # bollinger
    boll = ind.get("bollinger")
    if not isinstance(boll, dict):
        return False
    for k in ("upper", "middle", "lower"):
        if k not in boll or not num_or_null(boll.get(k)):
            return False
    # atr
    if "atr" not in ind or not num_or_null(ind.get("atr")):
        return False
    # adx
    if "adx" not in ind or not num_or_null(ind.get("adx")):
        return False
    # mfi OR williamsR (at least one present)
    has_mfi = "mfi" in ind and num_or_null(ind.get("mfi"))
    has_wr = "williamsR" in ind and num_or_null(ind.get("williamsR"))
    if not (has_mfi or has_wr):
        return False
    # pivotPoints
    piv = ind.get("pivotPoints")
    if not isinstance(piv, dict):
        return False
    for k in ("pp", "r1", "r2", "r3", "s1", "s2", "s3"):
        if k not in piv or not num_or_null(piv.get(k)):
            return False
    # fibonacci
    fib = ind.get("fibonacci")
    if not isinstance(fib, dict):
        return False
    for k in ("level0", "level236", "level382", "level500", "level618", "level786", "level100"):
        if k not in fib or not num_or_null(fib.get(k)):
            return False
    # keltner
    kel = ind.get("keltner")
    if not isinstance(kel, dict):
        return False
    for k in ("upper", "middle", "lower"):
        if k not in kel or not num_or_null(kel.get(k)):
            return False
    # donchian
    don = ind.get("donchian")
    if not isinstance(don, dict):
        return False
    for k in ("upper", "middle", "lower"):
        if k not in don or not num_or_null(don.get(k)):
            return False
    # vwap
    if "vwap" not in ind or not num_or_null(ind.get("vwap")):
        return False
    # ichimoku
    ichi = ind.get("ichimoku")
    if not isinstance(ichi, dict):
        return False
    for k in ("tenkan", "kijun", "senkouA", "senkouB"):
        if k not in ichi or not num_or_null(ichi.get(k)):
            return False
    # supertrend
    st = ind.get("supertrend")
    if not isinstance(st, dict):
        return False
    trend = st.get("trend")
    if not isinstance(trend, str) or trend not in {"bullish", "bearish", "neutral"}:
        return False
    for k in ("upper", "lower"):
        if k not in st or not num_or_null(st.get(k)):
            return False
    # support_resistance
    sr = ind.get("support_resistance")
    if not isinstance(sr, dict):
        return False
    if "support" not in sr or "resistance" not in sr:
        return False
    # arrays may be empty but must be numeric if present
    if not isinstance(sr.get("support"), list) or not isinstance(sr.get("resistance"), list):
        return False
    if not list_of_numbers(sr.get("support")) and len(sr.get("support")) > 0:
        return False
    if not list_of_numbers(sr.get("resistance")) and len(sr.get("resistance")) > 0:
        return False
    if "nearestSupport" not in sr or "nearestResistance" not in sr:
        return False
    if not num_or_null(sr.get("nearestSupport")):
        return False
    if not num_or_null(sr.get("nearestResistance")):
        return False
    return True

def validate_patterns(arr):
    if not isinstance(arr, list):
        return False
    for item in arr:
        if not isinstance(item, dict):
            return False
        if "type" not in item or "direction" not in item:
            return False
        if not isinstance(item["type"], str) or not isinstance(item["direction"], str):
            return False
    return True

def validate_recommendation(rec):
    if not isinstance(rec, dict):
        return False
    action = rec.get("action")
    if action not in {"buy", "sell", "hold"}:
        return False
    conf = rec.get("confidence")
    if not isinstance(conf, int) or conf < 0 or conf > 100:
        return False
    for k in ("stop_loss", "take_profit", "rrr"):
        if k not in rec or not is_number(rec.get(k)):
            return False
    rationale = rec.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) == 0:
        return False
    return True

def validate_analysis_json(data):
    if not isinstance(data, dict):
        return False
    # top-level
    if "symbol" not in data or not isinstance(data.get("symbol"), str):
        return False
    if "timeframe" not in data or not isinstance(data.get("timeframe"), str):
        return False
    if "current_price" not in data or not is_number(data.get("current_price")):
        return False
    if "indicators" not in data or not validate_indicators(data.get("indicators")):
        return False
    if "patterns" not in data or not validate_patterns(data.get("patterns")):
        return False
    if "volume_analysis" not in data or not isinstance(data.get("volume_analysis"), str):
        return False
    if "recommendation" not in data or not validate_recommendation(data.get("recommendation")):
        return False
    if "timestamp" not in data or not isinstance(data.get("timestamp"), str):
        return False
    return True

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def check_summary_md(path):
    if not os.path.isfile(path):
        return {
            "summary_exists": False,
            "summary_has_risk_disclaimer_title": False,
            "summary_has_disclaimer_sentence": False,
            "summary_has_label_btc_1h": False,
            "summary_has_label_btc_4h": False,
            "summary_has_label_eth_4h": False,
            "summary_has_methods_tag": False
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        content = ""
    exists = True
    has_title = "Risk Disclaimer" in content
    has_sentence = "This is not financial advice." in content
    has_btc1h = "BTC/USDT (1h)" in content
    has_btc4h = "BTC/USDT (4h)" in content
    has_eth4h = "ETH/USDT (4h)" in content
    has_methods = ("Indicators used:" in content) or ("Patterns detected:" in content)
    return {
        "summary_exists": exists,
        "summary_has_risk_disclaimer_title": has_title,
        "summary_has_disclaimer_sentence": has_sentence,
        "summary_has_label_btc_1h": has_btc1h,
        "summary_has_label_btc_4h": has_btc4h,
        "summary_has_label_eth_4h": has_eth4h,
        "summary_has_methods_tag": has_methods
    }

def check_watchlist_csv(path):
    checks = {
        "watchlist_exists": False,
        "watchlist_header_ok": False,
        "watchlist_rows_gte3": False,
        "watchlist_actions_valid": False,
        "watchlist_bias_valid": False,
        "watchlist_numeric_columns_valid": False
    }
    if not os.path.isfile(path):
        return checks
    checks["watchlist_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
    except Exception:
        return checks
    if not reader:
        return checks
    header = reader[0]
    expected_header = ["symbol","timeframe","bias","action","stop_loss","take_profit","nearest_support","nearest_resistance"]
    if header == expected_header:
        checks["watchlist_header_ok"] = True
    rows = reader[1:]
    if len(rows) >= 3:
        checks["watchlist_rows_gte3"] = True
    # actions and bias and numeric columns
    actions_ok = True
    bias_ok = True
    numeric_ok = True
    valid_actions = {"buy","sell","hold"}
    valid_bias = {"bullish","bearish","neutral"}
    for row in rows:
        if len(row) != 8:
            actions_ok = False
            bias_ok = False
            numeric_ok = False
            break
        action = row[3].strip()
        bias = row[2].strip()
        if action not in valid_actions:
            actions_ok = False
        if bias not in valid_bias:
            bias_ok = False
        for idx in (4,5,6,7):
            try:
                float(row[idx])
            except Exception:
                numeric_ok = False
    checks["watchlist_actions_valid"] = actions_ok and len(rows) > 0
    checks["watchlist_bias_valid"] = bias_ok and len(rows) > 0
    checks["watchlist_numeric_columns_valid"] = numeric_ok and len(rows) > 0
    return checks

def check_analysis_file(path, prefix):
    checks = {
        f"{prefix}_exists": False,
        f"{prefix}_json_valid": False,
        f"{prefix}_schema_valid": False
    }
    if not os.path.isfile(path):
        return checks
    checks[f"{prefix}_exists"] = True
    ok, data = load_json_file(path)
    if not ok:
        return checks
    checks[f"{prefix}_json_valid"] = True
    if validate_analysis_json(data):
        checks[f"{prefix}_schema_valid"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    analysis_dir = os.path.join(output_dir, "analysis")

    checks = {}

    # Required analysis JSON files
    btc1h_path = os.path.join(analysis_dir, "BTCUSDT_1h.json")
    btc4h_path = os.path.join(analysis_dir, "BTCUSDT_4h.json")
    eth4h_path = os.path.join(analysis_dir, "ETHUSDT_4h.json")

    checks.update(check_analysis_file(btc1h_path, "btc1h"))
    checks.update(check_analysis_file(btc4h_path, "btc4h"))
    checks.update(check_analysis_file(eth4h_path, "eth4h"))

    # Watchlist CSV
    watchlist_path = os.path.join(output_dir, "watchlist.csv")
    checks.update(check_watchlist_csv(watchlist_path))

    # Summary MD
    summary_path = os.path.join(output_dir, "summary.md")
    checks.update(check_summary_md(summary_path))

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure 0.0 when output directory is missing or no meaningful artifacts present
    # If none of the key existence checks are true, keep reward at 0.0
    key_exist_flags = [
        checks.get("btc1h_exists", False),
        checks.get("btc4h_exists", False),
        checks.get("eth4h_exists", False),
        checks.get("watchlist_exists", False),
        checks.get("summary_exists", False),
    ]
    if not any(key_exist_flags):
        reward = 0.0

    print(json.dumps({"reward": round(reward, 6), **checks}))

if __name__ == "__main__":
    main()