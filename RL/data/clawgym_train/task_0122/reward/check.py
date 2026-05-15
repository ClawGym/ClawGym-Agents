import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Stream file existence
        "tickers_btc_stream_exists": False,
        "tickers_eth_stream_exists": False,
        "trades_btc_stream_exists": False,
        # NDJSON line counts and validity
        "tickers_btc_min_events": False,
        "tickers_eth_min_events": False,
        "trades_btc_min_events": False,
        # Event format checks inside streams
        "tickers_btc_event_format": False,
        "tickers_eth_event_format": False,
        "trades_btc_event_format": False,
        # Reports
        "ticker_snapshot_valid": False,
        "trade_activity_valid": False,
        "metadata_lists_streams": False,
    }

    # Helper functions
    def parse_ndjson(path):
        """Parse NDJSON file, returning (objects, total_nonempty_lines, parsed_count)."""
        objs = []
        total_lines = 0
        parsed = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    total_lines += 1
                    try:
                        obj = json.loads(s)
                        objs.append(obj)
                        parsed += 1
                    except Exception:
                        # skip unparseable lines
                        pass
        except Exception:
            return [], 0, 0
        return objs, total_lines, parsed

    def find_event(objs, channel, inst_id, required_fields):
        """Find at least one event with arg.channel/channel and arg.instId/instId and required fields in data[0]."""
        for o in objs:
            # OKX may use 'arg' at top-level or in 'meta'
            arg = None
            if isinstance(o, dict):
                if isinstance(o.get("arg"), dict):
                    arg = o.get("arg")
                elif isinstance(o.get("meta"), dict) and isinstance(o["meta"].get("arg"), dict):
                    arg = o["meta"]["arg"]
            if not isinstance(arg, dict):
                continue
            ch = arg.get("channel")
            iid = arg.get("instId")
            if ch != channel or iid != inst_id:
                continue
            data = o.get("data")
            if not isinstance(data, list) or not data:
                continue
            d0 = data[0]
            if not isinstance(d0, dict):
                continue
            # Check required fields present
            ok = all(k in d0 for k in required_fields)
            if ok:
                return True
        return False

    def is_number_like(x):
        try:
            float(x)
            return True
        except Exception:
            return False

    def is_int_like(x):
        try:
            int(float(str(x)))
            return True
        except Exception:
            return False

    # Paths
    streams_dir = os.path.join(output_dir, "streams")
    reports_dir = os.path.join(output_dir, "reports")

    # Expected stream files
    tickers_btc_path = os.path.join(streams_dir, "tickers_BTC-USDT.jsonl")
    tickers_eth_path = os.path.join(streams_dir, "tickers_ETH-USDT.jsonl")
    trades_btc_path = os.path.join(streams_dir, "trades_BTC-USDT.jsonl")

    # Check existence
    if os.path.isfile(tickers_btc_path):
        checks["tickers_btc_stream_exists"] = True
    if os.path.isfile(tickers_eth_path):
        checks["tickers_eth_stream_exists"] = True
    if os.path.isfile(trades_btc_path):
        checks["trades_btc_stream_exists"] = True

    # Parse and validate NDJSON counts and event formats
    # Tickers BTC
    if checks["tickers_btc_stream_exists"]:
        objs, total, parsed = parse_ndjson(tickers_btc_path)
        if parsed >= 15 and parsed == total and total > 0:
            checks["tickers_btc_min_events"] = True
        # At least one valid event with required fields
        if find_event(objs, "tickers", "BTC-USDT", ["last", "bidPx", "askPx", "ts"]):
            checks["tickers_btc_event_format"] = True

    # Tickers ETH
    if checks["tickers_eth_stream_exists"]:
        objs, total, parsed = parse_ndjson(tickers_eth_path)
        if parsed >= 15 and parsed == total and total > 0:
            checks["tickers_eth_min_events"] = True
        if find_event(objs, "tickers", "ETH-USDT", ["last", "bidPx", "askPx", "ts"]):
            checks["tickers_eth_event_format"] = True

    # Trades BTC
    if checks["trades_btc_stream_exists"]:
        objs, total, parsed = parse_ndjson(trades_btc_path)
        if parsed >= 15 and parsed == total and total > 0:
            checks["trades_btc_min_events"] = True
        if find_event(objs, "trades", "BTC-USDT", ["px", "sz", "side", "ts"]):
            checks["trades_btc_event_format"] = True

    # Validate ticker_snapshot.json
    ticker_snapshot_path = os.path.join(reports_dir, "ticker_snapshot.json")
    if os.path.isfile(ticker_snapshot_path):
        try:
            with open(ticker_snapshot_path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            # Must include BTC-USDT and ETH-USDT keys
            valid = True
            for key in ["BTC-USDT", "ETH-USDT"]:
                if key not in snap or not isinstance(snap[key], dict):
                    valid = False
                    break
                item = snap[key]
                for field in ["last", "bidPx", "askPx", "ts"]:
                    if field not in item:
                        valid = False
                        break
                if not valid:
                    break
                # Numeric convertibility checks
                if not (is_number_like(item.get("last")) and is_number_like(item.get("bidPx")) and is_number_like(item.get("askPx")) and is_int_like(item.get("ts"))):
                    valid = False
                    break
            if valid:
                checks["ticker_snapshot_valid"] = True
        except Exception:
            pass

    # Validate trade_activity.json
    trade_activity_path = os.path.join(reports_dir, "trade_activity.json")
    if os.path.isfile(trade_activity_path):
        try:
            with open(trade_activity_path, "r", encoding="utf-8") as f:
                ta = json.load(f)
            valid = True
            # Must include BTC-USDT key with events >= 15 and first_ts <= last_ts numeric
            if "BTC-USDT" not in ta or not isinstance(ta["BTC-USDT"], dict):
                valid = False
            else:
                item = ta["BTC-USDT"]
                if "events" not in item or "first_ts" not in item or "last_ts" not in item:
                    valid = False
                else:
                    ev = item.get("events")
                    ft = item.get("first_ts")
                    lt = item.get("last_ts")
                    if not isinstance(ev, int):
                        # allow numeric-like strings but convert to int
                        try:
                            ev = int(float(str(ev)))
                        except Exception:
                            valid = False
                    if not (is_int_like(ft) and is_int_like(lt)):
                        valid = False
                    else:
                        ft_i = int(float(str(ft)))
                        lt_i = int(float(str(lt)))
                        if ev < 15 or ft_i > lt_i:
                            valid = False
            if valid:
                checks["trade_activity_valid"] = True
        except Exception:
            pass

    # Validate metadata.md includes the literal filenames of the three stream files
    metadata_path = os.path.join(reports_dir, "metadata.md")
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Check for substrings of the filenames
            required_names = [
                "tickers_BTC-USDT.jsonl",
                "tickers_ETH-USDT.jsonl",
                "trades_BTC-USDT.jsonl",
            ]
            if all(name in content for name in required_names):
                checks["metadata_lists_streams"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()