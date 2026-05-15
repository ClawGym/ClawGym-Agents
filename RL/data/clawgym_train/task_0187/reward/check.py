import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with strict False. Only set True after validation.
    checks = {
        "has_raw_file": False,
        "raw_non_empty": False,
        "raw_all_json_lines": False,
        "raw_data_count_ge_15": False,
        "raw_trade_btcusdt_ge_5": False,

        "has_combined_file": False,
        "combined_non_empty": False,
        "combined_all_json_lines": False,
        "combined_total_data_ge_20": False,
        "combined_eth_ge_10": False,
        "combined_bnb_ge_10": False,

        "summary_exists": False,
        "summary_valid_json": False,
        "summary_raw_fields_ok": False,
        "summary_combined_fields_ok": False,

        "streams_lowercase_if_present": False  # non-gating informational check
    }

    # Expected output paths
    raw_path = os.path.join(output_dir, "raw_btcusdt_trade.jsonl")
    combined_path = os.path.join(output_dir, "combined_eth_bnb_trade.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")

    # Helper functions
    def read_nonblank_lines(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
        nonblank = [ln for ln in lines if ln.strip() != ""]
        return nonblank

    def extract_payload_and_stream(obj):
        """
        Return (payload, stream_name_if_any, found_stream_flag)
        Handles:
        - {"e": "...", "s": "..."} direct payload
        - {"stream": "...", "data": {...}} wrapper
        - {"data": {"stream": "...", "data": {...}}} nested envelope
        - {"data": {...}} envelope without stream
        """
        stream = None
        found_stream = False
        payload = None

        if isinstance(obj, dict):
            if "stream" in obj and isinstance(obj.get("data"), dict):
                stream = obj.get("stream")
                found_stream = True
                payload = obj.get("data")
            elif "data" in obj and isinstance(obj.get("data"), dict):
                inner = obj.get("data")
                if isinstance(inner, dict) and "stream" in inner and isinstance(inner.get("data"), dict):
                    stream = inner.get("stream")
                    found_stream = True
                    payload = inner.get("data")
                else:
                    payload = inner
                    if "stream" in obj:
                        stream = obj.get("stream")
                        found_stream = True
            else:
                payload = obj
                if "stream" in obj:
                    stream = obj.get("stream")
                    found_stream = True
        return payload, stream, found_stream

    def is_trade_payload(payload):
        return isinstance(payload, dict) and payload.get("e") == "trade" and isinstance(payload.get("s"), str)

    # Process raw file
    streams_lowercase_flag_encountered = None  # None until we see any stream field

    if os.path.isfile(raw_path):
        checks["has_raw_file"] = True
        try:
            lines = read_nonblank_lines(raw_path)
            if len(lines) > 0:
                checks["raw_non_empty"] = True
            # Validate each non-blank line parses as JSON
            raw_all_json = True
            raw_trade_count = 0
            raw_btcusdt_trade_count = 0
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    raw_all_json = False
                    continue
                payload, stream, found_stream = extract_payload_and_stream(obj)
                if found_stream:
                    if streams_lowercase_flag_encountered is None:
                        streams_lowercase_flag_encountered = True
                    # If any encountered stream is not lowercase, mark as False later
                    if stream is None or not isinstance(stream, str) or stream != stream.lower():
                        streams_lowercase_flag_encountered = False
                    elif streams_lowercase_flag_encountered is True:
                        # still all lowercase so far
                        pass
                if is_trade_payload(payload):
                    raw_trade_count += 1
                    if payload.get("s") == "BTCUSDT":
                        raw_btcusdt_trade_count += 1
            checks["raw_all_json_lines"] = raw_all_json
            if raw_trade_count >= 15:
                checks["raw_data_count_ge_15"] = True
            if raw_btcusdt_trade_count >= 5:
                checks["raw_trade_btcusdt_ge_5"] = True
        except Exception:
            # leave as False
            pass

    # Process combined file
    if os.path.isfile(combined_path):
        checks["has_combined_file"] = True
        try:
            lines = read_nonblank_lines(combined_path)
            if len(lines) > 0:
                checks["combined_non_empty"] = True
            combined_all_json = True
            total_trade_count = 0
            eth_count = 0
            bnb_count = 0
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    combined_all_json = False
                    continue
                payload, stream, found_stream = extract_payload_and_stream(obj)
                if found_stream:
                    if streams_lowercase_flag_encountered is None:
                        streams_lowercase_flag_encountered = True
                    if stream is None or not isinstance(stream, str) or stream != stream.lower():
                        streams_lowercase_flag_encountered = False
                    elif streams_lowercase_flag_encountered is True:
                        pass
                if is_trade_payload(payload):
                    total_trade_count += 1
                    sym = payload.get("s")
                    # Determine stream name to attribute counts
                    stream_name = None
                    if isinstance(stream, str) and stream.strip():
                        stream_name = stream.lower()
                    elif isinstance(sym, str):
                        # infer from payload if not provided
                        stream_name = f"{sym.lower()}@trade"
                    if stream_name == "ethusdt@trade" and sym == "ETHUSDT":
                        eth_count += 1
                    elif stream_name == "bnbusdt@trade" and sym == "BNBUSDT":
                        bnb_count += 1
            checks["combined_all_json_lines"] = combined_all_json
            if total_trade_count >= 20:
                checks["combined_total_data_ge_20"] = True
            if eth_count >= 10:
                checks["combined_eth_ge_10"] = True
            if bnb_count >= 10:
                checks["combined_bnb_ge_10"] = True
        except Exception:
            # leave as False
            pass

    # Finalize lowercase stream check
    if streams_lowercase_flag_encountered is True:
        checks["streams_lowercase_if_present"] = True
    elif streams_lowercase_flag_encountered is False:
        checks["streams_lowercase_if_present"] = False
    else:
        # No stream fields encountered; keep as False (avoid vacuous pass)
        checks["streams_lowercase_if_present"] = False

    # Validate summary.json
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            checks["summary_valid_json"] = True

            # Validate raw section
            raw_obj = summary.get("raw")
            raw_fields_ok = False
            if isinstance(raw_obj, dict):
                fpath = raw_obj.get("file")
                count = raw_obj.get("count")
                symbol = raw_obj.get("symbol")
                if (
                    fpath == "output/raw_btcusdt_trade.jsonl"
                    and isinstance(count, int) and count >= 15
                    and symbol == "BTCUSDT"
                ):
                    raw_fields_ok = True
            checks["summary_raw_fields_ok"] = raw_fields_ok

            # Validate combined section
            combined_obj = summary.get("combined")
            combined_fields_ok = False
            if isinstance(combined_obj, dict):
                fpath = combined_obj.get("file")
                total_count = combined_obj.get("totalCount")
                counts_by_stream = combined_obj.get("countsByStream")
                symbols = combined_obj.get("symbols")
                has_required_counts = False
                if isinstance(counts_by_stream, dict):
                    eth_c = counts_by_stream.get("ethusdt@trade")
                    bnb_c = counts_by_stream.get("bnbusdt@trade")
                    if isinstance(eth_c, int) and eth_c >= 10 and isinstance(bnb_c, int) and bnb_c >= 10:
                        has_required_counts = True
                has_required_symbols = False
                if isinstance(symbols, list):
                    has_required_symbols = ("ETHUSDT" in symbols) and ("BNBUSDT" in symbols)
                if (
                    fpath == "output/combined_eth_bnb_trade.jsonl"
                    and isinstance(total_count, int) and total_count >= 20
                    and has_required_counts
                    and has_required_symbols
                ):
                    combined_fields_ok = True
            checks["summary_combined_fields_ok"] = combined_fields_ok

        except Exception:
            # summary_valid_json remains False if parsing failed
            pass

    # Determine final reward: binary pass only if all core checks succeed
    core_checks = [
        "has_raw_file",
        "raw_non_empty",
        "raw_all_json_lines",
        "raw_data_count_ge_15",
        "raw_trade_btcusdt_ge_5",
        "has_combined_file",
        "combined_non_empty",
        "combined_all_json_lines",
        "combined_total_data_ge_20",
        "combined_eth_ge_10",
        "combined_bnb_ge_10",
        "summary_exists",
        "summary_valid_json",
        "summary_raw_fields_ok",
        "summary_combined_fields_ok",
    ]
    all_core_pass = all(checks[k] for k in core_checks)
    reward = 1.0 if all_core_pass else 0.0

    # Print single JSON object with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()